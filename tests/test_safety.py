"""Backups, error alerts and alt-account flags (the admin Safety tab)."""
import gzip
import logging
import pickle

import fakeredis

from app import alerts, alts, backup
from test_app import char, client, login, put  # noqa: F401  (client is a fixture)
from test_features import player


def test_a_backup_restores_every_key_with_its_expiry(tmp_path):
    db = fakeredis.FakeRedis()
    db.set("plain", "v")
    db.set("short", "x", ex=500)
    db.hset("users", mapping={"1": pickle.dumps({"fragments": 5}), "2": b"raw"})
    db.rpush("list", "a", "b")
    db.zadd("board", {"u": 3})
    row = backup.write(db, str(tmp_path))
    assert row["keys"] == 5 and (tmp_path / row["file"]).exists()
    with gzip.open(tmp_path / row["file"], "rb") as fh:
        assert pickle.load(fh)["v"] == 1
    db.flushdb()
    assert backup.restore(db, str(tmp_path / row["file"])) == 5
    assert db.get("plain") == b"v" and db.hget("users", "2") == b"raw" and db.lrange("list", 0, -1) == [b"a", b"b"]
    assert db.zscore("board", "u") == 3 and 0 < db.ttl("short") <= 500 and db.ttl("plain") == -1


def test_backups_rotate_and_only_known_names_download(tmp_path, monkeypatch):
    monkeypatch.setenv("BACKUP_DIR", str(tmp_path))
    db = fakeredis.FakeRedis()
    for i in range(backup.KEEP + 3):
        (tmp_path / f"{backup.PREFIX}2026010{i:02d}-000000{backup.SUFFIX}").write_bytes(b"x")
    backup.write(db)
    assert len(backup.files()) == backup.KEEP
    assert backup.path_of("../secret") is None and backup.path_of("other.txt") is None
    assert backup.path_of(backup.files()[0]["name"])


def test_the_safety_tab_backs_up_and_downloads(client, tmp_path, monkeypatch):
    monkeypatch.setenv("BACKUP_DIR", str(tmp_path))
    player(client, "900", main_characters=[char(1)])
    client.application.config["DISCORD_ADMIN_IDS"] = {"900"}
    h = login(client, "900")
    row = backup.run_once(client.fake)
    page = client.get("/admin/safety", headers=h).data.decode()
    assert "Database backups" in page and row["file"] in page
    got = client.get(f"/admin/safety/download/{row['file']}", headers=h)
    assert got.status_code == 200 and got.data[:2] == b"\x1f\x8b"  # gzip
    assert client.get("/admin/safety/download/..%2Fwsgi.py", headers=h).status_code == 404


def test_more_than_four_accounts_on_one_address_get_flagged():
    db = fakeredis.FakeRedis()
    for uid in ("a", "b", "c", "d"):
        alts.record(db, uid, "203.0.113.9")
    assert alts.flags(db) == []  # four is fine (a family, a dorm)
    alts.record(db, "e", "203.0.113.9")
    flagged = alts.flags(db)
    assert len(flagged) == 1 and flagged[0]["uids"] == ["a", "b", "c", "d", "e"]
    assert "203.0.113.9" not in str(db.keys("*")) + str(flagged)  # only a salted hash is kept
    assert alts.neighbours(db, "a") == ["b", "c", "d", "e"]
    alts.dismiss(db, flagged[0]["hash"])
    alts.record(db, "a", "203.0.113.9")
    assert alts.flags(db) == []  # dismissed: the same group stays quiet...
    alts.record(db, "f", "203.0.113.9")
    assert len(alts.flags(db)[0]["uids"]) == 6  # ...until another account joins it


def test_signing_in_records_the_address(client):
    from app import accounts
    acc = accounts.create_account("alttester", "password123")
    with client.session_transaction() as s:
        s["csrf"] = "tok"
    client.post("/auth/login", data={"username": "alttester", "password": "password123"},
                headers={"X-CSRF-Token": "tok"}, environ_base={"REMOTE_ADDR": "198.51.100.7"})
    assert client.fake.smembers(f"web:alts:uid:{acc['uid']}")


def test_errors_alert_once_per_repeat_window(monkeypatch):
    db = fakeredis.FakeRedis()
    sent = []
    monkeypatch.setattr(alerts._q, "put_nowait", sent.append)
    h = alerts.AlertHandler(db)
    log = logging.getLogger("app.test_alerts")
    rec = log.makeRecord(log.name, logging.ERROR, __file__, 1, "boom on %s", ("page",), None)
    h.emit(rec)
    h.emit(rec)
    assert len(sent) == 1 and "boom on page" in alerts._text(sent[0])


def test_maintenance_closes_the_site_to_players_but_not_admins(client):
    from app import maintenance
    player(client, "700", main_characters=[char(1)])
    player(client, "701", main_characters=[char(1)])
    client.application.config["DISCORD_ADMIN_IDS"] = {"700"}
    h = login(client, "700")
    assert "Maintenance mode" in client.get("/admin", headers=h).data.decode()
    client.post("/admin/maintenance", data={"on": "1", "message": "New Part coming!", "until": "18:00 UTC"}, headers=h)
    maintenance._cache["db"] = None
    page = client.get("/team", headers=h)
    assert page.status_code == 200 and "Maintenance is ON" in page.data.decode()  # the admin browses, with a banner

    login(client, "701")  # a player
    maintenance._cache["db"] = None
    blocked = client.get("/team")
    body = blocked.data.decode()
    assert blocked.status_code == 503 and "Under maintenance" in body and "New Part coming!" in body and "18:00 UTC" in body
    assert client.get("/battles/queue-bar", headers={"HX-Request": "true"}).headers.get("HX-Refresh") == "true"
    assert client.get("/healthz").status_code == 200 and client.get("/auth/login").status_code in (200, 302)

    login(client, "700")
    client.post("/admin/maintenance", data={"on": "0"}, headers=h)
    maintenance._cache["db"] = None
    login(client, "701")
    assert client.get("/team").status_code == 200
