"""Smoother progression: Stand Discs (release → copies), the Weekly Road, mid-game Requiem Arrows, the story finale,
the fight advice line and the guided paths after the Beginner's path."""
from app.game import advice, altverse, logic, story, weekly
from app.game.character import CHARACTER_FILE
from app.game.gangs import week_key
from app.game.user import User
from test_app import char, client, doc, login, put  # noqa: F401  (client is a fixture)
from test_features import player  # noqa: E402


def test_releasing_pays_discs_and_a_starred_stand_refunds_its_copies(client):
    r_stand, ssr_two = char(4), char(1, xp=6000, awaken=2)  # Hermit Purple (R); Star Platinum (SSR) ★2: 2 copies spent
    player(client, "111", storage_characters=[r_stand, ssr_two])
    h = login(client, "111")
    r = client.post("/team/release", data={"uuid": [r_stand["uuid"], ssr_two["uuid"]]}, headers=h)
    assert b"Stand Discs" in r.data
    assert doc(client, "111")["web_discs"] == logic.DISC_VALUE["R"] + logic.DISC_VALUE["SSR"] * 3


def test_discs_buy_a_fresh_copy_of_a_banner_stand_you_own(client):
    keeper = char(1, xp=3000)
    player(client, "111", main_characters=[keeper], web_discs=logic.DISC_PRICE["SSR"] + 5)
    h = login(client, "111")
    panel = client.get(f"/team/stand/{keeper['uuid']}", headers=h).data.decode()
    assert "💿 Copy · 120" in panel and "Release ·" not in panel  # team stands can't be released
    client.post("/team/buy-copy", data={"uuid": keeper["uuid"]}, headers=h)
    d = doc(client, "111")
    assert d["web_discs"] == 5 and [c["id"] for c in d["storage_characters"]] == [1]
    copy = d["storage_characters"][0]
    assert copy["uuid"] != keeper["uuid"] and copy.get("awaken", 0) == 0
    assert b"costs 120 Stand Discs" in client.post("/team/buy-copy", data={"uuid": keeper["uuid"]}, headers=h).data
    in_banner = {c for b in logic.BANNERS for c in b["cards"]}
    outside = next(c["id"] for c in CHARACTER_FILE if c["id"] not in in_banner)
    assert logic.disc_price(outside) is None


def test_the_weekly_road_counts_play_and_pays_its_tiers_every_week(client):
    player(client, "111", web_road={"week": week_key(), "points": 70, "claimed": []})
    h = login(client, "111")
    page = client.get("/quests").data.decode()
    assert "70 points this week" in page and "Claim 2" in page
    before = doc(client, "111")
    client.post("/road/claim", headers=h)
    d = doc(client, "111")
    assert d["web_road"]["claimed"] == [0, 1] and d["fragments"] == before["fragments"] + weekly.TIERS[0][1]["fragments"]
    assert [i["id"] for i in d["items"]].count(2) == [i["id"] for i in before["items"]].count(2) + 1
    assert "Nothing to claim" in client.post("/road/claim", headers=h, follow_redirects=True).data.decode()
    u = User(d)
    logic.track_quest_progress(u, "daily_claim")
    logic.track_quest_progress(u, "fight_win")
    assert u.data["web_road"]["points"] == 70 + weekly.POINTS["daily_claim"] + weekly.POINTS["fight_win"]
    u.data["web_road"]["week"] = "1999-W01"  # a new week starts from zero
    assert weekly.view(u)["points"] == 0


def test_mid_game_bosses_pay_requiem_arrows_and_the_finale_is_eased():
    for k, s in enumerate(story.STAGES):
        if s.get("boss"):
            assert (3 in story.reward_for(k)["items"]) == (s["part"] in story.ARROW_PARTS)
    for c in altverse.CHAPTERS:
        boss = next(j for j, st in enumerate(c["stages"]) if st.get("boss"))
        assert (3 in altverse.reward_for(c["key"], boss)["items"]) == (c["after"] >= 5)
    assert story.STAGE_EASE[story.TOTAL - 1] < 1


def test_fight_pages_show_what_a_fight_asks_and_link_the_simulator(client):
    player(client, "111", main_characters=[char(1, xp=2000), char(2, xp=2000), char(5, xp=2000)])
    login(client, "111")
    page = client.get("/story").data.decode()
    assert "Recommended: Lv" in page and "Your team: Lv 20" in page and "simulator?vs=story:0" in page
    key = altverse.CHAPTERS[0]["key"]
    sim = client.get(f"/battles/simulator?vs=au:{key}:0").data.decode()
    assert "This fight" in sim and "Alternate Universe ·" in sim
    assert "This fight" not in client.get("/battles/simulator?vs=hv:0").data.decode()  # Heaven's Gate: not open yet
    a = advice.for_fight(User(doc(client, "111")), 100, 5, hard=True)
    assert a["state"] == "low" and "★5 on every stand" in a["missing"] and "+5 items" in a["missing"]
    assert advice.recommend(94, 3) == {"level": 94, "stars": 2, "refine": 0}


def test_the_wiki_explains_discs_and_the_weekly_road(client):
    stands = client.get("/wiki/stands").data.decode()
    assert "Stand Discs" in stands and "SSR 120" in stands and "story Parts 6, 7 and 8" in stands
    progress = client.get("/wiki/progress").data.decode()
    assert "Weekly Road" in progress and "the daily reward 5" in progress and "Arrowhead" in progress


def test_guided_paths_go_on_after_the_beginners_path(client):
    from app.game import onboarding
    beginner = [p[0] for p in onboarding.PATH] + ["done"]
    team = [char(1, xp=6000, awaken=1), char(4, xp=6000), char(5, xp=6000)]
    player(client, "111", main_characters=team, web_path=beginner, web_story={"cleared": 1})
    h = {**login(client, "111"), "HX-Request": "true"}
    home = client.get("/").data.decode()
    assert "Rising Stand User · chapter 2/4" in home and "Next: Release a spare stand for Stand Discs" in home
    r = client.post("/path/claim", data={"step": "star1"}, headers=h).data.decode()  # ★1 already on a team stand
    assert "20 Stand Discs" in r and doc(client, "111")["web_discs"] == 20
    assert "later chapter" in client.post("/path/claim", data={"step": "story"}, headers=h).data.decode()
    assert "Finish every step" in client.post("/path/claim", data={"step": "done:rising"}, headers=h).data.decode()
    d = doc(client, "111")  # every step of the chapter done: its reward (a Requiem Arrow) opens the next one
    d["web_path"] = beginner + [p[0] for p in onboarding.RISING]
    put(client, d)
    client.post("/path/claim", data={"step": "done:rising"}, headers=h)
    d = doc(client, "111")
    assert 3 in [i["id"] for i in d["items"]] and "Heir to the Arrow" in client.get("/").data.decode()
    guide = client.get("/wiki/guide").data.decode()
    assert "Guided paths" in guide and "Heir to the Arrow" in guide and "Your team at each step" in guide
