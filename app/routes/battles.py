"""Web battle modes: practice dummy, friend challenges and Redis ranked queue."""
import json
import time
import uuid

from flask import Blueprint, flash, redirect, render_template, request, Response, session, url_for
from markupsafe import Markup

from app.accounts import resolve_player
from app.auth import player_required
from app import social
from app.db import LIVE_FIGHTS, Busy, clear_fight, get_db, identity, load_fight, r, save_fight, user_lock, users_lock
from app.game import events, history, logic, seasons, simulate, story
from app.game.logic import GameError
from app.game.character import character_from_dict
from app.game.fight import Fight, Side, ai_choice, fighting_copy
from app.filters import PLAYABLE

bp = Blueprint("battles", __name__, url_prefix="/battles")
RANKED_QUEUE = "web:ranked:queue"
RANKED_ELO = "web:ranked:elo"
RANKED_ELO_RANGE = 300
CHALLENGE_INBOX = "web:friend:inbox:{}"
CHALLENGE_KEY = "web:friend:challenge:{}"
CHALLENGE_WAIT = "web:friend:waiting:{}"   # set while a player waits for a friend to accept (auto refresh)
CHALLENGE_TTL = 300

# PvP turn clock: every pick has TURN_SECONDS (plus the time the last action takes to replay).
# Running out picks a target automatically; running out AFK_LIMIT times in a row loses the duel.
PVP = {"ranked", "friend"}
TURN_SECONDS = 10
REPLAY_ALLOWANCE = 0.8   # seconds per log line the client replays, capped like the client (8 s)
AFK_LIMIT = 2


def arm_timer(fight):
    """Start the clock when a new pick is awaited (a new (turn, stand) decision)."""
    if fight.kind not in PVP or fight.finished or not fight.awaiting_input:
        return
    key = [fight.turn, fight.si]
    if fight.meta.get("timer_for") == key:
        return
    replay = min(8.0, REPLAY_ALLOWANCE * (len(fight.log) - fight.meta.get("timer_log", 0)))
    fight.meta.update(timer_for=key, timer_log=len(fight.log), deadline=time.time() + TURN_SECONDS + replay)


def enforce_timer(fight) -> bool:
    """If the acting player let the clock run out: auto pick, or forfeit after AFK_LIMIT misses in a row."""
    if fight.kind not in PVP or fight.finished or not fight.awaiting_input:
        return False
    deadline = fight.meta.get("deadline")
    if deadline is None or time.time() < deadline:
        return False
    side = fight.acting_side
    afk = fight.meta.setdefault("afk", [0, 0])
    afk[side] += 1
    name = fight.sides[side].name
    if afk[side] >= AFK_LIMIT:
        fight._log(f"⏱️ {name} ran out of time again and loses the duel.", "info", side=side)
        fight.forfeit(side)
        fight.meta["timeout"] = side
    else:
        fight._log(f"⏱️ Time's up! {name}'s stand picks a target on its own.", "info", side=side)
        fight.advance(ai_choice(fight.sides[1 - side].chars))
    arm_timer(fight)
    return True


