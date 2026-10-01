"""Data access shared with the stfu-reborn bot.

The bot keeps everything in Redis, in hashes whose fields are pickled dicts:
    HSET users  <discord_id> pickle(user_doc)
    HSET gangs  <gang_id>    pickle(gang_doc)
    HSET shops / guilds / logs / active_wars ...
Some very old players are stored under the field "b'<discord_id>'"; the bot
strips it in User.__init__ and writes back to doc["_id"], so we do the same.

Website-only keys are prefixed "web:" and never touch the bot's keys.
"""
import json
import pickle
import time
from contextlib import ExitStack, contextmanager
from typing import Optional

import redis
import requests
from flask import current_app, g

from app.game.user import User, create_user

_redis: Optional[redis.Redis] = None
PICKLE_PROTOCOL = 4  # readable by the bot's Python 3.11
LEGACY_STORAGE_FIELDS = (
    "character_storage_1", "character_storage_2", "character_storage_3", "character_storage_4",
    "pcharacter_storage_1", "pcharacter_storage_2", "pcharacter_storage_3", "pcharacter_storage_4",
)


def migrate_storage_document(document: dict) -> tuple[dict, bool]:
    """Fold old storage boxes into one canonical list without dropping stands."""
    legacy = [stand for field in LEGACY_STORAGE_FIELDS for stand in document.get(field, [])]
    canonical = document.get("storage_characters", [])
    if not legacy and "storage_characters" in document and all(not document.get(field) for field in LEGACY_STORAGE_FIELDS):
        return document, False

    combined = []
    seen_uuids = set()
    for stand in canonical + legacy:
        stand_uuid = stand.get("uuid")
        if stand_uuid and stand_uuid in seen_uuids:
            continue
        if stand_uuid:
            seen_uuids.add(stand_uuid)
        combined.append(stand)

    migrated = dict(document)
    migrated["storage_characters"] = combined
    for field in LEGACY_STORAGE_FIELDS:
        migrated[field] = []
    return migrated, True


def init_db(app):
    global _redis
    _redis = redis.Redis.from_url(app.config["REDIS_URL"])


def r() -> redis.Redis:
    return _redis


class Database:
    def _raw_user(self, user_id: str):
        user_id = str(user_id)
        raw = _redis.hget("users", user_id)
        if raw is None:
            raw = _redis.hget("users", f"b'{user_id}'")
        return raw

    def get_user_doc(self, user_id: str) -> Optional[dict]:
        raw = self._raw_user(user_id)
        return pickle.loads(raw) if raw else None

    def get_user(self, user_id: str) -> Optional[User]:
        doc = self.get_user_doc(user_id)
        return User(doc, self) if doc else None

    def user_exists(self, user_id: str) -> bool:
        return self._raw_user(user_id) is not None

    def add_user(self, user_id: str) -> User:
        doc = create_user(str(user_id))
        _redis.hset("users", str(user_id), pickle.dumps(doc, protocol=PICKLE_PROTOCOL))
        return User(doc, self)

    def update_user(self, doc: dict):
        _redis.hset("users", doc["_id"], pickle.dumps(doc, protocol=PICKLE_PROTOCOL))

    def get_gang(self, gang_id: Optional[str]) -> Optional[dict]:
        if not gang_id:
            return None
        raw = _redis.hget("gangs", gang_id)
        return pickle.loads(raw) if raw else None

    def all_gangs(self):
        for _, raw in _redis.hscan_iter("gangs", count=500):
            try:
                yield pickle.loads(raw)
            except Exception:
                continue

    def create_gang(self, document: dict):
        _redis.hset("gangs", document["_id"], pickle.dumps(document, protocol=PICKLE_PROTOCOL))

    def update_gang(self, document: dict):
        self.create_gang(document)

    def delete_gang(self, gang_id: str):
        _redis.hdel("gangs", gang_id)

    def get_shop(self, shop_id: Optional[str]) -> Optional[dict]:
        if not shop_id:
            return None
        raw = _redis.hget("shops", shop_id)
        return pickle.loads(raw) if raw else None

    def all_shops(self):
        for _, raw in _redis.hscan_iter("shops", count=500):
            try:
                yield pickle.loads(raw)
            except Exception:
                continue

    def create_shop(self, document: dict):
        _redis.hset("shops", document["_id"], pickle.dumps(document, protocol=PICKLE_PROTOCOL))

    def update_shop(self, document: dict):
        self.create_shop(document)

    def all_user_docs(self):
        for field, raw in _redis.hscan_iter("users", count=500):
            try:
                doc = pickle.loads(raw)
            except Exception:
                continue
            uid = field.decode() if isinstance(field, bytes) else str(field)
            if uid.startswith("b'"):
                uid = uid[2:-1]
            yield uid, doc


