"""Story-gated modes: Mirror World, Tower and Dungeon open after the first story fight, Ranked after Part 3, and
each new mode is tagged New (nav, story page, battle page) until the player opens it."""
import json

import pytest

from app.game import progression, story
from test_app import char, client, doc, login, put  # noqa: F401  (client is a fixture)
from test_features import _win_story_fight, player

REAL_GATES = dict(progression.GATES)


@pytest.fixture()
def gated(client, monkeypatch):
    monkeypatch.setattr(progression, "GATES", REAL_GATES)  # the shared fixture opens everything
    return client


def _fighter(c, cleared=0):
    player(c, "111", energy=10, main_characters=[char(1, xp=3000)], web_story={"cleared": cleared})
    c.fake.delete("web:story_cleared:111")
    return login(c, "111")


def _inbox(c):
    return [json.loads(n)["text"] for n in c.fake.lrange("web:notif:111", 0, -1)]


def test_gates_follow_the_story():
    assert progression.GATES["wormhole"] == progression.GATES["tower"] == progression.GATES["dungeon"] == 1
    assert progression.GATES["ranked"] == progression.done_at(3) == progression.GATES["altverse"]
    assert story.STAGES[progression.GATES["ranked"] - 1]["boss"] and story.STAGES[progression.GATES["ranked"]]["part"] == 4
    assert progression.requirement("tower") == "Win your first story fight"
    assert progression.requirement("ranked") == "Finish Part 3 · Stardust Crusaders in the story"
    assert progression.next_unlock(0) == (1, ["Mirror World", "Tower", "Dungeon", "Daily puzzle"])
    assert progression.next_unlock(1, skip=("dungeon",)) == (progression.done_at(3) - 1, ["Ranked", "Alternate Universe"])
    assert progression.next_unlock(story.TOTAL) is None


def test_side_modes_open_after_the_first_story_fight(gated):
    c = gated
    h = _fighter(c)
    page = c.get("/battles").data.decode()
    for key in ("wormhole", "tower", "dungeon", "ranked"):
        assert f'data-tour="{key}"' not in page, key
    assert 'data-tour="planner"' in page and 'data-tour="simulator"' in page  # always there, under Collection
    assert c.get("/tower").headers["Location"].endswith("/story")
    assert c.get("/mirror-world").headers["Location"].endswith("/story")
    c.post("/mirror-world/start", headers=h)
    assert c.fake.get("web:fight:111") is None
    assert "This fight opens" in c.get("/story").data.decode()

    _win_story_fight(c, h)
    opened = {"wormhole", "tower", "puzzle"} | ({"dungeon"} if c.application.config.get("DUNGEON_ENABLED") else set())
    assert set(progression.new("111")) == opened
    assert any("Unlocked: Mirror World, Tower" in t for t in _inbox(c))
    page = c.get("/story").data.decode()
    assert "Just unlocked" in page and 'data-tour="tower"' in page and 'data-tour="ranked"' not in page
    assert page.count('class="nav-badge new"') >= len(opened)

    assert c.get("/tower").status_code == 200  # opening a mode clears its New tag
    assert "tower" not in progression.new("111") and "wormhole" in progression.new("111")
    c.post("/unlocks/dismiss", headers=h)
    assert progression.new("111") == []
    assert "Just unlocked" not in c.get("/story").data.decode()


def test_ranked_opens_after_part_3_and_is_announced(gated):
    c = gated
    h = _fighter(c, cleared=progression.done_at(3) - 1)  # DIO is next
    page = c.get("/battles?mode=ranked").data.decode()
    assert "Continue the story" in page and "Join ranked queue" not in page and 'data-tour="ranked"' not in page
    assert c.post("/battles/ranked/queue", headers=h).headers["Location"].endswith("/story")
    assert c.post("/battles/ranked/roster", headers=h).headers["Location"].endswith("/story")

    _win_story_fight(c, h)
    assert doc(c, "111")["web_story"]["cleared"] == progression.done_at(3)
    assert {"ranked", "altverse"} <= set(progression.new("111"))
    assert any("Ranked is open" in t for t in _inbox(c))
    page = c.get("/battles").data.decode()
    assert 'data-tour="ranked"' in page and "unlock-card ranked" in page
    page = c.get("/battles?mode=ranked").data.decode()
    assert "Ranked roster" in page and "ranked" not in progression.new("111")


def test_turned_away_by_another_fight_shows_the_way_back(client):
    """Every "finish your fight first" carries a button to the fight that's on (the right page, tab or chapter)."""
    import app.db as dbmod
    from app.game.fight import Fight, Side
    from app.game.character import character_from_dict
    from app.routes.fightturn import resume
    player(client, "111", energy=10, main_characters=[char(1, xp=3000)], web_story={"cleared": story.TOTAL})
    h = login(client, "111")
    f = Fight(Side("A", [character_from_dict(char(1))], True), Side("B", [character_from_dict(char(2))], False),
              kind="over_heaven", meta={"track": "tower", "stage": 0})
    dbmod.save_fight("111", f)
    page = client.get("/carry-me").data.decode()
    assert "Back to your Over Heaven fight" in page and "/over-heaven?t=tower#fight" in page
    # a flashed refusal carries it too (the dungeon's "finish the fight you're in")
    client.post("/adventure/dungeon/fight", headers=h)
    page = client.get("/story").data.decode()
    assert "Finish the fight you" in page and page.count("Back to your Over Heaven fight") >= 1
    with client.application.test_request_context():
        assert resume("111")["kind"] == "over_heaven" and resume("nobody") is None
    f.finished = True
    dbmod.save_fight("111", f)
    assert "Back to your" not in client.get("/carry-me").data.decode()  # nothing on, no button
