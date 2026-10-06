"""Run the site locally for quick testing, with an admin account ready to log in.

    python scripts/dev.py                 # in-memory Redis (fakeredis), wiped on exit
    python scripts/dev.py --redis redis://localhost:6379/0   # a local Redis that persists
    python scripts/dev.py --port 5001

Log in at http://127.0.0.1:5000/auth/login with  admin / admin.
The admin has a game save (every stand at level 100, top awakening and shiny, fragments, items) and can
open /admin. A kept save (--redis) keeps its progress but gets the full maxed collection again on each start.

By default this never connects to a real Redis, even if REDIS_URL is set in your
shell, so it can't touch the bot's data. Pass --redis explicitly to use one; don't
point it at production.
"""
import argparse
import datetime
import json
import os
import pickle
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "admin"
# Admin rights are checked against Discord-style numeric ids, so the dev admin gets one.
ADMIN_UID = "100000000000000001"


def use_fake_redis():
    try:
        import fakeredis
    except ImportError:
        sys.exit("fakeredis is missing: pip install -r requirements-dev.txt (or pass --redis URL)")
    import app.db as dbmod
    server = fakeredis.FakeRedis()
    dbmod.redis.Redis.from_url = staticmethod(lambda *a, **k: server)


def seed_admin():
    """Create (or reset) the admin login and give it a playable save."""
    from werkzeug.security import generate_password_hash

    from app.db import PICKLE_PROTOCOL, r, remember_identity
    from app.game.character import CHARACTER_FILE, get_character_from_template
    from app.game.user import create_user

    # Written directly: the register form requires 8+ character passwords.
    account = {"uid": ADMIN_UID, "name": ADMIN_USERNAME, "pw": generate_password_hash(ADMIN_PASSWORD),
               "created": datetime.datetime.now(datetime.timezone.utc).isoformat()}
    r().set(f"web:account:{ADMIN_USERNAME}", json.dumps(account))
    r().set(f"web:account_uid:{ADMIN_UID}", ADMIN_USERNAME)
    r().delete(f"web:login_fail:user:{ADMIN_USERNAME}")
    remember_identity(ADMIN_UID, ADMIN_USERNAME, None, ttl=None)

    from app.game.character import MAX_LEVEL
    from app.game.logic import MAX_AWAKEN

    def stand(cid):
        """Maxed and shiny: level 100, the top awakening, two Universal types."""
        doc = get_character_from_template(CHARACTER_FILE[cid - 1], ["ATTACK", "HEALTH"], ["UNIVERSAL", "UNIVERSAL"]).to_dict()
        doc.update(xp=MAX_LEVEL * 100, awaken=MAX_AWAKEN, shiny=True)
        return doc

    # every stand a player can own, once: the team leads with three of them, the rest wait in storage
    ids = [c["id"] for c in CHARACTER_FILE if c["universe"] != "Dummy"]
    team_ids = [1, 2, 5]
    collection = dict(main_characters=[stand(i) for i in team_ids],
                      storage_characters=[stand(i) for i in ids if i not in team_ids],
                      web_dex=sorted(ids))

    if r().hexists("users", ADMIN_UID):  # a kept save (--redis): refresh the collection, keep the rest
        doc = pickle.loads(r().hget("users", ADMIN_UID))
        doc.update(collection)
        r().hset("users", ADMIN_UID, pickle.dumps(doc, protocol=PICKLE_PROTOCOL))
        return f"kept the existing save, every stand ({len(ids)}) maxed and shiny"

    doc = create_user(ADMIN_UID)
    doc.update(fragments=1_000_000, super_fragments=500, xp=250_000,
               items=[{"id": 2}] * 5 + [{"id": 1}, {"id": 5}, {"id": 6}], **collection)
    r().hset("users", ADMIN_UID, pickle.dumps(doc, protocol=PICKLE_PROTOCOL))
    return f"created a fresh save, every stand ({len(ids)}) maxed and shiny"


def main():
    parser = argparse.ArgumentParser(description="Run the site locally with an admin/admin account.")
    parser.add_argument("--redis", help="Redis URL to use instead of the in-memory fake")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5000)
    args = parser.parse_args()

    os.environ["SESSION_COOKIE_SECURE"] = "0"  # plain http on localhost
    os.environ.setdefault("SECRET_KEY", "dev-only-change-me")
    if args.redis:
        os.environ["REDIS_URL"] = args.redis
    else:
        use_fake_redis()

    from app import create_app
    app = create_app()
    app.config["DISCORD_ADMIN_IDS"] = app.config["DISCORD_ADMIN_IDS"] | {ADMIN_UID}
    with app.app_context():
        status = seed_admin()

    where = args.redis or "in-memory Redis (wiped when you stop the server)"
    print(f"\n  STFU Requiem dev server on {where}")
    print(f"  Admin login: {ADMIN_USERNAME} / {ADMIN_PASSWORD} ({status})")
    print(f"  http://{args.host}:{args.port}/auth/login   |   admin panel: /admin\n")
    # No reloader: it would start a second process with its own empty fake Redis.
    app.run(host=args.host, port=args.port, debug=True, use_reloader=False)


if __name__ == "__main__":
    main()
