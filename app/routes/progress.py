"""Story mode and achievements (bot /story, /achievements)."""
from flask import Blueprint, current_app, flash, redirect, render_template, request, session, url_for

from app.auth import player_required
from app.db import Busy, clear_fight, get_db, load_fight, r, save_fight, user_lock
from app.game import altverse, logic, progression, rush, story, training
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


CLEARED_TTL = 600  # the nav's copy of story progress; refreshed on every story win, re-read after this


def _cleared_key(uid) -> str:
    return f"web:story_cleared:{uid}"


def remember_cleared(uid, cleared: int) -> None:
    r().set(_cleared_key(uid), int(cleared), ex=CLEARED_TTL)


def _cleared(uid) -> int:
    """Stages cleared, from a small cached count instead of the whole save on every page."""
    raw = r().get(_cleared_key(uid))
    if raw is not None:
        return int(raw)
    user = get_db().get_user(uid)
    cleared = story.cleared(user) if user else 0
    remember_cleared(uid, cleared)
    return cleared


def unlocks(uid) -> dict:
    """Which story-gated modes the player has opened: {"wormhole": bool, "tower": bool, "ranked": bool, ...}
    (app/game/progression.py)."""
    opened = progression.opened(_cleared(uid))
    for key in progression.forced(uid) & opened.keys():  # an admin's debug unlock
        opened[key] = True
    return opened


def _skip() -> tuple:
    return () if current_app.config.get("DUNGEON_ENABLED") else ("dungeon",)


@bp.before_app_request
def progression_gate():
    """Story-gated modes: turn locked players away from their entry pages, and clear a mode's "New" tag
    once the player opens it."""
    uid = session.get("uid")
    ep = request.endpoint or ""
    page = progression.PAGES.get(ep) or ("ranked" if ep == "battles.index" and request.args.get("mode") == "ranked" else None)
    gate = progression.ENTRY.get(ep)
    if not uid or not (page or gate):
        return None
    opened = unlocks(uid)
    if gate and not opened[gate]:
        flash(f"{progression.LABELS[gate]} opens as you progress: {progression.requirement(gate).lower()}.", "error")
        return redirect(url_for("progress.story_page"))
    if page and opened[page] and request.method == "GET":
        progression.seen(uid, page)
    return None


@bp.post("/unlocks/dismiss")
@player_required
def unlocks_dismiss():
    progression.dismiss(session["uid"])
    return redirect(request.referrer or url_for("main.home"))


