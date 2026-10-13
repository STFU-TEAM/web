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

Guests play with no login at all: a web id like any password-only one, reached through a long-lived cookie on their
browser (GUEST_COOKIE holds a random token). Adding a username + password turns the guest into a normal account.
    web:guest:<token>       uid       (refreshed on every visit)
    web:guest_uid:<uid>     token     (exists while the save is a guest's)
    web:rename:<uid>        set for RENAME_COOLDOWN after a web-only player renames
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
    from app.db import index_name
    index_name(account["uid"], username=username)
    if is_local(account["uid"]):
        remember_identity(account["uid"], username, None, ttl=None)
    return account


GUEST_COOKIE = "stfu_guest"
GUEST_DAYS = 400  # the cookie's life, and the token's: renewed on every visit
RENAME_COOLDOWN = 7 * 24 * 3600


def create_guest() -> dict:
    """A new guest: {uid, name, token}. The token goes in the guest's cookie."""
    uid, token = f"acc{secrets.token_hex(8)}", secrets.token_urlsafe(32)
    name = f"Guest-{secrets.token_hex(2).upper()}"
    ttl = GUEST_DAYS * 86400
    r().set(f"web:guest:{token}", uid, ex=ttl)
    r().set(f"web:guest_uid:{uid}", token, ex=ttl)
    remember_identity(uid, name, None, ttl=None)
    return {"uid": uid, "name": name, "token": token}


def guest_of(token: Optional[str]) -> Optional[str]:
    """The guest save behind a cookie token (and the token's life starts over), or None."""
    if not token or len(token) > 100:
        return None
    raw = r().get(f"web:guest:{token}")
    if not raw:
        return None
    uid = raw.decode() if isinstance(raw, bytes) else raw
    if not r().exists(f"web:guest_uid:{uid}"):  # upgraded to a real account: the cookie no longer logs in
        return None
    ttl = GUEST_DAYS * 86400
    r().expire(f"web:guest:{token}", ttl)
    r().expire(f"web:guest_uid:{uid}", ttl)
    return uid


def is_guest(uid) -> bool:
    return bool(uid) and is_local(uid) and bool(r().exists(f"web:guest_uid:{uid}"))


def end_guest(uid: str):
    """A guest saved their progress with a username: the cookie stops logging in."""
    token = r().get(f"web:guest_uid:{uid}")
    if token:
        r().delete(f"web:guest:{token.decode() if isinstance(token, bytes) else token}")
    r().delete(f"web:guest_uid:{uid}")


def rename(uid: str, new: str) -> str:
    """A web-only player's new username (it is also their display name and their login). Once a week."""
    if not is_local(uid):
        raise AccountError("Discord players take their name from Discord.")
    old = r().get(f"web:account_uid:{uid}")
    if not old:
        raise AccountError("Save your account with a username first.")
    old = old.decode() if isinstance(old, bytes) else old
    if not USERNAME_RE.match(new or ""):
        raise AccountError("Usernames are 3-24 characters: letters, numbers, dot, dash or underscore.")
    if new.lower() == old and new == (get_account(old) or {}).get("name"):
        raise AccountError("That's already your name.")
    left = r().ttl(f"web:rename:{uid}")
    if left and left > 0:
        days = max(1, round(left / 86400))
        raise AccountError(f"You can rename again in {days} day{'s' if days != 1 else ''}.")
    account = get_account(old)
    if not account:
        raise AccountError("This account can't be renamed.")
    account["name"] = new
    if new.lower() != old:
        if not r().set(_key(new), json.dumps(account), nx=True):
            raise AccountError("That username is taken.")
        r().delete(_key(old))
        r().set(f"web:account_uid:{uid}", new.lower())
    else:  # only the capitals change
        r().set(_key(new), json.dumps(account))
    r().set(f"web:rename:{uid}", old, ex=RENAME_COOLDOWN)
    from app.db import identity, index_name
    remember_identity(uid, new, identity(uid).get("avatar"), ttl=None)
    index_name(uid, username=new)
    return new


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
    promoted = r().hget("web:admins", local_uid)  # an admin promoted on the site stays one (app/auth.py ADMINS_KEY)
    if promoted:
        r().hset("web:admins", discord_uid, promoted)
        r().hdel("web:admins", local_uid)
    r().delete(f"web:account_uid:{local_uid}", f"web:identity:{local_uid}", f"web:fight:{local_uid}")
