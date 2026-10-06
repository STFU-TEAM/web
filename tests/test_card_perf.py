"""Shiny and full-art cards stay cheap in big grids: animated art shows a still poster until hovered, and the
CSS only animates the card being looked at."""
import io
import os
import re
import sys

from test_app import client  # noqa: F401  (client is a fixture)


def test_animated_art_shows_its_poster_in_grids_and_plays_on_the_big_card(client):
    art, stills = client.application.extensions["art_files"], client.application.extensions["art_stills"]
    sid = 1
    art["shiny"][sid], stills["shiny"][sid] = "1.webp", "1.still.webp"
    try:
        grid = client.get("/stands?look=shiny", headers={"HX-Request": "true"}).data.decode()
        img = re.search(r'<img[^>]+alt="Star platinum"[^>]*>', grid).group(0)
        assert "/shiny/1.still.webp" in img and 'data-anim="' in img and "/shiny/1.webp" in img
        card_art = client.application.jinja_env.globals["card_art"]
        with client.application.test_request_context():
            url, own, anim = card_art(sid, shiny=True, animate=True)  # the big card plays it straight away
            assert url.endswith("/shiny/1.webp") and own and anim is None
            assert card_art(sid)[2] is None  # a classic card has nothing to animate
    finally:
        art["shiny"].pop(sid, None)
        stills["shiny"].pop(sid, None)


def test_pulled_stands_can_be_shiny_one_in_a_thousand(client, monkeypatch):
    from app.game import logic
    from test_app import doc, login
    from test_features import player
    assert logic.SHINY_CHANCE == 1 / 1000
    monkeypatch.setattr(logic, "SHINY_CHANCE", 1.0)  # every stand shiny
    player(client, "111", super_fragments=2)
    h = login(client, "111")
    r = client.post("/banners/0/pull", headers=h).data.decode()
    d = doc(client, "111")
    owned = d["main_characters"] + d["storage_characters"]
    assert len(owned) == 10 and all(c.get("shiny") for c in owned)
    assert 'data-shiny="1"' in r and "✨ 10 shiny!" in r
    monkeypatch.setattr(logic, "SHINY_CHANCE", 0.0)
    client.post("/banners/0/pull", headers=h)
    d = doc(client, "111")
    assert sum(bool(c.get("shiny")) for c in d["main_characters"] + d["storage_characters"]) == 10
    assert "1 in 1 000" in client.get("/wiki/stands").data.decode()  # the site's thin-space thousands


def test_a_shiny_stays_shiny_through_requiem(client):
    from test_app import char, doc, login
    from test_features import player
    kq = char(49, xp=10_000, awaken=2)
    kq["shiny"] = True
    player(client, "111", main_characters=[kq], items=[{"id": 3}])
    client.post("/items/use", data={"item": 3, "uuid": kq["uuid"], "mode": "requiem"}, headers=login(client, "111"))
    evolved = doc(client, "111")["main_characters"][0]
    assert evolved["id"] == 58 and evolved.get("shiny") is True


def test_card_effects_only_animate_where_someone_is_looking():
    css = open(os.path.join(os.path.dirname(__file__), "..", "app", "static", "css", "app.css"), encoding="utf-8").read()
    rest = re.search(r"\.card\.shiny \{[^}]*\}", css).group(0)
    assert "animation" not in rest
    sheen = re.search(r"\.card\.fullart::after \{[^}]*\}", css).group(0)
    assert "animation" not in sheen
    assert ".card.shiny:is(:hover, :focus-within, .big):not(.reveal) { animation: holo" in css
    assert "@keyframes twinkle { 50% { transform: scale(1.25) rotate(15deg); } }" in css  # no filter repaint


def test_art_helper_optimizes_stills_and_animations(tmp_path, monkeypatch):
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
    import art_helper as A
    from PIL import Image
    monkeypatch.setattr(A, "ART", str(tmp_path))
    big = Image.new("RGB", (1800, 3000), (200, 40, 90))
    buf = io.BytesIO()
    big.save(buf, "PNG")
    assert A.save("artwork", 7, buf.getvalue(), crop=False) == "7.webp"
    with Image.open(tmp_path / "artwork" / "7.webp") as out:
        assert out.height == A.STILL_MAX_H
    frames = [Image.new("RGB", (640, 640), (i * 2, 0, 0)) for i in range(150)]
    buf = io.BytesIO()
    frames[0].save(buf, "GIF", save_all=True, append_images=frames[1:], duration=40, loop=0)
    assert A.save("shiny", 9, buf.getvalue(), crop=True) == "9.webp"
    with Image.open(tmp_path / "shiny" / "9.webp") as anim:
        assert anim.height == A.ANIM_MAX_H and 1 < anim.n_frames <= A.ANIM_MAX_FRAMES
    assert (tmp_path / "shiny" / "9.still.webp").exists()
    # a still replacing it clears the old poster
    A.save("shiny", 9, (tmp_path / "artwork" / "7.webp").read_bytes(), crop=False)
    assert not (tmp_path / "shiny" / "9.still.webp").exists()
