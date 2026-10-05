"""Story mode and achievements (bot /story, /achievements)."""
from flask import Blueprint, flash, redirect, render_template, request, session, url_for

from app.auth import player_required
from app.db import Busy, clear_fight, get_db, load_fight, r, save_fight, user_lock
from app.game import altverse, logic, rush, story
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
    from app import social
    social.referral_progress(str(user.id), story.cleared(user))
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
# Alternate Universe: custom "what if" chapters (app/game/altverse.py)
# --------------------------------------------------------------------------- #
AU_KIND = "alt_universe"


def _au_fight(uid):
    fight = load_fight(uid)
    return fight if fight and fight.kind == AU_KIND else None


@bp.get("/alternate-universe")
@player_required
def au_page():
    uid = session["uid"]
    user = get_db().get_user(uid)
    other = load_fight(uid)
    error = f"Finish your {other.kind.replace('_', ' ')} fight first." if other and other.kind != AU_KIND and not other.finished else None
    fight = _au_fight(uid)
    chosen = request.args.get("ch") or (fight.meta.get("chapter") if fight else None)
    return render_template("alt_universe.html", u=user, fight=fight, error=error, chapters=altverse.chapters(user),
                           stage=altverse.current(user, chosen), cleared=altverse.total_cleared(user),
                           total=altverse.TOTAL, story_cleared=story.cleared(user),
                           fight_action=url_for("progress.au_attack"), fight_leave_action=url_for("progress.au_leave"),
                           fight_label="Alternate Universe")


@bp.post("/alternate-universe/fight")
@player_required
def au_fight():
    uid = session["uid"]
    key = request.form.get("chapter", "")
    existing = load_fight(uid)
    if existing and not (existing.kind == AU_KIND and existing.finished):
        return redirect(url_for("progress.au_page", ch=key))
    try:
        with user_lock(uid):
            user = get_db().get_user(uid)
            j = request.form.get("stage", type=int)
            j = altverse.cleared(user, key) if j is None else j
            try:
                altverse.check_can_fight(user, key, j)
            except GameError as e:
                flash(str(e), "error")
                return redirect(url_for("progress.au_page", ch=key))
            stage = altverse.BY_KEY[key]["stages"][j]
            foes = Side(f"AU · {stage['title']}", altverse.enemy_team(key, j), False)
            fight = Fight(Side(session.get("name", "You"), fighting_copy(user.main_characters), True, session.get("avatar")),
                          foes, kind=AU_KIND, meta={"chapter": key, "stage": j})
            fight.advance()
            save_fight(uid, fight)
            user.update()  # replays spend energy
    except Busy:
        flash("Your last action is still running.", "error")
    return redirect(url_for("progress.au_page", ch=key))


def _au_settle(user, fight):
    if fight.winner != 0:
        return {"won": False, "fragments": 0, "xp": 0, "stand_xp": 0, "item": None}
    logic.track_quest_progress(user, "fight_win")
    logic.check_achievements(user, "fight_win")
    return altverse.win(user, fight.meta["chapter"], int(fight.meta["stage"]))


@bp.post("/alternate-universe/attack")
@player_required
def au_attack():
    return play_turn(AU_KIND, url_for("progress.au_page"), "Alternate Universe", "progress.au_attack",
                     "progress.au_leave", _au_settle)


@bp.post("/alternate-universe/leave")
@player_required
def au_leave():
    fight = _au_fight(session["uid"])
    key = fight.meta.get("chapter") if fight else None
    if fight and fight.finished:
        clear_fight(session["uid"])
    return redirect(url_for("progress.au_page", ch=key) if key else url_for("progress.au_page"))


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
    rows.sort(key=lambda a: (a["unlocked"], a["secret"] and not a["unlocked"], -a["progress"] / max(1, a["target"])))
    return render_template("achievements.html", u=user, rows=rows,
                           unlocked=sum(a["unlocked"] for a in rows))


# --------------------------------------------------------------------------- #
# Limited-time events
# --------------------------------------------------------------------------- #
@bp.get("/events")
@player_required
def events_page():
    from app.game import events
    user = get_db().get_user(session["uid"])
    ev = events.current(r())
    return render_template("events.html", u=user, ev=ev, E=events, next_ev=None if ev else events.upcoming(r()),
                           tokens=events.tokens(user, ev), shop=events.shop_view(user, ev) if ev else [],
                           boosted=sorted(events.boosted_ids(ev)) if ev else [], now=logic.now())


@bp.post("/events/buy")
@player_required
def events_buy():
    from app.game import events
    got = _act(lambda u: events.buy(u, events.current(r()), request.form.get("key", "")))
    if got:
        flash(f"🎟️ Exchanged: {got}.", "ok")
    return redirect(url_for("progress.events_page"))


# --------------------------------------------------------------------------- #
# Stand Dex (collection sets) and titles
# --------------------------------------------------------------------------- #
@bp.get("/dex")
@player_required
def dex_page():
    from app.filters import PLAYABLE
    from app.game import dex
    uid = session["uid"]
    user = get_db().get_user(uid)
    before = list(user.data.get("web_dex") or [])
    sets = dex.view(user)
    if user.data.get("web_dex") != before:  # remember newly owned stands (a quick save, skipped if busy)
        try:
            with user_lock(uid, ttl=5):
                fresh = get_db().get_user(uid)
                dex.seen(fresh)
                fresh.update()
        except Busy:
            pass
    known = set(user.data.get("web_dex") or [])
    return render_template("dex.html", u=user, sets=sets, shown=request.args.get("set", ""), known=known, D=dex,
                           stands={c["id"]: c for c in PLAYABLE}, total_known=len(known), total=len(PLAYABLE))


@bp.post("/dex/claim")
@player_required
def dex_claim():
    from app.game import dex
    s = _act(lambda u: dex.claim(u, request.form.get("key", "")))
    if s:
        extra = f" and the title “{s['title']}”" if s["title"] else ""
        flash(f"{s['name']} complete: {dex.reward_text(s['reward'])}{extra}.", "ok")
    return redirect(url_for("progress.dex_page", set=request.form.get("key", "")))


@bp.post("/titles")
@player_required
def choose_title():
    from app.game import mastery, titles
    title = request.form.get("title", "")
    if _act(lambda u: titles.choose(u, title, mastery.titles(r(), u.id)) or True):
        flash(f"Your title is now “{title}”." if title else "Title hidden.", "ok")
    return redirect(url_for("main.profile", uid=session["uid"]))
