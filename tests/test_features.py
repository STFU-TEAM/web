"""Accounts, gangs, trades, story, items, collection tools, banners and engine fixes."""
import datetime
import pickle
import random

import pytest

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


def test_mirror_world_reflects_the_team_and_never_spawns_the_dummy_or_twoh():
    from app.game.character import Character
    team = [Character(char(i, xp=6000, awaken=2)) for i in (10, 75, 84)]  # UR, UR, LR at level 60, ★2
    rnd = __import__("random")
    rnd.seed(1)
    seen = set()
    for _ in range(200):
        _name, chars, multi, difficulty = logic.mirror_enemy(team)
        seen.add(difficulty)
        fewer = next(d[6] for d in logic.MIRROR_DIFFICULTIES if d[0] == difficulty)
        assert len(chars) == 3 - fewer and all(c.id not in (110, 164) for c in chars)
        assert all(c.rarity in ("SSR", "UR", "LR") for c in chars)  # near the team's rarities
        factor = next(d[2] for d in logic.MIRROR_DIFFICULTIES if d[0] == difficulty)
        assert all(abs(c.level - 60 * factor) <= 60 * factor * 0.11 + 1 for c in chars)
        assert multi > 1.5  # level 60 pays more than a level-0 trip
    assert seen == {d[0] for d in logic.MIRROR_DIFFICULTIES}
    with pytest.raises(logic.GameError):
        logic.mirror_enemy([])


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


def test_wars_match_two_queued_gangs_and_settle_on_the_site(client):
    import datetime
    from app.game import gangs as G
    gids = {}
    for uid, name, stand in (("111", "Passione", 1), ("222", "La Squadra", 2)):
        player(client, uid, fragments=20_000, storage_characters=[char(stand)])
        h = login(client, uid)
        client.post("/gangs/create", data={"name": name}, headers=h)
        gids[uid] = doc(client, uid)["gang_id"]
        if uid == "111":
            client.post("/gangs/war/start", headers=h)  # no guardian: refused
            assert client.fake.get(f"web:gang:queued:{gids[uid]}") is None
        client.post("/gangs/guardians/add", data={"uuid": doc(client, uid)["storage_characters"][0]["uuid"]}, headers=h)
        client.post("/gangs/war/start", headers=h)
    a, b = gids["111"], gids["222"]
    assert pickle.loads(client.fake.hget("active_wars", a)) == b and pickle.loads(client.fake.hget("active_wars", b)) == a
    assert client.fake.get(f"web:gang:queued:{a}") is None
    # members attack the other gang's guardians
    player(client, "111", fragments=0, main_characters=[char(5, xp=10000)], gang_id=a)
    h = login(client, "111")
    assert client.post("/gangs/war/attack", headers=h).headers["Location"].endswith("/gangs/fight")
    # time's up: the first visit settles it
    mine = pickle.loads(client.fake.hget("gangs", a))
    mine.update(damage_to_current_war=67, end_of_war=datetime.datetime(2000, 1, 1))
    client.fake.hset("gangs", a, pickle.dumps(mine))
    vault = mine.get("vault", 0)
    assert b"Passione" in client.get("/gangs").data
    mine, theirs = pickle.loads(client.fake.hget("gangs", a)), pickle.loads(client.fake.hget("gangs", b))
    assert mine["vault"] == vault + G.WAR_PRIZE and mine["war_elo"] > 0 and theirs["war_elo"] == 0
    assert client.fake.hget("active_wars", a) is None and client.fake.hget("active_wars", b) is None
    assert G.last_war(client.fake, a)["winner"] == a


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


def _ach_dust(d):
    """Meteor Dust paid by achievements this save unlocked (forced test wins land in round 1: ZA WARUDO)."""
    from app.game.achievements import ACHIEVEMENT_BY_ID
    return sum(ACHIEVEMENT_BY_ID[a]["reward"]["fragments"] for a in d.get("achievement_data", {}).get("unlocked", []))


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
    assert d["web_story"]["cleared"] == 1 and d["fragments"] == story.reward_for(0)["fragments"] + _ach_dust(d)
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
    assert drawn.rarity in ("UR", "LR") and user.pity == 0  # pity guarantees a UR or better
    assert logic.PITY_ODDS == {"UR": 0.55, "LR": 0.45}
    user.pity = 10
    logic._banner_draw(banner, user, forced="SSR")
    assert user.pity == 11  # an SSR no longer resets pity
    # Devil's Palms share the same pity: they count toward it and it can land on them
    logic._arrow_draw(banner, user, forced="SR")
    assert user.pity == 12
    user.pity = logic.PITY_LIMIT - 1
    assert logic._arrow_draw(banner, user).rarity in ("UR", "LR") and user.pity == 0
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
    team_hermit = char(4, xp=2000)  # Hermit Purple (R, Lv 20) in the team absorbs its storage copies
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
    hermit = d["main_characters"][0]
    # Lv 20 earns ★1 on the first copy; ★2 needs Lv 50, so the second copy pays XP only
    assert hermit["uuid"] == team_hermit["uuid"] and hermit["awaken"] == 1 and hermit["xp"] == 2000 + 2 * logic.FUSE_BONUS_XP["R"]
    wof = [c for c in d["storage_characters"] if c["id"] == 15]
    assert [c["uuid"] for c in wof] == [locked_copy["uuid"]] and wof[0]["awaken"] == 0 and wof[0]["xp"] == 900 + 2 * logic.FUSE_BONUS_XP["R"]
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
    left = doc(client, "111")["super_fragments"]  # 2, or 3 if the pull earned Bad Luck Brian's Arrowhead
    assert b"Pull 10 again" in r.data and f'{left}<span class="cur cur-head"'.encode() in r.data
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
    assert rate(starter, first[5], story.TOTAL) <= 0.03      # new teams can't skip ahead (a fluke at most)
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


