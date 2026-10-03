"""Game actions ported from stfu-reborn (singularitybot) slash commands.

Every function mutates a User and returns a small result for the UI.
Drop rates, costs, cooldowns, storage sizes and quest/achievement tracking
are copied from the bot so both stay interchangeable on the same Redis data.
"""
import datetime
import json
import os
import random
from typing import List, Optional

from app.game.achievements import check_achievements
from app.game.character import (
    CHARACTER_FILE, Character, Qualities, Types, get_character_from_template,
)
from app.game.items import Item, item_file, item_from_dict
from app.game.quests import claim_quest_reward, ensure_quests_assigned, get_claimable_quests, track_quest_progress
from app.game.user import STORAGE_CAPACITY, User

_DATA = os.path.join(os.path.dirname(__file__), "data")
with open(os.path.join(_DATA, "banners_data.json"), encoding="utf-8") as f:
    BANNERS = json.load(f)["banners"]
with open(os.path.join(_DATA, "recipes.json"), encoding="utf-8") as f:
    RECIPES = json.load(f)["recipes"]

# globals/variables.py
PLAYER_XPGAINS = 100
CHARACTER_XPGAINS = 15
FRAGMENTSGAIN = 300
CHANCEITEM = 10
DONOR_WH_WAIT_TIME = 1
NORMAL_WH_WAIT_TIME = 1.5
DONOR_ADV_WAIT_TIME = 6
NORMAL_ADV_WAIT_TIME = 6
STXPTOLEVEL = 100

STORAGE_SIZE = 25
MAX_TEAMS = 5
RARITIES = ["R", "SR", "SSR", "UR", "LR"]

# /shop default
DEFAULT_SHOP = {
    "super_fragment": {"name": "Arrowhead", "price": 5000, "type": "currency"},
    "1": {"name": "Dio's Knife", "price": 2500, "type": "item", "id": 1},
    "2": {"name": "Devil's Palm", "price": 5000, "type": "item", "id": 2, "summon": True},
    "3": {"name": "Requiem Arrow", "price": 10000, "type": "item", "id": 3},
    "4": {"name": "Giorno's ladybug", "price": 5000, "type": "item", "id": 4},
}

# /item use
GACHA_ITEMS = [12]  # Devil's Palms (2) are only spent on banners: 5 stands at SR or better
CHIP_IDS = [8, 9, 10, 11, 14, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27, 28, 29, 30, 31, 32]
CHIP_TEMPLATE_INDEX = [9, 0, 5, 29, 162, 30, 57, 31, 33, 44, 48, 49, 58, 59, 68, 74, 77, 79, 80, 82, 83]
REQUIEMABLE = [49, 6, 59]
# Stars a stand needs (at level 100) before a Requiem Arrow evolves it; Gold Experience needs ★3 for GER.
REQUIEM_STARS = {49: 2, 6: 2, 59: 3}
MAX_AWAKEN = 5  # ascension and fusion stop at ★3; Requiem Arrows can push to ★5, never further
REQUIEM_TEMPLATE_INDEX = [57, 82, 83]
SPECIAL_CHARACTERS = [163, 110, 84, 109, 161, 120, 114]


class GameError(Exception):
    """Player-facing error, shown as-is."""


def now() -> datetime.datetime:
    # the bot stores naive local time + 2h
    return datetime.datetime.now() + datetime.timedelta(hours=2)


def fmt_delta(td: datetime.timedelta) -> str:
    s = max(0, int(td.total_seconds()))
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    if h:
        return f"{h} h {m:02d} min"
    if m:
        return f"{m} min {sec:02d} s"
    return f"{sec} s"


def cooldown_left(last: datetime.datetime, hours: float) -> Optional[datetime.timedelta]:
    delta = now() - last
    if delta.total_seconds() // 3600 < hours:
        return datetime.timedelta(hours=hours) - delta
    return None


# --------------------------------------------------------------------------- #
# Storages
# --------------------------------------------------------------------------- #
def storages(user: User) -> List[List[Character]]:
    """Return the single web collection, independent of supporter status."""
    return [user.storage_characters]


def all_lists(user: User) -> List[List[Character]]:
    return [user.main_characters, user.storage_characters]


def locate(user: User, uuid: str):
    char, lst, idx = user.find_character_by_uuid(uuid)
    if char is None:
        raise GameError("That stand isn't in your collection anymore.")
    return char, lst, idx


def free_slots(user: User) -> int:
    return max(0, STORAGE_CAPACITY - len(user.storage_characters))


def add_to_available_storage(user: User, character: Character, skip_main: bool = False):
    """utils/functions.py version (the one the commands use)."""
    if len(user.main_characters) < 3 and not skip_main:
        user.main_characters.append(character)
        return "Team"
    if len(user.storage_characters) >= STORAGE_CAPACITY:
        return None
    user.storage_characters.append(character)
    return "Collection"


def get_drop_from_list(char_list: List[Character], number_of_drop: int = 1) -> list:
    num = {"R": 1, "SR": 2, "SSR": 3, "UR": 4, "LR": 5}
    rarity_num = random.choices([1, 2, 3, 4, 5], weights=[0.35, 0.3, 0.2, 0.1, 0.05], k=1)[0]
    filtered = [c for c in char_list if num.get(c.rarity, 0) == rarity_num] or char_list
    return random.choices(filtered, k=number_of_drop)


