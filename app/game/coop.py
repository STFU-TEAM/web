"""Co-op raid: 2-3 players bring one stand each and fight a raid crew together, in real time.

The host opens a lobby (a short code friends can type, or an invite from the friends list), everyone picks a
stand, and the host starts. The fight is one Fight saved under every player's uid (like a duel): side 0 holds
the party's stands and meta["owners"] says who picks for which. A player who lets the clock run out has their
stand pick on its own; nobody loses for someone else's AFK.

The crew is this week's story boss and as many of its henchmen as there are players; the boss leads with
BOSS_HP times the health. The first DAILY_WINS wins of each player's day pay rewards.

Redis:  web:coop:lobby:<code>  JSON {code, host, tier, members: [{uid, name, stand}], at}, expires LOBBY_TTL
        web:coop:of:<uid>      the code of the lobby uid is in
Save:   data["web_coop"] = {"day", "wins"}
"""
import json
import random
import string
import time
from typing import Optional

from app.game import story
from app.game.character import character_from_dict
from app.game.gangs import week_key
from app.game.logic import GameError, now

PARTY_MIN, PARTY_MAX = 2, 3
LOBBY_TTL = 30 * 60
TURN_SECONDS = 20
REPLAY_ALLOWANCE = 0.8
BOSS_HP = 1.8
DAILY_WINS = 3
# level, stars, quality, items, health/damage multiplier, and what a win pays (dust, player XP, XP for the stand
# brought, chip chance). Measured with the simulator on a mid-game collection (random types and qualities):
# Normal ~90% for a level 55-75 party; Hard ~25% for them, ~65% at level 85-99; Nightmare ~30% for maxed stands.
TIERS = {
    "normal": {"label": "Normal", "level": 45, "awaken": 1, "quality": "GOOD", "items": 0, "mult": 1.0,
               "dust": 600, "xp": 300, "stand_xp": 400, "chip": 0.35},
    "hard": {"label": "Hard", "level": 75, "awaken": 1, "quality": "GREAT", "items": 1, "mult": 1.0,
             "dust": 1000, "xp": 450, "stand_xp": 700, "chip": 0.55},
    "nightmare": {"label": "Nightmare", "level": 100, "awaken": 3, "quality": "SUPREME", "items": 2, "mult": 1.0,
                  "dust": 1600, "xp": 650, "stand_xp": 1000, "chip": 0.8},
}
BOSS_STAGES = [k for k, st in enumerate(story.STAGES) if st.get("boss")]


def _r():
    from app.db import r
    return r()


# ── This week's raid ─────────────────────────────────────────────────────

def boss_stage(week: Optional[str] = None) -> int:
    return BOSS_STAGES[sum(map(ord, week or week_key())) % len(BOSS_STAGES)]


def boss_view(week: Optional[str] = None) -> dict:
    stage = story.STAGES[boss_stage(week)]
    return {"title": stage["title"], "part": stage["part_title"], "lead": stage["enemies"][0], "crew": stage["enemies"]}


def crew(tier: str, party: int, week: Optional[str] = None) -> list:
    t = TIERS[tier]
    ids = story.STAGES[boss_stage(week)]["enemies"][:max(PARTY_MIN, min(PARTY_MAX, party))]
    team = []
    for i, cid in enumerate(ids):
        c = character_from_dict({"id": cid, "xp": t["level"] * 100, "awaken": t["awaken"], "types": ["BALANCE"],
                                 "qualities": [t["quality"]], "items": [{"id": 1}] * t["items"]})
        for stat, mult in (("hp", t["mult"] * (BOSS_HP if i == 0 else 1)), ("damage", t["mult"])):
            value = int(getattr(c, f"start_{stat}") * mult)
            setattr(c, f"start_{stat}", value)
            setattr(c, f"current_{stat}", value)
        team.append(c)
    return team


# ── Lobby ────────────────────────────────────────────────────────────────

def _lobby_key(code: str) -> str:
    return f"web:coop:lobby:{code}"


def _of_key(uid) -> str:
    return f"web:coop:of:{uid}"


