"""Stand specials.

Balance rules every special follows:
- Damage goes through character.attack (scales with damage, armor, crit, dodge)
  or is a share of a stat (true damage via target.take).
- Heals are a share of max health and go through target.heal, which caps at max.
- Buffs and debuffs are a share of the stat and temporary (effects); permanent
  self-growth uses character.grow, which stops at +100% of the starting stat.
- Single-target specials hit the stand's focus: the enemy it attacked this turn.
- Durations count the affected stand's own turns.
"""
import random


from typing import TYPE_CHECKING, List, Optional


from app.game.effects import Effect, EffectType, NEGATIVE_EFFECTS, POSITIVE_EFFECTS, Terrain

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
    # Joestar bloodline: every JoJo's Stand, across the parts
    "joestar": {1, 4, 31, 32, 59, 84, 86, 111, 112, 113, 114, 137, 163},
    # DIO's Tarot assassins (Part 3)
    "tarot": {7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21},
    # The Egyptian Nine Glory Gods (Part 3)
    "nine_gods": {22, 23, 24, 25, 26, 27, 28, 29},
    # Echoes, act by act (Koichi)
    "echoes": {36, 41, 42, 50},
    # Jolyne's crew (Part 6)
    "stone_ocean": {86, 92, 94, 97},
    # Steel Ball Run racers (Part 7)
    "sbr_racers": {111, 112, 113, 114, 115, 116, 117, 121, 122, 134},
    # Valentine's agents (Part 7)
    "president": {118, 120, 123, 124, 125, 126, 127, 129, 130, 131, 132, 133, 135, 136},
    # The Boom Boom family (Part 7)
    "boom_boom": {123, 135, 136},
    # Gappy and Yasuho (Part 8)
    "wall_eyes": {137, 138},
    # Stands that stop, skip, rewind or rush time
    "time_masters": {10, 31, 58, 75, 109, 110, 126, 134, 163},
    # Requiem duo
    "requiem": {83, 84},
}

# (label, icon) for the wiki, cards and the fight log
SYNERGY_INFO = {
    "crusaders": ("Stardust Crusaders", "⭐"),
    "kira": ("Kira duo", "💣"),
    "squadra": ("La Squadra", "🗡️"),
    "passione": ("Passione", "🐞"),
    "morioh": ("Morioh Warriors", "🏘️"),
    "pucci": ("Pucci evolution", "☽"),
    "tusk": ("Tusk evolution", "✦"),
    "clash_talking": ("Clash + Talking Head", "🦈"),
    "joestar": ("Joestar bloodline", "⭑"),
    "tarot": ("DIO's Tarot", "🃏"),
    "nine_gods": ("Nine Glory Gods", "𓂀"),
    "echoes": ("Echoes acts", "💬"),
    "stone_ocean": ("Jolyne's crew", "🦋"),
    "sbr_racers": ("Steel Ball Run racers", "🐎"),
    "president": ("Valentine's agents", "🇺🇸"),
    "boom_boom": ("Boom Boom family", "🧲"),
    "wall_eyes": ("Wall Eyes duo", "🫧"),
    "time_masters": ("Masters of time", "⏱️"),
    "requiem": ("Requiem", "🏹"),
}

# Team bonus: every member of a group gets these for the whole fight while 2+ members are on the team
# (fallen ones count). It comes on top of the special upgrades some members get (_has_synergy).
# stats: "damage_pct", "armor_pct", "speed_pct", "hp_pct" (shares of the stat), "crit_flat" (points)
SYNERGY_BONUS = {
    "crusaders": [("damage_pct", 0.08), ("speed_pct", 0.08)],
    "kira": [("damage_pct", 0.08), ("crit_flat", 10)],
    "squadra": [("damage_pct", 0.12)],
    "passione": [("speed_pct", 0.10), ("hp_pct", 0.06)],
    "morioh": [("armor_pct", 0.10), ("hp_pct", 0.08)],
    "pucci": [("speed_pct", 0.12)],
    "tusk": [("damage_pct", 0.06), ("crit_flat", 8)],
    "clash_talking": [("speed_pct", 0.12)],
    "joestar": [("hp_pct", 0.08), ("damage_pct", 0.06)],
    "tarot": [("damage_pct", 0.08)],
    "nine_gods": [("armor_pct", 0.10), ("crit_flat", 5)],
    "echoes": [("crit_flat", 10)],
    "stone_ocean": [("hp_pct", 0.08), ("armor_pct", 0.08)],
    "sbr_racers": [("speed_pct", 0.12)],
    "president": [("armor_pct", 0.08), ("damage_pct", 0.06)],
    "boom_boom": [("damage_pct", 0.12)],
    "wall_eyes": [("hp_pct", 0.10), ("speed_pct", 0.08)],
    "time_masters": [("speed_pct", 0.08), ("crit_flat", 8)],
    "requiem": [("damage_pct", 0.15)],
}


def _has_synergy(character_id: int, allied_characters: list, synergy_name: str) -> bool:
    """Check if character_id has at least one OTHER ally from the named synergy group."""
    group = SYNERGIES.get(synergy_name, set())
    if character_id not in group:
        return False
    ids = _ally_ids(allied_characters)
    # Need at least one OTHER member present
    return len(group & ids) >= 2


def active_synergies(team: list) -> list:
    """Names of the synergy groups with 2+ members on this team."""
    ids = _ally_ids(team)
    return [name for name, group in SYNERGIES.items() if len(group & ids) >= 2]


def apply_synergy_bonuses(team: list) -> list:
    """Give each member of an active group its team bonus, once per fighter (tower teams fight many floors).
    Returns [(group name, [member names])] for the fight log."""
    out = []
    for name in active_synergies(team):
        members = [c for c in team if c.id in SYNERGIES[name] and not getattr(c, "_synergy_done", False)]
        for c in members:
            for stat, value in SYNERGY_BONUS.get(name, []):
                if stat == "hp_pct":
                    added = int(c.start_hp * value)
                    c.start_hp += added
                    c.current_hp += added if c.current_hp > 0 else 0
                elif stat == "crit_flat":
                    c.current_critical += value
                else:
                    attr = {"damage_pct": "current_damage", "armor_pct": "current_armor",
                            "speed_pct": "current_speed"}[stat]
                    setattr(c, attr, getattr(c, attr) * (1 + value))
        if members:
            out.append((name, [c.name for c in members]))
    for c in team:
        c._synergy_done = True
    return out


# ── Special power: what a special scales with ────────────────────────────
# Every special scales with one stat. Its power multiplies the special's hits, damage over time,
# buffs, debuffs, true damage and growth (and heals, for health and armor specials):
#   power = (1 + investment) x (1 + type affinity), kept within POWER_RANGE
# investment: how far the build lifts the stat above the stand's natural value (no items, no types).
#   It reads the starting stats, so a special that buffs its own stat can't snowball. Damage specials
#   skip it: their hits already use the damage stat.
# affinity: the stand has the type that matches the stat (ATTACK damage, DEFENSE armor, HEALTH health,
#   SPEED speed, LUCK crit); the better its quality, the bigger. BALANCE gives half, for any stat.
STAT_INFO = {"damage": ("⚔️", "Damage", "ATTACK"), "armor": ("🛡️", "Armor", "DEFENSE"),
             "health": ("❤️", "Health", "HEALTH"), "speed": ("💨", "Speed", "SPEED"),
             "critical": ("🍀", "Luck", "LUCK")}
AFFINITY = {"UNIVERSAL": 0.25, "SUPREME": 0.18, "GREAT": 0.12, "GOOD": 0.06, "SUB_PAR": 0.0, "BAD": -0.06}
POWER_RANGE = (0.6, 2.5)
DEBUFF_CAP = 0.75
HEALING_STATS = ("health",)
ARMOR_BASE = 100
AFFINITY_SHARE = {}  # every stat has its own type now (HEALTH powers health specials)


def _invest(stat: str, char, natural: dict) -> float:
    if stat == "armor":
        return 0.0  # armor buffs are a share of starting armor: DEFENSE already grows them
    if stat == "health":
        return 0.5 * (char.start_hp / max(1, natural["hp"]) - 1)
    if stat == "speed":
        return 0.02 * (char.start_speed - natural["speed"])
    if stat == "critical":
        return 0.012 * (char.start_critical - natural["critical"])
    return 0.0


def scaling_of(char_id) -> str:
    return SCALING.get(int(char_id), "damage")


def special_power(char) -> dict:
    """{"stat", "power", "invest", "affinity", "type"} for the stand as it is right now."""
    from app.game.character import natural_stats
    stat = scaling_of(char.id)
    invest = _invest(stat, char, natural_stats(char))
    wanted = STAT_INFO[stat][2]
    affinity, via = 0.0, None
    for type_, quality in zip(char.types, char.qualities):
        bonus = (AFFINITY.get(quality, 0.0) * AFFINITY_SHARE.get(stat, 1)
                 * (1 if type_ == wanted else 0.5 if type_ == "BALANCE" else 0))
        if (type_ == wanted or type_ == "BALANCE") and (via is None or bonus > affinity):
            affinity, via = bonus, f"{type_.title()} {quality.replace('_', ' ').title()}"
    lo, hi = POWER_RANGE
    power = max(lo, min(hi, (1 + invest) * (1 + affinity)))
    return {"stat": stat, "power": power, "invest": invest, "affinity": affinity, "type": via}


_CTX = {"caster": None, "power": 1.0, "stat": "damage"}


def begin_special(char) -> dict:
    info = special_power(char)
    _CTX.update(caster=char, power=info["power"], stat=info["stat"])
    return info


def end_special():
    _CTX.update(caster=None, power=1.0, stat="damage")


def _power(heal: bool = False) -> float:
    if heal and _CTX["stat"] not in HEALING_STATS:
        return 1.0  # a damage stand's lifesteal already grew with its hit
    return _CTX["power"]


# ── Helpers ─────────────────────────────────────────────────────────────

def _alive(chars: list) -> list:
    return [c for c in chars if c.is_alive()]


def _target(character: "Character", enemies: list) -> Optional["Character"]:
    """The enemy this stand attacked this turn, or a random living one."""
    focus = getattr(character, "_focus", None)
    if focus is not None and focus in enemies and focus.is_alive():
        return focus
    valid = _alive(enemies)
    return random.choice(valid) if valid else None


def _weakest(chars: list) -> Optional["Character"]:
    """Living stand with the lowest share of its health."""
    valid = _alive(chars)
    return min(valid, key=lambda c: c.current_hp / max(1, c.start_hp)) if valid else None


def _impaired(c: "Character") -> bool:
    types = [e.type for e in c.effects]
    return EffectType.STUN in types or EffectType.SLOW in types or c.current_speed < c.start_speed


def _hit(character, target, multiplier, pierce=False) -> int:
    return character.attack(target, multiplier=multiplier * _power(), pierce=pierce)["damage"]


def _aoe(character, enemies, multiplier) -> int:
    return sum(_hit(character, e, multiplier) for e in _alive(enemies))


def _dot(target, kind: EffectType, turns: int, value: float, sender) -> None:
    target.add_effect(Effect(kind, turns, max(1, int(value * _power())), sender))


def _regen(target, turns: int, value: float, sender) -> None:
    target.add_effect(Effect(EffectType.REGENERATION, turns, value * _power(heal=True), sender))


def _heal(target, amount: float) -> int:
    return target.heal(amount * _power(heal=True))


def _take(target, amount: float) -> int:
    """True damage from a special; what the caster pays itself is never scaled."""
    return target.take(amount if target is _CTX["caster"] else amount * _power())


def _grow(target, stat: str, pct: float) -> float:
    return target.grow(stat, pct * _power())


def _stun(target, sender, turns: int = 1) -> None:
    target.add_effect(Effect(EffectType.STUN, turns, 0, sender))


_STAT_UP = {"damage": EffectType.DAMAGEUP, "speed": EffectType.SPEEDUP, "armor": EffectType.ARMORUP,
            "critical": EffectType.CRITUP}
_STAT_DOWN = {"damage": EffectType.WEAKEN, "speed": EffectType.SLOW, "armor": EffectType.ARMORBREAK}


# Base speeds are small (mostly 0-15), so speed changes move at least pct x SPEED_FLOOR points:
# +25% speed is always worth a few points of dodge.
SPEED_FLOOR = 20


def _buff(target, stat: str, pct: float, turns: int, sender) -> int:
    """Temporary +pct of the starting stat (critical: pct is flat points)."""
    pct *= _power()
    # armor buffs are points of the natural 100 armor, so DEFENSE's x1.4 doesn't count twice
    value = pct if stat == "critical" else ARMOR_BASE * pct if stat == "armor" else getattr(target, f"start_{stat}") * pct
    if stat == "speed":
        value = max(value, pct * SPEED_FLOOR)
    target.add_effect(Effect(_STAT_UP[stat], turns, value, sender))
    return round(value)


