"""Profile badges. Staff badges come from the player's role (the STFU Team: admins and the people admins add; the
moderators), the others are earned in the game. A player picks one main badge: it shows next to their name in every
chat and leads their profile. Staff show their staff badge in chats until they pick another.

Redis:
    web:badges:team   hash uid -> {"by", "at"}: STFU Team members added from the admin panel (admins are in it anyway)
    web:badges:main   hash uid -> the chosen badge key, or "-" for none (read by the chats)
"""
import datetime
from typing import Dict, Iterable, List, Optional

from app.db import r
from app.game.logic import GameError

TEAM_KEY = "web:badges:team"
MAIN_KEY = "web:badges:main"
NONE = "-"

# key -> (label, icon, what it means); staff first, then earned ones, in the order the profile shows them
BADGES = {
    "team": ("STFU Team", "⚡", "Makes STFU Requiem: the developers and admins."),
    "mod": ("Moderator", "🛡", "Keeps the chats and the community safe."),
    "supporter": ("Supporter", "★", "Supports the game on Ko-fi."),
    "heaven": ("Heaven's Gate", "🌌", "Climbed every stair of Heaven's Gate."),
    "requiem": ("Requiem", "☠", "Cleared every Requiem stage."),
    "shiny": ("Shiny hunter", "✨", "Owns a shiny stand."),
    "veteran": ("Veteran", "🎖", "Has played for a year or more."),
}
STAFF = ("team", "mod")


def view(key: str) -> dict:
    label, icon, desc = BADGES[key]
    return {"key": key, "label": label, "icon": icon, "desc": desc, "staff": key in STAFF}


def is_team(uid) -> bool:
    from app.auth import is_admin
    return bool(uid) and (is_admin(uid) or bool(r().hexists(TEAM_KEY, str(uid))))


def is_mod(uid) -> bool:
    from app.auth import MODS_KEY
    return bool(uid) and bool(r().hexists(MODS_KEY, str(uid)))


def earned(user) -> List[str]:
    """The badge keys this player holds, in display order."""
    uid = str(user.id)
    out = []
    if is_team(uid):
        out.append("team")
    if is_mod(uid):
        out.append("mod")
    try:
        if user.is_donator() or getattr(user, "early_supporter", False):
            out.append("supporter")
    except Exception:
        pass
    from app.game import heaven, requiem
    if heaven.cleared(user) >= len(heaven.FIGHTS):
        out.append("heaven")
    if requiem.total_cleared(user) >= requiem.TOTAL:
        out.append("requiem")
    if any(getattr(c, "shiny", False) for c in list(user.main_characters) + list(user.storage_characters)):
        out.append("shiny")
    joined = getattr(user, "join_date", None)
    if joined and joined.year > 1 and (datetime.datetime.now() - joined.replace(tzinfo=None)).days >= 365:
        out.append("veteran")
    return out


def chosen(uid) -> Optional[str]:
    raw = r().hget(MAIN_KEY, str(uid))
    return raw.decode() if isinstance(raw, bytes) else raw


def main(user, held: Optional[List[str]] = None) -> Optional[str]:
    """The badge this player shows: their pick if they still hold it; staff show their staff badge by default."""
    held = earned(user) if held is None else held
    pick = chosen(user.id)
    if pick == NONE:
        return None
    if pick in held:
        return pick
    return next((k for k in STAFF if k in held), None)


def choose(user, key: str) -> None:
    key = (key or "").strip()
    if not key:
        r().hset(MAIN_KEY, str(user.id), NONE)
        return
    if key not in BADGES or key not in earned(user):
        raise GameError("You don't have that badge.")
    r().hset(MAIN_KEY, str(user.id), key)


def main_of(uids: Iterable[str]) -> Dict[str, dict]:
    """{uid: badge view} for the chats: each player's main badge, staff badges checked live (cheap: a few reads for
    the whole list). Earned badges are trusted from the pick (they're never taken away)."""
    from app.auth import ADMINS_KEY, MODS_KEY
    from flask import current_app
    ids = [str(u) for u in dict.fromkeys(uids)]
    if not ids:
        return {}
    pipe = r().pipeline()
    pipe.hmget(MAIN_KEY, ids)
    pipe.hmget(TEAM_KEY, ids)
    pipe.hmget(ADMINS_KEY, ids)
    pipe.hmget(MODS_KEY, ids)
    picks, team, admins, mods = pipe.execute()
    owners = set(current_app.config.get("DISCORD_ADMIN_IDS") or ())
    out = {}
    for uid, pick, t, a, m in zip(ids, picks, team, admins, mods):
        pick = pick.decode() if isinstance(pick, bytes) else pick
        staff = {"team": bool(t or a or uid in owners), "mod": bool(m)}
        if pick == NONE:
            continue
        if pick in STAFF and not staff[pick]:
            pick = None  # no longer staff
        if not pick:
            pick = next((k for k in STAFF if staff[k]), None)
        if pick in BADGES:
            out[uid] = view(pick)
    return out
