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
from app.game.characterabilities import AFFINITY, PART_GROUPS, POWER_RANGE, SYNERGIES, SYNERGY_BONUS, SYNERGY_INFO
from app.game import fight as fight_mod
from app.game.effects import Emoji, EffectType, NEGATIVE_EFFECTS, TERRAIN_BENEFITS, TERRAIN_SETTERS, Terrain, fmt_perk

TOPICS = [
    # slug, title, one-line blurb, group
    ("stands", "Getting & upgrading stands", "Banners, rarity odds, pity, levels, fusing and ascension.", "Basics"),
    ("types", "Types & qualities", "What each type boosts and how much each quality multiplies it.", "Basics"),
    ("teams", "Team management", "Main team, storage and saved presets.", "Basics"),
    ("combat", "Combat system", "Turn order, stats, dodge, armor, specials and status effects.", "Combat"),
    ("terrains", "Terrain explorer", "Which stands set each terrain and who gets stronger on it.", "Combat"),
    ("synergies", "Synergy explorer", "Team combos and exactly what each member gains.", "Combat"),
    ("ranked", "Ranked, seasons & duels", "Matchmaking, the rank tiers, monthly seasons and their rewards.", "Modes"),
    ("battles", "Replays, live duels & simulator", "Your fight history, sharing replays, watching duels, testing teams.", "Modes"),
    ("adventure", "Mirror World, tower & dungeon", "PvE modes, cooldowns and rewards.", "Modes"),
    ("events", "Limited-time events", "Event modifiers, tokens and the exchange shop.", "Modes"),
    ("items", "Items & equipment", "Equipping, crafting and where items drop.", "Modes"),
    ("progress", "Mastery, titles & Stand Dex", "Stand mastery levels, profile titles and collection sets.", "Progress"),
    ("gangs", "Gangs & player shops", "Clans, gang chat, the shared market and what they cost.", "Community"),
    ("social", "Friends, gifts & trading", "Invites, daily gifts, the inbox, trades and the auction house.", "Community"),
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
    "FROZEN": "Ice stands harden while everyone else slows down.",
    "MIRROR": "Illusionists reshape the arena and strike from reflections.",
    "NATURE": "Living terrain heals everyone and feeds poison.",
    "GRAVITY": "Gravity users bend speed and damage in their favour.",
}


# What each stand's special does differently while its synergy is active.
SYNERGY_EFFECTS = {
    "crusaders": {
        1: "Always lands one extra punch.",
        2: "Crossfire Hurricane burns every enemy for 2 turns instead of hitting one.",
        3: "Emerald Splash hits at 0.75× instead of 0.55×.",
        6: "Keeps its armor while shedding it for speed (normally −20% armor).",
    },
    "kira": {
        49: "Bombs two enemies for 1.5× plus a burn instead of one for 1.9×.",
        54: "Guided bubbles hit every enemy and add a burn.",
    },
    "squadra": {
        63: "Deflates every enemy (−25% armor, −12% damage) instead of one.",
        68: "Traps two enemies in the mirror (stun, −20% damage) instead of one.",
        72: "Stronger aging: poison 0.45× (from 0.35×) and −30% speed (from −20%).",
        73: "Steals 25% damage (from 20%) plus 15% speed.",
        74: "+40% armor (from 30%) and a stronger slow.",
    },
    "passione": {
        59: "Heals 16% (from 12%) and gives the whole team +15% speed.",
        60: "1.5× strike, +15 crit and +25% speed (normally 1.2× and +10 crit).",
        64: "6 bullets at 0.32× (normally 5 at 0.26×).",
        67: "Strafes at 0.6× (from 0.5×) and makes the weakest enemy bleed.",
    },
    "pucci": {
        107: "The DISC theft also stuns the target.",
        108: "Slows enemies by 25% (from 15%) and cuts their armor by 15%.",
        109: "Other Pucci stands also get +25% speed and +15% damage.",
    },
    "tusk": {
        112: "The guided nail also slows the target.",
        113: "The wormhole nail also poisons the target.",
        114: "Infinite Rotation makes every other enemy bleed.",
    },
    "clash_talking": {
        76: "Warps between two confused enemies, hitting and stunning both.",
        77: "Confuses every enemy: −25% speed and −15% damage.",
    },
    "wall_eyes": {
        137: "Go Beyond: 1.8× true damage that can't be blocked or dodged, steals 40% damage and 25% speed.",
        138: "Gives the team +30% speed (from 20%) and charges Soft & Wet's Go Beyond on the spot.",
    },
    "hol_horse": {
        13: "Rides the Emperor's bullet: a second 0.6× strike on the same target.",
        14: "The headshot bends through a mirror and ignores armor.",
    },
    "kujo": {
        1: "One more punch (stacks with the Crusaders' extra punch).",
        31: "Time stop hits every enemy at 0.95× instead of 0.75×.",
        86: "Hits at 1.0× (from 0.6×) and the bound target also loses 25% armor.",
        163: "Time stop hits every enemy at 0.95× instead of 0.75×.",
    },
    "spin": {
        114: "Infinite rotation also stuns its target.",
        115: "Ages enemies harder (−25% damage and speed, from 15%) and gives allies +15% damage (from 10%).",
    },
    "josuke_okuyasu": {
        32: "Heals 35% (from 25%) and hits at 1.8× (from 1.5×) when nobody needs healing.",
        34: "Drags its target into reach: its special meter goes back to zero.",
    },
    "rohan_koichi": {
        45: "Also writes “cannot defend”: −30% armor on top of the stun.",
        50: "3 Freeze hits at 1.3× (from 1.0×) and slows the others by 35% (from 20%).",
    },
}