def _debuff(target, stat: str, pct: float, turns: int, sender) -> int:
    """Temporary -pct of the current stat."""
    pct = min(DEBUFF_CAP, pct * _power())
    value = getattr(target, f"current_{stat}") * pct
    if stat == "speed":
        value = max(value, pct * SPEED_FLOOR)
    return round(target.add_effect(Effect(_STAT_DOWN[stat], turns, value, sender)).value)


def _cleanse(target) -> None:
    """Remove negative effects, undoing their stat changes."""
    from app.game.effects import STAT_EFFECTS
    kept = []
    for e in target.effects:
        if e.type not in NEGATIVE_EFFECTS:
            kept.append(e)
        elif e.type in STAT_EFFECTS and e.used:
            attr, sign = STAT_EFFECTS[e.type]
            setattr(target, attr, getattr(target, attr) - sign * e.value)
    target.effects = kept


def _purge(target) -> None:
    """Remove positive effects, undoing their stat changes."""
    from app.game.effects import STAT_EFFECTS
    kept = []
    for e in target.effects:
        if e.type not in POSITIVE_EFFECTS:
            kept.append(e)
        elif e.type in STAT_EFFECTS and e.used:
            attr, sign = STAT_EFFECTS[e.type]
            setattr(target, attr, getattr(target, attr) - sign * e.value)
    target.effects = kept


def _pct(x: float) -> str:
    return f"{round(x * 100)}%"


def _time_stop(character, enemies, multiplier=0.75) -> tuple:
    payload = get_payload()
    damage = _aoe(character, enemies, multiplier)
    return payload, f"｢{character.name}｣ STOPS TIME and hits every enemy for {damage} total!"


"""

name your fonction to the character

def special_boiler_plate(character:"Character",allied_characters:List["Character"],enemy_characters:List["Character"])->tuple:
    payload = get_payload()
    #Whatever your code does to the lists above
    #Payload Contain behavior change to the game
    #message is what should be printed to the embed
    return payload,message

"""


# ── Part 3 ──────────────────────────────────────────────────────────────

def the_world_over_heaven(character, allied_characters, enemy_characters) -> tuple:
    payload = get_payload()
    damage = _aoe(character, enemy_characters, 1000)
    return payload, f"｢{character.name}｣! damaged everyone for {damage}!"


def star_platinum(character, allied_characters, enemy_characters) -> tuple:
    payload = get_payload()
    synergy = _has_synergy(character.id, allied_characters, "crusaders")
    target = _target(character, enemy_characters)
    if not target:
        return payload, f"｢{character.name}｣ punches the air!"
    hits = random.randint(2, 4) + (1 if synergy else 0)
    damage = sum(_hit(character, target, 0.45) for _ in range(hits) if target.is_alive())
    message = f"｢{character.name}｣ ORA ORA! {hits} punches on {target.name} for {damage}!"
    if synergy:
        message += " ⭐ Crusaders synergy!"
    return payload, message


def magician_red(character, allied_characters, enemy_characters) -> tuple:
    payload = get_payload()
    synergy = _has_synergy(character.id, allied_characters, "crusaders")
    valid = _alive(enemy_characters)
    if not valid:
        return payload, f"｢{character.name}｣ releases flames!"
    if synergy:
        for target in valid:
            _dot(target, EffectType.BURN, 2, 0.4 * character.current_damage, character)
        return payload, f"｢{character.name}｣ unleashes Crossfire Hurricane: every enemy burns for 2 turns! ⭐ Crusaders synergy!"
    target = _target(character, enemy_characters)
    damage = _hit(character, target, 0.7)
    _dot(target, EffectType.BURN, 2, 0.4 * character.current_damage, character)
    return payload, f"｢{character.name}｣ scorches {target.name} for {damage} and sets it ablaze for 2 turns!"


def hierophant_green(character, allied_characters, enemy_characters) -> tuple:
    payload = get_payload()
    synergy = _has_synergy(character.id, allied_characters, "crusaders")
    damage = _aoe(character, enemy_characters, 0.75 if synergy else 0.55)
    message = f"No one can deflect the Emerald Splash! {damage} damage to all!"
    if synergy:
        message += " ⭐ Crusaders synergy!"
    return payload, message


def hermit_purple(character, allied_characters, enemy_characters) -> tuple:
    payload = get_payload()
    terrain = _terrain(character)
    valid = _alive(enemy_characters)
    if not valid:
        return payload, f"｢{character.name}｣ lashes out!"
    if terrain == Terrain.FROZEN:
        for target in valid:
            _debuff(target, "speed", 0.25, 2, character)
            target.special_meter = max(0, target.special_meter - 1)
        return payload, f"｢{character.name}｣ spreads vines across the ice! Every enemy is slowed and its special delayed!"
    target = max(valid, key=lambda c: c.current_speed)
    _debuff(target, "speed", 0.25, 2, character)
    target.special_meter = max(0, target.special_meter - 1)
    damage = _hit(character, target, 0.7)
    return payload, f"｢{character.name}｣ divines {target.name}'s moves: {damage} damage, slowed, special delayed!"


def the_fool(character, allied_characters, enemy_characters) -> tuple:
    payload = get_payload()
    terrain = _terrain(character)
    target = _target(character, enemy_characters)
    if terrain == Terrain.DESERT:
        _grow(character, "armor", 0.20)
        damage = _hit(character, target, 1.0) if target else 0
        return payload, f"｢{character.name}｣ raises a sand fortress! +20% armor and a {damage} sand blast!"
    _grow(character, "armor", 0.08)
    damage = _hit(character, target, 0.5) if target else 0
    return payload, f"｢{character.name}｣ hardens its sand: +8% armor, {damage} damage!"


def silver_chariot(character, allied_characters, enemy_characters) -> tuple:
    payload = get_payload()
    synergy = _has_synergy(character.id, allied_characters, "crusaders")
    _buff(character, "speed", 0.40, 2, character)
    if not synergy:
        _debuff(character, "armor", 0.20, 2, character)
    target = _target(character, enemy_characters)
    damage = sum(_hit(character, target, 0.45) for _ in range(3) if target and target.is_alive()) if target else 0
    message = f"｢{character.name}｣ sheds its armor: +40% speed and a 3-hit rapier flurry for {damage}!"
    if synergy:
        message += " Keeps its armor! ⭐ Crusaders synergy!"
    return payload, message


def dark_blue_moon(character, allied_characters, enemy_characters) -> tuple:
    payload = get_payload()
    terrain = _terrain(character)
    if terrain == Terrain.OCEAN:
        _buff(character, "speed", 0.25, 2, character)
        damage = _aoe(character, enemy_characters, 0.6)
        return payload, f"｢{character.name}｣ dominates the ocean! +25% speed and {damage} damage to all!"
    damage = 0
    for target in _alive(enemy_characters):
        damage += _hit(character, target, 0.85 if _impaired(target) else 0.3)
    return payload, f"｢{character.name}｣ slashes with its scales for {damage}, hardest on slowed enemies!"


def tower_of_grey(character, allied_characters, enemy_characters) -> tuple:
    payload = get_payload()
    _buff(character, "speed", 0.50, 2, character)
    target = _weakest(enemy_characters)
    damage = _hit(character, target, 0.9) if target else 0
    return payload, f"｢{character.name}｣ darts at the weakest enemy{f', {target.name},' if target else ''} for {damage}! +50% speed!"


def strength(character, allied_characters, enemy_characters) -> tuple:
    payload = get_payload()
    healed = _heal(character, character.start_hp * 0.08)
    _buff(character, "armor", 0.20, 2, character)
    return payload, f"｢{character.name}｣ braces the ship: heals {healed} and gains +20% armor!"


def the_world(character, allied_characters, enemy_characters) -> tuple:
    return _time_stop(character, enemy_characters)


def ebony_devil(character, allied_characters, enemy_characters) -> tuple:
    payload = get_payload()
    terrain = _terrain(character)
    lost = 1 - character.current_hp / max(1, character.start_hp)
    rate = 0.6 if terrain == Terrain.DESERT else 0.4
    dmg = _grow(character, "damage", rate * lost)
    arm = _grow(character, "armor", rate * lost)
    target = _target(character, enemy_characters)
    hit = _hit(character, target, 0.8) if target else 0
    message = f"｢{character.name}｣ feeds on hatred and slashes for {hit}! +{round(dmg)} damage, +{round(arm)} armor"
    if terrain == Terrain.DESERT:
        if target and target.is_alive():
            _dot(target, EffectType.BURN, 2, 0.4 * character.current_damage, character)
            message += f" and burns {target.name} in the heat"
    return payload, message + "!"


def yellow_temperance(character, allied_characters, enemy_characters) -> tuple:
    payload = get_payload()
    _buff(character, "armor", 0.50, 2, character)
    healed = _heal(character, character.start_hp * 0.08)
    target = _target(character, enemy_characters)
    if target:
        _dot(target, EffectType.POISON, 2, 0.3 * character.current_damage, character)
    return payload, f"｢{character.name}｣ engulfs {target.name if target else 'nothing'}: +50% armor, heals {healed}, devours for 2 turns!"


def hanged_man(character, allied_characters, enemy_characters) -> tuple:
    payload = get_payload()
    terrain = _terrain(character)
    target = _target(character, enemy_characters)
    if terrain == Terrain.MIRROR:
        _buff(character, "critical", 25, 2, character)
        damage = _hit(character, target, 1.4, pierce=True) if target else 0
        return payload, f"｢{character.name}｣ strikes from every reflection for {damage}, ignoring armor! +25 crit!"
    _buff(character, "critical", 15, 2, character)
    damage = _hit(character, target, 0.9) if target else 0
    return payload, f"｢{character.name}｣ strikes from a reflection for {damage}! +15 crit!"


def emperor(character, allied_characters, enemy_characters) -> tuple:
    payload = get_payload()
    target = _target(character, enemy_characters)
    if not target:
        return payload, f"｢{character.name}｣ fires into the air!"
    damage = _hit(character, target, 2.2)
    return payload, f"｢{character.name}｣ headshot on {target.name} for {damage}!"


def wheel_of_fortune(character, allied_characters, enemy_characters) -> tuple:
    payload = get_payload()
    for ally in _alive(allied_characters):
        _buff(ally, "speed", 0.25, 2, character)
    target = _target(character, enemy_characters)
    damage = _hit(character, target, 1.1) if target else 0
    return payload, f"｢{character.name}｣ floors it! Team +25% speed, rams for {damage}!"


def justice(character, allied_characters, enemy_characters) -> tuple:
    payload = get_payload()
    damage = 0
    for enemy in _alive(enemy_characters):
        damage += _hit(character, enemy, 0.4)
        _debuff(enemy, "damage", 0.15, 2, character)
        _debuff(enemy, "speed", 0.15, 2, character)
    _buff(character, "speed", 0.30, 2, character)
    return payload, f"｢{character.name}｣'s fog puppets strike everyone for {damage}! Enemies -15% damage and speed!"


def the_lovers(character, allied_characters, enemy_characters) -> tuple:
    payload = get_payload()
    target = _target(character, enemy_characters)
    if not target:
        return payload, f"｢{character.name}｣ links souls!"
    pain = character.start_hp * 0.10 + (character.start_hp - character.current_hp) * 0.25
    dealt = _take(target, pain)
    return payload, f"｢{character.name}｣ links souls with {target.name} and shares its pain: {dealt} damage!"


def the_sun(character, allied_characters, enemy_characters) -> tuple:
    payload = get_payload()
    terrain = _terrain(character)
    hot = terrain == Terrain.DESERT
    for target in _alive(enemy_characters):
        _debuff(target, "speed", 0.20 if hot else 0.10, 2, character)
        _dot(target, EffectType.BURN, 2, (0.3 if hot else 0.15) * character.current_damage, character)
    if hot:
        return payload, f"｢{character.name}｣ scorches the desert! Every enemy slowed and burning!"
    return payload, f"｢{character.name}｣ blazes overhead, burning and slowing every enemy!"


def death_13(character, allied_characters, enemy_characters) -> tuple:
    payload = get_payload()
    damage, asleep = 0, 0
    for target in _alive(enemy_characters):
        if _impaired(target):
            damage += _hit(character, target, 1.8)
            asleep += 1
        else:
            damage += _hit(character, target, 0.5)
            _debuff(target, "speed", 0.20, 2, character)
    return payload, f"｢{character.name}｣ haunts their dreams for {damage}! ({asleep} defenceless)"