def test_iggys_collar_makes_its_holder_taunt():
    from app.game.fight import ai_choice
    from app.game.character import Character
    from app.game.items import get_item_from_template, item_file
    collar = next(i for i in item_file if i["name"] == "Iggy's Collar")
    hitter, weak, holder = _stand(10), _stand(1), _stand(2)
    bare_armor = holder.start_armor
    assert not holder.taunt
    holder = Character({**holder.to_dict(), "items": [get_item_from_template(collar)]})
    assert holder.taunt and not holder.natural_taunt
    assert holder.start_armor > bare_armor
    weak.current_hp = 5
    assert ai_choice([weak, holder], hitter) == 1  # the kill is skipped: the collar forces the target


def test_special_text_shows_what_each_number_is_worth():
    from app.filters import special_text
    emperor = _stand(14)  # Headshot: `220%` damage
    html = str(special_text(emperor))
    assert 'class="sp-scales"' in html and f"{emperor.start_damage * 2.2:,.0f}" in html
    assert 'class="sp-calc"' not in str(special_text(CHARACTER_FILE[13], owned=False))


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
    assert run["index"] == 1 and d["fragments"] == rush.REWARDS[0]["fragments"] + _ach_dust(d)
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
    client.post("/items/craft", data={"recipe": "Devil's Palm"}, headers=h)
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
    lv = [tower.level_for(f) for f in range(1, 45)]
    assert lv == sorted(lv) and lv[-1] == 100 and tower.overflow_for(60) == 1 and tower.overflow_for(80) > 2
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


def test_requiem_arrow_rules_for_ger_and_the_star_cap(client):
    from app.game.logic import MAX_AWAKEN
    ge_two = char(59, xp=10_000, awaken=2)
    player(client, "111", main_characters=[ge_two], items=[{"id": 3}, {"id": 3}])
    h = login(client, "111")
    client.post("/items/use", data={"item": 3, "uuid": ge_two["uuid"]}, headers=h)
    d = doc(client, "111")
    assert d["main_characters"][0]["id"] == 59 and d["main_characters"][0]["awaken"] == 3  # ★2: just an awakening
    client.post("/items/use", data={"item": 3, "uuid": ge_two["uuid"]}, headers=h)
    assert doc(client, "111")["main_characters"][0]["id"] == 84  # ★3 level 100: Gold Experience Requiem
    capped = char(1, awaken=MAX_AWAKEN)
    player(client, "222", main_characters=[capped], items=[{"id": 3}])
    h2 = login(client, "222")
    r = client.post("/items/use", data={"item": 3, "uuid": capped["uuid"]}, headers=h2)
    d = doc(client, "222")
    assert d["main_characters"][0]["awaken"] == MAX_AWAKEN and d["items"] == [{"id": 3}] and b"5" in r.data


def test_reforge_locks_pairs_charges_by_rarity_and_lets_the_player_choose(client):
    from app.game.logic import REFORGE_LOCK_MULT, REFORGE_PRICE
    stand = char(1, types=["ATTACK", "SPEED", "LUCK"], quals=["UNIVERSAL", "BAD", "GOOD"])
    other = char(4)
    player(client, "111", main_characters=[stand, other], fragments=50_000)
    h = login(client, "111")
    rarity = CHARACTER_FILE[0]["rarity"]
    page = client.get("/reforge?uuid=" + stand["uuid"]).data.decode()
    assert "data-forge-lock" in page and "data-costs" in page
    client.post("/reforge/roll", data={"uuid": stand["uuid"], "lock": ["0"]}, headers=h)
    d = doc(client, "111")
    assert d["fragments"] == 50_000 - int(round(REFORGE_PRICE[rarity] * REFORGE_LOCK_MULT, -1))
    pending = d["web_reforge_pending"]
    assert pending["types"][0] == "ATTACK" and pending["qualities"][0] == "UNIVERSAL"
    assert "ATTACK" not in pending["types"][1:]
    # a second stand can't start while the first decision waits
    assert b"still has a new roll waiting" in client.post("/reforge/roll", data={"uuid": other["uuid"]}, headers=h).data
    client.post("/reforge/keep", data={"keep": "new"}, headers=h)
    d = doc(client, "111")
    assert d["main_characters"][0]["types"] == pending["types"] and not d.get("web_reforge_pending")
    # every pair locked is refused and costs nothing
    before = d["fragments"]
    n = len(pending["types"])
    r = client.post("/reforge/roll", data={"uuid": stand["uuid"], "lock": [str(i) for i in range(n)]}, headers=h)
    assert b"at least one" in r.data and doc(client, "111")["fragments"] == before


def test_reach_quests_keep_the_best_value():
    from app.game.quests import ensure_quests_assigned, track_quest_progress
    u = User(create_user("1"))
    ensure_quests_assigned(u)
    track_quest_progress(u, "reach_story", 7)
    track_quest_progress(u, "reach_story", 3)
    story = {e["quest_id"]: e["progress"] for e in u.quests["active_permanent"] if e["quest_id"] in (1005, 1006)}
    assert story == {1005: 6, 1006: 7}  # capped at the target, never lowered by a smaller value


def test_service_worker_and_install_prompt(client):
    r = client.get("/sw.js")
    assert r.status_code == 200 and "javascript" in r.mimetype and r.headers["Service-Worker-Allowed"] == "/"
    player(client, "111")
    login(client, "111")
    assert b"data-install" in client.get("/").data