EFFECT_INFO = {
    "STUN": ("Stun", "Skips its next turn. A stand that just sat out a stun shrugs off stuns on its following turn."),
    "POISON": ("Poison", "Loses health at the end of each of its turns. Stronger in Nature."),
    "BURN": ("Burn", "Loses health at the end of each of its turns. Stronger in the Desert, put out by the Ocean."),
    "BLEED": ("Bleed", "Loses health at the end of each of its turns."),
    "WEAKEN": ("Weaken", "Damage is lowered while it lasts."),
    "SLOW": ("Slow", "Speed is lowered while it lasts."),
    "ARMORBREAK": ("Armor break", "Armor is lowered while it lasts."),
    "REGENERATION": ("Regeneration", "Heals at the end of each of its turns, up to max health."),
    "DAMAGEUP": ("Damage up", "Damage is raised while it lasts."),
    "SPEEDUP": ("Speed up", "Speed is raised while it lasts."),
    "ARMORUP": ("Armor up", "Armor is raised while it lasts."),
    "CRITUP": ("Critical up", "Critical chance is raised (or lowered) while it lasts."),
}

TYPE_INFO = {
    "ATTACK": "Multiplies damage by the quality. Powers specials that scale with ⚔️ damage.",
    "DEFENSE": "Multiplies armor by the quality. Powers 🛡️ armor specials.",
    "HEALTH": "Multiplies max health by the quality. Powers ❤️ health specials: heals, regeneration, sacrifices.",
    "SPEED": "Adds speed: +20 Universal, +15 Supreme, +10 Great, +4 Good, +2 Sub par. Powers 💨 speed specials.",
    "LUCK": "Adds critical chance (+40 / +30 / +20 / +8 / +4) and critical damage (+0.4 / +0.3 / +0.2 / +0.1). "
            "Powers 🍀 luck specials.",
    "BALANCE": "A bit of everything: quality ^ 0.25 to damage and armor, a quarter of the Speed and Luck "
               "bonuses, and half the type affinity for any special.",
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


fmt_bonus = fmt_perk


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
            "rule": terrain.rule if terrain != Terrain.DEFAULT else "",
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
            "rule": ("A whole team from this part (all 3 fighters). Only teams players build get it, not "
                     "computer-controlled enemies." if key in PART_GROUPS
                     else "Both stands on the team." if len(members) == 2 else "Any 2 of these on the team."),
            "bonus": [fmt_perk(s, v) for s, v in SYNERGY_BONUS.get(key, [])],
            "members": [{"stand": _stand(c), "effect": effects.get(c) if c in users else None}
                        for c in sorted(members)],
            "active": len(users),
        })
    return rows


def resonance_rows():
    from app.game.resonance import RESONANCES
    return [{"key": k, "name": label, "icon": icon, "needs": needs, "effect": effect}
            for k, (label, icon, needs, effect) in RESONANCES.items()]


def leverage_rows():
    from app.game.dex import RARITY_NAMES
    from app.game.effects import RARITY_LEVERAGE
    return [{"rarity": r, "name": RARITY_NAMES.get(r, r), "mult": m} for r, m in RARITY_LEVERAGE.items()]


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


def season_rows():
    from app.game import seasons
    return seasons.reward_table()


def event_shop_rows():
    from app.game import events
    rows = []
    for offer in sorted(events.SHOP, key=lambda o: not o.get("exclusive")):
        item = offer["give"].get("items", [None])[0]
        rows.append({**offer, "item": item, "ability": ITEM_ABILITY.get(item) if item else None})
    return rows


