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
    multiplier = 30
    valid_stand = [i for i in ennemy_stand if i.is_alive()]
    if len(valid_stand) != 0:
        target = random.choice(valid_stand)
        target.current_hp -= multiplier
        message = f"｢{stand.name}｣'s Sheer heart attack explode on {target.name} for {multiplier} damage"
    message = f"Sheer heart attack schearch for ennemies"
    return message


def red_stone_of_aja(
    stand: "Stand", allied_stand: List["Stand"], ennemy_stand: List["Stand"]
) -> tuple:
    stand.current_hp += 100
    stand.current_speed += 20
    stand.current_damage += 50
    stand.current_critical += 50

    message = f"｢{stand.name}｣ becomes transcend"

    return message


def stone_mask(
    stand: "Stand", allied_stand: List["Stand"], ennemy_stand: List["Stand"]
) -> tuple:
    stand.current_hp += 30
    stand.current_damage += 30

    message = f"｢{stand.name}｣ becomes a vempire"
    return message


def lottery_ticket(
    stand: "Stand", allied_stand: List["Stand"], ennemy_stand: List["Stand"]
) -> tuple:
    message = "None"
    return message


def polpos_lighter(
    stand: "Stand", allied_stand: List["Stand"], ennemy_stand: List["Stand"]
) -> tuple:
    e_type = [e.type for e in stand.effects if not e.sender in allied_stand]
    if EffectType.POISON in e_type:
        index = e_type.index(EffectType.POISON)
        target = stand.effects[index].sender
        target.effects.append(Effect(EffectType.WEAKEN, 1, 0.95, stand))
        message = (
            f"｢{stand.name}｣ manifest ｢Black Sabbath｣ and {target.name} gets weakened"
        )
        return message

    message = "None"
    return message


def holy_corpse(
    stand: "Stand", allied_stand: List["Stand"], ennemy_stand: List["Stand"]
) -> tuple:
    # Heal all allies and boost their stats
    for ally in allied_stand:
        if ally.is_alive():
            ally.current_hp += 50
            ally.current_damage += 15
            ally.current_armor += 10
    message = f"｢{stand.name}｣ channels the Holy Corpse, blessing all allies with +50 HP, +15 DMG, +10 ARM"
    return message


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
}