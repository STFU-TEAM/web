"""Launch pieces: link previews, the landing page, legal pages, the changelog, share cards, the first week, dev tools."""
import datetime

from app.game import onboarding
from test_app import char, client, doc, login, put  # noqa: F401  (client is a fixture)
from test_features import player


def test_pages_carry_link_preview_tags(client):
    home = client.get("/").data.decode()
    assert 'property="og:image"' in home and "randomAsset/avatar.png" in home and 'name="twitter:card"' in home
    stand = client.get("/stands/1").data.decode()
    assert 'property="og:title" content="Star platinum | STFU Requiem"' in stand and "/Image/1.png" in stand


def test_the_landing_page_sells_the_game_to_visitors_only(client):
    page = client.get("/").data.decode()
    assert "Play free" in page and "What waits for you" in page and "How it works" in page
    player(client, "301", main_characters=[char(1)])
    login(client, "301")
    page = client.get("/").data.decode()
    assert "What waits for you" not in page and "How it works" not in page


def test_legal_pages_changelog_robots_and_sitemap(client):
    assert "Privacy policy" in client.get("/privacy").data.decode()
    assert "Terms of use" in client.get("/terms").data.decode()
    assert "What's new" in client.get("/changelog").data.decode()
    footer = client.get("/").data.decode()
    assert "/privacy" in footer and "/terms" in footer and "/changelog" in footer
    robots = client.get("/robots.txt").data.decode()
    assert "Disallow: /admin" in robots and "Sitemap:" in robots
    sitemap = client.get("/sitemap.xml").data.decode()
    assert "/stands/1</loc>" in sitemap and "/wiki/guide</loc>" in sitemap


def test_share_cards_only_show_what_the_player_has(client):
    mine = char(10, xp=4000, awaken=2)
    player(client, "302", main_characters=[mine])
    h = login(client, "302", name="Jotaro")
    r = client.post("/share", data={"kind": "stand", "ref": mine["uuid"]}, headers=h)
    data = r.get_json()
    assert r.status_code == 200 and "/s/" in data["url"] and "TheWorld ★2" in data["title"]
    card = client.get(data["url"].split("localhost")[-1]).data.decode()
    assert "Jotaro pulled" in card and 'property="og:image"' in card and "/Image/10.png" in card and "Play free" not in card
    client.get("/auth/logout")
    with client.session_transaction() as s:
        s.clear()
    assert "Play free" in client.get(data["url"].split("localhost")[-1]).data.decode()  # a visitor gets the way in
    h = login(client, "302", name="Jotaro")
    assert client.post("/share", data={"kind": "stand", "ref": "not-mine"}, headers=h).status_code == 400
    assert client.post("/share", data={"kind": "requiem", "ref": "story"}, headers=h).status_code == 400
    assert client.post("/share", data={"kind": "profile"}, headers=h).status_code == 200
    assert client.get("/s/nope").status_code == 404


def test_the_beginners_path_pays_each_step_once(client):
    player(client, "303", main_characters=[char(1), char(4), char(5)], fragments=0, web_story={"cleared": 1})
    h = {**login(client, "303"), "HX-Request": "true"}
    page = client.get("/").data.decode()
    assert "Beginner's path" in page
    r = client.post("/path/claim", data={"step": "team"}, headers=h).data.decode()
    assert "300 Meteor Dust" in r and doc(client, "303")["fragments"] == 300
    client.post("/path/claim", data={"step": "team"}, headers=h)  # once only
    assert doc(client, "303")["fragments"] == 300
    r = client.post("/path/claim", data={"step": "part3"}, headers=h).data.decode()
    assert "Not done yet" in r and doc(client, "303")["super_fragments"] == 0
    client.post("/mirror-world/start", headers=h)
    assert doc(client, "303")["web_path_flags"]["mirror"] == 1  # starting a Mirror World fight marks the step
    assert "Fight in the Mirror World" in client.get("/").data.decode()


