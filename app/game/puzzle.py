"""Puzzles (web only): pick 3 of 6 stands, hand out a few items, beat a fixed crew under Over Heaven's rules.

Two modes share one library of checked puzzles:
    the daily puzzle     one a day, the same for everyone, a ladder for the fastest solve
    personal puzzles     your own path through the library, one after another, at your pace

Each puzzle brings 6 stands (semi-random: a synergy pair or trio as the hook, the rest from the whole roster), a pool
of items, a fixed enemy crew and one or two Over Heaven rules (app/game/overheaven.py). Every stand fights at level
100, ★3, Supreme, with the type that powers its special, so a puzzle is the same for a new player and a veteran.

Before a puzzle enters the library it is checked with the team simulator: all 20 teams of 3 are played with a few
item layouts each, the crew's strength is tuned so the best answer wins about TARGET of the time, and the puzzle is
rerolled unless that best answer is reliable AND only a handful of teams work (a puzzle, not a stat check).

Generation never runs in a request: a background task (start_generator, one per worker, one at a time across them)
builds one puzzle every GEN_EVERY seconds, first topping up the queue of upcoming daily puzzles, then growing the
personal library up to LIBRARY_MAX. The load is a fixed rate, whatever the number of players. The two pools never
overlap, so nobody has met the daily puzzle before.

The clock starts when you reveal a puzzle (not when you open the page) and stops on your first win.

Redis:
    web:puzzle:lib:seq           last puzzle id
    web:puzzle:lib               hash id -> JSON spec (stands, items, enemies, rules, mult, solution, checked)
    web:puzzle:queue:daily       list of ids waiting to be a day's puzzle (DAILY_BUFFER ahead)
    web:puzzle:queue:personal    list of ids, the personal library in order (append only)
    web:puzzle:gen:lock          held while a worker generates
    web:puzzle:gen:beat          the task's last heartbeat (unix time): the admin page shows if it's alive
    web:puzzle:log               list of JSON entries, newest first (LOG_KEEP): built, daily picked, errors
    web:puzzle:<day>             the day's spec (a library puzzle with its day), and per day, kept KEEP_DAYS:
    web:puzzle:start:<day>       hash uid -> reveal time
    web:puzzle:tries:<day>       hash uid -> fights started
    web:puzzle:ladder:<day>      zset uid -> seconds to solve (first win only)
    web:puzzle:me:<uid>          hash: idx (place in the personal library), started, tries, solved, skipped,
                                 paid_day, paid (rewarded solves that day)
    web:puzzle:best:<uid>        hash puzzle id -> seconds (personal solves)
    web:puzzle:solvers           zset uid -> personal puzzles solved (the "most solved" board)
"""
import datetime
import itertools
import json
import random
import time
from typing import List, Optional

from app.db import r
from app.game.character import CHARACTER_FILE, character_from_dict
from app.game.logic import GameError

STANDS, PICK, ITEMS, MAX_ITEMS = 6, 3, 4, 3
LEVEL, AWAKEN, QUALITY = 100, 3, "SUPREME"
TARGET = 0.7          # the best answer's win rate once tuned
MIN_BEST = 0.55       # ...and at least this when every team is checked
MAX_GOOD = 5          # at most this many of the 20 teams may win half the time or more
TRIES = 14            # rerolls before taking the closest candidate
KEEP_DAYS = 8
LADDER_SIZE = 20
REWARD = {"fragments": 1500, "xp": 600}  # the first solve of the day's puzzle
PERSONAL_REWARD = {"fragments": 500, "xp": 200}
PERSONAL_PAID = 5      # personal solves rewarded a day (the library is long; the rest are for fun and the board)
GEN_EVERY = 180        # seconds between two generated puzzles
DAILY_BUFFER = 14      # daily puzzles kept ready ahead
LIBRARY_MAX = 3000     # the personal library stops growing here

