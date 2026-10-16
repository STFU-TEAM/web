"""The Feature Lab, built: the fight's finale (To Be Continued, the MVP's pose), terrain scenery, raid phases,
ranked predictions, D'Arby's den and the Stand Arrow Gauntlet."""
import app.db as dbmod
from app.game.user import create_user
from test_app import char, client, login, put  # noqa: F401  (client is a fixture)


def _player(c, uid="111", **fields):
    d = create_user(uid)
    d.update(fields)
    put(c, d)
    return login(c, uid)


def _finish_rush(client, h):
    """A rush fight whose enemies are one blow from defeat, played to the end through the real route."""
    from app.game.fight import valid_targets
    client.post("/rush/fight", headers=h)
    fight = dbmod.load_fight("111")
    for c in fight.sides[1].chars:
        c.current_hp = 1
    dbmod.save_fight("111", fight)
    page = ""
    for _ in range(40):
        fight = dbmod.load_fight("111")
        if fight.finished:
            break
        targets = valid_targets(fight.sides[1].chars)
        page = client.post("/rush/attack", data={"target": targets[0] if targets else 0, "log_len": len(fight.log)},
                           headers=h).data.decode()
    return page, dbmod.load_fight("111")


def test_a_won_fight_ends_on_to_be_continued_and_its_mvp_pose(client):
    h = _player(client, main_characters=[char(1, xp=9000), char(2, xp=9000), char(3, xp=9000)])
    page, fight = _finish_rush(client, h)
    assert fight.finished and fight.winner == 0
    mvp, dealt = fight.mvp(0)
    assert mvp is not None and dealt > 0 and dealt == max(fight.damage_dealt(0).values())
    assert 'class="tbc-freeze"' in page and "To Be Continued" in page
    assert 'data-pose' in page and f"｢{mvp.name}｣ strikes its pose" in page and "MVP" in page


def test_damage_is_credited_to_whoever_caused_it():
    from app.game.fight import Fight, Side
    from app.game.character import character_from_dict
    mine = [character_from_dict(char(i, xp=4000)) for i in (1, 2)]
    foes = [character_from_dict(char(3, xp=4000))]
    f = Fight(Side("A", mine, True), Side("B", foes, False), kind="story")
    f.log = [{"hp": [[100, 100], [500]], "src": None},
             {"hp": [[100, 100], [420]], "src": [0, 1]},
             {"hp": [[90, 100], [420]], "src": [1, 0]},
             {"hp": [[90, 100], [300]], "src": [0, 0]},
             {"hp": [[90, 100], [280]], "src": None}]  # a poison tick: nobody's
    assert f.damage_dealt(0) == {1: 80, 0: 120} and f.mvp(0) == (mine[0], 120)


def test_raid_damage_moves_the_villain_through_its_phases(client, monkeypatch):
    import pickle
    from app.game import gangs as G
    from test_features import player
    for v in G.WEEKLY_RAIDS:
        assert len(G.PHASES[v["name"]]) == 3  # every villain has phases 2-4
    monkeypatch.setattr(G, "weekly_boss", lambda when=None: next(v for v in G.WEEKLY_RAIDS if v["name"] == "DIO"))
    player(client, "111", fragments=50_000, main_characters=[char(1, xp=9000)])
    h = login(client, "111")
    client.post("/gangs/create", data={"name": "Crusaders"}, headers=h)
    from test_app import doc
    gid = doc(client, "111")["gang_id"]
    gang = pickle.loads(client.fake.hget("gangs", gid))
    assert G.raid_phase(gang) == 0 and "Phase 1 of 4" in client.get("/gangs").data.decode()
    G.raid_state(gang)["damage"] = 210_000
    client.fake.hset("gangs", gid, pickle.dumps(gang))
    page = client.get("/gangs").data.decode()
    assert "Phase 3 of 4 · Road Roller" in page and "Phase 4 in" in page
    client.post("/gangs/raid/attack", headers=h)
    fight = dbmod.load_fight("111")
    assert fight.kind == "gang_raid" and fight.rules == {"time_stop": 3, "pressure": 0.03} and fight.meta["raid_phase"] == 3
    assert any("Phase 3 · Road Roller" in e["text"] for e in fight.log)


