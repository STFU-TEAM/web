"""Server logs in the admin panel, push diagnostics, and rewards players claim from their inbox."""
import json
import logging

import app.db as dbmod
from test_app import char, client, doc, login, put  # noqa: F401  (client is a fixture)
from test_features import player
from test_push import _browser_sub, pushy  # noqa: F401  (pushy is a fixture)


def _admin(c, uid="111"):
    c.application.config["DISCORD_ADMIN_IDS"] = {uid}
    player(c, uid)
    return login(c, uid)


# ── Logs ─────────────────────────────────────────────────────────────────────

def test_errors_land_in_the_logs_tab_with_their_traceback(client):
    h = _admin(client)
    with client.application.test_request_context("/somewhere"):
        try:
            1 / 0
        except ZeroDivisionError:
            logging.getLogger("app.test").exception("it broke")
    logging.getLogger("app.test").info("a detail")
    logging.getLogger("urllib3").info("library chatter")  # other loggers only from WARNING
    rows = [json.loads(x) for x in client.fake.lrange("web:logs", 0, -1)]
    assert [r["msg"] for r in rows] == ["a detail", "it broke"]
    assert "ZeroDivisionError" in rows[1]["exc"] and rows[1]["path"] == "GET /somewhere"

    page = client.get("/admin/logs").data.decode()  # Warning+ by default
    assert "it broke" in page and "ZeroDivisionError" in page and "a detail" not in page
    assert "a detail" in client.get("/admin/logs?level=INFO").data.decode()
    assert "it broke" not in client.get("/admin/logs?level=INFO&q=detail").data.decode()

    client.post("/admin/logs/clear", headers=h)
    assert not client.fake.exists("web:logs")
    login(client, "222")
    player(client, "222")
    assert client.get("/admin/logs").status_code == 403


def test_a_crashing_page_is_logged(client):
    _admin(client)

    @client.application.get("/boom")
    def boom():
        raise RuntimeError("kaboom")
    client.application.config["PROPAGATE_EXCEPTIONS"] = False
    assert client.get("/boom").status_code == 500
    row = json.loads(client.fake.lindex("web:logs", 0))
    assert row["level"] == "ERROR" and "kaboom" in row["exc"] and row["uid"] == "111"


def test_push_off_is_explained(client):
    from app import push
    _admin(client)
    push._warned_off = False
    with client.application.app_context():
        push.send("111", "trade", "hi")
    assert "VAPID" in json.loads(client.fake.lindex("web:logs", 0))["msg"]
    page = client.get("/admin/logs").data.decode()
    assert "🔴 Off" in page and "key missing" in page


def test_push_failures_are_counted_and_shown(client, pushy, monkeypatch):
    from app import push
    h = _admin(client)
    client.post("/community/push/subscribe", json=_browser_sub("https://push.example.com/ok"), headers=h)
    client.post("/admin/logs/push_test", headers=h)
    assert len(pushy) == 1

    class Resp:
        status_code, text, headers, reason = 403, "invalid JWT provided", {}, "Forbidden"
    monkeypatch.setattr("requests.post", lambda *a, **k: Resp())
    client.post("/admin/logs/push_test", headers=h)
    with client.application.app_context():
        st = push.status()
    assert st["enabled"] and st["sent"] == 1 and st["failed"] == 1 and "invalid JWT" in st["last_error"]
    page = client.get("/admin/logs").data.decode()
    assert "invalid JWT provided" in page and "push.example.com" in page


def test_due_notifications_survive_a_bad_entry(client):
    from app import social
    player(client, "111")
    with client.application.app_context():
        dbmod.r().zadd("web:notif:due", {"111|bad": 1, "111|good": 2})
        dbmod.r().hset("web:notif:due:data", "111|bad", "{not json")
        social.notify_later("111", "good", 2, "journey", "Home!")
        assert social.flush_due(now=10) == 1
        assert social.feed("111")[0]["text"] == "Home!"


# ── Rewards ──────────────────────────────────────────────────────────────────

def _send(c, h, **form):
    data = {"op": "create", "title": "Sorry!", "text": "Downtime", "fragments": "500", "super_fragments": "2",
            "energy": "3", "audience": "existing", "until": "", **form}
    return c.post("/admin/rewards", data=data, headers=h)


