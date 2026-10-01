"""Accounts, gangs, trades, story, items, collection tools, banners and engine fixes."""
import datetime
import pickle
import random

from app.game import logic
from app.game.character import CHARACTER_FILE, CRITMULTIPLIER, get_character_from_template
from app.game.effects import Effect, EffectType
from app.game.user import User, create_user
from test_app import char, client, doc, login, put  # noqa: F401  (client is a fixture)


def player(c, uid, **fields):
    d = create_user(uid)
    d.update(fields)
    put(c, d)
    return d


# --------------------------------------------------------------------------- #
# Engine fixes
# --------------------------------------------------------------------------- #
def test_crits_hit_harder_and_effects_revert_exactly():
    assert CRITMULTIPLIER == 1.5
    c = get_character_from_template(CHARACTER_FILE[0], ["ATTACK"], ["GOOD"])
    dmg, spd = c.current_damage, c.current_speed
    c.effects = [Effect(EffectType.WEAKEN, 1, 5), Effect(EffectType.SLOW, 1, 2), Effect(EffectType.DAMAGEUP, 1, 7)]
    c.end_turn()  # applied, then expired the same turn
    assert c.current_damage == dmg and c.current_speed == spd
    assert c.effects == []


def test_dummy_win_counts_for_the_story(client):
    from app.routes.battles import _settle
    player(client, "111")
    fight = type("F", (), {"kind": "dummy", "winner": 0, "meta": {"players": ["111"]}})()
    with client.application.test_request_context():
        _settle(fight)
    assert doc(client, "111")["achievement_data"]["counters"]["fight_win"] == 1


# --------------------------------------------------------------------------- #
# Username + password accounts
# --------------------------------------------------------------------------- #
def test_register_login_throttle_and_link(client, monkeypatch):
    client.get("/auth/register")
    with client.session_transaction() as s:
        tok = s["csrf"]
    r = client.post("/auth/register", data={"csrf": tok, "username": "Jolyne", "password": "stonefree!", "confirm": "stonefree!"})
    assert r.headers["Location"].endswith("/auth/welcome")
    with client.session_transaction() as s:
        uid, tok = s["uid"], s.get("csrf", tok)
    assert uid.startswith("acc")
    client.get("/auth/welcome")
    with client.session_transaction() as s:
        tok = s["csrf"]
    client.post("/auth/welcome", data={"csrf": tok})
    assert doc(client, uid)["super_fragements"] == 1

    # duplicate username, wrong password, then the right one
    client.post("/auth/logout", data={"csrf": tok})
    client.get("/auth/login")
    with client.session_transaction() as s:
        tok = s["csrf"]
    assert client.post("/auth/register", data={"csrf": tok, "username": "jolyne", "password": "whatever1", "confirm": "whatever1"}).status_code == 400
    assert client.post("/auth/login", data={"csrf": tok, "username": "jolyne", "password": "nope-nope"}).status_code == 401
    assert client.post("/auth/login", data={"csrf": tok, "username": "JOLYNE", "password": "stonefree!"}).status_code == 302
    with client.session_transaction() as s:
        assert s["uid"] == uid

    # players can find each other by username
    from app.accounts import resolve_player, link_discord, AccountError
    with client.application.test_request_context():
        assert resolve_player("jolyne") == uid
        link_discord(uid, "999")
        assert resolve_player("jolyne") == "999"
        assert client.fake.hget("users", uid) is None and doc(client, "999")["_id"] == "999"
        player(client, "998")
        try:
            link_discord("acc-none", "998")
            assert False
        except AccountError:
            pass

    # throttling after repeated failures
    with client.session_transaction() as s:
        s.clear()
        s["csrf"] = tok
    for _ in range(8):
        client.post("/auth/login", data={"csrf": tok, "username": "jolyne", "password": "bad-guess"})
    r = client.post("/auth/login", data={"csrf": tok, "username": "jolyne", "password": "stonefree!"})
    assert r.status_code == 401 and b"Too many attempts" in r.data


