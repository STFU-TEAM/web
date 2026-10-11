"""The forge: chip combining and the gear refining bench."""
import random

from app.game import chips, gear
from test_app import char, client, doc, login, put  # noqa: F401  (client is a fixture)
from test_features import player


class _Rigged(random.Random):
    """random() always returns `value`: forces the combine's tier roll."""
    def __init__(self, value):
        super().__init__(1)
        self.value = value

    def random(self):
        return self.value


class _User:
    def __init__(self, bag):
        self.data = {"web_chips": bag}


def _commons(n, syn="plague"):
    return [chips.roll(syn, "common", random.Random(i)) for i in range(n)]


def test_combine_uses_the_weakest_and_usually_keeps_the_tier():
    bag = _commons(10)
    keep = sorted(bag, key=chips.strength)[-2:]  # the two best rolls stay
    user = _User(bag)
    res = chips.combine(user, "common", "heavy_weather", _Rigged(0.5))
    assert res["used"] == 8 and not res["up"] and res["chip"]["tier"] == "common" and res["chip"]["syn"] == "heavy_weather"
    left = chips.bag(user)
    assert len(left) == 3 and all(k in left for k in keep)


def test_combine_climbs_a_tier_on_a_lucky_roll_and_needs_enough_chips():
    for tier, need, up in (("common", 8, "rare"), ("rare", 4, "epic"), ("epic", 2, "legendary")):
        user = _User([chips.roll("plague", tier, random.Random(i)) for i in range(need)])
        res = chips.combine(user, tier, "plague", _Rigged(chips.COMBINE_CHANCE / 2))
        assert res["up"] and res["chip"]["tier"] == up and len(chips.bag(user)) == 1
    import pytest
    from app.game.logic import GameError
    with pytest.raises(GameError):
        chips.combine(_User(_commons(7)), "common", "plague")
    with pytest.raises(GameError):
        chips.combine(_User([chips.roll("plague", "legendary")] * 2), "legendary", "plague")
    with pytest.raises(GameError):
        chips.combine(_User(_commons(8)), "common", "not-a-synergy")


def test_the_chip_page_combines(client):
    player(client, "111", main_characters=[char(1)], web_chips=_commons(9))
    h = login(client, "111")
    page = client.get("/chips", headers=h).data.decode()
    assert "Combine chips" in page and "8 common chips" in page and 'id="combine-syn"' in page
    r = client.post("/chips/combine", data={"tier": "common", "syn": "plague"}, headers={**h, "HX-Request": "true"})
    assert r.status_code == 200 and "fused into" in r.data.decode()
    left = doc(client, "111")["web_chips"]
    assert len(left) == 2 and any(c["syn"] == "plague" and c["tier"] in ("common", "rare") for c in left)


def test_the_gear_forge_lists_worn_and_bag_gear_and_refines_either(client):
    worn = char(1, xp=8000, items=[{"id": 1}])
    player(client, "111", main_characters=[worn], items=[{"id": 1}, {"id": 1}, {"id": 4}], fragments=50_000)
    h = login(client, "111")
    page = client.get("/items", headers=h).data.decode()
    assert 'id="forge"' in page and "Refine gear" in page and "on Star platinum" in page
    rows = gear.forge_rows(type("U", (), {"main_characters": [], "items": []})())
    assert rows == []
    # the copy the team wears, refined from the Items page with a bag spare
    client.post("/items/refine", data={"item": 1, "uuid": worn["uuid"], "slot": 0}, headers={**h, "HX-Request": "true"})
    d = doc(client, "111")
    assert d["main_characters"][0]["items"][0].get("refine") == 1
    assert [i["id"] for i in d["items"]].count(1) == 1 and d["fragments"] == 50_000 - gear.refine_cost(0)


def test_refine_preview_shows_the_next_level():
    from app.game.items import Item, item_file
    knife = Item({"id": 1, "refine": 1})
    lines = gear.refine_preview(knife)
    assert lines and all(l["next"] is not None and l["next"] >= l["now"] for l in lines)
    base = item_file[0]
    dmg = next(l for l in lines if l["label"] == "ATK") if base["bonus_damage"] else None
    if dmg:
        assert dmg["next"] == round(base["bonus_damage"] * 1.2)
    assert all(l["next"] is None for l in gear.refine_preview(Item({"id": 1, "refine": gear.REFINE_MAX})))
