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
CHARACTER_XPGAINS = 10
FRAGMENTSGAIN = 300
CHANCEITEM = 10
DONOR_WH_WAIT_TIME = 1
NORMAL_WH_WAIT_TIME = 1.5
DONOR_ADV_WAIT_TIME = 6
NORMAL_ADV_WAIT_TIME = 6
STXPTOLEVEL = 100

STORAGE_SIZE = 25
MAX_TEAMS = 5
REFORGE_COST = 10000
RARITIES = ["R", "SR", "SSR", "UR", "LR"]

# /shop default
DEFAULT_SHOP = {
    "super_fragment": {"name": "Super Fragment", "price": 5000, "type": "currency"},
    "1": {"name": "Dio's Knife", "price": 2500, "type": "item", "id": 1},
    "2": {"name": "Stand Arrows", "price": 2500, "type": "item", "id": 2},
    "3": {"name": "Requiem Arrow", "price": 10000, "type": "item", "id": 3},
    "4": {"name": "Giorno's ladybug", "price": 5000, "type": "item", "id": 4},
}

# /item use
GACHA_ITEMS = [2, 12]
CHIP_IDS = [8, 9, 10, 11, 14, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27, 28, 29, 30, 31, 32]
CHIP_TEMPLATE_INDEX = [9, 0, 5, 29, 162, 30, 57, 31, 33, 44, 48, 49, 58, 59, 68, 74, 77, 79, 80, 82, 83]
REQUIEMABLE = [49, 6, 59]
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


def _banner(banner_id: int) -> dict:
    for b in BANNERS:
        if b["id"] == banner_id and b["enabled"]:
            return b
    raise GameError("This banner isn't available.")


def _banner_draw(banner: dict, user: User) -> Character:
    """generate_character_data: pity at 100 = 50/50 UR or SSR."""
    types, qualities = roll_types_qualities()
    if user.pity >= 100:
        user.pity = 0
        rarity = random.choice(["UR", "SSR"])
    else:
        rarity = random.choices(["R", "SR", "SSR", "UR"], weights=[0.8, 0.19, 0.009, 0.001], k=1)[0]
    template = random.choice([CHARACTER_FILE[c - 1] for c in banner["cards"] if CHARACTER_FILE[c - 1]["rarity"] == rarity])
    return get_character_from_template(template, types, qualities)


def _arrow_draw(banner: dict) -> Character:
    """generate_arrow_character_data: no pity, SR floor."""
    types, qualities = roll_types_qualities()
    rarity = random.choices(["SR", "SSR", "UR"], weights=[0.70, 0.22, 0.08], k=1)[0]
    matching = [CHARACTER_FILE[c - 1] for c in banner["cards"] if CHARACTER_FILE[c - 1]["rarity"] == rarity]
    if not matching:
        matching = [CHARACTER_FILE[c - 1] for c in banner["cards"]]
    return get_character_from_template(random.choice(matching), types, qualities)


# --------------------------------------------------------------------------- #
# /adventure begin, /adventure daily
# --------------------------------------------------------------------------- #
def begin(user: User):
    user.super_fragements += 1


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
        item_id = random.choices([13, 1, 4, 2, 15], weights=[0.40, 0.25, 0.15, 0.15, 0.05], k=1)[0]
        item = item_from_dict({"id": item_id})
        user.items.append(item)
        res["item"] = item
    if roll < 2:
        user.super_fragements += 1
        res["super"] = 1
    track_quest_progress(user, "daily_claim")
    track_quest_progress(user, "reach_level", user.level)
    check_achievements(user, "daily_claim")
    check_achievements(user, "reach_level", user.level)
    return res


# --------------------------------------------------------------------------- #
# /banner pull, /banner arrow
# --------------------------------------------------------------------------- #
def banner_pull(user: User, banner_id: int) -> dict:
    banner = _banner(banner_id)
    if banner["cost"] > user.super_fragements:
        raise GameError(f"A 10-pull costs {banner['cost']} super fragment. You have {user.super_fragements}.")
    if free_slots(user) < 10:
        raise GameError("You need 10 free storage slots. Release a few stands first.")
    user.super_fragements -= banner["cost"]
    drawn = []
    for _ in range(10):
        c = _banner_draw(banner, user)
        where = add_to_available_storage(user, c, skip_main=True)
        drawn.append((c, where))
        user.pity += 1
    track_quest_progress(user, "banner_pull")
    check_achievements(user, "banner_pull")
    return {"banner": banner, "drawn": drawn}


