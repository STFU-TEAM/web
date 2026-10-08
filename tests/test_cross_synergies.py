"""The cross synergies for the weaker stands: who's in them, and every special that changes when one is lit."""
import random

import pytest

from app.game.character import CHARACTER_FILE, character_from_dict
from app.game.characterabilities import SYNERGIES, SYNERGY_BONUS, SYNERGY_INFO, apply_synergy_bonuses
from app.wiki import SYNERGY_EFFECTS, SYNERGY_USERS

NEW = ["dio_pucci", "boingo_hol_horse", "pesci_prosciutto", "enyaba_geil", "nijimura", "trussardi", "first_love",
       "polpo_test", "fate", "fugo_narancia", "cellmates", "tide", "swarm", "disguise", "fire", "gunslingers", "soul",
       "plague", "mirrors", "morioh_2011", "schott_keys"]


def stand(cid, level=60):
    return character_from_dict({"id": cid, "xp": level * 100, "awaken": 1, "types": ["BALANCE"], "qualities": ["GOOD"],
                                "items": []})


def test_every_new_group_is_complete_and_favours_the_weaker_stands():
    rarity = {c["id"]: c["rarity"] for c in CHARACTER_FILE}
    for key in NEW:
        assert key in SYNERGY_INFO and key in SYNERGY_BONUS and len(SYNERGIES[key]) >= 2, key
        assert SYNERGY_USERS.get(key), f"{key} changes no special"
    weak = [cid for key in NEW for cid in SYNERGIES[key] if rarity[cid] in ("R", "SR", "SSR")]
    strong = [cid for key in NEW for cid in SYNERGIES[key] if rarity[cid] in ("UR", "LR")]
    assert len(weak) > 10 * len(strong)
    for cid in (14, 24, 71, 72):  # Emperor, Tohth, Beach Boy, Grateful Dead: three crews or more each
        assert sum(cid in ids for k, ids in SYNERGIES.items() if not k.startswith("part")) >= 3
    orphans = [c["id"] for c in CHARACTER_FILE if c["universe"] != "Dummy" and c["rarity"] in ("R", "SR", "SSR")
               and not any(c["id"] in ids for k, ids in SYNERGIES.items() if not k.startswith("part"))]
    assert len(orphans) <= 4, orphans


def test_a_lit_pair_shares_its_bonus():
    team = [stand(71), stand(72)]
    before = [c.current_damage for c in team]
    lit = dict(apply_synergy_bonuses(team))
    assert "pesci_prosciutto" in lit and all(c.current_damage > b for c, b in zip(team, before))


def _partner(key, cid):
    others = sorted(SYNERGIES[key] - {cid})
    return others[0]


CASES = [(key, cid) for key in NEW for cid in sorted(SYNERGY_USERS.get(key, ()))]


@pytest.mark.parametrize("key,cid", CASES, ids=[f"{k}-{c}" for k, c in CASES])
def test_the_special_changes_with_its_synergy(key, cid):
    icon = SYNERGY_INFO[key][1]
    random.seed(4)
    outputs = []
    for with_partner in (False, True):
        me = stand(cid)
        allies = [me, stand(_partner(key, cid))] if with_partner else [me, stand(1 if cid != 1 else 2)]
        enemies = [stand(e, 100) for e in (9, 20, 25)]
        for e in enemies:
            e.current_speed = e.start_speed = 400  # faster than anyone: Black Sabbath's test needs a faster enemy
            if key == "fate":
                e.current_hp = int(e.start_hp * 0.4)  # inside the 45% window, outside the usual 30%
        me.special_meter = me.turn_for_ability
        _, message = me.special(allies, enemies)
        outputs.append(message)
    assert icon not in outputs[0] and icon in outputs[1], (key, cid, outputs)
    assert key in SYNERGY_EFFECTS and cid in SYNERGY_EFFECTS[key]


def test_computer_enemies_get_no_cross_synergy():
    from app.game.fight import Fight, Side
    me = Side("Me", [stand(71), stand(72)], True)
    foes = Side("AI", [stand(71), stand(72)], False)
    fight = Fight(me, foes, kind="story")
    lines = [e["text"] for e in fight.log]
    assert any("Prosciutto & Pesci synergy for Me" in t for t in lines)
    assert not any("Prosciutto & Pesci synergy for AI" in t for t in lines)
    assert all(c._computer for c in foes.chars) and not any(c._computer for c in me.chars)
    beach = foes.chars[0]
    beach.special_meter = beach.turn_for_ability
    _, message = beach.special(foes.chars, me.chars)
    assert "🎣" not in message  # nor the special change
