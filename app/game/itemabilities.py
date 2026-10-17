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
    from app.game.characterabilities import _cleanse
    healed = 0
    for ally in allied_stand:
        if ally.is_alive():
            _cleanse(ally)  # misfortune is sent elsewhere
            healed += ally.heal(ally.start_hp * _p(0.10))
            ally.add_effect(Effect(EffectType.DAMAGEUP, 2, ally.start_damage * _p(0.15), stand))
            ally.add_effect(Effect(EffectType.ARMORUP, 2, ally.start_armor * _p(0.15), stand))
    return (f"｢{stand.name}｣ channels the Holy Corpse: misfortune is sent elsewhere! The team sheds every debuff, "
            f"heals {healed} and gains +{_p(15):.0f}% damage and armor!")


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
    from app.game.character import dot_tick
    total, hit = 0, 0
    for target in [i for i in ennemy_stand if i.is_alive()]:
        dots = [e for e in target.effects if e.type in DETONATED and e.duration > 0]
        if not dots:
            continue
        burst = 0
        for e in dots:
            burst += dot_tick(target, e) * e.duration
        target.effects = [e for e in target.effects if e not in dots]
        total += target.take(_p(burst))
        hit += 1
    if not hit:
        return "None"
    return f"｢{stand.name}｣ presses the switch: BITES THE DUST! Every poison and burn detonates at once for {total} damage!"


# ── The Passione / bodyguard gear (58-69). Actives below; the passives run from the fight loop (on_hit, cheat_death).

def abbacchios_badge(
    stand: "Stand", allied_stand: List["Stand"], ennemy_stand: List["Stand"]
) -> tuple:
    for ally in [a for a in allied_stand if a.is_alive()]:
        ally.add_effect(Effect(EffectType.ARMORUP, 2, max(1, ally.start_armor * _p(0.20)), stand))
    return f"｢{stand.name}｣ flashes Abbacchio's badge: the whole team gains +{_p(20):.0f}% armor for 2 turns!"


def cioccolatas_spores(
    stand: "Stand", allied_stand: List["Stand"], ennemy_stand: List["Stand"]
) -> tuple:
    from app.game.characterabilities import POISON_MULT
    target = _focus_or_random(stand, ennemy_stand)
    if target is None:
        return "None"
    target.add_effect(Effect(EffectType.POISON, 3, max(1, int(stand.current_damage * _p(0.2) * POISON_MULT)), stand))
    return f"｢{stand.name}｣ releases Green Day's spores: {target.name} is poisoned for 3 turns!"


def trishs_lipstick(
    stand: "Stand", allied_stand: List["Stand"], ennemy_stand: List["Stand"]
) -> tuple:
    hurt = [a for a in allied_stand if a.is_alive() and a.current_hp < a.start_hp]
    if not hurt:
        return "None"
    ally = min(hurt, key=lambda a: a.current_hp / max(1, a.start_hp))
    healed = ally.heal(ally.start_hp * _p(0.08))
    if not healed:
        return "None"
    return f"｢{stand.name}｣'s Spice Girl softens the blows: {ally.name} heals {healed}!"


def hot_pants_spray(
    stand: "Stand", allied_stand: List["Stand"], ennemy_stand: List["Stand"]
) -> tuple:
    from app.game.characterabilities import _cleanse
    sick = [a for a in allied_stand if a.is_alive() and any(e.type in NEGATIVE_EFFECTS for e in a.effects)]
    if not sick:
        return "None"
    ally = max(sick, key=lambda a: sum(e.type in NEGATIVE_EFFECTS for e in a.effects))
    _cleanse(ally)
    return f"｢{stand.name}｣ sprays Cream Starter: {ally.name} is patched up, every debuff gone!"


def naranicas_toy_plane(
    stand: "Stand", allied_stand: List["Stand"], ennemy_stand: List["Stand"]
) -> tuple:
    valid = [e for e in ennemy_stand if e.is_alive()]
    if not valid:
        return "None"
    target = min(valid, key=lambda e: e.current_hp / max(1, e.start_hp))
    dealt = target.take(stand.current_damage * _p(0.4))
    return f"｢{stand.name}｣'s toy plane spots the weakest breath: Aerosmith strafes {target.name} for {dealt}!"


def rohans_pen(
    stand: "Stand", allied_stand: List["Stand"], ennemy_stand: List["Stand"]
) -> tuple:
    charging = [e for e in ennemy_stand if e.is_alive() and e.special_meter > 0]
    if not charging:
        return "None"
    target = max(charging, key=lambda e: e.special_meter / max(1, e.turn_for_ability))
    target.special_meter -= 1
    return f"｢{stand.name}｣ writes into {target.name}'s book: “I can't use my special yet.” It loses a turn of charge!"


def enyas_fog_lantern(
    stand: "Stand", allied_stand: List["Stand"], ennemy_stand: List["Stand"]
) -> tuple:
    valid = [e for e in ennemy_stand if e.is_alive()]
    if not valid:
        return "None"
    for e in valid:
        e.add_effect(Effect(EffectType.WEAKEN, 2, e.current_damage * _p(0.15), stand))
    return f"｢{stand.name}｣ lights Enya's lantern: Justice's fog weakens every enemy by {_p(15):.0f}% for 2 turns!"