# --------------------------------------------------------------------------- #
# Types & qualities roll (identical in pull, arrow and reforge)
# --------------------------------------------------------------------------- #
def roll_types_qualities():
    _types = [Types.ATTACK, Types.DEFENSE, Types.BALANCE, Types.LUCK, Types.SPEED]
    _qualities = [Qualities.UNIVERSAL, Qualities.SUPREME, Qualities.GREAT, Qualities.GOOD, Qualities.SUB_PAR, Qualities.BAD]
    _bad_qualities = [Qualities.SUB_PAR, Qualities.BAD]
    standard_probabilities = [0.05, 0.10, 0.20, 0.50, 0.10, 0.05]
    enhanced_probabilities = [0.40, 0.30, 0.20, 0.10, 0.05, 0.03]

    pulled_types = [random.choice(_types)]
    remove_i = _types.index(pulled_types[-1])
    standard_probabilities.pop(remove_i)
    enhanced_probabilities.pop(remove_i)
    _types.pop(remove_i)
    pulled_qualities = [random.choice(_qualities)]
    _qualities.pop(remove_i)
    pull_prob = 0.1
    if pulled_qualities[-1] in _bad_qualities:
        pull_prob = 1
    while random.random() <= pull_prob and len(_types) > 0:
        weights = standard_probabilities
        if pulled_qualities[-1] in _qualities:
            weights = enhanced_probabilities
        pulled_types.append(random.choice(_types))
        pulled_qualities.append(random.choices(_qualities, weights=weights, k=1)[0])
        remove_i = _types.index(pulled_types[-1])
        standard_probabilities.pop(remove_i)
        enhanced_probabilities.pop(remove_i)
        _types.pop(remove_i)
        _qualities.pop(remove_i)
        pull_prob = 0.1
    return [t.name for t in pulled_types], [q.name for q in pulled_qualities]


# Daily rotation: two Part banners (an early Part with a late one) plus one themed banner,
# changing at midnight (server time + 2h, like the dailies). Parts come back every 3 days, themes every 6.
ROTATION_START = datetime.date(2026, 1, 5)  # day 0 of the rotation
PART_PAIRS = [(0, 3), (1, 4), (2, 5)]       # Part 3 + 6, Part 4 + 7, Part 5 + 8
THEME_ORDER = [10, 11, 12, 13, 14, 15]      # JoJo Legacy, Adversaries, JoBros, Evolution, Hitmen, Lifeline


def rotation_day(when: Optional[datetime.date] = None) -> int:
    day = when or now().date()
    if isinstance(day, datetime.datetime):
        day = day.date()
    return (day - ROTATION_START).days


def rotation_ids(day: int) -> List[int]:
    """The three banners of a rotation day: two Parts, then the theme."""
    return [*PART_PAIRS[day % len(PART_PAIRS)], THEME_ORDER[day % len(THEME_ORDER)]]


def day_date(day: int) -> datetime.date:
    return ROTATION_START + datetime.timedelta(days=day)


def banner_schedule(days: int = 7, when=None) -> List[dict]:
    """Today and the next days: [{"day", "date", "current", "banners": [banner...]}]."""
    first = rotation_day(when)
    by_id = {b["id"]: b for b in BANNERS}
    return [{"day": d, "date": day_date(d), "current": d == first,
             "banners": [by_id[i] for i in rotation_ids(d) if i in by_id]} for d in range(first, first + days)]


def next_appearance(banner_id: int, horizon: int = 14, when=None) -> Optional[datetime.date]:
    """The day a banner next comes back (None if it's on today or not within the horizon)."""
    first = rotation_day(when)
    for d in range(first + 1, first + horizon):
        if banner_id in rotation_ids(d):
            return day_date(d)
    return None


def rotation_ends(when=None) -> datetime.datetime:
    return datetime.datetime.combine(day_date(rotation_day(when) + 1), datetime.time())


def banner_override(banner: dict):
    """An admin's on/off switch for a banner (web:banner_state), or None to follow the rotation."""
    try:
        from app.db import r
        state = r().hget("web:banner_state", str(banner["id"]))
    except Exception:
        return None
    return None if state is None else state in (b"1", "1")


def banner_enabled(banner: dict) -> bool:
    """On while it's in this week's rotation; an admin can force any banner on or off."""
    forced = banner_override(banner)
    if forced is not None:
        return forced
    return banner["enabled"] and banner["id"] in rotation_ids(rotation_day())


def _banner(banner_id: int) -> dict:
    for b in BANNERS:
        if b["id"] == banner_id and banner_enabled(b):
            return b
    raise GameError("This banner isn't available.")


# Web drop rates (kinder than the bot's 80 / 19 / 0.9 / 0.1 with pity at 100).
BANNER_ODDS = {"R": 0.55, "SR": 0.33, "SSR": 0.10, "UR": 0.02}
ARROW_ODDS = {"SR": 0.70, "SSR": 0.25, "UR": 0.05}  # 5 cards: ~1.25 SSR and 0.25 UR, about a 10-pull's worth
PITY_LIMIT = 50          # pulls without an SSR+ before one is guaranteed
PITY_ODDS = {"UR": 0.94, "LR": 0.06}  # the guaranteed pull; banners without an LR give a UR
HIGH_RARITIES = ("SSR", "UR", "LR")
SPARK_COST = 20  # every 10-pull earns a spark; this many buy any SSR from a banner


def sparks(user: User) -> int:
    return int(user.data.get("web_sparks", 0))


def spark_exchange(user: User, banner_id: int, stand_id: int) -> Character:
    banner = _banner(banner_id)
    template = next((c for c in CHARACTER_FILE if c["id"] == stand_id), None)
    if template is None or stand_id not in banner["cards"] or template["rarity"] != "SSR":
        raise GameError("Pick an SSR from this banner.")
    if sparks(user) < SPARK_COST:
        raise GameError(f"You need {SPARK_COST} sparks. You have {sparks(user)}.")
    if free_slots(user) < 1:
        raise GameError("Storage is full. Auto-fuse or release a few stands first.")
    user.data["web_sparks"] = sparks(user) - SPARK_COST
    types, qualities = roll_types_qualities()
    char = get_character_from_template(template, types, qualities)
    where = add_to_available_storage(user, char, skip_main=True)
    _fill_team(user, [(char, where)])
    return char


