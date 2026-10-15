"""Heaven's Gate: the campaign past Requiem · Over Heaven. Act I, "Stairway to Heaven": four fights, each built
around one of the series' impossible powers, played under Over Heaven rules (overheaven.py) and tuned against a real
top team (requiem.BENCH) so a maxed, refined team wins some of the time and has to play the gimmick to win more.

The gimmicks are fight rules too, read by the engine (Fight) and drawn by the fight screen:
  time_stop   N   every Nth round The World stops time: the enemy acts twice in a row
  erase       N   every Nth round King Crimson erases your next turn (announced a round ahead)
  epitaph         at the start of your turn you see who each enemy will strike, and fate holds them to it
  hidden_hp   N   Heaven's Door: an enemy's health stays hidden until you've hit it N times
  accel   [s, step, floor]   Made in Heaven: a turn clock of s seconds, `step` shorter every round down to `floor`;
                  when it runs out that stand's attack lands on nothing (0 damage)
Before each fight you pick one of three pacts (PACTS): a blessing for your team and a curse that comes with it.

Save: data["web_heaven"] = {"cleared": n, "paid": [stage, ...]}
"""
import random
from typing import List, Optional

from app.game.logic import GameError

TITLE = "Heaven's Gate"
ACT_TITLE = "Act I · Stairway to Heaven"
REPLAY_ENERGY = 3
OH = {"heaven_tax": 0.1}  # Over Heaven's borrowed power, in every fight of the campaign

# power: the enemies' health and damage multiplier, tuned with the simulator so requiem.BENCH (a maxed, refined top
# team, the simulator's smart AI picking targets) wins about 40% of the time; Epitaph and Heaven's Door give the player
# information the AI doesn't use, Made in Heaven's clock takes some away.
FIGHTS = [
    {"key": "world", "title": "Stopped Time", "boss": "DIO · The World", "power": 0.94, "ids": [10, 30, 14],
     "color": "#F4C542", "icon": "⏱️",
     "story": "DIO waits at the top of the first stair. Every third round, time stops for everyone but him.",
     "tip": "Time stops every 3rd round: on the round before, put up your shields, taunt or heal.",
     "rules": {**OH, "time_stop": 3, "heal_cut": 0.25}},
    {"key": "epitaph", "title": "Epitaph", "boss": "Diavolo · King Crimson", "power": 1.53, "ids": [75, 81, 80],
     "color": "#D6246E", "icon": "👁️",
     "story": "Diavolo sees ten seconds ahead, and so do you: Epitaph shows who each of his stands will strike. Fate holds.",
     "tip": "You see who each enemy will hit next turn: kill or stun that attacker first. Every 4th round your turn is erased.",
     "rules": {**OH, "epitaph": True, "erase": 4, "stun_immune": False}},
    {"key": "door", "title": "Heaven's Door", "boss": "Rohan · Heaven's Door", "power": 1.41, "ids": [45, 58, 32],
     "color": "#3AB4F2", "icon": "📖",
     "story": "Rohan has written \"you cannot read my health\" into the page. Hit a stand to read its book.",
     "tip": "Enemy health is hidden until you've hit a stand twice, and they heal every turn: focus one at a time.",
     "rules": {**OH, "hidden_hp": 2, "regen": 0.03, "purge": True}},
    {"key": "heaven", "title": "Made in Heaven", "boss": "Pucci · Made in Heaven", "power": 1.405, "ids": [109, 107, 108],
     "color": "#5FF2E4", "icon": "🌌", "boss_fight": True,
     "story": "Time accelerates toward the end of the universe. Every round, you have less time to choose.",
     "tip": "Your turn clock shrinks every round (15 s down to 2 s). Out of time: that stand's attack lands on nothing.",
     "rules": {**OH, "accel": [15, 2, 2], "enrage": 0.05, "pressure": 0.015}},
]
BY_KEY = {f["key"]: f for f in FIGHTS}
REWARDS = [  # first clears
    {"fragments": 20000, "super": 2, "items": [3]},
    {"fragments": 24000, "super": 2, "items": [3]},
    {"fragments": 28000, "super": 3, "items": [3]},
    {"fragments": 40000, "super": 5, "items": [3]},
]

