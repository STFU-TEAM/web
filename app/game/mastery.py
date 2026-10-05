"""Stand mastery: every stand you fight with keeps a record (per stand, not per copy, so fusing keeps it).

Recorded once per finished fight for the player's own side (db.save_fight -> record_fight).
Surrenders and the training dummy don't count. Points: 1 per fight, 3 more per win, 1 per special fired.

Redis: web:mastery:<uid>  hash "<stand id>:g" games, ":w" wins, ":d" damage dealt, ":s" specials fired
"""
from collections import defaultdict
from typing import Dict, List

from app.game.character import CHARACTER_FILE

SKIP_KINDS = {"dummy"}
LEVELS = [  # (points needed, name, icon)
    (0, "Untrained", ""),
    (15, "Bronze", "🥉"),
    (60, "Silver", "🥈"),
    (180, "Gold", "🥇"),
    (450, "Master", "👑"),
]
MASTER = LEVELS[-1][0]


def _key(uid: str) -> str:
    return f"web:mastery:{uid}"


def points(row: dict) -> int:
    return row.get("g", 0) + 3 * row.get("w", 0) + row.get("s", 0)


def level_of(pts: int) -> dict:
    idx = max(i for i, (need, _, _) in enumerate(LEVELS) if pts >= need)
    need, name, icon = LEVELS[idx]
    nxt = LEVELS[idx + 1] if idx + 1 < len(LEVELS) else None
    pct = 100 if not nxt else int(100 * (pts - need) / (nxt[0] - need))
    return {"level": idx, "rank": name, "icon": icon, "points": pts, "pct": pct,
            "next": nxt[1] if nxt else None, "to_next": nxt[0] - pts if nxt else 0}


def side_stats(fight, side: int) -> Dict[int, dict]:
    """{stand id: {"d": damage dealt, "s": specials}} for one side, read off the fight log."""
    chars = fight.sides[side].chars
    out = defaultdict(lambda: {"d": 0, "s": 0})
    prev = None
    for e in fight.log:
        src = e.get("src")
        if src and src[0] == side and src[1] < len(chars):
            cid = chars[src[1]].id
            if e.get("dmg"):
                out[cid]["d"] += int(e["dmg"])
            elif e["kind"] in ("special", "item") and prev and e.get("hp"):
                # specials and items log no number: count what the enemy side lost in that event
                lost = sum(max(0, a - b) for a, b in zip(prev[1 - side], e["hp"][1 - side]))
                out[cid]["d"] += int(lost)
            if e["kind"] == "special":
                out[cid]["s"] += 1
        if e.get("hp"):
            prev = e["hp"]
    return out


def record_fight(redis, fight, players: Dict[int, str]):
    """players: {side: uid} for the human sides."""
    if fight.kind in SKIP_KINDS or getattr(fight, "forfeited", False):
        return
    pipe = redis.pipeline()
    for side, uid in players.items():
        if not uid:
            continue
        stats = side_stats(fight, side)
        for c in fight.sides[side].chars:
            key = _key(uid)
            pipe.hincrby(key, f"{c.id}:g", 1)
            if fight.winner == side:
                pipe.hincrby(key, f"{c.id}:w", 1)
            if stats[c.id]["d"]:
                pipe.hincrby(key, f"{c.id}:d", stats[c.id]["d"])
            if stats[c.id]["s"]:
                pipe.hincrby(key, f"{c.id}:s", stats[c.id]["s"])
    pipe.execute()


def table(redis, uid: str) -> Dict[int, dict]:
    out = defaultdict(lambda: {"g": 0, "w": 0, "d": 0, "s": 0})
    for field, value in redis.hgetall(_key(uid)).items():
        field = field.decode() if isinstance(field, bytes) else field
        sid, stat = field.split(":")
        out[int(sid)][stat] = int(value)
    return out


def of(redis, uid: str, stand_id: int) -> dict:
    row = table(redis, uid).get(int(stand_id), {"g": 0, "w": 0, "d": 0, "s": 0})
    return {**row, **level_of(points(row)), "id": int(stand_id)}


def ranking(redis, uid: str, limit: int = 0) -> List[dict]:
    """The player's stands by mastery points, best first."""
    names = {c["id"]: c for c in CHARACTER_FILE}
    rows = []
    for sid, row in table(redis, uid).items():
        if sid not in names:
            continue
        rows.append({**row, **level_of(points(row)), "id": sid, "name": names[sid]["name"],
                     "rarity": names[sid]["rarity"]})
    rows.sort(key=lambda r: (-r["points"], r["name"]))
    return rows[:limit] if limit else rows


def titles(redis, uid: str) -> List[str]:
    return [f"{r['name']} Master" for r in ranking(redis, uid) if r["points"] >= MASTER]
