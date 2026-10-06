"""Over Heaven: the endgame PvE. Every PvE mode has an Over Heaven track of hand-made fights; each one is a
puzzle built around a rule that a raw UR/LR stack can't brute-force, and that the right preparation
(synergies, resonances, terrain, going second, damage over time...) takes apart.

Fight rules (Fight.rules, read by the engine through the hooks below):
  terrain       the field is locked to this terrain for the whole fight
  enemy_first   the enemy always moves first (you get the counter stance)
  heaven_tax    your UR and LR stands lose this share of their damage and max health
  ward          enemies take this much less from your stands that aren't in an active synergy
  native_ward   the same, but only natives of the locked terrain hit at full strength
  part_ward     [part, share]: the same, but only stands from that part of the story hit at full strength
  heal_cut      your healing (specials, regeneration, lifesteal) is this much weaker
  stun_immune   enemies can't be stunned
  regen         enemies heal this share of their max health at the end of each of their turns
  enrage        enemies gain this share of their starting damage at the end of each of their turns
  reflect       this share of every basic hit on an enemy comes back to the attacker as true damage
  purge         enemies shed every negative effect at the end of each of their turns
  pressure      your stands lose this share of their max health at the end of each of your turns

Save: data["web_over_heaven"] = {track key: stages cleared}
"""
from typing import List, Optional

from app.game.character import CHARACTER_FILE, character_from_dict
from app.game.effects import NEGATIVE_EFFECTS, STAT_EFFECTS, Terrain

RULE_TEXT = {
    "terrain": lambda v: f"The field is locked: {Terrain.from_string(v).emoji} {Terrain.from_string(v).display_name} "
                         f"all fight long. {Terrain.from_string(v).rule}",
    "enemy_first": lambda v: "The enemy always moves first.",
    "heaven_tax": lambda v: f"Borrowed power: your UR and LR stands lose {v:.0%} of their damage and health.",
    "ward": lambda v: f"Ward: stands outside an active synergy deal {v:.0%} less to the enemy.",
    "native_ward": lambda v: f"Home ground: only the field's natives hit at full strength; everyone else deals {v:.0%} less.",
    "part_ward": lambda v: f"Their own story: only Part {v[0]} stands hit at full strength; everyone else deals {v[1]:.0%} less.",
    "heal_cut": lambda v: ("Nothing on your side can heal." if v >= 1 else f"Your healing is {v:.0%} weaker."),
    "stun_immune": lambda v: "The enemy can't be stunned.",
    "regen": lambda v: f"The enemy heals {v:.0%} of its health every turn.",
    "enrage": lambda v: f"The enemy grows {v:.0%} stronger every turn.",
    "reflect": lambda v: f"{v:.0%} of every basic hit on the enemy comes back to the attacker.",
    "purge": lambda v: "The enemy sheds every debuff and damage over time at the end of its turns.",
    "pressure": lambda v: f"Heaven's pressure: your stands lose {v:.0%} of their health at the end of each turn.",
}


def rule_lines(rules: dict) -> List[str]:
    return [RULE_TEXT[k](v) for k, v in rules.items() if k in RULE_TEXT and v]


