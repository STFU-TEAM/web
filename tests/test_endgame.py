"""The PvP endgame balance pass and Over Heaven: rarity leverage, resonances, the second mover's counter stance,
the UR/LR trim and the Over Heaven tracks."""
import random

import pytest

from app.game.character import CHARACTER_FILE, get_character_from_template
from app.game.effects import EffectType
from test_app import char, client, doc, login, put  # noqa: F401  (client is a fixture)
from test_features import _ach_dust, player


def _stand(cid, types=("ATTACK",), quals=("GOOD",)):
    return get_character_from_template(CHARACTER_FILE[cid - 1], list(types), list(quals))


def test_synergy_and_terrain_bonuses_scale_with_rarity():
    from app.game.characterabilities import apply_synergy_bonuses
    from app.game.effects import RARITY_LEVERAGE, Terrain, apply_terrain_bonuses
    # Tarot: Dark Blue Moon (R) and Hanged Man (SR) share the same +12% damage, scaled by their rarity
    dbm, hanged = _stand(7), _stand(13)
    before = {c.id: c.current_damage for c in (dbm, hanged)}
    apply_synergy_bonuses([dbm, hanged])
    gain = {c.id: c.current_damage / before[c.id] - 1 for c in (dbm, hanged)}
    assert dbm.rarity == "R" and hanged.rarity == "SR"
    assert gain[7] > gain[13] > 0.12  # both above the SSR base, the Common most
    # the same native terrain bonus is bigger on a Common than on a Mythic
    for cid in (7, 109):
        assert RARITY_LEVERAGE[CHARACTER_FILE[cid - 1]["rarity"]] == pytest.approx(
            {"R": 1.6, "LR": 0.35}[CHARACTER_FILE[cid - 1]["rarity"]])
    sea, mih = _stand(7), _stand(109)
    s0, m0 = sea.current_speed, mih.current_speed
    apply_terrain_bonuses([sea], Terrain.OCEAN)
    apply_terrain_bonuses([mih], Terrain.GRAVITY)
    assert sea.current_speed / s0 - 1 == pytest.approx(0.20 * 1.6, abs=0.01)
    assert mih.current_speed / m0 - 1 == pytest.approx(0.20 * 0.35, abs=0.01)


def test_most_commons_and_rares_have_a_synergy():
    from app.game.characterabilities import SYNERGIES, SYNERGY_BONUS, SYNERGY_INFO
    from app.game.resonance import HEROES, VILLAINS
    assert set(SYNERGIES) == set(SYNERGY_BONUS) == set(SYNERGY_INFO)
    assert (HEROES | VILLAINS) <= set(SYNERGIES) and not HEROES & VILLAINS
    grouped = {i for g in SYNERGIES.values() for i in g}
    for rarity, share in (("R", 0.8), ("SR", 0.9)):
        ids = [c["id"] for c in CHARACTER_FILE if c["rarity"] == rarity and c["universe"] != "Dummy"]
        assert sum(i in grouped for i in ids) / len(ids) >= share, rarity


def test_ur_and_lr_are_trimmed_but_still_strong():
    from app.game.character import RARITY_TRIM
    mih = _stand(109)
    raw = CHARACTER_FILE[109 - 1]
    assert raw["turn_for_ability"] == 1 and mih.turn_for_ability == 2  # no special every single turn
    assert mih.base_speed == pytest.approx(raw["base_speed"] * RARITY_TRIM["LR"]["speed"])
    assert mih.base_damage < raw["base_damage"]
    ssr = _stand(1)
    assert mih.base_damage >= ssr.base_damage  # trimmed toward the SSR line, not below it
    assert _stand(110).base_hp == CHARACTER_FILE[110 - 1]["base_hp"]  # raid bosses keep their numbers


