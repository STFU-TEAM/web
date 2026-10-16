"""Link previews (app/og.py): shared cards, profiles, stands, news and the site show a 1200x630 picture."""
import io
import re

from PIL import Image

from app import news, og
from test_app import char, client, login  # noqa: F401  (client is a fixture)
from test_features import player


def _no_network(monkeypatch):
    """Stand pictures come from the image server: tests draw them from a plain square instead."""
    buf = io.BytesIO()
    Image.new("RGB", (300, 400), (200, 60, 120)).save(buf, "PNG")
    real = og.fetch_art
    monkeypatch.setattr(og, "fetch_art", lambda redis, url: buf.getvalue() if url and url.startswith("https://") else real(redis, url))


def _image(client, path):
    r = client.get(path)
    assert r.status_code == 200 and r.mimetype == "image/jpeg", path
    return Image.open(io.BytesIO(r.data)).size


def _og_image(page: str) -> str:
    return re.search(r'property="og:image" content="([^"]+)"', page).group(1)


def test_a_shared_card_previews_as_a_big_picture(client, monkeypatch):
    _no_network(monkeypatch)
    mine = char(10, xp=4000, awaken=2)
    player(client, "302", main_characters=[mine])
    h = login(client, "302", name="Jotaro")
    url = client.post("/share", data={"kind": "stand", "ref": mine["uuid"]}, headers=h).get_json()["url"]
    path = url.split("localhost")[-1]
    page = client.get(path).data.decode()
    image = _og_image(page)
    assert image.endswith(path + "/preview.jpg") and image.startswith("http")  # absolute, for the crawlers
    assert 'content="summary_large_image"' in page and 'og:image:width" content="1200"' in page
    assert _image(client, path + "/preview.jpg") == (og.W, og.H)
    assert client.get(path + "/preview.jpg").data == client.get(path + "/preview.jpg").data  # drawn once, cached
    assert client.get("/s/nope/preview.jpg").status_code == 404


def test_profiles_stands_news_and_the_site_preview_too(client, monkeypatch):
    _no_network(monkeypatch)
    player(client, "303", main_characters=[char(84, xp=9000, awaken=3)])
    assert _og_image(client.get("/u/303").data.decode()).endswith("/u/303/preview.jpg")
    assert _image(client, "/u/303/preview.jpg") == (og.W, og.H)
    assert _og_image(client.get("/stands/84").data.decode()).endswith("/stands/84/preview.jpg")
    assert _image(client, "/stands/84/preview.jpg") == (og.W, og.H)
    assert _image(client, "/preview.jpg") == (og.W, og.H)
    assert _og_image(client.get("/").data.decode()).endswith("/preview.jpg")
    post = news.save_post("1", "Patch notes", "## Big update\n- **New** stands", kind="patch")
    page = client.get(f"/news/{post['id']}").data.decode()
    assert _og_image(page).endswith(f"/news/{post['id']}/preview.jpg") and "## Big" not in page.split("<body")[0]
    assert _image(client, f"/news/{post['id']}/preview.jpg") == (og.W, og.H)


def test_titles_lose_the_emoji_the_font_cant_draw():
    assert og._clean("pulled ✨ shiny ★5 ☠", og.DISPLAY, 60) == "pulled shiny ★5"
