"""Story mode: The Bizarre Journey (web only).

A Stand Arrow tears the player's avatar out of time and drops them into each
part of the series in turn. In every part they fight beside that part's JoJo,
clearing the villains in order. Each stage is a battle; enemy levels, awakenings
and quality climb exponentially with the stage number, so the last parts need a
fully built team.

Progress lives in the save as data["web_story"] = {"cleared": <stages won>}.
The bot's own story_progress tutorial is left untouched.
"""

from typing import List, Optional

from app.game.character import CHARACTER_FILE, character_from_dict
from app.game.items import item_file, item_from_dict
from app.game.logic import GameError, train

# Difficulty, stage by stage: (enemy level, awakening, quality). Tuned with a 30-day simulation of
# a good daily player (scratch month.py): Part 3 falls on day 1-2, Part 4 in the first week, Part 5
# in week 2, Part 6 in weeks 3-4, Part 7 in the second month, and Part 8 asks for a maxed team.
CURVE = [
    (2, 0, "BAD"),                                                                        # prologue
    (3, 0, "BAD"), (4, 0, "BAD"), (5, 0, "BAD"), (7, 0, "BAD"), (9, 0, "SUB_PAR"),        # Part 3
    (10, 0, "SUB_PAR"), (12, 0, "SUB_PAR"), (14, 0, "SUB_PAR"), (16, 0, "GOOD"), (19, 0, "GOOD"),  # Part 4
    (23, 0, "GOOD"), (26, 0, "GOOD"), (30, 1, "GOOD"), (34, 1, "GOOD"), (38, 1, "GOOD"),  # Part 5
    (44, 1, "GOOD"), (48, 1, "GREAT"), (53, 2, "GREAT"), (58, 2, "GREAT"), (64, 2, "GREAT"),  # Part 6
    (70, 2, "GREAT"), (76, 2, "SUPREME"), (82, 3, "SUPREME"), (88, 3, "SUPREME"), (94, 3, "SUPREME"),  # Part 7
    (100, 3, "SUPREME"), (100, 3, "UNIVERSAL"), (100, 4, "UNIVERSAL"), (100, 4, "UNIVERSAL"), (100, 5, "UNIVERSAL"),  # Part 8
]