def judgement(character, allied_characters, enemy_characters) -> tuple:
    payload = get_payload()
    dead = [a for a in allied_characters if not a.is_alive() and a != character and not getattr(a, "_revived", False)]
    if dead:
        revived = random.choice(dead)
        revived.current_hp = int(revived.start_hp * 0.25)
        revived._revived = True
        return payload, f"｢{character.name}｣ grants a wish: {revived.name} returns with 25% health!"
    strongest = max(_alive(allied_characters), key=lambda c: c.current_damage)
    _buff(strongest, "damage", 0.25, 2, character)
    return payload, f"｢{character.name}｣ grants a wish: {strongest.name} +25% damage!"


def high_pristess(character, allied_characters, enemy_characters) -> tuple:
    payload = get_payload()
    _grow(character, "armor", 0.12)
    target = _target(character, enemy_characters)
    damage = _hit(character, target, 1.0) if target else 0
    return payload, f"｢{character.name}｣ becomes the floor and bites for {damage}! +12% armor!"


def geb(character, allied_characters, enemy_characters) -> tuple:
    payload = get_payload()
    terrain = _terrain(character)
    target = _target(character, enemy_characters)
    if not target:
        return payload, f"｢{character.name}｣ sneak attack!"
    if terrain == Terrain.OCEAN:
        damage = _hit(character, target, 2.0)
        _debuff(target, "speed", 0.20, 2, character)
        return payload, f"｢{character.name}｣ surges from the water! {damage} damage to {target.name} + slowed!"
    damage = _hit(character, target, 1.6)
    return payload, f"｢{character.name}｣ sneak attacks {target.name} for {damage}!"


def khnum(character, allied_characters, enemy_characters) -> tuple:
    payload = get_payload()
    target = _target(character, enemy_characters)
    if not target:
        return payload, f"｢{character.name}｣ takes on a disguise!"
    dmg = max(0, target.current_damage - character.current_damage)
    spd = max(0, target.current_speed - character.current_speed)
    character.add_effect(Effect(EffectType.DAMAGEUP, 2, dmg, character))
    character.add_effect(Effect(EffectType.SPEEDUP, 2, spd, character))
    damage = _hit(character, target, 1.0)
    return payload, f"｢{character.name}｣ disguises as {target.name}, copies its power and strikes for {damage}!"


def tohth(character, allied_characters, enemy_characters) -> tuple:
    payload = get_payload()
    for ally in _alive(allied_characters):
        _buff(ally, "critical", 12, 2, character)
        _buff(ally, "damage", 0.15, 2, character)
    target = _target(character, enemy_characters)
    if target:
        target.special_meter = max(0, target.special_meter - 1)
    return payload, f"｢{character.name}｣ predicts the future! Team +12 crit and +15% damage, enemy special delayed!"


def anubis(character, allied_characters, enemy_characters) -> tuple:
    payload = get_payload()
    valid = _alive(enemy_characters)
    if not valid:
        return payload, f"｢{character.name}｣ possesses the enemy!"
    controlled = _target(character, enemy_characters)
    others = [c for c in valid if c != controlled]
    if others:
        target = random.choice(others)
        damage = _hit(controlled, target, 1.0)
        return payload, f"｢{character.name}｣ possesses {controlled.name}, who slashes {target.name} for {damage}!"
    damage = _hit(character, controlled, 1.5)
    return payload, f"｢{character.name}｣ cuts {controlled.name} for {damage}!"


def bastet(character, allied_characters, enemy_characters) -> tuple:
    payload = get_payload()
    valid = _alive(enemy_characters)
    if not valid:
        return payload, f"｢{character.name}｣ magnetizes the enemy!"
    target = min(valid, key=lambda c: c.current_speed)
    _stun(target, character)
    damage = _hit(character, target, 0.4)
    return payload, f"｢{character.name}｣ magnetizes {target.name}: {damage} damage and stunned!"


def horus(character, allied_characters, enemy_characters) -> tuple:
    payload = get_payload()
    target = _target(character, enemy_characters)
    if not target:
        return payload, f"｢{character.name}｣!"
    damage = _hit(character, target, 1.0)
    _stun(target, character)
    return payload, f"｢{character.name}｣ impales {target.name} with ice for {damage} and freezes it!"


def atum(character, allied_characters, enemy_characters) -> tuple:
    payload = get_payload()
    target = _target(character, enemy_characters)
    if not target:
        return payload, f"｢{character.name}｣ rolls the dice"
    roll = random.randint(1, 6)
    damage = _hit(character, target, 0.4 * roll)
    return payload, f"｢{character.name}｣ reads {target.name}'s soul and rolls a {roll}: {damage} damage!"


def osiris(character, allied_characters, enemy_characters) -> tuple:
    payload = get_payload()
    target = _target(character, enemy_characters)
    if not target:
        return payload, f"｢{character.name}｣ rolls the dice"
    roll = random.randint(1, 6)
    damage = _hit(character, target, 0.35 * roll)
    healed = _heal(character, damage * 0.5)
    return payload, f"｢{character.name}｣ wagers {target.name}'s soul on a {roll}: {damage} damage, heals {healed}!"


def cream(character, allied_characters, enemy_characters) -> tuple:
    payload = get_payload()
    damage = sum(_hit(character, e, 0.9, pierce=True) for e in _alive(enemy_characters))
    _stun(character, character)
    return payload, f"｢{character.name}｣ devours space: {damage} damage to all, ignoring armor! It vanishes for a turn."


def star_platinum_the_world(character, allied_characters, enemy_characters) -> tuple:
    return _time_stop(character, enemy_characters)


# ── Part 4 ──────────────────────────────────────────────────────────────

def crazy_diamond(character, allied_characters, enemy_characters) -> tuple:
    payload = get_payload()
    ally = _weakest(allied_characters)
    if ally and ally.current_hp < ally.start_hp:
        healed = _heal(ally, ally.start_hp * 0.25)
        _cleanse(ally)
        return payload, f"｢{character.name}｣ restores {ally.name}: +{healed} health, debuffs cleared!"
    target = _target(character, enemy_characters)
    damage = _hit(character, target, 1.5) if target else 0
    return payload, f"｢{character.name}｣ DORA! {damage} damage!"


def aqua_necklace(character, allied_characters, enemy_characters) -> tuple:
    payload = get_payload()
    target = _target(character, enemy_characters)
    if not target:
        return payload, f"｢{character.name}｣ strikes!"
    damage = _hit(character, target, 1.1)
    _debuff(target, "speed", 0.20, 2, character)
    return payload, f"｢{character.name}｣ slips inside {target.name} for {damage} and slows it!"


def the_hand(character, allied_characters, enemy_characters) -> tuple:
    payload = get_payload()
    target = _target(character, enemy_characters)
    if not target:
        return payload, f"｢{character.name}｣ erases the air!"
    damage = _hit(character, target, 1.4, pierce=True)
    _debuff(target, "armor", 0.30, 2, character)
    return payload, f"｢{character.name}｣ erases space through {target.name}: {damage} damage ignoring armor, -30% armor!"


def heavens_door(character, allied_characters, enemy_characters) -> tuple:
    payload = get_payload()
    target = _target(character, enemy_characters)
    if not target:
        return payload, f"｢{character.name}｣!"
    damage = _hit(character, target, 1.1)
    _stun(target, character)
    _debuff(target, "damage", 0.25, 2, character)
    return payload, f"｢{character.name}｣ writes in {target.name} ({damage} damage): “cannot attack”. Stunned and -25% damage!"


def killer_queen(character, allied_characters, enemy_characters) -> tuple:
    payload = get_payload()
    synergy = _has_synergy(character.id, allied_characters, "kira")
    valid = _alive(enemy_characters)
    if not valid:
        return payload, f"｢{character.name}｣!"
    if synergy:
        targets = random.sample(valid, min(2, len(valid)))
        damage = 0
        for target in targets:
            damage += _hit(character, target, 1.5)
            _dot(target, EffectType.BURN, 1, 0.3 * character.current_damage, character)
        names = " and ".join(t.name for t in targets)
        return payload, f"｢{character.name}｣ air-bubble bombs {names} for {damage}! 💣🐈 Kira synergy!"
    target = _target(character, enemy_characters)
    damage = _hit(character, target, 1.9)
    return payload, f"｢{character.name}｣ detonates {target.name} for {damage}!"


def echoes_act_3(character, allied_characters, enemy_characters) -> tuple:
    payload = get_payload()
    target = _target(character, enemy_characters)
    if not target:
        return payload, f"｢{character.name}｣!"
    damage = _hit(character, target, 1.0)
    _stun(target, character)
    for other in _alive(enemy_characters):
        if other != target:
            _debuff(other, "speed", 0.20, 2, character)
    return payload, f"｢{character.name}｣ 3 FREEZE! {target.name} is pinned down for {damage}, the others slowed!"


DUMMY_HEAL = 0.03  # 2-8% all play the same: only a team that outlasts sudden death wins


def dummy(character, allied_characters, enemy_characters) -> tuple:
    """The practice dummy shrugs a little off each turn: sudden death can wear it down (an achievement)."""
    payload = get_payload()
    healed = character.heal(character.start_hp * DUMMY_HEAL)
    return payload, f"｢{character.name}｣ shrugs it off and patches {healed:,} health."


def killer_queen_bite_the_dust(character, allied_characters, enemy_characters) -> tuple:
    payload = get_payload()
    healed = sum(_heal(a, (a.start_hp - a.current_hp) * 0.3) for a in _alive(allied_characters))
    target = _target(character, enemy_characters)
    damage = _hit(character, target, 1.5) if target else 0
    return payload, f"｢{character.name}｣ Bites the Dust: rewinds {healed} health for the team and blows up {target.name if target else 'nothing'} for {damage}!"


def bad_company(character, allied_characters, enemy_characters) -> tuple:
    payload = get_payload()
    units = len(_alive(allied_characters))
    target = _target(character, enemy_characters)
    if not target:
        return payload, f"｢{character.name}｣ deploys the troops!"
    damage = _hit(character, target, 0.5 + 0.55 * units)
    return payload, f"｢{character.name}｣ deploys {units} squads! {target.name} takes {damage}!"


def echoes_act_0(character, allied_characters, enemy_characters) -> tuple:
    payload = get_payload()
    healed = _heal(character, character.start_hp * 0.10)
    grown = _grow(character, "damage", 0.10)
    target = _target(character, enemy_characters)
    damage = _hit(character, target, 0.5) if target else 0
    return payload, f"｢{character.name}｣ is about to hatch... heals {healed}, +{round(grown)} damage, pecks for {damage}!"


def red_hot_chili_peper(character, allied_characters, enemy_characters) -> tuple:
    payload = get_payload()
    target = _target(character, enemy_characters)
    damage = _hit(character, target, 1.3) if target else 0
    _buff(character, "speed", 0.30, 2, character)
    return payload, f"｢{character.name}｣ rides the power lines: {damage} damage and +30% speed!"


def the_lock(character, allied_characters, enemy_characters) -> tuple:
    payload = get_payload()
    lost = 1 - character.current_hp / max(1, character.start_hp)
    for enemy in _alive(enemy_characters):
        _debuff(enemy, "speed", 0.20, 2, character)
    target = _target(character, enemy_characters)
    if not target:
        return payload, f"｢{character.name}｣'s guilt weighs on everyone!"
    _debuff(target, "damage", 0.25 + 0.3 * lost, 2, character)
    _hit(character, target, 0.7)
    _dot(target, EffectType.BLEED, 2, 0.5 * character.current_damage, character)
    return payload, f"｢{character.name}｣'s guilt weighs on everyone! Enemies slowed; {target.name} weakened and bleeding!"


def surface(character, allied_characters, enemy_characters) -> tuple:
    payload = get_payload()
    valid = _alive(enemy_characters)
    if not valid:
        return payload, f"｢{character.name}｣ takes control!"
    controlled = _target(character, enemy_characters)
    others = [c for c in valid if c != controlled]
    if others:
        target = random.choice(others)
        damage = _hit(controlled, target, 1.4)
        return payload, f"｢{character.name}｣ mimics {controlled.name} into hitting {target.name} for {damage}!"
    damage = _hit(controlled, controlled, 0.6)
    return payload, f"｢{character.name}｣ makes {controlled.name} hurt itself for {damage}!"


def love_deluxe(character, allied_characters, enemy_characters) -> tuple:
    payload = get_payload()
    target = _target(character, enemy_characters)
    if not target:
        return payload, f"｢{character.name}｣ extends her hair!"
    damage = _hit(character, target, 0.8)
    if target.current_speed > character.current_speed:
        _debuff(target, "speed", 0.35, 2, character)
        return payload, f"｢{character.name}｣ tangles {target.name}'s legs: {damage} damage, -35% speed!"
    _stun(target, character)
    return payload, f"｢{character.name}｣ wraps around {target.name}: {damage} damage, stunned!"


