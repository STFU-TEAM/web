"""D'Arby's gambling den: the coin glass, played for Meteor Dust against D'Arby or another player.

A glass is filled to the brim; players take turns dropping one coin, or two (a bold move: your turn ends sooner, but
the glass gets fuller twice as fast). Every coin may be the one that spills it (risk(), rising with the coins already
in); whoever spills loses. Everything is decided here on the server, never in the page.

Against D'Arby the stake is matched by the house: a win pays it back doubled. Against a player both put in the same
stake and the winner takes the pot. Limits keep it a side game: account level MIN_LEVEL, stakes up to MAX_STAKE,
GAMES_PER_DAY games and LOSS_PER_DAY dust lost a day, and COOL_OFF minutes off the table after COOL_AFTER losses in
a row. Three wins in a row against D'Arby earn his poker chip (a title).

    web:den:game:<id>           JSON game state (GAME_TTL)
    web:den:active:<uid>        the id of the game uid is in
    web:den:day:<uid>:<date>    hash games, lost
    web:den:streak:<uid>        hash lose (losses in a row), win (wins in a row against D'Arby)
    web:den:cool:<uid>          set while the table is closed to uid
"""
import datetime
import json
import random
import secrets
import time
from typing import Optional

from app.game.logic import GameError

MIN_LEVEL = 10
MIN_STAKE, MAX_STAKE = 100, 2000
GAMES_PER_DAY = 10
LOSS_PER_DAY = 5000
COOL_AFTER, COOL_OFF = 3, 15 * 60
TURN_SECONDS = 15          # PvP: run out and a coin drops for you
ACCEPT_SECONDS = 10 * 60   # PvP: how long a challenge waits
GAME_TTL = 3600
CHIP_TITLE = "D'Arby's poker chip"
CHIP_STREAK = 3
LANTERN, LANTERN_NAME = 68, "Enya's Fog Lantern"  # paid each time a streak against D'Arby reaches CHIP_STREAK


def risk(coins: int) -> float:
    """The chance the next coin spills the glass, with `coins` already in."""
    return min(0.95, 0.02 + coins * coins * 0.0045)


def _s(v):
    return v.decode() if isinstance(v, bytes) else v


def _day(uid) -> str:
    return f"web:den:day:{uid}:{datetime.date.today().isoformat()}"


def today(redis, uid) -> dict:
    raw = {_s(k): int(v) for k, v in redis.hgetall(_day(uid)).items()}
    return {"games": raw.get("games", 0), "lost": raw.get("lost", 0)}


def cooling(redis, uid) -> int:
    """Seconds the table stays closed to uid (0: open)."""
    return max(0, int(redis.ttl(f"web:den:cool:{uid}") or 0))


def blocked(redis, user, stake: int = 0) -> Optional[str]:
    """Why user can't sit down for a game at this stake now, or None."""
    uid = str(user.id)
    if user.level < MIN_LEVEL:
        return f"D'Arby only plays with seasoned Stand users: reach level {MIN_LEVEL} first."
    left = cooling(redis, uid)
    if left:
        return f"Three losses in a row: D'Arby closes the table for {left // 60 + 1} more minute{'s' if left > 60 else ''}."
    t = today(redis, uid)
    if t["games"] >= GAMES_PER_DAY:
        return f"You played your {GAMES_PER_DAY} games today. The den opens again tomorrow."
    if t["lost"] >= LOSS_PER_DAY:
        return f"You lost {LOSS_PER_DAY:,} dust today, the daily limit. The den opens again tomorrow."
    if stake:
        if not MIN_STAKE <= stake <= MAX_STAKE or stake % 100:
            raise GameError(f"Stakes go from {MIN_STAKE} to {MAX_STAKE:,} dust, by 100.")
        if t["lost"] + stake > LOSS_PER_DAY:
            return f"That stake could take you past today's {LOSS_PER_DAY:,} dust limit: {LOSS_PER_DAY - t['lost']:,} left."
        if user.fragments < stake:
            return "Not enough Meteor Dust for that stake."
    if redis.get(f"web:den:active:{uid}"):
        return "You're already at a table."
    return None


# ── games ────────────────────────────────────────────────────────────────────

