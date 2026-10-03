"""Friends, player search, inbox, notifications, referrals, story-gated quests and fight status previews."""
import json

from app.game.character import character_from_dict
from app.game.effects import Effect, EffectType
from app.game.user import User, create_user
from test_app import char, client, doc, login, put  # noqa: F401  (client is a fixture)


def player(c, uid, name=None, **fields):
    d = create_user(uid)
    d.update(fields)
    put(c, d)
    c.fake.set(f"web:identity:{uid}", json.dumps({"name": name or f"P{uid}", "avatar": None}))
    return d


def test_friend_request_accept_and_inbox(client):
    player(client, "111", "Jotaro", main_characters=[char(1)])
    player(client, "222", "Polnareff", main_characters=[char(6)])
    h = login(client, "111")
    page = client.get("/community/players?q=polna").data.decode()
    assert "Polnareff" in page and "Add friend" in page
    client.post("/community/friends/add", data={"user_id": "222"}, headers=h)
    assert client.fake.sismember("web:friendreq:in:222", "111")

    h2 = login(client, "222", "Polnareff")
    home = client.get("/").data.decode()
    assert "wants to be friends" in home  # the pop-up toast on the next page
    assert 'class="bell has-news"' in home
    inbox = client.get("/community/inbox").data.decode()
    assert "Friend requests" in inbox and "Jotaro" in inbox
    client.post("/community/friends/accept", data={"user_id": "111"}, headers=h2)
    assert client.fake.sismember("web:friends:111", "222") and client.fake.sismember("web:friends:222", "111")
    assert "Jotaro" in client.get("/community/friends").data.decode()
    assert "Friends" in client.get("/u/111").data.decode()

    # a duel challenge, a trade offer and a gang invite all reach the inbox
    client.post("/battles/friends/invite", data={"user_id": "111"}, headers=h2)
    login(client, "111")
    inbox = client.get("/community/inbox").data.decode()
    assert "challenged you to a friendly duel" in inbox and "Duel challenges" in inbox


def test_quest_completion_toasts_ride_on_htmx_responses(client):
    from app.game.quests import track_quest_progress
    from app import social
    player(client, "111", main_characters=[char(1)])
    with client.application.app_context():
        u = User(doc(client, "111"))
        track_quest_progress(u, "daily_claim", 0)  # assigns the lists
        u.quests["active_daily"] = [{"quest_id": 4, "progress": 0, "claimed": False}]  # "claim your daily"
        track_quest_progress(u, "daily_claim")
        put(client, u.to_dict())
    h = login(client, "111")
    r = client.post("/quests/claim", headers={**h, "HX-Request": "true"})
    trigger = json.loads(r.headers["HX-Trigger"])
    assert trigger["toast"][0]["text"].startswith("Quest complete")
    assert "HX-Trigger" not in client.post("/quests/claim", headers={**h, "HX-Request": "true"}).headers  # drained


def test_quests_unlock_with_the_story():
    from app.game import quests as Q
    u = User(create_user("1"))
    Q.ensure_quests_assigned(u)
    perm = {e["quest_id"] for e in u.quests["active_permanent"]}
    assert 1014 in perm and 1010 not in perm  # Bring a Friend is open; the Part 8 milestone isn't
    assert all(Q.QUEST_BY_ID[e["quest_id"]].get("story_requirement", 0) == 0 for e in u.quests["active_daily"])
    assert Q.locked_preview(u)["stage"] == 3
    u.data["web_story"] = {"cleared": 26}
    Q.ensure_quests_assigned(u)
    assert 1010 in {e["quest_id"] for e in u.quests["active_permanent"]}
    assert Q.weekly_count(u) == 4


def test_invite_link_befriends_and_pays_a_palm_after_three_stages(client):
    player(client, "111", "Jotaro", main_characters=[char(1)])
    client.get("/community/join?ref=111")
    with client.session_transaction() as s:
        assert s["ref"] == "111"
        tok = s["csrf"]
    client.post("/auth/register", data={"csrf": tok, "username": "Jolyne", "password": "stonefree!", "confirm": "stonefree!"})
    client.get("/auth/welcome")
    with client.session_transaction() as s:
        new, tok = s["uid"], s["csrf"]
    client.post("/auth/welcome", data={"csrf": tok})
    assert client.fake.sismember("web:friends:111", new)
    assert client.fake.sismember("web:ref:pending:111", new)
    with client.application.app_context():
        from app import social
        social.referral_progress(new, 2)  # not yet
        assert client.fake.llen("web:ref:ready:111") == 0
        social.referral_progress(new, 3)
        social.referral_progress(new, 4)  # counted once
        assert client.fake.llen("web:ref:ready:111") == 1
    h = login(client, "111")
    client.get("/quests")
    d = doc(client, "111")
    entry = next(e for e in d["quests"]["active_permanent"] if e["quest_id"] == 1014)
    assert entry["progress"] == 1
    palms = sum(1 for i in d["items"] if i["id"] == 2)
    client.post("/quests/claim", data={"quest": 1014}, headers=h)
    assert sum(1 for i in doc(client, "111")["items"] if i["id"] == 2) == palms + 1


def test_fight_status_preview_matches_the_tick():
    from app.game import status
    c = character_from_dict(char(1, xp=3000))
    c.current_hp = c.start_hp - 100
    c.add_effect(Effect(EffectType.POISON, 2, 40))
    c.add_effect(Effect(EffectType.REGENERATION, 2, 30))
    c.add_effect(Effect(EffectType.STUN, 1, 0))
    v = status.view(c)
    assert v["dot"] == 40 and v["regen"] == 30
    names = [ch["name"] for ch in v["chips"]]
    assert names[:2] == ["Poison", "Stunned"] and "Regen" in names  # bad first
    hp = c.current_hp
    c.end_turn()
    assert c.current_hp == hp - 40 + 30