POOL = [c["id"] for c in CHARACTER_FILE if c["rarity"] in ("SR", "SSR", "UR") and c["universe"] != "Dummy"]
# the crews: every story boss stage's villains, plus the Alternate Universe finales
def _crews() -> List[List[int]]:
    from app.game import altverse, story
    crews = [s["enemies"] for s in story.STAGES if s.get("boss") and len(s["enemies"]) >= 2]
    crews += [c["stages"][-1]["enemies"] for c in altverse.CHAPTERS]
    return [[i for i in crew if i != 110][:3] for crew in crews if len([i for i in crew if i != 110]) >= 2]


RULES = [  # (rule, value) the puzzle draws one or two from
    ("enemy_first", True), ("ward", 0.3), ("regen", 0.04), ("enrage", 0.06), ("reflect", 0.25), ("heal_cut", 0.5),
    ("stun_immune", True), ("purge", True), ("heaven_tax", 0.3), ("pressure", 0.02),
    ("terrain", "OCEAN"), ("terrain", "DESERT"), ("terrain", "FROZEN"), ("terrain", "MIRROR"), ("terrain", "NATURE"),
]


def today() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")


def yesterday() -> str:
    return (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=1)).strftime("%Y-%m-%d")


def seconds_left() -> int:
    now = datetime.datetime.now(datetime.timezone.utc)
    return int((datetime.datetime.combine(now.date() + datetime.timedelta(days=1), datetime.time(), tzinfo=datetime.timezone.utc) - now).total_seconds())


def _items_pool() -> List[int]:
    from app.game.pickers import items
    return sorted(o["id"] for o in items())


# ── Building the fighters ───────────────────────────────────────────────

def stand(cid: int, items=()):
    from app.game.planner import best_type
    return character_from_dict({"id": cid, "xp": LEVEL * 100, "awaken": AWAKEN, "types": [best_type(cid)],
                                "qualities": [QUALITY], "items": [{"id": i} for i in items]})


def crew(spec: dict) -> list:
    team = []
    for cid in spec["enemies"]:
        c = character_from_dict({"id": cid, "xp": LEVEL * 100, "awaken": AWAKEN, "types": ["BALANCE"],
                                 "qualities": [QUALITY], "items": [{"id": 1}] * 2})
        for stat in ("hp", "damage"):
            value = int(getattr(c, f"start_{stat}") * spec["mult"])
            setattr(c, f"start_{stat}", value)
            setattr(c, f"current_{stat}", value)
        team.append(c)
    return team


def team_for(spec: dict, picks: List[int], gear: dict) -> list:
    """picks: 3 stand slots (0-5); gear: {item slot: stand slot}."""
    return [stand(spec["stands"][p], [spec["items"][k] for k, s in sorted(gear.items()) if s == p]) for p in picks]


# ── Generating and checking ─────────────────────────────────────────────

def _roll(rng: random.Random) -> dict:
    from app.game.characterabilities import SYNERGIES
    groups = [sorted(set(m) & set(POOL)) for m in SYNERGIES.values()]
    hook = rng.choice([g for g in groups if len(g) >= 2])
    stands = rng.sample(hook, min(len(hook), rng.choice((2, 3))))
    while len(stands) < STANDS:
        cid = rng.choice(POOL)
        if cid not in stands:
            stands.append(cid)
    rng.shuffle(stands)
    rules = dict(rng.sample(RULES, rng.choice((1, 2, 2))))
    return {"stands": stands, "items": rng.sample(_items_pool(), ITEMS), "enemies": rng.choice(_crews()),
            "rules": rules, "mult": 1.0}


def _layouts(picks) -> List[dict]:
    """A few ways to hand out the items: spread one way, spread the other, stacked on the first."""
    spread = {k: picks[k % PICK] for k in range(ITEMS)}
    back = {k: picks[(PICK - 1) - k % PICK] for k in range(ITEMS)}
    stacked = {k: picks[0] if k < MAX_ITEMS else picks[1] for k in range(ITEMS)}
    return [spread, back, stacked]


def _rate(spec, picks, gear, runs) -> float:
    from app.game import simulate
    foe = {"name": "Puzzle", "team": crew(spec), "ai": "smart", "rules": spec["rules"] or None}
    return simulate.run(team_for(spec, picks, gear), foe, runs)["rate"] / 100


