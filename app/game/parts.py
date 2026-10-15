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


NAMES = {3: "Stardust Crusaders", 4: "Diamond is Unbreakable", 5: "Golden Wind", 6: "Stone Ocean", 7: "Steel Ball Run",
         8: "JoJolion"}


def name(part) -> str:
    try:
        return NAMES[int(part)]
    except (KeyError, TypeError, ValueError):
        return ""


# part -> its watermark, drawn huge and faint behind every page in that part's colours (base.html, .part-mark):
# SVG shapes on a 100x100 box, filled with currentColor
SYMBOLS = {
    3: '<path d="M50 4 L61 38 L97 38 L68 59 L79 94 L50 72 L21 94 L32 59 L3 38 L39 38 Z"/>',  # the Joestar star
    4: '<path d="M50 4 L94 50 L50 96 L6 50 Z M50 24 L74 50 L50 76 L26 50 Z" fill-rule="evenodd"/>',  # a diamond
    5: '<path fill-rule="evenodd" d="M50 14 C74 14 88 34 88 56 C88 78 72 94 50 94 C28 94 12 78 12 56 C12 34 26 14 50 14 Z'
       ' M48 16 h4 v78 h-4 Z M34 44 a7 7 0 1 0 0.1 0 Z M66 44 a7 7 0 1 0 0.1 0 Z M33 70 a6 6 0 1 0 0.1 0 Z M67 70 a6 6 0 1 0 0.1 0 Z"/>',  # a ladybug
    6: '<ellipse cx="31" cy="36" rx="21" ry="26" transform="rotate(-25 31 36)"/><ellipse cx="69" cy="36" rx="21" ry="26" transform="rotate(25 69 36)"/>'
       '<ellipse cx="35" cy="72" rx="13" ry="17" transform="rotate(20 35 72)"/><ellipse cx="65" cy="72" rx="13" ry="17" transform="rotate(-20 65 72)"/>',  # a butterfly
    7: '<path fill-rule="evenodd" d="M18 10 h18 v44 a14 14 0 0 0 28 0 v-44 h18 v44 a32 32 0 0 1 -64 0 Z"/>',  # a horseshoe
    8: '<path d="M50 16 C58 4 74 6 76 18 C90 20 96 38 86 50 C94 64 84 82 68 80 C62 94 38 94 32 80 C16 82 6 64 14 50 C4 38 10 20 24 18 C26 6 42 4 50 16 Z"/>',  # the Rokakaka fruit
}


def mark(part) -> str:
    """The part's watermark as inline SVG markup ("" for none)."""
    try:
        shape = SYMBOLS[int(part)]
    except (KeyError, TypeError, ValueError):
        return ""
    return f'<svg viewBox="0 0 100 100" fill="currentColor" focusable="false">{shape}</svg>'


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
