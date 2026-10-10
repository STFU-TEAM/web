"""Part 10 · Carry Me: Joyce Joestar's story. Opens after the main story; Carry Me fights beside the team as a guest
in the form of a past JoJo's stand and is never saved."""
from app.game import carryme, story
from app.game.character import CHARACTER_FILE
from app.game.user import User, create_user
from test_app import char, client, doc, login, put  # noqa: F401  (client is a fixture)
from test_features import _ach_dust, player  # noqa: F401


def test_the_story_is_built_from_existing_stands_and_climbs():
    assert carryme.TOTAL == len(carryme.MULT) and carryme.STAGES[carryme.FINALE].get("finale")
    assert carryme.FINALE + 1 == carryme.FIRST_ENCORE and carryme.STAGES[-1].get("last")
    ids = {c["id"] for c in CHARACTER_FILE}
    for s in carryme.STAGES:
        assert s["form"] in ids and set(s["enemies"]) <= ids and s["text"]
        assert len(carryme.enemy_team(carryme.STAGES.index(s))) == len(s["enemies"])
    # evolutions happen on the act's boss: Star Platinum -> The World, Gold Experience -> Requiem, Tusk 1 -> 4
    forms = [s["form"] for s in carryme.STAGES]
    assert forms.index(31) > forms.index(1) and forms.index(84) > forms.index(59) and forms.index(114) > forms.index(111)
    rewards = [carryme.reward_for(k)["fragments"] for k in range(carryme.TOTAL)]  # the Encore pays more again
    assert rewards == sorted(rewards) and rewards[0] > story.reward_for(story.TOTAL - 1)["fragments"]
    assert carryme.resolve(User(create_user("1")))["word"] == "Hope"


def test_forms_are_remembered_and_only_those_can_be_chosen():
    u = User(create_user("1"))
    assert carryme.forms(u) == [4]                        # Hermit Purple, the first scene's form
    assert carryme.form_for(u, 0, 84) == 4                # can't borrow a form not yet remembered
    u.data["web_carry_me"] = {"cleared": carryme.FINALE}  # at the finale: every form is known
    assert set(carryme.forms(u)) >= {4, 1, 31, 32, 59, 84, 86, 111, 114, 137}
    assert carryme.form_for(u, carryme.FINALE, 84) == 84  # the finale: your choice
    assert carryme.form_for(u, 0, 84) == 84               # replays too
    assert carryme.form_for(u, carryme.FINALE, 999) == 137
    u.data["web_carry_me"] = {"cleared": carryme.FIRST_ENCORE}
    assert carryme.form_for(u, carryme.FIRST_ENCORE, 31) == 31  # the Encore: any form, every scene
    g = carryme.guest(84, carryme.FINALE)
    assert g.name == "Carry Me ｢Gold Experience Requiem｣" and g.level == 100 and g.guest


def test_joyce_opens_after_the_story_fights_beside_you_and_pays(client, monkeypatch):
    import app.db as dbmod
    # level 100 enemies could flatten the level 1 test stand before the test ends the fight: make them harmless
    monkeypatch.setattr(carryme, "MULT", [0.001] + carryme.MULT[1:])
    player(client, "111", fragments=0, super_fragments=0, energy=10, xp=500_000)  # past the level gates
    h = login(client, "111")
    d = doc(client, "111")
    d["main_characters"] = [char(1)]
    put(client, d)
    assert client.get("/carry-me").headers["Location"].endswith("/story")  # locked until the story is done
    client.post("/carry-me/fight", headers=h)
    assert client.fake.get("web:fight:111") is None

    d = doc(client, "111")
    d["web_story"] = {"cleared": story.TOTAL}
    put(client, d)
    client.fake.delete("web:story_cleared:111")
    page = client.get("/carry-me").data.decode()
    assert "Carry Me" in page and "The Callback" in page and "Resolve" in page and "Hermit purple" in page
    assert "/carry-me" in client.get("/story").data.decode()
    client.post("/carry-me/fight", data={"form": "84"}, headers=h)  # a form not remembered yet is ignored
    fight = dbmod.load_fight("111")
    assert fight.kind == "carry_me" and fight.meta == {"stage": 0, "form": 4}
    mine = fight.sides[0].chars
    assert len(mine) == 2 and mine[-1].name.startswith("Carry Me") and mine[-1].id == 4
    for c in fight.sides[1].chars:
        c.current_hp = 0
    dbmod.save_fight("111", fight)
    client.post("/carry-me/attack", data={"log_len": len(fight.log)}, headers=h)
    client.post("/carry-me/leave", headers=h)
    d = doc(client, "111")
    assert d["web_carry_me"]["cleared"] == 1 and d["fragments"] >= carryme.reward_for(0)["fragments"]
    assert len(d["main_characters"]) == 1 and all(c["id"] == 1 for c in d["main_characters"])  # the guest is never saved
    assert "Strength in Numbers" in client.get("/carry-me").data.decode()
    client.post("/carry-me/fight", data={"stage": 5}, headers=h)  # skipping ahead is refused
    assert client.fake.get("web:fight:111") is None


