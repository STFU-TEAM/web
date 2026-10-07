"""Co-op raid pages: the lobby (create, join by code, invite friends, pick a stand, start) and the shared fight.
The rules live in app/game/coop.py; the fight screen is the shared fight partial."""
from flask import Blueprint, Response, flash, redirect, render_template, request, session, url_for

from app import social
from app.auth import player_required
from app.db import Busy, clear_fight, get_db, identity, load_fight, r, save_fight, users_lock
from app.filters import power_score
from app.game import coop
from app.game.fight import Fight, Side, fighting_copy
from app.game.logic import GameError

bp = Blueprint("coop", __name__, url_prefix="/coop")


def _fight(uid):
    fight = load_fight(uid)
    return fight if fight and fight.kind == "coop" else None


def _lobby_ctx(uid):
    user = get_db().get_user(uid)
    lb = coop.lobby_of(uid)
    me = next((m for m in lb["members"] if m["uid"] == str(uid)), None) if lb else None
    friends = []
    if lb and lb["host"] == str(uid):
        inside = {m["uid"] for m in lb["members"]}
        friends = sorted(({"id": f, "name": identity(f)["name"]} for f in social.friends(uid) if f not in inside),
                         key=lambda f: f["name"].lower())
    used = coop.used_today(user) if user else set()
    stands = sorted(user.main_characters + user.storage_characters, key=lambda c: (c.uuid in used, -power_score(c))) if user else []
    return {"u": user, "lb": lb, "me_member": me, "friends": friends, "stands": stands[:60], "used": used,
            "tiers": coop.TIERS, "boss": coop.boss_view(), "party": (coop.PARTY_MIN, coop.PARTY_MAX),
            "wins_left": coop.wins_left(user) if user else 0, "daily": coop.DAILY_WINS,
            "join_code": request.args.get("join", "")}


def _fight_view(fight, uid, fresh_from=None):
    return render_template("partials/fight.html", fight=fight, fresh_from=fresh_from, my_side=0,
                           turn_left=coop.turn_left(fight), coop_me=str(uid),
                           fight_action=url_for("coop.attack"), fight_leave_action=url_for("coop.fight_leave"),
                           fight_label="Co-op raid")


@bp.get("")
@player_required
def index():
    uid = session["uid"]
    fight = _fight(uid)
    other = load_fight(uid)
    busy = other.kind.replace("_", " ") if other and other.kind != "coop" and not other.finished else None
    return render_template("coop.html", fight=fight, busy=busy, coop_me=str(uid), turn_left=coop.turn_left(fight) if fight else None,
                           fight_action=url_for("coop.attack"), fight_leave_action=url_for("coop.fight_leave"),
                           fight_label="Co-op raid", **_lobby_ctx(uid))


@bp.get("/lobby")
@player_required
def lobby_frame():
    """Polled by the lobby: the members as they come, and a jump into the fight once the host starts it."""
    uid = session["uid"]
    if _fight(uid) and not _fight(uid).finished:
        resp = Response("", 204)
        resp.headers["HX-Redirect"] = url_for("coop.index")
        return resp
    return render_template("partials/coop_lobby.html", **_lobby_ctx(uid))


def _act(fn, ok=None):
    try:
        result = fn()
        if ok:
            flash(ok, "ok")
        return result
    except GameError as e:
        flash(str(e), "error")


@bp.post("/create")
@player_required
def create():
    _act(lambda: coop.create(session["uid"], session.get("name", "Player"), request.form.get("tier", "normal")))
    return redirect(url_for("coop.index"))


@bp.post("/join")
@player_required
def join():
    _act(lambda: coop.join(session["uid"], session.get("name", "Player"), request.form.get("code", "")))
    return redirect(url_for("coop.index"))


@bp.post("/leave")
@player_required
def leave():
    coop.leave(session["uid"])
    return redirect(url_for("coop.index"))


@bp.post("/pick")
@player_required
def pick():
    user = get_db().get_user(session["uid"])
    _act(lambda: coop.pick(user, request.form.get("uuid", "")))
    if request.headers.get("HX-Request"):
        return render_template("partials/coop_lobby.html", **_lobby_ctx(session["uid"]))
    return redirect(url_for("coop.index"))


@bp.post("/tier")
@player_required
def tier():
    _act(lambda: coop.set_tier(session["uid"], request.form.get("tier", "")))
    return redirect(url_for("coop.index"))


