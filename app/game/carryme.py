"""Part 10 · Carry Me: Joyce Joestar's story (web only).

Present day. The world has forgotten Stands, and Joyce Joestar, a working actor in New York, has never heard of
them, until strange people start turning up at her auditions, her sets and her stage door. Her Stand, Carry Me, is
her bloodline: in each act it remembers one more JoJo and takes that Stand's form (evolutions included), and her
hope that things will change hardens, act by act, into a burning need for justice.

Carry Me fights beside the player's team as a guest. It is never a stand of its own: each form is an existing
stand (Hermit Purple, Star Platinum...) renamed for the fight, so no new stand id ever reaches a save the Discord
bot reads. Opens once the main story is finished.

After the final curtain comes the Encore: four scenes under Over Heaven's fight rules (app/game/overheaven.py),
where Carry Me can take any form it remembers.

Progress lives in the save as data["web_carry_me"] = {"cleared": <stages won>}.
"""
from typing import List, Optional

from app.game import story
from app.game.character import CHARACTER_FILE, character_from_dict
from app.game.economy import dust, stand_xp
from app.game.items import item_file, item_from_dict
from app.game.logic import GameError, train

TITLE = "Carry Me"            # the title for the final curtain
ENCORE_TITLE = "Encore"       # and for the last bow
NAME = "Carry Me"
REPLAY_ENERGY = story.REPLAY_ENERGY
REPLAY_SHARE = story.REPLAY_SHARE
MATERIALS = [38, 39, 40]      # Golden Ratio Shard, Rokakaka Fruit, Devil's Palm Sand
REQUIEM_ARROW = 3

