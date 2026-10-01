"""Wiki content built from the battle engine's own tables.

Terrain setters/bonuses, synergy groups, types, qualities, rank tiers and
status effects all come straight from app.game so the wiki can't drift from
what fights actually do. Only the prose describing each synergy effect is
written by hand; tests check it covers every stand the engine wires up.
"""
import inspect
import re

from app.game import character as character_mod
from app.game import logic
from app.game.character import CHARACTER_FILE, Qualities, Types, specials
from app.game.characterabilities import SYNERGIES
from app.game.effects import Emoji, EffectType, NEGATIVE_EFFECTS, TERRAIN_BENEFITS, TERRAIN_SETTERS, Terrain

TOPICS = [
    # slug, title, one-line blurb, group
    ("stands", "Getting & upgrading stands", "Banners, rarity odds, pity, levels, fusing and ascension.", "Basics"),
    ("types", "Types & qualities", "What each type boosts and how much each quality multiplies it.", "Basics"),
    ("teams", "Team management", "Main team, storage and saved presets.", "Basics"),
    ("combat", "Combat system", "Turn order, stats, dodge, armor, specials and status effects.", "Combat"),
    ("terrains", "Terrain explorer", "Which stands set each terrain and who gets stronger on it.", "Combat"),
    ("synergies", "Synergy explorer", "Team combos and exactly what each member gains.", "Combat"),
    ("ranked", "Ranked & ELO", "Matchmaking and the rank ladder.", "Modes"),
    ("adventure", "Wormhole, tower & dungeon", "PvE modes, cooldowns and rewards.", "Modes"),
    ("items", "Items & equipment", "Equipping, crafting and where items drop.", "Modes"),
    ("gangs", "Gangs & player shops", "Clans, the shared market and what they cost.", "Community"),
]
TOPIC_SLUGS = {slug for slug, *_ in TOPICS}
TOPIC_GROUPS = []  # [(group, [(slug, title, blurb), ...])] in TOPICS order
for _slug, _title, _blurb, _group in TOPICS:
    if not TOPIC_GROUPS or TOPIC_GROUPS[-1][0] != _group:
        TOPIC_GROUPS.append((_group, []))
    TOPIC_GROUPS[-1][1].append((_slug, _title, _blurb))

TERRAIN_BLURB = {
    "DEFAULT": "No terrain setter is alive, so nobody gets terrain bonuses.",
    "OCEAN": "Water stands take the field and hit faster and harder.",
    "DESERT": "Fire and sand stands burn hotter; The Fool digs in.",
    "FROZEN": "Ice stands harden while their allies speed up.",
    "MIRROR": "Illusionists reshape the arena and strike from reflections.",
    "NATURE": "Living terrain heals life stands and sharpens their allies.",
    "GRAVITY": "Gravity users bend speed and damage in their favour.",
}

STAT_LABEL = {"damage_pct": "damage", "speed_pct": "speed", "armor_pct": "armor",
              "crit_flat": "critical", "regen_pct": "regen / turn"}

SYNERGY_INFO = {
    "crusaders": ("Stardust Crusaders", "⭐"),
    "kira": ("Kira duo", "💣"),
    "squadra": ("La Squadra", "🗡️"),
    "passione": ("Passione", "🐞"),
    "morioh": ("Morioh Warriors", "🏘️"),
    "pucci": ("Pucci evolution", "☽"),
    "tusk": ("Tusk evolution", "✦"),
    "clash_talking": ("Clash + Talking Head", "🦈"),
}

