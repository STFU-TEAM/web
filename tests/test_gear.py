"""Item sets, refining duplicates, craft xN and the equip preview (app/game/gear.py)."""
from app.game import gear
from app.game.character import character_from_dict
from app.game.items import REFINE_MAX, item_from_dict
from test_app import char, client, doc, login, put  # noqa: F401  (client is a fixture)
from test_features import player


def _stand(cid, items=()):
    return character_from_dict(char(cid, xp=5000, items=[{"id": i} for i in items]))


def test_sets_light_up_with_two_and_three_different_pieces():
    bare, two, three, doubled = (_stand(1, ids) for ids in ((), (15, 55), (15, 55, 52), (15, 15)))
    assert gear.active_sets(bare.items) == [] and gear.active_sets(doubled.items) == []  # one piece twice isn't a set
    assert gear.active_sets(two.items)[0]["worn"] == 2 and gear.active_sets(three.items)[0]["worn"] == 3
    items_only = _stand(1, (15, 55))  # the same crit from the items themselves, without the set bonus
    raw = sum(item_from_dict({"id": i}).bonus_critical for i in (15, 55))
    assert two.start_critical > bare.start_critical + raw  # the 2-piece bonus lands on top of the items
    assert three.start_critical - two.start_critical > item_from_dict({"id": 52}).bonus_critical
    assert gear.set_info(55)["name"] == "High Roller" and gear.set_info(1) is None
    for key, (_, _, pieces, tiers) in gear.SETS.items():
        assert len(set(pieces)) >= 3 and set(tiers) == {2, 3}, key


def test_refining_a_bag_item_spends_a_spare_and_dust(client):
    player(client, "111", fragments=100_000, items=[{"id": 1}, {"id": 1}, {"id": 1, "refine": 2}])
    h = login(client, "111")
    page = client.post("/items/refine", data={"item": 1}, headers=h).data.decode()
    assert "Dio&#39;s Knife +3" in page
    d = doc(client, "111")
    assert sorted(i.get("refine", 0) for i in d["items"]) == [0, 3]  # the best copy went up, a plain one was spent
    assert d["fragments"] == 100_000 - gear.refine_cost(2)
    knife3 = item_from_dict({"id": 1, "refine": 3})
    assert knife3.bonus_damage == round(30 * 1.3) and knife3.label == "Dio's Knife +3"
    client.post("/items/refine", data={"item": 1}, headers=h)
    client.post("/items/refine", data={"item": 1}, headers=h)  # no spare left: refused
    assert sorted(i.get("refine", 0) for i in doc(client, "111")["items"]) == [4]
    assert gear.refine_cost(REFINE_MAX) is None


def test_refining_an_equipped_item_and_selling_never_takes_the_refined_copy(client):
    team = [char(1, xp=5000, items=[{"id": 4, "refine": 1}])]
    player(client, "111", fragments=100_000, main_characters=team, items=[{"id": 4}, {"id": 4}, {"id": 1, "refine": 2}, {"id": 1}])
    h = login(client, "111")
    client.post("/team/refine", data={"uuid": team[0]["uuid"], "slot": 0, "item": 4}, headers=h)
    d = doc(client, "111")
    assert d["main_characters"][0]["items"][0]["refine"] == 2 and [i["id"] for i in d["items"]].count(4) == 1
    client.post("/items/sell", data={"item": 1}, headers=h)  # sells the plain knife, keeps the +2
    assert [i.get("refine", 0) for i in doc(client, "111")["items"] if i["id"] == 1] == [2]


def test_equip_preview_and_craft_many(client):
    from app.game import characterabilities as abilities
    stand = _stand(161)
    line = gear.preview_line(stand, item_from_dict({"id": 49}))  # Calamity Charm on Wonder of U (a Luck special)
    assert "HP" in line and "CRT" in line and "special +" in line and abilities.scaling_of(161) == "critical"
    p = gear.preview(_stand(1, (15,)), item_from_dict({"id": 55}))
    assert p["sets"] and p["sets"][0]["name"] == "High Roller"

    player(client, "111", main_characters=[char(1, xp=5000)], items=[{"id": 38}] * 6 + [{"id": 15}] * 2)
    h = login(client, "111")
    page = client.get("/items").data.decode()
    assert "Craft ×2" in page and "to craft" in page.split("<main")[0]  # the button, and the nav badge
    assert "You crafted 2 × Valkyrie" in client.post("/items/craft", data={"recipe": "Valkyrie's Horseshoe", "count": 5},
                                                     headers=h).data.decode()
    assert [i["id"] for i in doc(client, "111")["items"]] == [38, 38, 50, 50]
    panel = client.get(f"/team/stand/{doc(client, '111')['main_characters'][0]['uuid']}").data.decode()
    assert "SPD" in panel and "CRT" in panel  # the horseshoe's preview line on this stand