def test_spectators_predict_a_ranked_duel_and_the_winners_split_the_pool(client):
    from test_app import doc
    from test_features import player
    from test_live_features import finish_duel
    player(client, "111", main_characters=[char(1, xp=2000)])
    player(client, "222", main_characters=[char(2, xp=2000)])
    for uid in ("333", "444"):
        player(client, uid, fragments=5000)
    with client.application.test_request_context():
        from app.routes.battles import _create_duel
        fight = _create_duel("111", "222", "ranked")
    url = f"/battles/watch/{fight.id}/predict"
    h = login(client, "333")
    assert "Make the call" in client.get(url, headers=h).data.decode()
    assert 'class="predict-panel"' in client.get(f"/battles/watch/{fight.id}", headers=h).data.decode()
    client.post(url, data={"side": 0, "stake": 500}, headers=h)
    assert "You backed" in client.get(url, headers=h).data.decode()
    assert "already made your call" in client.post(url, data={"side": 1, "stake": 50}, headers=h).data.decode()
    client.post(url, data={"side": 1, "stake": 100}, headers=login(client, "444"))
    assert "own duel" in client.post(url, data={"side": 0, "stake": 50}, headers=login(client, "111")).data.decode()
    assert doc(client, "333")["fragments"] == 4500 and doc(client, "444")["fragments"] == 4900
    fight = finish_duel(client)
    w = fight.winner
    expected = {None: (5000, 5000), 0: (5100, 4900), 1: (4500, 5500)}[w]
    assert (doc(client, "333")["fragments"], doc(client, "444")["fragments"]) == expected
    with client.application.test_request_context():
        from app import predictions
        assert predictions.settle(client.fake, fight) is None  # never paid twice


def test_prediction_payouts_refund_when_nobody_can_win():
    from app.predictions import payouts
    bets = {"a": {"side": 0, "stake": 100}, "b": {"side": 0, "stake": 300}, "c": {"side": 1, "stake": 200}}
    assert payouts(bets, 0) == {"a": 150, "b": 450}
    assert payouts(bets, None) == {"a": 100, "b": 300, "c": 200}  # a draw
    assert payouts({"a": {"side": 1, "stake": 50}}, 0) == {"a": 50}  # nobody backed the winner


def _rolls(monkeypatch, values):
    """Feed the den's dice: each value is one random() call (spill when below the glass's risk)."""
    from app.game import den
    it = iter(values)
    monkeypatch.setattr(den.random, "random", lambda: next(it, 0.99))


def test_the_coin_glass_against_darby_pays_double_and_keeps_its_limits(client, monkeypatch):
    from app.game import den
    from test_app import doc
    from test_features import player
    player(client, "111", fragments=10_000, xp=200_000)
    h = login(client, "111")
    assert "Play D'Arby" in client.get("/den", headers=h).data.decode()
    client.post("/den/start", data={"stake": 500}, headers=h)
    assert doc(client, "111")["fragments"] == 9_500
    game = den.active(client.fake, "111")
    _rolls(monkeypatch, [0.99, 0.5, 0.0])  # my coin stays; D'Arby picks one coin, and it spills
    page = client.post("/den/drop", data={"game": game["id"], "n": 1}, headers={**h, "HX-Request": "true"}).data.decode()
    assert "spilled it!" in page and doc(client, "111")["fragments"] == 10_500  # the stake back, doubled
    assert den.active(client.fake, "111") is None and den.today(client.fake, "111")["games"] == 1
    for _ in range(3):  # three losses in a row close the table
        client.post("/den/start", data={"stake": 100}, headers=h)
        game = den.active(client.fake, "111")
        _rolls(monkeypatch, [0.0])
        client.post("/den/drop", data={"game": game["id"], "n": 1}, headers=h)
    assert den.cooling(client.fake, "111") > 0 and "closes the table" in client.get("/den", headers=h).data.decode()
    assert den.today(client.fake, "111")["lost"] == 300
    client.post("/den/start", data={"stake": 100}, headers=h)
    assert den.active(client.fake, "111") is None  # turned away


def test_the_den_wants_seasoned_players_and_caps_the_day(client):
    from app.game import den
    from app.game.user import User
    from test_app import doc
    from test_features import player
    player(client, "111", fragments=10_000, xp=0)
    assert "level" in den.blocked(client.fake, User(doc(client, "111")))
    player(client, "222", fragments=10_000, xp=200_000)
    client.fake.hset(den._day("222"), mapping={"games": den.GAMES_PER_DAY, "lost": 0})
    assert "10 games" in den.blocked(client.fake, User(doc(client, "222")))
    client.fake.hset(den._day("222"), mapping={"games": 0, "lost": 4_900})
    assert "past today's" in den.blocked(client.fake, User(doc(client, "222")), 500)


