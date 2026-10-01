"""Username + password logins, next to Discord OAuth.

A Discord login's game id is the Discord user id (the bot's key). A password-only
account gets a web id "acc<hex>", which can never collide with a Discord snowflake
and never starts with "b" (User() strips a legacy "b'...'" prefix).

Redis (web-only keys):
    web:account:<username lower>  JSON {uid, name, pw, created}
    web:account_uid:<uid>         username lower  (reverse lookup)
A Discord player can add a username + password to the same save, and a
password-only player can later link Discord, which moves the save to their
Discord id so the bot sees it.
"""
import datetime
import json
import pickle
import re
import secrets
from typing import Optional

from werkzeug.security import check_password_hash, generate_password_hash

from app.db import PICKLE_PROTOCOL, get_db, r, remember_identity

USERNAME_RE = re.compile(r"^[A-Za-z0-9_.-]{3,24}$")
MIN_PASSWORD = 8
MAX_ATTEMPTS = 8           # per username and per IP ...
ATTEMPT_WINDOW = 15 * 60   # ... within this many seconds
# Burned on unknown usernames so a miss costs as much as a wrong password.
_DUMMY_HASH = generate_password_hash(secrets.token_hex(16))


class AccountError(Exception):
    pass


def _key(username: str) -> str:
    return f"web:account:{username.lower()}"


def is_local(uid: str) -> bool:
    return str(uid).startswith("acc")


def get_account(username: str) -> Optional[dict]:
    raw = r().get(_key(username))
    return json.loads(raw) if raw else None


def username_of(uid: str) -> Optional[str]:
    raw = r().get(f"web:account_uid:{uid}")
    if not raw:
        return None
    account = get_account(raw.decode() if isinstance(raw, bytes) else raw)
    return account["name"] if account else None


def validate(username: str, password: str):
    if not USERNAME_RE.match(username or ""):
        raise AccountError("Usernames are 3-24 characters: letters, numbers, dot, dash or underscore.")
    if len(password or "") < MIN_PASSWORD:
        raise AccountError(f"Use a password of at least {MIN_PASSWORD} characters.")
    if len(password) > 200:
        raise AccountError("That password is too long.")


def create_account(username: str, password: str, uid: Optional[str] = None) -> dict:
    """Create a login. uid=None makes a fresh web-only id; pass a Discord id to add a password to it."""
    validate(username, password)
    if uid and r().exists(f"web:account_uid:{uid}"):
        raise AccountError("This save already has a username. Change its password instead.")
    account = {"uid": uid or f"acc{secrets.token_hex(8)}", "name": username,
               "pw": generate_password_hash(password),
               "created": datetime.datetime.now(datetime.timezone.utc).isoformat()}
    if not r().set(_key(username), json.dumps(account), nx=True):
        raise AccountError("That username is taken.")
    r().set(f"web:account_uid:{account['uid']}", username.lower())
    if is_local(account["uid"]):
        remember_identity(account["uid"], username, None, ttl=None)
    return account


def set_password(uid: str, current: str, new: str):
    username = r().get(f"web:account_uid:{uid}")
    if not username:
        raise AccountError("This save has no username yet.")
    account = get_account(username.decode())
    if not account or not check_password_hash(account["pw"], current or ""):
        raise AccountError("Your current password is wrong.")
    validate(account["name"], new)
    account["pw"] = generate_password_hash(new)
    r().set(_key(account["name"]), json.dumps(account))


def _throttled(*keys: str) -> bool:
    return any(int(r().get(f"web:login_fail:{k}") or 0) >= MAX_ATTEMPTS for k in keys)


def _fail(*keys: str):
    for k in keys:
        pipe = r().pipeline()
        pipe.incr(f"web:login_fail:{k}")
        pipe.expire(f"web:login_fail:{k}", ATTEMPT_WINDOW)
        pipe.execute()


def authenticate(username: str, password: str, ip: str) -> dict:
    keys = (f"user:{(username or '').lower()}", f"ip:{ip}")
    if _throttled(*keys):
        raise AccountError("Too many attempts. Wait 15 minutes and try again.")
    account = get_account(username or "") if USERNAME_RE.match(username or "") else None
    if not check_password_hash(account["pw"] if account else _DUMMY_HASH, password or "") or not account:
        _fail(*keys)
        raise AccountError("Wrong username or password.")
    r().delete(f"web:login_fail:{keys[0]}")
    return account


def resolve_player(text: str) -> Optional[str]:
    """A Discord id, a web account id or a username -> game id of an existing save."""
    text = (text or "").strip().lstrip("@")
    if not text:
        return None
    db = get_db()
    if (text.isdigit() or is_local(text)) and db.user_exists(text):
        return text
    account = get_account(text) if USERNAME_RE.match(text) else None
    if account and db.user_exists(account["uid"]):
        return account["uid"]
    return None


def link_discord(local_uid: str, discord_uid: str):
    """Move a password-only save to a Discord id so the bot sees it."""
    db = get_db()
    if db.user_exists(discord_uid):
        raise AccountError("That Discord account already has a save. Log in with Discord, then add "
                           "a username and password from your profile instead.")
    if r().exists(f"web:account_uid:{discord_uid}"):
        raise AccountError("That Discord account already has a username.")
    doc = db.get_user_doc(local_uid)
    username = r().get(f"web:account_uid:{local_uid}")
    if doc is None or not username:
        raise AccountError("This save can't be linked.")
    username = username.decode()

    doc["_id"] = discord_uid
    r().hset("users", discord_uid, pickle.dumps(doc, protocol=PICKLE_PROTOCOL))
    r().hdel("users", local_uid)
    # Point everything that names the old id at the new one.
    gang = db.get_gang(doc.get("gang_id"))
    if gang:
        gang["users"] = [discord_uid if str(u) == local_uid else u for u in gang.get("users", [])]
        ranks = gang.get("ranks", {})
        if local_uid in ranks:
            ranks[discord_uid] = ranks.pop(local_uid)
        for field in ("war_attacks", "raid_attacks"):
            gang[field] = [discord_uid if str(u) == local_uid else u for u in gang.get(field, [])]
        db.update_gang(gang)
    shop = db.get_shop(doc.get("shop_id"))
    if shop and str(shop.get("owner")) == local_uid:
        shop["owner"] = discord_uid
        db.update_shop(shop)
    account = get_account(username)
    account["uid"] = discord_uid
    r().set(_key(username), json.dumps(account))
    r().set(f"web:account_uid:{discord_uid}", username)
    r().delete(f"web:account_uid:{local_uid}", f"web:identity:{local_uid}", f"web:fight:{local_uid}")
