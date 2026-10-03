"""Story mode and achievements (bot /story, /achievements)."""
from flask import Blueprint, flash, redirect, render_template, request, session, url_for

from app.auth import player_required
from app.db import Busy, clear_fight, get_db, load_fight, r, save_fight, user_lock
from app.game import logic, rush, story
from app.game.fight import Fight, Side, fighting_copy
from app.routes.fightturn import play_turn
from app.game.achievements import get_all_achievements_status
from app.game.logic import GameError

bp = Blueprint("progress", __name__)


def _act(fn):
    try:
        with user_lock(session["uid"]):
            user = get_db().get_user(session["uid"])
            try:
                result = fn(user)
            except GameError as e:
                flash(str(e), "error")
                return None
            user.update()
            return result
    except Busy:
        flash("Your last action is still running.", "error")
        return None


def _story_ctx(user, fight=None, error=None):
    return {"u": user, "fight": fight, "journey": story.journey(user), "stage": story.current(user),
            "cleared": story.cleared(user), "total": story.TOTAL, "error": error,
            "fight_action": url_for("progress.story_attack"),
            "fight_leave_action": url_for("progress.story_leave"), "fight_label": "Story"}


def _story_fight(uid):
    fight = load_fight(uid)
    return fight if fight and fight.kind == "story" else None


@bp.get("/story")
@player_required
def story_page():
    uid = session["uid"]
    user = get_db().get_user(uid)
    other = load_fight(uid)
    error = f"Finish your {other.kind.replace('_', ' ')} fight first." if other and other.kind != "story" and not other.finished else None
    if story.cleared(user) >= story.TOTAL:
        r().set(f"web:story_done:{uid}", 1)
    return render_template("story.html", **_story_ctx(user, _story_fight(uid), error))


@bp.post("/story/fight")
@player_required
def story_fight():
    uid = session["uid"]
    existing = load_fight(uid)
    if existing and not (existing.kind == "story" and existing.finished):
        return redirect(url_for("progress.story_page"))
    try:
        with user_lock(uid):
            user = get_db().get_user(uid)
            k = request.form.get("stage", type=int)
            k = story.cleared(user) if k is None else k
            try:
                story.check_can_fight(user, k)
            except GameError as e:
                flash(str(e), "error")
                return redirect(url_for("progress.story_page"))
            stage = story.STAGES[k]
            foes = Side(stage["title"], story.enemy_team(k), False)
            foes.ai = story.ai_level(k)
            fight = Fight(Side(session.get("name", "You"), fighting_copy(user.main_characters), True, session.get("avatar")),
                          foes, kind="story", meta={"stage": k})
            fight.advance()
            save_fight(uid, fight)
            user.update()  # replays spend energy
    except Busy:
        flash("Your last action is still running.", "error")
    return redirect(url_for("progress.story_page"))


def _story_settle(user, fight):
    if fight.winner != 0:
        return {"won": False, "fragments": 0, "xp": 0, "stand_xp": 0, "item": None}
    logic.track_quest_progress(user, "fight_win")
    logic.check_achievements(user, "fight_win")
    logic.track_quest_progress(user, "story_win")
    rewards = story.win(user, int(fight.meta["stage"]))
    logic.track_quest_progress(user, "reach_story", story.cleared(user))
    return rewards


@bp.post("/story/attack")
@player_required
def story_attack():
    return play_turn("story", url_for("progress.story_page"), "Story", "progress.story_attack", "progress.story_leave",
                     _story_settle)

@bp.post("/story/leave")
@player_required
def story_leave():
    fight = _story_fight(session["uid"])
    if fight and fight.finished:
        clear_fight(session["uid"])
        if fight.winner == 0 and story.cleared(get_db().get_user(session["uid"])) >= story.TOTAL:
            r().set(f"web:story_done:{session['uid']}", 1)
    return redirect(url_for("progress.story_page"))


# --------------------------------------------------------------------------- #
# Weekly boss rush
# --------------------------------------------------------------------------- #
def _rush_fight(uid):
    fight = load_fight(uid)
    return fight if fight and fight.kind == "rush" else None


@bp.get("/rush")
@player_required
def rush_page():
    uid = session["uid"]
    user = get_db().get_user(uid)
    s = rush.state(user)
    return render_template("rush.html", u=user, s=s, bosses=rush.bosses(), fight=_rush_fight(uid),
                           ran_today=rush.ran_today(user), board=rush.leaderboard(r()), ends_in=rush.ends_in(),
                           patch_up=round(rush.PATCH_UP * 100), fight_action=url_for("progress.rush_attack"),
                           fight_leave_action=url_for("progress.rush_leave"), fight_label="Boss rush")


@bp.post("/rush/fight")
@player_required
def rush_fight():
    """Start today's run, or the next boss of a run in progress."""
    uid = session["uid"]
    existing = load_fight(uid)
    if existing and not existing.finished:
        flash("Finish your current fight first.", "error")
        return redirect(url_for("progress.rush_page"))
    try:
        with user_lock(uid):
            user = get_db().get_user(uid)
            try:
                if not rush.state(user).get("run"):
                    rush.start_run(user)
                index = rush.state(user)["run"]["index"]
                team = rush.prepare_team(user, fighting_copy(user.main_characters))
            except GameError as e:
                flash(str(e), "error")
                return redirect(url_for("progress.rush_page"))
            foes = Side(f"Boss {index + 1} · {rush.bosses()[index]['title']}", rush.enemies(index), False)
            fight = Fight(Side(session.get("name", "You"), team, True, session.get("avatar")), foes,
                          kind="rush", meta={"index": index})
            fight.advance()
            save_fight(uid, fight)
            user.update()
    except Busy:
        flash("Your last action is still running.", "error")
    return redirect(url_for("progress.rush_page"))


def _rush_settle(user, fight):
    rewards = rush.finish_fight(user, fight, r(), session.get("name", "?"))
    if rewards["won"]:
        logic.track_quest_progress(user, "rush_boss")
        logic.track_quest_progress(user, "reach_rush", rewards.get("rush", {}).get("beaten", 0))
    return rewards


@bp.post("/rush/attack")
@player_required
def rush_attack():
    return play_turn("rush", url_for("progress.rush_page"), "Boss rush", "progress.rush_attack", "progress.rush_leave",
                     _rush_settle)


@bp.post("/rush/leave")
@player_required
def rush_leave():
    fight = _rush_fight(session["uid"])
    if fight and fight.finished:
        clear_fight(session["uid"])
    return redirect(url_for("progress.rush_page"))


@bp.post("/tour/done")
@player_required
def tour_done():
    r().delete(f"web:tour:{session['uid']}")
    return "", 204


@bp.get("/achievements")
@player_required
def achievements():
    user = get_db().get_user(session["uid"])
    rows = get_all_achievements_status(user)
    rows.sort(key=lambda a: (a["unlocked"], -a["progress"] / max(1, a["target"])))
    return render_template("achievements.html", u=user, rows=rows,
                           unlocked=sum(a["unlocked"] for a in rows))
