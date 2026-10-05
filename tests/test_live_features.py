"""Seasons, battle history and replays, live duels, events, mastery, gang chat, gifts, notifications,
the team simulator and the Stand Dex."""
import datetime
import json
import pickle

from app.game.character import CHARACTER_FILE
from app.game.user import create_user
from test_app import char, client, doc, login, put  # noqa: F401  (client is a fixture)

ADMIN = "242367586233352193"  # one of the default admin ids


def player(c, uid, **fields):
    d = create_user(uid)
    d.update(fields)
    put(c, d)
    return d


def befriend(c, a, b):
    c.fake.sadd(f"web:friends:{a}", b)
    c.fake.sadd(f"web:friends:{b}", a)


def duel(c, a="111", b="222"):
    """Start a friendly duel between a and b (b accepts a's challenge)."""
    player(c, a, main_characters=[char(1, xp=2000)])
    player(c, b, main_characters=[char(2, xp=2000)])
    login(c, a)
    c.post("/battles/friends/invite", data={"user_id": b}, headers={"X-CSRF-Token": "tok"})
    cid = c.fake.smembers(f"web:friend:inbox:{b}").pop().decode()
    h = login(c, b)
    c.post(f"/battles/friends/accept/{cid}", headers=h)
    return pickle.loads(c.fake.get(f"web:fight:{a}"))


def finish_duel(c, a="111", b="222"):
    """Play the duel out (each side picks a target whenever it's their turn)."""
    for _ in range(400):
        fight = pickle.loads(c.fake.get(f"web:fight:{a}"))
        if fight.finished:
            return fight
        acting = fight.meta["players"][fight.acting_side]
        h = login(c, acting)
        target = fight.targets()[0] if fight.targets() else 0
        c.post("/battles/attack", data={"target": target}, headers=h)
    raise AssertionError("the duel never ended")


# ── 1. Ranked seasons ────────────────────────────────────────────────────────

def test_season_rating_soft_reset_and_claim(client):
    from app.game import seasons
    player(client, "111", global_elo=1600)
    sid = seasons.season_id()
    prev = seasons.previous_id(sid)
    assert seasons.rating(client.fake, "111", 1600) == 800  # first season: half the lifetime Elo
    client.fake.zadd(f"web:season:{prev}:rating", {"111": 2100})
    assert seasons.rating(client.fake, "111", 1600) == 1050  # then half of the last season played

    qualified = []
    for _ in range(seasons.MIN_GAMES):
        qualified += seasons.record(client.fake, ["111", "222"], "111", {"111": 1600, "222": 0})
    assert qualified == ["111", "222"]
    assert seasons.rating(client.fake, "111") == 1050 + seasons.MIN_GAMES * seasons.WIN
    assert seasons.rating(client.fake, "222") == 0  # floored at zero

    # last season's reward: Requiem tier (2100) pays and gives a title, once
    client.fake.hset(f"web:season:{prev}:games", "111", seasons.MIN_GAMES)
    h = login(client, "111")
    page = client.get("/battles?mode=ranked").data.decode()
    assert "Season reward ready" in page and "Requiem" in page
    client.post("/battles/season/claim", headers=h)
    d = doc(client, "111")
    assert d["fragments"] == seasons.REWARDS["Requiem"]["fragments"]
    assert d["super_fragments"] == seasons.REWARDS["Requiem"]["super"]
    assert any(t.startswith("Requiem ·") for t in d["web_titles"])
    client.post("/battles/season/claim", headers=h)
    assert doc(client, "111")["fragments"] == seasons.REWARDS["Requiem"]["fragments"]

    board = client.get("/leaderboard?by=season").data.decode()
    assert "season" in board.lower()


