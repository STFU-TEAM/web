import random
import math
import json
import enum
import uuid

from app.game.items import Item, item_from_dict
from app.game.effects import (
    DOT_EFFECTS, STAT_EFFECTS, TERRAIN_CRIT_MULT, TERRAIN_CRIT_PIERCES, TERRAIN_DAMAGE_MULT, TERRAIN_DOT_MULT,
    TERRAIN_HEAL_MULT, TERRAIN_NO_DODGE, TERRAIN_REGEN, Effect, EffectType, Terrain,
)
from app.game.characterabilities import (
    specials,
    not_implemented,
)
from typing import List, TypeVar


# Health and damage grow at the same rate so a fight takes as many hits at level 100 as at level 1.
HPSCALING = 2
DAMAGESCALING = 2
SPEEDSCALING = 1
CRITICALSCALING = 1
CRITMULTIPLIER = 1.5  # bot's globals/variables.py value; character.py shadowed it with 1
# Critical chance has no cap: every full 100 is a sure crit and the rest is the chance of one more on top
# (150 = always a crit, half the time a double). Each crit past the first adds the crit bonus again.
DODGENERF = 2  # two points of speed gap per percent of dodge: speed decides who moves first, it shouldn't also be armor
DODGE_CHANCE_CAP = 20
# UR and LR are strong, not game-defining: their natural stats are trimmed toward the SSR line (speed most of all,
# since it decides who moves first), their specials need 2+ turns, and their specials hit a little softer
# (characterabilities.RARITY_SPECIAL_POWER). Raid bosses and the dummy keep their numbers.
RARITY_TRIM = {"UR": {"hp": 0.97, "damage": 0.96, "speed": 0.7}, "LR": {"hp": 0.95, "damage": 0.93, "speed": 0.6}}
UNTRIMMED = {110, 164}
# A sealed stand (data["sealed"]) takes these base stats and the special of SEALED_SPECIAL: The World Over Heaven
# (raid-boss numbers and a special that hits everyone for 1000x) fights like the other Mythics, with The World's
# time stop. The Torn Diary Page seals it in the Alternate Universe (app/game/altverse.py).
SEALED_FORMS = {110: {"base_hp": 510, "base_damage": 86, "base_speed": 20, "base_critical": 5, "base_armor": 100,
                      "turn_for_ability": 3}}
SEALED_SPECIAL = {110: 10}
# Some saves hold stands past ★5 (the bot allowed it): they keep their stars, but stats scale as ★5 at most
AWAKEN_SCALING_CAP = 5
MIN_SPECIAL_TURNS = {"UR": 2, "LR": 2}
# Giant Slayer (resonance): per rarity step a slayer deals more to higher-rarity stands and takes less from them
SLAYER_STEP, SLAYER_GUARD, SLAYER_STEPS = 0.12, 0.08, 3
ARMOR_CAP = 400  # damage taken never drops below 200 / (100 + 400) = 40%
GROWTH_CAP = 1.0
TAUNT_HP = 0  # taunt already draws every basic attack; keep the extra bulk modest
TAUNT_ARMOR = 20  # permanent self-buffs stop at +100% of the starting stat
STXPTOLEVEL = 100
MAX_LEVEL = 100
LEVEL_TO_STAT_INCREASE = 1
# Flat points the SPEED and LUCK types give, by quality (BALANCE gives a quarter)
SPEED_TYPE_POINTS = {"UNIVERSAL": 20, "SUPREME": 15, "GREAT": 10, "GOOD": 4, "SUB_PAR": 2, "BAD": 0}
LUCK_TYPE_POINTS = {"UNIVERSAL": 40, "SUPREME": 30, "GREAT": 20, "GOOD": 8, "SUB_PAR": 4, "BAD": 0}
# LUCK also makes crits hit harder: added to CRITMULTIPLIER
LUCK_CRIT_DAMAGE = {"UNIVERSAL": 0.4, "SUPREME": 0.3, "GREAT": 0.2, "GOOD": 0.1, "SUB_PAR": 0.0, "BAD": 0.0}