# Each act: the JoJo Carry Me remembers, its form stage by stage (evolutions on the act's boss), the era the
# act's enemies come from, and Joyce's resolve (hope -> justice), shown on the page.
ACTS = [
    {
        "title": "Act I · Open Call", "jojo": "Joseph Joestar", "color": "#7C5BB5", "resolve": "Hope",
        "intro": "New York, today. Joyce Joestar has a callback, a day job, and a breathing exercise her "
                 "grandmother swore by. Nobody remembers Stands anymore. Then the man reading against her at the "
                 "audition casts a shadow with too many teeth, and something purple coils out of her wrist.",
        "stages": [
            {"title": "The Callback", "form": 4, "enemies": [8, 7],
             "text": "A buzzing in the rafters, water rising in the green room. Thorny vines answer before Joyce "
                     "does. \"Okay. Okay. That's new.\""},
            {"title": "Strength in Numbers", "form": 4, "enemies": [9, 18],
             "text": "The theater's freight lift has a mind of its own, and the stage lights burn like a desert sun. "
                     "Carry Me reads the wiring like a map: Joseph always did love a trick."},
            {"title": "Sleep Through It", "form": 4, "enemies": [19, 13], "boss": True,
             "text": "Her understudy falls asleep in the wings and doesn't wake up. Joyce still thinks this can be "
                     "talked out. She'll try. Then she'll fight."},
        ],
    },
    {
        "title": "Act II · Stage Fright", "jojo": "Jotaro Kujo", "color": "#3A6FD8", "resolve": "Hope",
        "intro": "The people who came for her weren't random. Someone is sending them, someone who knows her "
                 "family name better than she does. Carry Me remembers a quiet man in a long coat, and how hard "
                 "he could hit.",
        "stages": [
            {"title": "Gun and Mirror", "form": 1, "enemies": [14, 13],
             "text": "A gun that's also a Stand, a killer living in every mirror of the dressing room. Star "
                     "Platinum's fists are faster than the bullet. Joyce is still shaking."},
            {"title": "Cold Open", "form": 1, "enemies": [27, 29],
             "text": "A falcon of ice over the loading dock, and a gambler who wants her soul as his stake. Joyce "
                     "folds her cards and lets Carry Me play."},
            {"title": "Time Stands Still", "form": 31, "enemies": [10, 30], "boss": True,
             "text": "A man who wears DIO's Stand like a costume stops the clock. For one held breath, Carry Me "
                     "stops it too. Star Platinum: The World."},
        ],
    },
    {
        "title": "Act III · Understudy", "jojo": "Josuke Higashikata", "color": "#D6246E", "resolve": "Doubt",
        "intro": "Her friend from acting class lost her apartment, her savings and her memory of Joyce in one "
                 "night. Nobody will investigate. Joyce learns the people behind this call themselves the Cutting "
                 "Room, and that they edit people out.",
        "stages": [
            {"title": "Water Damage", "form": 32, "enemies": [33, 35],
             "text": "Rain in the subway that isn't rain, and a toy army in the prop room. Crazy Diamond puts the "
                     "set back together. It can't put her friend's life back."},
            {"title": "Live Wire", "form": 32, "enemies": [37, 53],
             "text": "The power grid hunts her across Queens, and a road that never ends drains her on the "
                     "highway. Joyce stops asking why. She starts asking who."},
            {"title": "A Quiet Life", "form": 32, "enemies": [49, 54], "boss": True,
             "text": "A polite man who wants a quiet life, and blows up anyone who gets in its way. He's been paid "
                     "to erase her. \"Then you'll have to try harder.\""},
        ],
    },
    {
        "title": "Act IV · Golden Hour", "jojo": "Giorno Giovanna", "color": "#E3A93A", "resolve": "Resolve",
        "intro": "Joyce takes a role on a set run by the Cutting Room's money. If she can't trust the police, "
                 "she'll find the proof herself. Carry Me remembers a boy with a golden dream who built justice "
                 "out of a gang.",
        "stages": [
            {"title": "Slow Burn", "form": 59, "enemies": [72, 73],
             "text": "The crew ages in their chairs, and a child's Stand learns her face. Gold Experience gives "
                     "life back where it was taken. She's done waiting for permission."},
            {"title": "Iron and Rot", "form": 59, "enemies": [80, 81],
             "text": "Razor blades in her blood, mould on every wound. The producer smiles from the monitor. Joyce "
                     "smiles back, and means it less."},
            {"title": "The Erased Hour", "form": 84, "enemies": [75, 74], "boss": True,
             "text": "King Crimson cuts an hour out of the shoot, and everyone forgets what was done in it. Carry "
                     "Me answers with a truth that can't be cut: Gold Experience Requiem. What's done stays done."},
        ],
    },
    {
        "title": "Act V · Free Fall", "jojo": "Jolyne Cujoh", "color": "#2BB3A8", "resolve": "Anger",
        "intro": "Framed for the fire on set, Joyce spends a night in a cell she didn't earn. The world that "
                 "forgot Stands has no idea how to believe her. Carry Me unravels into thread: Jolyne knew this "
                 "room.",
        "stages": [
            {"title": "Holding Cell", "form": 86, "enemies": [87, 95],
             "text": "A guard who isn't a guard, and rotating blades in the yard. Stone Free stitches her way out. "
                     "Hope doesn't get her through the bars. Anger does."},
            {"title": "Buried Memory", "form": 86, "enemies": [105, 101],
             "text": "Underworld digs up the night her friend was erased. Joyce watches it twice. She won't forget "
                     "it a third time."},
            {"title": "Discs", "form": 86, "enemies": [107, 108], "boss": True,
             "text": "The Cutting Room's warden takes memories as discs, and has a shelf full of names. Joyce "
                     "takes them all back."},
        ],
    },
    {
        "title": "Act VI · Final Cut", "jojo": "Johnny Joestar", "color": "#9B1D3A", "resolve": "Justice",
        "intro": "Out on bail and out of patience, Joyce goes after the Cutting Room's money across the "
                 "country, the way Johnny once crossed it. Carry Me spins: a nail, then a hole, then a hole that "
                 "follows you through dimensions.",
        "stages": [
            {"title": "First Spin", "form": 111, "enemies": [115, 117],
             "text": "A Stand that steals your strength, and a man who turns into a dinosaur. Tusk Act 1 is small. "
                     "Joyce isn't."},
            {"title": "Golden Rectangle", "form": 112, "enemies": [126, 127],
             "text": "Time rewound six seconds, and rain that stands still. Act 2's spin follows them through "
                     "every second they steal."},
            {"title": "Civil War", "form": 113, "enemies": [132, 134],
             "text": "Her own guilt walks out of the walls: every friend she couldn't save. Act 3 folds her into "
                     "the hole she made, and she comes out the other side."},
            {"title": "Infinite Rotation", "form": 114, "enemies": [120, 121], "boss": True,
             "text": "The Cutting Room's backer can slip into any world that suits him. Tusk Act 4 doesn't care "
                     "which world he's in. It finds him."},
        ],
    },
    {
        "title": "Act VII · Curtain Call", "jojo": "Josuke (Gappy)", "color": "#3AB4F2", "resolve": "Justice",
        "intro": "Back in New York. Everything the Cutting Room took is in one building on the West Side: "
                 "the Archivist, the woman who made the world forget, and the Stand that keeps anyone from "
                 "reaching her. Every form Carry Me ever took comes with Joyce.",
        "stages": [
            {"title": "Bubbles", "form": 137, "enemies": [149, 154],
             "text": "A tornado of rain in the lobby, nails in the walls. Soft & Wet takes something from each of "
                     "them: their footing, their light, their nerve."},
            {"title": "The Archive", "form": 137, "enemies": [156, 159, 147],
             "text": "Shelves of people who were edited out. Joyce reads every name out loud, and Carry Me "
                     "remembers them."},
            {"title": "Wonder of You", "form": 137, "enemies": [161, 154, 149], "boss": True, "finale": True,
             "text": "Anyone who chases the Archivist is struck by calamity. Joyce chases her anyway. Choose the "
                     "form Carry Me takes for the final scene: the whole Joestar line is behind it."},
        ],
    },
    {
        "title": "Act VIII · Encore", "jojo": "every JoJo", "color": "#F4C542", "resolve": "Justice", "encore": True,
        "intro": "The audience won't leave. With the Archivist gone, everything she held back pours onto the "
                 "stage: Stands that went past Heaven, still wearing the faces of the past. Up here the rules bend "
                 "the way they do Over Heaven, and Carry Me can take any form it remembers.",
        "stages": [
            {"title": "Standing Ovation", "form": 137, "enemies": [58, 75],
             "rules": {"enemy_first": True, "enrage": 0.06},
             "text": "They come back for a bow nobody asked for: a bomb that rewinds the morning and a king who "
                     "skips the hour. They move first, and they get angrier every second the applause lasts."},
            {"title": "Second Reading", "form": 137, "enemies": [120, 134],
             "rules": {"reflect": 0.25, "regen": 0.04},
             "text": "A president who steps between worlds and a World that stops time on horseback. Every blow "
                     "comes back at you, and every wound on them closes."},
            {"title": "Lines Forgotten", "form": 137, "enemies": [94, 108, 105],
             "rules": {"heaven_tax": 0.3, "purge": True, "pressure": 0.02},
             "text": "Weather that turns the air to poison, gravity that flips the stage. Borrowed power fades, "
                     "debuffs wash away, and the stage itself grinds you down."},
            {"title": "Over Heaven", "form": 137, "enemies": [161, 58, 120], "boss": True, "last": True,
             "rules": {"enemy_first": True, "stun_immune": True, "heal_cut": 0.5},
             "text": "The last bow belongs to a calamity that can't be chased, a morning that keeps rewinding, and a "
                     "president who'd trade every world for his own. Every JoJo stood on a stage like this once. Joyce "
                     "stands on it now."},
        ],
    },
]

