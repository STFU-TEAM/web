"""How fast players earn and progress: Meteor Dust, Arrowheads and XP per day for typical players, read from the
game's own reward tables, against what there is to spend it on.

    python scripts/economy.py

A model, not a measurement: it assumes the player wins what they play. Re-run it after changing a reward table.
"""
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.game import dungeon, gear, logic, onboarding, puzzle, quests, requiem, rush, story, tower, whos  # noqa: E402
from app.game import overheaven, altverse, carryme  # noqa: E402

# who we model: (name, Mirror World wins a day, team level, player level, tower floor reached, Requiem Tower floor,
#                deepest dungeon floor cleared, plays the daily puzzle and Who's that Stand?, boss rush stage reached)
PROFILES = [
    ("New player (week 1)", 12, 20, 12, 8, 0, 3, True, 1),
    ("Casual (30 min a day)", 10, 60, 30, 20, 0, 3, True, 2),
    ("Dedicated (mid-game)", 30, 80, 40, 35, 0, 3, True, 4),
    ("Endgame (maxed team)", 30, 100, 60, 44, 11, 6, True, 5),
]
MIRROR_CAP = 24 * 60 // 14  # fights a day if someone played around the clock (14 min cooldown)


def mirror_multi(team_level: int) -> float:
    exp_reward = sum(w * r for _, w, _, _, r, _, _ in logic.MIRROR_DIFFICULTIES) / sum(w for _, w, *_ in logic.MIRROR_DIFFICULTIES)
    return (1 + team_level / 33) * exp_reward


def quest_income() -> dict:
    """Average daily value of the quest board: 4 dailies a day, 3-4 weeklies a week."""
    out = {}
    for cat, per_week in (("daily", 4 * 7), ("weekly", 4)):
        pool = [q for q in quests.ALL_QUESTS if q.get("category") == cat and q.get("enabled", True)]
        if not pool:
            continue
        avg = {k: statistics.mean(q["rewards"].get(k, 0) for q in pool) for k in ("fragments", "super_fragments", "xp")}
        for k, v in avg.items():
            out[k] = out.get(k, 0) + v * per_week / 7
    return out


def streak_income() -> dict:
    """The daily reward ladder, averaged over a week (week 2+ Dust multiplier included at +20%)."""
    d = sum(r.get("fragments", 0) for r in logic.STREAK_REWARDS) * 1.2 / 7
    h = sum(r.get("super", 0) for r in logic.STREAK_REWARDS) / 7
    return {"fragments": d, "super_fragments": h}


def dungeon_bag(power: int, deepest: int) -> int:
    """Dust in the bag for a run cleared to `deepest` (every fight, elite and boss won, every chest opened)."""
    total = 0
    for depth in range(1, deepest + 1):
        run = {"power": power, "depth": depth}
        mult = dungeon.LOOT_MULT[depth - 1]
        fights = sum(c for k, c in dungeon.EVENTS if k == "fight")
        total += fights * dungeon.dust_for(dungeon.enemy_floor(run, "fight")) * mult
        total += 2 * dungeon.dust_for(dungeon.enemy_floor(run, "elite")) * mult
        chests = sum(c for k, c in dungeon.EVENTS if k == "chest")
        total += chests * dungeon.dust_for(power + 2 * min(depth, 3)) // 2 * mult
        if depth in dungeon.BOSS_DEPTHS:
            total += 3 * dungeon.dust_for(dungeon.enemy_floor(run, "boss")) * mult
    return int(total)


def dungeon_xp(deepest: int) -> int:
    fights = sum(c for k, c in dungeon.EVENTS if k == "fight")
    return sum(dungeon.xp_for(d)[1] * fights + dungeon.xp_for(d, "elite")[1] + (dungeon.xp_for(d, "boss")[1] if d in dungeon.BOSS_DEPTHS else 0)
               for d in range(1, deepest + 1))


def tower_week(floor: int, rq_floor: int) -> dict:
    out = {"fragments": 0, "super_fragments": 0, "requiem_arrows": 0}
    for f in range(1, floor + 1):
        r = tower.reward_for(f)
        out["fragments"] += r["fragments"]
        out["super_fragments"] += r["super"]
    for f in range(1, rq_floor + 1):
        r = tower.reward_for(f, tower.RQ)
        out["fragments"] += r["fragments"]
        out["super_fragments"] += r["super"]
        out["requiem_arrows"] += r["items"].count(3)
    out["fragments"] -= tower.CLIMB_COST + (tower.RQ_COST if rq_floor else 0)
    return out


def rush_week(stage: int) -> int:
    return sum(r["fragments"] for r in rush.REWARDS[:stage])


def one_time() -> dict:
    """Everything the PvE content pays once: story, Alternate Universe, Carry Me, Over Heaven, Requiem."""
    from app.game.economy import dust
    out = {"fragments": 0, "super_fragments": 0}
    oh = [overheaven.reward_of(t["key"], j) for t in overheaven.TRACKS + overheaven.EXTRA for j in range(len(t["fights"]))]
    out["fragments"] += sum(r["fragments"] for r in oh)
    out["super_fragments"] += sum(r["super"] for r in oh)
    rq = [requiem.reward_for(t["key"], i) for t in requiem.TRACKS for i in range(len(t["stages"]))]
    out["fragments"] += sum(r.get("fragments", 0) for r in rq)
    out["super_fragments"] += sum(r.get("super", 0) for r in rq)
    return out


