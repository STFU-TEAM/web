"""Requiem mode: every track opens after its content, is tuned against the benchmark team, and pays once."""
import app.db as dbmod
from app.game import requiem as R
from app.game import story
from test_app import char, client, doc, login, put  # noqa: F401  (client is a fixture)
from test_features import player


def test_tracks_cover_the_story_every_universe_and_carry_me_with_a_tuned_multiplier():
    assert R.TOTAL == sum(len(t["stages"]) for t in R.TRACKS) and len(R.TRACKS) == 8
    for t in R.TRACKS:
        assert t["stages"][-1].get("finale")
        assert len(R.MULT.get(t["key"], [])) == len(t["stages"])  # calibrated (scripts/balance.py requiem)
        assert all(0.3 < R.mult(t["key"], i) < 10 for i in range(len(t["stages"])))
    team = R.enemy_team("story", 0)
    assert all(c.level == 100 and c.awaken == 5 for c in team)
    assert R.guest("carry_me", 0) is not None and R.guest("story", 0) is None
    finale = R.reward_for("story", len(R.BY_KEY["story"]["stages"]) - 1)
    assert finale["super_fragments"] == 2 and R.REQUIEM_ARROW in finale["items"]


def test_requiem_opens_after_the_story_and_pays_once(client, monkeypatch):
    player(client, "111", fragments=0, super_fragments=0, energy=10, main_characters=[char(1)])
    h = login(client, "111")
    assert client.get("/requiem").headers["Location"].endswith("/story")
    d = doc(client, "111")
    d["web_story"] = {"cleared": story.TOTAL}
    put(client, d)
    page = client.get("/requiem").data.decode()
    assert "Requiem" in page and "maxed team wins about" in page and "🔒" in page  # the universes are still locked
    monkeypatch.setattr(R, "MULT", {**R.MULT, "story": [0.001] + R.MULT["story"][1:]})
    client.post("/requiem/fight", data={"track": "story"}, headers=h)
    fight = dbmod.load_fight("111")
    assert fight.kind == "requiem" and fight.meta == {"track": "story", "stage": 0}
    for c in fight.sides[1].chars:
        c.current_hp = 0
    dbmod.save_fight("111", fight)
    client.post("/requiem/attack", data={"log_len": len(fight.log)}, headers=h)
    client.post("/requiem/leave", headers=h)
    d = doc(client, "111")
    assert d["web_requiem"]["story"] == 1 and d["fragments"] >= R.reward_for("story", 0)["fragments"]
    client.post("/requiem/fight", data={"track": "au:world_unbroken"}, headers=h)
    assert client.fake.get("web:fight:111") is None  # that universe isn't cleared normally yet
