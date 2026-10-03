"""Friends, notifications and referrals (web-only, all in Redis).

    web:friends:<uid>            set of friend uids (always both ways)
    web:friendreq:in:<uid>       set of uids asking uid to be friends
    web:friendreq:out:<uid>      set of uids uid asked
    web:notif:<uid>              list of JSON {kind, text, url, at}, newest first, capped
    web:notif:seen:<uid>         unix time the inbox was last opened
    web:toast:<uid>              list of JSON {text, url}: pop-ups shown on the next page or HTMX response
    web:ref:<uid>                uid of the player who invited uid (set once, at save creation)
    web:ref:pending:<inviter>    set of invited uids waiting to clear REFERRAL_STAGE
    web:ref:ready:<inviter>      list of invited uids that cleared it, not yet counted in the inviter's quests
"""
import json
import time
from typing import List, Optional

from app.db import get_db, identity, r

MAX_FRIENDS = 100
NOTIF_KEEP = 60
REFERRAL_STAGE = 3  # an invited player counts once it clears this many story stages (stops throwaway accounts)


class SocialError(Exception):
    pass


def _ids(raw) -> List[str]:
    return sorted(x.decode() if isinstance(x, bytes) else str(x) for x in raw)


# ── Notifications ────────────────────────────────────────────────────────────

def notify(uid: str, kind: str, text: str, url: Optional[str] = None, toast: bool = True):
    """Add to uid's inbox feed (and pop up a toast on their next page)."""
    entry = json.dumps({"kind": kind, "text": text, "url": url, "at": int(time.time())})
    pipe = r().pipeline()
    pipe.lpush(f"web:notif:{uid}", entry)
    pipe.ltrim(f"web:notif:{uid}", 0, NOTIF_KEEP - 1)
    if toast:
        pipe.rpush(f"web:toast:{uid}", json.dumps({"text": text, "url": url, "kind": kind}))
        pipe.ltrim(f"web:toast:{uid}", -8, -1)
        pipe.expire(f"web:toast:{uid}", 7 * 86400)
    pipe.execute()


def feed(uid: str, limit: int = NOTIF_KEEP) -> List[dict]:
    out = []
    for raw in r().lrange(f"web:notif:{uid}", 0, limit - 1):
        try:
            out.append(json.loads(raw))
        except ValueError:
            continue
    return out


def unread(uid: str) -> int:
    seen = int(r().get(f"web:notif:seen:{uid}") or 0)
    return sum(1 for n in feed(uid, 20) if n["at"] > seen)


def mark_seen(uid: str):
    r().set(f"web:notif:seen:{uid}", int(time.time()))


def take_toasts(uid: str) -> List[dict]:
    key = f"web:toast:{uid}"
    pipe = r().pipeline()
    pipe.lrange(key, 0, -1)
    pipe.delete(key)
    raw, _ = pipe.execute()
    out = []
    for item in raw:
        try:
            out.append(json.loads(item))
        except ValueError:
            continue
    return out


# ── Friends ──────────────────────────────────────────────────────────────────

def friends(uid: str) -> List[str]:
    return _ids(r().smembers(f"web:friends:{uid}"))


def are_friends(a: str, b: str) -> bool:
    return bool(r().sismember(f"web:friends:{a}", b))


def incoming(uid: str) -> List[str]:
    return _ids(r().smembers(f"web:friendreq:in:{uid}"))


def outgoing(uid: str) -> List[str]:
    return _ids(r().smembers(f"web:friendreq:out:{uid}"))


def _link(a: str, b: str):
    pipe = r().pipeline()
    pipe.sadd(f"web:friends:{a}", b)
    pipe.sadd(f"web:friends:{b}", a)
    for x, y in ((a, b), (b, a)):
        pipe.srem(f"web:friendreq:in:{x}", y)
        pipe.srem(f"web:friendreq:out:{x}", y)
    pipe.execute()


def request_friend(me: str, other: str) -> str:
    """Send a request, or accept theirs if they already asked. Returns "sent" or "friends"."""
    if me == other:
        raise SocialError("You can't add yourself.")
    if not get_db().user_exists(other):
        raise SocialError("That player doesn't exist.")
    if are_friends(me, other):
        raise SocialError(f"You're already friends with {identity(other)['name']}.")
    if r().sismember(f"web:friendreq:in:{me}", other):
        return accept_friend(me, other)
    if r().scard(f"web:friends:{me}") >= MAX_FRIENDS:
        raise SocialError(f"You can have {MAX_FRIENDS} friends.")
    r().sadd(f"web:friendreq:out:{me}", other)
    r().sadd(f"web:friendreq:in:{other}", me)
    notify(other, "friend", f"{identity(me)['name']} wants to be friends.", "/community/inbox")
    return "sent"


