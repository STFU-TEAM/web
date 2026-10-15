import random

from typing import TYPE_CHECKING, List

from app.game.effects import Effect, EffectType,NEGATIVE_EFFECTS

# A refined item's ability is stronger: Item.special sets this to 1 + REFINE_STEP x refine for the call (so a Stone
# Mask +5 heals and grows 50% more). Most of these items list a stat or two at most, so before this, refining them
# bought next to nothing.
_POWER = 1.0


def _p(x: float) -> float:
    return x * _POWER

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
    dealt = target.take(stand.current_damage * _p(0.4))
    return f"｢{stand.name}｣'s Sheer Heart Attack homes in on {target.name} and explodes for {dealt}!"


def red_stone_of_aja(
    stand: "Stand", allied_stand: List["Stand"], ennemy_stand: List["Stand"]
) -> tuple:
    healed = stand.heal(stand.start_hp * _p(0.15))
    stand.add_effect(Effect(EffectType.DAMAGEUP, 2, stand.start_damage * _p(0.25), stand))
    stand.add_effect(Effect(EffectType.CRITUP, 2, round(_p(20)), stand))
    return f"｢{stand.name}｣ is amplified by the Red Stone: heals {healed}, +{_p(25):.0f}% damage and +{_p(20):.0f} crit!"


def stone_mask(
    stand: "Stand", allied_stand: List["Stand"], ennemy_stand: List["Stand"]
) -> tuple:
    healed = stand.heal(stand.start_hp * _p(0.10))
    grown = stand.grow("damage", _p(0.10))
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
        poisoner.add_effect(Effect(EffectType.WEAKEN, 1, poisoner.current_damage * _p(0.15), stand))
        return f"｢{stand.name}｣ manifests ｢Black Sabbath｣ and {poisoner.name} gets weakened"

    message = "None"
    return message


def holy_corpse(
    stand: "Stand", allied_stand: List["Stand"], ennemy_stand: List["Stand"]
) -> tuple:
    healed = 0
    for ally in allied_stand:
        if ally.is_alive():
            healed += ally.heal(ally.start_hp * _p(0.08))
            ally.add_effect(Effect(EffectType.DAMAGEUP, 2, ally.start_damage * _p(0.10), stand))
            ally.add_effect(Effect(EffectType.ARMORUP, 2, ally.start_armor * _p(0.10), stand))
    return f"｢{stand.name}｣ channels the Holy Corpse: the team heals {healed}, +{_p(10):.0f}% damage and armor!"


def steel_ball(
    stand: "Stand", allied_stand: List["Stand"], ennemy_stand: List["Stand"]
) -> tuple:
    valid = [i for i in ennemy_stand if i.is_alive()]
    if not valid:
        return "None"
    focus = getattr(stand, "_focus", None)
    target = focus if focus in valid else random.choice(valid)
    dealt = target.take(stand.current_damage * _p(0.6))
    target.add_effect(Effect(EffectType.SLOW, 1, max(2, target.current_speed * _p(0.15)), stand))
    return f"｢{stand.name}｣ throws the Steel Ball: the Golden Spin hits {target.name} for {dealt} and slows it!"


def rokakaka_graft(
    stand: "Stand", allied_stand: List["Stand"], ennemy_stand: List["Stand"]
) -> tuple:
    healed = stand.heal(stand.start_hp * _p(0.08))
    if not healed:
        return "None"
    return f"｢{stand.name}｣'s Rokakaka graft takes root: heals {healed}!"


def ultimate_being_mask(
    stand: "Stand", allied_stand: List["Stand"], ennemy_stand: List["Stand"]
) -> tuple:
    healed = stand.heal(stand.start_hp * _p(0.10))
    stand.add_effect(Effect(EffectType.DAMAGEUP, 2, stand.start_damage * _p(0.20), stand))
    return f"｢{stand.name}｣ becomes the Ultimate Being: heals {healed} and +{_p(20):.0f}% damage!"


def _focus_or_random(stand, ennemy_stand):
    valid = [i for i in ennemy_stand if i.is_alive()]
    if not valid:
        return None
    focus = getattr(stand, "_focus", None)
    return focus if focus in valid else random.choice(valid)


def rokakaka_branch(
    stand: "Stand", allied_stand: List["Stand"], ennemy_stand: List["Stand"]
) -> tuple:
    # equivalent exchange: the deeper the holder's wounds, the harder it pays them back (revenge tanks)
    missing = stand.start_hp - stand.current_hp
    target = _focus_or_random(stand, ennemy_stand)
    if missing < 1 or target is None:
        return "None"
    dealt = target.take(missing * _p(0.15))
    return f"｢{stand.name}｣'s Rokakaka Branch makes an equivalent exchange: its wounds hit {target.name} for {dealt}!"


def darbys_chips(
    stand: "Stand", allied_stand: List["Stand"], ennemy_stand: List["Stand"]
) -> tuple:
    roll = random.choice((10, 20, 30, 40))
    bet = round(_p(roll))
    stand.add_effect(Effect(EffectType.CRITUP, 2, bet, stand))
    if roll == 40:
        return f"｢{stand.name}｣ calls D'Arby's bluff: jackpot, +{bet} crit for 2 turns!"
    return f"｢{stand.name}｣ bets D'Arby's chips: +{bet} crit for 2 turns."


def josephs_clackers(
    stand: "Stand", allied_stand: List["Stand"], ennemy_stand: List["Stand"]
) -> tuple:
    target = _focus_or_random(stand, ennemy_stand)
    if target is None:
        return "None"
    dealt = target.take(stand.current_damage * _p(0.3))
    return f"｢{stand.name}｣ swings a Clacker Volley at {target.name} for {dealt}!"


DETONATED = (EffectType.POISON, EffectType.BURN)


def bites_the_dust(
    stand: "Stand", allied_stand: List["Stand"], ennemy_stand: List["Stand"]
) -> tuple:
    # every poison and burn on the enemy team goes off at once: all their remaining ticks in one turn
    from app.game.character import POISON_MAX_HP
    from app.game.effects import TERRAIN_DOT_MULT
    total, hit = 0, 0
    for target in [i for i in ennemy_stand if i.is_alive()]:
        dots = [e for e in target.effects if e.type in DETONATED and e.duration > 0]
        if not dots:
            continue
        burst = 0
        for e in dots:
            tick = e.value + (POISON_MAX_HP * target.start_hp if e.type == EffectType.POISON else 0)
            burst += tick * TERRAIN_DOT_MULT.get(getattr(target, "terrain", None), {}).get(e.type, 1) * e.duration
        target.effects = [e for e in target.effects if e not in dots]
        total += target.take(_p(burst))
        hit += 1
    if not hit:
        return "None"
    return f"｢{stand.name}｣ presses the switch: BITES THE DUST! Every poison and burn detonates at once for {total} damage!"


# items whose ability does something in a fight (refining strengthens it; gear.refine_preview shows it)
ABILITY_ITEMS = {5, 6, 7, 16, 37, 41, 43, 45, 54, 55, 56, 57}

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
    "54": rokakaka_branch,
    "55": darbys_chips,
    "56": josephs_clackers,
    "57": bites_the_dust,
}