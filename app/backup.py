"""Backups of the whole Redis database (the bot's and the site's: it is the game's only database).

A snapshot is every key with its type-independent DUMP payload and its remaining TTL, pickled and gzipped into
BACKUP_DIR (a mounted volume in docker-compose.yml), newest KEEP kept. One is taken every day by a background
thread (any worker; a Redis lock makes it once a day across them all), and admins can take one, see the list and
download any file from the admin Safety tab, which is the simplest off-site copy. If BACKUP_WEBHOOK_URL is set (a
Discord channel webhook), each daily file small enough for Discord is also posted there.

Restore (on a stopped bot and site, against the right REDIS_URL):  python scripts/backup.py restore <file> [--flush]

Redis keeps its own copy on disk only if persistence is on (RDB snapshots or appendonly); persistence() reports it
on the Safety tab, since a restart without it loses everything since the last file here.

    web:backup:log    list of JSON {at, file, keys, bytes, seconds, error, sent}, newest first
"""
import datetime
import gzip
import json
import logging
import os
import pickle
import threading
import time
from typing import List, Optional

LOG_KEY = "web:backup:log"
LOCK_KEY = "web:backup:lock"
KEEP = 14
EVERY = 24 * 3600
PREFIX = "stfu-redis-"
SUFFIX = ".pkl.gz"
WEBHOOK_LIMIT = 24 * 1024 * 1024  # Discord's attachment limit for webhooks, with room to spare
logger = logging.getLogger(__name__)


def folder() -> str:
    return os.environ.get("BACKUP_DIR") or os.path.join(os.getcwd(), "backups")


def snapshot(redis) -> list:
    """[(key, pttl or 0, dump bytes)] for every key, read in batches."""
    out = []
    batch = []
    for key in redis.scan_iter(count=1000):
        batch.append(key)
        if len(batch) >= 500:
            out.extend(_dump(redis, batch))
            batch = []
    if batch:
        out.extend(_dump(redis, batch))
    return out


def _dump(redis, keys) -> list:
    pipe = redis.pipeline(transaction=False)
    for k in keys:
        pipe.dump(k)
        pipe.pttl(k)
    res = pipe.execute()
    rows = []
    for i, k in enumerate(keys):
        payload, ttl = res[2 * i], res[2 * i + 1]
        if payload is not None:  # expired between the scan and the dump
            rows.append((k, max(0, int(ttl or 0)), payload))
    return rows


def write(redis, directory: Optional[str] = None) -> dict:
    """Take a snapshot to a new file and drop the oldest past KEEP. Returns the log row."""
    directory = directory or folder()
    os.makedirs(directory, exist_ok=True)
    started = time.time()
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d-%H%M%S")
    path = os.path.join(directory, f"{PREFIX}{stamp}{SUFFIX}")
    rows = snapshot(redis)
    with gzip.open(path + ".part", "wb", compresslevel=6) as fh:
        pickle.dump({"v": 1, "at": stamp, "rows": rows}, fh, protocol=pickle.HIGHEST_PROTOCOL)
    os.replace(path + ".part", path)
    for old in files(directory)[KEEP:]:
        try:
            os.remove(os.path.join(directory, old["name"]))
        except OSError:
            pass
    return {"at": stamp, "file": os.path.basename(path), "keys": len(rows), "bytes": os.path.getsize(path),
            "seconds": round(time.time() - started, 1), "error": None, "sent": False}


def restore(redis, path: str, flush: bool = False) -> int:
    """Put every key of a backup file back (replacing what's there). flush: empty the database first."""
    with gzip.open(path, "rb") as fh:
        data = pickle.load(fh)  # only ever our own files: never restore one you didn't make
    if flush:
        redis.flushdb()
    pipe = redis.pipeline(transaction=False)
    for n, (key, ttl, payload) in enumerate(data["rows"], 1):
        pipe.restore(key, ttl, payload, replace=True)
        if n % 500 == 0:
            pipe.execute()
    pipe.execute()
    return len(data["rows"])


def files(directory: Optional[str] = None) -> List[dict]:
    """The backup files, newest first."""
    directory = directory or folder()
    try:
        names = sorted((n for n in os.listdir(directory) if n.startswith(PREFIX) and n.endswith(SUFFIX)), reverse=True)
    except OSError:
        return []
    return [{"name": n, "bytes": os.path.getsize(os.path.join(directory, n))} for n in names]


def path_of(name: str) -> Optional[str]:
    """A backup file's path, only for names this module wrote (no path tricks)."""
    if not (name.startswith(PREFIX) and name.endswith(SUFFIX)) or "/" in name or "\\" in name or ".." in name:
        return None
    path = os.path.join(folder(), name)
    return path if os.path.isfile(path) else None


def log(redis, row: dict):
    redis.lpush(LOG_KEY, json.dumps(row))
    redis.ltrim(LOG_KEY, 0, 99)


def read_log(redis, limit: int = 30) -> List[dict]:
    out = []
    for raw in redis.lrange(LOG_KEY, 0, limit - 1):
        try:
            out.append(json.loads(raw))
        except (TypeError, ValueError):
            continue
    return out


def persistence(redis) -> dict:
    """Is Redis itself saving to disk? {"rdb": bool|None, "aof": bool|None} (None: CONFIG isn't allowed here)."""
    try:
        save = redis.config_get("save").get("save", "")
        aof = redis.config_get("appendonly").get("appendonly", "no")
        return {"rdb": bool(save.strip()), "aof": aof == "yes"}
    except Exception:
        return {"rdb": None, "aof": None}


def send(path: str) -> bool:
    """Post a backup file to BACKUP_WEBHOOK_URL (a Discord webhook): the off-site copy. False if not sent."""
    url = os.environ.get("BACKUP_WEBHOOK_URL", "")
    if not url or os.path.getsize(path) > WEBHOOK_LIMIT:
        return False
    import requests
    with open(path, "rb") as fh:
        resp = requests.post(url, data={"content": f"🗄️ STFU Requiem backup `{os.path.basename(path)}`"},
                             files={"file": (os.path.basename(path), fh, "application/gzip")}, timeout=60)
    return resp.status_code < 300


def run_once(redis) -> dict:
    """One backup, logged (and posted off-site when configured). Never raises."""
    try:
        row = write(redis)
        try:
            row["sent"] = send(os.path.join(folder(), row["file"]))
        except Exception as e:
            row["error"] = f"saved, but the off-site post failed: {type(e).__name__}"
    except Exception as e:
        logger.exception("backup")
        row = {"at": datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d-%H%M%S"), "file": None, "keys": 0,
               "bytes": 0, "seconds": 0, "error": f"{type(e).__name__}: {e}"[:300], "sent": False}
    try:
        log(redis, row)
    except Exception:
        pass
    return row


def start(redis_getter):
    """The daily backup thread (one per worker; the lock lets only one of them run each day)."""
    def loop():
        time.sleep(60)
        while True:
            try:
                if redis_getter().set(LOCK_KEY, str(os.getpid()), nx=True, ex=EVERY - 300):
                    run_once(redis_getter())
            except Exception:
                logger.exception("backup loop")
            time.sleep(900)

    threading.Thread(target=loop, name="backup", daemon=True).start()
