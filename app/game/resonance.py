"""Resonances: cross-synergies. Two or more active synergies on one team unlock a fight-changing rule.

Lower rarities sit in more groups (Tarot, Nine Gods, Squadra, Morioh...), so a well-built team of commons
lights several resonances at once, while three Mythics rarely share more than one group. Groups that cover
exactly the same stands on the team count as one crossing (see crossings()). The rules:

  underdog       any 2 synergies           Giant Slayer: +12% damage per rarity step against higher-rarity stands,
                                           -8% damage taken per step from them (character.slayer_mult)
  golden_spirit  2 hero synergies          Second Wind: when an ally falls, the others heal and hit harder
  dark_network   2 villain synergies       Ambush: the enemy team starts slowed and with broken armor
  fated_clash    a hero + a villain group  Initiative: every special starts one turn closer
  bound          a duo + any other group   Lifesteal: basic attacks heal for a share of the damage
  home_field     a synergy, a terrain      Home Field: your terrain holds while its setter stands, natives'
                 setter and 2+ of its natives  bonuses x1.5
  triple_bond    3+ synergies              Resonant Strikes: basic attacks ignore 30% of armor

Everything here is set fresh at the start of each fight (tower teams keep their fighters between floors), and
anything done to the enemy is an effect, so it never outlives the fight.
"""
from typing import Dict, List

from app.game.characterabilities import SYNERGIES, active_synergies
from app.game.effects import TERRAIN_BENEFITS, TERRAIN_SETTERS, Effect, EffectType, leverage

HEROES = {"crusaders", "joestar", "kujo", "morioh", "passione", "stone_ocean", "josuke_okuyasu", "rohan_koichi",
          "echoes", "wall_eyes", "spin", "tusk", "sbr_racers", "townsfolk", "higashikata"}
VILLAINS = {"tarot", "nine_gods", "squadra", "kira", "president", "boom_boom", "pucci", "hol_horse",
            "clash_talking", "bow_arrow", "kira_family", "darby", "oingo_boingo", "dio_mansion", "boss_guard",
            "cioccolata_secco", "zucchero_sale", "pucci_agents", "dio_sons", "rock_humans"}
# neither side: the Saint's Corpse draws heroes and villains alike
DUOS = {name for name, ids in SYNERGIES.items() if len(ids) == 2}

SECOND_WIND_HEAL, SECOND_WIND_DAMAGE, SECOND_WIND_TURNS = 0.20, 0.20, 2
AMBUSH_SLOW, AMBUSH_BREAK, AMBUSH_TURNS = 0.25, 0.15, 3
LIFESTEAL = 0.15
HOME_FIELD_MULT = 1.5
PIERCE = 0.30

# key: (label, icon, what lights it, what it does)
RESONANCES = {
    "underdog": ("Underdog Spirit", "🗡️", "Any 2 synergies (on different stands)",
                 "Giant Slayer: +12% damage per rarity step against higher-rarity stands, and 8% less damage "
                 "taken per step from them (up to 3 steps)."),
    "golden_spirit": ("Golden Spirit", "✨", "2 hero synergies",
                      "Second Wind: whenever an ally falls, every survivor heals 20% of its health and gets +20% "
                      "damage for 2 turns (bigger for lower rarities)."),
    "dark_network": ("Dark Network", "🕸️", "2 villain synergies",
                     "Ambush: the enemy team starts with -25% speed and -15% armor for its first 3 turns, "
                     "before anyone checks who moves first."),
    "fated_clash": ("Fated Clash", "⚡", "A hero synergy and a villain synergy",
                    "Initiative: every special starts one turn closer to ready."),
    "bound": ("Bound by Fate", "🔗", "A duo synergy and any other synergy",
              "Lifesteal: basic attacks heal the attacker for 15% of the damage dealt (bigger for lower rarities)."),
    "home_field": ("Home Field", "🏟️", "A synergy, a terrain setter and 2+ of that terrain's natives",
                   "Your terrain holds while its setter stands, whoever is faster, and your natives' terrain "
                   "bonuses are 50% bigger."),
    "triple_bond": ("Triple Bond", "♾️", "3 or more synergies",
                    "Resonant Strikes: basic attacks ignore 30% of the target's armor."),
}


