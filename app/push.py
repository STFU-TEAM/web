"""Web push: phone and desktop notifications for things that happen while a player is away.

social.notify() calls send() for the kinds in PUSH_KINDS, unless the player has a page open (seen in the last
ACTIVE_SECONDS: the on-site toast covers it). Delivery runs on a small thread pool so a request never waits on a
push service. Off unless VAPID_PUBLIC_KEY and VAPID_PRIVATE_KEY are set (scripts/vapid_keys.py makes a pair).

    web:push:<uid>        hash  sha1(endpoint) -> JSON subscription {endpoint, keys: {p256dh, auth}}
    web:push:energy:<uid> "1" when the player wants an "energy full" push
    web:seen:<uid>        set on every page load, expires after ACTIVE_SECONDS
    web:push:stats        hash: sent / failed / dropped counters, last_error(_at), last_ok_at (admin Logs tab)
"""
import hashlib
import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Optional
from urllib.parse import urlparse

from flask import current_app

from app.db import r

log = logging.getLogger(__name__)

PUSH_KINDS = {"fight", "coop", "trade", "friend", "gift", "gang", "auction", "journey", "season", "energy"}
TITLES = {"fight": "⚔️ Duel", "coop": "🤝 Co-op raid", "trade": "⇄ Trade", "friend": "♥ Friends", "gift": "🎁 Gift",
          "gang": "⚑ Gang", "auction": "🔨 Auction", "journey": "🐫 Journey", "season": "♛ Season", "energy": "⚡ Energy"}
ACTIVE_SECONDS = 60
MAX_DEVICES = 5
STATS_KEY = "web:push:stats"
_pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="push")
_warned_off = False


def keys() -> Optional[dict]:
    try:
        cfg = current_app.config
    except RuntimeError:  # outside the app (scripts, unit tests of the game logic)
        return None
    if not (cfg.get("VAPID_PUBLIC_KEY") and cfg.get("VAPID_PRIVATE_KEY")):
        return None
    return {"public": cfg["VAPID_PUBLIC_KEY"], "private": cfg["VAPID_PRIVATE_KEY"],
            "subject": cfg.get("VAPID_SUBJECT") or "mailto:admin@stfurequiem.com"}


def enabled() -> bool:
    return keys() is not None


def _key(uid) -> str:
    return f"web:push:{uid}"


def subscribe(uid, sub: dict) -> bool:
    endpoint = (sub or {}).get("endpoint", "")
    if not endpoint.startswith("https://") or not (sub.get("keys") or {}).get("p256dh"):
        return False
    hset = r().hgetall(_key(uid))
    if len(hset) >= MAX_DEVICES:  # the oldest devices go first (insertion order isn't kept: drop any one)
        r().hdel(_key(uid), next(iter(hset)))
    r().hset(_key(uid), hashlib.sha1(endpoint.encode()).hexdigest(),
             json.dumps({"endpoint": endpoint, "keys": sub["keys"]}))
    return True


def unsubscribe(uid, endpoint: str):
    r().hdel(_key(uid), hashlib.sha1((endpoint or "").encode()).hexdigest())


def devices(uid) -> int:
    return r().hlen(_key(uid))


def wants_energy(uid) -> bool:
    return bool(r().get(f"web:push:energy:{uid}"))


def set_energy(uid, on: bool):
    if on:
        r().set(f"web:push:energy:{uid}", "1")
    else:
        r().delete(f"web:push:energy:{uid}")
        from app import social
        social.cancel_later(str(uid), "energy")


def seen(uid):
    r().set(f"web:seen:{uid}", "1", ex=ACTIVE_SECONDS)


def active(uid) -> bool:
    return bool(r().exists(f"web:seen:{uid}"))


