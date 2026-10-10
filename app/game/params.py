"""Stand parameters: the anime's hexagon chart, graded A (best) to E, from a stand's base stats.

Continuous stats (damage, speed, health) are graded by where the stand sits among every playable stand: the top
fifth is A, the bottom fifth E (ties share a grade). Discrete ones have fixed bands: special charge time in turns,
the number of synergy groups the stand belongs to, and rarity. Levels, items and awakenings don't move a grade:
it describes the stand, not one copy of it.
"""
import math
from bisect import bisect_left, bisect_right
from functools import lru_cache

from app.game.character import CHARACTER_FILE

LETTERS = "EDCBA"  # grade 1..5 -> letter
AXES = (  # key, Japanese label (the anime's), English label
    ("power", "破壊力", "Power"),
    ("speed", "スピード", "Speed"),
    ("durability", "持続力", "Durability"),
    ("special", "必殺", "Special"),
    ("synergy", "連携", "Synergy"),
    ("potential", "成長性", "Potential"),
)
POTENTIAL = {"R": 1, "SR": 2, "SSR": 3, "UR": 4, "LR": 5}


def _playable():
    return [c for c in CHARACTER_FILE if c["universe"] != "Dummy"]


def _groups(stand_id: int) -> int:
    from app.game.characterabilities import SYNERGIES
    return sum(stand_id in members for members in SYNERGIES.values())


@lru_cache(maxsize=1)
def _sorted_stats():
    pool = _playable()
    return {k: sorted(c[f] for c in pool) for k, f in (("power", "base_damage"), ("speed", "base_speed"),
                                                        ("durability", "base_hp"))}


def _percentile_grade(values, v) -> int:
    """1..5 from the stand's mid-rank among all stands (ties count half below, half above)."""
    below, upto = bisect_left(values, v), bisect_right(values, v)
    share = (below + (upto - below) / 2) / len(values)
    return min(5, 1 + int(share * 5))


def _special_grade(turns: int) -> int:
    return 5 if turns <= 1 else max(1, 6 - turns)  # 1 turn A, 2 B, 3 C, 4 D, 5+ E


def _synergy_grade(groups: int) -> int:
    return max(1, min(5, groups))  # 5+ groups A ... 1 group E


@lru_cache(maxsize=None)
def grades(stand_id: int) -> tuple:
    """((key, jp, en, grade 1-5, letter, what it's based on), ...) in AXES order. Empty for unknown stands."""
    if not 1 <= stand_id <= len(CHARACTER_FILE):
        return ()
    c = CHARACTER_FILE[stand_id - 1]
    stats = _sorted_stats()
    groups = _groups(stand_id)
    turns = int(c["turn_for_ability"])
    values = {
        "power": (_percentile_grade(stats["power"], c["base_damage"]), f"{c['base_damage']} damage"),
        "speed": (_percentile_grade(stats["speed"], c["base_speed"]), f"{c['base_speed']:g} speed"),
        "durability": (_percentile_grade(stats["durability"], c["base_hp"]), f"{c['base_hp']} health"),
        "special": (_special_grade(turns), "charges every turn" if turns <= 1 else f"charges in {turns} turns"),
        "synergy": (_synergy_grade(groups), f"{groups} synergy group{'s' if groups != 1 else ''}"),
        "potential": (POTENTIAL.get(c["rarity"], 1), c["rarity"]),
    }
    return tuple((k, jp, en, values[k][0], LETTERS[values[k][0] - 1], values[k][1]) for k, jp, en in AXES)


@lru_cache(maxsize=None)
def chart(stand_id: int) -> dict:
    """Everything the SVG hexagon needs, in a 300x300 viewBox: rings, axes, the stand's shape and label spots."""
    rows = grades(stand_id)
    if not rows:
        return {}
    c, r = 150, 88

    def pt(i, radius):
        a = -math.pi / 2 + i * math.pi / 3
        return round(c + radius * math.cos(a), 1), round(c + radius * math.sin(a), 1)

    def poly(radius_of):
        return " ".join(f"{x},{y}" for x, y in (pt(i, radius_of(i)) for i in range(6)))

    axes = []
    for i, (key, jp, en, grade, letter, basis) in enumerate(rows):
        lx, ly = pt(i, r + 34)
        anchor = "middle" if abs(lx - c) < 5 else ("start" if lx > c else "end")
        nudge = {"start": -10, "end": 10, "middle": 0}[anchor]
        gx, gy = pt(i, r + 13)
        axes.append({"key": key, "jp": jp, "en": en, "grade": grade, "letter": letter, "basis": basis,
                     "x2": pt(i, r)[0], "y2": pt(i, r)[1], "lx": lx + nudge, "ly": ly, "anchor": anchor, "gx": gx, "gy": gy,
                     "dot": pt(i, r * grade / 5)})
    return {"rings": [poly(lambda i, g=g: r * g / 5) for g in range(1, 6)],
            "ring_labels": [(pt(0, r * g / 5), LETTERS[g - 1]) for g in range(1, 6)],
            "shape": poly(lambda i: r * rows[i][3] / 5), "axes": axes, "center": c}
