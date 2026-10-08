"""End-to-end tests against an in-memory Redis laid out like the bot's.
Run: pip install pytest fakeredis && pytest -q"""
import datetime
import pickle

import fakeredis
import pytest

import app.db as dbmod
from app.game import logic
from app.game.character import CHARACTER_FILE, get_character_from_template
from app.game.user import create_user


@pytest.fixture()
def client(monkeypatch):
    fake = fakeredis.FakeRedis()
    monkeypatch.setattr(dbmod.redis.Redis, "from_url", staticmethod(lambda *a, **k: fake))
    # every banner open, whatever the week: tests shouldn't depend on today's rotation
    monkeypatch.setattr(logic, "rotation_ids", lambda day: [b["id"] for b in logic.BANNERS])
    # the side modes and ranked open with the story (test_progression.py); other tests start from a fresh save
    from app.game import progression
    monkeypatch.setattr(progression, "GATES", {**progression.GATES, "wormhole": 0, "tower": 0, "dungeon": 0, "ranked": 0})
    from app import create_app
    app = create_app()
    app.config.update(TESTING=True, SESSION_COOKIE_SECURE=False)
    c = app.test_client()
    c.fake = fake
    return c


def login(c, uid="111", name="Jotaro"):
    with c.session_transaction() as s:
        s["uid"], s["name"], s["avatar"], s["csrf"] = uid, name, None, "tok"
    return {"X-CSRF-Token": "tok"}


def doc(c, uid):
    return pickle.loads(c.fake.hget("users", uid))


def put(c, d, field=None):
    c.fake.hset("users", field or d["_id"], pickle.dumps(d))


def char(cid, xp=0, awaken=0, items=None, types=("ATTACK",), quals=("GOOD",)):
    ch = get_character_from_template(CHARACTER_FILE[cid - 1], list(types), list(quals))
    d = ch.to_dict()
    d.update(xp=xp, awaken=awaken, items=items or [])
    return d


def test_public_pages(client):
    home = client.get("/")
    assert home.status_code == 200 and b"randomAsset/avatar.png" in home.data
    r = client.get("/stands?q=star&rarity=SSR", headers={"HX-Request": "true"})
    assert r.status_code == 200 and b"Star platinum" in r.data
    assert client.get("/stands/1").status_code == 200
    assert client.get("/stands/999").status_code == 404
    assert client.get("/leaderboard").status_code == 200


def test_wiki_pages(client):
    from app.wiki import TOPICS
    assert client.get("/wiki").status_code == 200
    for slug, *_ in TOPICS:
        assert client.get(f"/wiki/{slug}").status_code == 200, slug
    assert client.get("/wiki/nope").status_code == 404
    terrains = client.get("/wiki/terrains").data.decode()
    assert "Ocean" in terrains and "Dark blue moon" in terrains and "+20% speed" in terrains
    synergies = client.get("/wiki/synergies").data.decode()
    assert "Kira duo" in synergies and "Bombs two enemies" in synergies
    assert "No special uses this synergy yet." in synergies  # Morioh has no consumer
    stand = client.get("/stands/76").data.decode()  # Clash: sets Ocean, Squadra + duo
    assert "/wiki/terrains#ocean" in stand and "Clash + Talking Head" in stand
    manifest = client.get("/manifest.webmanifest")
    assert manifest.mimetype == "application/manifest+json" and manifest.json["display"] == "standalone"


def test_every_wired_synergy_has_wiki_text():
    from app.wiki import SYNERGY_EFFECTS, SYNERGY_USERS
    for name, ids in SYNERGY_USERS.items():
        missing = ids - set(SYNERGY_EFFECTS.get(name, {}))
        assert not missing, f"{name}: describe stands {sorted(missing)} in app/wiki.py"


def test_dodge_chance_is_capped_for_extreme_speed_gaps(monkeypatch):
    attacker = get_character_from_template(CHARACTER_FILE[0], ["ATTACK"], ["GOOD"])
    defender = get_character_from_template(CHARACTER_FILE[1], ["SPEED"], ["GOOD"])
    attacker.current_speed = 1
    defender.current_speed = 1000
    rolls = iter((100, 30))
    monkeypatch.setattr("app.game.character.random.randint", lambda _low, _high: next(rolls))

    result = attacker.attack(defender)

    assert result["dodged"] is False
    assert result["damage"] > 0


