"""Team planner: any stand at any build, owned copies as they are, the review (synergies, near misses) and simulation."""
from app.game import planner
from app.game.user import User, create_user
from test_app import char, client, login, put  # noqa: F401  (client is a fixture)


def _player(c, uid="111", **fields):
    d = create_user(uid)
    d.update(fields)
    put(c, d)
    return login(c, uid)


def test_build_follows_level_stars_type_and_quality():
    lo = planner.build({"pick": "s:1", "level": 10, "awaken": 0, "type": "ATTACK", "quality": "none"}, None)
    hi = planner.build({"pick": "s:1", "level": 100, "awaken": 3, "type": "ATTACK", "quality": "perfect"}, None)
    good = planner.build({"pick": "s:1", "level": 100, "awaken": 3, "type": "ATTACK", "quality": "good"}, None)
    assert lo.types == [] and hi.types == ["ATTACK"] and hi.qualities == ["UNIVERSAL"] and good.qualities == ["GOOD"]
    assert lo.start_damage < good.start_damage < hi.start_damage and hi.level == 100 and hi.awaken == 3
    assert planner.build({"pick": "s:164", "level": 1, "awaken": 0, "type": None, "quality": "good"}, None) is None  # dummy
    assert planner.build({"pick": "s:9999", "level": 1, "awaken": 0, "type": None, "quality": "good"}, None) is None
    slot = {"pick": "s:1", "level": 50, "awaken": 0, "type": None, "quality": "perfect"}
    planner.build(slot, None)
    assert slot["type"] == planner.best_type(1)  # no type picked: the one that powers its special


def test_parse_clamps_and_defaults_to_the_players_team():
    user = User({**create_user("1"), "main_characters": [char(1, xp=4200, awaken=2)]})
    slots = planner.parse({}, user)
    assert slots[0]["pick"].startswith("u:") and slots[1] is None
    assert planner.parse({"blank": "1"}, user) == [None, None, None]
    s = planner.parse({"p0": "s:5", "l0": "500", "a0": "-3", "q0": "weird", "t0": "NOPE"}, user)[0]
    assert (s["level"], s["awaken"], s["quality"], s["type"]) == (100, 0, "perfect", None)


def test_review_lights_synergies_and_names_near_misses():
    crew = [planner.build({"pick": f"s:{i}", "level": 80, "awaken": 2, "type": None, "quality": "good"}, None) for i in (1, 2)]
    rev = planner.review(crew + [None])
    assert not rev["empty"] and rev["count"] == 2
    keys = {g["key"] for g in rev["synergies"]}
    assert "crusaders" in keys
    star = rev["stands"][0]
    assert star["after"]["damage"] > star["before"]["damage"] and star["gain"]["damage"] > 0
    assert any(g["label"].startswith("Part 3") for g in rev["near"])  # a third Part 3 stand would light it
    assert planner.review([None, None, None])["empty"]


def test_planner_page_review_and_simulation(client):
    mine = char(6, xp=9000, awaken=3)
    mine["chips"] = [{"id": "c1", "syn": "crusaders", "tier": "epic", "stats": [["damage_pct", 0.2]]}]
    h = _player(client, main_characters=[mine], energy=10)
    page = client.get("/battles/planner").data.decode()
    assert "Team planner" in page and "Silver chariot" in page and "1 chip" in page  # starts from my team, as it is
    q = "p0=s:1&l0=90&a0=3&q0=perfect&t0=LUCK&p1=s:2&l1=90&a1=3&q1=good&t1=ATTACK&blank=1"
    part = client.get(f"/battles/planner/review?{q}", headers={"HX-Request": "true"}).data.decode()
    assert 'id="plan-review"' in part and "Stardust Crusaders" in part and "data-share=" in part and "p0=s%3A1" in part
    res = client.post("/battles/planner/simulate", data={"p0": "s:1", "l0": "100", "a0": "5", "q0": "perfect", "blank": "1",
                                                        "vs": "story:0"}, headers=h).data.decode()
    assert "win rate" in res and "Your plan" in res
    assert "Put at least one stand" in client.post("/battles/planner/simulate", data={"blank": "1", "vs": "story:0"},
                                                    headers=h).data.decode()



def test_items_and_the_taunt_toggle():
    from werkzeug.datastructures import MultiDict
    args = MultiDict([("p0", "s:1"), ("l0", "100"), ("a0", "3"), ("q0", "perfect"), ("t0", "ATTACK"),
                      ("i0", "1"), ("i0", "42"), ("i0", "33"), ("i0", "1"), ("k0", "1"), ("blank", "1")])
    slot = planner.parse(args, None)[0]
    assert slot["items"] == [1, 42, 1] and slot["taunt"] is True  # the raid singularity (33) isn't offered
    built = planner.build(slot, None)
    bare = planner.build({**slot, "items": [], "taunt": None}, None)
    assert built.taunt and not bare.taunt and len(built.items) == 3
    assert built.start_damage > bare.start_damage and built.start_armor > bare.start_armor  # taunt adds armor
    off = planner.build({**slot, "pick": "s:5", "taunt": False}, None)  # The Fool taunts on its own: switched off
    assert not off.taunt
    q = planner.query([slot, None, None])
    assert q["i0"] == [1, 42, 1] and q["k0"] == "1"


