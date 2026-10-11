"""The October balance pass: refine prices, the Bites the Dust Switch, ★4/★5 copies, Heavy Weather and poison."""

from app.game import characterabilities as abilities
from app.game import gear
from app.game.character import POISON_MAX_HP, character_from_dict
from app.game.effects import Effect, EffectType
from app.game.items import item_file
from test_app import char, client, doc, login, put  # noqa: F401  (client is a fixture)
from test_features import player

BTD = 57


def _stand(cid, items=(), awaken=0):
    return character_from_dict(char(cid, xp=5000, awaken=awaken, items=[{"id": i} for i in items]))


def test_refining_doubles_from_2500_and_caps_at_10000():
    assert [gear.refine_cost(lv) for lv in range(gear.REFINE_MAX)] == [2500, 5000, 10000, 10000, 10000]
    assert max(gear.REFINE_COST) == 10_000


def test_bites_the_dust_detonates_every_poison_and_burn_at_once():
    holder = _stand(1, items=(BTD,))
    a, b = _stand(4), _stand(5)
    switch = holder.items[0]
    assert switch.special(holder, [holder], [a, b]) == "None"  # nothing to set off
    a.add_effect(Effect(EffectType.POISON, 3, 100, holder))
    a.add_effect(Effect(EffectType.BURN, 2, 50, holder))
    b.add_effect(Effect(EffectType.WEAKEN, 2, 5, holder))  # other effects are left alone
    hp_a, hp_b = a.current_hp, b.current_hp
    expected = int((100 + POISON_MAX_HP * a.start_hp) * 3 + 50 * 2)
    assert "BITES THE DUST" in switch.special(holder, [holder], [a, b])
    assert hp_a - a.current_hp == min(expected, hp_a) and b.current_hp == hp_b
    assert not [e for e in a.effects if e.type in (EffectType.POISON, EffectType.BURN)]
    assert [e.type for e in b.effects] == [EffectType.WEAKEN]


def test_the_switch_is_event_only():
    it = item_file[BTD - 1]
    assert it["id"] == BTD and it["is_equipable"] and not it["prurchasable"]
    from app.game import events, logic
    offer = events.SHOP_BY_KEY["btd"]
    assert offer["cost"] == 150 and offer["limit"] == 1 and offer["exclusive"] and offer["give"]["items"] == [BTD]
    assert BTD not in logic.MIRROR_ITEM_DROPS and BTD not in logic.DAILY_ITEM_DROPS
    assert all(r["result"] != BTD for r in logic.RECIPES)


def test_four_and_five_stars_take_an_arrow_and_a_spare_copy(client):
    sp = char(1, xp=10_000, awaken=3)
    locked_copy, spare = char(1), char(1, items=[{"id": 1}])
    player(client, "111", main_characters=[sp], storage_characters=[locked_copy, spare],
           items=[{"id": 3}, {"id": 3}], web_locked=[locked_copy["uuid"]])
    h = login(client, "111")
    client.post("/team/arrow", data={"uuid": sp["uuid"], "mode": "awaken"}, headers=h)
    d = doc(client, "111")
    assert d["main_characters"][0]["awaken"] == 4
    assert [c["uuid"] for c in d["storage_characters"]] == [locked_copy["uuid"]]  # the locked copy is kept
    assert sorted(i["id"] for i in d["items"]) == [1, 3]  # the spare's knife came back, one arrow left
    # no unlocked copy left: refused and the arrow comes back
    r = client.post("/team/arrow", data={"uuid": sp["uuid"], "mode": "awaken"}, headers=h)
    d = doc(client, "111")
    assert d["main_characters"][0]["awaken"] == 4 and sorted(i["id"] for i in d["items"]) == [1, 3]
    assert b"spare copy" in r.data


def test_below_three_stars_the_arrow_alone_is_enough(client):
    sp = char(1, xp=10_000, awaken=1)
    player(client, "111", main_characters=[sp], items=[{"id": 3}])
    client.post("/team/arrow", data={"uuid": sp["uuid"], "mode": "awaken"}, headers=login(client, "111"))
    assert doc(client, "111")["main_characters"][0]["awaken"] == 2


def test_heavy_weather_pairs_whitesnake_and_weather_report():
    assert abilities.SYNERGIES["heavy_weather"] == {94, 107}
    wr, ws = _stand(94), _stand(107)
    foe = _stand(1)
    abilities.weather_report(wr, [wr, ws], [foe])
    poison = [e for e in foe.effects if e.type == EffectType.POISON]
    assert poison and poison[0].duration == 3


def test_poison_ticks_eat_a_share_of_max_health():
    foe = _stand(1)
    foe.add_effect(Effect(EffectType.POISON, 2, 10, None))
    before = foe.current_hp
    foe.end_turn()
    assert before - foe.current_hp == int(10 + POISON_MAX_HP * foe.start_hp)