# ── The tracks ──────────────────────────────────────────────────────────
# Every enemy is level 100, ★5. A stand entry is (id, types, qualities, item ids, extra) where extra may hold
# "speed"/"armor"/"critical" (points added) for the stand. `power` multiplies the enemies' health and damage:
# it was calibrated with the team simulator so that raw UR/LR stacks lose and a team built for the rule wins.
U, S, G = "UNIVERSAL", "SUPREME", "GREAT"
TRACKS = [
    {
        "key": "story", "mode": "Story", "title": "The Bizarre Journey · Over Heaven", "color": "#7A3FB8",
        "intro": "The Arrow takes you back through every part, but the villains remember you now, and they "
                 "have prepared too.",
        "fights": [
            {"title": "Stopped Time", "power": 1.69,
             "enemies": [(10, ["ATTACK", "SPEED"], [U, S], [37], {}), (30, ["ATTACK"], [U], [45], {}),
                         (19, ["LUCK"], [U], [42], {})],
             "rules": {"enemy_first": True, "ward": 0.4},
             "text": "DIO's household already knows how the fight starts: with you a step behind.",
             "hint": "They always move first and shrug off stands outside a synergy. Weather the opening with "
                     "the counter stance, then win the long game with Lifesteal or Second Wind."},
            {"title": "The Endless Morning", "power": 1.25,
             "enemies": [(58, ["HEALTH", "DEFENSE"], [U, S], [43], {}), (49, ["ATTACK"], [U], [42], {}),
                         (54, ["HEALTH"], [U], [46], {})],
             "rules": {"terrain": "NATURE", "regen": 0.08, "native_ward": 0.5},
             "text": "Bites the Dust rewinds every wound. On a Nature field, the morning heals everything.",
             "hint": "They heal 8% a turn and only Nature natives hit them at full strength. Bring Nature natives "
                     "(Gold Experience, Purple Haze, Green Day, Stray Cat...): poison is 50% stronger here too."},
            {"title": "Heaven's Acceleration", "power": 2.13,
             "enemies": [(94, ["SPEED"], [U], [44], {"speed": 30}), (108, ["SPEED", "ATTACK"], [U, S], [5], {}),
                         (107, ["SPEED", "ATTACK"], [U, S], [5], {})],
             "rules": {"enrage": 0.06, "heal_cut": 0.5},
             "text": "Pucci's guard moves faster than thought, and Weather Report floods the field.",
             "hint": "Their speed holds an Ocean field and turns your attacks into misses. Take the field back: "
                     "a Home Field team keeps its terrain whatever the speed (Gravity: nobody can dodge)."},
            {"title": "The Road to Cairo", "power": 1.54,
             "enemies": [(10, ["ATTACK"], [U], [42], {}), (25, ["ATTACK", "LUCK"], [U, S], [42], {}),
                         (16, ["HEALTH"], [U], [46], {})],
             "rules": {"part_ward": [3, 0.5], "pressure": 0.03},
             "text": "Fifty days across the world, and DIO's assassins have learned every Crusader's trick.",
             "hint": "Only Part 3 stands hit them at full strength, and the journey wears you down. Bring a whole "
                     "Part 3 team: the Crusaders, DIO's Tarot, the Nine Gods (the Part 3 synergy needs all three)."},
            {"title": "Morioh's Rules", "power": 1.7,
             "enemies": [(58, ["HEALTH", "ATTACK"], [U, S], [37], {}), (53, ["SPEED"], [U], [44], {"speed": 15}),
                         (56, ["DEFENSE"], [U], [43], {})],
             "rules": {"part_ward": [4, 0.5], "enemy_first": True},
             "text": "A quiet town that only answers to its own. Kira has made sure of it.",
             "hint": "Only Part 4 stands hit them at full strength, and they move first. A Morioh team: Bow and "
                     "Arrow, the townsfolk, Josuke & Okuyasu, Echoes, with the Part 4 synergy on top."},
            {"title": "Calamity", "power": 1.92,
             "enemies": [(161, ["HEALTH", "ATTACK"], [U, S], [37], {}), (154, ["ATTACK"], [U], [45], {}),
                         (149, ["ATTACK"], [U], [42], {})],
             "rules": {"heaven_tax": 0.4, "ward": 0.5},
             "text": "Wonder of U turns pursuit into calamity. The stronger you are, the harder the world pushes back.",
             "hint": "UR and LR stands fight at 60%, and only stands inside a synergy hit hard. A full synergy "
                     "team of lower rarities, ideally lighting several resonances."},
        ],
    },
    {
        "key": "alt_universe", "mode": "Alternate Universe", "title": "What If · Over Heaven", "color": "#9B1D3A",
        "intro": "Every timeline where the villains won, folded into one. They have had years to get ready.",
        "fights": [
            {"title": "The Diary of Heaven", "power": 1.94,
             "enemies": [(10, ["DEFENSE", "HEALTH"], [U, S], [43], {"armor": 250}),
                         (27, ["DEFENSE"], [U], [44], {"armor": 250}), (29, ["DEFENSE"], [U], [46], {"armor": 250})],
             "rules": {"stun_immune": True},
             "text": "DIO's guard stands behind armor no fist has broken. Horus freezes the library.",
             "hint": "Walls of armor. Pierce it: Mirror World crits ignore armor, Triple Bond strikes ignore 30% "
                     "of it, and armor-break or true-damage specials."},
            {"title": "Requiem of All", "power": 1.7,
             "enemies": [(84, ["HEALTH", "DEFENSE"], [U, S], [43], {}), (83, ["HEALTH"], [U], [46], {}),
                         (60, ["HEALTH"], [U], [46], {})],
             "rules": {"reflect": 0.4, "heal_cut": 0.5, "stun_immune": True},
             "text": "Under Requiem, every action returns to zero, and to its sender.",
             "hint": "40% of every basic hit comes back and your healing is halved. Win with specials and damage "
                     "over time (poison, bleed, burn), not with raw attackers or heals."},
            {"title": "Heaven Reached", "power": 2.22,
             "enemies": [(109, ["ATTACK"], [U], [45], {}), (108, ["ATTACK"], [U], [42], {}),
                         (107, ["HEALTH"], [U], [43], {})],
             "rules": {"enrage": 0.12, "heal_cut": 1},
             "text": "Time accelerates every turn. Wait, and the universe resets without you.",
             "hint": "They grow 12% stronger every turn and you can't heal: you have a handful of turns. Burst, "
                     "Initiative (Fated Clash) and Dark Network's ambush to open the fight on your terms."},
            {"title": "Passione Ascendant", "power": 2.11,
             "enemies": [(75, ["ATTACK", "SPEED"], [U, S], [42], {}), (81, ["ATTACK"], [U], [45], {}),
                         (82, ["SPEED"], [U], [5], {})],
             "rules": {"part_ward": [5, 0.5], "regen": 0.04},
             "text": "The Boss kept his throne, and his guard grows back faster than you can cut it.",
             "hint": "Only Part 5 stands hit them at full strength, and they heal 4% a turn. A Naples team: "
                     "Passione, La Squadra, the Boss's guard, Zucchero & Sale, with the Part 5 synergy."},
            {"title": "Prison Without Walls", "power": 2.0,
             "enemies": [(107, ["HEALTH"], [U], [43], {}), (104, ["ATTACK"], [U], [42], {}),
                         (102, ["DEFENSE"], [U], [44], {})],
             "rules": {"part_ward": [6, 0.5], "enrage": 0.06},
             "text": "Green Dolphin Street never closed. Pucci rewrote the walls into the world itself.",
             "hint": "Only Part 6 stands hit them at full strength, and they grow 6% stronger every turn. A "
                     "Stone Ocean team: Jolyne's crew, Pucci's agents, DIO's sons, with the Part 6 synergy."},
            {"title": "The Saint's Corpse", "power": 1.45,
             "enemies": [(120, ["HEALTH", "ATTACK"], [U, S], [37], {}), (123, ["ATTACK"], [U], [42], {}),
                         (135, ["ATTACK"], [U], [42], {})],
             "rules": {"purge": True, "regen": 0.05, "ward": 0.3},
             "text": "D4C pulls a fresh self from another world. Every curse on him is left behind.",
             "hint": "They cleanse every debuff and heal each turn. Raw synergy damage wins: Giant Slayer "
                     "against the UR leader, Resonant Strikes through their armor."},
        ],
    },
    {
        "key": "rush", "mode": "Boss rush", "title": "Boss Rush · Over Heaven", "color": "#D6246E",
        "intro": "Four bosses who studied every run you ever made. Each one closes a door your team relies on.",
        "fights": [
            {"title": "Crimson Erasure", "power": 2.3,
             "enemies": [(75, ["ATTACK", "SPEED"], [U, S], [42], {}), (69, ["ATTACK"], [U], [45], {}),
                         (60, ["HEALTH"], [U], [43], {})],
             "rules": {"pressure": 0.04, "stun_immune": True},
             "text": "King Crimson erases the seconds you would have used to heal.",
             "hint": "Your stands lose 4% of their health every turn. Sustain decides it: Lifesteal, Second "
                     "Wind and Nature regeneration."},
            {"title": "Love Train", "power": 2.29,
             "enemies": [(120, ["DEFENSE", "HEALTH"], [U, S], [43], {}), (134, ["ATTACK", "SPEED"], [U, S], [5], {}),
                         (115, ["ATTACK"], [U], [42], {})],
             "rules": {"enemy_first": True, "ward": 0.5},
             "text": "Every misfortune the Love Train turns away lands on you.",
             "hint": "They act first, and stands outside a synergy barely scratch them. Every stand needs a "
                     "partner: build around two or three overlapping synergies."},
            {"title": "Pursuit", "power": 1.45,
             "enemies": [(161, ["HEALTH"], [U], [37], {}), (148, ["ATTACK"], [U], [45], {}),
                         (159, ["ATTACK"], [U], [42], {})],
             "rules": {"heaven_tax": 0.5, "terrain": "GRAVITY", "native_ward": 0.5},
             "text": "On a field where nothing can dodge, borrowed power is the first thing calamity finds.",
             "hint": "UR and LR fight at half strength, nobody dodges, and only Gravity natives hit at full "
                     "strength: C-Moon, Jumpin' Jack Flash, Ball Breaker, the Boom Boom family, I Am a Rock."},
            {"title": "Three Kings of Time", "power": 2.14,
             "enemies": [(10, ["ATTACK"], [U], [37], {}), (58, ["HEALTH"], [U], [43], {}),
                         (75, ["ATTACK", "SPEED"], [U, S], [42], {})],
             "rules": {"heaven_tax": 0.3, "stun_immune": True, "pressure": 0.03},
             "text": "The World, Bites the Dust and King Crimson, together. Time itself is against you.",
             "hint": "Three URs that can't be stunned while your health drains. Lower rarities with Giant Slayer "
                     "(every enemy is a UR) and sustain: Lifesteal, Second Wind."},
            {"title": "Requiem Gauntlet", "power": 2.3,
             "enemies": [(84, ["HEALTH"], [U], [43], {}), (83, ["ATTACK"], [U], [42], {}),
                         (109, ["SPEED"], [U], [5], {})],
             "rules": {"reflect": 0.3, "enemy_first": True, "heal_cut": 0.5},
             "text": "Every Requiem the Arrow ever made, waiting at the end of the run.",
             "hint": "They act first, reflect 30% of basic hits and halve your healing. Win with specials and "
                     "damage over time."},
            {"title": "The Final Stack", "power": 1.7,
             "enemies": [(109, ["ATTACK", "SPEED"], [U, U], [37], {}), (84, ["ATTACK", "HEALTH"], [U, U], [37], {}),
                         (114, ["ATTACK", "LUCK"], [U, U], [37], {})],
             "rules": {"heaven_tax": 0.3},
             "text": "The three most powerful stands in existence, maxed out and holding the Holy Corpse.",
             "hint": "The ultimate stack. Meet it with Giant Slayer: three lower-rarity stands lighting two or "
                     "more synergies hit Mythics far harder than Mythics hit them."},
        ],
    },
    {
        "key": "tower", "mode": "Tower", "title": "The Tower · Over Heaven", "color": "#2BB3A8",
        "intro": "Four floors above the clouds, each one a world of its own. The field is fixed; your team is not.",
        "fights": [
            {"title": "Floor of Tides", "power": 1.9,
             "enemies": [(7, ["ATTACK"], [U], [42], {}), (71, ["HEALTH"], [U], [43], {}), (22, ["ATTACK"], [U], [42], {})],
             "rules": {"terrain": "OCEAN", "native_ward": 0.6},
             "text": "The floor is underwater. Every native swims; everyone else wades.",
             "hint": "A locked Ocean field where only natives hit at full strength. Bring Ocean natives "
                     "(Dark Blue Moon, Clash, Beach Boy, Aqua Necklace, Geb, Jolyne's crew)."},
            {"title": "Floor of Ice", "power": 1.45,
             "enemies": [(74, ["DEFENSE"], [U], [44], {}), (27, ["LUCK"], [U], [42], {}), (146, ["LUCK"], [U], [6], {})],
             "rules": {"terrain": "FROZEN", "native_ward": 0.6},
             "text": "Frozen wastes where every critical hit shatters twice as hard.",
             "hint": "A locked Frozen field (crits x2) where only natives hit at full strength. Luck builds and "
                     "Frozen natives (White Album, Horus, Born This Way, The Hermit Purple, Echoes Act 2)."},
            {"title": "Floor of Sand", "power": 1.9,
             "enemies": [(18, ["HEALTH"], [U], [43], {}), (2, ["ATTACK"], [U], [42], {}), (143, ["ATTACK"], [U], [42], {})],
             "rules": {"terrain": "DESERT", "regen": 0.06, "native_ward": 0.6},
             "text": "The Sun never sets on this floor, and its guards heal in the heat.",
             "hint": "A locked Desert field (healing -30%, burns +50%) where they regenerate and only natives hit "
                     "at full strength. Burn them with Desert natives (Magician's Red, The Fool, the Nine Gods)."},
            {"title": "Floor of Gravity", "power": 1.7,
             "enemies": [(95, ["DEFENSE"], [U], [44], {}), (115, ["ATTACK"], [U], [42], {}),
                         (148, ["ATTACK"], [U], [42], {})],
             "rules": {"terrain": "GRAVITY", "native_ward": 0.6, "heaven_tax": 0.35},
             "text": "A floor where everything falls toward you, and nothing can step aside.",
             "hint": "A locked Gravity field (nobody dodges) where only natives hit at full strength, and UR / LR "
                     "fight at 65%. Gravity natives of lower rarity: C-Moon, Jumpin' Jack Flash, Ball Breaker, the "
                     "Boom Boom family, I Am a Rock."},
            {"title": "Floor of Leaves", "power": 1.8,
             "enemies": [(59, ["HEALTH"], [U], [43], {}), (81, ["ATTACK"], [U], [45], {}),
                         (147, ["ATTACK"], [U], [42], {})],
             "rules": {"terrain": "NATURE", "native_ward": 0.6, "regen": 0.03},
             "text": "A floor overgrown with life, mold and leaves that heal whatever they cover.",
             "hint": "A locked Nature field where only natives hit at full strength and they regenerate. Nature "
                     "natives (Gold Experience, Purple Haze, Green Day, Harvest, Les Feuilles...) and poison."},
            {"title": "Floor of Glass", "power": 1.78,
             "enemies": [(68, ["DEFENSE"], [U], [44], {"armor": 300}), (30, ["DEFENSE"], [U], [43], {"armor": 300}),
                         (13, ["DEFENSE"], [U], [46], {"armor": 300})],
             "rules": {"terrain": "MIRROR", "native_ward": 0.6},
             "text": "A hall of mirrors guarded by stands wrapped in armor.",
             "hint": "Massive armor, but the field is Mirror World: every crit ignores armor, and only natives hit "
                     "at full strength. Luck builds and Mirror natives (Man in the Mirror, Hanged Man, Enigma...)."},
        ],
    },
    {
        "key": "dungeon", "mode": "Daily dungeon", "title": "The Depths · Over Heaven", "color": "#E3A93A",
        "intro": "Below the deepest floor of the dungeon, things wait that were made to beat teams like yours.",
        "fights": [
            {"title": "The Swarm", "power": 1.49,
             "enemies": [(13, ["ATTACK"], [U], [42], {}), (14, ["ATTACK"], [U], [42], {}), (7, ["ATTACK"], [U], [42], {})],
             "rules": {},
             "text": "A pack of assassins who learned to work together: they light their own resonances.",
             "hint": "They ambush you with Dark Network and hit higher rarities harder with Giant Slayer. Answer "
                     "in kind: lower rarities so Giant Slayer has nothing to bite, and resonances of your own."},
            {"title": "Scorched Garden", "power": 2.19,
             "enemies": [(69, ["ATTACK"], [U], [45], {}), (81, ["ATTACK"], [U], [45], {}), (147, ["HEALTH"], [U], [43], {})],
             "rules": {"terrain": "DESERT", "heal_cut": 1, "regen": 0.05},
             "text": "A garden of mold and poison, grown in the sand, that grows back as fast as you cut it.",
             "hint": "You can't heal, they regenerate, and burns deal 50% more on this Desert field. Burn and "
                     "bleed them out faster than they grow back: damage over time and burst, not sustain."},
            {"title": "The Clock", "power": 1.97,
             "enemies": [(58, ["DEFENSE"], [U], [43], {}), (126, ["HEALTH"], [U], [43], {}), (31, ["DEFENSE"], [U], [44], {})],
             "rules": {"pressure": 0.06, "enrage": 0.05, "heal_cut": 1},
             "text": "Time runs out for everyone here; it just runs out faster for you.",
             "hint": "You lose 6% a turn, can't heal, and they grow 5% stronger: tanks lose. Pure burst: "
                     "Initiative, Resonant Strikes, high damage synergies (Squadra, Boom Boom, Tarot)."},
            {"title": "The Steel Ball Run", "power": 1.9,
             "enemies": [(117, ["SPEED", "ATTACK"], [U, S], [5], {}), (134, ["ATTACK"], [U], [42], {}),
                         (121, ["ATTACK"], [U], [42], {})],
             "rules": {"part_ward": [7, 0.5], "enemy_first": True},
             "text": "Deep below, the race never ended. Diego is still in the lead.",
             "hint": "Only Part 7 stands hit them at full strength, and they move first. A Steel Ball Run team: "
                     "the Tusk acts, the racers, Valentine's agents, the Saint's Corpse, with the Part 7 synergy."},
            {"title": "The Wall Eyes", "power": 1.56,
             "enemies": [(161, ["HEALTH"], [U], [37], {}), (159, ["DEFENSE"], [U], [43], {}),
                         (156, ["ATTACK"], [U], [42], {})],
             "rules": {"part_ward": [8, 0.5], "heaven_tax": 0.4},
             "text": "Where the earthquake raised the walls, something waits that takes as much as it gives.",
             "hint": "Only Part 8 stands hit them at full strength, and UR / LR fight at 60%. A JoJolion team: "
                     "the Higashikata family, the Rock Humans, the Wall Eyes duo, with the Part 8 synergy."},
            {"title": "The Abyss", "power": 4.7,
             "enemies": [(10, ["ATTACK", "HEALTH"], [U, U], [37], {"hp": 9000, "damage": 330})],
             "rules": {"enemy_first": True, "purge": True, "reflect": 0.2, "heaven_tax": 0.3},
             "text": "At the very bottom, something that was DIO waits Over Heaven.",
             "hint": "One giant that acts first, cleanses and reflects: no stack out-damages it. Outlast it "
                     "instead. Healers and cleanses (Crazy Diamond), Second Wind and Lifesteal carry you to sudden "
                     "death, which takes its health by share like everyone else's."},
        ],
    },
]
BY_KEY = {t["key"]: t for t in TRACKS}
LEVEL, AWAKEN = 100, 5
TOTAL = sum(len(t["fights"]) for t in TRACKS)
TITLE = "Over Heaven"  # every track cleared
REWARDS = [  # by stage within a track, paid on the first clear (at the economy's pace, economy.py)
    {"fragments": 5600, "super": 0, "items": [38]},
    {"fragments": 7000, "super": 1, "items": [39, 40]},
    {"fragments": 7000, "super": 0, "items": [38, 40]},
    {"fragments": 8400, "super": 1, "items": [38, 39]},
    {"fragments": 9800, "super": 0, "items": [39, 40, 38]},
    {"fragments": 14000, "super": 2, "items": [3]},  # a Requiem Arrow for the track's last fight
]
REPLAY_ENERGY = 2