# What each stand's special does differently while its synergy is active.
SYNERGY_EFFECTS = {
    "crusaders": {
        1: "Always lands one extra punch.",
        2: "Crossfire Hurricane burns every enemy (2 turns) instead of one.",
        3: "Emerald Splash hits at 0.7× instead of 0.5×.",
        6: "+15 speed and keeps its armor (normally +10 speed, −25% armor).",
    },
    "kira": {
        49: "Bombs two enemies for 200% damage instead of one for 150%.",
        54: "Guided bubbles hit every enemy at 1.5× and add a burn.",
    },
    "squadra": {
        63: "Deflates every enemy (−20% armor, −10% damage) instead of one.",
        68: "Traps two enemies in the mirror (stun + weaken) instead of one.",
        72: "Stronger aging: poison 30% (from 20%) and slow 5 (from 3).",
        73: "Steals 25% damage (from 15%) plus 10% speed.",
        74: "+50% armor (from 40%) and slows enemies by 6 (from 4).",
    },
    "passione": {
        59: "Heals 50 (from 30) and gives the whole team +3 speed.",
        60: "+7 crit and +5 speed, plus a 0.5× zipper strike (normally +5 crit).",
        64: "Up to 8 bullets at 0.4× (normally 6 at 0.3×).",
        67: "Strafes at 0.45× (from 0.35×) and makes the weakest enemy bleed.",
    },
    "pucci": {
        107: "The DISC theft also weakens the target for 2 turns.",
        108: "Slows enemies by 4 (from 2) and cuts their armor by 10%.",
        109: "+8 speed, +30 damage, +8 crit, and other Pucci stands get +5 speed, +10 damage.",
    },
    "tusk": {
        112: "The guided nail also slows the target.",
        113: "The wormhole nail also poisons the target.",
        114: "Infinite Rotation makes every other enemy bleed.",
    },
    "clash_talking": {
        76: "Warps between two confused enemies, hitting and stunning both.",
        77: "Confuses every enemy: −25% speed and critical ×0.6.",
    },
}

EFFECT_INFO = {
    "STUN": ("Stun", "Skips its next action."),
    "POISON": ("Poison", "Loses health at the end of each turn."),
    "BURN": ("Burn", "Loses health at the end of each turn."),
    "BLEED": ("Bleed", "Loses health at the end of each turn."),
    "WEAKEN": ("Weaken", "Damage is lowered while it lasts."),
    "SLOW": ("Slow", "Speed is lowered while it lasts."),
    "REGENERATION": ("Regeneration", "Heals at the end of each turn, up to max health."),
    "DAMAGEUP": ("Damage up", "Damage is raised while it lasts."),
    "SPEEDUP": ("Speed up", "Speed is raised while it lasts."),
    "HEALTHBOOST": ("Health boost", "Temporary extra health, removed when it ends."),
}

TYPE_INFO = {
    "ATTACK": "Multiplies damage by the quality.",
    "DEFENSE": "Multiplies armor by the quality.",
    "SPEED": "Multiplies speed by the quality.",
    "LUCK": "Multiplies critical chance by the quality.",
    "BALANCE": "Applies a gentler boost (quality ^ 0.25) to damage, armor, speed and critical.",
}


def _stand(char_id):
    return CHARACTER_FILE[char_id - 1]


def _scan_specials():
    """Which synergies and terrains each stand's special actually checks."""
    by_synergy, by_terrain = {}, {}
    for sid, func in specials.items():
        try:
            src = inspect.getsource(func)
        except (OSError, TypeError):
            continue
        for name in set(re.findall(r'_has_synergy\([^)]*"(\w+)"\)', src)):
            by_synergy.setdefault(name, set()).add(int(sid))
        for name in set(re.findall(r"Terrain\.(\w+)", src)) - {"DEFAULT"}:
            by_terrain.setdefault(name, set()).add(int(sid))
    return by_synergy, by_terrain


SYNERGY_USERS, TERRAIN_SPECIALS = _scan_specials()


def fmt_bonus(stat, value):
    if stat == "crit_flat":
        return f"+{value} {STAT_LABEL[stat]}"
    return f"+{round(value * 100)}% {STAT_LABEL[stat]}"


def terrain_rows():
    rows = []
    for terrain in Terrain:
        setters = sorted((cid for cid, t in TERRAIN_SETTERS.items() if t == terrain),
                         key=lambda cid: _stand(cid)["name"])
        boosted = []
        for cid, by_terrain in TERRAIN_BENEFITS.items():
            if terrain in by_terrain:
                boosted.append({"stand": _stand(cid),
                                "bonuses": [fmt_bonus(s, v) for s, v in by_terrain[terrain]]})
        boosted.sort(key=lambda b: b["stand"]["name"])
        rows.append({
            "key": terrain.name.lower(), "name": terrain.display_name, "emoji": terrain.emoji,
            "blurb": TERRAIN_BLURB.get(terrain.name, ""),
            "setters": [_stand(c) for c in setters],
            "boosted": boosted,
            "specials": [_stand(c) for c in sorted(TERRAIN_SPECIALS.get(terrain.name, ()))],
        })
    return rows