def _survey(spec, runs) -> list:
    """[(rate, picks, gear)] for every team of 3, each with its best item layout, best first."""
    out = []
    for picks in itertools.combinations(range(STANDS), PICK):
        out.append(max(((_rate(spec, list(picks), g, runs), list(picks), g) for g in _layouts(picks)),
                       key=lambda x: x[0]))
    return sorted(out, key=lambda x: -x[0])


def _tune(spec, picks, gear, runs=16) -> float:
    lo, hi = 0.2, 5.0
    for _ in range(8):
        spec["mult"] = (lo + hi) / 2
        lo, hi = (spec["mult"], hi) if _rate(spec, picks, gear, runs) >= TARGET else (lo, spec["mult"])
    spec["mult"] = round(lo, 3)
    return spec["mult"]


def generate(seed: str) -> dict:
    """A puzzle drawn from `seed`, checked with the simulator (about 10 s of CPU)."""
    best_seen = None
    checked = 0
    for attempt in range(TRIES):
        rng = random.Random(f"puzzle:{seed}:{attempt}")
        spec = _roll(rng)
        first = _survey(spec, 4)                       # who looks strongest at even strength
        checked += 20 * 3 * 4
        _, picks, gear = first[0]
        _tune(spec, picks, gear)                       # make the crew match that answer
        checked += 8 * 16
        survey = _survey(spec, 10)                     # then check every team at that strength
        checked += 20 * 3 * 10
        best, good = survey[0][0], sum(1 for x in survey if x[0] >= 0.5)
        spec.update(seed=seed, attempt=attempt, checked=checked,
                    solution={"picks": survey[0][1], "gear": {str(k): v for k, v in survey[0][2].items()},
                              "rate": round(best, 2)},
                    good=good)
        if best >= MIN_BEST and 1 <= good <= MAX_GOOD:
            return spec
        score = (best >= MIN_BEST, -abs(good - 3))
        if best_seen is None or score > best_seen[0]:
            best_seen = (score, dict(spec))
    return best_seen[1]


LIB, SEQ = "web:puzzle:lib", "web:puzzle:lib:seq"
DAILY_Q, PERSONAL_Q = "web:puzzle:queue:daily", "web:puzzle:queue:personal"


LOG_KEY, LOG_KEEP, BEAT_KEY = "web:puzzle:log", 300, "web:puzzle:gen:beat"


def log(kind: str, **fields):
    """One line in the puzzle task's log (the admin Puzzles tab). kind: built, daily, empty, full, error."""
    try:
        pipe = r().pipeline()
        pipe.lpush(LOG_KEY, json.dumps({"at": int(time.time()), "kind": kind, **fields}))
        pipe.ltrim(LOG_KEY, 0, LOG_KEEP - 1)
        pipe.execute()
    except Exception:  # the log never breaks the task
        pass


def read_log(limit: int = LOG_KEEP) -> list:
    out = []
    for raw in r().lrange(LOG_KEY, 0, limit - 1):
        try:
            out.append(json.loads(raw))
        except ValueError:
            continue
    return out


def status() -> dict:
    """For the admin page: the stock, the task's heartbeat, whether a build is running right now."""
    beat = r().get(BEAT_KEY)
    beat = int(beat) if beat else None
    return {**stock(), "beat": beat, "alive": bool(beat and time.time() - beat < GEN_EVERY * 2 + 60),
            "building": bool(r().exists("web:puzzle:gen:lock")), "every": GEN_EVERY,
            "daily_buffer": DAILY_BUFFER, "library_max": LIBRARY_MAX}


def from_library(pid) -> Optional[dict]:
    raw = r().hget(LIB, str(pid))
    return json.loads(raw) if raw else None


def stock() -> dict:
    return {"daily": r().llen(DAILY_Q), "personal": r().llen(PERSONAL_Q), "total": int(r().get(SEQ) or 0)}