def test_the_encore_plays_under_over_heaven_rules_and_pays_its_title(client, monkeypatch):
    import app.db as dbmod
    monkeypatch.setattr(carryme, "MULT", carryme.MULT[:-1] + [0.001])  # they move first: keep the test stand standing
    from app.game import overheaven
    encore = carryme.STAGES[carryme.FIRST_ENCORE:]
    assert len(encore) == 4 and all(s["rules"] and set(s["rules"]) <= set(overheaven.RULE_TEXT) for s in encore)
    assert all(not s["rules"] for s in carryme.STAGES[:carryme.FIRST_ENCORE])
    last = carryme.reward_for(carryme.TOTAL - 1)
    assert last["super_fragments"] == 2 and carryme.REQUIEM_ARROW in last["items"]
    assert "Encore" in " ".join(carryme.reward_text(carryme.TOTAL - 1))
    player(client, "111", energy=10, xp=500_000)
    h = login(client, "111")
    d = doc(client, "111")
    d["main_characters"] = [char(1)]
    d["web_story"] = {"cleared": story.TOTAL}
    d["web_carry_me"] = {"cleared": carryme.TOTAL - 1}
    put(client, d)
    page = client.get("/carry-me").data.decode()
    assert "Over Heaven" in page and "Last bow" in page and "☁️" in page and 'name="form"' in page
    client.post("/carry-me/fight", data={"form": "31"}, headers=h)
    fight = dbmod.load_fight("111")
    assert fight.meta["form"] == 31 and fight.rules == carryme.STAGES[-1]["rules"]
    for c in fight.sides[1].chars:
        c.current_hp = 0
    dbmod.save_fight("111", fight)
    client.post("/carry-me/attack", data={"log_len": len(fight.log)}, headers=h)
    d = doc(client, "111")
    assert d["web_carry_me"]["cleared"] == carryme.TOTAL and "Encore" in d["web_titles"]


def test_level_gates_pace_each_part_but_never_strand_a_player_inside_one(client):
    from app.game import altverse, gates
    from app.game.logic import GameError
    import pytest
    u = User({**create_user("1"), "main_characters": [char(1)]})
    assert u.level < gates.STORY[4]
    p4 = next(k for k, s in enumerate(story.STAGES) if s["part"] == 4)
    u.data["web_story"] = {"cleared": p4}
    with pytest.raises(GameError, match="player level"):
        story.check_can_fight(u, p4)                     # Part 4's first stage asks for the level
    u.data["web_story"] = {"cleared": p4 + 1}
    story.check_can_fight(u, p4 + 1)                     # already inside the part: carry on
    story.check_can_fight(u, 0) if u.energy else None    # replays are never gated
    assert gates.story(u, p4)["level"] == gates.STORY[4] and gates.story(u, p4 + 1) is None
    key = altverse.CHAPTERS[0]["key"]
    assert gates.au(u, key, 0)["level"] == gates.AU[altverse.CHAPTERS[0]["after"]] and gates.au(u, key, 1) is None
    assert gates.carry_me(u, 0)["level"] == gates.CARRY_ME[0] and gates.carry_me(u, 1) is None
    assert gates.STORY[8] < gates.CARRY_ME[0] < gates.CARRY_ME[-1]  # the climb goes on after the story
    # the page shows the gate instead of the button
    player(client, "111", energy=10)
    login(client, "111")
    d = doc(client, "111")
    d["main_characters"] = [char(1)]
    d["web_story"] = {"cleared": p4}
    put(client, d)
    page = client.get("/story").data.decode()
    assert "opens at player level" in page and "level-gate" in page
