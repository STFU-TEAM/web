"""Daily puzzle: generated from the date, checked solvable with the simulator, revealed to start the clock, one
ladder per day for the fastest solve."""
import json

import pytest

import app.db as dbmod
from app.game import puzzle
from app.game.logic import GameError
from test_app import client, doc, login  # noqa: F401  (client is a fixture)
from test_features import player


@pytest.fixture(scope="module")
def spec():
    """One real generation (a couple of rerolls at most, to keep the suite quick)."""
    old = puzzle.TRIES
    puzzle.TRIES = 3
    try:
        return puzzle.generate("2026-10-10")
    finally:
        puzzle.TRIES = old


def test_a_generated_puzzle_is_checked_solvable_and_not_trivial(spec):
    assert len(spec["stands"]) == puzzle.STANDS and len(set(spec["stands"])) == puzzle.STANDS
    assert len(spec["items"]) == puzzle.ITEMS and 1 <= len(spec["rules"]) <= 2 and spec["checked"] >= 900  # every team, every layout, every reroll
    sol = spec["solution"]
    assert len(sol["picks"]) == puzzle.PICK and sol["rate"] > 0.4
    gear = {int(k): v for k, v in sol["gear"].items()}
    assert puzzle._rate(spec, sol["picks"], gear, 20) > 0.3  # the recorded answer really wins
    assert spec["good"] <= 10  # far from every team works
    import random  # the date decides the draw: everyone gets the same puzzle, whichever worker builds it
    assert puzzle._roll(random.Random("puzzle:2026-10-10:0")) == puzzle._roll(random.Random("puzzle:2026-10-10:0"))
    assert puzzle._roll(random.Random("puzzle:2026-10-10:0")) != puzzle._roll(random.Random("puzzle:2026-10-11:0"))


def test_parse_wants_three_stands_and_items_on_them():
    from werkzeug.datastructures import MultiDict
    assert puzzle.parse(MultiDict([("s", "0"), ("s", "2"), ("s", "5"), ("g0", "2"), ("g1", "")])) == ([0, 2, 5], {0: 2})
    with pytest.raises(GameError, match="exactly"):
        puzzle.parse(MultiDict([("s", "0"), ("s", "0"), ("s", "1")]))
    with pytest.raises(GameError, match="picked"):
        puzzle.parse(MultiDict([("s", "0"), ("s", "1"), ("s", "2"), ("g0", "4")]))


def test_reveal_fight_solve_and_the_ladder(client, spec):
    day = puzzle.today()
    client.fake.set(f"web:puzzle:{day}", json.dumps({**spec, "day": day}))
    player(client, "111", fragments=0)
    h = login(client, "111")
    page = client.get("/puzzle").data.decode()
    assert "Reveal" in page and "Played through" in page and 'name="s"' not in page  # hidden until revealed
    client.post("/puzzle/fight", data={"s": ["0", "1", "2"]}, headers=h)
    assert client.fake.get("web:fight:111") is None  # no fighting before the reveal
    client.post("/puzzle/reveal", headers=h)
    client.fake.hset(f"web:puzzle:start:{day}", "111", int(client.fake.hget(f"web:puzzle:start:{day}", "111")) - 125)
    page = client.get("/puzzle").data.decode()
    assert 'name="s"' in page and "data-since" in page and "Over Heaven rules" in page
    client.post("/puzzle/fight", data={"s": ["0", "1", "2"], "g0": "1"}, headers=h)
    fight = dbmod.load_fight("111")
    assert fight.kind == "puzzle" and len(fight.sides[0].chars) == 3 and fight.rules == spec["rules"]
    assert [c.id for c in fight.sides[0].chars] == spec["stands"][:3] and len(fight.sides[0].chars[1].items) == 1
    for c in fight.sides[1].chars:
        c.current_hp = 0
    dbmod.save_fight("111", fight)
    client.post("/puzzle/attack", data={"log_len": len(fight.log)}, headers=h)
    assert puzzle.solved("111") >= 125 and puzzle.rank("111") == 1
    assert doc(client, "111")["fragments"] >= puzzle.REWARD["fragments"]
    client.post("/puzzle/leave", headers=h)
    page = client.get("/puzzle").data.decode()
    assert "Solved in" in page and "#1" in page and "2m 0" in page
    # a second win keeps the first time and pays nothing more
    before = doc(client, "111")["fragments"]
    client.post("/puzzle/fight", data={"s": ["3", "4", "5"]}, headers=h)
    fight = dbmod.load_fight("111")
    for c in fight.sides[1].chars:
        c.current_hp = 0
    dbmod.save_fight("111", fight)
    client.post("/puzzle/attack", data={"log_len": len(fight.log)}, headers=h)
    assert doc(client, "111")["fragments"] == before and puzzle.tries("111") == 2


def test_requests_never_generate_and_the_page_waits_for_the_task(client, monkeypatch):
    monkeypatch.setattr(puzzle, "generate", lambda seed: pytest.fail("a request must never generate"))
    player(client, "111")
    login(client, "111")
    assert "on their way" in client.get("/puzzle").data.decode()
    assert "cleared the whole library" in client.get("/puzzle?tab=personal").data.decode()