# Pacts: a blessing and its curse (rules of the fight). Three are offered before each fight.
PACTS = {
    "fury": ("🔥 Fury", "Your stands deal 20% more damage", "the enemy heals 2% every turn",
             {"my_damage": 0.2, "regen": 0.02}),
    "bulwark": ("🛡️ Bulwark", "Your stands have 20% more health", "your healing is 30% weaker",
                {"my_health": 0.2, "heal_cut": 0.3}),
    "haste": ("⚡ Haste", "Every special starts 1 turn closer", "the enemy moves first",
              {"my_charge": 1, "enemy_first": True}),
    "wrath": ("💢 Wrath", "Your stands deal 35% more damage", "they lose 2% health every turn",
              {"my_damage": 0.35, "pressure": 0.02}),
    "stone": ("🗿 Stone mask", "Your stands have 35% more health", "the enemy grows 4% stronger every turn",
              {"my_health": 0.35, "enrage": 0.04}),
    "gamble": ("🎲 Gamble", "Every special starts 2 turns closer", "the enemy reflects 15% of basic hits",
               {"my_charge": 2, "reflect": 0.15}),
}


def pacts_for(uid, j: int, attempt: int) -> List[str]:
    """The three pacts offered for fight j: drawn per player, fight and attempt (a loss draws new ones)."""
    rng = random.Random(f"{uid}:{j}:{attempt}")
    return rng.sample(sorted(PACTS), 3)


def pact_lines(key: str) -> dict:
    name, boon, bane, _ = PACTS[key]
    return {"key": key, "name": name, "boon": boon, "bane": bane}


def merge(rules: dict, pact: Optional[str]) -> dict:
    """A fight's rules with a pact on top (the harsher of two values when both set one)."""
    out = dict(rules)
    for k, v in (PACTS[pact][3] if pact in PACTS else {}).items():
        out[k] = max(out[k], v) if isinstance(v, (int, float)) and not isinstance(v, bool) and k in out else v
    return out


# ── Progress ────────────────────────────────────────────────────────────

def progress(user) -> dict:
    p = user.data.setdefault("web_heaven", {})
    p.setdefault("cleared", 0)
    p.setdefault("paid", [])
    p.setdefault("attempts", {})
    return p


def cleared(user) -> int:
    return int((user.data.get("web_heaven") or {}).get("cleared", 0))


def unlocked(user) -> bool:
    """After Requiem · Over Heaven (every fight of it), or an admin forced it."""
    from app.game import overheaven
    from app.game.progression import is_forced
    track = overheaven.REQUIEM_TRACK
    return overheaven.cleared(user, track["key"]) >= len(track["fights"]) or is_forced(user, "heaven")


def check_can_fight(user, j: int):
    if not unlocked(user):
        raise GameError("Heaven's Gate opens once you clear Requiem · Over Heaven.")
    if not 0 <= j < len(FIGHTS):
        raise GameError("That fight doesn't exist.")
    from app.game.progression import is_forced
    if j > cleared(user) and not is_forced(user, "heaven"):  # an admin's dev unlock opens every fight
        raise GameError("Clear the fights before it first.")
    if j < cleared(user):  # a replay
        if user.energy < REPLAY_ENERGY:
            raise GameError(f"A replay costs {REPLAY_ENERGY} energy.")
        user.energy -= REPLAY_ENERGY
    if len(user.main_characters) < 3:
        raise GameError("Bring a full team of three.")


def enemy_team(j: int) -> list:
    from app.game import requiem
    f = FIGHTS[j]
    return requiem.crew(f["ids"], f["power"])


def foe_name(j: int) -> str:
    return f"Heaven's Gate · {FIGHTS[j]['boss']}"


def lost(user, j: int):
    """A loss: the next try offers other pacts."""
    a = progress(user)["attempts"]
    a[str(j)] = a.get(str(j), 0) + 1


def attempt(user, j: int) -> int:
    return int(((user.data.get("web_heaven") or {}).get("attempts") or {}).get(str(j), 0))


def reward_text(j: int) -> List[str]:
    from app.game.items import item_file
    r = REWARDS[j]
    out = [f"{r['fragments']:,} Meteor Dust", f"{r['super']} Arrowheads"]
    counts = {}
    for i in r["items"]:
        counts[i] = counts.get(i, 0) + 1
    out += [f"{item_file[i - 1]['name']}{f' ×{n}' if n > 1 else ''}" for i, n in counts.items()]
    if j == len(FIGHTS) - 1:
        out.append(f"the title “{TITLE}”")
    return out