def lobby(code: str) -> Optional[dict]:
    raw = _r().get(_lobby_key(code)) if code else None
    return json.loads(raw) if raw else None


def lobby_of(uid) -> Optional[dict]:
    code = _r().get(_of_key(uid))
    code = code.decode() if isinstance(code, bytes) else code
    found = lobby(code)
    if code and not found:
        _r().delete(_of_key(uid))
    if found and not any(m["uid"] == str(uid) for m in found["members"]):
        _r().delete(_of_key(uid))
        return None
    return found


def _save(lb: dict):
    pipe = _r().pipeline()
    pipe.set(_lobby_key(lb["code"]), json.dumps(lb), ex=LOBBY_TTL)
    for m in lb["members"]:
        pipe.set(_of_key(m["uid"]), lb["code"], ex=LOBBY_TTL)
    pipe.execute()


def _locked(code: str):
    """A short lock around one lobby's read-modify-write."""
    from contextlib import contextmanager

    @contextmanager
    def held():
        key = f"web:coop:lock:{code}"
        for _ in range(30):
            if _r().set(key, "1", nx=True, ex=5):
                break
            time.sleep(0.05)
        else:
            raise GameError("The lobby is busy. Try again.")
        try:
            yield
        finally:
            _r().delete(key)
    return held()


def create(uid, name: str, tier: str) -> dict:
    if tier not in TIERS:
        raise GameError("Pick a difficulty.")
    if lobby_of(uid):
        raise GameError("You're already in a co-op lobby.")
    for _ in range(20):
        code = "".join(random.choices(string.ascii_uppercase.replace("O", "").replace("I", "") + "23456789", k=5))
        if not lobby(code):
            break
    lb = {"code": code, "host": str(uid), "tier": tier, "members": [{"uid": str(uid), "name": name, "stand": None}],
          "at": int(time.time())}
    _save(lb)
    return lb


def join(uid, name: str, code: str) -> dict:
    code = (code or "").strip().upper()
    mine = lobby_of(uid)
    if mine and mine["code"] == code:
        return mine
    if mine:
        raise GameError("Leave your current lobby first.")
    with _locked(code):
        lb = lobby(code)
        if not lb:
            raise GameError("No open lobby with that code.")
        if len(lb["members"]) >= PARTY_MAX:
            raise GameError("That lobby is full.")
        lb["members"].append({"uid": str(uid), "name": name, "stand": None})
        _save(lb)
    return lb


def leave(uid):
    lb = lobby_of(uid)
    _r().delete(_of_key(uid))
    if not lb:
        return
    with _locked(lb["code"]):
        lb = lobby(lb["code"])
        if not lb:
            return
        if lb["host"] == str(uid):  # the host leaving closes the lobby
            for m in lb["members"]:
                _r().delete(_of_key(m["uid"]))
            _r().delete(_lobby_key(lb["code"]))
            return
        lb["members"] = [m for m in lb["members"] if m["uid"] != str(uid)]
        _save(lb)


def pick(user, uuid: str) -> dict:
    lb = lobby_of(user.id)
    if not lb:
        raise GameError("You're not in a co-op lobby.")
    char, _, _ = user.find_character_by_uuid(uuid)
    if char is None:
        raise GameError("That stand isn't in your collection.")
    with _locked(lb["code"]):
        lb = lobby(lb["code"])
        for m in lb["members"]:
            if m["uid"] == str(user.id):
                m["stand"] = uuid
                m["stand_id"] = char.id
                m["stand_name"] = char.name
                m["stand_level"] = char.level
        _save(lb)
    return lb


def set_tier(uid, tier: str) -> dict:
    lb = lobby_of(uid)
    if not lb or lb["host"] != str(uid):
        raise GameError("Only the host picks the difficulty.")
    if tier not in TIERS:
        raise GameError("Pick a difficulty.")
    with _locked(lb["code"]):
        lb = lobby(lb["code"])
        lb["tier"] = tier
        _save(lb)
    return lb


