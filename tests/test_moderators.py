"""Moderators (moderation tools only, never grants or edits) and badges (the STFU Team, Moderator and earned ones,
the main badge shown in the chats)."""
from app.game import badges, chat as C
from app.game.user import User
from test_app import char, client, doc, login  # noqa: F401  (client is a fixture)
from test_features import player


def test_admins_add_moderators_who_moderate_but_never_give(client):
    client.application.config["DISCORD_ADMIN_IDS"] = {"111"}
    for uid in ("111", "222", "333"):
        player(client, uid)
    h = login(client, "111")
    client.post("/admin/roles/mod/add", data={"player": "222"}, headers=h)
    assert client.fake.hexists("web:moderators", "222")

    h = login(client, "222")
    assert client.get("/admin").status_code == 302  # a moderator's panel starts at the reports
    assert client.get("/admin/reports").status_code == 200
    page = client.get("/admin/player/333").data.decode()
    assert "Mute in the chats" in page and "Ban from website" in page
    assert "Grant" not in page and "Edit a value" not in page and "Raw save" not in page and "Delete this save" not in page
    client.post("/admin/player/333/mute", data={"hours": "1", "reason": "spam"}, headers=h)
    assert C.muted("333")
    before = doc(client, "333")["fragments"]
    assert client.post("/admin/player/333/grant", data={"kind": "fragments", "amount": "1000"}, headers=h).status_code == 403
    assert client.post("/admin/player/333/set", data={"field": "fragments", "value": "999999"}, headers=h).status_code == 403
    assert doc(client, "333")["fragments"] == before
    for path in ("/admin/admins", "/admin/stats", "/admin/news", "/admin/player/333/raw"):
        assert client.get(path).status_code == 403
    assert client.post("/admin/roles/mod/add", data={"player": "333"}, headers=h).status_code == 403
    nav = client.get("/story").data.decode().split("<main")[0]
    assert 'href="/admin"' in nav and "Moderation" in nav


def test_badges_show_on_the_profile_and_the_main_one_in_chats(client):
    client.application.config["DISCORD_ADMIN_IDS"] = {"111"}
    player(client, "111")
    player(client, "222", storage_characters=[{**char(1), "shiny": True}])
    client.fake.hset("web:moderators", "222", "{}")
    with client.application.test_request_context():
        assert badges.earned(User(doc(client, "111")))[0] == "team"
        assert badges.earned(User(doc(client, "222")))[:2] == ["mod", "shiny"]
        shown = badges.main_of(["111", "222", "999"])
        assert shown["111"]["key"] == "team" and shown["222"]["key"] == "mod" and "999" not in shown  # staff show by default

    h = login(client, "222")
    page = client.get("/u/222").data.decode()
    assert "🛡 Moderator" in page and "Shiny hunter" in page and 'name="badge"' in page
    client.post("/profile", data={"badge": "shiny", "title": ""}, headers=h)
    with client.application.test_request_context():
        assert badges.main_of(["222"])["222"]["key"] == "shiny"
    with client.application.app_context():
        C.post(C.resolve("global", "222"), "222", "hello from a mod")
    assert "Shiny hunter" in client.get("/chat").data.decode()
    client.post("/profile", data={"badge": "team", "title": ""}, headers=h)  # not theirs: refused
    with client.application.test_request_context():
        assert badges.main_of(["222"])["222"]["key"] == "shiny"
