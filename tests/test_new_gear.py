"""The Passione / bodyguard gear (items 58-69): taunts, passives, actives, sets and where each one drops."""
import random

from app.game import gear, itemabilities
from app.game.character import Character
from app.game.effects import Effect, EffectType, Terrain
from app.game.fight import Fight, Side
from app.game.items import item_file, item_from_dict
from test_app import char, client, doc, login, put  # noqa: F401  (client is a fixture)

NEW = range(58, 70)


def stand(cid=1, items=(), refine=0):
    return Character(char(cid, xp=5000, items=[{"id": i, "refine": refine} for i in items]))


def test_every_new_item_exists_with_its_taunt_and_ability():
    names = {i["id"]: i["name"] for i in item_file}
    assert [names[i] for i in (58, 61, 66, 69)] == ["Josuke's Comb", "Abbacchio's Badge", "Narancia's Toy Plane", "Fugo's Capsule"]
    assert {i for i in NEW if item_from_dict({"id": i}).taunt} == {58, 59, 60, 61}
    assert stand(17, [59]).taunt and not stand(17, [62]).taunt
    active = {i for i in NEW if item_file[i - 1]["is_active"]}
    assert active == {61, 62, 64, 65, 66, 67, 68} and all(str(i) in itemabilities.item_specials for i in active)
    # refining grows what the capsule gives, never its drawback
    capsule = item_from_dict({"id": 69, "refine": 5})
    assert capsule.bonus_damage == 60 and capsule.bonus_hp == -30


def test_the_actives_do_their_job():
    random.seed(3)
    me, ally, foe, foe2 = stand(1), stand(2), stand(3), stand(4)
    team, foes = [me, ally], [foe, foe2]

    armor = ally.current_armor
    assert "armor" in itemabilities.abbacchios_badge(me, team, foes) and ally.current_armor > armor

    me._focus = foe2
    itemabilities.cioccolatas_spores(me, team, foes)
    assert any(e.type == EffectType.POISON and e.duration == 3 for e in foe2.effects)

    ally.current_hp = ally.start_hp // 2
    assert itemabilities.trishs_lipstick(me, team, foes) != "None" and ally.current_hp > ally.start_hp // 2
    me.current_hp = me.start_hp
    ally.current_hp = ally.start_hp
    assert itemabilities.trishs_lipstick(me, team, foes) == "None"  # nobody hurt: it waits

    speed = ally.current_speed
    ally.add_effect(Effect(EffectType.SLOW, 2, 10, foe))
    ally.add_effect(Effect(EffectType.POISON, 2, 10, foe))
    assert itemabilities.hot_pants_spray(me, team, foes) != "None"
    assert not [e for e in ally.effects if e.type in (EffectType.SLOW, EffectType.POISON)]
    assert ally.current_speed == speed  # the slow is undone exactly

    foe2.current_hp = foe2.start_hp // 4
    before = foe2.current_hp
    itemabilities.naranicas_toy_plane(me, team, foes)
    assert foe2.current_hp < before and foe.current_hp == foe.start_hp  # it went for the weakest

    foe.special_meter, foe2.special_meter = 1, 0
    itemabilities.rohans_pen(me, team, foes)
    assert foe.special_meter == 0
    assert itemabilities.rohans_pen(me, team, foes) == "None"  # nothing charging

    dmg = foe.current_damage
    itemabilities.enyas_fog_lantern(me, team, foes)
    assert foe.current_damage < dmg and any(e.type == EffectType.WEAKEN for e in foe.effects)


def test_the_passives_trigger_on_basic_hits():
    attacker = stand(1)
    comb = stand(2, [58])
    base = comb.current_damage
    for _ in range(7):
        itemabilities.on_hit(attacker, comb, {"damage": 50})
    assert comb._comb == 5 and round(comb.current_damage - base) == round(comb.start_damage * 0.3)  # 5 stacks, no more

    slime = stand(2, [59])
    hp = attacker.current_hp
    lines = itemabilities.on_hit(attacker, slime, {"damage": 200})
    assert attacker.current_hp == hp - 30 and "Yellow Temperance" in lines[0]

    goggles, target, frozen_target = stand(1, [63]), stand(2), stand(2)
    target.current_speed = frozen_target.current_speed = 100
    itemabilities.on_hit(goggles, target, {"damage": 10})
    slow = next(e for e in target.effects if e.type == EffectType.SLOW)
    assert target.current_speed == 90
    goggles._active_terrain = Terrain.FROZEN
    itemabilities.on_hit(goggles, frozen_target, {"damage": 10})
    assert next(e for e in frozen_target.effects if e.type == EffectType.SLOW).value > slow.value  # twice on ice

    random.seed(11)
    fugo, victims, backfires = stand(1, [69]), 0, 0
    for _ in range(400):
        foe = stand(2)
        itemabilities.on_hit(fugo, foe, {"damage": 10})
        victims += any(e.type == EffectType.POISON for e in foe.effects)
    backfires = sum(e.type == EffectType.POISON for e in fugo.effects)
    assert 80 < victims < 160 and 15 < backfires < 70  # ~30% the target, ~10% the holder

    assert itemabilities.on_hit(attacker, stand(2), {"damage": 0}) == []  # a dodge triggers nothing


def test_avdols_ankh_cheats_death_once_in_a_real_fight():
    ankh = stand(17, [60])
    foe = stand(1)
    fight = Fight(Side("A", [ankh], False), Side("B", [foe], False), kind="story")
    ankh.current_hp = 0
    fight._check_falls()
    assert ankh.current_hp == 1 and any(e.type == EffectType.BURN for e in foe.effects)
    assert any("Avdol's Ankh" in line["text"] for line in fight.log)
    ankh.current_hp = 0
    fight._check_falls()
    assert ankh.current_hp == 0  # only once a fight


