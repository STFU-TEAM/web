"""Story mode and achievements (bot /story, /achievements)."""
from flask import Blueprint, flash, redirect, render_template, session, url_for

from app.auth import player_required
from app.db import Busy, get_db, user_lock
from app.game import story
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


@bp.get("/story")
@player_required
def story_page():
    user = get_db().get_user(session["uid"])
    chapter, step, idx = story.current_step(user)
    link = story.ACTION_LINKS.get(step.get("action")) if step else None
    return render_template("story.html", u=user, chapter=chapter, step=step, idx=idx,
                           met=story.action_met(user, step) if step else True,
                           reward=story.reward_text(step) if step else [],
                           already_claimed=bool(step) and f"{chapter['id']}_{step['id']}" in user.story_progress["rewards_claimed"],
                           link=link, chapters=story.chapter_rows(user),
                           done=len(user.story_progress["completed_steps"]), total=story.TOTAL_STEPS)


@bp.post("/story/next")
@player_required
def story_next():
    res = _act(story.advance)
    if res and res["claimed"]:
        flash("Reward: " + ", ".join(res["claimed"]) + ".", "ok")
    return redirect(url_for("progress.story_page"))


@bp.post("/story/back")
@player_required
def story_back():
    _act(story.back)
    return redirect(url_for("progress.story_page"))


@bp.get("/achievements")
@player_required
def achievements():
    user = get_db().get_user(session["uid"])
    rows = get_all_achievements_status(user)
    rows.sort(key=lambda a: (a["unlocked"], -a["progress"] / max(1, a["target"])))
    return render_template("achievements.html", u=user, rows=rows,
                           unlocked=sum(a["unlocked"] for a in rows))
