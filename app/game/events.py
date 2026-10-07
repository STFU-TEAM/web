"""Limited-time events: admins schedule a modifier for a few days, players earn event tokens and spend
them in that event's exchange shop.

Modifiers (one per event):
  dust         PvE wins pay DUST_BONUS more Meteor Dust
  rarity       stands of one rarity hit harder and move faster (BOOST) in every fight
  synergy      members of one synergy group get the same boost
Tokens: TOKENS_PVE per PvE win (story, tower, Mirror World, rush...), TOKENS_PVP per ranked win.

Redis: web:events  hash event id -> JSON {id, name, blurb, start, end (ISO dates, end exclusive), kind, target}
Save:  data["web_event"] = {event id: {"tokens": n, "bought": {shop key: count}}}
"""
import json
import time
import uuid
from datetime import date, datetime, timedelta
from typing import List, Optional

DUST_BONUS = 0.5
BOOST = 0.2
TOKENS_PVE = 3
TOKENS_PVP = 5
KINDS = {"dust": "Meteor Dust rush", "rarity": "Rarity spotlight", "synergy": "Synergy spotlight"}

SHOP = [  # key, label, cost, per-event limit, what it gives
    {"key": "dust", "label": "700 Meteor Dust", "cost": 10, "limit": 20, "give": {"fragments": 700}},
    {"key": "energy", "label": "Can of Energy", "cost": 6, "limit": 10, "give": {"items": [47]}},
    {"key": "coins", "label": "Bag of coins", "cost": 8, "limit": 5, "give": {"items": [13]}},
    {"key": "palm", "label": "Devil's Palm", "cost": 40, "limit": 3, "give": {"items": [2]}},
    {"key": "head", "label": "Arrowhead", "cost": 60, "limit": 1, "give": {"super": 1}},
    # Gear nothing else hands out: events are the only way to get it (one of each per event)
    {"key": "aja", "label": "Red stone of Aja", "cost": 55, "limit": 1, "give": {"items": [6]}, "exclusive": True},
    {"key": "sha", "label": "Sheer Heart Attack", "cost": 45, "limit": 1, "give": {"items": [5]}, "exclusive": True},
    {"key": "lighter", "label": "Polpo's lighter", "cost": 30, "limit": 1, "give": {"items": [16]}, "exclusive": True},
    {"key": "title", "label": "Event title", "cost": 30, "limit": 1, "give": {"title": True}},
]
SHOP_BY_KEY = {s["key"]: s for s in SHOP}

_cache = {"at": 0.0, "event": None}
CACHE_SECONDS = 30


# ── Admin ────────────────────────────────────────────────────────────────────

def all_events(redis) -> List[dict]:
    out = []
    for raw in redis.hvals("web:events"):
        try:
            out.append(json.loads(raw))
        except ValueError:
            continue
    return sorted(out, key=lambda e: e["start"], reverse=True)


def create(redis, name: str, blurb: str, start: str, end: str, kind: str, target: str = "") -> dict:
    from app.game.logic import GameError
    name, blurb = name.strip()[:60], blurb.strip()[:300]
    if not name:
        raise GameError("Give the event a name.")
    try:
        d0, d1 = date.fromisoformat(start), date.fromisoformat(end)
    except ValueError:
        raise GameError("Pick a start and an end date.")
    if d1 <= d0:
        raise GameError("The event must end after it starts.")
    if (d1 - d0).days > 31:
        raise GameError("Events last a month at most.")
    if kind not in KINDS:
        raise GameError("Unknown modifier.")
    target = _check_target(kind, target)
    for other in all_events(redis):  # one event at a time keeps the modifiers readable
        if date.fromisoformat(other["start"]) < d1 and d0 < date.fromisoformat(other["end"]):
            raise GameError(f"It overlaps {other['name']}.")
    ev = {"id": uuid.uuid4().hex[:10], "name": name, "blurb": blurb, "start": d0.isoformat(), "end": d1.isoformat(),
          "kind": kind, "target": target}
    redis.hset("web:events", ev["id"], json.dumps(ev))
    _cache["at"] = 0
    return ev


def delete(redis, event_id: str):
    redis.hdel("web:events", event_id)
    _cache["at"] = 0


def end_now(redis, event_id: str):
    raw = redis.hget("web:events", event_id)
    if raw:
        ev = json.loads(raw)
        ev["end"] = _today().isoformat()
        redis.hset("web:events", event_id, json.dumps(ev))
    _cache["at"] = 0


