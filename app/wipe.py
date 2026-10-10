"""Deleting a player's save so they can start over (admin panel, owners only), and restoring it.

The save lives in the bot's `users` hash, so the bot sees a fresh player too. Their login stays: a web account keeps
its username and password (web:account_uid), and the next page they open offers to begin a new save.

What goes with the save, so nobody else is left holding a broken reference:
  gang          they leave it; a boss seat passes to the next ranked member, an empty gang is deleted
  auction       their listings close (a top bidder gets the bid back); their bids on others' listings are void
  shops         their bot shop and what's listed in it
  trades        every offer they sent or received
  social        friendships and friend requests, referrals, gifts, notifications, push devices, co-op lobby
  ladders       their entries in season, boss rush and tower boards
  web:*:<uid>   every other per-player web key (history, mastery, caches...), except the login and their identity

A copy of the save is kept KEEP_DAYS (web:deleted:<uid>) so a mistake can be undone; a restore brings back the save
only, outside any gang (the friendships, listings and offers above are gone for good).

    web:deleted:<uid>   the pickled save, as the bot stored it, expires after KEEP_DAYS
    web:deleted         hash uid -> JSON {at, by, name, field}
"""
import json
import pickle
import time
from typing import List

from app.db import Busy, clear_fight, get_db, identity, load_fight, r, user_lock

KEEP_DAYS = 30
INDEX = "web:deleted"
CONFIRM_WORD = "DELETE"
KEEP_PREFIXES = ("web:account_uid:", "web:identity:", "web:lock:", "web:deleted:", "web:login_fail:")


class WipeError(Exception):
    pass


def _s(x) -> str:
    return x.decode() if isinstance(x, bytes) else str(x)


def _field(uid: str):
    """The users-hash field holding the save: the id, or the bot's older b'<id>' form."""
    for field in (uid, f"b'{uid}'"):
        if r().hexists("users", field):
            return field
    return None


def delete_save(uid: str, actor: str) -> dict:
    """Delete uid's save and everything tied to it. Returns a summary of what was cleaned up."""
    uid = str(uid)
    if uid == str(actor):
        raise WipeError("You can't delete your own save from here.")
    field = _field(uid)
    if field is None:
        raise WipeError("That player has no save.")
    fight = load_fight(uid)
    if fight and not fight.finished:
        raise WipeError("They're in a fight. Wait for it to end, or clear it first.")
    done = {}
    try:
        with user_lock(uid):
            raw = r().hget("users", field)
            user = get_db().get_user(uid)
            r().set(f"web:deleted:{uid}", raw, ex=KEEP_DAYS * 86400)
            r().hset(INDEX, uid, json.dumps({"at": int(time.time()), "by": str(actor), "name": identity(uid)["name"],
                                             "field": field}))
            done["gang"] = _leave_gang(uid, user.gang_id) if user and user.gang_id else None
            done["listings"], done["bids"] = _auctions(uid)
            done["shops"] = _shops(uid)
            done["trades"] = _trades(uid)
            done["friends"] = _social(uid)
            _ladders(uid)
            clear_fight(uid)
            from app.game import coop
            coop.leave(uid)
            done["keys"] = _own_keys(uid)
            r().hdel("users", field)
    except Busy:
        raise WipeError("That account is busy with another action. Try again.")
    return done


def _leave_gang(uid: str, gang_id: str):
    from app.game import gangs as G
    db = get_db()
    with user_lock(f"gang:{gang_id}"):
        gang = db.get_gang(gang_id)
        if not gang:
            return None
        was_boss = G.rank_of(gang, uid) == G.BOSS
        gang["users"] = [u for u in gang["users"] if str(u) != uid]
        gang.get("ranks", {}).pop(uid, None)
        if not gang["users"]:  # the last member: the gang, its guardians and its stash go with them
            db.delete_gang(gang_id)
            r().hdel("active_wars", gang_id)
            return f"{gang.get('name', 'their gang')} (deleted: they were its last member)"
        heir = None
        if was_boss:  # the best-ranked member left takes the seat
            heir = min(G.members(gang), key=lambda m: G.rank_of(gang, m))
            G._set_rank(gang, heir, G.BOSS)
        db.update_gang(gang)
        return f"{gang.get('name', 'their gang')}" + (f" ({identity(heir)['name']} is the new boss)" if heir else "")


