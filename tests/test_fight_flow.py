"""Crits past 100%, the Continue button on finished fights, "Simulate this fight" after a PvE loss,
and the harder tower and twelve-boss rush."""
import app.db as dbmod
from app.game.character import CHARACTER_FILE, get_character_from_template
from app.game.user import create_user
from test_app import char, client, login, put  # noqa: F401  (client is a fixture)


def _stand(cid=1):
    return get_character_from_template(CHARACTER_FILE[cid - 1], ["ATTACK"], ["GOOD"])


def _player(c, uid="111", **fields):
    d = create_user(uid)
    d.update(fields)
    put(c, d)
    return login(c, uid)


# --------------------------------------------------------------------------- #
# Crits
# --------------------------------------------------------------------------- #
def test_crit_chance_past_100_stacks_crits(monkeypatch):
    from app.game import character
    monkeypatch.setattr(character.random, "random", lambda: 0.49)
    assert character.crit_tier(0) == 0 and character.crit_tier(49) == 0 and character.crit_tier(50) == 1
    assert character.crit_tier(150) == 2 and character.crit_tier(250) == 3 and character.crit_tier(320) == 3
    monkeypatch.setattr(character.random, "random", lambda: 0.99)
    assert character.crit_tier(150) == 1 and character.crit_tier(100) == 1


def test_each_extra_crit_adds_the_crit_bonus_again(monkeypatch):
    from app.game import character
    monkeypatch.setattr(character.random, "random", lambda: 0.99)
    monkeypatch.setattr(character.random, "randint", lambda a, b: b)  # never dodges
    hits = {}
    for chance in (0, 100, 200, 300):
        attacker, target = _stand(1), _stand(2)
        attacker.current_speed = target.current_speed = 10
        attacker.current_critical = chance
        hits[chance] = attacker.attack(target)
    assert [hits[c]["crit"] for c in (0, 100, 200, 300)] == [0, 1, 2, 3]
    m = _stand(1).crit_multiplier
    base = hits[0]["damage"]
    for tier, chance in ((1, 100), (2, 200), (3, 300)):
        assert abs(hits[chance]["damage"] - base * (1 + (m - 1) * tier)) <= 1


def test_fight_log_records_the_crit_tier(monkeypatch):
    from app.game import character
    from app.game.fight import Fight, Side
    monkeypatch.setattr(character.random, "random", lambda: 0.0)
    me, foe = _stand(1), _stand(2)
    me.current_critical = 250
    fight = Fight(Side("Me", [me], True), Side("Foe", [foe], False), kind="dummy")
    for _ in range(30):
        if fight.finished:
            break
        fight.advance(0)
    mine = [e for e in fight.log if e["kind"] == "crit" and e["src"] and e["src"][0] == 0]
    assert mine and all(e["crit"] == 3 for e in mine) and "TRIPLE critical strike" in mine[0]["text"]


# --------------------------------------------------------------------------- #
# Continue and simulate
# --------------------------------------------------------------------------- #
def test_story_loss_offers_retry_and_a_simulation(client):
    h = _player(client, main_characters=[char(1, xp=500)])
    client.post("/story/fight", headers=h)
    page = client.post("/story/attack", data={"forfeit": "1"}, headers=h).data.decode()
    assert "Try again" in page and "Simulate this fight" in page and 'id="fight-next"' in page
    fight = dbmod.load_fight("111")
    assert fight.start_teams and len(fight.start_teams[0]) == 1
    sim = client.post("/battles/simulator/rematch", headers=h).data.decode()
    assert "win rate" in sim and "Your team" in sim
    # "Try again" posts straight to the start endpoint, which replaces the finished fight
    client.post("/story/fight", data={"stage": 0}, headers=h)
    again = dbmod.load_fight("111")
    assert again.kind == "story" and again.id != fight.id and not again.finished


def test_wins_offer_the_next_fight(client):
    from app.game import rush
    h = _player(client, main_characters=[char(1, xp=9000), char(2, xp=9000), char(3, xp=9000)])
    client.post("/rush/fight", headers=h)
    fight = dbmod.load_fight("111")
    for c in fight.sides[1].chars:
        c.current_hp = 0
    dbmod.save_fight("111", fight)
    page = client.post("/rush/attack", headers=h).data.decode()
    assert f"Next boss (2/{len(rush.BOSSES)})" in page and "Simulate this fight" not in page
    client.post("/rush/fight", headers=h)
    nxt = dbmod.load_fight("111")
    assert nxt.kind == "rush" and nxt.meta["index"] == 1 and not nxt.finished


def test_practice_again_and_simulation_is_pve_only(client):
    h = _player(client, main_characters=[char(1, xp=500)])
    client.post("/battles/dummy/start", headers=h)
    first = dbmod.load_fight("111")
    assert first.start_teams is None  # practice isn't simulated
    page = client.post("/battles/attack", data={"forfeit": "1"}, headers=h).data.decode()
    assert "Practice again" in page and "Simulate this fight" not in page
    client.post("/battles/dummy/start", headers=h)
    assert dbmod.load_fight("111").id != first.id
    assert "can't be simulated" in client.post("/battles/simulator/rematch", headers=h).data.decode()


def test_replays_leave_the_simulation_snapshot_out(client):
    import pickle
    import zlib
    from app.game import history
    from app.game.fight import Fight, Side
    fight = Fight(Side("Me", [_stand(1)], True), Side("Foe", [_stand(2)], False), kind="story")
    fight.forfeit()
    history.record(client.fake, fight, "111")
    kept = pickle.loads(zlib.decompress(client.fake.get(f"web:replay:{fight.id}")))
    assert kept.start_teams is None and fight.start_teams


# --------------------------------------------------------------------------- #
# Harder tower and boss rush
# --------------------------------------------------------------------------- #
def test_tower_climbs_faster_but_the_dungeon_keeps_its_curve():
    from app.game import tower
    assert tower.level_for(27) == 100 and tower.awaken_for(42) == 5
    hard = tower.floor_team(30, ids=[5])[0]
    delve = tower.floor_team(30, ids=[5], climb=False)[0]
    assert delve.level == round(1 + 30 ** 1.25) and hard.level == 100 and hard.start_hp > delve.start_hp
    assert len(tower.floor_team(1)) == 2 and len(tower.floor_team(5)) == 3


def test_boss_rush_has_twelve_bosses_that_keep_getting_stronger():
    from app.game import rush, story
    assert len(rush.BOSSES) == len(rush.REWARDS) == 12 and rush.bosses()[6]["encore"]
    hp = [sum(c.start_hp for c in rush.enemies(i)) / len(rush.enemies(i)) for i in range(12)]
    first_story = story.enemy_team(rush.BOSS_STAGES[0])
    assert hp[0] > sum(c.start_hp for c in first_story) / len(first_story)  # far beyond the story's numbers
    for i in range(rush.ENCORE, 12):
        assert hp[i] > hp[i - rush.ENCORE]  # each encore boss outclasses its first visit
