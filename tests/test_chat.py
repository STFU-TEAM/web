"""The chats (global, private, raid), open co-op lobbies, chat moderation, and milestone titles."""
import json

import app.db as dbmod
from app.game import chat as C
from app.game import coop, story
from test_app import char, client, doc, login, put  # noqa: F401  (client is a fixture)
from test_coop import _as, _lobby_with_party, _players
from test_features import player


def test_global_chat(client):
    player(client, "111")
    player(client, "222")
    h = login(client, "111")
    assert "Chat" in client.get("/story").data.decode()  # in the nav
    client.post("/chat/c/global", data={"text": "  Yare   yare\n\n\n\ndaze  "}, headers=h, environ_base={"HTTP_HX_REQUEST": "true"})
    msgs = json.loads(client.fake.lindex("web:chat:global", -1))
    assert msgs["text"] == "Yare yare\n\ndaze" and msgs["uid"] == "111"
    assert "Slow down" in client.post("/chat/c/global", data={"text": "again"}, headers={**h, "HX-Request": "true"}).data.decode()
    page = client.get("/chat").data.decode()
    assert "Yare yare" in page and "chat-global" in page
    seq = C.seq(C.Channel("global", "global", "global"))
    assert client.get(f"/chat/c/global?seq={seq}", headers=h).status_code == 204  # nothing new
    # someone else can't delete it, but can report it
    h2 = login(client, "222")
    client.post(f"/chat/c/global/{msgs['id']}/delete", headers=h2)
    assert client.fake.llen("web:chat:global") == 1
    client.post(f"/chat/c/global/{msgs['id']}/report", headers=h2)
    report = json.loads(next(iter(client.fake.hvals("web:reports"))))
    assert report["reason"] == "chat" and report["seen"]["message"]["text"].startswith("Yare")


def test_private_messages(client):
    player(client, "111")
    player(client, "222")
    h = login(client, "111")
    assert "✉ Message" in client.get("/u/222").data.decode()
    client.post("/chat/c/dm-222", data={"text": "hello there"}, headers=h)
    assert client.fake.hget("web:dm:unread:222", "111") == b"1"
    toasts = [json.loads(x) for x in client.fake.lrange("web:toast:222", 0, -1)]
    assert any(t["kind"] == "dm" and "hello there" in t["text"] for t in toasts)
    h2 = login(client, "222")
    page = client.get("/chat?tab=messages").data.decode()
    assert "conv-list" in page and 'nav-badge">1<' in page
    assert "hello there" in client.get("/chat/dm/111").data.decode()
    assert not client.fake.hexists("web:dm:unread:222", "111")  # read
    # a third player can't read their conversation
    player(client, "333")
    h3 = login(client, "333")
    assert client.get("/chat/c/dm-111", headers=h3).status_code == 200  # 333's own (empty) conversation with 111
    assert "hello there" not in client.get("/chat/c/dm-111", headers=h3).data.decode()
    # blocking, and friends-only
    login(client, "222")
    client.post("/chat/dm/111/block", data={"on": "1"}, headers=h2)
    h = login(client, "111")
    client.fake.delete("web:chat:slow:111")
    client.post("/chat/c/dm-222", data={"text": "still there?"}, headers=h)
    assert client.fake.llen(f"web:chat:{C.dm_key('111', '222')}") == 1
    login(client, "333")
    client.post("/chat/settings", data={"friends_only": "1"}, headers=h3)
    login(client, "111")
    client.fake.delete("web:chat:slow:111")
    client.post("/chat/c/dm-333", data={"text": "hi stranger"}, headers=h)
    assert not client.fake.exists(f"web:chat:{C.dm_key('111', '333')}")


def test_raid_chat_and_open_lobbies(client):
    uids = _players(client, 3)
    h = _as(client, uids[0])
    client.post("/coop/create", data={"tier": "normal", "open": "1"}, headers=h)
    lb = coop.lobby_of(uids[0])
    assert lb["open"] and lb["chat"]
    page = client.get("/coop", headers=_as(client, uids[1])).data.decode()
    assert "Open lobbies" in page and lb["code"] in page
    client.post("/coop/join", data={"code": lb["code"]}, headers=_as(client, uids[1]))
    token = f"raid-{lb['chat']}"
    client.post(f"/chat/c/{token}", data={"text": "I bring Star Platinum"}, headers=_as(client, uids[1]))
    page = client.get("/coop", headers=_as(client, uids[0])).data.decode()
    assert "Raid chat" in page and "I bring Star Platinum" in page
    # an outsider can't read or write it
    h3 = _as(client, uids[2])
    assert client.get(f"/chat/c/{token}", headers=h3).status_code == 286
    client.post(f"/chat/c/{token}", data={"text": "let me in"}, headers=h3)
    assert client.fake.llen(f"web:chat:raid:{lb['chat']}") == 1
    # the host closes the list; then starts: the chat carries into the fight
    client.post("/coop/open", data={"on": "0"}, headers=_as(client, uids[0]))
    assert "Open lobbies" not in client.get("/coop", headers=h3).data.decode()
    for uid in uids[:2]:
        client.post("/coop/pick", data={"uuid": doc(client, uid)["main_characters"][0]["uuid"]}, headers=_as(client, uid))
    client.post("/coop/start", headers=_as(client, uids[0]))
    f = dbmod.load_fight(uids[0])
    assert f.meta["chat"] == lb["chat"]
    assert "I bring Star Platinum" in client.get("/coop", headers=_as(client, uids[1])).data.decode()


