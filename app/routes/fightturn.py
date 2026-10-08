"""The one request every PvE fight screen sends: pick a target (or surrender), let the AI
answer, settle the rewards once when the fight ends, and render the fight partial.

Each mode only supplies which fight kind it owns and how to pay out. Ranked/friend duels
and gang fights lock more than one save, so they keep their own handlers."""
from typing import Callable, Optional

from flask import render_template, request, session, url_for

from app.db import Busy, get_db, load_fight, save_fight, user_lock


def fun_achievements(user, fight, side: int = 0):
    """The silly ones: surrendering, a first-round win, and the Arrow's test failed."""
    from app.game import logic
    if getattr(fight, "forfeited", False):
        if fight.winner != side:
            logic.check_achievements(user, "surrender")
        return
    if fight.winner == side and getattr(fight, "round", 99) <= 1:
        logic.check_achievements(user, "one_round_win")
    meta = getattr(fight, "meta", None) or {}
    if getattr(fight, "kind", "") == "story" and fight.winner != side and int(meta.get("stage", -1)) == 0:
        logic.check_achievements(user, "story_first_loss")


def next_step(fight, my_side: int = 0) -> Optional[dict]:
    """The follow-up a finished fight offers next to "Back": {"label", "action" (endpoint), "fields"} or None.
    Every start endpoint it points at replaces a finished fight of its own kind."""
    if not fight or not fight.finished:
        return None
    won = fight.winner == my_side
    rewards, meta = fight.rewards or {}, fight.meta or {}
    kind = fight.kind
    if kind == "tower":
        climb = rewards.get("tower") or {}
        if won and climb and not climb.get("over"):
            return {"label": f"Climb to floor {climb['floor'] + 1} ▶", "action": "play.tower_start", "fields": {}}
    elif kind == "rush":
        from app.game import rush
        run = rewards.get("rush") or {}
        if won and run and not run.get("over"):
            return {"label": f"Next boss ({run['beaten'] + 1}/{len(rush.BOSSES)}) ▶", "action": "progress.rush_fight",
                    "fields": {}}
    elif kind == "story":
        from app.game import story
        k = int(meta.get("stage", 0))
        if won and k + 1 < story.TOTAL:
            return {"label": "Next stage ▶", "action": "progress.story_fight", "fields": {"stage": k + 1}}
        if not won:
            return {"label": "↻ Try again", "action": "progress.story_fight", "fields": {"stage": k}}
    elif kind in ("alt_universe", "over_heaven"):
        from app.game import altverse, overheaven
        key, j = meta.get("chapter" if kind == "alt_universe" else "track"), int(meta.get("stage", 0))
        steps = (altverse.BY_KEY.get(key) or {}).get("stages") if kind == "alt_universe" else             (overheaven.BY_KEY.get(key) or {}).get("fights")
        action = "progress.au_fight" if kind == "alt_universe" else "progress.oh_fight"
        field = "chapter" if kind == "alt_universe" else "track"
        if won and steps and j + 1 < len(steps):
            return {"label": "Next fight ▶", "action": action, "fields": {field: key, "stage": j + 1}}
        if not won and steps:
            return {"label": "↻ Try again", "action": action, "fields": {field: key, "stage": j}}
    elif kind == "training":
        return {"label": "Train again ▶", "action": "progress.training_fight",
                "fields": {"drill": meta.get("drill", "spar"), "uuid": list(meta.get("uuids", []))}}
    elif kind == "wormhole":
        return {"label": "Fight again ▶", "action": "play.mirror_start", "fields": {}}
    elif kind == "dummy":
        return {"label": "Practice again ▶", "action": "battles.dummy_start", "fields": {}}
    elif kind == "ranked":
        return {"label": "Queue again ▶", "action": "battles.leave", "fields": {"next": "ranked"}}
    return None


def play_turn(kind: str, back_url: str, label: str, action: str, leave: str,
              settle: Optional[Callable] = None):
    """settle(user, fight) -> rewards dict; called once, under the save lock, then saved."""
    uid = session["uid"]
    try:
        with user_lock(uid, ttl=5):
            fight = load_fight(uid)
            if fight is None or fight.kind != kind:
                return (f'<p class="notice">This {label.lower()} fight is no longer active. '
                        f'<a href="{back_url}">Back to the {label.lower()}</a></p>'), 409
            if not fight.finished:
                if request.form.get("forfeit"):
                    fight.forfeit()
                else:
                    fight.advance(request.form.get("target", type=int))
            if fight.finished and fight.rewards is None and settle:
                user = get_db().get_user(uid)
                fight.rewards = settle(user, fight)
                if fight.winner == fight.human_side and not getattr(fight, "forfeited", False):
                    from app.game import bounty, events
                    fight.rewards = events.pve_win(user, fight.rewards)
                    line = bounty.record_win(user, fight.sides[fight.human_side].chars)  # the weekly off-meta bounty
                    if line and fight.rewards is not None:
                        fight.rewards = {**fight.rewards, "bounty": line}
                fun_achievements(user, fight)
                user.update()
            save_fight(uid, fight)
    except Busy:
        fight = load_fight(uid)
    return render_template("partials/fight.html", fight=fight, fresh_from=request.form.get("log_len", type=int),
                           fight_action=url_for(action), fight_leave_action=url_for(leave), fight_label=label)
