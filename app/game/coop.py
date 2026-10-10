"""Co-op raid: 2-3 players bring one stand each and fight a raid crew together, in real time.

The host opens a lobby (a short code friends can type, or an invite from the friends list), everyone picks a
stand, and the host starts. The fight is one Fight saved under every player's uid (like a duel): side 0 holds
the party's stands and meta["owners"] says who picks for which. A player who lets the clock run out has their
stand pick on its own; nobody loses for someone else's AFK.

The crew is this week's story boss and as many of its henchmen as there are players; the boss leads with
BOSS_HP times the health. The first DAILY_WINS wins of each player's day pay rewards.

Over Heaven (the "heaven" tier, open once a player has finished the story): a maxed crew under this week's
challenge, a fight rule from Over Heaven (app/game/overheaven.py) that raw power can't brute-force and the right
party takes apart. The party has to agree on what to bring. The first Over Heaven win of each week also pays
HEAVEN_WEEKLY, on top of the usual win rewards.

Redis:  web:coop:lobby:<code>  JSON {code, host, tier, open, chat, members: [{uid, name, stand}], at}, expires LOBBY_TTL
        web:coop:of:<uid>      the code of the lobby uid is in
        web:coop:open          zset code -> opened at: open lobbies, listed for anyone to join without the code
        web:coop:chat:<id>     set of the uids in a raid's chat (the lobby's members, then the fight's players)
Save:   data["web_coop"] = {"day", "wins", "used": [stand uuids], "heaven_week": week of the last weekly bonus}:
        a stand raids once a day (marked when the raid starts, win or lose)
"""
import json
import random
import string
import time
from typing import Optional

from app.game import story
from app.game.character import character_from_dict
from app.game.economy import stand_xp
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
               "dust": 600, "xp": 300, "stand_xp": stand_xp(400), "chip": 0.35},
    "hard": {"label": "Hard", "level": 75, "awaken": 1, "quality": "GREAT", "items": 1, "mult": 1.0,
             "dust": 1000, "xp": 450, "stand_xp": stand_xp(700), "chip": 0.55},
    "nightmare": {"label": "Nightmare", "level": 100, "awaken": 3, "quality": "SUPREME", "items": 2, "mult": 1.0,
                  "dust": 1600, "xp": 650, "stand_xp": stand_xp(1000), "chip": 0.8},
    "heaven": {"label": "Over Heaven", "level": 100, "awaken": 5, "quality": "UNIVERSAL", "items": 2, "mult": 1.0,
               "dust": 2400, "xp": 900, "stand_xp": stand_xp(1400), "chip": 1.0, "heaven": True},
}
HEAVEN = "heaven"
# The first Over Heaven win of each ISO week, per player (item ids: Golden Ratio Shard, Rokakaka Fruit)
HEAVEN_WEEKLY = {"super": 1, "items": [38, 39]}
# This week's challenge rotates through these. `power` multiplies the crew's health and damage on top of the tier,
# calibrated with the simulator (scripts/balance.py heaven): a raw LR party mostly loses, a party built for the
# rule mostly wins. "part_ward" with part None takes the part of this week's boss.
CHALLENGES = [
    {"key": "ward", "title": "Heaven's Ward", "power": 0.92, "rules": {"ward": 0.6, "enemy_first": True, "heaven_tax": 0.3},
     "hint": "Stands outside an active synergy deal 60% less, UR and LR stands fight at 70%, and the crew moves first. Agree on a group before "
             "you start: two or three of you bringing members of one crew, family or part lights it for the party."},
    {"key": "morning", "title": "The Endless Morning", "power": 0.77, "rules": {"regen": 0.06, "stun_immune": True, "heaven_tax": 0.3},
     "hint": "The crew heals 6% a turn and can't be stunned, and UR and LR stands fight at 70%. Out-damage the heal "
             "with lower rarities: burst, poison, bleed and burn."},
    {"key": "acceleration", "title": "Accelerating Time", "power": 0.79, "rules": {"enrage": 0.08, "heal_cut": 0.5, "heaven_tax": 0.3},
     "hint": "The crew grows 8% stronger every turn, your healing is halved and UR and LR stands fight at 70%: you "
             "have a handful of turns. Bring hard-hitting SSRs and specials that charge fast."},
    {"key": "mirror", "title": "Requiem's Mirror", "power": 0.63, "rules": {"reflect": 0.35, "heal_cut": 0.5, "heaven_tax": 0.3},
     "hint": "35% of every basic hit comes back to the attacker, healing is halved and UR and LR stands fight at "
             "70%. Let specials and damage over time do the work."},
    {"key": "borrowed", "title": "Borrowed Power", "power": 0.83, "rules": {"heaven_tax": 0.4, "pressure": 0.03},
     "hint": "UR and LR stands fight at 60% and everyone loses 3% a turn. Lower rarities with sustain carry it: "
             "Lifesteal, Second Wind, healers."},
    {"key": "story", "title": "Their Own Story", "power": 0.86, "rules": {"part_ward": [None, 0.5]},
     "hint": "Only stands from the boss's own part hit at full strength. Each of you brings a stand from that part, "
             "and three of them light its synergy."},
]
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


