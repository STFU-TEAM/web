"""Duels are paced for 1-2 minutes: harder hits, earlier sudden death, a lower round cap, and a 5-minute wall clock.
PvE fights keep the base numbers."""
import time

import app.db as dbmod
from app.game import fight as F
from app.routes import battles
from test_app import char, client, doc, login, put  # noqa: F401  (client is a fixture)
from test_features import player


def _stands(ids):
    from app.game.character import character_from_dict
    return [character_from_dict(char(i, xp=5000)) for i in ids]


def test_duels_hit_harder_and_end_sooner_than_pve(client):
    with client.application.app_context():
        duel = F.Fight(F.Side("A", _stands([1, 2, 3]), True), F.Side("B", _stands([4, 5, 6]), True), kind="friend",
                       meta={"players": ["a", "b"]})
        story = F.Fight(F.Side("A", _stands([1, 2, 3]), True), F.Side("B", _stands([4, 5, 6]), False), kind="story")
    assert duel.sides[0].chars[0].start_damage == int(story.sides[0].chars[0].start_damage * F.PVP_DAMAGE)
    assert (duel.sudden_death_round, duel.max_rounds) == (F.PVP_SUDDEN_DEATH_ROUND, F.PVP_MAX_ROUNDS)
    assert (story.sudden_death_round, story.max_rounds, story.sudden_death_step) == (
        F.SUDDEN_DEATH_ROUND, F.MAX_ROUNDS, F.SUDDEN_DEATH_STEP)
    while not duel.finished:  # the AI plays both sides to the end
        duel.advance(F.ai_choice(duel.sides[1 - duel.acting_side].chars, duel.acting_char))
    assert duel.round <= F.PVP_MAX_ROUNDS + 1


def test_a_duel_is_called_after_five_minutes(client):
    for uid in ("111", "222"):
        player(client, uid, main_characters=[char(1, xp=5000)])
    h = login(client, "111")
    with client.application.app_context():
        fight = battles._create_duel("111", "222", "friend")
    assert fight.meta["started"] <= time.time()
    fight.meta["started"] -= F.PVP_MAX_SECONDS + 1
    fight.sides[1].chars[0].current_hp //= 2  # 222 is behind on health
    dbmod.save_fight("111", fight)
    dbmod.save_fight("222", fight)
    client.post("/battles/attack", headers=h)
    done = dbmod.load_fight("111")
    assert done.finished and done.winner == 0
    assert any("duel clock ran out" in e["text"] for e in done.log)


def test_knocking_out_the_last_enemy_in_sudden_death_wins_instead_of_drawing(client):
    with client.application.app_context():
        f = F.Fight(F.Side("A", _stands([1]), True), F.Side("B", _stands([4]), True), kind="friend",
                    meta={"players": ["a", "b"]})
    me, foe = f.acting_side, 1 - f.acting_side
    f.turn = 2 * (f.sudden_death_round + 2) + (f.turn % 2)  # deep in sudden death, same side to act
    mine, theirs = f.sides[me].chars[0], f.sides[foe].chars[0]
    mine.current_hp, theirs.current_hp = 1, 1  # the tick at the end of this turn would finish the attacker too
    theirs.current_speed = mine.current_speed  # no dodge
    mine.special_meter = -99
    f.advance(0)
    assert f.finished and f.winner == me
