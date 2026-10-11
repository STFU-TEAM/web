"""Who's that Stand? (web only): a daily guessing game, the same stand for everyone.

Guess a stand by name. Each guess shows how it compares with the mystery stand: rarity (higher or lower), part,
what powers its special, and its health, damage and speed (higher or lower). The first guess is blind: the picture
only appears after a miss, as a coarse mosaic that sharpens with every miss after that; after 3 misses the special's description shows (the name blanked out), after 5 the
first letter. MAX_GUESSES tries; the ladder ranks fewest guesses, then the earliest solve.

The picture is made on the server (Pillow) from the stand's art, at the sharpness the player has earned, so the
page never holds the answer: not its id, not its image URL.

Redis (day = UTC date):
    web:wts:<day>:<uid>        JSON {guesses: [ids], solved, at}
    web:wts:ladder:<day>       zset uid -> guesses * 1e6 + seconds into the day
    web:wts:streak:<uid>       hash last (day solved), n (current streak), best
    web:wts:img:<day>:<step>   the mosaic PNG for a step, cached
"""
import datetime
import io
import json
import random
import time
import unicodedata
from typing import List, Optional

from app.db import r
from app.game.character import CHARACTER_FILE
from app.game.logic import GameError

MAX_GUESSES = 8
KEEP = 8 * 86400
BLOCKS = [5, 7, 10, 14, 20, 30, 44, 64]   # mosaic tiles across, by misses so far (more = sharper)
CLUE_SPECIAL, CLUE_LETTER = 3, 5          # misses before each clue shows
RARITY_ORDER = ["R", "SR", "SSR", "UR", "LR"]
REWARD_BASE, REWARD_PER_SPARE = 300, 60   # Meteor Dust: base, plus this per unused guess
XP_BASE, XP_PER_SPARE = 400, 50           # player XP, the same way
POOL = [c["id"] for c in CHARACTER_FILE if c["universe"] != "Dummy" and c["id"] != 110 and c["rarity"] in RARITY_ORDER]


def today() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")


def yesterday(day: Optional[str] = None) -> str:
    d = datetime.date.fromisoformat(day or today())
    return (d - datetime.timedelta(days=1)).isoformat()


def answer(day: Optional[str] = None) -> int:
    """The day's stand: the roster shuffled once per cycle, one a day, no repeat until every stand has come up."""
    d = datetime.date.fromisoformat(day or today())
    n = (d - datetime.date(2026, 1, 1)).days
    cycle, i = divmod(n, len(POOL))
    order = sorted(POOL)
    random.Random(f"wts-cycle-{cycle}").shuffle(order)
    return order[i]


def _fold(s: str) -> str:
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode().lower()
    return "".join(ch for ch in s if ch.isalnum())


_BY_NAME = {}


def find(name: str) -> Optional[int]:
    """A stand id from a typed name (case, accents, spaces and punctuation ignored)."""
    if not _BY_NAME:
        for cid in POOL:
            _BY_NAME.setdefault(_fold(CHARACTER_FILE[cid - 1]["name"]), cid)
    return _BY_NAME.get(_fold(name))


def names() -> List[str]:
    """Every guessable name, for the input's suggestions."""
    return sorted({CHARACTER_FILE[cid - 1]["name"] for cid in POOL}, key=str.lower)


# ── Comparing a guess ───────────────────────────────────────────────────

def facts(cid: int) -> dict:
    from app.game.character import Character
    from app.game.characterabilities import STAT_INFO, scaling_of
    from app.game.parts import of_stand
    c = Character({"id": cid, "xp": 100 * 100, "awaken": 0, "types": [], "qualities": [], "items": []})
    stat = scaling_of(cid)
    return {"id": cid, "name": c.name, "rarity": c.rarity, "part": of_stand(cid), "scales": STAT_INFO[stat][1],
            "scales_icon": STAT_INFO[stat][0], "hp": c.start_hp, "dmg": c.start_damage, "spd": c.start_speed}


def compare(guess: int, target: int) -> dict:
    """One row of feedback: per column, its value and how it compares ("hit", "up" = the answer is higher, "down", "miss")."""
    g, t = facts(guess), facts(target)
    def num(key):
        return "hit" if g[key] == t[key] else ("up" if t[key] > g[key] else "down")
    ri, ti = RARITY_ORDER.index(g["rarity"]), RARITY_ORDER.index(t["rarity"])
    return {"id": guess, "name": g["name"], "correct": guess == target, "cells": [
        {"label": "Rarity", "value": g["rarity"], "state": "hit" if ri == ti else ("up" if ti > ri else "down")},
        {"label": "Part", "value": f"Part {g['part']}" if g["part"] else "Other",
         "state": "hit" if g["part"] == t["part"] else ("up" if (t["part"] or 0) > (g["part"] or 0) else "down")},
        {"label": "Special", "value": f"{g['scales_icon']} {g['scales']}", "state": "hit" if g["scales"] == t["scales"] else "miss"},
        {"label": "Health", "value": f"{g['hp']:,}", "state": num("hp")},
        {"label": "Damage", "value": f"{g['dmg']:,}", "state": num("dmg")},
        {"label": "Speed", "value": f"{g['spd']:,}", "state": num("spd")},
    ]}


# ── A player's day ──────────────────────────────────────────────────────

def _key(uid, day):
    return f"web:wts:{day}:{uid}"


def state(uid, day: Optional[str] = None) -> dict:
    raw = r().get(_key(uid, day or today()))
    s = json.loads(raw) if raw else {"guesses": [], "solved": False, "at": None}
    s["misses"] = len(s["guesses"]) - (1 if s["solved"] else 0)
    s["over"] = s["solved"] or len(s["guesses"]) >= MAX_GUESSES
    return s