def test_second_human_side_targets_the_first_side():
    from app.game.fight import Fight, Side

    first = get_character_from_template(CHARACTER_FILE[0], ["ATTACK"], ["GOOD"])
    second = get_character_from_template(CHARACTER_FILE[1], ["SPEED"], ["GOOD"])
    first.current_speed = 1
    second.current_speed = 100
    fight = Fight(Side("First", [first], True), Side("Second", [second], True), kind="friend")

    assert fight.acting_side == 1
    assert fight.targets() == [0]


def test_admin_panel_mirrors_bot_permissions_and_audits_grants(client):
    assert "242367586233352193" in client.application.config["DISCORD_ADMIN_IDS"]
    client.application.config["DISCORD_ADMIN_IDS"] = {"111"}
    put(client, create_user("111"))
    put(client, create_user("222"))
    headers = login(client, "111")

    response = client.get("/admin?q=222", follow_redirects=True)
    assert response.status_code == 200 and b"Grant stand" in response.data and b"Edit a value" in response.data
    assert client.get("/admin").status_code == 200  # dashboard scan
    act = lambda op, **data: client.post(f"/admin/player/222/{op}", data=data, headers=headers)
    assert act("grant", kind="fragments", amount="500").status_code == 302
    assert doc(client, "222")["fragments"] == 500
    audit = client.fake.lrange("web:admin:audit", 0, -1)
    assert len(audit) == 1 and b'"actor": "111"' in audit[0]

    act("grant", kind="item", item_id="1", amount="2")
    assert doc(client, "222")["items"] == [{"id": 1}, {"id": 1}]
    act("grant_stand", stand_id="1", level="40", awaken="2")
    granted = doc(client, "222")["storage_characters"][-1]
    assert granted["id"] == 1 and granted["xp"] == 4000 and granted["awaken"] == 2
    act("supporter", days="30")
    assert doc(client, "222")["donor_status"] > datetime.datetime.now()
    act("grant", kind="fragments", amount="1000001")  # over the cap: refused
    assert doc(client, "222")["fragments"] == 500
    assert client.fake.llen("web:admin:audit") == 4

    act("set", field="pity", value="42")
    assert doc(client, "222")["pity"] == 42
    act("take_item", item_id="1", amount="1")
    assert doc(client, "222")["items"] == [{"id": 1}]
    act("stand_remove", uuid=granted["uuid"])
    assert all(s["uuid"] != granted["uuid"] for s in doc(client, "222")["storage_characters"])
    for page in ("/admin/gangs", "/admin/shops", "/admin/banners", "/admin/audit", "/admin/player/222/raw"):
        assert client.get(page).status_code == 200, page
    client.post("/admin/banners", data={"id": "0", "state": "0"}, headers=headers)
    assert client.post("/banners/0/pull", headers=headers).status_code in (200, 302)

    act("ban", reason="testing")
    with client.session_transaction() as session:
        session["uid"] = "222"
    assert client.get("/team").status_code == 403
    login(client, "111")
    act("ban")  # lift
    assert not client.fake.sismember("web:banned", "222")

    with client.session_transaction() as session:
        session["uid"] = "222"
    assert client.get("/admin").status_code == 403


def test_gang_and_shop_documents_use_bot_redis_hashes(client):
    gang = {"_id": "gang-1", "name": "Stardust", "users": ["111"], "ranks": {"111": 0}}
    shop = {"_id": "shop-1", "owner": "111", "name": "Joestar Market", "items": [{"id": 1}], "prices": [250]}
    db = dbmod.Database()

    db.create_gang(gang)
    db.create_shop(shop)

    assert db.get_gang("gang-1") == gang
    assert db.get_shop("shop-1") == shop
    assert list(db.all_gangs()) == [gang]
    assert list(db.all_shops()) == [shop]

    gang["war_elo"] = 10
    db.update_gang(gang)
    assert db.get_gang("gang-1")["war_elo"] == 10
    db.delete_gang("gang-1")
    assert db.get_gang("gang-1") is None


def test_user_unifies_legacy_storage_cases_without_losing_characters():
    data = create_user("storage-user")
    data["character_storage_1"] = [char(1), char(2)]
    data["pcharacter_storage_2"] = [char(3)]
    user = dbmod.User(data)

    assert [stand.id for stand in user.storage_characters] == [1, 2, 3]
    assert user.find_character_by_uuid(user.storage_characters[2].uuid)[0].id == 3
    user.storage_characters.append(get_character_from_template(CHARACTER_FILE[3], ["ATTACK"], ["GOOD"]))
    saved = user.to_dict()
    assert [stand["id"] for stand in saved["storage_characters"]] == [1, 2, 3, 4]


