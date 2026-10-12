"""Maintenance mode: an admin switches the site off for players from the admin dashboard.

While it's on, every page answers players with the maintenance screen (HTTP 503, so search engines come back later).
Admins browse as usual, under a banner. The login page, static files and /healthz always work, so an admin can sign in
and Coolify keeps the container healthy. Each worker reads the switch at most every CACHE_SECONDS.

    web:maintenance    JSON {"on": true, "message", "until" (ISO date-time or ""), "by", "at"}
"""
import datetime
import json
import time
from typing import Optional

KEY = "web:maintenance"
CACHE_SECONDS = 3
OPEN = {"static", "healthz", "auth.login", "auth.logout", "auth.discord_login", "auth.callback", "main.manifest",
        "main.robots", "chat.sticker"}
_cache = {"at": 0.0, "db": None, "state": None}


def state(redis) -> Optional[dict]:
    """The switch if it's on, else None (cached a few seconds per worker)."""
    if _cache["db"] is redis and time.time() - _cache["at"] < CACHE_SECONDS:
        return _cache["state"]
    try:
        raw = redis.get(KEY)
        st = json.loads(raw) if raw else None
    except Exception:
        st = None  # Redis down: never lock everyone out because of it
    st = st if st and st.get("on") else None
    _cache.update(at=time.time(), db=redis, state=st)
    return st


def turn_on(redis, by: str, message: str = "", until: str = "") -> dict:
    st = {"on": True, "message": message.strip()[:500], "until": until.strip()[:40], "by": str(by),
          "at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")}
    redis.set(KEY, json.dumps(st))
    _cache["db"] = None
    return st


def turn_off(redis):
    redis.delete(KEY)
    _cache["db"] = None


def install(app, redis_getter):
    """The gate in front of every page."""
    from flask import render_template, request, session

    @app.before_request
    def maintenance_gate():
        if request.endpoint in OPEN or request.endpoint is None and request.path.startswith("/static"):
            return None
        st = state(redis_getter())
        if not st:
            return None
        uid = session.get("uid")
        if uid:
            from app.auth import is_admin
            try:
                if is_admin(uid):
                    return None  # admins work as usual (base.html shows them a banner)
            except Exception:
                pass
        if request.headers.get("HX-Request"):  # a background poll: tell the page to show the screen
            resp = app.response_class(status=503)
            resp.headers["HX-Refresh"] = "true"
            return resp
        resp = app.make_response((render_template("maintenance.html", m=st), 503))
        resp.headers["Retry-After"] = "300"
        return resp

    @app.context_processor
    def maintenance_banner():
        try:
            return {"maintenance": state(redis_getter()) if session.get("uid") else None}
        except Exception:
            return {"maintenance": None}