def test_fusing_stars_wait_for_the_level_and_shop_heads_are_capped(client):
    from app.game.logic import SHOP_HEADS_PER_WEEK
    keeper, spare, spare2 = char(1, xp=4900), char(1), char(1)
    player(client, "111", main_characters=[keeper], storage_characters=[spare, spare2], fragments=100_000)
    h = login(client, "111")
    client.post("/team/fuse", data={"uuid": keeper["uuid"], "fodder": spare["uuid"]}, headers=h)  # team keeper is fine
    d = doc(client, "111")["main_characters"][0]
    assert d["xp"] == 4900 + logic.FUSE_BONUS_XP["SSR"] and d["awaken"] == 1  # Lv 50+: ★1 comes first
    client.post("/team/fuse", data={"uuid": keeper["uuid"], "fodder": spare2["uuid"]}, headers=h)
    assert doc(client, "111")["main_characters"][0]["awaken"] == 2
    for _ in range(SHOP_HEADS_PER_WEEK):
        client.post("/shop/buy", data={"key": "super_fragment"}, headers=h)
    r = client.post("/shop/buy", data={"key": "super_fragment"}, headers=h)
    assert b"summons a week" in r.data and doc(client, "111")["super_fragments"] == SHOP_HEADS_PER_WEEK
    palms = sum(1 for i in doc(client, "111")["items"] if i["id"] == 2)
    r = client.post("/shop/buy", data={"key": "2"}, headers=h)  # Devil's Palms share the same weekly cap
    assert b"summons a week" in r.data and sum(1 for i in doc(client, "111")["items"] if i["id"] == 2) == palms


def test_balance_stats_count_finished_fights_once(client):
    import datetime
    from app.game import stats
    from app.game.character import character_from_dict
    from app.game.fight import Fight, Side
    redis = client.fake
    when = datetime.datetime(2026, 10, 5)
    knife = character_from_dict(char(1, xp=5000, items=[{"id": 1}]))
    bare = character_from_dict(char(1, xp=5000))
    foes = [character_from_dict(char(4))]
    win = Fight(Side("A", [knife, bare], True), Side("B", foes, False), kind="story")
    win.finished, win.winner = True, 0
    assert stats.record(redis, win, when) and not stats.record(redis, win, when)  # once only
    lost = Fight(Side("A", [character_from_dict(char(1, xp=5000))], True), Side("B", foes, False), kind="tower")
    lost.finished, lost.winner = True, 1
    stats.record(redis, lost, when)
    duel = Fight(Side("A", [character_from_dict(char(2))], True), Side("B", [character_from_dict(char(3))], True), kind="ranked")
    duel.finished, duel.winner = True, None  # a draw: half a win each
    stats.record(redis, duel, when)
    quit_ = Fight(Side("A", [character_from_dict(char(2))], True), Side("B", foes, False), kind="story")
    quit_.forfeit()
    assert not stats.record(redis, quit_, when)
    rep = stats.report(redis, when, 1)
    sp = next(s for s in rep["stands"] if s["id"] == 1)
    assert sp["pve"] == {"games": 3, "rate": 2 / 3} and "pvp" not in sp
    assert next(s for s in rep["stands"] if s["id"] == 2)["pvp"]["rate"] == .5
    assert all(s["id"] != 4 for s in rep["stands"])  # scripted PvE enemies aren't counted
    knife_row = next(i for i in rep["items"] if i["id"] == 1)["pve"]
    assert knife_row["rate"] == 1 and round(knife_row["delta"], 3) == .5  # 100% with it vs 50% without
    admin = sorted(client.application.config["DISCORD_ADMIN_IDS"])[0]
    player(client, admin)
    login(client, admin)
    assert b"Balance stats" in client.get("/admin/stats?weeks=12").data


def test_specials_scale_with_their_stat_and_matching_type():
    import random as rnd
    from app.game import characterabilities as ab
    from app.game.character import LUCK_TYPE_POINTS, SPEED_TYPE_POINTS, Character, natural_stats

    def mk(cid, types=(), quals=(), items=()):
        return Character({"id": cid, "xp": 6000, "awaken": 1, "items": [{"id": i} for i in items],
                          "types": list(types), "qualities": list(quals)})
    bare = mk(1)
    assert ab.special_power(bare)["power"] == 1 and ab.scaling_of(1) == "speed"
    # SPEED and LUCK now add real points; a speed build powers Star Platinum's rush
    fast = mk(1, ["SPEED"], ["UNIVERSAL"], [44])
    assert fast.start_speed - natural_stats(fast)["speed"] >= SPEED_TYPE_POINTS["UNIVERSAL"]
    sp = ab.special_power(fast)
    assert sp["power"] > 1.6 and sp["affinity"] == ab.AFFINITY["UNIVERSAL"] and sp["type"] == "Speed Universal"
    lucky = mk(14, ["LUCK"], ["GREAT"])
    assert lucky.start_critical >= LUCK_TYPE_POINTS["GREAT"] and lucky.crit_multiplier > 1.5
    # damage specials only take the affinity (their hits already use damage)
    kq = ab.special_power(mk(49, ["ATTACK"], ["UNIVERSAL"], [1]))
    assert kq["invest"] == 0 and kq["power"] == 1 + ab.AFFINITY["UNIVERSAL"]
    # off-type rolls give nothing, BALANCE half
    assert ab.special_power(mk(1, ["DEFENSE"], ["UNIVERSAL"]))["affinity"] == 0
    assert ab.special_power(mk(1, ["BALANCE"], ["UNIVERSAL"]))["affinity"] == ab.AFFINITY["UNIVERSAL"] / 2

    # the same special, the same enemy: the built copy hits harder
    def rush(attacker):
        rnd.seed(3)
        foe = mk(10)
        foe.current_hp = 10 ** 6
        attacker.special([attacker], [foe])
        return 10 ** 6 - foe.current_hp
    assert rush(fast) > rush(mk(1)) * 1.4
    # health specials scale their heals; the power is gone once the special ends
    healer, hurt = mk(92, ["HEALTH"], ["UNIVERSAL"], [43]), mk(1)
    hurt.current_hp = 1
    healer.special([healer, hurt], [mk(10)])
    assert hurt.current_hp - 1 > hurt.start_hp * 0.25
    assert ab._CTX["caster"] is None and ab._power() == 1.0