def generate_one() -> Optional[str]:
    """One step of the task: build a puzzle where it's needed most. Returns the pool it went to, or None."""
    need = "daily" if r().llen(DAILY_Q) < DAILY_BUFFER else "personal" if r().llen(PERSONAL_Q) < LIBRARY_MAX else None
    if not need:
        return None
    pid = int(r().incr(SEQ))
    started_at = time.time()
    spec = generate(f"lib:{pid}")
    spec["id"] = pid
    sol = spec.get("solution") or {}
    log("built", id=pid, pool=need, seconds=round(time.time() - started_at, 1), attempt=spec.get("attempt"),
        best=sol.get("rate"), good=spec.get("good"), checked=spec.get("checked"), mult=spec.get("mult"),
        rules=list((spec.get("rules") or {}).keys()))
    pipe = r().pipeline()
    pipe.hset(LIB, str(pid), json.dumps(spec))
    pipe.rpush(DAILY_Q if need == "daily" else PERSONAL_Q, pid)
    pipe.execute()
    return need


def start_generator(app, every: int = GEN_EVERY):
    """The puzzle task: a daemon thread per worker; a Redis lock lets one of them build one puzzle per `every`
    seconds (sooner while no daily puzzle is ready). Started from wsgi.py, never in tests or scripts."""
    import logging
    import threading
    logger = logging.getLogger(__name__)

    def loop():
        time.sleep(20)
        while True:
            wait = every
            try:
                r().set(BEAT_KEY, int(time.time()), ex=86400)
                if r().set("web:puzzle:gen:lock", "1", nx=True, ex=every):
                    with app.app_context():
                        went = generate_one()
                    if went is None and not r().exists("web:puzzle:log:full"):
                        globals()["log"]("full", note="the library is full: nothing to build")
                        r().set("web:puzzle:log:full", "1", ex=86400)  # said once a day, not every round
                    if went == "daily" and r().llen(DAILY_Q) < 2:
                        wait = 15  # nothing for tomorrow yet: catch up first
                        r().delete("web:puzzle:gen:lock")
            except Exception as e:
                logger.exception("puzzle generator")
                globals()["log"]("error", error=f"{type(e).__name__}: {e}"[:300])
            time.sleep(wait)

    threading.Thread(target=loop, name="puzzle-generator", daemon=True).start()


def peek(day: Optional[str] = None) -> Optional[dict]:
    """The day's puzzle if one was picked already (never picks: the admin page only looks)."""
    raw = r().get(f"web:puzzle:{day or today()}")
    return json.loads(raw) if raw else None


def get(day: Optional[str] = None) -> Optional[dict]:
    """The day's puzzle: the next one off the daily queue the first time the day is asked for (None while the queue
    is empty: the task is still building the first ones). Never generates."""
    day = day or today()
    raw = r().get(f"web:puzzle:{day}")
    if raw:
        return json.loads(raw)
    pid = r().lpop(DAILY_Q)
    if pid is None:
        if r().set(f"web:puzzle:log:empty:{day}", "1", nx=True, ex=86400):
            log("empty", day=day, note="a player asked for the daily puzzle but the queue was empty")
        return None
    spec = from_library(int(pid))
    if not spec:
        return None
    spec["day"] = day
    if not r().set(f"web:puzzle:{day}", json.dumps(spec), nx=True, ex=KEEP_DAYS * 86400):
        r().lpush(DAILY_Q, pid)  # another worker picked the day first: put ours back
        return json.loads(r().get(f"web:puzzle:{day}"))
    log("daily", day=day, id=spec.get("id"), left=r().llen(DAILY_Q))
    return spec


# ── Playing ─────────────────────────────────────────────────────────────

def _key(kind, day):
    return f"web:puzzle:{kind}:{day}"


def _expire(*keys):
    pipe = r().pipeline()
    for k in keys:
        pipe.expire(k, KEEP_DAYS * 86400)
    pipe.execute()


def started(uid, day=None) -> Optional[int]:
    v = r().hget(_key("start", day or today()), str(uid))
    return int(v) if v else None


def reveal(uid, day=None) -> int:
    day = day or today()
    r().hsetnx(_key("start", day), str(uid), int(time.time()))
    _expire(_key("start", day))
    return started(uid, day)


def tries(uid, day=None) -> int:
    return int(r().hget(_key("tries", day or today()), str(uid)) or 0)


