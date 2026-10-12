"""A new player's first week: the Beginner's path (guided first goals, each paying once) and the Welcome week
(a gift a day for the first 7 days of a new save).

The path reads the save itself (stands owned, team size, story stages...), so a step done before it existed still
counts. Only Mirror World needs a mark (data["web_path_flags"]["mirror"], set when a fight starts there).
The welcome week is only for saves begun after it was added (logic.begin starts it): 7 claims, one per calendar
day, within WELCOME_WINDOW days of the start.

Save: data["web_path"] = [step keys claimed]
      data["web_welcome"] = {"start": ISO date, "claimed": n, "last": ISO date or None}
"""
import datetime
from typing import List, Optional

from app.game.logic import GameError, now

# key, title, how to do it, where (endpoint, kwargs), reward, done(user)
def _owned(u):
    return len(u.main_characters) + len(u.storage_characters)


def _story(u):
    from app.game import story
    return story.cleared(u)


PATH = [
    ("summon", "Summon your first stands", "Pull a 10-stand batch on any banner.", ("play.banners", {}),
     {"fragments": 200}, lambda u: _owned(u) >= 5),
    ("team", "Build a team of three", "Put your three best stands in your team.", ("play.team", {}),
     {"fragments": 300}, lambda u: len(u.main_characters) >= 3),
    ("story1", "Win your first story fight", "The Arrow's Test, stage 1 of the story.", ("progress.story_page", {}),
     {"items": [47]}, lambda u: _story(u) >= 1),
    ("mirror", "Fight in the Mirror World", "Your team against its own reflection: the best XP for your energy.",
     ("play.mirror", {}), {"fragments": 300}, lambda u: bool((u.data.get("web_path_flags") or {}).get("mirror"))),
    ("daily", "Claim a daily reward", "A gift every day; keep the streak for bigger ones.", ("main.home", {}),
     {"items": [47]}, lambda u: bool((u.data.get("web_streak") or {}).get("last"))),
    ("gear", "Equip an item", "Give a team stand an item from your bag.", ("play.items", {}),
     {"fragments": 400, "items": [1]}, lambda u: any(c.items for c in u.main_characters)),
    ("level20", "Train a stand to level 20", "Every fight trains your team; fusing copies trains faster.", ("play.team", {}),
     {"fragments": 500}, lambda u: any(c.level >= 20 for c in u.main_characters + u.storage_characters)),
    ("part3", "Beat DIO's Mansion", "Finish the story's first part: it opens ranked and the Alternate Universe.",
     ("progress.story_page", {}), {"super": 1}, lambda u: _story(u) >= 6),
    ("gang", "Join or found a gang", "Raid, chat and climb the gang ladder together.", ("gangs.index", {}),
     {"fragments": 500}, lambda u: bool(getattr(u, "gang_id", None))),
    ("level10", "Reach player level 10", "Player XP comes from every fight, quests and the dungeon.", ("play.quests", {}),
     {"fragments": 1000, "items": [2]}, lambda u: u.level >= 10),
]
PATH_DONE = {"super": 1, "title": "Rookie Stand User"}  # every step claimed
BY_KEY = {p[0]: p for p in PATH}

WELCOME = [  # day 1..7 of a new save's first week
    {"super": 2, "fragments": 500},
    {"items": [2], "fragments": 800},
    {"items": [47, 47], "fragments": 1000},
    {"super": 1, "items": [38, 39, 40]},
    {"items": [2, 2], "fragments": 1500},
    {"super": 2, "fragments": 2000},
    {"super": 3, "items": [2], "title": "Welcome Week"},
]
WELCOME_WINDOW = 14


def mark(user, flag: str):
    flags = user.data.setdefault("web_path_flags", {})
    flags[flag] = 1


def reward_lines(r: dict) -> List[str]:
    from app.game.items import item_file
    out = []
    if r.get("super"):
        out.append(f"{r['super']} Arrowhead{'s' if r['super'] > 1 else ''}")
    if r.get("fragments"):
        out.append(f"{r['fragments']:,} Meteor Dust")
    counts = {}
    for i in r.get("items", []):
        counts[i] = counts.get(i, 0) + 1
    out += [f"{item_file[i - 1]['name']}{f' ×{n}' if n > 1 else ''}" for i, n in counts.items()]
    if r.get("title"):
        out.append(f"the title “{r['title']}”")
    return out


