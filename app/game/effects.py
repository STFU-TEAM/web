from enum import Enum

from typing import TYPE_CHECKING, Optional

# It's for typehint
if TYPE_CHECKING:
    from app.game.character import Character


Emoji = {
    "STUN": "💫",
    "POISON": "☠️",
    "WEAKEN": "💔",
    "REGENERATION": "💚",
    "DAMAGEUP": "⚔️",
    "SPEEDUP": "💨",
    "SLOW": "🐌",
    "BURN": "🔥",
    "BLEED": "🩸",
    "HEALTHBOOST": "➕",
    "ARMORUP": "🛡️",
    "ARMORBREAK": "🧱",
    "CRITUP": "🎯",
    "TERRAIN": "",
}


class EffectType(Enum):
    STUN = "STUN"
    POISON = "POISON"
    WEAKEN = "WEAKEN"
    REGENERATION = "REGENERATION"
    SLOW = "SLOW"
    DAMAGEUP = "DAMAGEUP"
    SPEEDUP = "SPEEDUP"
    BURN = "BURN"
    BLEED = "BLEED"
    HEALTHBOOST = "HEALTHBOOST"
    ARMORUP = "ARMORUP"
    ARMORBREAK = "ARMORBREAK"
    CRITUP = "CRITUP"
    TERRAIN = "TERRAIN"


# Stat effects change a stat once when applied and undo exactly that when they expire.
# (attribute, sign): WEAKEN of value 12 means current_damage -12 while it lasts.
STAT_EFFECTS = {
    EffectType.WEAKEN: ("current_damage", -1),
    EffectType.DAMAGEUP: ("current_damage", 1),
    EffectType.SLOW: ("current_speed", -1),
    EffectType.SPEEDUP: ("current_speed", 1),
    EffectType.ARMORUP: ("current_armor", 1),
    EffectType.ARMORBREAK: ("current_armor", -1),
    EffectType.CRITUP: ("current_critical", 1),
}
DOT_EFFECTS = (EffectType.POISON, EffectType.BURN, EffectType.BLEED)


class Effect:
    def __init__(
        self,
        type: EffectType,
        duration: int,
        value: int,
        sender: Optional["Character"] = None,
    ):
        self.type: EffectType = type
        self.duration: int = duration
        self.value: int = value
        self.used: bool = False
        self.emoji: str = Emoji[self.type.name]
        self.sender: Optional["Character"] = sender
        # Set when it lands during its owner's own turn: that turn doesn't count toward the duration.
        self.fresh: bool = False


NEGATIVE_EFFECTS = [EffectType.POISON, EffectType.BURN, EffectType.BLEED, EffectType.STUN, EffectType.WEAKEN,
                    EffectType.SLOW, EffectType.ARMORBREAK]
POSITIVE_EFFECTS = [EffectType.REGENERATION, EffectType.DAMAGEUP, EffectType.SPEEDUP, EffectType.ARMORUP,
                    EffectType.CRITUP, EffectType.HEALTHBOOST]


class Terrain(Enum):
    """Terrain types for fights.
    The fastest alive stand that has a terrain entry sets the active terrain.
    Re-evaluated every round. Each terrain has a field-wide rule for everyone,
    plus bonuses for the stands native to it (TERRAIN_BENEFITS)."""
    DEFAULT  = ("DEFAULT",  "Neutral Ground", "🏞️", "No field rule.")
    OCEAN    = ("OCEAN",    "Ocean",          "🌊", "Burns are put out. Non-native stands lose 15% speed.")
    DESERT   = ("DESERT",   "Desert",         "🏜️", "Burns deal 50% more. All healing is 30% weaker.")
    FROZEN   = ("FROZEN",   "Frozen Wastes",  "❄️", "Critical hits deal ×2. Non-native stands lose 20% speed.")
    MIRROR   = ("MIRROR",   "Mirror World",   "🪞", "+10 critical for everyone. Critical hits ignore armor.")
    NATURE   = ("NATURE",   "Nature",         "🌿", "Every stand regenerates 3% max health per turn. Poison deals 50% more.")
    GRAVITY  = ("GRAVITY",  "Gravity Field",  "🌀", "Nobody can dodge. Every hit deals 10% more damage.")

    def __new__(cls, key, display_name, emoji, rule):
        obj = object.__new__(cls)
        obj._value_ = key
        obj.display_name = display_name
        obj.emoji = emoji
        obj.rule = rule
        return obj

    @property
    def name(self):
        return self._value_

    @classmethod
    def from_string(cls, name):
        try:
            return cls[name]
        except KeyError:
            return cls.DEFAULT


