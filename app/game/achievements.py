import json

from typing import List, Optional
from app.game.items import item_from_dict

import os
_DATA = os.path.join(os.path.dirname(__file__), "data")
with open(os.path.join(_DATA, "achievements.json"), "r", encoding="utf-8") as f:
    ALL_ACHIEVEMENTS = json.load(f)["achievements"]

ACHIEVEMENT_BY_ID = {a["id"]: a for a in ALL_ACHIEVEMENTS}

DEFAULT_ACHIEVEMENT_DATA = {
    "unlocked": [],
    "counters": {},
}


def check_achievements(user, action: str, count: int = 1) -> List[dict]:
    """Check and unlock achievements based on an action.

    Returns list of newly unlocked achievement defs.
    """
    ach_data = user.achievement_data
    unlocked = set(ach_data.get("unlocked", []))
    counters = ach_data.get("counters", {})

    # Update counter for this action
    if action == "reach_level":
        counters[action] = count
    else:
        counters[action] = counters.get(action, 0) + count

    ach_data["counters"] = counters
    newly_unlocked = []

    for ach in ALL_ACHIEVEMENTS:
        if ach["id"] in unlocked:
            continue
        if ach["action"] != action:
            continue
        if counters.get(action, 0) >= ach["target"]:
            unlocked.add(ach["id"])
            newly_unlocked.append(ach)
            # Apply rewards
            reward = ach["reward"]
            user.fragments += reward.get("fragments", 0)
            user.super_fragements += reward.get("super_fragments", 0)
            for item_data in reward.get("items", []):
                item = item_from_dict({"id": item_data["id"]})
                user.items.append(item)
            # Also add to the legacy achievements list
            if ach["id"] not in user.achievements:
                user.achievements.append(ach["id"])

    ach_data["unlocked"] = list(unlocked)
    return newly_unlocked


def get_all_achievements_status(user) -> List[dict]:
    """Return all achievements with their unlock status for display."""
    ach_data = user.achievement_data
    unlocked = set(ach_data.get("unlocked", []))
    counters = ach_data.get("counters", {})
    result = []
    for ach in ALL_ACHIEVEMENTS:
        progress = counters.get(ach["action"], 0)
        if ach["action"] == "reach_level":
            progress = counters.get("reach_level", 0)
        result.append({
            "id": ach["id"],
            "name": ach["name"],
            "description": ach["description"],
            "emoji": ach["emoji"],
            "target": ach["target"],
            "progress": min(progress, ach["target"]),
            "unlocked": ach["id"] in unlocked,
            "reward": ach["reward"],
        })
    return result
