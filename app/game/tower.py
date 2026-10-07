"""The Tower: an endless climb that resets every week.

A climb starts at floor 1 with your team at full strength and keeps the very same
fighters from floor to floor: health, permanent growth and losses all carry over
(a 20% patch-up after each floor; every 5th floor is a rest stop that heals 45%
and gets fallen stands back up at 25%). Enemies grow fast: level 100 by floor 27,
★5 by floor 42, every floor adds health and damage, and past ★5 that growth compounds. The
floors of a week are generated from the week's seed, so everyone climbs the same
tower and the weekly leaderboard is fair. A loss ends the climb.

Save: data["web_tower"] = {"week", "best", "paid" (highest floor rewarded this week),
                           "run": {"floor"} or None}
Redis: web:tower:team:<uid>  pickled fighters of the climb in progress
       ZSET web:tower:<week>  uid -> best floor (names in web:tower:<week>:names)
"""
import pickle
import random
from typing import List, Optional

from app.game.character import CHARACTER_FILE, character_from_dict
from app.game.effects import STAT_EFFECTS, remove_terrain_bonuses
from app.game.gangs import week_ends, week_key
from app.game.items import item_file, item_from_dict
from app.game.logic import GameError, now, train

CLIMB_COST = 500
LEVEL_POWER = 1.4      # enemy level = 1 + floor**LEVEL_POWER, so level 100 by floor 27
AWAKEN_FLOORS = (10, 18, 26, 34, 42)  # enemies gain ★1..★5 from these floors
PRESSURE = 0.012       # every floor adds 1.2% health and damage on top of level and stars...
OVERFLOW = 1.07        # ...and past the last awakening floor they multiply by this per floor
ITEM_FLOORS = (8, 20, 35)  # enemies carry one more item from each
REST_EVERY, REST_HEAL = 5, 0.45
FLOOR_HEAL = 0.20      # a breather after every floor; rest stops heal more
# The daily dungeon borrows the tower's enemies on the gentler curve the tower used to have
DELVE_LEVEL_POWER, DELVE_AWAKEN, DELVE_OVERFLOW = 1.25, (15, 25, 35, 50, 60), 1.05
DELVE_EASE_FROM, DELVE_EASE = 25, 0.94  # from here dungeon enemies field UR/LR-era teams, eased
BOSS_EVERY = 10
HEAD_EVERY = 20        # every other boss floor pays an Arrowhead (economy.py)
TRANSIENT = ("_focus", "_my_turn", "_heal_mult", "_skipped", "_stun_guard", "_active_terrain", "_terrain_bonus")
POOLS = {r: [c["id"] for c in CHARACTER_FILE if c["rarity"] == r and c["universe"] != "Dummy" and c["id"] != 110]
         for r in ("R", "SR", "SSR", "UR", "LR")}


def team_key(uid) -> str:
    return f"web:tower:team:{uid}"


def state(user) -> dict:
    s = user.data.get("web_tower")
    if not s or s.get("week") != week_key():
        s = {"week": week_key(), "best": 0, "paid": 0, "run": None}
        user.data["web_tower"] = s
    return s


# ── Floors ───────────────────────────────────────────────────────────────

def level_for(floor: int, power: float = LEVEL_POWER) -> int:
    return max(1, min(100, round(1 + floor ** power)))


def awaken_for(floor: int, floors=AWAKEN_FLOORS) -> int:
    return sum(floor >= f for f in floors)


def overflow_for(floor: int) -> float:
    """Health/damage multiplier once level and awakenings are maxed."""
    extra = floor - AWAKEN_FLOORS[-1]
    return OVERFLOW ** extra if extra > 0 else 1.0


def power_for(floor: int) -> float:
    """Every multiplier on a floor's health and damage: the steady pressure and, past ★5, the overflow."""
    return (1 + PRESSURE * floor) * overflow_for(floor)


def quality_for(floor: int) -> str:
    return ("BAD" if floor < 4 else "SUB_PAR" if floor < 8 else "GOOD" if floor < 14 else "GREAT" if floor < 22
            else "SUPREME" if floor < 32 else "UNIVERSAL")


def _delve(floor: int) -> tuple:
    """(level, stars, multiplier, quality, items) of a dungeon enemy at this tower-floor strength."""
    extra = floor - DELVE_AWAKEN[-1]
    mult = (DELVE_OVERFLOW ** extra if extra > 0 else 1.0) * (DELVE_EASE if floor >= DELVE_EASE_FROM else 1.0)
    quality = ("BAD" if floor < 5 else "SUB_PAR" if floor < 10 else "GOOD" if floor < 18 else "GREAT" if floor < 30
               else "SUPREME" if floor < 45 else "UNIVERSAL")
    return level_for(floor, DELVE_LEVEL_POWER), awaken_for(floor, DELVE_AWAKEN), mult, quality, int(floor >= 8)