def arrow_pull(user: User, banner_id: int) -> dict:
    banner = _banner(banner_id)
    arrow = next((i for i in user.items if i.id == 2), None)
    if arrow is None:
        raise GameError("You don't have any Stand Arrow.")
    if free_slots(user) < 5:
        raise GameError("You need 5 free storage slots. Release a few stands first.")
    user.items.remove(arrow)
    drawn = []
    for _ in range(5):
        c = _arrow_draw(banner)
        drawn.append((c, add_to_available_storage(user, c, skip_main=True)))
    track_quest_progress(user, "banner_pull")
    check_achievements(user, "banner_pull")
    return {"banner": banner, "drawn": drawn}


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


def release(user: User, uuids: List[str]) -> List[Character]:
    gone = []
    for u in uuids:
        char, lst, idx = locate(user, u)
        if lst is user.main_characters:
            raise GameError("Move a stand to storage before releasing it.")
        lst.pop(idx)
        gone.append(char)
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


def fuse(user: User, uuid: str, fodder_uuid: str) -> Character:
    if uuid == fodder_uuid:
        raise GameError("Pick two different copies.")
    char, lst, _ = locate(user, uuid)
    other, lst2, idx2 = locate(user, fodder_uuid)
    if lst is user.main_characters or lst2 is user.main_characters:
        raise GameError("Both copies must be in storage.")
    if char.id != other.id:
        raise GameError("You can only fuse two copies of the same stand.")
    lst2.pop(idx2)
    user.items.extend(other.items)
    char.xp += other.xp
    char.xp += 50 * STXPTOLEVEL
    if char.awaken < 3:
        char.awaken += 1
    # recompute stats like the bot's next load
    fresh = Character(char.to_dict())
    lst[lst.index(char)] = fresh
    return fresh


def reforge(user: User, uuid: str) -> Character:
    if user.fragments < REFORGE_COST:
        raise GameError(f"Reforging costs {REFORGE_COST:,} fragments. You have {user.fragments:,}.")
    char, lst, idx = locate(user, uuid)
    if lst is not user.main_characters:
        raise GameError("Only stands in your team can be reforged.")
    user.fragments -= REFORGE_COST
    char.types, char.qualities = roll_types_qualities()
    fresh = Character(char.to_dict())
    user.main_characters[idx] = fresh
    return fresh


# --------------------------------------------------------------------------- #
# /item equip | unequip | use | craft ; /shop default
# --------------------------------------------------------------------------- #
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
        res = {"kind": "fragments", "fragments": amount}
    elif item.id == 3:
        if not uuid:
            refund("Pick a stand from your team.")
        char = next((c for c in user.main_characters if c.uuid == uuid), None)
        if char is None:
            refund("Pick a stand from your team.")
        if char.awaken >= 7:
            refund(f"{char.name} is fully awakened.")
        idx = user.main_characters.index(char)
        if char.id in REQUIEMABLE and char.awaken >= 2 and char.level >= 100:
            template = CHARACTER_FILE[REQUIEM_TEMPLATE_INDEX[REQUIEMABLE.index(char.id)]]
            new = get_character_from_template(template, [], [])
            new.items = char.items
            new.reset()
            user.main_characters[idx] = new
            res = {"kind": "requiem", "stand": new}
        else:
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


def shop_buy(user: User, key: str) -> str:
    entry = DEFAULT_SHOP.get(key)
    if not entry:
        raise GameError("That isn't sold here.")
    if user.fragments < entry["price"]:
        raise GameError(f"You need {entry['price']:,} fragments. You have {user.fragments:,}.")
    user.fragments -= entry["price"]
    track_quest_progress(user, "shop_buy")
    check_achievements(user, "shop_buy")
    if entry["type"] == "currency":
        user.super_fragements += 1
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
    pool = [c for c in CHARACTER_FILE if c["rarity"] == rarity]
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
        return {"won": False}
    user.last_wormhole = now()
    for a in ("wormhole_win", "fight_win"):
        track_quest_progress(user, a)
        check_achievements(user, a)
    user.xp += PLAYER_XPGAINS
    user.fragments += FRAGMENTSGAIN * multi
    for c in user.main_characters:
        c.xp += CHARACTER_XPGAINS * multi
    item = None
    if random.randint(1, 100) <= CHANCEITEM:
        item_id = random.choices([13, 1, 4, 15, 2, 3], weights=[0.30, 0.20, 0.20, 0.15, 0.10, 0.05], k=1)[0]
        item = item_from_dict({"id": item_id})
        user.items.append(item)
    return {"won": True, "fragments": FRAGMENTSGAIN * multi, "xp": PLAYER_XPGAINS,
            "stand_xp": CHARACTER_XPGAINS * multi, "item": item.name if item else None}


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
