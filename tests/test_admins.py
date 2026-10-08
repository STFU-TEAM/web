"""Promoting admins from the admin panel: the owners (DISCORD_ADMIN_IDS) promote and remove, promoted admins get the
whole panel but can't hand it on, and every change is audited."""
import json

from test_app import client, login  # noqa: F401  (client is a fixture)
from test_features import player


def test_owners_promote_and_remove_admins(client):
    client.application.config["DISCORD_ADMIN_IDS"] = {"111"}
    player(client, "111")
    player(client, "222")
    player(client, "333")
    assert client.get("/admin").status_code == 302  # not logged in

    h = login(client, "222")
    assert client.get("/admin").status_code == 403
    assert "/admin" not in client.get("/story").data.decode().split("<main")[0]  # no Admin link in the nav

    h = login(client, "111")
    page = client.get("/admin/admins").data.decode()
    assert "Make admin" in page and "Owner" in page
    client.post("/admin/admins/promote", data={"player": "222"}, headers=h)
    assert client.fake.hexists("web:admins", "222")
    client.post("/admin/admins/promote", data={"player": "nobody-here"}, headers=h)
    assert client.fake.hlen("web:admins") == 1
    assert json.loads(client.fake.lindex("web:admin:audit", 0))["kind"] == "admin_promote"

    # a promoted admin has the panel and the nav link, but can't promote or remove anyone
    h = login(client, "222")
    assert client.get("/admin").status_code == 200
    assert 'href="/admin"' in client.get("/story").data.decode()
    page = client.get("/admin/admins").data.decode()
    assert "Make admin" not in page and "Remove" not in page
    client.post("/admin/admins/promote", data={"player": "333"}, headers=h)
    client.post("/admin/admins/222/demote", headers=h)
    assert not client.fake.hexists("web:admins", "333") and client.fake.hexists("web:admins", "222")

    h = login(client, "111")
    client.post("/admin/admins/111/demote", headers=h)  # owners live in the config, not here
    client.post("/admin/admins/222/demote", headers=h)
    assert client.fake.hlen("web:admins") == 0
    assert json.loads(client.fake.lindex("web:admin:audit", 0))["kind"] == "admin_demote"
    login(client, "222")
    assert client.get("/admin").status_code == 403
