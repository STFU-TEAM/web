"""Chat channels: the global chat, private messages between two players, and a co-op raid's chat (lobby and fight).
Gang chat keeps its own module (gangs.py); this one follows the same shape.

A channel is addressed by a token the routes put in URLs, resolved against the player who asks:
    "global"          every player with a save
    "dm-<other uid>"  the two of them (stored under both ids, sorted)
    "raid-<id>"       the players of one co-op raid (the id lives in the lobby, then in the fight's meta)

Redis:
    web:chat:<channel>          list of JSON {id, uid, text, at}, newest last, capped
    web:chat:seq:<channel>      last message id (the page polls with it: nothing new, nothing sent)
    web:chat:slow:<uid>         set for COOLDOWN seconds after a message
    web:chat:muted              hash uid -> JSON {until, by, reason}: an admin mute (no message anywhere but private ones
                                to admins until then)
    web:dm:with:<uid>           zset other uid -> time of the last message (the conversation list)
    web:dm:unread:<uid>         hash other uid -> unread count
    web:dm:blocked:<uid>        set of uids this player won't hear from
    web:dm:friends_only:<uid>   "1": only friends can start a conversation
"""
import json
import time
from typing import List, Optional

from app.db import r
from app.game.logic import GameError

MAX_LEN = 400
COOLDOWN = 2
KEEP = {"global": 200, "dm": 300, "raid": 120}
RAID_TTL = 2 * 86400
MUTE_KEY = "web:chat:muted"


class Channel:
    def __init__(self, kind: str, key: str, token: str, members: Optional[List[str]] = None, other: Optional[str] = None):
        self.kind, self.key, self.token, self.members, self.other = kind, key, token, members, other

    @property
    def store(self) -> str:
        return f"web:chat:{self.key}"


def dm_key(a: str, b: str) -> str:
    x, y = sorted((str(a), str(b)))
    return f"dm:{x}:{y}"


def resolve(token: str, me: str, raid_members=None) -> Channel:
    """The channel a token names, if `me` may use it. raid_members: (raid id -> member uids) for raid tokens."""
    me = str(me)
    if token == "global":
        return Channel("global", "global", token)
    if token.startswith("dm-"):
        other = token[3:]
        if not other or other == me:
            raise GameError("Pick someone to talk to.")
        from app.db import get_db
        if not get_db().user_exists(other) and not r().exists(f"web:chat:{dm_key(me, other)}"):
            raise GameError("That player doesn't exist.")
        return Channel("dm", dm_key(me, other), token, [me, other], other)
    if token.startswith("raid-"):
        members = raid_members(token[5:]) if raid_members else None
        if not members or me not in members:
            raise GameError("You're not in this raid.")
        return Channel("raid", f"raid:{token[5:]}", token, members)
    raise GameError("That chat doesn't exist.")


def seq(ch: Channel) -> int:
    return int(r().get(f"web:chat:seq:{ch.key}") or 0)


def messages(ch: Channel, limit: int = 80) -> list:
    out = []
    for raw in r().lrange(ch.store, -limit, -1):
        try:
            out.append(json.loads(raw))
        except ValueError:
            continue
    return out


def muted(uid) -> Optional[dict]:
    raw = r().hget(MUTE_KEY, str(uid))
    if not raw:
        return None
    m = json.loads(raw)
    if m["until"] <= time.time():
        r().hdel(MUTE_KEY, str(uid))
        return None
    return m


def mute(uid, by: str, hours: float, reason: str = ""):
    r().hset(MUTE_KEY, str(uid), json.dumps({"until": int(time.time() + hours * 3600), "by": str(by), "reason": (reason or "")[:200]}))


def unmute(uid):
    r().hdel(MUTE_KEY, str(uid))


def can_message(sender: str, other: str) -> Optional[str]:
    """Why sender can't write to other privately, or None."""
    if r().sismember(f"web:dm:blocked:{other}", sender):
        return "This player isn't taking messages from you."
    if r().sismember(f"web:dm:blocked:{sender}", other):
        return "You blocked this player. Unblock them to write."
    if r().get(f"web:dm:friends_only:{other}") and not r().exists(f"web:chat:{dm_key(sender, other)}"):
        from app.social import are_friends
        if not are_friends(other, sender):
            return "This player only takes new messages from friends."
    return None