def mastery_rows():
    from app.game import mastery
    return [{"rank": name, "icon": icon, "points": need} for need, name, icon in mastery.LEVELS[1:]]


def dex_rows():
    from app.game import dex
    by_id = {c["id"]: c["name"] for c in CHARACTER_FILE}
    return [{**s, "reward_text": dex.reward_text(s["reward"]), "names": [by_id.get(i, i) for i in s["ids"]]}
            for s in dex.SETS]


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
            synergies.append({"key": key, "name": label, "icon": icon, "effect": effect, "partners": partners,
                              "bonus": [fmt_perk(s, v) for s, v in SYNERGY_BONUS.get(key, [])]})
    return {"sets": sets, "boosts": boosts, "reacts": reacts, "synergies": synergies}


def facts():
    """Engine numbers quoted across the guide pages."""
    return {
        "xp_per_level": character_mod.STXPTOLEVEL, "catch_up": logic.CATCH_UP_LEVEL, "max_level": character_mod.MAX_LEVEL,
        "dodge_cap": character_mod.DODGE_CHANCE_CAP, "dodge_per": character_mod.DODGENERF,
        "crit_multiplier": character_mod.CRITMULTIPLIER,
        "counter_armor": round(fight_mod.COUNTER_ARMOR * 100), "counter_damage": round(fight_mod.COUNTER_DAMAGE * 100),
        "counter_turns": fight_mod.COUNTER_TURNS, "counter_crit": fight_mod.COUNTER_CRIT_MAX,
        "crit_cap": character_mod.CRIT_CHANCE_CAP, "armor_cap": character_mod.ARMOR_CAP,
        "armor_floor": round(200 / (100 + character_mod.ARMOR_CAP) * 100),
        "taunt_armor": character_mod.TAUNT_ARMOR, "growth_cap": round(character_mod.GROWTH_CAP * 100),
        "sudden_death_round": fight_mod.SUDDEN_DEATH_ROUND, "sudden_death_step": round(fight_mod.SUDDEN_DEATH_STEP * 100),
        "sudden_death_heal": round(fight_mod.SUDDEN_DEATH_HEAL * 100), "max_rounds": fight_mod.MAX_ROUNDS,
        "affinity": AFFINITY, "power_range": POWER_RANGE, "fuse_bonus": logic.FUSE_BONUS_XP,
        "reforge_prices": logic.REFORGE_PRICE, "reforge_lock_mult": logic.REFORGE_LOCK_MULT, "max_presets": logic.MAX_TEAMS,
        "daily_hours": logic.DONOR_ADV_WAIT_TIME + logic.NORMAL_ADV_WAIT_TIME,
        "daily_hours_donor": logic.DONOR_ADV_WAIT_TIME,
        "wormhole_minutes": round((logic.DONOR_WH_WAIT_TIME + logic.NORMAL_WH_WAIT_TIME) * 60),
        "energy_minutes": logic.ENERGY_REGEN_MINUTES, "energy_minutes_donor": logic.DONOR_ENERGY_REGEN_MINUTES,
        "energy_can": logic.ENERGY_CAN_AMOUNT, "energy_bank": logic.ENERGY_BANK,
        **_new_facts(),
    }


def _new_facts():
    from app import social
    from app.game import auction, events, gangs, history, mastery, seasons, simulate, trades
    return {
        "season_min": seasons.MIN_GAMES, "season_win": seasons.WIN, "season_loss": seasons.LOSS,
        "season_title_from": seasons.TITLE_FROM,
        "history_keep": history.KEEP, "replay_days": history.REPLAY_DAYS, "sim_runs": simulate.RUNS,
        "event_boost": round(events.BOOST * 100), "event_dust": round(events.DUST_BONUS * 100),
        "tokens_pve": events.TOKENS_PVE, "tokens_pvp": events.TOKENS_PVP,
        "mastery_master": mastery.MASTER,
        "chat_len": gangs.CHAT_MAX_LEN, "chat_keep": gangs.CHAT_KEEP,
        "gifts": social.GIFTS, "gift_cap": social.GIFT_RECEIVE_CAP, "gift_stage": social.REFERRAL_STAGE,
        "max_friends": social.MAX_FRIENDS,
        "trade_days": trades.OFFER_TTL // 86400, "trade_open": trades.MAX_OPEN, "trade_stands": trades.MAX_STANDS,
        "auction_days": auction.LISTING_DAYS, "auction_max": auction.MAX_LISTINGS, "auction_fee": round(auction.FEE * 100),
        "auction_hours": auction.BID_HOURS, "auction_raise": round(auction.MIN_RAISE * 100),
        "auction_snipe": auction.SNIPE_GUARD // 60, "spark_cost": logic.SPARK_COST,
    }


