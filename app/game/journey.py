"""The Crusaders' Journey: send a stand down the Part 3 road from Tokyo to Cairo on its own.

A journey is idle play. Pick a stand and a stop; the stand leaves your collection for the
trip (it can't fight, be traded, fused or sold while it's away) and comes back with loot.
The stronger the stand (its power score) and the longer the trip, the bigger the haul.
Everything is rolled when the stand sets out, so reloading the page changes nothing; the
loot is revealed and paid when you welcome it home. Recalling early brings it back with nothing.

Save: data["web_journeys"] = [{"id", "route", "stand" (save dict), "start", "end" (unix time),
                               "loot": {"fragments", "stand_xp", "items", "super"}, "events": [...]}]
"""
import random
import secrets
import time
from typing import List, Optional

from app.game.character import character_from_dict
from app.game.items import item_file, item_from_dict
from app.game.logic import GameError, add_to_available_storage, take_stand, train

SLOTS = 3
DUST_BASE, DUST_PER_POWER = 17.5, 0.035  # Meteor Dust per hour: base + power x this (economy pace: was 25, 0.05)
LONG_TRIP_BONUS = 0.03                 # each hour of the trip adds 3% to the per-hour rate
STAND_XP_PER_HOUR = 25
ITEM_POOL = [13, 47, 1, 4, 15, 38, 39, 40, 2]
ITEM_WEIGHTS = [0.18, 0.18, 0.12, 0.10, 0.10, 0.10, 0.08, 0.10, 0.04]

ROUTES = [
    {"key": "hong_kong", "name": "Hong Kong", "hours": 0.5, "emoji": "🏙️",
     "blurb": "The first leg out of Tokyo. Polnareff is waiting at a dim sum restaurant.",
     "events": ["shares a table with a Frenchman who swears about Silver Chariot's speed",
                "dodges a flaming porridge ladle meant for someone else",
                "watches a man in a green uniform make cherries disappear"]},
    {"key": "singapore", "name": "Singapore", "hours": 1, "emoji": "🚢",
     "blurb": "A hijacked ship, an orangutan at the wheel, and a hotel full of suspicious mirrors.",
     "events": ["finds the ape steering the cargo ship and declines the invitation to dinner",
                "spots a fake Kakyoin at the cable car and keeps its distance",
                "outruns a rolling train of Yellow Temperance"]},
    {"key": "calcutta", "name": "Calcutta", "hours": 2, "emoji": "🛕",
     "blurb": "Crowds, cows and the Hanged Man moving through every reflection.",
     "events": ["refuses to look into a single puddle all day",
                "helps Avdol out of a crowd of fortune tellers",
                "hears gunshots from an Emperor somewhere in the market"]},
    {"key": "karachi", "name": "Karachi", "hours": 4, "emoji": "🕌",
     "blurb": "A friendly kebab seller, a car that won't stop following, and a man who never blinks.",
     "events": ["buys a kebab from a man who smiles a little too wide",
                "is chased by a Wheel of Fortune down a cliff road",
                "wakes up in a dream that has a scythe in it"]},
    {"key": "red_sea", "name": "The Red Sea", "hours": 6, "emoji": "🌊",
     "blurb": "A submarine, a stolen face and the water itself turning against you.",
     "events": ["holds its breath while Dark Blue Moon circles below",
                "plays a game of video poker against a smug D'Arby",
                "sees Geb's water hand rise from a dune and keeps walking"]},
    {"key": "aswan", "name": "Aswan", "hours": 8, "emoji": "🏜️",
     "blurb": "The Egypt 9 Glory Gods wait at every oasis. Iggy came along, grudgingly.",
     "events": ["shares coffee-flavoured gum with a very bored Boston Terrier",
                "loses a bet against Osiris and wins it back",
                "stares down Horus across a frozen street"]},
    {"key": "cairo", "name": "Cairo · DIO's mansion", "hours": 12, "emoji": "🏰",
     "blurb": "The end of the road. Nobody walks out of the mansion empty-handed, if they walk out at all.",
     "events": ["slips past Vanilla Ice's void in the stairwell",
                "hears 'ZA WARUDO' and finds itself three steps further than it remembers",
                "takes a souvenir from DIO's library on the way out"],
     "super_chance": True},
]
BY_KEY = {r["key"]: r for r in ROUTES}


def fmt_hours(hours: float) -> str:
    return f"{int(hours * 60)} min" if hours < 1 else f"{hours:g} h"


def journeys(user) -> List[dict]:
    return user.data.setdefault("web_journeys", [])


def power_of(stand) -> int:
    from app.filters import power_score
    return power_score(stand)