def _auctions(uid: str):
    from app.game import auction
    db = get_db()
    closed = voided = 0
    for listing in auction.all_listings(r()):
        if listing["seller"] == uid:
            bidder = listing.get("bidder")
            if bidder and bidder != uid:
                with user_lock(bidder):
                    prev = db.get_user(bidder)
                    if prev:
                        auction._refund(listing, prev)
                        prev.update()
            auction._close(r(), listing)
            closed += 1
        elif listing.get("bidder") == uid:  # their held bid left with their save: the auction starts over
            listing.update(bid=0, bidder=None)
            auction._save(r(), listing)
            voided += 1
    r().delete(auction._seller_key(uid))
    return closed, voided


def _shops(uid: str) -> int:
    n = 0
    for shop in get_db().all_shops():
        if str(shop.get("owner")) == uid:
            r().hdel("shops", shop["_id"])
            n += 1
    return n


def _trades(uid: str) -> int:
    from app.game import trades as T
    n = 0
    for box in ("in", "out"):
        for offer_id in r().smembers(f"web:trades:{box}:{uid}"):
            offer = T.get(r(), _s(offer_id))
            if offer:
                T.close(r(), offer)
                r().delete(f"web:trade:{offer['id']}")
                n += 1
    return n


def _social(uid: str) -> int:
    friends = [_s(f) for f in r().smembers(f"web:friends:{uid}")]
    pipe = r().pipeline()
    for f in friends:
        pipe.srem(f"web:friends:{f}", uid)
    for other in r().smembers(f"web:friendreq:in:{uid}"):
        pipe.srem(f"web:friendreq:out:{_s(other)}", uid)
    for other in r().smembers(f"web:friendreq:out:{uid}"):
        pipe.srem(f"web:friendreq:in:{_s(other)}", uid)
    inviter = r().get(f"web:ref:{uid}")
    if inviter:
        pipe.srem(f"web:ref:pending:{_s(inviter)}", uid)
    for key in r().zscan_iter("web:notif:due", match=f"{uid}|*"):  # notifications waiting to be sent
        key = _s(key[0])
        pipe.zrem("web:notif:due", key)
        pipe.hdel("web:notif:due:data", key)
    pipe.zrem("web:ranked:queue", uid)
    from app.db import NAMES
    pipe.hdel(NAMES, uid)
    pipe.execute()
    return len(friends)


def _ladders(uid: str):
    """Their entries in this and past boards: seasons, the boss rush and the tower."""
    for pattern in ("web:season:*", "web:rush:*", "web:tower:*"):
        for key in r().scan_iter(pattern, count=1000):
            kind = _s(r().type(key))
            if kind == "zset":
                r().zrem(key, uid)
            elif kind == "hash":
                r().hdel(key, uid)
            elif kind == "set":
                r().srem(key, uid)
    for key in r().scan_iter("web:leaderboard:*", count=1000):  # cached ladders: rebuilt without them
        r().delete(key)


def _own_keys(uid: str) -> int:
    """Every web:...:<uid> key (the id as the last part, so a longer id that contains it never matches)."""
    doomed = [k for k in r().scan_iter(f"web:*:{uid}", count=1000) if not _s(k).startswith(KEEP_PREFIXES)]
    for i in range(0, len(doomed), 500):
        r().delete(*doomed[i:i + 500])
    return len(doomed)


def deleted() -> List[dict]:
    """Saves deleted in the last KEEP_DAYS, newest first, that can still be restored."""
    out = []
    for uid, raw in r().hgetall(INDEX).items():
        uid = _s(uid)
        meta = json.loads(raw)
        if not r().exists(f"web:deleted:{uid}"):
            r().hdel(INDEX, uid)  # the copy expired
            continue
        out.append({"uid": uid, **meta, "by_name": identity(meta["by"])["name"] if meta.get("by") else "?",
                    "restarted": _field(uid) is not None})
    return sorted(out, key=lambda m: m["at"], reverse=True)


def restore_save(uid: str) -> str:
    uid = str(uid)
    raw = r().get(f"web:deleted:{uid}")
    if not raw:
        raise WipeError("There's no copy of that save any more.")
    if _field(uid) is not None:
        raise WipeError("They already began a new save. Delete it first to bring the old one back.")
    meta = json.loads(r().hget(INDEX, uid) or "{}")
    doc = pickle.loads(raw)
    doc["gang_id"] = None  # they left their gang when it was deleted
    r().hset("users", meta.get("field") or uid, pickle.dumps(doc, protocol=4))
    r().delete(f"web:deleted:{uid}")
    r().hdel(INDEX, uid)
    return meta.get("name") or uid
