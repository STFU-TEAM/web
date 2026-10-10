"""Player shops page, LR pulls and duplicates, the daily streak (growth, shield, milestones), web-only profile
pictures, news kinds and the event announcement, the news ribbon and the chat bubble."""
import datetime
import json
import pickle

from app.game import logic
from app.game.user import User, create_user
from test_app import client, doc, login, put  # noqa: F401  (client is a fixture)
from test_features import player


def test_shops_page_lists_shops_with_their_listings(client):
    player(client, "111")
    client.fake.hset("shops", "s1", pickle.dumps({"_id": "s1", "name": "Pucci Bargains", "owner": "111",
                                                  "items": [{"id": 1}, {"id": 2}], "prices": [10, 20]}))
    login(client, "111")
    page = client.get("/shops").data.decode()
    assert "Pucci Bargains" in page and "2 listings" in page


def test_lr_odds_and_duplicates_in_a_pull():
    assert abs(sum(logic.BANNER_ODDS.values()) - 1) < 1e-9 and logic.BANNER_ODDS["LR"] == 0.002
    assert abs(sum(logic.ARROW_ODDS.values()) - 1) < 1e-9 and logic.PITY_ODDS["LR"] == 0.33
    banner = {"id": 99, "name": "t", "cards": [1, 2], "cost": 1}
    user = User(create_user("1"))
    drawn = [logic._banner_draw(banner, user, forced="SSR").id for _ in range(12)]
    assert drawn.count(1) == 12  # one SSR on the banner: no copy protection, every pull can repeat it


def test_daily_streak_grows_survives_one_missed_day_and_pays_milestones(monkeypatch):
    clock = [datetime.datetime(2026, 3, 1, 9)]
    monkeypatch.setattr(logic, "now", lambda: clock[0])
    user = User(create_user("1"))
    day = datetime.date(2026, 3, 1)
    supers, results = user.super_fragments, []
    for i in range(15):
        d = day + datetime.timedelta(days=i + (1 if i >= 9 else 0))  # skip one day after day 9
        clock[0] = datetime.datetime.combine(d, datetime.time(9))
        user.last_adventure = datetime.datetime.min
        results.append(logic.daily(user)["streak"])
    assert results[9]["shielded"] and results[9]["count"] == 10  # the shield kept it
    assert results[13]["milestone"]["day"] == 14 and user.super_fragments >= supers + 3  # two day-7s and day 14
    assert results[7]["fragments"] == round(70 * 1.2)  # week 2 pays 20% more Dust
    s = logic.streak(user)
    assert s["goal"] == 30 and not s["shield_ready"]


def test_web_only_players_set_a_profile_picture(client):
    from app import accounts
    with client.application.app_context():
        acc = accounts.create_account("jolyne", "a-good-password")
    uid = acc["uid"]
    put(client, create_user(uid))
    h = login(client, uid)
    assert 'name="avatar"' in client.get(f"/u/{uid}").data.decode()
    client.post("/profile", data={"theme": "night", "avatar": "https://i.imgur.com/abc123.png"}, headers=h)
    assert json.loads(client.fake.get(f"web:identity:{uid}"))["avatar"] == "https://i.imgur.com/abc123.png"
    client.post("/profile", data={"theme": "night", "avatar": "https://evil.example.com/x.png"}, headers=h)
    assert doc(client, uid)["web_profile"]["avatar"] == "https://i.imgur.com/abc123.png"  # refused
    # a Discord player doesn't get the field (their Discord picture is used)
    put(client, create_user("222"))
    login(client, "222")
    assert 'name="avatar"' not in client.get("/u/222").data.decode()


def test_events_announce_themselves_and_news_comes_first(client):
    client.application.config["DISCORD_ADMIN_IDS"] = {"111"}
    player(client, "111")
    h = login(client, "111")
    today = logic.now().date()
    client.post("/admin/events", data={"op": "create", "name": "Golden Week", "blurb": "Dust everywhere.",
                                       "start": today.isoformat(), "end": (today + datetime.timedelta(days=7)).isoformat(),
                                       "kind": "dust"}, headers=h)
    posts = [json.loads(v) for v in client.fake.hvals("web:news:posts")]
    assert len(posts) == 1 and posts[0]["kind"] == "event" and "Golden Week" in posts[0]["title"]
    client.post("/admin/news", data={"kind": "patch", "title": "Patch 2.4", "body": "Chat, raids and more."}, headers=h)
    from app import news
    news._latest["at"] = 0
    page = client.get("/").data.decode()
    assert "patch-card" in page and "Patch 2.4" in page
    assert page.index("What's new") < page.index("Today") if "Today" in page else True
    assert 'data-news-ribbon=' in client.get("/story").data.decode()
    assert "chat-bubble" in client.get("/story").data.decode()
