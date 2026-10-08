"""Story-gated modes: which nav tabs a player has opened, and the "New" tags that point them there.

The story drives progression: the first fight opens the side modes, Part 3 opens ranked and the Alternate
Universe, the last stage opens Over Heaven. A mode that opens stays "new" (web:nav_new:<uid>) until the
player visits it, so the nav, the story page and the battle page can point at it.
"""
from typing import List, Optional, Tuple

from app.db import r
from app.game import altverse, story


def done_at(part: int) -> int:
    """Stages cleared once a part's boss falls."""
    return altverse._boss_index(part) + 1


# mode -> story stages cleared to open it (in the order they're announced)
GATES = {
    "wormhole": 1,
    "tower": 1,
    "dungeon": 1,
    "ranked": done_at(3),
    "altverse": min(done_at(c["after"]) for c in altverse.CHAPTERS),
    "overheaven": story.TOTAL,
}
LABELS = {"wormhole": "Mirror World", "tower": "Tower", "dungeon": "Dungeon", "ranked": "Ranked",
          "altverse": "Alternate Universe", "overheaven": "Over Heaven"}

# entry points a locked player is turned away from (Over Heaven and the Alternate Universe guard their own pages)
ENTRY = {"play.mirror": "wormhole", "play.mirror_start": "wormhole",
         "play.tower": "tower", "play.tower_start": "tower",
         "play.dungeon": "dungeon", "play.dungeon_start": "dungeon",
         "battles.ranked_queue": "ranked", "battles.ranked_roster": "ranked"}
# the page of each mode: opening it clears the mode's "New" tag (ranked: the battle page's ranked tab)
PAGES = {"play.mirror": "wormhole", "play.tower": "tower", "play.dungeon": "dungeon",
         "progress.au_page": "altverse", "progress.oh_page": "overheaven"}

NEW_TTL = 30 * 86400


def _new_key(uid) -> str:
    return f"web:nav_new:{uid}"


def opened(cleared: int) -> dict:
    return {k: cleared >= n for k, n in GATES.items()}


def requirement(key: str) -> str:
    """What the story asks before a mode opens, for locked tabs."""
    n = GATES[key]
    if n <= 1:
        return "Win your first story fight"
    if n >= story.TOTAL:
        return "Finish the story"
    return f"Finish {story.STAGES[n - 1]['part_title']} in the story"


def next_unlock(cleared: int, skip=()) -> Optional[Tuple[int, List[str]]]:
    """(stages still to clear, labels of what they open) for the next gate ahead, or None."""
    ahead = [n for k, n in GATES.items() if n > cleared and k not in skip]
    if not ahead:
        return None
    n = min(ahead)
    return n - cleared, [LABELS[k] for k, m in GATES.items() if m == n and k not in skip]


def announce(uid, before: int, after: int, skip=()) -> List[str]:
    """Story progress went from `before` to `after` stages: tag what just opened as new and tell the player."""
    keys = [k for k, n in GATES.items() if before < n <= after and k not in skip]
    if not keys:
        return []
    pipe = r().pipeline()
    pipe.sadd(_new_key(uid), *keys)
    pipe.expire(_new_key(uid), NEW_TTL)
    pipe.execute()
    from flask import url_for
    from app import social
    if "ranked" in keys:
        social.notify(uid, "unlock", "♛ Ranked is open! Draft a roster of 5, climb this month's season and earn its rewards.",
                      url_for("battles.index", mode="ranked"))
    rest = [k for k in keys if k != "ranked"]
    if rest:
        names = [LABELS[k] for k in rest]
        listed = names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]
        urls = {"wormhole": url_for("play.mirror"), "tower": url_for("play.tower"), "dungeon": url_for("play.dungeon"),
                "altverse": url_for("progress.au_page"), "overheaven": url_for("progress.oh_page")}
        social.notify(uid, "unlock", f"🔓 Unlocked: {listed}. Look for the New tags in the menu.", urls[rest[0]])
    return keys


def new(uid) -> List[str]:
    keys = {k.decode() if isinstance(k, bytes) else k for k in r().smembers(_new_key(uid))}
    return [k for k in GATES if k in keys]


def seen(uid, key: str) -> None:
    r().srem(_new_key(uid), key)


def dismiss(uid) -> None:
    r().delete(_new_key(uid))
