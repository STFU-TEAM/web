"""Heaven's Gate: the campaign past Requiem · Over Heaven (app/game/heaven.py) and its fight gimmicks."""
import time

from app.game import heaven
from app.game.fight import Fight, Side
from app.game.logic import GameError
from app.game.user import User, create_user
from test_app import char, client, doc, login, put  # noqa: F401  (client is a fixture)
from test_features import player
from app.game.character import character_from_dict


def _team(ids=(1, 2, 5), xp=10000, awaken=5):
    return [character_from_dict(char(i, xp=xp, awaken=awaken)) for i in ids]


def _fight(rules, me=None, foe=None):
    return Fight(Side("You", me or _team(), True), Side("Boss", foe or _team((10, 30, 14)), False),
                 kind="heaven", meta={"rules": rules})


def _play(f, rounds=30):
    from app.game.fight import ai_choice
    steps = 0
    while not f.finished and steps < 400:
        f.advance(ai_choice(f.sides[1].chars, f.acting_char) if f.awaiting_input else None)
        steps += 1


def test_time_stop_gives_the_enemy_a_second_turn_every_third_round():
    f = _fight({"time_stop": 3})
    _play(f)
    stops = [e for e in f.log if e.get("fx") == "timestop"]
    flows = [e for e in f.log if e.get("fx") == "timeflow"]
    assert stops and flows and len(stops) == len(flows)


def test_king_crimson_erases_your_turn():
    f = _fight({"erase": 2})
    _play(f)
    assert any(e.get("fx") == "erase" for e in f.log)


def test_epitaph_foretells_the_enemy_targets_and_fate_holds():
    f = _fight({"epitaph": True})
    while not f.finished and not f.awaiting_input:
        f.advance()
    fate = dict(f._fate)
    assert fate and all(0 <= t < 3 for t in fate.values())
    lines = heaven.banner(f)
    assert any("Epitaph" in b["text"] for b in lines)


def test_heavens_door_hides_health_until_read():
    f = _fight({"hidden_hp": 2})
    foe = f.sides[1].chars[0]
    assert heaven.hp_hidden(f, foe, 1, 0)
    foe._read = 2
    assert not heaven.hp_hidden(f, foe, 1, 0)
    assert not heaven.hp_hidden(f, f.sides[0].chars[0], 0, 0)  # your own stands are never hidden


def test_pacts_bless_and_curse():
    rules = heaven.merge({"heal_cut": 0.25}, "bulwark")
    assert rules["my_health"] == 0.2 and rules["heal_cut"] == 0.3  # the harsher heal cut wins
    plain = _fight({})
    blessed = _fight({"my_health": 0.2, "my_damage": 0.2, "my_charge": 1})
    assert blessed.sides[0].chars[0].start_hp > plain.sides[0].chars[0].start_hp
    assert blessed.sides[0].chars[0].special_meter >= 1
    assert len(set(heaven.pacts_for("1", 0, 0))) == 3 and heaven.pacts_for("1", 0, 0) == heaven.pacts_for("1", 0, 0)


def test_made_in_heaven_clock_shrinks_to_2s_and_a_missed_clock_wastes_the_attack(client):
    rules = heaven.FIGHTS[3]["rules"]
    assert heaven.accel_seconds(rules, 1) == 15 and heaven.accel_seconds(rules, 20) == 2
    f = _fight({"accel": [15, 2, 2]})
    while not f.finished and not f.awaiting_input:
        f.advance()
    assert 0 < heaven.clock(f) <= 15
    with client.application.test_request_context(method="POST", data={"target": "1"}):
        assert heaven.pick(f, 1) == 1 and not f.__dict__.get("_whiff")  # in time: your pick stands
    with client.application.test_request_context(method="POST", data={"target": "1", "timeout": "1"}):
        t = heaven.pick(f, 1)  # the page's clock hit 0
    hp = [c.current_hp for c in f.sides[1].chars]
    f.advance(t)
    miss = next(e for e in f.log if "Out of time" in e["text"])
    assert miss["kind"] == "dodge" and not f.__dict__.get("_whiff")
    f2 = _fight({"accel": [15, 2, 2]})
    while not f2.finished and not f2.awaiting_input:
        f2.advance()
    heaven.clock(f2)
    f2.meta["clock"]["until"] = time.time() - 5  # too late, even without the page saying so
    with client.application.test_request_context(method="POST", data={"target": "0"}):
        heaven.pick(f2, 0)
    assert f2._whiff


def test_the_campaign_opens_after_requiem_over_heaven_and_pays_first_clears(client):
    from app.game import overheaven
    p = player(client, "111", main_characters=[char(1, xp=10000, awaken=5), char(2, xp=10000, awaken=5), char(5, xp=10000, awaken=5)])
    h = login(client, "111")
    assert "The gate is sealed" in client.get("/heaven").data.decode()
    d = doc(client, "111")
    d.setdefault("web_over_heaven", {})[overheaven.REQUIEM_TRACK["key"]] = len(overheaven.REQUIEM_TRACK["fights"])
    put(client, d)
    page = client.get("/heaven").data.decode()
    assert "Stopped Time" in page and "Choose a pact" in page
    user = User(doc(client, "111"))
    offered = heaven.pacts_for(user.id, 0, 0)
    assert "Pick one of the three pacts" in client.post("/heaven/fight", data={"stage": 0, "pact": "nope"}, headers=h,
                                                         follow_redirects=True).data.decode()
    client.post("/heaven/fight", data={"stage": 0, "pact": offered[0]}, headers=h)
    page = client.get("/heaven").data.decode()
    assert 'kind-heaven' in page and 'hv-world' in page and "Time stops" in page
    with client.application.test_request_context():
        with pytest_raises(GameError):
            heaven.check_can_fight(user, 2)  # one stair at a time
    user = User(doc(client, "111"))
    before = user.super_fragments
    res = heaven.win(user, 0)
    assert res["fragments"] == heaven.REWARDS[0]["fragments"] and user.super_fragments == before + heaven.REWARDS[0]["super"]
    assert heaven.win(user, 0)["fragments"] == 2000  # a replay
    heaven.lost(user, 1)
    assert heaven.attempt(user, 1) == 1  # a loss draws new pacts


def pytest_raises(exc):
    import pytest
    return pytest.raises(exc)


def test_duels_carry_each_players_look_and_ranked_goes_gold(client):
    from app.game import profile as P
    player(client, "111", main_characters=[char(1)])
    u = User(doc(client, "111"))
    look = P.duel_look(u)
    assert len(look["colors"]) == 3 and look["stand"] == 1