def echoes_act_1(character, allied_characters, enemy_characters) -> tuple:
    payload = get_payload()
    target = _target(character, enemy_characters)
    if not target:
        return payload, f"｢{character.name}｣ creates a sound!"
    damage = _hit(character, target, 1.0)
    _debuff(target, "speed", 0.15, 2, character)
    return payload, f"｢{character.name}｣ sticks a sound on {target.name}: {damage} damage and slowed!"


def echoes_act_2(character, allied_characters, enemy_characters) -> tuple:
    payload = get_payload()
    damage = 0
    for enemy in _alive(enemy_characters):
        damage += _hit(character, enemy, 0.75)
        _debuff(enemy, "speed", 0.25, 2, character)
    return payload, f"｢{character.name}｣ plants sound words on everyone: {damage} damage, all slowed!"


def pearl_jam(character, allied_characters, enemy_characters) -> tuple:
    payload = get_payload()
    terrain = _terrain(character)
    fresh = terrain == Terrain.NATURE
    healed = 0
    for ally in _alive(allied_characters):
        healed += _heal(ally, ally.start_hp * (0.12 if fresh else 0.08))
        _cleanse(ally)
        if fresh:
            _regen(ally, 2, ally.start_hp * 0.03, character)
    if fresh:
        return payload, f"｢{character.name}｣ cooks with fresh ingredients! Team heals {healed} + regen, debuffs cleared!"
    return payload, f"｢{character.name}｣ cooks a healing meal! Team heals {healed}, debuffs cleared!"


def achtung_baby(character, allied_characters, enemy_characters) -> tuple:
    payload = get_payload()
    terrain = _terrain(character)
    allies = [a for a in _alive(allied_characters) if a != character]
    target = max(allies, key=lambda c: c.current_damage) if allies else character
    mirror = terrain == Terrain.MIRROR
    _buff(target, "speed", 0.60, 2, character)
    _buff(target, "critical", 15, 2, character)
    _buff(target, "damage", 0.40 if mirror else 0.25, 2, character)
    _hit(character, _target(character, enemy_characters), 0.6) if _target(character, enemy_characters) else 0
    if mirror:
        return payload, f"｢{character.name}｣ bends light in the mirror world! {target.name} +60% speed, +15 crit, +40% damage!"
    return payload, f"｢{character.name}｣ makes {target.name} invisible! +60% speed, +15 crit, +25% damage!"


def ratt(character, allied_characters, enemy_characters) -> tuple:
    payload = get_payload()
    target = _target(character, enemy_characters)
    if not target:
        return payload, f"｢{character.name}｣ fires a dart!"
    damage = _hit(character, target, 0.8)
    _dot(target, EffectType.POISON, 3, 0.4 * character.current_damage, character)
    return payload, f"｢{character.name}｣ darts {target.name} for {damage}, melting it for 3 turns!"


def harvest(character, allied_characters, enemy_characters) -> tuple:
    payload = get_payload()
    terrain = _terrain(character)
    rich = terrain == Terrain.NATURE
    collected = []
    for ally in _alive(allied_characters):
        stat = random.choice(["damage", "speed", "armor", "critical"])
        amount = random.randint(15, 25) if stat == "critical" else random.uniform(0.20, 0.30)
        if rich:
            amount *= 1.6
        _buff(ally, stat, amount, 3, character)
        collected.append(f"{ally.name} +{amount if stat == 'critical' else _pct(amount)} {stat}")
    prefix = "a bountiful harvest" if rich else "resources"
    return payload, f"｢{character.name}｣ collects {prefix}! {', '.join(collected)}!"


def cinderella(character, allied_characters, enemy_characters) -> tuple:
    payload = get_payload()
    healed = 0
    for ally in _alive(allied_characters):
        _buff(ally, "critical", 12, 2, character)
        _buff(ally, "damage", 0.15, 2, character)
        healed += _heal(ally, ally.start_hp * 0.08)
    return payload, f"｢{character.name}｣ gives everyone a lucky makeover! Team +12 crit, +15% damage, heals {healed}!"


def atom_heart_father(character, allied_characters, enemy_characters) -> tuple:
    payload = get_payload()
    allies = [a for a in _alive(allied_characters) if a != character]
    if allies:
        for ally in allies:
            _buff(ally, "damage", 0.20, 2, character)
        target = _target(character, enemy_characters)
        if target:
            _stun(target, character)
        return payload, f"｢{character.name}｣ traps {target.name if target else 'the enemy'} in a photo (stunned)! Allies +20% damage!"
    _buff(character, "damage", 0.40, 2, character)
    return payload, f"｢{character.name}｣ focuses all power! +40% damage!"


def boy_ii_man(character, allied_characters, enemy_characters) -> tuple:
    payload = get_payload()
    target = _target(character, enemy_characters)
    if not target:
        return payload, f"｢{character.name}｣ waits for a challenger!"
    roll = random.choice(["rock", "paper", "scissors"])
    if roll == "rock":
        stolen = _debuff(target, "damage", 0.25, 3, character)
        character.add_effect(Effect(EffectType.DAMAGEUP, 3, stolen, character))
        return payload, f"｢{character.name}｣ throws Rock and wins! Steals {stolen} damage from {target.name}!"
    if roll == "paper":
        dealt = _take(target, min(character.start_hp - character.current_hp, character.start_hp * 0.4) * 0.6)
        return payload, f"｢{character.name}｣ throws Paper! Reflects {dealt} damage at {target.name}!"
    damage = _hit(character, target, 2.0)
    return payload, f"｢{character.name}｣ throws Scissors! Cuts {target.name} for {damage}!"


def highway_star(character, allied_characters, enemy_characters) -> tuple:
    payload = get_payload()
    target = _target(character, enemy_characters)
    if not target:
        return payload, f"｢{character.name}｣ searches for nutrients"
    damage = _hit(character, target, 0.7)
    healed = _heal(character, damage * 0.4)
    return payload, f"｢{character.name}｣ drains {target.name} for {damage} and heals {healed}!"


def stray_cat(character, allied_characters, enemy_characters) -> tuple:
    payload = get_payload()
    terrain = _terrain(character)
    synergy = _has_synergy(character.id, allied_characters, "kira")
    valid = _alive(enemy_characters)
    if not valid:
        return payload, f"｢{character.name}｣ prepares an explosive bubble."
    crit_bonus = 1 + min(character.current_critical, 75) / 100
    if synergy:
        total = 0
        for target in valid:
            total += _hit(character, target, 0.7 * crit_bonus)
            _dot(target, EffectType.BURN, 1, 0.3 * character.current_damage, character)
        return payload, f"｢{character.name}｣ fires Killer Queen-guided bubbles! {total} damage + burn! 💣🐈 Kira synergy!"
    if terrain == Terrain.NATURE:
        total = sum(_hit(character, t, 0.6 * crit_bonus) for t in valid)
        return payload, f"｢{character.name}｣ fires explosive bubbles at everyone for {total}!"
    target = _target(character, enemy_characters)
    damage = _hit(character, target, 1.4 * crit_bonus)
    return payload, f"｢{character.name}｣ pops an air bubble on {target.name} for {damage}!"


def super_fly(character, allied_characters, enemy_characters) -> tuple:
    payload = get_payload()
    _buff(character, "armor", 0.20, 2, character)
    valid = _alive(enemy_characters)
    reflect = (character.start_hp - character.current_hp) * 0.12
    if valid and reflect > 0:
        dealt = sum(_take(e, reflect / len(valid)) for e in valid)
        return payload, f"｢{character.name}｣ sends {dealt} damage back down the tower! +20% armor!"
    return payload, f"｢{character.name}｣ stands firm like a tower! +20% armor!"


def enigma(character, allied_characters, enemy_characters) -> tuple:
    payload = get_payload()
    target = _target(character, enemy_characters)
    if not target:
        return payload, f"｢{character.name}｣ searches for their fears."
    if _impaired(target):
        _stun(target, character)
        _debuff(target, "armor", 0.40, 2, character)
        return payload, f"｢{character.name}｣ folds the terrified {target.name} into paper! Stunned, -40% armor!"
    damage = _hit(character, target, 1.2)
    _debuff(target, "speed", 0.20, 2, character)
    return payload, f"｢{character.name}｣ finds {target.name}'s fear: {damage} damage, slowed!"


def cheap_trick(character, allied_characters, enemy_characters) -> tuple:
    payload = get_payload()
    dead_allies = [a for a in allied_characters if not a.is_alive() and a != character]
    target = _target(character, enemy_characters)
    if not target:
        return payload, f"｢{character.name}｣ whispers to nobody."
    if dead_allies:
        dealt = _take(target, target.current_hp * 0.5)
        lost = _take(character, character.current_hp * 0.3)
        return payload, f"｢{character.name}｣ drags {target.name} toward hell: {dealt} damage, for {lost} of its own health!"
    damage = _hit(character, target, 1.0)
    _debuff(target, "speed", 0.25, 2, character)
    _debuff(target, "armor", 0.25, 2, character)
    return payload, f"｢{character.name}｣ whispers behind {target.name}'s back: {damage} damage, -25% speed and armor."


def gold_experience(character, allied_characters, enemy_characters) -> tuple:
    payload = get_payload()
    synergy = _has_synergy(character.id, allied_characters, "passione")
    share = 0.16 if synergy else 0.12
    healed = sum(_heal(a, a.start_hp * share) for a in _alive(allied_characters))
    message = f"｢{character.name}｣ gives life: the team heals {healed}!"
    if synergy:
        for ally in _alive(allied_characters):
            _buff(ally, "speed", 0.15, 2, character)
        message += " 🐞 Passione synergy! Team +15% speed!"
    return payload, message


def sticky_finger(character, allied_characters, enemy_characters) -> tuple:
    payload = get_payload()
    synergy = _has_synergy(character.id, allied_characters, "passione")
    target = _target(character, enemy_characters)
    if synergy:
        _buff(character, "critical", 15, 2, character)
        _buff(character, "speed", 0.25, 2, character)
        damage = _hit(character, target, 1.5) if target else 0
        return payload, f"｢{character.name}｣ ARI ARI ARI! {damage} damage, +15 crit, +25% speed! 🐞 Passione synergy!"
    _buff(character, "critical", 10, 2, character)
    damage = _hit(character, target, 1.2) if target else 0
    return payload, f"｢{character.name}｣ unzips {target.name if target else 'the air'} for {damage}! +10 crit!"


def purple_haze(character, allied_characters, enemy_characters) -> tuple:
    payload = get_payload()
    for enemy in _alive(enemy_characters):
        _dot(enemy, EffectType.POISON, 2, 0.45 * character.current_damage, character)
    for ally in _alive(allied_characters):
        _dot(ally, EffectType.POISON, 1, 0.1 * character.current_damage, character)
    return payload, f"｢{character.name}｣ releases the virus! Every enemy is poisoned... and so are its allies, a little."


def king_crimson(character, allied_characters, enemy_characters) -> tuple:
    payload = get_payload()
    for enemy in _alive(enemy_characters):
        _stun(enemy, character)
    target = _target(character, enemy_characters)
    damage = _hit(character, target, 1.0) if target else 0
    return payload, f"｢{character.name}｣ erases time! Every enemy loses its next turn; {damage} damage to {target.name if target else 'nobody'}!"


def notorious_big(character, allied_characters, enemy_characters) -> tuple:
    payload = get_payload()
    _regen(character, 2, character.start_hp * 0.08, character)
    alone = len(_alive(allied_characters)) == 1
    if alone:
        _buff(character, "damage", 0.40, 2, character)
        return payload, f"｢{character.name}｣ feeds on everything that moves! Regenerates and +40% damage!"
    return payload, f"｢{character.name}｣ regenerates!"


def metallica(character, allied_characters, enemy_characters) -> tuple:
    payload = get_payload()
    for enemy in _alive(enemy_characters):
        _dot(enemy, EffectType.BLEED, 2, 0.25 * character.current_damage, character)
        _debuff(enemy, "damage", 0.10, 2, character)
    return payload, f"｢{character.name}｣ pulls iron from their blood! Every enemy bleeds and -10% damage!"


def green_day(character, allied_characters, enemy_characters) -> tuple:
    payload = get_payload()
    for enemy in _alive(enemy_characters):
        _debuff(enemy, "damage", 0.20, 2, character)
        _dot(enemy, EffectType.POISON, 2, 0.2 * character.current_damage, character)
    return payload, f"｢{character.name}｣ spreads the mold! Every enemy rots and loses 20% damage!"


