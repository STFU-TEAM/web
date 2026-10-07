"""Battle history and replays: every finished fight is kept for its players, and can be replayed by link.

Recorded once per fight from db.save_fight (fight.history_recorded guards the second save of a duel).

Redis:
  web:battles:<uid>     list of JSON summaries, newest first (KEEP)
  web:replay:<fight id> zlib(pickle(finished Fight)), kept REPLAY_DAYS
"""
import copy
import json
import pickle
import time
import zlib
from typing import Dict, List, Optional

KEEP = 30
REPLAY_DAYS = 14
LABELS = {"dummy": "Practice", "ranked": "Ranked", "friend": "Friendly duel", "wormhole": "Mirror World",
          "story": "Story", "alt_universe": "Alternate Universe", "rush": "Boss rush", "tower": "Tower",
          "dungeon": "Dungeon", "gang_war": "Gang war", "gang_raid": "Gang raid", "coop": "Co-op raid",
          "training": "Training", "over_heaven": "Over Heaven"}
ICONS = {"dummy": "🎯", "ranked": "♛", "friend": "⚔", "wormhole": "🪞", "story": "📜", "alt_universe": "🌀",
         "rush": "♛", "tower": "▲", "dungeon": "▦", "gang_war": "⚑", "gang_raid": "🐉", "coop": "🤝",
         "training": "🥊", "over_heaven": "☁"}
PVP = {"ranked", "friend"}


def players_of(fight, user_id: str) -> Dict[int, str]:
    """{side: uid} for the human sides of a fight."""
    players = (fight.meta or {}).get("players") or []
    if fight.kind in PVP and len(players) == 2:
        return {0: players[0], 1: players[1]}
    return {fight.human_side: str(user_id)}


def _result(fight, side: int) -> str:
    if fight.winner is None:
        return "draw"
    return "win" if fight.winner == side else "loss"


def record(redis, fight, user_id: str) -> Optional[str]:
    """Store the replay and a summary line for each human player. Returns the replay id."""
    players = players_of(fight, user_id)
    at = int(time.time())
    try:
        kept = copy.copy(fight)
        kept.start_teams = None  # the "Simulate this fight" snapshot: replays don't need it
        blob = zlib.compress(pickle.dumps(kept, protocol=4), 6)
    except Exception:  # an unpicklable fight is never worth breaking the game for
        return None
    pipe = redis.pipeline()
    pipe.set(f"web:replay:{fight.id}", blob, ex=REPLAY_DAYS * 86400)
    pairs = list(players.items())
    if fight.kind == "coop":  # every member of the raid party gets the line (they all fought on side 0)
        pairs = [(0, str(uid)) for uid in (fight.meta or {}).get("players", [user_id])]
    for side, uid in pairs:
        foe = 1 - side
        line = {"id": fight.id, "kind": fight.kind, "at": at, "result": _result(fight, side),
                "opp": fight.sides[foe].name, "opp_uid": players.get(foe),
                "mine": [c.id for c in fight.sides[side].chars], "theirs": [c.id for c in fight.sides[foe].chars],
                "rounds": fight.round, "surrender": bool(getattr(fight, "forfeited", False))}
        pipe.lpush(f"web:battles:{uid}", json.dumps(line))
        pipe.ltrim(f"web:battles:{uid}", 0, KEEP - 1)
    pipe.execute()
    return fight.id


def recent(redis, uid: str, limit: int = KEEP, kinds: Optional[set] = None) -> List[dict]:
    out = []
    for raw in redis.lrange(f"web:battles:{uid}", 0, KEEP - 1):
        try:
            line = json.loads(raw)
        except ValueError:
            continue
        if kinds and line["kind"] not in kinds:
            continue
        line["label"] = LABELS.get(line["kind"], "Battle")
        line["icon"] = ICONS.get(line["kind"], "⚔")
        line["replay"] = bool(redis.exists(f"web:replay:{line['id']}"))
        out.append(line)
        if len(out) >= limit:
            break
    return out


def record_line(redis, uid: str, fight_id: str) -> Optional[dict]:
    return next((b for b in recent(redis, uid) if b["id"] == fight_id), None)


def load_replay(redis, fight_id: str):
    if not fight_id.isalnum():
        return None
    raw = redis.get(f"web:replay:{fight_id}")
    if not raw:
        return None
    try:
        return pickle.loads(zlib.decompress(raw))
    except Exception:
        return None


def summary(rows: List[dict]) -> dict:
    wins = sum(r["result"] == "win" for r in rows)
    losses = sum(r["result"] == "loss" for r in rows)
    return {"wins": wins, "losses": losses, "draws": len(rows) - wins - losses}
