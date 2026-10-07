"""Weekly boss rush: twelve bosses back to back.

The six story bosses come first, each far stronger than in the story (RUSH_CURVE), then they all
come back for an encore at level 100 ★5 with more health and damage every fight.
Your team's health carries over from fight to fight (a 15% patch-up between them),
so a run is a test of the whole team, not of one lucky fight. One run per day; each
boss reached pays a reward the first time each week; the weekly leaderboard ranks
runs by bosses beaten, then by fewest rounds.

Save: data["web_rush"] = {"week", "day", "best": {"bosses", "rounds"}, "claimed": [i...],
                          "run": {"index", "hp": {uuid: hp}, "rounds"} or None}
Redis: ZSET web:rush:<week> uid -> score (bosses * 1000 - rounds)
"""
from typing import Optional

from app.game import story
from app.game.character import character_from_dict
from app.game.gangs import week_ends, week_key
from app.game.items import item_file, item_from_dict
from app.game.logic import GameError, now

BOSS_STAGES = [k for k, st in enumerate(story.STAGES) if st.get("boss")]
# (level, stars, quality, items, health/damage multiplier) of each boss in a run, in order
RUSH_CURVE = [
    (25, 1, "GOOD", 1, 1.0),
    (45, 1, "GREAT", 2, 1.0),
    (65, 2, "GREAT", 2, 1.05),
    (85, 3, "SUPREME", 2, 1.1),
    (100, 4, "SUPREME", 3, 1.15),
    (100, 5, "UNIVERSAL", 3, 1.2),
    # the encore: every boss again, maxed, and tougher each time
    (100, 5, "UNIVERSAL", 3, 1.35),
    (100, 5, "UNIVERSAL", 3, 1.5),
    (100, 5, "UNIVERSAL", 3, 1.7),
    (100, 5, "UNIVERSAL", 3, 1.9),
    (100, 5, "UNIVERSAL", 3, 2.15),
    (100, 5, "UNIVERSAL", 3, 2.45),
]
BOSSES = [BOSS_STAGES[i % len(BOSS_STAGES)] for i in range(len(RUSH_CURVE))]  # story stage of each boss
ENCORE = len(BOSS_STAGES)  # bosses from this index on are the encore
PATCH_UP = 0.15
CHIP_FROM = 3  # bosses from this index on drop a stand chip (the last one an epic) the first time each week
REWARDS = [  # weekly, at the economy's pace (economy.py)
    {"fragments": 350, "items": []},
    {"fragments": 700, "items": [40, 47]},
    {"fragments": 1400, "items": [38]},
    {"fragments": 2100, "items": [39, 40]},
    {"fragments": 2800, "items": [38, 38]},
    {"fragments": 4200, "super": 1, "items": [34]},
    # the encore: only the strongest teams get here, so it pays in items more than in dust
    {"fragments": 1500, "items": [47, 40]},
    {"fragments": 1800, "items": [38]},
    {"fragments": 2100, "items": [38, 39]},
    {"fragments": 2400, "items": [40, 40, 47]},
    {"fragments": 2800, "items": [38, 38]},
    {"fragments": 3500, "super": 1, "items": [35]},
]


def state(user) -> dict:
    s = user.data.get("web_rush")
    if not s or s.get("week") != week_key():
        s = {"week": week_key(), "day": None, "best": {"bosses": 0, "rounds": 0}, "claimed": [], "run": None}
        user.data["web_rush"] = s
    return s


def ran_today(user) -> bool:
    return state(user).get("day") == now().date().isoformat()


def reward_text(i: int) -> str:
    r = REWARDS[i]
    parts = [f"{r['fragments']:,} Meteor Dust"]
    if r.get("super"):
        parts.append(f"{r['super']} Arrowhead{'s' if r['super'] > 1 else ''}")
    parts += [item_file[x - 1]["name"] for x in r["items"]]
    return ", ".join(parts)


def title(i: int) -> str:
    name = story.STAGES[BOSSES[i]]["title"]
    return f"{name} (encore)" if i >= ENCORE else name


def bosses() -> list:
    return [{"index": i, "stage": k, "title": title(i), "part": story.STAGES[k]["part_title"],
             "level": RUSH_CURVE[i][0], "awaken": RUSH_CURVE[i][1], "mult": RUSH_CURVE[i][4],
             "encore": i >= ENCORE, "lead": story.STAGES[k]["enemies"][0],
             "reward": reward_text(i)} for i, k in enumerate(BOSSES)]


