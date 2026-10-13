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


# ── The guide: the first session, one action at a time ──────────────
# A new save is walked through its first session by coachmarks (app.js, partials/guide.html): each one lights up the
# real button or block on the page, scrolls it into view and waits for the player to use it. data["web_coach"] holds
# the stage ("done" once over), mirrored to Redis (GUIDE_KEY) so every page can draw the guide without loading the save.
#   pull   the first summon                         -> team   (the pull route)
#   team   the team, a stand, storage, then Battle  -> story  (the last mark, or /coach)
#   story  the first fight: Fight, attack, turns    -> mirror (the first story win)
#   mirror the Mirror World                          -> home   (the first Mirror World fight)
#   home   claim the path and welcome gifts, where to look when lost -> done
COACH_STEPS = ("pull", "team", "story", "mirror", "home", "done")
GUIDE_KEY = "web:coach:{}"

# Each mark: stage, page (endpoint), target (CSS selector; "nav:a,b" = the first visible nav entry with data-tour a or
# b; None = a card in the middle), title, text, do ("click": done when the target is used; "next": a Next button;
# "go": a button to `go` (endpoint) that also moves the stage to `advance`; "finish": ends the guide).
# optional: skipped when its page or target isn't there. when / unless: a selector that must (not) match.
# repeat: a click mark that stays until its target is gone (every card waiting to be tapped, one after the other).
# pill: the words on the pill that leads to the mark's page from elsewhere (else its title).
GUIDE = [
    {"stage": "pull", "page": "play.banners", "target": ".banner .pull-10", "do": "click",
     "title": "Your first summon", "text": "You start with an Arrowhead: tap Pull 10 to summon ten stands."},
    {"stage": "team", "page": "play.banners", "target": "[data-reveal-all]", "do": "click", "optional": True,
     "title": "Flip them over", "text": "Tap the cards one by one, or Reveal all. Your team is next."},
    {"stage": "team", "page": "play.banners", "target": ".pull-grid [data-flip].must-tap:not(.flipped)", "do": "click",
     "optional": True, "repeat": True, "title": "Your best pull", "text": "SSR and better are yours to turn over: tap it."},
    {"stage": "team", "page": "play.team", "target": "#team-shelf", "do": "next", "pill": "Meet your team",
     "title": "Your team", "text": "These three fight for you in every mode. Your best pulls went in on their own."},
    {"stage": "team", "page": "play.team", "target": "#team-shelf .team-grid > *", "do": "click",
     "title": "Look at a stand", "text": "Tap a stand to see its stats, its special and its items. Close the panel to go on."},
    {"stage": "team", "page": "play.team", "target": "#storage", "do": "next",
     "title": "Your storage", "text": "Every other stand waits here. Tap one, then Add to team to swap it in. "
                                     "Copies of a stand fuse into levels."},
    {"stage": "team", "page": "play.team", "target": "nav:adventure,battle,story", "do": "go", "go": "progress.story_page",
     "advance": "story", "label": "To the story →",
     "title": "Time to fight", "text": "Every fight mode lives here (Battle on phones, Adventure on a computer). Start with the Story: it opens everything else."},
    {"stage": "story", "page": "progress.story_page", "target": ".story-stage form .btn.gold", "do": "click",
     "unless": "#fight", "pill": "Your first story fight", "title": "Your first fight", "text": "Stage 1, The Arrow's Test. Tap Fight."},
    {"stage": "story", "page": "progress.story_page", "target": "#fight:not(.finished) .side.foe .fighter-hit:not([disabled])",
     "do": "click", "when": "#fight:not(.finished)",
     "title": "Attack!", "text": "Your move: tap an enemy to hit it. The number is roughly the damage you'll deal."},
    {"stage": "story", "page": "progress.story_page", "target": "#fight:not(.finished) .side.you", "do": "next",
     "when": "#fight:not(.finished)", "title": "Your stands",
     "text": "They act in speed order. The countdown under a stand is its special: it fires on its own. "
             "Knock out every enemy to win."},
    {"stage": "story", "page": "progress.story_page", "target": "#fight.finished .result.win", "do": "go",
     "go": "play.mirror", "advance": "mirror", "label": "The Mirror World →", "when": "#fight.finished .result.win",
     "title": "Victory!", "text": "Every win pays Meteor Dust and XP, and each one opens something new. "
                                  "The first: the Mirror World."},
    {"stage": "mirror", "page": "play.mirror", "target": "form[action$='/mirror-world/start'] button", "do": "click",
     "title": "The Mirror World", "pill": "Step into the Mirror World", "text": "Your team against its own reflection: the best XP for your energy. Step through."},
    {"stage": "home", "page": "main.home", "target": "#onboarding .bp-step .btn.gold", "do": "click", "optional": True,
     "title": "Claim your rewards", "text": "Your Beginner's path: every goal you reach pays once. Claim it here."},
    {"stage": "home", "page": "main.home", "target": "#onboarding [hx-post$='/welcome-week/claim']", "do": "click",
     "optional": True, "title": "A gift a day", "text": "Your first week has a gift for every day. Open today's."},
    {"stage": "home", "page": "main.home", "target": "nav:menu,account", "do": "finish", "pill": "Claim your rewards at Home",
     "title": "You're on your own now", "text": "Home always shows your next goal. Lost? Show me around (in the menu) "
                                                "replays the tour, and the wiki's guide maps the whole game. Have fun!"},
]
STAGE_PAGE = {"pull": "play.banners", "team": "play.team", "story": "progress.story_page", "mirror": "play.mirror",
              "home": "main.home"}


def guide_marks() -> dict:
    """GUIDE with its links (template global: partials/guide.html)."""
    from flask import url_for
    marks = []
    for m in GUIDE:
        m = dict(m, href=url_for(m["page"]))
        if m.get("go"):
            m["go"] = url_for(m["go"])
        marks.append(m)
    return {"marks": marks}


def coach(user) -> Optional[str]:
    """The guide's stage for this save, or None (older saves, or the guide is over)."""
    step = user.data.get("web_coach")
    return step if step in COACH_STEPS[:-1] else None


def coach_to(user, step: str):
    """Move the guide forward (never back)."""
    if step not in COACH_STEPS:
        raise GameError("Unknown step.")
    now_at = user.data.get("web_coach")
    if now_at in COACH_STEPS and COACH_STEPS.index(step) <= COACH_STEPS.index(now_at):
        return
    if now_at is None and step != "pull":
        return  # a save from before the guide: never start it half-way
    user.data["web_coach"] = step
    try:
        from app.db import r
        if step == "done":
            r().delete(GUIDE_KEY.format(user.id))
        else:
            r().set(GUIDE_KEY.format(user.id), step, ex=30 * 86400)
    except Exception:
        pass


def guide_stage(uid) -> Optional[str]:
    """The stage every page reads (one Redis GET), None when there's no guide."""
    from app.db import r
    raw = r().get(GUIDE_KEY.format(uid))
    step = raw.decode() if isinstance(raw, bytes) else raw
    return step if step in COACH_STEPS[:-1] else None


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