def test_gear_passives_run_in_a_whole_fight():
    random.seed(5)
    tank = stand(2, [58, 59])
    fight = Fight(Side("A", [tank], False), Side("B", [stand(1), stand(3)], False), kind="story")
    fight.advance()
    text = " ".join(line["text"] for line in fight.log)
    assert "hair" in text and "Yellow Temperance" in text


def test_the_new_sets():
    assert gear.SET_OF[61] == gear.SET_OF[64] == gear.SET_OF[66] == "passione"
    assert gear.SET_OF[58] == gear.SET_OF[59] == gear.SET_OF[60] == "bodyguards"
    worn = gear.active_sets([item_from_dict({"id": i}) for i in (58, 59, 60)])
    assert worn[0]["key"] == "bodyguards" and worn[0]["worn"] == 3
    plain, guarded = stand(2), stand(2, [58, 59, 60])
    assert guarded.current_armor > plain.current_armor


def test_where_the_new_gear_comes_from(client):
    from app.wiki import item_rows
    rows = {r["id"]: [w for w, _ in r["sources"]] for r in item_rows()}
    assert "Who's that Stand?" in rows[58] and "Crafting" in rows[59] and "Over Heaven" in rows[60]
    assert "Gang raid" in rows[61] and "Dungeon" in rows[62] and "Dungeon" in rows[63] and "Gang raid" in rows[64]
    assert "Crafting" in rows[65] and "Heaven's Door Gauntlet" in rows[66] and "Over Heaven" in rows[67]
    assert "D'Arby's den" in rows[68] and "Boss rush" in rows[69]
    assert all(rows[i] for i in NEW)


def test_den_streak_pays_the_lantern_once_per_streak(client):
    from types import SimpleNamespace
    from app.game import den
    user = SimpleNamespace(id="500", items=[], data={})
    redis = client.fake
    got = [den._result(redis, "500", True, 100, darby=True, user=user) for _ in range(5)]
    assert got == [False, False, True, False, False]
    assert [i.id for i in user.items].count(den.LANTERN) == 1
    den._result(redis, "500", False, 100, darby=True, user=user)  # the streak breaks...
    got = [den._result(redis, "500", True, 100, darby=True, user=user) for _ in range(3)]
    assert got[-1] is True  # ...and a new one pays again


def test_corpse_recipes_take_any_part(monkeypatch):
    from types import SimpleNamespace
    from app.game import logic
    from app.game.items import CORPSE_PARTS, NEW_ROKAKAKA
    holy = next(r for r in logic.RECIPES if r["result"] == 37)
    fruit = next(r for r in logic.RECIPES if r["result"] == NEW_ROKAKAKA)
    bag = lambda *ids: SimpleNamespace(items=[item_from_dict({"id": i}) for i in ids], data={})  # noqa: E731
    assert len(CORPSE_PARTS) == 9
    assert logic.craftable(bag(34, 34, 34), holy) == 0  # three of the same part isn't three parts
    assert logic.craftable(bag(70, 72, 75), holy) == 1  # any three different ones are
    assert logic.craftable(bag(70, 72, 75, 70, 72, 34), holy) == 2
    user = bag(39, 39, 39, 39, 71, 71, 36)
    assert logic.craftable(user, fruit) == 2
    monkeypatch.setattr(logic, "track_quest_progress", lambda *a, **k: None)
    monkeypatch.setattr(logic, "check_achievements", lambda *a, **k: None)
    made = logic.craft(user, "New Rokakaka")
    assert made.id == NEW_ROKAKAKA and sorted(i.id for i in user.items) == [36, 39, 39, 71, NEW_ROKAKAKA]  # spent a spare Spine
    slots = logic.ingredient_slots(holy)
    assert slots[0]["distinct"] and slots[0]["n"] == 3 and logic.slot_have(bag(34, 34, 70), slots[0]) == 2


def test_new_rokakaka_trades_wounds_once():
    holder, a, b = stand(17, [76]), stand(1), stand(2)
    a.current_hp = a.start_hp // 2
    fight = Fight(Side("A", [holder], False), Side("B", [a, b], False), kind="story")
    holder.current_hp = int(holder.start_hp * 0.4)
    fight._check_falls()
    assert holder.current_hp == int(holder.start_hp * 0.4)  # above 30%: nothing yet
    holder.current_hp = int(holder.start_hp * 0.2)
    fight._check_falls()
    assert holder.current_hp >= holder.start_hp * 0.95  # traded with the healthiest...
    assert b.start_hp * 0.79 <= b.current_hp <= b.start_hp * 0.81 and a.current_hp == a.start_hp // 2  # ...which loses 20% at most
    assert "Equivalent Exchange" in fight.log[-1]["text"]
    holder.current_hp = int(holder.start_hp * 0.1)
    fight._check_falls()
    assert holder.current_hp == int(holder.start_hp * 0.1)  # once a fight


def test_the_holy_corpse_sends_misfortune_elsewhere():
    me, ally = stand(1, [37]), stand(2)
    assert item_from_dict({"id": 37}).bonus_hp == 100
    ally.add_effect(Effect(EffectType.POISON, 3, 50, None))
    ally.current_hp = ally.start_hp // 2
    itemabilities.holy_corpse(me, [me, ally], [])
    assert not [e for e in ally.effects if e.type == EffectType.POISON] and ally.current_hp > ally.start_hp // 2