def turn_left(fight) -> int:
    """Seconds left on the clock (for the countdown); None outside a PvP pick."""
    if fight.kind not in PVP or fight.finished or "deadline" not in fight.meta:
        return None
    return max(0, int(round(fight.meta["deadline"] - time.time())))


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
    return render_template("partials/fight.html", fight=fight, fresh_from=fresh_from, my_side=my_side, turn_left=turn_left(fight),
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
    arm_timer(fight)
    save_fight(uid_a, fight)
    save_fight(uid_b, fight)
    r().hset(LIVE_FIGHTS, fight.id, json.dumps({"players": [uid_a, uid_b], "kind": kind, "at": int(time.time())}))
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
    user = get_db().get_user(uid)
    mode = request.args.get("mode", "dummy")
    extra = {}
    if mode == "ranked":
        extra = {"season": seasons.standing(r(), uid, user.global_elo), "season_claims": seasons.unclaimed(r(), user),
                 "season_rewards": seasons.reward_table(), "season_min": seasons.MIN_GAMES}
    elif mode == "watch":
        extra = {"live": live_duels(uid)}
    elif mode == "history":
        rows = history.recent(r(), uid)
        extra = {"recent": rows, "record": history.summary(rows)}
    return render_template("battles.html", u=user, mode=mode, **extra,
                           fight=_active_fight(uid), pending=pending, waiting=r().zscore(RANKED_QUEUE, uid) is not None,
                           challenge_to=(lambda t: identity(t.decode() if isinstance(t, bytes) else t)["name"] if t else None)(
                               r().get(CHALLENGE_WAIT.format(uid))),
                           turn_left=(lambda f: turn_left(f) if f else None)(_active_fight(uid)),
                           stands=PLAYABLE, story_stage=story.current(user), story_cleared=story.cleared(user),
                           story_total=story.TOTAL)


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
    r().set(CHALLENGE_KEY.format(challenge_id), json.dumps(challenge), ex=CHALLENGE_TTL)
    r().sadd(CHALLENGE_INBOX.format(target_id), challenge_id)
    r().set(CHALLENGE_WAIT.format(uid), target_id, ex=CHALLENGE_TTL)
    from app import social
    social.notify(target_id, "fight", f"{identity(uid)['name']} challenged you to a friendly duel (5 minutes to accept).",
                  url_for("community.inbox"))
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
                    from app import social
                    social.notify(challenge["from"], "fight", f"{identity(uid)['name']} accepted your duel. Fight!",
                                  url_for("battles.index"))
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
    _try_match(uid, user.global_elo)
    return redirect(url_for("battles.index", mode="ranked", waiting=1))


def _try_match(uid, elo):
    """Queue uid (refreshing its spot) and pair it with the closest Elo in range, if anyone is there."""
    now = time.time()
    token = uuid.uuid4().hex
    if not r().set("web:ranked:matchlock", token, nx=True, ex=5):
        r().zadd(RANKED_QUEUE, {uid: now})
        r().hset(RANKED_ELO, uid, elo)
        return
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


def pvp_waiting(uid) -> bool:
    """In the ranked queue, or waiting for a friend to accept: the pages poll /battles/ping."""
    return bool(r().zscore(RANKED_QUEUE, uid) is not None or r().exists(CHALLENGE_WAIT.format(uid)))


@bp.get("/ping")
@player_required
def ping():
    """Auto refresh while waiting: jump into the duel the moment it exists; 286 stops the polling."""
    uid = session["uid"]
    fight = load_fight(uid)
    if fight and fight.kind in PVP and not fight.finished:
        r().delete(CHALLENGE_WAIT.format(uid))
        resp = Response(status=204)
        resp.headers["HX-Redirect"] = url_for("battles.index")
        return resp
    if r().zscore(RANKED_QUEUE, uid) is not None:
        user = get_db().get_user(uid)
        if user and user.main_characters:
            _try_match(uid, user.global_elo)
            if load_fight(uid):
                resp = Response(status=204)
                resp.headers["HX-Redirect"] = url_for("battles.index")
                return resp
        return Response(status=204)
    if r().exists(CHALLENGE_WAIT.format(uid)):
        return Response(status=204)
    return Response(status=286)


@bp.post("/ranked/cancel")
@player_required
def ranked_cancel():
    r().zrem(RANKED_QUEUE, session["uid"])
    r().hdel(RANKED_ELO, session["uid"])
    return redirect(url_for("battles.index", mode="ranked"))


def _settle(fight):
    """Quest/achievement counters (and ranked elo) once a battle ends, like the bot's /fight."""
    players = fight.meta.get("players", [])
    from app.routes.fightturn import fun_achievements
    if fight.kind == "dummy":
        if players:
            user = get_db().get_user(players[0])
            if fight.winner == 0:
                logic.track_quest_progress(user, "fight_win")
                logic.check_achievements(user, "fight_win")
                logic.check_achievements(user, "dummy_kill")
            elif not getattr(fight, "forfeited", False):
                logic.check_achievements(user, "dummy_loss")
            fun_achievements(user, fight)
            user.update()
        return
    if len(players) != 2:
        return
    users = [get_db().get_user(p) for p in players]
    played = "fight_ranked" if fight.kind == "ranked" else "fight_local"
    for user in users:
        logic.track_quest_progress(user, played)
        logic.check_achievements(user, played)
    for side, user in enumerate(users):
        fun_achievements(user, fight, side)
        if fight.winner is None and not getattr(fight, "forfeited", False):
            logic.check_achievements(user, "draw")
    if fight.kind == "ranked":
        elos = {p: int(u.global_elo or 0) for p, u in zip(players, users)}
        winner_id = players[fight.winner] if fight.winner is not None else None
        for uid in seasons.record(r(), players, winner_id, elos):
            sid = seasons.season_id()
            social.notify_later(uid, f"season:{sid}", time.time() + seasons.seconds_left(sid), "season",
                                f"♛ The {seasons.label(sid)} ranked season is over. Claim your season reward!",
                                url_for("battles.index", mode="ranked"))
    if fight.winner is not None:
        winner, loser = users[fight.winner], users[1 - fight.winner]
        actions = ["fight_win"]
        if fight.kind == "ranked":
            winner.global_elo += seasons.WIN
            loser.global_elo = max(0, loser.global_elo - seasons.LOSS)
            actions.insert(0, "fight_ranked_win")
            fight.meta["tokens"] = events.earn(winner, events.TOKENS_PVP)
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
            enforce_timer(fight)  # whoever asks (the waiting player's poll included) applies a timeout
            if not fight.finished and fight.sides[fight.acting_side].is_human and fight.acting_side == my_side:
                if request.form.get("forfeit"):
                    fight.forfeit(my_side)
                elif _int("target") is not None:
                    fight.meta.setdefault("afk", [0, 0])[my_side] = 0  # a real pick clears the misses
                    fight.advance(_int("target"))
            arm_timer(fight)
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

# --------------------------------------------------------------------------- #
# Ranked seasons
# --------------------------------------------------------------------------- #
@bp.post("/season/claim")
@player_required
def season_claim():
    uid = session["uid"]
    try:
        with user_lock(uid):
            user = get_db().get_user(uid)
            paid = seasons.claim(r(), user)
            user.update()
        for s in paid:
            extra = f" and the title “{s['title']}”" if s["title"] else ""
            flash(f"♛ {s['label']}: you finished {s['tier']}. {seasons.reward_text(s['reward'])}{extra}.", "ok")
    except GameError as e:
        flash(str(e), "error")
    except Busy:
        flash("Your last action is still running.", "error")
    return redirect(url_for("battles.index", mode="ranked"))


# --------------------------------------------------------------------------- #
# Watching live duels and replays
# --------------------------------------------------------------------------- #
def can_watch(viewer, entry) -> bool:
    """Ranked duels are public; friendly duels are for the two players and their friends."""
    players = entry.get("players", [])
    if entry.get("kind") == "ranked" or (viewer and viewer in players):
        return True
    return bool(viewer) and any(social.are_friends(viewer, p) for p in players)


def _live_entry(fight_id):
    raw = r().hget(LIVE_FIGHTS, fight_id)
    return json.loads(raw) if raw else None


def _live_fight(fight_id, entry):
    """The duel behind a live entry, or None (and the stale entry dropped) once it's gone."""
    fight = load_fight(entry["players"][0]) if entry and entry.get("players") else None
    if not fight or fight.id != fight_id:
        r().hdel(LIVE_FIGHTS, fight_id)
        return None
    return fight


def live_duels(viewer) -> list:
    out = []
    for fid, raw in r().hgetall(LIVE_FIGHTS).items():
        fid = fid.decode() if isinstance(fid, bytes) else fid
        try:
            entry = json.loads(raw)
        except ValueError:
            r().hdel(LIVE_FIGHTS, fid)
            continue
        if not can_watch(viewer, entry):
            continue
        fight = _live_fight(fid, entry)
        if not fight or fight.finished:
            continue
        out.append({"id": fid, "kind": entry["kind"], "round": fight.round, "at": entry.get("at", 0),
                    "mine": viewer in entry["players"],
                    "sides": [{"name": s.name, "uid": entry["players"][i], "lead": [c.id for c in s.chars],
                               "hp": int(100 * sum(max(0, c.current_hp) for c in s.chars)
                                         / max(1, sum(c.start_hp for c in s.chars)))}
                              for i, s in enumerate(fight.sides)]})
    out.sort(key=lambda d: (not d["mine"], d["kind"] != "ranked", -d["at"]))
    return out


def live_fight_of(uid):
    """Id of the PvP duel uid is fighting right now (for the profile's Watch button), or None."""
    fight = load_fight(uid)
    if fight and fight.kind in PVP and not fight.finished and r().hexists(LIVE_FIGHTS, fight.id):
        return fight.id
    return None


def _viewer_view(fight, mode, fight_id, fresh_from=None):
    return render_template("partials/fight.html", fight=fight, fresh_from=fresh_from, my_side=0, viewer=mode,
                           turn_left=turn_left(fight), fight_action="", fight_leave_action="",
                           watch_frame=url_for("battles.watch_frame", fight_id=fight_id),
                           replay_url=url_for("battles.replay", fight_id=fight_id),
                           fight_label=history.LABELS.get(fight.kind, "Battle"))


@bp.get("/watch/<fight_id>")
@player_required
def watch(fight_id):
    entry = _live_entry(fight_id)
    fight = _live_fight(fight_id, entry) if entry else None
    if not fight:
        if history.load_replay(r(), fight_id):
            return redirect(url_for("battles.replay", fight_id=fight_id))
        flash("That duel is over.", "error")
        return redirect(url_for("battles.index", mode="watch"))
    if not can_watch(session["uid"], entry):
        flash("Friendly duels can only be watched by the players' friends.", "error")
        return redirect(url_for("battles.index", mode="watch"))
    return render_template("watch.html", fight=fight, fight_id=fight_id, entry=entry, mode="watch",
                           frame=Markup(_viewer_view(fight, "watch", fight_id, fresh_from=len(fight.log))))


@bp.get("/watch/<fight_id>/frame")
@player_required
def watch_frame(fight_id):
    """The polled view: 204 (nothing to swap) until something happened since log_len."""
    log_len = _int("log_len", 0)
    entry = _live_entry(fight_id)
    fight = _live_fight(fight_id, entry) if entry else None
    if fight and not can_watch(session["uid"], entry):
        return Response(status=403)
    if not fight:
        fight = history.load_replay(r(), fight_id)  # it just ended
        if not fight:
            return Response(status=286)
    elif len(fight.log) == log_len and not fight.finished:
        return Response(status=204)
    return _viewer_view(fight, "watch", fight_id, fresh_from=min(log_len, len(fight.log)))


@bp.get("/replay/<fight_id>")
def replay(fight_id):
    """Public: anyone with the link can watch a finished fight again."""
    fight = history.load_replay(r(), fight_id)
    if not fight:
        return render_template("error.html", code=404, message="This replay has expired (replays are kept "
                                                                f"{history.REPLAY_DAYS} days)."), 404
    return render_template("watch.html", fight=fight, fight_id=fight_id, mode="replay",
                           label=history.LABELS.get(fight.kind, "Battle"),
                           frame=Markup(_viewer_view(fight, "replay", fight_id, fresh_from=0)),
                           share_url=url_for("battles.replay", fight_id=fight_id, _external=True))


# --------------------------------------------------------------------------- #
# Team simulator
# --------------------------------------------------------------------------- #
def _sim_teams(user):
    teams = [{"value": "", "label": "Current team", "team": user.main_characters}]
    for name in sorted(user.teams):
        members = []
        for stand_uuid in user.teams.get(name) or []:
            found = user.find_character_by_uuid(stand_uuid)[0] if isinstance(stand_uuid, str) else None
            if found:
                members.append(found)
        if members:
            teams.append({"value": name, "label": f"Preset: {name}", "team": members})
    return teams


@bp.get("/simulator")
@player_required
def simulator():
    uid = session["uid"]
    user = get_db().get_user(uid)
    friends = sorted(({"id": f, "name": identity(f)["name"]} for f in social.friends(uid)), key=lambda f: f["name"].lower())
    k = story.cleared(user)
    from app.game import overheaven
    return render_template("simulator.html", u=user, teams=_sim_teams(user), groups=simulate.opponents(overheaven.unlocked(user)),
                           friends=friends, preset=request.args.get("vs") or f"story:{min(k, story.TOTAL - 1)}",
                           runs=simulate.RUNS)


@bp.post("/simulator/run")
@player_required
def simulator_run():
    uid = session["uid"]
    user = get_db().get_user(uid)
    pick = next((t for t in _sim_teams(user) if t["value"] == request.form.get("team", "")), None)
    vs = request.form.get("vs", "")
    if vs == "player":
        vs = f"player:{resolve_player(request.form.get('player', '')) or ''}"
    from app.game import overheaven
    if vs.startswith("oh:") and not overheaven.unlocked(user):
        vs = ""  # Over Heaven isn't open for this player yet
    foe = simulate.foe_for(vs, get_db())
    if not pick or not pick["team"]:
        return "<p class='notice error'>Put stands in that team first.</p>"
    if not foe:
        return "<p class='notice error'>Pick an opponent (a player needs a team to simulate against).</p>"
    if not r().set(f"web:sim:{uid}", "1", nx=True, ex=3):
        return "<p class='notice error'>One simulation at a time: try again in a few seconds.</p>"
    result = simulate.run(pick["team"], foe)
    return render_template("partials/sim_result.html", res=result, foe=foe, team_label=pick["label"])
