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


RANK = {"UNIVERSAL": "A", "SUPREME": "B", "GREAT": "C", "GOOD": "D", "SUB_PAR": "E", "BAD": "F"}


def owned(chars: Iterable, prefix: str = "", disable: Optional[Callable] = None, note: Optional[Callable] = None,
          notes: Optional[dict] = None, blocked: Optional[dict] = None, sort: bool = True) -> List[dict]:
    """The player's stands, strongest first. disable(c) / blocked[uuid] -> why it can't be picked; note(c) /
    notes[uuid] -> extra text for its line (templates pass the dicts)."""
    from app.filters import power_score
    chars = list(chars)
    out = []
    for c in sorted(chars, key=lambda c: -power_score(c)) if sort else chars:
        meta = f"Lv {c.level}" + (f" ★{c.awaken}" if c.awaken else "")
        if c.types:
            meta += " · " + " ".join(f"{t.title()} {RANK.get(q, '')}".strip() for t, q in zip(c.types, c.qualities))
        extra = (note(c) if note else None) or (notes or {}).get(c.uuid)
        why = (disable(c) if disable else None) or (blocked or {}).get(c.uuid)
        out.append({"v": prefix + c.uuid, "id": c.id, "n": c.name, "r": c.rarity, "lv": c.level, "aw": c.awaken,
                    "sh": bool(getattr(c, "shiny", False)), "t": bool(c.taunt), "img": stand_img(c.id),
                    "m": meta + (f" · {extra}" if extra else ""), "g": "mine", "x": why})
    return out


def pool(templates: Iterable, prefix: str = "") -> List[dict]:
    """Stands from the encyclopedia (dicts from characters.json), e.g. a banner's pool."""
    return [{"v": f"{prefix}{t['id']}", "id": t["id"], "n": t["name"], "r": t["rarity"], "t": bool(t.get("taunt")),
             "img": stand_img(t["id"]), "m": t.get("universe", ""), "g": "any"} for t in templates]


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


def _item_look(it: dict) -> dict:
    m = _EMOJI.match(it.get("emoji") or "")
    img = f"https://cdn.discordapp.com/emojis/{m.group(3)}.{'gif' if m.group(1) else 'webp'}?size=64" if m else None
    return {"e": None if img else it.get("emoji"), "img": img}


def _item_kind(it: dict) -> str:
    return "gear" if it.get("is_equipable") else "usable"


def owned_items(items: Iterable, equipable: Optional[bool] = None, tradable: bool = False) -> List[dict]:
    """The player's items, one option per kind with how many they own (q). equipable: only gear (True), only the rest
    (False) or both (None); tradable: leave out bound items."""
    counts = {}
    for item in items:
        if tradable and getattr(item, "bound", False):
            continue
        counts[item.id] = counts.get(item.id, 0) + 1
    out = []
    for iid in sorted(counts, key=lambda i: (not item_file[i - 1].get("is_equipable"), item_file[i - 1]["name"])):
        it = item_file[iid - 1]
        if equipable is not None and bool(it.get("is_equipable")) != equipable:
            continue
        line = item_line(it) if it.get("is_equipable") else ("Consumable" if it.get("is_usable") else "Material")
        out.append({"v": str(iid), "id": iid, "n": it["name"], "q": counts[iid], **_item_look(it),
                    "m": f"×{counts[iid]} · {line}", "g": _item_kind(it), "t": bool(it.get("taunt"))})
    return out


def catalog_items() -> List[dict]:
    """Every item in the game (the admin's gift form)."""
    return [{"v": str(it["id"]), "id": it["id"], "n": it["name"], **_item_look(it), "g": _item_kind(it),
             "m": f"#{it['id']} · " + (item_line(it) if it.get("is_equipable") else
                                      ("Consumable" if it.get("is_usable") else "Material"))} for it in item_file]


def item_ids() -> set:
    return {o["id"] for o in items()}