def enemy_team(key: str, j: int) -> list:
    fight = BY_KEY[key]["fights"][j]
    team = []
    for cid, types, quals, items, extra in fight["enemies"]:
        c = character_from_dict({"id": cid, "xp": LEVEL * 100, "awaken": AWAKEN, "types": list(types),
                                 "qualities": list(quals), "items": [{"id": i} for i in items]})
        for stat in ("hp", "damage"):
            if stat in extra:
                setattr(c, f"start_{stat}", extra[stat])
            value = int(getattr(c, f"start_{stat}") * fight["power"])
            setattr(c, f"start_{stat}", value)
            setattr(c, f"current_{stat}", value)
        for stat in ("speed", "armor", "critical"):
            if stat in extra:
                value = max(0, getattr(c, f"start_{stat}") + extra[stat])
                setattr(c, f"start_{stat}", value)
                setattr(c, f"current_{stat}", value)
        team.append(c)
    return team


def foe_name(key: str, j: int) -> str:
    return f"Over Heaven · {BY_KEY[key]['fights'][j]['title']}"


# ── Progress ─────────────────────────────────────────────────────────────

# Tracks had 4 fights before the two per track inserted ahead of each finale. A save from then counts fights
# cleared in the old order; it's moved once: the old fights before the finale stay cleared, and everything it was
# paid for is remembered (paid), so the finale never pays twice.
OLD_ORDER = {
    "story": ["Stopped Time", "The Endless Morning", "Heaven's Acceleration", "Calamity"],
    "alt_universe": ["The Diary of Heaven", "Requiem of All", "Heaven Reached", "The Saint's Corpse"],
    "rush": ["Crimson Erasure", "Love Train", "Pursuit", "The Final Stack"],
    "tower": ["Floor of Tides", "Floor of Ice", "Floor of Sand", "Floor of Glass"],
    "dungeon": ["The Swarm", "Scorched Garden", "The Clock", "The Abyss"],
}
SAVE_VERSION = 2


