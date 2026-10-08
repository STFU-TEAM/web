"""Build-diversity gear (items 49-56): every stat pair has a craftable item, the actives work in fights, and a
revenge tank like Wonder of U gets what it needs (health for the backlash, luck for its special's power)."""
import random

from app.game import characterabilities as abilities
from app.game.character import character_from_dict
from app.game.effects import EffectType
from app.game.items import item_file
from app.game.logic import RECIPES
from test_app import char, client, doc, login, put  # noqa: F401  (client is a fixture)
from test_features import player

NEW = range(49, 57)
WONDER_OF_U = 161


def _stand(cid, items=(), awaken=0):
    return character_from_dict(char(cid, xp=5000, awaken=awaken, items=[{"id": i} for i in items]))


def test_every_new_item_is_craftable_gear_from_existing_drops():
    results = {rec["result"]: rec for rec in RECIPES}
    for iid in NEW:
        it = item_file[iid - 1]
        assert it["id"] == iid and it["is_equipable"], it["name"]
        assert results[iid]["name"] == it["name"]
        for ingredient, _ in results[iid]["ingredients"]:
            assert ingredient < 49, (it["name"], ingredient)  # made from items that already drop
    stats = ("bonus_hp", "bonus_damage", "bonus_speed", "bonus_critical", "bonus_armor")
    pairs = {tuple(s for s in stats if item_file[i - 1][s] > 0) for i in NEW}
    for pair in [("bonus_hp", "bonus_critical"), ("bonus_speed", "bonus_critical"), ("bonus_hp", "bonus_speed"),
                 ("bonus_critical", "bonus_armor"), ("bonus_damage", "bonus_armor")]:
        assert tuple(s for s in stats if s in pair) in pairs, pair


def test_crafting_a_new_item_through_the_page(client):
    player(client, "111", items=[{"id": 4}, {"id": 39}, {"id": 39}, {"id": 15}])
    h = login(client, "111")
    assert b"You crafted Calamity Charm" in client.post("/items/craft", data={"recipe": "Calamity Charm"}, headers=h).data
    assert [i["id"] for i in doc(client, "111")["items"]] == [49]


def test_health_and_luck_gear_feed_wonder_of_u():
    assert abilities.scaling_of(WONDER_OF_U) == "critical"
    bare = _stand(WONDER_OF_U, awaken=5)
    geared = _stand(WONDER_OF_U, items=(49, 49, 52), awaken=5)
    # item bonuses grow with awakening (x2.67 at 5 stars) before the stand's types apply
    assert geared.start_hp > bare.start_hp + 2 * 70 * 2
    assert geared.start_critical > bare.start_critical + 3 * 12 * 2
    assert abilities.special_power(geared)["power"] > abilities.special_power(bare)["power"] * 1.5

    # the backlash is 30% of the health it lost, so a bigger pool hits back harder at the same share lost
    foes = [_stand(1), _stand(2)]
    for s in (bare, geared):
        s.current_hp = s.start_hp // 2
    hits = []
    for s in (bare, geared):
        for f in foes:
            f.current_hp = f.start_hp = 10 ** 6
        abilities.begin_special(s)
        try:
            abilities.wonder_of_u(s, [s], foes)
        finally:
            abilities.end_special()
        hits.append(sum(f.start_hp - f.current_hp for f in foes))
    assert hits[1] > hits[0] * 1.5


def test_the_new_actives_in_a_fight():
    random.seed(4)
    holder = _stand(WONDER_OF_U, items=(54, 55, 56))
    foe = _stand(1)
    branch, chips, clackers = holder.items

    assert branch.special(holder, [holder], [foe]) == "None"  # unhurt: nothing to pay back
    holder.current_hp = holder.start_hp - 1000
    before = foe.current_hp
    assert "Rokakaka Branch" in branch.special(holder, [holder], [foe])
    assert before - foe.current_hp == 150

    crit = holder.current_critical
    assert "crit for 2 turns" in chips.special(holder, [holder], [foe])
    gained = holder.current_critical - crit
    assert gained in (10, 20, 30, 40) and any(e.type == EffectType.CRITUP for e in holder.effects)

    before = foe.current_hp
    assert "Clacker Volley" in clackers.special(holder, [holder], [foe])
    assert before - foe.current_hp == int(holder.current_damage * 0.3)


def test_the_wiki_lists_the_new_gear(client):
    page = client.get("/wiki/items").data.decode()
    for iid in NEW:
        assert item_file[iid - 1]["name"].replace("'", "&#39;") in page
    assert "15% of the health the holder has lost" in page


def test_wonder_of_u_calamity_grows_exponentially_with_its_wounds():
    def calamity(lost_share, foe_hp=10 ** 6):
        wou = _stand(WONDER_OF_U, awaken=5)
        wou.current_hp = round(wou.start_hp * (1 - lost_share))
        foes = [_stand(1)]
        for f in foes:
            f.current_hp = f.start_hp = foe_hp
        abilities.wonder_of_u(wou, [wou], foes)
        return foe_hp - foes[0].current_hp - foe_hp * 0.08, wou.start_hp  # the backlash, past the 8% base share

    quarter, half, three_quarters = (calamity(s)[0] for s in (0.25, 0.5, 0.75))
    hp = calamity(0.5)[1]
    assert abs(half - hp * 0.5 * 0.30) <= 2  # 30% of what it lost at half health, as before
    assert half / quarter > 3 and three_quarters / half > 2.4  # each step down hurts much more than the last
    # no one-shot: at most 60% of the enemy's max health on top of the base share
    capped, _ = calamity(0.95, foe_hp=1000)
    assert capped <= 600 + 1
