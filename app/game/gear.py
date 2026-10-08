"""Gear beyond the raw item stats: item sets, refining duplicates, and what equipping an item would change.

Sets: a stand holding 2 or 3 different pieces of a set gains its bonus (stat lines like stand chips: *_pct are a
share of the stat, *_flat are points), on top of the items' own stats.

Refining: a spare copy of the same item plus Meteor Dust raises an item one level, up to items.REFINE_MAX; each
level adds items.REFINE_STEP of its listed stats. The copy refined is the best one in the bag (or one a team stand
holds); the copy spent is the least refined spare.
"""
from typing import List, Optional

from app.game.economy import dust
from app.game.items import REFINE_MAX, item_file, spare

STAT_LABEL = {"hp_pct": "HP", "damage_pct": "damage", "armor_pct": "armor", "speed_flat": "speed", "crit_flat": "crit"}

# key -> name, icon, pieces (item ids), {pieces worn: [(stat, value)]}
SETS = {
    "hamon": ("Hamon Breathing", "☀️", (51, 56, 6), {2: [("speed_flat", 6), ("hp_pct", 0.06)],
                                                     3: [("speed_flat", 12), ("hp_pct", 0.12), ("damage_pct", 0.06)]}),
    "rokakaka": ("Equivalent Exchange", "🌿", (43, 54, 49), {2: [("hp_pct", 0.10)],
                                                            3: [("hp_pct", 0.18), ("armor_pct", 0.10)]}),
    "gambler": ("High Roller", "🎲", (15, 55, 52), {2: [("crit_flat", 10)], 3: [("crit_flat", 22), ("speed_flat", 4)]}),
    "crusaders": ("Stardust Crusaders", "⭐", (46, 42, 44, 53), {2: [("armor_pct", 0.08), ("damage_pct", 0.05)],
                                                                3: [("armor_pct", 0.15), ("damage_pct", 0.10)]}),
    "sbr": ("Steel Ball Run", "🐎", (41, 50, 37), {2: [("speed_flat", 8)], 3: [("speed_flat", 14), ("damage_pct", 0.10)]}),
    "pillar": ("Pillar Men", "🗿", (7, 6, 45), {2: [("damage_pct", 0.08)], 3: [("damage_pct", 0.14), ("hp_pct", 0.08)]}),
}
SET_OF = {iid: key for key, (_, _, pieces, _) in SETS.items() for iid in pieces}

REFINE_COST = [dust(c) for c in (500, 1000, 2000, 3500, 5000)]  # Meteor Dust for +1 ... +5


def _fmt(stat: str, value: float) -> str:
    return f"+{round(value * 100)}% {STAT_LABEL[stat]}" if stat.endswith("_pct") else f"+{value:g} {STAT_LABEL[stat]}"


def active_sets(items) -> List[dict]:
    """Sets a stand's items light up: [{key, name, icon, worn, of, bonus: [(stat, value)], text}]."""
    worn = {}
    for it in items:
        key = SET_OF.get(it.id)
        if key:
            worn.setdefault(key, set()).add(it.id)
    out = []
    for key, ids in worn.items():
        name, icon, pieces, tiers = SETS[key]
        n = min(3, len(ids))
        if n < 2:
            continue
        bonus = tiers[n]
        out.append({"key": key, "name": name, "icon": icon, "worn": n, "of": min(3, len(pieces)), "bonus": bonus,
                    "text": ", ".join(_fmt(s, v) for s, v in bonus)})
    return out


def set_lines(items) -> List[dict]:
    """The set bonuses as chip-like stat lines (character.apply_chips)."""
    return [{"stats": s["bonus"]} for s in active_sets(items)]


def set_info(item_id: int) -> Optional[dict]:
    """The set an item belongs to, for its card: {name, icon, pieces: [names], tiers: {2: text, 3: text}}."""
    key = SET_OF.get(item_id)
    if not key:
        return None
    name, icon, pieces, tiers = SETS[key]
    return {"key": key, "name": name, "icon": icon, "pieces": [item_file[i - 1]["name"] for i in pieces],
            "tiers": {n: ", ".join(_fmt(s, v) for s, v in lines) for n, lines in tiers.items()}}


