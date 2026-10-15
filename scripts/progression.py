"""How long a new free player takes to reach the endgame: a day-by-day Monte Carlo of pulls, copies, Requiem Arrows,
stars, gear and the content they open, read from the game's own tables (banner odds, pity, sparks, star costs).

    python scripts/progression.py [players per profile]

A model, not a measurement. Each simulated player pulls every Arrowhead and Devil's Palm on one banner, and fields
the best three stands of a rarity they hold the most copies of (an SSR team, or a UR/LR team). A milestone opens
on the first day all of these hold:
  - the team has the stars it needs (STAR_GATES: measured with the team simulator, see the notes there);
  - the player level the content asks for (scripts/economy.py's XP model);
  - the previous milestone is done and its stages are played at the profile's pace;
  - from Over Heaven on, the team's 9 items are refined to +5 (paid from the profile's Meteor Dust).
The milestone's one-time rewards (Arrowheads, Requiem Arrows, Palms) are paid then.
"""
import json
import random
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from app.game import altverse, carryme, dungeon, gear, heaven, logic, onboarding, overheaven, requiem, story, tower, weekly  # noqa: E402
from app.game.character import CHARACTER_FILE  # noqa: E402
import economy as econ  # noqa: E402  (scripts/economy.py: the income side)

DAYS = 365
ORDER = ["R", "SR", "SSR", "UR", "LR"]
GEAR_COST = 9 * sum(gear.REFINE_COST)  # a team's 9 items, 0 to +5

# Stars a team needs before a milestone is ~70%+ to win (team simulator at Lv 100, Great quality, +3 items; the UR/LR
# column is requiem.BENCH: Wonder of U, Soft & Wet, Paisley Park). From Over Heaven on, ★5 alone wins ~0%: those
# fights also take +5 items (gear=True) and good qualities, so ★5 is where those rows start, not where they end.
# (milestone, SSR team stars, UR/LR team stars, player level, stages, gear, one-time Arrowheads, Arrows, Palms)
# The story's Requiem Arrows (ARROW_PARTS) and the Alternate Universe's are paid with the milestone that clears them.
_AU_ARROWS = sum(altverse.reward_for(c["key"], j)["items"].count(3) for c in altverse.CHAPTERS for j in range(len(c["stages"])))
STAR_GATES = [
    ("Story Part 6 (Made in Heaven)", 1, 1, 20, 21, False, 1, 6 in story.ARROW_PARTS, 0),
    ("Story Part 7 (Love Train)", 3, 2, 26, 5, False, 1, 7 in story.ARROW_PARTS, 0),
    ("Story finished (Wonder of U)", 3, 3, 32, 5, False, 1, 8 in story.ARROW_PARTS, 0),  # eased finale: ★3 ~50%
    ("Alternate Universe + Carry Me", 5, 4, 58, altverse.TOTAL + carryme.TOTAL, False, 18, 2 + _AU_ARROWS, 5),
    ("Over Heaven trials", 5, 5, 58, sum(len(t["fights"]) for t in overheaven.TRACKS), True, 35, 6, 0),
    ("Requiem tracks", 5, 5, 58, requiem.TOTAL, True, 27, 8, 0),
    ("Heaven's Gate cleared", 5, 5, 58, len(heaven.FIGHTS) + len(overheaven.REQUIEM_TRACK["fights"]), True, 12, 4, 0),
]
# name: (shop summons a week, buys the weekly Requiem Arrow, Mirror wins a day, dungeon runs a day, first clears a day,
#        Meteor Dust a day, player XP a day): Dust and XP from scripts/economy.py's casual and dedicated rows
PROFILES = {
    "Casual (30 min a day)": (0, False, 10, 0.5, 3, 12_700, 10_600),
    "Dedicated (1-2 h a day)": (2, True, 25, 1, 8, 29_800, 12_600),
}
BANNER = "Evolution"
DISCS = ROAD = True  # model Stand Discs and the Weekly Road (python scripts/progression.py 200 old: without them)


def road_week(wins):
    """The Weekly Road's tiers a profile reaches: points from its wins, dungeon runs and the daily reward."""
    return [r for p, r in weekly.TIERS if p <= 7 * (wins + 5 + 4)]


