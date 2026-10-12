"""Requiem mode (web only): the story, every Alternate Universe chapter and Carry Me again, tuned for maxed teams.

A track opens once its content is cleared normally. Each stage keeps its crew and its scene, but every enemy fights
at level 100, ★5, Universal, with refined items, and its health and damage are scaled by the stage's multiplier in
app/game/data/requiem.json. Those multipliers are calibrated with the team simulator against BENCH (a real top
team: three ★5 stands with refined item stacks) so that it wins about TARGET_FIRST of a track's first stage, falling
to about TARGET_LAST of the last one, and less against bosses and finales. Recalibrate after a balance change:
python scripts/balance.py requiem.

Progress lives in the save as data["web_requiem"] = {track key: stages cleared}.
"""
import json
import os
from typing import List, Optional

from app.game import altverse, carryme, story
from app.game.character import CHARACTER_FILE, character_from_dict
from app.game.economy import dust, stand_xp
from app.game.items import item_file, item_from_dict
from app.game.logic import GameError, train

LEVEL, AWAKEN, QUALITY = 100, 5, "UNIVERSAL"
ENEMY_ITEMS = [{"id": 1, "refine": 3}] * 3
REPLAY_ENERGY = 3
REPLAY_SHARE = 0.2
TARGET_FIRST, TARGET_LAST, BOSS_DROP, FINALE = 65, 25, 10, 18   # benchmark win rates (%)
REQUIEM_ARROW = 3
DATA = os.path.join(os.path.dirname(__file__), "data", "requiem.json")

# The benchmark: a player's real top team (Paisley Park, Wonder of U, Soft & Wet; ★5, Balance, refined stacks)
BENCH = [(138, [(42, 0), (42, 5), (42, 1)]), (161, [(49, 0), (49, 2), (46, 1)]), (137, [(41, 0), (41, 0), (41, 4)])]
BENCH_QUALITY = "SUPREME"


def bench_team() -> list:
    return [character_from_dict({"id": cid, "xp": 100 * 100, "awaken": 5, "types": ["BALANCE"], "qualities": [BENCH_QUALITY],
                                 "items": [{"id": i, "refine": r} for i, r in items]}) for cid, items in BENCH]


# ── Tracks ───────────────────────────────────────────────────────────────

def _story_stages():
    return [{"title": s["title"], "enemies": s["enemies"], "boss": s.get("boss", False), "text": s.get("text", ""),
             "label": s["part_title"], "part": s["part"]} for s in story.STAGES if s["part"]]


def _au_stages(c):
    return [{"title": s["title"], "enemies": s["enemies"], "boss": s.get("boss", False), "text": s.get("text", ""),
             "label": c["title"], "part": c["after"]} for s in c["stages"]]


def _cm_stages():
    acts = [3, 3, 4, 5, 6, 7, 8]
    return [{"title": s["title"], "enemies": s["enemies"], "boss": s.get("boss", False), "text": s.get("text", ""),
             "label": s["act_title"], "part": acts[s["act"]] if s["act"] < len(acts) else None, "form": s["form"], "cm": k}
            for k, s in enumerate(carryme.STAGES[:carryme.FINALE + 1])]


TRACKS = ([{"key": "story", "title": "The Bizarre Journey", "short": "Story", "icon": "📜", "color": "#7A3FB8",
            "stages": _story_stages(), "opens": "Finish the story"}]
          + [{"key": f"au:{c['key']}", "title": c["title"], "short": c["title"], "icon": "🌀", "color": c["color"],
              "stages": _au_stages(c), "opens": f"Clear the {c['title']} universe", "au": c["key"]} for c in altverse.CHAPTERS]
          + [{"key": "carry_me", "title": "Carry Me", "short": "Carry Me", "icon": "🎭", "color": "#3AB4F2",
              "stages": _cm_stages(), "opens": "Finish Carry Me's Act VII"}])
for _t in TRACKS:
    _t["stages"][-1]["finale"] = True
BY_KEY = {t["key"]: t for t in TRACKS}
TOTAL = sum(len(t["stages"]) for t in TRACKS)


def _mults() -> dict:
    try:
        with open(DATA, encoding="utf-8") as fh:
            return json.load(fh).get("mult", {})
    except (OSError, ValueError):
        return {}


MULT = _mults()


def mult(key: str, i: int) -> float:
    row = MULT.get(key) or []
    return float(row[i]) if i < len(row) else 1.0