import os
_DATA = os.path.join(os.path.dirname(__file__), "data")
with open(os.path.join(_DATA, "characters.json"), "r", encoding="utf-8") as _f:
    CHARACTER_FILE = json.load(_f)["characters"]

character = TypeVar("character", bound="Character")


class Character:
    def __init__(self, data: dict):
        character_file = CHARACTER_FILE
        # define the constant
        self.data: dict = data
        # Lazy UUID — retroactively assigned on first load, no migration needed
        if "uuid" not in data or data["uuid"] is None:
            data["uuid"] = str(uuid.uuid4())
        self.uuid: str = data["uuid"]
        self.id: str = data["id"]
        self.name: str = character_file[self.id-1]["name"]
        self.rarity:str = character_file[self.id-1]["rarity"]
        self.xp: int = data.get("xp", 0)
        self.awaken: int = data.get("awaken", 0)
        self.trained: int = data.get("trained", 0)
        self.shiny: bool = bool(data.get("shiny", False))  # cosmetic variant: alternate colours, holo frame
        self.types:list[str] = data.get("types", [])
        self.qualities:list[str] = data.get("qualities", [])
        self.etypes:list[Types] = [Types.from_string(typ) for typ in self.types]
        self.equalities:list[Qualities] = [Qualities.from_string(qual) for qual in self.qualities]
        self.base_critical: float = character_file[self.id-1]["base_critical"]
        self.base_hp: int = character_file[self.id-1]["base_hp"]
        self.base_damage: int = character_file[self.id-1]["base_damage"]
        self.base_speed: int = character_file[self.id-1]["base_speed"]
        self.base_armor: int = character_file[self.id-1]["armor"]
        self.turn_for_ability: int = character_file[self.id-1]["turn_for_ability"]
        # Sealed (the Torn Diary Page): The World Over Heaven fights as a normal LR, not a raid boss
        self.sealed: bool = bool(data.get("sealed")) and self.id in SEALED_FORMS
        if self.sealed:
            for attr, value in SEALED_FORMS[self.id].items():
                setattr(self, attr, value)
        trim = RARITY_TRIM.get(self.rarity) if self.id not in UNTRIMMED or self.sealed else None
        if trim:
            self.base_hp = int(self.base_hp * trim["hp"])
            self.base_damage = int(self.base_damage * trim["damage"])
            self.base_speed = self.base_speed * trim["speed"]
            self.turn_for_ability = max(self.turn_for_ability, MIN_SPECIAL_TURNS[self.rarity])
        self.special_description: str = character_file[self.id-1]["special_description"]
        self.special_url:str = character_file[self.id-1]["special_url"]
        self.items: List[Item] = [item_from_dict(s) for s in data.get("items", [])]
        self.natural_taunt: bool = character_file[self.id-1]["taunt"]
        self.taunt: bool = self.natural_taunt or any(item.taunt for item in self.items)
        self.universe: str = character_file[self.id-1]["universe"]
        self.level: int = min(MAX_LEVEL, self.xp // STXPTOLEVEL)

        # Compute the starting Items and XP scaling.
        bonus_hp = (TAUNT_HP * self.taunt) + 100 # Give taunting characters more effective health
        bonus_damage = 0
        bonus_speed = 0
        bonus_critical = 0
        bonus_armor = (TAUNT_ARMOR * self.taunt) # Give taunting characters more effective health
        for item in self.items:
            bonus_hp += item.bonus_hp
            bonus_damage += item.bonus_damage
            bonus_speed += item.bonus_speed
            bonus_critical += item.bonus_critical
            bonus_armor += item.bonus_armor
        # LEVEL SCALING
        bonus_damage += (
            (self.level // LEVEL_TO_STAT_INCREASE)
            * self.base_damage
            * (DAMAGESCALING / 100)
        )
        bonus_hp += (
            (self.level // LEVEL_TO_STAT_INCREASE)
            * self.base_hp
            * (HPSCALING / 100)
        )
        bonus_speed += (
            (self.level // LEVEL_TO_STAT_INCREASE)
            * self.base_speed
            * (SPEEDSCALING / 100)
        )
        bonus_critical += (
            (self.level // LEVEL_TO_STAT_INCREASE)
            * self.base_critical
            * (CRITICALSCALING / 100)
        )

        # Define the starting STATS and variables (stars past AWAKEN_SCALING_CAP are kept but add nothing)
        stars = min(max(self.awaken, 0), AWAKEN_SCALING_CAP)
        self.current_hp = int(self.base_hp + bonus_hp * (1 + stars / 3))
        self.current_damage = int(
            self.base_damage + bonus_damage * (1 + stars / 3)
        )
        self.current_speed = int(self.base_speed + bonus_speed * (1 + stars / 3))
        self.current_critical = self.base_critical + bonus_critical * (
            1 + stars / 3
        )
        self.current_armor = int(self.base_armor + bonus_armor * (1 + stars / 3))
        
        #TYPE and qualities final multiplier
        
        # Base speed and crit are tiny (median 2 and 1), so SPEED and LUCK add flat points rather
        # than multiplying almost nothing. Each type also powers the specials that scale with its stat.
        self.crit_multiplier = CRITMULTIPLIER
        for type_,quality in zip(self.types,self.qualities):
            type_ = Types.from_string(type_)
            quality = Qualities.from_string(quality)
            if type_ == Types.ATTACK:
                self.current_damage *= quality.coef
            elif type_ == Types.BALANCE:
                self.current_armor *= (quality.coef ** 0.25)
                self.current_damage *= (quality.coef ** 0.25)
                self.current_speed += SPEED_TYPE_POINTS[quality.name] / 4
                self.current_critical += LUCK_TYPE_POINTS[quality.name] / 4
                self.crit_multiplier += LUCK_CRIT_DAMAGE[quality.name] / 4
            elif type_ == Types.DEFENSE:
                self.current_armor *= quality.coef ** 1.75  # armor has diminishing returns: a stronger curve keeps it level with ATTACK
            elif type_ == Types.HEALTH:
                self.current_hp *= quality.coef
            elif type_ == Types.SPEED:
                self.current_speed += SPEED_TYPE_POINTS[quality.name]
            elif type_ == Types.LUCK:
                self.current_critical += LUCK_TYPE_POINTS[quality.name]
                self.crit_multiplier += LUCK_CRIT_DAMAGE[quality.name]
        apply_chips(self, data.get("chips") or [])  # stand chips (app/game/chips.py); ranked fights strip them
        self.current_hp = int(self.current_hp)
        self.current_speed = int(round(self.current_speed))
        
        self.start_hp = self.current_hp
        self.start_damage = self.current_damage
        self.start_speed = self.current_speed
        self.start_critical = self.current_critical
        self.start_armor = self.current_armor
        self.effects: List[Effect] = []
        self.special_meter: int = 0
        self.turn: int = 0
        self.armor: int = 1

    def is_alive(self) -> bool:
        """Check if a character is alive

        Returns:
            bool: The  answer
        """
        if self.current_hp <= 0:
            self.current_hp = 0
        return self.current_hp > 0

    @property
    def terrain(self) -> Terrain:
        return getattr(self, "_active_terrain", Terrain.DEFAULT)

    def attack(self, ennemy_character: character, multiplier: float = 1, pierce: bool = False) -> dict:
        """Attack a character. pierce=True ignores the target's armor.

        Returns:
            dict: Default {"damage": 0, "critical": False, "crit": 0, "dodged": False}; crit counts the crits
        """
        atck = {"damage": 0, "critical": False, "crit": 0, "dodged": False}
        terrain = self.terrain
        multi = multiplier * TERRAIN_DAMAGE_MULT.get(terrain, 1)
        tier = crit_tier(self.current_critical)
        if tier:
            crit_mult = getattr(self, "crit_multiplier", CRITMULTIPLIER)  # fights pickled before LUCK crit damage
            multi *= 1 + (max(crit_mult, TERRAIN_CRIT_MULT.get(terrain, 0)) - 1) * tier
            atck["critical"] = True
            atck["crit"] = tier
            pierce = pierce or terrain in TERRAIN_CRIT_PIERCES
        multi *= slayer_mult(self, ennemy_character)
        if getattr(ennemy_character, "_ward", 0) and not getattr(self, "_bonded", False):
            multi *= 1 - ennemy_character._ward  # Over Heaven ward: only stands in a synergy hit at full strength
        # Armor: 100 is neutral, 0 doubles damage, 400 (the cap) takes 40%. Resonant strikes ignore a share of it.
        if not pierce:
            armor = min(max(ennemy_character.current_armor, 0), ARMOR_CAP) * (1 - getattr(self, "_armor_pierce", 0))
            multi *= 200 / (100 + armor)
        # A faster target may dodge: one percent per point of speed gap.
        if ennemy_character.current_speed > self.current_speed and terrain not in TERRAIN_NO_DODGE:
            dodge_chance = min(DODGE_CHANCE_CAP, (ennemy_character.current_speed - self.current_speed) // DODGENERF)
            if random.randint(0, 100) < dodge_chance:
                atck["dodged"] = True
                return atck
        damage = max(1, int(self.current_damage * multi)) if multi > 0 else 0
        ennemy_character.current_hp -= damage
        atck["damage"] = damage
        return atck

    def heal(self, amount: float) -> int:
        """Heal up to max health (start_hp). Returns what was actually restored."""
        if not self.is_alive() or amount <= 0:
            return 0
        amount *= TERRAIN_HEAL_MULT.get(self.terrain, 1) * getattr(self, "_heal_mult", 1) * getattr(self, "_heal_cut", 1)
        gained = int(min(amount, self.start_hp - self.current_hp))
        if gained <= 0:
            return 0
        self.current_hp += gained
        return gained

    def take(self, amount: float) -> int:
        """True damage: no armor, dodge or crit. Returns what was dealt."""
        dealt = int(max(0, min(amount, self.current_hp)))
        self.current_hp -= dealt
        return dealt

    def add_effect(self, effect: Effect) -> Effect:
        """Attach an effect. Stat effects change the stat right away and undo it when they expire."""
        effect.fresh = bool(getattr(self, "_my_turn", False))
        if effect.type == EffectType.STUN and getattr(self, "_stun_immune", False):
            effect.duration = 0  # cleaned up at its end of turn without ever counting
            return effect
        if effect.type in STAT_EFFECTS:
            attr, sign = STAT_EFFECTS[effect.type]
            if sign < 0:  # never take a stat below its floor, so the revert stays exact
                floor = 1 if attr == "current_damage" else 0
                effect.value = max(0, min(effect.value, getattr(self, attr) - floor))
            setattr(self, attr, getattr(self, attr) + sign * effect.value)
            effect.used = True
        self.effects.append(effect)
        return effect

    def grow(self, stat: str, pct: float) -> float:
        """Permanent self-buff of pct x the starting stat, capped at GROWTH_CAP in total per stat."""
        grown = self.__dict__.setdefault("_growth", {})
        base = getattr(self, f"start_{stat}")
        room = GROWTH_CAP * base - grown.get(stat, 0)
        add = max(0, min(base * pct, room))
        grown[stat] = grown.get(stat, 0) + add
        setattr(self, f"current_{stat}", getattr(self, f"current_{stat}") + add)
        return add

    def is_stunned(self) -> bool:
        """Stunned unless it was stunned on its previous turn (no stun-locks)."""
        if getattr(self, "_stun_guard", False):
            self.effects = [e for e in self.effects if e.type != EffectType.STUN]
            return False
        return EffectType.STUN in [e.type for e in self.effects]

    def end_turn(self) -> None:
        """End of this stand's own turn: damage over time, regen, durations and the special meter."""
        terrain = self.terrain
        for effect in self.effects:
            if effect.duration <= 0:
                continue
            if effect.type in DOT_EFFECTS:
                self.current_hp -= int(effect.value * TERRAIN_DOT_MULT.get(terrain, {}).get(effect.type, 1))
            elif effect.type == EffectType.REGENERATION:
                self.heal(effect.value)
            elif effect.type in STAT_EFFECTS and not effect.used:
                # legacy path: effects appended without add_effect apply here once
                attr, sign = STAT_EFFECTS[effect.type]
                setattr(self, attr, getattr(self, attr) + sign * effect.value)
                effect.used = True
            if effect.fresh:
                effect.fresh = False
            else:
                effect.duration -= 1
        if terrain in TERRAIN_REGEN:
            self.heal(self.start_hp * TERRAIN_REGEN[terrain])

        # Cleanup effects that have ended: undo exactly what each one applied.
        remaining_effects = []
        for effect in self.effects:
            if effect.duration > 0:
                remaining_effects.append(effect)
                continue
            if not effect.used:
                continue
            if effect.type in STAT_EFFECTS:
                attr, sign = STAT_EFFECTS[effect.type]
                setattr(self, attr, getattr(self, attr) - sign * effect.value)
        self.effects = remaining_effects

        # A stand that just sat out a stun shrugs off stuns on its next turn (set by the fight loop).
        self._stun_guard = self.__dict__.pop("_skipped", False)

        # Add to the special meter
        self.special_meter += 1
        self.turn += 1

        # Add to items' special meter
        for item in self.items:
            item.special_meter += 1

    def as_special(self) -> bool:
        return self.special_meter >= self.turn_for_ability

    def special(self, allies: List[character], ennemies: List[character]) -> tuple:
        """used for fight

        Args:
            allies (List[character]): list of allies
            ennemies (List[character]): list of ennemies

        Returns:
            tuple: payload,message
        """
        # reset the meter
        self.special_meter = 0
        special_id = SEALED_SPECIAL.get(self.id, self.id) if getattr(self, "sealed", False) else self.id
        special_func = specials.get(str(special_id), not_implemented)
        from app.game import characterabilities as abilities
        abilities.begin_special(self)  # its stat and type set how strong it is
        try:
            return special_func(self, allies, ennemies)
        finally:
            abilities.end_special()

    def to_dict(self) -> dict:
        """Update the data of the character

        Returns:
            dict: the data of the character
        """
        self.data["uuid"] = self.uuid
        self.data["xp"] = self.xp
        self.data["awaken"] = self.awaken
        self.data["trained"] = self.trained
        self.data["items"] = [s.to_dict() for s in self.items]
        self.data["types"] = self.types
        self.data["qualities"] = self.qualities
        if self.shiny:
            self.data["shiny"] = True
        else:
            self.data.pop("shiny", None)
        return self.data

    def reset(self) -> None:
        """call at the end of a fight"""
        self.data["xp"] = self.xp
        self.data["awaken"] = self.awaken
        self.data["items"] = [s.to_dict() for s in self.items]
        self.__init__(self.data)


def apply_chips(char, chips: list) -> None:
    """Add socketed stand chips to the stats: *_pct lines are shares of the stat, *_flat lines points."""
    for chip in chips:
        for stat, value in chip.get("stats", []):
            if stat == "damage_pct":
                char.current_damage *= 1 + value
            elif stat == "hp_pct":
                char.current_hp *= 1 + value
            elif stat == "armor_pct":
                char.current_armor *= 1 + value
            elif stat == "speed_flat":
                char.current_speed += value
            elif stat == "crit_flat":
                char.current_critical += value


def crit_tier(chance: float) -> int:
    """How many times a hit crits: 0 (normal), 1 (crit), 2 (double), 3+..."""
    whole, rest = divmod(max(0.0, chance), 100)
    return int(whole) + (random.random() * 100 < rest)


def slayer_mult(attacker, target) -> float:
    """Giant Slayer: a slayer hits higher-rarity stands harder and takes less from them."""
    from app.game.effects import RARITY_RANK
    gap = RARITY_RANK.get(getattr(target, "rarity", ""), 2) - RARITY_RANK.get(getattr(attacker, "rarity", ""), 2)
    steps = min(abs(gap), SLAYER_STEPS)
    if gap > 0 and getattr(attacker, "_slayer", False):
        return 1 + SLAYER_STEP * steps
    if gap < 0 and getattr(target, "_slayer", False):
        return 1 - SLAYER_GUARD * steps
    return 1


def character_from_dict(data: dict) -> Character:
    return Character(data)


def get_character_from_template(template: dict,types:list[str],qualities:list[str]) -> Character:
    data = {"id": template["id"], "uuid": str(uuid.uuid4()), "xp": 0, "awaken": 0,"types":types,"qualities":qualities ,"items": []}
    return Character(data)


class Types(enum.Enum):
    ATTACK = ("ATTACK", "⚔️", 1)
    DEFENSE = ("DEFENSE", "🛡️", 2)
    SPEED = ("SPEED", "💨", 3)
    LUCK = ("LUCK", "🍀", 4)
    BALANCE = ("BALANCE", "⚖️", 5)
    HEALTH = ("HEALTH", "❤️", 6)

    def __new__(cls, string, emoji, number):
        obj = object.__new__(cls)
        obj._value_ = string
        obj.emoji = emoji
        obj.number = number
        return obj

    @property
    def name(self):
        return self._value_

    @classmethod
    def from_string(cls, name):
        try:
            return cls[name]
        except KeyError:
            raise ValueError(f"No type found with name '{name}'")

class Qualities(enum.Enum):
    UNIVERSAL = ("UNIVERSAL", "💫", 1.4, "A")
    SUPREME = ("SUPREME", "✨", 1.3, "B")
    GREAT = ("GREAT", "⏫", 1.2, "C")
    GOOD = ("GOOD", "🔼", 1, "D")
    SUB_PAR = ("SUB_PAR", "🔽", 0.95, "E")
    BAD = ("BAD", "⏬", 0.9, "F")

    def __new__(cls, name, emoji, coef, rank):
        obj = object.__new__(cls)
        obj._value_ = name
        obj.emoji = emoji
        obj.coef = coef
        obj.rank = rank
        return obj

    @property
    def name(self):
        return self._value_

    @classmethod
    def from_string(cls, name):
        try:
            return cls[name]
        except KeyError:
            raise ValueError(f"No quality found with name '{name}'")

def get_type_from_string(typ:str):
    if typ == "ATTACK":
        return Types.ATTACK
    elif typ == "DEFENSE":
        return Types.DEFENSE
    elif typ == "SPEED":
        return Types.SPEED
    elif typ == "LUCK":
        return Types.LUCK
    elif typ == "BALANCE":
        return Types.BALANCE
    elif typ == "HEALTH":
        return Types.HEALTH
    else:
        raise ValueError(f"No quality found with name '{typ}'")

def get_qualities_from_string(quality:str):
    if quality == "UNIVERSAL":
        return Qualities.UNIVERSAL
    elif quality == "SUPREME":
        return Qualities.SUPREME
    elif quality == "GREAT":
        return Qualities.GREAT
    elif quality == "GOOD":
        return Qualities.GOOD
    elif quality == "SUB_PAR":
        return Qualities.SUB_PAR
    elif quality == "BAD":
        return Qualities.BAD
    else:
        raise ValueError(f"No quality found with name '{quality}'")


_NATURAL = {}


def natural_stats(char) -> dict:
    """The stand's stats with no items, types or effects: its level and awakening only."""
    key = (char.id, min(MAX_LEVEL, char.xp // STXPTOLEVEL), char.awaken)
    if key not in _NATURAL:
        bare = Character({"id": char.id, "xp": char.xp, "awaken": char.awaken, "items": [], "types": [],
                          "qualities": []})
        _NATURAL[key] = {"hp": bare.start_hp, "damage": bare.start_damage, "armor": bare.start_armor,
                         "speed": bare.start_speed, "critical": bare.start_critical}
    return _NATURAL[key]