def test_funny_achievements_secrets_and_palms(client):
    from app.game import logic
    from app.game.achievements import check_achievements, get_all_achievements_status
    from app.game.user import User
    from app.routes.battles import _settle
    from app.game.character import character_from_dict
    from app.game.fight import Fight, Side
    player(client, "111", main_characters=[char(1)], items=[{"id": 2}], fragments=10_000)
    h = login(client, "111")
    # Devil's Palms only work on banners now
    r = client.post("/items/use", data={"item": 2}, headers=h)
    assert b"on a banner" in r.data and doc(client, "111")["items"] == [{"id": 2}]
    assert b"Pick a banner" in client.get("/items").data
    # secrets stay hidden until unlocked
    u = User(doc(client, "111"))
    rows = {a["id"]: a for a in get_all_achievements_status(u)}
    assert rows[24]["name"] == "???" and "Outlast" in rows[24]["description"]
    # defeating the dummy unlocks it (and a surrender is not a dummy loss)
    with client.application.app_context():
        dummy = character_from_dict({"id": 164, "xp": 100, "types": [], "qualities": [], "awaken": 0, "items": []})
        f = Fight(Side("A", [character_from_dict(char(1))], True), Side("D", [dummy], False), kind="dummy",
                  meta={"players": ["111"]})
        f.finished, f.winner = True, 0
        _settle(f)
    d = doc(client, "111")
    assert 24 in d["achievement_data"]["unlocked"]
    assert get_all_achievements_status(User(d))[23]["name"] == "Dummy Thicc"
    # reforging is a cheap service now
    assert logic.REFORGE_PRICE["LR"] <= 1500


def test_banner_rotation_two_parts_and_a_theme_each_day(client, monkeypatch):
    import datetime
    monkeypatch.undo()  # back to the real rotation (the fixture opens every banner)
    from app.game import logic as L
    themes = {b["id"] for b in L.BANNERS if b.get("theme")}
    parts = {b["id"] for b in L.BANNERS if not b.get("theme")}
    seen_parts, seen_themes = set(), set()
    for day in range(6):  # one full cycle shows everything
        ids = L.rotation_ids(day)
        assert len(ids) == 3 and len(set(ids) & parts) == 2 and len(set(ids) & themes) == 1
        seen_parts |= set(ids) & parts
        seen_themes |= set(ids) & themes
    assert seen_parts == parts and seen_themes == themes  # everything comes around
    day5 = L.ROTATION_START + datetime.timedelta(days=5)
    assert L.rotation_day(day5) == 5 and L.rotation_day(datetime.datetime.combine(day5, datetime.time(23, 59))) == 5
    sched = L.banner_schedule(3, when=day5)
    assert sched[0]["current"] and [b["id"] for b in sched[1]["banners"]] == L.rotation_ids(6)
    off = next(i for i in parts if i not in L.rotation_ids(5))
    assert L.next_appearance(off, when=day5) <= day5 + datetime.timedelta(days=3)  # a Part is back within 3 days
    assert L.rotation_ends(day5).date() == day5 + datetime.timedelta(days=1)
    # themed banners never turn an R draw into a rare: the nearest rarity fills in
    theme = next(b for b in L.BANNERS if b["id"] == 10)
    assert all(L._template_of(theme, "R")["rarity"] in ("R",) for _ in range(30))
    only_rare = {"cards": [10, 84]}
    assert L._template_of(only_rare, "R")["rarity"] == "UR"


def test_pulls_vary_pity_can_give_lr_and_admins_can_force_a_rarity(client):
    import random as rnd
    from app.game import logic
    from app.game.user import User
    # no stand twice in one 10-pull while its rarity has others left (JoJo Legacy used to repeat in every pull)
    legacy = next(b for b in logic.BANNERS if b["id"] == 10)
    u = User(create_user("1"))
    rnd.seed(4)
    for _ in range(200):
        drawn = []
        for _ in range(10):
            drawn.append(logic._banner_draw(legacy, u, exclude={c.id for c in drawn}))
        by_rarity = {}
        for c in drawn:
            by_rarity.setdefault(c.rarity, []).append(c.id)
        pool = {r: sum(1 for i in legacy["cards"] if CHARACTER_FILE[i - 1]["rarity"] == r) for r in by_rarity}
        for r, ids in by_rarity.items():
            assert len(set(ids)) == min(len(ids), pool[r]), (r, ids)
    # the pity roll can land an LR on a banner that has one
    rnd.seed(0)
    seen = set()
    for _ in range(400):
        u.pity = logic.PITY_LIMIT  # every draw is a pity draw
        seen.add(logic._banner_draw(legacy, u).rarity)
    assert seen == {"UR", "LR"}  # pity is a UR, sometimes an LR
    # admins can force a rarity on their own pulls; players can't
    admin = sorted(client.application.config["DISCORD_ADMIN_IDS"])[0]
    player(client, admin, super_fragments=5)
    h = login(client, admin)
    client.post("/banners/force", data={"rarity": "UR", "scope": "all"}, headers=h)
    r = client.post("/banners/0/pull", headers=h)
    assert r.status_code == 200
    got = doc(client, admin)["main_characters"] + doc(client, admin)["storage_characters"]
    assert {CHARACTER_FILE[c["id"] - 1]["rarity"] for c in got} == {"UR"}
    client.post("/banners/force", data={"rarity": ""}, headers=h)
    assert client.fake.get(f"web:admin:force_rarity:{admin}") is None
    player(client, "222")
    h2 = login(client, "222")
    assert client.post("/banners/force", data={"rarity": "LR"}, headers=h2).status_code == 403


