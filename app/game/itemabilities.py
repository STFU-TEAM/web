import random

from typing import TYPE_CHECKING, List

from app.game.effects import Effect, EffectType,NEGATIVE_EFFECTS

# It's for typehint
if TYPE_CHECKING:
    from app.game.character import Character


"""

name your fonction to the character

def item_special_boiler_plate(character:"character",allied_character:List["character"],ennemy_characterd:List["character"])->tuple:
    #Whatever your code does to the lists above
    #Payload Contain behavior change to the game
    #message is what should be printed to the embed
    return message


"""

def dio_Knife(
    stand: "Stand", allied_stand: List["Stand"], ennemy_stand: List["Stand"]
) -> tuple:
    message = "None"
    return message


def stand_arrows(
    stand: "Stand", allied_stand: List["Stand"], ennemy_stand: List["Stand"]
) -> tuple:
    message = "None"
    return message


def requiem_arrow(
    stand: "Stand", allied_stand: List["Stand"], ennemy_stand: List["Stand"]
) -> tuple:
    message = "None"
    return message


def giornos_ladybug(
    stand: "Stand", allied_stand: List["Stand"], ennemy_stand: List["Stand"]
) -> tuple:
    message = "None"
    return message


def sheer_heart_attack(
    stand: "Stand", allied_stand: List["Stand"], ennemy_stand: List["Stand"]
) -> tuple:
    valid_stand = [i for i in ennemy_stand if i.is_alive()]
    if not valid_stand:
        return "None"
    target = random.choice(valid_stand)
    dealt = target.take(stand.current_damage * 0.4)
    return f"｢{stand.name}｣'s Sheer Heart Attack homes in on {target.name} and explodes for {dealt}!"


def red_stone_of_aja(
    stand: "Stand", allied_stand: List["Stand"], ennemy_stand: List["Stand"]
) -> tuple:
    healed = stand.heal(stand.start_hp * 0.15)
    stand.add_effect(Effect(EffectType.DAMAGEUP, 2, stand.start_damage * 0.25, stand))
    stand.add_effect(Effect(EffectType.CRITUP, 2, 20, stand))
    return f"｢{stand.name}｣ is amplified by the Red Stone: heals {healed}, +25% damage and +20 crit!"


def stone_mask(
    stand: "Stand", allied_stand: List["Stand"], ennemy_stand: List["Stand"]
) -> tuple:
    healed = stand.heal(stand.start_hp * 0.10)
    grown = stand.grow("damage", 0.10)
    return f"｢{stand.name}｣ becomes a vampire: heals {healed}, +{round(grown)} damage!"


def lottery_ticket(
    stand: "Stand", allied_stand: List["Stand"], ennemy_stand: List["Stand"]
) -> tuple:
    message = "None"
    return message


def polpos_lighter(
    stand: "Stand", allied_stand: List["Stand"], ennemy_stand: List["Stand"]
) -> tuple:
    poisoner = next((e.sender for e in stand.effects
                     if e.type == EffectType.POISON and e.sender is not None and e.sender not in allied_stand), None)
    if poisoner is not None and poisoner.is_alive():
        poisoner.add_effect(Effect(EffectType.WEAKEN, 1, poisoner.current_damage * 0.15, stand))
        return f"｢{stand.name}｣ manifests ｢Black Sabbath｣ and {poisoner.name} gets weakened"

    message = "None"
    return message


def holy_corpse(
    stand: "Stand", allied_stand: List["Stand"], ennemy_stand: List["Stand"]
) -> tuple:
    healed = 0
    for ally in allied_stand:
        if ally.is_alive():
            healed += ally.heal(ally.start_hp * 0.08)
            ally.add_effect(Effect(EffectType.DAMAGEUP, 2, ally.start_damage * 0.10, stand))
            ally.add_effect(Effect(EffectType.ARMORUP, 2, ally.start_armor * 0.10, stand))
    return f"｢{stand.name}｣ channels the Holy Corpse: the team heals {healed}, +10% damage and armor!"


def steel_ball(
    stand: "Stand", allied_stand: List["Stand"], ennemy_stand: List["Stand"]
) -> tuple:
    valid = [i for i in ennemy_stand if i.is_alive()]
    if not valid:
        return "None"
    focus = getattr(stand, "_focus", None)
    target = focus if focus in valid else random.choice(valid)
    dealt = target.take(stand.current_damage * 0.6)
    target.add_effect(Effect(EffectType.SLOW, 1, max(2, target.current_speed * 0.15), stand))
    return f"｢{stand.name}｣ throws the Steel Ball: the Golden Spin hits {target.name} for {dealt} and slows it!"


def rokakaka_graft(
    stand: "Stand", allied_stand: List["Stand"], ennemy_stand: List["Stand"]
) -> tuple:
    healed = stand.heal(stand.start_hp * 0.12)
    if not healed:
        return "None"
    return f"｢{stand.name}｣'s Rokakaka graft takes root: heals {healed}!"


def ultimate_being_mask(
    stand: "Stand", allied_stand: List["Stand"], ennemy_stand: List["Stand"]
) -> tuple:
    healed = stand.heal(stand.start_hp * 0.10)
    stand.add_effect(Effect(EffectType.DAMAGEUP, 2, stand.start_damage * 0.20, stand))
    return f"｢{stand.name}｣ becomes the Ultimate Being: heals {healed} and +20% damage!"


item_specials = {
    "1": dio_Knife,
    "2": stand_arrows,
    "3": requiem_arrow,
    "4": giornos_ladybug,
    "5": sheer_heart_attack,
    "6": red_stone_of_aja,
    "7": stone_mask,
    "15": lottery_ticket,
    "16": polpos_lighter,
    "37": holy_corpse,
    "41": steel_ball,
    "43": rokakaka_graft,
    "45": ultimate_being_mask,
}