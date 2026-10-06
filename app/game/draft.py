"""Ranked draft: every ranked duel starts with a pick-and-ban.

1. Roster: before queueing, a player picks ROSTER_SIZE different stands from their whole collection (kept in the
   save as data["web_ranked_roster"], a list of stand uuids).
2. Ban (BAN_SECONDS): once matched, both players see each other's roster and each bans BANS of the opponent's.
3. Compose (COMPOSE_SECONDS): each player puts the TEAM_SIZE stands they have left in their fighting order.
4. The duel starts with those teams.

Both phases are simultaneous. A clock that runs out fills in for the player: the missing bans hit the
opponent's strongest stands, and an unordered team keeps its roster order. Whoever looks at the draft after a
deadline applies it (like the duel's turn clock), so nobody can stall.

Redis: web:draft:<id> (JSON, DRAFT_TTL), web:draft:of:<uid> -> draft id.
"""
import json
import time
import uuid as uuidlib
from typing import Callable, Dict, List, Optional

from app.game.logic import GameError

ROSTER_SIZE, BANS, TEAM_SIZE = 5, 2, 3
BAN_SECONDS = COMPOSE_SECONDS = 20
GRACE = 2          # seconds the server waits past a deadline (network lag) before filling in
DRAFT_TTL = 600


def _key(draft_id: str) -> str:
    return f"web:draft:{draft_id}"


def _of(uid: str) -> str:
    return f"web:draft:of:{uid}"


# ── Roster ──────────────────────────────────────────────────────────────

def roster(user) -> List:
    """The player's saved ranked roster (stands still owned, in their order). May be shorter than ROSTER_SIZE
    if stands were released or fused since."""
    out, seen = [], set()
    for stand_uuid in user.data.get("web_ranked_roster") or []:
        char = user.find_character_by_uuid(stand_uuid)[0]
        if char is not None and char.id not in seen:
            out.append(char)
            seen.add(char.id)
    return out


def roster_ready(user) -> bool:
    return len(roster(user)) == ROSTER_SIZE


def set_roster(user, uuids: List[str]) -> List:
    uuids = list(dict.fromkeys(u for u in uuids if u))
    if len(uuids) != ROSTER_SIZE:
        raise GameError(f"Pick exactly {ROSTER_SIZE} stands for your ranked roster.")
    chars = [user.find_character_by_uuid(u)[0] for u in uuids]
    if any(c is None for c in chars):
        raise GameError("One of those stands isn't in your collection any more.")
    if len({c.id for c in chars}) != ROSTER_SIZE:
        raise GameError(f"Your ranked roster needs {ROSTER_SIZE} different stands (no two copies of the same one).")
    user.data["web_ranked_roster"] = uuids
    return chars


# ── The draft ───────────────────────────────────────────────────────────

def create(redis, players: List[str], rosters: Dict[str, List[str]]) -> dict:
    """players: [uid_a, uid_b]; rosters: uid -> the ROSTER_SIZE stand uuids, in roster order."""
    draft = {"id": uuidlib.uuid4().hex, "players": list(players), "rosters": rosters, "phase": "ban",
             "deadline": time.time() + BAN_SECONDS, "bans": {p: None for p in players},
             "order": {p: None for p in players}, "auto": []}
    save(redis, draft)
    for p in players:
        redis.set(_of(p), draft["id"], ex=DRAFT_TTL)
    return draft


def save(redis, draft: dict) -> None:
    redis.set(_key(draft["id"]), json.dumps(draft), ex=DRAFT_TTL)


def of(redis, uid: str) -> Optional[dict]:
    draft_id = redis.get(_of(uid))
    if not draft_id:
        return None
    raw = redis.get(_key(draft_id.decode() if isinstance(draft_id, bytes) else draft_id))
    return json.loads(raw) if raw else None


def finish(redis, draft: dict) -> None:
    redis.delete(_key(draft["id"]))
    for p in draft["players"]:
        redis.delete(_of(p))


def opponent(draft: dict, uid: str) -> str:
    a, b = draft["players"]
    return b if uid == a else a


def banned_from(draft: dict, uid: str) -> List[str]:
    """uid's stands that the opponent banned."""
    return draft["bans"].get(opponent(draft, uid)) or []


def remaining(draft: dict, uid: str) -> List[str]:
    """uid's stand uuids still in play after the opponent's bans, in roster order."""
    gone = set(banned_from(draft, uid))
    return [u for u in draft["rosters"][uid] if u not in gone]


def seconds_left(draft: dict) -> int:
    return max(0, int(round(draft["deadline"] - time.time())))


def ban(draft: dict, uid: str, picks: List[str]) -> None:
    if draft["phase"] != "ban":
        raise GameError("The ban phase is over.")
    if draft["bans"][uid] is not None:
        raise GameError("You already locked in your bans.")
    picks = list(dict.fromkeys(picks))
    if len(picks) != BANS or not set(picks) <= set(draft["rosters"][opponent(draft, uid)]):
        raise GameError(f"Ban exactly {BANS} of your opponent's stands.")
    draft["bans"][uid] = picks


def compose(draft: dict, uid: str, order: List[str]) -> None:
    if draft["phase"] != "compose":
        raise GameError("It isn't time to compose your team.")
    if draft["order"][uid] is not None:
        raise GameError("Your team is already locked in.")
    left = remaining(draft, uid)
    if len(order) != len(left) or sorted(order) != sorted(left):
        raise GameError(f"Put your {len(left)} remaining stands in order, each once.")
    draft["order"][uid] = list(order)


def step(draft: dict, strongest: Callable[[str, List[str]], List[str]], force: bool = False) -> bool:
    """Move the draft on when both players are done, or when the clock ran out (force: ignore the grace).
    strongest(uid, uuids) -> uid's uuids, strongest first (used for bans a player didn't make).
    Returns True if anything changed. The draft is "ready" once both teams are set."""
    changed = False
    late = time.time() >= draft["deadline"] + (0 if force else GRACE)
    if draft["phase"] == "ban" and (all(draft["bans"].values()) or late):
        for p in draft["players"]:
            if draft["bans"][p] is None:  # out of time: the opponent's strongest stands go
                foe = opponent(draft, p)
                draft["bans"][p] = strongest(foe, draft["rosters"][foe])[:BANS]
                draft["auto"].append(f"ban:{p}")
        draft["phase"], draft["deadline"] = "compose", time.time() + COMPOSE_SECONDS
        changed = True
        late = False
    if draft["phase"] == "compose" and (all(draft["order"].values()) or late):
        for p in draft["players"]:
            if draft["order"][p] is None:  # out of time: roster order
                draft["order"][p] = remaining(draft, p)
                draft["auto"].append(f"order:{p}")
        draft["phase"] = "ready"
        changed = True
    return changed
