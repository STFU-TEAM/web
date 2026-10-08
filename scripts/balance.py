"""Balance reports from thousands of simulated fights through the real engine.

    python scripts/balance.py               # all reports
    python scripts/balance.py length        # fight length, overheals, timeouts, rarity gaps
    python scripts/balance.py stands        # win rate of every stand among its own rarity
    python scripts/balance.py story         # win rate of 5 team archetypes against each story stage
    python scripts/balance.py story --seed 3 --fights 100

Rerun after changing stats, specials, terrains or the story curve. Targets used so far:
PvE fights about a minute; duels (ranked, friendly) 1-2 minutes on average and never over 5 (fight.PVP_*,
with a 5-minute wall clock on top), stands within ~35-65% of their rarity,
each rarity beating the one below ~75-80% of the time.
"""
import argparse
import collections
import random
import statistics as st
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.game import story  # noqa: E402
from app.game.character import CHARACTER_FILE, Character  # noqa: E402
from app.game.fight import Fight, Side, ai_choice  # noqa: E402

# Estimated wall time: a click is one human target pick; the replay animates the events it produced.
CLICK_S = 3.0
STEP_S = {"hit": .7, "crit": .95, "dodge": .7, "special": 1.9, "item": 1.0, "info": .6, "stun": .7,
          "terrain": 1.3, "sudden": .9}
REPLAY_CAP_S = 8
POOL = [c for c in CHARACTER_FILE if c["universe"] != "Dummy" and c["id"] != 110]
RARITIES = ("R", "SR", "SSR", "UR", "LR")
TYPES = ["ATTACK", "DEFENSE", "SPEED", "LUCK", "BALANCE"]
QUALITIES, QUALITY_WEIGHTS = ["UNIVERSAL", "SUPREME", "GREAT", "GOOD", "SUB_PAR", "BAD"], [2, 5, 13, 40, 20, 20]


def make(cid, level, awaken, quality=None):
    n = random.choice([1, 1, 2])
    quals = [quality] * n if quality else random.choices(QUALITIES, QUALITY_WEIGHTS, k=n)
    return Character({"id": cid, "xp": level * 100, "awaken": awaken, "items": [],
                      "types": random.sample(TYPES, n), "qualities": quals})


def team(rarities, level, awaken, quality=None):
    pool = [c for c in POOL if c["rarity"] in rarities]
    return [make(c["id"], level, awaken, quality) for c in random.sample(pool, 3)]


def run(team_a, team_b, ai_b="smart", duel=False):
    """Side 0 plays the human (picked by the smart AI); a duel has a human on both sides. Stats for one fight."""
    foes = Side("B", team_b, duel)
    foes.ai = ai_b
    f = Fight(Side("A", team_a, True), foes, kind="friend" if duel else "wormhole",
              meta={"players": ["a", "b"]} if duel else None)
    clicks, secs = 0, 0.0
    while not f.finished and clicks < 2000:
        n = len(f.log)
        pick = ai_choice(f.sides[1 - f.acting_side].chars, f.acting_char) if f.awaiting_input else None
        f.advance(pick)
        clicks += 1
        secs += CLICK_S + min(REPLAY_CAP_S, sum(STEP_S.get(e["kind"], .6) for e in f.log[n:]))
    overheal = any(hp > c.start_hp for e in f.log for s, side in enumerate(f.sides)
                   for c, hp in zip(side.chars, e["hp"][s]))
    return {"winner": f.winner, "rounds": f.round, "secs": secs, "overheal": overheal,
            "a": [c.id for c in team_a], "b": [c.id for c in team_b]}


def pct(xs, p):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(len(xs) * p))]