def chariot_requiem(character, allied_characters, enemy_characters) -> tuple:
    payload = get_payload()
    target = _target(character, enemy_characters)
    if target and target.id != character.id and str(target.id) in specials:
        damage = _hit(character, target, 0.6)
        _payload, message = specials[str(target.id)](character, allied_characters, enemy_characters)
        return payload, f"｢{character.name}｣ swaps souls with {target.name} ({damage} damage) and borrows its power: {message}"
    grown = _grow(character, "damage", 0.10)
    return payload, f"｢{character.name}｣'s soul searches for the arrow... +{round(grown)} damage."


def gold_experience_requiem(character, allied_characters, enemy_characters) -> tuple:
    payload = get_payload()
    payload["GER"] = True
    for enemy in _alive(enemy_characters):
        _purge(enemy)
        enemy.current_damage = min(enemy.current_damage, enemy.start_damage)
        enemy.current_speed = min(enemy.current_speed, enemy.start_speed)
        enemy.special_meter = 0
    target = _target(character, enemy_characters)
    message = f"｢{character.name}｣ You will never reach the truth! Every enemy returns to zero"
    if target:
        damage = _hit(character, target, 1.5)
        _stun(target, character)
        message += f"; {target.name} takes {damage} and is stunned"
    return payload, message + "!"


def stone_free(character, allied_characters, enemy_characters) -> tuple:
    payload = get_payload()
    target = _target(character, enemy_characters)
    if not target:
        return payload, f"｢{character.name}｣ frees the stone ocean!"
    damage = _hit(character, target, 0.6)
    _stun(target, character)
    return payload, f"｢{character.name}｣ ties {target.name} up in string: {damage} damage and stunned!"


def weather_report(character, allied_characters, enemy_characters) -> tuple:
    payload = get_payload()
    for enemy in _alive(enemy_characters):
        _dot(enemy, EffectType.POISON, 2, 0.3 * character.current_damage, character)
    target = _target(character, enemy_characters)
    damage = _hit(character, target, 1.0) if target else 0
    return payload, f"｢{character.name}｣ makes poison frogs rain on everyone and strikes {target.name if target else 'nothing'} with lightning for {damage}!"


def jumpin_jack_flash(character, allied_characters, enemy_characters) -> tuple:
    payload = get_payload()
    target = _target(character, enemy_characters)
    if not target:
        return payload, f"｢{character.name}｣ removes gravity!"
    damage = _hit(character, target, 1.2)
    _stun(target, character)
    return payload, f"｢{character.name}｣ sends {target.name} floating off for {damage}! Stunned!"


def bohemian_rhapsody(character, allied_characters, enemy_characters) -> tuple:
    payload = get_payload()
    best = max(_alive(allied_characters), key=lambda c: c.current_damage)
    for stat, kind in (("damage", EffectType.DAMAGEUP), ("speed", EffectType.SPEEDUP), ("critical", EffectType.CRITUP)):
        gap = getattr(best, f"current_{stat}") - getattr(character, f"current_{stat}")
        if gap > 0:
            character.add_effect(Effect(kind, 2, gap, character))
    healed = _heal(character, character.start_hp * 0.10)
    return payload, f"｢{character.name}｣ becomes a perfect version of {best.name} and heals {healed}!"


def underworld(character, allied_characters, enemy_characters) -> tuple:
    payload = get_payload()
    dead = [a for a in allied_characters if not a.is_alive() and not getattr(a, "_revived", False)]
    if dead:
        revived = random.choice(dead)
        revived.current_hp = int(revived.start_hp * 0.3)
        revived._revived = True
        return payload, f"｢{character.name}｣ digs up a memory of {revived.name}: back with 30% health!"
    _buff(character, "armor", 0.40, 2, character)
    return payload, f"｢{character.name}｣ digs in, waiting for an ally to fall... +40% armor."


def c_moon(character, allied_characters, enemy_characters) -> tuple:
    payload = get_payload()
    synergy = _has_synergy(character.id, allied_characters, "pucci")
    damage = 0
    for enemy in _alive(enemy_characters):
        damage += _hit(character, enemy, 0.5)
        _debuff(enemy, "speed", 0.25 if synergy else 0.15, 2, character)
        if synergy:
            _debuff(enemy, "armor", 0.15, 2, character)
    message = f"｢{character.name}｣ turns gravity inside out: {damage} damage, every enemy slowed!"
    if synergy:
        message += " ☽ Pucci synergy! -15% enemy armor!"
    return payload, message


def made_in_heaven(character, allied_characters, enemy_characters) -> tuple:
    payload = get_payload()
    synergy = _has_synergy(character.id, allied_characters, "pucci")
    _grow(character, "speed", 0.20)
    _grow(character, "damage", 0.15)
    _buff(character, "critical", 10, 2, character)
    if synergy:
        for ally in [a for a in _alive(allied_characters) if a.id in SYNERGIES["pucci"] and a != character]:
            _buff(ally, "speed", 0.25, 2, character)
            _buff(ally, "damage", 0.15, 2, character)
        return payload, f"｢{character.name}｣ accelerates time for everyone! ☽ Pucci synergy!"
    return payload, f"｢{character.name}｣ accelerates time: +20% speed, +15% damage, +10 crit!"


# ── Part 5 ──────────────────────────────────────────────────────────────

def black_sabbath(character, allied_characters, enemy_characters) -> tuple:
    """ID 61 — Deals extra damage to enemies faster than it."""
    payload = get_payload()
    total = 0
    for target in _alive(enemy_characters):
        total += _hit(character, target, 0.7 if target.current_speed > character.current_speed else 0.35)
    return payload, f"｢{character.name}｣ drags the fast into the shadows for {total} damage!"


def moody_blues(character, allied_characters, enemy_characters) -> tuple:
    """ID 62 — Resets an enemy's special and speeds up an ally's."""
    payload = get_payload()
    parts = []
    target = _target(character, enemy_characters)
    if target:
        target.special_meter = 0
        parts.append(f"resets {target.name}'s special")
    allies = [a for a in _alive(allied_characters) if a != character and not a.as_special()]
    if allies:
        ally = random.choice(allies)
        ally.special_meter += 1
        parts.append(f"charges {ally.name}'s special")
    return payload, f"｢{character.name}｣ replays the past: " + (" and ".join(parts) or "nothing useful") + "!"


def soft_machine(character, allied_characters, enemy_characters) -> tuple:
    """ID 63 — Deflates an enemy. Squadra: deflates every enemy."""
    payload = get_payload()
    synergy = _has_synergy(character.id, allied_characters, "squadra")
    valid = _alive(enemy_characters)
    if not valid:
        return payload, f"｢{character.name}｣ slashes at the air!"
    if synergy:
        for target in valid:
            _debuff(target, "armor", 0.25, 2, character)
            _debuff(target, "damage", 0.12, 2, character)
        return payload, f"｢{character.name}｣ deflates every enemy! -25% armor, -12% damage! 🗡️ Squadra synergy!"
    target = _target(character, enemy_characters)
    damage = _hit(character, target, 0.8)
    _debuff(target, "armor", 0.30, 2, character)
    _debuff(target, "damage", 0.15, 2, character)
    return payload, f"｢{character.name}｣ deflates {target.name}: {damage} damage, -30% armor, -15% damage!"


def sex_pistol(character, allied_characters, enemy_characters) -> tuple:
    payload = get_payload()
    synergy = _has_synergy(character.id, allied_characters, "passione")
    target = _target(character, enemy_characters)
    if not target:
        return payload, f"｢{character.name}｣ fires!"
    shots = 6 if synergy else 5
    total = 0
    for _ in range(shots):
        if not target.is_alive():
            target = _target(character, enemy_characters)
            if not target:
                break
        total += _hit(character, target, 0.32 if synergy else 0.26)
    message = f"｢{character.name}｣ guide {shots} bullets into {target.name if target else 'the enemy'} for {total}!"
    if synergy:
        message += " 🐞 Passione synergy!"
    return payload, message


def kraft_work(character, allied_characters, enemy_characters) -> tuple:
    payload = get_payload()
    target = _target(character, enemy_characters)
    if not target:
        return payload, f"｢{character.name}｣ locks objects in place!"
    damage = _hit(character, target, 0.8)
    _stun(target, character)
    _debuff(target, "speed", 0.25, 2, character)
    return payload, f"｢{character.name}｣ locks {target.name} in place: {damage} damage, stunned and slowed!"


def little_feet(character, allied_characters, enemy_characters) -> tuple:
    """ID 66 — The lower the enemy's health, the more it shrinks."""
    payload = get_payload()
    target = _target(character, enemy_characters)
    if not target:
        return payload, f"｢{character.name}｣ shrinks the air!"
    lost = 1 - target.current_hp / max(1, target.start_hp)
    damage = _hit(character, target, 0.9)
    cut = _debuff(target, "damage", 0.2 + 0.3 * lost, 2, character)
    return payload, f"｢{character.name}｣ cuts {target.name} for {damage} and shrinks it: -{cut} damage!"


def aerosmith(character, allied_characters, enemy_characters) -> tuple:
    payload = get_payload()
    synergy = _has_synergy(character.id, allied_characters, "passione")
    damage = _aoe(character, enemy_characters, 0.6 if synergy else 0.5)
    message = f"｢{character.name}｣ strafes everyone for {damage} damage!"
    if synergy:
        weakest = _weakest(enemy_characters)
        if weakest:
            _dot(weakest, EffectType.BLEED, 2, 0.3 * character.current_damage, character)
            message += f" Locks onto {weakest.name} with bleed! 🐞 Passione synergy!"
    return payload, message


def man_in_the_miror(character, allied_characters, enemy_characters) -> tuple:
    payload = get_payload()
    synergy = _has_synergy(character.id, allied_characters, "squadra")
    valid = _alive(enemy_characters)
    if not valid:
        return payload, f"｢{character.name}｣ opens the mirror world!"
    if synergy:
        targets = random.sample(valid, min(2, len(valid)))
        for target in targets:
            _stun(target, character)
            _debuff(target, "damage", 0.20, 2, character)
        names = " and ".join(t.name for t in targets)
        return payload, f"｢{character.name}｣ traps {names} in the mirror world! 🗡️ Squadra synergy!"
    target = _target(character, enemy_characters)
    damage = _hit(character, target, 0.8)
    _stun(target, character)
    _debuff(target, "damage", 0.20, 2, character)
    return payload, f"｢{character.name}｣ traps {target.name} in the mirror world: {damage} damage, stunned, -20% damage!"


def mr_president(character, allied_characters, enemy_characters) -> tuple:
    """ID 70 — Shelters the weakest ally. Any non-DEFAULT terrain strengthens the room."""
    payload = get_payload()
    terrain = _terrain(character)
    has_terrain = terrain != Terrain.DEFAULT
    allies = [a for a in _alive(allied_characters) if a != character]
    target = _weakest(allies) if allies else character
    share = 0.10 if has_terrain else 0.07
    _regen(target, 2, target.start_hp * share, character)
    _buff(target, "armor", 0.40 if has_terrain else 0.25, 2, character)
    if has_terrain:
        _cleanse(target)
        return payload, f"｢{character.name}｣ seals the {terrain.display_name} inside the room! {target.name} regenerates, +40% armor, debuffs cleared!"
    return payload, f"｢{character.name}｣ shelters {target.name} in the turtle room! Regen and +25% armor!"


def beach_boy(character, allied_characters, enemy_characters) -> tuple:
    """ID 71 — Hooks enemies. In OCEAN: hooks ALL enemies."""
    payload = get_payload()
    terrain = _terrain(character)
    valid = _alive(enemy_characters)
    if not valid:
        return payload, f"｢{character.name}｣ casts its line but finds nothing!"
    if terrain == Terrain.OCEAN:
        total = 0
        for target in valid:
            total += _hit(character, target, 0.5)
            _dot(target, EffectType.BLEED, 2, 0.15 * character.current_damage, character)
        return payload, f"｢{character.name}｣ casts a wide net! {total} damage and bleed on every enemy!"
    target = _target(character, enemy_characters)
    damage = _hit(character, target, 0.7)
    _dot(target, EffectType.BLEED, 2, 0.2 * character.current_damage, character)
    return payload, f"｢{character.name}｣ hooks {target.name} for {damage}, and it bleeds!"


def the_grateful_dead(character, allied_characters, enemy_characters) -> tuple:
    payload = get_payload()
    synergy = _has_synergy(character.id, allied_characters, "squadra")
    for enemy in _alive(enemy_characters):
        _hit(character, enemy, 0.3)
        _dot(enemy, EffectType.POISON, 2, (0.45 if synergy else 0.35) * character.current_damage, character)
        _debuff(enemy, "speed", 0.30 if synergy else 0.20, 2, character)
    message = f"｢{character.name}｣ ages everyone! Every enemy withers and slows!"
    if synergy:
        message += " 🗡️ Squadra synergy!"
    return payload, message


