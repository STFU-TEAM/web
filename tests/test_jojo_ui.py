"""The JoJo touches: stand parameter grades and chart, part title cards, menacing titles, fight effects and their toggle,
the JoJo empty states."""
from app.game import params
from test_app import char, client, login, put  # noqa: F401  (client is a fixture)
from app.game.user import create_user


def test_parameter_grades_follow_the_stats():
    sp = {k: letter for k, _, _, _, letter, _ in params.grades(1)}  # Star Platinum: 77 damage, 10 speed, SSR, 2 turns
    assert sp["power"] == "A" and sp["speed"] == "A" and sp["special"] == "B" and sp["potential"] == "C"
    kq = {k: letter for k, _, _, _, letter, _ in params.grades(49)}  # Killer Queen: 1 speed, 3 turns
    assert kq["speed"] in "DE" and kq["special"] == "C"
    assert params.grades(109)[3][4] == "A"  # Made In Heaven charges every turn
    assert params.grades(0) == () and params.chart(9999) == {}
    ch = params.chart(1)
    assert len(ch["axes"]) == 6 and len(ch["rings"]) == 5 and ch["shape"].count(",") == 6


def test_stand_page_and_panel_show_the_chart(client):
    page = client.get("/stands/1").data.decode()
    assert 'class="param-chart' in page and "破壊力" in page and "data-params-flip" in page
    d = create_user("111")
    d["main_characters"] = [char(1, xp=3000)]
    put(client, d)
    login(client, "111")
    panel = client.get(f"/team/stand/{d['main_characters'][0]['uuid']}").data.decode()
    assert "card-params" in panel and "data-params-flip" in panel


def test_story_parts_are_title_cards_and_titles_menace(client):
    put(client, create_user("111"))
    login(client, "111")
    story = client.get("/story").data.decode()
    assert story.count('class="part-card"') >= 7 and "スターダストクルセイダース" in story
    assert 'class="menacing-title"' in client.get("/battles").data.decode()
    assert "Yare yare daze" in client.get("/trades").data.decode()


def test_fight_effects_toggle(client):
    d = create_user("111")
    d["main_characters"] = [char(1, xp=3000)]
    put(client, d)
    h = login(client, "111")
    page = client.post("/battles/dummy/start", headers=h, follow_redirects=True).data.decode()
    assert 'data-fx="1"' in page and 'data-cry="ORA"' in page and "💥 Effects on" in page
    assert client.post("/prefs/fight-fx", data={"on": "0"}, headers=h).status_code == 204
    page = client.get("/battles?mode=dummy", follow_redirects=True).data.decode()
    assert 'data-fx="0"' in page and "💥 Effects off" in page
