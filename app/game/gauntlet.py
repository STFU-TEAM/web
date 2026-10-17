"""The Heaven's Door Gauntlet: Rohan draws you an adventure, chapter by chapter, and you draft its cast as you climb.
Every stand fights at the same level (GAUNTLET_LEVEL, ★0, no items or chips from the save), so the picks make the run.
One loss ends it.

A run: chapter (floor) 1 offers three stands, pick one; every chapter after a win offers three more (rarer as you
climb: up to SR, then SSR from 3, UR from 6, LR from 9). With a full team a pick swaps a member out, or you take one
of Rohan's two pages instead: a boon (BOONS, a straight buff) or a pact (PACTS, a great buff with a terrible
downside; each pact once a run). Every third chapter once the team is full (4, 7, 10...) drops a prototype item
instead: absurdly strong, unstable, only for the run.
Your team keeps its wounds between floors and heals HEAL_BETWEEN; fallen stands get back up at that much.

Everyone climbs the same floors in a week (seeded by the week), and the weekly ladder ranks the deepest floor.
One free run a day; another costs EXTRA_RUN_ENERGY energy. Rewards: dust for every floor cleared, an Arrowhead the first
time a week you clear floor ARROW_FLOOR, a title at TITLE_FLOOR.

Save: data["web_gauntlet"] = {"run": {...} or None, "day": last free run's date, "best": {week: floor},
"paid": {week: [milestones]}}.  Redis: web:gauntlet:<week> zset uid -> floors cleared * 1e6 + seconds left in the week.
"""
import datetime
import random
from typing import List, Optional

from app.game.logic import GameError

GAUNTLET_LEVEL = 100
HEAL_BETWEEN = 50           # % of max health back between floors (the fallen get up at this much)
EXTRA_RUN_ENERGY = 5
ARROW_FLOOR, TITLE_FLOOR = 15, 20
PLANE_FLOOR, PLANE_ITEM = 10, 66  # Narancia's Toy Plane, once a week
TITLE = "Gauntlet Survivor"
ITEM_EVERY = 3
RARITY = ["R", "SR", "SSR", "UR", "LR"]
BOON = 0.10                 # +damage per boon in runs from before boons had kinds (an int)

# key: (name, glyph, stat lines (text, good?), what it does). Their effects live in apply_item() and the fight engine.
ITEMS = {
    "mask": ("Overclocked Stone Mask", "仮", [("+80% damage", 1), ("+40% speed", 1), ("-6% health a turn", 0)],
             "Vampiric hunger: every hit heals 25% of the damage dealt."),
    "arrow": ("Twin Requiem Arrowhead", "矢", [("special every turn", 1), ("-45% max health", 0)],
              "Its special is charged every single turn."),
    "ball": ("Infinite Steel Ball", "球", [("+30% damage", 1), ("+20 crit", 1)],
             "Every hit spins onward: the next enemy takes 60% of it, then the next 36%."),
    "aja": ("Cracked Red Stone of Aja", "石", [("+50 crit", 1), ("crits deal x3", 1), ("-30% armor", 0)],
            "A critical hit blinds its target: it misses its next attack."),
    "hat": ("Speedwagon's Lucky Hat", "帽", [("+150% speed", 1), ("-25% damage", 0)],
            "Moves before almost anything. When it dodges, it counters for 80%."),
    "disc": ("Blank DISC", "盤", [("+20% to every stat", 1)],
             "Once a fight, copies the first special an enemy uses and fires it back, 50% stronger."),
    "coin": ("D'Arby's Loaded Coin", "貨", [("x2.5 or x0.5 damage", 1)],
             "Every hit flips the coin: heads crushes, tails barely scratches."),
    "spine": ("Saint's Spine (shard)", "聖", [("+60% max health", 1), ("+40% armor", 1), ("-20% speed", 0)],
              "Once a run, when it falls it gets back up at 50% health, every debuff gone."),
    "bullet": ("Emperor's Silver Bullet", "銃", [("+15 crit", 1), ("first hit x3", 1)],
               "Its first hit each fight is triple damage and ignores armor."),
    "lips": ("Cinderella's Lipstick", "紅", [("+25 crit", 1)],
             "Beauty is contagious: every critical hit heals the whole team 6% of its health."),
    "freeze": ("Echoes ACT 3 Seal", "重", [("+15% damage", 1)],
               "3 FREEZE: every hit makes its target heavy, -30% speed for its next turn."),
    "bomb": ("Killer Queen's Switch", "爆", [("+20% damage", 1)],
             "When it falls, it detonates: 60% of its max health as damage to every enemy."),
    "restore": ("Crazy Diamond's Fist", "治", [("+20% max health", 1)],
                "At the end of each of its turns, restores the most wounded ally by 10% of its health."),
    "zipper": ("Sticky Fingers' Zipper", "閉", [("+25% speed", 1)],
               "Once a fight, a blow that would finish it zips it away instead: it stays at 1 health."),
    "hand": ("The Hand's Glove", "削", [("ignores armor", 1), ("-15% max health", 0)],
             "Its basic hits ignore armor, and each one erases 5% of the target's health."),
    "sha": ("Sheer Heart Attack", "追", [("+10% damage", 1)],
            "At the end of each of its turns, the tank homes in on the fastest enemy for 60% of its damage."),
}