def _template_of(banner: dict, rarity: str, exclude=()) -> dict:
    """A banner stand of that rarity; if the banner has none, the nearest rarity below, then above.
    Stands already drawn in this pull (exclude) are skipped while others of the rarity remain:
    small pools otherwise repeat the same stand in most 10-pulls."""
    order = ["R", "SR", "SSR", "UR", "LR"]
    i = order.index(rarity)
    for r in order[i::-1] + order[i + 1:]:
        pool = [CHARACTER_FILE[c - 1] for c in banner["cards"] if CHARACTER_FILE[c - 1]["rarity"] == r]
        if pool:
            fresh = [t for t in pool if t["id"] not in exclude]
            return random.choice(fresh or pool)
    return CHARACTER_FILE[random.choice(banner["cards"]) - 1]


def _banner_draw(banner: dict, user: User, floor: Optional[str] = None, exclude=(),
                 forced: Optional[str] = None) -> Character:
    """One banner stand. Pity: PITY_LIMIT pulls without SSR+ guarantee an SSR, UR or (rarely) LR.
    forced: an admin's test rarity."""
    types, qualities = roll_types_qualities()
    if forced:
        rarity = forced
    elif user.pity >= PITY_LIMIT - 1:
        rarity = random.choices(list(PITY_ODDS), weights=list(PITY_ODDS.values()), k=1)[0]
    else:
        rarity = random.choices(list(BANNER_ODDS), weights=list(BANNER_ODDS.values()), k=1)[0]
    if floor == "SR" and rarity == "R":
        rarity = "SR"
    template = _template_of(banner, rarity, exclude)
    user.pity = 0 if template["rarity"] in HIGH_RARITIES else user.pity + 1
    return get_character_from_template(template, types, qualities)


def _arrow_draw(banner: dict, exclude=(), forced: Optional[str] = None) -> Character:
    """Arrow: no pity, SR floor."""
    types, qualities = roll_types_qualities()
    rarity = forced or random.choices(list(ARROW_ODDS), weights=list(ARROW_ODDS.values()), k=1)[0]
    return get_character_from_template(_template_of(banner, rarity, exclude), types, qualities)


def _forced_at(force: Optional[dict], i: int, n: int) -> Optional[str]:
    """An admin's forced rarity for card i of n: {"rarity", "scope": "last" | "all"}."""
    if not force:
        return None
    return force["rarity"] if force.get("scope") == "all" or i == n - 1 else None


RARITY_ORDER = {"R": 0, "SR": 1, "SSR": 2, "UR": 3, "LR": 4}


def _fill_team(user: User, drawn: list) -> list:
    """Empty team slots take the best stands of this pull, so a new player can fight right away."""
    free = 3 - len(user.main_characters)
    if free <= 0:
        return drawn
    best = sorted((c for c, _ in drawn), key=lambda c: (RARITY_ORDER.get(c.rarity, 0), c.current_damage + c.current_hp / 5),
                  reverse=True)[:free]
    for c in best:
        if c in user.storage_characters:
            user.storage_characters.remove(c)
            user.main_characters.append(c)
    picked = {id(c) for c in best}
    return [(c, "Team" if id(c) in picked else where) for c, where in drawn]


def _record_pull(user: User, banner: dict, drawn: list, mode: str):
    """Mark first-time stands and keep a short web-only pull history in the save."""
    owned_before = {c.id for c in user.main_characters + user.storage_characters} - {c.id for c, _ in drawn}
    seen, out = set(), []
    for c, where in drawn:
        out.append({"stand": c, "where": where, "new": c.id not in owned_before and c.id not in seen})
        seen.add(c.id)
    history = user.data.setdefault("web_pull_history", [])
    history.insert(0, {"at": now().isoformat(timespec="minutes"), "banner": banner["name"], "mode": mode,
                       "rarities": [c.rarity for c, _ in drawn], "ids": [c.id for c, _ in drawn]})
    del history[30:]
    return out


# --------------------------------------------------------------------------- #
# /adventure begin, /adventure daily
# --------------------------------------------------------------------------- #
def begin(user: User):
    user.super_fragments += 1
    check_achievements(user, "register")


# Claiming the daily reward on consecutive days climbs this 7-day ladder, then starts over.
STREAK_REWARDS = [
    {"fragments": 100}, {"fragments": 150}, {"items": [13]}, {"fragments": 250},
    {"items": [2]}, {"fragments": 400}, {"super": 1},
]


def streak(user: User) -> dict:
    """{"count": days in a row, "day": position in the 7-day ladder (1-7), "alive": not broken yet}."""
    data = user.data.get("web_streak") or {}
    last = data.get("last")
    today = now().date()
    alive = bool(last) and (today - datetime.date.fromisoformat(last)).days <= 1
    count = data.get("count", 0) if alive else 0
    claimed_today = alive and last == today.isoformat()
    upcoming = count if claimed_today else count + 1
    return {"count": count, "claimed_today": claimed_today, "next_day": (upcoming - 1) % 7 + 1}


def _claim_streak(user: User) -> Optional[dict]:
    """Once per calendar day (the daily itself can be claimed more often)."""
    s = streak(user)
    if s["claimed_today"]:
        return None
    count = s["count"] + 1
    user.data["web_streak"] = {"count": count, "last": now().date().isoformat()}
    day = (count - 1) % 7 + 1
    bonus = STREAK_REWARDS[day - 1]
    user.fragments += bonus.get("fragments", 0)
    user.super_fragments += bonus.get("super", 0)
    items = [item_from_dict({"id": i}) for i in bonus.get("items", [])]
    user.items.extend(items)
    return {"count": count, "day": day, "fragments": bonus.get("fragments", 0), "super": bonus.get("super", 0),
            "items": [i.name for i in items]}


def daily(user: User) -> dict:
    wait = DONOR_ADV_WAIT_TIME + (not user.is_donator()) * NORMAL_ADV_WAIT_TIME
    left = cooldown_left(user.last_adventure, wait)
    if left:
        raise GameError(f"Your daily reward is back in {fmt_delta(left)}.")
    user.last_adventure = now()
    roll = random.randint(1, 100)
    res = {"fragments": 100, "item": None, "super": 0}
    user.fragments += 100
    if roll < 60:
        item_id = random.choices([13, 1, 4, 2, 15, 40, 38], weights=[0.34, 0.20, 0.12, 0.12, 0.05, 0.12, 0.05], k=1)[0]
        item = item_from_dict({"id": item_id})
        user.items.append(item)
        res["item"] = item
    if roll < 2:
        user.super_fragments += 1
        res["super"] = 1
    res["streak"] = _claim_streak(user)
    track_quest_progress(user, "daily_claim")
    track_quest_progress(user, "reach_level", user.level)
    check_achievements(user, "daily_claim")
    check_achievements(user, "reach_level", user.level)
    return res


