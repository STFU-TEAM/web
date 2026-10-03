"""What the fight screen shows about a stand's statuses: readable chips, and how much health its
damage over time and regeneration will move at the end of its next turn (the bar preview).

Mirrors Character.end_turn and Character.heal, so the preview matches what will happen."""
from app.game.effects import (DOT_EFFECTS, TERRAIN_DOT_MULT, TERRAIN_HEAL_MULT, TERRAIN_REGEN,
                              EffectType)

LABELS = {
    EffectType.POISON: ("Poison", "loses {v} health at the end of each of its turns"),
    EffectType.BURN: ("Burn", "loses {v} health at the end of each of its turns"),
    EffectType.BLEED: ("Bleed", "loses {v} health at the end of each of its turns"),
    EffectType.REGENERATION: ("Regen", "heals {v} at the end of each of its turns"),
    EffectType.STUN: ("Stunned", "skips its next turn"),
    EffectType.WEAKEN: ("Weakened", "{v} damage"),
    EffectType.DAMAGEUP: ("Empowered", "+{v} damage"),
    EffectType.SLOW: ("Slowed", "{v} speed"),
    EffectType.SPEEDUP: ("Hasted", "+{v} speed"),
    EffectType.ARMORBREAK: ("Armor broken", "{v} armor"),
    EffectType.ARMORUP: ("Guarded", "+{v} armor"),
    EffectType.CRITUP: ("Focused", "{s}{v} crit"),
}
SHORT = {  # the number shown on the chip itself
    EffectType.POISON: "−{v}", EffectType.BURN: "−{v}", EffectType.BLEED: "−{v}", EffectType.REGENERATION: "+{v}",
    EffectType.WEAKEN: "−{v}", EffectType.DAMAGEUP: "+{v}", EffectType.SLOW: "−{v}", EffectType.SPEEDUP: "+{v}",
    EffectType.ARMORBREAK: "−{v}", EffectType.ARMORUP: "+{v}", EffectType.CRITUP: "{s}{v}",
}
BAD = {EffectType.POISON, EffectType.BURN, EffectType.BLEED, EffectType.STUN, EffectType.WEAKEN, EffectType.SLOW,
       EffectType.ARMORBREAK}


def _heal_amount(c, amount: float) -> float:
    return amount * TERRAIN_HEAL_MULT.get(c.terrain, 1) * getattr(c, "_heal_mult", 1)


def view(c) -> dict:
    """{"dot": health lost next turn, "regen": health gained next turn, "chips": [...]}"""
    terrain = c.terrain
    dot = regen = 0.0
    chips = []
    for e in c.effects:
        if e.duration <= 0:
            continue
        value = e.value
        if e.type in DOT_EFFECTS:
            value = int(e.value * TERRAIN_DOT_MULT.get(terrain, {}).get(e.type, 1))
            dot += value
        elif e.type == EffectType.REGENERATION:
            value = int(_heal_amount(c, e.value))
            regen += value
        name, rule = LABELS.get(e.type, (e.type.name.title(), ""))
        sign = "+" if (e.type == EffectType.CRITUP and value >= 0) else ""
        v = abs(int(round(value)))
        if e.type in DOT_EFFECTS and value == 0:
            rule = "is put out by the terrain"
        turns = f"{e.duration} turn{'s' if e.duration != 1 else ''} left"
        bad = e.type in BAD or (e.type == EffectType.CRITUP and value < 0)
        chips.append({
            "emoji": e.emoji, "name": name, "bad": bad,
            "short": SHORT.get(e.type, "").format(v=v, s=sign) if v else "",
            "turns": e.duration,
            "title": f"{name}: {rule.format(v=v, s=sign)} · {turns}",
        })
    if terrain in TERRAIN_REGEN and c.is_alive():
        regen += _heal_amount(c, c.start_hp * TERRAIN_REGEN[terrain])
    hp = max(0, c.current_hp)
    dot = min(dot, hp)
    regen = max(0, min(regen, c.start_hp - (hp - dot)))
    chips.sort(key=lambda ch: (not ch["bad"], ch["name"]))
    return {"dot": int(dot), "regen": int(regen), "chips": chips}
