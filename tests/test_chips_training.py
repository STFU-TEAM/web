"""Stand chips (one kind per synergy, random stats, slots from awakening, off in ranked) and the training ground."""
import random

import app.db as dbmod
from app.game import altverse, chips, story
from app.game.character import Character
from app.game.user import User, create_user
from test_app import char, client, doc, login, put  # noqa: F401  (client is a fixture)


def _done(d):
    """Story and Alternate Universe cleared."""
    d["web_story"] = {"cleared": story.TOTAL}
    d["web_au"] = {"cleared": {c["key"]: len(c["stages"]) for c in altverse.CHAPTERS}}
    return d


def _player(c, uid="111", finished=True, **fields):
    d = create_user(uid)
    d.update(fields)
    put(c, _done(d) if finished else d)
    return login(c, uid)


def test_chip_rolls_follow_tier_and_synergy():
    rng = random.Random(4)
    for _ in range(50):
        chip = chips.roll("squadra", rng=rng)
        lines = chips.TIERS[chip["tier"]][1]
        assert len(chip["stats"]) == lines and len({s for s, _ in chip["stats"]}) == lines
        assert chip["stats"][0][0] == "damage_pct"  # La Squadra's own bonus is damage
    assert chips.roll("sbr_racers", "legendary", rng)["stats"][0][0] == "speed_flat"


def test_slots_grow_with_awakening_up_to_four():
    assert [chips.slots(Character(char(1, awaken=a))) for a in range(6)] == [1, 2, 3, 4, 4, 4]


def test_socketing_needs_the_synergy_and_a_free_slot_and_changes_stats():
    user = User(create_user("1"))
    star = Character(char(1, xp=5000))  # Star Platinum: crusaders, joestar, kujo, part 3...
    user.main_characters = [star]
    base = star.start_damage
    good = {"id": "a1", "syn": "crusaders", "tier": "rare", "stats": [["damage_pct", 0.1], ["crit_flat", 5]]}
    wrong = {"id": "b2", "syn": "squadra", "tier": "common", "stats": [["damage_pct", 0.1]]}
    extra = {"id": "c3", "syn": "joestar", "tier": "common", "stats": [["hp_pct", 0.05]]}
    chips.bag(user).extend([good, wrong, extra])
    import pytest
    from app.game.logic import GameError
    with pytest.raises(GameError, match="won't fit"):
        chips.socket(user, star.uuid, "b2")
    fresh, _ = chips.socket(user, star.uuid, "a1")
    assert abs(fresh.start_damage - base * 1.1) < 2 and fresh.start_critical == star.start_critical + 5
    with pytest.raises(GameError, match="full"):
        chips.socket(user, fresh.uuid, "c3")  # ★0: one slot
    chips.unsocket(user, fresh.uuid, "a1")
    assert [c["id"] for c in chips.bag(user)] == ["b2", "c3", "a1"]


def test_ranked_strips_chips_but_pve_keeps_them():
    stand = Character({**char(1, xp=5000), "chips": [{"id": "x", "syn": "crusaders", "tier": "epic",
                                                      "stats": [["damage_pct", 0.2]]}]})
    from app.game.fight import fighting_copy
    assert fighting_copy([stand])[0].start_damage == stand.start_damage
    bare = chips.strip([stand])[0]
    assert bare.start_damage < stand.start_damage and "chips" in stand.data


def test_released_and_fused_stands_give_their_chips_back(client):
    worn = {"id": "w1", "syn": "crusaders", "tier": "common", "stats": [["crit_flat", 3]]}
    a, b = char(1, xp=3000), char(1, xp=100)
    b["chips"] = [worn]
    c3 = char(2)
    c3["chips"] = [dict(worn, id="w2")]
    h = _player(client, main_characters=[a], storage_characters=[b, c3])
    client.post("/team/fuse", data={"uuid": a["uuid"], "fodder": b["uuid"]}, headers=h)
    client.post("/team/release", data={"uuid": c3["uuid"]}, headers=h)
    assert sorted(c["id"] for c in doc(client, "111")["web_chips"]) == ["w1", "w2"]


def test_chip_pages_render_and_scrap(client):
    h = _player(client, main_characters=[char(1, xp=500)],
                web_chips=[{"id": "s1", "syn": "crusaders", "tier": "common", "stats": [["crit_flat", 3]]}])
    page = client.get("/chips").data.decode()
    assert "Stardust Crusaders" in page and "+3 critical" in page and "Fits Star platinum" in page
    d = doc(client, "111")
    panel = client.get(f"/team/stand/{d['main_characters'][0]['uuid']}").data.decode()
    assert "Chips 0/1" in panel and "Socket" in panel
    before = d["fragments"]
    out = client.post("/chips/scrap", data={"chip": "s1"}, headers=h).data.decode()
    assert "Scrapped 1 chip" in out and doc(client, "111")["fragments"] == before + chips.TIERS["common"][3]


def test_training_ground_is_locked_until_story_and_au_are_done(client):
    h = _player(client, finished=False, main_characters=[char(1, xp=500)])
    assert "opens once you've finished" in client.get("/training").data.decode()
    client.post("/training/fight", data={"drill": "spar", "uuid": doc(client, "111")["main_characters"][0]["uuid"]},
                headers=h)
    assert dbmod.load_fight("111") is None


def test_training_trains_storage_stands_fast(client, monkeypatch):
    from app.game import training
    monkeypatch.setattr(training.random, "random", lambda: 0.0)  # the chip always drops
    keeper = char(5, xp=4000)  # level 40: no catch-up doubling
    h = _player(client, main_characters=[char(1, xp=500)], storage_characters=[keeper], energy=10)
    assert "Start training" in client.get("/training").data.decode()
    client.post("/training/fight", data={"drill": "intense", "uuid": keeper["uuid"]}, headers=h)
    fight = dbmod.load_fight("111")
    assert fight.kind == "training" and [c.uuid for c in fight.sides[0].chars] == [keeper["uuid"]]
    assert fight.sides[1].chars[0].level == 40 + training.DRILLS["intense"]["level"] and doc(client, "111")["energy"] == 8
    for c in fight.sides[1].chars:
        c.current_hp = 0
    dbmod.save_fight("111", fight)
    page = client.post("/training/attack", headers=h).data.decode()
    assert "Train again" in page and "chip" in page
    d = doc(client, "111")
    stand = next(s for s in d["storage_characters"] if s["uuid"] == keeper["uuid"])
    assert stand["xp"] == 4000 + training.DRILLS["intense"]["xp"] and len(d["web_chips"]) == 1


def test_training_loss_still_pays_a_share(client):
    from app.game import training
    keeper = char(5, xp=4000)
    h = _player(client, main_characters=[keeper], energy=5)
    client.post("/training/fight", data={"drill": "spar", "uuid": keeper["uuid"]}, headers=h)
    page = client.post("/training/attack", data={"forfeit": "1"}, headers=h).data.decode()
    assert "still learned" in page
    xp = doc(client, "111")["main_characters"][0]["xp"]
    assert xp == 4000 + int(training.DRILLS["spar"]["xp"] * training.LOSS_SHARE)
