"""The Torn Diary Page (The World Over Heaven, sealed) and the ★5 cap on stat scaling."""
import pytest

from app.game.character import CHARACTER_FILE, character_from_dict
from test_app import char, client, doc, login, put  # noqa: F401  (client is a fixture)
from test_features import player


def test_stars_past_five_are_kept_but_scale_like_five():
    five = character_from_dict({"id": 1, "xp": 10000, "awaken": 5, "types": [], "qualities": [], "items": []})
    seven = character_from_dict({"id": 1, "xp": 10000, "awaken": 7, "types": [], "qualities": [], "items": []})
    assert seven.awaken == 7 and seven.to_dict()["awaken"] == 7
    for stat in ("start_hp", "start_damage", "start_speed", "start_armor", "start_critical"):
        assert getattr(seven, stat) == getattr(five, stat), stat


def test_a_sealed_over_heaven_is_an_ordinary_mythic():
    from app.game import altverse
    raw = CHARACTER_FILE[110 - 1]
    boss = altverse.enemy_team("world_unbroken", 4)
    sealed = altverse.enemy_team("world_unbroken", 4, sealed=True)
    twoh, seal = next(c for c in boss if c.id == 110), next(c for c in sealed if c.id == 110)
    assert twoh.start_hp > 100_000 and not twoh.sealed               # the raid boss nobody can beat
    gold = next(c for c in sealed if c.id == 10)                     # The World, same level, beside it
    assert seal.sealed and seal.start_hp < 3 * gold.start_hp and seal.start_damage < 3 * gold.start_damage
    assert raw["base_hp"] == 999999  # the data is untouched: only the sealed copy changes
    from app.game.fight import Fight, Side
    fight = Fight(Side("A", [character_from_dict({"id": 1, "xp": 10000, "awaken": 5, "types": [], "qualities": [], "items": []})], True),
                  Side("B", sealed, False))
    seal = next(c for c in fight.sides[1].chars if c.id == 110)
    seal.special_meter = 99
    _payload, message = seal.special(fight.sides[1].chars, fight.sides[0].chars)
    assert "STOPS TIME" in message  # The World's time stop, not the 1000x hit


def test_the_page_is_handed_over_bound_and_seals_the_au_boss(client):
    import app.db as dbmod
    from app.game import altverse
    from app.game.items import TORN_DIARY_PAGE
    player(client, "111", main_characters=[char(1)], web_story={"cleared": altverse._boss_index(3) + 1},
           web_au={"cleared": {"world_unbroken": 4}}, energy=10)
    h = login(client, "111")
    client.post("/alternate-universe/fight", data={"chapter": "world_unbroken"}, headers=h)
    d = doc(client, "111")
    assert any(i["id"] == TORN_DIARY_PAGE for i in d["items"])
    fight = dbmod.load_fight("111")
    twoh = next(c for c in fight.sides[1].chars if c.id == 110)
    assert twoh.sealed and twoh.start_hp < 100_000
    assert any("Torn Diary Page burns" in e["text"] for e in fight.log)
    # bound: not sellable, not tradable, not listable
    from app.game import logic, trades
    from app.game.logic import GameError
    from app.game.user import User
    with pytest.raises(GameError, match="can't be sold"):
        logic.sell_item(User(d), TORN_DIARY_PAGE)

    class Form(dict):
        def getlist(self, k):
            return self.get(k, [])
    side = trades.parse_side(Form(give_item=[f"{TORN_DIARY_PAGE}:1", "1:1"]), "give")
    assert side["items"] == {"1": 1}
    # no second page next time
    client.post("/battles/leave", headers=h)
    dbmod.clear_fight("111")
    client.post("/alternate-universe/fight", data={"chapter": "world_unbroken"}, headers=h)
    assert sum(i["id"] == TORN_DIARY_PAGE for i in doc(client, "111")["items"]) == 1