def home_terrain(team: list):
    """The terrain this team can hold: one of its setters with 2+ natives of it on the team."""
    for c in team:
        terrain = TERRAIN_SETTERS.get(c.id)
        if terrain and sum(terrain in TERRAIN_BENEFITS.get(m.id, {}) for m in team) >= 2:
            return terrain
    return None


def crossings(team: list, parts: bool = True) -> List[set]:
    """The team's active synergies as distinct crossings: groups that cover exactly the same stands on this
    team (Tusk, Joestar and the SBR racers for the three Tusk acts) only cross once. Each entry is the set
    of group names sharing those stands."""
    ids = {c.id for c in team}
    by_members = {}
    for name in active_synergies(team, parts):
        by_members.setdefault(frozenset(SYNERGIES[name] & ids), set()).add(name)
    return list(by_members.values())


def active(team: list, parts: bool = True) -> List[str]:
    crossed = crossings(team, parts)
    heroes = [g for g in crossed if g & HEROES]
    villains = [g for g in crossed if g & VILLAINS]
    duos = [g for g in crossed if g & DUOS]
    out = []
    if len(crossed) >= 2:
        out.append("underdog")
    if len(heroes) >= 2:
        out.append("golden_spirit")
    if len(villains) >= 2:
        out.append("dark_network")
    if heroes and villains and len(crossed) >= 2:
        out.append("fated_clash")
    if duos and len(crossed) >= 2:
        out.append("bound")
    if crossed and home_terrain(team):
        out.append("home_field")
    if len(crossed) >= 3:
        out.append("triple_bond")
    return out


def uses_parts(side) -> bool:
    """Part synergies count for teams players built (yours, a PvP opponent's), not for computer PvE enemies."""
    parts = getattr(side, "parts", None)
    return side.is_human if parts is None else parts


def _reset(team: list) -> None:
    for c in team:
        c._slayer = False
        c._armor_pierce = 0
        c._lifesteal = 0
        c._home_mult = 1


def apply(fight) -> Dict[int, List[str]]:
    """Light each side's resonances on its fighters (and Ambush on the foe). Returns {side: [keys]}."""
    lit = {}
    for s, side in enumerate(fight.sides):
        _reset(side.chars)
        lit[s] = active(side.chars, parts=uses_parts(side))
    fight.home = {}
    for s, side in enumerate(fight.sides):
        team, foes = side.chars, fight.sides[1 - s].chars
        keys = lit[s]
        for c in team:
            c._slayer = "underdog" in keys
            c._armor_pierce = PIERCE if "triple_bond" in keys else 0
            c._lifesteal = LIFESTEAL * leverage(c) if "bound" in keys else 0
        if "fated_clash" in keys:
            for c in team:
                c.special_meter += 1
        if "home_field" in keys:
            terrain = home_terrain(team)
            fight.home[s] = terrain
            for c in team:
                if terrain in TERRAIN_BENEFITS.get(c.id, {}):
                    c._home_mult = HOME_FIELD_MULT
        if "dark_network" in keys:
            for c in foes:
                if c.is_alive():
                    c.add_effect(Effect(EffectType.SLOW, AMBUSH_TURNS, int(c.current_speed * AMBUSH_SLOW)))
                    c.add_effect(Effect(EffectType.ARMORBREAK, AMBUSH_TURNS, int(c.current_armor * AMBUSH_BREAK)))
    return lit


def second_wind(team: list, fallen) -> List[str]:
    """Golden Spirit: an ally just fell; the survivors rally. Returns the names that rallied."""
    out = []
    for c in team:
        if c is fallen or not c.is_alive():
            continue
        lift = leverage(c)
        c.heal(c.start_hp * SECOND_WIND_HEAL * lift)
        c.add_effect(Effect(EffectType.DAMAGEUP, SECOND_WIND_TURNS, int(c.current_damage * SECOND_WIND_DAMAGE * lift)))
        out.append(c.name)
    return out