def test_storage_migration_is_idempotent_and_deduplicates_partial_runs():
    first, second = char(1), char(2)
    document = create_user("migration-user")
    document["storage_characters"] = [first]
    document["character_storage_1"] = [first, second]

    migrated, changed = dbmod.migrate_storage_document(document)
    again, changed_again = dbmod.migrate_storage_document(migrated)

    assert changed and not changed_again
    assert [stand["id"] for stand in migrated["storage_characters"]] == [1, 2]
    assert migrated["character_storage_1"] == []
    assert again == migrated


def test_gang_invite_and_join_flow(client):
    leader = create_user("111")
    leader["fragments"] = 20000
    put(client, leader)
    member = create_user("222")
    put(client, member)
    headers = login(client, "111")

    response = client.post("/gangs/create", data={"name": "Stardust", "motto": "Yare yare", "motd": "Welcome"}, headers=headers)
    assert response.status_code == 302
    gang_id = doc(client, "111")["gang_id"]
    assert doc(client, "111")["fragments"] == 10000
    assert client.get("/gangs").status_code == 200

    response = client.post("/gangs/invite", data={"user_id": "222"}, headers=headers)
    assert response.status_code == 302
    assert gang_id in doc(client, "222")["gang_invites"]

    with client.session_transaction() as session:
        session["uid"], session["name"] = "222", "Jotaro"
    response = client.post(f"/gangs/join/{gang_id}", headers=headers)
    assert response.status_code == 302
    assert doc(client, "222")["gang_id"] == gang_id
    assert set(map(str, dbmod.Database().get_gang(gang_id)["users"])) == {"111", "222"}


def test_player_shop_listing_and_purchase(client):
    owner = create_user("111")
    owner["fragments"] = 5000
    owner["items"] = [{"id": 1}]
    put(client, owner)
    buyer = create_user("222")
    buyer["fragments"] = 1000
    put(client, buyer)
    headers = login(client, "111")

    response = client.post("/shops/create", data={"name": "Joestar Market", "description": "Good finds"}, headers=headers)
    assert response.status_code == 302
    shop_id = doc(client, "111")["shop_id"]
    assert doc(client, "111")["fragments"] == 2000
    assert b"Joestar Market" in client.get("/shops").data

    client.post(f"/shops/{shop_id}/list", data={"item": "1", "price": "750"}, headers=headers)
    assert doc(client, "111")["items"] == []
    assert client.get(f"/shops/{shop_id}").status_code == 200

    with client.session_transaction() as session:
        session["uid"], session["name"] = "222", "Jotaro"
    response = client.post(f"/shops/{shop_id}/buy/0", headers=headers)
    assert response.status_code == 302
    assert doc(client, "222")["fragments"] == 250
    assert doc(client, "222")["items"] == [{"id": 1}]
    assert doc(client, "111")["fragments"] == 2750


def test_tower_entry_and_bot_invite(client):
    user = create_user("111")
    user["fragments"] = 1200
    user["main_characters"] = [char(1, xp=10000)]
    put(client, user)
    headers = login(client, "111")

    assert client.get("/tower").status_code == 200
    response = client.post("/tower/start", headers=headers)
    assert response.status_code == 302
    fight = dbmod.load_fight("111")
    assert fight.kind == "tower" and len(fight.sides[1].chars) == 2  # floor 1 is a two-stand warm-up
    assert doc(client, "111")["fragments"] == 700
    assert b"Your tower fight is active" in client.get("/mirror-world").data
    assert client.get("/wormhole").headers["Location"].endswith("/mirror-world")  # old links still land
    response = client.post("/mirror-world/attack", data={"target": "0"}, headers=headers)
    assert response.status_code == 409
    assert dbmod.load_fight("111").turn == fight.turn
    assert b"/randomAsset/avatar.png" in client.get("/stands/31").data

    client.application.config["DISCORD_CLIENT_ID"] = "123456"
    response = client.get("/auth/bot")
    assert response.status_code == 302
    assert "scope=bot+applications.commands" in response.headers["Location"]