STAGES = [dict(stage, act=a, act_title=act["title"], jojo=act["jojo"], color=act["color"], resolve=act["resolve"],
               encore=act.get("encore", False), rules=stage.get("rules", {}))
          for a, act in enumerate(ACTS) for stage in act["stages"]]
TOTAL = len(STAGES)
RESOLVE_STEPS = ["Hope", "Doubt", "Resolve", "Anger", "Justice"]
FIRST_ENCORE = next(k for k, s in enumerate(STAGES) if s["encore"])
FINALE = next(k for k, s in enumerate(STAGES) if s.get("finale"))


def rule_lines(rules: dict) -> List[str]:
    from app.game.overheaven import rule_lines as lines
    return lines(rules) if rules else []

# Enemy build per act: (awakening, quality); every enemy is level 100. MULT (health and damage, by stage) was
# calibrated with the simulator so a maxed SSR/UR team (no items or chips) with Carry Me beside it wins about 85% of
# the first scene, falling steadily to about 20% of the finale; the Encore goes from about 30% down to 10%.
# Then everything x1.1: endgame players bring items and chips the simulation doesn't.
ACT_BUILD = [(3, "SUPREME"), (3, "SUPREME"), (4, "SUPREME"), (4, "UNIVERSAL"), (5, "UNIVERSAL"), (5, "UNIVERSAL"),
             (5, "UNIVERSAL"), (5, "UNIVERSAL")]
