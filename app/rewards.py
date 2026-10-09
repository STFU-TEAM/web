"""Rewards an admin sends to players' inboxes (update compensation, event prizes). Players claim them from the
inbox; each player claims a reward once.

Audiences:
    existing   every save that exists when it's sent (new accounts made afterwards can't farm it)
    everyone   anyone with a save, including players who join later
    players    the players the admin listed

    web:mail                hash id -> JSON {id, title, text, rewards, audience, at, until, by, recipients}
    web:mail:to:<id>        set of uids who may claim it (audiences "existing" and "players")
    web:mail:claimed:<id>   set of uids who claimed it

rewards: {"fragments": n, "super_fragments": n, "energy": n, "items": {"<item id>": n}, "stands": [stand id], "shiny": bool}
`until` is a game date (YYYY-MM-DD): the first day it can't be claimed anymore (like events). None = no end.
"""
import datetime
import json
import secrets
import time
from typing import List, Optional

from app.db import r

KEY = "web:mail"
AUDIENCES = {"existing": "Every current player", "everyone": "Everyone, players who join later too",
             "players": "Only the players listed"}
MAX_CURRENCY = 1_000_000
MAX_ENERGY = 100
MAX_ITEMS = 25          # per item kind
MAX_STANDS = 5
PRUNE_AFTER_DAYS = 30   # ended rewards are deleted this long after their end date


class RewardError(Exception):
    pass


def _s(x) -> str:
    return x.decode() if isinstance(x, bytes) else str(x)


def _today() -> datetime.date:
    from app.game.logic import now
    return now().date()


def _all_uids() -> set:
    out = set()
    for uid in r().hkeys("users"):
        uid = _s(uid)
        if uid.startswith("b'") and uid.endswith("'"):  # the bot's older keys (db._raw_user reads them too)
            uid = uid[2:-1]
        out.add(uid)
    return out


def clean_rewards(fragments=0, super_fragments=0, energy=0, items=None, stands=None, shiny=False) -> dict:
    """Bound and tidy what an admin typed; raises RewardError when nothing is left to give."""
    from app.game.character import CHARACTER_FILE
    from app.game.items import item_file

    def bound(v, cap):
        try:
            return max(0, min(cap, int(v or 0)))
        except (TypeError, ValueError):
            return 0
    out = {"fragments": bound(fragments, MAX_CURRENCY), "super_fragments": bound(super_fragments, MAX_CURRENCY),
           "energy": bound(energy, MAX_ENERGY), "items": {}, "stands": [], "shiny": bool(shiny)}
    for item_id, n in (items or {}).items():
        item_id, n = bound(item_id, len(item_file)), bound(n, MAX_ITEMS)
        if item_id and n:
            out["items"][str(item_id)] = min(MAX_ITEMS, out["items"].get(str(item_id), 0) + n)
    for sid in (stands or [])[:MAX_STANDS]:
        sid = bound(sid, len(CHARACTER_FILE))
        if sid and CHARACTER_FILE[sid - 1]["universe"] != "Dummy":
            out["stands"].append(sid)
    if not (out["fragments"] or out["super_fragments"] or out["energy"] or out["items"] or out["stands"]):
        raise RewardError("Add at least one reward.")
    return out


def describe(rewards: dict) -> List[dict]:
    """What a reward holds, as {icon, text} lines for the inbox and the admin list."""
    from app.game.character import CHARACTER_FILE
    from app.game.items import item_file
    lines = []
    if rewards.get("fragments"):
        lines.append({"icon": "✦", "text": f"{rewards['fragments']:,} Meteor Dust"})
    if rewards.get("super_fragments"):
        lines.append({"icon": "➶", "text": f"{rewards['super_fragments']:,} Arrowhead{'s' if rewards['super_fragments'] > 1 else ''}"})
    if rewards.get("energy"):
        lines.append({"icon": "⚡", "text": f"{rewards['energy']} energy"})
    for item_id, n in (rewards.get("items") or {}).items():
        it = item_file[int(item_id) - 1]
        lines.append({"icon": it.get("emoji") or "🎒", "text": f"{n} × {it['name']}"})
    for sid in rewards.get("stands") or []:
        c = CHARACTER_FILE[sid - 1]
        lines.append({"icon": "✨" if rewards.get("shiny") else "★",
                      "text": f"{'Shiny ' if rewards.get('shiny') else ''}{c['name']} ({c['rarity']})"})
    return lines


