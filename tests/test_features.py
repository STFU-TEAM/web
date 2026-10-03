"""Accounts, gangs, trades, story, items, collection tools, banners and engine fixes."""
import datetime
import pickle
import random

from app.game import logic
from app.game.character import CHARACTER_FILE, CRITMULTIPLIER, get_character_from_template
from app.game.effects import Effect, EffectType
from app.game.user import User, create_user
from test_app import char, client, doc, login, put  # noqa: F401  (client is a fixture)


def player(c, uid, **fields):
    d = create_user(uid)
    d.update(fields)
    put(c, d)
    return d


# --------------------------------------------------------------------------- #
# Engine fixes
# --------------------------------------------------------------------------- #
def test_crits_hit_harder_and_effects_revert_exactly():
    assert CRITMULTIPLIER == 1.5
    c = get_character_from_template(CHARACTER_FILE[0], ["ATTACK"], ["GOOD"])
    dmg, spd = c.current_damage, c.current_speed
    c.effects = [Effect(EffectType.WEAKEN, 1, 5), Effect(EffectType.SLOW, 1, 2), Effect(EffectType.DAMAGEUP, 1, 7)]
    c.end_turn()  # applied, then expired the same turn
    assert c.current_damage == dmg and c.current_speed == spd
    assert c.effects == []


def _stand(cid, **kw):
    return get_character_from_template(CHARACTER_FILE[cid - 1], kw.get("types", ["ATTACK"]), kw.get("quals", ["GOOD"]))


def test_healing_never_passes_max_health():
    from app.game.characterabilities import burning_down_the_house, foo_fighters
    healer, ally = _stand(92), _stand(1)
    ally.current_hp = ally.start_hp - 5
    foo_fighters(healer, [healer, ally], [_stand(10)])  # a 25% heal on someone missing 5 HP
    burning_down_the_house(_stand(91), [healer, ally], [_stand(10)])
    assert ally.current_hp == ally.start_hp and healer.current_hp == healer.start_hp
    assert ally.heal(1000) == 0


def test_stat_effects_apply_now_and_last_the_targets_turns():
    c = _stand(1)
    dmg = c.current_damage
    c._my_turn = False  # hit during the enemy's turn
    c.add_effect(Effect(EffectType.WEAKEN, 1, 10))
    assert c.current_damage == dmg - 10
    c.end_turn()  # its own turn passes with the weaken on, then it reverts
    assert c.current_damage == dmg and c.effects == []
    c._my_turn = True  # a self-buff cast on its own turn survives that turn's end
    c.add_effect(Effect(EffectType.DAMAGEUP, 1, 7))
    c.end_turn()
    assert c.current_damage == dmg + 7
    c.end_turn()
    assert c.current_damage == dmg


def test_a_stunned_stand_cannot_be_stunned_on_its_next_turn():
    c = _stand(1)
    c.add_effect(Effect(EffectType.STUN, 1, 0))
    assert c.is_stunned()
    c._skipped = True  # the fight loop marks the lost turn
    c.end_turn()
    c.add_effect(Effect(EffectType.STUN, 1, 0))
    assert not c.is_stunned()  # shrugged off
    c.end_turn()
    c.add_effect(Effect(EffectType.STUN, 1, 0))
    assert c.is_stunned()


def test_single_target_specials_follow_the_chosen_target():
    from app.game.characterabilities import emperor
    random.seed(0)
    shooter, a, b = _stand(14), _stand(1), _stand(10)
    shooter._focus = b
    emperor(shooter, [shooter], [a, b])
    assert a.current_hp == a.start_hp and b.current_hp < b.start_hp


def test_permanent_growth_is_capped():
    c = _stand(117)
    for _ in range(50):
        c.grow("damage", 0.2)
    assert c.current_damage <= c.start_damage * 2 + 1


def test_terrain_rules():
    from app.game.effects import Terrain
    random.seed(1)
    c = _stand(1)
    c._active_terrain = Terrain.OCEAN
    c.add_effect(Effect(EffectType.BURN, 1, 50))
    c.end_turn()
    assert c.current_hp == c.start_hp  # the ocean puts burns out
    fast, slow = _stand(1), _stand(10)
    fast.current_speed, slow.current_speed = 100, 0
    slow._active_terrain = Terrain.GRAVITY
    assert not any(slow.attack(fast)["dodged"] for _ in range(200))


def test_fights_end_within_the_round_cap():
    from app.game.fight import MAX_ROUNDS, SUDDEN_DEATH_ROUND, Fight, Side
    random.seed(2)
    # two healers that barely scratch each other would stall forever without sudden death
    fight = Fight(Side("A", [_stand(92), _stand(43)], False), Side("B", [_stand(59), _stand(91)], False))
    fight.advance()
    assert fight.finished and fight.round <= MAX_ROUNDS + 1
    if fight.round > SUDDEN_DEATH_ROUND:
        assert any(e["kind"] == "sudden" for e in fight.log)
    assert all(hp <= c.start_hp for e in fight.log for s, side in enumerate(fight.sides)
               for c, hp in zip(side.chars, e["hp"][s]))


