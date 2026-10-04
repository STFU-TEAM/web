"""Alternate Universe: original "what if" chapters, outside the canon story (web only).

Each chapter branches off one part of The Bizarre Journey: what if that part had ended the
other way? A chapter opens once its part is cleared in the main story, and starts a step
above that part's boss. Inside a chapter the stages are cleared in order; chapters are
independent of each other, so a player can work on several at once.

Progress lives in the save as data["web_au"] = {"cleared": {<chapter key>: <stages won>}}.
"""
from typing import List, Optional

from app.game import story
from app.game.character import CHARACTER_FILE, character_from_dict
from app.game.items import item_file, item_from_dict
from app.game.logic import GameError, train

QUALITIES = ["BAD", "SUB_PAR", "GOOD", "GREAT", "SUPREME", "UNIVERSAL"]
LEVEL_STEP = (1.15, 1.08)   # stage 1 is 15% above the source boss's level, then +8% a stage
OVERFLOW = 1.08             # once enemies are maxed (level 100, ★5), health and damage grow per stage instead
REPLAY_ENERGY = story.REPLAY_ENERGY
REPLAY_SHARE = story.REPLAY_SHARE
MATERIALS = [38, 39, 40]    # Golden Ratio Shard, Rokakaka Fruit, Devil's Palm Sand
REQUIEM_ARROW, DEVILS_PALM = 3, 2

