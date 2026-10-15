"""The UI refresh: part watermarks, the team on stage, the story road, the star-up moment, stand level-ups, sound."""
import json

from app.game import parts
from app.game.user import User
from test_app import char, client, doc, login, put  # noqa: F401  (client is a fixture)
from test_features import player


def test_every_part_has_a_watermark_and_pages_draw_it(client):
    assert all(parts.mark(p).startswith("<svg") for p in parts.COLORS) and parts.mark(None) == ""
    player(client, "111", main_characters=[char(1, xp=2000), char(2, xp=2000), char(5, xp=2000)], web_story={"cleared": 12})
    login(client, "111")
    page = client.get("/").data.decode()
    assert 'class="part-mark"' in page and "data-sound-menu" in page  # the part you're on, and the sound menu


def test_home_puts_the_team_on_stage_and_the_story_is_a_road(client):
    player(client, "111", main_characters=[char(1, xp=2000), char(2, xp=2000), char(5, xp=2000)], web_story={"cleared": 2})
    login(client, "111")
    home = client.get("/").data.decode()
    assert 'class="team-stage"' in home and "Your team" in home and home.count('class="ts-slot"') == 3
    assert "Your stand awakens here." not in home  # the visitor hero is for visitors
    story = client.get("/story").data.decode()
    assert 'class="story-map road"' in story and "--done:" in story and 'class="node-you"' in story


def test_a_new_star_tells_the_page_what_changed(client):
    keeper = char(1, xp=2500)
    player(client, "111", main_characters=[keeper], storage_characters=[char(1)])
    h = {**login(client, "111"), "HX-Request": "true"}
    r = client.post("/team/awaken", data={"uuid": keeper["uuid"]}, headers=h)
    star = json.loads(r.headers["HX-Trigger-After-Settle"])["starUp"]
    assert star["star"] == 1 and star["hp"][1] > star["hp"][0] and star["img"]
    r = client.post("/team/awaken", data={"uuid": keeper["uuid"]}, headers=h)  # no copy left: no moment
    assert "HX-Trigger-After-Settle" not in r.headers


def test_team_stands_that_level_up_pop_a_toast(client):
    from app.db import r
    stand = char(1, xp=1950)
    player(client, "111", main_characters=[stand])
    u = User(doc(client, "111"))
    u._note_stand_levels()  # the first save only records the levels
    assert not r().lrange("web:toast:111", 0, -1)
    u.main_characters[0].xp += 100  # Lv 19 -> 20
    u._note_stand_levels()
    toasts = [json.loads(t) for t in r().lrange("web:toast:111", 0, -1)]
    assert toasts and toasts[-1]["kind"] == "standup" and "level 20" in toasts[-1]["text"] and "new star" in toasts[-1]["text"]
