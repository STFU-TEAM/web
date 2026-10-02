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
CRIT_CHANCE_CAP = 75
DODGENERF = 1
DODGE_CHANCE_CAP = 25
ARMOR_CAP = 400  # damage taken never drops below 200 / (100 + 400) = 40%
GROWTH_CAP = 1.0
TAUNT_HP = 0  # taunt already draws every basic attack; keep the extra bulk modest
TAUNT_ARMOR = 20  # permanent self-buffs stop at +100% of the starting stat
STXPTOLEVEL = 100
MAX_LEVEL = 100
LEVEL_TO_STAT_INCREASE = 1

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
        self.special_description: str = character_file[self.id-1]["special_description"]
        self.special_url:str = character_file[self.id-1]["special_url"]
        self.taunt: bool = character_file[self.id-1]["taunt"]
        self.items: List[Item] = [item_from_dict(s) for s in data.get("items", [])]
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

        # Define the starting STATS and variables
        self.current_hp = int(self.base_hp + bonus_hp * (1 + self.awaken / 3))
        self.current_damage = int(
            self.base_damage + bonus_damage * (1 + self.awaken / 3)
        )
        self.current_speed = int(self.base_speed + bonus_speed * (1 + self.awaken / 3))
        self.current_critical = self.base_critical + bonus_critical * (
            1 + self.awaken / 3
        )
        self.current_armor = int(self.base_armor + bonus_armor * (1 + self.awaken / 3))
        
        #TYPE and qualities final multiplier
        
        for type_,quality in zip(self.types,self.qualities):
            type_ = Types.from_string(type_)
            quality = Qualities.from_string(quality)
            if type_ == Types.ATTACK:
                self.current_damage *= quality.coef
            elif type_ == Types.BALANCE:
                self.current_armor *= (quality.coef ** 0.25)
                self.current_damage *= (quality.coef ** 0.25)
                self.current_speed *= (quality.coef ** 0.25)
                self.current_critical *= (quality.coef ** 0.25)
            elif type_ == Types.DEFENSE:
                self.current_armor *= quality.coef
            elif type_ == Types.SPEED:
                self.current_speed *= quality.coef
            elif type_ == Types.LUCK:
                self.current_critical *= quality.coef
        
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
            dict: Default {"damage": 0, "critical": False, "dodged": False}
        """
        atck = {"damage": 0, "critical": False, "dodged": False}
        terrain = self.terrain
        multi = multiplier * TERRAIN_DAMAGE_MULT.get(terrain, 1)
        if min(self.current_critical, CRIT_CHANCE_CAP) >= random.randint(0, 100):
            multi *= TERRAIN_CRIT_MULT.get(terrain, CRITMULTIPLIER)
            atck["critical"] = True
            pierce = pierce or terrain in TERRAIN_CRIT_PIERCES
        # Armor: 100 is neutral, 0 doubles damage, 400 (the cap) takes 40%.
        if not pierce:
            armor = min(max(ennemy_character.current_armor, 0), ARMOR_CAP)
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
        amount *= TERRAIN_HEAL_MULT.get(self.terrain, 1) * getattr(self, "_heal_mult", 1)
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
            elif effect.type == EffectType.HEALTHBOOST and not effect.used:
                self.current_hp += effect.value
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
            elif effect.type == EffectType.HEALTHBOOST:
                self.current_hp = max(self.current_hp - effect.value, 1)
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
        special_func = specials.get(str(self.id), not_implemented)
        return special_func(self, allies, ennemies)

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
        return self.data

    def reset(self) -> None:
        """call at the end of a fight"""
        self.data["xp"] = self.xp
        self.data["awaken"] = self.awaken
        self.data["items"] = [s.to_dict() for s in self.items]
        self.__init__(self.data)


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