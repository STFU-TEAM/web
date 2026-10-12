"""Back up or restore the whole Redis database (app/backup.py).

    python scripts/backup.py backup                  # a new file in BACKUP_DIR (default ./backups)
    python scripts/backup.py list
    python scripts/backup.py restore <file> [--flush]   # put every key back (--flush empties the database first)

Uses REDIS_URL. Restore with the bot and the site stopped, and double-check REDIS_URL first: it overwrites keys.
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import redis  # noqa: E402

from app import backup  # noqa: E402


def main(argv):
    if not argv or argv[0] not in ("backup", "list", "restore"):
        sys.exit(__doc__)
    url = os.environ.get("REDIS_URL")
    if argv[0] == "list":
        for f in backup.files():
            print(f"{f['name']}  {f['bytes'] / 1e6:.1f} MB")
        return
    if not url:
        sys.exit("Set REDIS_URL first.")
    db = redis.Redis.from_url(url)
    if argv[0] == "backup":
        row = backup.write(db)
        print(f"{row['file']}: {row['keys']} keys, {row['bytes'] / 1e6:.1f} MB in {row['seconds']} s -> {backup.folder()}")
        return
    if len(argv) < 2:
        sys.exit("restore needs a backup file.")
    flush = "--flush" in argv
    answer = input(f"Restore {argv[1]} into {url}{' after EMPTYING it' if flush else ''}? Type yes: ")
    if answer.strip().lower() != "yes":
        sys.exit("Cancelled.")
    print(f"Restored {backup.restore(db, argv[1], flush=flush)} keys.")


if __name__ == "__main__":
    main(sys.argv[1:])
