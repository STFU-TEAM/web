"""End-to-end tests against an in-memory Redis laid out like the bot's.
Run: pip install pytest fakeredis && pytest -q"""
import datetime
import pickle

import fakeredis
import pytest

import app.db as dbmod
from app.game.character import CHARACTER_FILE, get_character_from_template
from app.game.user import create_user


@pytest.fixture()
def client(monkeypatch):
    fake = fakeredis.FakeRedis()
    monkeypatch.setattr(dbmod.redis.Redis, "from_url", staticmethod(lambda *a, **k: fake))
    from app import create_app
    app = create_app()
    app.config.update(TESTING=True, SESSION_COOKIE_SECURE=False)
    c = app.test_client()
    c.fake = fake
    return c


def login(c, uid="111", name="Jotaro"):
    with c.session_transaction() as s:
        s["uid"], s["name"], s["avatar"], s["csrf"] = uid, name, None, "tok"
    return {"X-CSRF-Token": "tok"}


def doc(c, uid):
    return pickle.loads(c.fake.hget("users", uid))


def put(c, d, field=None):
    c.fake.hset("users", field or d["_id"], pickle.dumps(d))


def char(cid, xp=0, awaken=0, items=None, types=("ATTACK",), quals=("GOOD",)):
    ch = get_character_from_template(CHARACTER_FILE[cid - 1], list(types), list(quals))
    d = ch.to_dict()
    d.update(xp=xp, awaken=awaken, items=items or [])
    return d


def test_public_pages(client):
    home = client.get("/")
    assert home.status_code == 200 and b"randomAsset/avatar.png" in home.data
    r = client.get("/stands?q=star&rarity=SSR", headers={"HX-Request": "true"})
    assert r.status_code == 200 and b"Star platinum" in r.data
    assert client.get("/stands/1").status_code == 200
    assert client.get("/stands/999").status_code == 404
    assert client.get("/leaderboard").status_code == 200


def test_admin_panel_mirrors_bot_permissions_and_audits_grants(client):
    assert "242367586233352193" in client.application.config["DISCORD_ADMIN_IDS"]
    client.application.config["DISCORD_ADMIN_IDS"] = {"111"}
    put(client, create_user("111"))
    put(client, create_user("222"))
    headers = login(client, "111")

    response = client.get("/admin?user_id=222")
    assert response.status_code == 200 and b"Admin panel" in response.data
    assert b"Grant resources" in response.data
    response = client.post("/admin/grant", data={"user_id": "222", "kind": "fragments", "amount": "500"}, headers=headers)
    assert response.status_code == 302
    assert doc(client, "222")["fragments"] == 500
    audit = client.fake.lrange("web:admin:audit", 0, -1)
    assert len(audit) == 1 and b'"actor": "111"' in audit[0]

    response = client.post("/admin/grant", data={"user_id": "222", "kind": "item", "item_id": "1", "amount": "2"}, headers=headers)
    assert response.status_code == 302
    assert doc(client, "222")["items"] == [{"id": 1}, {"id": 1}]
    response = client.post("/admin/grant", data={"user_id": "222", "kind": "fragments", "amount": "1000001"}, headers=headers)
    assert response.status_code == 302 and doc(client, "222")["fragments"] == 500

    with client.session_transaction() as session:
        session["uid"] = "222"
    assert client.get("/admin").status_code == 403


def test_gang_and_shop_documents_use_bot_redis_hashes(client):
    gang = {"_id": "gang-1", "name": "Stardust", "users": ["111"], "ranks": {"111": 0}}
    shop = {"_id": "shop-1", "owner": "111", "name": "Joestar Market", "items": [{"id": 1}], "prices": [250]}
    db = dbmod.Database()

    db.create_gang(gang)
    db.create_shop(shop)

    assert db.get_gang("gang-1") == gang
    assert db.get_shop("shop-1") == shop
    assert list(db.all_gangs()) == [gang]
    assert list(db.all_shops()) == [shop]

    gang["war_elo"] = 10
    db.update_gang(gang)
    assert db.get_gang("gang-1")["war_elo"] == 10
    db.delete_gang("gang-1")
    assert db.get_gang("gang-1") is None


def test_gang_invite_and_join_flow(client):
    leader = create_user("111")
    leader["fragments"] = 20000
    put(client, leader)
    member = create_user("222")
    put(client, member)
    headers = login(client, "111")

    response = client.post("/gangs/create", data={"name": "Stardust", "motto": "Yare yare", "motd": "Welcome"}, headers=headers)
    assert response.status_code == 302
    gang_id = doc(client, "111")["gang_id"]
    assert doc(client, "111")["fragments"] == 10000
    assert client.get("/gangs").status_code == 200

    response = client.post("/gangs/invite", data={"user_id": "222"}, headers=headers)
    assert response.status_code == 302
    assert gang_id in doc(client, "222")["gang_invites"]

    with client.session_transaction() as session:
        session["uid"], session["name"] = "222", "Jotaro"
    response = client.post(f"/gangs/join/{gang_id}", headers=headers)
    assert response.status_code == 302
    assert doc(client, "222")["gang_id"] == gang_id
    assert set(map(str, dbmod.Database().get_gang(gang_id)["users"])) == {"111", "222"}


