"""Burn sunders armor, poison grows as health runs out, the harder raid (the singularity, small gangs), the themed
synergies, Tenore Sax and Sethan, and the art helper's remembered search and part filter."""
import os
import sys

from app.game import gangs as G
from app.game.character import BURN_SUNDER, POISON_LOW_HP, character_from_dict, dot_tick, share_hp
from app.game.characterabilities import PARTS, SYNERGIES, active_synergies
from app.game.effects import Effect, EffectType, Terrain
from test_app import char


def _stand(cid, **kw):
    return character_from_dict(char(cid, xp=6000, **kw))


def test_burn_sunders_armor_once_and_not_on_the_ocean():
    c = _stand(1)
    armor = c.current_armor
    c.add_effect(Effect(EffectType.BURN, 2, 30))
    cut = int(armor * BURN_SUNDER)
    assert c.current_armor == armor - cut and any(getattr(e, "sunder", False) for e in c.effects)
    c.add_effect(Effect(EffectType.BURN, 3, 30))  # a second burn stretches the sunder, it doesn't stack
    sunders = [e for e in c.effects if getattr(e, "sunder", False)]
    assert len(sunders) == 1 and sunders[0].duration == 3 and c.current_armor == armor - cut
    for _ in range(3):
        c.end_turn()
    assert c.current_armor == armor  # the armor comes back when the burn is gone
    wet = _stand(1)
    wet._active_terrain = Terrain.OCEAN
    wet.add_effect(Effect(EffectType.BURN, 2, 30))
    assert wet.current_armor == armor  # the Ocean puts burns out: nothing to sunder


def test_poison_ticks_harder_as_health_runs_out():
    c = _stand(1)
    poison = Effect(EffectType.POISON, 2, 40)
    full = dot_tick(c, poison)
    c.current_hp = c.start_hp // 2
    half = dot_tick(c, poison)
    c.current_hp = 1
    low = dot_tick(c, poison)
    assert full < half < low and abs(half / full - (1 + POISON_LOW_HP / 2)) < 0.01
    assert dot_tick(c, Effect(EffectType.BURN, 2, 40)) == 40  # burns don't care


def test_the_raid_boss_carries_the_singularity_and_small_gangs_count_more():
    boss, *crew = G.raid_team()
    assert any(it.id == G.RAID_SINGULARITY for it in boss.items) and boss.start_hp > 100_000
    assert share_hp(boss) < 10_000 and share_hp(crew[0]) == crew[0].start_hp  # sudden death and poison see a normal stand
    plain = G.raid_team(singularity=False)[0]
    assert not plain.items and plain.start_hp < 10_000  # the Gang Cup's stand-ins
    assert G.raid_mult({"users": ["1", "2", "3"]}) == 2.0
    assert G.raid_mult({"users": [str(i) for i in range(12)]}) == 1.3
    assert G.raid_mult({"users": [str(i) for i in range(40)]}) == 1.0


def test_themed_synergies_and_the_new_stands():
    for name in ("debt_collectors", "beasts", "illusions", "youth"):
        assert name in SYNERGIES
    team = [_stand(93), _stand(155), _stand(1)]
    for c in team:
        c._computer = False
    assert "debt_collectors" in active_synergies(team)
    assert 165 in PARTS[3] and 166 in PARTS[3] and 165 in SYNERGIES["dio_mansion"] and 166 in SYNERGIES["nine_gods"]
    sax, sethan = _stand(165), _stand(166)
    assert (sax.name, sax.rarity, sethan.name, sethan.rarity) == ("Tenore Sax", "R", "Sethan", "SR")
    foes = [_stand(1), _stand(2), _stand(3)]
    sax.special_meter = sax.turn_for_ability
    text = sax.special([sax, _stand(16)], foes)[-1]
    assert "maze" in text and "Illusions" in text and any(e.type == EffectType.STUN for f in foes for e in f.effects)
    foes = [_stand(1), _stand(2), _stand(3)]
    for f in foes:
        f.special_meter = 3
    sethan.special_meter = sethan.turn_for_ability
    sethan.special([sethan, _stand(1)], foes)
    assert sorted(f.special_meter for f in foes) == [1, 3, 3]  # its target forgets its power: set back 2 turns


def test_the_new_stands_can_be_pulled():
    from app.game.logic import BANNERS
    part3 = next(b for b in BANNERS if b["name"] == "Part - 3")
    assert {165, 166} <= set(part3["cards"])


def test_the_art_helper_remembers_its_search_and_filters_by_part():
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
    import art_helper as A
    c = A.app.test_client()
    page = c.get("/?q=&part=3&rarity=SR&missing=").data.decode()
    assert "Sethan" in page and "Star platinum" not in page and 'value="3" selected' in page
    again = c.get("/").data.decode()  # no arguments: the search comes back
    assert "Sethan" in again and "Gold Experience" not in again
    cleared = c.get("/?clear=1", follow_redirects=True).data.decode()
    assert "Star platinum" in cleared and "Gold Experience" in cleared  # forgotten: every stand again