# Field-wide numbers the engine reads (character.attack / end_turn / heal).
TERRAIN_DOT_MULT = {Terrain.OCEAN: {EffectType.BURN: 0.0}, Terrain.DESERT: {EffectType.BURN: 1.5},
                    Terrain.NATURE: {EffectType.POISON: 1.5}}
TERRAIN_HEAL_MULT = {Terrain.DESERT: 0.7}
TERRAIN_REGEN = {Terrain.NATURE: 0.03}
TERRAIN_SPEED_PENALTY = {Terrain.OCEAN: 0.15, Terrain.FROZEN: 0.20}  # natives are exempt
TERRAIN_CRIT_MULT = {Terrain.FROZEN: 2.0}
TERRAIN_CRIT_BONUS = {Terrain.MIRROR: 10}
TERRAIN_CRIT_PIERCES = {Terrain.MIRROR}
TERRAIN_NO_DODGE = {Terrain.GRAVITY}
TERRAIN_DAMAGE_MULT = {Terrain.GRAVITY: 1.10}


# ── Terrain data ────────────────────────────────────────────────────────
# Which terrain a character "brings". The fastest alive setter wins.
TERRAIN_SETTERS = {
    # OCEAN
    7:  Terrain.OCEAN,    # Dark Blue Moon
    76: Terrain.OCEAN,    # Clash
    71: Terrain.OCEAN,    # Beach Boy
    # DESERT
    2:  Terrain.DESERT,   # Magician's Red
    18: Terrain.DESERT,   # The Sun
    # FROZEN
    74: Terrain.FROZEN,   # White Album
    27: Terrain.FROZEN,   # Horus
    # MIRROR
    68: Terrain.MIRROR,   # Man in the Mirror
    30: Terrain.MIRROR,   # Cream
    83: Terrain.MIRROR,   # Chariot Requiem
    # NATURE
    59: Terrain.NATURE,   # Gold Experience
    54: Terrain.NATURE,   # Stray Cat
    81: Terrain.NATURE,   # Green Day
    # GRAVITY
    108: Terrain.GRAVITY, # C-Moon
    109: Terrain.GRAVITY, # Made in Heaven
    95:  Terrain.GRAVITY, # Jumpin Jack Flash
}

# Character ID → {Terrain: [(stat, value)]}: the stands native to a terrain.
# stat types: "damage_pct", "speed_pct", "armor_pct", "crit_flat", "regen_pct"
# pct values are multipliers (0.15 = +15%), crit_flat is flat addition,
# regen_pct heals % of max health each round (not reversed).
# Natives also ignore the terrain's speed penalty.
TERRAIN_BENEFITS = {
    # ── OCEAN natives ──
    7:   {Terrain.OCEAN: [("speed_pct", 0.20), ("damage_pct", 0.15)]},
    76:  {Terrain.OCEAN: [("damage_pct", 0.15), ("speed_pct", 0.15)]},
    71:  {Terrain.OCEAN: [("damage_pct", 0.15), ("regen_pct", 0.03)]},
    22:  {Terrain.OCEAN: [("speed_pct", 0.20), ("damage_pct", 0.15)]},
    33:  {Terrain.OCEAN: [("damage_pct", 0.15)]},
    # ── DESERT natives ──
    2:   {Terrain.DESERT: [("damage_pct", 0.15)]},
    18:  {Terrain.DESERT: [("damage_pct", 0.15), ("armor_pct", 0.15)]},
    5:   {Terrain.DESERT: [("armor_pct", 0.25)]},
    80:  {Terrain.DESERT: [("damage_pct", 0.15)]},
    72:  {Terrain.DESERT: [("damage_pct", 0.15)]},
    143: {Terrain.DESERT: [("damage_pct", 0.15)]},
    # ── FROZEN natives ──
    74:  {Terrain.FROZEN: [("armor_pct", 0.25)]},
    27:  {Terrain.FROZEN: [("damage_pct", 0.15)]},
    42:  {Terrain.FROZEN: [("damage_pct", 0.10)]},
    4:   {Terrain.FROZEN: [("speed_pct", 0.15)]},
    127: {Terrain.FROZEN: [("crit_flat", 10)]},
    146: {Terrain.FROZEN: [("damage_pct", 0.15)]},
    # ── MIRROR natives ──
    68:  {Terrain.MIRROR: [("damage_pct", 0.15)]},
    30:  {Terrain.MIRROR: [("damage_pct", 0.15)]},
    13:  {Terrain.MIRROR: [("crit_flat", 10)]},
    44:  {Terrain.MIRROR: [("armor_pct", 0.15)]},
    83:  {Terrain.MIRROR: [("damage_pct", 0.15)]},
    # ── NATURE natives ──
    59:  {Terrain.NATURE: [("regen_pct", 0.04)]},
    69:  {Terrain.NATURE: [("damage_pct", 0.15)]},
    81:  {Terrain.NATURE: [("damage_pct", 0.15)]},
    54:  {Terrain.NATURE: [("crit_flat", 10)]},
    43:  {Terrain.NATURE: [("regen_pct", 0.03)]},
    47:  {Terrain.NATURE: [("speed_pct", 0.15)]},
    78:  {Terrain.NATURE: [("regen_pct", 0.03)]},
    147: {Terrain.NATURE: [("damage_pct", 0.15)]},
    # ── GRAVITY natives ──
    109: {Terrain.GRAVITY: [("speed_pct", 0.20)]},
    95:  {Terrain.GRAVITY: [("damage_pct", 0.15)]},
    115: {Terrain.GRAVITY: [("damage_pct", 0.15)]},
    114: {Terrain.GRAVITY: [("damage_pct", 0.15)]},
    161: {Terrain.GRAVITY: [("damage_pct", 0.15)]},
    # ── Multi-terrain natives ──
    108: {Terrain.OCEAN: [("speed_pct", 0.10)], Terrain.GRAVITY: [("speed_pct", 0.15), ("damage_pct", 0.10)]},
}


