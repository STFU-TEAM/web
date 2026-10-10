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
    "puzzle": 1,
    "ranked": done_at(3),
    "altverse": min(done_at(c["after"]) for c in altverse.CHAPTERS),
    "overheaven": story.TOTAL,
    "carryme": story.TOTAL,
}
LABELS = {"wormhole": "Mirror World", "tower": "Tower", "dungeon": "Dungeon", "puzzle": "Daily puzzle", "ranked": "Ranked",
          "altverse": "Alternate Universe", "overheaven": "Over Heaven", "carryme": "Carry Me (Part 10)"}

# entry points a locked player is turned away from (Over Heaven and the Alternate Universe guard their own pages)
ENTRY = {"play.mirror": "wormhole", "play.mirror_start": "wormhole",
         "play.tower": "tower", "play.tower_start": "tower",
         "play.dungeon": "dungeon", "play.dungeon_start": "dungeon",
         "progress.pz_page": "puzzle", "progress.pz_fight": "puzzle",
         "battles.ranked_queue": "ranked", "battles.ranked_roster": "ranked"}
# the page of each mode: opening it clears the mode's "New" tag (ranked: the battle page's ranked tab)
PAGES = {"play.mirror": "wormhole", "play.tower": "tower", "play.dungeon": "dungeon", "progress.pz_page": "puzzle",
         "progress.au_page": "altverse", "progress.oh_page": "overheaven", "progress.cm_page": "carryme"}

NEW_TTL = 30 * 86400


# Admin debug: a player can be given any mode regardless of progress (the admin checklist's tick boxes). Stored
# apart from the save (web:debug_unlock:<uid>, a set of keys), so it's reversible and the bot never sees it.
DEBUG_KEYS = {**{k: LABELS[k] for k in GATES}, "coop_heaven": "Co-op raids · Over Heaven", "training": "Training ground",
              "levels": "Skip the player-level gates", **{f"au:{c['key']}": f"Alternate Universe · {c['title']}"
                                                           for c in altverse.CHAPTERS}}


def _debug_key(uid) -> str:
    return f"web:debug_unlock:{uid}"


def forced(who) -> set:
    """The modes an admin forced open for this player (a user, cached on it, or a uid)."""
    user = who if hasattr(who, "data") else None
    if user is not None and "_forced" in user.__dict__:
        return user.__dict__["_forced"]
    uid = str(user.id) if user is not None else str(who)
    try:
        keys = {k.decode() if isinstance(k, bytes) else k for k in r().smembers(_debug_key(uid))}
    except Exception:  # no Redis (scripts, simulations): nothing forced
        keys = set()
    if user is not None:
        user.__dict__["_forced"] = keys
    return keys


def is_forced(who, key: str) -> bool:
    return key in forced(who)


def set_forced(uid, key: str, on: bool):
    if key not in DEBUG_KEYS:
        raise ValueError(key)
    (r().sadd if on else r().srem)(_debug_key(uid), key)


def _new_key(uid) -> str:
    return f"web:nav_new:{uid}"


def opened(cleared: int) -> dict:
    return {k: cleared >= n for k, n in GATES.items()}


def requirement(key: str) -> str:
    """What the story asks before a mode opens, for locked tabs."""
    return requirement_at(GATES[key])


def checklist(user, skip=()) -> List[dict]:
    """Every PvE mode for one player (the admin page): {label, need, done, have, of, played} in the order they open.
    `have`/`of` is how far they are toward the requirement; `played` how far into the mode once it's open."""
    from app.game import overheaven, training
    cleared = story.cleared(user)
    rows = [{"label": "Story", "need": "Open from the start", "done": True, "have": 1, "of": 1,
             "played": f"{min(cleared, story.TOTAL)}/{story.TOTAL} stages"}]
    for key, n in sorted(GATES.items(), key=lambda kv: kv[1]):
        if key in skip:
            continue
        row = {"label": LABELS[key], "need": requirement(key), "done": cleared >= n or is_forced(user, key),
               "have": min(cleared, n), "of": n, "played": "", "key": key}
        if key == "altverse":
            row["need"] += " (the first universe)"
        if key == "overheaven":
            row["played"] = f"{overheaven.total_cleared(user)}/{overheaven.TOTAL} fights"
        if key == "carryme":
            from app.game import carryme
            row["played"] = f"{min(carryme.cleared(user), carryme.TOTAL)}/{carryme.TOTAL} scenes"
        rows.append(row)
        if key == "altverse":  # each universe opens with its own part
            for c in altverse.CHAPTERS:
                need = done_at(c["after"])
                from app.game import gates
                rows.append({"label": f"Alternate Universe · {c['title']}",
                             "need": f"{requirement_at(need)}, player level {gates.AU.get(c['after'], 0)}",
                             "done": altverse.unlocked(user, c["key"]), "have": min(cleared, need), "of": need,
                             "played": f"{min(altverse.cleared(user, c['key']), len(c['stages']))}/{len(c['stages'])} stages",
                             "sub": True, "key": f"au:{c['key']}"})
    rows.append({"label": "Co-op raids · Normal to Nightmare", "need": "Open from the start", "done": True,
                 "have": 1, "of": 1, "played": ""})
    from app.game import coop, gates
    rows.append({"label": "Co-op raids · Over Heaven", "need": "Finish the story", "done": coop.unlocked(user, coop.HEAVEN),
                 "have": min(cleared, story.TOTAL), "of": story.TOTAL, "played": "", "key": "coop_heaven"})
    au = altverse.total_cleared(user)
    rows.append({"label": "Training ground", "need": "Finish the story and every Alternate Universe",
                 "done": training.unlocked(user), "have": min(cleared, story.TOTAL) + min(au, altverse.TOTAL),
                 "of": story.TOTAL + altverse.TOTAL, "played": "", "key": "training"})
    top = gates.CARRY_ME[-1]
    rows.append({"label": "Player-level gates", "need": f"Story parts, universes and acts ask a level (up to {top})",
                 "done": user.level >= top or is_forced(user, "levels"), "have": min(user.level, top), "of": top,
                 "played": f"level {user.level}", "key": "levels"})
    for row in rows:
        row["forced"] = bool(row.get("key")) and is_forced(user, row["key"])
    return rows


def requirement_at(n: int) -> str:
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
                "puzzle": url_for("progress.pz_page"),
                "altverse": url_for("progress.au_page"), "overheaven": url_for("progress.oh_page"),
                "carryme": url_for("progress.cm_page")}
        social.notify(uid, "unlock", f"🔓 Unlocked: {listed}. Look for the New tags in the menu.", urls[rest[0]])
    return keys


def new(uid) -> List[str]:
    keys = {k.decode() if isinstance(k, bytes) else k for k in r().smembers(_new_key(uid))}
    return [k for k in GATES if k in keys]


def seen(uid, key: str) -> None:
    r().srem(_new_key(uid), key)


def dismiss(uid) -> None:
    r().delete(_new_key(uid))
