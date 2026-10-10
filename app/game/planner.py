"""Team planner: put any 3 stands together, owned or not, at any level, awakening, type and quality, and see
what the team adds up to: each stand's stats before and after its synergies, the synergies and resonances it
lights, its terrain, the synergies one stand away, and a simulation through the real engine. Nothing is saved;
the plan lives in the URL so it can be shared.

A slot is p<i> = "u:<uuid>" (one of your copies, exactly as it is: items and chips included) or "s:<stand id>"
(any stand), with l<i> level, a<i> awakening, t<i> type, q<i> quality ("none", "good" or "perfect"), i<i> up to
MAX_ITEMS item ids (repeated), r<i> their refine level and k<i> taunt ("1" on, "0" off, absent: the stand's own).
One of your copies can try other gear too: ox<i>="1" swaps its items for o<i> (refined to or<i>), keeping everything
else (level, stars, types, chips) as it is.
"""
import copy
from typing import List, Optional

from app.game.character import CHARACTER_FILE, MAX_LEVEL, character_from_dict

SLOTS = 3
QUALITIES = {"none": None, "good": "GOOD", "perfect": "UNIVERSAL"}
QUALITY_LABEL = {"none": "No type", "good": "Good", "perfect": "Perfect"}
TYPES = ["ATTACK", "DEFENSE", "SPEED", "LUCK", "BALANCE", "HEALTH"]
MAX_STARS = 5
MAX_ITEMS = 3
REFINE_MAX = 5
PLAYABLE = [c for c in CHARACTER_FILE if c["universe"] != "Dummy"]
PLAYABLE_IDS = {c["id"] for c in PLAYABLE}
STATS = [("hp", "Health"), ("damage", "Damage"), ("armor", "Armor"), ("speed", "Speed"), ("critical", "Critical")]


def best_type(stand_id: int) -> str:
    """The type that powers this stand's special (what the planner suggests first)."""
    from app.game.characterabilities import STAT_INFO, scaling_of
    return STAT_INFO[scaling_of(stand_id)][2]


def _int(value, lo, hi, default):
    try:
        return max(lo, min(hi, int(value)))
    except (TypeError, ValueError):
        return default


def parse(args, user) -> List[dict]:
    """The slots of a plan from request args; an empty plan starts from the player's own team."""
    if not any(args.get(f"p{i}") for i in range(SLOTS)) and user and not args.get("blank"):
        return [{"pick": f"u:{c.uuid}", "level": c.level, "awaken": c.awaken, "type": best_type(c.id), "quality": "perfect"}
                for c in user.main_characters[:SLOTS]] + [None] * (SLOTS - len(user.main_characters[:SLOTS]))
    slots = []
    for i in range(SLOTS):
        pick = (args.get(f"p{i}") or "").strip()
        if not pick:
            slots.append(None)
            continue
        quality = args.get(f"q{i}") if args.get(f"q{i}") in QUALITIES else "perfect"
        stype = args.get(f"t{i}") if args.get(f"t{i}") in TYPES else None
        raw_items = args.getlist(f"i{i}") if hasattr(args, "getlist") else (args.get(f"i{i}") or [])
        if isinstance(raw_items, str):
            raw_items = [raw_items]
        from app.game.pickers import item_ids
        allowed = item_ids()
        items = [int(x) for x in raw_items if str(x).isdigit() and int(x) in allowed][:MAX_ITEMS]
        taunt = {"1": True, "0": False}.get(args.get(f"k{i}"))
        raw_over = args.getlist(f"o{i}") if hasattr(args, "getlist") else []
        override = args.get(f"ox{i}") == "1" and pick.startswith("u:")
        over_items = [int(x) for x in raw_over if str(x).isdigit() and int(x) in allowed][:MAX_ITEMS]
        slots.append({"pick": pick, "level": _int(args.get(f"l{i}"), 1, MAX_LEVEL, MAX_LEVEL),
                      "awaken": _int(args.get(f"a{i}"), 0, MAX_STARS, 0), "type": stype, "quality": quality,
                      "items": items, "taunt": taunt, "refine": _int(args.get(f"r{i}"), 0, REFINE_MAX, 0),
                      "override": override, "over_items": over_items, "over_refine": _int(args.get(f"or{i}"), 0, REFINE_MAX, 0)})
    return slots