COMB, SLIME, ANKH, GOGGLES, CAPSULE = 58, 59, 60, 63, 69
COMB_STACKS = 5


def _held(stand, item_id):
    """The power of the copy of item_id the stand holds (refining strengthens it), or 0."""
    from app.game.items import REFINE_STEP
    held = [i for i in getattr(stand, "items", []) if i.id == item_id]
    return max((1 + REFINE_STEP * i.refine for i in held), default=0)


def on_hit(attacker, target, data) -> List[str]:
    """After a basic attack lands: the passives of the attacker's and the target's gear. Returns log lines."""
    lines = []
    dealt = data.get("damage", 0)
    if not dealt:
        return lines
    power = _held(target, COMB)
    if power and target.is_alive() and target.__dict__.get("_comb", 0) < COMB_STACKS:
        target._comb = target.__dict__.get("_comb", 0) + 1
        target.current_damage += target.start_damage * 0.06 * power
        lines.append(f"💈 What did you say about {target.name}'s hair?! +{6 * power:.0f}% damage ({target._comb}/{COMB_STACKS}).")
    power = _held(target, SLIME)
    if power and attacker.is_alive():
        back = attacker.take(dealt * 0.15 * power)
        if back:
            lines.append(f"🟡 Yellow Temperance sticks to {attacker.name}: {back} damage comes back.")
    power = _held(attacker, GOGGLES)
    if power and target.is_alive():
        from app.game.effects import Terrain
        share = 0.10 * power * (2 if attacker.terrain == Terrain.FROZEN else 1)
        target.add_effect(Effect(EffectType.SLOW, 1, max(1, target.current_speed * share), attacker))
    power = _held(attacker, CAPSULE)
    if power:
        from app.game.characterabilities import POISON_MULT
        roll = random.random()
        tick = max(1, int(attacker.current_damage * 0.25 * POISON_MULT))
        if roll < 0.10:  # the virus doesn't care whose side it's on
            attacker.add_effect(Effect(EffectType.POISON, 2, tick, attacker))
            lines.append(f"💊 Purple Haze's capsule breaks the wrong way: {attacker.name} is poisoned!")
        elif roll < 0.10 + 0.30 * min(power, 1.5) and target.is_alive():
            target.add_effect(Effect(EffectType.POISON, 2, int(tick * power), attacker))
            lines.append(f"💊 Purple Haze's virus gets into {target.name}: poisoned for 2 turns!")
    return lines


NEW_ROKAKAKA, EXCHANGE_AT, EXCHANGE_CAP = 76, 0.30, 0.20


def equivalent_exchange(stand, enemies) -> str:
    """The New Rokakaka: once a fight, when its holder drops under EXCHANGE_AT of its health, it trades health shares
    with the enemy that has the most left."""
    power = _held(stand, NEW_ROKAKAKA)  # refining raises the trigger: 30% at +0, 45% at +5
    if not stand.is_alive() or stand.__dict__.get("_exchanged") or not power:
        return ""
    mine = stand.current_hp / max(1, stand.start_hp)
    if mine >= EXCHANGE_AT * power:
        return ""
    foes = [e for e in enemies if e.is_alive()]
    if not foes:
        return ""
    other = max(foes, key=lambda e: e.current_hp / max(1, e.start_hp))
    theirs = other.current_hp / max(1, other.start_hp)
    if theirs <= mine:
        return ""
    from app.game.character import share_hp
    stand._exchanged = True
    # the holder's side is a heal (heal cuts and heal fatigue apply); the enemy's loss is capped at EXCHANGE_CAP of its
    # health share, so a boss or the raid's damage sponge can't be cut down to a quarter in one go
    healed = stand.heal(stand.start_hp * (theirs - mine))
    lost = other.take(min(other.start_hp * (theirs - mine), share_hp(other) * EXCHANGE_CAP))
    other.current_hp = max(1, other.current_hp)
    return (f"🌱 Equivalent Exchange! The New Rokakaka trades {stand.name}'s wounds for {other.name}'s health: "
            f"+{healed} for {stand.name}, -{lost} for {other.name}.")


def cheat_death(stand, enemies) -> str:
    """Avdol's Ankh: once a fight its holder survives the blow that would fell it, and the enemy team burns."""
    power = _held(stand, ANKH)
    if not power or stand.__dict__.get("_ankh_used"):
        return ""
    stand._ankh_used = True
    stand.current_hp = 1
    for e in [e for e in enemies if e.is_alive()]:
        e.add_effect(Effect(EffectType.BURN, 2, max(1, int(stand.current_damage * 0.3 * power)), stand))
    return f"☥ Avdol's Ankh flares! {stand.name} hangs on at 1 health, and a Crossfire Hurricane sets every enemy ablaze!"


# items whose ability does something in a fight (refining strengthens it; gear.refine_preview shows it)
ABILITY_ITEMS = {5, 6, 7, 16, 37, 41, 43, 45, 54, 55, 56, 57, 76} | set(range(58, 70))

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
    "61": abbacchios_badge,
    "62": cioccolatas_spores,
    "64": trishs_lipstick,
    "65": hot_pants_spray,
    "66": naranicas_toy_plane,
    "67": rohans_pen,
    "68": enyas_fog_lantern,
}