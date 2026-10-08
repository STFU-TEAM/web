"""Training ground: opens once the story and the Alternate Universe are both cleared.

Pick up to TEAM_MAX stands from anywhere in the collection (storage included) and a drill. They fight a
sparring crew of their own rarities at their own level, and a win pays each of them far more stand XP per
energy than any other mode, plus a chance at a stand chip for one of their synergies. A loss still pays
LOSS_SHARE of the XP: the point is to level stands, not to gate them.

No save of its own: the fight's meta keeps {"drill", "uuids"}.
"""
import random
from typing import List

from app.game import altverse, chips, story
from app.game.character import CHARACTER_FILE, character_from_dict
from app.game.logic import GameError, locate, spend_energy, train

TEAM_MAX = 3
LOSS_SHARE = 0.25
# energy, stand XP per win, enemy level and stars over the trainees', enemy health/damage, chip chance on a win.
# Measured with the simulator on a mid-game collection: Sparring ~90% wins, Intense ~70%, Masterclass ~35%, so the
# XP per energy comes out even (~230-255, losses paying LOSS_SHARE) and the harder drills pay in chips. A star
# above the trainees is a cliff (+33% of their growth), so the drills climb in levels only.
DRILLS = {
    "spar": {"label": "Sparring", "icon": "🥊", "energy": 1, "xp": 250, "level": 0, "awaken": 0, "mult": 0.9,
             "chip": 0.25, "text": "A sparring crew a little softer than your stands."},
    "intense": {"label": "Intense drill", "icon": "🔥", "energy": 2, "xp": 650, "level": 5, "awaken": 0, "mult": 0.9,
                "chip": 0.45, "text": "Five levels above your stands."},
    "master": {"label": "Masterclass", "icon": "💀", "energy": 3, "xp": 1500, "level": 10, "awaken": 0, "mult": 0.95,
               "chip": 0.7, "text": "Ten levels above your stands: a real fight."},
}
POOLS = {r: [c["id"] for c in CHARACTER_FILE if c["rarity"] == r and c["universe"] != "Dummy" and c["id"] != 110]
         for r in ("R", "SR", "SSR", "UR", "LR")}


def unlocked(user) -> bool:
    return story.cleared(user) >= story.TOTAL and altverse.total_cleared(user) >= altverse.TOTAL


def progress(user) -> dict:
    return {"story": min(story.cleared(user), story.TOTAL), "story_total": story.TOTAL,
            "au": altverse.total_cleared(user), "au_total": altverse.TOTAL}


def trainees(user, uuids: List[str]) -> list:
    picked = []
    for u in dict.fromkeys(uuids):  # unique, in order
        char, _, _ = locate(user, u)
        picked.append(char)
    if not picked:
        raise GameError("Pick at least one stand to train.")
    if len(picked) > TEAM_MAX:
        raise GameError(f"Train up to {TEAM_MAX} stands at a time.")
    return picked


def sparring_team(team: list, drill: str, rng=random) -> list:
    """One sparring partner per trainee: same rarity, quality and number of items, at the trainees' average level
    plus the drill's."""
    d = DRILLS[drill]
    level = max(1, min(100, round(sum(c.level for c in team) / len(team)) + d["level"]))
    stars = max(0, min(5, round(sum(c.awaken for c in team) / len(team)) + d["awaken"]))
    taken = {c.id for c in team}
    out = []
    for c in team:
        pool = [i for i in POOLS.get(c.rarity, POOLS["SR"]) if i not in taken] or POOLS["SR"]
        cid = rng.choice(pool)
        taken.add(cid)
        # each partner mirrors its trainee's build quality and kit, so a well-rolled stand isn't punished
        quality = c.qualities[0] if c.qualities else "GOOD"
        foe = character_from_dict({"id": cid, "xp": level * 100, "awaken": stars, "types": ["BALANCE"],
                                   "qualities": [quality], "items": [{"id": 1}] * len(c.items)})
        for stat in ("hp", "damage"):
            value = int(getattr(foe, f"start_{stat}") * d["mult"])
            setattr(foe, f"start_{stat}", value)
            setattr(foe, f"current_{stat}", value)
        out.append(foe)
    return out


def start(user, uuids: List[str], drill: str) -> tuple:
    """Check, pay the energy, and return (trainees, sparring crew)."""
    if not unlocked(user):
        raise GameError("The training ground opens once you've finished the story and the Alternate Universe.")
    if drill not in DRILLS:
        raise GameError("Pick a drill.")
    team = trainees(user, uuids)
    spend_energy(user, DRILLS[drill]["energy"],
                 f"{DRILLS[drill]['label']} costs {DRILLS[drill]['energy']} energy. It refills over time.")
    return team, sparring_team(team, drill)


def settle(user, fight) -> dict:
    """Pay the trainees' XP (a share on a loss) and maybe a chip."""
    d = DRILLS.get(fight.meta.get("drill"), DRILLS["spar"])
    won = fight.winner == 0
    from app.game.economy import stand_xp
    amount = stand_xp(d["xp"] * (1 if won else LOSS_SHARE))
    trained = []
    for u in fight.meta.get("uuids", []):
        char, _, _ = user.find_character_by_uuid(u)
        if char is not None:
            train(char, amount)
            trained.append(char)
    chip = chips.grant(user, prefer=trained) if won and trained and random.random() < d["chip"] else None
    return {"won": won, "fragments": 0, "xp": 0, "stand_xp": amount if won else 0, "consolation_xp": 0 if won else amount,
            "item": f"a {chips.view(chip)['label']} chip ({chip['tier']})" if chip else None}