CHAPTERS = [
    {
        "key": "world_unbroken",
        "after": 3,
        "title": "The World Unbroken",
        "ally": "Noriaki Kakyoin",
        "color": "#9B1D3A",
        "intro": "What if DIO had won in Cairo? Jotaro fell on the bridge, and the night never ended. "
        "Kakyoin survived the water tower and leads what is left of the Crusaders. "
        "The Arrow drops you into a city with no sunrise.",
        "stages": [
            {"title": "Cairo Under Night", "enemies": [11, 26, 28],
             "text": "The streets belong to DIO's flesh buds now. Ebony Devil waits in every doll, Bastet "
             "magnetises the lamp posts, and Atum reads the answer to every question on your face. "
             "Kakyoin: \"We move at dawn. There is no dawn. So we move now.\""},
            {"title": "The Vampire Guard", "enemies": [12, 25, 23],
             "text": "Yellow Temperance wears the faces of people you saved. Khnum wears yours. Anubis "
             "has learned every sword style the Crusaders ever used against it."},
            {"title": "Vanilla Ice's Void", "enemies": [30, 21, 16],
             "text": "Cream erases whole districts, High Priestess is the floor of the mansion, and "
             "Justice's fog makes the dead walk. Kakyoin's Emerald Splash is the only light in the room."},
            {"title": "The Diary of Heaven", "enemies": [10, 27, 29],
             "text": "DIO is fourteen words from Heaven. Horus freezes the library, D'Arby bets the "
             "last pages, and The World stands guard. Steal the diary or the universe resets on his terms."},
            {"title": "DIO Over Heaven", "enemies": [110, 10, 30], "boss": True,
             "text": "He found Heaven. His World rewrites reality with every punch. Kakyoin finally "
             "deciphers the stopped time, and he can show you, only once, where to hit."},
        ],
    },
    {
        "key": "morioh_never_sleeps",
        "after": 4,
        "title": "Morioh Never Sleeps",
        "ally": "Rohan Kishibe",
        "color": "#4F6BD8",
        "intro": "What if Kira was never caught? Hayato's loop closed, and Bites the Dust replays the same "
        "morning forever. Only Rohan noticed: his manuscripts keep changing overnight. He has "
        "written you into the next chapter.",
        "stages": [
            {"title": "The Same Morning", "enemies": [46, 52, 55],
             "text": "Ratt melts the bus stop, Boy II Man takes your Stand piece by piece at rock-paper-"
             "scissors, and Super Fly pins you to the radio tower. Rohan takes notes."},
            {"title": "Faces in the Mirror", "enemies": [56, 48, 57],
             "text": "Enigma folds the frightened into paper, Cinderella sells new faces at the salon, and "
             "Cheap Trick whispers Rohan's secrets to anyone who will listen."},
            {"title": "The Arrow Keeper", "enemies": [53, 40, 37],
             "text": "Kira hands out Arrows to strangers so the town keeps him safe. Highway Star, Love "
             "Deluxe and Red Hot Chili Pepper answer to a man none of them have met."},
            {"title": "Rewritten Friends", "enemies": [34, 45, 50],
             "text": "Kira found Heaven's Door's pages. Okuyasu's The Hand and Koichi's Echoes Act 3 now "
             "fight for him, and Rohan must face a Heaven's Door he didn't write."},
            {"title": "Bites the Dust Forever", "enemies": [58, 49, 32], "boss": True,
             "text": "Even Crazy Diamond was rewritten. Rohan scrawls one sentence on his own arm: "
             "\"I remember the loop.\" Break it before the clock strikes 8:00 again."},
        ],
    },
    {
        "key": "golden_boss",
        "after": 5,
        "title": "The Golden Boss",
        "ally": "Trish Una",
        "color": "#C9A227",
        "intro": "What if Diavolo reached the Arrow first? King Crimson Requiem rules Rome, and Giorno "
        "is lost in a loop of endless deaths. Trish, the Boss's daughter, is the only one who "
        "can still feel her father's soul nearby.",
        "stages": [
            {"title": "Passione Divided", "enemies": [61, 62, 70],
             "text": "Black Sabbath hunts in the shadows of the Colosseum, Moody Blues replays your last "
             "steps for the Boss's men, and Mr. President hides an army in a turtle."},
            {"title": "Former Friends", "enemies": [64, 67, 60],
             "text": "The Boss rewrote loyalty with the Arrow. Mista's Pistols, Narancia's Aerosmith and "
             "Bucciarati's Sticky Fingers stand against you. Trish refuses to strike first."},
            {"title": "The Mold of Rome", "enemies": [81, 69, 72],
             "text": "Green Day blankets the hills, Purple Haze's virus drips from the fountains, and the "
             "Grateful Dead ages the city. Spice Girl softens the ground beneath your feet."},
            {"title": "Requiem Guards", "enemies": [83, 80, 78],
             "text": "Chariot Requiem still wanders, swapping souls at random. Metallica and Notorious "
             "B.I.G. guard the stairway up to the Boss's throne."},
            {"title": "Gold Experience, Stolen", "enemies": [84, 75, 83], "boss": True,
             "text": "Diavolo took Giorno's Requiem for himself. Whatever you do returns to zero. Trish "
             "knows his weakness: he has never once looked at what lies behind him."},
        ],
    },
    {
        "key": "heaven_reached",
        "after": 6,
        "title": "Heaven Reached",
        "ally": "Emporio Alniño",
        "color": "#1E8C82",
        "intro": "What if Pucci had finished the reset? A new universe where everyone knows their fate in "
        "advance, and nobody resists. Emporio is the only one who remembers Jolyne, and he has "
        "been waiting a whole cycle for help.",
        "stages": [
            {"title": "Fated Prison", "enemies": [96, 98, 103],
             "text": "Limp Bizkit's invisible zombies walk the yard, Planet Waves calls down meteors, and "
             "Bohemian Rhapsody pulls cartoon heroes out of the posters to stop you."},
            {"title": "Accepted Fates", "enemies": [106, 85, 89],
             "text": "Survivor turns the inmates against each other, Rolling Stones carves the names of "
             "the doomed in stone, and Kiss doubles every blow."},
            {"title": "Burning Archive", "enemies": [91, 88, 97],
             "text": "Emporio's ghost room is on fire. Burning Down the House turns the files to ash, "
             "Manhattan Transfer snipes from the clouds, and Diver Down hides inside the walls."},
            {"title": "The New Moon", "enemies": [107, 108, 95],
             "text": "Whitesnake steals the discs of the last survivors, C-Moon turns gravity inside out "
             "and Jumpin' Jack Flash floats the rest away."},
            {"title": "The Priest of the New World", "enemies": [109, 107, 94], "boss": True,
             "text": "Made in Heaven, faster than ever. Weather Report's disc is in Emporio's hand, and "
             "this time oxygen is his weapon. Hold Pucci still for one breath."},
        ],
    },
    {
        "key": "saints_corpse",
        "after": 7,
        "title": "The Saint's Corpse",
        "ally": "Gyro Zeppeli",
        "color": "#B5651D",
        "intro": "What if Valentine gathered the whole Corpse? Every misfortune of America is sent to "
        "another world, and every world has its own President. Gyro survived the train. He "
        "brought steel balls and a plan he hasn't explained.",
        "stages": [
            {"title": "Patriots of Every World", "enemies": [118, 128, 129],
             "text": "Cream Starter seals your wounds shut, Sugar Mountain's spring offers gifts with a "
             "catch, and Tatoo You! steps out of every agent's back."},
            {"title": "Trains and Tubes", "enemies": [130, 131, 133],
             "text": "Tubular Bells inflates the rails, 20th Century Boy cannot be hurt, and Chocolate "
             "Disco teleports anything to the square it chooses."},
            {"title": "The Boom Boom Bounty", "enemies": [123, 135, 136],
             "text": "The Boom Boom family took Valentine's money. Their magnetism pulls every nail and "
             "steel ball out of the air. Gyro grins: \"Then I'll throw it harder.\""},
            {"title": "Diego of Two Worlds", "enemies": [117, 134, 132],
             "text": "One Diego from this world, one from another. Scary Monsters and THE WORLD hunt "
             "you together while Civil War buries you in the guilt you've left behind."},
            {"title": "Dirty Deeds Done Dirt Cheap", "enemies": [120, 126, 134], "boss": True,
             "text": "Behind the Love Train, Valentine is untouchable. Mandom rewinds every opening. "
             "Gyro's Ball Breaker spins at the golden ratio for the last time."},
        ],
    },
    {
        "key": "requiem_of_all",
        "after": 8,
        "title": "Requiem of All Parts",
        "ally": "Every JoJo",
        "color": "#8C3FD9",
        "intro": "The Arrow never let go. It has been stitching every timeline into one, and the seams "
        "are full of the strongest Stands you have ever met, heroes and villains alike, some "
        "of them wearing your face. This is the end of the Arrow's journey, one way or another.",
        "stages": [
            {"title": "Heroes Out of Time", "enemies": [163, 31, 86],
             "text": "Jotaro's Stand, from three different times, does not recognise you. Stone Free "
             "unravels across the gap between worlds."},
            {"title": "The Infinite Spin", "enemies": [114, 137, 115],
             "text": "Tusk Act 4 and Ball Breaker spin at the golden ratio. Soft & Wet takes away the "
             "friction of the floor and the light in the room."},
            {"title": "Kings of Time", "enemies": [75, 109, 58],
             "text": "King Crimson erases, Made in Heaven accelerates, and Bites the Dust rewinds. "
             "Time itself has no idea which way to go."},
            {"title": "Calamity's Echo", "enemies": [161, 94, 120],
             "text": "Wonder of U is the calamity, Weather Report is the storm, and D4C drags in "
             "a new copy of every fallen foe."},
            {"title": "The Arrow's Will", "enemies": [84, 110, 161], "boss": True,
             "text": "Gold Experience Requiem, The World Over Heaven and Wonder of U wait in the light. "
             "The Arrow wants a master. Win, and it finally lets go of you."},
        ],
    },
]
BY_KEY = {c["key"]: c for c in CHAPTERS}


