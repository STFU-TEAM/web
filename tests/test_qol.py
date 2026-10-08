"""The Today card, the weekly off-meta bounty, the ranked meta chart and story auto-replay."""
import app.db as dbmod
from app.game import bounty, story
from test_app import char, client, doc, login, put  # noqa: F401  (client is a fixture)
from test_features import player
from test_progression import REAL_GATES  # at import, before the shared fixture opens every gate


def test_today_card_lists_whats_ready_first(client, monkeypatch):
    from app.game import progression
    monkeypatch.setattr(progression, "GATES", REAL_GATES)  # the shared fixture opens everything
    player(client, "111", main_characters=[char(1, xp=5000)], energy=3, web_story={"cleared": 0})
    login(client, "111")
    page = client.get("/").data.decode()
    assert "Today" in page and "Daily reward" in page and "Crusaders" in page
    assert "Mirror World" not in page.split('id="today-h"')[1].split("</section>")[0]  # not opened yet
    rows = page.split('class="today-grid"')[1]
    assert rows.index("today-row ready") < rows.index("Energy 3/")  # ready rows come before the waiting ones


def test_bounty_counts_fitting_wins_and_pays_once(client, monkeypatch):
    monkeypatch.setattr(bounty, "current", lambda when=None: bounty.BY_KEY["underdogs"])
    rs = [char(i) for i in (7, 8, 9)]  # R / SR stands
    from app.game.character import CHARACTER_FILE
    assert all(CHARACTER_FILE[c["id"] - 1]["rarity"] in ("R", "SR") for c in rs)
    player(client, "111", fragments=0, items=[])
    from app.game.character import character_from_dict
    from app.game.user import User
    user = User(doc(client, "111"))
    team = [character_from_dict(c) for c in rs]
    big = [character_from_dict(char(cid)) for cid in (1, 2, 3)]
    assert bounty.record_win(user, team[:2]) is None  # a full team only
    if not all(c.rarity in ("R", "SR") for c in big):
        assert bounty.record_win(user, big) is None
    for _ in range(bounty.BY_KEY["underdogs"]["goal"]):
        line = bounty.record_win(user, team)
    assert "claim it" in line and bounty.view(user)["done"]
    paid = bounty.claim(user)
    assert user.fragments == bounty.BY_KEY["underdogs"]["reward"]["fragments"] and paid["claimed"]
    assert [i.id for i in user.items] == bounty.BY_KEY["underdogs"]["reward"]["items"]
    assert bounty.record_win(user, team) is None
    try:
        bounty.claim(user)
        raise AssertionError("claimed twice")
    except Exception as e:
        assert "already claimed" in str(e)


def test_ranked_picks_build_the_meta_chart(client):
    bounty.record_picks([1, 2, 3, 1, 4, 5])  # two ranked teams: Star Platinum in both
    top = bounty.meta(3)
    assert top[0]["id"] == 1 and top[0]["picks"] == 2 and top[0]["share"] == 100 and top[1]["share"] == 50
    player(client, "111")
    login(client, "111")
    assert "This season's meta" in client.get("/battles?mode=ranked").data.decode()


def test_auto_replay_runs_cleared_stages_for_energy(client):
    team = [char(i, xp=10_000, awaken=3) for i in (1, 2, 3)]
    player(client, "111", main_characters=team, energy=3, fragments=0, web_story={"cleared": 3})
    h = login(client, "111")
    assert "Auto-replay" in client.get("/story").data.decode()
    client.post("/story/auto", data={"stage": 0, "count": 5}, headers=h)
    d = doc(client, "111")
    assert d["energy"] == 0 and d["fragments"] > 0  # three replays, then out of energy
    assert d["web_story"]["cleared"] == 3 and dbmod.load_fight("111") is None  # nothing left open, no progress skipped
    assert d["main_characters"][0]["xp"] > 10_000
    page = client.get("/story").data.decode()
    assert "×3: 3 won" in page
    client.post("/story/auto", data={"stage": 3, "count": 1}, headers=h)  # not cleared yet: refused
    assert doc(client, "111")["web_story"]["cleared"] == 3