def test_admin_mutes_and_deletes(client):
    client.application.config["DISCORD_ADMIN_IDS"] = {"111"}
    player(client, "111")
    player(client, "222")
    h2 = login(client, "222")
    client.post("/chat/c/global", data={"text": "something rude"}, headers=h2)
    msg = json.loads(client.fake.lindex("web:chat:global", -1))
    h1 = login(client, "111")
    client.post(f"/chat/c/global/{msg['id']}/delete", headers=h1)
    assert client.fake.llen("web:chat:global") == 0
    assert json.loads(client.fake.lindex("web:admin:audit", 0))["kind"] == "chat_delete"
    client.post("/admin/player/222/mute", data={"hours": "24", "reason": "Keep it civil"}, headers=h1)
    h2 = login(client, "222")
    client.fake.delete("web:chat:slow:222")
    page = client.post("/chat/c/global", data={"text": "again"}, headers={**h2, "HX-Request": "true"}).data.decode()
    assert "muted you" in page and client.fake.llen("web:chat:global") == 0
    client.post("/chat/c/dm-111", data={"text": "sorry, can I be unmuted?"}, headers=h2)  # writing to an admin is fine
    assert client.fake.llen(f"web:chat:{C.dm_key('111', '222')}") == 1
    client.post("/admin/player/222/unmute", headers=login(client, "111"))
    assert C.muted("222") is None


def test_milestone_titles(client):
    d = player(client, "222", main_characters=[char(1, xp=3000, awaken=5)], tower_level=31)
    d["web_story"] = {"cleared": story.TOTAL}
    put(client, d)
    h = login(client, "222")
    with client.application.app_context():
        from app.game import titles
        from app.game.achievements import check_achievements
        from app.game.user import User
        user = User(doc(client, "222"))
        check_achievements(user, "fight_win", 0)
        earned = set(user.data["web_titles"])
    assert {"Stardust Crusader", "Wall Eyes Witness", "Tower Climber", "Requiem Bearer"} <= earned
    assert "Heaven's Staircase" not in earned
    put(client, user.data)
    client.post("/profile", data={"theme": "night", "title": "Requiem Bearer"}, headers=h)
    assert client.fake.hget(titles.SHOWN_KEY, "222") == b"Requiem Bearer"
    client.post("/chat/c/global", data={"text": "ora"}, headers=h)
    assert "✦ Requiem Bearer" in client.get("/chat").data.decode()
    assert "Milestone titles" in client.get("/u/222").data.decode()


def test_the_bubble_holds_every_chat_with_red_dots_for_dms_and_the_gang(client):
    player(client, "111", fragments=50_000)
    player(client, "222")
    h = login(client, "111")
    client.post("/gangs/create", data={"name": "Crusaders"}, headers=h)
    gid = doc(client, "111")["gang_id"]
    client.post("/gangs/invite", data={"user_id": "222"}, headers=h)
    h2 = login(client, "222")
    client.post(f"/gangs/join/{gid}", headers=h2)
    # 222 messages the gang and 111 privately: 111 gets two red dots
    client.post("/gangs/chat", data={"text": "raid tonight?"}, headers={**h2, "HX-Request": "true"})
    client.post("/chat/c/dm-111", data={"text": "psst"}, headers=h2)
    assert client.fake.get("web:gang:unread:111") == b"1" and client.fake.get("web:gang:unread:222") is None
    h = login(client, "111")
    page = client.get("/story").data.decode()
    assert "red-dot" in page and "1 unread private message" in page and "1 unread gang message" in page
    assert "tab=messages" in page  # the bubble opens on what's waiting
    dots = client.get("/chat/dots?v=0-0")
    assert dots.status_code == 200 and "bubble-dot-gang" in dots.data.decode()
    assert client.get("/chat/dots?v=1-1").status_code == 204  # unchanged
    # the tabs: global, gang, messages, and a conversation inside the bubble
    tabs = client.get("/chat/bubble?tab=global").data.decode()
    assert "chat-global" in tabs and "⚑ Gang" in tabs and "✉ Messages" in tabs
    gang = client.get("/chat/bubble?tab=gang").data.decode()
    assert "raid tonight?" in gang and "gangs/chat" in gang
    assert client.fake.get("web:gang:unread:111") is None  # seen
    convs = client.get("/chat/bubble?tab=messages").data.decode()
    assert "/chat/bubble/dm/222" in convs and "red-dot" in convs
    dm = client.get("/chat/bubble/dm/222").data.decode()
    assert "psst" in dm and "chat-dm-222" in dm
    assert client.fake.hget("web:dm:unread:111", "222") is None
    assert "red-dot" not in client.get("/chat/dots?v=1-1").data.decode()
    # on the gang page, the bubble points at the page's own chat instead of a second box
    assert 'id="gang-chat"' not in client.get("/chat/bubble?tab=gang&here=gangs.index").data.decode()