# ── Items: what each one does and every place it comes from ──────────────
# The sources are read from the same tables the game rolls, so this page can't drift from the drops.
ITEM_ABILITY = {
    5: "In fights, every turn: homes in on a random enemy for 40% of the holder's damage as true damage.",
    6: "In fights, every 3 turns: heals 15% of max health, +25% damage and +20 crit for 2 turns.",
    7: "In fights, every 2 turns: heals 10% of max health and +10% damage for good.",
    16: "In fights: if a poisoner hit the holder, it weakens them (-15% damage for a turn).",
    37: "In fights, every turn: the whole team heals 8% and gains +10% damage and armor for 2 turns.",
    41: "In fights, every 3 turns: a Golden Spin throw for 60% damage as true damage that slows the target.",
    43: "In fights, every 3 turns: heals 12% of max health.",
    45: "In fights, every 3 turns: heals 10% of max health and +20% damage for 2 turns.",
    46: "The holder taunts: enemies must hit it first with basic attacks, and it gains the taunt armor bonus.",
}
ITEM_USE = {
    2: "Spent on a banner: 5 stands at SR or better.",
    3: "Awakens a team stand up to ★5. At level 100 it evolves Killer Queen, Silver Chariot and Gold Experience into Requiem.",
    12: "Draws a random Part 3 stand.",
    13: "Opens into Meteor Dust.",
    47: "Drink it for +5 energy. Unlike regen it can push you past your max, up to double it.",
}


def _pct(share: float) -> str:
    value = share * 100
    return f"{value:.1f}%" if value < 10 else f"{round(value)}%"


def _item_sources() -> dict:
    """item id -> [(where, detail)] for every way the game hands it out."""
    from app.game import altverse, dungeon, journey, rush, story, tower
    from app.game.achievements import ALL_ACHIEVEMENTS
    from app.game.gangs import RAID_TIERS
    from app.game.items import item_file
    from app.game.quests import ALL_QUESTS
    out = {}

    def add(item_id, where, detail=""):
        rows = out.setdefault(int(item_id), [])
        if (where, detail) not in rows:
            rows.append((where, detail))

    for entry in logic.DEFAULT_SHOP.values():
        if entry.get("id"):
            add(entry["id"], "Shop", f"{entry['price']:,} Meteor Dust" + (" (weekly summon limit)" if entry.get("summon") else ""))
    total = sum(logic.DAILY_ITEM_DROPS.values())
    for i, w in logic.DAILY_ITEM_DROPS.items():
        add(i, "Daily reward", f"{_pct(logic.DAILY_ITEM_CHANCE / 100 * w / total)} a claim")
    for day, bonus in enumerate(logic.STREAK_REWARDS, start=1):
        for i in bonus.get("items", []):
            add(i, "Daily streak", f"day {day} of the 7-day ladder")
    total = sum(logic.MIRROR_ITEM_DROPS.values())
    for i, w in logic.MIRROR_ITEM_DROPS.items():
        add(i, "Mirror World", f"{_pct(logic.CHANCEITEM / 100 * w / total)} a win")
    floors = {}
    for floor in range(1, tower.REST_EVERY * 3 + 1):  # the reward pattern repeats every 15 floors
        for i in tower.reward_for(floor)["items"]:
            floors.setdefault(i, []).append(floor)
    for i, fs in floors.items():
        add(i, "Tower", f"first clear of floors {', '.join(map(str, fs))}, then every 15 floors")
    story_palms = sum(1 for k in range(story.TOTAL) for i in story.reward_for(k)["items"] if i == 2)
    if story_palms:
        add(2, "Story", f"first clear of every 3rd stage ({story_palms} in all)")
    for c in altverse.CHAPTERS:
        for j in range(len(c["stages"])):
            for i in altverse.reward_for(c["key"], j)["items"]:
                add(i, "Alternate Universe", f"AU · {c['title']}, stage {j + 1}")
    for n, tier in enumerate(rush.REWARDS, start=1):
        for i in tier.get("items", []):
            add(i, "Boss rush", f"weekly reward for beating {n} boss{'es' if n != 1 else ''}")
    for tier in RAID_TIERS:
        for i in tier["items"]:
            for real in ([34, 35, 36] if i == "corpse" else [i]):
                add(real, "Gang raid", f"tier at {tier['damage']:,} damage" + (" (one part at random)" if i == "corpse" else ""))
    for i in journey.ITEM_POOL:
        add(i, "Crusaders' Journey", "chance on any trip; better with longer trips and stronger stands")
    for i, _w in dungeon.CHEST_ITEMS:
        if i:
            add(i, "Dungeon", "chests and elites in the daily dungeon")
    for i in dungeon.BOSS_ITEMS:
        add(i, "Dungeon", "the daily dungeon's boss")
    add(2, "Dungeon", f"the daily dungeon's boss ({round(dungeon.BOSS_PALM * 100)}% chance)")
    from app.game.events import SHOP as EVENT_SHOP
    for offer in EVENT_SHOP:
        for i in offer["give"].get("items", []):
            add(i, "Event shop", f"{offer['cost']} event tokens, {offer['limit']} per event")
    for r in logic.RECIPES:
        parts = ", ".join(f"{n} × {item_file[i - 1]['name']}" for i, n in r["ingredients"])
        add(r["result"], "Crafting", parts)
    for q in ALL_QUESTS:
        for it in (q.get("rewards") or {}).get("items", []):
            add(it["id"], "Quest", q.get("name") or q.get("description", ""))
    for a in ALL_ACHIEVEMENTS:
        for it in (a.get("reward") or {}).get("items", []):
            add(it["id"], "Achievement", a["name"])
    from app.game.items import TORN_DIARY_PAGE
    add(TORN_DIARY_PAGE, "Alternate Universe", "given the first time you face The World Over Heaven (bound: "
                                               "can't be sold or traded)")
    return out