def is_native(c, terrain: Terrain) -> bool:
    return terrain in TERRAIN_BENEFITS.get(c.id, {})


# ── Terrain helpers (called from the fight loop) ───────────────────────

def get_active_terrain(all_characters: list) -> Terrain:
    """Return the terrain set by the fastest alive character that has one."""
    fastest = None
    fastest_speed = -1
    for c in all_characters:
        if c.is_alive() and c.id in TERRAIN_SETTERS:
            if c.current_speed > fastest_speed:
                fastest = c
                fastest_speed = c.current_speed
    if fastest is None:
        return Terrain.DEFAULT
    return TERRAIN_SETTERS[fastest.id]


def apply_terrain_bonuses(all_characters: list, terrain: Terrain) -> None:
    """Apply the field rule and native bonuses for the active terrain. Call remove first."""
    for c in all_characters:
        c._active_terrain = terrain
    if terrain == Terrain.DEFAULT:
        return
    for c in all_characters:
        if not c.is_alive():
            continue
        benefits = list(TERRAIN_BENEFITS.get(c.id, {}).get(terrain, []))
        if terrain in TERRAIN_SPEED_PENALTY and not is_native(c, terrain):
            benefits.append(("speed_pct", -TERRAIN_SPEED_PENALTY[terrain]))
        if terrain in TERRAIN_CRIT_BONUS:
            benefits.append(("crit_flat", TERRAIN_CRIT_BONUS[terrain]))
        bonus = {}
        for stat, value in benefits:
            if stat == "damage_pct":
                added = int(c.current_damage * value)
                c.current_damage += added
                bonus["damage"] = bonus.get("damage", 0) + added
            elif stat == "speed_pct":
                added = c.current_speed * value
                c.current_speed += added
                bonus["speed"] = bonus.get("speed", 0) + added
            elif stat == "armor_pct":
                added = int(c.current_armor * value)
                c.current_armor += added
                bonus["armor"] = bonus.get("armor", 0) + added
            elif stat == "crit_flat":
                c.current_critical += value
                bonus["crit"] = bonus.get("crit", 0) + value
            elif stat == "regen_pct" and getattr(c, "_my_turn", True):
                # once per own turn; regen is not reversed — it's a heal, not a buff
                c.heal(c.start_hp * value)
        c._terrain_bonus = bonus


def remove_terrain_bonuses(all_characters: list) -> None:
    """Reverse stat bonuses from the previous terrain pass."""
    for c in all_characters:
        c._active_terrain = Terrain.DEFAULT
        bonus = getattr(c, "_terrain_bonus", None)
        if not bonus:
            continue
        if "damage" in bonus:
            c.current_damage -= bonus["damage"]
        if "speed" in bonus:
            c.current_speed -= bonus["speed"]
        if "armor" in bonus:
            c.current_armor -= bonus["armor"]
        if "crit" in bonus:
            c.current_critical -= bonus["crit"]
        c._terrain_bonus = None
