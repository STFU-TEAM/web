import os

from app import backup, create_app
from app.db import r
from app.game.puzzle import start_generator
from app.social import start_flusher

app = create_app()
# Background work (puzzle building, backups, notifications) belongs in its own process: scripts/worker.py, the
# `worker` service in docker-compose.yml, which sets RUN_BACKGROUND=0 here. Without that service it runs in the web
# workers as before (Redis locks keep each job to one run at a time), at the cost of the odd slow page.
if os.environ.get("RUN_BACKGROUND", "1") != "0":
    start_flusher(app)  # here and not in create_app: tests and scripts build apps without a background thread
    start_generator(app)  # the puzzle library: one checked puzzle every few minutes, whatever the traffic
    backup.start(r)  # a snapshot of the whole Redis database every day (app/backup.py)
