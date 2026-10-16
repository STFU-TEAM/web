"""D'Arby's gambling den (app/game/den.py): the coin glass against D'Arby or a friend, for Meteor Dust."""
from flask import Blueprint, Response, flash, redirect, render_template, request, session, url_for

from app import social
from app.auth import player_required
from app.db import Busy, get_db, identity, r, user_lock, users_lock
from app.game import den as D
from app.game.logic import GameError

bp = Blueprint("den", __name__, url_prefix="/den")
QUOTES = {
    "idle": "Good! Shall we begin? Your stake, if you please.",
    "playing": "Steady hands… the glass is waiting.",
    "won": "Hmph… a lucky glass. Again, if you dare.",
    "lost": "Good! GOOD! Your dust is mine.",
}


def _finish(game):
    """Pay out a game that just ended (once), each player's save under its lock."""
    if not game or game["state"] not in ("over", "declined", "expired") or game.get("paid") is not None:
        return game
    try:
        with users_lock(*game["players"], ttl=5):
            db = get_db()
            users = {uid: db.get_user(uid) for uid in game["players"]}
            if D.settle(r(), game, users):
                for uid, user in users.items():
                    if user:
                        user.update()
                if game["state"] == "over" and game["mode"] == "pvp":
                    for i, uid in enumerate(game["players"]):
                        won = game["winner"] == i
                        social.notify(uid, "den", (f"🪙 {game['names'][1 - i]} spilled the glass: you win {2 * game['stake']:,} dust!"
                                                   if won else f"🪙 You spilled the glass against {game['names'][1 - i]}."),
                                      url_for("den.index"), toast=False, push=False)
    except Busy:
        pass  # the next look at the table settles it
    return D.get(r(), game["id"]) or game


def _table(uid, game=None):
    game = game if game is not None else D.active(r(), uid)
    if game:
        game = _finish(D.timeout(r(), game))
    return D.view(r(), game, uid)


def _quote(t):
    if not t:
        return QUOTES["idle"]
    if t["state"] == "over":
        return QUOTES["won" if t["won"] else "lost"] if t["mode"] == "darby" else ""
    return QUOTES["playing"]


@bp.get("")
@player_required
def index():
    uid = session["uid"]
    user = get_db().get_user(uid)
    t = _table(uid, D.get(r(), request.args.get("game", "")) if request.args.get("game") else None)
    friends = [{"id": f, "name": identity(f).get("name") or "A friend"} for f in social.friends(uid)][:30]
    return render_template("den.html", t=t, u=user, today=D.today(r(), uid), cool=D.cooling(r(), uid), D=D,
                           friends=friends, blocked=D.blocked(r(), user) if not (t and t["state"] in ("playing", "waiting")) else None,
                           quote=_quote(t))


@bp.get("/table")
@player_required
def table():
    """The polled table (PvP): 286 stops the polling once the glass is settled."""
    uid = session["uid"]
    gid = request.args.get("game", "")
    t = _table(uid, D.get(r(), gid) if gid else None)
    html = render_template("partials/den_table.html", t=t, D=D, quote=_quote(t))
    return Response(html, status=286) if not t or t["state"] not in ("playing", "waiting") else html


def _act(fn):
    """Run fn(user) under the player's lock; errors become a flash. Returns the game or None."""
    uid = session["uid"]
    try:
        with user_lock(uid, ttl=5):
            user = get_db().get_user(uid)
            game = fn(user)
            user.update()
            return game
    except GameError as e:
        flash(str(e), "error")
    except Busy:
        flash("Busy, try again.", "error")
    return None


def _stake():
    try:
        return int(request.form.get("stake", 0))
    except ValueError:
        return 0


@bp.post("/start")
@player_required
def start():
    _act(lambda user: D.start_darby(r(), user, _stake()))
    return redirect(url_for("den.index"))


@bp.post("/challenge")
@player_required
def challenge_friend():
    uid, other = session["uid"], request.form.get("friend", "")
    if not social.are_friends(uid, other):
        flash("You can only challenge your friends.", "error")
        return redirect(url_for("den.index"))
    name = identity(other).get("name") or "your friend"
    game = _act(lambda user: D.challenge(r(), user, other, name, _stake()))
    if game:
        social.notify(other, "den", f"🪙 {game['names'][0]} challenges you to the coin glass for {game['stake']:,} dust.",
                      url_for("den.index"))
    return redirect(url_for("den.index"))


@bp.post("/accept/<gid>")
@player_required
def accept(gid):
    _act(lambda user: D.accept(r(), user, gid))
    return redirect(url_for("den.index"))


@bp.post("/decline/<gid>")
@player_required
def decline(gid):
    game = D.decline(r(), session["uid"], gid)
    if game:
        _finish(game)
    return redirect(url_for("den.index"))


@bp.post("/drop")
@player_required
def drop():
    uid = session["uid"]
    gid = request.form.get("game", "")
    try:
        n = int(request.form.get("n", 1))
    except ValueError:
        n = 1
    try:
        game = D.play(r(), uid, gid, n)
    except GameError as e:
        game = D.get(r(), gid)
        if request.headers.get("HX-Request"):
            t = _table(uid, game)
            return render_template("partials/den_table.html", t=t, D=D, quote=_quote(t), error=str(e))
        flash(str(e), "error")
        return redirect(url_for("den.index"))
    t = _table(uid, game)
    if request.headers.get("HX-Request"):
        return render_template("partials/den_table.html", t=t, D=D, quote=_quote(t))
    return redirect(url_for("den.index", game=gid))