def progress(user) -> dict:
    p = user.data.setdefault("web_over_heaven", {})
    if p.get("v") != SAVE_VERSION:
        paid = []
        for key, titles in OLD_ORDER.items():
            done = int(p.get(key, 0))
            paid += [f"{key}:{t}" for t in titles[:done]]
            p[key] = min(done, len(titles) - 1)  # the old finale now comes after the new fights
        p.update(v=SAVE_VERSION, paid=paid)
    return p


def cleared(user, key: str) -> int:
    return int(progress(user).get(key, 0))


def total_cleared(user) -> int:
    return sum(cleared(user, t["key"]) for t in TRACKS)


def unlocked(user) -> bool:
    """Over Heaven opens once the story is finished."""
    from app.game import story
    return story.cleared(user) >= story.TOTAL


def reward_text(j: int) -> List[str]:
    from app.game.items import item_file
    r = REWARDS[min(j, len(REWARDS) - 1)]
    parts = [f"{r['fragments']:,} Meteor Dust"]
    if r["super"]:
        parts.append(f"{r['super']} Arrowhead{'s' if r['super'] > 1 else ''}")
    return parts + [item_file[i - 1]["name"] for i in r["items"]]


def stand_view(entry) -> dict:
    cid, types, quals, items, extra = entry
    from app.game.items import item_file
    return {"stand": CHARACTER_FILE[cid - 1], "build": " · ".join(f"{t.title()} {q.replace('_', ' ').title()}"
                                                                   for t, q in zip(types, quals)),
            "gear": [item_file[i - 1]["name"] for i in items]}


