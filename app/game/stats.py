"""Balance telemetry for the admin panel: win rates of stands and items, per fight kind and per week.

Recorded once per finished fight (db.save_fight). PvE counts only the player's side (the enemies
are scripted); PvP counts both sides. Surrenders, the training dummy and raid fights (scored by
damage, not by winning) are left out. A draw is worth half a win.

Redis, per ISO week and fight kind (kept STATS_DAYS):
  web:stats:<week>:<kind>:stands  "<stand>:g" games, "<stand>:p" points (2 a win, 1 a draw)
  web:stats:<week>:<kind>:pairs   "<stand>:<item>:g" / ":p", the same for a stand holding that item
"""
import datetime
from collections import defaultdict
from typing import Dict, List

from app.game.character import CHARACTER_FILE
from app.game.fight import PVP_KINDS
from app.game.items import item_file

PVP = set(PVP_KINDS) | {"gang_war"}
PVE = {"wormhole", "story", "alt_universe", "rush", "tower", "dungeon"}
STATS_DAYS = 120
MIN_GAMES = 5  # rows with fewer games are shown greyed out


def week_of(when: datetime.datetime) -> str:
    return when.strftime("%G-W%V")


def _key(week: str, kind: str, what: str) -> str:
    return f"web:stats:{week}:{kind}:{what}"


def record(redis, fight, when: datetime.datetime) -> bool:
    """Count a finished fight once. Returns True if it was counted."""
    if not fight.finished or getattr(fight, "stats_recorded", False):
        return False
    fight.stats_recorded = True
    if getattr(fight, "forfeited", False) or fight.kind not in PVP | PVE:
        return False
    sides = (0, 1) if fight.kind in PVP else (fight.human_side,)
    week = week_of(when)
    stands, pairs = _key(week, fight.kind, "stands"), _key(week, fight.kind, "pairs")
    pipe = redis.pipeline()
    for s in sides:
        points = 1 if fight.winner is None else 2 * (fight.winner == s)
        for c in fight.sides[s].chars:
            pipe.hincrby(stands, f"{c.id}:g", 1)
            pipe.hincrby(stands, f"{c.id}:p", points)
            for item_id in {i.id for i in c.items}:
                pipe.hincrby(pairs, f"{c.id}:{item_id}:g", 1)
                pipe.hincrby(pairs, f"{c.id}:{item_id}:p", points)
    for key in (stands, pairs):
        pipe.expire(key, STATS_DAYS * 86400)
    pipe.execute()
    return True


def _weeks(now: datetime.datetime, n: int) -> List[str]:
    return sorted({week_of(now - datetime.timedelta(days=7 * i)) for i in range(n)})


def _load(redis, weeks, kinds, what) -> Dict[tuple, List[int]]:
    """{(stand,) or (stand, item): [games, points]} summed over weeks and kinds."""
    out = defaultdict(lambda: [0, 0])
    for week in weeks:
        for kind in kinds:
            for field, value in redis.hgetall(_key(week, kind, what)).items():
                field = field.decode() if isinstance(field, bytes) else field
                *ids, stat = field.split(":")
                out[tuple(int(i) for i in ids)][0 if stat == "g" else 1] += int(value)
    return out


def _rate(games: int, points: int):
    return points / (2 * games) if games else None


def report(redis, now: datetime.datetime, weeks: int = 4) -> dict:
    """Stand and item tables for PvE and PvP over the last `weeks` weeks."""
    span = _weeks(now, weeks)
    names = {c["id"]: c for c in CHARACTER_FILE}
    out = {"weeks": span, "min_games": MIN_GAMES}
    stand_rows = defaultdict(dict)
    item_rows = defaultdict(dict)
    for scope, kinds in (("pve", PVE), ("pvp", PVP)):
        stands = _load(redis, span, kinds, "stands")
        pairs = _load(redis, span, kinds, "pairs")
        for (sid,), (g, p) in stands.items():
            stand_rows[sid][scope] = {"games": g, "rate": _rate(g, p)}
        # an item's delta: how much better each stand does holding it than the same stand without it,
        # weighted by the games played with it (only stands with games both ways count)
        by_item = defaultdict(lambda: {"games": 0, "points": 0, "dw": 0.0, "dn": 0})
        for (sid, iid), (g, p) in pairs.items():
            row = by_item[iid]
            row["games"] += g
            row["points"] += p
            sg, sp = stands.get((sid,), (0, 0))
            if sg - g > 0:
                row["dw"] += g * (_rate(g, p) - _rate(sg - g, sp - p))
                row["dn"] += g
        for iid, row in by_item.items():
            item_rows[iid][scope] = {"games": row["games"], "rate": _rate(row["games"], row["points"]),
                                     "delta": row["dw"] / row["dn"] if row["dn"] else None, "delta_games": row["dn"]}
    out["stands"] = sorted(
        ({"id": sid, "name": names.get(sid, {}).get("name", f"#{sid}"), "rarity": names.get(sid, {}).get("rarity", "?"),
          **{k: v for k, v in rows.items()}} for sid, rows in stand_rows.items()),
        key=lambda r: -(r.get("pve", {}).get("games", 0) + r.get("pvp", {}).get("games", 0)))
    out["items"] = sorted(
        ({"id": iid, "name": item_file[iid - 1]["name"] if 0 < iid <= len(item_file) else f"#{iid}", **rows}
         for iid, rows in item_rows.items()),
        key=lambda r: -(r.get("pve", {}).get("games", 0) + r.get("pvp", {}).get("games", 0)))
    return out
