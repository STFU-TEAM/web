"""The deep dungeon (B4-B9), Requiem · Over Heaven, the ranked queue bar and the Requiem Tower."""
import time

import app.db as dbmod
from app.game import dungeon, overheaven, progression, requiem, tower
from test_app import _win_dungeon_fight, char, client, doc, login, put  # noqa: F401  (client is a fixture)
from test_features import player


# ── The deep dungeon ─────────────────────────────────────────────────────

def test_nine_floors_in_three_bands_with_warnings_and_growing_xp():
    assert dungeon.DEPTHS == 9 and dungeon.BOSS_DEPTHS == (3, 6, 9)
    assert [dungeon.band(d) for d in (1, 3, 4, 6, 7, 9)] == ["delve", "delve", "heaven", "heaven", "requiem", "requiem"]
    assert dungeon.warning(3) is None and all(dungeon.warning(d) for d in range(4, 10))
    assert "Over Heaven" in dungeon.warning(4) and "Requiem" in dungeon.warning(7)
    xps = [dungeon.xp_for(d) for d in range(1, 10)]
    assert all(b[0] >= a[0] and b[1] > a[1] for a, b in zip(xps, xps[1:]))  # stand and player XP grow every floor
    # heaven's rule holds a floor of the Over Heaven depths; its boss keeps it and adds another; Requiem floors have none
    floor = dungeon.floor_rules("2026-10-12", 5)
    boss = dungeon.floor_rules("2026-10-12", 5, "boss")
    assert len(floor) == 1 and len(boss) == 2 and floor.items() <= boss.items()
    assert dungeon.floor_rules("2026-10-12", 2) == {} and dungeon.floor_rules("2026-10-12", 8) == {}
    run = {"day": "2026-10-12", "depth": 7, "power": 5}
    foes = dungeon.enemies(run, (2, 2), "fight")
    assert all(c.level == 100 and c.awaken == 5 for c in foes)


def _on_stairs(client, uid, depth, boss_beaten):
    d = doc(client, uid)
    run = d["web_delve"]["run"]
    plan = dungeon.floor_plan(run["day"], depth)
    run.update(depth=depth, pos=list(plan["stairs"]), seen=[dungeon.key(plan["stairs"])],
               done=[dungeon.key(plan["stairs"])] if boss_beaten else [])
    put(client, d)
    return plan


def test_a_boss_on_b3_lets_you_go_deeper_into_the_over_heaven_depths(client):
    player(client, "601", main_characters=[char(1, xp=10000)])
    h = login(client, "601")
    client.post("/adventure/dungeon/start", headers=h)
    _on_stairs(client, "601", 3, boss_beaten=False)
    client.post("/adventure/dungeon/descend", headers=h)  # the boss still guards the stairs
    assert doc(client, "601")["web_delve"]["run"]["depth"] == 3
    client.post("/adventure/dungeon/cashout", headers=h)  # and the way out
    assert doc(client, "601")["web_delve"]["run"] is not None

    client.post("/adventure/dungeon/fight", headers=h)
    assert dbmod.load_fight("601").meta["event"] == "boss"
    _win_dungeon_fight(client, h, "601")
    d = doc(client, "601")
    assert d["web_delve"]["run"]["depth"] == 3 and d["web_dungeon_clears"] == 1  # the run goes on
    page = client.get("/adventure/dungeon", headers=h).data.decode()
    assert "Over Heaven depths" in page and "Go deeper · B4" in page and "hx-confirm" in page

    client.post("/adventure/dungeon/descend", headers=h)
    assert doc(client, "601")["web_delve"]["run"]["depth"] == 4
    page = client.get("/adventure/dungeon", headers=h).data.decode()
    assert "B4 · Over Heaven depths" in page and "Heaven's rule" in page
    plan = _on_stairs(client, "601", 4, boss_beaten=True)
    d = doc(client, "601")
    fight_tile = next(t for t, k in sorted(plan["events"].items()) if k == "fight")
    d["web_delve"]["run"]["pos"] = list(fight_tile)
    put(client, d)
    client.post("/adventure/dungeon/fight", headers=h)
    fight = dbmod.load_fight("601")
    assert fight.rules == dungeon.floor_rules(d["web_delve"]["run"]["day"], 4) and fight.rules
    assert all(c.level == 100 for c in fight.sides[1].chars)