def test_tower_victory_unlocks_next_floor(client):
    user = create_user("111")
    user["fragments"] = 1000
    user["main_characters"] = [char(1, xp=1000000, awaken=3, quals=("UNIVERSAL",)),
                               char(10, xp=1000000, awaken=3, quals=("UNIVERSAL",)),
                               char(31, xp=1000000, awaken=3, quals=("UNIVERSAL",))]
    put(client, user)
    headers = login(client, "111")
    client.post("/tower/start", headers=headers)

    for _ in range(200):
        fight = dbmod.load_fight("111")
        if fight.finished:
            break
        assert fight.awaiting_input
        response = client.post("/tower/attack", data={"target": fight.targets()[0], "log_len": len(fight.log)}, headers=headers)
        assert response.status_code == 200

    fight = dbmod.load_fight("111")
    assert fight.finished and fight.winner == 0
    saved = doc(client, "111")
    assert saved["web_tower"]["run"]["floor"] == 2 and saved["web_tower"]["best"] == 1
    assert saved["fragments"] > 500 and saved["tower_level"] >= 1
    # the same fighters climb on: their health carried over into the next floor
    client.post("/tower/leave", headers=headers)
    from app.game import tower
    team = tower.load_team(client.fake, "111")
    client.post("/tower/start", headers=headers)
    nxt = dbmod.load_fight("111")
    assert nxt.meta["floor"] == 2 and [c.uuid for c in nxt.sides[0].chars] == [c.uuid for c in team]
    assert b"Floor 2" in client.get("/tower").data


def test_dungeon_can_be_closed(client):
    client.application.config["DUNGEON_ENABLED"] = False
    player = create_user("555")
    player["main_characters"] = [char(1)]
    put(client, player)
    login(client, "555")
    r = client.get("/adventure/dungeon")
    assert r.status_code == 302 and r.headers["Location"].startswith("/battles")
    client.application.config["DUNGEON_ENABLED"] = True


def _walk_to(client, headers, uid, goal, avoid_fights=False):
    """Walk the day's map (breadth-first over open tiles) to goal; "fight" if a fight stopped the walk."""
    from collections import deque
    from app.game import dungeon
    run = doc(client, uid)["web_delve"]["run"]
    plan = dungeon.floor_plan(run["day"], run["depth"])
    start = tuple(run["pos"])
    blocked = {t for t, k in plan["events"].items() if k in dungeon.FIGHTS and t != goal} if avoid_fights else set()
    prev, queue = {start: None}, deque([start])
    while queue:
        t = queue.popleft()
        for d, (dx, dy) in dungeon.MOVES.items():
            n = (t[0] + dx, t[1] + dy)
            if n in plan["open"] and n not in prev and n not in blocked:
                prev[n] = (t, d)
                queue.append(n)
    if goal not in prev:
        return False
    steps, t = [], goal
    while prev[t]:
        t, d = prev[t]
        steps.append(d)
    for d in reversed(steps):
        client.post("/adventure/dungeon/move", data={"direction": d}, headers=headers)
        fight = dbmod.load_fight(uid)
        if fight and not fight.finished:
            return "fight"
    return True


def _win_dungeon_fight(client, headers, uid):
    fight = dbmod.load_fight(uid)
    for c in fight.sides[1].chars:
        c.current_hp = 0
    dbmod.save_fight(uid, fight)
    client.post("/adventure/dungeon/attack", headers=headers)
    client.post("/adventure/dungeon/leave", headers=headers)


def test_dungeon_is_free_daily_and_blocks_walls(client):
    user = create_user("444")
    user["energy"] = 0
    user["fragments"] = 0
    user["main_characters"] = [char(1, xp=10000)]
    put(client, user)
    headers = login(client, "444")

    page = client.get("/adventure/dungeon")
    assert page.status_code == 200 and b"Enter the dungeon" in page.data
    assert client.post("/adventure/dungeon/start", headers=headers).status_code == 302
    saved = doc(client, "444")
    run = saved["web_delve"]["run"]
    assert saved["energy"] == 0 and saved["fragments"] == 0  # costs nothing
    assert run["depth"] == 1 and run["pos"] == [0, 0] and saved["web_delve"]["runs"] == 1

    client.post("/adventure/dungeon/move", data={"direction": "up"}, headers=headers)  # off the map
    assert doc(client, "444")["web_delve"]["run"]["pos"] == [0, 0]
    assert b"Loot bag" in client.get("/adventure/dungeon").data

    # one run a day: giving up keeps half the bag and closes the door until tomorrow
    client.post("/adventure/dungeon/giveup", headers=headers)
    saved = doc(client, "444")
    assert saved["web_delve"]["run"] is None and saved["web_delve"]["last"]["how"] == "lost"
    client.post("/adventure/dungeon/start", headers=headers)
    assert doc(client, "444")["web_delve"]["run"] is None
    assert b"been down today" in client.get("/adventure/dungeon").data


