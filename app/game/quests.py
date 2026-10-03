import json
import random
import datetime

from typing import List, Optional
from app.game.items import Item, item_from_dict

import os
_DATA = os.path.join(os.path.dirname(__file__), "data")
with open(os.path.join(_DATA, "quests.json"), "r", encoding="utf-8") as f:
    ALL_QUESTS = json.load(f)["quests"]

QUEST_BY_ID = {q["id"]: q for q in ALL_QUESTS}

DEFAULT_QUEST_DATA = {
    "active_daily": [],
    "active_weekly": [],
    "active_permanent": [],
    "last_daily_reset": None,
    "last_weekly_reset": None,
    "completed_permanent": [],
}


def get_quest_data(user) -> dict:
    """Get quest data from user, initializing defaults if missing."""
    return user.quests


def story_progress(user) -> int:
    """Story stages cleared (read straight from the save: story.py imports this module's users)."""
    return int(user.data.get("web_story", {}).get("cleared", 0))


def unlocked(q: dict, user) -> bool:
    return (q["enabled"] and q["level_requirement"] <= user.level
            and q.get("story_requirement", 0) <= story_progress(user))


def daily_count(user) -> int:
    return 4


def weekly_count(user) -> int:
    return 3 if story_progress(user) < 11 else 4


def _pick_quests(category: str, count: int, user, exclude_ids: list = None) -> list:
    """Pick random quests from a category among those this player has unlocked."""
    exclude_ids = exclude_ids or []
    pool = [
        q for q in ALL_QUESTS
        if q["category"] == category
        and unlocked(q, user)
        and q["id"] not in exclude_ids
    ]
    picked = random.sample(pool, min(count, len(pool)))
    return [{"quest_id": q["id"], "progress": 0, "claimed": False} for q in picked]


def _needs_daily_reset(quest_data: dict) -> bool:
    now = datetime.datetime.now() + datetime.timedelta(hours=2)
    last = quest_data.get("last_daily_reset")
    if last is None or last == datetime.datetime.min:
        return True
    return now.date() > last.date()


def _needs_weekly_reset(quest_data: dict) -> bool:
    now = datetime.datetime.now() + datetime.timedelta(hours=2)
    last = quest_data.get("last_weekly_reset")
    if last is None or last == datetime.datetime.min:
        return True
    # Reset on Monday
    last_monday = last.date() - datetime.timedelta(days=last.weekday())
    now_monday = now.date() - datetime.timedelta(days=now.weekday())
    return now_monday > last_monday


def ensure_quests_assigned(user) -> None:
    """Lazy-assign daily/weekly/permanent quests if needed."""
    qd = user.quests
    now = datetime.datetime.now() + datetime.timedelta(hours=2)

    if _needs_daily_reset(qd):
        qd["active_daily"] = _pick_quests("daily", daily_count(user), user)
        qd["last_daily_reset"] = now

    if _needs_weekly_reset(qd):
        qd["active_weekly"] = _pick_quests("weekly", weekly_count(user), user)
        qd["last_weekly_reset"] = now

    # Permanent quests: assign all that aren't completed yet
    completed = set(qd.get("completed_permanent", []))
    permanent_pool = [
        q for q in ALL_QUESTS
        if q["category"] == "permanent"
        and unlocked(q, user)
        and q["id"] not in completed
    ]
    active_perm_ids = {p["quest_id"] for p in qd["active_permanent"]}
    fresh = [q for q in permanent_pool if q["id"] not in active_perm_ids]
    for q in fresh:
        qd["active_permanent"].append({"quest_id": q["id"], "progress": 0, "claimed": False})
    if fresh and active_perm_ids:  # not on a brand-new save
        _notify(user, f"New journey quest{'s' if len(fresh) > 1 else ''} unlocked: "
                      + ", ".join(q["name"] for q in fresh) + ".")


def locked_preview(user) -> Optional[dict]:
    """The next story stage that unlocks quests, and how many: {"stage", "count"}."""
    done = story_progress(user)
    later = [q.get("story_requirement", 0) for q in ALL_QUESTS
             if q["enabled"] and q.get("story_requirement", 0) > done]
    if not later:
        return None
    stage = min(later)
    return {"stage": stage, "count": sum(1 for s in later if s == stage), "total": len(later)}


def _notify(user, text: str):
    """Pop-up + inbox entry on the website; silently skipped outside it (simulations, scripts)."""
    try:
        from app.social import notify
        notify(str(user.id), "quest", text, "/quests")
    except Exception:
        pass


def track_quest_progress(user, action: str, count: int = 1) -> List[str]:
    """Increment progress on matching quests. Returns names of newly completed quests."""
    ensure_quests_assigned(user)
    qd = user.quests
    newly_completed = []

    for quest_list in [qd["active_daily"], qd["active_weekly"], qd["active_permanent"]]:
        for entry in quest_list:
            quest_def = QUEST_BY_ID.get(entry["quest_id"])
            if not quest_def:
                continue
            if quest_def["action"] != action:
                continue
            if entry["claimed"]:
                continue
            was_complete = entry["progress"] >= quest_def["target"]
            # reach_* quests record the best value so far (level, story stage, tower floor...)
            if action.startswith("reach_"):
                entry["progress"] = max(entry["progress"], min(count, quest_def["target"]))
            else:
                entry["progress"] = min(entry["progress"] + count, quest_def["target"])
            is_complete = entry["progress"] >= quest_def["target"]
            if is_complete and not was_complete:
                newly_completed.append(quest_def["name"])

    for name in newly_completed:
        _notify(user, f"Quest complete: {name}. Claim your reward!")
    return newly_completed


def claim_quest_reward(user, quest_id: int) -> Optional[dict]:
    """Claim a completed quest's reward. Returns reward info dict or None."""
    qd = user.quests
    quest_def = QUEST_BY_ID.get(quest_id)
    if not quest_def:
        return None

    for quest_list in [qd["active_daily"], qd["active_weekly"], qd["active_permanent"]]:
        for entry in quest_list:
            if entry["quest_id"] != quest_id:
                continue
            if entry["progress"] < quest_def["target"]:
                return None
            if entry["claimed"]:
                return None

            # Apply rewards
            rewards = quest_def["rewards"]
            user.fragments += rewards.get("fragments", 0)
            user.super_fragments += rewards.get("super_fragments", 0)
            user.xp += rewards.get("xp", 0)
            items_given = []
            for item_data in rewards.get("items", []):
                item = item_from_dict({"id": item_data["id"]})
                user.items.append(item)
                items_given.append(item)

            entry["claimed"] = True

            # Track permanent completion
            if quest_def["category"] == "permanent":
                if quest_id not in qd["completed_permanent"]:
                    qd["completed_permanent"].append(quest_id)

            return {
                "name": quest_def["name"],
                "fragments": rewards.get("fragments", 0),
                "super_fragments": rewards.get("super_fragments", 0),
                "xp": rewards.get("xp", 0),
                "items": items_given,
            }

    return None


def get_claimable_quests(user) -> list:
    """Return list of quest defs that are complete but not claimed."""
    ensure_quests_assigned(user)
    qd = user.quests
    claimable = []
    for quest_list in [qd["active_daily"], qd["active_weekly"], qd["active_permanent"]]:
        for entry in quest_list:
            quest_def = QUEST_BY_ID.get(entry["quest_id"])
            if not quest_def:
                continue
            if entry["progress"] >= quest_def["target"] and not entry["claimed"]:
                claimable.append(quest_def)
    return claimable
