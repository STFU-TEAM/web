"""Alt-account flags: accounts that share an IP address, for an admin to review (nothing is blocked).

An IP is never stored: only a salted hash of it (IP_SALT, else SECRET_KEY), kept for RETENTION. Every sign-in and,
for players who stay signed in, the first request of each day records the hash against the account. Once more than
FLAG_AFTER accounts share one hash, the group is flagged on the admin Safety tab. Households, schools and phone
carriers share addresses too, so a flag is a lead, not a verdict; an admin can dismiss a group (it comes back only if
another account joins it).

    web:alts:ip:<hash>     set of uids seen on that address (expires RETENTION after the last sighting)
    web:alts:uid:<uid>     set of hashes that account was seen on (same)
    web:alts:flags         hash <hash> -> JSON {uids, first, last}
    web:alts:dismissed     hash <hash> -> how many accounts the group had when dismissed
"""
import datetime
import hashlib
import json
import os
from typing import List, Optional

FLAG_AFTER = 4          # flag an address once MORE than this many accounts use it
RETENTION = 90 * 86400
FLAGS_KEY = "web:alts:flags"
DISMISSED_KEY = "web:alts:dismissed"


def ip_hash(ip: str) -> str:
    salt = os.environ.get("IP_SALT") or os.environ.get("SECRET_KEY") or "stfu"
    return hashlib.sha256(f"{salt}:{ip}".encode()).hexdigest()[:20]


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


def record(redis, uid, ip: Optional[str]) -> Optional[str]:
    """Note that uid was seen on ip; flags the address when it crosses FLAG_AFTER accounts. Returns the hash."""
    if not uid or not ip or ip == "?":
        return None
    h, uid = ip_hash(ip), str(uid)
    pipe = redis.pipeline(transaction=False)
    pipe.sadd(f"web:alts:ip:{h}", uid)
    pipe.expire(f"web:alts:ip:{h}", RETENTION)
    pipe.sadd(f"web:alts:uid:{uid}", h)
    pipe.expire(f"web:alts:uid:{uid}", RETENTION)
    pipe.smembers(f"web:alts:ip:{h}")
    members = pipe.execute()[-1]
    uids = sorted(m.decode() if isinstance(m, bytes) else str(m) for m in members)
    if len(uids) > FLAG_AFTER:
        dismissed = redis.hget(DISMISSED_KEY, h)
        if dismissed is None or len(uids) > int(dismissed):
            old = redis.hget(FLAGS_KEY, h)
            first = json.loads(old)["first"] if old else _now()
            redis.hset(FLAGS_KEY, h, json.dumps({"uids": uids, "first": first, "last": _now()}))
            if dismissed is not None:
                redis.hdel(DISMISSED_KEY, h)
    return h


def touch(redis, session, ip: Optional[str]):
    """Once a day per session (and when the address changes): record without a sign-in. Costs nothing otherwise."""
    uid = session.get("uid")
    if not uid or not ip:
        return
    mark = f"{datetime.date.today().isoformat()}:{ip_hash(ip)[:8]}"
    if session.get("ipd") == mark:
        return
    session["ipd"] = mark
    record(redis, uid, ip)


def flags(redis) -> List[dict]:
    """Flagged addresses, the most accounts first: [{hash, uids, first, last}]."""
    out = []
    for h, raw in (redis.hgetall(FLAGS_KEY) or {}).items():
        try:
            row = json.loads(raw)
        except (TypeError, ValueError):
            continue
        out.append({"hash": h.decode() if isinstance(h, bytes) else h, **row})
    return sorted(out, key=lambda f: (-len(f["uids"]), f["last"]), reverse=False)


def dismiss(redis, h: str):
    raw = redis.hget(FLAGS_KEY, h)
    n = len(json.loads(raw)["uids"]) if raw else 0
    redis.hset(DISMISSED_KEY, h, n)
    redis.hdel(FLAGS_KEY, h)


def neighbours(redis, uid) -> List[str]:
    """The other accounts seen on any address this one used (the admin player page)."""
    others = set()
    for h in redis.smembers(f"web:alts:uid:{uid}") or ():
        h = h.decode() if isinstance(h, bytes) else h
        for m in redis.smembers(f"web:alts:ip:{h}") or ():
            m = m.decode() if isinstance(m, bytes) else str(m)
            if m != str(uid):
                others.add(m)
    return sorted(others)


GUESTS_PER_DAY = 5  # new guest saves one address can make in a day


def too_many_guests(redis, ip: Optional[str]) -> bool:
    """Counts a new guest save against its address; True (and no save) once the day's GUESTS_PER_DAY are used."""
    if not ip or ip == "?":
        return False
    key = f"web:alts:guests:{ip_hash(ip)}:{datetime.date.today().isoformat()}"
    n = redis.incr(key)
    redis.expire(key, 2 * 86400)
    return n > GUESTS_PER_DAY