def test_wormhole_never_spawns_the_dummy_or_the_world_over_heaven():
    from app.game.user import User
    for xp, tier in ((450_000, "UR"), (100_000_000, "LR")):  # levels 60 and 100
        data = create_user("1")
        data["xp"] = xp
        user = User(data)
        assert (50 <= user.level < 75) if tier == "UR" else user.level >= 75
        for _ in range(60):
            _name, chars, _multi = logic.wormhole_enemy(user)
            assert all(c.id not in (110, 164) for c in chars)


def test_dummy_win_counts_for_the_story(client):
    from app.routes.battles import _settle
    player(client, "111")
    fight = type("F", (), {"kind": "dummy", "winner": 0, "meta": {"players": ["111"]}})()
    with client.application.test_request_context():
        _settle(fight)
    assert doc(client, "111")["achievement_data"]["counters"]["fight_win"] == 1


# --------------------------------------------------------------------------- #
# Username + password accounts
# --------------------------------------------------------------------------- #
def test_register_login_throttle_and_link(client, monkeypatch):
    client.get("/auth/register")
    with client.session_transaction() as s:
        tok = s["csrf"]
    r = client.post("/auth/register", data={"csrf": tok, "username": "Jolyne", "password": "stonefree!", "confirm": "stonefree!"})
    assert r.headers["Location"].endswith("/auth/welcome")
    with client.session_transaction() as s:
        uid, tok = s["uid"], s.get("csrf", tok)
    assert uid.startswith("acc")
    client.get("/auth/welcome")
    with client.session_transaction() as s:
        tok = s["csrf"]
    client.post("/auth/welcome", data={"csrf": tok})
    assert doc(client, uid)["super_fragments"] == 1

    # duplicate username, wrong password, then the right one
    client.post("/auth/logout", data={"csrf": tok})
    client.get("/auth/login")
    with client.session_transaction() as s:
        tok = s["csrf"]
    assert client.post("/auth/register", data={"csrf": tok, "username": "jolyne", "password": "whatever1", "confirm": "whatever1"}).status_code == 400
    assert client.post("/auth/login", data={"csrf": tok, "username": "jolyne", "password": "nope-nope"}).status_code == 401
    assert client.post("/auth/login", data={"csrf": tok, "username": "JOLYNE", "password": "stonefree!"}).status_code == 302
    with client.session_transaction() as s:
        assert s["uid"] == uid

    # players can find each other by username
    from app.accounts import resolve_player, link_discord, AccountError
    with client.application.test_request_context():
        assert resolve_player("jolyne") == uid
        link_discord(uid, "999")
        assert resolve_player("jolyne") == "999"
        assert client.fake.hget("users", uid) is None and doc(client, "999")["_id"] == "999"
        player(client, "998")
        try:
            link_discord("acc-none", "998")
            assert False
        except AccountError:
            pass

    # throttling after repeated failures
    with client.session_transaction() as s:
        s.clear()
        s["csrf"] = tok
    for _ in range(8):
        client.post("/auth/login", data={"csrf": tok, "username": "jolyne", "password": "bad-guess"})
    r = client.post("/auth/login", data={"csrf": tok, "username": "jolyne", "password": "stonefree!"})
    assert r.status_code == 401 and b"Too many attempts" in r.data


