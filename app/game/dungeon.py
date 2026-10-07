"""The Delve: a free daily dungeon. No energy: one run a day.

Each day brings a new dungeon, the same for everyone (seeded by the date): DEPTHS floors of
corridors under a fog, each hiding fights, an elite, chests, traps and a campfire. The team
walks in at full health and keeps its wounds from fight to fight (campfires heal, traps hurt).
Fights and chests fill a loot bag that is only paid out when the run ends:
  - standing on a stairway, take the bag home or go deeper (harder fights, bigger loot);
  - the last floor's stairway is guarded by a boss: beating it pays the bag plus a bonus;
  - if the team falls (or gives up), only half the bag comes home.
Enemies are scaled to the team you bring in (its average level), so the dungeon stays a
challenge at every stage of the game.

Save:  data["web_delve"] = {"day", "runs", "best", "last", "run": run or None}
       run = {"day", "depth", "pos", "seen": ["x:y"], "done": ["x:y"], "power", "bag": {"fragments", "items"}}
Redis: web:delve:team:<uid>  pickled fighters of the run in progress
"""
import math
import pickle
import random
from collections import deque
from functools import lru_cache
from typing import Optional

from app.game import tower
from app.game.items import item_file, item_from_dict
from app.game.logic import GameError, check_achievements, now, track_quest_progress, train

W, H = 11, 9            # tiles; rooms sit on even coordinates, the odd tiles between them are walls or doors
START = (0, 0)
DEPTHS = 3
RUNS_PER_DAY = 1
LOOPS = 0.15            # share of inner walls knocked down, so the maze has more than one way round
EVENTS = (("fight", 4), ("elite", 1), ("chest", 3), ("trap", 2), ("camp", 1))
POWER_SHARE = 0.8       # enemies sit a little under a tower floor of the team's own level...
DEPTH_STEP = (-1, 2, 5)  # ...and climb with each depth
ELITE_STEP, BOSS_STEP = 3, 6
TRAP_HIT = 0.15         # share of max health a trap takes (never a killing blow)
CAMP_HEAL, CAMP_REVIVE = 0.40, 0.25
WIPE_KEEP = 0.5         # share of the bag that comes home when the team falls or gives up
CHEST_ITEMS = ((47, 30), (38, 20), (39, 15), (40, 20), (7, 5), (2, 3), (None, 12))  # (item id or nothing, weight)
BOSS_ITEMS = (38, 39, 40)
BOSS_PALM = 0.30        # chance the boss also drops a Devil's Palm
ICONS = {"fight": "!", "elite": "☠", "chest": "◇", "trap": "×", "camp": "♨", "stairs": "⇩", "boss": "♛"}
NAMES = {"fight": "Monsters", "elite": "Elite", "chest": "Chest", "trap": "Trap", "camp": "Campfire",
         "stairs": "Stairs down", "boss": "Boss"}
MOVES = {"up": (0, -1), "down": (0, 1), "left": (-1, 0), "right": (1, 0)}
FIGHTS = ("fight", "elite", "boss")


def team_key(uid) -> str:
    return f"web:delve:team:{uid}"


def day_key() -> str:
    return now().date().isoformat()


def key(tile) -> str:
    return f"{tile[0]}:{tile[1]}"


def state(user) -> dict:
    """Today's record. A run started before midnight carries on, but the run count starts over."""
    s = user.data.get("web_delve")
    if not s or s.get("day") != day_key():
        s = {"day": day_key(), "runs": 0, "best": 0, "last": (s or {}).get("last"), "run": (s or {}).get("run")}
        user.data["web_delve"] = s
    return s


def runs_left(user) -> int:
    return max(0, RUNS_PER_DAY - state(user)["runs"])


# ── Floors ───────────────────────────────────────────────────────────────

def _neighbours(tile):
    x, y = tile
    return [(x + dx, y + dy) for dx, dy in MOVES.values()]