# ── Refining ─────────────────────────────────────────────────────────────
def refine_cost(level: int) -> Optional[int]:
    """Meteor Dust to take an item from level to level + 1, or None at the cap."""
    return REFINE_COST[level] if level < REFINE_MAX else None


def refine(user, item_id: int, uuid: Optional[str] = None, slot: Optional[int] = None):
    """Refine the best bag copy of item_id (or the one a team stand holds in slot) with a spare copy and dust.
    Returns the refined item."""
    from app.game.logic import GameError, locate
    if uuid:
        char, _, _ = locate(user, uuid)
        if slot is None or not 0 <= slot < len(char.items) or char.items[slot].id != item_id:
            raise GameError("That item isn't in that slot.")
        target = char.items[slot]
        fodder = spare(user.items, item_id)
    else:
        copies = spare(user.items, item_id)
        if not copies:
            raise GameError("You don't have that item.")
        target, fodder = copies[-1], copies[:-1]
    if not target.is_equipable:
        raise GameError(f"{target.name} can't be refined: only gear can.")
    cost = refine_cost(target.refine)
    if cost is None:
        raise GameError(f"{target.label} is already at +{REFINE_MAX}.")
    if not fodder:
        raise GameError(f"Refining needs a spare {target.name} to fuse into it.")
    if user.fragments < cost:
        raise GameError(f"Refining to +{target.refine + 1} costs {cost:,} Meteor Dust.")
    user.items.remove(fodder[0])
    user.fragments -= cost
    target.data["refine"] = target.refine + 1
    from app.game.items import Item
    fresh = Item(target.data)
    holder = char.items if uuid else user.items
    holder[holder.index(target)] = fresh
    return fresh


# ── Equip preview ────────────────────────────────────────────────────────
def preview(char, item) -> dict:
    """What equipping item (an Item) on char would change: stat deltas, special power, sets lit."""
    from app.game import characterabilities as abilities
    from app.game.character import Character
    before = Character(char.to_dict())
    data = char.to_dict()
    data = {**data, "items": list(data.get("items", [])) + [dict(item.to_dict())]}
    after = Character(data)
    delta = {"hp": after.start_hp - before.start_hp, "damage": round(after.start_damage - before.start_damage),
             "speed": after.start_speed - before.start_speed, "crit": round(after.start_critical - before.start_critical),
             "armor": round(after.start_armor - before.start_armor)}
    p0, p1 = abilities.special_power(before), abilities.special_power(after)
    special = round((p1["power"] / max(0.01, p0["power"]) - 1) * 100)
    new_sets = [s for s in active_sets(after.items) if s["key"] not in {x["key"] for x in active_sets(before.items)}
                or s["worn"] > next(x["worn"] for x in active_sets(before.items) if x["key"] == s["key"])]
    return {"delta": delta, "special": special, "stat": abilities.STAT_INFO[p0["stat"]][1], "sets": new_sets}


def preview_line(char, item) -> str:
    """"+187 HP · +32 crit · special +38% (Luck) · set: High Roller 2/3" for pickers."""
    p = preview(char, item)
    labels = (("hp", "HP"), ("damage", "ATK"), ("armor", "ARM"), ("speed", "SPD"), ("crit", "CRT"))
    parts = [f"{'+' if p['delta'][k] > 0 else ''}{p['delta'][k]} {label}" for k, label in labels if p["delta"][k]]
    if p["special"]:
        parts.append(f"special {'+' if p['special'] > 0 else ''}{p['special']}% ({p['stat']})")
    parts += [f"{s['icon']} {s['name']} {s['worn']}/{s['of']}" for s in p["sets"]]
    return " · ".join(parts) or "no stat change"
