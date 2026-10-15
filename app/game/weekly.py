"""The Weekly Road: a reward track that never runs out. Playing earns points (POINTS, counted through
quests.track_quest_progress), and each week's points open the same TIERS again, so a player who has finished every
first clear still has something steady to pull with. Resets every Monday (gangs.week_key).

Progress lives in user.data["web_road"] = {"week", "points", "claimed": [tier indexes]}.
"""
from typing import List

from app.game.economy import dust
from app.game.gangs import week_key
from app.game.logic import GameError

# points per counted action (quest action names): every win, a Mirror World trip, a tower floor, a dungeon run...
POINTS = {"fight_win": 1, "wormhole_complete": 1, "tower_floor": 1, "raid_attack": 2, "rush_boss": 2,
          "dungeon_complete": 4, "daily_claim": 5}
# (points, reward): a casual week (~20 points a day) reaches the third tier, an hour a day the fifth
TIERS = [
    (30, {"fragments": dust(5000)}),
    (70, {"items": [2]}),
    (120, {"discs": 40}),
    (180, {"super": 1}),
    (250, {"items": [2], "discs": 60}),
]


def _state(user) -> dict:
    s = user.data.get("web_road")
    if not s or s.get("week") != week_key():
        s = {"week": week_key(), "points": 0, "claimed": []}
        user.data["web_road"] = s
    return s


def add(user, action: str, count: int = 1) -> None:
    pts = POINTS.get(action)
    if pts:
        _state(user)["points"] += pts * max(1, count)


def reward_text(reward: dict) -> List[str]:
    from app.game.items import item_file
    out = []
    if reward.get("fragments"):
        out.append(f"{reward['fragments']:,} Meteor Dust")
    if reward.get("super"):
        out.append(f"{reward['super']} Arrowhead")
    out += [item_file[i - 1]["name"] for i in reward.get("items", [])]
    if reward.get("discs"):
        out.append(f"{reward['discs']} Stand Discs")
    return out


def view(user) -> dict:
    s = _state(user)
    top = TIERS[-1][0]
    tiers = [{"i": i, "points": p, "reward": ", ".join(reward_text(r)), "claimed": i in s["claimed"],
              "ready": s["points"] >= p and i not in s["claimed"]} for i, (p, r) in enumerate(TIERS)]
    return {"points": s["points"], "top": top, "tiers": tiers, "ready": sum(t["ready"] for t in tiers),
            "pct": min(100, 100 * s["points"] // top)}


def claim(user) -> List[str]:
    """Every tier reached and not yet claimed this week."""
    from app.game.items import item_from_dict
    s = _state(user)
    got = []
    for i, (p, reward) in enumerate(TIERS):
        if s["points"] < p or i in s["claimed"]:
            continue
        user.fragments += reward.get("fragments", 0)
        user.super_fragments += reward.get("super", 0)
        for item_id in reward.get("items", []):
            user.items.append(item_from_dict({"id": item_id}))
        if reward.get("discs"):
            user.data["web_discs"] = int(user.data.get("web_discs", 0)) + reward["discs"]
        s["claimed"].append(i)
        if p >= 70:  # the guided path's "70 points on the Weekly Road" step
            user.data.setdefault("web_path_flags", {})["road"] = 1
        got += reward_text(reward)
    if not got:
        raise GameError(f"Nothing to claim yet: the next tier opens at {next((p for p, _ in TIERS if p > s['points']), TIERS[-1][0])} points.")
    return got
