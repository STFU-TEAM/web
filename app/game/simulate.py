"""Team simulator: play a team against a story stage, a tower floor or another player's team many times
through the real engine (your picks made by the smart AI) and report how it went. Nothing is spent or saved.
"""
from typing import List, Optional

from app.game import story, tower
from app.game.fight import Fight, Side, ai_choice, fighting_copy

RUNS = 40
MAX_STEPS = 400


def opponents(heaven: bool = True) -> List[dict]:
    """The PvE groups the picker offers (Over Heaven only once it's open for the player)."""
    stages = [{"value": f"story:{k}", "label": f"{s['part_title'].split('·')[0].strip()} · {s['title']}"
               + (" (boss)" if s.get("boss") else "")} for k, s in enumerate(story.STAGES)]
    floors = [{"value": f"tower:{f}", "label": f"Floor {f}" + (" (boss)" if tower.is_boss(f) else "")}
              for f in range(1, 61)]
    from app.game import overheaven
    heaven_options = [{"value": f"oh:{t['key']}:{j}", "label": f"{t['mode']} · {f['title']}"}
              for t in overheaven.TRACKS for j, f in enumerate(t["fights"])]
    groups = [{"group": "Story", "options": stages}, {"group": "Tower (this week)", "options": floors}]
    return groups + ([{"group": "Over Heaven", "options": heaven_options}] if heaven else [])


def foe_for(value: str, db=None) -> Optional[dict]:
    """{name, team, ai} for a picker value, or None."""
    kind, _, arg = (value or "").partition(":")
    if kind == "story" and arg.isdigit() and int(arg) < story.TOTAL:
        k = int(arg)
        return {"name": story.STAGES[k]["title"], "team": story.enemy_team(k), "ai": story.ai_level(k),
                "label": f"Story · {story.STAGES[k]['title']}"}
    if kind == "tower" and arg.isdigit() and 1 <= int(arg) <= 200:
        f = int(arg)
        return {"name": f"Floor {f}", "team": tower.floor_team(f), "ai": "smart", "label": f"Tower · floor {f}"}
    if kind == "oh":
        from app.game import overheaven
        key, _, j = arg.partition(":")
        if key in overheaven.BY_KEY and j.isdigit() and int(j) < len(overheaven.BY_KEY[key]["fights"]):
            fight = overheaven.BY_KEY[key]["fights"][int(j)]
            return {"name": fight["title"], "team": overheaven.enemy_team(key, int(j)), "ai": "smart",
                    "rules": fight["rules"], "label": f"Over Heaven · {fight['title']}"}
    if kind == "player" and arg and db is not None:
        other = db.get_user(arg)
        if other and other.main_characters:
            from app.db import identity
            name = identity(arg)["name"]
            return {"name": name, "team": other.main_characters, "ai": "smart", "label": f"{name}'s team"}
    return None


def run(team, foe: dict, runs: int = RUNS) -> dict:
    wins = losses = draws = 0
    rounds, hp_left = [], []
    per = [{"id": c.id, "name": c.name, "dmg": 0, "alive": 0, "specials": 0} for c in team]
    for _ in range(runs):
        enemies = Side(foe["name"], fighting_copy(foe["team"]), False)
        enemies.ai = foe.get("ai", "smart")
        f = Fight(Side("You", fighting_copy(team), True), enemies, kind="simulation",
                  meta={"rules": foe["rules"]} if foe.get("rules") else None)
        steps = 0
        while not f.finished and steps < MAX_STEPS:
            pick = ai_choice(f.sides[1].chars, f.acting_char) if f.awaiting_input else None
            f.advance(pick)
            steps += 1
        if not f.finished:
            f.forfeit(0)
        if f.winner == 0:
            wins += 1
            share = sum(max(0, c.current_hp) for c in f.sides[0].chars) / max(1, sum(c.start_hp for c in f.sides[0].chars))
            hp_left.append(share)
        elif f.winner is None:
            draws += 1
        else:
            losses += 1
        rounds.append(f.round)
        prev = None
        for e in f.log:
            src = e.get("src")
            if src and src[0] == 0 and src[1] < len(per):
                if e.get("dmg"):
                    per[src[1]]["dmg"] += e["dmg"]
                elif e["kind"] in ("special", "item") and prev and e.get("hp"):
                    per[src[1]]["dmg"] += sum(max(0, a - b) for a, b in zip(prev[1], e["hp"][1]))
                if e["kind"] == "special":
                    per[src[1]]["specials"] += 1
            if e.get("hp"):
                prev = e["hp"]
        for i, c in enumerate(f.sides[0].chars):
            per[i]["alive"] += c.current_hp > 0
    total_dmg = sum(p["dmg"] for p in per) or 1
    for p in per:
        p["share"] = round(100 * p["dmg"] / total_dmg)
        p["avg"] = int(p["dmg"] / runs)
        p["survive"] = round(100 * p["alive"] / runs)
        p["specials"] = round(p["specials"] / runs, 1)
    rate = round(100 * (wins + draws / 2) / runs)
    return {"runs": runs, "wins": wins, "losses": losses, "draws": draws, "rate": rate,
            "rounds": round(sum(rounds) / len(rounds), 1),
            "hp_left": round(100 * sum(hp_left) / len(hp_left)) if hp_left else 0,
            "stands": per, "verdict": verdict(rate), "carry": max(per, key=lambda p: p["dmg"])["name"] if per else None}


def verdict(rate: int) -> str:
    if rate >= 90:
        return "Safe: this team should win almost every time."
    if rate >= 65:
        return "Favoured: expect to win most attempts."
    if rate >= 40:
        return "Coin flip: target picks and specials will decide it."
    if rate >= 15:
        return "Risky: level up, fuse or rethink the team first."
    return "Out of reach for now."