def test_resonances_need_different_stands_to_cross():
    from app.game import resonance
    # the three Tusk acts are one crossing (Tusk, Joestar and SBR share the same stands)
    assert resonance.active([_stand(i) for i in (111, 112, 113)]) == []
    # Hol Horse + Tarot: two villain groups and a duo
    lit = resonance.active([_stand(i) for i in (13, 14, 7)])
    assert {"underdog", "dark_network", "bound"} <= set(lit)
    # Josuke & Okuyasu + Star Platinum: Morioh/duo on one pair, Joestar on another
    lit = resonance.active([_stand(i) for i in (32, 34, 1)])
    assert {"underdog", "golden_spirit", "bound"} <= set(lit)


def test_giant_slayer_hits_up_and_guards_against_higher_rarities():
    from app.game.character import SLAYER_GUARD, SLAYER_STEP, slayer_mult
    low, high = _stand(7), _stand(109)  # R vs LR: 4 steps, capped at 3
    assert slayer_mult(low, high) == 1 and slayer_mult(high, low) == 1  # no resonance, no slayer
    low._slayer = True
    assert slayer_mult(low, high) == pytest.approx(1 + 3 * SLAYER_STEP)
    assert slayer_mult(high, low) == pytest.approx(1 - 3 * SLAYER_GUARD)
    high._slayer = True
    assert slayer_mult(high, low) == pytest.approx(1 - 3 * SLAYER_GUARD)  # it never helps hitting down


def test_dark_network_ambush_lands_before_the_speed_check():
    from app.game.fight import Fight, Side
    random.seed(1)
    villains = [_stand(i) for i in (13, 14, 7)]
    foes = [_stand(i, types=("SPEED",), quals=("UNIVERSAL",)) for i in (10, 31, 163)]
    speed = [c.current_speed for c in foes]
    fight = Fight(Side("A", villains, True), Side("B", foes, False))
    assert "dark_network" in fight.resonances[0]
    for c, s in zip(foes, speed):
        assert c.current_speed < s and any(e.type == EffectType.SLOW for e in c.effects)
    assert any("Dark Network" in e["text"] for e in fight.log)


def test_the_second_mover_opens_in_a_counter_stance():
    from app.game.fight import COUNTER_TURNS, Fight, Side
    fast = [_stand(i, types=("SPEED",), quals=("UNIVERSAL",)) for i in (30, 80, 103)]
    slow = [_stand(i) for i in (105, 149, 154)]
    fight = Fight(Side("A", fast, True), Side("B", slow, False))
    assert fight.order == [0, 1]
    for c in slow:
        assert c.special_meter == 1
        kinds = {e.type: e for e in c.effects}
        assert kinds[EffectType.ARMORUP].duration == COUNTER_TURNS and EffectType.DAMAGEUP in kinds
        assert kinds[EffectType.CRITUP].value > 0  # the speed it gave up comes back as critical
    assert all(c.special_meter == 0 and not c.effects for c in fast)
    assert any("counter stance" in e["text"] for e in fight.log)