def get_db() -> Database:
    if "db" not in g:
        g.db = Database()
    return g.db


# --------------------------------------------------------------------------- #
# Leaderboard: scanning every user is slow, cache the result 5 minutes
# --------------------------------------------------------------------------- #
LEADERBOARD_FIELDS = {"global_elo", "xp", "tower_level", "missions_level", "prestige"}


def leaderboard(field: str, limit: int = 50):
    if field not in LEADERBOARD_FIELDS:
        field = "global_elo"
    key = f"web:leaderboard:{field}"
    cached = _redis.get(key)
    if cached:
        return json.loads(cached)
    rows = []
    for uid, doc in get_db().all_user_docs():
        lead = doc.get("main_characters") or []
        rows.append({"id": uid, "value": int(doc.get(field, 0) or 0),
                     "lead": lead[0]["id"] if lead else None})
    rows.sort(key=lambda x: x["value"], reverse=True)
    rows = rows[:limit]
    _redis.set(key, json.dumps(rows), ex=300)
    return rows


# --------------------------------------------------------------------------- #
# Per-user action lock (double clicks, two tabs)
# --------------------------------------------------------------------------- #
class Busy(Exception):
    pass


@contextmanager
def user_lock(user_id: str, ttl: int = 10):
    key = f"web:lock:{user_id}"
    token = str(time.time())
    if not _redis.set(key, token, nx=True, ex=ttl):
        raise Busy()
    try:
        yield
    finally:
        if _redis.get(key) == token.encode():
            _redis.delete(key)


@contextmanager
def users_lock(*user_ids: str, ttl: int = 10):
    """Lock multiple accounts in a stable order for marketplace transfers."""
    with ExitStack() as stack:
        for user_id in sorted(set(map(str, user_ids))):
            stack.enter_context(user_lock(user_id, ttl))
        yield


# --------------------------------------------------------------------------- #
# Fights (pickled state machine, web-only keys)
# --------------------------------------------------------------------------- #
FIGHT_TTL = 15 * 60


def save_fight(user_id: str, fight):
    _redis.set(f"web:fight:{user_id}", pickle.dumps(fight), ex=FIGHT_TTL)


def load_fight(user_id: str):
    raw = _redis.get(f"web:fight:{user_id}")
    return pickle.loads(raw) if raw else None


def clear_fight(user_id: str):
    _redis.delete(f"web:fight:{user_id}")


# --------------------------------------------------------------------------- #
# Discord identities for leaderboards / profiles
# --------------------------------------------------------------------------- #
def remember_identity(user_id: str, name: str, avatar: Optional[str]):
    _redis.set(f"web:identity:{user_id}", json.dumps({"name": name, "avatar": avatar}), ex=30 * 24 * 3600)


def identity(user_id: str) -> dict:
    user_id = str(user_id)
    raw = _redis.get(f"web:identity:{user_id}")
    if raw:
        return json.loads(raw)
    token = current_app.config.get("DISCORD_BOT_TOKEN")
    data = {"name": f"Player {user_id[-4:]}", "avatar": None}
    if token:
        try:
            resp = requests.get(f"https://discord.com/api/v10/users/{user_id}",
                                headers={"Authorization": f"Bot {token}"}, timeout=3)
            if resp.ok:
                u = resp.json()
                data = {"name": u.get("global_name") or u["username"], "avatar": avatar_url(u)}
        except requests.RequestException:
            pass
    _redis.set(f"web:identity:{user_id}", json.dumps(data), ex=24 * 3600)
    return data


def avatar_url(u: dict) -> Optional[str]:
    if u.get("avatar"):
        ext = "gif" if u["avatar"].startswith("a_") else "png"
        return f"https://cdn.discordapp.com/avatars/{u['id']}/{u['avatar']}.{ext}?size=128"
    return None