def build(slot: Optional[dict], user):
    """A Character for a slot, or None (empty, or a copy the player no longer has)."""
    if not slot:
        return None
    kind, _, ref = slot["pick"].partition(":")
    if kind == "u":
        char, _, _ = user.find_character_by_uuid(ref) if user else (None, None, None)
        if char is None:
            return None
        slot.update(level=char.level, awaken=char.awaken, owned=True)
        data = copy.deepcopy(char.to_dict())
        if slot.get("override"):  # this copy, with other gear on
            data["items"] = [{"id": i, "refine": slot.get("over_refine", 0)} for i in slot.get("over_items") or []][:MAX_ITEMS]
        else:
            slot["over_items"] = [it["id"] for it in data.get("items", [])][:MAX_ITEMS]  # what the switch starts from
        return character_from_dict(data)
    if kind != "s" or not ref.isdigit() or int(ref) not in PLAYABLE_IDS:
        return None
    sid = int(ref)
    slot["type"] = slot.get("type") or best_type(sid)
    q = QUALITIES[slot["quality"]]
    slot["owned"] = False
    data = {"id": sid, "xp": slot["level"] * 100, "awaken": slot["awaken"], "types": [slot["type"]] if q else [],
            "qualities": [q] if q else [], "items": [{"id": i, "refine": slot.get("refine", 0)} for i in slot.get("items") or []][:MAX_ITEMS]}
    if slot.get("taunt") is not None:
        data["_planner_taunt"] = slot["taunt"]
    return character_from_dict(data)


def _stats(c) -> dict:
    """What a stand walks into a fight with (synergies raise max health and the current stats)."""
    return {"hp": c.start_hp, "damage": c.current_damage, "armor": c.current_armor, "speed": c.current_speed,
            "critical": c.current_critical}


def review(chars: list) -> dict:
    """Everything the review panel shows for a team of built stands (Nones are empty slots)."""
    from app.filters import power_score
    from app.game import resonance
    from app.game.characterabilities import (SYNERGIES, SYNERGY_BONUS, SYNERGY_INFO, SYNERGY_MIN,
                                             apply_synergy_bonuses, special_power)
    from app.game.effects import TERRAIN_SETTERS, fmt_perk
    team = [c for c in chars if c is not None]
    if not team:
        return {"empty": True}
    boosted = copy.deepcopy(team)
    groups = apply_synergy_bonuses(boosted, parts=True)
    stands = []
    for c, b in zip(team, boosted):
        before, after = _stats(c), _stats(b)
        sp = special_power(c)
        stands.append({"char": c, "before": before, "after": after,
                       "gain": {k: after[k] - before[k] for k in before},
                       "power": power_score(c), "special": sp, "turns": c.turn_for_ability, "taunt": c.taunt,
                       "crit_mult": getattr(c, "crit_multiplier", 1.5), "terrain": TERRAIN_SETTERS.get(c.id)})
    ids = {c.id for c in team}
    synergies = [{"key": name, "label": SYNERGY_INFO.get(name, (name, "✶"))[0], "icon": SYNERGY_INFO.get(name, (name, "✶"))[1],
                  "members": members, "perks": [fmt_perk(s, v) for s, v in SYNERGY_BONUS.get(name, [])]}
                 for name, members in groups]
    lit = set(g["key"] for g in synergies)
    near = []  # groups one stand away from lighting, with the stands that would do it
    names = {c["id"]: c["name"] for c in PLAYABLE}
    for name, members in SYNERGIES.items():
        have, need = len(members & ids), SYNERGY_MIN.get(name, 2)
        if name in lit or have == 0 or have != need - 1:
            continue
        label, icon = SYNERGY_INFO.get(name, (name, "✶"))
        near.append({"label": label, "icon": icon, "with": [names[i] for i in sorted(members - ids) if i in names][:5],
                     "more": max(0, len(members - ids) - 5)})
    near.sort(key=lambda g: len(g["with"]))
    reso = [{"key": k, **dict(zip(("label", "icon", "needs", "effect"), resonance.RESONANCES[k]))}
            for k in resonance.active(team)]
    totals = {k: sum(s["after"][k] for s in stands) for k, _ in STATS}
    return {"empty": False, "stands": stands, "synergies": synergies, "near": near[:6], "resonances": reso,
            "totals": totals, "power": sum(s["power"] for s in stands),
            "avg_crit": round(totals["critical"] / len(stands), 1),
            "terrains": [(s["char"].name, s["terrain"]) for s in stands if s["terrain"]],
            "home": resonance.home_terrain(team) if "home_field" in {r["key"] for r in reso} else None,
            "taunts": [s["char"].name for s in stands if s["taunt"]], "count": len(team)}


# ── Suggestions for the last empty slot ──────────────────────────────────

RESONANCE_WORTH = 0.08   # each resonance a candidate lights counts as this share of the team's value
TAUNT_WORTH = 0.04       # and a first taunt on the team as this
SUGGEST = 4              # how many of each kind (yours, any stand)
NOT_SUGGESTED = {110}    # The World Over Heaven unsealed: raid-boss numbers would top every list


