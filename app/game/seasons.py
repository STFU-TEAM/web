"""Ranked seasons: one calendar month each, on top of the bot's lifetime Elo.

global_elo is shared with the bot and never resets. A season keeps its own rating (web-only), which
starts from a soft reset: half of the player's rating at the end of the last season they played
(their first season starts from half their lifetime Elo). Ranked wins and losses move both numbers
by the same amount. Once a season is over, every player who played at least MIN_GAMES ranked duels
claims a reward by the tier they finished in, plus a title for the profile.

Redis:
  web:season:<sid>:rating   zset uid -> season rating
  web:season:<sid>:games    hash uid -> ranked duels played
  web:season:<sid>:wins     hash uid -> ranked duels won
Save: data["web_season_claimed"] = [sid, ...], titles go to data["web_titles"] (see titles()).
"""
import datetime
from typing import List, Optional

from app.game.logic import RANK_TIERS, fmt_delta, now, rank_name

MIN_GAMES = 5
WIN, LOSS = 25, 20  # same as the lifetime Elo
# What the final tier of a season pays (fragments = Meteor Dust, super = Arrowheads)
REWARDS = {
    "ACT 1": {"fragments": 500},
    "ACT 2": {"fragments": 1000},
    "ACT 3": {"fragments": 2000, "super": 1},
    "ACT 4": {"fragments": 3000, "super": 2},
    "Requiem": {"fragments": 4500, "super": 3},
    "Love Train": {"fragments": 6000, "super": 4},
    "Over Heaven": {"fragments": 8000, "super": 5},
}
TIER_ICONS = {"ACT 1": "Ⅰ", "ACT 2": "Ⅱ", "ACT 3": "Ⅲ", "ACT 4": "Ⅳ", "Requiem": "🏹", "Love Train": "🚂",
              "Over Heaven": "☀"}
# Titles are only given for these tiers and up (an ACT 1 title is not much of a flex)
TITLE_FROM = "ACT 3"


def season_id(when: Optional[datetime.datetime] = None) -> str:
    return (when or now()).strftime("%Y-%m")


def previous_id(sid: str) -> str:
    year, month = map(int, sid.split("-"))
    return f"{year - 1}-12" if month == 1 else f"{year}-{month - 1:02d}"


def label(sid: str) -> str:
    year, month = map(int, sid.split("-"))
    return datetime.date(year, month, 1).strftime("%B %Y")


def ends_at(sid: Optional[str] = None) -> datetime.datetime:
    year, month = map(int, (sid or season_id()).split("-"))
    return datetime.datetime(year + (month == 12), month % 12 + 1, 1)


def _key(sid: str, what: str) -> str:
    return f"web:season:{sid}:{what}"


def _uid(raw) -> str:
    return raw.decode() if isinstance(raw, bytes) else str(raw)


def start_rating(redis, uid: str, sid: str, lifetime_elo: int) -> int:
    """Soft reset: half the last season played (looking back a year), else half the lifetime Elo."""
    back = sid
    for _ in range(12):
        back = previous_id(back)
        score = redis.zscore(_key(back, "rating"), uid)
        if score is not None:
            return int(score) // 2
    return max(0, int(lifetime_elo or 0)) // 2


def rating(redis, uid: str, lifetime_elo: int = 0, sid: Optional[str] = None) -> int:
    sid = sid or season_id()
    score = redis.zscore(_key(sid, "rating"), uid)
    return int(score) if score is not None else start_rating(redis, uid, sid, lifetime_elo)


def record(redis, players: List[str], winner: Optional[str], elos: dict, sid: Optional[str] = None) -> List[str]:
    """A finished ranked duel. elos: {uid: lifetime Elo} for the soft-reset seed. A draw (winner None) counts as
    played. Returns the players who just qualified for this season's reward (their MIN_GAMES-th duel)."""
    sid = sid or season_id()
    qualified = [uid for uid in players if int(redis.hget(_key(sid, "games"), uid) or 0) == MIN_GAMES - 1]
    pipe = redis.pipeline()
    for uid in players:
        current = rating(redis, uid, elos.get(uid, 0), sid)
        delta = 0 if winner is None else (WIN if uid == winner else -LOSS)
        pipe.zadd(_key(sid, "rating"), {uid: max(0, current + delta)})
        pipe.hincrby(_key(sid, "games"), uid, 1)
        if winner is not None and uid == winner:
            pipe.hincrby(_key(sid, "wins"), uid, 1)
    for what in ("rating", "games", "wins"):
        pipe.expire(_key(sid, what), 400 * 86400)
    pipe.execute()
    return qualified