def test_pickers_on_training_and_ranked(client):
    from app.game import altverse, story
    d = create_user("111")
    d.update(main_characters=[char(1, xp=5000)], storage_characters=[char(i, xp=3000) for i in (2, 3, 4, 5)],
             web_story={"cleared": story.TOTAL},
             web_au={"cleared": {c["key"]: len(c["stages"]) for c in altverse.CHAPTERS}})
    put(client, d)
    login(client, "111")
    training = client.get("/training").data.decode()
    assert 'data-sp-source="#sp-train"' in training and 'id="sp-train"' in training and 'data-sp-max="3"' in training
    ranked = client.get("/battles?mode=ranked").data.decode()
    assert 'data-sp-source="#sp-roster"' in ranked and "data-sp-unique" in ranked
    planner_page = client.get("/battles/planner").data.decode()
    assert 'id="sp-planner"' in planner_page and 'id="sp-items"' in planner_page and 'name="k0"' in planner_page



def test_suggestions_fill_the_last_slot():
    user = User({**create_user("1"), "main_characters": [char(1, xp=9000, awaken=2)],
                 "storage_characters": [char(4, xp=8000), char(4, xp=100), char(29, xp=9000), char(110, xp=9000)]})
    slots = [{"pick": f"u:{user.main_characters[0].uuid}"}, {"pick": "s:2", "level": 90, "awaken": 2, "type": None,
                                                          "quality": "perfect", "items": []}, None]
    chars = [planner.build(s, user) for s in slots]
    sug = planner.suggest(chars, user, slots)
    assert sug["slot"] == 2 and sug["level"] == 90 and sug["awaken"] == 2  # the team average (Lv 90 and Lv 90)
    mine = {x["name"]: x for x in sug["mine"]}
    assert "Hermit purple" in mine and mine["Hermit purple"]["level"] == 80  # the better copy of the two
    assert any("Joestar" in w for w in mine["Hermit purple"]["why"])
    assert all(x["id"] not in (1, 2, 110) for x in sug["mine"] + sug["any"])  # not in the team, never the raid boss
    gains = [x["gain"] for x in sug["any"]]
    assert gains == sorted(gains, reverse=True) and len(sug["any"]) == planner.SUGGEST
    assert planner.suggest(chars[:1] + [None, None], user, slots) is None  # only with one slot left
    assert planner.suggest(chars[:2] + [chars[0]], user, slots) is None


def test_review_shows_suggestions(client):
    _player(client, main_characters=[char(1, xp=9000)], storage_characters=[char(4, xp=8000)])
    part = client.get("/battles/planner/review?p0=s:1&p1=s:2&blank=1", headers={"HX-Request": "true"}).data.decode()
    assert "Suggestions for stand 3" in part and 'data-suggest-slot="2"' in part and "Hermit purple" in part


def test_owned_copy_tries_other_items_and_the_team_page_plans_it(client):
    from werkzeug.datastructures import MultiDict
    mine = char(6, xp=9000, awaken=3)
    mine["items"] = [{"id": 1}]
    _player(client, main_characters=[mine], energy=10)
    from test_app import doc
    user = User(doc(client, "111"))
    uuid = user.main_characters[0].uuid
    kept = planner.parse(MultiDict([("p0", f"u:{uuid}"), ("blank", "1")]), user)[0]
    as_is = planner.build(kept, user)
    assert [it.id for it in as_is.items] == [1] and kept["over_items"] == [1]  # the switch starts from its gear
    args = MultiDict([("p0", f"u:{uuid}"), ("ox0", "1"), ("o0", "42"), ("o0", "1"), ("or0", "9"), ("blank", "1")])
    slot = planner.parse(args, user)[0]
    assert slot["override"] and slot["over_items"] == [42, 1] and slot["over_refine"] == planner.REFINE_MAX
    other = planner.build(slot, user)
    assert [it.id for it in other.items] == [42, 1] and other.level == as_is.level and other.awaken == as_is.awaken
    assert user.main_characters[0].items[0].id == 1  # the save isn't touched
    q = planner.query([slot, None, None])
    assert q["ox0"] == "1" and q["o0"] == [42, 1] and q["or0"] == planner.REFINE_MAX
    refined = planner.parse(MultiDict([("p0", "s:1"), ("i0", "42"), ("r0", "3"), ("blank", "1")]), None)[0]
    assert refined["refine"] == 3 and planner.query([refined, None, None])["r0"] == 3
    assert planner.build(refined, None).start_damage >= planner.build({**refined, "refine": 0}, None).start_damage
    page = client.get("/team").data.decode()
    assert "Plan this team" in page and f"p0=u:{uuid}" in page


def test_the_same_item_can_be_planned_more_than_once(client):
    _player(client, main_characters=[char(6)], energy=10)
    page = client.get("/battles/planner").data.decode()
    assert page.count("data-sp-repeat") >= 2 * planner.SLOTS  # build items and an owned copy's items, per slot
    part = client.get("/battles/planner/review?p0=s:1&l0=100&a0=3&q0=perfect&t0=ATTACK&i0=42&i0=42&i0=42&blank=1",
                      headers={"HX-Request": "true"}).data.decode()
    assert "i0=42&amp;i0=42&amp;i0=42" in part or "i0=42&i0=42&i0=42" in part  # kept in the share link


def test_refine_on_an_owned_copy_without_picking_items_refines_its_own():
    from werkzeug.datastructures import MultiDict
    mine = char(6)
    mine["items"] = [{"id": 42, "refine": 1}]
    u = User({**create_user("1"), "main_characters": [mine]})
    uuid = u.main_characters[0].uuid
    plain = planner.build(planner.parse(MultiDict([("p0", f"u:{uuid}"), ("blank", "1")]), u)[0], u)
    tuned = planner.build(planner.parse(MultiDict([("p0", f"u:{uuid}"), ("ox0", "1"), ("or0", "5"), ("blank", "1")]), u)[0], u)
    assert [(i.id, i.refine) for i in plain.items] == [(42, 1)] and [(i.id, i.refine) for i in tuned.items] == [(42, 5)]
    assert tuned.start_damage > plain.start_damage