def unlocked(user, key: str) -> bool:
    t = BY_KEY.get(key)
    if not t:
        return False
    from app.game.progression import is_forced
    if is_forced(user, "requiem"):
        return True
    if key == "story":
        return story.cleared(user) >= story.TOTAL
    if key == "carry_me":
        return carryme.cleared(user) > carryme.FINALE
    return altverse.cleared(user, t["au"]) >= len(altverse.BY_KEY[t["au"]]["stages"])


def any_unlocked(user) -> bool:
    return any(unlocked(user, t["key"]) for t in TRACKS)


def cleared(user, key: str) -> int:
    return int((user.data.get("web_requiem") or {}).get(key, 0))


def total_cleared(user) -> int:
    return sum(min(cleared(user, t["key"]), len(t["stages"])) for t in TRACKS)


def target(i: int, n: int, stage: dict) -> float:
    """The benchmark team's win rate (%) this stage is tuned for."""
    if stage.get("finale"):
        return FINALE
    t = TARGET_FIRST - (TARGET_FIRST - TARGET_LAST) * i / max(1, n - 1)
    return t - (BOSS_DROP if stage.get("boss") else 0)


def crew(ids, m: float) -> list:
    """Stands at Requiem strength: level 100, ★5, Universal, refined items, health and damage times m.
    The deep dungeon, the Requiem Tower and Over Heaven's Requiem track build their enemies with it too."""
    team = []
    for cid in ids:
        c = character_from_dict({"id": cid, "xp": LEVEL * 100, "awaken": AWAKEN, "types": ["BALANCE"], "qualities": [QUALITY],
                                 "items": ENEMY_ITEMS, **({"sealed": True} if cid == altverse.OVER_HEAVEN_ID else {})})
        for stat in ("hp", "damage"):
            value = int(getattr(c, f"start_{stat}") * m)
            setattr(c, f"start_{stat}", value)
            setattr(c, f"current_{stat}", value)
        team.append(c)
    return team


def enemy_team(key: str, i: int, m: Optional[float] = None) -> list:
    return crew(BY_KEY[key]["stages"][i]["enemies"], mult(key, i) if m is None else m)


def guest(key: str, i: int):
    """Carry Me's track: Joyce's Stand fights beside the team, as in the story."""
    stage = BY_KEY[key]["stages"][i]
    return carryme.guest(stage["form"], stage["cm"]) if "form" in stage else None


# ── Rewards ─────────────────────────────────────────────────────────────

def reward_for(key: str, i: int) -> dict:
    stage = BY_KEY[key]["stages"][i]
    n = len(BY_KEY[key]["stages"])
    reward = {"fragments": dust(6000 + 6000 * i / max(1, n - 1)), "xp": 900 + 40 * i, "stand_xp": stand_xp(200 + 5 * i),
              "super_fragments": 1 if stage.get("boss") else 0, "items": []}
    if stage.get("finale"):
        reward["super_fragments"] = 2
        reward["items"].append(REQUIEM_ARROW)
    return reward


def title_of(key: str) -> str:
    return f"Requiem · {BY_KEY[key]['short']}"


def reward_text(key: str, i: int) -> List[str]:
    r = reward_for(key, i)
    parts = [f"{r['fragments']:,} Meteor Dust", f"{r['xp']} player XP"]
    if r["super_fragments"]:
        parts.append(f"{r['super_fragments']} Arrowhead{'s' if r['super_fragments'] > 1 else ''}")
    parts += [item_file[x - 1]["name"] for x in r["items"]]
    if BY_KEY[key]["stages"][i].get("finale"):
        parts.append(f"the title “{title_of(key)}”")
    return parts


# ── Views ───────────────────────────────────────────────────────────────

def tracks(user) -> list:
    out = []
    for t in TRACKS:
        done, open_ = cleared(user, t["key"]), unlocked(user, t["key"])
        stages = [{"index": i, "title": s["title"], "boss": s.get("boss"), "finale": s.get("finale"), "mult": mult(t["key"], i),
                   "state": "cleared" if i < done else "current" if i == done and open_ else "locked"}
                  for i, s in enumerate(t["stages"])]
        out.append({**t, "stages": stages, "unlocked": open_, "cleared": min(done, len(stages)), "complete": done >= len(stages)})
    return out


def stage_view(user, key: str, i: int) -> dict:
    s = BY_KEY[key]["stages"][i]
    n = len(BY_KEY[key]["stages"])
    return {**s, "key": key, "index": i, "number": i + 1, "of": n, "mult": mult(key, i), "target": round(target(i, n, s)),
            "enemy_stands": [CHARACTER_FILE[c - 1] for c in s["enemies"]], "reward": reward_text(key, i),
            "guest": CHARACTER_FILE[s["form"] - 1] if "form" in s else None}


# ── Fighting ────────────────────────────────────────────────────────────

