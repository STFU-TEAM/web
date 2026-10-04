"""The Crusaders' Journey: idle trips down the Part 3 road (app/game/journey.py)."""
import time

from flask import Blueprint, flash, redirect, render_template, request, session, url_for

from app.auth import player_required
from app.db import Busy, get_db, user_lock
from app.game import journey as J
from app.game.logic import GameError
from app.routes.trades import sorted_stands

bp = Blueprint("journey", __name__, url_prefix="/journey")


def _act(fn):
    try:
        with user_lock(session["uid"]):
            user = get_db().get_user(session["uid"])
            result = fn(user)
            user.update()
            return result
    except GameError as e:
        flash(str(e), "error")
    except Busy:
        flash("Your last action is still running.", "error")
    return None


@bp.get("")
@player_required
def index():
    user = get_db().get_user(session["uid"])
    stands = sorted_stands(user)
    pick = request.args.get("uuid") or (stands[0].uuid if stands else None)
    chosen = next((c for c in stands if c.uuid == pick), stands[0] if stands else None)
    power = J.power_of(chosen) if chosen else 0
    return render_template("journey.html", u=user, trips=J.view(user), stands=stands, chosen=chosen, power=power,
                           routes=[{**r, "est": J.estimate(r, power)} for r in J.ROUTES], slots=J.SLOTS,
                           powers={c.uuid: J.power_of(c) for c in stands}, server_now=time.time())


@bp.post("/depart")
@player_required
def depart():
    trip = _act(lambda u: J.depart(u, request.form.get("uuid", ""), request.form.get("route", "")))
    if trip:
        route = J.BY_KEY[trip["route"]]
        flash(f"{route['emoji']} Your stand sets out for {route['name']}. Back in {J.fmt_hours(route['hours'])}.", "ok")
    return redirect(url_for("journey.index"))


@bp.post("/<trip_id>/claim")
@player_required
def claim(trip_id):
    res = _act(lambda u: J.claim(u, trip_id))
    if res:
        extra = [f"{res['fragments']:,} Meteor Dust", f"+{res['stand_xp']} XP"] + res["items"]
        if res["super"]:
            extra.append("1 Arrowhead")
        flash(f"{res['stand'].name} is home from {res['route']}: {', '.join(extra)}.", "ok")
    return redirect(url_for("journey.index"))


@bp.post("/<trip_id>/recall")
@player_required
def recall(trip_id):
    stand = _act(lambda u: J.recall(u, trip_id))
    if stand:
        flash(f"{stand.name} turned back early. No loot this time.", "ok")
    return redirect(url_for("journey.index"))
