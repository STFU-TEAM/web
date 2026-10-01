"""Migrate legacy character boxes to one web collection.

Run a dry-run first with:
    python scripts/migrate_storage.py
Apply after reviewing the count with:
    python scripts/migrate_storage.py --apply
Original pickles are backed up in Redis hash web:storage:migration:v1:backup.
"""
import argparse
import os
import pickle
import sys
from pathlib import Path

import redis

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db import PICKLE_PROTOCOL, migrate_storage_document

BACKUP_HASH = "web:storage:migration:v1:backup"


def main():
    parser = argparse.ArgumentParser(description="Unify legacy character storage boxes.")
    parser.add_argument("--apply", action="store_true", help="Write migrated documents; default is dry-run.")
    args = parser.parse_args()

    redis_url = os.environ.get("REDIS_URL")
    if not redis_url:
        parser.error("REDIS_URL must point to the existing game Redis database.")
    client = redis.Redis.from_url(redis_url)
    planned = 0
    skipped = 0
    for field, raw in client.hscan_iter("users", count=500):
        try:
            document = pickle.loads(raw)
        except Exception:
            skipped += 1
            continue
        migrated, changed = migrate_storage_document(document)
        if not changed:
            continue
        planned += 1
        if args.apply:
            field_text = field.decode() if isinstance(field, bytes) else str(field)
            client.hsetnx(BACKUP_HASH, field, raw)
            client.hset("users", field, pickle.dumps(migrated, protocol=PICKLE_PROTOCOL))
            client.hset("web:storage:migration:v1:completed", field_text, "1")

    mode = "Migrated" if args.apply else "Would migrate"
    print(f"{mode} {planned} user documents; skipped {skipped} unreadable documents.")
    if not args.apply:
        print("No data changed. Re-run with --apply to save backups and write the migration.")
    else:
        print(f"Original user pickles are backed up in Redis hash {BACKUP_HASH}.")
    client.close()


if __name__ == "__main__":
    main()