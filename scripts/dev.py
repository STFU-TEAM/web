"""Run the site locally for quick testing, with an admin account ready to log in.

    python scripts/dev.py                 # in-memory Redis (fakeredis), wiped on exit
    python scripts/dev.py --redis redis://localhost:6379/0   # a local Redis that persists
    python scripts/dev.py --port 5001
    python scripts/dev.py --demo          # a lived-in world for filming the promo (see seed_demo)

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


# --demo: a lived-in world for filming (promo/). The admin plays a believable save instead of every stand maxed and
# shiny, and there are other players on the ladder, a gang, auction listings, Looking-for requests and a global chat.
DEMO_NAME = "GoldenWind"
DEMO_TEAM = [120, 119, 1]  # D4C + Ticket to Ride (Love Train) and Star Platinum
DEMO_PLAYERS = [  # name, ranked elo, team, in the admin's gang
    ("ZaWarudo99", 2480, [110, 1, 13], False), ("Polnareff_Hair", 2210, [4, 49, 94], True),
    ("JolyneString", 2050, [84, 98, 94], False), ("SpeedwagonFDN", 1930, [1, 13, 59], False),
    ("Hamon_Caesar", 1820, [49, 4, 107], False), ("Narancia_Aero", 1710, [59, 61, 64], True),
    ("Rohan_Heaven", 1600, [40, 49, 94], False), ("Mista_No4", 1490, [62, 59, 61], True),
    ("Okuyasu_Hand", 1350, [37, 40, 13], True), ("Kakyoin_Cherry", 1220, [4, 13, 1], False),
    ("Bruno_Zipper", 1100, [61, 59, 62], True), ("Trish_Spice", 980, [66, 59, 61], True),
]
DEMO_CHAT = [  # (player index, minutes ago, text)
    (0, 52, "anyone else pulling on the Part 5 banner? 🔥"),
    (2, 47, "GOT GER LAST NIGHT 😭 1 in 500 baby"),
    (1, 40, "Love Train is busted in the Requiem Tower lol"),
    (5, 33, "gang raid at 21:00, bring your poison stands 🐍"),
    (6, 25, "today's puzzle took me 41s, beat that"),
    (7, 18, "who's that stand today was way too easy"),
    (9, 11, "LF Tusk Act 4, paying 15 arrowheads (it's in Looking for)"),
    (3, 6, "welcome to all the new stand users 👋"),
    (4, 2, "ゴゴゴゴゴ"),
]


def seed_demo():
    import random
    import secrets
    import time as _time

    from app.db import PICKLE_PROTOCOL, get_db, r, remember_identity
    from app.game import auction as A
    from app.game import gangs as G
    from app.game import progression
    from app.game import wanted as W
    from app.game.character import CHARACTER_FILE, get_character_from_template
    from app.game.logic import roll_types_qualities
    from app.game.user import create_user

    rng = random.Random(7)  # the same world on every start

    def stand(cid, level, awaken=0, shiny=False):
        types, quals = roll_types_qualities()
        doc = get_character_from_template(CHARACTER_FILE[cid - 1], types, quals).to_dict()
        doc.update(xp=level * 100, awaken=awaken, shiny=shiny)
        return doc

    # the admin: a good player, a few weeks in. No Gold Experience Requiem (84) yet, so a pull shows it NEW.
    account = json.loads(r().get(f"web:account:{ADMIN_USERNAME}"))
    account["name"] = DEMO_NAME
    r().set(f"web:account:{ADMIN_USERNAME}", json.dumps(account))
    remember_identity(ADMIN_UID, DEMO_NAME, None, ttl=None)
    playable = [c["id"] for c in CHARACTER_FILE if c["universe"] != "Dummy" and c["id"] not in (84, *DEMO_TEAM)]
    owned = rng.sample(playable, 64)
    team = [stand(120, 100, 4), stand(119, 100, 5), stand(1, 100, 3)]
    storage = [stand(cid, rng.choice([24, 38, 52, 67, 80, 100]), rng.choice([0, 0, 1, 2, 3]), shiny=(k in (5, 23)))
               for k, cid in enumerate(owned)]
    storage.append(stand(59, 100, 3))  # Gold Experience: it fills a Looking-for request below
    doc = create_user(ADMIN_UID)
    doc.update(fragments=284_000, super_fragments=12, xp=415_000, global_elo=1655, energy=99,
               items=[{"id": 2}] * 3 + [{"id": 3}] * 2 + [{"id": 1}, {"id": 4}, {"id": 5}, {"id": 6}, {"id": 47}],
               main_characters=team, storage_characters=storage,
               web_dex=sorted({c["id"] for c in team + storage}))
    doc.setdefault("web_story", {})["cleared"] = 13  # in the middle of Part 5
    for key in progression.DEBUG_KEYS:  # every mode open, for filming every minigame
        progression.set_forced(ADMIN_UID, key, True)

    # other players: the ranked ladder, a gang, the market and the chat
    gang_id = "demo-golden-wind"
    members = [ADMIN_UID]
    uids = []
    for k, (name, elo, ids, in_gang) in enumerate(DEMO_PLAYERS):
        uid = f"2000000000000001{k:02d}"
        uids.append(uid)
        p = create_user(uid)
        p.update(global_elo=elo, xp=rng.randint(120_000, 900_000), fragments=rng.randint(200_000, 2_000_000),
                 super_fragments=rng.randint(5, 60), main_characters=[stand(cid, 100, rng.randint(2, 5)) for cid in ids],
                 storage_characters=[stand(cid, rng.choice([40, 70, 100])) for cid in rng.sample(playable, 12)])
        if in_gang:
            p["gang_id"] = gang_id
            members.append(uid)
        r().hset("users", uid, pickle.dumps(p, protocol=PICKLE_PROTOCOL))
        remember_identity(uid, name, None, ttl=None)
    doc["gang_id"] = gang_id
    r().hset("users", ADMIN_UID, pickle.dumps(doc, protocol=PICKLE_PROTOCOL))

    gang = G.new_gang(gang_id, ADMIN_UID, "Golden Wind", "Ari ari ari!", "Raid at 21:00: bring your poison stands 🐍")
    gang.update(users=members, vault=125_000, raid_level=4, war_elo=1450)
    for uid in members[1:]:
        gang["ranks"][uid] = G.SOLDIER
    gang["ranks"][members[1]] = G.CAPO
    get_db().create_gang(gang)

    now = int(_time.time())
    listings = [  # seller index, stand, level, price (dust, heads) or a bid auction
        (1, 4, 80, (45_000, 0), None), (2, 98, 100, (120_000, 0), None), (0, 13, 90, (300_000, 2), None),
        (6, 40, 100, None, ("dust", 20_000, 34_000, 7)), (4, 94, 70, None, ("heads", 5, 8, 11)),
        (8, 37, 60, (18_000, 0), None),
    ]
    for seller, cid, level, price, bid in listings:
        lid = secrets.token_urlsafe(8)
        listing = {"id": lid, "seller": uids[seller], "stand": stand(cid, level, rng.randint(0, 3)), "at": now - rng.randint(600, 40_000)}
        if bid:
            currency, start, top, bidder = bid
            listing.update(mode="bid", currency=currency, start=start, bid=top, bidder=uids[bidder], bids=rng.randint(2, 6),
                           dust=0, heads=0, ends=now + rng.randint(3, 20) * 3600)
        else:
            listing.update(mode="fixed", dust=price[0], heads=price[1], ends=now + rng.randint(2, 6) * 86400)
        r().hset(A.KEY, lid, json.dumps(listing))
        r().sadd(f"web:auction:seller:{uids[seller]}", lid)
    wanted = [(3, 109, 50, 0, 600_000, 0), (9, 114, 0, 0, 0, 15), (11, 59, 60, 0, 80_000, 0), (5, 62, 0, 2, 25_000, 0)]
    for buyer, cid, level, stars, dust, heads in wanted:
        pid = secrets.token_urlsafe(8)
        post = {"id": pid, "buyer": uids[buyer], "stand": cid, "level": level, "stars": stars, "dust": dust, "heads": heads,
                "at": now - rng.randint(600, 30_000), "ends": now + rng.randint(3, 6) * 86400}
        r().hset(W.KEY, pid, json.dumps(post))
        r().sadd(f"web:auction:wanted:buyer:{uids[buyer]}", pid)

    for k, (who, ago, text) in enumerate(DEMO_CHAT, start=1):
        r().rpush("web:chat:global", json.dumps({"id": k, "uid": uids[who], "text": text, "at": now - ago * 60}))
    r().set("web:chat:seq:global", len(DEMO_CHAT))

    try:  # today's daily puzzle (the worker builds them in production; ~10 s)
        from app.game import puzzle
        puzzle.generate_one()
    except Exception as e:  # the rest of the world is still there
        print("  (no daily puzzle:", e, ")")
    return f"demo world: {DEMO_NAME}, {len(DEMO_PLAYERS)} other players, a gang, {len(listings)} listings, chat"


def main():
    parser = argparse.ArgumentParser(description="Run the site locally with an admin/admin account.")
    parser.add_argument("--redis", help="Redis URL to use instead of the in-memory fake")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5000)
    parser.add_argument("--demo", action="store_true", help="a lived-in world for filming (promo/)")
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
        if args.demo:
            status = seed_demo()

    where = args.redis or "in-memory Redis (wiped when you stop the server)"
    print(f"\n  STFU Requiem dev server on {where}")
    print(f"  Admin login: {ADMIN_USERNAME} / {ADMIN_PASSWORD} ({status})")
    print(f"  http://{args.host}:{args.port}/auth/login   |   admin panel: /admin\n")
    # No reloader: it would start a second process with its own empty fake Redis.
    app.run(host=args.host, port=args.port, debug=True, use_reloader=False)


if __name__ == "__main__":
    main()