def test_dungeon_floor_plans_are_daily_and_reachable():
    from collections import deque
    from app.game import dungeon
    for day in ("2026-10-05", "2026-10-06", "2027-01-01"):
        for depth in range(1, dungeon.DEPTHS + 1):
            plan = dungeon.floor_plan(day, depth)
            seen, queue = {dungeon.START}, deque([dungeon.START])
            while queue:
                t = queue.popleft()
                for dx, dy in dungeon.MOVES.values():
                    n = (t[0] + dx, t[1] + dy)
                    if n in plan["open"] and n not in seen:
                        seen.add(n)
                        queue.append(n)
            assert set(plan["events"]) <= seen and plan["stairs"] in seen
            assert plan["events"][plan["stairs"]] == ("boss" if depth == dungeon.DEPTHS else "stairs")
            assert sum(k == "chest" for k in plan["events"].values()) == 3
    assert dungeon.floor_plan("2026-10-05", 1) != dungeon.floor_plan("2026-10-06", 1)


def test_dungeon_fight_fills_the_bag_and_stairs_cash_out(client):
    from app.game import dungeon
    user = create_user("555")
    user["main_characters"] = [char(1, xp=1000000, awaken=3, quals=("UNIVERSAL",)),
                               char(10, xp=1000000, awaken=3, quals=("UNIVERSAL",)),
                               char(31, xp=1000000, awaken=3, quals=("UNIVERSAL",))]
    put(client, user)
    headers = login(client, "555")
    client.post("/adventure/dungeon/start", headers=headers)
    run = doc(client, "555")["web_delve"]["run"]
    plan = dungeon.floor_plan(run["day"], 1)

    # step on a monster tile: a fight starts, and the team keeps its wounds afterwards
    target = next(t for t, k in sorted(plan["events"].items())
                  if k in dungeon.FIGHTS and _walk_to(client, headers, "555", t, avoid_fights=True))
    assert dbmod.load_fight("555").kind == "dungeon"
    fight = dbmod.load_fight("555")
    assert fight.kind == "dungeon" and len(fight.sides[1].chars) == 3
    assert b"Dungeon" in client.get("/adventure/dungeon").data
    fight.sides[0].chars[0].current_hp = fight.sides[0].chars[0].start_hp // 2
    dbmod.save_fight("555", fight)
    _win_dungeon_fight(client, headers, "555")
    saved = doc(client, "555")
    run = saved["web_delve"]["run"]
    assert f"{target[0]}:{target[1]}" in run["done"] and run["bag"]["fragments"] > 0
    team = dungeon.load_team(client.fake, "555")
    assert team[0].current_hp < team[0].start_hp

    # the stairs: take the bag home in full
    before = saved["fragments"]
    while (walked := _walk_to(client, headers, "555", plan["stairs"])) == "fight":
        _win_dungeon_fight(client, headers, "555")
    assert walked is True
    bag = doc(client, "555")["web_delve"]["run"]["bag"]["fragments"]
    client.post("/adventure/dungeon/cashout", headers=headers)
    saved = doc(client, "555")
    assert saved["web_delve"]["run"] is None and saved["web_delve"]["last"]["how"] == "left"
    assert saved["fragments"] == before + bag and saved["web_dungeon_completions"] == 1


def test_dungeon_loss_keeps_half_the_bag(client):
    from app.game import dungeon
    user = create_user("556")
    user["main_characters"] = [char(1, xp=10000)]
    put(client, user)
    headers = login(client, "556")
    client.post("/adventure/dungeon/start", headers=headers)
    saved = doc(client, "556")
    saved["web_delve"]["run"]["bag"] = {"fragments": 1000, "items": [38, 39]}
    put(client, saved)
    run = saved["web_delve"]["run"]
    plan = dungeon.floor_plan(run["day"], 1)
    target = next(t for t, k in sorted(plan["events"].items())
                  if k in dungeon.FIGHTS and _walk_to(client, headers, "556", t, avoid_fights=True))
    assert dbmod.load_fight("556").kind == "dungeon"
    before = doc(client, "556")["fragments"]
    client.post("/adventure/dungeon/attack", data={"forfeit": "1"}, headers=headers)
    saved = doc(client, "556")
    assert saved["web_delve"]["run"] is None and saved["fragments"] == before + 500
    assert [i["id"] for i in saved["items"]][-1:] == [38]


