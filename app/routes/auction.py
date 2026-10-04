"""Auction house: fixed-price listings and bid auctions, in Meteor Dust and/or Arrowheads."""
import time

from flask import Blueprint, flash, redirect, render_template, request, session, url_for

from app.auth import player_required
from app.db import Busy, get_db, identity, r, user_lock, users_lock
from app.game import auction as A
from app.game.logic import GameError
from app.routes.trades import RARITY_RANK, sorted_stands

bp = Blueprint("auction", __name__, url_prefix="/auction")
SORTS = {"new": "Newest", "ending": "Ending soonest", "dust": "Cheapest Meteor Dust", "heads": "Fewest Arrowheads",
         "rarity": "Rarest", "level": "Highest level"}


def _notify(uid, text, toast=True):
    from app import social
    social.notify(uid, "auction", text, url_for("auction.index"), toast=toast)


def _amount(listing, amount):
    word = "Meteor Dust" if listing["currency"] == "dust" else ("Arrowhead" if amount == 1 else "Arrowheads")
    return f"{amount:,} {word}"


def _sweep(db):
    """Close what has run out: unsold stands go back, finished auctions go to the top bidder.
    Busy players are retried on the next visit."""
    for listing in A.all_listings(r()):
        if not A.expired(listing):
            continue
        winner_id = listing.get("bidder") if A.is_bid(listing) else None
        try:
            with users_lock(listing["seller"], *([winner_id] if winner_id else [])):
                fresh = A.get(r(), listing["id"])
                seller = db.get_user(listing["seller"])
                if not fresh or not seller:
                    continue
                name = A.stand_of(fresh).name
                if A.is_bid(fresh) and fresh.get("bidder"):
                    winner = db.get_user(fresh["bidder"])
                    if winner is None:  # the winner's account is gone: the seller keeps the stand
                        fresh["bidder"] = None
                        A.give_back(r(), seller, fresh)
                        seller.update()
                        continue
                    A.settle(r(), seller, winner, fresh)
                    seller.update()
                    winner.update()
                    _notify(winner.id, f"You won the auction for {name} with {_amount(fresh, fresh['bid'])}. It's in your storage.")
                    _notify(seller.id, f"Your {name} sold at auction to {identity(winner.id)['name']} for "
                                       f"{_amount(fresh, fresh['bid'])}.")
                else:
                    A.give_back(r(), seller, fresh)
                    seller.update()
                    _notify(seller.id, f"Your {name} didn't sell. It's back in your storage.", toast=False)
        except Busy:
            continue


def _row(listing, me_id):
    return {**listing, "char": A.stand_of(listing), "seller_name": identity(listing["seller"])["name"],
            "bid_mode": A.is_bid(listing), "min_bid": A.min_bid(listing) if A.is_bid(listing) else 0,
            "winning": A.is_bid(listing) and listing.get("bidder") == me_id,
            "buyout": A.has_buyout(listing)}


def _price_key(x, field):
    """Sort by what it costs now: the buyout or fixed price, else the next bid."""
    if x["bid_mode"] and not x["buyout"]:
        return x["min_bid"] if x.get("currency") == field else float("inf")
    return x[field] if x[field] or not x[("heads" if field == "dust" else "dust")] else float("inf")