def _value(team: list) -> tuple:
    """(team value, lit synergy keys, lit resonance keys): the power formula on the stats after synergies."""
    from app.game import resonance
    from app.game.characterabilities import apply_synergy_bonuses, special_power
    boosted = copy.deepcopy(team)
    groups = {name for name, _ in apply_synergy_bonuses(boosted, parts=True)}
    total = 0.0
    for c, b in zip(team, boosted):
        raw = (b.start_hp / 3 + b.current_damage * 2 + b.current_armor / 2 + b.current_speed * 6 + b.current_critical * 3)
        total += raw * (1 + 0.4 * (special_power(c)["power"] - 1))
    return total, groups, set(resonance.active(team))


def suggest(chars: list, user, slots: List[Optional[dict]]) -> Optional[dict]:
    """With exactly one slot left empty: the stands that would add the most there, from the player's collection and
    from every stand (built like the team: its average level and stars, Perfect, the type its special wants)."""
    from app.filters import power_score
    from app.game import resonance
    from app.game.characterabilities import SYNERGY_INFO
    team = [c for c in chars if c is not None]
    if len(team) != SLOTS - 1:
        return None
    empty = next(i for i, c in enumerate(chars) if c is None)
    base, base_groups, base_reso = _value(team)
    ids = {c.id for c in team}
    has_taunt = any(c.taunt for c in team)
    level = max(1, min(MAX_LEVEL, round(sum(c.level for c in team) / len(team))))
    stars = max(0, min(MAX_STARS, round(sum(c.awaken for c in team) / len(team))))

    def score(cand):
        value, groups, reso = _value(team + [cand])
        new_groups, new_reso = groups - base_groups, reso - base_reso
        gain = value - base + base * (RESONANCE_WORTH * len(new_reso) + (TAUNT_WORTH if cand.taunt and not has_taunt else 0))
        why = [f"{SYNERGY_INFO.get(g, (g, ''))[1]} {SYNERGY_INFO.get(g, (g, ''))[0]}" for g in sorted(new_groups)]
        why += [f"{resonance.RESONANCES[k][1]} {resonance.RESONANCES[k][0]}" for k in sorted(new_reso)]
        if cand.taunt and not has_taunt:
            why.append("🎯 a taunt to shield the team")
        return gain, why

    mine, seen = [], {}
    if user:
        for c in user.main_characters + user.storage_characters:
            if c.id in ids or (c.id in NOT_SUGGESTED and not getattr(c, "sealed", False)):
                continue
            if c.id in seen and power_score(seen[c.id]) >= power_score(c):
                continue
            seen[c.id] = c
        for c in seen.values():
            gain, why = score(character_from_dict(copy.deepcopy(c.to_dict())))
            mine.append({"value": f"u:{c.uuid}", "id": c.id, "name": c.name, "rarity": c.rarity, "level": c.level,
                         "awaken": c.awaken, "gain": gain, "why": why})
    anyone = []
    for t in PLAYABLE:
        if t["id"] in ids or t["id"] in NOT_SUGGESTED:
            continue
        slot = {"pick": f"s:{t['id']}", "level": level, "awaken": stars, "type": None, "quality": "perfect", "items": []}
        cand = build(slot, None)
        gain, why = score(cand)
        anyone.append({"value": slot["pick"], "id": t["id"], "name": t["name"], "rarity": t["rarity"], "level": level,
                       "awaken": stars, "type": slot["type"], "gain": gain, "why": why})
    top = lambda rows: [dict(r, pct=round(100 * r["gain"] / base) if base else 0)
                        for r in sorted(rows, key=lambda r: -r["gain"])[:SUGGEST]]
    return {"slot": empty, "mine": top(mine), "any": top(anyone), "level": level, "awaken": stars}


def query(slots: List[Optional[dict]]) -> dict:
    """The plan as URL args (for the shareable link)."""
    out = {}
    for i, s in enumerate(slots):
        if not s:
            continue
        out[f"p{i}"] = s["pick"]
        if not s["pick"].startswith("u:"):
            out.update({f"l{i}": s["level"], f"a{i}": s["awaken"], f"t{i}": s.get("type") or "", f"q{i}": s["quality"]})
            if s.get("items"):
                out[f"i{i}"] = list(s["items"])
            if s.get("taunt") is not None:
                out[f"k{i}"] = "1" if s["taunt"] else "0"
            if s.get("refine"):
                out[f"r{i}"] = s["refine"]
        elif s.get("override"):  # your copy, trying other gear
            out.update({f"ox{i}": "1", f"o{i}": list(s.get("over_items") or []), f"or{i}": s.get("over_refine", 0)})
    return out
