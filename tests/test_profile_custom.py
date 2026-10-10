"""Profile customization (the Stand User file), reporting a profile, and the admin tools that remove a customization
and lock it. Plus the fight touches that ride on the same templates (再起不能, 勝利, the eyecatch)."""
import json

from app.game import profile as P
from app.game import story
from test_app import char, client, doc, login, put  # noqa: F401  (client is a fixture)
from test_features import player


def _me(c, uid="222", **fields):
    d = player(c, uid, main_characters=[char(1, xp=3000), char(10, xp=3000)], **fields)
    return d, login(c, uid)


def test_customize_and_see_it_on_the_profile(client):
    d, h = _me(client)
    sp = d["main_characters"][1]["uuid"]
    client.post("/profile", data={"quote": "  Yare\nyare​   daze. " + "x" * 200, "theme": "night", "stand": sp,
                                  "showcase": [sp, "not-mine"], "pins": ["nope"]}, headers=h)
    prof = doc(client, "222")["web_profile"]
    assert prof["quote"].startswith("Yare yare daze. ") and len(prof["quote"]) == P.QUOTE_MAX
    assert prof["stand"] == sp and prof["showcase"] == [sp] and prof["pins"] == []
    page = client.get("/u/222").data.decode()
    assert "user-file" in page and "「Yare yare daze." in page and "Signature stand" in page and "Customize your profile" in page
    # a theme you haven't unlocked is refused, one you have is kept
    client.post("/profile", data={"theme": "part5"}, headers=h)
    assert doc(client, "222")["web_profile"]["theme"] == "night"
    d = doc(client, "222")
    d["web_story"] = {"cleared": story.TOTAL}
    put(client, d)
    client.post("/profile", data={"theme": "part5"}, headers=h)
    assert doc(client, "222")["web_profile"]["theme"] == "part5"


def test_report_flow_and_admin_lock(client):
    client.application.config["DISCORD_ADMIN_IDS"] = {"111"}
    player(client, "111")
    _me(client)
    client.post("/profile", data={"quote": "something rude", "theme": "night"}, headers=login(client, "222"))
    player(client, "333")
    h3 = login(client, "333")
    assert "⚑ Report" in client.get("/u/222").data.decode()
    client.post("/u/222/report", data={"reason": "text", "note": "look at the catchphrase"}, headers=h3)
    client.post("/u/222/report", data={"reason": "text"}, headers=h3)  # once a day per profile
    client.post("/u/333/report", data={"reason": "text"}, headers=h3)  # not yourself
    assert client.fake.zcard(P.OPEN_KEY) == 1

    h1 = login(client, "111")
    page = client.get("/admin/reports").data.decode()
    assert "something rude" in page and "look at the catchphrase" in page and 'nav-badge new">1<' in page
    rid = next(iter(client.fake.zrange(P.OPEN_KEY, 0, -1))).decode()
    client.post(f"/admin/reports/{rid}/lock", data={"reason": "Keep it civil"}, headers=h1)
    assert doc(client, "222")["web_profile"] == {} and client.fake.zcard(P.OPEN_KEY) == 0
    assert json.loads(client.fake.hget(P.LOCKED_KEY, "222"))["reason"] == "Keep it civil"
    assert json.loads(client.fake.lindex("web:admin:audit", 0))["kind"] == "profile_lock"

    h2 = login(client, "222")
    assert "Keep it civil" in client.get("/u/222").data.decode()
    client.post("/profile", data={"quote": "again", "theme": "night"}, headers=h2)
    assert doc(client, "222")["web_profile"] == {}  # locked

    h1 = login(client, "111")
    assert "Unlock customization" in client.get("/admin/player/222").data.decode()
    client.post("/admin/player/222/profile_unlock", headers=h1)
    client.post("/profile", data={"quote": "nice now", "theme": "night"}, headers=login(client, "222"))
    assert doc(client, "222")["web_profile"]["quote"] == "nice now"


def test_admin_clears_from_the_player_page(client):
    client.application.config["DISCORD_ADMIN_IDS"] = {"111"}
    player(client, "111")
    _, h = _me(client)
    client.post("/profile", data={"quote": "hello", "theme": "night"}, headers=h)
    client.post("/admin/player/222/profile_clear", headers=login(client, "111"))
    assert doc(client, "222")["web_profile"] == {} and not client.fake.hexists(P.LOCKED_KEY, "222")


def test_a_new_title_stamps_in(client):
    d, h = _me(client)
    with client.application.app_context():
        from app.game import titles
        from app.game.user import User
        user = User(doc(client, "222"))
        assert titles.grant(user, "Over Heaven")
    toasts = [json.loads(x) for x in client.fake.lrange("web:toast:222", 0, -1)]
    assert any(t["kind"] == "title" and "Over Heaven" in t["text"] for t in toasts)


def test_fight_touches_render(client):
    d, h = _me(client)
    page = client.post("/battles/dummy/start", headers=h, follow_redirects=True).data.decode()
    assert "再起不能" in page and "data-eyecatch" not in page  # a practice fight gets no eyecatch
    page = client.post("/battles/attack", data={"forfeit": "1"}, headers=h).data.decode()
    assert "敗北" in page and "Defeat" in page
    # a story boss fight opens with the eyecatch
    boss = next(k for k, s in enumerate(story.STAGES) if s.get("boss"))
    d = doc(client, "222")
    d["web_story"] = {"cleared": boss}
    put(client, d)
    import app.db as dbmod
    dbmod.clear_fight("222")  # the finished practice fight
    client.post("/story/fight", headers=h)
    page = client.get("/story").data.decode()
    assert 'data-eyecatch="' in page and 'data-eyecatch-label="Boss fight"' in page