def accept_friend(me: str, other: str) -> str:
    if not r().sismember(f"web:friendreq:in:{me}", other):
        raise SocialError("That request is gone.")
    _link(me, other)
    notify(other, "friend", f"{identity(me)['name']} accepted your friend request.", f"/u/{me}")
    return "friends"


def decline_friend(me: str, other: str):
    pipe = r().pipeline()
    pipe.srem(f"web:friendreq:in:{me}", other)
    pipe.srem(f"web:friendreq:out:{other}", me)
    pipe.execute()


def cancel_request(me: str, other: str):
    decline_friend(other, me)


def remove_friend(me: str, other: str):
    pipe = r().pipeline()
    pipe.srem(f"web:friends:{me}", other)
    pipe.srem(f"web:friends:{other}", me)
    pipe.execute()


def relation(me: str, other: str) -> str:
    """"self", "friends", "sent", "received" or "none" (for profile buttons)."""
    if me == other:
        return "self"
    if are_friends(me, other):
        return "friends"
    if r().sismember(f"web:friendreq:out:{me}", other):
        return "sent"
    if r().sismember(f"web:friendreq:in:{me}", other):
        return "received"
    return "none"


# ── Player search ────────────────────────────────────────────────────────────

def search(query: str, limit: int = 20) -> List[dict]:
    """Players whose username or display name contains the query (web accounts and Discord players)."""
    q = (query or "").strip().lower().lstrip("@")
    if len(q) < 2:
        return []
    found, seen = [], set()
    db = get_db()
    for key in r().scan_iter("web:identity:*", count=500):
        uid = key.decode().split(":", 2)[2] if isinstance(key, bytes) else key.split(":", 2)[2]
        try:
            name = json.loads(r().get(key) or "{}").get("name", "")
        except ValueError:
            continue
        if uid not in seen and q in name.lower() and db.user_exists(uid):
            seen.add(uid)
            found.append(uid)
            if len(found) >= limit:
                break
    if len(found) < limit:
        for key in r().scan_iter(f"web:account:*{q}*", count=500):
            raw = r().get(key)
            try:
                uid = json.loads(raw or "{}").get("uid")
            except ValueError:
                continue
            if uid and uid not in seen and db.user_exists(uid):
                seen.add(uid)
                found.append(uid)
                if len(found) >= limit:
                    break
    return found


# ── Referrals ────────────────────────────────────────────────────────────────

def record_referral(new_uid: str, inviter: Optional[str]) -> bool:
    """Called when a new save is created from an invite link: befriend both, wait for the first stages."""
    if not inviter or inviter == new_uid or not get_db().user_exists(inviter):
        return False
    if not r().set(f"web:ref:{new_uid}", inviter, nx=True):
        return False
    _link(new_uid, inviter)
    r().sadd(f"web:ref:pending:{inviter}", new_uid)
    name = identity(new_uid)["name"]
    notify(inviter, "friend", f"{name} joined with your invite link and is now your friend. "
                              f"Once they clear {REFERRAL_STAGE} story stages, your invite quest counts it.", f"/u/{new_uid}")
    return True


def referral_progress(uid: str, cleared: int):
    """After a story win: an invited player who reaches REFERRAL_STAGE credits whoever invited them."""
    if cleared < REFERRAL_STAGE:
        return
    raw = r().get(f"web:ref:{uid}")
    inviter = raw.decode() if isinstance(raw, bytes) else raw
    if inviter and r().srem(f"web:ref:pending:{inviter}", uid):
        r().rpush(f"web:ref:ready:{inviter}", uid)
        notify(inviter, "quest", f"{identity(uid)['name']} cleared {REFERRAL_STAGE} story stages: your invite counts! "
                                 "Claim it in Quests.", "/quests")


def take_referrals(uid: str) -> int:
    """How many invited players to count now (the caller holds uid's save lock and tracks the quest)."""
    key = f"web:ref:ready:{uid}"
    pipe = r().pipeline()
    pipe.llen(key)
    pipe.delete(key)
    n, _ = pipe.execute()
    return int(n)


def referral_stats(uid: str) -> dict:
    return {"pending": _ids(r().smembers(f"web:ref:pending:{uid}"))}