@lru_cache(maxsize=64)
def floor_plan(day: str, depth: int) -> dict:
    """A floor's maze (depth-first carve plus a few loops), its stairs (the room farthest from the start)
    and its events. The same for everyone on that day."""
    rng = random.Random(f"delve:{day}:{depth}")
    rooms = {(x, y) for y in range(0, H, 2) for x in range(0, W, 2)}
    open_tiles, seen, stack = {START}, {START}, [START]
    while stack:
        x, y = stack[-1]
        nxt = sorted(r for r in ((x + 2, y), (x - 2, y), (x, y + 2), (x, y - 2)) if r in rooms and r not in seen)
        if not nxt:
            stack.pop()
            continue
        room = rng.choice(nxt)
        open_tiles |= {room, ((x + room[0]) // 2, (y + room[1]) // 2)}
        seen.add(room)
        stack.append(room)
    walls = sorted((x, y) for y in range(H) for x in range(W) if (x + y) % 2 == 1 and (x, y) not in open_tiles)
    open_tiles |= set(rng.sample(walls, int(len(walls) * LOOPS)))

    dist, queue = {START: 0}, deque([START])
    while queue:
        tile = queue.popleft()
        for n in _neighbours(tile):
            if n in open_tiles and n not in dist:
                dist[n] = dist[tile] + 1
                queue.append(n)
    stairs = max(sorted(rooms), key=lambda r: dist[r])
    spots = [r for r in sorted(rooms) if r not in (START, stairs) and dist[r] > 2]
    rng.shuffle(spots)
    dead_ends = [r for r in spots if sum(n in open_tiles for n in _neighbours(r)) == 1]
    events = {}
    for kind, count in EVENTS:
        for _ in range(count):
            pool = [r for r in (dead_ends if kind == "chest" else []) + spots if r not in events]
            if pool:
                events[pool[0]] = kind
    events[stairs] = "boss" if depth == DEPTHS else "stairs"
    return {"open": frozenset(open_tiles), "stairs": stairs, "events": events}


def _plan(run) -> dict:
    return floor_plan(run["day"], run["depth"])


def power_for(team) -> int:
    """The tower floor whose enemies match the team's average level."""
    avg = sum(c.level for c in team) / max(1, len(team))
    return max(1, round(POWER_SHARE * max(0.0, avg - 1) ** 0.8))


def enemy_floor(run, kind: str) -> int:
    step = DEPTH_STEP[run["depth"] - 1] + (ELITE_STEP if kind == "elite" else BOSS_STEP if kind == "boss" else 0)
    return max(1, run["power"] + step)


def enemies(run, tile, kind: str) -> list:
    floor = enemy_floor(run, kind)
    rng = random.Random(f"delve:{run['day']}:{run['depth']}:{key(tile)}")
    rarities = tower._rarities(floor)
    if kind == "boss":
        rarities = ["LR" if floor >= 25 else "UR"] + rarities[:2]  # the boss leads
    elif kind == "elite":
        rarities = rarities[1:] + ["UR" if floor >= 15 else "SSR"]
    ids = []
    for rarity in rarities:
        ids.append(rng.choice([i for i in tower.POOLS[rarity] if i not in ids]))
    return tower.floor_team(floor, ids=ids, climb=False)


# ── Loot ────────────────────────────────────────────────────────────────

def dust_for(floor: int) -> int:
    from app.game.economy import dust
    return dust(40 * 1.07 ** floor)


def _roll(rng, table) -> Optional[int]:
    return rng.choices([i for i, _ in table], weights=[w for _, w in table], k=1)[0]


def item_name(item_id: int) -> str:
    it = item_file[item_id - 1]
    return f"{it['name']}"


def bag_view(bag) -> dict:
    return {"fragments": bag["fragments"], "items": [item_name(i) for i in bag["items"]]}


# ── The run ──────────────────────────────────────────────────────────────

def load_team(redis, uid) -> Optional[list]:
    raw = redis.get(team_key(uid))
    return pickle.loads(raw) if raw else None


def save_team(redis, uid, team: list):
    redis.set(team_key(uid), pickle.dumps(team), ex=60 * 60 * 48)


def start(user, redis, fighters: list) -> dict:
    s = state(user)
    if s.get("run"):
        raise GameError("You're already in the dungeon.")
    if not user.main_characters:
        raise GameError("Put stands in your team before you enter the dungeon.")
    if runs_left(user) < 1:
        raise GameError("You've been down today. A new dungeon opens at midnight.")
    s["runs"] += 1
    s["run"] = {"day": s["day"], "depth": 1, "pos": list(START), "seen": [key(START)], "done": [],
                "power": power_for(fighters), "bag": {"fragments": 0, "items": []}}
    save_team(redis, user.id, fighters)
    return s["run"]


def _run(user, redis) -> tuple:
    run = state(user).get("run")
    if not run:
        raise GameError("Enter the dungeon first.")
    team = load_team(redis, user.id)
    if not team or not any(c.is_alive() for c in team):
        end(user, redis, WIPE_KEEP, "lost")
        raise GameError("Your expedition expired. Half the loot bag was sent home.")
    return run, team


def move(user, redis, direction: str) -> dict:
    """Step one tile. Returns {"kind": event or "move", "message", and for a fight "enemies"}."""
    run, team = _run(user, redis)
    delta = MOVES.get(direction)
    plan = _plan(run)
    if delta is None:
        raise GameError("Pick a direction.")
    target = (run["pos"][0] + delta[0], run["pos"][1] + delta[1])
    if target not in plan["open"]:
        raise GameError("A wall blocks the way.")
    run["pos"] = list(target)
    if key(target) not in run["seen"]:
        run["seen"].append(key(target))
    kind = plan["events"].get(target)
    if kind is None or key(target) in run["done"]:
        return {"kind": "move", "message": None}
    if kind in FIGHTS:
        return {"kind": "fight", "event": kind, "enemies": enemies(run, target, kind),
                "message": None, "tile": key(target)}
    if kind == "stairs":
        return {"kind": "stairs", "message": "Stairs lead down. Take the loot home, or go deeper."}
    run["done"].append(key(target))
    rng = random.Random(f"delve:{run['day']}:{run['depth']}:{key(target)}:loot:{user.id}")
    if kind == "chest":
        dust = dust_for(run["power"] + 2 * run["depth"]) // 2
        item = _roll(rng, CHEST_ITEMS)
        run["bag"]["fragments"] += dust
        if item:
            run["bag"]["items"].append(item)
        message = f"Chest: +{dust:,} Meteor Dust" + (f" and {item_name(item)}" if item else "") + " into the bag."
    elif kind == "trap":
        for c in team:
            if c.current_hp > 0:
                c.current_hp = max(1, int(c.current_hp - c.start_hp * TRAP_HIT))
        message = f"A trap! Every stand loses {round(TRAP_HIT * 100)}% of its health."
    else:  # camp
        for c in team:
            share = CAMP_HEAL if c.current_hp > 0 else CAMP_REVIVE
            c.current_hp = min(c.start_hp, int(c.current_hp + c.start_hp * share))
        message = f"A campfire: the team heals {round(CAMP_HEAL * 100)}%, and fallen stands get back up."
    save_team(redis, user.id, team)
    return {"kind": kind, "message": message}


def fight_tile(user) -> Optional[str]:
    """The fight waiting on the tile you stand on (it was left, or the page reloaded), if any."""
    run = state(user).get("run")
    if not run:
        return None
    tile = tuple(run["pos"])
    kind = _plan(run)["events"].get(tile)
    return kind if kind in FIGHTS and key(tile) not in run["done"] else None


def finish_fight(user, fight, redis) -> dict:
    """Settle a fight: a loss ends the run, a win fills the bag (and a boss win ends the run in triumph)."""
    rewards = {"won": fight.winner == 0, "fragments": 0, "xp": 0, "stand_xp": 0, "item": None}
    run = state(user).get("run")
    if not run:
        return rewards
    if fight.winner != 0:
        rewards["delve"] = end(user, redis, WIPE_KEEP, "lost")
        return rewards
    tile, kind = run["pos"], fight.meta.get("event", "fight")
    floor = enemy_floor(run, kind)
    run["done"].append(key(tile))
    team = tower.settle_fighters(fight.sides[0].chars)
    save_team(redis, user.id, team)
    dust = dust_for(floor) * (2 if kind == "elite" else 3 if kind == "boss" else 1)
    run["bag"]["fragments"] += dust
    found = []
    rng = random.Random(f"delve:{run['day']}:{run['depth']}:{key(tile)}:loot:{user.id}")
    if kind == "elite":
        found = [i for i in [_roll(rng, CHEST_ITEMS)] if i]
    elif kind == "boss":
        found = [rng.choice(BOSS_ITEMS)] + ([2] if rng.random() < BOSS_PALM else [])
    run["bag"]["items"].extend(found)
    stand_xp = (6 + 3 * run["depth"]) * (2 if kind != "fight" else 1)
    for c in user.main_characters:
        train(c, stand_xp)
    user.xp += 40 * run["depth"]
    rewards.update(xp=40 * run["depth"], stand_xp=stand_xp,
                   item=f"+{dust:,} Meteor Dust" + "".join(f", {item_name(i)}" for i in found) + " into your loot bag")
    if kind == "boss":
        rewards["delve"] = end(user, redis, 1.0, "cleared")
    return rewards


def descend(user, redis):
    run, team = _run(user, redis)
    if tuple(run["pos"]) != _plan(run)["stairs"] or run["depth"] >= DEPTHS:
        raise GameError("Find the stairs first.")
    run.update(depth=run["depth"] + 1, pos=list(START), seen=[key(START)], done=[])
    s = state(user)
    s["best"] = max(s.get("best", 0), run["depth"])
    return run


def cash_out(user, redis) -> dict:
    run, _ = _run(user, redis)
    if tuple(run["pos"]) != _plan(run)["stairs"]:
        raise GameError("Only the stairs lead out. Find them, or give up and keep half the bag.")
    return end(user, redis, 1.0, "left")


def give_up(user, redis) -> dict:
    if not state(user).get("run"):
        raise GameError("You're not in the dungeon.")
    return end(user, redis, WIPE_KEEP, "lost")


def end(user, redis, keep: float, how: str) -> dict:
    """Close the run and pay the bag (all of it, or a share). how: "left", "cleared" or "lost"."""
    s = state(user)
    run = s.get("run")
    s["run"] = None
    redis.delete(team_key(user.id))
    if not run:
        return {}
    bag = run["bag"]
    dust = int(bag["fragments"] * keep)
    items = bag["items"][:math.ceil(len(bag["items"]) * keep)] if keep < 1 else bag["items"]
    user.fragments += dust
    user.items.extend(item_from_dict({"id": i}) for i in items)
    s["best"] = max(s.get("best", 0), run["depth"])
    s["last"] = {"how": how, "depth": run["depth"], "fragments": dust, "items": [item_name(i) for i in items],
                 "lost": bag["fragments"] - dust, "lost_items": len(bag["items"]) - len(items)}
    if how != "lost":
        user.data["web_dungeon_completions"] = int(user.data.get("web_dungeon_completions", 0)) + 1
        track_quest_progress(user, "dungeon_complete")
        check_achievements(user, "dungeon_complete")
    return s["last"]


# ── Drawing ──────────────────────────────────────────────────────────────

def cells(run) -> list:
    """The map under its fog: tiles you've stood on and their neighbours are revealed."""
    plan = _plan(run)
    seen = {tuple(map(int, k.split(":"))) for k in run["seen"]}
    lit = seen | {n for t in seen for n in _neighbours(t)}
    pos = tuple(run["pos"])
    out = []
    for y in range(H):
        for x in range(W):
            tile = (x, y)
            kind = plan["events"].get(tile)
            done = key(tile) in run["done"]
            shown = tile in lit
            out.append({"x": x, "y": y, "fog": not shown, "wall": shown and tile not in plan["open"],
                        "current": tile == pos, "visited": tile in seen,
                        "event": kind if shown and kind and (not done or kind == "stairs") else None,
                        "done": shown and done})
    return out


def allowed_moves(run) -> list:
    plan = _plan(run)
    x, y = run["pos"]
    return [d for d, (dx, dy) in MOVES.items() if (x + dx, y + dy) in plan["open"]]
