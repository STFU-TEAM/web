"""Web battle modes: practice dummy, friend challenges and Redis ranked queue."""
import json
import time
import uuid

from flask import Blueprint, flash, redirect, render_template, request, session, url_for

from app.accounts import resolve_player
from app.auth import player_required
from app.db import Busy, clear_fight, get_db, identity, load_fight, r, save_fight, user_lock, users_lock
from app.game import logic
from app.game.character import character_from_dict
from app.game.fight import Fight, Side, fighting_copy
from app.filters import PLAYABLE

bp = Blueprint("battles", __name__, url_prefix="/battles")
RANKED_QUEUE = "web:ranked:queue"
RANKED_ELO = "web:ranked:elo"
RANKED_ELO_RANGE = 300
CHALLENGE_INBOX = "web:friend:inbox:{}"
CHALLENGE_KEY = "web:friend:challenge:{}"


def _int(name, default=None):
    try:
        return int(request.values.get(name))
    except (TypeError, ValueError):
        return default


def _active_fight(uid):
    fight = load_fight(uid)
    return fight if fight and fight.kind in {"dummy", "ranked", "friend"} else None


def _fight_view(fight, uid, fresh_from=None):
    players = fight.meta.get("players", [uid])
    my_side = players.index(uid) if uid in players else 0
    return render_template("partials/fight.html", fight=fight, fresh_from=fresh_from, my_side=my_side,
                           fight_action=url_for("battles.attack"), fight_leave_action=url_for("battles.leave"),
                           fight_label={"dummy": "Practice", "ranked": "Ranked", "friend": "Friendly duel"}.get(fight.kind, "Battle"))


def _create_duel(uid_a, uid_b, kind):
    db = get_db()
    if load_fight(uid_a) or load_fight(uid_b):
        return None
    user_a, user_b = db.get_user(uid_a), db.get_user(uid_b)
    if not user_a or not user_b or not user_a.main_characters or not user_b.main_characters:
        return None
    fight = Fight(Side(identity(uid_a)["name"], fighting_copy(user_a.main_characters), True),
                  Side(identity(uid_b)["name"], fighting_copy(user_b.main_characters), True),
                  kind=kind, meta={"players": [uid_a, uid_b], "elo_applied": False})
    fight.advance()
    save_fight(uid_a, fight)
    save_fight(uid_b, fight)
    return fight


@bp.get("")
@player_required
def index():
    uid = session["uid"]
    pending = []
    inbox = CHALLENGE_INBOX.format(uid)
    for challenge_id in r().smembers(inbox):
        challenge_id = challenge_id.decode() if isinstance(challenge_id, bytes) else str(challenge_id)
        raw = r().get(CHALLENGE_KEY.format(challenge_id))
        if raw:
            challenge = json.loads(raw)
            challenge["id"] = challenge_id
            challenge["challenger_name"] = identity(challenge["from"])["name"]
            pending.append(challenge)
        else:
            r().srem(inbox, challenge_id)
    return render_template("battles.html", u=get_db().get_user(uid), mode=request.args.get("mode", "dummy"),
                           fight=_active_fight(uid), pending=pending, waiting=bool(r().zscore(RANKED_QUEUE, uid)),
                           stands=PLAYABLE)


@bp.post("/dummy/start")
@player_required
def dummy_start():
    uid = session["uid"]
    if load_fight(uid):
        return redirect(url_for("battles.index", mode="dummy"))
    user = get_db().get_user(uid)
    if not user or not user.main_characters:
        flash("Add at least one stand to your team first.", "error")
        return redirect(url_for("battles.index", mode="dummy"))
    dummy = character_from_dict({"id": 164, "xp": 100, "types": [], "qualities": [], "awaken": 0, "items": [{"id": 5}]})
    fight = Fight(Side(session.get("name", "You"), fighting_copy(user.main_characters), True, session.get("avatar")),
                  Side("Training Dummy", [dummy], False), kind="dummy", meta={"players": [uid]})
    fight.advance()
    save_fight(uid, fight)
    return redirect(url_for("battles.index", mode="dummy"))


@bp.post("/friends/invite")
@player_required
def invite_friend():
    uid = session["uid"]
    target_id = request.form.get("user_id", "").strip()
    target_id = resolve_player(target_id) or ""
    if not target_id or target_id == uid:
        flash("Enter another registered player's username or Discord ID.", "error")
        return redirect(url_for("battles.index", mode="friends"))
    if not get_db().get_user(uid).main_characters:
        flash("Add a stand to your team before inviting a friend.", "error")
        return redirect(url_for("battles.index", mode="friends"))
    challenge_id = uuid.uuid4().hex
    challenge = {"from": uid, "to": target_id, "created": int(time.time())}
    r().set(CHALLENGE_KEY.format(challenge_id), json.dumps(challenge), ex=300)
    r().sadd(CHALLENGE_INBOX.format(target_id), challenge_id)
    flash(f"Friendly duel invitation sent to {identity(target_id)['name']}.", "ok")
    return redirect(url_for("battles.index", mode="friends"))


@bp.post("/friends/accept/<challenge_id>")
@player_required
def accept_friend(challenge_id):
    uid = session["uid"]
    raw = r().get(CHALLENGE_KEY.format(challenge_id))
    challenge = json.loads(raw) if raw else None
    if not challenge or challenge.get("to") != uid:
        flash("That challenge expired or is not yours.", "error")
        return redirect(url_for("battles.index", mode="friends"))
    try:
        with users_lock(challenge["from"], uid):
            if load_fight(uid) or load_fight(challenge["from"]):
                flash("One of you is already in a fight.", "error")
            else:
                fight = _create_duel(challenge["from"], uid, "friend")
                if fight:
                    r().delete(CHALLENGE_KEY.format(challenge_id))
                    r().srem(CHALLENGE_INBOX.format(uid), challenge_id)
                    flash("Friendly duel accepted.", "ok")
                else:
                    flash("Both players need a team before fighting.", "error")
    except Busy:
        flash("One of you is completing another action. Try again.", "error")
    return redirect(url_for("battles.index", mode="friends"))