def get(redis, gid: str) -> Optional[dict]:
    raw = redis.get(f"web:den:game:{gid}") if gid and gid.isalnum() else None
    return json.loads(raw) if raw else None


def active(redis, uid) -> Optional[dict]:
    gid = _s(redis.get(f"web:den:active:{uid}"))
    game = get(redis, gid) if gid else None
    if gid and not game:
        redis.delete(f"web:den:active:{uid}")
    return game


def _save(redis, game: dict):
    redis.set(f"web:den:game:{game['id']}", json.dumps(game), ex=GAME_TTL)
    for uid in game["players"]:
        if game["state"] in ("waiting", "playing"):
            redis.set(f"web:den:active:{uid}", game["id"], ex=GAME_TTL)
        elif _s(redis.get(f"web:den:active:{uid}")) == game["id"]:
            redis.delete(f"web:den:active:{uid}")


def _count_game(redis, uid):
    redis.hincrby(_day(uid), "games", 1)
    redis.expire(_day(uid), 86400)


def start_darby(redis, user, stake: int) -> dict:
    """Sit down against D'Arby: the stake is taken now, paid back doubled on a win."""
    why = blocked(redis, user, stake)
    if why:
        raise GameError(why)
    user.fragments -= stake
    uid = str(user.id)
    game = {"id": secrets.token_hex(6), "mode": "darby", "players": [uid], "names": [user.data.get("name") or "You", "D'Arby"],
            "stake": stake, "coins": 0, "turn": 0, "state": "playing", "winner": None, "last": [], "at": time.time()}
    _count_game(redis, uid)
    _save(redis, game)
    return game


def challenge(redis, user, other_uid: str, other_name: str, stake: int) -> dict:
    """Challenge a friend: your stake is held now; theirs when they accept."""
    why = blocked(redis, user, stake)
    if why:
        raise GameError(why)
    if str(other_uid) == str(user.id):
        raise GameError("Pick someone else.")
    if redis.get(f"web:den:active:{other_uid}"):
        raise GameError(f"{other_name} is already at a table.")
    user.fragments -= stake
    uid = str(user.id)
    game = {"id": secrets.token_hex(6), "mode": "pvp", "players": [uid, str(other_uid)],
            "names": [user.data.get("name") or "Challenger", other_name], "stake": stake, "coins": 0, "turn": 0,
            "state": "waiting", "winner": None, "last": [], "at": time.time(), "turn_at": None}
    _save(redis, game)
    return game


def accept(redis, user, gid: str) -> dict:
    game = get(redis, gid)
    if not game or game["state"] != "waiting" or str(user.id) != game["players"][1]:
        raise GameError("That challenge is gone.")
    if time.time() - game["at"] > ACCEPT_SECONDS:
        raise GameError("That challenge expired.")
    why = blocked(redis, user, game["stake"])
    if why and why != "You're already at a table.":
        raise GameError(why)
    user.fragments -= game["stake"]
    game.update(state="playing", turn_at=time.time())
    for uid in game["players"]:
        _count_game(redis, uid)
    _save(redis, game)
    return game


def decline(redis, uid: str, gid: str) -> Optional[dict]:
    """The challenged player says no (or the challenger withdraws): the challenger's stake goes back."""
    game = get(redis, gid)
    if not game or game["state"] != "waiting" or str(uid) not in game["players"]:
        return None
    game["state"] = "declined"
    _save(redis, game)
    return game


def _drop(game: dict, n: int, who: int, rng=random) -> bool:
    """who drops n coins; True if the glass spilled (who loses)."""
    for i in range(n):
        if rng.random() < risk(game["coins"]):
            game["coins"] += 1
            game["last"].append({"who": who, "n": i + 1, "spilled": True})
            game.update(state="over", winner=1 - who)
            return True
        game["coins"] += 1
    game["last"].append({"who": who, "n": n, "spilled": False})
    return False


def play(redis, uid: str, gid: str, n: int, rng=random) -> dict:
    """uid drops n (1 or 2) coins on its turn. Against D'Arby, he answers at once."""
    game = get(redis, gid)
    if not game or game["state"] != "playing":
        raise GameError("This glass is settled.")
    me = game["players"].index(str(uid)) if str(uid) in game["players"] else -1
    if me != game["turn"]:
        raise GameError("Not your turn.")
    if n not in (1, 2):
        raise GameError("One coin or two.")
    game["last"] = []
    if not _drop(game, n, me, rng):
        if game["mode"] == "darby":
            _drop(game, 1 if game["coins"] > 9 or rng.random() < 0.7 else 2, 1, rng)
        else:
            game.update(turn=1 - me, turn_at=time.time())
    _save(redis, game)
    return game