def report_length(fights):
    print("Fight length (random 3v3, same level both sides)")
    for level, awaken in ((0, 0), (30, 0), (100, 0), (100, 3)):
        res = [run(team(RARITIES, level, awaken), team(RARITIES, level, awaken)) for _ in range(fights)]
        secs, rounds = [r["secs"] for r in res], [r["rounds"] for r in res]
        print(f"  Lv{level:<3} A{awaken}  rounds med {st.median(rounds):4.1f} max {max(rounds):3d} | "
              f"time avg {st.mean(secs) / 60:.1f}m p90 {pct(secs, .9) / 60:.1f}m p99 {pct(secs, .99) / 60:.1f}m | "
              f"overheal {sum(r['overheal'] for r in res)}  draws {sum(r['winner'] is None for r in res)}")
    print("Duel length (ranked / friendly pace, a human picking on both sides)")
    for level, awaken in ((30, 0), (100, 0), (100, 3)):
        res = [run(team(RARITIES, level, awaken), team(RARITIES, level, awaken), duel=True) for _ in range(fights)]
        secs, rounds = [r["secs"] for r in res], [r["rounds"] for r in res]
        print(f"  Lv{level:<3} A{awaken}  rounds med {st.median(rounds):4.1f} max {max(rounds):3d} | "
              f"time avg {st.mean(secs) / 60:.1f}m p90 {pct(secs, .9) / 60:.1f}m p99 {pct(secs, .99) / 60:.1f}m | "
              f"draws {sum(r['winner'] is None for r in res)}")
    print("Rarity gaps at level 50 (row beats the rarity below)")
    for low, high in zip(RARITIES, RARITIES[1:]):
        wins = sum(run(team((high,), 50, 0), team((low,), 50, 0))["winner"] == 0 for _ in range(fights))
        print(f"  {high:>3} vs {low:<3} {wins / fights:.0%}")


def report_stands(fights):
    print("Win rate of each stand among its own rarity (outside 38-62% listed)")
    wins, seen = collections.Counter(), collections.Counter()
    for rarity in ("R", "SR", "SSR", "UR", "LR"):
        if len([c for c in POOL if c["rarity"] == rarity]) < 6:
            continue
        for _ in range(fights * 3):
            r = run(team((rarity,), 50, 0), team((rarity,), 50, 0))
            for side, ids in ((0, r["a"]), (1, r["b"])):
                for cid in ids:
                    seen[cid] += 1
                    wins[cid] += r["winner"] == side
    name = {c["id"]: f'{c["name"]} ({c["rarity"]})' for c in CHARACTER_FILE}
    rows = sorted(((wins[c] / seen[c], c) for c in seen))
    out = [(w, c) for w, c in rows if not .38 <= w <= .62]
    for w, c in out:
        print(f"  {name[c]:<42} {w:.0%}  (n={seen[c]})")
    print(f"  {len(out)}/{len(rows)} outside 38-62%, range {rows[0][0]:.0%}-{rows[-1][0]:.0%}")


ARCHETYPES = [("starter", ("R", "SR"), 5, 0, "GOOD"), ("early", ("SR", "SSR"), 30, 0, "GOOD"),
              ("mid", ("SSR",), 60, 1, "GREAT"), ("late", ("UR",), 100, 2, "GREAT"),
              ("max", ("UR", "LR"), 100, 3, "UNIVERSAL")]


def story_curve(fights):
    """{stage index: [win rate per archetype]}"""
    return {k: [sum(run(team(r, lvl, aw, q), story.enemy_team(k), story.ai_level(k))["winner"] == 0
                    for _ in range(fights)) / fights for _, r, lvl, aw, q in ARCHETYPES]
            for k in range(story.TOTAL)}


def report_story(fights):
    print("Story: win rate per team archetype")
    print("  " + " " * 34 + "lvl aw " + "".join(f"{a[0]:>8}" for a in ARCHETYPES))
    for k, rates in story_curve(fights).items():
        s = story.STAGES[k]
        print(f"  {k + 1:>2} {s['title'][:30]:<31} {story.level_for(k):>3} {story.awaken_for(k):>2} "
              + "".join(f"{r:>8.0%}" for r in rates))


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("report", nargs="?", choices=("length", "stands", "story"))
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--fights", type=int, default=300, help="fights per sample (story uses a fifth)")
    args = parser.parse_args()
    random.seed(args.seed)
    if args.report in (None, "length"):
        report_length(args.fights)
    if args.report in (None, "stands"):
        report_stands(args.fights)
    if args.report in (None, "story"):
        report_story(max(20, args.fights // 5))


if __name__ == "__main__":
    main()
