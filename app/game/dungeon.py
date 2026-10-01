"""Dungeon map and event data ported from the bot's map_0.json."""
import random


LAYOUT = (
    "0000010000",
    "0111110110",
    "0101000100",
    "0101111101",
    "0000000101",
    "0111110101",
    "0000010101",
    "0111010101",
    "0100000000",
)
START = (0, 0)
EXIT = (9, 8)

FIGHTS = {
    (0, 7): (51, 53, 54),
    (2, 3): (58, 56, 59),
    (6, 4): (18, 19, 20),
    (7, 8): (24, 21, 23),
    (8, 2): (79, 80, 81),
    (8, 7): (71, 72, 57),
}
CHESTS = {
    (0, 8): ((8, 0.9), (13, 0.1)),
    (2, 2): ((7, 0.8), (14, 0.1), (18, 0.1)),
    (4, 3): ((10, 0.85), (15, 0.1), (12, 0.05)),
}
BOMBS = {(4, 7), (6, 1)}


def valid_position(position):
    x, y = position
    return 0 <= y < len(LAYOUT) and 0 <= x < len(LAYOUT[y]) and LAYOUT[y][x] == "0"


def allowed_moves(position):
    x, y = position
    return [direction for direction, target in (
        ("up", (x, y - 1)), ("down", (x, y + 1)),
        ("left", (x - 1, y)), ("right", (x + 1, y)),
    ) if valid_position(target)]


def moved_position(position, direction):
    delta = {"up": (0, -1), "down": (0, 1), "left": (-1, 0), "right": (1, 0)}.get(direction)
    if delta is None:
        return None
    target = (position[0] + delta[0], position[1] + delta[1])
    return target if valid_position(target) else None


def event_at(position):
    if position in FIGHTS:
        return "fight"
    if position in CHESTS:
        return "chest"
    if position in BOMBS:
        return "bomb"
    if position == EXIT:
        return "exit"
    return None


def chest_item(position):
    entries = CHESTS[position]
    return random.choices([item_id for item_id, _ in entries], weights=[weight for _, weight in entries], k=1)[0]


def map_cells(position, triggered):
    cells = []
    for y, row in enumerate(LAYOUT):
        for x, wall in enumerate(row):
            coord = (x, y)
            cells.append({
                "x": x, "y": y, "wall": wall == "1", "current": coord == tuple(position),
                "exit": coord == EXIT, "event": event_at(coord), "seen": f"{x}:{y}" in triggered,
            })
    return cells