def win(user, j: int) -> dict:
    """The first clear pays the fight's reward (the last one, the title too); replays pay a little Dust."""
    from app.game import titles
    from app.game.items import item_from_dict
    p = progress(user)
    if j < p["cleared"] or j in p["paid"]:
        user.fragments += 2000
        return {"won": True, "fragments": 2000, "xp": 0, "stand_xp": 0, "item": None}
    p["cleared"] = max(p["cleared"], j + 1)
    p["paid"].append(j)
    r = REWARDS[j]
    user.fragments += r["fragments"]
    user.super_fragments += r["super"]
    items = [item_from_dict({"id": i}) for i in r["items"]]
    user.items.extend(items)
    names = [i.name for i in items] + [f"{r['super']} Arrowheads"]
    if j == len(FIGHTS) - 1 and titles.grant(user, TITLE):
        names.append(f"the title “{TITLE}”")
    return {"won": True, "fragments": r["fragments"], "xp": 0, "stand_xp": 0, "item": ", ".join(names)}


def view(user) -> list:
    done = cleared(user)
    out = []
    for j, f in enumerate(FIGHTS):
        from app.game import overheaven
        from app.game.progression import is_forced
        state = "cleared" if j < done else ("open" if j == done or is_forced(user, "heaven") else "locked")
        out.append({**f, "j": j, "state": state,
                    "rules_text": overheaven.rule_lines(f["rules"]), "reward": reward_text(j),
                    "pacts": [pact_lines(k) for k in pacts_for(user.id, j, attempt(user, j))]})
    return out


# ── The gimmicks, for the fight screen ───────────────────────────────────

def accel_seconds(rules: dict, round_no: int) -> Optional[int]:
    if not rules.get("accel"):
        return None
    start, step, floor = rules["accel"]
    return max(floor, start - step * (round_no - 1))


def clock(fight) -> Optional[int]:
    """Made in Heaven's turn clock: seconds left for the current pick (a new pick starts a new clock)."""
    import time
    secs = accel_seconds(fight.__dict__.get("rules") or {}, fight.round)
    if secs is None or fight.finished or not fight.awaiting_input:
        return None
    c = fight.meta.get("clock")
    if not c or c.get("log") != len(fight.log) or c.get("si") != fight.si:
        c = fight.meta["clock"] = {"log": len(fight.log), "si": fight.si, "until": time.time() + secs}
    return max(0, int(round(c["until"] - time.time())))


def pick(fight, target):
    """Out of time (the page says so when its clock hits 0, and the server checks with a little grace for the
    network): the stand's attack lands on nothing."""
    import time
    from flask import request
    c = fight.meta.get("clock")
    late = c and time.time() > c["until"] + 1.5
    if c and not fight.finished and (late or request.form.get("timeout")):
        fight._whiff = True
        valid = fight.targets()
        return target if target in valid else (random.choice(valid) if valid else target)
    return target


def hp_hidden(fight, c, side: int, my_side: int) -> bool:
    """Heaven's Door: an enemy's health stays unread until it has been hit enough times."""
    n = (fight.__dict__.get("rules") or {}).get("hidden_hp")
    return bool(n) and side != my_side and c.is_alive() and c.__dict__.get("_read", 0) < n


def banner(fight) -> List[dict]:
    """What the fight screen announces: [{icon, text, hot}] (hot: it happens now or next)."""
    r, out = fight.rules, []
    rnd = fight.round
    if r.get("time_stop"):
        n = r["time_stop"]
        left = (-rnd) % n
        if fight.__dict__.get("_ts_left") is not None:
            out.append({"icon": "⏱️", "text": "TIME IS STOPPED", "hot": True})
        else:
            out.append({"icon": "⏱️", "text": "Time stops THIS round: brace!" if left == 0 else f"Time stops in {left} round{'s' if left != 1 else ''}",
                        "hot": left <= 1})
    if r.get("erase"):
        n = r["erase"]
        left = (-rnd) % n
        out.append({"icon": "👁️", "text": "King Crimson erases your next turn after this round" if left == 0
                    else f"Your turn is erased in {left} round{'s' if left != 1 else ''}", "hot": left == 0})
    if r.get("epitaph"):
        fate = fight.__dict__.get("_fate") or {}
        me, foe = fight.sides[fight.human_side], fight.sides[1 - fight.human_side]
        for i, t in sorted(fate.items()):
            if i < len(foe.chars) and t < len(me.chars) and foe.chars[i].is_alive() and me.chars[t].is_alive():
                from app.game.fight import _expected_hit
                out.append({"icon": "📜", "text": f"Epitaph: {foe.chars[i].name} will strike {me.chars[t].name} "
                                                  f"(~{int(_expected_hit(foe.chars[i], me.chars[t])):,})", "hot": True})
    if r.get("hidden_hp"):
        out.append({"icon": "📖", "text": f"Heaven's Door: hit a stand {r['hidden_hp']} times to read its health", "hot": False})
    return out