# ── Unlocks and difficulty ──────────────────────────────────────────────

def _boss_index(part: int) -> int:
    """The main-story stage index of a part's boss."""
    return max(i for i, st in enumerate(story.STAGES) if st["part"] == part)


def unlocked(user, key: str) -> bool:
    return story.cleared(user) > _boss_index(BY_KEY[key]["after"])


def progress(user) -> dict:
    return user.data.get("web_au", {}).get("cleared", {})


def cleared(user, key: str) -> int:
    return int(progress(user).get(key, 0))


def total_cleared(user) -> int:
    return sum(min(cleared(user, c["key"]), len(c["stages"])) for c in CHAPTERS)


TOTAL = sum(len(c["stages"]) for c in CHAPTERS)


def _base(key: str, j: int) -> tuple:
    k = _boss_index(BY_KEY[key]["after"])
    base_level, base_awaken, base_quality = story.CURVE[min(k, len(story.CURVE) - 1)]
    level = min(100, round(base_level * LEVEL_STEP[0] * LEVEL_STEP[1] ** j))
    awaken = min(5, base_awaken + 1 + (j >= 3))
    quality = QUALITIES[min(len(QUALITIES) - 1, QUALITIES.index(base_quality) + (j >= 2) + (j >= 4))]
    return level, awaken, quality


