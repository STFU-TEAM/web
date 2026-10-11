"""The Gang Cup (web only): a monthly knockout tournament between the top gangs.

When a cup opens (the first visit to the cup page in a month without one), the best SEEDS gangs by war Elo that
have members are seeded into a bracket (1 v 8, 4 v 5, 2 v 7, 3 v 6), with byes when fewer qualify. Each round lasts
ROUND_DAYS. During a round every member of a gang still in the cup gets one cup bout a day against the opposing
gang's guardians (the weekly raid crew stands in for a gang without any); the damage dealt counts toward their gang.
The gang with more damage per member goes through (a tie goes to the better seed), like a gang war.

Rounds settle lazily, the first time anyone looks after a round ends. The champion's vault gets PRIZES[0], the
runner-up's PRIZES[1]; every champion member gets the title "Gang Cup Champion · <month>" when they next visit.

Redis:
    web:cup:current            the open (or last) cup id, "YYYY-MM"
    web:cup:<id>               JSON: id, start (date), seeds [{id, name, image, seed}], rounds [[match…]…], champion, done
                               a match: {a, b (gang ids or None for a bye), winner, score_a, score_b}
    web:cup:<id>:dmg:<round>   hash gang id -> damage dealt this round
    web:cup:<id>:bout:<round>:<day>   set of uids who fought that day
    web:cup:champions          list of JSON {cup, gang, name}, newest first
"""
import datetime
import json
from typing import Optional

from app.db import r
from app.game.logic import GameError

SEEDS = 8
ROUND_DAYS = 7
PRIZES = (30_000, 10_000)  # Meteor Dust into the champion's and the runner-up's vaults
ORDER = {8: [1, 8, 4, 5, 2, 7, 3, 6], 4: [1, 4, 2, 3], 2: [1, 2]}
ROUND_NAMES = {8: ["Quarter-finals", "Semi-finals", "Final"], 4: ["Semi-finals", "Final"], 2: ["Final"]}


def _today() -> datetime.date:
    return datetime.datetime.now(datetime.timezone.utc).date()


def _load(cid) -> Optional[dict]:
    raw = r().get(f"web:cup:{cid}")
    return json.loads(raw) if raw else None


def _save(cup: dict):
    r().set(f"web:cup:{cup['id']}", json.dumps(cup))


def round_dates(cup: dict, i: int) -> tuple:
    start = datetime.date.fromisoformat(cup["start"]) + datetime.timedelta(days=ROUND_DAYS * i)
    return start, start + datetime.timedelta(days=ROUND_DAYS)


def current_round(cup: dict) -> Optional[int]:
    """The round being played today (None: the cup is over, or between)."""
    if cup.get("done"):
        return None
    today = _today()
    for i in range(len(cup["rounds"])):
        start, end = round_dates(cup, i)
        if start <= today < end:
            return i
    return None