def test_ranked_duel_moves_the_season_rating(client):
    from app.game import seasons
    player(client, "111", main_characters=[char(1, xp=5000)], global_elo=1000)
    player(client, "222", main_characters=[char(2, xp=5000)], global_elo=1000)
    from app.routes.battles import _create_duel
    app = client.application
    with app.test_request_context():
        fight = _create_duel("111", "222", "ranked")
    assert client.fake.hexists("web:live", fight.id)
    fight = finish_duel(client)
    games = client.fake.hget(f"web:season:{seasons.season_id()}:games", "111")
    assert int(games) == 1
    assert not client.fake.hexists("web:live", fight.id)  # off the live list once it's over


# ── 2. Battle history and replays ────────────────────────────────────────────

def test_finished_fights_are_kept_with_a_public_replay(client):
    duel(client)
    fight = finish_duel(client)
    for uid in ("111", "222"):
        rows = [json.loads(x) for x in client.fake.lrange(f"web:battles:{uid}", 0, -1)]
        assert len(rows) == 1 and rows[0]["id"] == fight.id  # recorded once, though saved for both players
    h = login(client, "111")
    page = client.get("/battles?mode=history", headers=h).data.decode()
    assert "Friendly duel" in page and f"/battles/replay/{fight.id}" in page
    with client.session_transaction() as s:
        s.clear()
    replay = client.get(f"/battles/replay/{fight.id}")  # no login needed to watch a shared replay
    assert replay.status_code == 200
    body = replay.data.decode()
    assert 'data-replay="full"' in body and "fight-replay" in body and "Watch again" in body
    assert "hx-post" not in body.split('id="fight"')[1].split("</section>")[0]  # nothing to click in a replay
    assert client.get("/battles/replay/nope").status_code == 404
    profile = client.get("/u/111").data.decode()
    assert "Recent battles" in profile


# ── 6. Watching live duels ───────────────────────────────────────────────────

def test_friends_can_watch_a_friendly_duel_live(client):
    fight = duel(client)
    player(client, "333")
    h = login(client, "333")
    assert "No duel is running" in client.get("/battles?mode=watch", headers=h).data.decode()
    assert client.get(f"/battles/watch/{fight.id}", headers=h).status_code == 302  # not a friend: no access
    befriend(client, "333", "111")
    listing = client.get("/battles?mode=watch", headers=h).data.decode()
    assert f"/battles/watch/{fight.id}" in listing
    page = client.get(f"/battles/watch/{fight.id}", headers=h)
    assert page.status_code == 200 and b"watch_frame" not in page.data and b"/frame?log_len=" in page.data
    n = len(fight.log)
    assert client.get(f"/battles/watch/{fight.id}/frame?log_len={n}", headers=h).status_code == 204
    assert client.get(f"/battles/watch/{fight.id}/frame?log_len=0", headers=h).status_code == 200
    assert f"/battles/watch/{fight.id}".encode() in client.get("/u/111", headers=h).data


# ── 3. Events ────────────────────────────────────────────────────────────────