def guess(user, name: str, day: Optional[str] = None) -> dict:
    """Record a guess; on the right one, the ladder, the streak and the reward. Returns the new state."""
    day = day or today()
    uid = str(user.id)
    s = state(uid, day)
    if s["over"]:
        raise GameError("Today's stand is settled. Come back tomorrow for a new one.")
    cid = find(name)
    if not cid:
        raise GameError("No stand by that name. Pick one from the suggestions.")
    if cid in s["guesses"]:
        raise GameError("You already guessed that one.")
    s["guesses"].append(cid)
    target = answer(day)
    if cid == target:
        s.update(solved=True, at=int(time.time()))
        midnight = datetime.datetime.combine(datetime.date.fromisoformat(day), datetime.time(), tzinfo=datetime.timezone.utc)
        r().zadd(f"web:wts:ladder:{day}", {uid: len(s["guesses"]) * 1_000_000 + max(0, int(time.time() - midnight.timestamp()))})
        r().expire(f"web:wts:ladder:{day}", KEEP)
        _streak_up(uid, day)
        spare = MAX_GUESSES - len(s["guesses"])
        dust, xp = REWARD_BASE + REWARD_PER_SPARE * spare, XP_BASE + XP_PER_SPARE * spare
        user.fragments += dust
        user.xp += xp
        s["reward"], s["reward_xp"] = dust, xp
    r().set(_key(uid, day), json.dumps({k: s[k] for k in ("guesses", "solved", "at")}), ex=KEEP)
    return state(uid, day) | ({"reward": s["reward"], "reward_xp": s["reward_xp"]} if "reward" in s else {})


def _streak_up(uid, day):
    key = f"web:wts:streak:{uid}"
    raw = {(k.decode() if isinstance(k, bytes) else k): (v.decode() if isinstance(v, bytes) else v) for k, v in r().hgetall(key).items()}
    n = int(raw.get("n", 0)) + 1 if raw.get("last") == yesterday(day) else 1
    r().hset(key, mapping={"last": day, "n": n, "best": max(n, int(raw.get("best", 0)))})


def streak(uid) -> dict:
    raw = {(k.decode() if isinstance(k, bytes) else k): (v.decode() if isinstance(v, bytes) else v) for k, v in r().hgetall(f"web:wts:streak:{uid}").items()}
    alive = raw.get("last") in (today(), yesterday())
    return {"n": int(raw.get("n", 0)) if alive else 0, "best": int(raw.get("best", 0))}


def ladder(day: Optional[str] = None, size: int = 20) -> list:
    rows = r().zrange(f"web:wts:ladder:{day or today()}", 0, size - 1, withscores=True)
    return [{"rank": i + 1, "uid": (u.decode() if isinstance(u, bytes) else u), "guesses": int(s // 1_000_000)} for i, (u, s) in enumerate(rows)]


def solvers(day: Optional[str] = None) -> int:
    return r().zcard(f"web:wts:ladder:{day or today()}")


def clues(s: dict, day: Optional[str] = None) -> dict:
    """The clues earned so far (the special with the stand's name blanked, the first letter)."""
    t = facts(answer(day))
    out = {}
    if s["misses"] >= CLUE_SPECIAL or s["over"]:
        text = CHARACTER_FILE[t["id"] - 1]["special_description"].replace("`", "")
        for word in t["name"].split():
            if len(word) > 2:
                text = text.replace(word, "▇" * len(word))
        out["special"] = text
    if s["misses"] >= CLUE_LETTER or s["over"]:
        out["letter"] = t["name"][0].upper()
        out["length"] = len(t["name"])
    return out


def share_text(s: dict, day: Optional[str] = None) -> str:
    """The result to paste anywhere: a grid of how each guess compared, no names."""
    target = answer(day)
    icon = {"hit": "🟩", "up": "🔼", "down": "🔽", "miss": "🟥"}
    lines = ["".join(icon[c["state"]] for c in compare(g, target)["cells"]) for g in s["guesses"]]
    head = f"Who's that Stand? {day or today()} · {len(s['guesses']) if s['solved'] else 'X'}/{MAX_GUESSES}"
    return "\n".join([head, *lines, "stfurequiem.com"])


# ── The picture ─────────────────────────────────────────────────────────

def picture_step(s: dict) -> Optional[int]:
    """How sharp the picture is for this player: None before the first miss (nothing shown), then 0, 1, 2..."""
    return None if s["misses"] < 1 else min(s["misses"] - 1, len(BLOCKS) - 1)


def mosaic(day: str, step: int, fetch) -> Optional[bytes]:
    """The day's stand as a PNG mosaic, `step` sharpness (0 = coarsest), cached. fetch(url) -> bytes."""
    step = max(0, min(step, len(BLOCKS) - 1))
    key = f"web:wts:img:{day}:{step}"
    cached = r().get(key)
    if cached:
        return cached
    try:
        from PIL import Image
        raw = fetch(answer(day))
        img = Image.open(io.BytesIO(raw)).convert("RGBA")
        img.thumbnail((360, 360))
        w, h = img.size
        n = BLOCKS[step]
        small = img.resize((max(1, n), max(1, round(n * h / w))), Image.BILINEAR)
        out = small.resize((w, h), Image.NEAREST)
        buf = io.BytesIO()
        out.save(buf, "PNG", optimize=True)
        data = buf.getvalue()
    except Exception:
        return None
    r().set(key, data, ex=2 * 86400)
    return data