def tracks(user) -> list:
    out = []
    for t in TRACKS:
        done = cleared(user, t["key"])
        fights = [{"index": j, "title": f["title"], "text": f["text"], "hint": f["hint"],
                   "rules": rule_lines(f["rules"]), "enemies": [stand_view(e) for e in f["enemies"]],
                   "reward": reward_text(j),
                   "state": "cleared" if j < done else "current" if j == done else "locked"}
                  for j, f in enumerate(t["fights"])]
        out.append({**{k: t[k] for k in ("key", "mode", "title", "color", "intro")}, "fights": fights,
                    "cleared": done, "total": len(t["fights"])})
    return out


def check_can_fight(user, key: str, j: int):
    from app.game.logic import GameError, spend_energy
    if not unlocked(user):
        raise GameError("Over Heaven opens once you finish the story.")
    if key not in BY_KEY or not 0 <= j < len(BY_KEY[key]["fights"]):
        raise GameError("That fight doesn't exist.")
    if not user.main_characters:
        raise GameError("Put stands in your team first.")
    if j > cleared(user, key):
        raise GameError("Clear the fights before it first.")
    if j < cleared(user, key):
        spend_energy(user, REPLAY_ENERGY, f"Replaying an Over Heaven fight costs {REPLAY_ENERGY} energy.")