def test_player_shop_listing_and_purchase(client):
    owner = create_user("111")
    owner["fragments"] = 5000
    owner["items"] = [{"id": 1}]
    put(client, owner)
    buyer = create_user("222")
    buyer["fragments"] = 1000
    put(client, buyer)
    headers = login(client, "111")

    response = client.post("/shops/create", data={"name": "Joestar Market", "description": "Good finds"}, headers=headers)
    assert response.status_code == 302
    shop_id = doc(client, "111")["shop_id"]
    assert doc(client, "111")["fragments"] == 2000
    assert b"Joestar Market" in client.get("/shops").data

    client.post(f"/shops/{shop_id}/list", data={"item": "1", "price": "750"}, headers=headers)
    assert doc(client, "111")["items"] == []
    assert client.get(f"/shops/{shop_id}").status_code == 200

    with client.session_transaction() as session:
        session["uid"], session["name"] = "222", "Jotaro"
    response = client.post(f"/shops/{shop_id}/buy/0", headers=headers)
    assert response.status_code == 302
    assert doc(client, "222")["fragments"] == 250
    assert doc(client, "222")["items"] == [{"id": 1}]
    assert doc(client, "111")["fragments"] == 2750


def test_tower_entry_and_bot_invite(client):
    user = create_user("111")
    user["fragments"] = 1200
    user["main_characters"] = [char(1, xp=10000)]
    put(client, user)
    headers = login(client, "111")

    assert client.get("/tower").status_code == 200
    response = client.post("/tower/start", headers=headers)
    assert response.status_code == 302
    fight = dbmod.load_fight("111")
    assert fight.kind == "tower" and len(fight.sides[1].chars) == 3
    assert doc(client, "111")["fragments"] == 700
    assert b"Your tower fight is active" in client.get("/wormhole").data
    response = client.post("/wormhole/attack", data={"target": "0"}, headers=headers)
    assert response.status_code == 409
    assert dbmod.load_fight("111").turn == fight.turn
    assert b"/randomAsset/avatar.png" in client.get("/stands/31").data

    client.application.config["DISCORD_CLIENT_ID"] = "123456"
    response = client.get("/auth/bot")
    assert response.status_code == 302
    assert "scope=bot+applications.commands" in response.headers["Location"]


def test_tower_victory_unlocks_next_floor(client):
    user = create_user("111")
    user["fragments"] = 1000
    user["main_characters"] = [char(1, xp=1000000, awaken=3, quals=("UNIVERSAL",)),
                               char(10, xp=1000000, awaken=3, quals=("UNIVERSAL",)),
                               char(31, xp=1000000, awaken=3, quals=("UNIVERSAL",))]
    put(client, user)
    headers = login(client, "111")
    client.post("/tower/start", headers=headers)

    for _ in range(200):
        fight = dbmod.load_fight("111")
        if fight.finished:
            break
        assert fight.awaiting_input
        response = client.post("/tower/attack", data={"target": fight.targets()[0], "log_len": len(fight.log)}, headers=headers)
        assert response.status_code == 200

    fight = dbmod.load_fight("111")
    assert fight.finished and fight.winner == 0
    saved = doc(client, "111")
    assert saved["web_tower_floor"] == 1
    assert saved["web_tower_active"] is True
    assert saved["fragments"] > 500


def test_begin_pull_and_team(client):
    h = login(client)
    assert client.get("/team").headers["Location"].endswith("/auth/welcome")
    r = client.post("/auth/welcome", headers=h)
    assert r.headers["Location"].startswith("/banners")
    d = doc(client, "111")
    assert d["super_fragements"] == 1 and d["main_characters"] == []

    assert client.get("/banners").status_code == 200
    r = client.post("/banners/0/pull", headers=h)
    assert r.status_code == 200 and b"10 stands" in r.data, r.data[:500]
    assert b"randomAsset/avatar.png" in r.data
    assert b"media.tenor.com" not in r.data
    assert b"/opening/" in r.data
    d = doc(client, "111")
    assert d["super_fragements"] == 0 and d["pity"] == 10 and len(d["character_storage_1"]) == 10
    # second pull refused
    assert b"costs 1 super fragment" in client.post("/banners/0/pull", headers=h).data

    # move 3 into the team, swap a 4th in
    ids = [c["uuid"] for c in d["character_storage_1"]]
    for u in ids[:3]:
        assert b"joined your team" in client.post("/team/main", data={"uuid": u}, headers=h).data
    r = client.post("/team/main", data={"uuid": ids[3], "swap": ids[0]}, headers=h)
    assert b"joined your team" in r.data
    d = doc(client, "111")
    assert [c["uuid"] for c in d["main_characters"]] == ids[1:4]

    # preset save / load
    assert b"saved" in client.post("/team/preset/save", data={"name": "Main"}, headers=h).data
    client.post("/team/store", data={"uuid": ids[1]}, headers=h)
    assert len(doc(client, "111")["main_characters"]) == 2
    assert b"loaded" in client.post("/team/preset/load", data={"name": "main"}, headers=h).data
    assert [c["uuid"] for c in doc(client, "111")["main_characters"]] == ids[1:4]

    # release
    assert b"was released" in client.post("/team/release", data={"uuid": ids[5]}, headers=h).data
    assert client.get("/team").status_code == 200
    assert client.get("/team/collection?shelf=s1").status_code == 200
    # daily + cooldown
    assert b"Claimed" in client.post("/daily", headers=h).data
    assert b"back in" in client.post("/daily", headers=h).data.lower()
    # quests page assigns quests and daily_claim progressed
    assert client.get("/quests").status_code == 200
    assert doc(client, "111")["quests"]["active_daily"]
    # csrf
    assert client.post("/daily").status_code == 400


