import random


from typing import TYPE_CHECKING, List


from app.game.effects import Effect, EffectType, NEGATIVE_EFFECTS, Terrain

# It's for typehint
if TYPE_CHECKING:
    from app.game.character import Character


def get_payload():
    return {
        "gold_experience_requiem": False,
        "tusk_act_4": False,
        "king_crimson": False,
        "is_a_special": True,
    }


def _terrain(character) -> Terrain:
    """Get the active terrain from the character (set by fight_loop)."""
    return getattr(character, "_active_terrain", Terrain.DEFAULT)


def _ally_ids(allied_characters: list) -> set:
    """Return the set of character IDs on the team (alive or dead)."""
    return {c.id for c in allied_characters}


# ── Synergy definitions ────────────────────────────────────────────────
# Each entry maps a frozenset of required ally IDs to a synergy name.
# A character triggers synergy if the required allies are present on the team.
SYNERGIES = {
    # Stardust Crusaders — any 2+ of {Star Plat, Mag Red, Hierophant, Hermit, Fool, Chariot}
    "crusaders": {1, 2, 3, 4, 5, 6},
    # Kira combo — Killer Queen + Stray Cat
    "kira": {49, 54},
    # La Squadra — any 2+ of the assassination team
    "squadra": {63, 66, 68, 72, 73, 74, 76, 77},
    # Passione (Bucciarati gang)
    "passione": {59, 60, 64, 67, 69, 79},
    # Morioh Warriors
    "morioh": {32, 34, 37, 42, 45, 50},
    # Pucci Evolution — Whitesnake + C-Moon + MiH
    "pucci": {107, 108, 109},
    # Tusk Evolution
    "tusk": {111, 112, 113, 114},
    # Clash + Talking Head duo
    "clash_talking": {76, 77},
}


def _has_synergy(character_id: int, allied_characters: list, synergy_name: str) -> bool:
    """Check if character_id has at least one OTHER ally from the named synergy group."""
    group = SYNERGIES.get(synergy_name, set())
    if character_id not in group:
        return False
    ids = _ally_ids(allied_characters)
    # Need at least one OTHER member present
    return len(group & ids) >= 2


"""

name your fonction to the character

def special_boiler_plate(character:"Character",allied_characters:List["Character"],enemy_characters:List["Character"])->tuple:
    payload = get_payload()
    #Whatever your code does to the lists above
    #Payload Contain behavior change to the game
    #message is what should be printed to the embed
    return payload,message

their is a load of exemple bellow
AOE attack : the_world
AOE effect : weather_report
self buff  : made_in_heaven

"""


def the_world_over_heaven(
    character: "Character", allied_characters: List["Character"], enemy_characters: List["Character"]
) -> tuple:
    payload = get_payload()
    damage = 0
    for ennemy in enemy_characters:
        damage += character.attack(ennemy, multiplier=1000)["damage"]
    message = f"｢{character.name}｣! damaged everyone for {int(damage)}!"
    return payload, message


def star_platinum(
    character: "Character", allied_characters: List["Character"], enemy_characters: List["Character"]
) -> tuple:
    payload = get_payload()
    synergy = _has_synergy(character.id, allied_characters, "crusaders")
    multiplier = random.randint(1, 4)
    if synergy:
        multiplier += 1  # Crusaders synergy: guaranteed extra hit
    valid_characters = [i for i in enemy_characters if i.is_alive()]
    if valid_characters:
        target = random.choice(valid_characters)
        character.attack(target, multiplier=multiplier)
        msg = f"｢{character.name}｣ punches {target.name} {multiplier} times for {int(character.current_damage*multiplier)} damage!"
        if synergy:
            msg += " ⭐ Crusaders synergy!"
        message = msg
    else:
        message = f"｢{character.name}｣ punches multiple times!"
    return payload, message


def silver_chariot(
    character: "Character", allied_characters: List["Character"], enemy_characters: List["Character"]
) -> tuple:
    payload = get_payload()
    synergy = _has_synergy(character.id, allied_characters, "crusaders")
    if synergy:
        # Crusaders synergy: shed armor without the penalty
        character.current_speed += 15
        message = f"｢{character.name}｣ sheds its armor! +15 speed, no armor loss! ⭐ Crusaders synergy!"
    else:
        character.current_speed += 10
        character.current_armor = max(1, int(character.current_armor * 0.75))
        message = f"｢{character.name}｣ gains speed but loses resistance."
    return payload, message


def the_world(
    character: "Character", allied_characters: List["Character"], enemy_characters: List["Character"]
) -> tuple:
    payload = get_payload()
    multiplier = 0.6
    damage = 0
    for ennemy in enemy_characters:
        damage += character.attack(ennemy, multiplier=multiplier)["damage"]
    message = f"｢{character.name}｣ STOPS TIME! and damages everyone for {int(damage)}"
    return payload, message


def cream(
    character: "Character", allied_characters: List["Character"], enemy_characters: List["Character"]
) -> tuple:
    payload = get_payload()
    character.current_speed += 5
    character.current_damage += 5
    character.effects.append(Effect(EffectType.STUN, 1, 0, character))
    message = f"｢{character.name}｣ gets faster"
    return payload, message


def star_platinum_the_world(
    character: "Character", allied_characters: List["Character"], enemy_characters: List["Character"]
) -> tuple:
    payload = get_payload()
    multiplier = 0.6
    damage = 0
    for ennemy in enemy_characters:
        damage += character.attack(ennemy, multiplier=multiplier)["damage"]
    message = f"｢{character.name}｣ STOPS TIME! and damages everyone for {int(damage)}"
    return payload, message