def test_pvp_waiting_auto_refreshes_and_the_turn_clock_stops_stalling(client, monkeypatch):
    import time as _time
    from app.db import load_fight
    from app.routes import battles as B
    player(client, "111", main_characters=[char(1, xp=3000)])
    player(client, "222", main_characters=[char(2, xp=3000)])
    # ranked: the first player waits; the page polls /battles/ping, which matches once someone else queues
    h1 = login(client, "111")
    client.post("/battles/ranked/queue", headers=h1)
    assert b"battles/ping" in client.get("/team").data  # every page polls while waiting
    assert client.get("/battles/ping", headers=h1).status_code == 204  # nobody yet
    client.fake.zadd(B.RANKED_QUEUE, {"222": _time.time()})
    client.fake.hset(B.RANKED_ELO, "222", 0)
    r = client.get("/battles/ping", headers=h1)
    assert r.headers.get("HX-Redirect", "").endswith("/battles")
    fight = load_fight("111")
    assert fight and fight.kind == "ranked" and fight.meta["deadline"] > _time.time()
    # the clock: a miss picks for you, a second miss in a row loses the duel
    with client.application.app_context():
        acting = fight.meta["players"][fight.acting_side]
        h = login(client, acting)
        turn = fight.turn
        fight.meta["deadline"] = _time.time() - 1
        from app.db import save_fight
        for uid in fight.meta["players"]:
            save_fight(uid, fight)
    client.post("/battles/attack", data={"log_len": 0}, headers=h)
    fight = load_fight(acting)
    assert fight.meta["afk"][fight.meta["players"].index(acting)] == 1 and not fight.finished
    assert "Time's up" in " ".join(e["text"] for e in fight.log)
    side = fight.meta["players"].index(acting)
    if fight.acting_side == side and not fight.finished:
        fight.meta["deadline"] = _time.time() - 1
        with client.application.app_context():
            for uid in fight.meta["players"]:
                save_fight(uid, fight)
        client.post("/battles/attack", data={"log_len": 0}, headers=h)
        fight = load_fight(acting)
        assert fight.finished and fight.winner == 1 - side and fight.meta["timeout"] == side
    # nothing to wait for any more: the poll tells the page to stop (htmx 286)
    client.post("/battles/leave", headers=h)
    client.fake.delete("web:fight:111", "web:fight:222")
    assert client.get("/battles/ping", headers=login(client, "222")).status_code == 286


def test_friend_challenge_sender_waits_and_hears_the_accept(client):
    player(client, "111", main_characters=[char(1)])
    player(client, "222", main_characters=[char(6)])
    h1 = login(client, "111")
    client.post("/battles/friends/invite", data={"user_id": "222"}, headers=h1)
    page = client.get("/battles?mode=friends").data.decode()
    assert "Waiting for" in page and "battles/ping" in page
    h2 = login(client, "222")
    cid = next(iter(client.fake.smembers("web:friend:inbox:222"))).decode()
    client.post(f"/battles/friends/accept/{cid}", headers=h2)
    h1 = login(client, "111")
    assert client.get("/battles/ping", headers=h1).headers.get("HX-Redirect", "").endswith("/battles")
    assert b"accepted your duel" in client.get("/community/inbox").data


def test_banner_details_show_odds_and_every_stand(client):
    from app.game import logic
    player(client, "111", storage_characters=[char(1)])
    h = login(client, "111")
    r = client.get("/banners/0/details", headers={**h, "HX-Request": "true"})
    page = r.data.decode()
    assert r.status_code == 200 and "Odds" in page and "Star platinum" in page and "TheWorld" in page
    assert "You own 1 of these" in page and "One given stand" in page
    assert "this banner has no LR" in page  # Part 3: pity gives a UR
    assert "<html" in client.get("/banners/0/details").data.decode().lower()  # full page without JS
    b = next(x for x in logic.BANNERS if x["id"] == 0)
    from app.routes.play import banner_odds
    rows = {row["rarity"]: row for row in banner_odds(b)["rows"]}
    assert abs(sum(r["pull"] for r in rows.values()) - 1) < 1e-9
    assert abs(rows["R"]["pull_each"] * rows["R"]["count"] - logic.BANNER_ODDS["R"]) < 1e-9
    assert client.get("/banners/999/details", headers=h).status_code == 404


def test_health_type_boosts_health_and_powers_healers():
    from app.game import characterabilities as ab
    from app.game.character import Character, natural_stats
    mk = lambda t: Character({"id": 92, "xp": 6000, "awaken": 1, "items": [], "types": [t], "qualities": ["UNIVERSAL"]})
    healer = mk("HEALTH")
    assert healer.start_hp > natural_stats(healer)["hp"] * 1.3
    assert ab.special_power(healer)["type"] == "Health Universal"
    assert ab.special_power(mk("DEFENSE"))["affinity"] == 0  # DEFENSE is armor only now
    assert mk("DEFENSE").start_hp == natural_stats(healer)["hp"]


def test_admins_can_grant_and_toggle_shiny_and_fusing_keeps_it(client):
    from app.game import logic
    from app.game.user import User
    admin = sorted(client.application.config["DISCORD_ADMIN_IDS"])[0]
    player(client, admin)
    player(client, "111", storage_characters=[char(1)])
    h = login(client, admin)
    client.post("/admin/player/111/grant_stand", data={"stand_id": 1, "level": 30, "awaken": 5, "shiny": "1"}, headers=h)
    stands = doc(client, "111")["storage_characters"]
    shiny = next(s for s in stands if s.get("shiny"))
    assert shiny["id"] == 1 and shiny["awaken"] == 5  # ★5 is now grantable too
    # the toggle on an existing stand: off, then on again
    plain = next(s for s in stands if not s.get("shiny"))
    client.post("/admin/player/111/stand_edit", data={"uuid": shiny["uuid"], "level": 30, "awaken": 5}, headers=h)
    assert not next(s for s in doc(client, "111")["storage_characters"] if s["uuid"] == shiny["uuid"]).get("shiny")
    client.post("/admin/player/111/stand_edit", data={"uuid": shiny["uuid"], "level": 30, "awaken": 5, "shiny": "1"}, headers=h)
    # fusing a shiny copy into a plain one keeps the shine
    u = User(doc(client, "111"))
    keeper = next(c for c in u.storage_characters if c.uuid == plain["uuid"])
    fodder = next(c for c in u.storage_characters if c.uuid == shiny["uuid"])
    logic._absorb(u, keeper, fodder)
    assert keeper.shiny and keeper.to_dict()["shiny"] is True
    # and the card shows it
    login(client, "111")
    page = client.get("/team").data.decode()
    assert "card" in page and " shiny" in page and "shiny-badge" in page