def test_battle_modes_dummy_friend_and_ranked_share_fight_state(client):
    first = create_user("111")
    first["main_characters"] = [char(1, xp=100000)]
    second = create_user("222")
    second["main_characters"] = [char(2, xp=100000)]
    put(client, first)
    put(client, second)
    headers = login(client, "111")

    assert client.get("/battles?mode=dummy").status_code == 200
    client.post("/battles/dummy/start", headers=headers)
    dummy_fight = dbmod.load_fight("111")
    assert dummy_fight.kind == "dummy" and dummy_fight.sides[1].name == "Training Dummy"
    assert b"Practice Dummy" in client.get("/battles?mode=dummy").data
    dummy_fight.forfeit()
    dbmod.save_fight("111", dummy_fight)
    client.post("/battles/leave", headers=headers)

    client.post("/battles/friends/invite", data={"user_id": "222"}, headers=headers)
    inbox = client.fake.smembers("web:friend:inbox:222")
    assert len(inbox) == 1
    challenge_id = inbox.pop().decode()
    with client.session_transaction() as session:
        session["uid"], session["name"] = "222", "Player Two"
    client.post(f"/battles/friends/accept/{challenge_id}", headers=headers)
    first_fight = dbmod.load_fight("111")
    second_fight = dbmod.load_fight("222")
    assert first_fight.kind == "friend" and second_fight.id == first_fight.id
    assert first_fight.meta["players"] == ["111", "222"]
    friend_page = client.get("/battles?mode=friends")
    assert friend_page.status_code == 200 and b"Friendly Duel" in friend_page.data
    assert b"is choosing a target" in friend_page.data or b"Pick a target" in friend_page.data

    dbmod.clear_fight("111")
    dbmod.clear_fight("222")
    # ranked: a roster of 5 different stands each, then ban 2 and order the 3 left
    from app.game import draft as D
    for uid, ids in (("111", (1, 2, 3, 4, 5)), ("222", (6, 7, 8, 9, 10))):
        doc_ = create_user(uid)
        doc_["storage_characters"] = [char(i, xp=100000) for i in ids]
        put(client, doc_)
        with client.session_transaction() as session:
            session["uid"], session["name"] = uid, uid
        client.post("/battles/ranked/roster", data={"uuid": [c["uuid"] for c in doc_["storage_characters"]]}, headers=headers)
    with client.session_transaction() as session:
        session["uid"], session["name"] = "111", "Jotaro"
    client.post("/battles/ranked/queue", headers=headers)
    with client.session_transaction() as session:
        session["uid"], session["name"] = "222", "Player Two"
    client.post("/battles/ranked/queue", headers=headers)
    draft = D.of(client.fake, "111")
    assert draft and draft["phase"] == "ban" and dbmod.load_fight("111") is None
    assert b"Ban 2 of their stands" in client.get("/battles?mode=ranked").data
    for uid in ("111", "222"):
        with client.session_transaction() as session:
            session["uid"] = uid
        foe = D.opponent(draft, uid)
        client.post("/battles/ranked/ban", data={"ban": draft["rosters"][foe][:2]}, headers=headers)
    draft = D.of(client.fake, "111")
    assert draft["phase"] == "compose" and draft["bans"]["111"] == draft["rosters"]["222"][:2]
    for uid in ("111", "222"):
        with client.session_transaction() as session:
            session["uid"] = uid
        left = D.remaining(draft, uid)[::-1]  # lock in the reverse order
        client.post("/battles/ranked/compose", data={f"slot{i}": u for i, u in enumerate(left)}, headers=headers)
    ranked = dbmod.load_fight("111")
    teams = {p: [c.id for c in side.chars] for p, side in zip(ranked.meta["players"], ranked.sides)}
    assert teams == {"111": [5, 4, 3], "222": [10, 9, 8]}  # each banned the other's first 2, then reversed the rest
    assert D.of(client.fake, "111") is None
    assert ranked.kind == "ranked"
    assert dbmod.load_fight("222").id == ranked.id
    ranked.sides[1].chars[0].current_hp = 0
    ranked._finish()
    winner_id = ranked.meta["players"][0]
    loser_id = ranked.meta["players"][1]
    dbmod.save_fight("111", ranked)
    dbmod.save_fight("222", ranked)
    with client.session_transaction() as session:
        session["uid"] = "111"
    client.post("/battles/attack", data={"log_len": len(ranked.log)}, headers=headers)
    client.post("/battles/attack", data={"log_len": len(ranked.log)}, headers=headers)
    assert doc(client, winner_id)["global_elo"] == 25
    assert doc(client, loser_id)["global_elo"] == 0


