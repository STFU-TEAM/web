"""Rival bots for the ranked queue: when nobody else is around, a player who has waited BOT_WAIT seconds can fight a
bot instead. A bot is always labelled as one (its name says "bot"), never stored as a player, and pays a quarter of a
real match's Elo, with a daily cap on what it can add, so nobody climbs the ladder on bots alone.

A bot exists only inside its match: its id is "bot:<draft id>", its roster lives in the draft (draft["bot"]), and in
the duel it's a computer side (Side(..., False)) driven by the fight AI, so the duel's meta lists only the human.
Bot matches skip the season record (seasons.record: games toward the season's minimum and its ladder), the watch
list and the ranked meta.

Save: data["web_bot_elo"] = {"day": ISO date, "gain": Elo gained from bots that day}
"""
import random
import uuid as uuidlib
from typing import Dict, List

from app.game import seasons
from app.game.character import CHARACTER_FILE, character_from_dict

BOT_WAIT = 45                     # seconds in the queue before a bot is offered
WIN = round(seasons.WIN / 4)      # a quarter of a real match: +6
LOSS = round(seasons.LOSS / 4)    # and -5
DAILY_GAIN_CAP = 30               # Elo a day that bot wins can add
NAMES = ["DIO's Minion", "Passione Grunt", "Rock Human", "Rokakaka Smuggler", "Pillar Man Acolyte", "Whitesnake Disc",
         "Speedwagon Agent", "Morioh Delinquent", "Green Dolphin Inmate", "Saint's Corpse Hunter"]
QUALITIES = ["GOOD", "GOOD", "GREAT", "GREAT", "SUPREME"]
TYPES = ["ATTACK", "DEFENSE", "BALANCE", "LUCK", "SPEED", "HEALTH"]


def is_bot(uid) -> bool:
    return str(uid).startswith("bot:")


def _pool() -> Dict[str, List[int]]:
    """Banner stands by rarity (no Requiem forms, specials or the training dummy)."""
    from app.game.logic import BANNERS
    ids = {c for b in BANNERS for c in b["cards"]}
    pool: Dict[str, List[int]] = {}
    for c in CHARACTER_FILE:
        if c["id"] in ids and c["universe"] != "Dummy":
            pool.setdefault(c["rarity"], []).append(c["id"])
    return pool


def build(roster, rng=random) -> dict:
    """A bot that mirrors a player's ranked roster: for each of their stands, a different stand of the same rarity at
    the same level and stars, with the same number of items (refined alike). Returns {"id", "name", "stands"}:
    stands maps a uuid to the stand's saved dict."""
    pool = _pool()
    taken = {c.id for c in roster}
    stands = {}
    for c in roster:
        choices = [i for i in pool.get(c.rarity, []) if i not in taken] or [i for i in pool.get("SR", []) if i not in taken]
        sid = rng.choice(choices)
        taken.add(sid)
        u = uuidlib.uuid4().hex
        stands[u] = {"id": sid, "uuid": u, "xp": c.xp, "awaken": c.awaken, "types": [rng.choice(TYPES)],
                     "qualities": [rng.choice(QUALITIES)],
                     "items": [{"id": it.id, "refine": getattr(it, "refine", 0)} for it in c.items]}
    return {"name": f"🤖 {rng.choice(NAMES)} (bot)", "stands": stands}


def stands(bot: dict) -> Dict[str, object]:
    """uuid -> Character, for the draft panel and the duel."""
    return {u: character_from_dict(d) for u, d in bot["stands"].items()}


def gain_left(user) -> int:
    from app.game.logic import now
    today = now().date().isoformat()
    s = user.data.get("web_bot_elo") or {}
    return DAILY_GAIN_CAP - (s.get("gain", 0) if s.get("day") == today else 0)


def settle(user, won: bool, lost: bool) -> int:
    """Apply a bot match's Elo to user: a win adds WIN (within the daily cap), a loss takes LOSS. Returns the change."""
    from app.game.logic import now
    if won:
        gain = max(0, min(WIN, gain_left(user)))
        today = now().date().isoformat()
        s = user.data.get("web_bot_elo") or {}
        user.data["web_bot_elo"] = {"day": today, "gain": (s.get("gain", 0) if s.get("day") == today else 0) + gain}
        user.global_elo += gain
        return gain
    if lost:
        before = int(user.global_elo or 0)
        user.global_elo = max(0, before - LOSS)
        return user.global_elo - before
    return 0