def _check_target(kind: str, target: str) -> str:
    from app.game.logic import GameError, RARITIES
    from app.game.characterabilities import SYNERGIES
    if kind == "rarity":
        if target not in RARITIES:
            raise GameError("Pick a rarity for the spotlight.")
    elif kind == "synergy":
        if target not in SYNERGIES:
            raise GameError("Pick a synergy group for the spotlight.")
    else:
        target = ""
    return target


# ── What's on ────────────────────────────────────────────────────────────────

def _today() -> date:
    from app.game.logic import now
    return now().date()


def is_live(ev: dict, today: Optional[date] = None) -> bool:
    today = today or _today()
    return date.fromisoformat(ev["start"]) <= today < date.fromisoformat(ev["end"])


def current(redis) -> Optional[dict]:
    """The live event, cached a few seconds per process (it's read on every fight)."""
    if time.time() - _cache["at"] < CACHE_SECONDS:
        return _cache["event"]
    live = next((e for e in all_events(redis) if is_live(e)), None)
    _cache.update(at=time.time(), event=live)
    return live


def upcoming(redis) -> Optional[dict]:
    today = _today()
    later = [e for e in all_events(redis) if date.fromisoformat(e["start"]) > today]
    return min(later, key=lambda e: e["start"]) if later else None


def cached() -> Optional[dict]:
    """The event as last read by current(): what the fight engine uses (None outside a web request)."""
    ev = _cache["event"]
    return ev if ev and is_live(ev) else None


def ends_at(ev: dict) -> datetime:
    return datetime.combine(date.fromisoformat(ev["end"]), datetime.min.time())


def starts_at(ev: dict) -> datetime:
    return datetime.combine(date.fromisoformat(ev["start"]), datetime.min.time())


def describe(ev: dict) -> str:
    if ev["kind"] == "dust":
        return f"PvE wins pay {DUST_BONUS:.0%} more Meteor Dust."
    if ev["kind"] == "rarity":
        return f"{ev['target']} stands deal {BOOST:.0%} more damage and are {BOOST:.0%} faster in every fight."
    from app.game.characterabilities import SYNERGY_INFO
    name = SYNERGY_INFO.get(ev["target"], (ev["target"], ""))[0]
    return f"{name} stands deal {BOOST:.0%} more damage and are {BOOST:.0%} faster in every fight."


KIND_HELP = {
    "dust": {"icon": "✦", "who": "Every player",
             "does": [f"PvE wins pay {DUST_BONUS:.0%} more Meteor Dust (story, Alternate Universe, Over Heaven, Mirror World, "
                      "tower, boss rush, dungeon, training, co-op).",
                      "Only the dust a win already pays is boosted: first-clear-only rewards still pay once."],
             "pick": None},
    "rarity": {"icon": "★", "who": "Every stand of one rarity",
               "does": [f"Those stands get +{BOOST:.0%} damage and +{BOOST:.0%} speed in every fight.",
                        "Enemies of that rarity get it too, so PvE gets harder where they show up.",
                        "Applied once per fighter: tower and rush teams that carry over never stack it."],
               "pick": "rarity"},
    "synergy": {"icon": "⚑", "who": "The members of one synergy group",
                "does": [f"Those stands get +{BOOST:.0%} damage and +{BOOST:.0%} speed in every fight, on top of their "
                         "normal synergy bonus.",
                         "Enemies in the group get it too. Pick a crew with a few common stands so everyone can join in."],
                "pick": "synergy"},
}


def target_view() -> dict:
    """For the admin form: how many stands each rarity / synergy target boosts, and who."""
    from app.game.character import CHARACTER_FILE
    from app.game.characterabilities import SYNERGIES, SYNERGY_INFO
    from app.game.logic import RARITIES
    playable = [c for c in CHARACTER_FILE if c["universe"] != "Dummy"]
    names = {c["id"]: c["name"] for c in playable}
    rar = {r: sum(c["rarity"] == r for c in playable) for r in RARITIES}
    syn = {k: {"label": SYNERGY_INFO.get(k, (k, ""))[0], "members": [names[i] for i in sorted(ids) if i in names]}
           for k, ids in SYNERGIES.items()}
    return {"rarity": rar, "synergy": syn}


def boosted_ids(ev: Optional[dict]) -> set:
    if not ev:
        return set()
    if ev["kind"] == "rarity":
        from app.game.character import CHARACTER_FILE
        return {c["id"] for c in CHARACTER_FILE if c["rarity"] == ev["target"]}
    if ev["kind"] == "synergy":
        from app.game.characterabilities import SYNERGIES
        return set(SYNERGIES.get(ev["target"], ()))
    return set()


# ── In fights ────────────────────────────────────────────────────────────────

