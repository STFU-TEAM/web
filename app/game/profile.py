"""Profile customization (the Stand User file at the top of a profile), reports from other players, and the admin
tools that remove a customization and lock it.

What a player can set: a catchphrase, a colour theme (unlocked by clearing story parts, supporting the game, or
reaching Over Heaven), a signature stand, up to SHOWCASE_MAX stands to showcase and up to PIN_MAX achievements to
pin. An admin can wipe all of it and lock it (nothing can be set again until they unlock it).

Save:   data["web_profile"] = {"quote", "theme", "stand": uuid, "showcase": [uuids], "pins": [achievement ids]}
Redis:  web:profile:locked              hash uid -> JSON {by, at, reason}
        web:reports                     hash id -> JSON {id, target, reporter, reason, note, at, status, seen: snapshot}
        web:reports:open                zset id -> at (the admin queue)
        web:report:by:<reporter>:<uid>  set for a day: one report per player per profile per day
        web:report:count:<reporter>     reports sent today (capped at DAILY_REPORTS)
"""
import json
import re
import secrets
import time
import unicodedata
from typing import List, Optional

from app.db import r
from app.game.logic import GameError

QUOTE_MAX = 80
SHOWCASE_MAX = 6
PIN_MAX = 3
DAILY_REPORTS = 10
LOCKED_KEY = "web:profile:locked"
REPORTS_KEY = "web:reports"
OPEN_KEY = "web:reports:open"
REASONS = {"text": "Offensive catchphrase", "name": "Offensive name or picture", "cheating": "Cheating or abuse",
           "other": "Something else"}


# ── Themes ───────────────────────────────────────────────────────────────

def themes(user=None) -> List[dict]:
    """Every theme: {key, label, colors: [3], unlock (how to get it), open (for this user, if one is given)}."""
    from app.game import overheaven, story, titles
    out = [{"key": "night", "label": "Night", "colors": ["#7A3FB8", "#D6246E", "#2BB3A8"], "unlock": "Everyone has it"}]
    journey = story.journey(user) if user else []
    done = {p["part"] for p in journey if p["stages"] and p["cleared"] == len(p["stages"])}
    for p in story.PARTS:
        if not p["part"]:
            continue
        name = p["title"].split(" · ", 1)[1]
        out.append({"key": f"part{p['part']}", "label": name, "colors": [p["color"], "#1C0F2E", "#F4C542"],
                    "unlock": f"Clear Part {p['part']} of the story", "open": p["part"] in done})
    out.append({"key": "supporter", "label": "Supporter gold", "colors": ["#F4C542", "#C8931B", "#FFF3C4"],
                "unlock": "Support the game on Ko-fi", "open": bool(user and user.is_donator())})
    out.append({"key": "heaven", "label": "Over Heaven", "colors": ["#FF4DA0", "#F4C542", "#5FF2E4"],
                "unlock": "Earn the Over Heaven title",
                "open": bool(user and overheaven.TITLE in titles.available(user))})
    for t in out:
        t.setdefault("open", True)
    return out


def theme_of(key: Optional[str]) -> dict:
    return next((t for t in themes() if t["key"] == key), themes()[0])


# ── The player's choices ─────────────────────────────────────────────────

def locked(uid) -> Optional[dict]:
    raw = r().hget(LOCKED_KEY, str(uid))
    return json.loads(raw) if raw else None


def get(user) -> dict:
    """What the profile shows; empty while an admin lock holds."""
    if locked(user.id):
        return {}
    return dict(user.data.get("web_profile") or {})


def clean_quote(text: str) -> str:
    """One line, no control or invisible characters, at most QUOTE_MAX characters."""
    text = re.sub(r"\s+", " ", text or "")  # line breaks and tabs become spaces first
    text = "".join(ch for ch in text if unicodedata.category(ch)[0] != "C")
    return re.sub(r" +", " ", text).strip()[:QUOTE_MAX]