def test_wormhole_fight(client):
    h = login(client, "222", "Dio")
    d = create_user("222")
    d["main_characters"] = [char(1, xp=5000), char(10, xp=5000), char(59, xp=5000)]
    put(client, d)
    assert client.post("/wormhole/start", headers=h).status_code == 302
    assert client.get("/wormhole").status_code == 200
    fight = dbmod.load_fight("222")
    for _ in range(400):
        fight = dbmod.load_fight("222")
        if fight.finished:
            break
        r = client.post("/wormhole/attack", data={"target": fight.targets()[0], "log_len": len(fight.log)}, headers=h)
        assert r.status_code == 200
    assert fight.finished and fight.rewards is not None
    d = doc(client, "222")
    assert d["energy"] == 9
    assert d["achievement_data"]["counters"].get("wormhole_complete") == 1
    client.post("/wormhole/leave", headers=h)
    r = client.post("/wormhole/start", headers=h)
    assert b"next wormhole opens" in r.data


def test_legacy_bytes_key_user_items_shop(client):
    """A very old player stored under b'<id>' with fields missing, like the bot's data."""
    d = create_user("b'333'")
    for k in ("achievement_data", "quests", "story_progress", "teams"):
        d.pop(k)
    d["main_characters"] = [char(6, xp=100 * 100, awaken=2)]  # Silver Chariot lvl 100 awaken 2 -> requiem
    d["character_storage_1"] = [char(1), char(1, types=("LUCK",))]
    d["items"] = [{"id": 3}, {"id": 13}, {"id": 4}, {"id": 34}, {"id": 35}, {"id": 36}]
    d["fragments"] = 20000
    d["last_full_energy"] = datetime.datetime.min
    put(client, d)
    h = login(client, "333")
    assert client.get("/team").status_code == 200
    assert b"The bag held" in client.post("/items/use", data={"item": 13}, headers=h).data
    after = doc(client, "b'333'")                      # written back under the bot's field
    assert after["fragments"] > 20000 and not client.fake.hexists("users", "333")
    assert b"equipped" in client.post("/team/equip", data={"uuid": after["main_characters"][0]["uuid"], "item": 4}, headers=h).data
    r = client.post("/items/use", data={"item": 3, "uuid": after["main_characters"][0]["uuid"]}, headers=h)
    assert b"Requiem" in r.data
    assert doc(client, "b'333'")["main_characters"][0]["id"] == 83  # Chariot Requiem
    assert b"You crafted Holy Corpse" in client.post("/items/craft", data={"recipe": "Holy Corpse"}, headers=h).data
    assert b"You bought Super Fragment" in client.post("/shop/buy", data={"key": "super_fragment"}, headers=h).data
    # fuse the two Star Platinum copies
    s1 = doc(client, "b'333'")["character_storage_1"]
    r = client.post("/team/fuse", data={"uuid": s1[0]["uuid"], "fodder": s1[1]["uuid"]}, headers=h)
    assert b"Fused" in r.data
    s1 = doc(client, "b'333'")["character_storage_1"]
    assert len(s1) == 1 and s1[0]["awaken"] == 1
    # reforge costs 10000
    frag = doc(client, "b'333'")["fragments"]
    uid0 = doc(client, "b'333'")["main_characters"][0]["uuid"]
    assert b"reforged" in client.post("/team/reforge", data={"uuid": uid0}, headers=h).data
    assert doc(client, "b'333'")["fragments"] == frag - 10000
    # energy refilled on page load (last_full_energy was long ago)
    client.get("/wormhole")
    assert doc(client, "b'333'")["energy"] == 10
    assert client.get("/u/333").status_code == 200
    assert client.get("/leaderboard?by=xp").status_code == 200