def check_start(uid) -> dict:
    lb = lobby_of(uid)
    if not lb or lb["host"] != str(uid):
        raise GameError("Only the host can start the raid.")
    if len(lb["members"]) < PARTY_MIN:
        raise GameError(f"A raid needs {PARTY_MIN} to {PARTY_MAX} players.")
    waiting = [m["name"] for m in lb["members"] if not m.get("stand")]
    if waiting:
        raise GameError(f"Waiting for {', '.join(waiting)} to pick a stand.")
    return lb


def close(lb: dict):
    pipe = _r().pipeline()
    pipe.delete(_lobby_key(lb["code"]))
    for m in lb["members"]:
        pipe.delete(_of_key(m["uid"]))
    pipe.execute()


# ── The fight ────────────────────────────────────────────────────────────

def owner(fight) -> Optional[str]:
    """Who picks for the stand that acts now (None on the crew's turn)."""
    owners = fight.meta.get("owners") or []
    if fight.finished or not fight.awaiting_input or fight.si >= len(owners):
        return None
    return owners[fight.si]


def arm_timer(fight):
    if fight.finished or not fight.awaiting_input:
        return
    key = [fight.turn, fight.si]
    if fight.meta.get("timer_for") == key:
        return
    replay = min(8.0, REPLAY_ALLOWANCE * (len(fight.log) - fight.meta.get("timer_log", 0)))
    fight.meta.update(timer_for=key, timer_log=len(fight.log), deadline=time.time() + TURN_SECONDS + replay)


def enforce_timer(fight) -> bool:
    """The picking player ran out of time: their stand picks on its own (smart AI)."""
    from app.game.fight import ai_choice
    if fight.finished or not fight.awaiting_input:
        return False
    deadline = fight.meta.get("deadline")
    if deadline is None or time.time() < deadline:
        return False
    who = fight.meta.get("names", {}).get(owner(fight) or "", "Someone")
    fight._log(f"⏱️ {who} took too long: {fight.acting_char.name} picks a target on its own.", "info", side=0)
    fight.advance(ai_choice(fight.sides[1].chars, fight.acting_char))
    arm_timer(fight)
    return True


def turn_left(fight) -> Optional[int]:
    if fight.finished or not fight.awaiting_input or "deadline" not in fight.meta:
        return None
    return max(0, int(round(fight.meta["deadline"] - time.time())))


def settle(fight, users: dict) -> dict:
    """Pay each player (their first DAILY_WINS wins of the day). users: {uid: User}. Returns {uid: rewards}."""
    from app.game import chips
    from app.game.economy import dust
    from app.game.logic import check_achievements, track_quest_progress, train
    t = TIERS[fight.meta["tier"]]
    won = fight.winner == 0
    day = now().date().isoformat()
    out = {}
    for uid, user in users.items():
        s = user.data.get("web_coop") or {}
        if s.get("day") != day:
            s = {"day": day, "wins": 0}
        rewards = {"won": won, "fragments": 0, "xp": 0, "stand_xp": 0, "item": None, "capped": False}
        if won and s["wins"] < DAILY_WINS:
            s["wins"] += 1
            stand, _, _ = user.find_character_by_uuid(fight.meta["stands"].get(uid, ""))
            rewards.update(fragments=dust(t["dust"]), xp=t["xp"])
            user.fragments += rewards["fragments"]
            user.xp += t["xp"]
            if stand is not None:
                rewards["stand_xp"] = train(stand, t["stand_xp"])
                if random.random() < t["chip"]:
                    chip = chips.grant(user, prefer=[stand])
                    if chip:
                        rewards["item"] = f"a {chips.view(chip)['label']} chip ({chip['tier']})"
            track_quest_progress(user, "fight_win")
            check_achievements(user, "fight_win")
        elif won:
            rewards["capped"] = True
        rewards["wins_left"] = max(0, DAILY_WINS - s["wins"])
        user.data["web_coop"] = s
        out[uid] = rewards
    return out


def wins_left(user) -> int:
    s = user.data.get("web_coop") or {}
    return DAILY_WINS - (s.get("wins", 0) if s.get("day") == now().date().isoformat() else 0)