def challenge(week: Optional[str] = None) -> dict:
    """This week's Over Heaven challenge: {key, title, power, rules, hint, lines, part}, with the part filled in."""
    week = week or week_key()
    ch = CHALLENGES[(sum(map(ord, week)) * 7 + 3) % len(CHALLENGES)]
    part = story.STAGES[boss_stage(week)]["part"]
    rules = {k: ([part, v[1]] if k == "part_ward" else v) for k, v in ch["rules"].items()}
    from app.game.overheaven import rule_lines
    hint = ch["hint"].replace("the boss's own part", f"Part {part}").replace("that part", f"Part {part}")
    return {**ch, "rules": rules, "hint": hint, "lines": rule_lines(rules), "part": part}


def unlocked(user, tier: str) -> bool:
    """Over Heaven raids open with the story's end (like Over Heaven itself); the other tiers are always open."""
    if not TIERS.get(tier, {}).get("heaven"):
        return True
    from app.game import overheaven
    from app.game.progression import is_forced
    return user is not None and (overheaven.unlocked(user) or is_forced(user, "coop_heaven"))


def crew(tier: str, party: int, week: Optional[str] = None) -> list:
    t = TIERS[tier]
    ids = story.STAGES[boss_stage(week)]["enemies"][:max(PARTY_MIN, min(PARTY_MAX, party))]
    power = t["mult"] * (challenge(week)["power"] if t.get("heaven") else 1)
    team = []
    for i, cid in enumerate(ids):
        c = character_from_dict({"id": cid, "xp": t["level"] * 100, "awaken": t["awaken"], "types": ["BALANCE"],
                                 "qualities": [t["quality"]], "items": [{"id": 1}] * t["items"]})
        for stat, mult in (("hp", power * (BOSS_HP if i == 0 else 1)), ("damage", power)):
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


OPEN_KEY = "web:coop:open"


def _chat_key(chat_id: str) -> str:
    return f"web:coop:chat:{chat_id}"


def chat_members(chat_id: str) -> list:
    """Who may read and write a raid's chat (chat.resolve)."""
    return [m.decode() if isinstance(m, bytes) else m for m in _r().smembers(_chat_key(chat_id))] if chat_id else []


def _chat_set(chat_id: str, uids):
    if not chat_id:
        return
    pipe = _r().pipeline()
    pipe.delete(_chat_key(chat_id))
    if uids:
        pipe.sadd(_chat_key(chat_id), *[str(u) for u in uids])
        pipe.expire(_chat_key(chat_id), 2 * 86400)
    pipe.execute()


def open_lobbies(limit: int = 20) -> list:
    """Open lobbies with a free seat, newest first (stale entries are dropped as they're met)."""
    out = []
    for code in _r().zrevrange(OPEN_KEY, 0, 100):
        code = code.decode() if isinstance(code, bytes) else code
        lb = lobby(code)
        if not lb or not lb.get("open"):
            _r().zrem(OPEN_KEY, code)
            continue
        if len(lb["members"]) < PARTY_MAX:
            out.append(lb)
        if len(out) >= limit:
            break
    return out


def set_open(uid, on: bool) -> dict:
    lb = lobby_of(uid)
    if not lb or lb["host"] != str(uid):
        raise GameError("Only the host opens or closes the lobby.")
    with _locked(lb["code"]):
        lb = lobby(lb["code"])
        lb["open"] = bool(on)
        _save(lb)
    if on:
        _r().zadd(OPEN_KEY, {lb["code"]: time.time()})
    else:
        _r().zrem(OPEN_KEY, lb["code"])
    return lb


def create(uid, name: str, tier: str, user=None, open_lobby: bool = False) -> dict:
    if tier not in TIERS:
        raise GameError("Pick a difficulty.")
    if not unlocked(user, tier):
        raise GameError("Over Heaven raids open once you finish the story.")
    if lobby_of(uid):
        raise GameError("You're already in a co-op lobby.")
    for _ in range(20):
        code = "".join(random.choices(string.ascii_uppercase.replace("O", "").replace("I", "") + "23456789", k=5))
        if not lobby(code):
            break
    import secrets
    lb = {"code": code, "host": str(uid), "tier": tier, "open": bool(open_lobby), "chat": secrets.token_hex(6),
          "members": [{"uid": str(uid), "name": name, "stand": None}], "at": int(time.time())}
    _save(lb)
    _chat_set(lb["chat"], [uid])
    if open_lobby:
        _r().zadd(OPEN_KEY, {code: time.time()})
    return lb