def solved(uid, day=None) -> Optional[int]:
    v = r().zscore(_key("ladder", day or today()), str(uid))
    return int(v) if v is not None else None


def parse(form) -> tuple:
    """(picks, gear) from the form: s = stand slots (3), g<k> = the stand slot item k goes to ("" = unused)."""
    picks = []
    for v in (form.getlist("s") if hasattr(form, "getlist") else form.get("s", [])):
        if str(v).isdigit() and 0 <= int(v) < STANDS and int(v) not in picks:
            picks.append(int(v))
    if len(picks) != PICK:
        raise GameError(f"Pick exactly {PICK} stands.")
    gear = {}
    for k in range(ITEMS):
        v = form.get(f"g{k}", "")
        if str(v).isdigit():
            if int(v) not in picks:
                raise GameError("Items can only go to the stands you picked.")
            gear[k] = int(v)
    for p in picks:
        if sum(1 for s in gear.values() if s == p) > MAX_ITEMS:
            raise GameError(f"A stand holds {MAX_ITEMS} items at most.")
    return picks, gear


def start(uid, spec: dict, picks, gear):
    """Count the attempt (the clock is already running from the reveal)."""
    if not started(uid, spec["day"]):
        raise GameError("Reveal the puzzle first.")
    r().hincrby(_key("tries", spec["day"]), str(uid), 1)
    _expire(_key("tries", spec["day"]))


def win(user, day: str) -> dict:
    """The first win of the day: on the ladder with its time, and the solve reward."""
    uid = str(user.id)
    rewards = {"won": True, "fragments": 0, "xp": 0, "stand_xp": 0, "item": None}
    if solved(uid, day) is not None or day != today():
        rewards["item"] = "already solved: no second reward" if day == today() else "yesterday's puzzle: no reward"
        return rewards
    took = max(1, int(time.time()) - (started(uid, day) or int(time.time())))
    r().zadd(_key("ladder", day), {uid: took}, nx=True)
    _expire(_key("ladder", day))
    user.fragments += REWARD["fragments"]
    user.xp += REWARD["xp"]
    rewards.update(fragments=REWARD["fragments"], xp=REWARD["xp"], item=f"solved in {clock(took)}, #{rank(uid, day)} today")
    return rewards


def rank(uid, day=None) -> Optional[int]:
    """Place on the day's ladder: by time, then fewer attempts."""
    rows = ladder(day, size=None)
    return next((row["rank"] for row in rows if row["uid"] == str(uid)), None)


def ladder(day=None, size: Optional[int] = LADDER_SIZE) -> list:
    day = day or today()
    rows = [(m.decode() if isinstance(m, bytes) else m, int(s)) for m, s in r().zrange(_key("ladder", day), 0, -1, withscores=True)]
    t = r().hgetall(_key("tries", day))
    t = {(k.decode() if isinstance(k, bytes) else k): int(v) for k, v in t.items()}
    rows.sort(key=lambda x: (x[1], t.get(x[0], 1)))
    out = [{"rank": i + 1, "uid": u, "seconds": s, "clock": clock(s), "tries": t.get(u, 1)} for i, (u, s) in enumerate(rows)]
    return out[:size] if size else out


# ── Personal puzzles ────────────────────────────────────────────────────

def _me(uid) -> str:
    return f"web:puzzle:me:{uid}"


def me(uid) -> dict:
    raw = r().hgetall(_me(uid))
    d = {(k.decode() if isinstance(k, bytes) else k): (v.decode() if isinstance(v, bytes) else v) for k, v in raw.items()}
    return {"idx": int(d.get("idx", 0)), "started": int(d["started"]) if d.get("started") else None,
            "tries": int(d.get("tries", 0)), "solved": int(d.get("solved", 0)), "skipped": int(d.get("skipped", 0)),
            "paid": int(d.get("paid", 0)) if d.get("paid_day") == today() else 0}


def personal(uid) -> Optional[dict]:
    """Your current puzzle from the personal library (None: you've done them all, for now)."""
    pid = r().lindex(PERSONAL_Q, me(uid)["idx"])
    return from_library(int(pid)) if pid is not None else None