@bp.post("/invite")
@player_required
def invite():
    uid, friend = session["uid"], request.form.get("friend", "")
    lb = coop.lobby_of(uid)
    if lb and lb["host"] == str(uid) and friend in social.friends(uid):
        tier = coop.TIERS[lb["tier"]]["label"]
        social.notify(friend, "coop", f"{identity(uid)['name']} invites you to a {tier} co-op raid against "
                                      f"{coop.boss_view()['title']}. Code {lb['code']}.",
                      url_for("coop.index", join=lb["code"]))
        flash(f"Invite sent to {identity(friend)['name']}.", "ok")
    return redirect(url_for("coop.index"))


@bp.post("/start")
@player_required
def start():
    uid = session["uid"]
    try:
        lb = coop.check_start(uid)
    except GameError as e:
        flash(str(e), "error")
        return redirect(url_for("coop.index"))
    players = [m["uid"] for m in lb["members"]]
    try:
        with users_lock(*players):
            if any(load_fight(p) and not load_fight(p).finished for p in players):
                flash("Someone in the party is still in another fight.", "error")
                return redirect(url_for("coop.index"))
            db = get_db()
            stands, users = [], []
            for m in lb["members"]:
                user = db.get_user(m["uid"])
                char, _, _ = user.find_character_by_uuid(m["stand"]) if user else (None, None, None)
                if char is None:
                    flash(f"{m['name']}'s stand isn't in their collection any more.", "error")
                    return redirect(url_for("coop.index"))
                if m["stand"] in coop.used_today(user):
                    flash(f"{m['name']}'s {char.name} already raided today: they need to pick another stand.", "error")
                    return redirect(url_for("coop.index"))
                stands.append(char)
                users.append((user, m["stand"]))
            names = {m["uid"]: m["name"] for m in lb["members"]}
            boss = coop.boss_view()
            fight = Fight(Side("Raid party", fighting_copy(stands), True),
                          Side(f"{boss['title']} · {coop.TIERS[lb['tier']]['label']}", coop.crew(lb["tier"], len(stands)), False),
                          kind="coop", meta={"players": players, "owners": players, "names": names, "tier": lb["tier"],
                                             "stands": {m["uid"]: m["stand"] for m in lb["members"]}})
            fight.advance()
            coop.arm_timer(fight)
            for p in players:
                save_fight(p, fight)
            for user, uuid in users:  # each stand raids once a day, win or lose
                coop.mark_used(user, uuid)
                user.update()
            coop.close(lb)
    except Busy:
        flash("Someone in the party is busy. Try again in a moment.", "error")
        return redirect(url_for("coop.index"))
    for p in players:
        if p != str(uid):
            social.notify(p, "coop", f"The co-op raid against {boss['title']} has started!", url_for("coop.index"), toast=False)
    return redirect(url_for("coop.index"))


@bp.post("/attack")
@player_required
def attack():
    uid = session["uid"]
    fight = _fight(uid)
    if not fight:
        return "<p class='notice'>This raid is over. <a href='/coop'>Back to co-op</a></p>", 409
    players = fight.meta["players"]
    try:
        with users_lock(*players, ttl=5):
            fight = _fight(uid)
            if not fight:
                return "<p class='notice'>This raid is over. <a href='/coop'>Back to co-op</a></p>", 409
            coop.enforce_timer(fight)
            target = request.form.get("target", type=int)
            if not fight.finished and coop.owner(fight) == str(uid) and target is not None:
                fight.advance(target)
            coop.arm_timer(fight)
            if fight.finished and not fight.meta.get("settled"):
                fight.meta["settled"] = True
                db = get_db()
                users = {p: db.get_user(p) for p in players}
                fight.meta["rewards"] = coop.settle(fight, {p: u for p, u in users.items() if u})
                for u in users.values():
                    if u:
                        u.update()
            for p in players:
                current = load_fight(p)
                if current is not None and current.id == fight.id:  # not a player who already left the result
                    save_fight(p, fight)
    except Busy:
        fight = _fight(uid) or fight
    return _fight_view(fight, uid, request.form.get("log_len", type=int))


@bp.post("/fight/leave")
@player_required
def fight_leave():
    fight = _fight(session["uid"])
    if fight and fight.finished:
        clear_fight(session["uid"])
    return redirect(url_for("coop.index"))
