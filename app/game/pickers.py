"""Options for the stand / item picker (templates/partials/picker.html + app.js): one compact dict per choice.

    v  value posted       id stand id (one-copy rules)   n name      r rarity     lv level   aw stars
    sh shiny              t  taunts                      img picture e emoji      m  one line under the name
    g  group ("mine", "any", "item")                     x  why it can't be picked (shown, greyed)
    best type that powers its special (stands you don't own: the planner pre-selects it)
"""
import re
from typing import Callable, Iterable, List, Optional

from flask import current_app

from app.game.character import CHARACTER_FILE
from app.game.items import item_file

NO_PLANNER_ITEMS = {33}  # the raid boss's singularity
_EMOJI = re.compile(r"<(a?):(\w+):(\d+)>")


def stand_img(stand_id) -> str:
    cfg = current_app.config
    return cfg["IMAGE_BASE_URL"] + cfg["IMAGE_PATH"].format(id=stand_id)


def owned(chars: Iterable, prefix: str = "", disable: Optional[Callable] = None, note: Optional[Callable] = None) -> List[dict]:
    """The player's stands, strongest first. disable(c) -> reason or None; note(c) -> extra text for the line."""
    from app.filters import power_score
    out = []
    for c in sorted(chars, key=lambda c: -power_score(c)):
        meta = f"Lv {c.level}" + (f" ★{c.awaken}" if c.awaken else "")
        if c.types:
            meta += f" · {c.types[0].title()}"
        extra = note(c) if note else None
        out.append({"v": prefix + c.uuid, "id": c.id, "n": c.name, "r": c.rarity, "lv": c.level, "aw": c.awaken,
                    "sh": bool(getattr(c, "shiny", False)), "t": bool(c.taunt), "img": stand_img(c.id),
                    "m": meta + (f" · {extra}" if extra else ""), "g": "mine", "x": disable(c) if disable else None})
    return out


def every_stand(prefix: str = "s:") -> List[dict]:
    from app.game.planner import best_type
    order = {"LR": 0, "UR": 1, "SSR": 2, "SR": 3, "R": 4}
    stands = sorted((c for c in CHARACTER_FILE if c["universe"] != "Dummy"), key=lambda c: (order[c["rarity"]], c["name"]))
    return [{"v": f"{prefix}{c['id']}", "id": c["id"], "n": c["name"], "r": c["rarity"], "t": bool(c["taunt"]),
             "img": stand_img(c["id"]), "m": c["universe"], "g": "any", "best": best_type(c["id"])} for c in stands]


def item_line(it: dict) -> str:
    parts = [f"+{it[k]} {label}" for k, label in (("bonus_hp", "HP"), ("bonus_damage", "ATK"), ("bonus_armor", "ARM"),
                                                    ("bonus_speed", "SPD"), ("bonus_critical", "CRT")) if it.get(k)]
    if it.get("taunt"):
        parts.append("taunt")
    return ", ".join(parts) or "special only"


def items() -> List[dict]:
    out = []
    for it in item_file:
        if not it.get("is_equipable") or it["id"] in NO_PLANNER_ITEMS:
            continue
        m = _EMOJI.match(it.get("emoji") or "")
        img = f"https://cdn.discordapp.com/emojis/{m.group(3)}.{'gif' if m.group(1) else 'webp'}?size=64" if m else None
        out.append({"v": str(it["id"]), "id": it["id"], "n": it["name"], "e": None if img else it.get("emoji"), "img": img,
                    "m": item_line(it), "g": "item", "t": bool(it.get("taunt"))})
    return out


def item_ids() -> set:
    return {o["id"] for o in items()}