def personal_reveal(uid):
    if personal(uid):
        r().hsetnx(_me(uid), "started", int(time.time()))


def personal_start(uid, spec: dict):
    if not me(uid)["started"]:
        raise GameError("Reveal the puzzle first.")
    r().hincrby(_me(uid), "tries", 1)


def _advance(uid, field: str):
    pipe = r().pipeline()
    pipe.hincrby(_me(uid), "idx", 1)
    pipe.hincrby(_me(uid), field, 1)
    pipe.hdel(_me(uid), "started", "tries")
    pipe.execute()


def personal_skip(uid):
    if personal(uid):
        _advance(uid, "skipped")


def personal_win(user, pid: int) -> dict:
    """Solving your current puzzle: its time kept, the next one comes up, and a reward for the first few a day."""
    uid = str(user.id)
    rewards = {"won": True, "fragments": 0, "xp": 0, "stand_xp": 0, "item": None}
    cur = personal(uid)
    if not cur or cur["id"] != pid:
        rewards["item"] = "a puzzle you'd already moved past: no reward"
        return rewards
    state = me(uid)
    took = max(1, int(time.time()) - (state["started"] or int(time.time())))
    r().hset(f"web:puzzle:best:{uid}", str(pid), took)
    r().zincrby("web:puzzle:solvers", 1, uid)
    _advance(uid, "solved")
    note = f"puzzle #{pid} solved in {clock(took)}"
    if state["paid"] < PERSONAL_PAID:
        pipe = r().pipeline()
        pipe.hset(_me(uid), mapping={"paid_day": today(), "paid": state["paid"] + 1})
        pipe.execute()
        user.fragments += PERSONAL_REWARD["fragments"]
        user.xp += PERSONAL_REWARD["xp"]
        rewards.update(fragments=PERSONAL_REWARD["fragments"], xp=PERSONAL_REWARD["xp"])
    else:
        note += f" (the first {PERSONAL_PAID} a day pay)"
    rewards["item"] = note
    return rewards


def solvers(size: int = 10) -> list:
    rows = r().zrevrange("web:puzzle:solvers", 0, size - 1, withscores=True)
    return [{"rank": i + 1, "uid": (u.decode() if isinstance(u, bytes) else u), "solved": int(n)} for i, (u, n) in enumerate(rows)]


def clock(seconds: int) -> str:
    h, rest = divmod(int(seconds), 3600)
    m, s = divmod(rest, 60)
    return f"{h}h {m:02d}m {s:02d}s" if h else f"{m}m {s:02d}s"


def view(spec: dict) -> dict:
    """What the board shows: each stand's level-100 numbers and the synergies it shares with the other five."""
    from app.game.overheaven import rule_lines
    from app.game.items import item_file
    from app.game.pickers import item_line
    from app.game.characterabilities import SYNERGIES, SYNERGY_INFO
    shared = {k: [i for i, c in enumerate(spec["stands"]) if c in m] for k, m in SYNERGIES.items()}
    shared = {k: v for k, v in shared.items() if len(v) >= 2}
    cards = []
    for i, cid in enumerate(spec["stands"]):
        c = stand(cid)
        cards.append({**CHARACTER_FILE[cid - 1], "slot": i, "hp": c.start_hp, "dmg": c.current_damage, "spd": c.current_speed,
                      "crit": round(c.current_critical, 1), "special": CHARACTER_FILE[cid - 1]["special_description"].replace("`", ""),
                      "syn": [k for k, v in shared.items() if i in v]})
    return {"cards": cards, "synergies": {k: {"label": SYNERGY_INFO[k][0], "icon": SYNERGY_INFO[k][1]} for k in shared},
            "stands": [CHARACTER_FILE[c - 1] for c in spec["stands"]],
            "items": [{**item_file[i - 1], "line": item_line(item_file[i - 1])} for i in spec["items"]],
            "enemies": [CHARACTER_FILE[c - 1] for c in spec["enemies"]],
            "rules": rule_lines(spec["rules"]), "mult": spec["mult"], "checked": spec.get("checked", 0),
            "rate": spec.get("solution", {}).get("rate"), "good": spec.get("good")}
