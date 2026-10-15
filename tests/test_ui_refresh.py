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


def test_pages_carry_the_text_size_setting_and_the_transition_fallback(client):
    page = client.get("/").data.decode()
    assert 'name="density" value="compact"' in page and 'name="density" value="comfy"' in page
    head = page.split("</head>")[0]
    assert 'localStorage.getItem("density")' in head and '"onpagereveal" in window' in head and "vt-enter" in head


def test_pve_menus_draw_the_world_map_wormholes_theatre_sky_and_targets(client):
    from app.game import worldmap
    rows = [{"part": None, "title": "Prologue · The Arrow", "color": "#999", "cleared": 1, "stages": [1]},
            {"part": 3, "title": "Part 3 · Stardust Crusaders", "color": "#7A3FB8", "cleared": 2, "stages": [1] * 5},
            {"part": 4, "title": "Part 4 · Diamond is Unbreakable", "color": "#D6246E", "cleared": 0, "stages": [1] * 5}]
    wm = worldmap.view(rows)
    assert [p["part"] for p in wm["pins"]] == [0, 3, 4] and [p["current"] for p in wm["pins"]] == [False, True, False]
    assert all(0 <= p["x"] <= 100 and 0 <= p["y"] <= 100 for p in wm["pins"])
    player(client, "111", main_characters=[char(1, xp=2000), char(2, xp=2000), char(5, xp=2000)], web_story={"cleared": 8})
    login(client, "111")
    assert 'class="world-map"' in client.get("/story").data.decode() and 'id="part-3"' in client.get("/story").data.decode()
    assert 'class="rifts"' in client.get("/alternate-universe").data.decode()


def test_refining_strengthens_an_items_ability_and_the_forge_says_so():
    from app.game import gear
    from app.game.character import character_from_dict
    from app.game.items import item_from_dict
    grown = []
    for refine in (0, 5):
        ch = character_from_dict({"id": 1, "xp": 5000, "types": ["ATTACK"], "qualities": ["GOOD"], "items": []})
        before = ch.current_damage
        item_from_dict({"id": 7, "refine": refine}).special(ch, [ch], [])  # the Stone Mask
        grown.append(ch.current_damage - before)
    assert grown[1] > grown[0] * 1.45
    rows = gear.refine_preview(item_from_dict({"id": 7, "refine": 2}))
    assert {"label": "Ability", "now": "+20%", "next": "+30%"} in rows


def test_special_numbers_explain_their_power(client):
    import re
    from app.filters import special_text
    from app.game.character import character_from_dict
    with client.application.test_request_context():
        ch = character_from_dict({"id": 111, "xp": 8000, "types": ["ATTACK"], "qualities": ["GREAT"], "items": []})  # Tusk Act 1
        tip = re.findall(r'data-tip="([^"]*)"', str(special_text(ch)))[0]
    assert "1.12 power (1 + 12% Attack Great type)" in tip and "Grows with ATK" in tip