MULT = [2.32, 2.65, 2.29, 2.29, 2.18, 2.48, 2.42, 2.11, 1.91, 2.16, 2.44, 2.57, 2.48, 2.37, 2.22, 2.57, 2.39, 2.67,
        2.3, 2.9, 2.22, 1.97,
        3.21, 2.62, 1.61, 1.83]  # the Encore, under its Over Heaven rules


def cleared(user) -> int:
    return int(user.data.get("web_carry_me", {}).get("cleared", 0))


def unlocked(user) -> bool:
    """Joyce's story opens once the main story is finished."""
    from app.game.progression import is_forced
    return story.cleared(user) >= story.TOTAL or is_forced(user, "carryme")


def difficulty(k: int) -> dict:
    awaken, quality = ACT_BUILD[STAGES[k]["act"]]
    return {"level": 100, "awaken": awaken, "quality": quality, "mult": MULT[k]}


def enemy_team(k: int) -> list:
    stage, d = STAGES[k], difficulty(k)
    items = [{"id": 1}] * (2 + bool(stage.get("boss")))
    team = []
    for cid in stage["enemies"]:
        c = character_from_dict({"id": cid, "xp": 100 * 100, "awaken": d["awaken"], "types": ["BALANCE"],
                                 "qualities": [d["quality"]], "items": items})
        if d["mult"] != 1:
            for stat in ("hp", "damage"):
                value = int(getattr(c, f"start_{stat}") * d["mult"])
                setattr(c, f"start_{stat}", value)
                setattr(c, f"current_{stat}", value)
        team.append(c)
    return team


# ── Carry Me ────────────────────────────────────────────────────────────

def forms(user) -> List[int]:
    """The forms Carry Me remembers: those of every stage cleared, plus the one in front of you."""
    done = min(cleared(user), TOTAL)
    seen = [STAGES[k]["form"] for k in range(min(done + 1, TOTAL))]
    return list(dict.fromkeys(seen))


def form_for(user, k: int, chosen: Optional[int] = None) -> int:
    """The stage's own form, unless the player picked another one they remember (the finale, the Encore, replays)."""
    allowed = forms(user)
    if chosen in allowed and (STAGES[k].get("finale") or STAGES[k]["encore"] or k < cleared(user)):
        return chosen
    return STAGES[k]["form"]


