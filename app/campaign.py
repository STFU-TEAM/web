"""Where players come from: a link with ?src=<source> (tiktok, youtube, discord, reddit...) counts a visit for that
source, and the browser keeps its first source in the session so a save begun later counts as that source's signup.
Only counts per source and day are stored: nothing about the visitor. The admin dashboard shows the last 30 days.

    web:src:visits:<YYYY-MM-DD>   hash source -> visits that day
    web:src:signups:<YYYY-MM-DD>  hash source -> saves begun that day
"""
import datetime
import re

SRC_RE = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,23}$")
KEEP = 120 * 86400


def _day(offset: int = 0) -> str:
    return (datetime.datetime.now(datetime.timezone.utc).date() - datetime.timedelta(days=offset)).isoformat()


def _count(redis, kind: str, src: str):
    key = f"web:src:{kind}:{_day()}"
    pipe = redis.pipeline(transaction=False)
    pipe.hincrby(key, src, 1)
    pipe.expire(key, KEEP)
    pipe.execute()


def install(app, redis_getter):
    from flask import request, session

    @app.before_request
    def campaign_source():
        src = (request.args.get("src") or request.args.get("utm_source") or "").strip().lower()
        if not src or request.endpoint == "static" or not SRC_RE.match(src):
            return
        session.setdefault("src", src)  # the first source this browser came with
        if session.get("src_seen") == src:  # one visit per session and source: reloads don't count twice
            return
        session["src_seen"] = src
        try:
            _count(redis_getter(), "visits", src)
        except Exception:
            pass  # a counter must never break a page


def signup(redis, session):
    """A save just began: count it for the source this browser came with, if any."""
    src = session.get("src")
    if src:
        try:
            _count(redis, "signups", src)
        except Exception:
            pass


def report(redis, days: int = 30) -> list:
    """[{src, visits, signups, visits_7, signups_7}] for the last `days` days, most visits first."""
    rows = {}
    for offset in range(days):
        day = _day(offset)
        for kind in ("visits", "signups"):
            for src, n in redis.hgetall(f"web:src:{kind}:{day}").items():
                src = src.decode() if isinstance(src, bytes) else src
                row = rows.setdefault(src, {"src": src, "visits": 0, "signups": 0, "visits_7": 0, "signups_7": 0})
                row[kind] += int(n)
                if offset < 7:
                    row[f"{kind}_7"] += int(n)
    return sorted(rows.values(), key=lambda x: (-x["visits"], -x["signups"], x["src"]))