def test_begin_pull_and_team(client):
    h = login(client)
    assert client.get("/team").headers["Location"].endswith("/auth/welcome")
    r = client.post("/auth/welcome", headers=h)
    assert r.headers["Location"].startswith("/banners")
    d = doc(client, "111")
    assert d["super_fragments"] == 1 and d["main_characters"] == []

    assert client.get("/banners").status_code == 200
    r = client.post("/banners/0/pull", headers=h)
    assert r.status_code == 200 and b"10 stands" in r.data, r.data[:500]
    assert b"randomAsset/avatar.png" in r.data
    assert b"media.tenor.com" not in r.data
    assert b"/opening/" in r.data
    d = doc(client, "111")
    # an empty team takes the three rarest stands of the pull; the rest go to storage
    from app.game.achievements import ACHIEVEMENT_BY_ID  # a 9-R pull pays Bad Luck Brian's Arrowhead
    heads = sum(ACHIEVEMENT_BY_ID[a]["reward"]["super_fragments"] for a in d["achievement_data"]["unlocked"])
    assert d["super_fragments"] == heads and len(d["main_characters"]) == 3 and len(d["storage_characters"]) == 7
    rank = {"R": 0, "SR": 1, "SSR": 2, "UR": 3, "LR": 4}
    team_rank = sorted(rank[CHARACTER_FILE[c["id"] - 1]["rarity"]] for c in d["main_characters"])
    rest_rank = [rank[CHARACTER_FILE[c["id"] - 1]["rarity"]] for c in d["storage_characters"]]
    assert team_rank[0] >= max(rest_rank)
    # pity counts pulls since the last UR or LR (an SSR doesn't reset it)
    rarities = [CHARACTER_FILE[i - 1]["rarity"] for i in d["web_pull_history"][0]["ids"]]
    since = next((i for i, r in enumerate(reversed(rarities)) if r in ("UR", "LR")), len(rarities))
    assert d["pity"] == since
    # second pull refused (spend any Arrowhead Bad Luck Brian paid first)
    d["super_fragments"] = 0
    put(client, d)
    assert b"costs 1 Arrowhead" in client.post("/banners/0/pull", headers=h).data
    d = doc(client, "111")
    for c in d["main_characters"]:  # empty the team to test moving stands in by hand
        client.post("/team/store", data={"uuid": c["uuid"]}, headers=h)
    d = doc(client, "111")
    assert d["main_characters"] == [] and len(d["storage_characters"]) == 10

    # move 3 into the team, swap a 4th in
    ids = [c["uuid"] for c in d["storage_characters"]]
    for u in ids[:3]:
        assert b"joined your team" in client.post("/team/main", data={"uuid": u}, headers=h).data
    r = client.post("/team/main", data={"uuid": ids[3], "swap": ids[0]}, headers=h)
    assert b"joined your team" in r.data
    d = doc(client, "111")
    assert [c["uuid"] for c in d["main_characters"]] == ids[1:4]

    # preset save / load
    assert b"saved" in client.post("/team/preset/save", data={"name": "Main"}, headers=h).data
    client.post("/team/store", data={"uuid": ids[1]}, headers=h)
    assert len(doc(client, "111")["main_characters"]) == 2
    assert b"loaded" in client.post("/team/preset/load", data={"name": "main"}, headers=h).data
    assert [c["uuid"] for c in doc(client, "111")["main_characters"]] == ids[1:4]

    # release
    assert b"was released" in client.post("/team/release", data={"uuid": ids[5]}, headers=h).data
    assert client.get("/team").status_code == 200
    assert client.get("/team/collection").status_code == 200
    # daily + cooldown
    assert b"Claimed" in client.post("/daily", headers=h).data
    assert b"back in" in client.post("/daily", headers=h).data.lower()
    # quests page assigns quests and daily_claim progressed
    assert client.get("/quests").status_code == 200
    assert doc(client, "111")["quests"]["active_daily"]
    # csrf
    assert client.post("/daily").status_code == 400


