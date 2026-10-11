"""Part palettes: each JoJo part has its colours, and a page about one part (a story chapter, an Alternate Universe
chapter, a stand's page, a Carry Me act) takes them on (base.html sets data-part and --part / --part-2 on <body>).
"""
from typing import Optional

# part -> (main colour, light accent)
COLORS = {
    3: ("#7A3FB8", "#F4C542"),   # Stardust Crusaders: violet and gold
    4: ("#D6246E", "#FF9EC7"),   # Diamond is Unbreakable: pink
    5: ("#E3A93A", "#FFE07A"),   # Golden Wind: gold
    6: ("#2BB3A8", "#8BE3C0"),   # Stone Ocean: teal and green
    7: ("#C8642B", "#F2C27A"),   # Steel Ball Run: desert orange
    8: ("#3A6FD8", "#9FD3FF"),   # JoJolion: sailor blue
}


def style(part) -> str:
    """The inline CSS variables for a part ("" for none)."""
    try:
        main, light = COLORS[int(part)]
    except (KeyError, TypeError, ValueError):
        return ""
    return f"--part: {main}; --part-2: {light};"


def of_stand(stand_id: int) -> Optional[int]:
    """The part a stand comes from (by its part synergy group), or None."""
    from app.game.characterabilities import PART_GROUPS, SYNERGIES
    for key, part in PART_GROUPS.items():
        if stand_id in SYNERGIES.get(key, ()):
            return part
    return None