def _pay(user, r: dict) -> List[str]:
    from app.game import titles
    from app.game.items import item_from_dict
    user.fragments += r.get("fragments", 0)
    user.super_fragments += r.get("super", 0)
    user.items.extend(item_from_dict({"id": i}) for i in r.get("items", []))
    if r.get("title"):
        titles.grant(user, r["title"])
    return reward_lines(r)


# ── The Beginner's path ─────────────────────────────────────────────────

def path(user) -> Optional[dict]:
    """The path as the home page draws it, or None once it's finished and its last reward paid."""
    claimed = set(user.data.get("web_path") or [])
    if len(claimed) >= len(PATH) and "done" in claimed:
        return None
    steps = []
    for key, title, how, (ep, kw), reward, done in PATH:
        steps.append({"key": key, "title": title, "how": how, "endpoint": ep, "kwargs": kw, "reward": reward_lines(reward),
                      "done": bool(done(user)), "claimed": key in claimed})
    nxt = next((s for s in steps if not s["done"]), None)
    return {"steps": steps, "next": nxt, "claimed": sum(s["claimed"] for s in steps), "total": len(steps),
            "ready": [s for s in steps if s["done"] and not s["claimed"]],
            "finished": all(s["claimed"] for s in steps), "final": reward_lines(PATH_DONE)}


def claim_step(user, key: str) -> List[str]:
    claimed = user.data.setdefault("web_path", [])
    if key == "done":
        if not all(k in claimed for k in BY_KEY):
            raise GameError("Finish every step of the path first.")
        if "done" in claimed:
            raise GameError("Already claimed.")
        claimed.append("done")
        return _pay(user, PATH_DONE)
    step = BY_KEY.get(key)
    if not step:
        raise GameError("That step doesn't exist.")
    if key in claimed:
        raise GameError("Already claimed.")
    if not step[5](user):
        raise GameError(f"Not done yet: {step[2]}")
    claimed.append(key)
    return _pay(user, step[4])


# ── The coach: the first session, one step at a time ────────────────────
# A new save walks: the first pull -> the team (what it is, how to build it) -> the first story fight (and where to
# look when lost). Each step is a card on the page it's about; data["web_coach"] holds the step ("done" once over).
COACH_STEPS = ("pull", "team", "story", "done")


def coach(user) -> Optional[str]:
    """The coach's step for this save, or None (older saves, or the guide is over)."""
    step = user.data.get("web_coach")
    return step if step in COACH_STEPS[:-1] else None


def coach_to(user, step: str):
    """Move the coach forward (never back)."""
    if step not in COACH_STEPS:
        raise GameError("Unknown step.")
    now_at = user.data.get("web_coach")
    if now_at in COACH_STEPS and COACH_STEPS.index(step) <= COACH_STEPS.index(now_at):
        return
    user.data["web_coach"] = step


# ── The Welcome week ────────────────────────────────────────────────────

def start_welcome(user):
    """Called when a new save begins (logic.begin)."""
    user.data["web_welcome"] = {"start": now().date().isoformat(), "claimed": 0, "last": None}


def welcome(user) -> Optional[dict]:
    """The calendar, or None for saves without it (older ones) and once it's over."""
    w = user.data.get("web_welcome")
    if not w:
        return None
    today = now().date()
    start = datetime.date.fromisoformat(w["start"])
    days_in = (today - start).days
    if w["claimed"] >= len(WELCOME) or days_in >= WELCOME_WINDOW:
        return None
    can = w.get("last") != today.isoformat()
    return {"days": [{"day": i + 1, "reward": reward_lines(r), "big": bool(r.get("super", 0) >= 2 or r.get("title")),
                      "state": "claimed" if i < w["claimed"] else ("today" if i == w["claimed"] and can else "ahead")}
                     for i, r in enumerate(WELCOME)],
            "can": can, "claimed": w["claimed"], "left": WELCOME_WINDOW - days_in}


def claim_welcome(user) -> List[str]:
    view = welcome(user)
    if not view:
        raise GameError("The welcome week is over.")
    if not view["can"]:
        raise GameError("Come back tomorrow for the next day's gift.")
    w = user.data["web_welcome"]
    reward = WELCOME[w["claimed"]]
    w["claimed"] += 1
    w["last"] = now().date().isoformat()
    return _pay(user, reward)