# Rohan's pages when the team is full: a boon is a straight buff; a pact a great one with a terrible price.
# key: (name, glyph, text). Their effects: run_mods() and pact_rules(); a pact can be signed once a run.
BOONS = {
    "sketch": ("A sharper sketch", "筆", "+15% damage for the rest of the run."),
    "ink": ("Thicker ink", "墨", "+20% max health for the rest of the run."),
    "speed": ("Speed lines", "速", "+15% speed for the rest of the run."),
    "luck": ("Lucky panel", "運", "+10 crit for the rest of the run."),
    "rest": ("A chapter break", "休", "Your whole team heals 60% right now."),
}
PACTS = {
    "mask": ("Pact of the Stone Mask", "仮", "+60% damage. But nothing on your team can heal any more."),
    "arrow": ("Pact of the Arrow", "矢", "Specials charge one turn faster. But every special costs its caster 12% of its max health."),
    "darby": ("Pact of D'Arby", "賭", "Triple dust from every chapter. But when the run ends in a loss, D'Arby takes back half of what you banked."),
    "kira": ("Pact of the Quiet Life", "吉", "+40% to every stat. But one random stand starts every fight at 1 health."),
    "valentine": ("Pact of D4C", "国", "Enemies have 30% less health. But your stands lose 5% of their health every turn."),
    "rock": ("Pact of the Rock Humans", "岩", "Double armor and +30% health. But enemies always move first and you're 30% slower."),
}


def week_key(when=None) -> str:
    year, week, _ = (when or datetime.datetime.now(datetime.timezone.utc)).isocalendar()
    return f"{year}-W{week:02d}"


def _today() -> str:
    return datetime.datetime.now(datetime.timezone.utc).date().isoformat()


def state(user) -> dict:
    s = user.data.get("web_gauntlet") or {}
    s.setdefault("run", None)
    s.setdefault("best", {})
    s.setdefault("paid", {})
    run = s["run"]
    if run and run.get("week") != week_key():  # a run from last week is over
        s["run"] = None
    return s


def _save(user, s: dict):
    user.data["web_gauntlet"] = s


def roll_deal(run: dict, rng=random) -> dict:
    """Rohan's two pages for a full team: a boon, and a pact not yet signed this run."""
    pacts = [k for k in PACTS if k not in run.get("pacts", [])]
    return {"boon": rng.choice(list(BOONS)), "pact": rng.choice(pacts) if pacts else None}