def join(uid, name: str, code: str, user=None) -> dict:
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
        if not unlocked(user, lb["tier"]):
            raise GameError("That lobby is an Over Heaven raid: it opens once you finish the story.")
        lb["members"].append({"uid": str(uid), "name": name, "stand": None})
        _save(lb)
    _chat_set(lb.get("chat"), [m["uid"] for m in lb["members"]])
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
            _r().zrem(OPEN_KEY, lb["code"])
            _chat_set(lb.get("chat"), [])
            return
        lb["members"] = [m for m in lb["members"] if m["uid"] != str(uid)]
        _save(lb)
        _chat_set(lb.get("chat"), [m["uid"] for m in lb["members"]])


def today(user) -> dict:
    """Today's co-op record for a player: {"day", "wins", "used"} (a fresh one on a new day)."""
    s = user.data.get("web_coop") or {}
    day = now().date().isoformat()
    if s.get("day") != day:
        s = {"day": day, "wins": 0, "used": [], "heaven_week": s.get("heaven_week")}
    s.setdefault("used", [])
    return s


def used_today(user) -> set:
    return set(today(user)["used"])


def mark_used(user, uuid: str):
    s = today(user)
    if uuid not in s["used"]:
        s["used"].append(uuid)
    user.data["web_coop"] = s


def pick(user, uuid: str) -> dict:
    lb = lobby_of(user.id)
    if not lb:
        raise GameError("You're not in a co-op lobby.")
    char, _, _ = user.find_character_by_uuid(uuid)
    if char is None:
        raise GameError("That stand isn't in your collection.")
    if uuid in used_today(user):
        raise GameError(f"{char.name} already raided today. Pick another stand; it can raid again tomorrow.")
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


def set_tier(uid, tier: str, user=None) -> dict:
    lb = lobby_of(uid)
    if not lb or lb["host"] != str(uid):
        raise GameError("Only the host picks the difficulty.")
    if tier not in TIERS:
        raise GameError("Pick a difficulty.")
    if not unlocked(user, tier):
        raise GameError("Over Heaven raids open once you finish the story.")
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
    """The raid started: the lobby goes (its chat carries on with the fight's players)."""
    pipe = _r().pipeline()
    pipe.zrem(OPEN_KEY, lb["code"])
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
    from app.game.items import item_from_dict
    t = TIERS[fight.meta["tier"]]
    won = fight.winner == 0
    week = week_key()
    out = {}
    for uid, user in users.items():
        s = today(user)
        rewards = {"won": won, "fragments": 0, "xp": 0, "stand_xp": 0, "item": None, "capped": False}
        bonus = None
        if won and t.get("heaven") and s.get("heaven_week") != week:  # the weekly Over Heaven bonus, cap or not
            s["heaven_week"] = week
            user.super_fragments += HEAVEN_WEEKLY["super"]
            user.items.extend(item_from_dict({"id": i}) for i in HEAVEN_WEEKLY["items"])
            bonus = f"this week's Over Heaven bonus: {', '.join(weekly_bonus_text())}"
        if won:  # lifetime counters for the Raid Partner / Heaven's Raider titles
            user.data["web_coop_wins"] = int(user.data.get("web_coop_wins", 0)) + 1
            if t.get("heaven"):
                user.data["web_coop_heaven_wins"] = int(user.data.get("web_coop_heaven_wins", 0)) + 1
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
            from app.game import events
            rewards = events.pve_win(user, rewards)  # event tokens, and the Dust rush bonus
        elif won:
            rewards["capped"] = True
            check_achievements(user, "fight_win", 0)  # no reward, but the titles still count the win
        if bonus:
            rewards["item"] = f"{rewards['item']} and {bonus}" if rewards["item"] else bonus
        rewards["wins_left"] = max(0, DAILY_WINS - s["wins"])
        user.data["web_coop"] = s
        out[uid] = rewards
    return out


def wins_left(user) -> int:
    return DAILY_WINS - today(user)["wins"]


def weekly_bonus_text() -> list:
    from app.game.items import item_file
    n = HEAVEN_WEEKLY["super"]
    return ([f"{n} Arrowhead{'s' if n > 1 else ''}"] if n else []) + [item_file[i - 1]["name"] for i in HEAVEN_WEEKLY["items"]]


def weekly_bonus_ready(user) -> bool:
    return today(user).get("heaven_week") != week_key()