def win(user, key: str, j: int) -> dict:
    """First clear pays the stage's reward (and the title once every track is done); replays pay nothing."""
    from app.game import titles
    from app.game.items import item_from_dict
    rewards = {"won": True, "fragments": 0, "xp": 0, "stand_xp": 0, "item": None}
    if j != cleared(user, key):
        return rewards
    p = progress(user)
    p[key] = j + 1
    tag = f"{key}:{BY_KEY[key]['fights'][j]['title']}"
    if tag in p["paid"]:  # beaten before the tracks grew (OLD_ORDER): progress again, but no second reward
        rewards["item"] = "no second reward: you cleared this fight before the track grew"
        if total_cleared(user) >= TOTAL:
            titles.grant(user, TITLE)
        return rewards
    p["paid"].append(tag)
    r = REWARDS[min(j, len(REWARDS) - 1)]
    user.fragments += r["fragments"]
    user.super_fragments += r["super"]
    items = [item_from_dict({"id": i}) for i in r["items"]]
    user.items.extend(items)
    names = [i.name for i in items] + ([f"{r['super']} Arrowhead{'s' if r['super'] > 1 else ''}"] if r["super"] else [])
    if total_cleared(user) >= TOTAL and titles.grant(user, TITLE):
        names.append(f"the title “{TITLE}”")
    rewards.update(fragments=r["fragments"], item=", ".join(names))
    return rewards


