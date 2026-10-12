"""Error alerts: every ERROR the site logs (a crashed page is one) is posted to a Discord channel webhook,
ALERT_WEBHOOK_URL, so a broken page is known before players report it. The full line, traceback included, is in the
admin Logs tab either way (app/logs.py).

Posting happens on a background thread, never in the request. The same error (logger, message and exception type)
is posted once per REPEAT seconds across all workers, and at most PER_HOUR alerts an hour go out.
"""
import hashlib
import logging
import os
import queue
import threading
import time

REPEAT = 600
PER_HOUR = 30
_q: "queue.Queue[dict]" = queue.Queue(maxsize=200)
_started = False


class AlertHandler(logging.Handler):
    def __init__(self, redis):
        super().__init__(logging.ERROR)
        self.redis = redis

    def emit(self, record):
        try:
            exc = record.exc_info[0].__name__ if record.exc_info and record.exc_info[0] else ""
            msg = record.getMessage()
            sig = hashlib.sha1(f"{record.name}|{msg[:200]}|{exc}".encode()).hexdigest()[:16]
            if not self.redis.set(f"web:alert:sig:{sig}", 1, nx=True, ex=REPEAT):
                return  # the same error was just posted
            hour = f"web:alert:hour:{int(time.time() // 3600)}"
            n = self.redis.incr(hour)
            self.redis.expire(hour, 3700)
            if n > PER_HOUR:
                return
            path = uid = None
            try:
                from flask import has_request_context, request, session
                if has_request_context():
                    path, uid = f"{request.method} {request.path}", session.get("uid")
            except Exception:
                pass
            tb = logging.Formatter().formatException(record.exc_info) if record.exc_info else ""
            _q.put_nowait({"msg": msg, "logger": record.name, "path": path, "uid": uid, "tb": tb, "exc": exc})
        except Exception:
            pass  # an alert must never break a request


def _text(a: dict) -> str:
    head = f"🚨 **{a['exc'] or 'Error'}** in `{a['logger']}`" + (f" on `{a['path']}`" if a["path"] else "")
    who = f"\nplayer `{a['uid']}`" if a["uid"] else ""
    body = f"\n{a['msg'][:400]}"
    tb = f"\n```{a['tb'][-1200:]}```" if a["tb"] else ""
    return (head + who + body + tb)[:1950]


def _loop(url: str):
    import requests
    while True:
        a = _q.get()
        try:
            requests.post(url, json={"content": _text(a), "allowed_mentions": {"parse": []}}, timeout=10)
        except Exception:
            pass


def install(redis):
    """Attach the handler when ALERT_WEBHOOK_URL is set (once per process)."""
    global _started
    url = os.environ.get("ALERT_WEBHOOK_URL", "")
    root = logging.getLogger()
    for h in list(root.handlers):
        if isinstance(h, AlertHandler):
            root.removeHandler(h)
    if not url:
        return False
    root.addHandler(AlertHandler(redis))
    if not _started:
        threading.Thread(target=_loop, args=(url,), name="alerts", daemon=True).start()
        _started = True
    return True
