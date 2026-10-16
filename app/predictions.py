"""Ranked predictions: spectators of a live ranked duel back a side with a little Meteor Dust before round CLOSE_ROUND.
The winners split the whole pool by their stakes. A draw, a duel that ends with nobody on the winning side, or one that
disappears without finishing (battles._live_fight drops it: refund()) refunds everyone. The two duelists can't predict
their own duel.

    web:pred:<fight_id>            hash uid -> JSON {side, stake}
    web:pred:<fight_id>:pool       hash side -> dust staked on it
    web:pred:<fight_id>:done       JSON {winner, paid: {uid: dust}} once settled
    web:pred:day:<uid>:<date>      dust staked today
    web:pred:streak:<uid>          hash n (right calls in a row), best
"""
import datetime
import json
from typing import Optional

from app.game.logic import GameError

CLOSE_ROUND = 3
STAKES = (50, 100, 250, 500)
PER_DAY = 2000
ORACLE = 10           # right calls in a row for the title
ORACLE_TITLE = "Oracle"
KEEP = 2 * 86400


def _k(fight_id: str, part: str = "") -> str:
    return f"web:pred:{fight_id}{':' + part if part else ''}"


def _s(v):
    return v.decode() if isinstance(v, bytes) else v


def _day_key(uid) -> str:
    return f"web:pred:day:{uid}:{datetime.date.today().isoformat()}"


def pools(redis, fight_id: str) -> list:
    raw = {_s(k): int(v) for k, v in redis.hgetall(_k(fight_id, "pool")).items()}
    return [raw.get("0", 0), raw.get("1", 0)]


def mine(redis, fight_id: str, uid) -> Optional[dict]:
    raw = redis.hget(_k(fight_id), str(uid))
    return json.loads(raw) if raw else None


def is_open(fight) -> bool:
    return fight.kind == "ranked" and not fight.finished and fight.round < CLOSE_ROUND and len(fight.meta.get("players", [])) == 2


def place(redis, user, fight, side: int, stake: int) -> dict:
    """Back side with stake (taken from user's dust now). Raises GameError with the reason it can't."""
    uid = str(user.id)
    if not is_open(fight):
        raise GameError(f"Predictions close at round {CLOSE_ROUND}.")
    if uid in [str(p) for p in fight.meta.get("players", [])]:
        raise GameError("You can't predict your own duel.")
    if side not in (0, 1) or stake not in STAKES:
        raise GameError("Pick a side and a stake.")
    if mine(redis, fight.id, uid):
        raise GameError("You already made your call on this duel.")
    today = int(redis.get(_day_key(uid)) or 0)
    if today + stake > PER_DAY:
        raise GameError(f"You can stake {PER_DAY:,} dust a day on predictions; {max(0, PER_DAY - today):,} left today.")
    if user.fragments < stake:
        raise GameError("Not enough Meteor Dust.")
    user.fragments -= stake
    redis.hset(_k(fight.id), uid, json.dumps({"side": side, "stake": stake}))
    redis.hincrby(_k(fight.id, "pool"), str(side), stake)
    redis.incrby(_day_key(uid), stake)
    for key in (_k(fight.id), _k(fight.id, "pool")):
        redis.expire(key, KEEP)
    redis.expire(_day_key(uid), 86400)
    return {"side": side, "stake": stake}


def payouts(bets: dict, winner: Optional[int]) -> dict:
    """{uid: dust back}: winners split the pool by stake (rounded down); with no winner, or nobody on the winning
    side, everyone gets their stake back."""
    total = sum(b["stake"] for b in bets.values())
    backers = {u: b for u, b in bets.items() if b["side"] == winner}
    won = sum(b["stake"] for b in backers.values())
    if winner is None or not won:
        return {u: b["stake"] for u, b in bets.items()}
    return {u: b["stake"] * total // won for u, b in backers.items()}


def settle(redis, fight) -> Optional[dict]:
    """Pay out once the duel is over (battles._settle). Returns {winner, paid} (also kept for the spectators' panel)."""
    if fight.kind != "ranked":
        return None
    return _pay(redis, fight.id, fight.winner)


def refund(redis, fight_id: str) -> Optional[dict]:
    """The duel is gone without an end: every stake goes back."""
    return _pay(redis, fight_id, None)


def _pay(redis, fight_id: str, winner: Optional[int]) -> Optional[dict]:
    bets = {_s(u): json.loads(v) for u, v in redis.hgetall(_k(fight_id)).items()}
    paid = payouts(bets, winner)
    result = {"winner": winner, "paid": paid}
    if not redis.set(_k(fight_id, "done"), json.dumps(result), ex=KEEP, nx=True):
        return None  # already settled: never pay twice
    if not bets:
        return result
    from app.db import get_db, user_lock
    from app.game import titles
    for uid, bet in bets.items():
        right = winner is not None and bet["side"] == winner
        streak = _streak(redis, uid, right) if winner is not None else None
        try:
            with user_lock(uid, ttl=5):
                user = get_db().get_user(uid)
                if not user:
                    continue
                user.fragments += paid.get(uid, 0)
                if streak and streak >= ORACLE:
                    titles.grant(user, ORACLE_TITLE)
                user.update()
        except Exception:  # a busy save: the stake stays on record in the done key for an admin to check
            continue
    return result


def _streak(redis, uid, right: bool) -> int:
    key = f"web:pred:streak:{uid}"
    if not right:
        redis.hset(key, "n", 0)
        return 0
    n = redis.hincrby(key, "n", 1)
    if n > int(redis.hget(key, "best") or 0):
        redis.hset(key, "best", n)
    return n


def streak(redis, uid) -> int:
    return int(redis.hget(f"web:pred:streak:{uid}", "n") or 0)


def view(redis, fight, uid) -> dict:
    """Everything the spectators' panel shows."""
    pool = pools(redis, fight.id)
    total = sum(pool)
    my = mine(redis, fight.id, uid) if uid else None
    done_raw = redis.get(_k(fight.id, "done"))
    done = json.loads(done_raw) if done_raw else None
    today = int(redis.get(_day_key(uid)) or 0) if uid else 0
    duelist = str(uid) in [str(p) for p in fight.meta.get("players", [])]

    def mult(side, extra=0):
        return round((total + extra) / max(1, pool[side] + extra), 2) if total + extra else 2.0
    return {
        "open": is_open(fight) and not duelist and not my, "closed": not is_open(fight), "duelist": duelist,
        "names": [fight.sides[0].name, fight.sides[1].name], "pool": pool, "total": total,
        "share": [round(100 * p / total) if total else 50 for p in pool],
        "mult": [mult(0, 100), mult(1, 100)] if not my else [mult(0), mult(1)],
        "mine": my, "stakes": STAKES, "left": max(0, PER_DAY - today), "close_round": CLOSE_ROUND,
        "backers": redis.hlen(_k(fight.id)), "done": done,
        "paid": (done or {}).get("paid", {}).get(str(uid), 0) if done and my else 0,
        "streak": streak(redis, uid) if uid else 0, "oracle": ORACLE,
    }