def roll_loot(route: dict, power: int, rng: random.Random) -> dict:
    """What a stand of this power brings back from this route."""
    hours = route["hours"]
    per_hour = (DUST_BASE + power * DUST_PER_POWER) * (1 + LONG_TRIP_BONUS * hours)
    loot = {"fragments": int(round(hours * per_hour, -1)), "stand_xp": int(hours * STAND_XP_PER_HOUR),
            "items": [], "super": 0}
    item_chance = min(90, 10 + hours * 5 + power / 100)
    if rng.uniform(0, 100) < item_chance:
        loot["items"].append(rng.choices(ITEM_POOL, weights=ITEM_WEIGHTS, k=1)[0])
    if hours >= 8 and rng.uniform(0, 100) < item_chance / 2:  # long roads bring back a second find
        loot["items"].append(rng.choices(ITEM_POOL, weights=ITEM_WEIGHTS, k=1)[0])
    if route.get("super_chance") and rng.uniform(0, 100) < super_chance(power):
        loot["super"] = 1
    return loot


def super_chance(power: int) -> float:
    """Chance of an Arrowhead from DIO's mansion, in percent."""
    return min(14.0, 2 + power / 350)  # economy pace (was min(25, 3 + power / 200))


def estimate(route: dict, power: int) -> dict:
    """The sure part of the loot plus the odds, for the planner."""
    hours = route["hours"]
    per_hour = (DUST_BASE + power * DUST_PER_POWER) * (1 + LONG_TRIP_BONUS * hours)
    return {"fragments": int(round(hours * per_hour, -1)), "stand_xp": int(hours * STAND_XP_PER_HOUR),
            "item_chance": round(min(90, 10 + hours * 5 + power / 100)),
            "super_chance": round(super_chance(power), 1) if route.get("super_chance") else 0}


def depart(user, uuid: str, route_key: str, now: Optional[float] = None) -> dict:
    route = BY_KEY.get(route_key)
    if route is None:
        raise GameError("Pick a stop on the road.")
    trips = journeys(user)
    if len(trips) >= SLOTS:
        raise GameError(f"You already have {SLOTS} stands on the road. Welcome one home first.")
    if len(user.main_characters) == 1 and user.main_characters[0].uuid == uuid:
        raise GameError("That's your last team stand. Put another one in your team first.")
    stand = take_stand(user, uuid)
    power = power_of(stand)
    rng = random.Random(secrets.randbits(64))
    now = now or time.time()
    trip = {"id": secrets.token_urlsafe(6), "route": route_key, "stand": stand.to_dict(), "power": power,
            "start": int(now), "end": int(now + route["hours"] * 3600), "loot": roll_loot(route, power, rng),
            "events": rng.sample(route["events"], 2)}
    trips.append(trip)
    return trip


def _find(user, trip_id: str) -> dict:
    trip = next((t for t in journeys(user) if t["id"] == trip_id), None)
    if trip is None:
        raise GameError("That journey is over.")
    return trip


def _bring_home(user, trip: dict):
    journeys(user).remove(trip)
    stand = character_from_dict(dict(trip["stand"]))
    if add_to_available_storage(user, stand) is None:  # it was theirs before it left: storage cap or not
        user.storage_characters.append(stand)
    return stand


def claim(user, trip_id: str, now: Optional[float] = None) -> dict:
    trip = _find(user, trip_id)
    if (now or time.time()) < trip["end"]:
        raise GameError("It's still on the road.")
    stand = _bring_home(user, trip)
    loot = trip["loot"]
    gained = train(stand, loot["stand_xp"])
    user.fragments += loot["fragments"]
    user.super_fragments += loot["super"]
    items = [item_from_dict({"id": i}) for i in loot["items"]]
    user.items.extend(items)
    return {"stand": stand, "fragments": loot["fragments"], "stand_xp": gained, "super": loot["super"],
            "items": [i.name for i in items], "route": BY_KEY[trip["route"]]["name"]}


def recall(user, trip_id: str, now: Optional[float] = None):
    """Bring a stand home early, empty-handed."""
    trip = _find(user, trip_id)
    if (now or time.time()) >= trip["end"]:
        raise GameError("It's already home. Collect its loot instead.")
    return _bring_home(user, trip)


def view(user, now: Optional[float] = None) -> List[dict]:
    now = now or time.time()
    out = []
    for t in journeys(user):
        route = BY_KEY[t["route"]]
        total = max(1, t["end"] - t["start"])
        out.append({**t, "route_info": route, "char": character_from_dict(dict(t["stand"])),
                    "left": max(0, int(t["end"] - now)), "pct": min(100, round(100 * (now - t["start"]) / total)),
                    "done": now >= t["end"],
                    "item_names": [item_file[i - 1]["name"] for i in t["loot"]["items"]]})
    return out


def ready_count(user, now: Optional[float] = None) -> int:
    now = now or time.time()
    return sum(1 for t in journeys(user) if now >= t["end"])