PARTS = [
    {
        "part": 0,
        "title": "Prologue · The Arrow",
        "jojo": None,
        "color": "#B3A3CF",
        "intro": "An Arrow falls out of a clear sky and pierces your hand. The world folds. "
        "Somewhere far away, a bloodline older than you is calling for help.",
        "stages": [
            {
                "title": "The Arrow's Test",
                "enemies": [8],
                "text": "Before it carries you anywhere, the Arrow tests you. A flicker of a Stand, a "
                "Tower of Grey, buzzes out of the light. Strike it down and prove you can stand.",
            },
        ],
    },
    {
        "part": 3,
        "title": "Part 3 · Stardust Crusaders",
        "jojo": "Jotaro Kujo",
        "color": "#7A3FB8",
        "intro": "Cairo, 1989, by way of every road between. Jotaro Kujo and the Crusaders race to "
        "reach DIO before Holly Kujo's Stand kills her. They could use one more Stand user.",
        "stages": [
            {
                "title": "Ambush at Sea",
                "enemies": [9, 7],
                "text": 'The ship the Crusaders boarded is itself a Stand. Jotaro nods at you: "You take '
                "the ape's machine. I'll handle the water.\"",
            },
            {
                "title": "The Hanged Man's Mirror",
                "enemies": [13, 14],
                "text": "Hol Horse's Emperor fires from the crowd while Hanged Man moves through every "
                "reflection. Polnareff charges in. You cover his back.",
            },
            {
                "title": "Desert Heat",
                "enemies": [18, 22],
                "text": "Egypt. The Sun bakes the sand and Geb strikes from the water skins, a needle "
                "of water through the dunes. Avdol saved your life once already today.",
            },
            {
                "title": "Gamblers of the Soul",
                "enemies": [29, 27],
                "text": "D'Arby wants your soul as his stake, and Pet Shop's Horus freezes the street "
                "behind you. Iggy growls. No more games.",
            },
            {
                "title": "DIO's Mansion",
                "enemies": [10, 30, 19],
                "boss": True,
                "text": "The World stops time. Only Jotaro can move in it, and only if someone keeps DIO "
                "busy for the seconds that matter. That someone is you.",
            },
        ],
    },
    {
        "part": 4,
        "title": "Part 4 · Diamond is Unbreakable",
        "jojo": "Josuke Higashikata",
        "color": "#D6246E",
        "intro": "Morioh, 1999. A quiet town with a murderer in it. Josuke Higashikata fixes "
        "everything Crazy Diamond touches, except what has already been lost.",
        "stages": [
            {
                "title": "Water in the Faucets",
                "enemies": [33, 35],
                "text": "Anjuro's Aqua Necklace hides in the rain while the Nijimura house bristles with "
                "Bad Company's tiny army. Okuyasu still owes you an apology.",
            },
            {
                "title": "The Arrow's Other Victims",
                "enemies": [37, 38, 39],
                "text": "Someone is handing out Stands with a bow and arrow. Red Hot Chili Pepper "
                "rides the power lines, and the town is suddenly full of doubles.",
            },
            {
                "title": "Highway Star",
                "enemies": [53, 40, 44],
                "text": "A Stand that runs at sixty kilometers an hour and drinks your nutrients. Josuke "
                "drives, you aim. Don't look back at the tunnel.",
            },
            {
                "title": "Kira's Shadow",
                "enemies": [54, 51, 57],
                "text": "Stray Cat's air bubbles drift through the Kira house. Yoshihiro's photo hunts you "
                "from inside a picture. A Cheap Trick whispers on your back.",
            },
            {
                "title": "Another One Bites the Dust",
                "enemies": [58, 49, 54],
                "boss": True,
                "text": "Kira's Bites the Dust rewinds the morning over and over. Hayato remembers every "
                "loop. This time you break it with him.",
            },
        ],
    },
    {
        "part": 5,
        "title": "Part 5 · Golden Wind",
        "jojo": "Giorno Giovanna",
        "color": "#F4C542",
        "intro": "Naples, 2001. Giorno Giovanna has a dream: to become a Gang-Star and clean up "
        "Passione from the inside. Bucciarati's team escorts the Boss's daughter.",
        "stages": [
            {
                "title": "The Train to Florence",
                "enemies": [72, 73],
                "text": "The Grateful Dead ages everyone on board while Baby Face learns how to kill you. "
                "Keep cool: literally, the ice in your hand is all that slows it.",
            },
            {
                "title": "Venice by Boat",
                "enemies": [71, 63, 66],
                "text": "Beach Boy fishes through the hull, Soft Machine deflates the crew. Mista "
                "counts his bullets and refuses to count to four.",
            },
            {
                "title": "La Squadra",
                "enemies": [74, 68, 65],
                "text": "White Album freezes the canal, Man in the Mirror pulls you into the other side, "
                "and Kraft Work pins the bullets in midair. They want the girl.",
            },
            {
                "title": "Rome, the Colosseum",
                "enemies": [81, 82, 80],
                "text": "Green Day's mold spreads downhill, Oasis swims through the pavement, Metallica "
                "pulls iron from your blood. Bucciarati is still walking.",
            },
            {
                "title": "King Crimson",
                "enemies": [75, 83, 78],
                "boss": True,
                "text": "The Boss erases time. Chariot Requiem swaps every soul in Rome. Giorno reaches "
                "for the Arrow; your job is to make sure he lives long enough to touch it.",
            },
        ],
    },
    {
        "part": 6,
        "title": "Part 6 · Stone Ocean",
        "jojo": "Jolyne Cujoh",
        "color": "#2BB3A8",
        "intro": "Green Dolphin Street Prison, Florida, 2011. Jolyne Cujoh was framed. Her father's "
        "memory and Stand were stolen as DISCs. The escape starts from the inside.",
        "stages": [
            {
                "title": "Locked Inside",
                "enemies": [90, 87, 93],
                "text": "Highway to Hell, Goo Goo Dolls and Marilyn Manson collect their debts in the "
                "cell blocks. Jolyne unravels into string and grins at you.",
            },
            {
                "title": "The Ultra Security Unit",
                "enemies": [102, 100, 99],
                "text": "Jail House Lock steals all but three memories at a time. Write everything on your "
                "arm. Yo-Yo Ma is polite while it melts you.",
            },
            {
                "title": "Hurricane Season",
                "enemies": [101, 104, 105],
                "text": "Green Green Grass of Home shrinks the world, Sky High sends the Rods, Underworld "
                "replays the past. Weather Report finally remembers who he is.",
            },
            {
                "title": "Kennedy Space Center",
                "enemies": [95, 108, 107],
                "text": "Jumpin' Jack Flash takes away gravity and C-Moon turns it inside out. Pucci is "
                "almost at the new moon.",
            },
            {
                "title": "Made in Heaven",
                "enemies": [109, 108, 94],
                "boss": True,
                "text": "Time accelerates until the universe loops. Emporio runs. You and Jolyne buy him "
                "every second you can.",
            },
        ],
    },
    {
        "part": 7,
        "title": "Part 7 · Steel Ball Run",
        "jojo": "Johnny Joestar",
        "color": "#E3A93A",
        "intro": "America, 1890. A horse race across a continent, and the Saint's Corpse scattered "
        "along its route. Johnny Joestar can't walk, but his nails spin.",
        "stages": [
            {
                "title": "The Start in San Diego",
                "enemies": [116, 119, 122],
                "text": "Riders sabotage the first stage. Oh! Lonesome Me lassos the leaders. Gyro "
                "teaches you the Spin with a wink and a steel ball.",
            },
            {
                "title": "Rocky Mountains",
                "enemies": [117, 123, 135],
                "text": "Diego's Scary Monsters hunt as dinosaurs, and the Boom Boom family magnetizes "
                "every bit of iron in your body.",
            },
            {
                "title": "Philadelphia",
                "enemies": [121, 127, 132],
                "text": "In a Silent Way turns sounds into blades, Catch the Rainbow walks on frozen rain, "
                "and Civil War drags up every guilt you've ever buried.",
            },
            {
                "title": "The President's Guard",
                "enemies": [124, 126, 125],
                "text": "Mandom rewinds six seconds, Wired drags you on hooks, Boku no Rhythm sets its "
                "ticking bombs. Valentine is watching from the next dimension.",
            },
            {
                "title": "Love Train",
                "enemies": [120, 134, 115],
                "boss": True,
                "text": "D4C hides behind the Love Train, Diego's World stops time, and the Ball Breaker "
                "ages everything it touches. Johnny spins the golden rectangle. You make sure "
                "the shot lands.",
            },
        ],
    },
    {
        "part": 8,
        "title": "Part 8 · JoJolion",
        "jojo": "Gappy (Josuke Higashikata)",
        "color": "#3BA7E0",
        "intro": "Morioh again, 2011, but not the one you knew. A young man was found buried by the "
        "Wall Eyes with no memory. Soft & Wet takes things away, and so does this town.",
        "stages": [
            {
                "title": "The Wall Eyes",
                "enemies": [139, 147, 145],
                "text": "Doggy Style unravels, Les Feuilles poisons the garden, and California King Bed "
                "steals a memory for every rule you break.",
            },
            {
                "title": "The Rokakaka Smugglers",
                "enemies": [140, 143, 158],
                "text": "Nut King Call unscrews limbs, Speed King stores heat in your blood, and Ozon "
                "Baby raises the pressure underground.",
            },
            {
                "title": "The Higashikata House",
                "enemies": [148, 159, 156],
                "text": "I Am a Rock pulls everything to its target, Doctor Wu dissolves into stone, and "
                "Blue Hawaii takes control of anyone it touches. Family dinner is tense.",
            },
            {
                "title": "The Hospital",
                "enemies": [154, 149, 160],
                "text": "Walking Heart's heels pierce the walls, Doobie Wah follows your breath. "
                "The head doctor smiles too politely.",
            },
            {
                "title": "Wonder of U",
                "enemies": [161, 154, 149],
                "boss": True,
                "text": "Pursue it and calamity finds you. Gappy's bubble is the only thing that can "
                "reach something that isn't there. The Arrow pulls at you one last time.",
            },
        ],
    },
]

