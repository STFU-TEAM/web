import json

from typing import List, Optional
from app.game.items import item_from_dict

import os
_DATA = os.path.join(os.path.dirname(__file__), "data")
with open(os.path.join(_DATA, "achievements.json"), "r", encoding="utf-8") as f:
    ALL_ACHIEVEMENTS = json.load(f)["achievements"]

from app.game.economy import scale_rewards  # noqa: E402  (rewards at the economy's pace: one-time milestones)
for _ach in ALL_ACHIEVEMENTS:
    _ach["reward"] = scale_rewards(_ach.get("reward") or {})

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

    # Update counter for this action (reach_* record the best value)
    if action.startswith("reach_"):
        counters[action] = max(counters.get(action, 0), count)
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
            user.super_fragments += reward.get("super_fragments", 0)
            for item_data in reward.get("items", []):
                item = item_from_dict({"id": item_data["id"]})
                user.items.append(item)
            # Also add to the legacy achievements list
            if ach["id"] not in user.achievements:
                user.achievements.append(ach["id"])
            _notify(user, ach)

    ach_data["unlocked"] = list(unlocked)
    return newly_unlocked


def _notify(user, ach: dict):
    """A pop-up on the website; skipped outside it (simulations, scripts)."""
    try:
        from app.social import notify
        notify(str(user.id), "achievement", f"{ach['emoji']} Achievement unlocked: {ach['name']}!", "/achievements")
    except Exception:
        pass


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
        hidden = ach.get("secret") and ach["id"] not in unlocked
        result.append({
            "id": ach["id"],
            "name": "???" if hidden else ach["name"],
            "description": ("Secret. Hint: " + ach.get("hint", "keep playing")) if hidden else ach["description"],
            "emoji": "❔" if hidden else ach["emoji"],
            "secret": bool(ach.get("secret")),
            "target": ach["target"],
            "progress": min(progress, ach["target"]),
            "unlocked": ach["id"] in unlocked,
            "reward": ach["reward"],
        })
    return result