def pool_of(name):
    data = json.load(open(ROOT / "app/game/data/banners_data.json", encoding="utf-8"))
    banner = next(b for b in data["banners"] if b.get("name") == name)
    by = {r: [c for c in banner["cards"] if CHARACTER_FILE[c - 1]["rarity"] == r] for r in ORDER}
    return {r: v for r, v in by.items() if v}


class Player:
    def __init__(self, pool, rng):
        self.pool, self.rng = pool, rng
        self.copies = {}   # stand id -> copies owned (the kept one included)
        self.pity = self.sparks = self.pulls = 0
        self.arrows = 0.0
        self.discs = 0.0  # Stand Discs: every R and SR pulled is released (the model keeps SSR and up)

    def card(self, odds):
        if self.pity >= logic.PITY_LIMIT - 1:
            rarity = self.rng.choices(list(logic.PITY_ODDS), weights=list(logic.PITY_ODDS.values()))[0]
        else:
            rarity = self.rng.choices(list(odds), weights=list(odds.values()))[0]
        while rarity not in self.pool:  # the banner has none: the nearest below (as logic._template_of)
            rarity = ORDER[ORDER.index(rarity) - 1]
        cid = self.rng.choice(self.pool[rarity])
        self.pity = 0 if rarity in logic.PITY_RESETS else self.pity + 1
        if rarity in ("R", "SR") and DISCS:
            self.discs += logic.DISC_VALUE[rarity]
            return
        self.copies[cid] = self.copies.get(cid, 0) + 1

    def spend_discs(self, rarities):
        """Discs buy copies for the team stand (of those rarities) furthest behind."""
        while True:
            owned = sorted((c for r in rarities for c in self.pool.get(r, []) if self.copies.get(c)),
                           key=lambda c: -self.copies[c])[:3]
            if len(owned) < 3:
                return
            low = min(owned, key=lambda c: self.copies[c])
            if self.copies[low] >= 1 + sum(logic.STAR_COPIES.values()):
                return
            price = logic.DISC_PRICE[CHARACTER_FILE[low - 1]["rarity"]]
            if self.discs < price:
                return
            self.discs -= price
            self.copies[low] += 1

    def ten_pull(self, first=False):
        for i in range(10):
            if first and i == 9:  # a new player's first pull holds an SSR or better
                self.card({r: o for r, o in logic.BANNER_ODDS.items() if r in ("SSR", "UR", "LR")})
            else:
                self.card(logic.BANNER_ODDS)
        self.pulls += 1
        self.sparks += 1
        if self.sparks >= logic.SPARK_COST:  # sparks buy the SSR you already have most of
            self.sparks -= logic.SPARK_COST
            best = max(self.pool["SSR"], key=lambda c: self.copies.get(c, 0))
            self.copies[best] = self.copies.get(best, 0) + 1

    def palm(self):
        for _ in range(5):
            self.card(logic.ARROW_ODDS)

    def team_stars(self, rarities):
        """Stars of the weakest of the best three stands of those rarities, Arrows going to the weakest first."""
        owned = sorted((self.copies[c] for r in rarities for c in self.pool.get(r, []) if self.copies.get(c)), reverse=True)[:3]
        if len(owned) < 3:
            return -1
        spares, stars, arrows = [n - 1 for n in owned], [0, 0, 0], int(self.arrows)
        while True:
            i = min(range(3), key=lambda j: stars[j])
            s = stars[i] + 1
            if s > logic.MAX_AWAKEN:
                break
            need = logic.STAR_COPIES[s]
            if spares[i] >= need:
                spares[i] -= need
            elif arrows and spares[i] >= need - 1:
                spares[i] -= need - 1
                arrows -= 1
            else:
                break
            stars[i] = s
        return min(stars)


TEAMS = {"SSR team": ("SSR",), "UR/LR team": ("UR", "LR")}


