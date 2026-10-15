"""What a PvE fight asks of a team, shown before the fight next to the player's own team.

The rule of thumb comes from the team simulator (scripts/progression.py, STAR_GATES): a Lv-matched team one star
under the enemies wins about 70% of story-like fights; harder multipliers ask for the full star; and the endgame
crews (Over Heaven, Requiem, Heaven's Gate: ★5, Universal, refined items) are only beaten by ★5 teams with +5 items
built for their stands, where good qualities count too.
"""
from typing import Optional

ENDGAME_REFINE = 5


def recommend(level: int, stars: int, mult: float = 1.0, hard: bool = False) -> dict:
    if hard:
        return {"level": 100, "stars": 5, "refine": ENDGAME_REFINE}
    rec = max(0, min(5, stars - 1 + (mult >= 1.2)))
    return {"level": min(100, level), "stars": rec, "refine": 0}


def team_view(user) -> Optional[dict]:
    team = list(user.main_characters)
    if not team:
        return None
    items = [it for c in team for it in c.items]
    return {"level": round(sum(c.level for c in team) / len(team)), "stars": min(c.awaken for c in team),
            "refine": round(sum(getattr(it, "refine", 0) for it in items) / len(items), 1) if items else 0, "size": len(team)}


def for_fight(user, level: int, stars: int, mult: float = 1.0, hard: bool = False, vs: Optional[str] = None) -> dict:
    """{"rec", "team", "state": "ready" | "close" | "low", "missing": [...], "vs"}."""
    rec, team = recommend(level, stars, mult, hard), team_view(user)
    missing = []
    if team is None or team["size"] < 3:
        missing.append("a full team of three")
        team = team or {"level": 0, "stars": 0, "refine": 0, "size": 0}
    if team["level"] < rec["level"] - 5:
        missing.append(f"{rec['level'] - team['level']} more levels")
    if team["stars"] < rec["stars"]:
        missing.append(f"★{rec['stars']} on every stand")
    if rec["refine"] and team["refine"] < rec["refine"] - 0.5:
        missing.append(f"+{rec['refine']} items")
    gap = (rec["stars"] - team["stars"]) + max(0, rec["level"] - 5 - team["level"]) / 10
    state = "ready" if not missing else ("close" if gap <= 1 and team["size"] >= 3 and not (rec["refine"] and team["refine"] < 3) else "low")
    return {"rec": rec, "team": team, "state": state, "missing": missing, "vs": vs, "hard": hard}