def start_run(user):
    s = state(user)
    if not user.main_characters:
        raise GameError("Put stands in your team before starting a run.")
    if s.get("run"):
        raise GameError("Your run is still going.")
    if ran_today(user):
        raise GameError("You already ran the gauntlet today. Come back tomorrow.")
    s["day"] = now().date().isoformat()
    s["run"] = {"index": 0, "hp": {c.uuid: c.start_hp for c in user.main_characters}, "rounds": 0}


def prepare_team(user, team: list) -> list:
    """Apply the run's carried-over health to fresh fighting copies of the team."""
    hp = state(user)["run"]["hp"]
    for c in team:
        c.current_hp = min(c.start_hp, int(hp.get(c.uuid, c.start_hp)))
    if not any(c.current_hp > 0 for c in team):
        raise GameError("Your whole team is down. The run is over.")
    return team


def enemies(index: int) -> list:
    """The story boss's crew at the run's strength for this index (not the story's own numbers)."""
    lvl, awaken, quality, items, mult = RUSH_CURVE[index]
    team = []
    for cid in story.STAGES[BOSSES[index]]["enemies"]:
        c = character_from_dict({"id": cid, "xp": lvl * 100, "awaken": awaken, "types": ["BALANCE"],
                                 "qualities": [quality], "items": [{"id": 1}] * items})
        for stat in ("hp", "damage"):
            value = int(getattr(c, f"start_{stat}") * mult)
            setattr(c, f"start_{stat}", value)
            setattr(c, f"current_{stat}", value)
        team.append(c)
    return team


def _score(bosses_beaten: int, rounds: int) -> int:
    return bosses_beaten * 1000 - rounds


def finish_fight(user, fight, redis, name: str) -> dict:
    """Settle one rush fight: carry health, pay first-time-this-week boss rewards, end the run on a loss."""
    s = state(user)
    run = s.get("run")
    rewards = {"won": fight.winner == 0, "fragments": 0, "xp": 0, "stand_xp": 0, "item": None}
    if not run:
        return rewards
    run["rounds"] += fight.round
    index = run["index"]
    if fight.winner == 0:
        for c in fight.sides[0].chars:
            healed = max(0, c.current_hp) + (c.start_hp * PATCH_UP if c.current_hp > 0 else 0)
            run["hp"][c.uuid] = min(c.start_hp, int(healed))
        run["index"] = index + 1
        if index not in s["claimed"]:
            reward = REWARDS[index]
            user.fragments += reward["fragments"]
            user.super_fragments += reward.get("super", 0)
            items = [item_from_dict({"id": i}) for i in reward["items"]]
            user.items.extend(items)
            s["claimed"].append(index)
            names = [i.name for i in items] + ([f"{reward['super']} Arrowhead"] if reward.get("super") else [])
            if index >= CHIP_FROM:  # the later bosses also drop a stand chip, the last boss an epic
                from app.game import chips
                chip = chips.grant(user, prefer=fight.sides[0].chars,
                                   tier="epic" if index == len(BOSSES) - 1 else None)
                if chip:
                    names.append(f"a {chips.view(chip)['label']} chip")
            rewards.update(fragments=reward["fragments"], item=", ".join(names) or None)
    beaten = run["index"]
    if fight.winner != 0 or beaten >= len(BOSSES):
        s["run"] = None
    best = s["best"]
    if beaten > best["bosses"] or (beaten == best["bosses"] and beaten and run["rounds"] < best["rounds"]):
        s["best"] = {"bosses": beaten, "rounds": run["rounds"]}
        if beaten:
            redis.zadd(f"web:rush:{s['week']}", {str(user.id): _score(beaten, run["rounds"])})
            redis.hset(f"web:rush:names:{s['week']}", str(user.id), name)
            redis.expire(f"web:rush:{s['week']}", 60 * 60 * 24 * 21)
            redis.expire(f"web:rush:names:{s['week']}", 60 * 60 * 24 * 21)
    rewards["rush"] = {"beaten": beaten, "over": s["run"] is None}
    return rewards


def leaderboard(redis, limit: int = 10) -> list:
    week = week_key()
    rows = redis.zrevrange(f"web:rush:{week}", 0, limit - 1, withscores=True)
    out = []
    for uid, score in rows:
        uid = uid.decode() if isinstance(uid, bytes) else uid
        name = redis.hget(f"web:rush:names:{week}", uid)
        score = int(score)
        bosses_beaten = (score + 999) // 1000
        out.append({"uid": uid, "name": name.decode() if isinstance(name, bytes) else (name or "?"),
                    "bosses": bosses_beaten, "rounds": bosses_beaten * 1000 - score})
    return out


def ends_in(when=None):
    return week_ends(when) - (when or now())