def simulate(profile, seed):
    shop_heads, buys_arrow, wins, runs, pace, dust_day, xp_day = PROFILES[profile]
    rng = random.Random(seed)
    p = Player(pool_of(BANNER), rng)
    q, s = econ.quest_income(), econ.streak_income()
    heads_day = q["super_fragments"] + s["super_fragments"] + shop_heads / 7 + tower.reward_for(5)["super"] / 7
    heads = float(sum(r.get("super", 0) for r in onboarding.WELCOME[:1]))
    palms = dust = 0.0
    hit, done, ready_from = {}, 0, 0.0
    for day in range(1, DAYS + 1):
        heads += heads_day + (sum(r.get("super", 0) for r in onboarding.WELCOME[day:day + 1]))
        heads += 27 / 120 if day <= 120 else 0  # achievements, spread over the first four months
        heads += sum(x[4].get("super", 0) for x in onboarding.PATH) / 3 if day <= 3 else 0
        deep = done >= 5  # the Requiem depths (B7-B9) open with a Requiem-strength team
        palms += 1 / 7 + runs * (1.0 if done >= 4 else dungeon.BOSS_PALM)
        p.arrows += wins * logic.CHANCEITEM / 100 * logic.MIRROR_ITEM_DROPS[3] + (runs * dungeon.REQUIEM_ARROW_CHANCE if deep else 0)
        dust += dust_day
        if ROAD and day % 7 == 0:
            for r in road_week(wins):
                heads += r.get("super", 0)
                palms += r.get("items", []).count(2)
                p.discs += r.get("discs", 0) if DISCS else 0
                dust += r.get("fragments", 0)
        if buys_arrow and day % 7 == 0 and dust >= 40_000:
            p.arrows += 1
            dust -= 40_000
        while heads >= 1:
            heads -= 1
            p.ten_pull(first=p.pulls == 0)
        while palms >= 1:
            palms -= 1
            p.palm()
        if DISCS:  # the SSR team first; once it's ★5, the UR/LR team
            p.spend_discs(("SSR",) if p.team_stars(("SSR",)) < 5 else ("UR", "LR"))
        stars = {name: p.team_stars(rs) for name, rs in TEAMS.items()}
        for name, st in stars.items():
            for n in range(1, 6):
                if st >= n:
                    hit.setdefault((name, f"★{n}"), day)
        while done < len(STAR_GATES):
            name, ssr, ur, level, stages, needs_gear, h, a, pm = STAR_GATES[done]
            ok = stars["SSR team"] >= ssr or stars["UR/LR team"] >= ur
            ok = ok and day * xp_day >= econ.xp_for_level(level) and day >= ready_from
            if needs_gear and "gear" not in hit:
                ok = ok and dust >= GEAR_COST
            if not ok:
                break
            if needs_gear and "gear" not in hit:
                dust -= GEAR_COST
                hit["gear"] = day
            hit[name] = day
            heads, p.arrows, palms = heads + h, p.arrows + a, palms + pm
            done += 1
            nxt = STAR_GATES[done][4] if done < len(STAR_GATES) else 0
            ready_from = day + nxt / pace
    return hit, p


def cell(days, runs):
    got = [d for d in days if d]
    return f"day {statistics.median(got):>4.0f} ({100 * len(got) // runs:>3}%)" if got else f"{'never':>15}"


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    global DISCS, ROAD
    runs = int(sys.argv[1]) if len(sys.argv) > 1 else 200
    if "old" in sys.argv[2:]:
        DISCS = ROAD = False
    print(f"Banner {BANNER} {({r: len(v) for r, v in pool_of(BANNER).items()})} · {runs} players a profile · median day"
          f" (share of players who get there within {DAYS} days)\n")
    for profile in PROFILES:
        results = [simulate(profile, seed) for seed in range(runs)]
        print(profile)
        print(f"  {'Team stars':34}" + "".join(f"{t:>18}" for t in TEAMS))
        for n in range(1, 6):
            print(f"  {f'★{n} (all three stands)':34}" + "".join(f"{cell([r.get((t, f'★{n}')) for r, _ in results], runs):>18}" for t in TEAMS))
        print(f"  {'Milestones (best team)':34}")
        for g in STAR_GATES:
            print(f"  {g[0]:34}{cell([r.get(g[0]) for r, _ in results], runs):>18}")
        print(f"  {'Team gear refined to +5':34}{cell([r.get('gear') for r, _ in results], runs):>18}")
        print(f"  10-pulls in a year: {statistics.mean(p.pulls for _, p in results):.0f}"
              f" · Requiem Arrows earned: {statistics.mean(p.arrows for _, p in results):.0f}\n")


if __name__ == "__main__":
    main()