def test_admin_event_boosts_fights_and_pays_tokens(client):
    from app.game import events, logic
    player(client, ADMIN)
    h = login(client, ADMIN)
    today = logic.now().date()
    assert client.get("/admin/events", headers=h).status_code == 200
    client.post("/admin/events", data={"op": "create", "name": "SR Week", "kind": "rarity", "rarity": "SR",
                                       "start": today.isoformat(), "end": (today + datetime.timedelta(days=7)).isoformat()},
                headers=h)
    assert "SR Week" in client.get("/admin/events", headers=h).data.decode()
    ev = events.current(client.fake)
    assert ev and ev["name"] == "SR Week"
    # an overlapping event is refused
    client.post("/admin/events", data={"op": "create", "name": "Clash", "kind": "dust",
                                       "start": today.isoformat(), "end": (today + datetime.timedelta(days=3)).isoformat()}, headers=h)
    assert len(events.all_events(client.fake)) == 1

    # the boost lands once, even when a team carries over (tower floors)
    from app.game.character import character_from_dict
    from app.game.fight import Fight, Side
    sr = next(c for c in CHARACTER_FILE if c["rarity"] == "SR")
    stand = character_from_dict(char(sr["id"]))
    base = stand.start_damage
    with client.application.test_request_context():
        events.current(client.fake)
        f = Fight(Side("A", [stand], True), Side("B", [character_from_dict(char(1))], False))
        Fight(Side("A", [stand], True), Side("B", [character_from_dict(char(1))], False))
    assert stand.start_damage == base + int(base * events.BOOST)
    assert any("SR Week" in e["text"] for e in f.log)

    # tokens and the shop
    d = doc(client, ADMIN)
    d["web_event"] = {ev["id"]: {"tokens": 50, "bought": {}}}
    put(client, d)
    assert "SR Week" in client.get("/events", headers=h).data.decode()
    client.post("/events/buy", data={"key": "dust"}, headers=h)
    client.post("/events/buy", data={"key": "title"}, headers=h)
    d = doc(client, ADMIN)
    assert d["fragments"] == 1000 and d["web_event"][ev["id"]]["tokens"] == 50 - 10 - 30
    assert "SR Week veteran" in d["web_titles"]
    client.post("/events/buy", data={"key": "title"}, headers=h)  # one per event
    assert doc(client, ADMIN)["web_event"][ev["id"]]["tokens"] == 10

    # gear with no other source: sold only here, one per event, and the wiki says so
    d = doc(client, ADMIN)
    d["web_event"][ev["id"]]["tokens"] = 500
    put(client, d)
    page = client.get("/events", headers=h).data.decode()
    assert "Event only" in page and "Red stone of Aja" in page
    client.post("/events/buy", data={"key": "aja"}, headers=h)
    client.post("/events/buy", data={"key": "aja"}, headers=h)
    assert [i["id"] for i in doc(client, ADMIN)["items"]].count(6) == 1
    from app.wiki import item_rows
    sourceless = [it["name"] for it in item_rows() if not it["sources"] and it["kind"] != "Stand chip"]
    assert sourceless == []
    client.post("/admin/events", data={"op": "delete", "id": ev["id"]}, headers=h)
    assert events.current(client.fake) is None


# ── 4. Stand mastery and titles ──────────────────────────────────────────────

def test_mastery_counts_fights_and_unlocks_a_title(client):
    from app.game import mastery
    duel(client)
    finish_duel(client)
    row = mastery.of(client.fake, "111", 1)
    assert row["g"] == 1 and row["d"] > 0
    client.fake.hset("web:mastery:111", "1:w", 200)  # a lot of wins later...
    assert "Star platinum Master" in mastery.titles(client.fake, "111")
    h = login(client, "111")
    stand_uuid = doc(client, "111")["main_characters"][0]["uuid"]
    assert "mastery" in client.get(f"/team/stand/{stand_uuid}", headers=h).data.decode()
    client.post("/titles", data={"title": "Star platinum Master"}, headers=h)
    assert "Star platinum Master" in client.get("/u/111").data.decode()
    client.post("/titles", data={"title": "Made up"}, headers=h)
    assert doc(client, "111")["web_title"] == "Star platinum Master"


# ── 5. Gang chat ─────────────────────────────────────────────────────────────

def test_gang_chat_post_poll_and_moderation(client):
    player(client, "111", fragments=50_000)
    player(client, "222")
    h = login(client, "111")
    client.post("/gangs/create", data={"name": "Crusaders"}, headers=h)
    gid = doc(client, "111")["gang_id"]
    client.post("/gangs/invite", data={"user_id": "222"}, headers=h)
    h2 = login(client, "222")
    client.post(f"/gangs/join/{gid}", headers=h2)

    r = client.post("/gangs/chat", data={"text": "  ora <b>ora</b>  "}, headers={**h2, "HX-Request": "true"})
    assert r.status_code == 200 and "ora &lt;b&gt;ora&lt;/b&gt;" in r.data.decode()  # escaped
    r = client.post("/gangs/chat", data={"text": "again"}, headers={**h2, "HX-Request": "true"})
    assert "Slow down" in r.data.decode()  # cooldown
    from app.game import gangs as G
    seq = G.chat_seq(client.fake, gid)
    assert client.get(f"/gangs/chat?seq={seq}", headers=h2).status_code == 204
    assert client.get(f"/gangs/chat?seq={seq - 1}", headers=h2).status_code == 200
    assert "Gang chat" in client.get("/gangs", headers=h2).data.decode()

    msg = G.chat_messages(client.fake, gid)[0]
    h = login(client, "111")  # the boss can remove anyone's message
    client.post(f"/gangs/chat/{msg['id']}/delete", headers={**h, "HX-Request": "true"})
    assert G.chat_messages(client.fake, gid) == []