# --------------------------------------------------------------------------- #
# Gangs
# --------------------------------------------------------------------------- #
def test_gang_ranks_vault_guardians_and_raid(client):
    player(client, "111", fragments=50_000, storage_characters=[char(1), char(2)])
    player(client, "222", fragments=1_000, main_characters=[char(3, xp=10000)])
    h = login(client, "111")
    client.post("/gangs/create", data={"name": "Crusaders"}, headers=h)
    gid = doc(client, "111")["gang_id"]
    assert gid and doc(client, "111")["fragments"] == 40_000

    client.post("/gangs/invite", data={"user_id": "222"}, headers=h)
    h2 = login(client, "222")
    client.post(f"/gangs/join/{gid}", headers=h2)
    gang = pickle.loads(client.fake.hget("gangs", gid))
    assert "222" in gang["users"] and gang["ranks"]["222"] == 2

    # soldiers can't promote; the boss can, and promoting a capo hands over the boss seat
    client.post("/gangs/promote", data={"member": "111"}, headers=h2)
    assert pickle.loads(client.fake.hget("gangs", gid))["ranks"]["111"] == 0
    h = login(client, "111")
    client.post("/gangs/promote", data={"member": "222"}, headers=h)
    assert pickle.loads(client.fake.hget("gangs", gid))["ranks"]["222"] == 1
    client.post("/gangs/demote", data={"member": "222"}, headers=h)
    assert pickle.loads(client.fake.hget("gangs", gid))["ranks"]["222"] == 2

    # vault and payments
    client.post("/gangs/vault/deposit", data={"amount": "20000"}, headers=h)
    client.post("/gangs/vault/pay", data={"member": "222", "amount": "500"}, headers=h)
    assert pickle.loads(client.fake.hget("gangs", gid))["vault"] == 19_500
    assert doc(client, "222")["fragments"] == 1_500

    # guardians leave storage and come back
    uuid = doc(client, "111")["storage_characters"][0]["uuid"]
    client.post("/gangs/guardians/add", data={"uuid": uuid}, headers=h)
    assert len(pickle.loads(client.fake.hget("gangs", gid))["characters"]) == 1
    assert len(doc(client, "111")["storage_characters"]) == 1
    client.post("/gangs/guardians/remove", data={"index": "0"}, headers=h)
    assert len(doc(client, "111")["storage_characters"]) == 2

    # weekly raid: one attack a day, damage recorded on the gang, tiers claimed by attackers
    from app.game import gangs as G
    h2 = login(client, "222")
    assert G.weekly_boss()["name"] in client.get("/gangs").data.decode()
    assert client.post("/gangs/raid/attack", headers=h2).headers["Location"].endswith("/gangs/fight")
    assert client.get("/gangs/fight").status_code == 200
    for _ in range(60):
        r = client.post("/gangs/fight/attack", data={"forfeit": "1"}, headers=h2)
        if b"damage dealt" in r.data:
            break
    gang = pickle.loads(client.fake.hget("gangs", gid))
    assert gang["web_raid"]["week"] == G.week_key() and "222" in gang["web_raid"]["hits"]
    assert doc(client, "222")["fragments"] > 1_500  # consolation payout
    client.post("/gangs/fight/leave", headers=h2)
    client.post("/gangs/raid/attack", headers=h2)  # second attack the same day refused
    assert client.fake.get("web:fight:222") is None
    gang["web_raid"]["damage"] = G.RAID_TIERS[0]["damage"]  # the gang reaches tier 1
    client.fake.hset("gangs", gid, pickle.dumps(gang))
    before = doc(client, "222")["fragments"]
    client.post("/gangs/raid/claim", headers=h2)
    assert doc(client, "222")["fragments"] == before + G.RAID_TIERS[0]["fragments"]
    client.post("/gangs/raid/claim", headers=h2)  # paid once
    assert doc(client, "222")["fragments"] == before + G.RAID_TIERS[0]["fragments"]
    h = login(client, "111")  # never attacked: nothing to claim
    f111 = doc(client, "111")["fragments"]
    client.post("/gangs/raid/claim", headers=h)
    assert doc(client, "111")["fragments"] == f111
    h2 = login(client, "222")

    # kick needs a higher rank; the gang page renders for both
    client.post("/gangs/kick", data={"member": "111"}, headers=h2)
    assert "111" in pickle.loads(client.fake.hget("gangs", gid))["users"]
    assert client.get("/gangs").status_code == 200
    h = login(client, "111")
    client.post("/gangs/kick", data={"member": "222"}, headers=h)
    assert "222" not in pickle.loads(client.fake.hget("gangs", gid))["users"]
    assert doc(client, "222")["gang_id"] is None


def test_war_queue_publishes_to_the_bot_matchmaker(client):
    player(client, "111", fragments=20_000, storage_characters=[char(1)])
    h = login(client, "111")
    client.post("/gangs/create", data={"name": "Passione"}, headers=h)
    gid = doc(client, "111")["gang_id"]
    client.post("/gangs/war/start", headers=h)  # no guardian: refused
    assert client.fake.get(f"web:gang:queued:{gid}") is None
    client.post("/gangs/guardians/add", data={"uuid": doc(client, "111")["storage_characters"][0]["uuid"]}, headers=h)
    pubsub = client.fake.pubsub()
    pubsub.subscribe("war_matchmaking_requests")
    pubsub.get_message()
    client.post("/gangs/war/start", headers=h)
    msg = pubsub.get_message()
    assert msg and pickle.loads(msg["data"]) == gid
    # once the bot matches it, members can attack the opponent's guardians
    other = {"_id": "rival", "name": "Rivals", "users": ["x"], "ranks": {"x": 0}, "characters": [char(2)],
             "damage_to_current_war": 0, "war_attacks": []}
    client.fake.hset("gangs", "rival", pickle.dumps(other))
    client.fake.hset("active_wars", gid, pickle.dumps("rival"))
    player(client, "111", fragments=0, main_characters=[char(5, xp=10000)], gang_id=gid)
    assert client.post("/gangs/war/attack", headers=h).headers["Location"].endswith("/gangs/fight")