def seconds_left(sid: Optional[str] = None) -> float:
    return max(0.0, (ends_at(sid) - now()).total_seconds())


def standing(redis, uid: str, lifetime_elo: int = 0, sid: Optional[str] = None) -> dict:
    sid = sid or season_id()
    r = rating(redis, uid, lifetime_elo, sid)
    games = int(redis.hget(_key(sid, "games"), uid) or 0)
    wins = int(redis.hget(_key(sid, "wins"), uid) or 0)
    place = redis.zrevrank(_key(sid, "rating"), uid)
    tier = rank_name(r)
    nxt = next(((t, n) for t, n in reversed(RANK_TIERS) if t > r), None)
    return {"sid": sid, "label": label(sid), "rating": r, "tier": tier, "icon": TIER_ICONS.get(tier, ""),
            "games": games, "wins": wins, "losses": games - wins, "place": place + 1 if place is not None else None,
            "qualified": games >= MIN_GAMES, "next_tier": nxt[1] if nxt else None,
            "to_next": nxt[0] - r if nxt else None, "ends": ends_at(sid),
            "ends_in": fmt_delta(ends_at(sid) - now())}


def board(redis, sid: Optional[str] = None, limit: int = 50) -> List[dict]:
    sid = sid or season_id()
    rows = redis.zrevrange(_key(sid, "rating"), 0, limit - 1, withscores=True)
    games = redis.hgetall(_key(sid, "games"))
    games = {_uid(k): int(v) for k, v in games.items()}
    return [{"id": _uid(u), "value": int(s), "games": games.get(_uid(u), 0)} for u, s in rows]


def unclaimed(redis, user, lookback: int = 6) -> List[dict]:
    """Past seasons this player qualified for and hasn't claimed yet (newest first)."""
    claimed = set(user.data.get("web_season_claimed") or [])
    out, sid = [], season_id()
    for _ in range(lookback):
        sid = previous_id(sid)
        if sid in claimed:
            continue
        if int(redis.hget(_key(sid, "games"), user.id) or 0) < MIN_GAMES:
            continue
        final = int(redis.zscore(_key(sid, "rating"), user.id) or 0)
        tier = rank_name(final)
        out.append({"sid": sid, "label": label(sid), "rating": final, "tier": tier, "reward": REWARDS[tier],
                    "title": title_for(sid, tier)})
    return out


def title_for(sid: str, tier: str) -> Optional[str]:
    order = [name for _, name in reversed(RANK_TIERS)]
    if order.index(tier) < order.index(TITLE_FROM):
        return None
    return f"{tier} · {label(sid)}"


def claim(redis, user) -> List[dict]:
    """Pay every finished season waiting. The caller holds the save lock and saves."""
    from app.game import titles
    from app.game.logic import GameError
    todo = unclaimed(redis, user)
    if not todo:
        raise GameError("No season reward is waiting.")
    claimed = list(user.data.get("web_season_claimed") or [])
    for s in todo:
        user.fragments += s["reward"].get("fragments", 0)
        user.super_fragments += s["reward"].get("super", 0)
        if s["title"]:
            titles.grant(user, s["title"])
        claimed.append(s["sid"])
    user.data["web_season_claimed"] = claimed[-24:]
    return todo


def reward_text(reward: dict) -> str:
    parts = [f"{reward['fragments']:,} Meteor Dust"] if reward.get("fragments") else []
    if reward.get("super"):
        parts.append(f"{reward['super']} Arrowhead{'s' if reward['super'] > 1 else ''}")
    return " + ".join(parts)


def reward_table() -> List[dict]:
    return [{"tier": name, "from": t, "icon": TIER_ICONS.get(name, ""), "reward": reward_text(REWARDS[name]),
             "title": name if t >= dict((n, v) for v, n in RANK_TIERS)[TITLE_FROM] else None}
            for t, name in reversed(RANK_TIERS)]
