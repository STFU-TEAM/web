"""Weekly boss rush: the six story bosses back to back.

Your team's health carries over from fight to fight (a 20% patch-up between them),
so a run is a test of the whole team, not of one lucky fight. One run per day; each
boss reached pays a reward the first time each week; the weekly leaderboard ranks
runs by bosses beaten, then by fewest rounds.

Save: data["web_rush"] = {"week", "day", "best": {"bosses", "rounds"}, "claimed": [i...],
                          "run": {"index", "hp": {uuid: hp}, "rounds"} or None}
Redis: ZSET web:rush:<week> uid -> score (bosses * 1000 - rounds)
"""
from typing import Optional

from app.game import story
from app.game.gangs import week_ends, week_key
from app.game.items import item_file, item_from_dict
from app.game.logic import GameError, now

BOSS_STAGES = [k for k, st in enumerate(story.STAGES) if st.get("boss")]
PATCH_UP = 0.20
REWARDS = [
    {"fragments": 500, "items": []},
    {"fragments": 1000, "items": [40]},
    {"fragments": 2000, "items": [38]},
    {"fragments": 3000, "items": [39, 40]},
    {"fragments": 4000, "super": 1, "items": [38, 38]},
    {"fragments": 6000, "super": 2, "items": [34]},
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
    parts = [f"{r['fragments']:,} fragments"]
    if r.get("super"):
        parts.append(f"{r['super']} super fragment{'s' if r['super'] > 1 else ''}")
    parts += [item_file[x - 1]["name"] for x in r["items"]]
    return ", ".join(parts)


def bosses() -> list:
    return [{"index": i, "stage": k, "title": story.STAGES[k]["title"], "part": story.STAGES[k]["part_title"],
             "level": story.level_for(k), "awaken": story.awaken_for(k), "lead": story.STAGES[k]["enemies"][0],
             "reward": reward_text(i)} for i, k in enumerate(BOSS_STAGES)]


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
    return story.enemy_team(BOSS_STAGES[index])


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
            user.super_fragements += reward.get("super", 0)
            items = [item_from_dict({"id": i}) for i in reward["items"]]
            user.items.extend(items)
            s["claimed"].append(index)
            rewards.update(fragments=reward["fragments"],
                           item=", ".join([i.name for i in items] + ([f"{reward['super']} super fragment"] if reward.get("super") else [])) or None)
    beaten = run["index"]
    if fight.winner != 0 or beaten >= len(BOSS_STAGES):
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
