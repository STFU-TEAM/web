"""Ranked chat: the lobby on the Ranked tab, and a match's chat for its two players from the draft to the end screen."""
import pytest

from app.game import chat as C
from app.game.logic import GameError
from test_app import char, client, doc, login, put  # noqa: F401  (client is a fixture)
from test_features import player


def test_a_match_chat_is_for_its_two_players_only(client):
    with client.application.app_context():
        _match_chat_rules()


def _match_chat_rules():
    C.match_open("abc", ["111", "222"])
    ch = C.resolve("match-abc", "111")
    assert ch.kind == "match" and ch.other == "222"
    with pytest.raises(GameError):
        C.resolve("match-abc", "333")
    C.post(ch, "111", "glhf")
    assert [m["text"] for m in C.messages(C.resolve("match-abc", "222"))] == ["glhf"]
    C.block("222", "111")
    with pytest.raises(GameError, match="blocked"):
        C.post(ch, "111", "again")


def test_the_draft_page_shows_the_match_chat_and_the_ranked_tab_the_lobby(client):
    from app.game import draft as draft_mod, progression
    from app.db import r
    player(client, "111", main_characters=[char(1)], web_story={"cleared": progression.GATES["ranked"]})
    login(client, "111")
    page = client.get("/battles?mode=ranked").data.decode()
    assert "Ranked lobby" in page and 'id="chat-ranked"' in page
    draft = draft_mod.create(r(), ["111", "222"], {"111": [], "222": []})
    C.match_open(draft["id"], ["111", "222"])
    page = client.get("/battles?mode=ranked").data.decode()
    assert "Match chat" in page and f'id="chat-match-{draft["id"]}"' in page