def timeout(redis, game: dict, rng=random) -> dict:
    """PvP: a player who let the clock run out drops one coin (checked whenever either side looks at the table)."""
    if game and game["mode"] == "pvp" and game["state"] == "playing" and game.get("turn_at") \
            and time.time() - game["turn_at"] > TURN_SECONDS:
        game["last"] = []
        if not _drop(game, 1, game["turn"], rng):
            game.update(turn=1 - game["turn"], turn_at=time.time())
        _save(redis, game)
    elif game and game["state"] == "waiting" and time.time() - game["at"] > ACCEPT_SECONDS:
        game["state"] = "expired"
        _save(redis, game)
    return game


def settle(redis, game: dict, users: dict) -> Optional[dict]:
    """Pay out a finished, declined or expired game once. users: {uid: User} (saved by the caller).
    Returns {uid: dust back}."""
    if game["state"] not in ("over", "declined", "expired") or game.get("paid") is not None:
        return None
    if not redis.set(f"web:den:paid:{game['id']}", 1, ex=GAME_TTL, nx=True):
        return None  # never pay twice
    stake, paid = game["stake"], {}
    if game["state"] in ("declined", "expired"):
        paid[game["players"][0]] = stake  # the challenger's stake goes back
    elif game["mode"] == "darby":
        uid = game["players"][0]
        won = game["winner"] == 0
        paid[uid] = 2 * stake if won else 0
        if _result(redis, uid, won, stake, darby=True, user=users.get(uid)):
            game["prize"] = LANTERN_NAME
    else:
        for i, uid in enumerate(game["players"]):
            won = game["winner"] == i
            paid[uid] = 2 * stake if won else 0
            _result(redis, uid, won, stake, darby=False, user=users.get(uid))
    for uid, dust in paid.items():
        if dust and users.get(uid):
            users[uid].fragments += dust
    game["paid"] = paid
    _save(redis, game)
    return paid


def _result(redis, uid: str, won: bool, stake: int, darby: bool, user=None) -> bool:
    """Streaks and limits after a game. True when this win completed a streak and paid the Fog Lantern."""
    key = f"web:den:streak:{uid}"
    if won:
        redis.hset(key, "lose", 0)
        if darby:
            wins = redis.hincrby(key, "win", 1)
            if wins >= CHIP_STREAK and user is not None:
                from app.game import titles
                titles.grant(user, CHIP_TITLE)
            if wins == CHIP_STREAK and user is not None:  # once per streak, however long it runs
                from app.game.items import item_from_dict
                user.items.append(item_from_dict({"id": LANTERN}))
                return True
        return False
    redis.hset(key, "win", 0)
    redis.hincrby(_day(uid), "lost", stake)
    redis.expire(_day(uid), 86400)
    if redis.hincrby(key, "lose", 1) >= COOL_AFTER:
        redis.hset(key, "lose", 0)
        redis.set(f"web:den:cool:{uid}", 1, ex=COOL_OFF)
    return False


def view(redis, game: Optional[dict], uid: str) -> Optional[dict]:
    """The table as the page draws it (from uid's seat)."""
    if not game:
        return None
    me = game["players"].index(str(uid)) if str(uid) in game["players"] else 0
    left = max(0, int(TURN_SECONDS - (time.time() - (game.get("turn_at") or time.time()))))
    return {**game, "me": me, "opp": game["names"][1 - me] if len(game["names"]) > 1 else "D'Arby",
            "my_turn": game["state"] == "playing" and game["turn"] == me, "risk": round(risk(game["coins"]) * 100),
            "tension": "calm" if risk(game["coins"]) < .2 else "trembling" if risk(game["coins"]) < .45 else "about to break",
            "won": game["state"] == "over" and game["winner"] == me, "clock": left,
            "paid_me": (game.get("paid") or {}).get(str(uid), 0)}