# ── Requiem · Over Heaven ────────────────────────────────────────────────

def test_requiem_over_heaven_opens_once_requiem_is_cleared(client):
    from app.game import story
    player(client, "602", main_characters=[char(1, xp=10000)], web_story={"cleared": story.TOTAL})
    h = login(client, "602")
    page = client.get("/over-heaven?t=requiem", headers=h)
    page = page if page.status_code == 200 else client.get("/overheaven?t=requiem", headers=h)
    assert "Sealed until Requiem falls" in page.data.decode()
    assert "requiem" in overheaven.BY_KEY and overheaven.REQUIEM_TRACK not in overheaven.TRACKS  # outside the title count
    d = doc(client, "602")
    d["web_requiem"] = {t["key"]: len(t["stages"]) for t in requiem.TRACKS}
    put(client, d)
    page = client.get(page.request.path + "?t=requiem", headers=h).data.decode()
    assert "Sealed until Requiem falls" not in page and "Encore of Calamity" in page
    foes = overheaven.enemy_team("requiem", 0)
    assert all(c.level == 100 and c.awaken == 5 for c in foes)


# ── The ranked queue bar ─────────────────────────────────────────────────

def test_the_queue_bar_counts_live_players_only(client):
    from app.routes.battles import RANKED_QUEUE
    player(client, "603", main_characters=[char(1)])
    h = login(client, "603")
    now = time.time()
    client.fake.zadd(RANKED_QUEUE, {"a": now, "b": now - 10, "stale": now - 600, "603": now})
    page = client.get("/team", headers=h).data.decode()
    assert page.count('class="queue-bar') == 2  # the sidebar's and the phone menu's
    bar = client.get("/battles/queue-bar?w=sheet", headers=h).data.decode()
    assert "<strong>3</strong> in queue" in bar and "You're in" in bar and "queue-bar sheet" in bar


# ── The Requiem Tower ────────────────────────────────────────────────────

def test_the_requiem_tower_is_its_own_harder_better_paid_climb(client, monkeypatch):
    monkeypatch.setattr(tower, "RQ_BASE", 0.01)  # level 100 ★5 still, but too weak to end the test's lone stand first
    player(client, "604", main_characters=[char(1, xp=10000)], fragments=5000)
    h = login(client, "604")
    page = client.get("/tower", headers=h).data.decode()
    assert "Climb the Requiem Tower" in page and "t=requiem" in page
    assert "Enter the Requiem Tower" in client.get("/tower?t=requiem", headers=h).data.decode()
    client.post("/tower/start", data={"mode": "requiem", "oh": "1"}, headers=h)
    d = doc(client, "604")
    assert d["fragments"] == 5000 - tower.RQ_COST and d["web_tower"]["run"] == {"floor": 1, "mode": "requiem", "oh": True}
    fight = dbmod.load_fight("604")
    assert fight.meta["mode"] == "requiem" and fight.rules == tower.heaven_rules(1, tower.RQ)
    assert all(c.level == 100 and c.awaken == 5 for c in fight.sides[1].chars)
    for c in fight.sides[1].chars:
        c.current_hp = 0
    dbmod.save_fight("604", fight)
    client.post("/tower/attack", headers=h)
    d = doc(client, "604")
    paid = tower.reward_for(1, tower.RQ, oh=True)["fragments"]
    assert d["web_tower"]["rq"] == {"best": 1, "paid": 1} and d["web_tower"]["paid"] == 0
    assert d["fragments"] >= 5000 - tower.RQ_COST + paid and paid > tower.reward_for(1)["fragments"] * 10  # plus any win bonus
    assert client.fake.zscore(tower.board_key(d["web_tower"]["week"], tower.RQ), "604") == 1
    assert d.get("tower_level", 0) == 0  # the all-time Tower record is the normal climb's


def test_requiem_tower_loot_beats_the_tower_and_the_toggle_pays_more():
    r10, n10 = tower.reward_for(10, tower.RQ), tower.reward_for(10)
    assert r10["fragments"] > n10["fragments"] and 3 in r10["items"] and r10["super"] == 1
    assert tower.reward_for(10, tower.RQ, oh=True)["fragments"] > r10["fragments"]
    assert tower.rq_mult(2) > tower.rq_mult(1)
