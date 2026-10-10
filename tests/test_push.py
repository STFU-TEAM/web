"""Web push: subscriptions, who gets pushed (kinds, away from the site), dead devices, and the energy-full push."""
import base64
import json

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

import app.db as dbmod
from app.game.user import create_user
from test_app import client, doc, login, put  # noqa: F401  (client is a fixture)


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _vapid():
    key = ec.generate_private_key(ec.SECP256R1())
    return (_b64(key.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)),
            _b64(key.private_numbers().private_value.to_bytes(32, "big")))


def _browser_sub(endpoint="https://push.example.com/abc"):
    """A subscription as a browser makes it: its own P-256 key and auth secret."""
    key = ec.generate_private_key(ec.SECP256R1())
    p256dh = key.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    return {"endpoint": endpoint, "keys": {"p256dh": _b64(p256dh), "auth": _b64(b"0123456789abcdef")}}


@pytest.fixture()
def pushy(client, monkeypatch):
    """Push configured, deliveries run inline, the push service replaced by a recorder."""
    from app import push
    public, private = _vapid()
    client.application.config.update(VAPID_PUBLIC_KEY=public, VAPID_PRIVATE_KEY=private)
    monkeypatch.setattr(push._pool, "submit", lambda fn, *a: fn(*a))
    sent = []

    class Resp:
        def __init__(self, code):
            self.status_code, self.text, self.headers, self.reason = code, "", {}, "Gone" if code == 410 else "Created"

    def fake_post(url, data=None, headers=None, timeout=None, **_):
        sent.append({"url": url, "headers": headers, "data": data})
        return Resp(410 if "gone" in url else 201)

    monkeypatch.setattr("requests.post", fake_post)
    return sent


def _player(c, uid="111"):
    put(c, create_user(uid))
    return login(c, uid)


def test_a_push_is_encrypted_signed_and_sent_only_while_away(client, pushy):
    from app import push
    h = _player(client)
    r = client.post("/community/push/subscribe", json=_browser_sub(), headers=h)
    assert r.status_code == 200 and r.get_json()["devices"] == 1
    # this browser (its pdev cookie names its subscription) has the site open: no push for it
    client.set_cookie("pdev", push.device_id("https://push.example.com/abc"))
    client.get("/story")
    with client.application.app_context():
        push.send("111", "trade", "Jotaro sent you a trade offer.", "/trades")
        assert not pushy
        # a second device (a phone) still gets it while the first is in use
        client.post("/community/push/subscribe", json=_browser_sub("https://push.example.com/phone"), headers=h)
        push.send("111", "trade", "Jotaro sent you a trade offer.", "/trades")
        assert [p["url"] for p in pushy] == ["https://push.example.com/phone"]
        pushy.clear()
        push.unsubscribe("111", "https://push.example.com/phone")
        dbmod.r().delete("web:seen:111", f"web:seen:111:{push.device_id('https://push.example.com/abc')}")
        push.send("111", "achievement", "Achievement unlocked")  # not a push kind
        push.send("111", "trade", "Jotaro sent you a trade offer.", "/trades")
    assert len(pushy) == 1
    req = pushy[0]
    assert req["url"] == "https://push.example.com/abc"
    assert req["headers"]["Content-Encoding"] == "aes128gcm" and req["headers"]["Authorization"].startswith("vapid t=")
    assert req["data"] and b"Jotaro" not in req["data"]  # encrypted for the browser


def test_dead_devices_are_dropped(client, pushy):
    from app import push
    h = _player(client)
    client.post("/community/push/subscribe", json=_browser_sub("https://push.example.com/gone"), headers=h)
    client.post("/community/push/subscribe", json=_browser_sub("https://push.example.com/ok"), headers=h)
    with client.application.app_context():
        dbmod.r().delete("web:seen:111")
        push.send("111", "gift", "A gift!")
        assert push.devices("111") == 1


def test_social_notify_pushes_and_the_inbox_offers_it(client, pushy):
    from app import social
    h = _player(client)
    client.post("/community/push/subscribe", json=_browser_sub(), headers=h)
    page = client.get("/community/inbox").data.decode()
    assert "Notifications on this device" in page and "data-key=" in page
    with client.application.app_context():
        dbmod.r().delete("web:seen:111")
        social.notify("111", "friend", "Dio wants to be friends.", "/community/inbox")
    assert len(pushy) == 1
    assert client.post("/community/push/subscribe", json={"endpoint": "http://x"}, headers=h).status_code == 400


def test_energy_full_push_is_scheduled_and_stays_out_of_the_inbox(client, pushy):
    import time
    from app import push, social
    from app.game import logic
    from app.game.user import User
    h = _player(client)
    client.post("/community/push/subscribe", json=_browser_sub(), headers=h)
    client.post("/community/push/energy", data={"on": "1"}, headers=h)
    with client.application.app_context():
        user = User(doc(client, "111"))
        logic.spend_energy(user, 1)
        due = dbmod.r().zscore("web:notif:due", "111|energy")
        assert due and due > time.time()
        dbmod.r().delete("web:seen:111")
        social.flush_due(now=due + 1)
        assert not social.feed("111")  # push only
        push.set_energy("111", False)
        assert dbmod.r().zscore("web:notif:due", "111|energy") is None
    assert len(pushy) == 1


def test_push_is_off_without_keys(client):
    h = _player(client)
    assert "Notifications on this device" not in client.get("/community/inbox").data.decode()
    assert client.post("/community/push/subscribe", json=_browser_sub(), headers=h).status_code == 400