def check_can_fight(user, key: str, i: int):
    if key not in BY_KEY or not unlocked(user, key):
        raise GameError("That Requiem track isn't open yet: clear its content normally first.")
    if not user.main_characters:
        raise GameError("Put at least one stand in your team first.")
    if i < 0 or i >= len(BY_KEY[key]["stages"]) or i > cleared(user, key):
        raise GameError("That stage isn't open yet.")
    if i < cleared(user, key):
        from app.game.logic import spend_energy
        spend_energy(user, REPLAY_ENERGY, f"Replaying a Requiem stage costs {REPLAY_ENERGY} energy.")


def win(user, key: str, i: int) -> dict:
    from app.game import titles
    r = reward_for(key, i)
    for char in user.main_characters:
        train(char, r["stand_xp"])
    if i != cleared(user, key):
        f = int(round(r["fragments"] * REPLAY_SHARE, -1))
        user.fragments += f
        return {"won": True, "fragments": f, "xp": 0, "stand_xp": r["stand_xp"], "item": None}
    user.fragments += r["fragments"]
    user.super_fragments += r["super_fragments"]
    user.xp += r["xp"]
    names = []
    for item_id in r["items"]:
        item = item_from_dict({"id": item_id})
        user.items.append(item)
        names.append(item.name)
    if r["super_fragments"]:
        names.append(f"{r['super_fragments']} Arrowhead{'s' if r['super_fragments'] > 1 else ''}")
    user.data.setdefault("web_requiem", {})[key] = i + 1
    if BY_KEY[key]["stages"][i].get("finale") and titles.grant(user, title_of(key)):
        names.append(f"the title “{title_of(key)}”")
    return {"won": True, "fragments": r["fragments"], "xp": r["xp"], "stand_xp": r["stand_xp"], "item": ", ".join(names) or None}


# ── Calibration (scripts/balance.py requiem) ────────────────────────────

def rate(key: str, i: int, m: float, runs: int = 16) -> float:
    from app.game import simulate
    team = bench_team() + ([guest(key, i)] if guest(key, i) else [])
    return simulate.run(team, {"name": "rq", "team": enemy_team(key, i, m), "ai": "smart"}, runs)["rate"]


def _decreasing(ys: list) -> list:
    """The closest non-increasing curve to noisy win rates (pool adjacent violators): stronger enemies never win less."""
    blocks = []  # [sum, count]
    for y in ys:
        blocks.append([y, 1])
        while len(blocks) > 1 and blocks[-2][0] / blocks[-2][1] < blocks[-1][0] / blocks[-1][1]:
            s2, c2 = blocks.pop()
            blocks[-1][0] += s2
            blocks[-1][1] += c2
    out = []
    for total, count in blocks:
        out += [total / count] * count
    return out


GRID = [round(0.6 * (10 ** (k / 15)), 3) for k in range(16)]  # 0.6x .. 6x, evenly spaced on a log scale


def calibrate(keys=None, runs: int = 40) -> dict:
    """Each stage's multiplier: its win rate measured across GRID, smoothed into a curve that only goes down as
    enemies get stronger, read where it crosses the stage's target. Writes requiem.json; returns {track: [mult…]}."""
    import random
    random.seed(20261011)
    out = dict(MULT)
    for t in TRACKS:
        if keys and t["key"] not in keys:
            continue
        n, row = len(t["stages"]), []
        for i, s in enumerate(t["stages"]):
            goal = target(i, n, s)
            curve = _decreasing([rate(t["key"], i, m, runs) for m in GRID])
            lo, hi = GRID[0], GRID[-1]
            for k in range(1, len(GRID)):
                if curve[k] < goal <= curve[k - 1]:  # the two grid points around the target
                    lo, hi = GRID[k - 1], GRID[k]
                    break
            else:
                lo = hi = GRID[0] if curve[0] < goal else GRID[-1]
            # win rates fall off a cliff over a narrow band of strength: find the target on it with a finer search
            for _ in range(7 if lo != hi else 0):
                mid = (lo * hi) ** 0.5
                lo, hi = (mid, hi) if rate(t["key"], i, mid, runs * 2) >= goal else (lo, mid)
            row.append(round((lo * hi) ** 0.5, 3))
        out[t["key"]] = row
    with open(DATA, "w", encoding="utf-8") as fh:
        json.dump({"_comment": "Requiem multipliers (enemy health and damage) per track and stage, calibrated against "
                               "requiem.BENCH with scripts/balance.py requiem.", "mult": out}, fh, indent=2)
        fh.write("\n")
    MULT.clear()
    MULT.update(out)
    return out