@bp.get("")
@player_required
def index():
    db = get_db()
    _sweep(db)
    me = db.get_user(session["uid"])
    rows = [_row(x, me.id) for x in A.all_listings(r())]
    mine = [x for x in rows if x["seller"] == me.id]
    market = [x for x in rows if x["seller"] != me.id]
    bidding = [x for x in market if x["winning"]]
    q = request.args.get("q", "").strip().lower()
    rarity = request.args.get("rarity", "")
    pay = request.args.get("pay", "")
    kind = request.args.get("kind", "")
    if q:
        market = [x for x in market if q in x["char"].name.lower()]
    if rarity:
        market = [x for x in market if x["char"].rarity == rarity]
    if pay == "dust":
        market = [x for x in market if (x.get("currency") == "dust" if x["bid_mode"] else not x["heads"])]
    elif pay == "heads":
        market = [x for x in market if (x.get("currency") == "heads" if x["bid_mode"] else x["heads"])]
    if kind in ("bid", "fixed"):
        market = [x for x in market if x["bid_mode"] == (kind == "bid")]
    sort = request.args.get("sort", "new")
    keys = {"new": lambda x: -x["at"], "ending": lambda x: x["ends"],
            "dust": lambda x: _price_key(x, "dust"), "heads": lambda x: _price_key(x, "heads"),
            "rarity": lambda x: (-RARITY_RANK.get(x["char"].rarity, 0), x["ends"]),
            "level": lambda x: (-x["char"].level, x["ends"])}
    market.sort(key=keys.get(sort, keys["new"]))
    locked = set(me.data.get("web_locked", []))
    return render_template("auction.html", u=me, market=market, mine=sorted(mine, key=lambda x: -x["at"]),
                           bidding=bidding, sellable=[c for c in sorted_stands(me) if c.uuid not in locked],
                           sorts=SORTS, sort=sort, q=request.args.get("q", ""), rarity=rarity, pay=pay, kind=kind,
                           fee=round(A.FEE * 100), days=A.LISTING_DAYS, max_listings=A.MAX_LISTINGS,
                           bid_hours=A.BID_HOURS, raise_pct=round(A.MIN_RAISE * 100),
                           snipe_min=A.SNIPE_GUARD // 60, now=time.time())


def _int(name):
    try:
        return max(0, int(request.form.get(name) or 0))
    except ValueError:
        return 0


@bp.post("/sell")
@player_required
def sell():
    mode = "bid" if request.form.get("mode") == "bid" else "fixed"
    if mode == "bid":
        currency = request.form.get("currency", "dust")
        cap = A.MAX_DUST if currency == "dust" else A.MAX_HEADS
        start, buyout = min(cap, _int("start")), min(cap, _int("buyout"))
        dust, heads = (buyout, 0) if currency == "dust" else (0, buyout)
    else:
        currency, start = "dust", 0
        dust, heads = A.parse_price(request.form)
    try:
        with user_lock(session["uid"]):
            me = get_db().get_user(session["uid"])
            listing = A.create(r(), me, request.form.get("uuid", ""), dust, heads, mode=mode, currency=currency,
                               start=start, hours=_int("hours") or A.BID_HOURS[1])
            me.update()
            name = A.stand_of(listing).name
            if mode == "bid":
                flash(f"{name} is up for bids for {_int('hours') or A.BID_HOURS[1]} hours, "
                      f"starting at {_amount(listing, start)}.", "ok")
            else:
                flash(f"{name} is for sale for {A.LISTING_DAYS} days.", "ok")
    except GameError as e:
        flash(str(e), "error")
    except Busy:
        flash("Your last action is still running.", "error")
    return redirect(url_for("auction.index"))


@bp.post("/<listing_id>/cancel")
@player_required
def cancel(listing_id):
    uid = session["uid"]
    try:
        with user_lock(uid):
            listing = A.get(r(), listing_id)
            if not listing or listing["seller"] != uid:
                raise GameError("That listing is gone.")
            me = get_db().get_user(uid)
            A.give_back(r(), me, listing)
            me.update()
            flash("Listing cancelled. The stand is back in your storage.", "ok")
    except GameError as e:
        flash(str(e), "error")
    except Busy:
        flash("Your last action is still running.", "error")
    return redirect(url_for("auction.index"))


@bp.post("/<listing_id>/bid")
@player_required
def bid(listing_id):
    uid = session["uid"]
    listing = A.get(r(), listing_id)
    if not listing:
        flash("That auction is over.", "error")
        return redirect(url_for("auction.index"))
    prev_id = listing.get("bidder")
    try:
        with users_lock(uid, *([prev_id] if prev_id else [])):
            listing = A.get(r(), listing_id)  # re-read under the locks
            if not listing:
                raise GameError("That auction is over.")
            if listing.get("bidder") != prev_id:
                raise GameError("Someone bid at the same moment. Check the new price and try again.")
            db = get_db()
            me = db.get_user(uid)
            prev = me if prev_id == uid else (db.get_user(prev_id) if prev_id else None)
            refunded = listing.get("bid", 0)
            result = A.place_bid(r(), me, prev, listing, _int("amount"))
            me.update()
            if prev is not None and prev is not me:
                prev.update()
            name = A.stand_of(listing).name
            if result["outbid"]:
                _notify(result["outbid"], f"You were outbid on {name}. Your {_amount(listing, refunded)} "
                                          "is back in your wallet.")
            _notify(listing["seller"], f"New bid on your {name}: {_amount(listing, listing['bid'])}.", toast=False)
            flash(f"You're the top bidder on {name} with {_amount(listing, listing['bid'])}.", "ok")
    except GameError as e:
        flash(str(e), "error")
    except Busy:
        flash("Someone in this auction is busy. Try again in a moment.", "error")
    return redirect(url_for("auction.index", **({"sort": request.form["sort"]} if request.form.get("sort") else {})))


@bp.post("/<listing_id>/buy")
@player_required
def buy(listing_id):
    uid = session["uid"]
    listing = A.get(r(), listing_id)
    if not listing:
        flash("Someone else bought it first, or it was withdrawn.", "error")
        return redirect(url_for("auction.index"))
    prev_id = listing.get("bidder")
    try:
        with users_lock(uid, listing["seller"], *([prev_id] if prev_id else [])):
            listing = A.get(r(), listing_id)  # re-read under the locks
            if not listing:
                raise GameError("Someone else bought it first, or it was withdrawn.")
            if listing.get("bidder") != prev_id:
                raise GameError("Someone bid at the same moment. Check the auction and try again.")
            db = get_db()
            buyer, seller = db.get_user(uid), db.get_user(listing["seller"])
            if seller is None:
                raise GameError("The seller's account is gone.")
            prev = buyer if prev_id == uid else (db.get_user(prev_id) if prev_id else None)
            sale = A.buy(r(), buyer, seller, listing, prev=prev)
            buyer.update()
            seller.update()
            if prev is not None and prev is not buyer:
                prev.update()
                _notify(prev.id, f"{sale['stand'].name} was bought out. Your bid is back in your wallet.")
            price = " and ".join(p for p in (f"{listing['dust']:,} Meteor Dust" if listing["dust"] else "",
                                             f"{listing['heads']} Arrowhead{'s' if listing['heads'] != 1 else ''}"
                                             if listing["heads"] else "") if p)
            _notify(seller.id, f"{identity(uid)['name']} bought your {sale['stand'].name} for {price}.")
            flash(f"You bought {sale['stand'].name}. It's in your storage.", "ok")
    except GameError as e:
        flash(str(e), "error")
    except Busy:
        flash("The seller or you are busy with another action. Try again.", "error")
    return redirect(url_for("auction.index"))
