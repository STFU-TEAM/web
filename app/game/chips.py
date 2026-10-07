"""Stand chips (web only): small random stat boosts socketed into a stand.

Every chip belongs to one synergy group (characterabilities.SYNERGIES, crews and parts alike), and only a
member of that group can socket it, so there are as many kinds of chip as there are synergies. A stand has
one slot, plus one per awakening up to SLOT_MAX at ★3. A chip rolls 1-3 random stat lines by tier; its first
line always comes from its synergy's own bonus. Chips work everywhere except ranked duels.

Save: data["web_chips"] = [chip, ...]           the spare chips (at most BAG_MAX)
      stand data["chips"] = [chip, ...]         the socketed ones (Character applies them)
chip = {"id": hex, "syn": synergy key, "tier": "common"|"rare"|"epic"|"legendary", "stats": [[stat, value], ...]}
"""
import copy
import random
import uuid
from typing import List, Optional

from app.game.character import character_from_dict
from app.game.logic import GameError, locate

SLOT_BASE, SLOT_MAX = 1, 4
BAG_MAX = 60
# tier: (drop weight, stat lines, value multiplier, scrap dust, reroll dust)
TIERS = {
    "common": (60, 1, 1.0, 40, 150),
    "rare": (28, 2, 1.25, 120, 400),
    "epic": (10, 3, 1.5, 350, 900),
    "legendary": (2, 3, 1.85, 900, 2000),
}
TIER_ICON = {"common": "◇", "rare": "◆", "epic": "✦", "legendary": "✸"}
# stat: (low, high) for one common line; percentages are shares of the stat, the rest flat points
STATS = {
    "damage_pct": (0.02, 0.04),
    "hp_pct": (0.02, 0.04),
    "armor_pct": (0.03, 0.05),
    "speed_flat": (1, 3),
    "crit_flat": (2, 4),
}
STAT_LABEL = {"damage_pct": "damage", "hp_pct": "health", "armor_pct": "armor", "speed_flat": "speed",
              "crit_flat": "critical"}
SYNERGY_STAT = {"speed_pct": "speed_flat"}  # the synergy tables boost speed by a share; chips add points


def slots(char) -> int:
    return min(SLOT_MAX, SLOT_BASE + max(0, min(char.awaken, SLOT_MAX - SLOT_BASE)))


def fits(chip: dict, char) -> bool:
    from app.game.characterabilities import SYNERGIES
    return char.id in SYNERGIES.get(chip["syn"], ())


def groups_of(stand_id: int) -> List[str]:
    from app.game.characterabilities import SYNERGIES
    return [name for name, ids in SYNERGIES.items() if stand_id in ids]


def roll(syn: str, tier: Optional[str] = None, rng=random) -> dict:
    from app.game.characterabilities import SYNERGY_BONUS
    tier = tier or rng.choices(list(TIERS), weights=[t[0] for t in TIERS.values()], k=1)[0]
    _, lines, mult, _, _ = TIERS[tier]
    own = [SYNERGY_STAT.get(s, s) for s, _ in SYNERGY_BONUS.get(syn, [])]
    first = rng.choice([s for s in own if s in STATS] or list(STATS))
    picked = [first] + rng.sample([s for s in STATS if s != first], lines - 1)
    stats = []
    for stat in picked:
        low, high = STATS[stat]
        value = rng.uniform(low, high) * mult
        stats.append([stat, round(value, 3) if stat.endswith("_pct") else max(1, round(value))])
    return {"id": uuid.uuid4().hex[:10], "syn": syn, "tier": tier, "stats": stats}


def strip(team: list) -> list:
    """Fighting copies with no chips (ranked duels)."""
    out = []
    for c in team:
        data = copy.deepcopy(c.to_dict())
        data.pop("chips", None)
        out.append(character_from_dict(data))
    return out


# ── Views ────────────────────────────────────────────────────────────────

def stat_text(stat: str, value) -> str:
    return f"+{value * 100:.1f}% {STAT_LABEL[stat]}" if stat.endswith("_pct") else f"+{value} {STAT_LABEL[stat]}"