def _mods(run: dict) -> dict:
    """The run's boons and pacts as multipliers: damage, health, speed, armor, crit points, charge."""
    m = {"damage": 1.0, "hp": 1.0, "speed": 1.0, "armor": 1.0, "crit": 0, "charge": 0}
    boons = run.get("boons", [])
    if isinstance(boons, int):  # a run from before boons had kinds
        m["damage"] += BOON * boons
        boons = []
    for b in boons:
        if b == "sketch":
            m["damage"] *= 1.15
        elif b == "ink":
            m["hp"] *= 1.2
        elif b == "speed":
            m["speed"] *= 1.15
        elif b == "luck":
            m["crit"] += 10
    for p in run.get("pacts", []):
        if p == "mask":
            m["damage"] *= 1.6
        elif p == "arrow":
            m["charge"] += 1
        elif p == "kira":
            for k in ("damage", "hp", "speed", "armor"):
                m[k] *= 1.4
        elif p == "rock":
            m["armor"] *= 2
            m["hp"] *= 1.3
            m["speed"] *= 0.7
    return m


def pact_rules(run: dict) -> dict:
    """Fight rules the run's pacts bring (the Over Heaven engine: overheaven.RULE_TEXT)."""
    rules = {}
    pacts = run.get("pacts", [])
    if "valentine" in pacts:
        rules["pressure"] = 0.05
    if "rock" in pacts:
        rules["enemy_first"] = True
    if "mask" in pacts:
        rules["heal_cut"] = 1
    return rules


def prepare_fight(run: dict, mine: list, foes: list, rng=random):
    """After the fight's own set-up: the pacts that touch the enemy or the opening (D4C, the Quiet Life)."""
    pacts = run.get("pacts", [])
    if "valentine" in pacts:
        for c in foes:
            c.start_hp = int(c.start_hp * 0.7)
            c.current_hp = min(c.current_hp, c.start_hp)
    if "kira" in pacts:
        alive = [c for c in mine if c.current_hp > 0]
        if alive:
            rng.choice(alive).current_hp = 1
    if "arrow" in pacts:
        for c in mine:
            c._g_tax = 0.12


def free_run_left(user) -> bool:
    return state(user).get("day") != _today()


def _pool(cap: int, exclude) -> List[dict]:
    from app.filters import PLAYABLE
    return [c for c in PLAYABLE if c["id"] != 110 and RARITY.index(c["rarity"]) <= cap and c["id"] not in exclude]


