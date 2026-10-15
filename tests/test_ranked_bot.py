"""Rival bots in the ranked queue (app/game/ranked_bot.py): offered after a wait, labelled, a quarter of the Elo."""
import time

from app.db import load_fight, r
from app.game import draft as draft_mod, ranked_bot, seasons
from app.game.user import User
from app.routes.battles import QUEUE_SINCE, RANKED_QUEUE
from test_app import char, client, doc, login, put  # noqa: F401  (client is a fixture)
from test_features import ranked_player


def _queue(client, h, waited):
    client.post("/battles/ranked/queue", headers=h)
    r().set(QUEUE_SINCE.format("111"), int(time.time() - waited))


def test_a_bot_is_offered_only_after_the_wait_and_bans_at_once(client):
    ranked_player(client, "111")
    h = login(client, "111")
    _queue(client, h, 5)
    page = client.get("/battles?mode=ranked").data.decode()
    assert "Fight a rival bot" in page and 'data-bot-in="' in page
    client.post("/battles/ranked/bot", headers=h)
    assert draft_mod.of(r(), "111") is None  # too early
    r().set(QUEUE_SINCE.format("111"), int(time.time() - ranked_bot.BOT_WAIT - 1))
    client.post("/battles/ranked/bot", headers=h)
    draft = draft_mod.of(r(), "111")
    bot = draft["bot"]["id"]
    assert draft["players"] == ["111", bot] and "(bot)" in draft["bot"]["name"]
    assert len(draft["bans"][bot]) == draft_mod.BANS and set(draft["bans"][bot]) <= set(draft["rosters"]["111"])
    assert r().zscore(RANKED_QUEUE, "111") is None
    assert "(bot)" in client.get("/battles?mode=ranked").data.decode()


def test_the_bot_drafts_with_you_and_fights_as_the_computer(client):
    ranked_player(client, "111")
    h = login(client, "111")
    _queue(client, h, ranked_bot.BOT_WAIT + 1)
    client.post("/battles/ranked/bot", headers=h)
    draft = draft_mod.of(r(), "111")
    bot = draft["bot"]["id"]
    client.post("/battles/ranked/ban", data={"ban": draft["rosters"][bot][:draft_mod.BANS]}, headers=h)
    draft = draft_mod.of(r(), "111")
    assert draft["phase"] == "compose" and draft["order"][bot]  # the bot fielded its team at once
    mine = draft_mod.remaining(draft, "111")
    client.post("/battles/ranked/compose", data={f"slot{i}": u for i, u in enumerate(mine)}, headers=h)
    fight = load_fight("111")
    assert fight and fight.kind == "ranked" and fight.meta["players"] == ["111"] and fight.meta["bot"]
    assert fight.sides[0].is_human and not fight.sides[1].is_human
    before = User(doc(client, "111")).global_elo
    client.post("/battles/attack", data={"forfeit": "1"}, headers=h)
    after = User(doc(client, "111"))
    assert after.global_elo == max(0, before - ranked_bot.LOSS)
    assert seasons.standing(r(), "111", after.global_elo).get("games", 0) == 0  # not a season game


def test_bot_wins_pay_a_quarter_up_to_a_daily_cap():
    from app.game.user import create_user
    u = User(create_user("1"))
    u.global_elo = 1000
    gains = [ranked_bot.settle(u, True, False) for _ in range(7)]
    assert gains[0] == ranked_bot.WIN == round(seasons.WIN / 4) and sum(gains) == ranked_bot.DAILY_GAIN_CAP and gains[-1] == 0
    assert ranked_bot.settle(u, False, True) == -ranked_bot.LOSS
    assert u.global_elo == 1000 + ranked_bot.DAILY_GAIN_CAP - ranked_bot.LOSS


def test_a_bot_duel_plays_to_the_end(client):
    ranked_player(client, "111")
    h = login(client, "111")
    _queue(client, h, ranked_bot.BOT_WAIT + 1)
    client.post("/battles/ranked/bot", headers=h)
    draft = draft_mod.of(r(), "111")
    bot = draft["bot"]["id"]
    client.post("/battles/ranked/ban", data={"ban": draft["rosters"][bot][:draft_mod.BANS]}, headers=h)
    mine = draft_mod.remaining(draft_mod.of(r(), "111"), "111")
    client.post("/battles/ranked/compose", data={f"slot{i}": u for i, u in enumerate(mine)}, headers=h)
    before = User(doc(client, "111")).global_elo
    for _ in range(300):
        fight = load_fight("111")
        if fight.finished:
            break
        target = next(i for i, c in enumerate(fight.sides[1].chars) if c.current_hp > 0)
        assert client.post("/battles/attack", data={"target": target}, headers=h).status_code == 200
    fight = load_fight("111")
    assert fight.finished and fight.meta.get("settled")
    delta = User(doc(client, "111")).global_elo - before
    assert delta in (ranked_bot.WIN, -ranked_bot.LOSS, 0) and fight.meta["elo_delta"] == delta