def test_wormhole_fight(client):
    h = login(client, "222", "Dio")
    d = create_user("222")
    d["main_characters"] = [char(1, xp=5000), char(10, xp=5000), char(59, xp=5000)]
    put(client, d)
    assert client.post("/mirror-world/start", headers=h).status_code == 302
    assert client.get("/mirror-world").status_code == 200
    fight = dbmod.load_fight("222")
    for _ in range(400):
        fight = dbmod.load_fight("222")
        if fight.finished:
            break
        r = client.post("/mirror-world/attack", data={"target": fight.targets()[0], "log_len": len(fight.log)}, headers=h)
        assert r.status_code == 200
    assert fight.finished and fight.rewards is not None
    d = doc(client, "222")
    assert d["energy"] == 9
    assert d["achievement_data"]["counters"].get("wormhole_complete") == 1
    client.post("/mirror-world/leave", headers=h)
    client.post("/mirror-world/start", headers=h)
    assert b"opens again" in client.get("/mirror-world").data


def test_legacy_bytes_key_user_items_shop(client):
    """A very old player stored under b'<id>' with fields missing, like the bot's data."""
    d = create_user("b'333'")
    for k in ("achievement_data", "quests", "story_progress", "teams"):
        d.pop(k)
    d["main_characters"] = [char(6, xp=100 * 100, awaken=2)]  # Silver Chariot lvl 100 awaken 2 -> requiem
    d["character_storage_1"] = [char(1), char(1, types=("LUCK",))]
    d["items"] = [{"id": 3}, {"id": 13}, {"id": 4}, {"id": 34}, {"id": 35}, {"id": 36}]
    d["fragments"] = 20000
    d["last_full_energy"] = datetime.datetime.min
    put(client, d)
    h = login(client, "333")
    assert client.get("/team").status_code == 200
    assert b"The bag held" in client.post("/items/use", data={"item": 13}, headers=h).data
    after = doc(client, "b'333'")                      # written back under the bot's field
    assert after["fragments"] > 20000 and not client.fake.hexists("users", "333")
    assert b"equipped" in client.post("/team/equip", data={"uuid": after["main_characters"][0]["uuid"], "item": 4}, headers=h).data
    r = client.post("/items/use", data={"item": 3, "uuid": after["main_characters"][0]["uuid"]}, headers=h)
    assert b"Requiem" in r.data
    assert doc(client, "b'333'")["main_characters"][0]["id"] == 83  # Chariot Requiem
    assert b"You crafted Holy Corpse" in client.post("/items/craft", data={"recipe": "Holy Corpse"}, headers=h).data
    assert b"You bought Arrowhead" in client.post("/shop/buy", data={"key": "super_fragment"}, headers=h).data
    # fuse the two Star Platinum copies
    s1 = doc(client, "b'333'")["storage_characters"]
    r = client.post("/team/fuse", data={"uuid": s1[0]["uuid"], "fodder": s1[1]["uuid"]}, headers=h)
    assert b"Fused" in r.data
    s1 = doc(client, "b'333'")["storage_characters"]
    assert len(s1) == 1 and s1[0]["awaken"] == 0 and s1[0]["xp"] == logic.FUSE_BONUS_XP["SSR"]  # SSR bonus; ★1 waits for Lv 20
    # reforge: priced by rarity, the player compares and picks
    frag = doc(client, "b'333'")["fragments"]
    uid0 = doc(client, "b'333'")["main_characters"][0]["uuid"]
    assert client.get("/reforge?uuid=" + uid0).status_code == 200
    r = client.post("/reforge/roll", data={"uuid": uid0}, headers=h)
    assert b"Keep the new roll" in r.data and b"forge-pairs spin" in r.data
    assert doc(client, "b'333'")["fragments"] == frag - logic.REFORGE_PRICE["UR"]  # Chariot Requiem is UR
    assert b"keeps its old roll" in client.post("/reforge/keep", data={"keep": "old"}, headers=h).data
    # energy refilled on page load (last_full_energy was long ago)
    client.get("/mirror-world")
    assert doc(client, "b'333'")["energy"] == 10
    assert client.get("/u/333").status_code == 200
    assert client.get("/leaderboard?by=xp").status_code == 200
