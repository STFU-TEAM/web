"""The one request every PvE fight screen sends: pick a target (or surrender), let the AI
answer, settle the rewards once when the fight ends, and render the fight partial.

Each mode only supplies which fight kind it owns and how to pay out. Ranked/friend duels
and gang fights lock more than one save, so they keep their own handlers."""
from typing import Callable, Optional

from flask import render_template, request, session, url_for

from app.db import Busy, get_db, load_fight, save_fight, user_lock


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
                user.update()
            save_fight(uid, fight)
    except Busy:
        fight = load_fight(uid)
    return render_template("partials/fight.html", fight=fight, fresh_from=request.form.get("log_len", type=int),
                           fight_action=url_for(action), fight_leave_action=url_for(leave), fight_label=label)
