"""The auction house's "Looking for" board: buy orders for a stand.

A buyer names a stand (and, if they like, a minimum level and awakening) and a price in Meteor Dust, Arrowheads or
both. The price is taken from them at once and held, so any player who owns a match can fill the request on the spot:
the stand goes to the buyer's storage (its gear stays with the seller), and the seller is paid, minus the house fee on
the Meteor Dust like a sale. A request nobody fills comes back (refunded) when the buyer cancels it or after
WANTED_DAYS.

Redis (web-only):
    web:auction:wanted              hash id -> JSON request
    web:auction:wanted:buyer:<uid>  set of request ids
"""
import json
import secrets
import time
from typing import List, Optional

from app.game.auction import MAX_DUST, MAX_HEADS, fee_for
from app.game.character import CHARACTER_FILE
from app.game.items import item_from_dict
from app.game.logic import GameError, locked, take_stand

KEY = "web:auction:wanted"
WANTED_DAYS = 7
MAX_WANTED = 3
MAX_LEVEL = 100
MAX_STARS = 5
STANDS = {c["id"]: c for c in CHARACTER_FILE if c["universe"] != "Dummy"}


def _buyer_key(uid: str) -> str:
    return f"web:auction:wanted:buyer:{uid}"


def stand_id_of(name_or_id: str) -> Optional[int]:
    """A stand's id from its name (any case) or its #id."""
    text = (name_or_id or "").strip().lstrip("#")
    if text.isdigit() and int(text) in STANDS:
        return int(text)
    low = text.lower()
    return next((cid for cid, c in STANDS.items() if c["name"].lower() == low), None)


def get(redis, post_id: str) -> Optional[dict]:
    raw = redis.hget(KEY, post_id)
    return json.loads(raw) if raw else None


def all_posts(redis) -> List[dict]:
    out = []
    for _, raw in redis.hscan_iter(KEY, count=500):
        try:
            out.append(json.loads(raw))
        except ValueError:
            continue
    return out


def expired(post: dict, now: Optional[float] = None) -> bool:
    return (now or time.time()) >= post["ends"]


def _close(redis, post: dict):
    redis.hdel(KEY, post["id"])
    redis.srem(_buyer_key(post["buyer"]), post["id"])


def create(redis, buyer, stand_id: int, min_level: int, min_stars: int, dust: int, heads: int) -> dict:
    if stand_id not in STANDS:
        raise GameError("Pick a stand by its name.")
    if dust <= 0 and heads <= 0:
        raise GameError("Offer Meteor Dust, Arrowheads, or both.")
    dust, heads = min(dust, MAX_DUST), min(heads, MAX_HEADS)
    min_level, min_stars = max(0, min(MAX_LEVEL, min_level)), max(0, min(MAX_STARS, min_stars))
    if redis.scard(_buyer_key(buyer.id)) >= MAX_WANTED:
        raise GameError(f"You're already looking for {MAX_WANTED} stands. Cancel a request first.")
    if buyer.fragments < dust or buyer.super_fragments < heads:
        raise GameError("You can't afford that offer: it's held from your wallet until the request is filled.")
    buyer.fragments -= dust
    buyer.super_fragments -= heads
    now = int(time.time())
    post = {"id": secrets.token_urlsafe(8), "buyer": buyer.id, "stand": stand_id, "level": min_level,
            "stars": min_stars, "dust": dust, "heads": heads, "at": now, "ends": now + WANTED_DAYS * 86400}
    redis.hset(KEY, post["id"], json.dumps(post))
    redis.sadd(_buyer_key(buyer.id), post["id"])
    return post


def refund(redis, buyer, post: dict):
    """Cancel or expiry: the held offer goes back to the buyer."""
    buyer.fragments += post["dust"]
    buyer.super_fragments += post["heads"]
    _close(redis, post)


def matches(post: dict, char) -> bool:
    return char.id == post["stand"] and char.level >= post["level"] and char.awaken >= post["stars"]


def candidates(user, post: dict) -> list:
    """The seller's stands that fill the request (locked ones and their last team stand left out)."""
    held = locked(user)
    last = user.main_characters[0].uuid if len(user.main_characters) == 1 else None
    return [c for c in user.main_characters + user.storage_characters
            if matches(post, c) and c.uuid not in held and c.uuid != last]


def fill(redis, seller, buyer, post: dict, uuid: str) -> dict:
    """seller hands over the stand uuid; the buyer gets it, the seller the held offer (minus the fee on the Dust)."""
    if seller.id == post["buyer"]:
        raise GameError("That's your own request. Cancel it instead.")
    if expired(post):
        raise GameError("That request has expired.")
    char = next((c for c in candidates(seller, post) if c.uuid == uuid), None)
    if char is None:
        raise GameError("That stand doesn't fill the request (or it's locked, or your last team stand).")
    take_stand(seller, uuid)
    seller.items.extend(item_from_dict(i.to_dict()) for i in char.items)  # the gear stays with the seller
    char.items = []
    buyer.storage_characters.append(char)  # their offer was held for it: it goes in even past the storage cap
    paid = post["dust"] - fee_for(post["dust"])
    seller.fragments += paid
    seller.super_fragments += post["heads"]
    _close(redis, post)
    return {"stand": char, "paid_dust": paid, "paid_heads": post["heads"]}
