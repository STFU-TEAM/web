"""The Animation Lab, built: the damage preview, the stand sheet's tabs, the daily stamp, the ranked promotion moment."""
import time

from app.db import load_fight, r, save_fight
from app.game import draft as draft_mod, ranked_bot
from app.game.user import User
from app.routes.battles import QUEUE_SINCE
from test_app import char, client, doc, login, put  # noqa: F401  (client is a fixture)
from test_features import player, ranked_player


def test_targets_preview_the_health_a_hit_would_take(client):
    player(client, "111", main_characters=[char(1, xp=500)])
    h = login(client, "111")
    client.post("/story/fight", headers=h)
    page = client.get("/story", headers=h).data.decode()
    assert 'data-hit="≈ ' in page and ("% of its health" in page or "finishes it" in page)
    assert 'class="hp-ghost"' in page


def test_the_stand_panel_splits_into_tabs(client):
    d = player(client, "111", main_characters=[char(1, xp=500)])
    login(client, "111")
    panel = client.get(f"/team/stand/{d['main_characters'][0]['uuid']}").data.decode()
    assert 'data-tab="stats"' in panel
    for tab in ("stats", "gear", "stars", "chips"):
        assert f'data-ptab="{tab}"' in panel and f'data-group="{tab}"' in panel


def test_a_claimed_day_wears_a_stamp_and_today_slams_on(client):
    player(client, "111", main_characters=[char(1, xp=500)])
    h = login(client, "111")
    page = client.post("/daily", headers=h).data.decode()
    assert 'class="streak-stamp new"' in page and "済" in page and 'class="streak-ink"' in page


def test_a_ranked_win_into_a_new_tier_is_a_promotion(client):
    ranked_player(client, "111", global_elo=999)
    h = login(client, "111")
    client.post("/battles/ranked/queue", headers=h)
    r().set(QUEUE_SINCE.format("111"), int(time.time() - ranked_bot.BOT_WAIT - 1))
    client.post("/battles/ranked/bot", headers=h)
    draft = draft_mod.of(r(), "111")
    bot = draft["bot"]["id"]
    client.post("/battles/ranked/ban", data={"ban": draft["rosters"][bot][:draft_mod.BANS]}, headers=h)
    mine = draft_mod.remaining(draft_mod.of(r(), "111"), "111")
    client.post("/battles/ranked/compose", data={f"slot{i}": u for i, u in enumerate(mine)}, headers=h)
    fight = load_fight("111")
    fight.forfeit(1)  # the bot gives up: the next request settles the duel
    save_fight("111", fight)
    page = client.post("/battles/attack", headers=h).data.decode()
    fight = load_fight("111")
    assert User(doc(client, "111")).global_elo >= 1000
    assert fight.meta["promoted"]["111"] == ["ACT 2", "ACT 3"]
    assert 'class="promo-moment"' in page and "PROMOTED" in page


def test_profile_stands_open_their_build_read_only(client):
    d = player(client, "222", main_characters=[char(1, xp=500)])
    uuid = d["main_characters"][0]["uuid"]
    profile = client.get("/u/222").data.decode()
    assert f'href="/u/222/stand/{uuid}"' in profile and 'id="stand-panel"' in profile
    part = client.get(f"/u/222/stand/{uuid}", headers={"HX-Request": "true"}).data.decode()
    assert 'class="panel-grid build-view"' in part and 'data-ptab="chips"' in part and "Stand wiki" in part
    assert 'data-inspect="SSR"' in part and "hx-post" not in part  # nothing on it changes the stand
    page = client.get(f"/u/222/stand/{uuid}").data.decode()
    assert "<html" in page and "build-view" in page  # no script: the link opens a full page
    assert client.get("/u/222/stand/nope").status_code == 404


def test_the_stand_panel_has_inspect(client):
    d = player(client, "111", main_characters=[char(1, xp=500)])
    login(client, "111")
    panel = client.get(f"/team/stand/{d['main_characters'][0]['uuid']}").data.decode()
    assert 'class="card-tools"' in panel and 'data-inspect="SSR"' in panel and "data-params-flip" in panel
