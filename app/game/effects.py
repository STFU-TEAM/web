
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
    "DAMAGEUP":"⚔️",
    "SPEEDUP":"💨",
    "SLOW": "🐌",
    "BURN":"🔥",
    "BLEED":"🩸",
    "HEALTHBOOST":"➕",
    "TERRAIN":""
}


class EffectType(Enum):
    STUN = "STUN"
    POISON = "POISON"
    WEAKEN = "WEAKEN"
    REGENERATION = "REGENERATION"
    SLOW = "SLOW"
    DAMAGEUP= "DAMAGEUP"
    SPEEDUP = "SPEEDUP"
    BURN="BURN"
    BLEED="BLEED"
    HEALTHBOOST="HEALTHBOOST"
    TERRAIN="TERRAIN"


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

NEGATIVE_EFFECTS = [EffectType.POISON, EffectType.BURN, EffectType.BLEED,EffectType.STUN,EffectType.WEAKEN]


class Terrain(Enum):
    """Terrain types for fights.
    The fastest alive stand that has a terrain entry sets the active terrain.
    Re-evaluated every turn — if a stand becomes fastest, its terrain applies."""
    DEFAULT  = ("DEFAULT",  "Neutral Ground", "🏞️")
    OCEAN    = ("OCEAN",    "Ocean",          "🌊")
    DESERT   = ("DESERT",   "Desert",         "🏜️")
    FROZEN   = ("FROZEN",   "Frozen Wastes",  "❄️")
    MIRROR   = ("MIRROR",   "Mirror World",   "🪞")
    NATURE   = ("NATURE",   "Nature",         "🌿")
    GRAVITY  = ("GRAVITY",  "Gravity Field",  "🌀")

    def __new__(cls, key, display_name, emoji):
        obj = object.__new__(cls)
        obj._value_ = key
        obj.display_name = display_name
        obj.emoji = emoji
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

# Character ID → {Terrain: [(stat, value)]}
# stat types: "damage_pct", "speed_pct", "armor_pct", "crit_flat", "regen_pct"
# pct values are multipliers (0.15 = +15%), crit_flat is flat addition,
# regen_pct heals % of start_hp (not reversed).
TERRAIN_BENEFITS = {
    # ── OCEAN beneficiaries ──
    7:   {Terrain.OCEAN: [("speed_pct", 0.20), ("damage_pct", 0.15)]},
    76:  {Terrain.OCEAN: [("damage_pct", 0.15), ("speed_pct", 0.15)]},
    71:  {Terrain.OCEAN: [("damage_pct", 0.15)]},
    22:  {Terrain.OCEAN: [("speed_pct", 0.20)]},
    # ── DESERT beneficiaries ──
    2:   {Terrain.DESERT: [("damage_pct", 0.15)]},
    18:  {Terrain.DESERT: [("damage_pct", 0.15)]},
    5:   {Terrain.DESERT: [("armor_pct", 0.20)]},
    80:  {Terrain.DESERT: [("damage_pct", 0.15)]},
    72:  {Terrain.DESERT: [("damage_pct", 0.15)]},
    # ── FROZEN beneficiaries ──
    74:  {Terrain.FROZEN: [("armor_pct", 0.20)]},
    27:  {Terrain.FROZEN: [("damage_pct", 0.15)]},
    42:  {Terrain.FROZEN: [("damage_pct", 0.10)]},
    4:   {Terrain.FROZEN: [("speed_pct", 0.15)]},
    # ── MIRROR beneficiaries ──
    68:  {Terrain.MIRROR: [("damage_pct", 0.15)]},
    30:  {Terrain.MIRROR: [("damage_pct", 0.15)]},
    13:  {Terrain.MIRROR: [("crit_flat", 5)]},
    44:  {Terrain.MIRROR: [("armor_pct", 0.15)]},
    83:  {Terrain.MIRROR: [("damage_pct", 0.10)]},
    # ── NATURE beneficiaries ──
    59:  {Terrain.NATURE: [("regen_pct", 0.10)]},
    69:  {Terrain.NATURE: [("damage_pct", 0.15)]},
    81:  {Terrain.NATURE: [("damage_pct", 0.10)]},
    54:  {Terrain.NATURE: [("crit_flat", 5)]},
    43:  {Terrain.NATURE: [("regen_pct", 0.05)]},
    47:  {Terrain.NATURE: [("speed_pct", 0.15)]},
    78:  {Terrain.NATURE: [("regen_pct", 0.05)]},
    # ── GRAVITY beneficiaries ──
    109: {Terrain.GRAVITY: [("speed_pct", 0.20)]},
    95:  {Terrain.GRAVITY: [("damage_pct", 0.15)]},
    115: {Terrain.GRAVITY: [("damage_pct", 0.15)]},
    114: {Terrain.GRAVITY: [("damage_pct", 0.15)]},
    161: {Terrain.GRAVITY: [("damage_pct", 0.10)]},
    # ── Multi-terrain beneficiaries ──
    108: {Terrain.OCEAN: [("speed_pct", 0.10)], Terrain.GRAVITY: [("speed_pct", 0.15)]},
}


# ── Terrain helpers (called from fight_loop) ───────────────────────────

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
    """Apply stat bonuses for the active terrain. Call remove first."""
    for c in all_characters:
        c._active_terrain = terrain
    if terrain == Terrain.DEFAULT:
        return
    for c in all_characters:
        if not c.is_alive():
            continue
        benefits = TERRAIN_BENEFITS.get(c.id, {}).get(terrain)
        if not benefits:
            continue
        bonus = {}
        for stat, value in benefits:
            if stat == "damage_pct":
                added = int(c.current_damage * value)
                c.current_damage += added
                bonus["damage"] = bonus.get("damage", 0) + added
            elif stat == "speed_pct":
                added = int(c.current_speed * value)
                c.current_speed += added
                bonus["speed"] = bonus.get("speed", 0) + added
            elif stat == "armor_pct":
                added = int(c.current_armor * value)
                c.current_armor += added
                bonus["armor"] = bonus.get("armor", 0) + added
            elif stat == "crit_flat":
                c.current_critical += value
                bonus["crit"] = bonus.get("crit", 0) + value
            elif stat == "regen_pct":
                heal = int(c.start_hp * value)
                c.current_hp = min(c.current_hp + heal, c.start_hp)
                # regen is not reversed — it's a heal, not a buff
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
