"""Player-to-player trade offers (the bot's /character trade, made asynchronous).

An offer lists what each side hands over: stands (by uuid), items (id -> count)
and Meteor Dust. Nothing moves until the receiver accepts; ownership is checked
again at that moment under both players' locks, so an offer can't duplicate or
steal anything that changed in the meantime.

Redis (web-only):
    web:trade:<id>           JSON offer, expires after OFFER_TTL
    web:trades:in:<uid>      set of offer ids sent to uid
    web:trades:out:<uid>     set of offer ids sent by uid
"""
import datetime
import json
import secrets

from app.game.items import BOUND_ITEMS, item_file, item_from_dict
from app.game.logic import GameError, free_slots

OFFER_TTL = 3 * 24 * 3600
MAX_OPEN = 10
MAX_STANDS = 5
MAX_FRAGMENTS = 10_000_000


def empty_side():
    return {"stands": [], "items": {}, "fragments": 0}


def parse_side(form, prefix: str) -> dict:
    side = empty_side()
    side["stands"] = list(dict.fromkeys(form.getlist(f"{prefix}_stand")))[:MAX_STANDS]
    for raw in form.getlist(f"{prefix}_item"):
        try:
            item_id, count = (int(x) for x in raw.split(":"))
        except ValueError:
            continue
        if 1 <= item_id <= len(item_file) and count > 0 and item_id not in BOUND_ITEMS:  # bound items never trade
            side["items"][str(item_id)] = side["items"].get(str(item_id), 0) + min(count, 999)
    try:
        side["fragments"] = max(0, min(MAX_FRAGMENTS, int(form.get(f"{prefix}_fragments") or 0)))
    except ValueError:
        side["fragments"] = 0
    return side


def is_empty(side) -> bool:
    return not side["stands"] and not side["items"] and not side["fragments"]


def _all_stands(user):
    return user.main_characters + user.storage_characters


def check_side(user, side, who: str):
    owned = {c.uuid for c in _all_stands(user)}
    if any(u not in owned for u in side["stands"]):
        raise GameError(f"{who} no longer own{'s' if who != 'You' else ''} every stand in this offer.")
    have = {}
    for it in user.items:
        have[it.id] = have.get(it.id, 0) + 1
    for item_id, n in side["items"].items():
        if have.get(int(item_id), 0) < n:
            raise GameError(f"{who} no longer {'have' if who == 'You' else 'has'} enough {item_file[int(item_id) - 1]['name']}.")
    if user.fragments < side["fragments"]:
        raise GameError(f"{who} no longer {'have' if who == 'You' else 'has'} {side['fragments']:,} Meteor Dust.")


def describe(user, side) -> dict:
    """Display data for one side; missing stands show as gone."""
    by_uuid = {c.uuid: c for c in _all_stands(user)} if user else {}
    return {"stands": [by_uuid.get(u) for u in side["stands"]],
            "items": [(item_file[int(i) - 1], n) for i, n in side["items"].items()],
            "fragments": side["fragments"]}


def create(redis, sender, receiver_id: str, give: dict, want: dict) -> str:
    if receiver_id == sender.id:
        raise GameError("You can't trade with yourself.")
    if is_empty(give) and is_empty(want):
        raise GameError("Add something to the offer.")
    if redis.scard(f"web:trades:out:{sender.id}") >= MAX_OPEN:
        raise GameError(f"You already have {MAX_OPEN} open offers. Cancel one first.")
    check_side(sender, give, "You")
    if set(give["stands"]) & set(sender.data.get("web_locked", [])):
        raise GameError("Unlock your stands before offering them.")
    offer_id = secrets.token_urlsafe(9)
    offer = {"id": offer_id, "from": sender.id, "to": receiver_id, "give": give, "want": want,
             "at": datetime.datetime.now(datetime.timezone.utc).isoformat()}
    redis.set(f"web:trade:{offer_id}", json.dumps(offer), ex=OFFER_TTL)
    redis.sadd(f"web:trades:out:{sender.id}", offer_id)
    redis.sadd(f"web:trades:in:{receiver_id}", offer_id)
    return offer_id


def get(redis, offer_id: str):
    raw = redis.get(f"web:trade:{offer_id}")
    return json.loads(raw) if raw else None


def listing(redis, uid: str, box: str) -> list:
    out = []
    key = f"web:trades:{box}:{uid}"
    for raw_id in redis.smembers(key):
        offer_id = raw_id.decode() if isinstance(raw_id, bytes) else raw_id
        offer = get(redis, offer_id)
        if offer:
            out.append(offer)
        else:
            redis.srem(key, offer_id)  # expired
    return sorted(out, key=lambda o: o["at"], reverse=True)


def close(redis, offer):
    redis.delete(f"web:trade:{offer['id']}")
    redis.srem(f"web:trades:out:{offer['from']}", offer["id"])
    redis.srem(f"web:trades:in:{offer['to']}", offer["id"])


def _take(user, side):
    """Remove one side's goods from user and return them."""
    stands = []
    for u in side["stands"]:
        for lst in (user.main_characters, user.storage_characters):
            found = next((c for c in lst if c.uuid == u), None)
            if found:
                lst.remove(found)
                stands.append(found)
                break
    items = []
    for item_id, n in side["items"].items():
        for _ in range(n):
            it = next(i for i in user.items if i.id == int(item_id))
            user.items.remove(it)
            items.append(it)
    user.fragments -= side["fragments"]
    # equipped items travel with the stand; presets forget traded stands
    for team in user.teams.values():
        for s in stands:
            if s.uuid in team:
                team.remove(s.uuid)
    return stands, items, side["fragments"]


def _give(user, goods):
    stands, items, fragments = goods
    user.storage_characters.extend(stands)
    user.items.extend(item_from_dict(i.to_dict()) for i in items)
    user.fragments += fragments


def accept(sender, receiver, offer):
    check_side(sender, offer["give"], "They")
    check_side(receiver, offer["want"], "You")
    if free_slots(receiver) < len(offer["give"]["stands"]):
        raise GameError("Your storage doesn't have room for these stands.")
    if free_slots(sender) < len(offer["want"]["stands"]):
        raise GameError("Their storage doesn't have room for your stands.")
    from_sender = _take(sender, offer["give"])
    from_receiver = _take(receiver, offer["want"])
    _give(receiver, from_sender)
    _give(sender, from_receiver)