def _story_ctx(user, fight=None, error=None):
    from app.game import gates
    done = story.cleared(user)
    return {"u": user, "fight": fight, "journey": story.journey(user), "stage": story.current(user),
            "gate": gates.story(user, done) if done < story.TOTAL else None,
            "cleared": story.cleared(user), "total": story.TOTAL, "error": error,
            "next_unlock": progression.next_unlock(story.cleared(user), _skip()),
            "auto_max": AUTO_REPLAYS,
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
    before = story.cleared(user)
    rewards = story.win(user, int(fight.meta["stage"]))
    remember_cleared(user.id, story.cleared(user))  # may open new modes in the nav
    progression.announce(user.id, before, story.cleared(user), _skip())
    logic.track_quest_progress(user, "reach_story", story.cleared(user))
    from app import social
    social.referral_progress(str(user.id), story.cleared(user))
    return rewards


AUTO_REPLAYS = 5  # the most one "Auto-replay" runs


@bp.post("/story/auto")
@player_required
def story_auto():
    """Replay a cleared stage up to AUTO_REPLAYS times in one go: the team fights on its own (the smart AI picks),
    each replay costs its energy and pays like a normal replay."""
    uid = session["uid"]
    existing = load_fight(uid)
    if existing and not existing.finished:
        flash("Finish the fight you're in first.", "error")
        return redirect(url_for("progress.story_page"))
    k, n = request.form.get("stage", type=int), max(1, min(AUTO_REPLAYS, request.form.get("count", 1, type=int)))
    try:
        with user_lock(uid):
            user = get_db().get_user(uid)
            if k is None or not 0 <= k < story.cleared(user):
                flash("Pick a stage you've already cleared.", "error")
                return redirect(url_for("progress.story_page"))
            stage = story.STAGES[k]
            from app.game import bounty
            won = played = dust = stand_xp = 0
            for _ in range(n):
                try:
                    story.check_can_fight(user, k)  # spends the replay's energy
                except GameError as e:
                    if not played:
                        flash(str(e), "error")
                    break
                foes = Side(stage["title"], story.enemy_team(k), False)
                foes.ai = story.ai_level(k)
                me = Side(session.get("name", "You"), fighting_copy(user.main_characters), False, parts=True)  # still your team
                fight = Fight(me, foes, kind="story", meta={"stage": k, "auto": True})
                fight.advance()
                played += 1
                if fight.winner == 0:
                    rewards = _story_settle(user, fight)
                    bounty.record_win(user, fight.sides[0].chars)
                    won += 1
                    dust += rewards.get("fragments", 0)
                    stand_xp += rewards.get("stand_xp", 0)
            user.update()
    except Busy:
        flash("Your last action is still running.", "error")
        return redirect(url_for("progress.story_page"))
    if played:
        flash(f"⏩ {stage['title']} ×{played}: {won} won · +{dust:,} Meteor Dust · +{stand_xp} XP for each stand · "
              f"{user.energy}⚡ left.", "ok" if won else "error")
    return redirect(url_for("progress.story_page"))


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
    fight = _au_fight(uid)
    if not fight and not any(altverse.unlocked(user, c["key"]) for c in altverse.CHAPTERS):
        flash("The Alternate Universe opens when you beat DIO at the end of Part 3.", "error")
        return redirect(url_for("progress.story_page"))
    other = load_fight(uid)
    error = f"Finish your {other.kind.replace('_', ' ')} fight first." if other and other.kind != AU_KIND and not other.finished else None
    chosen = request.args.get("ch") or (fight.meta.get("chapter") if fight else None)
    from app.game import gates
    stage = altverse.current(user, chosen)
    return render_template("alt_universe.html", u=user, fight=fight, error=error, chapters=altverse.chapters(user),
                           stage=stage, cleared=altverse.total_cleared(user), au_level=gates.au_level,
                           gate=gates.au(user, stage["chapter"], stage["index"]) if stage else None,
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
            from app.game.items import TORN_DIARY_PAGE, item_from_dict
            facing = altverse.has_over_heaven(key, j)
            if facing and not any(i.id == TORN_DIARY_PAGE for i in user.items):
                # the first time DIO stands Over Heaven, the Arrow hands over a page of his diary (bound, never drops)
                user.items.append(item_from_dict({"id": TORN_DIARY_PAGE}))
                flash("📖 The Arrow tears a page from DIO's diary and gives it to you: while you hold it, "
                      "The World Over Heaven fights as an ordinary stand.", "ok")
            sealed = any(i.id == TORN_DIARY_PAGE for i in user.items)
            foes = Side(f"AU · {stage['title']}", altverse.enemy_team(key, j, sealed=sealed), False)
            fight = Fight(Side(session.get("name", "You"), fighting_copy(user.main_characters), True, session.get("avatar")),
                          foes, kind=AU_KIND, meta={"chapter": key, "stage": j})
            if facing and sealed:
                fight._log("📖 The Torn Diary Page burns: The World Over Heaven loses Heaven and fights as an "
                           "ordinary stand.", "terrain")
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
# Over Heaven: the endgame puzzle fights, one track per PvE mode (app/game/overheaven.py)
# --------------------------------------------------------------------------- #
OH_KIND = "over_heaven"


def _oh_fight(uid):
    fight = load_fight(uid)
    return fight if fight and fight.kind == OH_KIND else None


@bp.get("/over-heaven")
@player_required
def oh_page():
    from app.game import overheaven
    from app.game.resonance import RESONANCES, active as lit
    uid = session["uid"]
    user = get_db().get_user(uid)
    fight = _oh_fight(uid)
    if not fight and not overheaven.unlocked(user):
        flash("Over Heaven opens once you finish the story.", "error")
        return redirect(url_for("progress.story_page"))
    other = load_fight(uid)
    error = f"Finish your {other.kind.replace('_', ' ')} fight first." if other and other.kind != OH_KIND and not other.finished else None
    tracks = overheaven.tracks(user)
    shown = request.args.get("t") or (fight.meta.get("track") if fight else None) or tracks[0]["key"]
    track = next((t for t in tracks if t["key"] == shown), tracks[0])
    return render_template("over_heaven.html", u=user, fight=fight, error=error, tracks=tracks, track=track,
                           unlocked=overheaven.unlocked(user), cleared=overheaven.total_cleared(user),
                           total=overheaven.TOTAL, resonances=[RESONANCES[k] for k in lit(user.main_characters)],
                           replay_energy=overheaven.REPLAY_ENERGY, title=overheaven.TITLE,
                           fight_action=url_for("progress.oh_attack"), fight_leave_action=url_for("progress.oh_leave"),
                           fight_label="Over Heaven")


@bp.post("/over-heaven/fight")
@player_required
def oh_fight():
    from app.game import overheaven
    uid = session["uid"]
    key = request.form.get("track", "")
    existing = load_fight(uid)
    if existing and not (existing.kind == OH_KIND and existing.finished):
        return redirect(url_for("progress.oh_page", t=key))
    try:
        with user_lock(uid):
            user = get_db().get_user(uid)
            j = request.form.get("stage", type=int)
            j = overheaven.cleared(user, key) if j is None and key in overheaven.BY_KEY else (j or 0)
            try:
                overheaven.check_can_fight(user, key, j)
            except GameError as e:
                flash(str(e), "error")
                return redirect(url_for("progress.oh_page", t=key))
            rules = overheaven.BY_KEY[key]["fights"][j]["rules"]
            fight = Fight(Side(session.get("name", "You"), fighting_copy(user.main_characters), True, session.get("avatar")),
                          Side(overheaven.foe_name(key, j), overheaven.enemy_team(key, j), False),
                          kind=OH_KIND, meta={"track": key, "stage": j, "rules": rules})
            fight.advance()
            save_fight(uid, fight)
            user.update()  # replays spend energy
    except Busy:
        flash("Your last action is still running.", "error")
    return redirect(url_for("progress.oh_page", t=key))


def _oh_settle(user, fight):
    from app.game import overheaven
    if fight.winner != 0:
        return {"won": False, "fragments": 0, "xp": 0, "stand_xp": 0, "item": None}
    logic.track_quest_progress(user, "fight_win")
    logic.check_achievements(user, "fight_win")
    return overheaven.win(user, fight.meta["track"], int(fight.meta["stage"]))


@bp.post("/over-heaven/attack")
@player_required
def oh_attack():
    return play_turn(OH_KIND, url_for("progress.oh_page"), "Over Heaven", "progress.oh_attack", "progress.oh_leave",
                     _oh_settle)


@bp.post("/over-heaven/leave")
@player_required
def oh_leave():
    fight = _oh_fight(session["uid"])
    key = fight.meta.get("track") if fight else None
    if fight and fight.finished:
        clear_fight(session["uid"])
    return redirect(url_for("progress.oh_page", t=key) if key else url_for("progress.oh_page"))


# --------------------------------------------------------------------------- #
# Part 10 · Carry Me: Joyce Joestar's story (app/game/carryme.py)
# --------------------------------------------------------------------------- #
CM_KIND = "carry_me"
JOYCE_AVATAR = "img/mascot-face.webp"


def _cm_fight(uid):
    fight = load_fight(uid)
    return fight if fight and fight.kind == CM_KIND else None


@bp.get("/carry-me")
@player_required
def cm_page():
    from app.game import carryme
    uid = session["uid"]
    user = get_db().get_user(uid)
    fight = _cm_fight(uid)
    if not fight and not carryme.unlocked(user):
        flash("Joyce's story opens once you finish the main story.", "error")
        return redirect(url_for("progress.story_page"))
    other = load_fight(uid)
    error = f"Finish your {other.kind.replace('_', ' ')} fight first." if other and other.kind != CM_KIND and not other.finished else None
    from app.game import gates
    done = carryme.cleared(user)
    return render_template("carry_me.html", u=user, fight=fight, error=error, acts=carryme.acts(user),
                           gate=gates.carry_me(user, done) if done < carryme.TOTAL else None, act_levels=gates.CARRY_ME,
                           stage=carryme.current(user), cleared=min(carryme.cleared(user), carryme.TOTAL),
                           total=carryme.TOTAL, lineage=carryme.lineage(user), resolve=carryme.resolve(user),
                           choices=[carryme.form_view(f) for f in carryme.forms(user)], title=carryme.TITLE,
                           replay_energy=carryme.REPLAY_ENERGY,
                           fight_action=url_for("progress.cm_attack"), fight_leave_action=url_for("progress.cm_leave"),
                           fight_label="Carry Me")


@bp.post("/carry-me/fight")
@player_required
def cm_fight():
    from app.game import carryme
    uid = session["uid"]
    existing = load_fight(uid)
    if existing and not (existing.kind == CM_KIND and existing.finished):
        return redirect(url_for("progress.cm_page"))
    try:
        with user_lock(uid):
            user = get_db().get_user(uid)
            k = request.form.get("stage", type=int)
            k = carryme.cleared(user) if k is None else k
            try:
                carryme.check_can_fight(user, k)
            except GameError as e:
                flash(str(e), "error")
                return redirect(url_for("progress.cm_page"))
            form = carryme.form_for(user, k, request.form.get("form", type=int))
            stage = carryme.STAGES[k]
            team = fighting_copy(user.main_characters) + [carryme.guest(form, k)]
            fight = Fight(Side(session.get("name", "You"), team, True, url_for("static", filename=JOYCE_AVATAR)),
                          Side(f"Carry Me · {stage['title']}", carryme.enemy_team(k), False),
                          kind=CM_KIND, meta={"stage": k, "form": form, **({"rules": stage["rules"]} if stage["rules"] else {})})
            fight._log(f"🎭 Joyce Joestar steps in. Carry Me remembers {stage['jojo']}: {team[-1].name}.", "terrain")
            fight.advance()
            save_fight(uid, fight)
            user.update()  # replays spend energy
    except Busy:
        flash("Your last action is still running.", "error")
    return redirect(url_for("progress.cm_page"))


def _cm_settle(user, fight):
    from app.game import carryme
    if fight.winner != 0:
        return {"won": False, "fragments": 0, "xp": 0, "stand_xp": 0, "item": None}
    logic.track_quest_progress(user, "fight_win")
    logic.check_achievements(user, "fight_win")
    return carryme.win(user, int(fight.meta["stage"]))


@bp.post("/carry-me/attack")
@player_required
def cm_attack():
    return play_turn(CM_KIND, url_for("progress.cm_page"), "Carry Me", "progress.cm_attack", "progress.cm_leave",
                     _cm_settle)


@bp.post("/carry-me/leave")
@player_required
def cm_leave():
    fight = _cm_fight(session["uid"])
    if fight and fight.finished:
        clear_fight(session["uid"])
    return redirect(url_for("progress.cm_page"))


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


# --------------------------------------------------------------------------- #
# Training ground: fast stand XP once the story and the AU are done (app/game/training.py)
# --------------------------------------------------------------------------- #
def _training_fight(uid):
    fight = load_fight(uid)
    return fight if fight and fight.kind == "training" else None


@bp.get("/training")
@player_required
def training_page():
    uid = session["uid"]
    user = get_db().get_user(uid)
    other = load_fight(uid)
    error = f"Finish your {other.kind.replace('_', ' ')} fight first." if other and other.kind != "training" and not other.finished else None
    from app.game import pickers
    team = {c.uuid for c in user.main_characters}
    stands = pickers.owned(user.main_characters + user.storage_characters,
                           note=lambda c: "maxed: ascend it first" if c.level >= 100 else ("team" if c.uuid in team else None))
    return render_template("training.html", u=user, fight=_training_fight(uid), error=error,
                           unlocked=training.unlocked(user), progress=training.progress(user), stand_options=stands,
                           drills=training.DRILLS,
                           team_max=training.TEAM_MAX, loss_share=round(training.LOSS_SHARE * 100),
                           fight_action=url_for("progress.training_attack"),
                           fight_leave_action=url_for("progress.training_leave"), fight_label="Training ground")


@bp.post("/training/fight")
@player_required
def training_fight():
    uid = session["uid"]
    existing = load_fight(uid)
    if existing and not (existing.kind == "training" and existing.finished):
        flash("Finish your current fight first.", "error")
        return redirect(url_for("progress.training_page"))
    drill = request.form.get("drill", "")
    uuids = request.form.getlist("uuid")

    def start(user):
        team, foes = training.start(user, uuids, drill)
        d = training.DRILLS[drill]
        fight = Fight(Side(session.get("name", "You"), fighting_copy(team), True, session.get("avatar")),
                      Side(f"{d['icon']} {d['label']}", foes, False), kind="training",
                      meta={"drill": drill, "uuids": [c.uuid for c in team]})
        fight.advance()
        save_fight(uid, fight)

    _act(start)
    return redirect(url_for("progress.training_page"))


def _training_settle(user, fight):
    rewards = training.settle(user, fight)
    if rewards["won"]:
        logic.track_quest_progress(user, "fight_win")
        logic.check_achievements(user, "fight_win")
    return rewards


@bp.post("/training/attack")
@player_required
def training_attack():
    return play_turn("training", url_for("progress.training_page"), "Training ground", "progress.training_attack",
                     "progress.training_leave", _training_settle)


@bp.post("/training/leave")
@player_required
def training_leave():
    fight = _training_fight(session["uid"])
    if fight and fight.finished:
        clear_fight(session["uid"])
    return redirect(url_for("progress.training_page"))


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