# ── 7. Gifts ─────────────────────────────────────────────────────────────────

def test_daily_gifts_between_friends(client):
    player(client, "111", web_story={"cleared": 5})
    player(client, "222", energy=0)
    player(client, "333")
    befriend(client, "111", "222")
    h = login(client, "111")
    client.post("/community/gift", data={"user_id": "333", "kind": "dust"}, headers=h)  # not friends
    client.post("/community/gift", data={"user_id": "222", "kind": "dust"}, headers=h)
    client.post("/community/gift", data={"user_id": "222", "kind": "energy"}, headers=h)  # one a day per friend
    assert client.fake.llen("web:gifts:222") == 1 and client.fake.llen("web:gifts:333") == 0
    assert "🎁 Sent" in client.get("/community/friends", headers=h).data.decode()

    h2 = login(client, "222")
    assert "1 gift waiting" in client.get("/community/friends", headers=h2).data.decode()
    client.post("/community/gifts/open", headers=h2)
    assert doc(client, "222")["fragments"] == 50 and client.fake.llen("web:gifts:222") == 0

    befriend(client, "222", "111")
    client.post("/community/gift", data={"user_id": "111", "kind": "dust"}, headers=h2)  # needs story progress
    assert client.fake.llen("web:gifts:111") == 0


# ── 8. Notifications ─────────────────────────────────────────────────────────

def test_scheduled_notifications_stay_on_the_site(client):
    from app import social
    player(client, "111")
    with client.application.test_request_context():
        social.notify_later("111", "journey:x", 100, "journey", "Home!", "/journey")
        social.notify_later("111", "journey:y", 10 ** 12, "journey", "Later", "/journey")
        assert social.flush_due(now=200) == 1
        assert social.flush_due(now=200) == 0
        social.cancel_later("111", "journey:y")
        assert client.fake.zcard("web:notif:due") == 0
    feed = [json.loads(x)["text"] for x in client.fake.lrange("web:notif:111", 0, -1)]
    assert feed == ["Home!"]
    assert not client.fake.exists("web:dm:queue")  # nothing goes through Discord

    # the journey schedules its own "home" notification
    player(client, "222", main_characters=[char(1), char(2)])
    h = login(client, "222")
    uuid = doc(client, "222")["main_characters"][1]["uuid"]
    client.post("/journey/depart", data={"uuid": uuid, "route": "hong_kong"}, headers=h)
    assert client.fake.zcard("web:notif:due") == 1


# ── 9. Team simulator ────────────────────────────────────────────────────────

def test_team_simulator(client):
    player(client, "111", main_characters=[char(1, xp=8000), char(2, xp=8000)], teams={})
    player(client, "222", main_characters=[char(3, xp=100)])
    h = login(client, "111")
    page = client.get("/battles/simulator", headers=h).data.decode()
    assert "Team simulator" in page and "story:0" in page and "tower:1" in page
    r = client.post("/battles/simulator/run", data={"team": "", "vs": "story:0"}, headers={**h, "HX-Request": "true"})
    body = r.data.decode()
    assert "win rate" in body and "Star platinum" in body
    client.fake.delete("web:sim:111")
    r = client.post("/battles/simulator/run", data={"team": "", "vs": "player", "player": "222"}, headers=h)
    assert "win rate" in r.data.decode()
    r = client.post("/battles/simulator/run", data={"team": "", "vs": "story:1"}, headers=h)  # throttled
    assert "One simulation at a time" in r.data.decode()


