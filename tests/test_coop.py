"""Co-op raid: the lobby (create, join by code, pick, start), who picks for which stand, the turn clock, per-player
rewards with the daily cap, and the history line every player gets."""
import time

import app.db as dbmod
from app.game import coop
from app.game.user import create_user
from test_app import char, client, doc, login, put  # noqa: F401  (client is a fixture)


def _players(c, n=2):
    uids = [str(111 + i) for i in range(n)]
    for i, uid in enumerate(uids):
        d = create_user(uid)
        d["main_characters"] = [char(1 + i, xp=9000, awaken=3)]
        put(c, d)
    return uids


def _as(c, uid, name=None):
    return login(c, uid, name or f"P{uid}")


def _lobby_with_party(c, uids, tier="normal"):
    h = _as(c, uids[0])
    c.post("/coop/create", data={"tier": tier}, headers=h)
    code = coop.lobby_of(uids[0])["code"]
    for uid in uids[1:]:
        c.post("/coop/join", data={"code": code.lower()}, headers=_as(c, uid))
    for uid in uids:
        h = _as(c, uid)
        c.post("/coop/pick", data={"uuid": doc(c, uid)["main_characters"][0]["uuid"]}, headers=h)
    return code


def test_lobby_flow_and_start(client):
    uids = _players(client, 3)
    code = _lobby_with_party(client, uids)
    lb = coop.lobby(code)
    assert [m["uid"] for m in lb["members"]] == uids and all(m["stand"] for m in lb["members"])
    page = client.get("/coop", headers=_as(client, uids[1])).data.decode()
    assert code in page and "Waiting for the host" in page
    # only the host starts
    client.post("/coop/start", headers=_as(client, uids[1]))
    assert dbmod.load_fight(uids[0]) is None
    client.post("/coop/start", headers=_as(client, uids[0]))
    fights = [dbmod.load_fight(u) for u in uids]
    assert all(f and f.kind == "coop" for f in fights) and len({f.id for f in fights}) == 1
    f = fights[0]
    assert len(f.sides[0].chars) == 3 and len(f.sides[1].chars) == 3 and f.meta["owners"] == uids
    assert f.sides[1].chars[0].start_hp > f.sides[1].chars[1].start_hp  # the boss leads with far more health
    assert coop.lobby(code) is None and coop.lobby_of(uids[0]) is None
    # the poll sends everyone into the fight
    assert client.get("/coop/lobby", headers=_as(client, uids[2])).headers.get("HX-Redirect") == "/coop"


def test_each_player_picks_only_for_their_own_stand(client):
    uids = _players(client, 2)
    _lobby_with_party(client, uids)
    client.post("/coop/start", headers=_as(client, uids[0]))
    f = dbmod.load_fight(uids[0])
    who = coop.owner(f)
    other = next(u for u in uids if u != who)
    before = len(f.log)
    page = client.post("/coop/attack", data={"target": 0}, headers=_as(client, other)).data.decode()
    assert len(dbmod.load_fight(uids[0]).log) == before  # not their stand: nothing happens
    assert "Waiting for" in page
    client.post("/coop/attack", data={"target": 0}, headers=_as(client, who))
    after = dbmod.load_fight(uids[1])
    assert len(after.log) > before and after.id == f.id  # every player's copy moved on


def test_the_clock_picks_for_an_afk_player(client):
    uids = _players(client, 2)
    _lobby_with_party(client, uids)
    client.post("/coop/start", headers=_as(client, uids[0]))
    f = dbmod.load_fight(uids[0])
    f.meta["deadline"] = time.time() - 1
    dbmod.save_fight(uids[0], f)
    dbmod.save_fight(uids[1], f)
    client.post("/coop/attack", headers=_as(client, uids[1]))
    f2 = dbmod.load_fight(uids[0])
    assert any("took too long" in e["text"] for e in f2.log)


def test_a_win_pays_each_player_with_a_daily_cap(client):
    uids = _players(client, 2)
    _lobby_with_party(client, uids)
    client.post("/coop/start", headers=_as(client, uids[0]))
    f = dbmod.load_fight(uids[0])
    for c in f.sides[1].chars:
        c.current_hp = 0
    for u in uids:
        dbmod.save_fight(u, f)
    d = doc(client, uids[1])
    d["web_coop"] = {"day": coop.now().date().isoformat(), "wins": coop.DAILY_WINS}  # already capped today
    put(client, d)
    who = coop.owner(f)
    page = client.post("/coop/attack", data={"target": 0}, headers=_as(client, who)).data.decode()
    if who != uids[0]:
        page = client.post("/coop/attack", headers=_as(client, uids[0])).data.decode()
    assert "Victory" in page and "XP for your stand" in page
    f = dbmod.load_fight(uids[0])
    assert f.meta["rewards"][uids[0]]["fragments"] > 0 and f.meta["rewards"][uids[1]]["capped"]
    assert "today's rewarded raid wins" in client.post("/coop/attack", headers=_as(client, uids[1])).data.decode()
    stand = doc(client, uids[0])["main_characters"][0]
    assert stand["xp"] > 9000
    import json
    for u in uids:  # both players have the raid in their history
        assert any(json.loads(x)["kind"] == "coop" for x in dbmod.r().lrange(f"web:battles:{u}", 0, -1))
    client.post("/coop/fight/leave", headers=_as(client, uids[0]))
    assert dbmod.load_fight(uids[0]) is None and dbmod.load_fight(uids[1]) is not None


def test_host_leaving_closes_the_lobby_and_invites_notify(client):
    uids = _players(client, 2)
    from app import social
    social._link(uids[0], uids[1])
    h = _as(client, uids[0])
    client.post("/coop/create", data={"tier": "hard"}, headers=h)
    code = coop.lobby_of(uids[0])["code"]
    client.post("/coop/invite", data={"friend": uids[1]}, headers=h)
    feed = social.feed(uids[1])
    assert feed and code in feed[0]["text"] and feed[0]["kind"] == "coop"
    assert code in client.get(f"/coop?join={code}", headers=_as(client, uids[1])).data.decode()
    client.post("/coop/join", data={"code": code}, headers=_as(client, uids[1]))
    client.post("/coop/leave", headers=_as(client, uids[0]))
    assert coop.lobby(code) is None and coop.lobby_of(uids[1]) is None
    assert "This lobby has closed" in client.get("/coop/lobby", headers=_as(client, uids[1])).data.decode()