def rarity_cap(floor: int) -> int:
    """The rarest pick a floor can offer: SR on floors 1-2, SSR from 3, UR from 6, LR from 9."""
    return min(4, 1 + floor // 3)


def roll_offers(run: dict, rng=random) -> List[int]:
    pool = _pool(rarity_cap(run["floor"]), {m["id"] for m in run["team"]})
    return [c["id"] for c in rng.sample(pool, min(3, len(pool)))]


def is_item_floor(floor: int) -> bool:
    """Every third floor once the team is full (floors 4, 7, 10...): a prototype item instead of a stand."""
    return floor > 3 and floor % ITEM_EVERY == 1


def roll_items(run: dict, rng=random) -> List[str]:
    return rng.sample(list(ITEMS), 3)


def start(user) -> dict:
    s = state(user)
    if s["run"] and not s["run"].get("over"):
        raise GameError("You already have a run going.")
    if free_run_left(user):
        s["day"] = _today()
    elif user.energy >= EXTRA_RUN_ENERGY:
        user.energy -= EXTRA_RUN_ENERGY
    else:
        raise GameError(f"Your free run today is used. Another costs {EXTRA_RUN_ENERGY} energy.")
    run = {"week": week_key(), "floor": 1, "team": [], "phase": "pick", "offers": [], "items": [], "boons": [],
           "pacts": [], "deal": None, "dust": 0, "revived": False, "over": False}
    run["offers"] = roll_offers(run)
    s["run"] = run
    _save(user, s)
    return run


def _run(user, phase: Optional[str] = None) -> dict:
    run = state(user)["run"]
    if not run or run.get("over"):
        raise GameError("Start a run first.")
    if phase and run["phase"] != phase:
        raise GameError("That's not what this floor offers.")
    return run


def pick(user, stand_id: int, replace: Optional[int] = None) -> dict:
    run = _run(user, "pick")
    if stand_id not in run["offers"]:
        raise GameError("Pick one of the three stands on offer.")
    if len(run["team"]) < 3:
        run["team"].append({"id": stand_id, "hp": 100, "item": None})
    else:
        if replace is None or not 0 <= replace < 3:
            raise GameError("Your team is full: choose who leaves.")
        run["team"][replace] = {"id": stand_id, "hp": 100, "item": None}
    run.update(phase="ready", offers=[], deal=None)
    _save(user, state(user) | {"run": run})
    return run


def take_page(user, which: str) -> dict:
    """Keep the team and take one of Rohan's pages: the boon or the pact."""
    run = _run(user, "pick")
    deal = run.get("deal") or {}
    if len(run["team"]) < 3 or which not in ("boon", "pact") or not deal.get(which):
        raise GameError("That page isn't on offer.")
    key = deal[which]
    if which == "boon":
        if isinstance(run.get("boons"), int):
            run["boons"] = ["sketch"] * run["boons"]
        run.setdefault("boons", []).append(key)
        if key == "rest":
            for m in run["team"]:
                m["hp"] = min(100, m["hp"] + 60)
    else:
        run.setdefault("pacts", []).append(key)
    run.update(phase="ready", offers=[], deal=None)
    _save(user, state(user) | {"run": run})
    return run


def boon(user) -> dict:  # the old single boon button: the offered boon
    return take_page(user, "boon")


def give_item(user, key: str, slot: int) -> dict:
    run = _run(user, "item")
    if key not in run["items"] or not 0 <= slot < len(run["team"]):
        raise GameError("Pick an item and a stand to hold it.")
    run["team"][slot]["item"] = key
    run.update(phase="ready", items=[])
    _save(user, state(user) | {"run": run})
    return run


def abandon(user) -> Optional[dict]:
    s = state(user)
    run = s["run"]
    if run and not run.get("over"):
        run.update(over=True, phase="over")
        _save(user, s)
    return run


# ── fights ──────────────────────────────────────────────────────────────────

def _fighter(stand_id: int, level: int, awaken: int):
    from app.game.character import character_from_dict
    return character_from_dict({"id": stand_id, "xp": level * 100, "awaken": awaken, "types": ["BALANCE"],
                                "qualities": ["GOOD"], "items": []})


def team(run: dict) -> list:
    """The run's fighters: equal level, the boons on top, each one's item applied, its wounds carried over."""
    out = []
    mods = _mods(run)
    for m in run["team"]:
        c = _fighter(m["id"], GAUNTLET_LEVEL, 0)
        c.current_damage *= mods["damage"]
        c.current_speed *= mods["speed"]
        c.current_armor *= mods["armor"]
        c.current_critical += mods["crit"]
        c.start_hp = int(c.start_hp * mods["hp"])
        c.current_hp = c.start_hp
        c.turn_for_ability = max(1, c.turn_for_ability - mods["charge"])
        if m.get("item"):
            apply_item(c, m["item"], revived=run.get("revived", False))
        c._g_hp = m["hp"]
        out.append(c)
    return out


def carry_wounds(chars: list):
    """After the fight's own set-up (synergies add health): each fighter starts at its carried share of health."""
    for c in chars:
        pct = getattr(c, "_g_hp", 100)
        c.current_hp = max(1, int(c.start_hp * pct / 100))


def enemies(floor: int, week: Optional[str] = None) -> list:
    """The same crew for everyone on a floor this week: stronger every floor, a boss with a rare stand every fifth.
    The first floors match the team you've drafted so far: one enemy on floor 1, two on floor 2."""
    rng = random.Random(f"gauntlet:{week or week_key()}:{floor}")
    cap = min(4, 1 + floor // 4) if floor % 5 else min(4, 2 + floor // 5)
    pool = _pool(cap, set())
    picks = rng.sample(pool, min(3, floor))
    level, awaken = min(100, 30 + floor * 3), min(5, floor // 6)
    out = []
    for p in picks:
        c = _fighter(p["id"], level, awaken)
        power = 1 + 0.07 * max(0, floor - 12)  # past floor 12 the crews grow faster than levels allow
        c.start_hp = int(c.start_hp * power)
        c.current_hp = c.start_hp
        c.current_damage *= power
        out.append(c)
    return out


def floor_name(floor: int) -> str:
    crews = ["DIO's guards", "The Nine Glory Gods", "La Squadra", "Pucci's agents", "The Rock Humans",
             "Valentine's agents", "The Boss's guard", "Morioh's killers"]
    return ("Boss · " if floor % 5 == 0 else "") + crews[(floor - 1) % len(crews)]


def finish(user, fight, redis=None, name: str = "?") -> dict:
    """A floor's fight is over: on a win, the dust, the wounds carried, the next floor's offer; on a loss, the end."""
    s = state(user)
    run = s["run"]
    won = fight.winner == fight.human_side and not getattr(fight, "forfeited", False)
    rewards = {"won": won, "fragments": 0}
    if not run or run.get("over"):
        return rewards
    floor = run["floor"]
    if fight.meta.get("revived"):
        run["revived"] = True
    if won:
        dust = (40 + 10 * floor) * (3 if "darby" in run.get("pacts", []) else 1)
        user.fragments += dust
        run["dust"] += dust
        rewards["fragments"] = dust
        chars = fight.sides[fight.human_side].chars
        for m, c in zip(run["team"], chars):
            left = 100 * max(0, c.current_hp) / max(1, c.start_hp)
            m["hp"] = int(min(100, left + HEAL_BETWEEN))
        week = run["week"]
        paid = s["paid"].setdefault(week, [])
        if floor >= PLANE_FLOOR and PLANE_FLOOR not in paid:
            from app.game.items import item_from_dict
            user.items.append(item_from_dict({"id": PLANE_ITEM}))
            paid.append(PLANE_FLOOR)
            rewards["item"] = f"Narancia's Toy Plane (floor {PLANE_FLOOR})"
        if floor >= ARROW_FLOOR and ARROW_FLOOR not in paid:
            user.super_fragments += 1
            paid.append(ARROW_FLOOR)
            rewards["item"] = f"an Arrowhead (floor {ARROW_FLOOR})"
        if floor >= TITLE_FLOOR and TITLE_FLOOR not in paid:
            from app.game import titles
            titles.grant(user, TITLE)
            paid.append(TITLE_FLOOR)
            rewards["item"] = f"the title “{TITLE}”"
        s["best"][week] = max(int(s["best"].get(week, 0)), floor)
        if redis is not None:
            _ladder(redis, user.id, week, floor, name)
        run["floor"] = floor + 1
        if is_item_floor(run["floor"]):
            run.update(phase="item", items=roll_items(run), deal=None)
        else:
            run.update(phase="pick", offers=roll_offers(run), deal=roll_deal(run) if len(run["team"]) >= 3 else None)
    else:
        run.update(over=True, phase="over")
        if "darby" in run.get("pacts", []) and run["dust"]:  # D'Arby collects
            taken = min(user.fragments, run["dust"] // 2)
            user.fragments -= taken
            run["dust"] -= taken
            rewards["darby_took"] = taken
    rewards["gauntlet"] = {"floor": floor, "over": not won}
    _save(user, s)
    return rewards


def _ladder(redis, uid, week: str, floors: int, name: str):
    key = f"web:gauntlet:{week}"
    now = datetime.datetime.now(datetime.timezone.utc)
    monday = (now - datetime.timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    left = int((monday + datetime.timedelta(days=7) - now).total_seconds())
    score = floors * 1_000_000 + left  # the deepest first, then whoever got there first
    if float(redis.zscore(key, str(uid)) or 0) < score:
        redis.zadd(key, {str(uid): score})
        redis.hset(f"{key}:names", str(uid), name)
    redis.expire(key, 21 * 86400)
    redis.expire(f"{key}:names", 21 * 86400)


def ladder(redis, week: Optional[str] = None, size: int = 10) -> list:
    key = f"web:gauntlet:{week or week_key()}"
    rows = redis.zrevrange(key, 0, size - 1, withscores=True)
    names = {(k.decode() if isinstance(k, bytes) else k): (v.decode() if isinstance(v, bytes) else v)
             for k, v in redis.hgetall(f"{key}:names").items()}
    out = []
    for i, (uid, score) in enumerate(rows):
        uid = uid.decode() if isinstance(uid, bytes) else uid
        out.append({"rank": i + 1, "uid": uid, "name": names.get(uid, "?"), "floor": int(score // 1_000_000)})
    return out


# ── the prototype items ─────────────────────────────────────────────────────

def apply_item(c, key: str, revived: bool = False):
    """Turn a run fighter into its item's absurd version. The flags (_g_*) are read by the fight engine."""
    if key == "mask":
        c.current_damage *= 1.8
        c.current_speed *= 1.4
        c._lifesteal = max(getattr(c, "_lifesteal", 0), 0.25)
        c._g_drain = 0.06
    elif key == "arrow":
        c.turn_for_ability = 1
        c.special_meter = 1
        c.start_hp = int(c.start_hp * 0.55)
        c.current_hp = min(c.current_hp, c.start_hp)
    elif key == "ball":
        c.current_damage *= 1.3
        c.current_critical += 20
        c._g_chain = 0.6
    elif key == "aja":
        c.current_critical += 50
        c.crit_multiplier = 3
        c.current_armor *= 0.7
        c._g_blind = True
    elif key == "hat":
        c.current_speed = c.current_speed * 2.5 + 15
        c.current_damage *= 0.75
        c._g_counter = 0.8
    elif key == "disc":
        c.current_damage *= 1.2
        c.current_speed *= 1.2
        c.current_armor *= 1.2
        c.start_hp = int(c.start_hp * 1.2)
        c.current_hp = c.start_hp
        c._g_disc = True
    elif key == "coin":
        c._g_coin = True
    elif key == "spine":
        c.start_hp = int(c.start_hp * 1.6)
        c.current_hp = c.start_hp
        c.current_armor *= 1.4
        c.current_speed *= 0.8
        c._g_revive = not revived
    elif key == "bullet":
        c.current_critical += 15
        c._g_bullet = True
    elif key == "lips":
        c.current_critical += 25
        c._g_lips = 0.06
    elif key == "freeze":
        c.current_damage *= 1.15
        c._g_freeze = 0.3
    elif key == "bomb":
        c.current_damage *= 1.2
        c._g_bomb = 0.6
    elif key == "restore":
        c.start_hp = int(c.start_hp * 1.2)
        c.current_hp = c.start_hp
        c._g_restore = 0.1
    elif key == "zipper":
        c.current_speed *= 1.25
        c._g_zip = True
    elif key == "hand":
        c._armor_pierce = 1
        c.start_hp = int(c.start_hp * 0.85)
        c.current_hp = min(c.current_hp, c.start_hp)
        c._g_erase = 0.05
    elif key == "sha":
        c.current_damage *= 1.1
        c._g_sha = 0.6
    c._g_item = key


def page_view(kind: str, key: Optional[str]) -> Optional[dict]:
    if not key:
        return None
    name, glyph, text = (BOONS if kind == "boon" else PACTS)[key]
    return {"kind": kind, "key": key, "name": name, "glyph": glyph, "text": text}


def item_view(key: str) -> dict:
    name, glyph, stats, effect = ITEMS[key]
    return {"key": key, "name": name, "glyph": glyph, "effect": effect,
            "stats": [{"t": t, "good": bool(g)} for t, g in stats]}