def send(uid, kind: str, text: str, url: Optional[str] = None, force: bool = False):
    """Queue a push to every device of uid (if this kind pushes and the player isn't on the site)."""
    global _warned_off
    if kind not in PUSH_KINDS:
        return
    if not enabled():
        if not _warned_off:  # once per worker: the usual cause is the keys missing from the container's env
            _warned_off = True
            log.warning("push is off: VAPID_PUBLIC_KEY / VAPID_PRIVATE_KEY aren't set (or push.send ran outside the app)")
        return
    if active(uid) and not force:
        return
    subs = r().hgetall(_key(uid))
    if not subs:
        if force:
            log.info("push test for %s: this player has no device subscribed", uid)
        return
    payload = json.dumps({"title": TITLES.get(kind, "STFU Requiem"), "body": text, "url": url or "/",
                          "tag": kind})
    k = keys()
    redis = r()
    for field, raw in subs.items():
        _pool.submit(_deliver, redis, str(uid), field, raw, payload, k)


def _deliver(redis, uid, field, raw, payload, k):
    """Runs on the pool, where nothing raised reaches anyone: every outcome is logged and counted."""
    try:
        from pywebpush import WebPushException, webpush
    except Exception:
        _count(redis, "failed", "pywebpush can't be imported")
        log.exception("push to %s failed: pywebpush can't be imported", uid)
        return
    try:
        sub = json.loads(raw)
    except ValueError:
        redis.hdel(_key(uid), field)
        log.warning("push to %s: dropped an unreadable subscription", uid)
        return
    host = urlparse(sub.get("endpoint") or "").netloc or "?"  # fcm.googleapis.com, updates.push.services.mozilla.com…
    try:
        webpush(subscription_info=sub, data=payload, vapid_private_key=k["private"],
                vapid_claims={"sub": k["subject"]}, ttl=12 * 3600)
        _count(redis, "sent")
    except WebPushException as e:
        status = getattr(e.response, "status_code", None)
        if status in (404, 410):  # the browser dropped this subscription
            redis.hdel(_key(uid), field)
            _count(redis, "dropped")
            log.info("push to %s: %s says the device is gone (%s), removed it", uid, host, status)
        else:
            body = (getattr(e.response, "text", "") or "")[:300]
            _count(redis, "failed", f"{host} {status}: {body or e}"[:400])
            log.warning("push to %s via %s failed (%s): %s %s", uid, host, status, e, body)
    except Exception as e:
        _count(redis, "failed", f"{host}: {e!r}"[:400])
        log.exception("push to %s via %s failed", uid, host)


def _count(redis, what: str, error: Optional[str] = None):
    try:
        pipe = redis.pipeline()
        pipe.hincrby(STATS_KEY, what, 1)
        if error:
            pipe.hset(STATS_KEY, mapping={"last_error": error, "last_error_at": int(time.time())})
        elif what == "sent":
            pipe.hset(STATS_KEY, "last_ok_at", int(time.time()))
        pipe.execute()
    except Exception:
        log.exception("push stats")


def status() -> dict:
    """Push health for the admin Logs tab: configured, library present, delivery counters, the due queue."""
    try:
        import pywebpush  # noqa: F401
        lib = True
    except Exception:
        lib = False
    raw = {(k.decode() if isinstance(k, bytes) else k): (v.decode() if isinstance(v, bytes) else v)
           for k, v in r().hgetall(STATS_KEY).items()}
    cfg = current_app.config
    return {"enabled": enabled(), "public": bool(cfg.get("VAPID_PUBLIC_KEY")),
            "private": bool(cfg.get("VAPID_PRIVATE_KEY")), "subject": cfg.get("VAPID_SUBJECT") or "", "library": lib,
            "sent": int(raw.get("sent", 0)), "failed": int(raw.get("failed", 0)), "dropped": int(raw.get("dropped", 0)),
            "last_error": raw.get("last_error"), "last_error_at": int(raw.get("last_error_at", 0)) or None,
            "last_ok_at": int(raw.get("last_ok_at", 0)) or None,
            "due": r().zcard("web:notif:due"), "late": r().zcount("web:notif:due", "-inf", time.time() - 120)}


def schedule_energy(user):
    """After energy is spent: a push for when the bar is full again (for players who asked)."""
    if not enabled() or not wants_energy(user.id):
        return
    from app import social
    from app.game import logic
    left = logic.energy_refill_in(user)
    if left is None:
        return
    social.notify_later(str(user.id), "energy", time.time() + left.total_seconds(), "energy",
                        "Your energy is full. Time to fight!", "/mirror-world", push_only=True)
