"""Share cards: a short public link (/s/<id>) that shows off a moment and previews in Discord, X, Reddit...

The card is built on the server from what the player really has (a stand they own, a Requiem track they cleared, a
tower record, their profile): the link can't be made to claim anything else. Each card lives TTL, and a player can
make at most PER_DAY a day.

    web:share:<id>          JSON {kind, uid, name, title, text, image, url, at}
    web:share:count:<uid>:<day>
"""
import datetime
import json
import secrets
from typing import Optional

from app.game.logic import GameError

TTL = 60 * 86400
PER_DAY = 40


def _key(card_id: str) -> str:
    return f"web:share:{card_id}"


def get(redis, card_id: str) -> Optional[dict]:
    if not card_id.isalnum() or len(card_id) > 16:
        return None
    raw = redis.get(_key(card_id))
    return json.loads(raw) if raw else None


def _save(redis, uid, card: dict) -> str:
    day = datetime.date.today().isoformat()
    count = f"web:share:count:{uid}:{day}"
    if redis.incr(count) > PER_DAY:
        raise GameError("That's a lot of sharing for one day. Try again tomorrow.")
    redis.expire(count, 86400)
    card_id = secrets.token_urlsafe(6).replace("-", "a").replace("_", "b")
    redis.set(_key(card_id), json.dumps({**card, "uid": str(uid), "at": day}), ex=TTL)
    return card_id


def build(user, name: str, kind: str, ref: str, img) -> dict:
    """The card for kind/ref, checked against the user's save. img(stand_id) -> picture URL."""
    from flask import url_for
    from app.game.logic import locate
    profile = url_for("main.profile", uid=user.id)
    if kind == "stand":
        try:
            c, _, _ = locate(user, ref)
        except GameError:
            raise GameError("That stand isn't yours to show off.")
        stars = f" ★{c.awaken}" if c.awaken else ""
        shiny = "✨ shiny " if getattr(c, "shiny", False) else ""
        return {"kind": kind, "name": name, "title": f"{name} pulled {shiny}{c.name}{stars}!",
                "text": f"A {c.rarity} stand, level {c.level}{stars}. Pull your own on STFU Requiem, the free JoJo stand gacha.",
                "image": img(c.id), "url": url_for("main.stand", stand_id=c.id), "badge": c.rarity}
    if kind == "requiem":
        from app.game import requiem
        t = requiem.BY_KEY.get(ref)
        if not t or requiem.cleared(user, ref) < len(t["stages"]):
            raise GameError("Clear that whole Requiem track first.")
        boss = t["stages"][-1]["enemies"][0]
        return {"kind": kind, "name": name, "title": f"{name} conquered {t['title']} in Requiem mode ☠",
                "text": f"All {len(t['stages'])} stages at their hardest, built for maxed teams. Think you can? STFU Requiem is free to play.",
                "image": img(boss), "url": profile, "badge": "REQUIEM"}
    if kind == "tower":
        from app.game import tower
        s = tower.state(user)
        mode = tower.RQ if ref == tower.RQ else tower.NORMAL
        best = tower.record(s, mode)["best"]
        if best < 1:
            raise GameError("Clear a floor first.")
        where = "the Requiem Tower" if mode == tower.RQ else "the Tower"
        return {"kind": kind, "name": name, "title": f"{name} reached floor {best} of {where} this week",
                "text": "Every floor harder than the last, one weekly ladder for everyone. Climb it yourself on STFU Requiem.",
                "image": img(user.main_characters[0].id) if user.main_characters else None, "url": profile,
                "badge": f"FLOOR {best}"}
    if kind == "profile":
        from app.filters import RARITY_RANK
        best = max(user.main_characters + user.storage_characters, key=lambda c: (RARITY_RANK.get(c.rarity, 0), c.level), default=None)
        return {"kind": kind, "name": name, "title": f"{name}'s Stand user profile",
                "text": f"Level {user.level}, {len(user.main_characters) + len(user.storage_characters)} stands. Come fight me on STFU Requiem.",
                "image": img(best.id) if best else None, "url": profile, "badge": f"LV {user.level}"}
    raise GameError("Nothing to share there.")


def create(redis, user, name: str, kind: str, ref: str, img) -> str:
    return _save(redis, user.id, build(user, name, kind, ref, img))
