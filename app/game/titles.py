"""Profile titles: earned from ranked seasons, stand mastery, collection sets, events, Over Heaven, and the milestones
below; one is shown under the name (and next to it in the chats).

Save: data["web_titles"] = [title, ...] (earned, kept forever), data["web_title"] = the one on display (or None).
Mastery titles aren't stored: they follow the mastery counters (see available()).
Redis: web:titles:shown  hash uid -> the title on display, so a chat can show it without loading every sender's save.

Milestone titles (MILESTONES) are granted by sync(), which achievements.check_achievements runs after every
tracked action: a story part cleared, a tower floor, a big collection, a ★5 stand...
"""
from typing import Callable, Iterable, List, Optional

MAX_STORED = 80
SHOWN_KEY = "web:titles:shown"


def _part_cleared(part: int) -> Callable:
    def check(user) -> bool:
        from app.game import story
        return any(p["part"] == part and p["stages"] and p["cleared"] == len(p["stages"]) for p in story.journey(user))
    return check


def _dex(n: int) -> Callable:
    def check(user) -> bool:
        ids = set(user.data.get("web_dex") or []) | {c.id for c in user.main_characters + user.storage_characters}
        return len(ids) >= n
    return check


def _rush_all(user) -> bool:
    from app.game import rush
    return int((rush.state(user).get("best") or {}).get("bosses", 0)) >= len(rush.BOSSES)


# (title, how to earn it, check(user) -> bool), in the order the profile lists them
MILESTONES = [
    ("Stardust Crusader", "Clear Part 3 of the story", _part_cleared(3)),
    ("Guardian of Morioh", "Clear Part 4 of the story", _part_cleared(4)),
    ("Gang-Star", "Clear Part 5 of the story", _part_cleared(5)),
    ("Free as Stone", "Clear Part 6 of the story", _part_cleared(6)),
    ("Saint's Pilgrim", "Clear Part 7 of the story", _part_cleared(7)),
    ("Wall Eyes Witness", "Clear Part 8 of the story", _part_cleared(8)),
    ("Tower Climber", "Reach floor 30 of the Tower", lambda u: int(u.tower_level or 0) >= 30),
    ("Heaven's Staircase", "Reach floor 60 of the Tower", lambda u: int(u.tower_level or 0) >= 60),
    ("Stand Collector", "Discover 50 different stands", _dex(50)),
    ("Bizarre Archivist", "Discover 100 different stands", _dex(100)),
    ("Living Encyclopedia", "Discover 150 different stands", _dex(150)),
    ("Shiny Hunter", "Own a shiny stand", lambda u: any(getattr(c, "shiny", False) for c in u.main_characters + u.storage_characters)),
    ("Requiem Bearer", "Awaken a stand to ★5", lambda u: any(c.awaken >= 5 for c in u.main_characters + u.storage_characters)),
    ("Stand Duelist", "Reach 1,500 lifetime ranked Elo", lambda u: int(u.global_elo or 0) >= 1500),
    ("Over the Top", "Reach 2,000 lifetime ranked Elo", lambda u: int(u.global_elo or 0) >= 2000),
    ("Raid Partner", "Win 10 co-op raids", lambda u: int(u.data.get("web_coop_wins", 0)) >= 10),
    ("Heaven's Raider", "Win an Over Heaven co-op raid", lambda u: int(u.data.get("web_coop_heaven_wins", 0)) >= 1),
    ("Gauntlet Breaker", "Beat every boss of a weekly boss rush", _rush_all),
    ("Deep Delver", "Clear the daily dungeon down to its boss", lambda u: int(u.data.get("web_dungeon_clears", 0)) >= 1),
]
MILESTONE_NAMES = {t for t, _, _ in MILESTONES}


def grant(user, title: str) -> bool:
    owned = list(user.data.get("web_titles") or [])
    if title in owned:
        return False
    owned.append(title)
    user.data["web_titles"] = owned[-MAX_STORED:]
    try:  # the 称号獲得 pop-up on the website (app.js); skipped outside it (simulations, scripts)
        from app.social import notify
        notify(str(user.id), "title", f"New title: {title}", f"/u/{user.id}")
    except Exception:
        pass
    return True


def sync(user) -> List[str]:
    """Grant every milestone title the save now qualifies for. Returns the new ones."""
    owned = set(user.data.get("web_titles") or [])
    new = []
    for title, _, check in MILESTONES:
        if title in owned:
            continue
        try:
            if check(user):
                grant(user, title)
                new.append(title)
        except Exception:  # a half-built save (simulations, scripts) never blocks the action that called this
            continue
    return new


def progress(user) -> List[dict]:
    """Every milestone, earned or not, for the profile's "titles to earn" list."""
    owned = set(user.data.get("web_titles") or [])
    return [{"title": t, "how": how, "earned": t in owned} for t, how, _ in MILESTONES]


def available(user, mastery_titles: Optional[List[str]] = None) -> List[str]:
    return list(user.data.get("web_titles") or []) + [t for t in (mastery_titles or []) if t not in (user.data.get("web_titles") or [])]


def shown(user, mastery_titles: Optional[List[str]] = None) -> Optional[str]:
    """The displayed title, if the player still has it."""
    pick = user.data.get("web_title")
    return pick if pick and pick in available(user, mastery_titles) else None


def choose(user, title: str, mastery_titles: Optional[List[str]] = None):
    from app.game.logic import GameError
    if not title:
        user.data["web_title"] = None
        _remember(user.id, None)
        return
    if title not in available(user, mastery_titles):
        raise GameError("You haven't earned that title.")
    user.data["web_title"] = title
    _remember(user.id, title)


def _remember(uid, title: Optional[str]):
    try:
        from app.db import r
        if title:
            r().hset(SHOWN_KEY, str(uid), title)
        else:
            r().hdel(SHOWN_KEY, str(uid))
    except Exception:
        pass


def remember(uid, title: Optional[str]):
    """Keep the chat's copy of a player's displayed title in step (the profile page calls this)."""
    _remember(uid, title)


def shown_of(uids: Iterable[str]) -> dict:
    """{uid: displayed title} for the players who show one."""
    ids = list(uids)
    if not ids:
        return {}
    from app.db import r
    vals = r().hmget(SHOWN_KEY, ids)
    return {u: (v.decode() if isinstance(v, bytes) else v) for u, v in zip(ids, vals) if v}