def is_boss(floor: int) -> bool:
    return floor % BOSS_EVERY == 0


def is_rest(floor: int) -> bool:
    return floor % REST_EVERY == 0


def _climb_rarities(floor: int) -> List[str]:
    if floor < 3:
        return ["R", "SR"]  # a two-stand warm-up
    if floor < 5:
        return ["R", "SR", "SR"]
    if floor < 9:
        return ["SR", "SR", "SSR"]
    if floor < 16:
        return ["SR", "SSR", "SSR"]
    if floor < 25:
        return ["SSR", "SSR", "UR"]
    if floor < 40:
        return ["SSR", "UR", "UR"]
    return ["UR", "UR", "UR"]


def _rarities(floor: int) -> List[str]:
    """The dungeon's rarities at a tower-floor strength (the climb has its own, _climb_rarities)."""
    if floor < 6:
        return ["R", "SR"]
    if floor < 10:
        return ["R", "R", "SR"]
    if floor < 15:
        return ["SR", "SR", "SSR"]
    if floor < 30:
        return ["SR", "SSR", "SSR"]
    if floor < 45:
        return ["SSR", "SSR", "UR"]
    return ["SSR", "UR", "UR"]


def floor_ids(floor: int, week: Optional[str] = None) -> List[int]:
    rng = random.Random(f"{week or week_key()}:{floor}")
    rarities = _climb_rarities(floor)
    if is_boss(floor):
        rarities = rarities[:2] + ["LR" if floor >= 20 else "UR"]
    ids = []
    for rarity in rarities:
        pool = [i for i in POOLS[rarity] if i not in ids]
        ids.append(rng.choice(pool))
    return ids[::-1] if is_boss(floor) else ids  # the boss leads


def floor_team(floor: int, week: Optional[str] = None, ids: Optional[List[int]] = None, climb: bool = True) -> list:
    """The enemies of a floor; ids: other stands at that floor's strength. climb=False: the dungeon's gentler curve."""
    if climb:
        lvl, aw, mult, quality = level_for(floor), awaken_for(floor), power_for(floor), quality_for(floor)
        items = sum(floor >= f for f in ITEM_FLOORS)
    else:
        lvl, aw, mult, quality, items = _delve(floor)
    team = []
    for cid in ids or floor_ids(floor, week):
        c = character_from_dict({"id": cid, "xp": lvl * 100, "awaken": aw, "types": ["BALANCE"],
                                 "qualities": [quality], "items": [{"id": 1}] * items})
        if mult != 1:
            for stat in ("hp", "damage"):
                value = getattr(c, f"start_{stat}") * mult
                setattr(c, f"start_{stat}", int(value))
                setattr(c, f"current_{stat}", int(value))
        team.append(c)
    return team


def preview(floor: int) -> dict:
    return {"floor": floor, "ids": floor_ids(floor), "level": level_for(floor), "awaken": awaken_for(floor),
            "mult": round(power_for(floor), 2), "boss": is_boss(floor), "rest": is_rest(floor),
            "stands": [CHARACTER_FILE[i - 1] for i in floor_ids(floor)], "reward": reward_view(floor)}


# ── Rewards ─────────────────────────────────────────────────────────────

def stand_xp_for(floor: int) -> int:
    """Each team stand's XP for a floor's first clear of the week: flat, so the tower doesn't outpace the rest."""
    return 10 + floor // 2


