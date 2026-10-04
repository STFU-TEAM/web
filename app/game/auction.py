"""Auction house: sell a stand at a fixed price, or put it up for bids.

Listing a stand takes it out of the seller's collection and holds it in escrow, so it can't be
fused, traded or fought with while it's for sale; its equipped items go back to the seller's
inventory. The seller is paid when it sells (minus the house fee on Meteor Dust).

Two kinds of listing:
- "fixed": a price in Meteor Dust, Arrowheads, or both; the first buyer who can pay gets it.
- "bid": bids in one currency, from a starting bid, each at least MIN_RAISE above the last. A bid
  is taken from the bidder at once and held; whoever is outbid gets theirs back right away. A bid
  in the last SNIPE_GUARD seconds pushes the end back so the others can answer. An optional
  buyout price (same currency) ends it early. When time runs out the top bidder wins.
An unsold stand comes back when the seller cancels (only before the first bid) or time runs out.

Redis (web-only):
    web:auction:listings        hash id -> JSON listing (the stand's save dict included)
    web:auction:seller:<uid>    set of listing ids
"""
import json
import math
import secrets
import time
from typing import List, Optional

from app.game.character import character_from_dict
from app.game.items import item_from_dict
from app.game.logic import GameError, free_slots, locked, take_stand

LISTING_DAYS = 7
MAX_LISTINGS = 5
MAX_DUST = 50_000_000
MAX_HEADS = 1_000
FEE = 0.05  # taken from the Meteor Dust part of a sale; Arrowheads pass through whole
KEY = "web:auction:listings"
BID_HOURS = (12, 24, 48, 72)
MIN_RAISE = 0.05       # each bid beats the last by at least 5% (and at least 1)
SNIPE_GUARD = 5 * 60   # a bid this close to the end pushes the end back to this far away
CURRENCIES = {"dust": "fragments", "heads": "super_fragments"}


def _seller_key(uid: str) -> str:
    return f"web:auction:seller:{uid}"


def parse_price(form) -> tuple:
    def num(name, cap):
        try:
            return max(0, min(cap, int(form.get(name) or 0)))
        except ValueError:
            return 0
    return num("dust", MAX_DUST), num("heads", MAX_HEADS)


def fee_for(dust: int) -> int:
    return int(dust * FEE)


def create(redis, seller, uuid: str, dust: int, heads: int, mode: str = "fixed", currency: str = "dust",
           start: int = 0, hours: int = BID_HOURS[1]) -> dict:
    if mode == "bid":
        if currency not in CURRENCIES:
            raise GameError("Pick Meteor Dust or Arrowheads for the bids.")
        if start <= 0:
            raise GameError("Set a starting bid.")
        if hours not in BID_HOURS:
            raise GameError("Pick how long the auction runs.")
        buyout = dust if currency == "dust" else heads
        if buyout and buyout <= start:
            raise GameError("The buyout price has to be above the starting bid.")
        dust, heads = (buyout, 0) if currency == "dust" else (0, buyout)  # the buyout is in the bid currency only
    elif dust <= 0 and heads <= 0:
        raise GameError("Set a price in Meteor Dust, Arrowheads, or both.")
    if redis.scard(_seller_key(seller.id)) >= MAX_LISTINGS:
        raise GameError(f"You already have {MAX_LISTINGS} stands for sale. Cancel one first.")
    if uuid in locked(seller):
        raise GameError("That stand is locked. Unlock it before selling it.")
    if len(seller.main_characters) == 1 and any(c.uuid == uuid for c in seller.main_characters):
        raise GameError("That's your last team stand. Put another one in your team first.")
    char = take_stand(seller, uuid)
    seller.items.extend(item_from_dict(i.to_dict()) for i in char.items)  # gear stays with the seller
    char.items = []
    now = int(time.time())
    listing = {"id": secrets.token_urlsafe(8), "seller": seller.id, "stand": char.to_dict(), "dust": dust,
               "heads": heads, "at": now, "mode": "fixed", "ends": now + LISTING_DAYS * 86400}
    if mode == "bid":
        listing.update(mode="bid", currency=currency, start=start, bid=0, bidder=None, bids=0,
                       ends=now + hours * 3600)
    redis.hset(KEY, listing["id"], json.dumps(listing))
    redis.sadd(_seller_key(seller.id), listing["id"])
    return listing


def get(redis, listing_id: str) -> Optional[dict]:
    raw = redis.hget(KEY, listing_id)
    return json.loads(raw) if raw else None


def all_listings(redis) -> List[dict]:
    out = []
    for _, raw in redis.hscan_iter(KEY, count=500):
        try:
            out.append(json.loads(raw))
        except ValueError:
            continue
    return out


def expired(listing: dict, now: Optional[float] = None) -> bool:
    return (now or time.time()) >= listing["ends"]


def stand_of(listing: dict):
    return character_from_dict(dict(listing["stand"]))