def baby_face(character, allied_characters, enemy_characters) -> tuple:
    payload = get_payload()
    synergy = _has_synergy(character.id, allied_characters, "squadra")
    target = _target(character, enemy_characters)
    if not target:
        return payload, f"｢{character.name}｣ learns!"
    damage = _hit(character, target, 1.0)
    stolen = _debuff(target, "damage", 0.25 if synergy else 0.20, 3, character)
    character.add_effect(Effect(EffectType.DAMAGEUP, 3, stolen, character))
    message = f"｢{character.name}｣ takes {target.name} apart for {damage} and rebuilds itself: steals {stolen} damage"
    if synergy:
        spd = _debuff(target, "speed", 0.15, 3, character)
        character.add_effect(Effect(EffectType.SPEEDUP, 3, spd, character))
        message += f" and {spd} speed! 🗡️ Squadra synergy"
    return payload, message + "!"


def white_album(character, allied_characters, enemy_characters) -> tuple:
    payload = get_payload()
    synergy = _has_synergy(character.id, allied_characters, "squadra")
    _buff(character, "armor", 0.40 if synergy else 0.30, 2, character)
    for enemy in _alive(enemy_characters):
        _debuff(enemy, "speed", 0.25 if synergy else 0.18, 2, character)
    message = f"｢{character.name}｣ freezes the area! +{'40' if synergy else '30'}% armor, every enemy slowed!"
    if synergy:
        message += " 🗡️ Squadra synergy!"
    return payload, message


def clash(character, allied_characters, enemy_characters) -> tuple:
    """ID 76 — Teleports and bites. OCEAN: guaranteed stun. Duo with Talking Head: hit 2 targets."""
    payload = get_payload()
    terrain = _terrain(character)
    duo = _has_synergy(character.id, allied_characters, "clash_talking")
    valid = _alive(enemy_characters)
    if not valid:
        return payload, f"｢{character.name}｣ searches for water but finds none!"
    if duo:
        targets = random.sample(valid, min(2, len(valid)))
        total = 0
        for t in targets:
            total += _hit(character, t, 0.8)
            _stun(t, character)
        names = " and ".join(t.name for t in targets)
        return payload, f"｢{character.name}｣ warps between {names} while they're confused! {total} damage, both stunned! 🦈🤥 Duo synergy!"
    target = _target(character, enemy_characters)
    if terrain == Terrain.OCEAN:
        damage = _hit(character, target, 1.3)
        _stun(target, character)
        return payload, f"｢{character.name}｣ surges through the water and bites {target.name} for {damage}! Stunned!"
    damage = _hit(character, target, 1.0)
    if random.random() < 0.35:
        _stun(target, character)
        return payload, f"｢{character.name}｣ warps to {target.name} and bites for {damage}! Stunned!"
    return payload, f"｢{character.name}｣ warps to {target.name} and bites for {damage}!"


def talking_head(character, allied_characters, enemy_characters) -> tuple:
    """ID 77 — Confuses an enemy. Duo with Clash: confuse ALL enemies."""
    payload = get_payload()
    duo = _has_synergy(character.id, allied_characters, "clash_talking")
    valid = _alive(enemy_characters)
    if not valid:
        return payload, f"｢{character.name}｣ has nothing to confuse!"
    if duo:
        for target in valid:
            _debuff(target, "speed", 0.25, 2, character)
            _debuff(target, "damage", 0.15, 2, character)
        return payload, f"｢{character.name}｣ confuses ALL enemies! -25% speed, -15% damage! 🦈🤥 Duo synergy!"
    target = _target(character, enemy_characters)
    damage = _hit(character, target, 0.8)
    _debuff(target, "speed", 0.30, 2, character)
    _debuff(target, "damage", 0.25, 2, character)
    target.special_meter = max(0, target.special_meter - 1)
    return payload, f"｢{character.name}｣ makes {target.name} say the opposite: {damage} damage, -30% speed, -25% damage, special delayed!"


def spice_girl(character, allied_characters, enemy_characters) -> tuple:
    payload = get_payload()
    for ally in _alive(allied_characters):
        _buff(ally, "armor", 0.30, 2, character)
    return payload, f"｢{character.name}｣ softens every blow! Team +30% armor!"


def oasis(character, allied_characters, enemy_characters) -> tuple:
    """ID 82 — Softens the ground; boosts own speed and deals AoE damage."""
    payload = get_payload()
    _buff(character, "speed", 0.30, 2, character)
    total = _aoe(character, enemy_characters, 0.55)
    return payload, f"｢{character.name}｣ softens the earth! +30% speed and {total} damage to all!"


def rolling_stones(character, allied_characters, enemy_characters) -> tuple:
    """ID 85 — Marks an enemy for death: executes it below 30% health."""
    payload = get_payload()
    target = _target(character, enemy_characters)
    if not target:
        return payload, f"｢{character.name}｣ rolls aimlessly..."
    if target.current_hp / max(target.start_hp, 1) < 0.3:
        dealt = _take(target, target.current_hp * 0.8)
        return payload, f"｢{character.name}｣ reveals {target.name}'s fate... inevitable! {dealt} execution damage!"
    damage = _hit(character, target, 0.8)
    _dot(target, EffectType.BLEED, 3, 0.3 * character.current_damage, character)
    _debuff(target, "speed", 0.15, 3, character)
    return payload, f"｢{character.name}｣ shows {target.name} its future: {damage} damage, bleeding and slowed for 3 turns!"


# ── Part 6 ──────────────────────────────────────────────────────────────

def goo_goo_dolls(character, allied_characters, enemy_characters) -> tuple:
    payload = get_payload()
    target = _target(character, enemy_characters)
    if not target:
        return payload, f"｢{character.name}｣ has no target to shrink!"
    damage = _hit(character, target, 1.2)
    _debuff(target, "damage", 0.25, 2, character)
    return payload, f"｢{character.name}｣ shrinks {target.name}: {damage} damage and -25% damage!"


def manhattan_transfer(character, allied_characters, enemy_characters) -> tuple:
    payload = get_payload()
    for ally in _alive(allied_characters):
        _buff(ally, "critical", 10, 2, character)
    target = _target(character, enemy_characters)
    damage = _hit(character, target, 1.3, pierce=True) if target else 0
    return payload, f"｢{character.name}｣ relays a sniper shot: {damage} damage ignoring armor! Team +10 crit!"


def kiss(character, allied_characters, enemy_characters) -> tuple:
    payload = get_payload()
    target = _target(character, enemy_characters)
    if not target:
        return payload, f"｢{character.name}｣ has no target!"
    damage = _hit(character, target, 0.85)
    if target.is_alive():
        damage += _hit(character, target, 0.85)
    return payload, f"｢{character.name}｣ sticks a sticker on {target.name}: two strikes for {damage}!"


def highway_to_hell(character, allied_characters, enemy_characters) -> tuple:
    payload = get_payload()
    target = _target(character, enemy_characters)
    if not target:
        return payload, f"｢{character.name}｣ has no target to bind!"
    dealt = _take(target, character.current_hp * 0.4)
    lost = _take(character, character.current_hp * 0.15)
    return payload, f"｢{character.name}｣ shares its fate with {target.name}: {dealt} damage for {lost} of its own health!"


def burning_down_the_house(character, allied_characters, enemy_characters) -> tuple:
    payload = get_payload()
    healed = sum(_heal(a, a.start_hp * 0.10) for a in _alive(allied_characters))
    for ally in _alive(allied_characters):
        _buff(ally, "armor", 0.15, 2, character)
    return payload, f"｢{character.name}｣ opens the ghost room! Team heals {healed}, +15% armor!"


def foo_fighters(character, allied_characters, enemy_characters) -> tuple:
    payload = get_payload()
    target = _weakest(allied_characters)
    if not target:
        return payload, f"｢{character.name}｣ has no ally to heal!"
    healed = _heal(target, target.start_hp * 0.25)
    return payload, f"｢{character.name}｣ patches {target.name} with plankton! +{healed} health!"


def marilyn_manson(character, allied_characters, enemy_characters) -> tuple:
    payload = get_payload()
    target = _target(character, enemy_characters)
    if not target:
        return payload, f"｢{character.name}｣ has no debt to collect!"
    _hit(character, target, 0.8)
    dmg = _debuff(target, "damage", 0.25, 3, character)
    spd = _debuff(target, "speed", 0.25, 3, character)
    character.add_effect(Effect(EffectType.DAMAGEUP, 3, dmg, character))
    character.add_effect(Effect(EffectType.SPEEDUP, 3, spd, character))
    return payload, f"｢{character.name}｣ collects the debt! Takes {dmg} damage and {spd} speed from {target.name}!"


def limp_bizkit(character, allied_characters, enemy_characters) -> tuple:
    payload = get_payload()
    grown = _grow(character, "damage", 0.20)
    healed = _heal(character, character.start_hp * 0.15)
    return payload, f"｢{character.name}｣ summons invisible zombies! +{round(grown)} damage, heals {healed}!"


def diver_down(character, allied_characters, enemy_characters) -> tuple:
    payload = get_payload()
    allies = [a for a in _alive(allied_characters) if a != character]
    target = _weakest(allies) if allies else character
    _buff(target, "armor", 0.40, 2, character)
    _regen(target, 2, target.start_hp * 0.07, character)
    return payload, f"｢{character.name}｣ dives into {target.name}! +40% armor and regen!"


def planet_waves(character, allied_characters, enemy_characters) -> tuple:
    payload = get_payload()
    total, stunned = 0, 0
    for enemy in _alive(enemy_characters):
        total += _hit(character, enemy, 0.6)
        if random.random() < 0.25:
            _stun(enemy, character)
            stunned += 1
    return payload, f"｢{character.name}｣ pulls meteorites from orbit! {total} damage, {stunned} stunned!"


def dragons_dream(character, allied_characters, enemy_characters) -> tuple:
    payload = get_payload()
    for ally in _alive(allied_characters):
        _buff(ally, "critical", 15, 2, character)
        _buff(ally, "damage", 0.20, 2, character)
    return payload, f"｢{character.name}｣ points to the lucky directions! Team +15 crit, +20% damage!"


def yo_yo_ma(character, allied_characters, enemy_characters) -> tuple:
    payload = get_payload()
    target = _target(character, enemy_characters)
    if not target:
        return payload, f"｢{character.name}｣ has no target!"
    _dot(target, EffectType.POISON, 3, 0.5 * character.current_damage, character)
    _debuff(target, "armor", 0.15, 3, character)
    return payload, f"｢{character.name}｣ drools acid on {target.name}! Poisoned and -15% armor for 3 turns!"


def green_green_grass_home(character, allied_characters, enemy_characters) -> tuple:
    payload = get_payload()
    for enemy in _alive(enemy_characters):
        _debuff(enemy, "damage", 0.30, 2, character)
    return payload, f"｢{character.name}｣ shrinks every enemy the closer they get! -30% damage!"


def jail_house_lock(character, allied_characters, enemy_characters) -> tuple:
    payload = get_payload()
    target = _target(character, enemy_characters)
    for enemy in _alive(enemy_characters):
        enemy.special_meter = max(0, enemy.special_meter - 1)
    if target:
        _hit(character, target, 0.9)
        _debuff(target, "damage", 0.25, 2, character)
    return payload, f"｢{character.name}｣ limits their memory: every special delayed, {target.name if target else 'nobody'} -25% damage!"


def sky_high(character, allied_characters, enemy_characters) -> tuple:
    payload = get_payload()
    drained = sum(_take(e, e.current_hp * 0.13) for e in _alive(enemy_characters))
    healed = _heal(character, drained * 0.5)
    return payload, f"｢{character.name}｣ sends the Rods! Drains {drained} from enemies, heals {healed}!"


def survivor(character, allied_characters, enemy_characters) -> tuple:
    payload = get_payload()
    valid = _alive(enemy_characters)
    if len(valid) >= 2:
        attacker = _target(character, enemy_characters)
        target = random.choice([e for e in valid if e != attacker])
        damage = _hit(attacker, target, 1.2)
        return payload, f"｢{character.name}｣ enrages the enemies! {attacker.name} attacks {target.name} for {damage}!"
    if valid:
        _stun(valid[0], character)
        _debuff(valid[0], "armor", 0.20, 2, character)
        return payload, f"｢{character.name}｣ enrages {valid[0].name}! Stunned and -20% armor!"
    return payload, f"｢{character.name}｣ has no target to enrage!"