def test_existing_players_claim_a_reward_once(client):
    h = _admin(client)
    player(client, "222", fragments=0, super_fragments=0)
    _send(client, h, item=["1:2"], stand=["1"], shiny="1")
    mail = json.loads(next(iter(client.fake.hvals("web:mail"))))
    assert mail["recipients"] == 2 and mail["rewards"]["items"] == {"1": 2}

    h2 = login(client, "222")
    page = client.get("/community/inbox").data.decode()
    assert "Sorry!" in page and "500 Meteor Dust" in page and "Shiny" in page
    before = len(doc(client, "222")["items"])
    client.post("/community/rewards/claim", data={"id": mail["id"]}, headers=h2)
    d = doc(client, "222")
    assert d["fragments"] == 500 and d["super_fragments"] == 2 and len(d["items"]) == before + 2
    assert any(s["id"] == 1 and s.get("shiny") for s in d["storage_characters"])
    client.post("/community/rewards/claim", data={"id": mail["id"]}, headers=h2)  # a second time does nothing
    assert doc(client, "222")["fragments"] == 500
    assert "reward-list" not in client.get("/community/inbox").data.decode()

    player(client, "333")  # joined after it was sent
    login(client, "333")
    assert "reward-list" not in client.get("/community/inbox").data.decode()

    login(client, "111")
    page = client.get("/admin/rewards").data.decode()
    assert "Sorry!" in page and ">1</td>" in page  # one claim


def test_everyone_rewards_reach_new_players_and_end_dates_close_them(client):
    h = _admin(client)
    _send(client, h, audience="everyone", until="2999-01-01")
    player(client, "333", fragments=0)
    h3 = login(client, "333")
    client.post("/community/rewards/claim", headers=h3)  # claim all
    assert doc(client, "333")["fragments"] == 500

    login(client, "111")
    mail_id = json.loads(next(iter(client.fake.hvals("web:mail"))))["id"]
    client.post("/admin/rewards", data={"op": "end", "id": mail_id}, headers=h)
    player(client, "444")
    login(client, "444")
    assert "reward-list" not in client.get("/community/inbox").data.decode()


def test_listed_players_are_notified_and_others_cant_claim(client):
    h = _admin(client)
    player(client, "222")
    player(client, "333", fragments=0)
    _send(client, h, audience="players", players="222")
    mail_id = json.loads(next(iter(client.fake.hvals("web:mail"))))["id"]
    with client.application.app_context():
        from app import social
        assert "Sorry!" in social.feed("222")[0]["text"]
    h3 = login(client, "333")
    client.post("/community/rewards/claim", data={"id": mail_id}, headers=h3)
    assert doc(client, "333")["fragments"] == 0

    login(client, "111")
    _send(client, h, audience="players", players="nobody-like-this")
    assert client.fake.hlen("web:mail") == 1  # refused: unknown player
    _send(client, h, fragments="0", super_fragments="0", energy="0")
    assert client.fake.hlen("web:mail") == 1  # refused: nothing to give


def test_a_full_storage_keeps_the_reward_waiting(client):
    from app.game import logic
    h = _admin(client)
    stands = [char(1) for _ in range(logic.STORAGE_CAPACITY)]
    player(client, "222", fragments=0, storage_characters=stands)
    _send(client, h, stand=["2"])
    h2 = login(client, "222")
    client.post("/community/rewards/claim", headers=h2)
    d = doc(client, "222")
    assert d["fragments"] == 0 and len(d["storage_characters"]) == logic.STORAGE_CAPACITY
    assert "reward-list" in client.get("/community/inbox").data.decode()  # still claimable


def test_a_subscription_from_an_old_key_is_dropped(client, pushy, monkeypatch):
    from app import push
    h = _admin(client)
    client.post("/community/push/subscribe", json=_browser_sub(), headers=h)
    assert 'name="push-key"' in client.get("/story").data.decode()  # app.js renews old subscriptions from it

    class Resp:
        status_code, headers, reason = 401, {}, "Unauthorized"
        text = '{"code":401,"errno":109,"error":"Unauthorized","message":"VAPID public key mismatch"}'
    monkeypatch.setattr("requests.post", lambda *a, **k: Resp())
    with client.application.app_context():
        assert push.pair_ok() is True
        dbmod.r().delete("web:seen:111")
        push.send("111", "trade", "hi")
        assert push.devices("111") == 0 and push.status()["dropped"] == 1


def test_keys_from_two_pairs_are_flagged(client, pushy):
    from app import push
    from test_push import _vapid
    _admin(client)
    client.application.config["VAPID_PUBLIC_KEY"] = _vapid()[0]  # another pair's public half
    with client.application.app_context():
        assert push.pair_ok() is False
    assert "different pairs" in client.get("/admin/logs").data.decode()
