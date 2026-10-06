"""Ranked pick-and-ban: a roster of 5 different stands, 2 bans each (20 s), then the team order (20 s)."""
import time

import pytest

from app.game import draft as D
from app.game.logic import GameError
from app.game.user import User
from test_app import char, client, doc, login, put  # noqa: F401  (client is a fixture)
from test_features import finish_draft, ranked_player, player


def test_the_roster_is_five_different_owned_stands(client):
    a, b = char(1), char(1)  # two copies of Star Platinum
    others = [char(i) for i in (2, 3, 4, 5)]
    d = player(client, "111", main_characters=[a], storage_characters=[b] + others)
    user = User(d)
    with pytest.raises(GameError, match="different stands"):
        D.set_roster(user, [a["uuid"], b["uuid"]] + [o["uuid"] for o in others[:3]])
    with pytest.raises(GameError, match="exactly 5"):
        D.set_roster(user, [a["uuid"]] + [o["uuid"] for o in others[:3]])
    with pytest.raises(GameError, match="isn't in your collection"):
        D.set_roster(user, [a["uuid"], "nope"] + [o["uuid"] for o in others[:3]])
    D.set_roster(user, [a["uuid"]] + [o["uuid"] for o in others])
    assert D.roster_ready(user) and [c.id for c in D.roster(user)] == [1, 2, 3, 4, 5]
    # releasing one breaks it until a new pick
    user.storage_characters = [c for c in user.storage_characters if c.id != 5]
    assert not D.roster_ready(user)


def test_queueing_needs_a_roster_and_it_is_locked_while_queued(client):
    player(client, "111", main_characters=[char(1)])
    h = login(client, "111")
    r = client.post("/battles/ranked/queue", headers=h, follow_redirects=True)
    assert b"Pick your 5 ranked stands" in r.data
    assert client.fake.zscore("web:ranked:queue", "111") is None
    ranked_player(client, "111")
    client.post("/battles/ranked/queue", headers=h)
    assert client.fake.zscore("web:ranked:queue", "111") is not None
    r = client.post("/battles/ranked/roster", data={"uuid": ["x"] * 5}, headers=h, follow_redirects=True)
    assert b"change your roster while queued" in r.data


def test_bans_and_order_are_checked(client):
    ranked_player(client, "111")
    ranked_player(client, "222", ids=(6, 7, 8, 9, 10))
    from app.routes.battles import _create_draft
    with client.application.test_request_context():
        draft = _create_draft("111", "222")
    mine, theirs = draft["rosters"]["111"], draft["rosters"]["222"]
    with pytest.raises(GameError):
        D.ban(draft, "111", mine[:2])          # your own stands
    with pytest.raises(GameError):
        D.ban(draft, "111", theirs[:3])        # three
    D.ban(draft, "111", theirs[:2])
    with pytest.raises(GameError, match="already"):
        D.ban(draft, "111", theirs[2:4])
    with pytest.raises(GameError):
        D.compose(draft, "111", mine[:3])      # not yet
    D.ban(draft, "222", mine[3:])
    assert D.step(draft, lambda uid, uuids: uuids) and draft["phase"] == "compose"
    assert D.remaining(draft, "111") == mine[:3] and D.remaining(draft, "222") == theirs[2:]
    with pytest.raises(GameError):
        D.compose(draft, "111", mine[2:5])     # a banned one
    D.compose(draft, "111", mine[:3][::-1])
    assert draft["order"]["111"] == mine[:3][::-1]


def test_running_out_of_time_bans_the_strongest_and_keeps_roster_order(client):
    ranked_player(client, "111")
    # 222's last stand is far stronger than the rest: an automatic ban takes it first
    d = ranked_player(client, "222", ids=(6, 7, 8, 9, 10))
    d["storage_characters"][-1]["xp"] = 100 * 100
    d["storage_characters"][-1]["awaken"] = 5
    put(client, d)
    from app.routes.battles import _create_draft
    with client.application.test_request_context():
        draft = _create_draft("111", "222")
    strong = d["storage_characters"][-1]["uuid"]
    finish_draft(client)
    from app.db import load_fight
    fight = load_fight("111")
    assert fight and fight.kind == "ranked" and D.of(client.fake, "111") is None
    teams = {p: [c.uuid for c in side.chars] for p, side in zip(fight.meta["players"], fight.sides)}
    assert strong not in teams["222"] and len(teams["222"]) == 3 and len(teams["111"]) == 3
    assert "Ban 2" not in client.get("/battles?mode=ranked").data.decode()


def test_the_draft_page_and_its_poll(client):
    ranked_player(client, "111")
    ranked_player(client, "222", ids=(6, 7, 8, 9, 10))
    from app.routes.battles import _create_draft
    with client.application.test_request_context():
        draft = _create_draft("111", "222")
    h = login(client, "111")
    page = client.get("/battles?mode=ranked").data.decode()
    assert "Ban 2 of their stands" in page and 'data-turn-clock="' in page and page.count('name="ban"') == 5
    state = re.search(r"state=([^\"&]+)", page).group(1)
    assert client.get(f"/battles/ranked/draft/poll?state={state}", headers=h).headers.get("HX-Refresh") is None
    with client.session_transaction() as s:
        s["uid"] = "222"
    client.post("/battles/ranked/ban", data={"ban": draft["rosters"]["111"][:2]}, headers=h)
    with client.session_transaction() as s:
        s["uid"] = "111"
    # the opponent locked in: the page reloads to show it
    assert client.get(f"/battles/ranked/draft/poll?state={state}", headers=h).headers.get("HX-Refresh") == "true"


import re  # noqa: E402
