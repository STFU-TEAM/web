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
    assert client.get("/").status_code == 200
    r = client.get("/stands?q=star&rarity=SSR", headers={"HX-Request": "true"})
    assert r.status_code == 200 and b"Star platinum" in r.data
    assert client.get("/stands/1").status_code == 200
    assert client.get("/stands/999").status_code == 404
    assert client.get("/leaderboard").status_code == 200


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
