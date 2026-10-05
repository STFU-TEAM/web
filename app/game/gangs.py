"""Gang rules ported from the bot's extensions/gang.py.

Gangs are pickled dicts in the "gangs" hash (see models/gameobjects/gang.py).
Wars are matched and ended by the bot's parallel_process/warmatchmaking.py,
raids are web-only and weekly (see "Weekly raid" below); for wars the web queues,
attacks and reads the shared keys:
    PUBLISH war_matchmaking_requests pickle(gang_id)
    HGET   active_wars <gang_id>      -> pickle(opponent gang id)
    HGETALL war_records               -> pickle({winner, loser, winner_damage, loser_damage, timestamp})
"""
import datetime
import json
import pickle
import re
import time
from typing import Optional

from app.game.character import character_from_dict
from app.game.items import item_file, item_from_dict
from app.game.logic import CHARACTER_XPGAINS, FRAGMENTSGAIN, PLAYER_XPGAINS, GameError, now, train

BOSS, CAPO, SOLDIER = 0, 1, 2
RANK_NAMES = {BOSS: "Boss", CAPO: "Capo", SOLDIER: "Soldier"}
MAX_GUARDIANS = 3
GANG_COST = 10000
WAR_QUEUE = "web:war:queue"
WAR_HOURS = 48
WAR_PRIZE = 10_000  # Meteor Dust paid into the winner's vault
WAR_ELO_K = 32
DEFAULT_IMAGE = "https://media1.tenor.com/m/-fG6_QSIjZAAAAAC/amicreeper-galaxy.gif"


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
        raise GameError(f"You only have {user.fragments:,} Meteor Dust.")
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


def _queued_key(gang_id: str) -> str:
    return f"web:gang:queued:{gang_id}"


def queue_war(redis, gang: dict, actor: str) -> Optional[str]:
    """Look for a war. Returns the id of a waiting gang to fight now, or None after joining the queue."""
    require_rank(gang, actor, CAPO)
    if not gang.get("characters"):
        raise GameError("Your gang needs at least one guardian to go to war.")
    if opponent_id(redis, gang["_id"]):
        raise GameError("Your gang is already at war.")
    if redis.get(_queued_key(gang["_id"])):
        raise GameError("Your gang is already looking for an opponent.")
    for raw in redis.lrange(WAR_QUEUE, 0, -1):
        gid = raw.decode() if isinstance(raw, bytes) else str(raw)
        redis.lrem(WAR_QUEUE, 0, gid)
        if gid != gang["_id"] and redis.get(_queued_key(gid)) and not opponent_id(redis, gid):
            return gid
    redis.rpush(WAR_QUEUE, gang["_id"])
    redis.set(_queued_key(gang["_id"]), 1, ex=24 * 3600)
    return None


def requeue(redis, gang_id: str):
    """Put a gang back at the head of the queue (its match couldn't start)."""
    redis.lpush(WAR_QUEUE, gang_id)


def start_war(redis, a: dict, b: dict):
    end = now() + datetime.timedelta(hours=WAR_HOURS)
    for gang, other in ((a, b), (b, a)):
        gang.update(end_of_war=end, damage_to_current_war=0, war_attacks=[])
        redis.hset("active_wars", gang["_id"], pickle.dumps(other["_id"]))
        redis.delete(_queued_key(gang["_id"]))


def war_over(gang: dict) -> bool:
    end = gang.get("end_of_war")
    return isinstance(end, datetime.datetime) and end <= now()