# --------------------------------------------------------------------------- #
# /banner pull, /banner arrow
# --------------------------------------------------------------------------- #
def banner_pull(user: User, banner_id: int, force: Optional[dict] = None) -> dict:
    banner = _banner(banner_id)
    if banner["cost"] > user.super_fragments:
        raise GameError(f"A 10-pull costs {banner['cost']} Arrowhead. You have {user.super_fragments}.")
    if free_slots(user) < 10:
        raise GameError("You need 10 free storage slots. Auto-fuse your R and SR duplicates or release a few stands first.")
    user.super_fragments -= banner["cost"]
    drawn = []
    for i in range(10):
        # 10-pull floor: the last stand is at least SR if the first nine were all R
        floor = "SR" if i == 9 and all(c.rarity == "R" for c, _ in drawn) else None
        c = _banner_draw(banner, user, floor, exclude={d.id for d, _ in drawn}, forced=_forced_at(force, i, 10))
        drawn.append((c, add_to_available_storage(user, c, skip_main=True)))
    track_quest_progress(user, "banner_pull")
    check_achievements(user, "banner_pull")
    if sum(c.rarity == "R" for c, _ in drawn) >= 9:
        check_achievements(user, "unlucky_pull")
    drawn = _fill_team(user, drawn)
    user.data["web_sparks"] = sparks(user) + 1
    return {"banner": banner, "drawn": drawn, "cards": _record_pull(user, banner, drawn, "pull")}


def arrow_pull(user: User, banner_id: int, force: Optional[dict] = None) -> dict:
    banner = _banner(banner_id)
    arrow = next((i for i in user.items if i.id == 2), None)
    if arrow is None:
        raise GameError("You don't have any Devil's Palm.")
    if free_slots(user) < 5:
        raise GameError("You need 5 free storage slots. Auto-fuse your R and SR duplicates or release a few stands first.")
    user.items.remove(arrow)
    drawn = []
    for i in range(5):
        c = _arrow_draw(banner, exclude={d.id for d, _ in drawn}, forced=_forced_at(force, i, 5))
        drawn.append((c, add_to_available_storage(user, c, skip_main=True)))
    track_quest_progress(user, "banner_pull")
    check_achievements(user, "banner_pull")
    drawn = _fill_team(user, drawn)
    return {"banner": banner, "drawn": drawn, "cards": _record_pull(user, banner, drawn, "arrow")}


# --------------------------------------------------------------------------- #
# /character main | store | remove | ascend | fuse | reforge
# --------------------------------------------------------------------------- #
def to_main(user: User, uuid: str, swap_uuid: Optional[str] = None) -> Character:
    char, lst, idx = locate(user, uuid)
    if lst is user.main_characters:
        raise GameError(f"{char.name} is already in your team.")
    if len(user.main_characters) < 3:
        lst.pop(idx)
        user.main_characters.append(char)
        return char
    if not swap_uuid:
        raise GameError("Your team is full. Choose who leaves.")
    out = next((c for c in user.main_characters if c.uuid == swap_uuid), None)
    if out is None:
        raise GameError("That stand isn't in your team.")
    lst.pop(idx)
    user.main_characters.remove(out)
    lst.append(out)
    user.main_characters.append(char)
    return char


def store(user: User, uuid: str):
    char, lst, idx = locate(user, uuid)
    if lst is not user.main_characters:
        raise GameError(f"{char.name} is already in storage.")
    lst.pop(idx)
    where = add_to_available_storage(user, char, skip_main=True)
    if not where:
        lst.insert(idx, char)
        raise GameError("Every storage is full.")
    return char, where


def locked(user: User) -> set:
    """Web-only protection list, stored in the save as data["web_locked"] (the bot ignores it)."""
    return set(user.data.get("web_locked", []))


def toggle_lock(user: User, uuid: str) -> bool:
    char, _, _ = locate(user, uuid)
    current = locked(user)
    now_locked = uuid not in current
    current.symmetric_difference_update({uuid})
    owned = {c.uuid for c in user.main_characters + user.storage_characters}
    user.data["web_locked"] = sorted(current & owned)
    return now_locked


def set_locks(user: User, uuids: List[str], lock: bool) -> int:
    """Lock or unlock many stands at once. Returns how many changed."""
    owned = {c.uuid for c in user.main_characters + user.storage_characters}
    current = locked(user)
    wanted = set(uuids) & owned
    changed = len(wanted - current) if lock else len(wanted & current)
    current = (current | wanted) if lock else (current - wanted)
    user.data["web_locked"] = sorted(current & owned)
    return changed


def release(user: User, uuids: List[str]) -> List[Character]:
    """Release stands. A single pick must be releasable; a bulk pick skips locked and team stands."""
    gone = []
    protected = locked(user)
    bulk = len(uuids) > 1
    for u in uuids:
        char, lst, idx = locate(user, u)
        if lst is user.main_characters:
            if bulk:
                continue
            raise GameError("Move a stand to storage before releasing it.")
        if u in protected:
            if bulk:
                continue
            raise GameError(f"{char.name} is locked. Unlock it first.")
        lst.pop(idx)
        gone.append(char)
        if char.rarity in ("SSR", "UR", "LR"):
            check_achievements(user, "release_rare")
    if not gone:
        raise GameError("Every selected stand is locked or in your team.")
    for team in user.teams.values():  # keep presets tidy
        for c in gone:
            if c.uuid in team:
                team.remove(c.uuid)
    return gone