# ── Engine hooks (called by Fight) ─────────────────────────────────────────

def _player(fight) -> int:
    return fight.human_side


def apply_rules(fight) -> List[str]:
    """At the start of the fight, after synergies and resonances. Returns the lines for the log."""
    rules = fight.rules
    me, foe = fight.sides[_player(fight)], fight.sides[1 - _player(fight)]
    tax = rules.get("heaven_tax", 0)
    if tax:
        for c in me.chars:
            if c.rarity in ("UR", "LR"):
                c.current_damage *= 1 - tax
                c.start_hp = int(c.start_hp * (1 - tax))
                c.current_hp = min(c.current_hp, c.start_hp)
    if rules.get("ward"):
        from app.game.characterabilities import SYNERGIES, active_synergies
        groups = active_synergies(me.chars)
        for c in me.chars:
            c._bonded = any(c.id in SYNERGIES[g] for g in groups)
        for c in foe.chars:
            c._ward = rules["ward"]
    elif rules.get("part_ward"):
        from app.game.characterabilities import part_of
        part, share = rules["part_ward"]
        for c in me.chars:
            c._bonded = part_of(c.id) == part
        for c in foe.chars:
            c._ward = share
    elif rules.get("native_ward"):
        from app.game.effects import is_native
        field = Terrain.from_string(rules.get("terrain", ""))
        for c in me.chars:
            c._bonded = is_native(c, field)
        for c in foe.chars:
            c._ward = rules["native_ward"]
    for c in me.chars:
        c._heal_cut = 1 - min(1, rules.get("heal_cut", 0))
    for c in foe.chars:
        c._stun_immune = bool(rules.get("stun_immune"))
    return ["☁️ Over Heaven: " + line for line in rule_lines(rules)]