def _close(redis, listing: dict):
    redis.hdel(KEY, listing["id"])
    redis.srem(_seller_key(listing["seller"]), listing["id"])


def is_bid(listing: dict) -> bool:
    return listing.get("mode") == "bid"


def has_buyout(listing: dict) -> bool:
    return bool(listing["dust"] or listing["heads"])


def min_bid(listing: dict) -> int:
    if not listing.get("bid"):
        return listing["start"]
    return listing["bid"] + max(1, math.ceil(listing["bid"] * MIN_RAISE))


def _save(redis, listing: dict):
    redis.hset(KEY, listing["id"], json.dumps(listing))


def give_back(redis, seller, listing: dict):
    """Cancel or expiry with no sale: the stand returns to the seller's storage (even past the cap: it was theirs)."""
    if is_bid(listing) and listing.get("bidder"):
        raise GameError("Someone has bid on it. The auction has to run its course.")
    seller.storage_characters.append(stand_of(listing))
    _close(redis, listing)


def _refund(listing: dict, prev):
    """Give the current top bid back to whoever placed it."""
    if listing.get("bidder") and prev is not None:
        attr = CURRENCIES[listing["currency"]]
        setattr(prev, attr, getattr(prev, attr) + listing["bid"])


def place_bid(redis, bidder, prev, listing: dict, amount: int, now: Optional[float] = None) -> dict:
    """bidder bids amount; prev is the current top bidder's save (or None), refunded in the same step."""
    now = now or time.time()
    if not is_bid(listing):
        raise GameError("That stand has a fixed price. Buy it instead.")
    if bidder.id == listing["seller"]:
        raise GameError("You can't bid on your own stand.")
    if expired(listing, now):
        raise GameError("That auction has ended.")
    if amount < min_bid(listing):
        raise GameError(f"Bid at least {min_bid(listing):,}.")
    buyout = listing["dust"] or listing["heads"]
    if buyout and amount >= buyout:
        raise GameError("That's at least the buyout price. Buy it out instead.")
    attr = CURRENCIES[listing["currency"]]
    raising = prev is not None and prev.id == bidder.id  # raising your own bid only costs the difference
    if getattr(bidder, attr) < amount - (listing["bid"] if raising else 0):
        raise GameError("You can't afford that bid.")
    if free_slots(bidder) < 1:
        raise GameError("Your storage is full. Make room before you bid.")
    outbid = None if raising else listing.get("bidder")
    _refund(listing, prev)
    setattr(bidder, attr, getattr(bidder, attr) - amount)
    listing.update(bid=amount, bidder=bidder.id, bids=listing.get("bids", 0) + 1)
    if listing["ends"] - now < SNIPE_GUARD:
        listing["ends"] = int(now + SNIPE_GUARD)
    _save(redis, listing)
    return {"outbid": outbid, "ends": listing["ends"]}


def settle(redis, seller, winner, listing: dict) -> dict:
    """A finished auction with bids: the top bidder gets the stand, the seller the bid it already held."""
    stand = stand_of(listing)
    winner.storage_characters.append(stand)  # they had room when they bid, so it goes in even if full now
    paid = listing["bid"] - (fee_for(listing["bid"]) if listing["currency"] == "dust" else 0)
    attr = CURRENCIES[listing["currency"]]
    setattr(seller, attr, getattr(seller, attr) + paid)
    _close(redis, listing)
    return {"stand": stand, "paid": paid}


def buy(redis, buyer, seller, listing: dict, prev=None) -> dict:
    """Pay the fixed price, or an auction's buyout (prev, the top bidder so far, gets their bid back)."""
    if is_bid(listing) and not has_buyout(listing):
        raise GameError("That auction has no buyout price. Place a bid instead.")
    if buyer.id == listing["seller"]:
        raise GameError("That's your own listing. Cancel it instead.")
    if expired(listing):
        raise GameError("That listing has expired.")
    if is_bid(listing):
        # the top bidder (maybe the buyer) is paid back first; on a refusal below nothing is saved
        _refund(listing, prev)
    if buyer.fragments < listing["dust"]:
        raise GameError(f"You need {listing['dust']:,} Meteor Dust.")
    if buyer.super_fragments < listing["heads"]:
        raise GameError(f"You need {listing['heads']} Arrowhead{'s' if listing['heads'] != 1 else ''}.")
    if free_slots(buyer) < 1:
        raise GameError("Your storage is full. Make room first.")
    buyer.fragments -= listing["dust"]
    buyer.super_fragments -= listing["heads"]
    paid = listing["dust"] - fee_for(listing["dust"])
    seller.fragments += paid
    seller.super_fragments += listing["heads"]
    stand = stand_of(listing)
    buyer.storage_characters.append(stand)
    _close(redis, listing)
    return {"stand": stand, "paid_dust": paid, "paid_heads": listing["heads"]}