# --------------------------------------------------------------------------- #
# Trades, selling, locks
# --------------------------------------------------------------------------- #
def test_trade_offer_accept_and_lock(client):
    a = player(client, "111", fragments=1_000, storage_characters=[char(1), char(2)], items=[{"id": 1}])
    b = player(client, "222", fragments=0, storage_characters=[char(3)])
    give_uuid, want_uuid = a["storage_characters"][0]["uuid"], b["storage_characters"][0]["uuid"]
    h = login(client, "111")
    client.post("/trades/new", data={"with": "222", "give_stand": give_uuid, "give_item": "1:1",
                                     "give_fragments": "300", "want_stand": want_uuid}, headers=h)
    offer_id = next(iter(client.fake.smembers("web:trades:in:222"))).decode()
    assert client.get("/trades").status_code == 200

    h2 = login(client, "222")
    client.post(f"/trades/{offer_id}/accept", headers=h2)
    a2, b2 = doc(client, "111"), doc(client, "222")
    assert want_uuid in [c["uuid"] for c in a2["storage_characters"]]
    assert give_uuid in [c["uuid"] for c in b2["storage_characters"]]
    assert a2["fragments"] == 700 and b2["fragments"] == 300 and b2["items"] == [{"id": 1}]
    assert not client.fake.exists(f"web:trade:{offer_id}")

    # locked stands can't be released or offered
    h = login(client, "111")
    locked_uuid = a2["storage_characters"][0]["uuid"]
    client.post("/team/lock", data={"uuid": locked_uuid}, headers=h)
    assert locked_uuid in doc(client, "111")["web_locked"]
    client.post("/team/release", data={"uuid": locked_uuid}, headers=h)
    assert locked_uuid in [c["uuid"] for c in doc(client, "111")["storage_characters"]]
    client.post("/trades/new", data={"with": "222", "give_stand": locked_uuid}, headers=h)
    assert not client.fake.smembers("web:trades:out:111")
    assert client.get(f"/team/stand/{locked_uuid}").status_code == 200
    assert client.get("/team").status_code == 200