def end_turn(fight, p: int) -> Optional[str]:
    rules = fight.rules
    side = fight.sides[p]
    alive = [c for c in side.chars if c.is_alive()]
    if not alive:
        return None
    if p == _player(fight):
        share = rules.get("pressure", 0)
        if share:
            for c in alive:
                c.take(c.start_hp * share)
            return f"☁️ Heaven's pressure: {side.name}'s stands lose {share:.0%} of their health."
        return None
    notes = []
    if rules.get("purge"):
        for c in alive:
            for e in c.effects:
                if e.type in NEGATIVE_EFFECTS:
                    if e.type in STAT_EFFECTS and e.used:
                        attr, sign = STAT_EFFECTS[e.type]
                        setattr(c, attr, getattr(c, attr) - sign * e.value)
                    e.duration = 0
            c.effects = [e for e in c.effects if e.duration > 0]
        notes.append("shrugs off every debuff")
    if rules.get("regen"):
        healed = sum(c.heal(c.start_hp * rules["regen"]) for c in alive)
        if healed:
            notes.append(f"regenerates {healed}")
    if rules.get("enrage"):
        for c in alive:
            c.current_damage += c.start_damage * rules["enrage"]
        notes.append(f"grows {rules['enrage']:.0%} stronger")
    return f"☁️ {side.name} {', '.join(notes)}." if notes else None


def after_hit(fight, attacker, target, damage: int) -> Optional[str]:
    share = fight.rules.get("reflect", 0)
    if share and target in fight.sides[1 - _player(fight)].chars and attacker.is_alive():
        back = attacker.take(damage * share)
        if back:
            return f"☁️ {target.name} reflects {back} back at {attacker.name}."
    return None
