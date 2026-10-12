"""Gunicorn settings (the Dockerfile runs `gunicorn -c gunicorn.conf.py wsgi:app`). Tune with env vars in Coolify,
no rebuild needed:

    WEB_WORKERS   processes (default 3). Each loads the whole app (memory) and holds its own background threads
                  (puzzle builder, backups, notifications; Redis locks keep those to one run at a time). With spare
                  RAM and CPUs, raise it to about 2 per CPU + 1.
    WEB_THREADS   threads per process (default 8). Requests mostly wait on Redis, so threads are cheap capacity:
                  workers x threads requests run at once (3 x 8 = 24 on a 1-CPU box).
"""
import os

bind = "0.0.0.0:8000"
worker_class = "gthread"
workers = int(os.environ.get("WEB_WORKERS") or 3)
threads = int(os.environ.get("WEB_THREADS") or 8)
timeout = 60            # a fight simulation or a backup can take a while; a stuck request is still cut off
graceful_timeout = 30
keepalive = 5           # browsers reuse the connection for the HTMX polls
max_requests = 3000     # recycle workers now and then (memory), staggered so they never restart together
max_requests_jitter = 300
accesslog = "-"
