"""The home page's "Today" card: every timer and daily allowance in one place, what's ready first.

Each row: {key, icon, title, detail, ready, endpoint, args}. Rows for modes the player hasn't opened yet
(app/game/progression.py) are left out.
"""
import datetime
from typing import List

from app.game import coop, dungeon, journey, logic, progression, story, tower
from app.game.logic import fmt_delta


def rows(user, dungeon_on: bool = True) -> List[dict]:
    opened = progression.opened(story.cleared(user))
    out = []

    def add(key, icon, title, detail, ready, endpoint, **args):
        out.append({"key": key, "icon": icon, "title": title, "detail": detail, "ready": bool(ready),
                    "endpoint": endpoint, "args": args})

    full_in = logic.energy_refill_in(user)
    add("energy", "⚡", f"Energy {user.energy}/{user.total_energy}",
        "Full: spend it before it caps" if full_in is None else f"Full in {fmt_delta(full_in)}",
        full_in is None, "progress.story_page")

    hours = logic.DONOR_ADV_WAIT_TIME + (not user.is_donator()) * logic.NORMAL_ADV_WAIT_TIME
    daily = logic.cooldown_left(user.last_adventure, hours)
    streak = logic.streak(user)
    add("daily", "🎁", "Daily reward", "Ready to claim" + (f" · streak day {streak['next_day']}" if streak["count"] else "")
        if daily is None else f"Back in {fmt_delta(daily)}", daily is None, "play.quests")

    claimable = len(logic.get_claimable_quests(user))
    add("quests", "☑", "Quests", f"{claimable} ready to claim" if claimable else "Nothing to claim yet", claimable,
        "play.quests")

    if opened["wormhole"]:
        mirror = logic.cooldown_left(user.last_wormhole, logic.wormhole_wait(user))
        add("mirror", "🪞", "Mirror World", "The mirror is open" if mirror is None else f"Opens in {fmt_delta(mirror)}",
            mirror is None, "play.mirror")

    trips = journey.view(user)
    home = sum(t["done"] for t in trips)
    if home:
        detail = f"{home} stand{'s' if home > 1 else ''} back home"
    elif trips:
        detail = f"Next one home in {fmt_delta(datetime.timedelta(seconds=min(t['left'] for t in trips)))}"
    else:
        detail = f"{journey.SLOTS} free slots: send a stand on the road"
    add("journey", "🐫", "Crusaders' Journey", detail, home or len(trips) < journey.SLOTS, "journey.index")

    if opened["dungeon"] and dungeon_on:
        left = dungeon.runs_left(user)
        add("dungeon", "▦", "Dungeon", f"{left} run{'s' if left != 1 else ''} left today" if left else "Done for today",
            left, "play.dungeon")

    if opened["tower"]:
        best = tower.state(user)["best"]
        add("tower", "▲", "Tower", f"Best this week: floor {best} · resets in {fmt_delta(tower.ends_in())}", False,
            "play.tower")

    wins = coop.wins_left(user)
    add("coop", "🤝", "Co-op raid", f"{wins} paid win{'s' if wins != 1 else ''} left today" if wins else "Paid wins done today",
        False, "coop.index")

    from app.game import bounty
    b = bounty.view(user)
    add("bounty", b["icon"], f"Bounty: {b['name']}",
        "Claimed this week" if b["claimed"] else ("Done: claim it" if b["done"] else f"{b['progress']}/{b['goal']} · {b['short']}"),
        b["done"] and not b["claimed"], "play.quests", _anchor="bounty")

    out.sort(key=lambda row: not row["ready"])  # what's ready first, otherwise the order above
    return out


def ready_count(user) -> int:
    return sum(r["ready"] for r in rows(user))
