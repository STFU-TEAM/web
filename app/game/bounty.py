"""Off-meta incentives: a weekly bounty that rewards winning with teams the meta skips, and the ranked meta itself
(the stands picked most this season), which the "Off the Meta" bounty reads.

One bounty a week, rotating (ISO week number). Any PvE win counts (fightturn.play_turn) when the team that fought
fits the bounty. Progress lives in user.data["web_bounty"] = {"week", "key", "progress", "claimed"}.
Ranked picks: every stand of both final teams, per season, in web:meta:<season> (a sorted set of stand ids).
"""
from typing import List, Optional

from app.db import r
from app.game.economy import dust
from app.game.gangs import week_key
from app.game.logic import GameError, now

META_KEY = "web:meta:{}"
META_TOP = 10  # "the meta": this season's most picked ranked stands

BOUNTIES = [
    {"key": "underdogs", "icon": "🐾", "name": "Underdogs", "goal": 5, "short": "wins with only R and SR stands",
     "text": "Win {goal} fights with a full team of R and SR stands (story, Tower, Mirror World, dungeon, boss rush...).",
     "reward": {"fragments": dust(3000), "items": [2]}},
    {"key": "no_legends", "icon": "🚫", "name": "No Legends", "goal": 8, "short": "wins without a UR or LR stand",
     "text": "Win {goal} fights with a full team that has no UR or LR stand.",
     "reward": {"fragments": dust(2500), "items": [38, 39]}},
    {"key": "off_meta", "icon": "🃏", "name": "Off the Meta", "goal": 5, "short": "wins without this season's top 10 ranked picks",
     "text": "Win {goal} fights with a full team that has none of this season's {top} most picked ranked stands.",
     "reward": {"fragments": dust(3000), "items": [2]}},
]
BY_KEY = {b["key"]: b for b in BOUNTIES}


def current(when=None) -> dict:
    week = (when or now()).isocalendar()[1]
    return BOUNTIES[week % len(BOUNTIES)]


def fits(bounty: dict, team) -> bool:
    if len(team) < 3:
        return False
    if bounty["key"] == "underdogs":
        return all(c.rarity in ("R", "SR") for c in team)
    if bounty["key"] == "no_legends":
        return not any(c.rarity in ("UR", "LR") for c in team)
    if bounty["key"] == "off_meta":
        top = {m["id"] for m in meta(limit=META_TOP)}
        return not any(c.id in top for c in team)
    return False


def _state(user) -> dict:
    b = current()
    s = user.data.get("web_bounty")
    if not s or s.get("week") != week_key() or s.get("key") != b["key"]:
        s = {"week": week_key(), "key": b["key"], "progress": 0, "claimed": False}
        user.data["web_bounty"] = s
    return s


def view(user) -> dict:
    b, s = current(), _state(user)
    from app.game.items import item_file
    reward = [f"{b['reward']['fragments']:,} Meteor Dust"] + [item_file[i - 1]["name"] for i in b["reward"].get("items", [])]
    return {**b, "text": b["text"].format(goal=b["goal"], top=META_TOP), "progress": min(s["progress"], b["goal"]),
            "done": s["progress"] >= b["goal"], "claimed": s["claimed"], "reward_text": ", ".join(reward)}


def record_win(user, team) -> Optional[str]:
    """Count a PvE win if the team fits this week's bounty. Returns a line for the fight's rewards, or None."""
    b, s = current(), _state(user)
    if s["claimed"] or s["progress"] >= b["goal"] or not fits(b, team):
        return None
    s["progress"] += 1
    return f"{b['icon']} {b['name']} bounty {s['progress']}/{b['goal']}" + (": claim it!" if s["progress"] >= b["goal"] else "")


def claim(user) -> dict:
    b, s = current(), _state(user)
    if s["claimed"]:
        raise GameError("This week's bounty is already claimed.")
    if s["progress"] < b["goal"]:
        raise GameError(f"{s['progress']}/{b['goal']}: not done yet.")
    from app.game.items import item_from_dict
    user.fragments += b["reward"]["fragments"]
    for i in b["reward"].get("items", []):
        user.items.append(item_from_dict({"id": i}))
    s["claimed"] = True
    return view(user)


# ── The ranked meta ──────────────────────────────────────────────────────
def record_picks(stand_ids, sid: Optional[str] = None) -> None:
    from app.game import seasons
    key = META_KEY.format(sid or seasons.season_id())
    pipe = r().pipeline()
    for cid in stand_ids:
        pipe.zincrby(key, 1, int(cid))
    pipe.expire(key, 120 * 86400)
    pipe.execute()


def meta(limit: int = 10, sid: Optional[str] = None) -> List[dict]:
    """This season's most picked ranked stands: [{id, name, rarity, picks, share}] (share: % of teams)."""
    from app.game import seasons
    from app.game.character import CHARACTER_FILE
    key = META_KEY.format(sid or seasons.season_id())
    rows = r().zrevrange(key, 0, limit - 1, withscores=True)
    total = sum(int(s) for _, s in r().zrange(key, 0, -1, withscores=True)) or 1
    teams = max(1, total / 3)
    out = []
    for cid, picks in rows:
        cid = int(cid)
        t = CHARACTER_FILE[cid - 1]
        out.append({"id": cid, "name": t["name"], "rarity": t["rarity"], "picks": int(picks),
                    "share": round(100 * picks / teams)})
    return out