def post(ch: Channel, uid: str, text: str) -> dict:
    uid = str(uid)
    text = "\n".join(" ".join(line.split()) for line in (text or "").strip().splitlines())[:MAX_LEN].strip()
    while "\n\n\n" in text:
        text = text.replace("\n\n\n", "\n\n")
    if not text:
        raise GameError("Write something first.")
    m = muted(uid)
    if m:
        from app.auth import is_admin
        if not (ch.kind == "dm" and is_admin(ch.other)):  # a muted player can still write to an admin
            left = max(1, int((m["until"] - time.time()) // 60))
            raise GameError(f"An admin muted you for {left} more minute{'s' if left != 1 else ''}"
                            + (f": {m['reason']}" if m.get("reason") else "."))
    if ch.kind == "dm":
        why = can_message(uid, ch.other)
        if why:
            raise GameError(why)
    if not r().set(f"web:chat:slow:{uid}", "1", nx=True, ex=COOLDOWN):
        raise GameError("Slow down a little.")
    msg = {"id": int(r().incr(f"web:chat:seq:{ch.key}")), "uid": uid, "text": text, "at": int(time.time())}
    pipe = r().pipeline()
    pipe.rpush(ch.store, json.dumps(msg))
    pipe.ltrim(ch.store, -KEEP[ch.kind], -1)
    if ch.kind == "raid":
        pipe.expire(ch.store, RAID_TTL)
        pipe.expire(f"web:chat:seq:{ch.key}", RAID_TTL)
    if ch.kind == "dm":
        pipe.zadd(f"web:dm:with:{uid}", {ch.other: msg["at"]})
        pipe.zadd(f"web:dm:with:{ch.other}", {uid: msg["at"]})
        pipe.hincrby(f"web:dm:unread:{ch.other}", uid, 1)
    res = pipe.execute()
    if ch.kind == "dm" and res[-1] == 1:  # the first unread message of a burst: a notification (and a push)
        from app.db import identity
        from app.social import notify
        notify(ch.other, "dm", f"✉ {identity(uid)['name']}: {text[:80]}", f"/chat/dm/{uid}")
    return msg


def delete(ch: Channel, actor: str, msg_id: int, admin: bool = False):
    """Your own messages always; any message in the global and raid chats for an admin."""
    for raw in r().lrange(ch.store, 0, -1):
        try:
            msg = json.loads(raw)
        except ValueError:
            continue
        if msg.get("id") == msg_id:
            if msg["uid"] != str(actor) and not (admin and ch.kind != "dm"):
                raise GameError("You can only remove your own messages.")
            r().lrem(ch.store, 1, raw)
            r().incr(f"web:chat:seq:{ch.key}")  # the pollers refresh
            return msg
    raise GameError("That message is gone.")


def find(ch: Channel, msg_id: int) -> Optional[dict]:
    return next((m for m in messages(ch, KEEP[ch.kind]) if m.get("id") == msg_id), None)


# ── Private messages ─────────────────────────────────────────────────────

def conversations(uid: str, limit: int = 50) -> List[dict]:
    """[{uid, at, unread}] newest first."""
    rows = r().zrevrange(f"web:dm:with:{uid}", 0, limit - 1, withscores=True)
    unread = {(k.decode() if isinstance(k, bytes) else k): int(v) for k, v in r().hgetall(f"web:dm:unread:{uid}").items()}
    out = []
    for other, at in rows:
        other = other.decode() if isinstance(other, bytes) else other
        out.append({"uid": other, "at": int(at), "unread": unread.get(other, 0)})
    return out


def mark_read(uid: str, other: str):
    r().hdel(f"web:dm:unread:{uid}", other)


def unread_total(uid: str) -> int:
    return sum(int(v) for v in r().hvals(f"web:dm:unread:{uid}"))


def block(uid: str, other: str):
    r().sadd(f"web:dm:blocked:{uid}", other)


def unblock(uid: str, other: str):
    r().srem(f"web:dm:blocked:{uid}", other)


def blocked(uid: str, other: str) -> bool:
    return bool(r().sismember(f"web:dm:blocked:{uid}", other))


def friends_only(uid: str) -> bool:
    return bool(r().get(f"web:dm:friends_only:{uid}"))


def set_friends_only(uid: str, on: bool):
    if on:
        r().set(f"web:dm:friends_only:{uid}", "1")
    else:
        r().delete(f"web:dm:friends_only:{uid}")