def test_second_wind_rallies_survivors_once_per_fall():
    from app.game.fight import Fight, Side
    team = [_stand(i) for i in (32, 34, 1)]
    fight = Fight(Side("A", team, True), Side("B", [_stand(150)], False))
    assert "golden_spirit" in fight.resonances[0]
    for c in team:
        c.current_hp = c.start_hp // 2
    team[0].current_hp = 0
    fight._check_falls()
    assert all(c.current_hp > c.start_hp // 2 for c in team[1:])
    hp = [c.current_hp for c in team]
    fight._check_falls()  # the same fall doesn't rally twice
    assert [c.current_hp for c in team] == hp


def test_home_field_holds_the_terrain_against_a_faster_setter():
    from app.game.effects import Terrain
    from app.game.fight import Fight, Side
    jolyne = [_stand(i) for i in (94, 92, 97)]  # Weather Report sets Ocean; Jolyne's crew are natives
    rival = _stand(109, types=("SPEED",), quals=("UNIVERSAL",))  # Made in Heaven sets Gravity, much faster
    rival.current_speed = 999
    fight = Fight(Side("A", jolyne, True), Side("B", [rival], False))
    assert "home_field" in fight.resonances[0]
    fight._start_turn(fight.acting_side)
    assert fight.terrain == Terrain.OCEAN


def test_over_heaven_rules_hook_into_the_engine():
    from app.game import overheaven
    from app.game.effects import Terrain
    from app.game.fight import Fight, Side
    mine = [_stand(109), _stand(7), _stand(150)]
    hp, dmg = mine[0].start_hp, mine[0].current_damage
    rules = {"terrain": "MIRROR", "enemy_first": True, "heaven_tax": 0.4, "ward": 0.5, "stun_immune": True,
             "reflect": 0.4, "heal_cut": 1, "regen": 0.1, "enrage": 0.1}
    foes = overheaven.enemy_team("tower", 3)
    fight = Fight(Side("A", mine, True), Side("B", foes, False), kind="over_heaven", meta={"rules": rules})
    assert fight.order == [1, 0]                                     # the enemy always moves first
    stance = sum(e.value for e in mine[0].effects if e.type == EffectType.DAMAGEUP)  # we move second
    assert mine[0].start_hp == int(hp * 0.6) and mine[0].current_damage - stance == pytest.approx(dmg * 0.6)
    assert mine[1].start_hp > 0 and not getattr(mine[1], "_bonded", True)  # no synergy: warded
    assert all(c._ward == 0.5 and c._stun_immune for c in foes)
    fight._start_turn(fight.acting_side)
    assert fight.terrain == Terrain.MIRROR                           # locked, whoever sets what
    mine[1].current_hp = mine[1].start_hp // 2
    assert mine[1].heal(1000) == 0                                   # heal_cut 1: nothing heals
    foes[0].add_effect(__import__("app.game.effects", fromlist=["Effect"]).Effect(EffectType.STUN, 1, 0))
    assert not foes[0].is_stunned()
    assert overheaven.rule_lines(rules) and all(isinstance(line, str) for line in overheaven.rule_lines(rules))


def test_over_heaven_tracks_cover_every_pve_mode():
    from app.game import overheaven
    assert {t["key"] for t in overheaven.TRACKS} == {"story", "alt_universe", "rush", "tower", "dungeon"}
    for t in overheaven.TRACKS:
        assert len(t["fights"]) == len(overheaven.REWARDS)
        for j, f in enumerate(t["fights"]):
            assert f["hint"] and f["rules"] is not None and f["power"] > 0
            team = overheaven.enemy_team(t["key"], j)
            assert team and all(c.level == 100 and c.awaken == 5 for c in team)
            assert set(f["rules"]) <= set(overheaven.RULE_TEXT)


def test_over_heaven_opens_after_the_story_and_pays_once(client, monkeypatch):
    import app.db as dbmod
    from app.game import overheaven, story
    # level 100 enemies would flatten the level 1 test stand in their opening turn: make this floor harmless
    monkeypatch.setitem(overheaven.BY_KEY["tower"]["fights"][0], "power", 0.001)
    player(client, "111", fragments=0, super_fragments=0, energy=10)
    h = login(client, "111")
    d = doc(client, "111")
    d["main_characters"] = [char(1)]
    put(client, d)
    # locked: not in the nav or the simulator, and the page sends you back to the story
    assert client.get("/over-heaven").headers["Location"].endswith("/story")
    assert "/over-heaven" not in client.get("/story").data.decode()
    assert "oh:tower:0" not in client.get("/battles/simulator").data.decode()
    client.post("/over-heaven/fight", data={"track": "story"}, headers=h)
    assert client.fake.get("web:fight:111") is None  # locked until the story is done

    d = doc(client, "111")
    d["web_story"] = {"cleared": story.TOTAL}
    put(client, d)
    client.fake.delete("web:story_cleared:111")  # a story win refreshes the nav's copy; this test edits the save
    assert "/over-heaven" in client.get("/story").data.decode()
    assert "Stopped Time" in client.get("/over-heaven").data.decode()
    client.post("/over-heaven/fight", data={"track": "tower"}, headers=h)
    fight = dbmod.load_fight("111")
    assert fight.kind == "over_heaven" and fight.meta["track"] == "tower" and fight.meta["stage"] == 0
    assert fight.rules == overheaven.BY_KEY["tower"]["fights"][0]["rules"]
    for c in fight.sides[1].chars:
        c.current_hp = 0
    dbmod.save_fight("111", fight)
    client.post("/over-heaven/attack", data={"log_len": len(fight.log)}, headers=h)
    client.post("/over-heaven/leave", headers=h)
    d = doc(client, "111")
    assert d["web_over_heaven"]["tower"] == 1 and d["web_over_heaven"]["paid"] == ["tower:Floor of Tides"]
    reward = overheaven.REWARDS[0]
    assert d["fragments"] == reward["fragments"] + _ach_dust(d) and d["super_fragments"] == reward["super"]
    assert "Floor of Ice" in client.get("/over-heaven?t=tower").data.decode()
    # skipping ahead is refused; the simulator offers every fight
    client.post("/over-heaven/fight", data={"track": "tower", "stage": 3}, headers=h)
    assert client.fake.get("web:fight:111") is None
    sim = client.get("/battles/simulator").data.decode()
    assert "oh:tower:3" in sim and "Floor of Glass" in sim


def test_old_progress_moves_to_the_longer_tracks_without_paying_twice():
    from app.game import overheaven
    from app.game.user import User, create_user
    u = User(create_user("1"))
    u.data["web_over_heaven"] = {"story": 4, "rush": 2}  # a save from the 4-fight tracks: story fully cleared
    assert overheaven.cleared(u, "story") == 3 and overheaven.cleared(u, "rush") == 2
    fights = overheaven.BY_KEY["story"]["fights"]
    assert len(fights) == 6 and fights[-1]["title"] == "Calamity" and fights[3]["title"] == "The Road to Cairo"
    before = (u.fragments, u.super_fragments)
    for j in (3, 4):  # the two new fights pay
        overheaven.win(u, "story", j)
    assert u.fragments > before[0]
    paid = (u.fragments, u.super_fragments, len(u.items))
    res = overheaven.win(u, "story", 5)  # the old finale: progress, no second Requiem Arrow
    assert overheaven.cleared(u, "story") == 6 and (u.fragments, u.super_fragments, len(u.items)) == paid
    assert res["fragments"] == 0


def test_part_synergies_need_a_whole_team_and_only_count_for_player_teams():
    from app.game.characterabilities import active_synergies, part_of
    from app.game.fight import Fight, Side
    assert part_of(1) == 3 and part_of(49) == 4 and part_of(161) == 8
    trio = [_stand(i) for i in (2, 3, 6)]       # three Part 3 stands
    pair = [_stand(i) for i in (2, 50, 112)]   # Part 3, 4, 7
    assert "part3" in active_synergies(trio) and "part3" not in active_synergies(trio, parts=False)
    assert not any(g.startswith("part") for g in active_synergies(pair))
    fight = Fight(Side("A", [_stand(i) for i in (2, 3, 6)], True), Side("B", [_stand(i) for i in (7, 8, 9)], False))
    log = " ".join(e["text"] for e in fight.log)
    assert "Part 3 · Stardust Crusaders synergy for A" in log and "Part 3 · Stardust Crusaders synergy for B" not in log


def test_the_title_comes_with_the_last_track():
    from app.game import overheaven
    from app.game.user import User, create_user
    u = User(create_user("1"))
    u.data["web_over_heaven"] = {"v": overheaven.SAVE_VERSION, "paid": []}
    for t in overheaven.TRACKS:
        u.data.setdefault("web_over_heaven", {})[t["key"]] = len(t["fights"])
    u.data["web_over_heaven"]["dungeon"] -= 1
    res = overheaven.win(u, "dungeon", len(overheaven.BY_KEY["dungeon"]["fights"]) - 1)
    assert overheaven.TITLE in u.data["web_titles"] and "Requiem Arrow" in res["item"]
