"""Server logs kept in Redis, so the admin panel can show what went wrong (Logs tab) without shell access.

Every worker writes to one shared list. The site's own loggers (app.*) are kept from INFO, everything else
(libraries, Flask internals) from WARNING. Records still go to stderr as before, for `docker logs`.

    web:logs    list of JSON {at, level, logger, msg, exc, path, uid, pid}, newest first, capped at KEEP
"""
import datetime
import json
import logging
import os
import sys
import threading

KEY = "web:logs"
KEEP = 2000
LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")
_local = threading.local()


class RedisHandler(logging.Handler):
    def __init__(self, redis):
        super().__init__(logging.INFO)
        self.redis = redis

    def filter(self, record):
        own = record.name == "app" or record.name.startswith("app.")
        return record.levelno >= (logging.INFO if own else logging.WARNING)

    def emit(self, record):
        if getattr(_local, "busy", False):  # a Redis error logged while writing a log line
            return
        _local.busy = True
        try:
            entry = {"at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
                     "level": record.levelname, "logger": record.name, "msg": record.getMessage()[:4000],
                     "exc": self.formatter_exc(record), "pid": os.getpid(), "path": None, "uid": None}
            try:
                from flask import has_request_context, request, session
                if has_request_context():
                    entry["path"] = f"{request.method} {request.full_path.rstrip('?')}"[:300]
                    entry["uid"] = session.get("uid")
            except Exception:
                pass
            pipe = self.redis.pipeline()
            pipe.lpush(KEY, json.dumps(entry, default=str))
            pipe.ltrim(KEY, 0, KEEP - 1)
            pipe.execute()
        except Exception:
            pass  # never let logging break a request
        finally:
            _local.busy = False

    @staticmethod
    def formatter_exc(record):
        if record.exc_info:
            return logging.Formatter().formatException(record.exc_info)[-8000:]
        return None


def install(app, redis):
    """Attach the Redis handler (once per process) and make sure stderr still gets the lines."""
    root = logging.getLogger()
    for h in list(root.handlers):
        if isinstance(h, RedisHandler):
            root.removeHandler(h)  # a second create_app (tests) points the handler at its own Redis
    if not any(type(h) is logging.StreamHandler for h in root.handlers):
        stream = logging.StreamHandler(sys.stderr)
        stream.setFormatter(logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s"))
        stream.setLevel(logging.INFO)
        stream.addFilter(lambda rec: rec.levelno >= logging.WARNING or rec.name == "app" or rec.name.startswith("app."))
        root.addHandler(stream)
    root.addHandler(RedisHandler(redis))
    if root.level > logging.INFO or root.level == logging.NOTSET:
        root.setLevel(logging.INFO)
    logging.getLogger("app").setLevel(logging.INFO)


def read(redis, level: str = "", logger: str = "", q: str = "", limit: int = 300):
    """The newest lines first, at or above `level`, whose logger starts with `logger` and that contain `q`."""
    floor = LEVELS.index(level) if level in LEVELS else 0
    q = (q or "").lower()
    out = []
    for raw in redis.lrange(KEY, 0, KEEP - 1):
        try:
            row = json.loads(raw)
        except (TypeError, ValueError):
            continue
        if row.get("level") in LEVELS and LEVELS.index(row["level"]) < floor:
            continue
        if logger and not (row.get("logger") or "").startswith(logger):
            continue
        if q and q not in json.dumps(row).lower():
            continue
        out.append(row)
        if len(out) >= limit:
            break
    return out


def counts(redis) -> dict:
    """Lines per level among the kept ones (the Logs tab's header)."""
    seen = {lv: 0 for lv in LEVELS}
    for raw in redis.lrange(KEY, 0, KEEP - 1):
        try:
            seen[json.loads(raw).get("level", "INFO")] += 1
        except (TypeError, ValueError, KeyError):
            continue
    return seen


def clear(redis):
    redis.delete(KEY)
