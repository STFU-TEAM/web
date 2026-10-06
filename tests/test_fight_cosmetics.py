"""Shiny and full-art stands fight with their own art, behind a "✨ Cosmetics" toggle kept in the session."""
import re

from test_app import char, client, doc, login, put  # noqa: F401  (client is a fixture)
from test_features import player


def _fighter(html, name):
    from markupsafe import escape
    m = re.search(r'<li class="fighter[^"]*"[^>]*data-name="%s"[^>]*>' % re.escape(str(escape(name))), html)
    assert m, (name, re.findall(r'data-name="([^"]*)"', html))
    return m.group(0)


def test_shiny_and_full_art_fighters_use_their_cosmetics_and_the_toggle_turns_them_off(client):
    from app.game.character import CHARACTER_FILE
    own = client.application.extensions["art_files"]["shiny"]
    painted = next(i for i in sorted(own) if CHARACTER_FILE[i - 1]["universe"] != "Dummy")    # its own shiny art
    hued = next(c["id"] for c in CHARACTER_FILE if c["id"] not in own and c["universe"] != "Dummy" and c["id"] != painted)
    a, b = char(painted), char(hued)
    a["shiny"] = b["shiny"] = True
    full = char(next(c["id"] for c in CHARACTER_FILE if c["id"] not in (painted, hued) and c["universe"] != "Dummy"), awaken=3)
    name = {c["id"]: c["name"] for c in CHARACTER_FILE}
    player(client, "111", main_characters=[a, b, full])
    h = login(client, "111")
    client.post("/battles/dummy/start", headers=h)
    page = client.get("/battles?mode=dummy", headers=h).data.decode()
    assert "✨ Cosmetics on" in page and 'aria-pressed="true"' in page
    f = _fighter(page, name[painted])
    assert " shiny" in f and 'data-art-own="1"' in f and "data-hue" not in f and "/shiny/" in f   # drawn shiny already
    f = _fighter(page, name[hued])
    assert " shiny" in f and 'data-hue="1"' in f                                                  # colours shifted
    f = _fighter(page, name[full["id"]])
    assert " fullart" in f and 'data-art-full="1"' in f
    assert "data-art-classic" not in _fighter(page, "dummy")  # nothing to switch on a plain stand

    assert client.post("/prefs/fight-cosmetics", data={"on": "0"}, headers=h).status_code == 204
    page = client.get("/battles?mode=dummy", headers=h).data.decode()
    assert "✨ Cosmetics off" in page
    f = _fighter(page, name[hued])
    assert " shiny" not in f.split('"')[1] and "data-hue" not in f and 'data-art-shiny="1"' in f  # both pictures still there


def test_the_toggle_only_shows_when_a_fighter_has_cosmetics(client):
    player(client, "111", main_characters=[char(1)])
    h = login(client, "111")
    client.post("/battles/dummy/start", headers=h)
    page = client.get("/battles?mode=dummy", headers=h).data.decode()
    assert "id=\"fight\"" in page and "data-cosmetics-toggle" not in page