def crazy_diamond(
    character: "Character", allied_characters: List["Character"], enemy_characters: List["Character"]
) -> tuple:
    payload = get_payload()
    valid_characters = [i for i in allied_characters if i.is_alive() and i != character]
    if len(valid_characters) != 0:
        ally: "Character" = random.choice(valid_characters)
        dif_damage = abs(character.start_hp - character.current_hp)
        heal = min(ally.start_hp, ally.current_hp + (dif_damage // 2))
        ally.current_hp = heal
        message = f"｢{character.name}｣ heals {ally.name}"
    else:
        message = f"｢{character.name}｣ enraged!"
    return payload, message


def the_hand(
    character: "Character", allied_characters: List["Character"], enemy_characters: List["Character"]
) -> tuple:
    multiplier = random.choice((0.75, 1, 1.5, 2.5))
    payload = get_payload()
    valid_characters = [i for i in enemy_characters if i.is_alive()]
    message = f"｢{character.name}｣ !"
    if len(valid_characters) != 0:
        target: "Character" = random.choice(valid_characters)
        damage = character.attack(target, multiplier=multiplier)
        message = f"｢{character.name}｣ throws out random items and deals {damage} damage"
    return payload, message


def heavens_door(
    character: "Character", allied_characters: List["Character"], enemy_characters: List["Character"]
) -> tuple:
    payload = get_payload()
    multiplicator = 2
    valid_characters = [i for i in enemy_characters if i.is_alive()]
    if len(valid_characters) != 0:
        target: "Character" = random.choice(valid_characters)
        target.effects.append(Effect(EffectType.STUN, multiplicator, 0, character))
        message = f"｢{character.name}｣ stuns {target.name} for {multiplicator} rounds!"
    else:
        message = f"｢{character.name}｣!"
    return payload, message


def killer_queen(
    character: "Character", allied_characters: List["Character"], enemy_characters: List["Character"]
) -> tuple:
    payload = get_payload()
    synergy = _has_synergy(character.id, allied_characters, "kira")
    valid_characters = [i for i in enemy_characters if i.is_alive()]
    if not valid_characters:
        message = f"｢{character.name}｣!"
        return payload, message
    if synergy:
        # Kira synergy: Stray Cat's air bubble + bomb = homing explosive on 2 targets
        targets = random.sample(valid_characters, min(2, len(valid_characters)))
        for target in targets:
            target.effects.append(
                Effect(EffectType.BURN, 1, 2.0 * character.current_damage, character)
            )
        names = " and ".join(t.name for t in targets)
        message = f"｢{character.name}｣ plants air bubble bombs on {names}! 💣🐈 Kira synergy!"
    else:
        target = random.choice(valid_characters)
        target.effects.append(
            Effect(EffectType.BURN, 1, 1.5 * character.current_damage, character)
        )
        message = f"｢{character.name}｣ places a bomb on {target.name} for {int(1.5*character.current_damage)} damage!"
    return payload, message


def echoes_act_3(
    character: "Character", allied_characters: List["Character"], enemy_characters: List["Character"]
) -> tuple:
    payload = get_payload()
    multiplicator = 2
    valid_characters = [i for i in enemy_characters if i.is_alive()]
    if len(valid_characters) != 0:
        target: "Character" = random.choice(valid_characters)
        target.effects.append(Effect(EffectType.STUN, multiplicator, 0, character))
        message = f"｢{character.name}｣ stuns {target.name} for {multiplicator} rounds and slow everyone else"
        for st in valid_characters:
            if st != target:
                st.effects.append(Effect(EffectType.SLOW, 2, 10, character))
    else:
        message = f"｢{character.name}｣!"
    return payload, message


def dummy(
    character: "Character", allied_characters: List["Character"], enemy_characters: List["Character"]
) -> tuple:
    payload = get_payload()
    character.current_hp = character.start_hp
    message = f"｢{character.name}｣ restores all of its health to full!"
    return payload, message


def killer_queen_bite_the_dust(
    character: "Character", allied_characters: List["Character"], enemy_characters: List["Character"]
) -> tuple:
    payload = get_payload()
    heal = (character.start_hp - character.current_hp) // 3
    character.current_hp += heal
    character.current_hp = max(0, min(character.current_hp, character.start_hp))
    message = f"｢{character.name}｣ resets the timeline! and heals for {heal}"
    return payload, message


def gold_experience(
    character: "Character", allied_characters: List["Character"], enemy_characters: List["Character"]
) -> tuple:
    payload = get_payload()
    synergy = _has_synergy(character.id, allied_characters, "passione")
    heal_amount = 50 if synergy else 30
    for ally in allied_characters:
        if ally.current_hp < ally.start_hp:
            ally.current_hp = min(ally.start_hp, ally.current_hp + heal_amount)
    message = f"｢{character.name}｣ heals all allies for {heal_amount}!"
    if synergy:
        # Passione: also grant a small speed buff to the team
        for ally in [a for a in allied_characters if a.is_alive()]:
            ally.current_speed += 3
        message += " 🐞 Passione synergy! +3 speed to all!"
    return payload, message


def sticky_finger(
    character: "Character", allied_characters: List["Character"], enemy_characters: List["Character"]
) -> tuple:
    payload = get_payload()
    synergy = _has_synergy(character.id, allied_characters, "passione")
    if synergy:
        # Passione: Ariari combo — crit + speed + a zipper strike
        character.current_critical += 7
        character.current_speed += 5
        valid = [e for e in enemy_characters if e.is_alive()]
        if valid:
            target = random.choice(valid)
            dmg = character.attack(target, multiplier=0.5)["damage"]
            message = f"｢{character.name}｣ ARI ARI ARI! +7 crit, +5 speed, {dmg} damage to {target.name}! 🐞 Passione synergy!"
        else:
            message = f"｢{character.name}｣ becomes razor-sharp! +7 crit, +5 speed! 🐞 Passione synergy!"
    else:
        character.current_critical += 5
        message = f"｢{character.name}｣ becomes more precise. +5 crit!"
    return payload, message


def purple_haze(
    character: "Character", allied_characters: List["Character"], enemy_characters: List["Character"]
) -> tuple:
    multiplier = 0.5
    payload = get_payload()
    for s in allied_characters + enemy_characters:
        s.effects.append(
            Effect(EffectType.POISON, 3, character.current_damage * multiplier, character)
        )
    message = f"｢{character.name}｣ poisons everyone for {character.current_damage*multiplier}!"
    return payload, message


def king_crimson(
    character: "Character", allied_characters: List["Character"], enemy_characters: List["Character"]
) -> tuple:
    payload = get_payload()
    payload["king_crimson"] = True
    message = f"｢{character.name}｣ has already..."
    return payload, message


def notorious_big(
    character: "Character", allied_characters: List["Character"], enemy_characters: List["Character"]
) -> tuple:
    multiplier = 0.1
    payload = get_payload()
    alive_allies = [i for i in allied_characters if i.is_alive() and i != character]
    if len(alive_allies) != 0:
        character.effects.append(
            Effect(EffectType.REGENERATION, 1, character.current_hp * multiplier, character)
        )
    message = f"｢{character.name}｣ Regenerates itself!"
    return payload, message


def metallica(
    character: "Character", allied_characters: List["Character"], enemy_characters: List["Character"]
) -> tuple:
    multiplier = 0.5
    payload = get_payload()
    for ennemy in enemy_characters:
        for effect in ennemy.effects:
            if effect == EffectType.REGENERATION:
                effect.value *= multiplier
        ennemy.effects.append(
            Effect(EffectType.POISON, 2, character.current_damage * 0.1, character)
        )
    message = f"｢{character.name}｣ infects their blood stream!"
    return payload, message


def green_day(
    character: "Character", allied_characters: List["Character"], enemy_characters: List["Character"]
) -> tuple:
    multiplier = 0.90
    payload = get_payload()
    for ennemy in enemy_characters:
        ennemy.effects.append(Effect(EffectType.WEAKEN, 3, multiplier, character))
    message = f"｢{character.name}｣ weakens all enemies!"
    return payload, message


def chariot_requiem(
    character: "Character", allied_characters: List["Character"], enemy_characters: List["Character"]
) -> tuple:
    payload = get_payload()
    valid_characters = [i for i in enemy_characters if i.is_alive()]
    if len(valid_characters) != 0:
        target: "Character" = random.choice(valid_characters)
        if target.id != character.id:
            try:
                return specials[f"{target.id}"](character, allied_characters, enemy_characters)
            except:
                character.current_damage += 10
    character.current_damage += 5
    message = f"｢{character.name}｣'s soul searches for the arrow..."
    return payload, message


def gold_experience_requiem(
    character: "Character", allied_characters: List["Character"], enemy_characters: List["Character"]
) -> tuple:
    payload = get_payload()
    payload["GER"] = True
    valid_characters = [i for i in enemy_characters if i.is_alive()]
    message = f"｢{character.name}｣ You will never reach the truth, Return to Zero!"
    # reset their scaling
    for ennemy in enemy_characters:
        ennemy: "Character" = character
        ennemy.current_hp = min(ennemy.current_hp, ennemy.start_hp)
        ennemy.current_damage = min(ennemy.current_damage, ennemy.start_damage)
        ennemy.current_speed = min(ennemy.current_speed, ennemy.start_speed)
    if len(valid_characters) != 0:
        target = random.choice(valid_characters)
        target.effects.append(Effect(EffectType.STUN, 2, 0, character))
        message += f"｢{character.name}｣ stunned {target.name}!"
    return payload, message


def stone_free(
    character: "Character", allied_characters: List["Character"], enemy_characters: List["Character"]
) -> tuple:
    multiplier = 0.90
    payload = get_payload()
    valid_characters = [i for i in enemy_characters if i.is_alive()]
    message = f"｢{character.name}｣ frees the stone ocean!"
    if len(valid_characters) != 0:
        target = random.choice(valid_characters)
        target.effects.append(Effect(EffectType.STUN, 1, 0, character))
        target.current_speed *= multiplier
    return payload, message


def weather_report(
    character: "Character", allied_characters: List["Character"], enemy_characters: List["Character"]
) -> tuple:
    payload = get_payload()
    multiplier = 0.20
    for ennemy in enemy_characters:
        ennemy.effects.append(
            Effect(EffectType.POISON, 3, character.current_damage * multiplier, character)
        )
    message = f"｢{character.name}｣ makes death rain... and poisons everyone for {character.current_damage*multiplier}!"
    return payload, message


def jumpin_jack_flash(
    character: "Character", allied_characters: List["Character"], enemy_characters: List["Character"]
) -> tuple:
    payload = get_payload()
    valid_characters = [i for i in enemy_characters if i.is_alive()]
    message = f"｢{character.name}｣ removes gravity!"
    if len(valid_characters) != 0:
        target = random.choice(valid_characters)
        target.effects.append(Effect(EffectType.STUN, character.turn // 2, 0, character))
    return payload, message


def bohemian_rhapsody(
    character: "Character", allied_characters: List["Character"], enemy_characters: List["Character"]
) -> tuple:
    payload = get_payload()
    message = f"｢{character.name}｣ creates a perfect version of itself!"
    for ally in allied_characters:
        character.current_hp = max(character.current_hp, ally.current_hp)
        character.current_damage = max(character.current_damage, ally.current_damage)
        character.current_critical = max(character.current_critical, ally.current_critical)
        character.current_speed = max(character.current_speed, ally.current_speed)
    return payload, message


def underworld(
    character: "Character", allied_characters: List["Character"], enemy_characters: List["Character"]
) -> tuple:
    multiplier = 4
    payload = get_payload()
    if sum([s.is_alive() for s in allied_characters]) == len(allied_characters):
        message = f"｢{character.name}｣ waits for an ally to die..."
        character.special_meter = 2
        return payload, message
    valid_characters = [i for i in allied_characters if not i.is_alive()]
    revived = random.choice(valid_characters)
    revived.current_hp = revived.start_hp // 4
    message = f"｢{character.name}｣ brings a memory of {revived.name}!"
    return payload, message


def c_moon(
    character: "Character", allied_characters: List["Character"], enemy_characters: List["Character"]
) -> tuple:
    payload = get_payload()
    synergy = _has_synergy(character.id, allied_characters, "pucci")
    slow_amount = 4 if synergy else 2
    for ennemy in enemy_characters:
        ennemy.current_speed -= slow_amount
    message = f"｢{character.name}｣ alters the gravity! All enemies -{slow_amount} speed!"
    if synergy:
        # Pucci: gravity inversion also weakens armor
        for ennemy in enemy_characters:
            ennemy.current_armor = max(1, int(ennemy.current_armor * 0.9))
        message += " ☽ Pucci synergy! -10% enemy armor!"
    return payload, message


def made_in_heaven(
    character: "Character", allied_characters: List["Character"], enemy_characters: List["Character"]
) -> tuple:
    payload = get_payload()
    synergy = _has_synergy(character.id, allied_characters, "pucci")
    if synergy:
        # Pucci evolution: time acceleration amplified
        character.current_speed += 8
        character.current_damage += 30
        character.current_critical += 8
        # Also accelerate Pucci allies
        pucci_ids = SYNERGIES["pucci"]
        for ally in [a for a in allied_characters if a.is_alive() and a.id in pucci_ids and a != character]:
            ally.current_speed += 5
            ally.current_damage += 10
        message = f"｢{character.name}｣ accelerates time for everyone! ☽ Pucci synergy!"
    else:
        character.current_speed += 5
        character.current_damage += 20
        character.current_critical += 5
        message = f"｢{character.name}｣'s speed increases!"
    return payload, message


def tusk_act_4(
    character: "Character", allied_characters: List["Character"], enemy_characters: List["Character"]
) -> tuple:
    payload = get_payload()
    payload["tusk_act_4"] = True
    valid_characters = [i for i in enemy_characters if i.is_alive()]
    synergy = _has_synergy(character.id, allied_characters, "tusk")
    message = f"｢{character.name}｣ Lesson 5!"
    if valid_characters:
        target = random.choice(valid_characters)
        dmg = character.attack(target, multiplier=1.5)["damage"]
        target.effects.append(
            Effect(EffectType.POISON, 4, character.current_damage * 0.75, character)
        )
        target.current_armor = max(1, int(target.current_armor * 0.6))
        message += f" Infinite rotation hits ｢{target.name}｣ for {int(dmg)} impact damage, poison for 4 rounds, -40% armor!"
        if synergy:
            for enemy in valid_characters:
                if enemy != target:
                    enemy.effects.append(Effect(EffectType.BLEED, 2, character.current_damage * 0.3, character))
            message += " ✦ Tusk synergy! All other enemies bleed!"
    return payload, message


def ball_breaker(
    character: "Character", allied_characters: List["Character"], enemy_characters: List["Character"]
) -> tuple:
    payload = get_payload()
    multiplier = 0.65
    for ennemy in enemy_characters:
        ennemy.effects.append(Effect(EffectType.WEAKEN, 1, multiplier, character))
    for ally in allied_characters:
        ally.current_damage += 5
    message = f"｢{character.name}｣ harnesses the power of the spin!"
    return payload, message


def dirty_deed_done_dirt_cheap(
    character: "Character", allied_characters: List["Character"], enemy_characters: List["Character"]
) -> tuple:
    payload = get_payload()
    character.effects = [e for e in character.effects if e.type == EffectType.REGENERATION]
    message = f"｢{character.name}｣ retrieves an alternate version!"
    return payload, message


def boku_no_rythm_wo_kiitekure(
    character: "Character", allied_characters: List["Character"], enemy_characters: List["Character"]
) -> tuple:
    multiplicator = 0.5
    payload = get_payload()
    valid_characters = [i for i in enemy_characters if i.is_alive()]
    for target in valid_characters:
        target: "Character" = random.choice(valid_characters)
        target.effects.append(
            Effect(EffectType.POISON, 1, multiplicator * character.current_damage, character)
        )
    message = f"｢{character.name}｣ plants bombs on everyone."
    return payload, message


def mandom(
    character: "Character", allied_characters: List["Character"], enemy_characters: List["Character"]
) -> tuple:
    payload = get_payload()
    for ally in allied_characters:
        ally.current_critical += 5
    message = f"Welcome to the True Man's world!"
    return payload, message


def the_world_sbr(
    character: "Character", allied_characters: List["Character"], enemy_characters: List["Character"]
) -> tuple:
    payload = get_payload()
    multiplier = 0.6
    damage = 0
    for ennemy in enemy_characters:
        damage += character.attack(ennemy, multiplier=multiplier)["damage"]
    message = f"｢{character.name}｣ STOPS TIME! and damages everyone for {int(damage)}"
    return payload, message


def soft_and_wet(
    character: "Character", allied_characters: List["Character"], enemy_characters: List["Character"]
) -> tuple:
    multiplier = 0.50
    payload = get_payload()
    valid_characters = [i for i in enemy_characters if i.is_alive()]
    message = f"｢{character.name}｣ breaks and weakens!"
    if len(valid_characters) != 0:
        target = random.choice(valid_characters)
        target.effects.append(Effect(EffectType.WEAKEN, 1, multiplier, character))
    return payload, message


def doobie_wah(
    character: "Character", allied_characters: List["Character"], enemy_characters: List["Character"]
) -> tuple:
    payload = get_payload()
    multiplier = 0.4
    valid_characters = [i for i in enemy_characters if i.is_alive()]
    message = f"｢{character.name}｣ seeks it's enemy!"
    if len(valid_characters) != 0:
        target = random.choice(valid_characters)
        target.effects.append(
            Effect(EffectType.POISON, 1, multiplier * character.current_damage, character)
        )
    return payload, message


def walking_heart(
    character: "Character", allied_characters: List["Character"], enemy_characters: List["Character"]
) -> tuple:
    payload = get_payload()
    character.current_damage += 5
    character.current_critical += 1
    message = f"｢{character.name}｣ !"
    return payload, message


def wonder_of_u(
    character: "Character", allied_characters: List["Character"], enemy_characters: List["Character"]
) -> tuple:
    payload = get_payload()
    multiplicator = 0.1
    dif_damage = abs(character.start_hp - character.current_hp)
    # web fix: a slowed Wonder of U can reach negative speed -> complex damage
    woudamage = lambda speed: int(max(speed, 0) * (dif_damage * max(speed, 0) * multiplicator) ** (1 / 2))
    valid_characters = [i for i in enemy_characters if i.is_alive()]
    message = f"｢{character.name}｣ !"
    if len(valid_characters) != 0:
        target = random.choice(valid_characters)
        target.current_hp -= woudamage(character.current_speed)
        message = f"｢{character.name}｣ redirects calamity to {target.name} for {woudamage(character.current_speed)}!"
    return payload, message


def victorious_star_platinum(
    character: "Character", allied_characters: List["Character"], enemy_characters: List["Character"]
) -> tuple:
    payload = get_payload()
    multiplier = 0.4
    damage = 0
    for ennemy in enemy_characters:
        damage += character.attack(ennemy, multiplier=multiplier)["damage"]
    message = f"｢{character.name}｣ STOPS TIME! and damages everyone for {int(damage)}"
    return payload, message


def magician_red(
    character: "Character", allied_characters: List["Character"], enemy_characters: List["Character"]
) -> tuple:
    payload = get_payload()
    synergy = _has_synergy(character.id, allied_characters, "crusaders")
    valid_characters = [i for i in enemy_characters if i.is_alive()]
    if not valid_characters:
        message = f"｢{character.name}｣ releases flames!"
        return payload, message
    if synergy:
        # Crusaders synergy: burn ALL enemies
        for target in valid_characters:
            target.effects.append(
                Effect(EffectType.BURN, 2, 0.4 * character.current_damage, character)
            )
        message = f"｢{character.name}｣ unleashes Crossfire Hurricane on all enemies! ⭐ Crusaders synergy!"
    else:
        target = random.choice(valid_characters)
        target.effects.append(
            Effect(EffectType.BURN, 1, 0.5 * character.current_damage, character)
        )
        message = f"｢{character.name}｣ burns {target.name}!"
    return payload, message


def hierophant_green(
    character: "Character", allied_characters: List["Character"], enemy_characters: List["Character"]
) -> tuple:
    payload = get_payload()
    synergy = _has_synergy(character.id, allied_characters, "crusaders")
    valid_characters = [i for i in enemy_characters if i.is_alive()]
    multiplier = 0.7 if synergy else 0.5
    damage = 0
    for s in valid_characters:
        damage += character.attack(s, multiplier=multiplier)["damage"]
    message = f"No one can deflect the Emerald Splash! {int(damage)} damage to all!"
    if synergy:
        message += " ⭐ Crusaders synergy!"
    return payload, message


def the_fool(
    character: "Character", allied_characters: List["Character"], enemy_characters: List["Character"]
) -> tuple:
    payload = get_payload()
    terrain = _terrain(character)
    if terrain == Terrain.DESERT:
        # Desert: sand fortress — massive armor + damage reflect
        character.current_armor = int(character.current_armor * 1.25)
        valid = [e for e in enemy_characters if e.is_alive()]
        if valid:
            target = random.choice(valid)
            reflect = int(character.current_armor * 0.15)
            target.current_hp -= reflect
            message = f"｢{character.name}｣ raises a sand fortress! +25% armor, {reflect} sand damage to {target.name}!"
        else:
            message = f"｢{character.name}｣ raises a sand fortress! +25% armor!"
    else:
        character.current_armor = int(character.current_armor * 1.1)
        message = f"｢{character.name}｣ becomes more resilient! +10% armor!"
    return payload, message


def hanged_man(
    character: "Character", allied_characters: List["Character"], enemy_characters: List["Character"]
) -> tuple:
    payload = get_payload()
    terrain = _terrain(character)
    if terrain == Terrain.MIRROR:
        # Mirror: infinite reflections — big crit boost + strike from reflection
        character.current_critical *= 1.25
        valid = [e for e in enemy_characters if e.is_alive()]
        if valid:
            target = random.choice(valid)
            dmg = character.attack(target, multiplier=0.6)["damage"]
            message = f"｢{character.name}｣ strikes from every reflection! +25% crit, {dmg} damage to {target.name}!"
        else:
            message = f"｢{character.name}｣ multiplies across reflections! +25% crit!"
    else:
        character.current_critical *= 1.1
        message = f"｢{character.name}｣ finds the weak spot! +10% crit!"
    return payload, message


def emperor(
    character: "Character", allied_characters: List["Character"], enemy_characters: List["Character"]
) -> tuple:
    payload = get_payload()
    multiplier = 1.5
    valid_characters = [i for i in enemy_characters if i.is_alive()]
    message = f"｢{character.name}｣ headshot !"
    if len(valid_characters) != 0:
        target = random.choice(valid_characters)
        damage = character.attack(target, multiplier=multiplier)["damage"]
        message = f"｢{character.name}｣ headshot {target.name} for {damage}｣!"
    return payload, message


def justice(
    character: "Character", allied_characters: List["Character"], enemy_characters: List["Character"]
) -> tuple:
    payload = get_payload()
    multiplier = 25
    message = f"｢{character.name}｣ become more elusive"
    character.current_speed += multiplier
    return payload, message


def death_13(
    character: "Character", allied_characters: List["Character"], enemy_characters: List["Character"]
) -> tuple:
    payload = get_payload()
    multiplier_impared = 5
    multiplier_classic = 0.3
    damage = 0
    valid_characters = [i for i in enemy_characters if i.is_alive()]
    for target in valid_characters:
        if (
            EffectType.STUN in [e.type for e in target.effects]
            or EffectType.SLOW in [e.type for e in target.effects]
            or target.current_speed < target.start_speed
        ):
            damage += character.attack(target, multiplier=multiplier_impared)["damage"]
        else:
            damage += character.attack(target, multiplier=multiplier_classic)["damage"]

    message = f"｢{character.name}｣"
    return payload, message


def high_pristess(
    character: "Character", allied_characters: List["Character"], enemy_characters: List["Character"]
) -> tuple:
    payload = get_payload()
    message = f"｢{character.name}｣ hardened"
    character.current_armor = int(character.current_armor * 1.25)
    return payload, message


def geb(
    character: "Character", allied_characters: List["Character"], enemy_characters: List["Character"]
) -> tuple:
    payload = get_payload()
    terrain = _terrain(character)
    valid_characters = [i for i in enemy_characters if i.is_alive()]
    if not valid_characters:
        message = f"｢{character.name}｣ sneak attack!"
        return payload, message
    if terrain == Terrain.OCEAN:
        # Ocean: water amplifies Geb — hit harder + slow
        target = random.choice(valid_characters)
        damage = character.attack(target, multiplier=2.0)["damage"]
        target.effects.append(Effect(EffectType.SLOW, 2, 5, character))
        message = f"｢{character.name}｣ surges from the water! {damage} damage to {target.name} + slowed!"
    else:
        target = random.choice(valid_characters)
        damage = character.attack(target, multiplier=1.5)["damage"]
        message = f"｢{character.name}｣ sneak attacks {target.name} for {damage}!"
    return payload, message


def horus(
    character: "Character", allied_characters: List["Character"], enemy_characters: List["Character"]
) -> tuple:
    payload = get_payload()
    multiplicator = 2
    valid_characters = [i for i in enemy_characters if i.is_alive()]
    if len(valid_characters) != 0:
        target: "Character" = random.choice(valid_characters)
        target.effects.append(Effect(EffectType.STUN, multiplicator, 0, character))
        message = f"｢{character.name}｣ stuns {target.name} for {multiplicator} rounds!"
    else:
        message = f"｢{character.name}｣!"
    return payload, message


def atum(
    character: "Character", allied_characters: List["Character"], enemy_characters: List["Character"]
) -> tuple:
    payload = get_payload()
    dice_roll = random.randint(0, 6)
    multiplier = dice_roll
    message = f"｢{character.name}｣ roll the dices"
    valid_characters = [i for i in enemy_characters if i.is_alive()]
    if len(valid_characters) != 0:
        target: "Character" = random.choice(valid_characters)
        damage = character.attack(target, multiplier=multiplier)["damage"]
        message = f"｢{character.name}｣ roll the dices and land on {dice_roll} ! and damage {target.name} for {damage}"
    return payload, message


def osiris(
    character: "Character", allied_characters: List["Character"], enemy_characters: List["Character"]
) -> tuple:
    payload = get_payload()
    dice_roll = random.randint(0, 6)
    multiplier = dice_roll
    message = f"｢{character.name}｣ roll the dices"
    valid_characters = [i for i in enemy_characters if i.is_alive()]
    if len(valid_characters) != 0:
        target: "Character" = random.choice(valid_characters)
        damage = character.attack(target, multiplier=multiplier)["damage"]
        message = f"｢{character.name}｣ roll the dices and land on {dice_roll} ! and damage {target.name} for {damage}"
    return payload, message


def aqua_necklace(
    character: "Character", allied_characters: List["Character"], enemy_characters: List["Character"]
) -> tuple:
    payload = get_payload()
    valid_characters = [i for i in enemy_characters if i.is_alive()]
    message = f"｢{character.name}｣ strikes!"
    if valid_characters:
        target = random.choice(valid_characters)
        damage = character.attack(target, multiplier=1.5)["damage"]
        target.effects.append(Effect(EffectType.SLOW, 2, 3, character))
        message = f"｢{character.name}｣ lands a critical blow on {target.name} for {damage} and slows them!"
    return payload, message


def bad_company(
    character: "Character", allied_characters: List["Character"], enemy_characters: List["Character"]
) -> tuple:
    payload = get_payload()
    alive_allies = sum(1 for a in allied_characters if a.is_alive())
    multiplier = 0.4 * alive_allies
    valid_characters = [i for i in enemy_characters if i.is_alive()]
    message = f"｢{character.name}｣ deploys the troops!"
    if valid_characters:
        target = random.choice(valid_characters)
        damage = character.attack(target, multiplier=multiplier)["damage"]
        message = f"｢{character.name}｣ deploys {alive_allies} units! {target.name} takes {damage} damage!"
    return payload, message


def echoes_act_0(
    character: "Character", allied_characters: List["Character"], enemy_characters: List["Character"]
) -> tuple:
    payload = get_payload()
    payload["is_a_special"] = False
    message = f"｢{character.name}｣ is just an egg... it does nothing."
    return payload, message


def the_lock(
    character: "Character", allied_characters: List["Character"], enemy_characters: List["Character"]
) -> tuple:
    payload = get_payload()
    hp_lost = character.start_hp - character.current_hp
    slow_value = max(1, int(hp_lost * 0.02))
    for enemy in enemy_characters:
        enemy.effects.append(Effect(EffectType.SLOW, 2, slow_value, character))
    message = f"｢{character.name}｣ guilt weighs on everyone! Slows all enemies by {slow_value}!"
    return payload, message


def surface(
    character: "Character", allied_characters: List["Character"], enemy_characters: List["Character"]
) -> tuple:
    payload = get_payload()
    valid_characters = [i for i in enemy_characters if i.is_alive()]
    message = f"｢{character.name}｣ takes control!"
    if valid_characters:
        controlled = random.choice(valid_characters)
        other_targets = [i for i in enemy_characters if i.is_alive() and i != controlled]
        if other_targets:
            target = random.choice(other_targets)
            damage = controlled.attack(target)["damage"]
            message = f"｢{character.name}｣ controls {controlled.name} to attack {target.name} for {damage}!"
        else:
            damage = controlled.attack(controlled, multiplier=0.5)["damage"]
            message = f"｢{character.name}｣ controls {controlled.name} to hurt itself for {damage}!"
    return payload, message


def love_deluxe(
    character: "Character", allied_characters: List["Character"], enemy_characters: List["Character"]
) -> tuple:
    payload = get_payload()
    valid_characters = [i for i in enemy_characters if i.is_alive()]
    message = f"｢{character.name}｣ extends her hair!"
    if valid_characters:
        target = random.choice(valid_characters)
        if target.current_speed > character.current_speed:
            target.effects.append(Effect(EffectType.SLOW, 2, 5, character))
            message = f"｢{character.name}｣ tangles {target.name}'s legs! Slowed!"
        else:
            target.effects.append(Effect(EffectType.STUN, 1, 0, character))
            message = f"｢{character.name}｣ wraps around {target.name}! Stunned!"
    return payload, message


def echoes_act_1(
    character: "Character", allied_characters: List["Character"], enemy_characters: List["Character"]
) -> tuple:
    payload = get_payload()
    valid_characters = [i for i in enemy_characters if i.is_alive()]
    message = f"｢{character.name}｣ creates a sound!"
    if valid_characters:
        target = random.choice(valid_characters)
        damage = character.attack(target, multiplier=0.6)["damage"]
        target.effects.append(Effect(EffectType.SLOW, 1, 2, character))
        message = f"｢{character.name}｣ plants a sound on {target.name} for {damage} damage!"
    return payload, message


def pearl_jam(
    character: "Character", allied_characters: List["Character"], enemy_characters: List["Character"]
) -> tuple:
    payload = get_payload()
    terrain = _terrain(character)
    if terrain == Terrain.NATURE:
        # Nature: fresh ingredients — much stronger heal + regen
        heal_amount = 50
        for ally in [a for a in allied_characters if a.is_alive()]:
            ally.current_hp = min(ally.start_hp, ally.current_hp + heal_amount)
            ally.effects = [e for e in ally.effects if e.type not in NEGATIVE_EFFECTS]
            ally.effects.append(Effect(EffectType.REGENERATION, 2, 15, character))
        message = f"｢{character.name}｣ cooks a feast with fresh ingredients! All allies healed for {heal_amount} + regen!"
    else:
        heal_amount = 20
        for ally in [a for a in allied_characters if a.is_alive()]:
            ally.current_hp = min(ally.start_hp, ally.current_hp + heal_amount)
            ally.effects = [e for e in ally.effects if e.type not in NEGATIVE_EFFECTS]
        message = f"｢{character.name}｣ cooks a healing meal! All allies healed for {heal_amount} and debuffs cleared!"
    return payload, message


def achtung_baby(
    character: "Character", allied_characters: List["Character"], enemy_characters: List["Character"]
) -> tuple:
    payload = get_payload()
    terrain = _terrain(character)
    alive_allies = [a for a in allied_characters if a.is_alive() and a != character]
    if alive_allies:
        strongest = max(alive_allies, key=lambda c: c.current_damage)
        if terrain == Terrain.MIRROR:
            # Mirror: reflections amplify invisibility — speed + damage boost
            strongest.current_speed += 50
            boost = int(strongest.current_damage * 0.2)
            strongest.current_damage += boost
            message = f"｢{character.name}｣ bends light in the mirror world! {strongest.name} gains +50 speed and +{boost} damage!"
        else:
            strongest.current_speed += 50
            message = f"｢{character.name}｣ makes {strongest.name} invisible! +50 speed!"
    else:
        character.current_speed += 50
        message = f"｢{character.name}｣ turns invisible! +50 speed!"
    return payload, message


def ratt(
    character: "Character", allied_characters: List["Character"], enemy_characters: List["Character"]
) -> tuple:
    payload = get_payload()
    multiplier = 0.3
    valid_characters = [i for i in enemy_characters if i.is_alive()]
    message = f"｢{character.name}｣ fires a dart!"
    if valid_characters:
        target = random.choice(valid_characters)
        target.effects.append(
            Effect(EffectType.POISON, 3, character.current_damage * multiplier, character)
        )
        message = f"｢{character.name}｣ poisons {target.name} for {int(character.current_damage * multiplier)} over 3 turns!"
    return payload, message


def harvest(
    character: "Character", allied_characters: List["Character"], enemy_characters: List["Character"]
) -> tuple:
    payload = get_payload()
    terrain = _terrain(character)
    stat_choices = ["damage", "speed", "armor", "critical"]
    collected = []
    # Nature: double the harvest
    lo, hi = (5, 15) if terrain == Terrain.NATURE else (2, 8)
    for ally in [a for a in allied_characters if a.is_alive()]:
        stat = random.choice(stat_choices)
        amount = random.randint(lo, hi)
        if stat == "damage":
            ally.current_damage += amount
        elif stat == "speed":
            ally.current_speed += amount
        elif stat == "armor":
            ally.current_armor += amount
        elif stat == "critical":
            ally.current_critical += amount
        collected.append(f"+{amount} {stat}")
    prefix = "bountiful " if terrain == Terrain.NATURE else ""
    message = f"｢{character.name}｣ collects {prefix}resources! {', '.join(collected)}!"
    return payload, message


def atom_heart_father(
    character: "Character", allied_characters: List["Character"], enemy_characters: List["Character"]
) -> tuple:
    payload = get_payload()
    buff = 10
    alive_allies = [a for a in allied_characters if a.is_alive() and a != character]
    if alive_allies:
        for ally in alive_allies:
            ally.current_damage += buff
        message = f"｢{character.name}｣ empowers allies! All allies gain +{buff} damage!"
    else:
        character.current_damage += buff * 2
        message = f"｢{character.name}｣ focuses all power! +{buff * 2} damage!"
    return payload, message


def boy_ii_man(
    character: "Character", allied_characters: List["Character"], enemy_characters: List["Character"]
) -> tuple:
    payload = get_payload()
    roll = random.choice(["rock", "paper", "scissors"])
    valid_characters = [i for i in enemy_characters if i.is_alive()]
    if roll == "rock":
        message = f"｢{character.name}｣ throws Rock! Nothing happens..."
    elif roll == "paper":
        damage_taken = character.start_hp - character.current_hp
        if valid_characters and damage_taken > 0:
            target = random.choice(valid_characters)
            target.current_hp -= damage_taken
            message = f"｢{character.name}｣ throws Paper! Reflects {int(damage_taken)} damage back at {target.name}!"
        else:
            message = f"｢{character.name}｣ throws Paper! No damage to reflect."
    else:
        if valid_characters:
            target = random.choice(valid_characters)
            damage = character.attack(target, multiplier=3.0)["damage"]
            message = f"｢{character.name}｣ throws Scissors! Critical strike on {target.name} for {damage}!"
        else:
            message = f"｢{character.name}｣ throws Scissors!"
    return payload, message


def super_fly(
    character: "Character", allied_characters: List["Character"], enemy_characters: List["Character"]
) -> tuple:
    payload = get_payload()
    character.current_armor = int(character.current_armor * 1.3)
    valid_characters = [i for i in enemy_characters if i.is_alive()]
    damage_taken = character.start_hp - character.current_hp
    reflect = int(damage_taken * 0.25)
    if valid_characters and reflect > 0:
        for enemy in valid_characters:
            enemy.current_hp -= reflect // len(valid_characters)
        message = f"｢{character.name}｣ reflects {reflect} damage back! Armor increased!"
    else:
        message = f"｢{character.name}｣ stands firm like a tower! Armor increased!"
    return payload, message


def cheap_trick(
    character: "Character", allied_characters: List["Character"], enemy_characters: List["Character"]
) -> tuple:
    payload = get_payload()
    dead_allies = [a for a in allied_characters if not a.is_alive() and a != character]
    valid_enemies = [i for i in enemy_characters if i.is_alive()]
    if dead_allies and valid_enemies:
        target = random.choice(valid_enemies)
        target.current_hp = 0
        character.current_hp = 0
        message = f"｢{character.name}｣ drags {target.name} to hell! Both are eliminated!"
    elif not dead_allies:
        message = f"｢{character.name}｣ lurks, waiting for an ally to fall..."
        character.special_meter = character.turn_for_ability - 1
    else:
        message = f"｢{character.name}｣ has no target to drag down!"
    return payload, message


def red_hot_chili_peper(
    character: "Character", allied_characters: List["Character"], enemy_characters: List["Character"]
) -> tuple:
    payload = get_payload()
    multiplier = 0.01
    dif_damge = (character.current_hp - character.start_hp) * multiplier
    character.current_speed += int(dif_damge)
    message = f"｢{character.name}｣ gains more speed ! {int(dif_damge)} speed !"
    return payload, message


def echoes_act_2(
    character: "Character", allied_characters: List["Character"], enemy_characters: List["Character"]
) -> tuple:
    payload = get_payload()
    multiplier = 5
    for ennemy in enemy_characters:
        ennemy.effects.append(Effect(EffectType.SLOW, 3, multiplier, character))
    message = f"｢{character.name}｣ slow everyone for {multiplier}!"
    return payload, message


def cinderella(
    character: "Character", allied_characters: List["Character"], enemy_characters: List["Character"]
) -> tuple:
    payload = get_payload()
    multiplier = 5
    for ally in [s for s in allied_characters if s.is_alive()]:
        ally.current_critical += multiplier
    message = f"｢{character.name}｣ make everyone prettier"
    return payload, message


def highway_star(
    character: "Character", allied_characters: List["Character"], enemy_characters: List["Character"]
) -> tuple:
    payload = get_payload()
    multiplier = 0.5
    message = f"｢{character.name}｣ schearch nutrient"
    valid_characters = [i for i in enemy_characters if i.is_alive()]
    if len(valid_characters) != 0:
        target: "Character" = random.choice(valid_characters)
        damage = character.attack(target, multiplier=multiplier)["damage"]
        character.current_hp += damage
        message = f"｢{character.name}｣ damage {target.name} for {damage} and heal himself for {damage}"
    return payload, message


def stray_cat(
    character: "Character", allied_characters: List["Character"], enemy_characters: List["Character"]
) -> tuple:
    payload = get_payload()
    terrain = _terrain(character)
    synergy = _has_synergy(character.id, allied_characters, "kira")
    multiplier = 10
    atck_multiplier = character.current_critical / multiplier
    valid_characters = [i for i in enemy_characters if i.is_alive()]
    if not valid_characters:
        message = f"｢{character.name}｣ prepares an explosive bubble."
        return payload, message
    if synergy:
        # Kira synergy: guided explosive bubbles — AoE + burn
        total = 0
        for target in valid_characters:
            total += character.attack(target, multiplier=atck_multiplier * 1.5)["damage"]
            target.effects.append(Effect(EffectType.BURN, 1, character.current_damage * 0.3, character))
        message = f"｢{character.name}｣ fires Killer Queen-guided bubbles! {total} damage + burn! 💣🐈 Kira synergy!"
    elif terrain == Terrain.NATURE:
        total = 0
        for target in valid_characters:
            total += character.attack(target, multiplier=atck_multiplier)["damage"]
        message = f"｢{character.name}｣ fires explosive bubbles at everyone for {total} total damage!"
    else:
        target = random.choice(valid_characters)
        damage = character.attack(target, multiplier=atck_multiplier)["damage"]
        message = f"｢{character.name}｣ explodes a bubble on {target.name} for {damage} damage!"
    return payload, message


def enigma(
    character: "Character", allied_characters: List["Character"], enemy_characters: List["Character"]
) -> tuple:
    payload = get_payload()
    valid_characters = [i for i in enemy_characters if i.is_alive()]

    message = f"｢{character.name}｣ schearch their fears."
    if len(valid_characters) != 0:
        target = random.choice(valid_characters)
        if (
            EffectType.STUN in [e.type for e in target.effects]
            or EffectType.SLOW in [e.type for e in target.effects]
            or target.current_speed < target.start_speed
        ):
            target.current_armor = max(1, int(target.current_armor * 0.6))
            message = f"｢{character.name}｣ make {target.name} weak"
    return payload, message


def sex_pistol(
    character: "Character", allied_characters: List["Character"], enemy_characters: List["Character"]
) -> tuple:
    payload = get_payload()
    synergy = _has_synergy(character.id, allied_characters, "passione")
    valid_characters = [i for i in enemy_characters if i.is_alive()]
    message = f"｢{character.name}｣ fires!"
    if valid_characters:
        max_shots = 8 if synergy else 6
        shot_multi = 0.4 if synergy else 0.3
        shots = min(max_shots, len(valid_characters) + random.randint(1, 3))
        total_damage = 0
        for _ in range(shots):
            target = random.choice(valid_characters)
            damage = character.attack(target, multiplier=shot_multi)["damage"]
            total_damage += damage
        message = f"｢{character.name}｣ fires {shots} guided bullets for {total_damage} total damage!"
        if synergy:
            message += " 🐞 Passione synergy!"
    return payload, message


def kraft_work(
    character: "Character", allied_characters: List["Character"], enemy_characters: List["Character"]
) -> tuple:
    payload = get_payload()
    valid_characters = [i for i in enemy_characters if i.is_alive()]
    message = f"｢{character.name}｣ locks objects in place!"
    if valid_characters:
        target = random.choice(valid_characters)
        target.effects.append(Effect(EffectType.STUN, 1, 0, character))
        target.effects.append(Effect(EffectType.SLOW, 2, 5, character))
        message = f"｢{character.name}｣ locks {target.name} in place! Stunned and slowed!"
    return payload, message


def aerosmith(
    character: "Character", allied_characters: List["Character"], enemy_characters: List["Character"]
) -> tuple:
    payload = get_payload()
    synergy = _has_synergy(character.id, allied_characters, "passione")
    multiplier = 0.45 if synergy else 0.35
    damage = 0
    valid_characters = [i for i in enemy_characters if i.is_alive()]
    for target in valid_characters:
        damage += character.attack(target, multiplier=multiplier)["damage"]
    message = f"｢{character.name}｣ strafes everyone for {int(damage)} damage!"
    if synergy:
        # Passione: Narancia tracks via CO2 — also apply bleed to lowest HP enemy
        if valid_characters:
            weakest = min(valid_characters, key=lambda c: c.current_hp)
            weakest.effects.append(Effect(EffectType.BLEED, 2, character.current_damage * 0.15, character))
            message += f" Locks onto {weakest.name} with bleed! 🐞 Passione synergy!"
    return payload, message


def man_in_the_miror(
    character: "Character", allied_characters: List["Character"], enemy_characters: List["Character"]
) -> tuple:
    payload = get_payload()
    synergy = _has_synergy(character.id, allied_characters, "squadra")
    valid_characters = [i for i in enemy_characters if i.is_alive()]
    message = f"｢{character.name}｣ opens the mirror world!"
    if valid_characters:
        if synergy:
            # Squadra: trap 2 enemies in the mirror world
            targets = random.sample(valid_characters, min(2, len(valid_characters)))
            for target in targets:
                target.effects.append(Effect(EffectType.STUN, 1, 0, character))
                target.effects.append(Effect(EffectType.WEAKEN, 2, 0.75, character))
            names = " and ".join(t.name for t in targets)
            message = f"｢{character.name}｣ traps {names} in the mirror world! 🗡️ Squadra synergy!"
        else:
            target = random.choice(valid_characters)
            target.effects.append(Effect(EffectType.STUN, 1, 0, character))
            target.effects.append(Effect(EffectType.WEAKEN, 2, 0.8, character))
            message = f"｢{character.name}｣ traps {target.name} in the mirror world! Stunned and weakened!"
    return payload, message


def the_grateful_dead(
    character: "Character", allied_characters: List["Character"], enemy_characters: List["Character"]
) -> tuple:
    payload = get_payload()
    synergy = _has_synergy(character.id, allied_characters, "squadra")
    poison_multi = 0.3 if synergy else 0.2
    slow_val = 5 if synergy else 3
    for enemy in enemy_characters:
        enemy.effects.append(Effect(EffectType.POISON, 3, character.current_damage * poison_multi, character))
        enemy.effects.append(Effect(EffectType.SLOW, 3, slow_val, character))
    message = f"｢{character.name}｣ ages everyone! Poison and slow applied to all enemies!"
    if synergy:
        message += " 🗡️ Squadra synergy!"
    return payload, message


def baby_face(
    character: "Character", allied_characters: List["Character"], enemy_characters: List["Character"]
) -> tuple:
    payload = get_payload()
    synergy = _has_synergy(character.id, allied_characters, "squadra")
    valid_characters = [i for i in enemy_characters if i.is_alive()]
    message = f"｢{character.name}｣ learns!"
    if valid_characters:
        steal_pct = 0.25 if synergy else 0.15
        target = random.choice(valid_characters)
        stolen_dmg = int(target.current_damage * steal_pct)
        stolen_spd = int(target.current_speed * 0.1) if synergy else 0
        target.current_damage -= stolen_dmg
        character.current_damage += stolen_dmg
        if stolen_spd:
            target.current_speed -= stolen_spd
            character.current_speed += stolen_spd
        message = f"｢{character.name}｣ steals {stolen_dmg} damage"
        if stolen_spd:
            message += f" and {stolen_spd} speed"
        message += f" from {target.name}!"
        if synergy:
            message += " 🗡️ Squadra synergy!"
    return payload, message


def white_album(
    character: "Character", allied_characters: List["Character"], enemy_characters: List["Character"]
) -> tuple:
    payload = get_payload()
    synergy = _has_synergy(character.id, allied_characters, "squadra")
    armor_multi = 1.5 if synergy else 1.4
    character.current_armor = int(character.current_armor * armor_multi)
    slow_val = 6 if synergy else 4
    for enemy in enemy_characters:
        enemy.effects.append(Effect(EffectType.SLOW, 2, slow_val, character))
    message = f"｢{character.name}｣ freezes the area! +{int((armor_multi-1)*100)}% armor, all enemies slowed!"
    if synergy:
        message += " 🗡️ Squadra synergy!"
    return payload, message


def spice_girl(
    character: "Character", allied_characters: List["Character"], enemy_characters: List["Character"]
) -> tuple:
    payload = get_payload()
    for ally in [a for a in allied_characters if a.is_alive()]:
        ally.current_armor = int(ally.current_armor * 1.2)
    message = f"｢{character.name}｣ softens the team! All allies gain +20% armor!"
    return payload, message


# ── Part 5 passive / minor stands ──────────────────────────────────────


def black_sabbath(
    character: "Character", allied_characters: List["Character"], enemy_characters: List["Character"]
) -> tuple:
    """ID 61 — Deals extra damage to enemies above a speed threshold."""
    payload = get_payload()
    valid = [e for e in enemy_characters if e.is_alive()]
    total_damage = 0
    speed_threshold = character.current_speed * 1.5
    for target in valid:
        multi = 0.6 if target.current_speed > speed_threshold else 0.3
        dmg = character.attack(target, multiplier=multi)["damage"]
        total_damage += dmg
    message = f"｢{character.name}｣ drags the fast into the shadows for {total_damage} damage!"
    return payload, message


def moody_blues(
    character: "Character", allied_characters: List["Character"], enemy_characters: List["Character"]
) -> tuple:
    """ID 62 — Reset an enemy ability counter, boost an ally's counter."""
    payload = get_payload()
    valid_enemies = [e for e in enemy_characters if e.is_alive()]
    valid_allies = [a for a in allied_characters if a.is_alive() and a != character and not a.as_special()]
    msg_parts = []
    if valid_enemies:
        target = random.choice(valid_enemies)
        target.special_meter = 0
        msg_parts.append(f"reset {target.name}'s ability")
    if valid_allies:
        ally = random.choice(valid_allies)
        ally.special_meter = ally.turn_for_ability
        msg_parts.append(f"readied {ally.name}'s ability")
    if not msg_parts:
        msg_parts.append("replayed the past but found nothing useful")
    message = f"｢{character.name}｣ " + " and ".join(msg_parts) + "!"
    return payload, message


def soft_machine(
    character: "Character", allied_characters: List["Character"], enemy_characters: List["Character"]
) -> tuple:
    """ID 63 — Deflates a random enemy. Squadra: deflates ALL enemies."""
    payload = get_payload()
    synergy = _has_synergy(character.id, allied_characters, "squadra")
    valid = [e for e in enemy_characters if e.is_alive()]
    if not valid:
        message = f"｢{character.name}｣ slashes at the air!"
        return payload, message
    if synergy:
        # Squadra: coordinated ambush — deflate everyone
        total_armor = 0
        total_dmg = 0
        for target in valid:
            ar = int(target.current_armor * 0.2)
            dr = int(target.current_damage * 0.1)
            target.current_armor -= ar
            target.current_damage -= dr
            total_armor += ar
            total_dmg += dr
        message = f"｢{character.name}｣ deflates all enemies! -{total_armor} armor, -{total_dmg} damage total! 🗡️ Squadra synergy!"
    else:
        target = random.choice(valid)
        armor_reduction = int(target.current_armor * 0.25)
        dmg_reduction = int(target.current_damage * 0.15)
        target.current_armor -= armor_reduction
        target.current_damage -= dmg_reduction
        message = f"｢{character.name}｣ deflates {target.name}! -{armor_reduction} armor, -{dmg_reduction} damage!"
    return payload, message


def little_feet(
    character: "Character", allied_characters: List["Character"], enemy_characters: List["Character"]
) -> tuple:
    """ID 66 — The lower the enemy HP, the lower their damage (shrinking)."""
    payload = get_payload()
    valid = [e for e in enemy_characters if e.is_alive()]
    total_reduced = 0
    for target in valid:
        hp_ratio = target.current_hp / max(target.start_hp, 1)
        reduction = int(target.current_damage * (1 - hp_ratio) * 0.3)
        target.current_damage -= reduction
        total_reduced += reduction
    message = f"｢{character.name}｣ shrinks the enemies! Total damage reduced by {total_reduced}!"
    return payload, message


def mr_president(
    character: "Character", allied_characters: List["Character"], enemy_characters: List["Character"]
) -> tuple:
    """ID 70 — Shelters weakest ally. Any non-DEFAULT terrain strengthens the room."""
    payload = get_payload()
    terrain = _terrain(character)
    valid_allies = [a for a in allied_characters if a.is_alive() and a != character]
    has_terrain = terrain != Terrain.DEFAULT
    if valid_allies:
        weakest = min(valid_allies, key=lambda a: a.current_hp)
        if has_terrain:
            # Any active terrain: the room absorbs the environment — stronger shelter
            heal = int(weakest.start_hp * 0.25)
            weakest.effects.append(Effect(EffectType.REGENERATION, 3, heal, character))
            weakest.current_armor += 40
            weakest.effects = [e for e in weakest.effects if e.type not in NEGATIVE_EFFECTS]
            message = f"｢{character.name}｣ seals the {terrain.display_name} inside the room! {weakest.name} gets +{heal} regen, +40 armor, debuffs cleared!"
        else:
            heal = int(weakest.start_hp * 0.15)
            weakest.effects.append(Effect(EffectType.REGENERATION, 2, heal, character))
            weakest.current_armor += 20
            message = f"｢{character.name}｣ shelters {weakest.name} in the turtle room! +{heal} regen, +20 armor!"
    else:
        armor_gain = 50 if has_terrain else 30
        character.current_armor += armor_gain
        message = f"｢{character.name}｣ retreats into its shell! +{armor_gain} armor!"
    return payload, message


def beach_boy(
    character: "Character", allied_characters: List["Character"], enemy_characters: List["Character"]
) -> tuple:
    """ID 71 — Hooks enemies. In OCEAN: hooks ALL enemies."""
    payload = get_payload()
    terrain = _terrain(character)
    valid = [e for e in enemy_characters if e.is_alive()]
    if not valid:
        message = f"｢{character.name}｣ casts its line but finds nothing!"
        return payload, message
    if terrain == Terrain.OCEAN:
        # Ocean: hook every enemy
        total_reflected = 0
        for target in valid:
            reflected = int(target.current_damage * 0.3)
            target.current_hp -= reflected
            target.effects.append(Effect(EffectType.BLEED, 2, character.current_damage * 0.15, character))
            total_reflected += reflected
        message = f"｢{character.name}｣ casts a wide net! {total_reflected} reflected damage and bleed on all enemies!"
    else:
        target = random.choice(valid)
        reflected = int(target.current_damage * 0.3)
        target.current_hp -= reflected
        target.effects.append(Effect(EffectType.BLEED, 2, character.current_damage * 0.1, character))
        message = f"｢{character.name}｣ hooks {target.name}! {reflected} reflected damage and bleed!"
    return payload, message


def clash(
    character: "Character", allied_characters: List["Character"], enemy_characters: List["Character"]
) -> tuple:
    """ID 76 — Teleports and bites. OCEAN: guaranteed stun. Duo with Talking Head: hit 2 targets."""
    payload = get_payload()
    terrain = _terrain(character)
    duo = _has_synergy(character.id, allied_characters, "clash_talking")
    valid = [e for e in enemy_characters if e.is_alive()]
    if not valid:
        message = f"｢{character.name}｣ searches for water but finds none!"
        return payload, message
    if duo:
        # Clash+TH duo: confusion lets Clash hit 2 targets, always stun
        targets = random.sample(valid, min(2, len(valid)))
        total = 0
        for t in targets:
            total += character.attack(t, multiplier=0.6)["damage"]
            t.effects.append(Effect(EffectType.STUN, 1, 0, character))
        names = " and ".join(t.name for t in targets)
        message = f"｢{character.name}｣ warps between {names} while they're confused! {total} damage, both stunned! 🦈🤥 Duo synergy!"
    elif terrain == Terrain.OCEAN:
        target = random.choice(valid)
        dmg = character.attack(target, multiplier=0.8)["damage"]
        target.effects.append(Effect(EffectType.STUN, 1, 0, character))
        message = f"｢{character.name}｣ surges through the water and bites {target.name} for {dmg} damage! Stunned!"
    else:
        target = random.choice(valid)
        dmg = character.attack(target, multiplier=0.4)["damage"]
        if random.random() < 0.3:
            target.effects.append(Effect(EffectType.STUN, 1, 0, character))
            message = f"｢{character.name}｣ warps to {target.name} and bites for {dmg} damage! Stunned!"
        else:
            message = f"｢{character.name}｣ warps to {target.name} and bites for {dmg} damage!"
    return payload, message


def talking_head(
    character: "Character", allied_characters: List["Character"], enemy_characters: List["Character"]
) -> tuple:
    """ID 77 — Confuses an enemy. Duo with Clash: confuse ALL enemies."""
    payload = get_payload()
    duo = _has_synergy(character.id, allied_characters, "clash_talking")
    valid = [e for e in enemy_characters if e.is_alive()]
    if not valid:
        message = f"｢{character.name}｣ has nothing to confuse!"
        return payload, message
    if duo:
        # Clash+TH duo: confusion spreads to all enemies
        total_spd = 0
        for target in valid:
            spd_loss = int(target.current_speed * 0.25)
            target.current_speed -= spd_loss
            target.current_critical = max(0, target.current_critical * 0.6)
            total_spd += spd_loss
        message = f"｢{character.name}｣ confuses ALL enemies! -{total_spd} total speed, crit halved! 🦈🤥 Duo synergy!"
    else:
        target = random.choice(valid)
        spd_loss = int(target.current_speed * 0.3)
        crit_loss = target.current_critical * 0.5
        target.current_speed -= spd_loss
        target.current_critical = max(0, target.current_critical - crit_loss)
        message = f"｢{character.name}｣ makes {target.name} say the opposite! -{spd_loss} speed, -{int(crit_loss)} crit!"
    return payload, message


def oasis(
    character: "Character", allied_characters: List["Character"], enemy_characters: List["Character"]
) -> tuple:
    """ID 82 — Softens the ground; boosts own speed and deals AoE damage."""
    payload = get_payload()
    character.current_speed = int(character.current_speed * 1.3)
    valid = [e for e in enemy_characters if e.is_alive()]
    total_dmg = 0
    for target in valid:
        dmg = character.attack(target, multiplier=0.25)["damage"]
        total_dmg += dmg
    message = f"｢{character.name}｣ softens the earth! +30% speed and {total_dmg} AoE damage!"
    return payload, message


def rolling_stones(
    character: "Character", allied_characters: List["Character"], enemy_characters: List["Character"]
) -> tuple:
    """ID 85 — Reveals fate: marks a random enemy for death (massive damage if HP below threshold)."""
    payload = get_payload()
    valid = [e for e in enemy_characters if e.is_alive()]
    if valid:
        target = random.choice(valid)
        hp_ratio = target.current_hp / max(target.start_hp, 1)
        if hp_ratio < 0.3:
            execute_dmg = int(target.current_hp * 0.8)
            target.current_hp -= execute_dmg
            message = f"｢{character.name}｣ reveals {target.name}'s fate... inevitable! {execute_dmg} execution damage!"
        else:
            target.effects.append(Effect(EffectType.BLEED, 3, character.current_damage * 0.2, character))
            message = f"｢{character.name}｣ shows {target.name} their future... bleed applied!"
    else:
        message = f"｢{character.name}｣ rolls aimlessly..."
    return payload, message


"""
def oasis_placeholder(
    character: "Character", allied_characters: List["Character"], enemy_characters: List["Character"]
) -> tuple:
    payload = get_payload()
    # Whatever your code does to the lists above
    # Payload Contain behavior change to the game
    # message is what should be printed to the embed
    return payload, message
"""


def goo_goo_dolls(
    character: "Character", allied_characters: List["Character"], enemy_characters: List["Character"]
) -> tuple:
    payload = get_payload()
    valid = [e for e in enemy_characters if e.is_alive()]
    if valid:
        target = random.choice(valid)
        reduction = 0.7
        target.current_damage = int(target.current_damage * reduction)
        target.current_hp = int(target.current_hp * reduction)
        message = f"｢{character.name}｣ shrinks {target.name}! -30% damage and HP!"
    else:
        message = f"｢{character.name}｣ has no target to shrink!"
    return payload, message


def manhattan_transfer(
    character: "Character", allied_characters: List["Character"], enemy_characters: List["Character"]
) -> tuple:
    payload = get_payload()
    for ally in allied_characters:
        if ally.is_alive():
            ally.current_critical += 10
    message = f"｢{character.name}｣ guides the wind! All allies +10 critical!"
    return payload, message


def kiss(
    character: "Character", allied_characters: List["Character"], enemy_characters: List["Character"]
) -> tuple:
    payload = get_payload()
    valid = [e for e in enemy_characters if e.is_alive()]
    if valid:
        target = random.choice(valid)
        dmg1 = character.attack(target, multiplier=1)["damage"]
        dmg2 = character.attack(target, multiplier=1)["damage"]
        message = f"｢{character.name}｣ places a sticker on {target.name} and strikes twice for {int(dmg1 + dmg2)} damage!"
    else:
        message = f"｢{character.name}｣ has no target!"
    return payload, message


def highway_to_hell(
    character: "Character", allied_characters: List["Character"], enemy_characters: List["Character"]
) -> tuple:
    payload = get_payload()
    valid = [e for e in enemy_characters if e.is_alive()]
    if valid:
        target = random.choice(valid)
        shared_dmg = character.current_hp // 2
        character.current_hp -= shared_dmg
        target.current_hp -= shared_dmg
        message = f"｢{character.name}｣ shares its fate with {target.name}! Both lose {shared_dmg} HP!"
    else:
        message = f"｢{character.name}｣ has no target to bind!"
    return payload, message


def burning_down_the_house(
    character: "Character", allied_characters: List["Character"], enemy_characters: List["Character"]
) -> tuple:
    payload = get_payload()
    heal_amount = character.current_damage * 2
    for ally in allied_characters:
        if ally.is_alive():
            ally.current_hp += heal_amount
    message = f"｢{character.name}｣ opens the ghost room! All allies heal {int(heal_amount)} HP!"
    return payload, message


def foo_fighters(
    character: "Character", allied_characters: List["Character"], enemy_characters: List["Character"]
) -> tuple:
    payload = get_payload()
    alive_allies = [a for a in allied_characters if a.is_alive()]
    if alive_allies:
        target = min(alive_allies, key=lambda a: a.current_hp / max(1, a.start_hp))
        heal = int(target.start_hp * 0.3)
        target.current_hp += heal
        message = f"｢{character.name}｣ injects plankton into {target.name}! +{heal} HP!"
    else:
        message = f"｢{character.name}｣ has no ally to heal!"
    return payload, message


def marilyn_manson(
    character: "Character", allied_characters: List["Character"], enemy_characters: List["Character"]
) -> tuple:
    payload = get_payload()
    valid = [e for e in enemy_characters if e.is_alive()]
    if valid:
        target = random.choice(valid)
        stolen_dmg = target.current_damage // 4
        stolen_spd = target.current_speed // 4
        target.current_damage -= stolen_dmg
        target.current_speed -= stolen_spd
        character.current_damage += stolen_dmg
        character.current_speed += stolen_spd
        message = f"｢{character.name}｣ collects the debt! Stole {int(stolen_dmg)} dmg and {int(stolen_spd)} speed from {target.name}!"
    else:
        message = f"｢{character.name}｣ has no debt to collect!"
    return payload, message


def limp_bizkit(
    character: "Character", allied_characters: List["Character"], enemy_characters: List["Character"]
) -> tuple:
    payload = get_payload()
    character.current_damage = int(character.current_damage * 1.5)
    character.current_hp += character.start_hp // 4
    message = f"｢{character.name}｣ summons invisible zombies! +50% damage and heals!"
    return payload, message


def diver_down(
    character: "Character", allied_characters: List["Character"], enemy_characters: List["Character"]
) -> tuple:
    payload = get_payload()
    alive_allies = [a for a in allied_characters if a.is_alive() and a != character]
    if alive_allies:
        target = min(alive_allies, key=lambda a: a.current_hp)
        target.current_armor += 50
        target.effects.append(Effect(EffectType.REGENERATION, 2, character.current_damage * 0.5, character))
        message = f"｢{character.name}｣ dives into {target.name}! +50 armor and regen!"
    else:
        character.current_armor += 50
        character.effects.append(Effect(EffectType.REGENERATION, 2, character.current_damage * 0.5, character))
        message = f"｢{character.name}｣ reinforces itself! +50 armor and regen!"
    return payload, message


def planet_waves(
    character: "Character", allied_characters: List["Character"], enemy_characters: List["Character"]
) -> tuple:
    payload = get_payload()
    total_dmg = 0
    for enemy in enemy_characters:
        if enemy.is_alive():
            dmg = character.attack(enemy, multiplier=0.6)["damage"]
            total_dmg += dmg
            if random.random() < 0.3:
                enemy.effects.append(Effect(EffectType.STUN, 1, 0, character))
    message = f"｢{character.name}｣ pulls meteorites from orbit! {int(total_dmg)} total damage!"
    return payload, message


def dragons_dream(
    character: "Character", allied_characters: List["Character"], enemy_characters: List["Character"]
) -> tuple:
    payload = get_payload()
    for ally in allied_characters:
        if ally.is_alive():
            ally.current_critical += 15
    message = f"｢{character.name}｣ reveals the lucky spots! All allies +15 critical!"
    return payload, message


def yo_yo_ma(
    character: "Character", allied_characters: List["Character"], enemy_characters: List["Character"]
) -> tuple:
    payload = get_payload()
    valid = [e for e in enemy_characters if e.is_alive()]
    if valid:
        target = random.choice(valid)
        target.effects.append(Effect(EffectType.POISON, 3, character.current_damage * 0.4, character))
        message = f"｢{character.name}｣ drools acid on {target.name}! Poisoned for 3 turns!"
    else:
        message = f"｢{character.name}｣ has no target!"
    return payload, message


def green_green_grass_home(
    character: "Character", allied_characters: List["Character"], enemy_characters: List["Character"]
) -> tuple:
    payload = get_payload()
    for enemy in enemy_characters:
        if enemy.is_alive():
            reduction = max(1, enemy.current_damage // 4)
            enemy.current_damage -= reduction
    message = f"｢{character.name}｣ shrinks all enemies! All enemies -25% damage!"
    return payload, message


def jail_house_lock(
    character: "Character", allied_characters: List["Character"], enemy_characters: List["Character"]
) -> tuple:
    payload = get_payload()
    valid = [e for e in enemy_characters if e.is_alive()]
    for enemy in valid:
        enemy.effects.append(Effect(EffectType.STUN, 1, 0, character))
        enemy.current_speed = max(0, enemy.current_speed - 2)
    message = f"｢{character.name}｣ locks their memories! All enemies stunned and -2 speed!"
    return payload, message


def sky_high(
    character: "Character", allied_characters: List["Character"], enemy_characters: List["Character"]
) -> tuple:
    payload = get_payload()
    total_drain = 0
    for enemy in enemy_characters:
        if enemy.is_alive():
            drain = int(enemy.current_hp * 0.1)
            enemy.current_hp -= drain
            total_drain += drain
    character.current_hp += total_drain // 2
    message = f"｢{character.name}｣ sends the rods! Drained {total_drain} HP from enemies!"
    return payload, message


def survivor(
    character: "Character", allied_characters: List["Character"], enemy_characters: List["Character"]
) -> tuple:
    payload = get_payload()
    valid = [e for e in enemy_characters if e.is_alive()]
    if len(valid) >= 2:
        attacker = random.choice(valid)
        targets = [e for e in valid if e != attacker]
        target = random.choice(targets)
        dmg = attacker.attack(target, multiplier=1)["damage"]
        message = f"｢{character.name}｣ enrages the enemies! {attacker.name} attacks {target.name} for {int(dmg)} damage!"
    elif len(valid) == 1:
        valid[0].effects.append(Effect(EffectType.STUN, 1, 0, character))
        message = f"｢{character.name}｣ enrages {valid[0].name}! Stunned for 1 turn!"
    else:
        message = f"｢{character.name}｣ has no target to enrage!"
    return payload, message


def whitesnake(
    character: "Character", allied_characters: List["Character"], enemy_characters: List["Character"]
) -> tuple:
    payload = get_payload()
    valid = [e for e in enemy_characters if e.is_alive()]
    synergy = _has_synergy(character.id, allied_characters, "pucci")
    if valid:
        target = max(valid, key=lambda e: e.current_speed)
        stolen_dmg = target.current_damage // 3
        stolen_spd = target.current_speed // 3
        target.current_damage -= stolen_dmg
        target.current_speed -= stolen_spd
        character.current_damage += stolen_dmg
        character.current_speed += stolen_spd
        message = f"｢{character.name}｣ steals {target.name}'s DISC! +{int(stolen_dmg)} dmg, +{int(stolen_spd)} speed!"
        if synergy:
            target.effects.append(Effect(EffectType.WEAKEN, 2, character.current_damage * 0.2, character))
            message += " ☽ Pucci synergy! Target weakened!"
    else:
        message = f"｢{character.name}｣ has no target to steal from!"
    return payload, message


def tusk_act_1(
    character: "Character", allied_characters: List["Character"], enemy_characters: List["Character"]
) -> tuple:
    payload = get_payload()
    valid = [e for e in enemy_characters if e.is_alive()]
    if valid:
        target = random.choice(valid)
        dmg = character.attack(target, multiplier=1.2)["damage"]
        message = f"｢{character.name}｣ fires a nail bullet at {target.name} for {int(dmg)} damage!"
    else:
        message = f"｢{character.name}｣ fires into the void!"
    return payload, message


def tusk_act_2(
    character: "Character", allied_characters: List["Character"], enemy_characters: List["Character"]
) -> tuple:
    payload = get_payload()
    valid = [e for e in enemy_characters if e.is_alive()]
    if valid:
        target = random.choice(valid)
        dmg = character.attack(target, multiplier=1.4)["damage"]
        target.effects.append(Effect(EffectType.BLEED, 2, character.current_damage * 0.15, character))
        synergy = _has_synergy(character.id, allied_characters, "tusk")
        message = f"｢{character.name}｣ shoots a guided nail at {target.name} for {int(dmg)} damage! Bleed applied!"
        if synergy:
            target.effects.append(Effect(EffectType.SLOW, 1, 2, character))
            message += " ✦ Tusk synergy! Target slowed!"
    else:
        message = f"｢{character.name}｣ fires into the void!"
    return payload, message


def tusk_act_3(
    character: "Character", allied_characters: List["Character"], enemy_characters: List["Character"]
) -> tuple:
    payload = get_payload()
    valid = [e for e in enemy_characters if e.is_alive()]
    synergy = _has_synergy(character.id, allied_characters, "tusk")
    if valid:
        target = random.choice(valid)
        dmg = character.attack(target, multiplier=1.6)["damage"]
        target.effects.append(Effect(EffectType.BLEED, 2, character.current_damage * 0.25, character))
        target.current_armor = max(1, int(target.current_armor * 0.8))
        message = f"｢{character.name}｣ fires a wormhole nail at {target.name} for {int(dmg)} damage! Bleed and -20% armor!"
        if synergy:
            target.effects.append(Effect(EffectType.POISON, 2, character.current_damage * 0.2, character))
            message += " ✦ Tusk synergy! Poison applied!"
    else:
        message = f"｢{character.name}｣ fires into the void!"
    return payload, message


def oh_lonesome_me(
    character: "Character", allied_characters: List["Character"], enemy_characters: List["Character"]
) -> tuple:
    payload = get_payload()
    valid = [e for e in enemy_characters if e.is_alive()]
    if valid:
        target = random.choice(valid)
        target.effects.append(Effect(EffectType.STUN, 1, 0, character))
        target.current_damage = int(target.current_damage * 0.8)
        message = f"｢{character.name}｣ lassoes {target.name}! Stunned and -20% damage!"
    else:
        message = f"｢{character.name}｣ swings the rope..."
    return payload, message


def scary_monsters(
    character: "Character", allied_characters: List["Character"], enemy_characters: List["Character"]
) -> tuple:
    payload = get_payload()
    character.current_damage = int(character.current_damage * 1.4)
    character.current_speed += 3
    character.current_critical += 5
    valid = [e for e in enemy_characters if e.is_alive()]
    if valid:
        target = random.choice(valid)
        dmg = character.attack(target, multiplier=0.8)["damage"]
        message = f"｢{character.name}｣ transforms into a dinosaur! +40% damage, +3 speed, and bites {target.name} for {int(dmg)}!"
    else:
        message = f"｢{character.name}｣ transforms into a dinosaur! +40% damage, +3 speed!"
    return payload, message


def cream_starter(
    character: "Character", allied_characters: List["Character"], enemy_characters: List["Character"]
) -> tuple:
    payload = get_payload()
    alive_allies = [a for a in allied_characters if a.is_alive()]
    if alive_allies:
        target = min(alive_allies, key=lambda a: a.current_hp / max(1, a.start_hp))
        heal = int(target.start_hp * 0.25)
        target.current_hp += heal
        target.current_damage = int(target.current_damage * 1.1)
        message = f"｢{character.name}｣ reshapes {target.name}'s flesh! +{heal} HP and +10% damage!"
    else:
        message = f"｢{character.name}｣ has no one to heal!"
    return payload, message


def ticket_to_ride(
    character: "Character", allied_characters: List["Character"], enemy_characters: List["Character"]
) -> tuple:
    payload = get_payload()
    for ally in allied_characters:
        if ally.is_alive():
            ally.effects.append(Effect(EffectType.REGENERATION, 3, character.current_damage * 0.3, character))
    for enemy in enemy_characters:
        if enemy.is_alive():
            enemy.effects.append(Effect(EffectType.WEAKEN, 2, 0.85, character))
    message = f"｢{character.name}｣ emits the holy light! Allies regenerate, enemies weakened!"
    return payload, message


def in_a_silent_way(
    character: "Character", allied_characters: List["Character"], enemy_characters: List["Character"]
) -> tuple:
    payload = get_payload()
    valid = [e for e in enemy_characters if e.is_alive()]
    total_dmg = 0
    for enemy in valid:
        dmg = character.attack(enemy, multiplier=0.5)["damage"]
        total_dmg += dmg
        enemy.effects.append(Effect(EffectType.BLEED, 2, character.current_damage * 0.2, character))
    message = f"｢{character.name}｣ stores sound into blades! {int(total_dmg)} total damage and bleed to all!"
    return payload, message


def hey_ya(
    character: "Character", allied_characters: List["Character"], enemy_characters: List["Character"]
) -> tuple:
    payload = get_payload()
    for ally in allied_characters:
        if ally.is_alive():
            ally.current_critical += 10
            ally.current_speed += 2
    message = f"｢{character.name}｣ cheers everyone on! All allies +10 critical, +2 speed!"
    return payload, message


def tomb_of_boom(
    character: "Character", allied_characters: List["Character"], enemy_characters: List["Character"]
) -> tuple:
    payload = get_payload()
    valid = [e for e in enemy_characters if e.is_alive()]
    if valid:
        target = random.choice(valid)
        target.effects.append(Effect(EffectType.POISON, 2, character.current_damage * 0.6, character))
        target.current_speed = max(0, target.current_speed - 3)
        message = f"｢{character.name}｣ implants iron in {target.name}! Poisoned and -3 speed!"
    else:
        message = f"｢{character.name}｣ has no target!"
    return payload, message


def wired(
    character: "Character", allied_characters: List["Character"], enemy_characters: List["Character"]
) -> tuple:
    payload = get_payload()
    valid = [e for e in enemy_characters if e.is_alive()]
    total_dmg = 0
    for enemy in valid:
        dmg = character.attack(enemy, multiplier=0.4)["damage"]
        total_dmg += dmg
        enemy.effects.append(Effect(EffectType.BLEED, 1, character.current_damage * 0.15, character))
    message = f"｢{character.name}｣ launches barbed wire! {int(total_dmg)} total damage and bleed!"
    return payload, message


def catch_the_rainbow(
    character: "Character", allied_characters: List["Character"], enemy_characters: List["Character"]
) -> tuple:
    payload = get_payload()
    character.current_armor += 80
    valid = [e for e in enemy_characters if e.is_alive()]
    if valid:
        target = random.choice(valid)
        dmg = character.attack(target, multiplier=1.5)["damage"]
        message = f"｢{character.name}｣ freezes in the rain! +80 armor and pierces {target.name} for {int(dmg)}!"
    else:
        character.current_damage += 15
        message = f"｢{character.name}｣ freezes in the rain! +80 armor, +15 damage!"
    return payload, message


def sugar_mountain(
    character: "Character", allied_characters: List["Character"], enemy_characters: List["Character"]
) -> tuple:
    payload = get_payload()
    for ally in allied_characters:
        if ally.is_alive():
            ally.current_damage += 10
            ally.current_hp += 50
    message = f"｢{character.name}｣ offers gifts from the spring! All allies +10 damage, +50 HP!"
    return payload, message


def tatoo_you(
    character: "Character", allied_characters: List["Character"], enemy_characters: List["Character"]
) -> tuple:
    payload = get_payload()
    for ally in allied_characters:
        if ally.is_alive():
            ally.current_armor += 30
    message = f"｢{character.name}｣ hides the team in its skin! All allies +30 armor!"
    return payload, message


def tubular_bells(
    character: "Character", allied_characters: List["Character"], enemy_characters: List["Character"]
) -> tuple:
    payload = get_payload()
    valid = [e for e in enemy_characters if e.is_alive()]
    if valid:
        target = random.choice(valid)
        dmg = character.attack(target, multiplier=1.3)["damage"]
        target.effects.append(Effect(EffectType.STUN, 1, 0, character))
        message = f"｢{character.name}｣ inflates a balloon animal that attacks {target.name} for {int(dmg)}! Stunned!"
    else:
        message = f"｢{character.name}｣ inflates a balloon..."
    return payload, message


def twentieth_century_boy(
    character: "Character", allied_characters: List["Character"], enemy_characters: List["Character"]
) -> tuple:
    payload = get_payload()
    character.current_armor += 200
    character.effects.append(Effect(EffectType.REGENERATION, 2, character.start_hp * 0.1, character))
    message = f"｢{character.name}｣ kneels and becomes invincible! +200 armor and regen!"
    return payload, message


def civil_war(
    character: "Character", allied_characters: List["Character"], enemy_characters: List["Character"]
) -> tuple:
    payload = get_payload()
    valid = [e for e in enemy_characters if e.is_alive()]
    for enemy in valid:
        enemy.effects.append(Effect(EffectType.POISON, 2, character.current_damage * 0.3, character))
        enemy.current_damage = int(enemy.current_damage * 0.85)
    message = f"｢{character.name}｣ summons the guilt of the past! All enemies poisoned and -15% damage!"
    return payload, message


def chocolate_disco(
    character: "Character", allied_characters: List["Character"], enemy_characters: List["Character"]
) -> tuple:
    payload = get_payload()
    valid = [e for e in enemy_characters if e.is_alive()]
    total_dmg = 0
    for enemy in valid:
        dmg = character.attack(enemy, multiplier=0.7)["damage"]
        total_dmg += dmg
    message = f"｢{character.name}｣ marks the grid! Precise strikes for {int(total_dmg)} total damage!"
    return payload, message


def paisley_park(
    character: "Character", allied_characters: List["Character"], enemy_characters: List["Character"]
) -> tuple:
    payload = get_payload()
    for ally in allied_characters:
        if ally.is_alive():
            ally.current_speed += 3
            ally.current_critical += 5
    valid = [e for e in enemy_characters if e.is_alive()]
    if valid:
        target = min(valid, key=lambda e: e.current_hp)
        message = f"｢{character.name}｣ finds the optimal path! Allies +3 speed, +5 critical! Weakest enemy revealed: {target.name}!"
    else:
        message = f"｢{character.name}｣ finds the optimal path! Allies +3 speed, +5 critical!"
    return payload, message


def doggy_style(
    character: "Character", allied_characters: List["Character"], enemy_characters: List["Character"]
) -> tuple:
    payload = get_payload()
    valid = [e for e in enemy_characters if e.is_alive()]
    if valid:
        target = random.choice(valid)
        dmg = character.attack(target, multiplier=1.3)["damage"]
        target.effects.append(Effect(EffectType.BLEED, 2, character.current_damage * 0.2, character))
        message = f"｢{character.name}｣ unravels and lashes {target.name} for {int(dmg)} damage! Bleed applied!"
    else:
        message = f"｢{character.name}｣ unravels into the air..."
    return payload, message


def nut_king_call(
    character: "Character", allied_characters: List["Character"], enemy_characters: List["Character"]
) -> tuple:
    payload = get_payload()
    valid = [e for e in enemy_characters if e.is_alive()]
    if valid:
        target = random.choice(valid)
        target.current_armor = max(1, int(target.current_armor * 0.6))
        target.current_damage = int(target.current_damage * 0.8)
        dmg = character.attack(target, multiplier=1.2)["damage"]
        message = f"｢{character.name}｣ unscrews {target.name}! -40% armor, -20% damage, {int(dmg)} hit!"
    else:
        message = f"｢{character.name}｣ screws the air..."
    return payload, message


def paper_moon_king(
    character: "Character", allied_characters: List["Character"], enemy_characters: List["Character"]
) -> tuple:
    payload = get_payload()
    valid = [e for e in enemy_characters if e.is_alive()]
    for enemy in valid:
        enemy.current_critical = max(0, enemy.current_critical - 10)
        enemy.current_speed = max(0, enemy.current_speed - 2)
    message = f"｢{character.name}｣ distorts perception! All enemies -10 critical, -2 speed!"
    return payload, message


def king_nothing(
    character: "Character", allied_characters: List["Character"], enemy_characters: List["Character"]
) -> tuple:
    payload = get_payload()
    valid = [e for e in enemy_characters if e.is_alive()]
    if valid:
        target = max(valid, key=lambda e: e.current_damage)
        target.current_armor = max(1, int(target.current_armor * 0.7))
        target.effects.append(Effect(EffectType.WEAKEN, 2, 0.8, character))
        message = f"｢{character.name}｣ tracks {target.name}'s scent! -30% armor and weakened!"
    else:
        message = f"｢{character.name}｣ searches for a scent..."
    return payload, message


def speed_king(
    character: "Character", allied_characters: List["Character"], enemy_characters: List["Character"]
) -> tuple:
    payload = get_payload()
    valid = [e for e in enemy_characters if e.is_alive()]
    if valid:
        target = random.choice(valid)
        dmg = character.attack(target, multiplier=1.5)["damage"]
        target.effects.append(Effect(EffectType.BURN, 2, character.current_damage * 0.3, character))
        message = f"｢{character.name}｣ ignites {target.name} from the inside! {int(dmg)} damage and burn!"
    else:
        message = f"｢{character.name}｣ heats up..."
    return payload, message


def fun_fun_fun(
    character: "Character", allied_characters: List["Character"], enemy_characters: List["Character"]
) -> tuple:
    payload = get_payload()
    valid = [e for e in enemy_characters if e.is_alive()]
    if valid:
        target = random.choice(valid)
        target.effects.append(Effect(EffectType.STUN, 2, 0, character))
        target.current_damage = int(target.current_damage * 0.7)
        message = f"｢{character.name}｣ takes control of {target.name}! Stunned 2 turns and -30% damage!"
    else:
        message = f"｢{character.name}｣ has no one to control!"
    return payload, message


def california_king_bed(
    character: "Character", allied_characters: List["Character"], enemy_characters: List["Character"]
) -> tuple:
    payload = get_payload()
    valid = [e for e in enemy_characters if e.is_alive()]
    if valid:
        target = random.choice(valid)
        stolen_dmg = target.current_damage // 3
        target.current_damage -= stolen_dmg
        character.current_damage += stolen_dmg
        message = f"｢{character.name}｣ steals a memory from {target.name}! Took {int(stolen_dmg)} damage!"
    else:
        message = f"｢{character.name}｣ has no memory to steal!"
    return payload, message


def born_this_way(
    character: "Character", allied_characters: List["Character"], enemy_characters: List["Character"]
) -> tuple:
    payload = get_payload()
    valid = [e for e in enemy_characters if e.is_alive()]
    total_dmg = 0
    for enemy in valid:
        dmg = character.attack(enemy, multiplier=0.5)["damage"]
        total_dmg += dmg
        enemy.effects.append(Effect(EffectType.SLOW, 2, 3, character))
    message = f"｢{character.name}｣ rides in on the frozen wind! {int(total_dmg)} AOE damage and all enemies slowed!"
    return payload, message


def les_feuilles(
    character: "Character", allied_characters: List["Character"], enemy_characters: List["Character"]
) -> tuple:
    payload = get_payload()
    valid = [e for e in enemy_characters if e.is_alive()]
    if valid:
        target = random.choice(valid)
        target.effects.append(Effect(EffectType.POISON, 3, character.current_damage * 0.25, character))
        target.current_speed = max(0, target.current_speed - 3)
        message = f"｢{character.name}｣ wraps leaves around {target.name}! Poisoned 3 turns and -3 speed!"
    else:
        message = f"｢{character.name}｣ scatters leaves..."
    return payload, message


def i_am_a_rock(
    character: "Character", allied_characters: List["Character"], enemy_characters: List["Character"]
) -> tuple:
    payload = get_payload()
    valid = [e for e in enemy_characters if e.is_alive()]
    for enemy in valid:
        enemy.effects.append(Effect(EffectType.STUN, 1, 0, character))
    character.current_armor += 40
    message = f"｢{character.name}｣ attracts everything! All enemies stunned and +40 armor!"
    return payload, message


def love_love_deluxe(
    character: "Character", allied_characters: List["Character"], enemy_characters: List["Character"]
) -> tuple:
    payload = get_payload()
    valid = [e for e in enemy_characters if e.is_alive()]
    if valid:
        target = random.choice(valid)
        target.effects.append(Effect(EffectType.POISON, 2, character.current_damage * 0.3, character))
        target.current_armor = max(1, int(target.current_armor * 0.8))
        message = f"｢{character.name}｣ extends hair into {target.name}! Poisoned and -20% armor!"
    else:
        message = f"｢{character.name}｣ extends its hair..."
    return payload, message


def schott_key(
    character: "Character", allied_characters: List["Character"], enemy_characters: List["Character"]
) -> tuple:
    payload = get_payload()
    valid = [e for e in enemy_characters if e.is_alive()]
    total_dmg = 0
    for enemy in valid:
        dmg = character.attack(enemy, multiplier=0.6)["damage"]
        total_dmg += dmg
    message = f"｢{character.name}｣ explodes! {int(total_dmg)} AOE damage!"
    return payload, message


def vitamine_c(
    character: "Character", allied_characters: List["Character"], enemy_characters: List["Character"]
) -> tuple:
    payload = get_payload()
    valid = [e for e in enemy_characters if e.is_alive()]
    for enemy in valid:
        enemy.current_speed = max(0, enemy.current_speed - 3)
        enemy.current_damage = int(enemy.current_damage * 0.85)
    message = f"｢{character.name}｣ softens everything! All enemies -3 speed and -15% damage!"
    return payload, message


def milagro_man(
    character: "Character", allied_characters: List["Character"], enemy_characters: List["Character"]
) -> tuple:
    payload = get_payload()
    valid = [e for e in enemy_characters if e.is_alive()]
    if valid:
        target = random.choice(valid)
        curse_dmg = int(target.current_damage * 0.5)
        target.current_hp -= curse_dmg
        target.effects.append(Effect(EffectType.POISON, 2, curse_dmg * 0.5, character))
        message = f"｢{character.name}｣ curses {target.name} with endless wealth! {curse_dmg} damage and poison!"
    else:
        message = f"｢{character.name}｣ scatters cursed money..."
    return payload, message


def blue_hawaii(
    character: "Character", allied_characters: List["Character"], enemy_characters: List["Character"]
) -> tuple:
    payload = get_payload()
    valid = [e for e in enemy_characters if e.is_alive()]
    if valid:
        target = random.choice(valid)
        target.effects.append(Effect(EffectType.STUN, 2, 0, character))
        target.effects.append(Effect(EffectType.POISON, 2, character.current_damage * 0.2, character))
        message = f"｢{character.name}｣ takes control of {target.name}! Stunned 2 turns and poisoned!"
    else:
        message = f"｢{character.name}｣ has no one to control!"
    return payload, message


def brain_storm(
    character: "Character", allied_characters: List["Character"], enemy_characters: List["Character"]
) -> tuple:
    payload = get_payload()
    valid = [e for e in enemy_characters if e.is_alive()]
    total_dmg = 0
    for enemy in valid:
        dmg = character.attack(enemy, multiplier=0.5)["damage"]
        total_dmg += dmg
        enemy.effects.append(Effect(EffectType.BLEED, 2, character.current_damage * 0.15, character))
    message = f"｢{character.name}｣ folds the pages! {int(total_dmg)} AOE damage and bleed!"
    return payload, message


def ozon_baby(
    character: "Character", allied_characters: List["Character"], enemy_characters: List["Character"]
) -> tuple:
    payload = get_payload()
    valid = [e for e in enemy_characters if e.is_alive()]
    for enemy in valid:
        pressure_dmg = int(enemy.current_hp * 0.12)
        enemy.current_hp -= pressure_dmg
        enemy.current_speed = max(0, enemy.current_speed - 2)
    message = f"｢{character.name}｣ increases air pressure! All enemies lose 12% HP and -2 speed!"
    return payload, message


def doctor_wu(
    character: "Character", allied_characters: List["Character"], enemy_characters: List["Character"]
) -> tuple:
    payload = get_payload()
    valid = [e for e in enemy_characters if e.is_alive()]
    if valid:
        target = random.choice(valid)
        target.effects.append(Effect(EffectType.POISON, 3, character.current_damage * 0.35, character))
        target.current_armor = max(1, int(target.current_armor * 0.8))
        message = f"｢{character.name}｣ infiltrates {target.name}'s body! Poison 3 turns and -20% armor!"
    else:
        message = f"｢{character.name}｣ scatters its particles..."
    return payload, message


def awaking_iii_leaves(
    character: "Character", allied_characters: List["Character"], enemy_characters: List["Character"]
) -> tuple:
    payload = get_payload()
    valid = [e for e in enemy_characters if e.is_alive()]
    if valid:
        target = random.choice(valid)
        target.effects.append(Effect(EffectType.STUN, 1, 0, character))
        target.current_speed = max(0, target.current_speed - 5)
        message = f"｢{character.name}｣ pressurizes {target.name}! Stunned and -5 speed!"
    else:
        message = f"｢{character.name}｣ builds pressure..."
    return payload, message


def space_trucking(
    character: "Character", allied_characters: List["Character"], enemy_characters: List["Character"]
) -> tuple:
    payload = get_payload()
    valid = [e for e in enemy_characters if e.is_alive()]
    total_dmg = 0
    for enemy in valid:
        dmg = character.attack(enemy, multiplier=0.6)["damage"]
        total_dmg += dmg
    character.current_speed += 3
    message = f"｢{character.name}｣ extends its arms! {int(total_dmg)} AOE damage and +3 speed!"
    return payload, message


"""
def tusk_act_3_stub(
    character: "Character", allied_characters: List["Character"], enemy_characters: List["Character"]
) -> tuple:
    payload = get_payload()
    # Whatever your code does to the lists above
    # Payload Contain behavior change to the game
    # message is what should be printed to the embed
    return payload, message


def scary_monster(
    character: "Character", allied_characters: List["Character"], enemy_characters: List["Character"]
) -> tuple:
    payload = get_payload()
    # Whatever your code does to the lists above
    # Payload Contain behavior change to the game
    # message is what should be printed to the embed
    return payload, message


def in_a_silent_way(
    character: "Character", allied_characters: List["Character"], enemy_characters: List["Character"]
) -> tuple:
    payload = get_payload()
    # Whatever your code does to the lists above
    # Payload Contain behavior change to the game
    # message is what should be printed to the embed
    return payload, message


def tomb_of_boom(
    character: "Character", allied_characters: List["Character"], enemy_characters: List["Character"]
) -> tuple:
    payload = get_payload()
    # Whatever your code does to the lists above
    # Payload Contain behavior change to the game
    # message is what should be printed to the embed
    return payload, message


def wired(
    character: "Character", allied_characters: List["Character"], enemy_characters: List["Character"]
) -> tuple:
    payload = get_payload()
    # Whatever your code does to the lists above
    # Payload Contain behavior change to the game
    # message is what should be printed to the embed
    return payload, message


def catch_the_rainbow(
    character: "Character", allied_characters: List["Character"], enemy_characters: List["Character"]
) -> tuple:
    payload = get_payload()
    # Whatever your code does to the lists above
    # Payload Contain behavior change to the game
    # message is what should be printed to the embed
    return payload, message


def civil_war(
    character: "Character", allied_characters: List["Character"], enemy_characters: List["Character"]
) -> tuple:
    payload = get_payload()
    # Whatever your code does to the lists above
    # Payload Contain behavior change to the game
    # message is what should be printed to the embed
    return payload, message


def paisley_park(
    character: "Character", allied_characters: List["Character"], enemy_characters: List["Character"]
) -> tuple:
    payload = get_payload()
    # Whatever your code does to the lists above
    # Payload Contain behavior change to the game
    # message is what should be printed to the embed
    return payload, message


def nut_king_call(
    character: "Character", allied_characters: List["Character"], enemy_characters: List["Character"]
) -> tuple:
    payload = get_payload()
    # Whatever your code does to the lists above
    # Payload Contain behavior change to the game
    # message is what should be printed to the embed
    return payload, message


def speed_king(
    character: "Character", allied_characters: List["Character"], enemy_characters: List["Character"]
) -> tuple:
    payload = get_payload()
    # Whatever your code does to the lists above
    # Payload Contain behavior change to the game
    # message is what should be printed to the embed
    return payload, message


def fun_fun_fun(
    character: "Character", allied_characters: List["Character"], enemy_characters: List["Character"]
) -> tuple:
    payload = get_payload()
    # Whatever your code does to the lists above
    # Payload Contain behavior change to the game
    # message is what should be printed to the embed
    return payload, message


def born_this_way(
    character: "Character", allied_characters: List["Character"], enemy_characters: List["Character"]
) -> tuple:
    payload = get_payload()
    # Whatever your code does to the lists above
    # Payload Contain behavior change to the game
    # message is what should be printed to the embed
    return payload, message


def i_am_a_rock(
    character: "Character", allied_characters: List["Character"], enemy_characters: List["Character"]
) -> tuple:
    payload = get_payload()
    # Whatever your code does to the lists above
    # Payload Contain behavior change to the game
    # message is what should be printed to the embed
    return payload, message


def blue_hawaii(
    character: "Character", allied_characters: List["Character"], enemy_characters: List["Character"]
) -> tuple:
    payload = get_payload()
    # Whatever your code does to the lists above
    # Payload Contain behavior change to the game
    # message is what should be printed to the embed
    return payload, message


def ozon_baby(
    character: "Character", allied_characters: List["Character"], enemy_characters: List["Character"]
) -> tuple:
    payload = get_payload()
    # Whatever your code does to the lists above
    # Payload Contain behavior change to the game
    # message is what should be printed to the embed
    return payload, message


def doctor_wu(
    character: "Character", allied_characters: List["Character"], enemy_characters: List["Character"]
) -> tuple:
    payload = get_payload()
    # Whatever your code does to the lists above
    # Payload Contain behavior change to the game
    # message is what should be printed to the embed
    return payload, message


def space_trucking(
    character: "Character", allied_characters: List["Character"], enemy_characters: List["Character"]
) -> tuple:
    payload = get_payload()
    # Whatever your code does to the lists above
    # Payload Contain behavior change to the game
    # message is what should be printed to the embed
    return payload, message


def empress(
    character: "Character", allied_characters: List["Character"], enemy_characters: List["Character"]
) -> tuple:
    payload = get_payload()
    # Whatever your code does to the lists above
    # Payload Contain behavior change to the game
    # message is what should be printed to the embed
    return payload, message
"""


def hermit_purple(
    character: "Character", allied_characters: List["Character"], enemy_characters: List["Character"]
) -> tuple:
    payload = get_payload()
    terrain = _terrain(character)
    valid_characters = [i for i in enemy_characters if i.is_alive()]
    if not valid_characters:
        message = f"｢{character.name}｣ lashes out!"
        return payload, message
    if terrain == Terrain.FROZEN:
        # Frozen: vines spread on ice — slow ALL enemies
        for target in valid_characters:
            target.effects.append(Effect(EffectType.SLOW, 2, 5, character))
        message = f"｢{character.name}｣ spreads vines across the ice! All enemies slowed!"
    else:
        target = max(valid_characters, key=lambda c: c.current_speed)
        target.effects.append(Effect(EffectType.SLOW, 2, 5, character))
        message = f"｢{character.name}｣ slows {target.name}!"
    return payload, message


def dark_blue_moon(
    character: "Character", allied_characters: List["Character"], enemy_characters: List["Character"]
) -> tuple:
    payload = get_payload()
    terrain = _terrain(character)
    valid_characters = [i for i in enemy_characters if i.is_alive()]
    if terrain == Terrain.OCEAN:
        # Ocean: massive speed surge + AoE damage to all enemies
        character.current_speed += 15
        total = 0
        for target in valid_characters:
            total += character.attack(target, multiplier=0.8)["damage"]
        message = f"｢{character.name}｣ dominates the ocean! +15 speed, {int(total)} AoE damage!"
    else:
        # Out of water: weaker, just hits slowed targets harder
        damage = 0
        for target in valid_characters:
            is_slowed = (
                EffectType.SLOW in [e.type for e in target.effects]
                or target.current_speed < target.start_speed
            )
            multiplier = 1.0 if is_slowed else 0.3
            damage += character.attack(target, multiplier=multiplier)["damage"]
        message = f"｢{character.name}｣ attacks for {int(damage)} damage!"
    return payload, message


def tower_of_grey(
    character: "Character", allied_characters: List["Character"], enemy_characters: List["Character"]
) -> tuple:
    payload = get_payload()
    character.current_speed += 20
    character.current_damage = max(1, character.current_damage - 15)
    message = f"｢{character.name}｣ moves at extreme speed but loses damage!"
    return payload, message


def strength(
    character: "Character", allied_characters: List["Character"], enemy_characters: List["Character"]
) -> tuple:
    payload = get_payload()
    heal = int((character.start_hp - character.current_hp) * 0.15)
    character.current_hp = min(character.start_hp, character.current_hp + heal)
    message = f"｢{character.name}｣ heals for {heal}!"
    return payload, message


def ebony_devil(
    character: "Character", allied_characters: List["Character"], enemy_characters: List["Character"]
) -> tuple:
    payload = get_payload()
    terrain = _terrain(character)
    damage_taken = character.start_hp - character.current_hp
    if terrain == Terrain.DESERT:
        # Desert: heat amplifies hatred — double scaling + burn a target
        power_gained = max(1, int(damage_taken * 0.2))
        character.current_damage += power_gained
        character.current_armor += power_gained
        valid = [e for e in enemy_characters if e.is_alive()]
        if valid:
            target = random.choice(valid)
            target.effects.append(Effect(EffectType.BURN, 2, power_gained, character))
            message = f"｢{character.name}｣ rages in the heat! +{power_gained} damage/armor, burns {target.name}!"
        else:
            message = f"｢{character.name}｣ rages in the heat! +{power_gained} damage and armor!"
    else:
        power_gained = max(1, int(damage_taken * 0.1))
        character.current_damage += power_gained
        character.current_armor += power_gained
        message = f"｢{character.name}｣ feeds on hatred! +{power_gained} damage and armor!"
    return payload, message


def yellow_temperance(
    character: "Character", allied_characters: List["Character"], enemy_characters: List["Character"]
) -> tuple:
    payload = get_payload()
    valid_characters = [i for i in enemy_characters if i.is_alive()]
    message = f"｢{character.name}｣ !"
    if valid_characters:
        target = max(valid_characters, key=lambda c: c.current_speed)
        target.effects.append(Effect(EffectType.SLOW, 2, 5, character))
        message = f"｢{character.name}｣ slows {target.name}!"
    return payload, message


def wheel_of_fortune(
    character: "Character", allied_characters: List["Character"], enemy_characters: List["Character"]
) -> tuple:
    payload = get_payload()
    speed_gain = 15
    for ally in [s for s in allied_characters if s.is_alive()]:
        ally.current_speed += speed_gain
    message = f"｢{character.name}｣ accelerates the whole team by {speed_gain} speed!"
    return payload, message


def the_lovers(
    character: "Character", allied_characters: List["Character"], enemy_characters: List["Character"]
) -> tuple:
    payload = get_payload()
    valid_characters = [i for i in enemy_characters if i.is_alive()]
    message = f"｢{character.name}｣ links souls!"
    if valid_characters:
        target = random.choice(valid_characters)
        target.current_hp = character.current_hp
        message = f"｢{character.name}｣ links with {target.name}, setting their HP to {int(character.current_hp)}!"
    return payload, message


def the_sun(
    character: "Character", allied_characters: List["Character"], enemy_characters: List["Character"]
) -> tuple:
    payload = get_payload()
    terrain = _terrain(character)
    if terrain == Terrain.DESERT:
        # Desert: scorching heat — slow + burn everyone
        for target in enemy_characters:
            target.effects.append(Effect(EffectType.SLOW, 2, 4, character))
            target.effects.append(Effect(EffectType.BURN, 2, character.current_damage * 0.25, character))
        message = f"｢{character.name}｣ scorches the desert! All enemies slowed and burning!"
    else:
        for target in enemy_characters:
            target.effects.append(Effect(EffectType.SLOW, 2, 2, character))
        message = f"｢{character.name}｣ shines brightly, slowing all enemies!"
    return payload, message


def judgement(
    character: "Character", allied_characters: List["Character"], enemy_characters: List["Character"]
) -> tuple:
    payload = get_payload()
    dead_allies = [i for i in allied_characters if not i.is_alive() and i != character]
    if dead_allies:
        revived = random.choice(dead_allies)
        revived.current_hp = 1
        message = f"｢{character.name}｣ creates a clay replica of {revived.name} with 1 HP!"
    else:
        message = f"｢{character.name}｣ waits for an ally to fall..."
        character.special_meter = 2
    return payload, message


def khnum(
    character: "Character", allied_characters: List["Character"], enemy_characters: List["Character"]
) -> tuple:
    payload = get_payload()
    valid_characters = [i for i in enemy_characters if i.is_alive()]
    message = f"｢{character.name}｣ takes on a disguise!"
    if valid_characters:
        target = random.choice(valid_characters)
        character.current_damage = max(character.current_damage, target.current_damage)
        character.current_speed = max(character.current_speed, target.current_speed)
        message = f"｢{character.name}｣ copies {target.name}'s power!"
    return payload, message


def tohth(
    character: "Character", allied_characters: List["Character"], enemy_characters: List["Character"]
) -> tuple:
    payload = get_payload()
    crit_gain = 5
    for ally in [s for s in allied_characters if s.is_alive()]:
        ally.current_critical += crit_gain
    message = f"｢{character.name}｣ predicts victory! All allies gain {crit_gain} critical!"
    return payload, message


def anubis(
    character: "Character", allied_characters: List["Character"], enemy_characters: List["Character"]
) -> tuple:
    payload = get_payload()
    valid_characters = [i for i in enemy_characters if i.is_alive()]
    message = f"｢{character.name}｣ possesses the enemy!"
    if valid_characters:
        controlled = random.choice(valid_characters)
        other_targets = [i for i in enemy_characters if i.is_alive() and i != controlled]
        target = random.choice(other_targets) if other_targets else controlled
        damage = controlled.attack(target)["damage"]
        message = f"｢{character.name}｣ forces {controlled.name} to attack {target.name} for {damage}!"
    return payload, message


def bastet(
    character: "Character", allied_characters: List["Character"], enemy_characters: List["Character"]
) -> tuple:
    payload = get_payload()
    valid_characters = [i for i in enemy_characters if i.is_alive()]
    message = f"｢{character.name}｣ magnetizes the enemy!"
    if valid_characters:
        target = min(valid_characters, key=lambda c: c.current_speed)
        target.effects.append(Effect(EffectType.STUN, 2, 0, character))
        message = f"｢{character.name}｣ stuns {target.name}!"
    return payload, message


def not_implemented(
    character: "Character", allied_characters: List["Character"], enemy_characters: List["Character"]
) -> tuple:
    payload = get_payload()
    message = f"｢{character.name}｣ has no power yet"
    payload["is_a_special"] = False
    return payload, message


specials = {
    "1": star_platinum,
    "2": magician_red,
    "3": hierophant_green,
    "4": hermit_purple,
    "5": the_fool,
    "6": silver_chariot,
    "7": dark_blue_moon,
    "8": tower_of_grey,
    "9": strength,
    "10": the_world,
    "11": ebony_devil,
    "12": yellow_temperance,
    "13": hanged_man,
    "14": emperor,
    "15": wheel_of_fortune,
    "16": justice,
    "17": the_lovers,
    "18": the_sun,
    "19": death_13,
    "20": judgement,
    "21": high_pristess,
    "22": geb,
    "23": khnum,
    "24": tohth,
    "25": anubis,
    "26": bastet,
    "27": horus,
    "28": atum,
    "29": osiris,
    "30": cream,
    "31": star_platinum_the_world,
    "32": crazy_diamond,
    "33": aqua_necklace,
    "34": the_hand,
    "35": bad_company,
    "36": echoes_act_0,
    "37": red_hot_chili_peper,
    "38": the_lock,
    "39": surface,
    "40": love_deluxe,
    "41": echoes_act_1,
    "42": echoes_act_2,
    "43": pearl_jam,
    "44": achtung_baby,
    "45": heavens_door,
    "46": ratt,
    "47": harvest,
    "48": cinderella,
    "49": killer_queen,
    "50": echoes_act_3,
    "51": atom_heart_father,
    "52": boy_ii_man,
    "53": highway_star,
    "54": stray_cat,
    "55": super_fly,
    "56": enigma,
    "57": cheap_trick,
    "58": killer_queen_bite_the_dust,
    "59": gold_experience,
    "60": sticky_finger,
    "61": black_sabbath,
    "62": moody_blues,
    "63": soft_machine,
    "64": sex_pistol,
    "65": kraft_work,
    "66": little_feet,
    "67": aerosmith,
    "68": man_in_the_miror,
    "69": purple_haze,
    "70": mr_president,
    "71": beach_boy,
    "72": the_grateful_dead,
    "73": baby_face,
    "74": white_album,
    "75": king_crimson,
    "76": clash,
    "77": talking_head,
    "78": notorious_big,
    "79": spice_girl,
    "80": metallica,
    "81": green_day,
    "82": oasis,
    "83": chariot_requiem,
    "84": gold_experience_requiem,
    "85": rolling_stones,
    "86": stone_free,
    "87": goo_goo_dolls,
    "88": manhattan_transfer,
    "89": kiss,
    "90": highway_to_hell,
    "91": burning_down_the_house,
    "92": foo_fighters,
    "93": marilyn_manson,
    "94": weather_report,
    "95": jumpin_jack_flash,
    "96": limp_bizkit,
    "97": diver_down,
    "98": planet_waves,
    "99": dragons_dream,
    "100": yo_yo_ma,
    "101": green_green_grass_home,
    "102": jail_house_lock,
    "103": bohemian_rhapsody,
    "104": sky_high,
    "105": underworld,
    "106": survivor,
    "107": whitesnake,
    "108": c_moon,
    "109": made_in_heaven,
    "110": the_world_over_heaven,
    "111": tusk_act_1,
    "112": tusk_act_2,
    "113": tusk_act_3,
    "114": tusk_act_4,
    "115": ball_breaker,
    "116": oh_lonesome_me,
    "117": scary_monsters,
    "118": cream_starter,
    "119": ticket_to_ride,
    "120": dirty_deed_done_dirt_cheap,
    "121": in_a_silent_way,
    "122": hey_ya,
    "123": tomb_of_boom,
    "124": boku_no_rythm_wo_kiitekure,
    "125": wired,
    "126": mandom,
    "127": catch_the_rainbow,
    "128": sugar_mountain,
    "129": tatoo_you,
    "130": tubular_bells,
    "131": twentieth_century_boy,
    "132": civil_war,
    "133": chocolate_disco,
    "134": the_world_sbr,
    "135": tomb_of_boom,
    "136": tomb_of_boom,
    "137": soft_and_wet,
    "138": paisley_park,
    "139": doggy_style,
    "140": nut_king_call,
    "141": paper_moon_king,
    "142": king_nothing,
    "143": speed_king,
    "144": fun_fun_fun,
    "145": california_king_bed,
    "146": born_this_way,
    "147": les_feuilles,
    "148": i_am_a_rock,
    "149": doobie_wah,
    "150": love_love_deluxe,
    "151": schott_key,
    "152": schott_key,
    "153": vitamine_c,
    "154": walking_heart,
    "155": milagro_man,
    "156": blue_hawaii,
    "157": brain_storm,
    "158": ozon_baby,
    "159": doctor_wu,
    "160": awaking_iii_leaves,
    "161": wonder_of_u,
    "162": space_trucking,
    "163": victorious_star_platinum,
    "164": dummy,
}