def test_the_task_fills_the_daily_queue_first_then_the_library(client, monkeypatch, spec):
    made = []
    monkeypatch.setattr(puzzle, "generate", lambda seed: made.append(seed) or {**spec})
    monkeypatch.setattr(puzzle, "DAILY_BUFFER", 2)
    monkeypatch.setattr(puzzle, "LIBRARY_MAX", 3)
    assert [puzzle.generate_one() for _ in range(6)] == ["daily", "daily", "personal", "personal", "personal", None]
    assert made == ["lib:1", "lib:2", "lib:3", "lib:4", "lib:5"] and puzzle.stock() == {"daily": 2, "personal": 3, "total": 5}
    day = puzzle.get()  # the day takes the next daily puzzle, once
    assert day["id"] == 1 and day["day"] == puzzle.today() and puzzle.get()["id"] == 1 and puzzle.stock()["daily"] == 1
    assert puzzle.get(puzzle.yesterday())["id"] == 2  # another day, the next one
    assert {puzzle.from_library(i)["id"] for i in (3, 4, 5)} == {3, 4, 5}  # personal ones never become a daily


def test_personal_puzzles_walk_the_library(client, monkeypatch, spec):
    monkeypatch.setattr(puzzle, "generate", lambda seed: {**spec})
    monkeypatch.setattr(puzzle, "DAILY_BUFFER", 0)
    for _ in range(3):
        puzzle.generate_one()
    player(client, "111", fragments=0)
    h = login(client, "111")
    page = client.get("/puzzle?tab=personal").data.decode()
    assert "Your next puzzle" in page and "#1" in page and 'name="s"' not in page
    client.post("/puzzle/reveal", data={"mode": "personal"}, headers=h)
    page = client.get("/puzzle?tab=personal").data.decode()
    assert "data-pz-form" in page and "Skip" in page and 'name="mode" value="personal"' in page
    for n in range(puzzle.PERSONAL_PAID + 1):
        if n:
            client.post("/puzzle/reveal", data={"mode": "personal"}, headers=h)
        if puzzle.personal("111") is None:
            client.post("/puzzle/skip", headers=h)  # nothing left: a no-op
            break
        client.post("/puzzle/fight", data={"mode": "personal", "s": ["0", "1", "2"]}, headers=h)
        fight = dbmod.load_fight("111")
        assert fight.meta["mode"] == "personal"
        for c in fight.sides[1].chars:
            c.current_hp = 0
        dbmod.save_fight("111", fight)
        client.post("/puzzle/attack", data={"log_len": len(fight.log)}, headers=h)
        client.post("/puzzle/leave", headers=h)
    state = puzzle.me("111")
    assert state["solved"] == 3 and state["idx"] == 3 and puzzle.solvers()[0]["solved"] == 3
    assert state["paid"] == 3 and doc(client, "111")["fragments"] >= 3 * puzzle.PERSONAL_REWARD["fragments"]  # (+ quest dust)
    assert "cleared the whole library" in client.get("/puzzle?tab=personal").data.decode()
    # skipping moves on without a reward
    puzzle.generate_one()
    client.post("/puzzle/skip", headers=h)
    assert puzzle.me("111")["skipped"] == 1 and puzzle.personal("111") is None


def test_the_reward_cap_on_personal_solves(client, monkeypatch, spec):
    from app.game.user import User, create_user
    monkeypatch.setattr(puzzle, "generate", lambda seed: {**spec})
    monkeypatch.setattr(puzzle, "DAILY_BUFFER", 0)
    monkeypatch.setattr(puzzle, "PERSONAL_PAID", 1)
    for _ in range(2):
        puzzle.generate_one()
    u = User(create_user("9"))
    for _ in range(2):
        puzzle.personal_reveal("9")
        pid = puzzle.personal("9")["id"]
        puzzle.personal_win(u, pid)
    assert u.fragments == puzzle.PERSONAL_REWARD["fragments"] and puzzle.me("9")["solved"] == 2


def test_puzzle_answers_dont_leak_through_fight_history(client, spec):
    """Your own history shows your puzzle team and replay; nobody else's view does (profile, replay link)."""
    day = puzzle.today()
    client.fake.set(f"web:puzzle:{day}", json.dumps({**spec, "day": day}))
    player(client, "111")
    player(client, "222")
    h = login(client, "111")
    client.post("/puzzle/reveal", headers=h)
    client.post("/puzzle/fight", data={"s": ["0", "1", "2"]}, headers=h)
    fight = dbmod.load_fight("111")
    fid = fight.id
    for c in fight.sides[1].chars:
        c.current_hp = 0
    dbmod.save_fight("111", fight)
    client.post("/puzzle/attack", data={"log_len": len(fight.log)}, headers=h)
    from app.game import history
    mine = history.recent(client.fake, "111")[0]
    assert mine["kind"] == "puzzle" and mine["mine"] and mine["replay"]
    assert client.get(f"/battles/replay/{fid}").status_code == 200       # the player who fought it
    seen = history.recent(client.fake, "111", viewer="222")[0]
    assert seen["mine"] == [] and not seen["replay"] and seen["hidden"]
    login(client, "222")
    assert client.get(f"/battles/replay/{fid}").status_code == 403        # anyone else
    assert f"/battles/replay/{fid}" not in client.get("/u/111").data.decode()
    with client.session_transaction() as s:
        s.clear()
    assert client.get(f"/battles/replay/{fid}").status_code == 403        # or logged out


def test_the_admin_page_shows_the_worker_log(client, monkeypatch, spec):
    monkeypatch.setattr(puzzle, "generate", lambda seed: {**spec})
    puzzle.generate_one()
    puzzle.log("error", error="RuntimeError: boom")
    client.application.config["DISCORD_ADMIN_IDS"] = {"111"}
    player(client, "111")
    login(client, "111")
    page = client.get("/admin/puzzles").data.decode()
    assert "Puzzle worker log" in page and "🧩 Built" in page and "#1 → daily" in page and "boom" in page
    assert "silent" in page  # no heartbeat in tests: the thread isn't running
    assert [row["kind"] for row in puzzle.read_log()][:2] == ["error", "built"]
