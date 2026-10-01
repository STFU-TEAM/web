"""Gang rules ported from the bot's extensions/gang.py.

Gangs are pickled dicts in the "gangs" hash (see models/gameobjects/gang.py).
Wars are matched and ended by the bot's parallel_process/warmatchmaking.py,
raids are ended by parallel_process/raid_end.py; the web only queues, attacks
and reads the shared keys:
    PUBLISH war_matchmaking_requests pickle(gang_id)
    HGET   active_wars <gang_id>      -> pickle(opponent gang id)
    HGETALL war_records               -> pickle({winner, loser, winner_damage, loser_damage, timestamp})
    HGET   RAID_RECORDS raid_<gang_id> -> pickle({successful, rewards, ...})
"""
import datetime
import json
import os
import pickle
import re
from typing import Optional

from app.game.character import character_from_dict
from app.game.items import item_file, item_from_dict
from app.game.logic import CHARACTER_XPGAINS, FRAGMENTSGAIN, PLAYER_XPGAINS, GameError, now

BOSS, CAPO, SOLDIER = 0, 1, 2
RANK_NAMES = {BOSS: "Boss", CAPO: "Capo", SOLDIER: "Soldier"}
MAX_GUARDIANS = 3
GANG_COST = 10000
MATCHMAKING_CHANNEL = "war_matchmaking_requests"
DEFAULT_IMAGE = "https://media1.tenor.com/m/-fG6_QSIjZAAAAAC/amicreeper-galaxy.gif"

with open(os.path.join(os.path.dirname(__file__), "data", "raid.json"), encoding="utf-8") as _f:
    RAID = json.load(_f)
RAID_REWARD_NAMES = [item_file[i - 1]["name"] for i in RAID["rewards"]]


def new_gang(gang_id: str, owner: str, name: str, motto: str, motd: str) -> dict:
    never = datetime.datetime.min
    return {
        "_id": gang_id, "name": name, "motd": motd, "motto": motto, "image_url": DEFAULT_IMAGE,
        "users": [owner], "ranks": {owner: BOSS}, "vault": 0, "characters": [], "items": [],
        "raid_level": 1, "war_elo": 0, "war_attacks": [], "raid_attacks": [],
        "damage_to_current_war": 0, "damage_to_current_raid": 0,
        "end_of_raid": never, "end_of_war": never, "last_raid": never, "last_war": never,
    }


def rank_of(gang: dict, uid) -> int:
    ranks = gang.get("ranks", {})
    uid = str(uid)
    if uid in ranks:
        return int(ranks[uid])
    if uid.isdigit() and int(uid) in ranks:  # very old gangs keyed ranks by int
        return int(ranks[int(uid)])
    return SOLDIER


def _set_rank(gang: dict, uid: str, rank: int):
    ranks = gang.setdefault("ranks", {})
    if uid.isdigit():
        ranks.pop(int(uid), None)
    ranks[uid] = rank


def members(gang: dict) -> list:
    return [str(u) for u in gang.get("users", [])]


def require_rank(gang: Optional[dict], uid: str, minimum: int):
    if not gang:
        raise GameError("You are not in a gang, or your gang no longer exists.")
    if rank_of(gang, uid) > minimum:
        raise GameError(f"Only a {RANK_NAMES[minimum].lower()} or higher can do that.")


# --------------------------------------------------------------------------- #
# Members
# --------------------------------------------------------------------------- #
def kick(gang: dict, actor: str, target_user) -> str:
    require_rank(gang, actor, CAPO)
    target = str(target_user.id)
    if target not in members(gang):
        raise GameError("That player isn't in your gang.")
    if rank_of(gang, actor) >= rank_of(gang, target):
        raise GameError("You can only kick members ranked below you.")
    gang["users"] = [u for u in gang["users"] if str(u) != target]
    gang.get("ranks", {}).pop(target, None)
    target_user.gang_id = None
    return target


def promote(gang: dict, actor: str, target: str) -> str:
    """Soldier -> capo. Promoting a capo hands them the boss seat (actor becomes capo)."""
    require_rank(gang, actor, BOSS)
    if target not in members(gang) or target == actor:
        raise GameError("Pick another member of your gang.")
    if rank_of(gang, target) == CAPO:
        _set_rank(gang, target, BOSS)
        _set_rank(gang, actor, CAPO)
        return "boss"
    _set_rank(gang, target, CAPO)
    return "capo"


def demote(gang: dict, actor: str, target: str):
    require_rank(gang, actor, BOSS)
    if target not in members(gang) or target == actor:
        raise GameError("Pick another member of your gang.")
    _set_rank(gang, target, SOLDIER)


def edit_profile(gang: dict, actor: str, motto: str, motd: str, image_url: str):
    require_rank(gang, actor, BOSS)
    if len(motto) > 120 or len(motd) > 160:
        raise GameError("The motto is limited to 120 characters and the message to 160.")
    if image_url and not re.match(r"^https://[^\s\"'<>]{4,300}$", image_url):
        raise GameError("The image must be an https:// link.")
    gang["motto"], gang["motd"] = motto, motd
    gang["image_url"] = image_url or DEFAULT_IMAGE


# --------------------------------------------------------------------------- #
# Vault and gang items
# --------------------------------------------------------------------------- #
def deposit(gang: dict, user, amount: int):
    if amount is None or amount <= 0:
        raise GameError("Deposit a positive amount.")
    if amount > user.fragments:
        raise GameError(f"You only have {user.fragments:,} fragments.")
    user.fragments -= amount
    gang["vault"] = int(gang.get("vault", 0)) + amount