def reward_for(floor: int) -> dict:
    """Paid the first time each week you clear a floor."""
    from app.game.economy import dust
    reward = {"fragments": dust(80 * 1.08 ** floor), "items": [], "super": 0}
    if floor % 5 == 0:
        reward["items"].append([40, 38, 39][(floor // 5) % 3])
    elif floor % 5 == 3:
        reward["items"].append(47)  # a Can of Energy keeps the climb going
    if floor % HEAD_EVERY == 0:
        reward["super"] = 1
    return reward


def reward_view(floor: int) -> dict:
    """A floor's first-clear reward, ready to draw: dust, each team stand's XP, items and Arrowheads."""
    r = reward_for(floor)
    return {"fragments": r["fragments"], "stand_xp": stand_xp_for(floor), "super": r["super"],
            "items": [{"name": item_file[i - 1]["name"], "emoji": item_file[i - 1]["emoji"]} for i in r["items"]]}


def milestones(after: int, count: int = 4) -> list:
    """The next floors past `after` that pay more than dust: items every 5th floor, an Arrowhead every 20th."""
    first = (after // REST_EVERY + 1) * REST_EVERY
    return [{"floor": f, **reward_view(f)} for f in range(first, first + REST_EVERY * count, REST_EVERY)]


def reward_text(floor: int) -> str:
    r = reward_for(floor)
    parts = [f"{r['fragments']:,} Meteor Dust"] + [item_file[i - 1]["name"] for i in r["items"]]
    if r["super"]:
        parts.append("1 Arrowhead")
    return ", ".join(parts)


# ── The climb ───────────────────────────────────────────────────────────

def load_team(redis, uid) -> Optional[list]:
    raw = redis.get(team_key(uid))
    return pickle.loads(raw) if raw else None


def save_team(redis, uid, team: list):
    redis.set(team_key(uid), pickle.dumps(team), ex=60 * 60 * 24 * 9)


def settle_fighters(team: list) -> list:
    """After a floor: undo effects and terrain, keep health and permanent growth."""
    remove_terrain_bonuses(team)
    for c in team:
        for e in c.effects:
            if e.type in STAT_EFFECTS and e.used:
                attr, sign = STAT_EFFECTS[e.type]
                setattr(c, attr, getattr(c, attr) - sign * e.value)
        c.effects = []
        c.special_meter = 0
        c.current_hp = max(0, min(c.current_hp, c.start_hp))
        for attr in TRANSIENT:
            c.__dict__.pop(attr, None)
    return team


REVIVE = 0.25          # rest stops also bring fallen stands back at this share


def patch_up(team: list, floor: int):
    """Heal the survivors between floors; rest stops also revive the fallen."""
    rest = is_rest(floor)
    share = REST_HEAL if rest else FLOOR_HEAL
    for c in team:
        if c.current_hp > 0:
            c.current_hp = min(c.start_hp, int(c.current_hp + c.start_hp * share))
        elif rest:
            c.current_hp = int(c.start_hp * REVIVE)


def start_climb(user, redis, fighters: list):
    s = state(user)
    if s.get("run"):
        raise GameError("You're already climbing.")
    if not user.main_characters:
        raise GameError("Put stands in your team before you climb.")
    if user.fragments < CLIMB_COST:
        raise GameError(f"A climb costs {CLIMB_COST} Meteor Dust.")
    user.fragments -= CLIMB_COST
    s["run"] = {"floor": 1}
    save_team(redis, user.id, fighters)


def abandon(user, redis):
    state(user)["run"] = None
    redis.delete(team_key(user.id))


def finish_floor(user, fight, redis, name: str) -> dict:
    s = state(user)
    run = s.get("run")
    rewards = {"won": fight.winner == 0, "fragments": 0, "xp": 0, "stand_xp": 0, "item": None}
    if not run:
        return rewards
    floor = run["floor"]
    if fight.winner != 0:
        abandon(user, redis)
        rewards["tower"] = {"floor": floor, "over": True}
        return rewards
    team = settle_fighters(fight.sides[0].chars)
    patch_up(team, floor)
    save_team(redis, user.id, team)
    run["floor"] = floor + 1
    if floor > s["paid"]:
        reward = reward_for(floor)
        user.fragments += reward["fragments"]
        user.super_fragments += reward["super"]
        items = [item_from_dict({"id": i}) for i in reward["items"]]
        user.items.extend(items)
        for c in user.main_characters:
            train(c, stand_xp_for(floor))
        s["paid"] = floor
        names = [i.name for i in items] + (["1 Arrowhead"] if reward["super"] else [])
        if is_boss(floor):  # boss floors also drop a stand chip, most often for one of the climbers' synergies
            from app.game import chips
            chip = chips.grant(user, prefer=team)
            if chip:
                names.append(f"a {chips.view(chip)['label']} chip")
        rewards.update(fragments=reward["fragments"], stand_xp=stand_xp_for(floor), item=", ".join(names) or None)
    if floor > s["best"]:
        s["best"] = floor
        user.tower_level = max(user.tower_level, floor)  # all-time best, shown on the ladder and profile
        key = f"web:tower:{s['week']}"
        redis.zadd(key, {str(user.id): floor})
        redis.hset(f"{key}:names", str(user.id), name)
        redis.expire(key, 60 * 60 * 24 * 21)
        redis.expire(f"{key}:names", 60 * 60 * 24 * 21)
    rewards["tower"] = {"floor": floor, "over": False, "rest": is_rest(floor)}
    return rewards


def leaderboard(redis, limit: int = 10) -> list:
    key = f"web:tower:{week_key()}"
    out = []
    for uid, floor in redis.zrevrange(key, 0, limit - 1, withscores=True):
        uid = uid.decode() if isinstance(uid, bytes) else uid
        name = redis.hget(f"{key}:names", uid)
        out.append({"uid": uid, "name": name.decode() if isinstance(name, bytes) else (name or "?"), "floor": int(floor)})
    return out


def ends_in():
    return week_ends() - now()