def difficulty(key: str, j: int) -> dict:
    """Enemy level, awakening, quality and overflow for stage j of a chapter."""
    level, awaken, quality = _base(key, j)
    # past level 100 and ★5 there is nothing left to raise: health and damage grow each stage instead
    maxed = sum(_base(key, i)[:2] == (100, 5) for i in range(j + 1))
    return {"level": level, "awaken": awaken, "quality": quality, "mult": round(OVERFLOW ** maxed, 2)}


def enemy_team(key: str, j: int) -> list:
    stage = BY_KEY[key]["stages"][j]
    d = difficulty(key, j)
    items = [{"id": 1}] * (2 + bool(stage.get("boss")))
    team = []
    for cid in stage["enemies"]:
        c = character_from_dict({"id": cid, "xp": d["level"] * 100, "awaken": d["awaken"], "types": ["BALANCE"],
                                 "qualities": [d["quality"]], "items": items})
        if d["mult"] > 1:
            for stat in ("hp", "damage"):
                value = int(getattr(c, f"start_{stat}") * d["mult"])
                setattr(c, f"start_{stat}", value)
                setattr(c, f"current_{stat}", value)
        team.append(c)
    return team


# ── Rewards ─────────────────────────────────────────────────────────────

def reward_for(key: str, j: int) -> dict:
    """First clear only. Worth more than the source part's boss; the 3rd stage adds a crafting
    material, the chapter boss an Arrowhead and a Devil's Palm, the finale a Requiem Arrow."""
    chapter = BY_KEY[key]
    index = CHAPTERS.index(chapter)
    base = story.reward_for(_boss_index(chapter["after"]))
    stage = chapter["stages"][j]
    reward = {"fragments": int(round(base["fragments"] * (1.2 + 0.15 * j), -1)),
              "xp": int(base["xp"] * 1.2), "stand_xp": base["stand_xp"] + 5 * (j + 1),
              "super_fragments": 0, "items": []}
    if j == 2:
        reward["items"].append(MATERIALS[index % len(MATERIALS)])
    if stage.get("boss"):
        reward["super_fragments"] = 1
        reward["items"].append(REQUIEM_ARROW if chapter is CHAPTERS[-1] else DEVILS_PALM)
    return reward


def reward_text(key: str, j: int) -> List[str]:
    reward = reward_for(key, j)
    parts = [f"{reward['fragments']:,} Meteor Dust", f"+{reward['stand_xp']} stand XP"]
    if reward["super_fragments"]:
        parts.append(f"{reward['super_fragments']} Arrowhead")
    parts += [item_file[i - 1]["name"] for i in reward["items"]]
    return parts