def pay(gang: dict, actor: str, target_user, amount: int):
    require_rank(gang, actor, BOSS)
    if str(target_user.id) not in members(gang):
        raise GameError("You can only pay members of your gang.")
    if amount is None or amount <= 0:
        raise GameError("Pay a positive amount.")
    if amount > int(gang.get("vault", 0)):
        raise GameError("The vault doesn't hold that much.")
    gang["vault"] -= amount
    target_user.fragments += amount


def give_item(gang: dict, actor: str, target_user, index: int):
    require_rank(gang, actor, BOSS)
    if str(target_user.id) not in members(gang):
        raise GameError("You can only give items to members of your gang.")
    items = gang.get("items", [])
    if index is None or not 0 <= index < len(items):
        raise GameError("That item is no longer in the gang stash.")
    target_user.items.append(item_from_dict(items.pop(index)))


# --------------------------------------------------------------------------- #
# Guardians (gang.characters): defend in wars
# --------------------------------------------------------------------------- #
def add_guardian(gang: dict, user, uuid: str):
    if str(user.id) not in members(gang):
        raise GameError("You are not in this gang.")
    if len(gang.get("characters", [])) >= MAX_GUARDIANS:
        raise GameError(f"A gang has at most {MAX_GUARDIANS} guardians.")
    stand = next((c for c in user.storage_characters if c.uuid == uuid), None)
    if stand is None:
        raise GameError("Pick a stand from your storage.")
    user.storage_characters.remove(stand)
    user.character_storage_list = [user.storage_characters]
    gang.setdefault("characters", []).append(stand.to_dict())
    return stand


def remove_guardian(gang: dict, user, index: int, free_slots: int):
    require_rank(gang, str(user.id), CAPO)
    chars = gang.get("characters", [])
    if index is None or not 0 <= index < len(chars):
        raise GameError("That guardian is gone.")
    if free_slots < 1:
        raise GameError("Your storage is full.")
    stand = character_from_dict(chars.pop(index))
    user.storage_characters.append(stand)
    return stand


# --------------------------------------------------------------------------- #
# Wars
# --------------------------------------------------------------------------- #
def opponent_id(redis, gang_id: str) -> Optional[str]:
    raw = redis.hget("active_wars", gang_id)
    if not raw:
        return None
    value = pickle.loads(raw)
    return value.decode() if isinstance(value, bytes) else str(value)


def queue_war(redis, gang: dict, actor: str):
    require_rank(gang, actor, CAPO)
    if not gang.get("characters"):
        raise GameError("Your gang needs at least one guardian to go to war.")
    if opponent_id(redis, gang["_id"]):
        raise GameError("Your gang is already at war.")
    if redis.get(f"web:gang:queued:{gang['_id']}"):
        raise GameError("Your gang is already looking for an opponent.")
    redis.publish(MATCHMAKING_CHANNEL, pickle.dumps(gang["_id"]))
    redis.set(f"web:gang:queued:{gang['_id']}", 1, ex=30 * 60)


def last_war(redis, gang_id: str) -> Optional[dict]:
    best = None
    for raw in redis.hvals("war_records"):
        try:
            record = pickle.loads(raw)
        except Exception:
            continue
        if gang_id in (record.get("winner"), record.get("loser")):
            if best is None or record.get("timestamp", "") > best.get("timestamp", ""):
                best = record
    return best


def war_damage(enemies) -> int:
    """Percentage of the enemy guardians knocked out (fighthandler gang_fight)."""
    return int(100 * sum(not c.is_alive() for c in enemies) / max(1, len(enemies)))


# --------------------------------------------------------------------------- #
# Raids
# --------------------------------------------------------------------------- #
def raid_active(gang: dict) -> bool:
    return gang.get("end_of_raid", datetime.datetime.min) > now()


def start_raid(gang: dict, actor: str):
    require_rank(gang, actor, CAPO)
    if raid_active(gang):
        raise GameError("Your gang is already raiding.")
    if int(gang.get("vault", 0)) < RAID["cost"]:
        raise GameError(f"A raid costs {RAID['cost']:,} fragments from the vault.")
    gang["vault"] -= RAID["cost"]
    gang["end_of_raid"] = now() + datetime.timedelta(days=1)
    gang["damage_to_current_raid"] = 0
    gang["raid_attacks"] = []


def raid_boss():
    return [character_from_dict(dict(c)) for c in RAID["main_characters"]]


def raid_damage(enemies) -> int:
    """HP taken off the raid boss team (fighthandler calculate_team_damage)."""
    return int(sum(max(0, c.start_hp - max(c.current_hp, 0)) for c in enemies))


def raid_record(redis, gang_id: str) -> Optional[dict]:
    raw = redis.hget("RAID_RECORDS", f"raid_{gang_id}")
    return pickle.loads(raw) if raw else None


def attack_rewards(user, won: bool) -> dict:
    """Same payout as the bot after a war or raid attack: doubled on a win."""
    mult = 1 + int(won)
    user.xp += PLAYER_XPGAINS * mult
    user.fragments += FRAGMENTSGAIN * mult
    for c in user.main_characters:
        c.xp += CHARACTER_XPGAINS * mult
    return {"won": won, "fragments": FRAGMENTSGAIN * mult, "xp": PLAYER_XPGAINS * mult,
            "stand_xp": CHARACTER_XPGAINS * mult, "item": None}