def test_sell_items(client):
    player(client, "111", fragments=0, items=[{"id": 1}, {"id": 1}, {"id": 8}])
    h = login(client, "111")
    client.post("/items/sell", data={"item": "1", "all": "1"}, headers=h)
    assert doc(client, "111")["fragments"] == 2 * (2500 // 10)
    r = client.post("/items/sell", data={"item": "8"}, headers=h)  # free chip: refused
    assert b"be sold" in r.data and doc(client, "111")["items"] == [{"id": 8}]
    assert client.get("/items").status_code == 200


# --------------------------------------------------------------------------- #
# Story, achievements
# --------------------------------------------------------------------------- #
def _win_story_fight(client, h):
    """Start the next story fight and knock out the enemy team."""
    import app.db as dbmod
    client.post("/story/fight", headers=h)
    fight = dbmod.load_fight("111")
    assert fight.kind == "story"
    for c in fight.sides[1].chars:
        c.current_hp = 0
    dbmod.save_fight("111", fight)
    client.post("/story/attack", data={"log_len": len(fight.log)}, headers=h)
    client.post("/story/leave", headers=h)


def test_story_journey_gates_pays_once_and_rewards_bosses(client):
    from app.game import story
    player(client, "111", fragments=0, super_fragments=0)
    h = login(client, "111")
    page = client.get("/story").data.decode()
    assert "Arrow&#39;s Test" in page and "You need stands to fight" in page
    client.post("/story/fight", headers=h)  # no team: refused
    assert client.fake.get("web:fight:111") is None

    d = doc(client, "111")
    d["main_characters"] = [char(1)]
    put(client, d)
    _win_story_fight(client, h)
    d = doc(client, "111")
    assert d["web_story"]["cleared"] == 1 and d["fragments"] == story.reward_for(0)["fragments"]
    assert "Ambush at Sea" in client.get("/story").data.decode()

    # a loss doesn't move the journey
    client.post("/story/fight", headers=h)
    client.post("/story/attack", data={"forfeit": "1"}, headers=h)
    client.post("/story/leave", headers=h)
    assert doc(client, "111")["web_story"]["cleared"] == 1

    for _ in range(5):  # through Part 3's boss
        _win_story_fight(client, h)
    d = doc(client, "111")
    boss = next(i for i, st in enumerate(story.STAGES) if st.get("boss"))
    assert d["web_story"]["cleared"] == boss + 1 and d["super_fragments"] == 1
    assert sum(1 for it in d["items"] if it["id"] == 2) == sum(1 for k in range(boss + 1) if k % 3 == 2)
    assert client.get("/achievements").status_code == 200


def test_story_gets_exponentially_harder():
    from app.game import story
    from app.filters import power_score
    power = [sum(power_score(c) for c in story.enemy_team(k)) / len(story.STAGES[k]["enemies"]) for k in range(story.TOTAL)]
    assert all(story.level_for(k) <= story.level_for(k + 1) for k in range(story.TOTAL - 1))
    assert power[-1] > 5 * power[0]
    # roughly geometric: every part's average stand is stronger than the previous part's
    by_part = {}
    for k, st in enumerate(story.STAGES):
        by_part.setdefault(st["part"], []).append(power[k])
    means = [sum(v) / len(v) for part, v in sorted(by_part.items()) if part]  # the prologue is a tutorial
    assert all(b >= 0.9 * a for a, b in zip(means, means[1:])) and means[-1] > 2 * means[0]


def test_new_save_gets_the_tour_once(client):
    from app.game.logic import BANNER_ODDS, PITY_LIMIT
    assert abs(sum(BANNER_ODDS.values()) - 1) < 1e-9 and BANNER_ODDS["SSR"] >= 0.1 and PITY_LIMIT <= 50
    h = login(client, "999")
    client.post("/auth/welcome", headers=h)
    assert client.fake.exists("web:tour:999")
    page = client.get("/team").data.decode()
    assert 'data-autostart="1"' in page and "Start the story" in page and "nav-dot" in page
    client.post("/tour/done", headers=h)
    assert not client.fake.exists("web:tour:999")
    assert 'data-autostart="0"' in client.get("/team").data.decode()


# --------------------------------------------------------------------------- #
# Banners
# --------------------------------------------------------------------------- #
def test_pity_floor_and_new_tags(client):
    banner = logic.BANNERS[0]
    user = User(create_user("111"))
    random.seed(1)
    user.pity = logic.PITY_LIMIT - 1
    drawn = logic._banner_draw(banner, user)
    assert drawn.rarity in ("SSR", "UR") and user.pity == 0
    # ten pulls always include an SR or better
    for seed in range(40):
        random.seed(seed)
        u = User(create_user("111"))
        u.super_fragments = 1
        res = logic.banner_pull(u, banner["id"])
        assert any(c.rarity != "R" for c, _ in res["drawn"])
        assert any(e["new"] for e in res["cards"])
        assert u.data["web_pull_history"][0]["banner"] == banner["name"]


# --------------------------------------------------------------------------- #
# Collection management
# --------------------------------------------------------------------------- #
def test_auto_fuse_merges_r_and_sr_duplicates_only(client):
    team_hermit = char(4)  # Hermit Purple (R) in the team absorbs its storage copies
    locked_copy = char(15)  # Wheel of Fortune (R), locked: never consumed
    storage = [char(4), char(4), char(15, xp=900), locked_copy, char(15),
               char(1), char(1),  # Star Platinum is SSR: left alone
               char(2)]  # a single SR: nothing to fuse
    player(client, "111", main_characters=[team_hermit], storage_characters=storage,
           web_locked=[locked_copy["uuid"]])
    h = login(client, "111")
    assert b"Auto-fuse R &amp; SR" in client.get("/team").data
    r = client.post("/team/autofuse", headers=h)
    assert b"Auto-fuse: 4 duplicates fused into 2 stands." in r.data
    d = doc(client, "111")
    assert d["main_characters"][0]["uuid"] == team_hermit["uuid"] and d["main_characters"][0]["awaken"] == 2
    wof = [c for c in d["storage_characters"] if c["id"] == 15]
    assert [c["uuid"] for c in wof] == [locked_copy["uuid"]] and wof[0]["awaken"] == 2
    assert sorted(c["id"] for c in d["storage_characters"]) == [1, 1, 2, 15]
    assert b"No R or SR duplicates" in client.post("/team/autofuse", headers=h).data


def test_bulk_lock_and_release_skip_locked(client):
    stands = [char(4), char(15), char(2)]
    player(client, "111", storage_characters=stands)
    h = login(client, "111")
    uuids = [s["uuid"] for s in stands]
    assert b"2 stands locked." in client.post("/team/lock-many", data={"uuid": uuids[:2], "lock": "1"}, headers=h).data
    r = client.post("/team/release", data={"uuid": uuids}, headers=h)
    assert b"2 locked or team stands kept." in r.data
    assert [c["uuid"] for c in doc(client, "111")["storage_characters"]] == uuids[:2]
    assert b"1 stand unlocked." in client.post("/team/lock-many", data={"uuid": uuids[:1], "lock": "0"}, headers=h).data
    assert doc(client, "111")["web_locked"] == [uuids[1]]


def test_pull_result_offers_the_same_banner_again(client):
    player(client, "111", super_fragments=3, items=[{"id": 2}])
    h = login(client, "111")
    r = client.post("/banners/0/pull", headers=h)
    assert b"Pull 10 again" in r.data and b"2 super fragments left" in r.data
    assert b'/banners/0/pull' in r.data and b'/banners/0/arrow' in r.data


def test_story_difficulty_curve_keeps_its_shape():
    """Fixed-seed simulation: each team archetype clears its part of the journey and walls later."""
    import importlib.util
    import pathlib
    import random as rnd
    from app.game import story
    path = pathlib.Path(__file__).resolve().parents[1] / "scripts" / "balance.py"
    spec = importlib.util.spec_from_file_location("balance", path)
    balance = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(balance)
    rnd.seed(7)
    curve = balance.story_curve(fights=10)
    first = {}  # part -> first stage index
    for k, st in enumerate(story.STAGES):
        first.setdefault(st["part"], k)
    starter, best = 0, 4
    rate = lambda who, lo, hi: sum(curve[k][who] for k in range(lo, hi)) / (hi - lo)
    assert rate(starter, 0, 5) >= 0.8                       # a fresh 10-pull clears the opening
    for k, rates in curve.items():                           # a stronger team never does much worse
        assert all(b >= a - 0.25 for a, b in zip(rates, rates[1:])), (k, rates)
    for who in range(5):                                     # the end is harder than Part 3
        assert rate(who, first[8], story.TOTAL) <= rate(who, first[3], first[4])
    assert rate(starter, first[5], story.TOTAL) == 0         # new teams can't skip ahead
    assert rate(best, first[8], story.TOTAL) >= 0.3          # a maxed team can get through Part 8


def test_smart_ai_finishes_kills_and_respects_taunt():
    from app.game.fight import ai_choice
    hitter = _stand(10)
    weak, strong = _stand(1), _stand(2)
    weak.current_hp = 5
    assert ai_choice([strong, weak], hitter) == 1          # takes the kill
    tank = _stand(5)                                       # The Fool taunts
    assert ai_choice([strong, weak, tank], hitter) == 2    # taunt still forces the target
    random.seed(3)
    assert {ai_choice([strong, weak], hitter, "easy") for _ in range(30)} == {0, 1}


def test_story_replay_costs_energy_and_pays_a_share(client):
    import app.db as dbmod
    from app.game import story
    player(client, "111", main_characters=[char(1, xp=5000)], energy=1)
    h = login(client, "111")
    _win_story_fight(client, h)
    first = doc(client, "111")["fragments"]
    client.post("/story/fight", data={"stage": 0}, headers=h)       # replay stage 1
    fight = dbmod.load_fight("111")
    assert fight.meta["stage"] == 0 and doc(client, "111")["energy"] == 0
    for c in fight.sides[1].chars:
        c.current_hp = 0
    dbmod.save_fight("111", fight)
    client.post("/story/attack", headers=h)
    client.post("/story/leave", headers=h)
    d = doc(client, "111")
    assert d["fragments"] == first + int(round(story.reward_for(0)["fragments"] * story.REPLAY_SHARE, -1))
    assert d["web_story"]["cleared"] == 1                           # a replay doesn't advance
    client.post("/story/fight", data={"stage": 0}, headers=h)       # out of energy
    assert dbmod.load_fight("111") is None and doc(client, "111")["energy"] == 0


def test_daily_streak_counts_once_a_day_and_pays_a_super_fragment_on_day_7(monkeypatch):
    from app.game.user import User
    clock = [datetime.datetime(2026, 3, 1, 9)]
    monkeypatch.setattr(logic, "now", lambda: clock[0])
    data = create_user("1")
    user = User(data)
    supers = user.super_fragments
    for day in range(7):
        clock[0] = datetime.datetime(2026, 3, 1 + day, 9)
        user.last_adventure = datetime.datetime.min
        res = logic.daily(user)
        assert res["streak"]["count"] == day + 1
        user.last_adventure = datetime.datetime.min           # a second claim the same day
        assert logic.daily(user)["streak"] is None
    assert user.super_fragments >= supers + 1
    clock[0] = datetime.datetime(2026, 3, 10, 9)              # skipped a day: back to 1
    user.last_adventure = datetime.datetime.min
    assert logic.daily(user)["streak"]["count"] == 1


def test_sparks_buy_an_ssr_from_the_banner(client):
    player(client, "111", super_fragments=2, web_sparks=19)
    h = login(client, "111")
    client.post("/banners/0/pull", headers=h)
    assert doc(client, "111")["web_sparks"] == 20
    page = client.get("/banners").data.decode()
    assert "Spark exchange" in page
    client.post("/banners/0/spark", data={"stand": 10}, headers=h)   # The World is UR: refused
    assert doc(client, "111")["web_sparks"] == 20
    client.post("/banners/0/spark", data={"stand": 1}, headers=h)    # Star Platinum (SSR)
    d = doc(client, "111")
    assert d["web_sparks"] == 0 and any(c["id"] == 1 for c in d["storage_characters"] + d["main_characters"])


def test_suggested_team_picks_the_strongest_trio(client):
    weak = char(4)
    strong = [char(10, xp=9000), char(31, xp=9000), char(1, xp=9000)]
    player(client, "111", main_characters=[weak], storage_characters=strong)
    h = login(client, "111")
    assert b"Use this team" in client.get("/team").data
    from app.game import logic as lg
    from app.game.user import User
    best = lg.best_team(User(doc(client, "111")))
    uuids = [c.uuid for c in best["team"]]
    assert set(uuids) == {s["uuid"] for s in strong}
    client.post("/team/suggested", data={"uuid": uuids}, headers=h)
    d = doc(client, "111")
    assert {c["uuid"] for c in d["main_characters"]} == set(uuids)
    assert [c["uuid"] for c in d["storage_characters"]] == [weak["uuid"]]
    assert b"Use this team" not in client.get("/team").data


# --------------------------------------------------------------------------- #
# News, ko-fi, dungeon
# --------------------------------------------------------------------------- #
def test_admin_posts_news_with_a_cover(client):
    import io
    admin = sorted(client.application.config["DISCORD_ADMIN_IDS"])[0]
    player(client, admin)
    h = login(client, admin)
    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
    r = client.post("/admin/news", headers=h, content_type="multipart/form-data", data={
        "title": "Weekly raid is live", "body": "First paragraph with **bold**.\n\nSee [the wiki](https://example.com/w).",
        "cover_file": (io.BytesIO(png), "cover.png")})
    assert r.status_code == 302
    post_id = r.headers["Location"].rsplit("/", 1)[1]
    page = client.get(f"/news/{post_id}").data.decode()
    assert "<strong>bold</strong>" in page and 'href="https://example.com/w"' in page and f"/news/cover/{post_id}" in page
    cover = client.get(f"/news/cover/{post_id}")
    assert cover.data == png and cover.mimetype == "image/png"
    assert "Weekly raid is live" in client.get("/").data.decode() and "Weekly raid is live" in client.get("/news").data.decode()
    # not an image: refused
    r = client.post("/admin/news", headers=h, content_type="multipart/form-data", data={
        "title": "Bad", "body": "x", "cover_file": (io.BytesIO(b"<script>"), "x.png")})
    assert r.status_code == 400
    # html is escaped
    client.post("/admin/news", headers=h, data={"id": post_id, "title": "Edited", "body": "<script>alert(1)</script>"})
    assert "<script>alert" not in client.get(f"/news/{post_id}").data.decode()
    client.post(f"/admin/news/{post_id}/delete", headers=h)
    assert client.get(f"/news/{post_id}").status_code == 404 and not client.fake.exists(f"web:news:cover:{post_id}")
    # players can't post
    player(client, "222")
    h2 = login(client, "222")
    assert client.post("/admin/news", headers=h2, data={"title": "Hack", "body": "x"}).status_code == 403


def test_kofi_link_everywhere(client):
    assert b"https://ko-fi.com/eirblast" in client.get("/").data


# --------------------------------------------------------------------------- #
# Boss rush, crafting
# --------------------------------------------------------------------------- #
def _end_rush_fight(client, h, win):
    import app.db as dbmod
    fight = dbmod.load_fight("111")
    assert fight.kind == "rush"
    if win:
        for c in fight.sides[1].chars:
            c.current_hp = 0
        fight.sides[0].chars[0].current_hp = fight.sides[0].chars[0].start_hp // 2  # took a beating
        dbmod.save_fight("111", fight)
        client.post("/rush/attack", headers=h)
    else:
        client.post("/rush/attack", data={"forfeit": "1"}, headers=h)
    client.post("/rush/leave", headers=h)


def test_boss_rush_carries_health_pays_weekly_and_ranks(client):
    from app.game import rush
    team = [char(1, xp=9000), char(2, xp=9000), char(3, xp=9000)]
    player(client, "111", fragments=0, main_characters=team)
    h = login(client, "111")
    assert b"Start the run" in client.get("/rush").data
    client.post("/rush/fight", headers=h)
    _end_rush_fight(client, h, win=True)
    d = doc(client, "111")
    run = d["web_rush"]["run"]
    assert run["index"] == 1 and d["fragments"] == rush.REWARDS[0]["fragments"]
    from app.game.user import User
    lead = User(d).main_characters[0]
    assert run["hp"][lead.uuid] < lead.start_hp  # the beating carries over (half health + the patch-up)
    page = client.get("/rush").data.decode()
    assert "Fight boss 2" in page and "rounds" in page
    client.post("/rush/fight", headers=h)
    _end_rush_fight(client, h, win=False)  # boss 2 wins: the run is over
    d = doc(client, "111")
    assert d["web_rush"]["run"] is None and d["web_rush"]["best"]["bosses"] == 1
    assert client.fake.zscore(f"web:rush:{d['web_rush']['week']}", "111") is not None
    client.post("/rush/fight", headers=h)  # one run a day
    assert client.fake.get("web:fight:111") is None
    page = client.get("/rush").data.decode()
    assert "Come back tomorrow" in page and "1/6" in page


def test_new_recipes_and_gear_specials(client):
    from app.game.itemabilities import item_specials
    from app.game.effects import Effect, EffectType
    player(client, "111", items=[{"id": 38}, {"id": 38}, {"id": 1}, {"id": 40}, {"id": 40}, {"id": 40}])
    h = login(client, "111")
    assert b"Steel Ball" in client.get("/items").data
    client.post("/items/craft", data={"recipe": "Steel Ball"}, headers=h)
    client.post("/items/craft", data={"recipe": "Stand Arrow"}, headers=h)
    assert sorted(i["id"] for i in doc(client, "111")["items"]) == [2, 41]
    holder, foe = _stand(1), _stand(10)
    holder._focus = foe
    msg = item_specials["41"](holder, [holder], [foe])
    assert "Steel Ball" in msg and foe.current_hp < foe.start_hp
    holder.current_hp = holder.start_hp // 2
    assert "heals" in item_specials["43"](holder, [holder], [foe])
    assert "Ultimate Being" in item_specials["45"](holder, [holder], [foe])


# --------------------------------------------------------------------------- #
# Tower, PvP draws, raid carry-over, save migration
# --------------------------------------------------------------------------- #
def test_tower_carries_health_heals_a_little_and_is_the_same_for_everyone():
    from app.game import tower
    from app.game.user import User
    import fakeredis
    redis = fakeredis.FakeRedis()
    user = User(create_user("1"))
    user.fragments = 1000
    team = [_stand(1), _stand(2)]
    user.main_characters = list(team)
    tower.start_climb(user, redis, team)
    assert user.fragments == 1000 - tower.CLIMB_COST
    fighters = tower.load_team(redis, user.id)
    fighters[0].current_hp = fighters[0].start_hp // 2
    fighters[1].current_hp = 0
    fight = type("F", (), {"winner": 0, "sides": [type("S", (), {"chars": fighters})()], "round": 4})()
    tower.finish_floor(user, fight, redis, "me")
    carried = tower.load_team(redis, user.id)
    assert carried[0].current_hp == int(fighters[0].start_hp // 2 + fighters[0].start_hp * tower.FLOOR_HEAL)
    assert carried[1].current_hp == 0  # fallen stands wait for a rest stop
    assert tower.state(user)["run"]["floor"] == 2 and tower.state(user)["best"] == 1
    # the floors of a week are fixed; enemies grow exponentially
    assert tower.floor_ids(7, "2026-W40") == tower.floor_ids(7, "2026-W40")
    lv = [tower.level_for(f) for f in range(1, 40)]
    assert lv == sorted(lv) and lv[-1] == 100 and tower.overflow_for(60) > 2
    assert tower.is_rest(5) and tower.is_boss(10)
    # a loss ends the climb
    fight.winner = 1
    tower.finish_floor(user, fight, redis, "me")
    assert tower.state(user)["run"] is None and tower.load_team(redis, user.id) is None


def test_pvp_mutual_ko_is_a_draw_but_pve_goes_to_the_mover():
    from app.game.fight import Fight, Side
    for kind, expected in (("ranked", None), ("story", 0)):
        a, b = _stand(1), _stand(2)
        f = Fight(Side("A", [a], True), Side("B", [b], False), kind=kind)
        a.current_hp = b.current_hp = 0
        f._last_actor = 0
        f._finish()
        assert f.winner == expected, kind


def test_last_weeks_raid_tiers_stay_claimable(monkeypatch):
    from app.game import gangs as G
    from app.game.user import User
    clock = [datetime.datetime(2026, 3, 4, 12)]  # a Wednesday
    monkeypatch.setattr(G, "now", lambda: clock[0])
    gang = {"_id": "g1", "name": "Crusaders"}
    G.raid_state(gang)["hits"]["1"] = 5
    G.raid_state(gang)["damage"] = G.RAID_TIERS[1]["damage"]
    clock[0] = datetime.datetime(2026, 3, 10, 12)  # next week
    user = User(create_user("1"))
    before = user.fragments
    assert G.claimable_tiers(gang, "1") == [] and G.claimable_previous(gang, "1") == [0, 1]
    G.claim_raid(gang, user)
    assert user.fragments == before + G.RAID_TIERS[0]["fragments"] + G.RAID_TIERS[1]["fragments"]
    assert G.claimable_previous(gang, "1") == []
    clock[0] = datetime.datetime(2026, 3, 18, 12)  # two weeks on: gone
    assert G.previous_raid(gang) is None


def test_old_saves_with_the_misspelled_field_still_load(client):
    d = create_user("111")
    d.pop("super_fragments", None)
    d["super_fragements"] = 7
    put(client, d)
    h = login(client, "111")
    assert b"7" in client.get("/banners").data
    client.post("/daily", headers=h)
    saved = doc(client, "111")
    assert saved["super_fragments"] >= 7 and "super_fragements" not in saved


def test_wiki_search_index_covers_guides_stands_and_rules(client):
    entries = client.get("/wiki/search.json").get_json()
    kinds = {e["k"].split(" ·")[0] for e in entries}
    assert {"Guide", "Stand", "Item", "Terrain", "Synergy", "Status effect"} <= kinds
    combat = next(e for e in entries if e["k"] == "Guide" and e["t"] == "Combat system")
    assert "sudden death" in combat["x"].lower() and "<" not in combat["x"]
    assert any(e["t"] == "Star platinum" for e in entries)
    assert b'data-wiki-search' in client.get("/wiki").data


def test_profile_shows_records_and_collection(client):
    player(client, "111", main_characters=[char(1)], storage_characters=[char(10), char(4)], xp=5000)
    page = client.get("/u/111").data.decode()
    for text in ("Story stages", "Tower this week", "Boss rush", "Achievements", "Stands discovered", "Showcase", "Copy profile link"):
        assert text in page, text
