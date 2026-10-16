"""The Stand Arrow Gauntlet (app/game/gauntlet.py): draft a team floor by floor, prototype items, a weekly ladder."""
from flask import Blueprint, flash, redirect, render_template, request, session, url_for

from app.auth import player_required
from app.db import Busy, clear_fight, get_db, load_fight, r, save_fight, user_lock
from app.game import gauntlet as GT
from app.game.character import CHARACTER_FILE
from app.game.fight import Fight, Side
from app.game.logic import GameError
from app.routes.fightturn import play_turn

bp = Blueprint("gauntlet", __name__, url_prefix="/gauntlet")
KIND = "gauntlet"


def _fight(uid):
    fight = load_fight(uid)
    return fight if fight and fight.kind == KIND else None


def _stand(stand_id: int) -> dict:
    s = CHARACTER_FILE[stand_id - 1]
    return {"id": stand_id, "name": s["name"], "rarity": s["rarity"], "special": s.get("special_description", "").replace("`", "")}


@bp.get("")
@player_required
def index():
    uid = session["uid"]
    user = get_db().get_user(uid)
    s = GT.state(user)
    run = s["run"]
    team = [{**_stand(m["id"]), "hp": m["hp"], "item": GT.item_view(m["item"]) if m.get("item") else None}
            for m in (run or {}).get("team", [])]
    deal = (run or {}).get("deal") or {}
    return render_template("gauntlet.html", u=user, s=s, run=run, team=team, GT=GT,
                           boon=GT.page_view("boon", deal.get("boon")), pact=GT.page_view("pact", deal.get("pact")),
                           boons=[GT.page_view("boon", b) for b in ((run or {}).get("boons") or []) if isinstance(b, str)],
                           pacts=[GT.page_view("pact", p) for p in (run or {}).get("pacts", [])],
                           offers=[_stand(i) for i in (run or {}).get("offers", [])],
                           items=[GT.item_view(k) for k in (run or {}).get("items", [])],
                           free=GT.free_run_left(user), best=int(s["best"].get(GT.week_key(), 0)),
                           board=GT.ladder(r()), fight=_fight(uid), floor_name=GT.floor_name,
                           fight_action=url_for("gauntlet.attack"), fight_leave_action=url_for("gauntlet.leave"),
                           fight_label="Gauntlet")


def _do(fn, ok=None):
    uid = session["uid"]
    if _fight(uid) and not _fight(uid).finished:
        flash("Finish the floor's fight first.", "busy")
        return redirect(url_for("gauntlet.index"))
    try:
        with user_lock(uid):
            user = get_db().get_user(uid)
            fn(user)
            user.update()
            if ok:
                flash(ok, "ok")
    except GameError as e:
        flash(str(e), "error")
    except Busy:
        flash("Your last action is still running.", "error")
    return redirect(url_for("gauntlet.index"))


def _int(name):
    try:
        return int(request.form.get(name, ""))
    except ValueError:
        return None


@bp.post("/start")
@player_required
def start():
    return _do(GT.start)


@bp.post("/pick")
@player_required
def pick():
    return _do(lambda user: GT.pick(user, _int("stand") or 0, _int("replace")))


@bp.post("/page")
@player_required
def page():
    """Keep the team: take Rohan's boon or sign his pact."""
    which = request.form.get("which", "")
    return _do(lambda user: GT.take_page(user, which), "Rohan writes it into your story." if which == "boon" else "The pact is signed.")


@bp.post("/item")
@player_required
def item():
    return _do(lambda user: GT.give_item(user, request.form.get("item", ""), _int("slot") if _int("slot") is not None else -1))


@bp.post("/abandon")
@player_required
def abandon():
    return _do(GT.abandon, "Run over. The prototypes go back to the lab.")


@bp.post("/fight")
@player_required
def fight():
    """The current floor's fight."""
    uid = session["uid"]
    existing = load_fight(uid)
    if existing and not existing.finished:
        flash("Finish your current fight first.", "busy")
        return redirect(url_for("gauntlet.index"))
    try:
        with user_lock(uid):
            user = get_db().get_user(uid)
            run = GT.state(user)["run"]
            if not run or run.get("over") or run["phase"] != "ready" or not run["team"]:
                flash("Pick for this floor first.", "error")
                return redirect(url_for("gauntlet.index"))
            mine = Side(session.get("name", "You"), GT.team(run), True, session.get("avatar"))
            floor = run["floor"]
            foes = Side(f"Chapter {floor} · {GT.floor_name(floor)}", GT.enemies(floor, run["week"]), False)
            rules = GT.pact_rules(run)
            meta = {"floor": floor, **({"rules": rules, "rules_label": "📖 Pact"} if rules else {})}
            f = Fight(mine, foes, kind=KIND, meta=meta)
            GT.carry_wounds(f.sides[f.human_side].chars)
            GT.prepare_fight(run, f.sides[f.human_side].chars, f.sides[1 - f.human_side].chars)
            f.advance()
            save_fight(uid, f)
    except Busy:
        flash("Your last action is still running.", "error")
    return redirect(url_for("gauntlet.index"))


def _settle(user, fight):
    return GT.finish(user, fight, r(), session.get("name", "?"))


@bp.post("/attack")
@player_required
def attack():
    return play_turn(KIND, url_for("gauntlet.index"), "Gauntlet", "gauntlet.attack", "gauntlet.leave", _settle)


@bp.post("/leave")
@player_required
def leave():
    f = _fight(session["uid"])
    if f and f.finished:
        clear_fight(session["uid"])
    return redirect(url_for("gauntlet.index"))