STAGES = [
    dict(stage, part=p["part"], part_title=p["title"], jojo=p["jojo"])
    for p in PARTS
    for stage in p["stages"]
]
TOTAL = len(STAGES)


def cleared(user) -> int:
    return int(user.data.get("web_story", {}).get("cleared", 0))


def level_for(k: int) -> int:
    return CURVE[min(k, len(CURVE) - 1)][0]


def awaken_for(k: int) -> int:
    return CURVE[min(k, len(CURVE) - 1)][1]


def quality_for(k: int) -> str:
    return CURVE[min(k, len(CURVE) - 1)][2]


# Parts 7 and 8 lost some reach for maxed teams when UR/LR were trimmed and villain crews gained rarity
# leverage; their enemies' health and damage are eased to keep the end of the journey where it was.
LATE_EASE = {7: 0.88, 8: 0.85}
# Stages whose enemies share one of the newer synergy groups (Bow and Arrow, Kira family, Pucci's agents, the
# Higashikata family, the Rock Humans...): eased so the team that used to clear them on the edge still does.
STAGE_EASE = {6: 0.92, 8: 0.96, 9: 0.92, 16: 0.95, 17: 0.92, 27: 0.93, 28: 0.92}


def enemy_team(k: int) -> list:
    stage = STAGES[k]
    lvl, awaken, quality = level_for(k), awaken_for(k), quality_for(k)
    ease = LATE_EASE.get(stage["part"], 1) * STAGE_EASE.get(k, 1)
    team = []
    for cid in stage["enemies"]:
        items = [{"id": 1}] * (
            1 + (k >= TOTAL // 2) + bool(stage.get("boss") and k > 10)
        )
        team.append(
            character_from_dict(
                {
                    "id": cid,
                    "xp": lvl * 100,
                    "awaken": awaken,
                    "types": ["BALANCE"],
                    "qualities": [quality],
                    "items": items if k >= 6 else [],
                }
            )
        )
        if ease != 1:
            c = team[-1]
            for stat in ("hp", "damage"):
                value = int(getattr(c, f"start_{stat}") * ease)
                setattr(c, f"start_{stat}", value)
                setattr(c, f"current_{stat}", value)
    return team


def ai_level(k: int) -> str:
    """Gentle target picks until Part 3's boss; every later enemy plays smart."""
    boss = next(i for i, st in enumerate(STAGES) if st.get("boss"))
    return "easy" if k < boss else "smart"


HEAD_PARTS = (3, 5, 8)  # the bosses whose first clear pays an Arrowhead (economy.py: every other part)


def reward_for(k: int) -> dict:
    """First clear only. Meteor Dust grows with the stage; the bosses of HEAD_PARTS add an Arrowhead."""
    from app.game.economy import dust
    stage = STAGES[k]
    reward = {
        "fragments": dust(150 * 1.12**k),
        "xp": 100 + 40 * k,
        "stand_xp": 20 + 5 * k,
        "super_fragments": 1 if stage.get("boss") and stage["part"] in HEAD_PARTS else 0,
        "items": [],
    }
    if k % 3 == 2:
        reward["items"].append(2)  # a Devil's Palm every third stage
    return reward


def reward_text(k: int) -> List[str]:
    reward = reward_for(k)
    parts = [f"{reward['fragments']:,} Meteor Dust"]
    if reward["super_fragments"]:
        parts.append(f"{reward['super_fragments']} Arrowhead")
    for item_id in reward["items"]:
        parts.append(item_file[item_id - 1]["name"])
    return parts


def stage_view(k: int) -> dict:
    stage = STAGES[k]
    return {
        "index": k,
        "number": k + 1,
        **stage,
        "level": level_for(k),
        "awaken": awaken_for(k),
        "quality": quality_for(k).replace("_", " ").title(),
        "enemy_stands": [CHARACTER_FILE[cid - 1] for cid in stage["enemies"]],
        "reward": reward_text(k),
    }


def journey(user) -> list:
    """Every part with its stages marked cleared / current / locked."""
    done = cleared(user)
    rows, k = [], 0
    for p in PARTS:
        stages = []
        for stage in p["stages"]:
            stages.append(
                {
                    "index": k,
                    "title": stage["title"],
                    "boss": stage.get("boss", False),
                    "level": level_for(k),
                    "awaken": awaken_for(k),
                    "state": (
                        "cleared" if k < done else "current" if k == done else "locked"
                    ),
                }
            )
            k += 1
        rows.append(
            {
                **p,
                "stages": stages,
                "cleared": sum(s["state"] == "cleared" for s in stages),
            }
        )
    return rows


def current(user) -> Optional[dict]:
    done = cleared(user)
    return stage_view(done) if done < TOTAL else None


REPLAY_ENERGY = 1
REPLAY_SHARE = (
    0.2  # replays pay this share of the first-clear Meteor Dust, plus full stand XP
)


def check_can_fight(user, k: int):
    """The next stage is free; a cleared stage can be replayed for energy."""
    if not user.main_characters:
        raise GameError("Put at least one stand in your team before you set out.")
    if k < 0 or k >= TOTAL or k > cleared(user):
        raise GameError("That stage isn't open yet.")
    if k < cleared(user):
        from app.game.logic import spend_energy
        spend_energy(user, REPLAY_ENERGY, f"Replaying a stage costs {REPLAY_ENERGY} energy. It refills over time.")


def win(user, k: int) -> dict:
    """Pay the first-clear reward for stage k and move the journey on; a replay pays a share."""
    reward = reward_for(k)
    if k != cleared(user):
        fragments = int(round(reward["fragments"] * REPLAY_SHARE, -1))
        user.fragments += fragments
        for char in user.main_characters:
            train(char, reward["stand_xp"])
        return {
            "won": True,
            "fragments": fragments,
            "xp": 0,
            "stand_xp": reward["stand_xp"],
            "item": None,
        }
    user.fragments += reward["fragments"]
    user.super_fragments += reward["super_fragments"]
    user.xp += reward["xp"]
    for char in user.main_characters:
        train(char, reward["stand_xp"])
    names = []
    for item_id in reward["items"]:
        item = item_from_dict({"id": item_id})
        user.items.append(item)
        names.append(item.name)
    if reward["super_fragments"]:
        names.append(f"{reward['super_fragments']} Arrowhead")
    user.data.setdefault("web_story", {})["cleared"] = k + 1
    return {
        "won": True,
        "fragments": reward["fragments"],
        "xp": reward["xp"],
        "stand_xp": reward["stand_xp"],
        "item": ", ".join(names) or None,
    }
