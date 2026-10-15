"""The story's world map (story.html, partials/world_map.html): each part is a pin where it happens, joined by the
route the JoJos travel, over a low-poly world. Coordinates are longitude/latitude; the map shows WEST..EAST and
NORTH..SOUTH (the northern band where the story happens), mapped to an SVG box of the same size in degrees.
"""
from typing import Dict, List

WEST, EAST, NORTH, SOUTH = -130, 172, 72, 0

# part -> (place, longitude, latitude, label anchor: "above" | "below" | "left" | "right")
PLACES: Dict[int, tuple] = {
    0: ("Tokyo", 131.0, 30.5, "below"),                  # the prologue: the Arrow (pins nudged apart: Japan is small)
    3: ("Cairo", 31.2, 30.0, "below"),
    4: ("Morioh", 142.0, 39.5, "left"),
    5: ("Naples", 14.3, 40.8, "above"),
    6: ("Florida", -81.7, 27.9, "below"),
    7: ("San Diego to New York", -98.0, 39.5, "above"),
    8: ("Morioh, 2011", 153.5, 48.5, "above"),
}

# a low-poly world: (longitude, latitude) outlines, enough to read the continents
LAND: List[List[tuple]] = [
    # North America
    [(-165, 68), (-140, 70), (-110, 72), (-85, 70), (-75, 62), (-62, 55), (-58, 48), (-66, 44), (-70, 41), (-76, 35),
     (-81, 30), (-80, 25), (-84, 30), (-90, 29), (-97, 26), (-97, 20), (-90, 16), (-84, 11), (-78, 8), (-85, 13),
     (-92, 15), (-105, 20), (-110, 24), (-117, 32), (-124, 40), (-124, 48), (-133, 56), (-147, 60), (-160, 59), (-165, 63)],
    # Greenland
    [(-55, 60), (-45, 60), (-20, 70), (-20, 80), (-60, 82), (-70, 77), (-55, 70)],
    # South America
    [(-80, 9), (-72, 12), (-60, 10), (-50, 0), (-35, -5), (-37, -12), (-40, -22), (-48, -26), (-58, -38), (-65, -41),
     (-68, -50), (-74, -52), (-72, -42), (-71, -30), (-70, -18), (-76, -12), (-81, -5), (-79, 2)],
    # Europe
    [(-10, 36), (-9, 43), (-1, 46), (-5, 48), (2, 51), (8, 54), (5, 58), (10, 63), (20, 70), (30, 71), (40, 67), (42, 60),
     (30, 55), (28, 45), (40, 42), (28, 41), (24, 38), (20, 40), (16, 38), (12, 44), (8, 44), (3, 43), (-1, 37)],
    # Britain
    [(-6, 50), (2, 51), (-2, 56), (-5, 58), (-6, 55)],
    # Africa
    [(-17, 21), (-17, 15), (-12, 7), (-5, 5), (8, 4), (9, -1), (13, -6), (12, -17), (15, -27), (20, -35), (28, -33),
     (33, -26), (35, -20), (40, -15), (40, -5), (43, 0), (51, 12), (43, 12), (37, 18), (33, 30), (25, 32), (11, 33),
     (10, 37), (-6, 36), (-10, 30)],
    # Asia
    [(30, 55), (42, 60), (60, 70), (80, 73), (105, 78), (140, 72), (170, 68), (180, 66), (170, 60), (160, 55), (142, 52),
     (140, 42), (135, 35), (127, 35), (122, 30), (120, 22), (108, 20), (106, 10), (100, 13), (100, 5), (103, 1), (98, 8),
     (92, 20), (85, 22), (80, 15), (77, 8), (72, 20), (66, 25), (57, 25), (52, 28), (48, 30), (44, 38), (40, 42)],
    # Japan
    [(130, 31), (135, 34), (140, 35), (142, 40), (141, 45), (139, 40), (135, 36), (131, 34)],
    # Australia
    [(114, -22), (122, -18), (130, -12), (137, -12), (142, -11), (146, -19), (153, -26), (150, -37), (140, -38),
     (132, -32), (115, -34)],
]


def xy(lon: float, lat: float) -> tuple:
    return round(lon - WEST, 1), round(NORTH - lat, 1)


def view(journey: list) -> dict:
    """The map for story.html's journey rows ({part, title, color, cleared, stages}): the land outlines, a pin per
    part (with how far it is cleared, as a fraction, and whether it's the one being played) and the route."""
    width, height = EAST - WEST, NORTH - SOUTH
    land = [" ".join(f"{x},{y}" for x, y in (xy(lon, lat) for lon, lat in poly)) for poly in LAND]
    pins, current_found = [], False
    for p in journey:
        part = p.get("part") or 0
        if part not in PLACES:
            continue
        place, lon, lat, anchor = PLACES[part]
        x, y = xy(lon, lat)
        total = len(p["stages"]) or 1
        done = p["cleared"] >= total
        current = not done and not current_found and p["cleared"] < total
        current_found = current_found or current
        pins.append({"part": part, "place": place, "anchor": anchor, "color": p["color"], "title": p["title"],
                     "x": round(100 * x / width, 2), "y": round(100 * y / height, 2), "px": x, "py": y,
                     "frac": round(p["cleared"] / total, 3), "done": done, "current": current,
                     "started": p["cleared"] > 0})
    route = " ".join(f"{p['px']},{p['py']}" for p in pins)
    reached = [p for p in pins if p["done"] or p["current"]]
    done_route = " ".join(f"{p['px']},{p['py']}" for p in reached)
    return {"w": width, "h": height, "land": land, "pins": pins, "route": route, "done_route": done_route}
