"""Deleting a save from the admin panel (owners only): the player starts over, nothing of theirs is left dangling for
anyone else, their login survives, and the copy can be restored."""
import json
import pickle

import app.db as dbmod
from app import wipe
from app.game import auction
from test_app import char, client, doc, login, put  # noqa: F401  (client is a fixture)
from test_features import player


def _setup(c):
    c.application.config["DISCORD_ADMIN_IDS"] = {"111"}
    player(c, "111")
    victim = player(c, "222", fragments=500, gang_id="g1", storage_characters=[char(1), char(2)])
    player(c, "333", fragments=10_000, gang_id="g1")
    c.fake.hset("gangs", "g1", pickle.dumps({"_id": "g1", "name": "Passione", "users": ["222", "333"],
                                             "ranks": {"222": 0, "333": 2}}))
    # friends, a trade offer, an auction listing with 333's bid on it, a ladder entry
    c.fake.sadd("web:friends:222", "333"); c.fake.sadd("web:friends:333", "222")
    c.fake.set("web:trade:t1", json.dumps({"id": "t1", "from": "222", "to": "333"}))
    c.fake.sadd("web:trades:out:222", "t1"); c.fake.sadd("web:trades:in:333", "t1")
    stand = victim["storage_characters"][0]
    listing = {"id": "L1", "seller": "222", "stand": stand, "mode": "bid", "currency": "dust", "start": 100,
               "dust": 0, "heads": 0, "bid": 700, "bidder": "333", "bids": 1, "ends": 9_999_999_999}
    c.fake.hset(auction.KEY, "L1", json.dumps(listing)); c.fake.sadd("web:auction:seller:222", "L1")
    c.fake.zadd("web:season:2026-10:rating", {"222": 1500, "333": 1400})
    c.fake.set("web:mastery:222", "x"); c.fake.set("web:account_uid:222", "acc-login")
    return victim


def test_only_owners_delete_and_must_type_the_word(client):
    _setup(client)
    client.fake.hset("web:admins", "444", "{}")
    player(client, "444")
    client.post("/admin/player/222/delete", data={"confirm": "DELETE"}, headers=login(client, "444"))
    assert client.fake.hexists("users", "222")  # a promoted admin can't
    h = login(client, "111")
    assert "Delete this save" in client.get("/admin/player/222").data.decode()
    client.post("/admin/player/222/delete", data={"confirm": "delete pls"}, headers=h)
    assert client.fake.hexists("users", "222")


def test_delete_cleans_up_and_the_player_starts_over(client):
    _setup(client)
    h = login(client, "111")
    client.post("/admin/player/222/delete", data={"confirm": "DELETE"}, headers=h)
    assert not client.fake.hexists("users", "222")
    gang = pickle.loads(client.fake.hget("gangs", "g1"))
    assert gang["users"] == ["333"] and gang["ranks"]["333"] == 0  # the boss seat passed on
    assert doc(client, "333")["fragments"] == 10_700  # their held bid came back
    assert not client.fake.hexists(auction.KEY, "L1") and not client.fake.exists("web:trade:t1")
    assert not client.fake.sismember("web:friends:333", "222") and not client.fake.smembers("web:trades:in:333")
    assert client.fake.zscore("web:season:2026-10:rating", "222") is None
    assert not client.fake.exists("web:mastery:222") and client.fake.get("web:account_uid:222") == b"acc-login"
    assert json.loads(client.fake.lindex("web:admin:audit", 0))["kind"] == "delete_save"
    # their next visit asks them to begin again
    login(client, "222")
    assert "/welcome" in client.get("/team").headers.get("Location", "")


def test_a_deleted_save_can_be_restored(client):
    _setup(client)
    h = login(client, "111")
    client.post("/admin/player/222/delete", data={"confirm": "DELETE"}, headers=h)
    assert "Deleted saves" in client.get("/admin").data.decode()
    client.post("/admin/deleted/222/restore", headers=h)
    d = doc(client, "222")
    assert d["fragments"] == 500 and d["gang_id"] is None and len(d["storage_characters"]) == 2
    assert not client.fake.exists("web:deleted:222")