def test_friends_play_the_coin_glass_for_the_pot(client, monkeypatch):
    import time
    from app.game import den
    from test_app import doc
    from test_features import player
    from test_live_features import befriend
    player(client, "111", fragments=5_000, xp=200_000)
    player(client, "222", fragments=5_000, xp=200_000)
    befriend(client, "111", "222")
    h1 = login(client, "111")
    client.post("/den/challenge", data={"friend": "222", "stake": 1000}, headers=h1)
    game = den.active(client.fake, "111")
    assert game["state"] == "waiting" and doc(client, "111")["fragments"] == 4_000
    h2 = login(client, "222")
    assert "challenges you" in client.get("/den", headers=h2).data.decode()
    client.post(f"/den/accept/{game['id']}", headers=h2)
    assert doc(client, "222")["fragments"] == 4_000 and den.get(client.fake, game["id"])["state"] == "playing"
    h1 = login(client, "111")
    _rolls(monkeypatch, [0.99])
    client.post("/den/drop", data={"game": game["id"], "n": 1}, headers=h1)
    assert den.get(client.fake, game["id"])["turn"] == 1  # 222's move now
    g = den.get(client.fake, game["id"])
    g["turn_at"] = time.time() - den.TURN_SECONDS - 1  # 222 lets the clock run out...
    client.fake.set(f"web:den:game:{g['id']}", __import__("json").dumps(g))
    _rolls(monkeypatch, [0.0])  # ...and the coin dropped for them spills it
    assert "spilled" in client.get(f"/den/table?game={g['id']}", headers=h1).data.decode()
    assert doc(client, "111")["fragments"] == 6_000 and doc(client, "222")["fragments"] == 4_000
    client.get(f"/den/table?game={g['id']}", headers=h1)
    assert doc(client, "111")["fragments"] == 6_000  # never paid twice


def _win_floor(client, h):
    """Start the floor's fight with its crew one blow from defeat and play it out."""
    from app.game.fight import valid_targets
    client.post("/gauntlet/fight", headers=h)
    fight = dbmod.load_fight("111")
    for c in fight.sides[1].chars:
        c.current_hp = 1
    dbmod.save_fight("111", fight)
    for _ in range(40):
        fight = dbmod.load_fight("111")
        if fight.finished:
            break
        t = valid_targets(fight.sides[1].chars)
        client.post("/gauntlet/attack", data={"target": t[0] if t else 0, "log_len": len(fight.log)}, headers=h)
    client.post("/gauntlet/leave", headers=h)
    return dbmod.load_fight("111") or fight


def test_a_gauntlet_run_drafts_climbs_and_hands_out_a_prototype(client):
    from app.game import gauntlet as GT
    from test_app import doc
    from test_features import player
    player(client, "111", energy=20)
    h = login(client, "111")
    assert "Open a new story (free today)" in client.get("/gauntlet", headers=h).data.decode()
    client.post("/gauntlet/start", headers=h)
    run = doc(client, "111")["web_gauntlet"]["run"]
    assert run["floor"] == 1 and run["phase"] == "pick" and len(run["offers"]) == 3
    for floor in (1, 2, 3):
        offers = doc(client, "111")["web_gauntlet"]["run"]["offers"]
        client.post("/gauntlet/pick", data={"stand": offers[0]}, headers=h)
        _win_floor(client, h)
        run = doc(client, "111")["web_gauntlet"]["run"]
        assert run["floor"] == floor + 1 and len(run["team"]) == floor
    assert run["phase"] == "item" and len(run["items"]) == 3  # floor 4: a prototype
    assert "PROTOTYPE" in client.get("/gauntlet", headers=h).data.decode()
    client.post("/gauntlet/item", data={"item": run["items"][0], "slot": 1}, headers=h)
    run = doc(client, "111")["web_gauntlet"]["run"]
    assert run["team"][1]["item"] == run["team"][1]["item"] and run["phase"] == "ready" and run["dust"] > 0
    assert GT.ladder(client.fake)[0]["floor"] == 3
    client.post("/gauntlet/abandon", headers=h)
    client.post("/gauntlet/start", headers=h)  # the free run is used: this one costs energy
    assert doc(client, "111")["energy"] == 20 - GT.EXTRA_RUN_ENERGY