def ascend(user: User, uuid: str) -> Character:
    char, lst, _ = locate(user, uuid)
    if lst is not user.main_characters:
        raise GameError("Only stands in your team can ascend.")
    if char.level >= 100 and char.awaken < 3:
        char.awaken += 1
        char.xp = 0
        return char
    raise GameError("A stand must be level 100 and below 3 awakenings to ascend.")


CATCH_UP_LEVEL = 30  # stands below this level learn twice as fast, so new pulls can join the team


def train(char: Character, amount: int) -> int:
    """Give a stand XP from playing (doubled below CATCH_UP_LEVEL). Returns what it got."""
    if char.xp // STXPTOLEVEL < CATCH_UP_LEVEL:
        amount *= 2
    char.xp += amount
    return amount


# Fusing: the kept copy takes the other's XP plus a bonus by its rarity. It also gains an
# awakening, but only once it has the level for it, so stars come with time played and a
# lucky pull can't skip the whole climb. Below the gate a copy still pays its XP.
FUSE_BONUS_XP = {"R": 25, "SR": 50, "SSR": 200, "UR": 400, "LR": 600}
AWAKEN_LEVELS = (20, 50, 80)  # level needed for ★1, ★2, ★3 through fusing


def awaken_gate(char: Character) -> Optional[int]:
    """Level the next fusion awakening needs, or None once fusing can't add stars."""
    return AWAKEN_LEVELS[char.awaken] if char.awaken < len(AWAKEN_LEVELS) else None