def test_short_cooldowns_open_when_the_timer_hits_zero():
    import datetime
    assert logic.wormhole_wait(User(create_user("cd"))) == 10 / 60
    just_over = logic.now() - datetime.timedelta(minutes=10, seconds=5)
    assert logic.cooldown_left(just_over, 10 / 60) is None          # used to stay locked for the whole hour
    left = logic.cooldown_left(logic.now() - datetime.timedelta(minutes=4), 10 / 60)
    assert 5 * 60 < left.total_seconds() <= 6 * 60
    assert logic.cooldown_left(logic.now() - datetime.timedelta(hours=1, minutes=45), 1.5) is None


def test_tower_floors_show_their_rewards():
    from app.game import tower
    view = tower.preview(10)["reward"]
    assert view["fragments"] == tower.reward_for(10)["fragments"] and view["super"] == 1
    assert view["items"] and view["stand_xp"] == tower.stand_xp_for(10)
    assert [m["floor"] for m in tower.milestones(3)] == [5, 10, 15, 20]
    assert [m["floor"] for m in tower.milestones(10)] == [15, 20, 25, 30]


def test_synergy_team_bonus_applies_once_and_logs():
    from app.game.characterabilities import SYNERGY_BONUS, SYNERGY_INFO, SYNERGIES
    from app.game.fight import Fight, Side
    assert set(SYNERGY_BONUS) == set(SYNERGIES) == set(SYNERGY_INFO)  # every group has a bonus and a name
    jotaro, avdol, loner = _stand(1), _stand(2), _stand(92)
    dmg, spd = jotaro.current_damage, jotaro.current_speed
    team = [jotaro, avdol, loner]
    fight = Fight(Side("A", team, True), Side("B", [_stand(150)], False))
    assert jotaro.current_damage == pytest.approx(dmg * 1.08) and jotaro.current_speed == pytest.approx(spd * 1.08)
    assert any("Stardust Crusaders" in e["text"] for e in fight.log)
    Fight(Side("A", team, True), Side("B", [_stand(150)], False))  # the tower reuses its fighters
    assert jotaro.current_damage == pytest.approx(dmg * 1.08)


def test_new_terrain_setters_are_natives():
    from app.game.effects import TERRAIN_BENEFITS, TERRAIN_SETTERS
    assert all(t in TERRAIN_BENEFITS.get(cid, {}) for cid, t in TERRAIN_SETTERS.items())


def test_alternate_universe_opens_with_the_story_and_pays_once(client):
    import app.db as dbmod
    from app.game import altverse
    player(client, "111", fragments=0, super_fragments=0)
    h = login(client, "111")
    d = doc(client, "111")
    d["main_characters"] = [char(1)]
    put(client, d)
    page = client.get("/alternate-universe").data.decode()
    assert "No universe has split off yet" in page and "Opens after Part 3" in page
    client.post("/alternate-universe/fight", data={"chapter": "world_unbroken"}, headers=h)
    assert client.fake.get("web:fight:111") is None  # locked until Part 3's boss falls

    d = doc(client, "111")
    d["web_story"] = {"cleared": altverse._boss_index(3) + 1}
    put(client, d)
    assert "Cairo Under Night" in client.get("/alternate-universe").data.decode()
    client.post("/alternate-universe/fight", data={"chapter": "world_unbroken"}, headers=h)
    fight = dbmod.load_fight("111")
    assert fight.kind == "alt_universe" and fight.meta == {"chapter": "world_unbroken", "stage": 0}
    for c in fight.sides[1].chars:
        c.current_hp = 0
    dbmod.save_fight("111", fight)
    client.post("/alternate-universe/attack", data={"log_len": len(fight.log)}, headers=h)
    client.post("/alternate-universe/leave", headers=h)
    d = doc(client, "111")
    assert d["web_au"]["cleared"]["world_unbroken"] == 1
    assert d["fragments"] == altverse.reward_for("world_unbroken", 0)["fragments"] + _ach_dust(d)
    assert "The Vampire Guard" in client.get("/alternate-universe?ch=world_unbroken").data.decode()
    # the finale's boss is the hardest fight and pays a Requiem Arrow
    assert altverse.difficulty("requiem_of_all", 4)["mult"] > 1
    assert 3 in altverse.reward_for("requiem_of_all", 4)["items"]