def _undo(c):
    old = getattr(c, "_event_boost", None)
    if not old:
        return
    for attr, added in old["added"].items():
        setattr(c, f"start_{attr}", getattr(c, f"start_{attr}") - added)
        setattr(c, f"current_{attr}", getattr(c, f"current_{attr}") - added)
    c.__dict__.pop("_event_boost", None)


def apply_to_fight(fight) -> List[str]:
    """Boost the spotlighted stands once (tower teams carry over between floors: never twice)."""
    ev = cached()
    ids = boosted_ids(ev)
    names = []
    for side in fight.sides:
        for c in side.chars:
            old = getattr(c, "_event_boost", None)
            if old and (not ev or old["event"] != ev["id"] or c.id not in ids):
                _undo(c)
            if c.id in ids and not getattr(c, "_event_boost", None):
                added = {"damage": int(c.start_damage * BOOST), "speed": int(c.start_speed * BOOST)}
                for attr, value in added.items():
                    setattr(c, f"start_{attr}", getattr(c, f"start_{attr}") + value)
                    setattr(c, f"current_{attr}", getattr(c, f"current_{attr}") + value)
                c._event_boost = {"event": ev["id"], "added": added}
            if getattr(c, "_event_boost", None) and c.name not in names:
                names.append(c.name)
    return names


# ── Tokens and rewards ───────────────────────────────────────────────────────

def _wallet(user, ev: dict) -> dict:
    all_ = user.data.setdefault("web_event", {})
    for old in [k for k in all_ if k != ev["id"] and len(all_) > 3]:  # keep the save small
        all_.pop(old, None)
    return all_.setdefault(ev["id"], {"tokens": 0, "bought": {}})


def tokens(user, ev: Optional[dict]) -> int:
    if not ev:
        return 0
    return int((user.data.get("web_event") or {}).get(ev["id"], {}).get("tokens", 0))


def earn(user, amount: int) -> int:
    ev = cached()
    if not ev or amount <= 0:
        return 0
    _wallet(user, ev)["tokens"] += amount
    return amount


def pve_win(user, rewards: Optional[dict]) -> Optional[dict]:
    """Called once when a PvE fight is won: tokens, and the Dust rush bonus on top of the rewards."""
    ev = cached()
    if not ev or not isinstance(rewards, dict):
        return rewards
    rewards["tokens"] = earn(user, TOKENS_PVE)
    if ev["kind"] == "dust" and rewards.get("fragments"):
        bonus = int(rewards["fragments"] * DUST_BONUS)
        user.fragments += bonus
        rewards["fragments"] += bonus
        rewards["event_bonus"] = bonus
    return rewards


def shop_view(user, ev: dict) -> List[dict]:
    from app.wiki import ITEM_ABILITY
    bought = (user.data.get("web_event") or {}).get(ev["id"], {}).get("bought", {})
    return [{**s, "bought": bought.get(s["key"], 0), "left": s["limit"] - bought.get(s["key"], 0),
             "ability": ITEM_ABILITY.get(s["give"]["items"][0]) if s.get("exclusive") else None}
            for s in sorted(SHOP, key=lambda s: not s.get("exclusive"))]  # the event-only gear leads


def title_for(ev: dict) -> str:
    return f"{ev['name']} veteran"


def buy(user, ev: Optional[dict], key: str) -> str:
    from app.game import titles
    from app.game.items import item_from_dict
    from app.game.logic import GameError
    if not ev or not is_live(ev):
        raise GameError("No event is running.")
    offer = SHOP_BY_KEY.get(key)
    if not offer:
        raise GameError("That's not in the event shop.")
    wallet = _wallet(user, ev)
    if wallet["bought"].get(key, 0) >= offer["limit"]:
        raise GameError(f"You already bought every {offer['label']} this event.")
    if wallet["tokens"] < offer["cost"]:
        raise GameError(f"You need {offer['cost']} tokens (you have {wallet['tokens']}).")
    wallet["tokens"] -= offer["cost"]
    wallet["bought"][key] = wallet["bought"].get(key, 0) + 1
    give = offer["give"]
    user.fragments += give.get("fragments", 0)
    user.super_fragments += give.get("super", 0)
    for item_id in give.get("items", []):
        user.items.append(item_from_dict({"id": item_id}))
    if give.get("title"):
        titles.grant(user, title_for(ev))
        return f"New title: {title_for(ev)}"
    return offer["label"]


def window(ev: dict) -> str:
    end = date.fromisoformat(ev["end"]) - timedelta(days=1)
    return f"{date.fromisoformat(ev['start']):%b %d} to {end:%b %d}"
