"""Who's that Stand? (the daily guessing game) and the Gang Cup (the monthly gang tournament)."""
import datetime
import io
import pickle

import app.db as dbmod
from app.game import cup as CUP
from app.game import whos
from test_app import char, client, doc, login, put  # noqa: F401  (client is a fixture)
from test_features import player


def test_the_daily_stand_never_repeats_within_a_cycle_and_guesses_compare():
    days = [(datetime.date(2026, 1, 1) + datetime.timedelta(days=i)).isoformat() for i in range(60)]
    picks = [whos.answer(d) for d in days]
    assert len(set(picks)) == len(picks) and all(p in whos.POOL for p in picks)
    target = picks[0]
    same = whos.compare(target, target)
    assert same["correct"] and all(c["state"] == "hit" for c in same["cells"])
    other = next(p for p in whos.POOL if p != target)
    row = whos.compare(other, target)
    assert not row["correct"] and {c["label"] for c in row["cells"]} == {"Rarity", "Part", "Special", "Health", "Damage", "Speed"}
    assert whos.find(" STAR  platinum!") == whos.find("Star platinum") is not None


def test_guess_until_solved_with_clues_streak_ladder_and_reward(client, monkeypatch):
    player(client, "111", fragments=0)
    h = login(client, "111")
    page = client.get("/whos-that-stand").data.decode()
    assert "Who's that Stand?" in page and "wts-names" in page
    target = whos.answer()
    tname = whos.facts(target)["name"]
    import re
    outside = re.sub(r"<datalist.*?</datalist>", "", page, flags=re.S)  # (the suggestions list every stand)
    assert tname not in outside and f"/{target}.png" not in page  # the page never holds the answer
    wrong = [p for p in whos.POOL if p != target][:3]
    for cid in wrong:
        client.post("/whos-that-stand/guess", data={"name": whos.facts(cid)["name"]}, headers=h)
    s = whos.state("111")
    assert s["misses"] == 3 and not s["solved"]
    page = client.get("/whos-that-stand").data.decode()
    assert "▇" in page  # the special's clue, name blanked
    client.post("/whos-that-stand/guess", data={"name": "Not a stand at all"}, headers=h)
    assert whos.state("111")["misses"] == 3  # a typo costs nothing
    client.post("/whos-that-stand/guess", data={"name": tname}, headers=h)
    s = whos.state("111")
    assert s["solved"] and s["over"] and len(s["guesses"]) == 4
    assert doc(client, "111")["fragments"] >= whos.REWARD_BASE + whos.REWARD_PER_SPARE * (whos.MAX_GUESSES - 4)
    assert doc(client, "111")["xp"] >= whos.XP_BASE + whos.XP_PER_SPARE * (whos.MAX_GUESSES - 4)
    assert whos.streak("111") == {"n": 1, "best": 1} and whos.ladder()[0]["guesses"] == 4
    page = client.get("/whos-that-stand").data.decode()
    assert "Nice!" in page and tname in page and "Copy my result" in page and "🟩" in page


def test_the_picture_is_made_on_the_server_and_sharpens(client, monkeypatch):
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGBA", (200, 200), (200, 50, 120, 255)).save(buf, "PNG")
    calls = []

    class Res:
        content = buf.getvalue()
        def raise_for_status(self):
            pass
    import requests
    monkeypatch.setattr(requests, "get", lambda url, timeout: calls.append(url) or Res())
    player(client, "111")
    h = login(client, "111")
    assert client.get("/whos-that-stand/picture.png").status_code == 404 and not calls  # the first guess is blind
    assert "First guess is blind" in client.get("/whos-that-stand").data.decode()
    wrong = next(p for p in whos.POOL if p != whos.answer())
    client.post("/whos-that-stand/guess", data={"name": whos.facts(wrong)["name"]}, headers=h)
    r1 = client.get("/whos-that-stand/picture.png")
    assert r1.status_code == 200 and r1.mimetype == "image/png" and len(calls) == 1
    client.get("/whos-that-stand/picture.png")
    assert len(calls) == 1  # cached per day and step


def _gang(client, uid, name, elo):
    player(client, uid, fragments=50_000, main_characters=[char(1, xp=9000)])
    h = login(client, uid)
    client.post("/gangs/create", data={"name": name}, headers=h)
    gid = doc(client, uid)["gang_id"]
    g = pickle.loads(client.fake.hget("gangs", gid))
    g["war_elo"] = elo
    client.fake.hset("gangs", gid, pickle.dumps(g))
    return gid, h


def test_the_gang_cup_seeds_plays_settles_and_crowns(client, monkeypatch):
    today = datetime.datetime.now(datetime.timezone.utc).date()
    clock = {"d": today}
    monkeypatch.setattr(CUP, "_today", lambda: clock["d"])
    a, _ = _gang(client, "111", "Crusaders", 300)
    b, hb = _gang(client, "222", "Passione", 200)
    c, _ = _gang(client, "333", "Kira's Crew", 100)
    page = client.get("/gangs/cup").data.decode()  # public; opens this month's cup
    assert "Gang Cup" in page and "Semi-finals" in page and "Final" in page and "Bye" in page
    cup = CUP._load(today.strftime("%Y-%m"))
    assert cup["size"] == 4 and [s["id"] for s in cup["seeds"]] == [a, b, c]
    assert cup["rounds"][0][0]["winner"] == a  # seed 1 has a bye
    # Passione (2) vs Kira's Crew (3): a bout a day
    login(client, "222")
    page = client.get("/gangs/cup").data.decode()
    assert "Fight today&#39;s cup bout" in page or "Fight today's cup bout" in page
    client.post("/gangs/cup/attack", headers=hb)
    fight = dbmod.load_fight("222")
    assert fight.kind == "gang_cup" and fight.meta["round"] == 0
    for e in fight.sides[1].chars:
        e.current_hp = 0
    dbmod.save_fight("222", fight)
    client.post("/gangs/fight/attack", data={"log_len": len(fight.log)}, headers=hb)
    client.post("/gangs/fight/leave", headers=hb)
    assert CUP._damage(cup["id"], 0)[b] > 0
    client.post("/gangs/cup/attack", headers=hb)
    assert dbmod.load_fight("222") is None  # one bout a day
    # a week later: the semi settles, the final is set; two weeks later: the champion
    clock["d"] = today + datetime.timedelta(days=CUP.ROUND_DAYS)
    client.get("/gangs/cup")
    cup = CUP._load(cup["id"])
    assert cup["rounds"][0][1]["winner"] == b and cup["rounds"][1][0]["a"] == a and cup["rounds"][1][0]["b"] == b
    vault = pickle.loads(client.fake.hget("gangs", b)).get("vault", 0)
    clock["d"] = today + datetime.timedelta(days=2 * CUP.ROUND_DAYS)
    page = client.get("/gangs/cup").data.decode()
    cup = CUP._load(cup["id"])
    assert cup["done"] and cup["champion"] == a  # no bouts in the final: the better seed wins the tie
    assert pickle.loads(client.fake.hget("gangs", b)).get("vault", 0) == vault + CUP.PRIZES[1]
    assert "Champion" in page and CUP.champions()[0]["gang"] == a
    login(client, "111")
    client.get("/gangs/cup")
    assert any(t.startswith("Gang Cup Champion") for t in doc(client, "111").get("web_titles", []))
    from app.game import gangs as G
    G._ladder_cache.update(at=0, rows=None)
    assert "🏆" in client.get("/gangs/ladder").data.decode()
