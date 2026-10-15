"""Contact us and bug reports: a form anyone can send (signed in or a visitor), read by the admins in the Contact tab.

A message keeps its kind, the text, an optional email to answer to, the page it's about and the browser's name (to
reproduce a bug), plus who sent it when they're signed in. At most PER_HOUR sends an hour per player or address.
When CONTACT_WEBHOOK_URL is set (a Discord channel webhook) each message is also posted there, without the email.

Redis:
    web:contact:msgs      hash id -> JSON message
    web:contact:order     zset id -> sent at (newest last)
    web:contact:rl:<who>  sends this hour (who = player id or a hash of the address)
"""
import hashlib
import json
import os
import secrets
import threading
import time

KINDS = {  # key -> (icon, label, what the form asks for)
    "bug": ("🐞", "Bug report", "What happened, and what did you expect? Steps to make it happen again help a lot."),
    "account": ("🔑", "Account or save", "Which account, and what's wrong with it? Never send your password."),
    "idea": ("💡", "Idea or feedback", "What would make the game better?"),
    "other": ("✉", "Something else", "How can we help?"),
}
MIN_LEN, MAX_LEN = 10, 3000
KEEP = 1000            # messages kept; the oldest go first
PER_HOUR = 5
MSGS, ORDER = "web:contact:msgs", "web:contact:order"


class ContactError(ValueError):
    pass


def _who(uid, addr) -> str:
    if uid:
        return f"u{uid}"
    return "a" + hashlib.sha256(f"contact|{addr or '?'}".encode()).hexdigest()[:16]


def submit(redis, kind: str, message: str, email: str = "", page: str = "", ua: str = "",
           uid=None, name: str = "", addr: str = "") -> dict:
    """Validate and store a message; returns it. Raises ContactError with a reason to show."""
    kind = kind if kind in KINDS else "other"
    message = (message or "").strip()
    email = (email or "").strip()[:200]
    if len(message) < MIN_LEN:
        raise ContactError(f"Tell us a bit more: at least {MIN_LEN} characters.")
    if len(message) > MAX_LEN:
        raise ContactError(f"That's long: keep it under {MAX_LEN:,} characters.")
    if email and ("@" not in email or " " in email or "." not in email.split("@")[-1]):
        raise ContactError("That email doesn't look right. Leave it empty if you'd rather not give one.")
    rl = f"web:contact:rl:{_who(uid, addr)}"
    n = redis.incr(rl)
    if n == 1:
        redis.expire(rl, 3600)
    if n > PER_HOUR:
        raise ContactError("You've sent several messages this hour. Please wait a bit before the next one.")
    entry = {"id": secrets.token_hex(5), "kind": kind, "message": message, "email": email, "page": (page or "").strip()[:300],
             "ua": (ua or "")[:300], "uid": str(uid) if uid else "", "name": (name or "")[:80], "at": int(time.time()),
             "status": "open", "closed_by": ""}
    redis.hset(MSGS, entry["id"], json.dumps(entry))
    redis.zadd(ORDER, {entry["id"]: entry["at"]})
    extra = redis.zcard(ORDER) - KEEP
    if extra > 0:
        old = [x.decode() if isinstance(x, bytes) else x for x in redis.zrange(ORDER, 0, extra - 1)]
        redis.hdel(MSGS, *old)
        redis.zrem(ORDER, *old)
    _post(entry)
    return entry


def listing(redis, status: str = "open", limit: int = 200) -> list:
    """Messages, newest first: status 'open', 'done' or 'all'."""
    ids = [x.decode() if isinstance(x, bytes) else x for x in redis.zrevrange(ORDER, 0, KEEP)]
    out = []
    for raw in (redis.hmget(MSGS, ids) if ids else []):
        if not raw:
            continue
        e = json.loads(raw)
        if status == "all" or e["status"] == status:
            out.append(e)
            if len(out) >= limit:
                break
    return out


def set_status(redis, mid: str, status: str, by: str = "") -> bool:
    raw = redis.hget(MSGS, mid)
    if not raw:
        return False
    e = json.loads(raw)
    e["status"], e["closed_by"] = status, (by if status == "done" else "")
    redis.hset(MSGS, mid, json.dumps(e))
    return True


def delete(redis, mid: str) -> bool:
    redis.zrem(ORDER, mid)
    return bool(redis.hdel(MSGS, mid))


def open_count(redis) -> int:
    return len(listing(redis, "open", KEEP))


def _post(e: dict):
    """Post to CONTACT_WEBHOOK_URL on a background thread (never the email; never mentions anyone)."""
    url = os.environ.get("CONTACT_WEBHOOK_URL", "")
    if not url:
        return
    icon, label, _ = KINDS[e["kind"]]
    who = f"**{e['name']}** (`{e['uid']}`)" if e["uid"] else "a visitor"
    text = (f"{icon} **{label}** from {who}" + (f" on `{e['page']}`" if e["page"] else "")
            + (" · email given" if e["email"] else "") + f"\n>>> {e['message'][:1700]}")[:1950]

    def send():
        try:
            import requests
            requests.post(url, json={"content": text, "allowed_mentions": {"parse": []}}, timeout=10)
        except Exception:
            pass
    threading.Thread(target=send, daemon=True).start()