def open_cup(db) -> Optional[dict]:
    """The cup to show: the current one (settled up to today), or a new one if this month has none yet."""
    cid = r().get("web:cup:current")
    cid = cid.decode() if isinstance(cid, bytes) else cid
    cup = _load(cid) if cid else None
    month = _today().strftime("%Y-%m")
    if cup and not cup.get("done"):
        return settle(db, cup)
    if cup and cup["id"] == month:
        return cup  # this month's cup already finished: show its result
    # a new month: seed a new cup (if two gangs can play), once across workers
    if not r().set(f"web:cup:lock:{month}", "1", nx=True, ex=30):
        return _load(month) or cup
    gangs = [g for g in db.all_gangs() if g.get("_id") and g.get("users")]
    gangs.sort(key=lambda g: (-int(g.get("war_elo", 0)), str(g.get("name", "")).lower()))
    gangs = gangs[:SEEDS]
    if len(gangs) < 2:
        return cup
    size = 2 if len(gangs) <= 2 else 4 if len(gangs) <= 4 else 8
    seeds = [{"id": g["_id"], "name": g.get("name", "?"), "image": g.get("image_url") or "", "seed": i + 1} for i, g in enumerate(gangs)]
    by_seed = {s["seed"]: s["id"] for s in seeds}
    order = ORDER[size]
    first = [{"a": by_seed.get(order[k]), "b": by_seed.get(order[k + 1]), "winner": None, "score_a": 0, "score_b": 0}
             for k in range(0, size, 2)]
    rounds = [first] + [[{"a": None, "b": None, "winner": None, "score_a": 0, "score_b": 0} for _ in range(size // 2 ** (n + 1))]
                        for n in range(1, len(ROUND_NAMES[size]))]
    cup = {"id": month, "start": _today().isoformat(), "size": size, "seeds": seeds, "rounds": rounds,
           "champion": None, "done": False}
    _resolve_byes(cup, 0)
    _save(cup)
    r().set("web:cup:current", month)
    return cup


def _seed_of(cup, gid) -> int:
    return next((s["seed"] for s in cup["seeds"] if s["id"] == gid), 99)


def name_of(cup, gid) -> str:
    return next((s["name"] for s in cup["seeds"] if s["id"] == gid), "?")


def _resolve_byes(cup: dict, i: int):
    for m in cup["rounds"][i]:
        if m["winner"] is None and (m["a"] is None) != (m["b"] is None):
            m["winner"] = m["a"] or m["b"]
    if i + 1 < len(cup["rounds"]):
        _advance(cup, i)


def _advance(cup: dict, i: int):
    """Move every decided winner of round i into its slot in the next round (a bye goes through at once)."""
    nxt = cup["rounds"][i + 1]
    for k, m in enumerate(cup["rounds"][i]):
        if m["winner"]:
            nxt[k // 2]["a" if k % 2 == 0 else "b"] = m["winner"]


def status_of(cup: dict, gid: Optional[str]) -> str:
    """Where a gang stands: "playing" (a match today), "bye" (through without playing), "waiting" (through, the next
    round hasn't started), "out", "champion" or "not_in"."""
    if not gid or gid not in {s["id"] for s in cup["seeds"]}:
        return "not_in"
    if cup.get("done"):
        return "champion" if cup.get("champion") == gid else "out"
    for rnd in cup["rounds"]:
        for m in rnd:
            if m["winner"] and gid in (m["a"], m["b"]) and m["winner"] != gid:
                return "out"
    if match_of(cup, gid):
        return "playing"
    live = current_round(cup)
    if live is not None:
        for m in cup["rounds"][live]:
            if gid in (m["a"], m["b"]) and m["winner"] == gid and not (m["a"] and m["b"]):
                return "bye"
    return "waiting"


def per_member(db, gid: str, damage: int) -> float:
    g = db.get_gang(gid)
    from app.game.gangs import members
    return damage / max(1, len(members(g))) if g else 0.0


def settle(db, cup: dict) -> dict:
    """Close every round whose week is over, in order: winners go through, the final crowns the champion."""
    changed = False
    for i, matches in enumerate(cup["rounds"]):
        if all(m["winner"] for m in matches):
            continue
        if _today() < round_dates(cup, i)[1]:
            break  # this round is still being played
        dmg = _damage(cup["id"], i)
        for m in matches:
            if m["winner"]:
                continue
            if not (m["a"] and m["b"]):
                m["winner"] = m["a"] or m["b"]
                continue
            m["score_a"], m["score_b"] = (round(per_member(db, g, dmg.get(g, 0)), 1) for g in (m["a"], m["b"]))
            if m["score_a"] != m["score_b"]:
                m["winner"] = m["a"] if m["score_a"] > m["score_b"] else m["b"]
            else:  # a tie goes to the better seed
                m["winner"] = min((m["a"], m["b"]), key=lambda g: _seed_of(cup, g))
        if i + 1 < len(cup["rounds"]):
            _advance(cup, i)
            _resolve_byes(cup, i + 1)
        changed = True
    final = cup["rounds"][-1][0]
    if final["winner"] and not cup.get("done"):
        _crown(db, cup, final)
        changed = True
    if changed:
        _save(cup)
    return cup


def _crown(db, cup: dict, final: dict):
    cup.update(done=True, champion=final["winner"])
    runner = final["b"] if final["winner"] == final["a"] else final["a"]
    for gid, prize in ((final["winner"], PRIZES[0]), (runner, PRIZES[1])):
        if not gid:
            continue
        g = db.get_gang(gid)
        if g:
            g["vault"] = int(g.get("vault", 0)) + prize
            db.update_gang(g)
    r().lpush("web:cup:champions", json.dumps({"cup": cup["id"], "gang": final["winner"], "name": name_of(cup, final["winner"])}))
    try:
        from app import social
        g = db.get_gang(final["winner"])
        from app.game.gangs import members
        for m in members(g) if g else []:
            social.notify(str(m), "gang", f"🏆 {g['name']} won the Gang Cup! {PRIZES[0]:,} Meteor Dust went to the vault.", "/gangs/cup")
    except Exception:
        pass


def _damage(cid, i) -> dict:
    raw = r().hgetall(f"web:cup:{cid}:dmg:{i}")
    return {(k.decode() if isinstance(k, bytes) else k): int(v) for k, v in raw.items()}


def scores(db, cup: dict, i: int) -> dict:
    """Live damage per member for the round being played."""
    dmg = _damage(cup["id"], i)
    return {gid: round(per_member(db, gid, d), 1) for gid, d in dmg.items()}


def match_of(cup: dict, gid: str) -> Optional[tuple]:
    """(round, match) the gang plays today, or None."""
    i = current_round(cup)
    if i is None or not gid:
        return None
    for m in cup["rounds"][i]:
        if gid in (m["a"], m["b"]) and m["a"] and m["b"] and not m["winner"]:
            return i, m
    return None


def can_bout(cup: dict, gid: str, uid) -> Optional[str]:
    """None if this player may fight a cup bout now, else why not."""
    found = match_of(cup, gid)
    if not found:
        return "Your gang has no cup match today."
    i, _ = found
    if r().sismember(f"web:cup:{cup['id']}:bout:{i}:{_today().isoformat()}", str(uid)):
        return "You already fought your cup bout today. One a day: come back tomorrow."
    return None


def start_bout(cup: dict, gid: str, uid) -> tuple:
    """Spend today's bout. Returns (round, opponent gang id)."""
    why = can_bout(cup, gid, uid)
    if why:
        raise GameError(why)
    i, m = match_of(cup, gid)
    key = f"web:cup:{cup['id']}:bout:{i}:{_today().isoformat()}"
    r().sadd(key, str(uid))
    r().expire(key, 3 * 86400)
    return i, (m["b"] if m["a"] == gid else m["a"])


def record_damage(cup_id: str, i: int, gid: str, damage: int):
    r().hincrby(f"web:cup:{cup_id}:dmg:{i}", gid, int(damage))


def champions(limit: int = 12) -> list:
    out = []
    for raw in r().lrange("web:cup:champions", 0, limit - 1):
        try:
            out.append(json.loads(raw))
        except ValueError:
            continue
    return out


def titles_of(gid: str) -> int:
    """How many cups a gang has won (the 🏆 count on its pages)."""
    return sum(1 for c in champions(200) if c.get("gang") == gid)


def claim_title(user, cup: dict):
    """A champion member's title, granted on their next visit to the cup page."""
    if cup.get("done") and cup.get("champion") and user and user.gang_id == cup["champion"]:
        from app.game import titles
        month = datetime.date.fromisoformat(cup["id"] + "-01").strftime("%B %Y")
        titles.grant(user, f"Gang Cup Champion · {month}")