@bp.post("/ranked/queue")
@player_required
def ranked_queue():
    uid = session["uid"]
    user = get_db().get_user(uid)
    if not user or not user.main_characters:
        flash("Add a stand to your team before ranked combat.", "error")
        return redirect(url_for("battles.index", mode="ranked"))
    if load_fight(uid):
        return redirect(url_for("battles.index", mode="ranked"))
    now = time.time()
    elo = user.global_elo
    token = uuid.uuid4().hex
    if not r().set("web:ranked:matchlock", token, nx=True, ex=5):
        r().zadd(RANKED_QUEUE, {uid: now})
        r().hset(RANKED_ELO, uid, elo)
        return redirect(url_for("battles.index", mode="ranked", waiting=1))
    try:
        candidates = r().zrangebyscore(RANKED_QUEUE, now - 120, "+inf")
        candidate_ids = [candidate.decode() if isinstance(candidate, bytes) else str(candidate)
                         for candidate in candidates]
        nearby = []
        stale = []
        for candidate_id in candidate_ids:
            if candidate_id == uid:
                continue
            candidate_elo = r().hget(RANKED_ELO, candidate_id)
            if candidate_elo is None:
                stale.append(candidate_id)
                continue
            if abs(int(candidate_elo) - elo) <= RANKED_ELO_RANGE:
                nearby.append((abs(int(candidate_elo) - elo), candidate_id))
        if stale:
            r().zrem(RANKED_QUEUE, *stale)
            r().hdel(RANKED_ELO, *stale)
        opponent = min(nearby)[1] if nearby else None
        if opponent:
            with users_lock(uid, opponent):
                fight = _create_duel(uid, opponent, "ranked")
                if fight:
                    r().zrem(RANKED_QUEUE, uid, opponent)
                    r().hdel(RANKED_ELO, uid, opponent)
                else:
                    r().zrem(RANKED_QUEUE, uid, opponent)
                    r().hdel(RANKED_ELO, opponent)
                    if not load_fight(uid):
                        r().zadd(RANKED_QUEUE, {uid: now})
                        r().hset(RANKED_ELO, uid, elo)
        else:
            r().zadd(RANKED_QUEUE, {uid: now})
            r().hset(RANKED_ELO, uid, elo)
    finally:
        if r().get("web:ranked:matchlock") == token.encode():
            r().delete("web:ranked:matchlock")
    return redirect(url_for("battles.index", mode="ranked", waiting=1))


@bp.post("/ranked/cancel")
@player_required
def ranked_cancel():
    r().zrem(RANKED_QUEUE, session["uid"])
    r().hdel(RANKED_ELO, session["uid"])
    return redirect(url_for("battles.index", mode="ranked"))


def _settle(fight):
    """Quest/achievement counters (and ranked elo) once a battle ends, like the bot's /fight."""
    players = fight.meta.get("players", [])
    if fight.kind == "dummy":
        if fight.winner == 0 and players:
            user = get_db().get_user(players[0])
            logic.track_quest_progress(user, "fight_win")
            logic.check_achievements(user, "fight_win")
            user.update()
        return
    if len(players) != 2:
        return
    users = [get_db().get_user(p) for p in players]
    played = "fight_ranked" if fight.kind == "ranked" else "fight_local"
    for user in users:
        logic.track_quest_progress(user, played)
        logic.check_achievements(user, played)
    if fight.winner is not None:
        winner, loser = users[fight.winner], users[1 - fight.winner]
        actions = ["fight_win"]
        if fight.kind == "ranked":
            winner.global_elo += 25
            loser.global_elo = max(0, loser.global_elo - 20)
            actions.insert(0, "fight_ranked_win")
        for action_name in actions:
            logic.track_quest_progress(winner, action_name)
            logic.check_achievements(winner, action_name)
    for user in users:
        user.update()


@bp.post("/attack")
@player_required
def attack():
    uid = session["uid"]
    fight = load_fight(uid)
    if not fight or fight.kind not in {"dummy", "ranked", "friend"}:
        return "<p class='notice'>This battle is not active.</p>", 409
    player_ids = fight.meta.get("players", [uid])
    lock_ids = player_ids if fight.kind in {"ranked", "friend"} else [uid]
    try:
        with users_lock(*lock_ids, ttl=5):
            fight = load_fight(uid)
            if not fight or fight.kind not in {"dummy", "ranked", "friend"}:
                return "<p class='notice'>This battle is not active.</p>", 409
            my_side = fight.meta.get("players", [uid]).index(uid)
            if not fight.finished and fight.sides[fight.acting_side].is_human and fight.acting_side == my_side:
                if request.form.get("forfeit"):
                    fight.forfeit(my_side)
                else:
                    fight.advance(_int("target"))
            if fight.finished and not fight.meta.get("settled"):
                fight.meta["settled"] = True
                _settle(fight)
            for player_id in lock_ids:
                save_fight(player_id, fight)
    except Busy:
        fight = load_fight(uid)
    return _fight_view(fight, uid, _int("log_len"))


@bp.post("/leave")
@player_required
def leave():
    uid = session["uid"]
    fight = load_fight(uid)
    if fight and fight.kind in {"dummy", "ranked", "friend"} and fight.finished:
        players = fight.meta.get("players", [uid])
        for player_id in players:
            clear_fight(player_id)
    return redirect(url_for("battles.index"))