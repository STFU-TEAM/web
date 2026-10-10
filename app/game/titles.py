"""Profile titles: earned from ranked seasons, stand mastery and collection sets; one is shown under the name.

Save: data["web_titles"] = [title, ...] (earned, kept forever), data["web_title"] = the one on display (or None).
Mastery titles aren't stored: they follow the mastery counters (see available()).
"""
from typing import List, Optional

MAX_STORED = 60


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
        return
    if title not in available(user, mastery_titles):
        raise GameError("You haven't earned that title.")
    user.data["web_title"] = title