# ── 10. Stand Dex ────────────────────────────────────────────────────────────

def test_dex_remembers_stands_and_pays_a_complete_set(client):
    from app.game import dex
    lr = next(s for s in dex.SETS if s["key"] == "rarity:LR")
    player(client, "111", storage_characters=[char(i) for i in lr["ids"]])
    h = login(client, "111")
    page = client.get("/dex", headers=h).data.decode()
    assert "Stand Dex" in page and "Every LR stand" in page
    assert set(lr["ids"]) <= set(doc(client, "111")["web_dex"])
    # released stands still count
    d = doc(client, "111")
    d["storage_characters"] = []
    put(client, d)
    client.post("/dex/claim", data={"key": "rarity:LR"}, headers=h)
    d = doc(client, "111")
    assert d["fragments"] == lr["reward"]["fragments"] and "Mythic collector" in d["web_titles"]
    client.post("/dex/claim", data={"key": "rarity:LR"}, headers=h)
    assert doc(client, "111")["fragments"] == lr["reward"]["fragments"]
    client.post("/dex/claim", data={"key": "rarity:R"}, headers=h)  # incomplete
    assert "rarity:R" not in doc(client, "111")["web_sets_claimed"]


def test_new_pages_render_for_a_new_player(client):
    player(client, "111")
    h = login(client, "111")
    for url in ("/events", "/dex", "/battles/simulator", "/battles?mode=watch", "/battles?mode=history",
                "/battles?mode=ranked", "/community/friends", "/auth/account", "/u/111", "/leaderboard?by=season"):
        assert client.get(url, headers=h).status_code == 200, url


def test_dust_rush_pays_tokens_and_bonus_on_pve_wins(client):
    from app.game import events, logic
    from app.game.user import User
    today = logic.now().date()
    with client.application.test_request_context():
        events.create(client.fake, "Dust Rush", "", today.isoformat(), (today + datetime.timedelta(days=2)).isoformat(), "dust")
        events.current(client.fake)
        user = User(create_user("111"))
        rewards = events.pve_win(user, {"won": True, "fragments": 300})
        assert rewards["fragments"] == 450 and rewards["event_bonus"] == 150 and user.fragments == 150
        assert rewards["tokens"] == events.TOKENS_PVE and events.tokens(user, events.cached()) == events.TOKENS_PVE
        assert events.pve_win(user, None) is None  # a fight that paid nothing stays that way


def test_wiki_covers_the_new_systems(client):
    pages = {slug: client.get(f"/wiki/{slug}").data.decode() for slug in ("ranked", "battles", "events", "progress", "social", "gangs", "stands")}
    assert "Seasons" in pages["ranked"] and "Over Heaven" in pages["ranked"] and "half the rating" in pages["ranked"]
    assert "Replays" in pages["battles"] and "Team simulator" in pages["battles"] and "Watching live duels" in pages["battles"]
    assert "Red stone of Aja" in pages["events"] and "Event only" in pages["events"] and "Synergy spotlight" in pages["events"]
    assert "Stand mastery" in pages["progress"] and "Mythic collector" in pages["progress"] and "Stardust Crusaders" in pages["progress"]
    assert "Daily gifts" in pages["social"] and "Auction house" in pages["social"] and "Trades" in pages["social"]
    assert "Gang chat" in pages["gangs"] and "spark" in pages["stands"]
    index = client.get("/wiki/search.json").json
    assert {"Limited-time events", "Mastery, titles & Stand Dex", "Friends, gifts & trading"} <= {e["t"] for e in index}


def test_dex_remembers_stands_traded_away_without_opening_the_dex(client):
    player(client, "111", main_characters=[char(1)], storage_characters=[char(57)])
    with client.application.test_request_context():
        from app.db import get_db
        u = get_db().get_user("111")
        u.update()  # any web save while it's owned (the pull, a fuse, a fight...)
        u.storage_characters = []  # then traded away
        u.update()
    assert 57 in doc(client, "111")["web_dex"]
