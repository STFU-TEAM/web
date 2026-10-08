"""Slower progression (app/game/economy.py) and the stands page's cosmetic previews."""
from test_app import client  # noqa: F401  (client is a fixture)


def test_economy_rounding():
    from app.game import economy
    assert economy.dust(1000) == 600 and economy.dust(150) == 90 and economy.dust(20) == 12
    assert economy.stand_xp(100) == 80 and economy.stand_xp(1) == 1 and economy.stand_xp(0) == 0
    assert [economy.heads(n) for n in (0, 1, 2, 3, 5)] == [0, 1, 1, 2, 3]   # one-time: a single one is kept
    assert [economy.heads(n, recurring=True) for n in (1, 2)] == [0, 1]


def test_arrowheads_are_scarcer():
    from app.game import dex, quests, story, tower
    heads = [story.reward_for(k)["super_fragments"] for k in range(story.TOTAL)]
    bosses = [k for k, s in enumerate(story.STAGES) if s.get("boss")]
    assert sum(heads) == len(story.HEAD_PARTS) < len(bosses)
    assert story.reward_for(bosses[0])["super_fragments"] == 1          # the first boss still pays one
    assert [f for f in range(1, 61) if tower.reward_for(f)["super"]] == [20, 40, 60]
    weekly = [q for q in quests.ALL_QUESTS if q["category"] in ("daily", "weekly")]
    assert sum(q["rewards"].get("super_fragments", 0) for q in weekly) == 2   # was 4
    assert dex.RARITY_REWARDS["SR"].get("super", 0) == 0 and dex.RARITY_REWARDS["LR"]["super"] == 3


def test_time_gates_are_longer():
    from app.game import logic
    assert logic.ENERGY_REGEN_MINUTES == 6 and logic.DONOR_ENERGY_REGEN_MINUTES == 4
    assert logic.DONOR_ADV_WAIT_TIME + logic.NORMAL_ADV_WAIT_TIME == 16
    assert logic.SHOP_HEADS_PER_WEEK == 2


def test_stands_page_previews_cosmetics(client):
    page = client.get("/stands").data.decode()
    assert "Cosmetics" in page and "Shiny full art" in page and "Unique art only" in page
    shiny = client.get("/stands?look=both", headers={"HX-Request": "true"}).data.decode()
    assert "card " in shiny and " fullart" in shiny and " shiny" in shiny and "shown as shiny full art" in shiny
    plain = client.get("/stands", headers={"HX-Request": "true"}).data.decode()
    assert " fullart" not in plain and "shiny-badge" not in plain
    assert "No stand" not in client.get("/stands?look=junk", headers={"HX-Request": "true"}).data.decode()


def test_unique_art_filter_keeps_only_illustrated_stands(client):
    art = client.application.extensions["art_files"]
    owned = sorted(set(art["artwork"]) | set(art["shiny"]))
    page = client.get("/stands?unique=1", headers={"HX-Request": "true"}).data.decode()
    assert f"{len(owned)} stand" in page
    page = client.get("/stands?unique=1&look=shiny", headers={"HX-Request": "true"}).data.decode()
    assert f"{len(art['shiny'])} stand" in page