def whitesnake(character, allied_characters, enemy_characters) -> tuple:
    payload = get_payload()
    synergy = _has_synergy(character.id, allied_characters, "pucci")
    valid = _alive(enemy_characters)
    if not valid:
        return payload, f"｢{character.name}｣ has no target to steal from!"
    target = max(valid, key=lambda e: e.current_speed)
    _hit(character, target, 0.8)
    dmg = _debuff(target, "damage", 0.25, 3, character)
    spd = _debuff(target, "speed", 0.25, 3, character)
    character.add_effect(Effect(EffectType.DAMAGEUP, 3, dmg, character))
    character.add_effect(Effect(EffectType.SPEEDUP, 3, spd, character))
    message = f"｢{character.name}｣ steals {target.name}'s DISC! +{dmg} damage, +{spd} speed!"
    if synergy:
        _stun(target, character)
        message += " ☽ Pucci synergy! Target stunned!"
    return payload, message


# ── Part 7 ──────────────────────────────────────────────────────────────

def tusk_act_1(character, allied_characters, enemy_characters) -> tuple:
    payload = get_payload()
    target = _target(character, enemy_characters)
    if not target:
        return payload, f"｢{character.name}｣ fires into the void!"
    damage = _hit(character, target, 1.15)
    return payload, f"｢{character.name}｣ fires nail bullets at {target.name} for {damage}!"


def tusk_act_2(character, allied_characters, enemy_characters) -> tuple:
    payload = get_payload()
    target = _target(character, enemy_characters)
    if not target:
        return payload, f"｢{character.name}｣ fires into the void!"
    synergy = _has_synergy(character.id, allied_characters, "tusk")
    damage = _hit(character, target, 1.1)
    _dot(target, EffectType.BLEED, 2, 0.2 * character.current_damage, character)
    message = f"｢{character.name}｣ shoots a guided nail at {target.name} for {damage}! It bleeds!"
    if synergy:
        _debuff(target, "speed", 0.20, 2, character)
        message += " ✦ Tusk synergy! Target slowed!"
    return payload, message


def tusk_act_3(character, allied_characters, enemy_characters) -> tuple:
    payload = get_payload()
    target = _target(character, enemy_characters)
    if not target:
        return payload, f"｢{character.name}｣ fires into the void!"
    synergy = _has_synergy(character.id, allied_characters, "tusk")
    damage = _hit(character, target, 1.15)
    _dot(target, EffectType.BLEED, 2, 0.25 * character.current_damage, character)
    _debuff(target, "armor", 0.20, 2, character)
    message = f"｢{character.name}｣ fires a wormhole nail at {target.name} for {damage}! Bleed and -20% armor!"
    if synergy:
        _dot(target, EffectType.POISON, 2, 0.25 * character.current_damage, character)
        message += " ✦ Tusk synergy! Poisoned too!"
    return payload, message


def tusk_act_4(character, allied_characters, enemy_characters) -> tuple:
    payload = get_payload()
    payload["tusk_act_4"] = True
    target = _target(character, enemy_characters)
    synergy = _has_synergy(character.id, allied_characters, "tusk")
    message = f"｢{character.name}｣ Lesson 5!"
    if target:
        damage = _hit(character, target, 1.4, pierce=True)
        _dot(target, EffectType.POISON, 3, 0.4 * character.current_damage, character)
        _debuff(target, "armor", 0.40, 3, character)
        message += f" Infinite rotation hits {target.name} for {damage} through armor: poisoned, -40% armor!"
        if synergy:
            for enemy in _alive(enemy_characters):
                if enemy != target:
                    _dot(enemy, EffectType.BLEED, 2, 0.3 * character.current_damage, character)
            message += " ✦ Tusk synergy! Every other enemy bleeds!"
    return payload, message


def ball_breaker(character, allied_characters, enemy_characters) -> tuple:
    payload = get_payload()
    for enemy in _alive(enemy_characters):
        _debuff(enemy, "damage", 0.15, 2, character)
        _debuff(enemy, "speed", 0.15, 2, character)
    for ally in _alive(allied_characters):
        _buff(ally, "damage", 0.10, 2, character)
    return payload, f"｢{character.name}｣ harnesses the golden spin! Enemies age (-15% damage and speed), allies +10% damage!"


def oh_lonesome_me(character, allied_characters, enemy_characters) -> tuple:
    payload = get_payload()
    target = _target(character, enemy_characters)
    if not target:
        return payload, f"｢{character.name}｣ swings the rope..."
    damage = _hit(character, target, 0.8)
    _stun(target, character)
    _debuff(target, "damage", 0.20, 2, character)
    return payload, f"｢{character.name}｣ lassoes {target.name}: {damage} damage, stunned, -20% damage!"


def scary_monsters(character, allied_characters, enemy_characters) -> tuple:
    payload = get_payload()
    _grow(character, "damage", 0.20)
    _buff(character, "speed", 0.20, 2, character)
    target = _target(character, enemy_characters)
    damage = _hit(character, target, 1.3) if target else 0
    return payload, f"｢{character.name}｣ goes full dinosaur! +20% damage for good, +20% speed, bites for {damage}!"


def cream_starter(character, allied_characters, enemy_characters) -> tuple:
    payload = get_payload()
    target = _weakest(allied_characters)
    if not target:
        return payload, f"｢{character.name}｣ has no one to heal!"
    healed = _heal(target, target.start_hp * 0.20)
    _buff(target, "damage", 0.15, 2, character)
    return payload, f"｢{character.name}｣ sprays flesh onto {target.name}! +{healed} health, +15% damage!"


def ticket_to_ride(character, allied_characters, enemy_characters) -> tuple:
    payload = get_payload()
    for ally in _alive(allied_characters):
        _regen(ally, 2, ally.start_hp * 0.06, character)
    for enemy in _alive(enemy_characters):
        _debuff(enemy, "damage", 0.20, 2, character)
    return payload, f"｢{character.name}｣ shines a holy light! Allies regenerate, enemies -20% damage!"


def dirty_deed_done_dirt_cheap(character, allied_characters, enemy_characters) -> tuple:
    payload = get_payload()
    _cleanse(character)
    healed = _heal(character, character.start_hp * 0.20)
    target = _target(character, enemy_characters)
    damage = _hit(character, target, 1.6) if target else 0
    return payload, f"｢{character.name}｣ swaps in a fresh self from another world: heals {healed}, cleansed, and strikes for {damage}!"


def in_a_silent_way(character, allied_characters, enemy_characters) -> tuple:
    payload = get_payload()
    total = 0
    for enemy in _alive(enemy_characters):
        total += _hit(character, enemy, 0.5)
        _dot(enemy, EffectType.BLEED, 2, 0.2 * character.current_damage, character)
    return payload, f"｢{character.name}｣ turns sound into blades! {total} damage and every enemy bleeds!"


def hey_ya(character, allied_characters, enemy_characters) -> tuple:
    payload = get_payload()
    for ally in _alive(allied_characters):
        _buff(ally, "critical", 15, 2, character)
        _buff(ally, "speed", 0.20, 2, character)
        _buff(ally, "damage", 0.25, 2, character)
    healed = sum(_heal(a, a.start_hp * 0.08) for a in _alive(allied_characters))
    return payload, f"｢{character.name}｣ cheers everyone on! Team +15 crit, +20% speed, +25% damage, heals {healed}!"


def tomb_of_boom(character, allied_characters, enemy_characters) -> tuple:
    payload = get_payload()
    target = _target(character, enemy_characters)
    if not target:
        return payload, f"｢{character.name}｣ has no target!"
    damage = _hit(character, target, 1.0)
    _dot(target, EffectType.POISON, 2, 0.5 * character.current_damage, character)
    _debuff(target, "speed", 0.20, 2, character)
    return payload, f"｢{character.name}｣ magnetizes iron inside {target.name}: {damage} damage, poisoned and slowed!"


def boku_no_rythm_wo_kiitekure(character, allied_characters, enemy_characters) -> tuple:
    payload = get_payload()
    for enemy in _alive(enemy_characters):
        _dot(enemy, EffectType.BURN, 1, 0.8 * character.current_damage, character)
    return payload, f"｢{character.name}｣ sticks a ticking bomb on every enemy!"


def wired(character, allied_characters, enemy_characters) -> tuple:
    payload = get_payload()
    total = 0
    for enemy in _alive(enemy_characters):
        total += _hit(character, enemy, 0.45)
        _dot(enemy, EffectType.BLEED, 2, 0.15 * character.current_damage, character)
    return payload, f"｢{character.name}｣ launches barbed wire! {total} damage and bleed!"


def mandom(character, allied_characters, enemy_characters) -> tuple:
    payload = get_payload()
    healed = 0
    for ally in _alive(allied_characters):
        _cleanse(ally)
        healed += _heal(ally, ally.start_hp * 0.08)
    target = _target(character, enemy_characters)
    if target:
        target.special_meter = max(0, target.special_meter - 1)
    return payload, f"Welcome to the True Man's world! Six seconds rewound: team cleansed, heals {healed}, {target.name if target else 'nobody'}'s special delayed!"


def catch_the_rainbow(character, allied_characters, enemy_characters) -> tuple:
    payload = get_payload()
    _buff(character, "armor", 0.30, 2, character)
    target = _target(character, enemy_characters)
    damage = _hit(character, target, 1.2) if target else 0
    return payload, f"｢{character.name}｣ walks on frozen rain: +30% armor and pierces {target.name if target else 'nothing'} for {damage}!"


def sugar_mountain(character, allied_characters, enemy_characters) -> tuple:
    payload = get_payload()
    healed = 0
    for ally in _alive(allied_characters):
        _buff(ally, "damage", 0.15, 2, character)
        healed += _heal(ally, ally.start_hp * 0.08)
    return payload, f"｢{character.name}｣ offers gifts from the spring! Team +15% damage, heals {healed}!"


def tatoo_you(character, allied_characters, enemy_characters) -> tuple:
    payload = get_payload()
    for ally in _alive(allied_characters):
        _buff(ally, "armor", 0.25, 2, character)
    target = _target(character, enemy_characters)
    damage = _hit(character, target, 0.8) if target else 0
    return payload, f"｢{character.name}｣ hides the team in its skin and ambushes for {damage}! Team +25% armor!"


def tubular_bells(character, allied_characters, enemy_characters) -> tuple:
    payload = get_payload()
    target = _target(character, enemy_characters)
    if not target:
        return payload, f"｢{character.name}｣ inflates a balloon..."
    damage = _hit(character, target, 0.9)
    _stun(target, character)
    return payload, f"｢{character.name}｣'s balloon animal attacks {target.name} for {damage}! Stunned!"


def twentieth_century_boy(character, allied_characters, enemy_characters) -> tuple:
    payload = get_payload()
    _buff(character, "armor", 0.4, 1, character)
    _regen(character, 2, character.start_hp * 0.04, character)
    return payload, f"｢{character.name}｣ kneels and becomes nearly invincible! +40% armor for a turn and regen!"


def civil_war(character, allied_characters, enemy_characters) -> tuple:
    payload = get_payload()
    for enemy in _alive(enemy_characters):
        _dot(enemy, EffectType.POISON, 2, 0.3 * character.current_damage, character)
        _debuff(enemy, "damage", 0.15, 2, character)
    return payload, f"｢{character.name}｣ summons the guilt of the past! Every enemy is haunted (-15% damage) and suffers!"


def chocolate_disco(character, allied_characters, enemy_characters) -> tuple:
    payload = get_payload()
    total = _aoe(character, enemy_characters, 0.55)
    return payload, f"｢{character.name}｣ marks the grid! Precise strikes for {total} total damage!"


def the_world_sbr(character, allied_characters, enemy_characters) -> tuple:
    return _time_stop(character, enemy_characters)


def soft_and_wet(character, allied_characters, enemy_characters) -> tuple:
    payload = get_payload()
    target = _target(character, enemy_characters)
    if not target:
        return payload, f"｢{character.name}｣ releases bubbles!"
    damage = _hit(character, target, 1.4)
    stolen = _debuff(target, "damage", 0.30, 2, character)
    return payload, f"｢{character.name}｣'s bubble pops on {target.name} for {damage} and steals its strength: -{stolen} damage!"


def paisley_park(character, allied_characters, enemy_characters) -> tuple:
    payload = get_payload()
    for ally in _alive(allied_characters):
        _buff(ally, "speed", 0.20, 2, character)
        _buff(ally, "critical", 15, 2, character)
    target = _weakest(enemy_characters)
    damage = 0
    if target:
        _debuff(target, "armor", 0.30, 2, character)
        damage = _hit(character, target, 1.0)
    return payload, f"｢{character.name}｣ finds the path: team +20% speed and +15 crit, {target.name if target else 'nobody'} exposed (-30% armor) and hit for {damage}!"


