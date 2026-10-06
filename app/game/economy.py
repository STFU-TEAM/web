"""Progression pace: the knobs that set how fast players earn.

Meteor Dust from playing (fights, quests, daily, journeys, dungeon, raids, first clears) is multiplied by DUST_RATE
where each reward is defined, so the amount a page shows is the amount paid. Player-to-player money (trades,
shops, auctions, gifts) is untouched.

Arrowheads are whole numbers, so they are cut source by source (fewer story bosses and tower floors pay one,
smaller Dex / season / Over Heaven / raid tables, fewer from quests and achievements); heads() rounds the
JSON tables. Time gates (daily, energy, Mirror World) live in logic.py and are about TIME_RATE longer than
they were.
"""
DUST_RATE = 0.7
TIME_RATE = 1.4
# Arrowheads in the quest and achievement tables: one-time rewards keep at least one, recurring ones lose more
HEAD_RATE = 0.6


def dust(amount: float) -> int:
    """A Meteor Dust reward at the current pace, rounded to tens like the tables."""
    value = amount * DUST_RATE
    return int(round(value, -1)) if value >= 50 else int(round(value))


def heads(n: int, recurring: bool = False) -> int:
    """An Arrowhead reward at the current pace: 2 -> 1, 3 -> 2, 5 -> 3; a recurring single one is dropped
    from every other source (see quests.py), a one-time single one is kept."""
    if n <= 0:
        return 0
    if n == 1:
        return 0 if recurring else 1
    return max(1, int(n * HEAD_RATE + 0.3))


def scale_rewards(rewards: dict, recurring: bool = False, key: str = "super_fragments") -> dict:
    """A quest/achievement reward table at the current pace (a copy)."""
    out = dict(rewards)
    if out.get("fragments"):
        out["fragments"] = dust(out["fragments"])
    if out.get(key):
        out[key] = heads(out[key], recurring)
    return out