# --------------------------------------------------------------------------- #
# Auction house, Crusaders' Journey, gang hub
# --------------------------------------------------------------------------- #
def test_auction_escrows_sells_for_dust_and_arrowheads_and_returns_unsold(client):
    import json
    from app.game import auction as A
    sold, kept = char(10, items=[{"id": 1}]), char(1)
    player(client, "111", main_characters=[kept], storage_characters=[sold], fragments=0, super_fragments=0)
    player(client, "222", fragments=5000, super_fragments=3)
    h = login(client, "111")
    client.post("/auction/sell", data={"uuid": kept["uuid"], "dust": 100}, headers=h)  # last team stand: refused
    assert not A.all_listings(client.fake)
    client.post("/auction/sell", data={"uuid": sold["uuid"]}, headers=h)  # no price: refused
    assert not A.all_listings(client.fake)
    client.post("/auction/sell", data={"uuid": sold["uuid"], "dust": 1000, "heads": 2}, headers=h)
    d = doc(client, "111")
    assert d["storage_characters"] == [] and [i["id"] for i in d["items"]] == [1]  # escrowed, gear kept
    listing = A.all_listings(client.fake)[0]
    assert "TheWorld" in client.get("/auction").data.decode()

    h2 = login(client, "222")
    client.post(f"/auction/{listing['id']}/buy", headers=h2)
    buyer, seller = doc(client, "222"), doc(client, "111")
    assert buyer["fragments"] == 4000 and buyer["super_fragments"] == 1
    assert [c["uuid"] for c in buyer["storage_characters"]] == [sold["uuid"]]
    assert seller["fragments"] == 1000 - A.fee_for(1000) and seller["super_fragments"] == 2
    assert not A.all_listings(client.fake)

    # an unsold listing comes back when it expires
    h = login(client, "222")
    client.post("/auction/sell", data={"uuid": sold["uuid"], "heads": 1}, headers=h)
    listing = A.all_listings(client.fake)[0]
    listing["ends"] = 0
    client.fake.hset(A.KEY, listing["id"], json.dumps(listing))
    client.get("/auction")
    assert [c["uuid"] for c in doc(client, "222")["storage_characters"]] == [sold["uuid"]]


def test_journey_takes_the_stand_away_and_pays_by_power():
    import time as _time
    from app.game import journey as J
    u = User(create_user("j"))
    weak, strong = _stand(8), _stand(84)
    strong.xp, strong.awaken = 10000, 3
    strong = Character_from(strong)
    u.main_characters = [weak, strong]
    with pytest.raises(logic.GameError):
        J.depart(u, weak.uuid, "nowhere")
    trip = J.depart(u, strong.uuid, "cairo", now=1000)
    assert strong.uuid not in [c.uuid for c in u.main_characters + u.storage_characters]  # can't be fielded
    with pytest.raises(logic.GameError):
        J.depart(u, weak.uuid, "hong_kong")  # the last team stand stays
    cairo = J.BY_KEY["cairo"]
    assert J.estimate(cairo, J.power_of(strong))["fragments"] > J.estimate(cairo, J.power_of(weak))["fragments"] * 2
    with pytest.raises(logic.GameError):
        J.claim(u, trip["id"], now=1000 + 3600)  # still on the road
    dust = u.fragments
    res = J.claim(u, trip["id"], now=trip["end"])
    assert u.fragments == dust + trip["loot"]["fragments"] and res["stand"].uuid == strong.uuid
    assert strong.uuid in [c.uuid for c in u.main_characters + u.storage_characters]
    trip = J.depart(u, strong.uuid, "singapore", now=_time.time())
    J.recall(u, trip["id"])
    assert J.journeys(u) == []


def Character_from(c):
    from app.game.character import character_from_dict
    return character_from_dict(c.to_dict())


def test_team_page_puts_the_gang_up_front(client):
    player(client, "111", main_characters=[char(1)])
    login(client, "111")
    page = client.get("/team").data.decode()
    assert "not in a gang yet" in page and "Crusaders" in page and "Plan a trip" in page
    assert page.index('class="nav-gang"') < page.index("Summon")
    assert client.get("/journey").status_code == 200


def test_auction_bids_escrow_refund_extend_and_settle(client):
    import json
    from app.game import auction as A
    lot, other = char(10), char(1)
    player(client, "111", main_characters=[char(2)], storage_characters=[lot, other], fragments=0, super_fragments=0)
    player(client, "222", fragments=5000)
    player(client, "333", fragments=5000)
    h1 = login(client, "111")
    client.post("/auction/sell", data={"uuid": lot["uuid"], "mode": "bid", "currency": "dust", "start": 1000,
                                       "buyout": 900, "hours": 24}, headers=h1)
    assert not A.all_listings(client.fake)  # buyout under the start: refused
    client.post("/auction/sell", data={"uuid": lot["uuid"], "mode": "bid", "currency": "dust", "start": 1000,
                                       "hours": 24}, headers=h1)
    listing = A.all_listings(client.fake)[0]
    assert listing["mode"] == "bid" and listing["dust"] == 0 and A.min_bid(listing) == 1000

    h2 = login(client, "222")
    client.post(f"/auction/{listing['id']}/bid", data={"amount": 999}, headers=h2)  # under the start
    assert doc(client, "222")["fragments"] == 5000
    client.post(f"/auction/{listing['id']}/bid", data={"amount": 1000}, headers=h2)
    assert doc(client, "222")["fragments"] == 4000  # held in escrow
    client.post(f"/auction/{listing['id']}/bid", data={"amount": 1100}, headers=h2)  # raising costs the difference
    assert doc(client, "222")["fragments"] == 3900

    h1 = login(client, "111")
    client.post(f"/auction/{listing['id']}/cancel", headers=h1)  # it has bids: can't cancel
    assert A.get(client.fake, listing["id"])

    h3 = login(client, "333")
    client.post(f"/auction/{listing['id']}/bid", data={"amount": 1150}, headers=h3)  # under +5%
    assert A.get(client.fake, listing["id"])["bidder"] == "222"
    listing = A.get(client.fake, listing["id"])
    listing["ends"] = int(__import__("time").time()) + 30  # 30 s left: the next bid pushes the end back
    client.fake.hset(A.KEY, listing["id"], json.dumps(listing))
    client.post(f"/auction/{listing['id']}/bid", data={"amount": 1200}, headers=h3)
    fresh = A.get(client.fake, listing["id"])
    assert fresh["bidder"] == "333" and fresh["ends"] - __import__("time").time() > A.SNIPE_GUARD - 5
    assert doc(client, "222")["fragments"] == 5000 and doc(client, "333")["fragments"] == 3800  # 222 refunded

    fresh["ends"] = 0
    client.fake.hset(A.KEY, fresh["id"], json.dumps(fresh))
    client.get("/auction")  # the sweep settles it
    assert [c["uuid"] for c in doc(client, "333")["storage_characters"]] == [lot["uuid"]]
    assert doc(client, "111")["fragments"] == 1200 - A.fee_for(1200)