def doggy_style(character, allied_characters, enemy_characters) -> tuple:
    payload = get_payload()
    target = _target(character, enemy_characters)
    if not target:
        return payload, f"｢{character.name}｣ unravels into the air..."
    damage = _hit(character, target, 1.1)
    _dot(target, EffectType.BLEED, 2, 0.2 * character.current_damage, character)
    return payload, f"｢{character.name}｣ unravels and lashes {target.name} for {damage}! It bleeds!"


def nut_king_call(character, allied_characters, enemy_characters) -> tuple:
    payload = get_payload()
    target = _target(character, enemy_characters)
    if not target:
        return payload, f"｢{character.name}｣ screws the air..."
    _debuff(target, "armor", 0.30, 2, character)
    _debuff(target, "damage", 0.15, 2, character)
    damage = _hit(character, target, 1.7)
    return payload, f"｢{character.name}｣ unscrews {target.name}: -30% armor, -15% damage, {damage} damage!"


def paper_moon_king(character, allied_characters, enemy_characters) -> tuple:
    payload = get_payload()
    damage = 0
    for enemy in _alive(enemy_characters):
        damage += _hit(character, enemy, 0.35)
        enemy.add_effect(Effect(EffectType.CRITUP, 2, -min(10, enemy.current_critical), character))
        _debuff(enemy, "speed", 0.15, 2, character)
        _debuff(enemy, "damage", 0.20, 2, character)
    return payload, f"｢{character.name}｣ folds their perception for {damage}! Every enemy -10 crit, -15% speed, -20% damage!"


def king_nothing(character, allied_characters, enemy_characters) -> tuple:
    payload = get_payload()
    valid = _alive(enemy_characters)
    if not valid:
        return payload, f"｢{character.name}｣ searches for a scent..."
    target = max(valid, key=lambda e: e.current_damage)
    _debuff(target, "armor", 0.30, 2, character)
    _debuff(target, "damage", 0.25, 2, character)
    damage = _hit(character, target, 1.0)
    return payload, f"｢{character.name}｣ tracks {target.name}'s scent: {damage} damage, -30% armor, -25% damage!"


def speed_king(character, allied_characters, enemy_characters) -> tuple:
    payload = get_payload()
    target = _target(character, enemy_characters)
    if not target:
        return payload, f"｢{character.name}｣ heats up..."
    damage = _hit(character, target, 1.1)
    _dot(target, EffectType.BURN, 2, 0.25 * character.current_damage, character)
    return payload, f"｢{character.name}｣ ignites {target.name} from the inside! {damage} damage and burn!"


def fun_fun_fun(character, allied_characters, enemy_characters) -> tuple:
    payload = get_payload()
    target = _target(character, enemy_characters)
    if not target:
        return payload, f"｢{character.name}｣ has no one to control!"
    damage = _hit(character, target, 0.8)
    _stun(target, character)
    _debuff(target, "damage", 0.25, 2, character)
    return payload, f"｢{character.name}｣ pins {target.name}'s marks: {damage} damage, stunned, -25% damage!"


def california_king_bed(character, allied_characters, enemy_characters) -> tuple:
    payload = get_payload()
    target = _target(character, enemy_characters)
    if not target:
        return payload, f"｢{character.name}｣ has no memory to steal!"
    damage = _hit(character, target, 0.8)
    stolen = _debuff(target, "damage", 0.25, 3, character)
    character.add_effect(Effect(EffectType.DAMAGEUP, 3, stolen, character))
    target.special_meter = max(0, target.special_meter - 1)
    return payload, f"｢{character.name}｣ steals a memory from {target.name}: {damage} damage, {stolen} damage taken, special delayed!"


def born_this_way(character, allied_characters, enemy_characters) -> tuple:
    payload = get_payload()
    total = 0
    for enemy in _alive(enemy_characters):
        total += _hit(character, enemy, 0.5)
        _debuff(enemy, "speed", 0.15, 2, character)
    return payload, f"｢{character.name}｣ rides in on the frozen wind! {total} damage, every enemy slowed!"


def les_feuilles(character, allied_characters, enemy_characters) -> tuple:
    payload = get_payload()
    target = _target(character, enemy_characters)
    if not target:
        return payload, f"｢{character.name}｣ scatters leaves..."
    damage = _hit(character, target, 0.7)
    _dot(target, EffectType.POISON, 3, 0.5 * character.current_damage, character)
    _debuff(target, "speed", 0.20, 3, character)
    return payload, f"｢{character.name}｣ wraps leaves around {target.name}: {damage} damage, poisoned and slowed for 3 turns!"


def i_am_a_rock(character, allied_characters, enemy_characters) -> tuple:
    payload = get_payload()
    target = _target(character, enemy_characters)
    if target:
        _stun(target, character)
    for enemy in _alive(enemy_characters):
        _debuff(enemy, "speed", 0.15, 2, character)
    _buff(character, "armor", 0.30, 2, character)
    return payload, f"｢{character.name}｣ pulls everything onto {target.name if target else 'itself'}! Stunned, enemies slowed, +30% armor!"


def doobie_wah(character, allied_characters, enemy_characters) -> tuple:
    payload = get_payload()
    target = _target(character, enemy_characters)
    if not target:
        return payload, f"｢{character.name}｣ seeks its enemy!"
    damage = _hit(character, target, 1.5)
    _dot(target, EffectType.POISON, 2, 0.3 * character.current_damage, character)
    return payload, f"｢{character.name}｣'s tornado follows {target.name}'s breath: {damage} damage and suffocating!"


def love_love_deluxe(character, allied_characters, enemy_characters) -> tuple:
    payload = get_payload()
    target = _target(character, enemy_characters)
    if not target:
        return payload, f"｢{character.name}｣ extends its hair..."
    damage = _hit(character, target, 0.7)
    _dot(target, EffectType.POISON, 2, 0.35 * character.current_damage, character)
    _debuff(target, "armor", 0.25, 2, character)
    return payload, f"｢{character.name}｣ grows hair into {target.name}: {damage} damage, poisoned and -25% armor!"


def schott_key(character, allied_characters, enemy_characters) -> tuple:
    payload = get_payload()
    total = _aoe(character, enemy_characters, 0.7)
    return payload, f"｢{character.name}｣ explodes! {total} damage to all!"


def vitamine_c(character, allied_characters, enemy_characters) -> tuple:
    payload = get_payload()
    for enemy in _alive(enemy_characters):
        _debuff(enemy, "speed", 0.20, 2, character)
        _debuff(enemy, "damage", 0.20, 2, character)
        _debuff(enemy, "armor", 0.20, 2, character)
    return payload, f"｢{character.name}｣ softens everything! Every enemy -20% speed, damage and armor!"


def walking_heart(character, allied_characters, enemy_characters) -> tuple:
    payload = get_payload()
    target = _target(character, enemy_characters)
    damage = _hit(character, target, 1.4) if target else 0
    _buff(character, "damage", 0.15, 2, character)
    return payload, f"｢{character.name}｣ stabs with its heels for {damage}! +15% damage!"


def milagro_man(character, allied_characters, enemy_characters) -> tuple:
    payload = get_payload()
    target = _target(character, enemy_characters)
    if not target:
        return payload, f"｢{character.name}｣ scatters cursed money..."
    curse = _take(target, target.current_damage * 0.6)
    _dot(target, EffectType.POISON, 2, curse * 0.4, character)
    return payload, f"｢{character.name}｣ curses {target.name} with endless money! {curse} damage and poison!"


def blue_hawaii(character, allied_characters, enemy_characters) -> tuple:
    payload = get_payload()
    target = _target(character, enemy_characters)
    if not target:
        return payload, f"｢{character.name}｣ has no one to control!"
    _stun(target, character)
    _dot(target, EffectType.POISON, 2, 0.35 * character.current_damage, character)
    return payload, f"｢{character.name}｣ takes control of {target.name}! Stunned and poisoned!"


def brain_storm(character, allied_characters, enemy_characters) -> tuple:
    payload = get_payload()
    total = 0
    for enemy in _alive(enemy_characters):
        total += _hit(character, enemy, 0.6)
        _dot(enemy, EffectType.BLEED, 2, 0.2 * character.current_damage, character)
    return payload, f"｢{character.name}｣ folds the pages! {total} damage and bleed!"


def ozon_baby(character, allied_characters, enemy_characters) -> tuple:
    payload = get_payload()
    total = 0
    for enemy in _alive(enemy_characters):
        total += _take(enemy, enemy.current_hp * 0.16)
        _debuff(enemy, "speed", 0.15, 2, character)
    return payload, f"｢{character.name}｣ raises the air pressure! {total} damage, every enemy slowed!"


def doctor_wu(character, allied_characters, enemy_characters) -> tuple:
    payload = get_payload()
    target = _target(character, enemy_characters)
    if not target:
        return payload, f"｢{character.name}｣ scatters its particles..."
    damage = _hit(character, target, 0.8)
    _dot(target, EffectType.POISON, 3, 0.4 * character.current_damage, character)
    _debuff(target, "armor", 0.20, 3, character)
    return payload, f"｢{character.name}｣ infiltrates {target.name}'s body: {damage} damage, poison and -20% armor for 3 turns!"


def awaking_iii_leaves(character, allied_characters, enemy_characters) -> tuple:
    payload = get_payload()
    target = _target(character, enemy_characters)
    if not target:
        return payload, f"｢{character.name}｣ builds pressure..."
    _stun(target, character)
    _debuff(target, "speed", 0.25, 2, character)
    return payload, f"｢{character.name}｣ pins {target.name} with arrows! Stunned and slowed!"


def wonder_of_u(character, allied_characters, enemy_characters) -> tuple:
    payload = get_payload()
    total = 0
    for enemy in _alive(enemy_characters):
        share = 0.16 if _impaired(enemy) or enemy.current_hp < enemy.start_hp / 2 else 0.08
        total += _take(enemy, enemy.start_hp * share)
    return payload, f"｢{character.name}｣ turns pursuit into calamity: {total} damage to every enemy, worst for the wounded!"


def space_trucking(character, allied_characters, enemy_characters) -> tuple:
    payload = get_payload()
    total = _aoe(character, enemy_characters, 0.7)
    _buff(character, "speed", 0.20, 2, character)
    return payload, f"｢{character.name}｣ stretches its arms! {total} damage to all, +20% speed!"


def victorious_star_platinum(character, allied_characters, enemy_characters) -> tuple:
    return _time_stop(character, enemy_characters)


def not_implemented(character, allied_characters, enemy_characters) -> tuple:
    payload = get_payload()
    message = f"｢{character.name}｣ has no power yet"
    payload["is_a_special"] = False
    return payload, message


SCALING = {
    # 💨 speed: rushes, multi-hits, time stops and chasers
    1: "speed", 4: "speed", 6: "speed", 8: "speed", 10: "speed", 15: "speed", 22: "speed", 26: "speed",
    31: "speed", 37: "speed", 40: "speed", 44: "speed", 53: "speed", 61: "speed", 62: "speed", 67: "speed",
    75: "speed", 76: "speed", 82: "speed", 103: "speed", 107: "speed", 109: "speed", 116: "speed",
    117: "speed", 134: "speed", 139: "speed", 143: "speed", 146: "speed", 149: "speed", 154: "speed",
    160: "speed", 162: "speed", 163: "speed",
    # 🛡️ armor: shields, walls and bindings
    5: "armor", 9: "armor", 12: "armor", 21: "armor", 55: "armor", 65: "armor", 70: "armor", 74: "armor",
    79: "armor", 86: "armor", 97: "armor", 101: "armor", 105: "armor", 127: "armor", 129: "armor",
    131: "armor", 148: "armor", 153: "armor",
    # ❤️ health: healers, sacrifices and stands that feed on their wounds
    11: "health", 17: "health", 32: "health", 36: "health", 38: "health", 43: "health", 48: "health",
    57: "health", 58: "health", 59: "health", 78: "health", 90: "health", 91: "health", 92: "health",
    96: "health", 118: "health", 119: "health", 120: "health", 126: "health", 128: "health", 164: "health",
    # 🍀 luck (crit): snipers, gamblers, fortune tellers and controllers
    13: "critical", 14: "critical", 20: "critical", 24: "critical", 28: "critical", 29: "critical",
    35: "critical", 45: "critical", 47: "critical", 51: "critical", 52: "critical", 56: "critical",
    60: "critical", 64: "critical", 68: "critical", 71: "critical", 77: "critical", 85: "critical",
    88: "critical", 93: "critical", 98: "critical", 99: "critical", 102: "critical", 122: "critical",
    133: "critical", 138: "critical", 141: "critical", 144: "critical", 145: "critical", 155: "critical",
    161: "critical",
}


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