# ── Views ───────────────────────────────────────────────────────────────

def chapters(user) -> list:
    """Every chapter with its unlock state and its stages marked cleared / current / locked."""
    rows = []
    for c in CHAPTERS:
        done, open_ = cleared(user, c["key"]), unlocked(user, c["key"])
        stages = [{"index": j, "title": st["title"], "boss": st.get("boss", False), **difficulty(c["key"], j),
                   "state": ("cleared" if j < done else "current" if j == done and open_ else "locked")}
                  for j, st in enumerate(c["stages"])]
        part = next(p for p in story.PARTS if p["part"] == c["after"])
        rows.append({**c, "stages": stages, "unlocked": open_, "cleared": min(done, len(stages)),
                     "complete": done >= len(stages), "source": part["title"]})
    return rows


def stage_view(key: str, j: int) -> dict:
    chapter = BY_KEY[key]
    stage = chapter["stages"][j]
    return {"chapter": key, "chapter_title": chapter["title"], "ally": chapter["ally"], "intro": chapter["intro"],
            "color": chapter["color"], "index": j, "number": j + 1, **stage, **difficulty(key, j),
            "quality_name": difficulty(key, j)["quality"].replace("_", " ").title(),
            "enemy_stands": [CHARACTER_FILE[cid - 1] for cid in stage["enemies"]], "reward": reward_text(key, j)}


def current(user, key: Optional[str] = None) -> Optional[dict]:
    """The next stage of the chosen chapter, or of the first open chapter with stages left."""
    if key not in BY_KEY:
        key = next((c["key"] for c in CHAPTERS if unlocked(user, c["key"])
                    and cleared(user, c["key"]) < len(c["stages"])), None)
    if key is None or not unlocked(user, key):
        return None
    j = cleared(user, key)
    return stage_view(key, j) if j < len(BY_KEY[key]["stages"]) else None


# ── Fighting ────────────────────────────────────────────────────────────

def check_can_fight(user, key: str, j: int):
    """The next stage of an open chapter is free; a cleared stage can be replayed for energy."""
    if not user.main_characters:
        raise GameError("Put at least one stand in your team before you cross over.")
    chapter = BY_KEY.get(key)
    if chapter is None or not unlocked(user, key):
        raise GameError("That universe hasn't opened yet. Clear its part of the main story first.")
    if j < 0 or j >= len(chapter["stages"]) or j > cleared(user, key):
        raise GameError("That stage isn't open yet.")
    if j < cleared(user, key):
        from app.game.logic import refill_energy
        refill_energy(user)
        if user.energy < REPLAY_ENERGY:
            raise GameError(f"Replaying a stage costs {REPLAY_ENERGY} energy. It refills over time.")
        user.energy -= REPLAY_ENERGY


def win(user, key: str, j: int) -> dict:
    """Pay the first-clear reward and move the chapter on; a replay pays a share and full stand XP."""
    reward = reward_for(key, j)
    for char in user.main_characters:
        train(char, reward["stand_xp"])
    if j != cleared(user, key):
        fragments = int(round(reward["fragments"] * REPLAY_SHARE, -1))
        user.fragments += fragments
        return {"won": True, "fragments": fragments, "xp": 0, "stand_xp": reward["stand_xp"], "item": None}
    user.fragments += reward["fragments"]
    user.super_fragments += reward["super_fragments"]
    user.xp += reward["xp"]
    names = []
    for item_id in reward["items"]:
        item = item_from_dict({"id": item_id})
        user.items.append(item)
        names.append(item.name)
    if reward["super_fragments"]:
        names.append(f"{reward['super_fragments']} Arrowhead")
    user.data.setdefault("web_au", {}).setdefault("cleared", {})[key] = j + 1
    return {"won": True, "fragments": reward["fragments"], "xp": reward["xp"], "stand_xp": reward["stand_xp"],
            "item": ", ".join(names) or None}
