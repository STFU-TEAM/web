"""Chat emotes and stickers stored in Redis (app/stickers.py)."""
import io

import fakeredis
import pytest
from PIL import Image

from app import stickers
from test_app import char, client, doc, login, put  # noqa: F401  (client is a fixture)
from test_features import player


def _png(color=(255, 0, 0)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (16, 16), color).save(buf, "PNG")
    return buf.getvalue()


def _gif() -> bytes:
    buf = io.BytesIO()
    frames = [Image.new("P", (8, 8), i) for i in range(3)]
    frames[0].save(buf, "GIF", save_all=True, append_images=frames[1:], loop=0)
    return buf.getvalue()


def test_only_real_images_with_clean_names_get_in():
    db = fakeredis.FakeRedis()
    meta = stickers.add(db, ":Menacing:", "emote", _png(), "1")
    assert meta["name"] == "menacing" and meta["mime"] == "image/png"
    assert stickers.add(db, "dance", "sticker", _gif(), "1")["mime"] == "image/gif"
    for name, kind, data in (("x", "emote", _png()), ("bad name", "emote", _png()), ("ok_name", "huge", _png()),
                             ("fake", "emote", b"<script>alert(1)</script>"),
                             ("big", "emote", b"\x89PNG" + b"0" * (stickers.MAX_BYTES + 1))):
        with pytest.raises(stickers.StickerError):
            stickers.add(db, name, kind, data, "1")
    assert set(stickers.all_stickers(db)) == {"menacing", "dance"}


def test_messages_draw_known_codes_and_escape_everything_else(client):
    db = client.fake
    with client.application.test_request_context():
        stickers.add(db, "menacing", "emote", _png(), "1")
        stickers.add(db, "dance", "sticker", _gif(), "1")
        known = stickers.all_stickers(db)
        html = str(stickers.render("ゴゴゴ :menacing: <b>hi</b> :nope:", known))
        assert 'class="chat-emote"' in html and "&lt;b&gt;hi&lt;/b&gt;" in html and ":nope:" in html
        alone = str(stickers.render("  :dance: ", known))
        assert 'class="chat-sticker"' in alone and "chat-emote" not in alone


def test_stickers_are_served_listed_and_shown_in_chat(client):
    player(client, "601", main_characters=[char(1)])
    h = login(client, "601")
    with client.application.test_request_context():
        stickers.add(client.fake, "menacing", "emote", _png(), "601")
    got = client.get("/chat/stickers/menacing")
    assert got.status_code == 200 and got.mimetype == "image/png" and "max-age" in got.headers["Cache-Control"]
    assert client.get("/chat/stickers/nope").status_code == 404
    listed = client.get("/chat/stickers.json").get_json()
    assert listed[0]["name"] == "menacing" and "/chat/stickers/menacing" in listed[0]["url"]
    from app.db import r
    from app.game import chat as C
    page = client.get("/chat", headers=h).data.decode()
    token = page.split('action="/chat/c/')[1].split('"')[0]
    client.post(f"/chat/c/{token}", data={"text": "look :menacing:"}, headers={**h, "HX-Request": "true"})
    page = client.get("/chat", headers=h).data.decode()
    assert 'class="chat-emote"' in page


def test_admins_upload_and_delete_from_the_panel(client):
    player(client, "602", main_characters=[char(1)])
    client.application.config["DISCORD_ADMIN_IDS"] = {"602"}
    h = login(client, "602")
    client.post("/admin/stickers/add", data={"name": "jojo", "kind": "sticker", "file": (io.BytesIO(_png()), "a.png")},
                headers=h, content_type="multipart/form-data")
    assert "jojo" in stickers.all_stickers(client.fake)
    assert ":jojo:" in client.get("/admin/stickers", headers=h).data.decode()
    client.post("/admin/stickers/delete", data={"name": "jojo"}, headers=h)
    assert "jojo" not in stickers.all_stickers(client.fake)
    assert client.fake.get(stickers.IMG_KEY.format("jojo")) is None
