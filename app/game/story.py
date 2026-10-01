"""Story mode, ported from the bot's models/gameobjects/story.py and extensions/story.py.

Progress lives in user.story_progress, shared with the bot:
    {current_chapter, current_step, completed_steps: ["<ch>_<step>"], rewards_claimed: [...]}
current_chapter == -1 means the story is finished.
"""
import datetime
import json
import os

from app.game.items import item_file, item_from_dict
from app.game.logic import GameError

with open(os.path.join(os.path.dirname(__file__), "data", "story.json"), encoding="utf-8") as _f:
    CHAPTERS = json.load(_f)["chapters"]
CHAPTER_BY_ID = {c["id"]: c for c in CHAPTERS}
TOTAL_STEPS = sum(len(c["steps"]) for c in CHAPTERS)

# Where to go to satisfy each step requirement on the web.
ACTION_LINKS = {
    "check_has_character": ("play.team", "Open your team"),
    "check_fight_test": ("battles.index", "Fight the training dummy"),
    "check_daily": ("play.team", "Claim your daily reward"),
}


def current_step(user):
    """(chapter, step, index) or (None, None, None) once the story is complete."""
    progress = user.story_progress
    chapter = CHAPTER_BY_ID.get(progress["current_chapter"])
    if not chapter:
        return None, None, None
    for i, step in enumerate(chapter["steps"]):
        if step["id"] == progress["current_step"]:
            return chapter, step, i
    return None, None, None


def action_met(user, step) -> bool:
    action = step.get("action")
    if not action:
        return True
    if action == "check_has_character":
        return len(user.main_characters) > 0
    if action == "check_fight_test":
        return user.achievement_data.get("counters", {}).get("fight_win", 0) > 0
    if action == "check_daily":
        return user.last_adventure != datetime.datetime.min
    return True


def reward_text(step) -> list:
    reward = step.get("reward") or {}
    parts = []
    if reward.get("fragments"):
        parts.append(f"{reward['fragments']} fragments")
    counts = {}
    for item_id in reward.get("items", []):
        counts[item_id] = counts.get(item_id, 0) + 1
    for item_id, n in counts.items():
        parts.append(f"{n} × {item_file[item_id - 1]['name']}" if n > 1 else item_file[item_id - 1]["name"])
    return parts


def advance(user) -> dict:
    """Claim the current step's reward (once) and move on. Mirrors the bot's story_next button."""
    chapter, step, idx = current_step(user)
    if not chapter:
        raise GameError("You've finished every chapter written so far.")
    if not action_met(user, step):
        raise GameError(f"First: {step.get('action_label', 'complete this step')}.")
    progress = user.story_progress
    key = f"{chapter['id']}_{step['id']}"
    claimed = []
    if step.get("reward") and key not in progress["rewards_claimed"]:
        reward = step["reward"]
        user.fragments += reward.get("fragments", 0)
        for item_id in reward.get("items", []):
            user.items.append(item_from_dict({"id": item_id}))
        progress["rewards_claimed"].append(key)
        claimed = reward_text(step)
    if key not in progress["completed_steps"]:
        progress["completed_steps"].append(key)
    steps = chapter["steps"]
    if idx + 1 < len(steps):
        progress["current_step"] = steps[idx + 1]["id"]
    elif chapter["id"] + 1 in CHAPTER_BY_ID:
        nxt = CHAPTER_BY_ID[chapter["id"] + 1]
        progress["current_chapter"], progress["current_step"] = nxt["id"], nxt["steps"][0]["id"]
    else:
        progress["current_chapter"] = progress["current_step"] = -1
    return {"claimed": claimed}


def back(user):
    progress = user.story_progress
    chapter = CHAPTER_BY_ID.get(progress["current_chapter"])
    if not chapter:  # finished: step back into the last chapter
        last = CHAPTERS[-1]
        progress["current_chapter"], progress["current_step"] = last["id"], last["steps"][-1]["id"]
        return
    steps = chapter["steps"]
    idx = next((i for i, s in enumerate(steps) if s["id"] == progress["current_step"]), 0)
    if idx > 0:
        progress["current_step"] = steps[idx - 1]["id"]
    elif chapter["id"] - 1 in CHAPTER_BY_ID:
        prev = CHAPTER_BY_ID[chapter["id"] - 1]
        progress["current_chapter"], progress["current_step"] = prev["id"], prev["steps"][-1]["id"]


def chapter_rows(user) -> list:
    done = set(user.story_progress["completed_steps"])
    return [{"chapter": c, "done": sum(f"{c['id']}_{s['id']}" in done for s in c["steps"]),
             "total": len(c["steps"]), "current": user.story_progress["current_chapter"] == c["id"]}
            for c in CHAPTERS]