def level_after(xp: float) -> int:
    from app.game.user import LVLSCALING, USRXPTOLEVEL
    return min(USRXPTOLEVEL, int(LVLSCALING * xp ** 0.5))


def xp_for_level(level: int) -> int:
    from app.game.user import LVLSCALING
    return int((level / LVLSCALING) ** 2)


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # the Windows console
    except Exception:
        pass
    q, s = quest_income(), streak_income()
    print("Meteor Dust, Arrowheads and player XP per day, by kind of player (wins only; see the script's notes)\n")
    print(f"{'':26}{'Dust/day':>10}{'Heads/wk':>10}{'XP/day':>9}  where the Dust comes from")
    rows = []
    for name, wins, team_lvl, plvl, t_floor, rq_floor, deep, daily_games, rush_stage in PROFILES:
        mirror = wins * logic.FRAGMENTSGAIN * mirror_multi(team_lvl)
        power = dungeon.power_for([type("C", (), {"level": team_lvl})()] * 3)
        dung = dungeon_bag(power, deep)
        tw = tower_week(t_floor, rq_floor)
        games = (puzzle.REWARD["fragments"] + puzzle.PERSONAL_REWARD["fragments"] + whos.REWARD_BASE + 3 * whos.REWARD_PER_SPARE) if daily_games else 0
        rush_d = rush_week(rush_stage) / 7
        parts = {"Mirror": mirror, "dungeon": dung, "quests": q["fragments"], "daily": s["fragments"], "puzzles": games,
                 "tower": tw["fragments"] / 7, "rush": rush_d}
        dust_day = sum(parts.values())
        heads_week = 7 * (q["super_fragments"] + s["super_fragments"]) + tw["super_fragments"]
        streak_xp = statistics.mean(logic.STREAK_XP + logic.STREAK_XP_STEP * d for d in range(7)) * 1.2
        games_xp = (puzzle.REWARD["xp"] + puzzle.PERSONAL_REWARD["xp"] + whos.XP_BASE + 3 * whos.XP_PER_SPARE) if daily_games else 0
        xp_day = (wins * logic.PLAYER_XPGAINS + q["xp"] + dungeon_xp(deep) + dungeon.RUN_XP_PER_FLOOR * deep
                  + streak_xp + games_xp)
        top = ", ".join(f"{k} {v / dust_day:.0%}" for k, v in sorted(parts.items(), key=lambda kv: -kv[1])[:4])
        print(f"{name:26}{dust_day:>10,.0f}{heads_week:>10.1f}{xp_day:>9,.0f}  {top}")
        rows.append((name, dust_day, heads_week, xp_day, tw))
    print(f"\n(Mirror World caps at {MIRROR_CAP} fights a day; energy never binds before the 14-minute cooldown does.)")

    print("\nFirst week bonuses for a new save:")
    ww = sum(r.get("fragments", 0) for r in onboarding.WELCOME)
    wh = sum(r.get("super", 0) for r in onboarding.WELCOME)
    pd = sum(p[4].get("fragments", 0) for p in onboarding.PATH)
    ph = sum(p[4].get("super", 0) for p in onboarding.PATH) + onboarding.PATH_DONE.get("super", 0)
    print(f"  Welcome week: {ww:,} Dust, {wh} Arrowheads ({wh} extra 10-pulls) · Beginner's path: {pd:,} Dust, {ph} Arrowheads")

    print("\nWhat there is to spend it on:")
    item_full = sum(gear.REFINE_COST)
    print(f"  Refining one item 0 → +{gear.REFINE_MAX}: {item_full:,} Dust · a whole team's 9 items: {9 * item_full:,}")
    for name, dust_day, *_ in rows:
        print(f"    {name:26} one item maxed every {item_full / dust_day:5.1f} days · the whole team in {9 * item_full / dust_day:5.0f} days")
    print(f"  ★4 and ★5 for a team of three: 6 Requiem Arrows and 6 spare copies; the tower climb {tower.CLIMB_COST} a week,"
          f" the Requiem Tower {tower.RQ_COST}")
    ot = one_time()
    print(f"  One-time PvE first clears (Over Heaven + Requiem): {ot['fragments']:,} Dust, {ot['super_fragments']} Arrowheads")

    print("\nPlayer level (the gates: story parts at 8-32, the Alternate Universe 18-44, Carry Me 36-58):")
    for name, _, _, xp_day, _ in rows:
        marks = []
        for lvl in (10, 20, 32, 44, 58):
            marks.append(f"Lv{lvl} day {xp_for_level(lvl) / xp_day:4.0f}")
        print(f"  {name:26} " + " · ".join(marks))
    _, _, _, _, tw = rows[-1]
    print(f"\nRequiem Arrows a week at the endgame: {tw['requiem_arrows']} from the Requiem Tower, plus a 35% chance a day"
          f" from the B9 dungeon boss (~{0.35 * 7:.1f} a week if cleared daily).")


if __name__ == "__main__":
    main()