def settle_war(redis, a: dict, b: dict) -> dict:
    """End a war: more damage per member wins Elo and WAR_PRIZE for its vault."""
    per = {g["_id"]: int(g.get("damage_to_current_war", 0)) / max(1, len(members(g))) for g in (a, b)}
    winner, loser = (a, b) if per[a["_id"]] >= per[b["_id"]] else (b, a)
    decided = per[winner["_id"]] > per[loser["_id"]]
    if decided:
        expected = 1 / (1 + 10 ** ((int(loser.get("war_elo", 0)) - int(winner.get("war_elo", 0))) / 400))
        delta = max(1, round(WAR_ELO_K * (1 - expected)))
        winner["war_elo"] = int(winner.get("war_elo", 0)) + delta
        loser["war_elo"] = max(0, int(loser.get("war_elo", 0)) - delta)
        winner["vault"] = int(winner.get("vault", 0)) + WAR_PRIZE
    stamp = now()
    for gang in (a, b):
        gang.update(last_war=stamp, war_attacks=[])
        redis.hdel("active_wars", gang["_id"])
    record = {"winner": winner["_id"], "loser": loser["_id"], "winner_damage": per[winner["_id"]],
              "loser_damage": per[loser["_id"]], "draw": not decided, "timestamp": stamp.isoformat()}
    redis.hset("war_records", f"{winner['_id']}:{loser['_id']}:{stamp.isoformat()}", pickle.dumps(record))
    return record


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
# Weekly raid (web): one villain per week, one attack per member per day,
# gang damage unlocks reward tiers that every attacker claims.
# --------------------------------------------------------------------------- #
WEEKLY_RAIDS = [
    {"name": "DIO", "boss": 10, "minions": [30, 19], "flavor": "The World stops time over Cairo. Vanilla Ice and Death 13 guard the stairs."},
    {"name": "Yoshikage Kira", "boss": 58, "minions": [54, 51], "flavor": "Bites the Dust loops Morioh's morning. Stray Cat and Atom Heart Father watch the house."},
    {"name": "Diavolo", "boss": 75, "minions": [81, 82], "flavor": "King Crimson erases the hours. Green Day and Oasis hold the Colosseum."},
    {"name": "Enrico Pucci", "boss": 109, "minions": [108, 107], "flavor": "Made in Heaven accelerates the universe. C-Moon and Whitesnake buy him time."},
    {"name": "Funny Valentine", "boss": 120, "minions": [124, 126], "flavor": "D4C hides behind every dimension. His guards rewind and booby-trap the train."},
    {"name": "Toru", "boss": 161, "minions": [154, 149], "flavor": "Wonder of U turns pursuit into calamity. Walking Heart and Doobie Wah stalk the hospital."},
    {"name": "Diego Brando", "boss": 134, "minions": [117, 132], "flavor": "THE WORLD from another universe, with Scary Monsters and Civil War at its side."},
    {"name": "Chariot Requiem", "boss": 83, "minions": [68, 74], "flavor": "Every soul in Rome swaps. Man in the Mirror and White Album seal the exits."},
]
RAID_LEVEL, RAID_AWAKEN, RAID_BOSS_HP = 80, 1, 12  # the boss is a damage sponge, not a kill
RAID_TIERS = [
    {"damage": 10_000, "fragments": 1500, "items": [40, 40, 47]},
    {"damage": 50_000, "fragments": 3000, "items": [38, 38, 39, 47, 47]},
    {"damage": 200_000, "fragments": 5000, "super": 1, "items": [2, 38, 38]},
    {"damage": 600_000, "fragments": 8000, "super": 2, "items": [39, 39, "corpse"]},
]


def week_key(when=None) -> str:
    year, week, _ = (when or now()).isocalendar()
    return f"{year}-W{week:02d}"