def test_the_welcome_week_gives_one_gift_a_day_to_new_saves(client):
    today = datetime.date.today().isoformat()
    player(client, "304", main_characters=[char(1)], fragments=0, super_fragments=0,
           web_welcome={"start": today, "claimed": 0, "last": None})
    h = {**login(client, "304"), "HX-Request": "true"}
    assert 'id="ww-h"' in client.get("/").data.decode()
    client.post("/welcome-week/claim", headers=h)
    d = doc(client, "304")
    assert d["super_fragments"] == onboarding.WELCOME[0]["super"] and d["web_welcome"]["claimed"] == 1
    r = client.post("/welcome-week/claim", headers=h).data.decode()
    assert "tomorrow" in r and doc(client, "304")["web_welcome"]["claimed"] == 1
    d = doc(client, "304")
    d["web_welcome"]["last"] = "2000-01-01"  # as if it were the next day
    put(client, d)
    client.post("/welcome-week/claim", headers=h)
    assert doc(client, "304")["web_welcome"]["claimed"] == 2
    player(client, "305", main_characters=[char(1)])  # an older save: no welcome week
    login(client, "305")
    assert 'id="ww-h"' not in client.get("/").data.decode()  # no welcome-week panel


def test_a_new_save_starts_its_welcome_week(client):
    from app.game.user import User
    from app.game.logic import begin
    from app.game.user import create_user
    u = User(create_user("306"))
    begin(u)
    assert u.data["web_welcome"]["claimed"] == 0 and onboarding.welcome(u)["can"]


def test_dev_mode_makes_a_brand_new_test_player(client):
    player(client, "307", main_characters=[char(1)])
    h = login(client, "307")
    assert client.post("/auth/dev/fresh", headers=h).status_code == 404  # never in production
    client.application.debug = True
    try:
        assert "New test player" in client.get("/").data.decode()
        r = client.post("/auth/dev/fresh", headers=h)
        assert r.status_code == 302 and r.headers["Location"].endswith("/auth/welcome")
        with client.session_transaction() as s:
            assert s["uid"] != "307" and s["name"].startswith("test")
            new_uid = s["uid"]
        assert client.fake.hget("users", new_uid) is None  # nothing yet: the welcome screen begins the save
    finally:
        client.application.debug = False


def test_htmx_polls_skip_the_nav_and_stay_cheap(client, monkeypatch):
    import fakeredis
    player(client, "308", main_characters=[char(1)])
    h = login(client, "308")
    calls = []
    real = fakeredis.FakeRedis.execute_command
    monkeypatch.setattr(fakeredis.FakeRedis, "execute_command", lambda self, *a, **k: (calls.append(a[0]), real(self, *a, **k))[1])
    client.get("/battles/queue-bar", headers={**h, "HX-Request": "true"})
    assert len(calls) <= 6, calls  # the queue count, not the whole nav (it was 16)
    calls.clear()
    client.get("/team", headers=h)
    assert len(calls) > 10  # a full page still draws the nav


def test_a_level_up_pops_with_what_it_opened(client):
    from app.game import gates
    from app.game.user import LVLSCALING
    need = int((gates.STORY[4] / LVLSCALING) ** 2)  # the XP of the level that opens Part 4
    player(client, "309", main_characters=[char(1)], xp=need - 50, web_level=gates.STORY[4] - 1)
    h = login(client, "309")
    client.post("/daily", headers=h)  # the daily reward pays XP now: over the line
    d = doc(client, "309")
    assert d["web_level"] >= gates.STORY[4]
    toasts = [t.decode() for t in client.fake.lrange("web:notif:309", 0, -1)]  # the inbox copy (the page took the pop-up)
    assert any('"levelup"' in t and "Diamond is Unbreakable" in t for t in toasts), toasts


def test_old_saves_are_not_flooded_with_past_level_ups(client):
    player(client, "310", main_characters=[char(1)], xp=500_000)  # no web_level yet: an older save
    h = login(client, "310")
    client.post("/daily", headers=h)
    assert doc(client, "310")["web_level"] > 0
    assert not any(b'"levelup"' in t for t in client.fake.lrange("web:notif:310", 0, -1))


def test_the_daily_routine_pays_real_xp():
    from app.game import dungeon, logic, puzzle, quests, whos
    daily = [q for q in quests.ALL_QUESTS if q["category"] == "daily"]
    assert min(q["rewards"]["xp"] for q in daily if q["rewards"].get("xp")) >= 200
    assert logic.STREAK_XP >= 500 and puzzle.REWARD["xp"] >= 1500 and whos.XP_BASE >= 1000
    assert dungeon.RUN_XP_PER_FLOOR * 3 >= 1000