def view(chip: dict) -> dict:
    from app.game.characterabilities import SYNERGY_INFO
    label, icon = SYNERGY_INFO.get(chip["syn"], (chip["syn"], "✶"))
    return {**chip, "label": label, "icon": icon, "tier_icon": TIER_ICON[chip["tier"]],
            "lines": [stat_text(s, v) for s, v in chip["stats"]], "scrap": TIERS[chip["tier"]][3],
            "reroll": TIERS[chip["tier"]][4]}


def bag(user) -> List[dict]:
    return user.data.setdefault("web_chips", [])


def socketed(char) -> List[dict]:
    return char.data.setdefault("chips", [])


# ── Actions ──────────────────────────────────────────────────────────────

def grant(user, syn: Optional[str] = None, tier: Optional[str] = None, prefer: Optional[list] = None,
          rng=random) -> Optional[dict]:
    """Drop a chip into the bag: for syn, else most often one of `prefer`'s synergies (the stands that earned it).
    Returns the chip, or None when the bag is full."""
    from app.game.characterabilities import SYNERGIES
    if len(bag(user)) >= BAG_MAX:
        return None
    if not syn:
        mine = sorted({g for c in (prefer or []) for g in groups_of(c.id)})
        syn = rng.choice(mine) if mine and rng.random() < 0.75 else rng.choice(sorted(SYNERGIES))
    chip = roll(syn, tier, rng)
    bag(user).append(chip)
    return chip


def _take(user, chip_id: str) -> dict:
    for i, chip in enumerate(bag(user)):
        if chip["id"] == chip_id:
            return bag(user).pop(i)
    raise GameError("That chip isn't in your bag.")


def _refresh(user, char):
    from app.game.logic import _refresh as refresh
    return refresh(user, char)


def socket(user, uuid_: str, chip_id: str):
    char, _, _ = locate(user, uuid_)
    chip = next((c for c in bag(user) if c["id"] == chip_id), None)
    if chip is None:
        raise GameError("That chip isn't in your bag.")
    if not fits(chip, char):
        raise GameError(f"{char.name} isn't part of {view(chip)['label']}: that chip won't fit.")
    if len(socketed(char)) >= slots(char):
        raise GameError(f"{char.name}'s {slots(char)} chip slot{'s are' if slots(char) > 1 else ' is'} full. "
                        "Each awakening opens another, up to 4.")
    socketed(char).append(_take(user, chip_id))
    return _refresh(user, char), chip


def unsocket(user, uuid_: str, chip_id: str):
    char, _, _ = locate(user, uuid_)
    if len(bag(user)) >= BAG_MAX:
        raise GameError(f"Your chip bag is full ({BAG_MAX}). Scrap a chip first.")
    for i, chip in enumerate(socketed(char)):
        if chip["id"] == chip_id:
            bag(user).append(socketed(char).pop(i))
            return _refresh(user, char), chip
    raise GameError("That chip isn't socketed there.")


def scrap(user, chip_ids: List[str]) -> int:
    """Break spare chips down into Meteor Dust. Returns the dust."""
    gained = 0
    for chip_id in chip_ids:
        chip = _take(user, chip_id)
        gained += TIERS[chip["tier"]][3]
    user.fragments += gained
    return gained


def reroll(user, chip_id: str) -> dict:
    """New random stats for a spare chip, same synergy and tier, for Meteor Dust."""
    chip = next((c for c in bag(user) if c["id"] == chip_id), None)
    if chip is None:
        raise GameError("That chip isn't in your bag.")
    cost = TIERS[chip["tier"]][4]
    if user.fragments < cost:
        raise GameError(f"A reroll costs {cost:,} Meteor Dust.")
    user.fragments -= cost
    fresh = roll(chip["syn"], chip["tier"])
    chip["stats"] = fresh["stats"]
    return chip


def give_back(user, chars: list) -> int:
    """Released or fused-away stands drop their chips into the bag (past BAG_MAX they're scrapped for dust)."""
    back = 0
    for char in chars:
        for chip in char.data.pop("chips", []) or []:
            if len(bag(user)) < BAG_MAX:
                bag(user).append(chip)
            else:
                user.fragments += TIERS[chip["tier"]][3]
            back += 1
    return back
