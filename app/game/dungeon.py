"""The Delve: a free daily dungeon. No energy: one run a day.

Each day brings a new dungeon, the same for everyone (seeded by the date): DEPTHS floors of
corridors under a fog, each hiding fights, an elite, chests, traps and a campfire. B1-B3 are the delve, matched to
your team; below them the dungeon stops matching you: B4-B6 are the Over Heaven depths (Requiem-strength enemies
rising to Over Heaven's level, one of heaven's rules per floor) and B7-B9 the Requiem depths (rising to Requiem
mode's strength). A boss guards the stairs of B3, B6 and B9: beat it, then take the bag home or go deeper. Loot and
XP grow with every floor. The team
walks in at full health and keeps its wounds from fight to fight (campfires heal, traps hurt).
Fights and chests fill a loot bag that is only paid out when the run ends:
  - standing on a stairway, take the bag home or go deeper (harder fights, bigger loot);
  - B3, B6 and B9's stairways are guarded by a boss; beating the last one pays the bag plus a bonus;
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
DEPTHS = 9
BOSS_DEPTHS = (3, 6, 9)
HEAVEN_FROM, REQUIEM_FROM = 4, 7  # the Over Heaven depths (B4-B6) and the Requiem depths (B7-B9)
RUNS_PER_DAY = 1
LOOPS = 0.15            # share of inner walls knocked down, so the maze has more than one way round
EVENTS = (("fight", 4), ("elite", 1), ("chest", 3), ("trap", 2), ("camp", 1))
POWER_SHARE = 0.8       # enemies sit a little under a tower floor of the team's own level...
DEPTH_STEP = (-1, 2, 5)  # ...and climb with each depth (B1-B3)
# Below B3 enemies are absolute: requiem.crew (level 100, ★5, Universal, refined items) times these. Calibrated with the
# simulator against requiem.BENCH: a fresh top team wins a B4 fight every time and a B9 boss about half the time,
# and wounds carry from fight to fight.
DEEP_MULT = {4: 1.20, 5: 1.35, 6: 1.45, 7: 1.50, 8: 1.58, 9: 1.65}
DEEP_KIND = {"fight": 1.0, "elite": 1.05, "boss": 1.1}
LOOT_MULT = (1, 1, 1, 1.6, 1.9, 2.3, 2.8, 3.3, 4.0)  # by depth: the bag's dust (B4 and below)
XP_GROWTH = 0.15        # stand and player XP grow 15% per floor on top of the depth itself
RUN_XP_PER_FLOOR = 400  # player XP for bringing a run home (left or cleared), per floor reached
DEEP_BOSS_PALM = 6      # the B6 boss always adds a Devil's Palm...
REQUIEM_ARROW_CHANCE = 0.15  # ...and the B9 boss may add a Requiem Arrow
ELITE_STEP, BOSS_STEP = 3, 6
TRAP_HIT = 0.15         # share of max health a trap takes (never a killing blow)
CAMP_HEAL, CAMP_REVIVE = 0.40, 0.25
WIPE_KEEP = 0.5         # share of the bag that comes home when the team falls or gives up
CHEST_ITEMS = ((47, 30), (38, 20), (39, 15), (40, 20), (15, 15), (7, 5), (2, 3), (None, 12))  # (item id or nothing, weight)
BOSS_ITEMS = (38, 39, 40)
BOSS_PALM = 0.30        # chance the boss also drops a Devil's Palm
BOSS_GEAR, BOSS_GEAR_CHANCE = (62, 63), 0.25  # ...and a piece of the dungeon's own gear: Cioccolata's Spores, Ghiaccio's Goggles
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
    events[stairs] = "boss" if depth in BOSS_DEPTHS else "stairs"
    return {"open": frozenset(open_tiles), "stairs": stairs, "events": events}


def _plan(run) -> dict:
    return floor_plan(run["day"], run["depth"])


def power_for(team) -> int:
    """The tower floor whose enemies match the team's average level."""
    avg = sum(c.level for c in team) / max(1, len(team))
    return max(1, round(POWER_SHARE * max(0.0, avg - 1) ** 0.8))


def band(depth: int) -> str:
    """"delve" (B1-B3, matched to the team), "heaven" (B4-B6) or "requiem" (B7-B9)."""
    return "requiem" if depth >= REQUIEM_FROM else "heaven" if depth >= HEAVEN_FROM else "delve"


BAND_NAMES = {"delve": "The delve", "heaven": "Over Heaven depths", "requiem": "Requiem depths"}


def enemy_floor(run, kind: str) -> int:
    """The tower-floor strength of a B1-B3 enemy (deeper floors use it, at B3, for their loot)."""
    step = DEPTH_STEP[min(run["depth"], len(DEPTH_STEP)) - 1] + (ELITE_STEP if kind == "elite" else BOSS_STEP if kind == "boss" else 0)
    return max(1, run["power"] + step)


def floor_rules(day: str, depth: int, kind: str = "fight") -> dict:
    """Heaven's rule on an Over Heaven floor (the same for everyone that day), plus a second one for its boss."""
    if band(depth) != "heaven":
        return {}
    from app.game import overheaven
    return overheaven.random_rules(f"delve:{day}:{depth}", 2 if kind == "boss" else 1)


