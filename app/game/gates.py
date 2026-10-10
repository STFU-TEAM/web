"""Player-level gates: each story part, Alternate Universe chapter and Carry Me act asks for a player level before
its first stage, so the PvE path paces out over 3-4 weeks instead of a strong roster clearing it in days.

Player XP mostly comes from energy (Mirror World: 100 XP a fight, an energy every 6 minutes), quests, raids, the
dungeon and the stages themselves. A dedicated player makes ~15-18k XP a day: level ~20 on day 3, ~30 on day 7,
~45 at two weeks, ~60 at four (level = 0.09 * sqrt(xp)). The levels below follow that: story done around day 9,
the Alternate Universe through weeks 2-3, Carry Me from day 10 to week 4.

Only a part's first stage is gated: a player already inside a part (or past it, from before the gates) carries on.
"""
from typing import Optional

STORY = {0: 0, 3: 0, 4: 8, 5: 14, 6: 20, 7: 26, 8: 32}        # by story part
AU = {3: 18, 4: 24, 5: 30, 6: 36, 7: 40, 8: 44}               # by the part a chapter branches from
CARRY_ME = [36, 39, 42, 45, 48, 51, 54, 58]                   # by act (the last is the Encore)

HOW = "Level up in Mirror World, quests, the dungeon, co-op raids and the tower."


def _gate(user, need: int, what: str) -> Optional[dict]:
    from app.game.progression import is_forced
    if user.level >= need or is_forced(user, "levels"):  # an admin's debug unlock skips them all
        return None
    return {"level": need, "have": user.level, "what": what,
            "text": f"{what} opens at player level {need}. You're level {user.level}. {HOW}"}


def story(user, k: int) -> Optional[dict]:
    """The gate in front of story stage k, if it's the first stage of its part and the player is below it."""
    from app.game import story as s
    stage = s.STAGES[k]
    if k != next(i for i, st in enumerate(s.STAGES) if st["part"] == stage["part"]):
        return None
    return _gate(user, STORY.get(stage["part"], 0), stage["part_title"])


def au(user, key: str, j: int) -> Optional[dict]:
    from app.game import altverse
    chapter = altverse.BY_KEY[key]
    return _gate(user, AU.get(chapter["after"], 0), f"Alternate Universe · {chapter['title']}") if j == 0 else None


def au_level(key: str) -> int:
    from app.game import altverse
    return AU.get(altverse.BY_KEY[key]["after"], 0)


def carry_me(user, k: int) -> Optional[dict]:
    from app.game import carryme
    stage = carryme.STAGES[k]
    if k != next(i for i, st in enumerate(carryme.STAGES) if st["act"] == stage["act"]):
        return None
    return _gate(user, CARRY_ME[stage["act"]], stage["act_title"])


def check(gate: Optional[dict]):
    from app.game.logic import GameError
    if gate:
        raise GameError(gate["text"])