def save(user, quote: str, theme: str, stand: str, showcase: List[str], pins: List[str]):
    """Validate and store a customization (the caller holds the save lock and saves)."""
    lock = locked(user.id)
    if lock:
        raise GameError("An admin removed your profile customization and locked it"
                        + (f": {lock['reason']}" if lock.get("reason") else ".") + " Ask on the Discord server to have it reopened.")
    open_themes = {t["key"] for t in themes(user) if t["open"]}
    if theme and theme not in open_themes:
        raise GameError("You haven't unlocked that theme yet.")
    owned = {c.uuid for c in user.main_characters + user.storage_characters}
    if stand and stand not in owned:
        raise GameError("Pick one of your own stands as your signature.")
    showcase = [u for u in dict.fromkeys(showcase or []) if u in owned][:SHOWCASE_MAX]
    unlocked = set(user.achievement_data.get("unlocked", []))
    pins = [p for p in dict.fromkeys(pins or []) if p in unlocked][:PIN_MAX]
    user.data["web_profile"] = {"quote": clean_quote(quote), "theme": theme or "night", "stand": stand or None,
                                "showcase": showcase, "pins": pins}


def view(user) -> dict:
    """The resolved profile for the template: theme colours, the signature stand's copy, showcase copies, pins."""
    p = get(user)
    by_uuid = {c.uuid: c for c in user.main_characters + user.storage_characters}
    from app.game.achievements import ALL_ACHIEVEMENTS
    achievements = {a["id"]: a for a in ALL_ACHIEVEMENTS}
    return {"quote": p.get("quote") or "", "theme": theme_of(p.get("theme")),
            "stand": by_uuid.get(p.get("stand") or ""),
            "showcase": [by_uuid[u] for u in p.get("showcase") or [] if u in by_uuid],
            "pins": [achievements[a] for a in p.get("pins") or [] if a in achievements],
            "locked": locked(user.id)}


# ── Moderation ───────────────────────────────────────────────────────────

def clear(user):
    """Remove every customization (the caller saves)."""
    user.data["web_profile"] = {}


def lock(uid, by: str, reason: str = ""):
    r().hset(LOCKED_KEY, str(uid), json.dumps({"by": str(by), "at": int(time.time()), "reason": (reason or "")[:200]}))


def unlock(uid):
    r().hdel(LOCKED_KEY, str(uid))


def report(reporter: str, target, reason: str, note: str = "") -> dict:
    target = str(target)
    if reporter == target:
        raise GameError("You can't report your own profile.")
    if reason not in REASONS:
        raise GameError("Pick what's wrong with this profile.")
    if not r().set(f"web:report:by:{reporter}:{target}", "1", nx=True, ex=86400):
        raise GameError("You already reported this profile today. An admin will look at it.")
    count = r().incr(f"web:report:count:{reporter}")
    if count == 1:
        r().expire(f"web:report:count:{reporter}", 86400)
    if count > DAILY_REPORTS:
        raise GameError("You've sent enough reports for today. Thanks for helping.")
    from app.db import get_db, identity
    user = get_db().get_user(target)
    seen = {"name": identity(target)["name"], "avatar": identity(target).get("avatar")}
    if user:
        p = user.data.get("web_profile") or {}
        seen.update(quote=p.get("quote") or "", theme=p.get("theme") or "night")
    rid = secrets.token_hex(5)
    entry = {"id": rid, "target": target, "reporter": reporter, "reason": reason, "note": clean_quote(note)[:300] if note else "",
             "at": int(time.time()), "status": "open", "seen": seen}
    r().hset(REPORTS_KEY, rid, json.dumps(entry))
    r().zadd(OPEN_KEY, {rid: entry["at"]})
    return entry


def open_count() -> int:
    return r().zcard(OPEN_KEY)


def reports(status: str = "open", limit: int = 100) -> List[dict]:
    out = []
    for raw in r().hvals(REPORTS_KEY):
        e = json.loads(raw)
        if status == "all" or e["status"] == status or (status == "closed" and e["status"] != "open"):
            out.append(e)
    out.sort(key=lambda e: e["at"], reverse=True)
    return out[:limit]


def resolve(rid: str, by: str, outcome: str) -> Optional[dict]:
    raw = r().hget(REPORTS_KEY, rid)
    if not raw:
        return None
    e = json.loads(raw)
    e.update(status=outcome, closed_by=str(by), closed_at=int(time.time()))
    r().hset(REPORTS_KEY, rid, json.dumps(e))
    r().zrem(OPEN_KEY, rid)
    return e


def resolve_all(target: str, by: str, outcome: str) -> int:
    """Close every open report about one player (after acting on any of them)."""
    n = 0
    for e in reports("open", 1000):
        if e["target"] == str(target):
            resolve(e["id"], by, outcome)
            n += 1
    return n