def test_auction_buyout_refunds_the_top_bidder(client):
    from app.game import auction as A
    lot = char(10)
    player(client, "111", main_characters=[char(2)], storage_characters=[lot], super_fragments=0)
    player(client, "222", super_fragments=10)
    player(client, "333", super_fragments=10)
    client.post("/auction/sell", data={"uuid": lot["uuid"], "mode": "bid", "currency": "heads", "start": 2,
                                       "buyout": 6, "hours": 12}, headers=login(client, "111"))
    listing = A.all_listings(client.fake)[0]
    assert listing["heads"] == 6 and listing["currency"] == "heads"
    client.post(f"/auction/{listing['id']}/bid", data={"amount": 3}, headers=login(client, "222"))
    client.post(f"/auction/{listing['id']}/bid", data={"amount": 6}, headers=login(client, "333"))  # >= buyout: refused
    assert doc(client, "333")["super_fragments"] == 10
    client.post(f"/auction/{listing['id']}/buy", headers=login(client, "333"))
    assert doc(client, "222")["super_fragments"] == 10  # refunded
    assert doc(client, "333")["super_fragments"] == 4 and doc(client, "111")["super_fragments"] == 6
    assert [c["uuid"] for c in doc(client, "333")["storage_characters"]] == [lot["uuid"]]


def test_wonder_of_u_returns_its_wounds():
    from app.game.characterabilities import wonder_of_u
    wou = _stand(161)
    foes = [_stand(150), _stand(151)]
    hp = [f.current_hp for f in foes]
    wonder_of_u(wou, [wou], foes)
    plain = [h - f.current_hp for h, f in zip(hp, foes)]
    wou2, foes2 = _stand(161), [_stand(150), _stand(151)]
    wou2.current_hp = wou2.start_hp // 2
    lost = wou2.start_hp - wou2.current_hp
    wonder_of_u(wou2, [wou2], foes2)
    hurt = [h - f.current_hp for h, f in zip(hp, foes2)]
    assert all(b >= a + int(lost * 0.3) - 1 for a, b in zip(plain, hurt))


def test_wall_eyes_go_beyond_and_new_special_synergies():
    from app.game.characterabilities import paisley_park, soft_and_wet, emperor, crazy_diamond
    gappy, yasuho = _stand(137), _stand(138)
    target = _stand(150)
    target.current_speed = 999  # Go Beyond can't be dodged
    gappy._focus = target
    hp = target.current_hp
    _, msg = soft_and_wet(gappy, [gappy, yasuho], [target])
    assert "GO BEYOND" in msg and hp - target.current_hp >= int(gappy.current_damage * 1.8) - 1
    gappy.special_meter = 0
    _, msg = paisley_park(yasuho, [gappy, yasuho], [_stand(151)])
    assert gappy.as_special() and "Go Beyond is ready" in msg
    _, msg = emperor(_stand(14), [_stand(14), _stand(13)], [_stand(150)])
    assert "Emperor & Hanged Man" in msg
    josuke = _stand(32)
    josuke._focus = foe = _stand(150)
    _, msg = crazy_diamond(josuke, [josuke, _stand(34)], [foe])
    assert "Josuke & Okuyasu" in msg


def test_wiki_item_catalog_lists_every_source(client):
    from app.wiki import item_rows
    rows = {r["id"]: r for r in item_rows()}
    assert ("Crafting" in [w for w, _ in rows[46]["sources"]]) and rows[46]["ability"]
    assert {"Shop", "Daily reward", "Mirror World"} <= {w for w, _ in rows[1]["sources"]}
    assert "Gang raid" in {w for w, _ in rows[34]["sources"]}
    page = client.get("/wiki/items").data.decode()
    assert "Iggy&#39;s Collar" in page and "Where to get it" in page and "Gang raid" in page


def test_energy_regens_one_point_at_a_time_and_cans_bank_past_max():
    import datetime
    u = User(create_user("e"))
    step = logic.energy_interval(u)
    full = u.total_energy
    u.energy = full
    logic.spend_energy(u, 3)  # spending from a full bar starts the clock now
    assert u.energy == full - 3 and abs((logic.now() - u.last_full_energy).total_seconds()) < 5
    u.last_full_energy = logic.now() - step * 2 - datetime.timedelta(seconds=10)
    assert logic.refill_energy(u) and u.energy == full - 1  # two points, not the whole bar
    assert logic.energy_next_in(u) <= step and logic.energy_refill_in(u) <= step
    u.last_full_energy = logic.now() - step * 50
    logic.refill_energy(u)
    assert u.energy == full and logic.energy_refill_in(u) is None  # never past the max by regen
    with pytest.raises(logic.GameError):
        logic.spend_energy(User(dict(create_user("f"), energy=0)), 1)
    from app.game.items import item_from_dict
    u.items = [item_from_dict({"id": logic.ENERGY_CAN}) for _ in range(5)]
    res = logic.use_item(u, logic.ENERGY_CAN)
    assert res["kind"] == "energy" and u.energy == full + logic.ENERGY_CAN_AMOUNT  # banked past the max
    u.energy = full * logic.ENERGY_BANK
    with pytest.raises(logic.GameError):
        logic.use_item(u, logic.ENERGY_CAN)  # the bank is full; the can is given back
    assert sum(1 for i in u.items if i.id == logic.ENERGY_CAN) == 4


def test_energy_cans_drop_in_many_places():
    from app.wiki import item_rows
    can = next(r for r in item_rows() if r["id"] == 47)
    places = {w for w, _ in can["sources"]}
    assert {"Daily reward", "Daily streak", "Mirror World", "Tower", "Boss rush", "Gang raid", "Crusaders' Journey"} <= places
