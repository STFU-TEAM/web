"""The background worker: everything that isn't answering a page, in its own process so it never slows one down.

    python scripts/worker.py

Runs the puzzle builder (a puzzle every few minutes: thousands of simulated fights, seconds of CPU), the daily
database backup and the notification flusher. In docker-compose.yml it's the `worker` service, and the web service
sets RUN_BACKGROUND=0 so its gunicorn workers run none of it. Python runs one thread at a time per process: a puzzle
built inside a web worker used to stall every request that worker was serving.
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import backup, create_app  # noqa: E402
from app.db import r  # noqa: E402
from app.game.puzzle import start_generator  # noqa: E402
from app.social import start_flusher  # noqa: E402


def main():
    app = create_app()
    start_flusher(app)
    start_generator(app)
    backup.start(r)
    app.logger.info("background worker started: puzzles, backups, notifications")
    while True:
        time.sleep(3600)


if __name__ == "__main__":
    main()