def warning(depth: int) -> Optional[str]:
    """What waits on floor `depth`, shown before going down to it (None for the gentle floors)."""
    if depth < HEAVEN_FROM:
        return None
    strength = round(DEEP_MULT[depth] * 100)
    boss = " Its stairs are guarded by a boss." if depth in BOSS_DEPTHS else ""
    if band(depth) == "heaven":
        first = "You leave the delve behind: these are the Over Heaven depths. " if depth == HEAVEN_FROM else ""
        return (f"{first}B{depth}: every enemy is level 100 ★5 at {strength}% strength with refined items, and one of "
                f"heaven's rules holds the whole floor.{boss} Loot ×{LOOT_MULT[depth - 1]:g}.")
    first = "The Requiem depths: Requiem mode's strength, no more mercy. " if depth == REQUIEM_FROM else ""
    return (f"{first}B{depth}: level 100 ★5 enemies at {strength}% strength with refined items.{boss} "
            f"Loot ×{LOOT_MULT[depth - 1]:g}. If your team falls, half the bag is lost.")


def enemies(run, tile, kind: str) -> list:
    rng = random.Random(f"delve:{run['day']}:{run['depth']}:{key(tile)}")
    if run["depth"] >= HEAVEN_FROM:  # the deep floors: absolute strength, UR and LR crews
        from app.game import requiem
        rarities = {"fight": ["SSR", "UR", "UR"], "elite": ["UR", "UR", "UR"], "boss": ["LR", "UR", "UR"]}[kind]
        ids = []
        for rarity in rarities:
            ids.append(rng.choice([i for i in tower.POOLS[rarity] if i not in ids]))
        return requiem.crew(ids, DEEP_MULT[run["depth"]] * DEEP_KIND[kind])
    floor = enemy_floor(run, kind)
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


EXPIRED = "Your expedition expired. Half the loot bag was sent home."


def close_if_stale(user, redis) -> Optional[str]:
    """A run whose fighters are gone (their copy expired, or all fell outside a fight) is closed here, without an
    error, so the caller saves it: raising after end() used to throw the close away and strand the run."""
    run = state(user).get("run")
    if not run:
        return None
    team = load_team(redis, user.id)
    if team and any(c.is_alive() for c in team):
        return None
    end(user, redis, WIPE_KEEP, "lost")
    return EXPIRED


def _run(user, redis) -> tuple:
    run = state(user).get("run")
    if not run:
        raise GameError("Enter the dungeon first.")
    team = load_team(redis, user.id)
    if not team or not any(c.is_alive() for c in team):
        raise GameError(EXPIRED + " Reload the dungeon page to settle it.")  # see close_if_stale
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
        dust = int(dust_for(run["power"] + 2 * min(run["depth"], 3)) // 2 * LOOT_MULT[run["depth"] - 1])
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
    depth = run["depth"]
    dust = int(dust_for(floor) * (2 if kind == "elite" else 3 if kind == "boss" else 1) * LOOT_MULT[depth - 1])
    run["bag"]["fragments"] += dust
    found = []
    rng = random.Random(f"delve:{run['day']}:{depth}:{key(tile)}:loot:{user.id}")
    if kind == "elite":
        found = [i for i in [_roll(rng, CHEST_ITEMS)] if i]
    elif kind == "boss":
        found = [rng.choice(BOSS_ITEMS)]
        if depth >= DEEP_BOSS_PALM or rng.random() < BOSS_PALM:
            found.append(2)
        if rng.random() < BOSS_GEAR_CHANCE:
            found.append(rng.choice(BOSS_GEAR))
        if depth == DEPTHS and rng.random() < REQUIEM_ARROW_CHANCE:
            found.append(3)
    run["bag"]["items"].extend(found)
    stand_xp, player_xp = xp_for(depth, kind)
    for c in user.main_characters:
        train(c, stand_xp)
    user.xp += player_xp
    rewards.update(xp=player_xp, stand_xp=stand_xp,
                   item=f"+{dust:,} Meteor Dust" + "".join(f", {item_name(i)}" for i in found) + " into your loot bag")
    if kind == "boss":
        if depth == BOSS_DEPTHS[0]:  # down to the first boss (the Deep Delver title)
            user.data["web_dungeon_clears"] = int(user.data.get("web_dungeon_clears", 0)) + 1
        if depth >= DEPTHS:
            rewards["delve"] = end(user, redis, 1.0, "cleared")
        else:
            rewards["delve_boss"] = {"depth": depth, "next": warning(depth + 1)}
    return rewards


def xp_for(depth: int, kind: str = "fight") -> tuple:
    """(each team stand's XP, player XP) for a fight won on floor `depth`: both grow with every floor."""
    from app.game.economy import stand_xp as paced
    grow = 1 + XP_GROWTH * (depth - 1)
    return paced((6 + 3 * depth) * (2 if kind != "fight" else 1) * grow), round(40 * depth * grow)


def _boss_waiting(run) -> bool:
    """The floor's stairs are guarded by a boss that's still standing."""
    stairs = _plan(run)["stairs"]
    return _plan(run)["events"].get(stairs) == "boss" and key(stairs) not in run["done"]


def descend(user, redis):
    run, team = _run(user, redis)
    if tuple(run["pos"]) != _plan(run)["stairs"] or run["depth"] >= DEPTHS:
        raise GameError("Find the stairs first.")
    if _boss_waiting(run):
        raise GameError("Beat the boss guarding the stairs first.")
    run.update(depth=run["depth"] + 1, pos=list(START), seen=[key(START)], done=[])
    s = state(user)
    s["best"] = max(s.get("best", 0), run["depth"])
    return run


def cash_out(user, redis) -> dict:
    run, _ = _run(user, redis)
    if tuple(run["pos"]) != _plan(run)["stairs"]:
        raise GameError("Only the stairs lead out. Find them, or give up and keep half the bag.")
    if _boss_waiting(run):
        raise GameError("Beat the boss guarding the stairs first.")
    return end(user, redis, 1.0, "cleared" if _plan(run)["events"].get(_plan(run)["stairs"]) == "boss" else "left")


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
        bonus = RUN_XP_PER_FLOOR * run["depth"]
        user.xp += bonus
        s["last"]["xp"] = bonus
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