def week_ends(when=None) -> datetime.datetime:
    when = when or now()
    monday = (when - datetime.timedelta(days=when.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    return monday + datetime.timedelta(days=7)


def weekly_boss(when=None) -> dict:
    _, week, _ = (when or now()).isocalendar()
    return WEEKLY_RAIDS[week % len(WEEKLY_RAIDS)]


def raid_state(gang: dict) -> dict:
    """This week's raid on the gang, reset lazily when a new week starts."""
    state = gang.get("web_raid")
    if not state or state.get("week") != week_key():
        if state and state.get("hits"):  # last week's tiers stay claimable for one more week
            gang["web_raid_prev"] = state
        state = {"week": week_key(), "damage": 0, "attacks": {}, "hits": {}, "claimed": {}}
        gang["web_raid"] = state
    return state


def previous_raid(gang: dict) -> Optional[dict]:
    """Last week's raid, if it ended in the week just before this one."""
    raid_state(gang)
    prev = gang.get("web_raid_prev")
    last_week = week_key(now() - datetime.timedelta(days=7))
    return prev if prev and prev.get("week") == last_week else None


def can_attack(gang: dict, uid: str) -> bool:
    return raid_state(gang)["attacks"].get(str(uid)) != now().date().isoformat()


def raid_team() -> list:
    boss = weekly_boss()
    team = []
    for i, cid in enumerate([boss["boss"]] + boss["minions"]):
        c = character_from_dict({"id": cid, "xp": RAID_LEVEL * 100, "awaken": RAID_AWAKEN, "types": ["BALANCE"],
                                 "qualities": ["GREAT"], "items": [{"id": 1}] if i == 0 else []})
        if i == 0:
            c.start_hp *= RAID_BOSS_HP
            c.current_hp = c.start_hp
        team.append(c)
    return team


def start_raid_attack(gang: dict, uid: str):
    if not can_attack(gang, uid):
        raise GameError("You already attacked the raid boss today. Come back tomorrow.")
    raid_state(gang)["attacks"][str(uid)] = now().date().isoformat()


def raid_damage(enemies) -> int:
    """HP taken off the raid team."""
    return int(sum(max(0, c.start_hp - max(c.current_hp, 0)) for c in enemies))


def record_raid_damage(gang: dict, uid: str, damage: int, week: str, redis=None):
    state = raid_state(gang)
    if state["week"] != week:  # the fight started last week: too late to count
        return
    state["damage"] += damage
    state["hits"][str(uid)] = state["hits"].get(str(uid), 0) + damage
    if redis is not None:  # weekly leaderboard without scanning every gang
        key = f"web:raid:{week}"
        redis.zadd(key, {gang["_id"]: state["damage"]})
        redis.hset(f"{key}:names", gang["_id"], gang.get("name", "?"))
        redis.expire(key, 60 * 60 * 24 * 21)
        redis.expire(f"{key}:names", 60 * 60 * 24 * 21)


def _tiers_for(state: Optional[dict], uid: str) -> list:
    if not state or str(uid) not in state["hits"]:
        return []
    done = set(state["claimed"].get(str(uid), []))
    return [i for i, t in enumerate(RAID_TIERS) if state["damage"] >= t["damage"] and i not in done]


def claimable_tiers(gang: dict, uid: str) -> list:
    return _tiers_for(raid_state(gang), uid)


def claimable_previous(gang: dict, uid: str) -> list:
    return _tiers_for(previous_raid(gang), uid)


def tier_text(tier: dict) -> str:
    parts = [f"{tier['fragments']:,} Meteor Dust"]
    if tier.get("super"):
        parts.append(f"{tier['super']} Arrowhead{'s' if tier['super'] > 1 else ''}")
    counts = {}
    for i in tier["items"]:
        name = "a Saint's Corpse part" if i == "corpse" else item_file[i - 1]["name"]
        counts[name] = counts.get(name, 0) + 1
    parts += [f"{n} × {name}" if n > 1 else name for name, n in counts.items()]
    return ", ".join(parts)


def claim_raid(gang: dict, user) -> list:
    """Claim every reached tier of this week and of last week's raid. Returns the tiers paid."""
    import random
    paid = []
    for state, tiers in ((raid_state(gang), claimable_tiers(gang, user.id)),
                         (previous_raid(gang), claimable_previous(gang, user.id))):
        for i in tiers:
            tier = RAID_TIERS[i]
            user.fragments += tier["fragments"]
            user.super_fragments += tier.get("super", 0)
            for item_id in tier["items"]:
                user.items.append(item_from_dict({"id": random.choice([34, 35, 36]) if item_id == "corpse" else item_id}))
            paid.append(i)
        if tiers:
            state["claimed"].setdefault(str(user.id), []).extend(tiers)
    if not paid:
        raise GameError("Nothing to claim yet. Attack the boss and reach the next tier.")
    return paid


def raid_board(redis, limit: int = 10) -> list:
    key = f"web:raid:{week_key()}"
    rows = redis.zrevrange(key, 0, limit - 1, withscores=True)
    out = []
    for gid, damage in rows:
        gid = gid.decode() if isinstance(gid, bytes) else gid
        name = redis.hget(f"{key}:names", gid)
        out.append({"id": gid, "name": name.decode() if isinstance(name, bytes) else (name or "?"), "damage": int(damage)})
    return [row for row in out if row["damage"]]


def attack_rewards(user, won: bool) -> dict:
    """Same payout as the bot after a war or raid attack: doubled on a win."""
    mult = 1 + int(won)
    user.xp += PLAYER_XPGAINS * mult
    user.fragments += FRAGMENTSGAIN * mult
    for c in user.main_characters:
        train(c, CHARACTER_XPGAINS * mult)
    return {"won": won, "fragments": FRAGMENTSGAIN * mult, "xp": PLAYER_XPGAINS * mult,
            "stand_xp": CHARACTER_XPGAINS * mult, "item": None}


# --------------------------------------------------------------------------- #
# Gang chat (web): a short shared message board polled by the gang page.
#   web:gang:chat:<gang_id>      list of JSON {id, uid, text, at}, newest last, capped CHAT_KEEP
#   web:gang:chat:seq:<gang_id>  last message id (the page polls with it: nothing new, nothing sent)
# --------------------------------------------------------------------------- #
CHAT_KEEP = 150
CHAT_MAX_LEN = 300
CHAT_COOLDOWN = 2  # seconds between two messages from the same player


def chat_post(redis, gang: dict, uid: str, text: str) -> dict:
    text = " ".join((text or "").split())[:CHAT_MAX_LEN]
    if not text:
        raise GameError("Write something first.")
    if str(uid) not in [str(m) for m in members(gang)]:
        raise GameError("You're not in this gang.")
    if not redis.set(f"web:gang:chat:slow:{uid}", "1", nx=True, ex=CHAT_COOLDOWN):
        raise GameError("Slow down a little.")
    gid = gang["_id"]
    msg = {"id": int(redis.incr(f"web:gang:chat:seq:{gid}")), "uid": str(uid), "text": text, "at": int(time.time())}
    pipe = redis.pipeline()
    pipe.rpush(f"web:gang:chat:{gid}", json.dumps(msg))
    pipe.ltrim(f"web:gang:chat:{gid}", -CHAT_KEEP, -1)
    pipe.execute()
    return msg


def chat_seq(redis, gang_id: str) -> int:
    return int(redis.get(f"web:gang:chat:seq:{gang_id}") or 0)


def chat_messages(redis, gang_id: str, limit: int = 60) -> list:
    out = []
    for raw in redis.lrange(f"web:gang:chat:{gang_id}", -limit, -1):
        try:
            out.append(json.loads(raw))
        except ValueError:
            continue
    return out


def chat_delete(redis, gang: dict, actor: str, msg_id: int):
    """Capos and the boss can remove any message; everyone can remove their own."""
    key = f"web:gang:chat:{gang['_id']}"
    for raw in redis.lrange(key, 0, -1):
        try:
            msg = json.loads(raw)
        except ValueError:
            continue
        if msg.get("id") == msg_id:
            if msg["uid"] != str(actor) and rank_of(gang, actor) > CAPO:
                raise GameError("Only capos and the boss can remove other members' messages.")
            redis.lrem(key, 1, raw)
            redis.incr(f"web:gang:chat:seq:{gang['_id']}")  # the pollers refresh
            return
    raise GameError("That message is gone.")
