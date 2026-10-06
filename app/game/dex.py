"""Stand Dex: collection sets (every stand of a rarity, every member of a synergy group) with a reward
for completing each one.

A stand counts once it has ever been owned on the site: data["web_dex"] keeps every stand id seen in the
collection (User.to_dict adds the current collection on every web save, and the dex page on every read),
so releasing, fusing or trading a copy never undoes progress.
Save: data["web_dex"] = [stand ids], data["web_sets_claimed"] = [set keys]
"""
from typing import List

from app.game.character import CHARACTER_FILE

PLAYABLE_IDS = {c["id"] for c in CHARACTER_FILE if c["universe"] != "Dummy"}
RARITY_REWARDS = {"R": {"fragments": 1050}, "SR": {"fragments": 2100},  # at the economy's pace (economy.py)
                  "SSR": {"fragments": 3500, "super": 1}, "UR": {"fragments": 5600, "super": 2},
                  "LR": {"fragments": 8400, "super": 3}}
GROUP_REWARD_PER_STAND = 175  # synergy sets pay Meteor Dust by size
MIN_GROUP = 3
RARITY_NAMES = {"R": "Common", "SR": "Rare", "SSR": "Epic", "UR": "Legend", "LR": "Mythic"}


def _sets() -> List[dict]:
    from app.game.characterabilities import SYNERGIES, SYNERGY_INFO
    out = []
    for rarity, reward in RARITY_REWARDS.items():
        ids = sorted(c["id"] for c in CHARACTER_FILE if c["rarity"] == rarity and c["id"] in PLAYABLE_IDS)
        out.append({"key": f"rarity:{rarity}", "kind": "rarity", "name": f"Every {rarity} stand", "icon": rarity,
                    "rarity": rarity, "ids": ids, "reward": reward, "title": f"{RARITY_NAMES[rarity]} collector"})
    for key, members in SYNERGIES.items():
        ids = sorted(set(members) & PLAYABLE_IDS)
        if len(ids) < MIN_GROUP:
            continue
        label, icon = SYNERGY_INFO.get(key, (key, "✶"))
        out.append({"key": f"group:{key}", "kind": "group", "name": label, "icon": icon, "ids": ids,
                    "reward": {"fragments": GROUP_REWARD_PER_STAND * len(ids)}, "title": None})
    return out


SETS = _sets()
SET_BY_KEY = {s["key"]: s for s in SETS}


def seen(user) -> set:
    """Every stand ever owned here, updated with the current collection (the caller saves if it changed)."""
    have = {c.id for c in user.main_characters + user.storage_characters} & PLAYABLE_IDS
    known = set(user.data.get("web_dex") or [])
    if not have <= known:
        known |= have
        user.data["web_dex"] = sorted(known)
    return known


def view(user) -> List[dict]:
    known = seen(user)
    claimed = set(user.data.get("web_sets_claimed") or [])
    out = []
    for s in SETS:
        have = [i for i in s["ids"] if i in known]
        out.append({**s, "have": len(have), "total": len(s["ids"]), "owned": set(have),
                    "pct": int(100 * len(have) / len(s["ids"])), "complete": len(have) == len(s["ids"]),
                    "claimed": s["key"] in claimed})
    return out


def claim(user, key: str) -> dict:
    from app.game import titles
    from app.game.logic import GameError
    s = SET_BY_KEY.get(key)
    if not s:
        raise GameError("That set doesn't exist.")
    claimed = list(user.data.get("web_sets_claimed") or [])
    if key in claimed:
        raise GameError("You already claimed this set.")
    missing = [i for i in s["ids"] if i not in seen(user)]
    if missing:
        raise GameError(f"{len(missing)} stand{'s' if len(missing) > 1 else ''} still missing from this set.")
    user.fragments += s["reward"].get("fragments", 0)
    user.super_fragments += s["reward"].get("super", 0)
    if s["title"]:
        titles.grant(user, s["title"])
    claimed.append(key)
    user.data["web_sets_claimed"] = claimed
    return s


def reward_text(reward: dict) -> str:
    parts = [f"{reward['fragments']:,} Meteor Dust"] if reward.get("fragments") else []
    if reward.get("super"):
        parts.append(f"{reward['super']} Arrowhead{'s' if reward['super'] > 1 else ''}")
    return " + ".join(parts)


def ready_count(user) -> int:
    return sum(1 for s in view(user) if s["complete"] and not s["claimed"])