def create(by: str, title: str, text: str, rewards: dict, audience: str, players: Optional[List[str]] = None,
           until: Optional[str] = None) -> dict:
    title, text = (title or "").strip()[:80], (text or "").strip()[:500]
    if not title:
        raise RewardError("Give it a title.")
    if audience not in AUDIENCES:
        raise RewardError("Pick who gets it.")
    if until:
        try:
            if datetime.date.fromisoformat(until) <= _today():
                raise RewardError("The end date has to be after today.")
        except ValueError:
            raise RewardError("That end date isn't a date.")
    recipients = None
    if audience == "existing":
        recipients = _all_uids()
    elif audience == "players":
        recipients = set(players or [])
        if not recipients:
            raise RewardError("List at least one player.")
    mail_id = secrets.token_hex(5)
    mail = {"id": mail_id, "title": title, "text": text, "rewards": rewards, "audience": audience,
            "at": int(time.time()), "until": until or None, "by": by,
            "recipients": len(recipients) if recipients is not None else None}
    pipe = r().pipeline()
    ordered = sorted(recipients or ())
    for i in range(0, len(ordered), 5000):
        pipe.sadd(f"{KEY}:to:{mail_id}", *ordered[i:i + 5000])
    pipe.hset(KEY, mail_id, json.dumps(mail))
    pipe.execute()
    prune()
    return mail


def get(mail_id: str) -> Optional[dict]:
    raw = r().hget(KEY, mail_id)
    try:
        return json.loads(raw) if raw else None
    except ValueError:
        return None


def all_mails() -> List[dict]:
    out = []
    for raw in r().hvals(KEY):
        try:
            out.append(json.loads(raw))
        except ValueError:
            continue
    return sorted(out, key=lambda m: m.get("at", 0), reverse=True)


def is_live(mail: dict, today: Optional[datetime.date] = None) -> bool:
    return not mail.get("until") or (today or _today()) < datetime.date.fromisoformat(mail["until"])


def delete(mail_id: str):
    r().delete(KEY + ":to:" + mail_id, KEY + ":claimed:" + mail_id)
    r().hdel(KEY, mail_id)


def end_now(mail_id: str):
    mail = get(mail_id)
    if mail:
        mail["until"] = _today().isoformat()
        r().hset(KEY, mail_id, json.dumps(mail))


def prune():
    """Delete rewards that ended more than PRUNE_AFTER_DAYS ago, with their sets."""
    cutoff = _today() - datetime.timedelta(days=PRUNE_AFTER_DAYS)
    for mail in all_mails():
        if mail.get("until") and datetime.date.fromisoformat(mail["until"]) < cutoff:
            delete(mail["id"])


def claimed_count(mail_id: str) -> int:
    return r().scard(f"{KEY}:claimed:{mail_id}")


def claimable(uid: str) -> List[dict]:
    """The live rewards uid may claim and hasn't, newest first (each with its `lines`)."""
    today = _today()
    mails = [m for m in all_mails() if is_live(m, today)]
    if not mails:
        return []
    pipe = r().pipeline()
    for m in mails:
        pipe.sismember(f"{KEY}:claimed:{m['id']}", uid)
        pipe.sismember(f"{KEY}:to:{m['id']}", uid)
    flags = pipe.execute()
    out = []
    for i, m in enumerate(mails):
        claimed, listed = flags[2 * i], flags[2 * i + 1]
        if not claimed and (m["audience"] == "everyone" or listed):
            out.append({**m, "lines": describe(m["rewards"])})
    return out


def count(uid: str) -> int:
    return len(claimable(uid))


def claim(user, mail_id: str) -> dict:
    """Give one reward to the save (the caller holds the save lock and saves). Returns the mail."""
    uid = str(user.id)
    mail = next((m for m in claimable(uid) if m["id"] == mail_id), None)
    if not mail:
        raise RewardError("That reward is gone or already claimed.")
    if not r().sadd(f"{KEY}:claimed:{mail_id}", uid):  # two tabs claiming at once
        raise RewardError("You already claimed that reward.")
    try:
        _give(user, mail["rewards"])
    except Exception:
        r().srem(f"{KEY}:claimed:{mail_id}", uid)
        raise
    return mail


def _give(user, rw: dict):
    from app.game import logic
    from app.game.character import CHARACTER_FILE, get_character_from_template
    from app.game.items import item_from_dict
    stands = rw.get("stands") or []
    if len(stands) > logic.free_slots(user):  # checked first: a claim gives everything or nothing
        raise RewardError(f"Your stand storage is full: free {len(stands)} slot{'s' if len(stands) > 1 else ''} "
                          "to claim this reward.")
    for sid in stands:
        types, qualities = logic.roll_types_qualities()
        stand = get_character_from_template(CHARACTER_FILE[sid - 1], types, qualities)
        stand.shiny = bool(rw.get("shiny"))
        logic.add_to_available_storage(user, stand, skip_main=True)
    user.fragments += rw.get("fragments", 0)
    user.super_fragments += rw.get("super_fragments", 0)
    if rw.get("energy"):
        logic.refill_energy(user)
        user.energy += rw["energy"]
    for item_id, n in (rw.get("items") or {}).items():
        user.items.extend(item_from_dict({"id": int(item_id)}) for _ in range(n))
