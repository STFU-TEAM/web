"""Trade offers between players."""
from flask import Blueprint, flash, redirect, render_template, request, session, url_for

from app.accounts import resolve_player
from app.auth import player_required
from app.db import Busy, get_db, identity, r, users_lock
from app.game import trades as T
from app.game.logic import GameError

bp = Blueprint("trades", __name__, url_prefix="/trades")


def _grouped_items(user):
    counts = {}
    for it in user.items:
        counts.setdefault(it.id, [it, 0])[1] += 1
    return sorted(counts.values(), key=lambda x: x[0].name)


RARITY_RANK = {"R": 0, "SR": 1, "SSR": 2, "UR": 3, "LR": 4}


def sorted_stands(user):
    return sorted(user.main_characters + user.storage_characters,
                  key=lambda c: (-RARITY_RANK.get(c.rarity, 0), -c.level, c.name))


def _view(offer, db):
    sender, receiver = db.get_user(offer["from"]), db.get_user(offer["to"])
    return {**offer, "from_name": identity(offer["from"])["name"], "to_name": identity(offer["to"])["name"],
            "give_view": T.describe(sender, offer["give"]), "want_view": T.describe(receiver, offer["want"])}


@bp.get("")
@player_required
def index():
    db = get_db()
    uid = session["uid"]
    return render_template("trades.html",
                           incoming=[_view(o, db) for o in T.listing(r(), uid, "in")],
                           outgoing=[_view(o, db) for o in T.listing(r(), uid, "out")])


@bp.get("/new")
@player_required
def new():
    db = get_db()
    me = db.get_user(session["uid"])
    other_id = resolve_player(request.args.get("with", ""))
    if request.args.get("with") and not other_id:
        flash("No player found with that username or Discord ID.", "error")
    if other_id == me.id:
        flash("You can't trade with yourself.", "error")
        other_id = None
    other = db.get_user(other_id) if other_id else None
    return render_template("trade_new.html", u=me, other=other, other_name=identity(other_id)["name"] if other else None,
                           my_items=_grouped_items(me), my_stands=sorted_stands(me),
                           their_stands=sorted_stands(other) if other else [], their_items=_grouped_items(other) if other else [],
                           query=request.args.get("with", ""))


@bp.post("/new")
@player_required
def create():
    other_id = resolve_player(request.form.get("with", ""))
    if not other_id:
        flash("That player doesn't exist.", "error")
        return redirect(url_for("trades.new"))
    give, want = T.parse_side(request.form, "give"), T.parse_side(request.form, "want")
    try:
        me = get_db().get_user(session["uid"])
        T.create(r(), me, other_id, give, want)
        flash(f"Offer sent to {identity(other_id)['name']}. Nothing moves until they accept.", "ok")
        return redirect(url_for("trades.index"))
    except GameError as e:
        flash(str(e), "error")
        return redirect(url_for("trades.new", **{"with": other_id}))


@bp.post("/<offer_id>/<verb>")
@player_required
def respond(offer_id, verb):
    uid = session["uid"]
    offer = T.get(r(), offer_id)
    if not offer or uid not in (offer["from"], offer["to"]):
        flash("That offer is gone.", "error")
        return redirect(url_for("trades.index"))
    if verb in ("decline", "cancel"):
        T.close(r(), offer)
        flash("Offer declined." if verb == "decline" else "Offer cancelled.", "ok")
    elif verb == "accept" and uid == offer["to"]:
        try:
            with users_lock(offer["from"], offer["to"]):
                offer = T.get(r(), offer_id)
                if not offer:
                    raise GameError("That offer was just withdrawn.")
                db = get_db()
                sender, receiver = db.get_user(offer["from"]), db.get_user(offer["to"])
                T.accept(sender, receiver, offer)
                sender.update()
                receiver.update()
                T.close(r(), offer)
                flash("Trade complete. New stands are in your storage.", "ok")
        except GameError as e:
            flash(str(e), "error")
        except Busy:
            flash("One of you is busy with another action. Try again.", "error")
    return redirect(url_for("trades.index"))