def _absorb(user: User, keeper: Character, fodder: Character) -> Character:
    """Fold fodder into keeper: its XP plus a rarity bonus, one gated awakening, its items back to the bag."""
    user.items.extend(fodder.items)
    keeper.xp += fodder.xp + FUSE_BONUS_XP.get(fodder.rarity, 100)
    gate = awaken_gate(keeper)
    if gate is not None and min(100, keeper.xp // STXPTOLEVEL) >= gate:
        keeper.awaken += 1
    return keeper


def _refresh(user: User, char: Character) -> Character:
    """Recompute stats like the bot's next load, in place in whichever list holds it."""
    _, lst, idx = locate(user, char.uuid)
    fresh = Character(char.to_dict())
    lst[idx] = fresh
    return fresh


def fuse(user: User, uuid: str, fodder_uuid: str) -> Character:
    if uuid == fodder_uuid:
        raise GameError("Pick two different copies.")
    char, lst, _ = locate(user, uuid)
    other, lst2, idx2 = locate(user, fodder_uuid)
    if lst2 is user.main_characters:
        raise GameError("The copy you consume must be in storage.")
    if char.id != other.id:
        raise GameError("You can only fuse two copies of the same stand.")
    if fodder_uuid in locked(user):
        raise GameError(f"The copy you'd consume is locked. Unlock it first.")
    lst2.pop(idx2)
    track_quest_progress(user, "fuse")
    return _refresh(user, _absorb(user, char, other))


AUTO_FUSE_RARITIES = ("R", "SR")


def auto_fuse_plan(user: User, rarities=AUTO_FUSE_RARITIES) -> List[tuple]:
    """[(keeper, [fodder...])] for every R/SR stand owned more than once.
    The keeper is the team copy if there is one, else the most advanced copy.
    Only unlocked storage copies are consumed; nothing is fused past what it can use."""
    protected = locked(user)
    by_id = {}
    for c in user.main_characters + user.storage_characters:
        if c.rarity in rarities:
            by_id.setdefault(c.id, []).append(c)
    plan = []
    for copies in by_id.values():
        if len(copies) < 2:
            continue
        team = [c for c in copies if c in user.main_characters]
        keeper = team[0] if team else max(copies, key=lambda c: (c.uuid in protected, c.awaken, c.xp))
        fodder = [c for c in copies if c is not keeper and c not in user.main_characters and c.uuid not in protected]
        if fodder:
            plan.append((keeper, fodder))
    return plan


def auto_fuse(user: User, rarities=AUTO_FUSE_RARITIES) -> dict:
    plan = auto_fuse_plan(user, rarities)
    if not plan:
        raise GameError("No R or SR duplicates to fuse.")
    fused, copies = [], 0
    gone = set()
    for keeper, fodder in plan:
        for f in fodder:
            _absorb(user, keeper, f)
            gone.add(f.uuid)
        copies += len(fodder)
        fused.append(keeper.uuid)
    user.storage_characters[:] = [c for c in user.storage_characters if c.uuid not in gone]
    for team in user.teams.values():
        team[:] = [u for u in team if u not in gone]
    stands = [_refresh(user, locate(user, u)[0]) for u in fused]
    track_quest_progress(user, "fuse", copies)
    return {"stands": stands, "copies": copies}


def _power(c: Character) -> float:
    """Same as the collection's power score."""
    from app.filters import power_score
    return power_score(c)


def best_team(user: User) -> dict:
    """Strongest 3 among the owned stands: raw power, +8% for each member of an active synergy,
    +5% for each native of a terrain the team itself sets. Tries every trio of the top 14."""
    from itertools import combinations
    from app.game.characterabilities import SYNERGIES
    from app.game.effects import TERRAIN_BENEFITS, TERRAIN_SETTERS
    owned = user.main_characters + user.storage_characters
    pool = sorted(owned, key=_power, reverse=True)[:14]
    best, best_score, best_why = [], -1, []
    for trio in combinations(pool, min(3, len(pool))):
        ids = {c.id for c in trio}
        if len(ids) < len(trio):
            continue  # two copies of one stand: keep the slot for something else
        bonus, why = 0.0, []
        for name, members in SYNERGIES.items():
            active = ids & members
            if len(active) >= 2:
                bonus += 0.08 * len(active)
                why.append(name.replace("_", " + ").title() + " synergy")
        for c in trio:
            terrain = TERRAIN_SETTERS.get(c.id)
            natives = [o for o in trio if terrain in TERRAIN_BENEFITS.get(o.id, {})] if terrain else []
            if natives:
                bonus += 0.05 * len(natives)
                why.append(f"{terrain.display_name} terrain")
        score = sum(_power(c) for c in trio) * (1 + bonus)
        if score > best_score:
            best, best_score, best_why = list(trio), score, sorted(set(why))
    current = sum(_power(c) for c in user.main_characters)
    return {"team": best, "why": best_why, "same": {c.uuid for c in best} == {c.uuid for c in user.main_characters},
            "gain": int(round(100 * (sum(_power(c) for c in best) / current - 1))) if current else None}


def use_team(user: User, uuids: List[str]) -> List[Character]:
    """Make exactly these stands the team; the current members go back to storage."""
    if not 1 <= len(uuids) <= 3 or len(set(uuids)) != len(uuids):
        raise GameError("Pick one to three different stands.")
    chosen = [locate(user, u)[0] for u in uuids]
    leaving = [c for c in user.main_characters if c.uuid not in uuids]
    if len(user.storage_characters) - sum(c in user.storage_characters for c in chosen) + len(leaving) > STORAGE_CAPACITY:
        raise GameError("Storage is full. Release a few stands first.")
    for c in chosen:
        if c in user.storage_characters:
            user.storage_characters.remove(c)
    for c in leaving:
        user.storage_characters.append(c)
    user.main_characters[:] = chosen
    return chosen


# Reforge: reroll a stand's type/quality pairs. Price depends on rarity; each locked pair
# costs 50% more. The new roll waits next to the old one until the player keeps one of them.
REFORGE_PRICE = {"R": 200, "SR": 350, "SSR": 600, "UR": 900, "LR": 1200}  # a service, not an endgame sink
REFORGE_LOCK_MULT = 1.5


def reforge_cost(char: Character, locks: int = 0) -> int:
    return int(round(REFORGE_PRICE.get(char.rarity, 600) * REFORGE_LOCK_MULT ** locks, -1))


def _reroll(types: List[str], qualities: List[str], locked: List[int]):
    """Keep the locked pairs; replace the rest with a fresh roll that never repeats a locked type."""
    keep = [(types[i], qualities[i]) for i in sorted(set(locked)) if i < len(types)]
    kept_types = {t for t, _ in keep}
    new_types, new_quals = roll_types_qualities()
    fresh = [(t, q) for t, q in zip(new_types, new_quals) if t not in kept_types]
    if not fresh:  # the roll only produced locked types: draw one free pair
        spare = [t.name for t in Types if t.name not in kept_types]
        fresh = [(random.choice(spare), random.choices([q.name for q in Qualities], [5, 10, 20, 50, 10, 5])[0])]
    pairs = keep + fresh
    return [t for t, _ in pairs], [q for _, q in pairs]


def reforge_roll(user: User, uuid: str, locked: List[int]) -> dict:
    char, lst, idx = locate(user, uuid)
    locked = sorted({i for i in locked if 0 <= i < len(char.types)})
    if char.types and len(locked) >= len(char.types):
        raise GameError("Leave at least one stat unlocked to reroll.")
    waiting = reforge_pending(user)
    if waiting and waiting["uuid"] != uuid:
        other = locate(user, waiting["uuid"])[0]
        raise GameError(f"{other.name} still has a new roll waiting. Keep it or drop it first.")
    cost = reforge_cost(char, len(locked))
    if user.fragments < cost:
        raise GameError(f"This reforge costs {cost:,} Meteor Dust. You have {user.fragments:,}.")
    user.fragments -= cost
    types, qualities = _reroll(char.types, char.qualities, locked)
    user.data["web_reforge_pending"] = {"uuid": uuid, "types": types, "qualities": qualities,
                                        "old_types": list(char.types), "old_qualities": list(char.qualities)}
    track_quest_progress(user, "reforge")
    check_achievements(user, "reforge")
    _check_broke(user)
    return {"char": char, "cost": cost, "types": types, "qualities": qualities}


def reforge_pending(user: User, uuid: Optional[str] = None) -> Optional[dict]:
    pending = user.data.get("web_reforge_pending")
    if not pending or (uuid and pending["uuid"] != uuid):
        return None
    try:
        locate(user, pending["uuid"])
    except GameError:
        user.data.pop("web_reforge_pending", None)
        return None
    return pending


def reforge_keep(user: User, keep_new: bool) -> Character:
    pending = reforge_pending(user)
    if not pending:
        raise GameError("There is no reforge waiting for a decision.")
    char, lst, idx = locate(user, pending["uuid"])
    user.data.pop("web_reforge_pending", None)
    if keep_new:
        from app.filters import power_score
        before = power_score(char)
        char.types, char.qualities = list(pending["types"]), list(pending["qualities"])
        lst[idx] = Character(char.to_dict())
        if power_score(lst[idx]) < before:
            check_achievements(user, "reforge_downgrade")
        return lst[idx]
    return char


def preview_with(char: Character, types: List[str], qualities: List[str]) -> Character:
    """A throwaway copy of the stand with another roll, to compare stats."""
    data = dict(char.to_dict())
    data.update(types=list(types), qualities=list(qualities))
    return Character(data)

def _take_item(user: User, item_id: int) -> Item:
    for i, it in enumerate(user.items):
        if it.id == item_id:
            return user.items.pop(i)
    raise GameError("You don't have that item.")


def equip(user: User, uuid: str, item_id: int):
    char, lst, _ = locate(user, uuid)
    if lst is not user.main_characters:
        raise GameError("Only stands in your team can hold items.")
    if len(char.items) >= 3:
        raise GameError(f"{char.name} already holds 3 items.")
    item = _take_item(user, item_id)
    if not item.is_equipable:
        user.items.append(item)
        raise GameError(f"{item.name} can't be equipped.")
    char.items.append(item)
    track_quest_progress(user, "item_equip")
    check_achievements(user, "item_equip")
    if len(char.items) >= 3:
        check_achievements(user, "full_kit")
    return char, item


def unequip(user: User, uuid: str, slot: int):
    char, _, _ = locate(user, uuid)
    if not (0 <= slot < len(char.items)):
        raise GameError("Nothing in that slot.")
    item = char.items.pop(slot)
    user.items.append(item)
    return char, item


def use_item(user: User, item_id: int, uuid: Optional[str] = None) -> dict:
    item = _take_item(user, item_id)
    if item.is_equipable:
        user.items.append(item)
        raise GameError(f"{item.name} is equipped on a stand, not used.")

    def refund(msg):
        user.items.append(item)
        raise GameError(msg)

    if item.id == 2:
        refund("Spend Devil's Palms on a banner: each one draws 5 stands at SR or better.")
    if item.id in GACHA_ITEMS:
        pool = [
            get_character_from_template(c, [], [])
            for c in CHARACTER_FILE
            if c["id"] not in SPECIAL_CHARACTERS and (item.id == 2 or c["id"] < 31)
        ]
        drop = get_drop_from_list(pool)[0]
        where = add_to_available_storage(user, drop)
        if not where:
            refund("Every storage slot is full.")
        res = {"kind": "stand", "stand": drop, "where": where}
    elif item.id in CHIP_IDS:
        template = CHARACTER_FILE[CHIP_TEMPLATE_INDEX[CHIP_IDS.index(item.id)]]
        c = get_character_from_template(template, [], [])
        where = add_to_available_storage(user, c)
        if not where:
            refund("Every storage slot is full.")
        res = {"kind": "stand", "stand": c, "where": where}
    elif item.id == 13:
        amount = random.randint(75, 125)
        user.fragments += amount
        check_achievements(user, "bag_open")
        res = {"kind": "fragments", "fragments": amount}
    elif item.id == 3:
        if not uuid:
            refund("Pick a stand from your team.")
        char = next((c for c in user.main_characters if c.uuid == uuid), None)
        if char is None:
            refund("Pick a stand from your team.")
        idx = user.main_characters.index(char)
        if char.id in REQUIEMABLE and char.awaken >= REQUIEM_STARS[char.id] and char.level >= 100:
            template = CHARACTER_FILE[REQUIEM_TEMPLATE_INDEX[REQUIEMABLE.index(char.id)]]
            new = get_character_from_template(template, [], [])
            new.items = char.items
            new.reset()
            user.main_characters[idx] = new
            res = {"kind": "requiem", "stand": new}
            track_quest_progress(user, "requiem")
        else:
            if char.awaken >= MAX_AWAKEN:
                refund(f"{char.name} is at ★{MAX_AWAKEN}, the highest awakening.")
            char.awaken += 1
            user.main_characters[idx] = Character(char.to_dict())
            res = {"kind": "awaken", "stand": user.main_characters[idx]}
    else:
        refund(f"{item.name} can't be used here.")
    track_quest_progress(user, "item_use")
    check_achievements(user, "item_use")
    res["item"] = item
    return res


def craft(user: User, recipe_name: str) -> Item:
    recipe = next((r for r in RECIPES if r["name"] == recipe_name), None)
    if not recipe:
        raise GameError("Unknown recipe.")
    for item_id, amount in recipe["ingredients"]:
        if sum(1 for i in user.items if i.id == item_id) < amount:
            raise GameError(f"Missing {item_file[item_id - 1]['name']}.")
    for item_id, amount in recipe["ingredients"]:
        for _ in range(amount):
            user.items.remove(next(i for i in user.items if i.id == item_id))
    crafted = Item({"id": recipe["result"]})
    user.items.append(crafted)
    track_quest_progress(user, "item_craft")
    check_achievements(user, "item_craft")
    return crafted


SHOP_HEADS_PER_WEEK = 3  # summons (Arrowheads and Devil's Palms together) the shop sells each player per week


def shop_heads_left(user: User) -> int:
    bought = user.data.get("web_shop_heads") or {}
    return SHOP_HEADS_PER_WEEK - (bought.get("n", 0) if bought.get("week") == now().strftime("%G-W%V") else 0)


def _check_broke(user: User):
    if user.fragments < 100:
        check_achievements(user, "broke")


def shop_buy(user: User, key: str) -> str:
    entry = DEFAULT_SHOP.get(key)
    if not entry:
        raise GameError("That isn't sold here.")
    if entry["type"] == "currency" or entry.get("summon"):
        left = shop_heads_left(user)
        if left <= 0:
            raise GameError(f"The shop sells {SHOP_HEADS_PER_WEEK} summons a week (Arrowheads and Devil's Palms). "
                            "More arrive on Monday.")
        user.data["web_shop_heads"] = {"week": now().strftime("%G-W%V"), "n": SHOP_HEADS_PER_WEEK - left + 1}
    if user.fragments < entry["price"]:
        raise GameError(f"You need {entry['price']:,} Meteor Dust. You have {user.fragments:,}.")
    user.fragments -= entry["price"]
    _check_broke(user)
    track_quest_progress(user, "shop_buy")
    check_achievements(user, "shop_buy")
    if entry["type"] == "currency":
        user.super_fragments += 1
    else:
        user.items.append(Item({"id": entry["id"]}))
    return entry["name"]


# --------------------------------------------------------------------------- #
# /team save | load | delete
# --------------------------------------------------------------------------- #
def team_save(user: User, name: str) -> str:
    if not user.main_characters:
        raise GameError("Your team is empty.")
    name = name.strip().lower()[:20]
    if not name:
        raise GameError("Give the preset a name.")
    if len(user.teams) >= MAX_TEAMS and name not in user.teams:
        raise GameError(f"You can keep {MAX_TEAMS} presets. Delete one first.")
    user.teams[name] = [c.uuid for c in user.main_characters]
    return name


def team_load(user: User, name: str) -> List[Character]:
    if name not in user.teams:
        raise GameError("That preset doesn't exist.")
    uuids = user.teams[name]
    if not any(user.find_character_by_uuid(u)[0] for u in uuids):
        raise GameError("None of that preset's stands are left.")
    # like the bot: everyone back to storage, then pull the preset out.
    # Unlike the bot, stop if storage is full instead of losing a stand
    # (GameError = nothing is saved).
    for c in list(user.main_characters):
        if not add_to_available_storage(user, c, skip_main=True):
            raise GameError("Your storage is full, free a slot to swap teams.")
    user.main_characters.clear()
    for u in uuids:
        c, lst, idx = user.find_character_by_uuid(u)
        if c is not None:
            lst.pop(idx)
            user.main_characters.append(c)
    return user.main_characters


def team_delete(user: User, name: str):
    if user.teams.pop(name, None) is None:
        raise GameError("That preset doesn't exist.")


# --------------------------------------------------------------------------- #
# Energy (utils/decorators.py energy_check)
# --------------------------------------------------------------------------- #
def refill_energy(user: User) -> bool:
    wait = (12 - 6 * user.is_donator()) * 3600
    if (now() - user.last_full_energy).total_seconds() >= wait and user.energy < user.total_energy:
        user.energy = user.total_energy
        user.last_full_energy = now()
        return True
    return False


def energy_refill_in(user: User) -> Optional[datetime.timedelta]:
    if user.energy >= user.total_energy:
        return None
    wait = datetime.timedelta(hours=12 - 6 * user.is_donator())
    return max(datetime.timedelta(0), user.last_full_energy + wait - now())


# --------------------------------------------------------------------------- #
# /wormhole
# --------------------------------------------------------------------------- #
WORMHOLE_NAMES = ["Megalo", "Mr Davelo", "Vince", "Icarus", "Arkkos", "Yoshikage Ramsay",
                  "Keyshiwo", "EIRBLAST", "Obama", "Mizu", "ft.fate"]


def wormhole_wait(user: User) -> float:
    return DONOR_WH_WAIT_TIME + (not user.is_donator()) * NORMAL_WH_WAIT_TIME


def wormhole_enemy(user: User):
    lvl = user.level
    if lvl < 5:
        rarity, n, multi = "R", random.randint(1, 2), 1
    elif lvl < 25:
        rarity, n, multi = "SR", 1, 2
    elif lvl < 50:
        rarity, n, multi = "SSR", random.randint(2, 3), 3
    elif lvl < 75:
        rarity, n, multi = "UR", 3, 3
    else:
        rarity, n, multi = "LR", 3, 4
    # no training dummy (1M HP) or The World Over Heaven (100k damage) in the wild
    pool = [c for c in CHARACTER_FILE if c["rarity"] == rarity and c["universe"] != "Dummy" and c["id"] != 110]
    chars = [get_character_from_template(t, [], []) for t in random.choices(pool, k=n)]
    return f"{random.choice(WORMHOLE_NAMES)}'s Soul", chars, multi


def wormhole_start(user: User):
    if not user.main_characters:
        raise GameError("You need at least one stand in your team.")
    left = cooldown_left(user.last_wormhole, wormhole_wait(user))
    if left:
        raise GameError(f"The next wormhole opens in {fmt_delta(left)}.")
    refill_energy(user)
    if user.energy < 1:
        raise GameError("You need 1 energy. It refills over time.")
    user.energy -= 1
    user.last_wormhole = now()
    return wormhole_enemy(user)


def wormhole_reward(user: User, won: bool, multi: int) -> dict:
    track_quest_progress(user, "wormhole_complete")
    check_achievements(user, "wormhole_complete")
    if not won:
        check_achievements(user, "wormhole_loss")
        return {"won": False}
    user.last_wormhole = now()
    for a in ("wormhole_win", "fight_win"):
        track_quest_progress(user, a)
        check_achievements(user, a)
    user.xp += PLAYER_XPGAINS
    user.fragments += FRAGMENTSGAIN * multi
    for c in user.main_characters:
        train(c, CHARACTER_XPGAINS * multi)
    item = None
    if random.randint(1, 100) <= CHANCEITEM:
        item_id = random.choices([13, 1, 4, 15, 2, 3, 38, 39, 40],
                                 weights=[0.24, 0.16, 0.14, 0.12, 0.08, 0.04, 0.08, 0.06, 0.08], k=1)[0]
        item = item_from_dict({"id": item_id})
        user.items.append(item)
    return {"won": True, "fragments": FRAGMENTSGAIN * multi, "xp": PLAYER_XPGAINS,
            "stand_xp": CHARACTER_XPGAINS * multi, "item": item.name if item else None}


def sell_price(item) -> int:
    """/shop sell: a tenth of the shop price; free items can't be sold."""
    return (item.price or 0) // 10


def sell_item(user: User, item_id: int, count: int = 1) -> dict:
    owned = [i for i in user.items if i.id == item_id]
    if not owned:
        raise GameError("You don't have that item.")
    price = sell_price(owned[0])
    if price <= 0:
        raise GameError(f"{owned[0].name} can't be sold.")
    count = max(1, min(count, len(owned)))
    for it in owned[:count]:
        user.items.remove(it)
    user.fragments += price * count
    return {"name": owned[0].name, "count": count, "fragments": price * count}


# --------------------------------------------------------------------------- #
# /quest
# --------------------------------------------------------------------------- #
def quest_claim(user: User, quest_id: int) -> dict:
    ensure_quests_assigned(user)
    res = claim_quest_reward(user, quest_id)
    if not res:
        raise GameError("This quest isn't ready to claim.")
    return res


def quest_claim_all(user: User) -> List[dict]:
    ensure_quests_assigned(user)
    out = [claim_quest_reward(user, q["id"]) for q in get_claimable_quests(user)]
    out = [r for r in out if r]
    if not out:
        raise GameError("No quest is ready to claim.")
    return out


RANK_TIERS = [(3000, "Over Heaven"), (2500, "Love Train"), (2000, "Requiem"),
              (1500, "ACT 4"), (1000, "ACT 3"), (500, "ACT 2"), (0, "ACT 1")]


def rank_name(elo: int) -> str:
    return next(name for threshold, name in RANK_TIERS if elo >= threshold)