def synergy_rows():
    rows = []
    for key, members in SYNERGIES.items():
        label, icon = SYNERGY_INFO.get(key, (key.replace("_", " ").title(), "✶"))
        effects = SYNERGY_EFFECTS.get(key, {})
        users = SYNERGY_USERS.get(key, set())
        rows.append({
            "key": key, "name": label, "icon": icon,
            "rule": "Both stands on the team." if len(members) == 2 else "Any 2 of these on the team.",
            "members": [{"stand": _stand(c), "effect": effects.get(c) if c in users else None}
                        for c in sorted(members)],
            "active": len(users),
        })
    return rows


def effect_rows():
    negative = {e.name for e in NEGATIVE_EFFECTS}
    return [{"key": e.name, "emoji": Emoji[e.name], "name": EFFECT_INFO[e.name][0],
             "text": EFFECT_INFO[e.name][1], "negative": e.name in negative}
            for e in EffectType if e.name in EFFECT_INFO]


def type_rows():
    return [{"name": t.name.title(), "emoji": t.emoji, "text": TYPE_INFO[t.name]} for t in Types]


def quality_rows():
    return [{"name": q.name.replace("_", " ").title(), "emoji": q.emoji, "coef": q.coef, "rank": q.rank}
            for q in Qualities]


def rank_rows():
    return [{"name": name, "elo": elo} for elo, name in reversed(logic.RANK_TIERS)]


def stand_links(stand_id):
    """Terrain and synergy facts for one stand's detail page."""
    sets = TERRAIN_SETTERS.get(stand_id)
    boosts = [{"key": t.name.lower(), "name": t.display_name, "emoji": t.emoji,
               "bonuses": [fmt_bonus(s, v) for s, v in perks]}
              for t, perks in TERRAIN_BENEFITS.get(stand_id, {}).items()]
    reacts = [{"key": t.lower(), "name": Terrain[t].display_name, "emoji": Terrain[t].emoji}
              for t, ids in TERRAIN_SPECIALS.items() if stand_id in ids]
    synergies = []
    for key, members in SYNERGIES.items():
        if stand_id in members:
            label, icon = SYNERGY_INFO.get(key, (key, "✶"))
            effect = SYNERGY_EFFECTS.get(key, {}).get(stand_id) if stand_id in SYNERGY_USERS.get(key, ()) else None
            partners = [_stand(c) for c in sorted(members) if c != stand_id]
            synergies.append({"key": key, "name": label, "icon": icon, "effect": effect, "partners": partners})
    return {"sets": sets, "boosts": boosts, "reacts": reacts, "synergies": synergies}


def facts():
    """Engine numbers quoted across the guide pages."""
    return {
        "xp_per_level": character_mod.STXPTOLEVEL, "max_level": character_mod.MAX_LEVEL,
        "dodge_cap": character_mod.DODGE_CHANCE_CAP, "crit_multiplier": character_mod.CRITMULTIPLIER,
        "reforge_cost": logic.REFORGE_COST, "max_presets": logic.MAX_TEAMS,
        "daily_hours": logic.DONOR_ADV_WAIT_TIME + logic.NORMAL_ADV_WAIT_TIME,
        "daily_hours_donor": logic.DONOR_ADV_WAIT_TIME,
        "wormhole_hours": logic.DONOR_WH_WAIT_TIME + logic.NORMAL_WH_WAIT_TIME,
        "wormhole_hours_donor": logic.DONOR_WH_WAIT_TIME,
    }


def _stand_tags():
    """stand id -> [(icon, tooltip)] for card badges: terrain it sets, synergies it belongs to."""
    tags = {}
    for cid, terrain in TERRAIN_SETTERS.items():
        tags.setdefault(cid, []).append((terrain.emoji, f"Sets {terrain.display_name}"))
    for key, members in SYNERGIES.items():
        label, icon = SYNERGY_INFO.get(key, (key, "✶"))
        for cid in members:
            active = cid in SYNERGY_USERS.get(key, ())
            tags.setdefault(cid, []).append((icon, f"{label} synergy" + ("" if active else " (enabler)")))
    return tags


STAND_TAGS = _stand_tags()
