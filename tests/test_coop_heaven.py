"""Co-op Over Heaven: the difficulty opens with the story's end, its crew fights under this week's Over Heaven rule,
and the first Over Heaven win of the week pays a bonus once."""
from markupsafe import escape

import app.db as dbmod
from app.game import coop, story
from test_app import client, doc, put  # noqa: F401  (client is a fixture)
from test_coop import _as, _lobby_with_party, _players


def _finish_story(c, uids):
    for uid in uids:
        d = doc(c, uid)
        d["web_story"] = {"cleared": story.TOTAL}
        put(c, d)


def test_heaven_opens_with_the_story_and_every_player_needs_it(client):
    uids = _players(client, 2)
    h = _as(client, uids[0])
    assert "finish the story" in client.get("/coop", headers=h).data.decode()
    client.post("/coop/create", data={"tier": coop.HEAVEN}, headers=h)
    assert coop.lobby_of(uids[0]) is None  # refused

    _finish_story(client, uids[:1])
    client.post("/coop/create", data={"tier": coop.HEAVEN}, headers=h)
    code = coop.lobby_of(uids[0])["code"]
    client.post("/coop/join", data={"code": code}, headers=_as(client, uids[1]))
    assert len(coop.lobby(code)["members"]) == 1  # the second player hasn't finished the story

    client.post("/coop/tier", data={"tier": "normal"}, headers=_as(client, uids[0]))
    client.post("/coop/join", data={"code": code}, headers=_as(client, uids[1]))
    assert len(coop.lobby(code)["members"]) == 2
    client.post("/coop/tier", data={"tier": coop.HEAVEN}, headers=_as(client, uids[0]))
    for uid in uids:
        client.post("/coop/pick", data={"uuid": doc(client, uid)["main_characters"][0]["uuid"]}, headers=_as(client, uid))
    client.post("/coop/start", headers=_as(client, uids[0]))
    assert dbmod.load_fight(uids[0]) is None  # still refused at the start


def test_the_crew_fights_under_this_weeks_rule(client):
    uids = _players(client, 2)
    _finish_story(client, uids)
    _lobby_with_party(client, uids, tier=coop.HEAVEN)
    page = client.get("/coop", headers=_as(client, uids[0])).data.decode()
    ch = coop.challenge()
    assert str(escape(ch["title"])) in page and str(escape(ch["lines"][0])) in page
    client.post("/coop/start", headers=_as(client, uids[0]))
    f = dbmod.load_fight(uids[0])
    assert f.meta["rules"] == ch["rules"] and f.rules == ch["rules"]
    assert ch["title"] in f.sides[1].name
    lead = f.sides[1].chars[0]
    assert lead.level == 100 and lead.awaken == 5


def test_every_week_has_a_rule_and_the_part_follows_the_boss():
    for n in range(1, 53):
        week = f"2026-W{n:02d}"
        ch = coop.challenge(week)
        assert ch["lines"] and ch["power"] < 1.5
        if "part_ward" in ch["rules"]:
            assert ch["rules"]["part_ward"][0] == story.STAGES[coop.boss_stage(week)]["part"]
            assert f"Part {ch['part']}" in ch["hint"]
    assert len({coop.challenge(f"2026-W{n:02d}")["key"] for n in range(1, 53)}) == len(coop.CHALLENGES)


def test_the_weekly_bonus_pays_once(client):
    uids = _players(client, 2)
    _finish_story(client, uids)
    for _ in range(2):
        _lobby_with_party(client, uids, tier=coop.HEAVEN)
        client.post("/coop/start", headers=_as(client, uids[0]))
        f = dbmod.load_fight(uids[0])
        with client.application.app_context():
            users = {u: dbmod.get_db().get_user(u) for u in uids}
            f.winner = 0
            rewards = coop.settle(f, users)
            for u in users.values():
                u.data["web_coop"]["used"] = []  # let the same stands raid again for the test
                u.update()
        for u in uids:
            dbmod.clear_fight(u)
        if _ == 0:
            first = rewards
    assert "Over Heaven bonus" in first[uids[0]]["item"] and "Over Heaven bonus" not in (rewards[uids[0]]["item"] or "")
    d = doc(client, uids[0])
    assert d["super_fragments"] >= coop.HEAVEN_WEEKLY["super"] and d["web_coop"]["heaven_week"] == coop.week_key()