def test_no_delete_mid_fight_or_of_yourself(client):
    _setup(client)
    login(client, "111")
    with client.application.app_context():
        try:
            wipe.delete_save("111", "111")
            raise AssertionError("deleted their own save")
        except wipe.WipeError:
            pass
        from app.game.fight import Fight, Side
        from app.game.character import character_from_dict
        f = Fight(Side("A", [character_from_dict(char(1))], True), Side("B", [character_from_dict(char(2))], False), kind="dummy")
        dbmod.save_fight("222", f)
        try:
            wipe.delete_save("222", "111")
            raise AssertionError("deleted mid-fight")
        except wipe.WipeError as e:
            assert "fight" in str(e)
    assert client.fake.hexists("users", "222")


def test_remove_everything_leaves_nothing_but_the_ban_and_the_audit_line(client):
    from app import accounts
    from app.game import profile as P
    client.application.config["DISCORD_ADMIN_IDS"] = {"111"}
    player(client, "111")
    with client.application.app_context():
        acc = accounts.create_account("jolyne", "a-good-password")
    uid = acc["uid"]
    player(client, uid, fragments=900)
    client.fake.sadd("web:banned", uid)
    client.fake.hset("web:admins", uid, "{}")
    client.fake.set(f"web:identity:{uid}", json.dumps({"name": "jolyne", "avatar": None}))
    client.fake.set(f"web:mastery:{uid}", "x")
    client.fake.sadd("web:mail:claimed:m1", uid, "333")
    with client.application.app_context():
        P.report("333", uid, "text")
        P.report(uid, "333", "text")
    # their browser is still logged in
    with client.session_transaction() as s:
        s["uid"], s["csrf"], s["since"] = uid, "tok", 1
    h = login(client, "111")
    page = client.get(f"/admin/player/{uid}").data.decode()
    assert "Remove all of this player" in page
    client.post(f"/admin/player/{uid}/remove_everything", data={"confirm": "nope"}, headers=h)
    assert client.fake.hexists("users", uid)
    client.post(f"/admin/player/{uid}/remove_everything", data={"confirm": "REMOVE"}, headers=h)
    assert not client.fake.hexists("users", uid) and not client.fake.exists(f"web:deleted:{uid}")
    assert not client.fake.exists("web:account:jolyne") and not client.fake.exists(f"web:account_uid:{uid}")
    assert not client.fake.exists(f"web:identity:{uid}") and not client.fake.exists(f"web:mastery:{uid}")
    assert not client.fake.hexists("web:admins", uid) and client.fake.smembers("web:mail:claimed:m1") == {b"333"}
    assert client.fake.hlen(P.REPORTS_KEY) == 0
    assert client.fake.sismember("web:banned", uid)  # a ban survives
    row = json.loads(client.fake.lindex("web:admin:audit", 0))
    assert row["kind"] == "remove_everything" and "name" not in row
    # the old session is logged out; a login made after the removal isn't
    with client.session_transaction() as s:
        s["uid"], s["csrf"], s["since"] = uid, "tok", 1
    client.get("/")
    with client.session_transaction() as s:
        assert "uid" not in s
    with client.session_transaction() as s:
        s["uid"], s["csrf"], s["since"] = uid, "tok", 4_000_000_000
    client.get("/")
    with client.session_transaction() as s:
        assert s.get("uid") == uid


def test_remove_everything_after_a_delete(client):
    _setup(client)
    h = login(client, "111")
    client.post("/admin/player/222/delete", data={"confirm": "DELETE"}, headers=h)
    assert client.fake.exists("web:deleted:222")
    client.post("/admin/player/222/remove_everything", data={"confirm": "REMOVE"}, headers=h)
    assert not client.fake.exists("web:deleted:222") and not client.fake.hexists("web:deleted", "222")
    assert not client.fake.exists("web:account_uid:222")