# --------------------------------------------------------------------------- #
# Gangs
# --------------------------------------------------------------------------- #
def test_gang_ranks_vault_guardians_and_raid(client):
    player(client, "111", fragments=50_000, storage_characters=[char(1), char(2)])
    player(client, "222", fragments=1_000, main_characters=[char(3, xp=10000)])
    h = login(client, "111")
    client.post("/gangs/create", data={"name": "Crusaders"}, headers=h)
    gid = doc(client, "111")["gang_id"]
    assert gid and doc(client, "111")["fragments"] == 40_000

    client.post("/gangs/invite", data={"user_id": "222"}, headers=h)
    h2 = login(client, "222")
    client.post(f"/gangs/join/{gid}", headers=h2)
    gang = pickle.loads(client.fake.hget("gangs", gid))
    assert "222" in gang["users"] and gang["ranks"]["222"] == 2

    # soldiers can't promote; the boss can, and promoting a capo hands over the boss seat
    client.post("/gangs/promote", data={"member": "111"}, headers=h2)
    assert pickle.loads(client.fake.hget("gangs", gid))["ranks"]["111"] == 0
    h = login(client, "111")
    client.post("/gangs/promote", data={"member": "222"}, headers=h)
    assert pickle.loads(client.fake.hget("gangs", gid))["ranks"]["222"] == 1
    client.post("/gangs/demote", data={"member": "222"}, headers=h)
    assert pickle.loads(client.fake.hget("gangs", gid))["ranks"]["222"] == 2

    # vault and payments
    client.post("/gangs/vault/deposit", data={"amount": "20000"}, headers=h)
    client.post("/gangs/vault/pay", data={"member": "222", "amount": "500"}, headers=h)
    assert pickle.loads(client.fake.hget("gangs", gid))["vault"] == 19_500
    assert doc(client, "222")["fragments"] == 1_500

    # guardians leave storage and come back
    uuid = doc(client, "111")["storage_characters"][0]["uuid"]
    client.post("/gangs/guardians/add", data={"uuid": uuid}, headers=h)
    assert len(pickle.loads(client.fake.hget("gangs", gid))["characters"]) == 1
    assert len(doc(client, "111")["storage_characters"]) == 1
    client.post("/gangs/guardians/remove", data={"index": "0"}, headers=h)
    assert len(doc(client, "111")["storage_characters"]) == 2

    # raid: started from the vault, one attack per member, damage recorded on the gang
    client.post("/gangs/raid/start", headers=h)
    gang = pickle.loads(client.fake.hget("gangs", gid))
    assert gang["vault"] == 9_500 and gang["end_of_raid"] > logic.now()
    h2 = login(client, "222")
    assert client.post("/gangs/raid/attack", headers=h2).headers["Location"].endswith("/gangs/fight")
    assert client.get("/gangs/fight").status_code == 200
    for _ in range(60):
        r = client.post("/gangs/fight/attack", data={"forfeit": "1"}, headers=h2)
        if b"damage dealt" in r.data:
            break
    gang = pickle.loads(client.fake.hget("gangs", gid))
    assert "222" in gang["raid_attacks"]
    assert doc(client, "222")["fragments"] > 1_500  # consolation payout
    client.post("/gangs/fight/leave", headers=h2)
    client.post("/gangs/raid/attack", headers=h2)  # second attempt refused
    assert client.fake.get("web:fight:222") is None

    # kick needs a higher rank; the gang page renders for both
    client.post("/gangs/kick", data={"member": "111"}, headers=h2)
    assert "111" in pickle.loads(client.fake.hget("gangs", gid))["users"]
    assert client.get("/gangs").status_code == 200
    h = login(client, "111")
    client.post("/gangs/kick", data={"member": "222"}, headers=h)
    assert "222" not in pickle.loads(client.fake.hget("gangs", gid))["users"]
    assert doc(client, "222")["gang_id"] is None


def test_war_queue_publishes_to_the_bot_matchmaker(client):
    player(client, "111", fragments=20_000, storage_characters=[char(1)])
    h = login(client, "111")
    client.post("/gangs/create", data={"name": "Passione"}, headers=h)
    gid = doc(client, "111")["gang_id"]
    client.post("/gangs/war/start", headers=h)  # no guardian: refused
    assert client.fake.get(f"web:gang:queued:{gid}") is None
    client.post("/gangs/guardians/add", data={"uuid": doc(client, "111")["storage_characters"][0]["uuid"]}, headers=h)
    pubsub = client.fake.pubsub()
    pubsub.subscribe("war_matchmaking_requests")
    pubsub.get_message()
    client.post("/gangs/war/start", headers=h)
    msg = pubsub.get_message()
    assert msg and pickle.loads(msg["data"]) == gid
    # once the bot matches it, members can attack the opponent's guardians
    other = {"_id": "rival", "name": "Rivals", "users": ["x"], "ranks": {"x": 0}, "characters": [char(2)],
             "damage_to_current_war": 0, "war_attacks": []}
    client.fake.hset("gangs", "rival", pickle.dumps(other))
    client.fake.hset("active_wars", gid, pickle.dumps("rival"))
    player(client, "111", fragments=0, main_characters=[char(5, xp=10000)], gang_id=gid)
    assert client.post("/gangs/war/attack", headers=h).headers["Location"].endswith("/gangs/fight")