def test_prototype_items_bend_the_rules():
    import random
    from app.game import gauntlet as GT
    from app.game.character import character_from_dict
    from app.game.fight import Fight, Side
    mk = lambda i: character_from_dict(char(i, xp=8000))  # noqa: E731
    shooter, target = mk(1), mk(2)
    GT.apply_item(shooter, "bullet")
    plain = mk(1)
    target.current_speed = 999  # it would dodge anything, but not the silver bullet
    hit = shooter.attack(target)
    assert not hit["dodged"] and hit["damage"] > 0 and "_g_bullet" not in shooter.__dict__
    blinded = mk(3)
    blinded._g_blinded = True
    assert blinded.attack(mk(4))["dodged"] and not getattr(blinded, "_g_blinded", False)
    arrow = mk(5)
    GT.apply_item(arrow, "arrow")
    assert arrow.turn_for_ability == 1 and arrow.start_hp < plain.start_hp
    # the spine: back up at half health once
    a, b = [mk(1)], [mk(2)]
    GT.apply_item(a[0], "spine")
    f = Fight(Side("A", a, True), Side("B", b, False), kind="gauntlet")
    a[0].current_hp = 0
    f._check_falls()
    assert a[0].current_hp == a[0].start_hp // 2 and f.meta["revived"]
    # the steel ball chains to the others
    random.seed(1)
    ball, foes = mk(1), [mk(2), mk(3), mk(4)]
    GT.apply_item(ball, "ball")
    f = Fight(Side("A", [ball], True), Side("B", foes, False), kind="gauntlet")
    before = [c.current_hp for c in foes]
    f._gauntlet_hit(ball, foes[0], {"dodged": False, "damage": 300, "critical": False}, 0, 0)
    assert foes[1].current_hp < before[1] and foes[2].current_hp < before[2] and before[1] - foes[1].current_hp > before[2] - foes[2].current_hp


def test_a_full_cast_can_take_rohans_boon_or_sign_his_pact(client):
    import random
    from app.game import gauntlet as GT
    from app.game.user import User
    from test_app import doc, put
    from test_features import player
    d = player(client, "111")
    h = login(client, "111")
    client.post("/gauntlet/start", headers=h)
    d = doc(client, "111")
    run = d["web_gauntlet"]["run"]
    run.update(team=[{"id": i, "hp": 60, "item": None} for i in (1, 2, 3)], phase="pick", offers=[4, 5, 6],
               deal={"boon": "rest", "pact": "darby"})
    put(client, d)
    page = client.get("/gauntlet", headers=h).data.decode()
    assert "A chapter break" in page and "Pact of D&#39;Arby" in page and "Sign the pact" in page
    client.post("/gauntlet/page", data={"which": "boon"}, headers=h)
    run = doc(client, "111")["web_gauntlet"]["run"]
    assert run["boons"] == ["rest"] and all(m["hp"] == 100 for m in run["team"]) and run["phase"] == "ready"
    # a pact: its rules reach the fight, and D'Arby's collects on a loss
    run = {**run, "pacts": ["valentine", "rock", "mask", "darby"], "dust": 900}
    assert GT.pact_rules(run) == {"pressure": 0.05, "enemy_first": True, "heal_cut": 1}
    mods = GT._mods(run)
    assert mods["damage"] == 1.6 and mods["armor"] == 2 and mods["speed"] == 0.7
    assert GT.roll_deal(run, random.Random(1))["pact"] not in run["pacts"]
    foes = GT.enemies(5, "T")
    before = foes[0].start_hp
    GT.prepare_fight(run, GT.team(run), foes)
    assert foes[0].start_hp == int(before * 0.7)


def test_the_new_prototypes_work_in_a_fight():
    from app.game import gauntlet as GT
    from app.game.character import character_from_dict
    from app.game.fight import Fight, Side
    mk = lambda i: character_from_dict(char(i, xp=8000))  # noqa: E731
    assert len(GT.ITEMS) == 16
    # the zipper holds on once, the bomb takes the enemy with it
    a, b = [mk(1), mk(2)], [mk(3), mk(4)]
    GT.apply_item(a[0], "zipper")
    GT.apply_item(a[1], "bomb")
    f = Fight(Side("A", a, True), Side("B", b, False), kind="gauntlet")
    a[0].current_hp = a[1].current_hp = 0
    hp_b = [c.current_hp for c in b]
    f._check_falls()
    assert a[0].current_hp == 1 and all(c.current_hp < h for c, h in zip(b, hp_b))
    # the hand erases more, the seal makes the target heavy, the lipstick heals the team on a crit
    hand, foe = mk(1), mk(2)
    GT.apply_item(hand, "hand")
    GT.apply_item(hand, "freeze")
    GT.apply_item(hand, "lips")
    f = Fight(Side("A", [hand, mk(3)], True), Side("B", [foe], False), kind="gauntlet")
    f.sides[0].chars[1].current_hp = 10
    hp = foe.current_hp
    f._gauntlet_hit(hand, foe, {"dodged": False, "damage": 100, "critical": True}, 0, 0)
    assert foe.current_hp < hp and any(e.type.name == "SLOW" for e in foe.effects) and f.sides[0].chars[1].current_hp > 10
