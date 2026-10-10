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
    elif kind == "puzzle":
        if not won:
            fields = {"s": list(meta.get("picks", [])), "mode": meta.get("mode", "daily")}
            fields.update({f"g{k}": v for k, v in (meta.get("gear") or {}).items()})
            return {"label": "↻ Try again", "action": "progress.pz_fight", "fields": fields}
    elif kind == "carry_me":
        from app.game import carryme
        k = int(meta.get("stage", 0))
        if won and k + 1 < carryme.TOTAL:
            return {"label": "Next scene ▶", "action": "progress.cm_fight", "fields": {"stage": k + 1}}
        if not won:
            return {"label": "↻ Try again", "action": "progress.cm_fight", "fields": {"stage": k, "form": meta.get("form", "")}}
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


# The page each kind of fight is played on (and the arguments that bring the right tab or chapter back).
RESUME = {
    "story": ("progress.story_page", None), "alt_universe": ("progress.au_page", ("ch", "chapter")),
    "over_heaven": ("progress.oh_page", ("t", "track")), "carry_me": ("progress.cm_page", None),
    "puzzle": ("progress.pz_page", ("tab", "mode")), "training": ("progress.training_page", None),
    "rush": ("progress.rush_page", None), "tower": ("play.tower", None), "wormhole": ("play.mirror", None),
    "dungeon": ("play.dungeon", None), "coop": ("coop.index", None), "gang_war": ("gangs.fight_page", None),
    "gang_raid": ("gangs.fight_page", None), "dummy": ("battles.index", None), "ranked": ("battles.index", None),
    "friend": ("battles.index", None),
}
LABELS = {"wormhole": "Mirror World", "alt_universe": "Alternate Universe", "over_heaven": "Over Heaven",
          "carry_me": "Carry Me", "gang_war": "gang war", "gang_raid": "gang raid", "coop": "co-op raid",
          "dummy": "practice", "friend": "duel"}


def resume(uid=None) -> Optional[dict]:
    """{url, label} of the player's unfinished fight, for the "Back to your fight" buttons (None: no fight on)."""
    from flask import session
    from app.db import load_fight
    uid = uid or session.get("uid")
    fight = load_fight(uid) if uid else None
    if not fight or fight.finished or fight.kind not in RESUME:
        return None
    endpoint, arg = RESUME[fight.kind]
    kwargs = {}
    if arg and (fight.meta or {}).get(arg[1]):
        kwargs[arg[0]] = fight.meta[arg[1]]
    return {"url": url_for(endpoint, **kwargs) + "#fight", "label": LABELS.get(fight.kind, fight.kind.replace("_", " ")),
            "kind": fight.kind}


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
                    line = bounty.record_win(user, [c for c in fight.sides[fight.human_side].chars if not getattr(c, "guest", False)])  # the weekly off-meta bounty
                    if line and fight.rewards is not None:
                        fight.rewards = {**fight.rewards, "bounty": line}
                fun_achievements(user, fight)
                user.update()
            save_fight(uid, fight)
    except Busy:
        fight = load_fight(uid)
    return render_template("partials/fight.html", fight=fight, fresh_from=request.form.get("log_len", type=int),
                           fight_action=url_for(action), fight_leave_action=url_for(leave), fight_label=label)