# --------------------------------------------------------------------------- #
# Trades, selling, locks
# --------------------------------------------------------------------------- #
def test_trade_offer_accept_and_lock(client):
    a = player(client, "111", fragments=1_000, storage_characters=[char(1), char(2)], items=[{"id": 1}])
    b = player(client, "222", fragments=0, storage_characters=[char(3)])
    give_uuid, want_uuid = a["storage_characters"][0]["uuid"], b["storage_characters"][0]["uuid"]
    h = login(client, "111")
    client.post("/trades/new", data={"with": "222", "give_stand": give_uuid, "give_item": "1:1",
                                     "give_fragments": "300", "want_stand": want_uuid}, headers=h)
    offer_id = next(iter(client.fake.smembers("web:trades:in:222"))).decode()
    assert client.get("/trades").status_code == 200

    h2 = login(client, "222")
    client.post(f"/trades/{offer_id}/accept", headers=h2)
    a2, b2 = doc(client, "111"), doc(client, "222")
    assert want_uuid in [c["uuid"] for c in a2["storage_characters"]]
    assert give_uuid in [c["uuid"] for c in b2["storage_characters"]]
    assert a2["fragments"] == 700 and b2["fragments"] == 300 and b2["items"] == [{"id": 1}]
    assert not client.fake.exists(f"web:trade:{offer_id}")

    # locked stands can't be released or offered
    h = login(client, "111")
    locked_uuid = a2["storage_characters"][0]["uuid"]
    client.post("/team/lock", data={"uuid": locked_uuid}, headers=h)
    assert locked_uuid in doc(client, "111")["web_locked"]
    client.post("/team/release", data={"uuid": locked_uuid}, headers=h)
    assert locked_uuid in [c["uuid"] for c in doc(client, "111")["storage_characters"]]
    client.post("/trades/new", data={"with": "222", "give_stand": locked_uuid}, headers=h)
    assert not client.fake.smembers("web:trades:out:111")
    assert client.get(f"/team/stand/{locked_uuid}").status_code == 200
    assert client.get("/team").status_code == 200


def test_sell_items(client):
    player(client, "111", fragments=0, items=[{"id": 1}, {"id": 1}, {"id": 8}])
    h = login(client, "111")
    client.post("/items/sell", data={"item": "1", "all": "1"}, headers=h)
    assert doc(client, "111")["fragments"] == 2 * (2500 // 10)
    r = client.post("/items/sell", data={"item": "8"}, headers=h)  # free chip: refused
    assert b"be sold" in r.data and doc(client, "111")["items"] == [{"id": 8}]
    assert client.get("/items").status_code == 200


# --------------------------------------------------------------------------- #
# Story, achievements
# --------------------------------------------------------------------------- #
def test_story_gates_and_pays_once(client):
    player(client, "111", fragments=0)
    h = login(client, "111")
    assert client.get("/story").status_code == 200
    client.post("/story/next", headers=h)  # step 1 has no requirement
    assert doc(client, "111")["story_progress"]["current_step"] == 2
    client.post("/story/next", headers=h)  # step 2 needs a team stand
    assert doc(client, "111")["story_progress"]["current_step"] == 2
    d = doc(client, "111")
    d["main_characters"] = [char(1)]
    d["achievement_data"] = {"unlocked": [], "counters": {"fight_win": 1}}
    d["last_adventure"] = datetime.datetime(2026, 1, 1)
    put(client, d)
    for _ in range(6):
        client.post("/story/next", headers=h)
    d = doc(client, "111")
    assert d["story_progress"]["current_chapter"] == -1 and d["fragments"] == 500 and len(d["items"]) == 3
    client.post("/story/back", headers=h)
    client.post("/story/next", headers=h)
    assert doc(client, "111")["fragments"] == 500  # the last reward isn't paid twice
    assert client.get("/achievements").status_code == 200


# --------------------------------------------------------------------------- #
# Banners
# --------------------------------------------------------------------------- #
def test_pity_floor_and_new_tags(client):
    banner = logic.BANNERS[0]
    user = User(create_user("111"))
    random.seed(1)
    user.pity = logic.PITY_LIMIT - 1
    drawn = logic._banner_draw(banner, user)
    assert drawn.rarity in ("SSR", "UR") and user.pity == 0
    # ten pulls always include an SR or better
    for seed in range(40):
        random.seed(seed)
        u = User(create_user("111"))
        u.super_fragements = 1
        res = logic.banner_pull(u, banner["id"])
        assert any(c.rarity != "R" for c, _ in res["drawn"])
        assert any(e["new"] for e in res["cards"])
        assert u.data["web_pull_history"][0]["banner"] == banner["name"]