def guest(form: int, k: int):
    """Carry Me in a form: that stand at level 100, renamed. A fighting copy only: never saved anywhere."""
    from app.game.planner import best_type
    awaken = min(5, 2 + STAGES[k]["act"] // 2)
    c = character_from_dict({"id": form, "xp": 100 * 100, "awaken": awaken, "types": [best_type(form)],
                             "qualities": ["SUPREME"], "items": [{"id": 1}] * 2})
    c.name = f"{NAME} ｢{CHARACTER_FILE[form - 1]['name']}｣"
    c.guest = True  # bounties skip it
    return c


# ── Rewards ─────────────────────────────────────────────────────────────

def reward_for(k: int) -> dict:
    """First clear only: above the end of the main story. Each act's boss adds an Arrowhead and a crafting
    material; the finale a Requiem Arrow and the title. The Encore pays like Over Heaven: more dust, an Arrowhead a
    scene, and the last bow two more, a Requiem Arrow and its own title."""
    stage = STAGES[k]
    reward = {"fragments": dust(5000 + 400 * k), "xp": 1300 + 60 * k, "stand_xp": stand_xp(175 + 5 * k),
              "super_fragments": 0, "items": []}
    if stage.get("boss"):
        reward["super_fragments"] = 1
        reward["items"].append(MATERIALS[stage["act"] % len(MATERIALS)])
    if stage.get("finale"):
        reward["items"].append(REQUIEM_ARROW)
    if stage["encore"]:
        reward["fragments"] = dust(14000 + 1500 * (k - FIRST_ENCORE))
        reward["super_fragments"] = 2 if stage.get("last") else 1
        reward["items"] = [MATERIALS[k % len(MATERIALS)]] + ([REQUIEM_ARROW] if stage.get("last") else [])
    return reward


def reward_text(k: int) -> List[str]:
    reward = reward_for(k)
    parts = [f"{reward['fragments']:,} Meteor Dust", f"+{reward['stand_xp']} stand XP"]
    if reward["super_fragments"]:
        parts.append(f"{reward['super_fragments']} Arrowhead")
    parts += [item_file[i - 1]["name"] for i in reward["items"]]
    if STAGES[k].get("finale"):
        parts.append(f"the title “{TITLE}”")
    if STAGES[k].get("last"):
        parts.append(f"the title “{ENCORE_TITLE}”")
    return parts


# ── Views ───────────────────────────────────────────────────────────────

def form_view(cid: int) -> dict:
    c = CHARACTER_FILE[cid - 1]
    return {"id": cid, "name": c["name"], "rarity": c["rarity"]}


def acts(user) -> list:
    done, k, rows = cleared(user), 0, []
    for a, act in enumerate(ACTS):
        stages = []
        for st in act["stages"]:
            stages.append({"index": k, "title": st["title"], "boss": st.get("boss", False), "form": form_view(st["form"]),
                           "rules": rule_lines(STAGES[k]["rules"]),
                           **difficulty(k), "state": "cleared" if k < done else "current" if k == done else "locked"})
            k += 1
        rows.append({**act, "index": a, "stages": stages, "cleared": sum(s["state"] == "cleared" for s in stages),
                     "complete": all(s["state"] == "cleared" for s in stages),
                     "open": stages[0]["state"] != "locked"})
    return rows


def lineage(user) -> list:
    """Every form of the line in order, remembered or not (the page's lineage strip)."""
    known = set(forms(user))
    return [{**form_view(cid), "known": cid in known, "jojo": STAGES[next(k for k, s in enumerate(STAGES) if s["form"] == cid)]["jojo"]}
            for cid in dict.fromkeys(s["form"] for s in STAGES)]


def stage_view(user, k: int) -> dict:
    stage = STAGES[k]
    return {"index": k, "number": k + 1, **stage, **difficulty(k),
            "quality_name": difficulty(k)["quality"].replace("_", " ").title(),
            "act_intro": ACTS[stage["act"]]["intro"] if k == sum(len(a["stages"]) for a in ACTS[:stage["act"]]) else None,
            "enemy_stands": [CHARACTER_FILE[cid - 1] for cid in stage["enemies"]], "reward": reward_text(k),
            "form_view": form_view(stage["form"]), "choices": [form_view(f) for f in forms(user)],
            "rule_lines": rule_lines(stage["rules"])}


def current(user) -> Optional[dict]:
    done = cleared(user)
    return stage_view(user, done) if done < TOTAL else None


def resolve(user) -> dict:
    """Joyce's resolve, from hope to justice, as the acts go by."""
    done = min(cleared(user), TOTAL)
    word = STAGES[min(done, TOTAL - 1)]["resolve"] if done < TOTAL else "Justice"
    return {"word": word, "step": RESOLVE_STEPS.index(word), "steps": RESOLVE_STEPS}


# ── Fighting ────────────────────────────────────────────────────────────

def check_can_fight(user, k: int):
    if not unlocked(user):
        raise GameError("Joyce's story opens once you finish the main story.")
    if not user.main_characters:
        raise GameError("Put at least one stand in your team first.")
    if k < 0 or k >= TOTAL or k > cleared(user):
        raise GameError("That scene isn't open yet.")
    if k == cleared(user):
        from app.game import gates
        gates.check(gates.carry_me(user, k))
    if k < cleared(user):
        from app.game.logic import spend_energy
        spend_energy(user, REPLAY_ENERGY, f"Replaying a scene costs {REPLAY_ENERGY} energy. It refills over time.")


def win(user, k: int) -> dict:
    """Pay the first-clear reward and move the story on; a replay pays a share and full stand XP."""
    from app.game import titles
    reward = reward_for(k)
    for char in user.main_characters:
        train(char, reward["stand_xp"])
    if k != cleared(user):
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
    user.data.setdefault("web_carry_me", {})["cleared"] = k + 1
    if STAGES[k].get("finale") and titles.grant(user, TITLE):
        names.append(f"the title “{TITLE}”")
    if STAGES[k].get("last") and titles.grant(user, ENCORE_TITLE):
        names.append(f"the title “{ENCORE_TITLE}”")
    return {"won": True, "fragments": reward["fragments"], "xp": reward["xp"], "stand_xp": reward["stand_xp"],
            "item": ", ".join(names) or None}


assert len(MULT) == TOTAL