def item_rows() -> list:
    from app.game.items import item_file
    sources = _item_sources()
    used_in = {}
    for r in logic.RECIPES:
        for i, n in r["ingredients"]:
            used_in.setdefault(i, []).append(r["name"])
    rows = []
    for it in item_file:
        iid = it["id"]
        if not it.get("name") or it.get("price") is None:  # leftovers from the bot nobody can get
            continue
        if iid in logic.CHIP_IDS or "Stand Chip" in it["name"]:
            kind = "Stand chip"
        elif it.get("is_equipable"):
            kind = "Gear"
        elif iid in (38, 39, 40):
            kind = "Material"
        elif 34 <= iid <= 36:
            kind = "Corpse part"
        elif iid in ITEM_USE:
            kind = "Usable"
        else:
            kind = "Collectible"
        bonus = [fmt for fmt in (
            f"+{it['bonus_hp']} HP" if it.get("bonus_hp") else "", f"+{it['bonus_damage']} ATK" if it.get("bonus_damage") else "",
            f"+{it['bonus_armor']} ARM" if it.get("bonus_armor") else "", f"+{it['bonus_speed']} SPD" if it.get("bonus_speed") else "",
            f"+{it['bonus_critical']}% CRT" if it.get("bonus_critical") else "") if fmt]
        use = ITEM_USE.get(iid)
        if kind == "Stand chip":
            use = f"Unlocks {it['name'].replace(' Stand Chip', '').strip()} as a stand."
        elif kind == "Corpse part":
            use = "Collect all three to craft the Holy Corpse."
        rows.append({"id": iid, "name": it["name"], "emoji": it.get("emoji") or "◈", "kind": kind, "bonus": bonus,
                     "ability": ITEM_ABILITY.get(iid), "use": use, "sources": sources.get(iid, []),
                     "used_in": used_in.get(iid, []), "sell": logic.sell_price(type("I", (), {"price": it.get("price")})())})
    order = {"Gear": 0, "Usable": 1, "Material": 2, "Corpse part": 3, "Stand chip": 4, "Collectible": 5}
    rows.sort(key=lambda x: (order[x["kind"]], x["id"]))
    return rows


def _stand_tags():
    """stand id -> [(icon, tooltip)] for card badges: terrain it sets, synergies it belongs to."""
    tags = {}
    for cid, terrain in TERRAIN_SETTERS.items():
        tags.setdefault(cid, []).append((terrain.emoji, f"Sets {terrain.display_name}"))
    for key, members in SYNERGIES.items():
        label, icon = SYNERGY_INFO.get(key, (key, "✶"))
        bonus = ", ".join(fmt_perk(s, v) for s, v in SYNERGY_BONUS.get(key, []))
        for cid in members:
            tags.setdefault(cid, []).append((icon, f"{label} synergy: {bonus}"))
    return tags


STAND_TAGS = _stand_tags()
