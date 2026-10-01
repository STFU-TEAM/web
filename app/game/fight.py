"""Web fight engine: parallel_process/fighthandler.py::fight_loop as a
resumable state machine (pickled in Redis between requests).
Same order of operations: terrain re-evaluated each round, basic attack
(human picks a target, taunt forces the choice), special, item specials,
end_turn for everyone, King Crimson skips a turn."""
import copy
import random
import uuid
from typing import List, Optional

from app.game.character import Character, character_from_dict
from app.game.effects import Terrain, apply_terrain_bonuses, get_active_terrain, remove_terrain_bonuses


class Side:
    def __init__(self, name: str, chars: List[Character], is_human: bool, avatar: Optional[str] = None):
        self.name = name
        self.chars = chars
        self.is_human = is_human
        self.avatar = avatar

    def alive(self) -> bool:
        return any(c.is_alive() for c in self.chars)


def valid_targets(enemies: List[Character]) -> List[int]:
    taunt = any(c.taunt and c.is_alive() for c in enemies)
    return [i for i, c in enumerate(enemies) if c.is_alive() and (not taunt or c.taunt)]


def ai_choice(enemies: List[Character]) -> int:
    """models/gameobjects/ia.py: taunt first, then highest damage, then HP."""
    alive = [(i, e) for i, e in enumerate(enemies) if e.is_alive()]
    alive.sort(key=lambda x: (not x[1].taunt, -x[1].current_damage, -x[1].current_hp))
    return alive[0][0] if alive else 0


class Fight:
    def __init__(self, human: Side, opponent: Side, kind: str = "wormhole", meta: Optional[dict] = None):
        self.id = uuid.uuid4().hex
        self.kind = kind
        self.meta = meta or {}
        self.sides = [human, opponent]
        self.log: List[dict] = []
        self.turn = 0
        self.si = 0
        self.round_started = False
        self.terrain = Terrain.DEFAULT
        self.king_crimson = False
        self.finished = False
        self.winner: Optional[int] = None
        self.rewards: Optional[dict] = None

        s0 = sum(c.current_speed for c in human.chars)
        s1 = sum(c.current_speed for c in opponent.chars)
        self.order = [0, 1]
        if s1 > s0 or (s1 == s0 and random.random() < 0.5):
            self.order = [1, 0]
        for c in self.sides[self.order[1]].chars:
            c.special_meter += 1

    @property
    def acting_side(self) -> int:
        return self.order[self.turn % 2]

    @property
    def awaiting_input(self) -> bool:
        return not self.finished and self.acting_side == 0

    @property
    def acting_char(self) -> Optional[Character]:
        side = self.sides[self.acting_side]
        return side.chars[self.si] if self.si < len(side.chars) else None

    def targets(self) -> List[int]:
        return valid_targets(self.sides[1].chars) if self.awaiting_input else []

    def _on(self) -> bool:
        return self.sides[0].alive() and self.sides[1].alive()

    def _log(self, text, kind, char=None, side=None):
        self.log.append({"turn": self.turn + 1, "text": text, "kind": kind,
                         "char_id": char.id if char else None, "side": side})

    def forfeit(self):
        for c in self.sides[0].chars:
            c.current_hp = 0
        self._log(f"{self.sides[0].name} surrendered.", "info")
        self._finish()

    def advance(self, target: Optional[int] = None) -> None:
        while self._on():
            p = self.acting_side
            player, watcher = self.sides[p], self.sides[1 - p]

            if not self.round_started:
                everyone = self.sides[0].chars + self.sides[1].chars
                remove_terrain_bonuses(everyone)
                self.terrain = get_active_terrain(everyone)
                apply_terrain_bonuses(everyone, self.terrain)
                self.round_started = True

            while self.si < len(player.chars):
                if not self._on():
                    break
                char = player.chars[self.si]
                if char.is_alive() and not char.is_stunned():
                    if player.is_human:
                        if target is None or target not in valid_targets(watcher.chars):
                            return  # wait for a (valid) pick
                        idx, target = target, None
                    else:
                        idx = ai_choice(watcher.chars)
                    targeted = watcher.chars[idx]
                    data = char.attack(targeted)
                    if data["dodged"]:
                        self._log(f"{targeted.name} dodged {char.name}'s attack.", "dodge", char, p)
                    elif data["critical"]:
                        self._log(f"{char.name} lands a critical strike on {targeted.name} for {data['damage']}.", "crit", char, p)
                    else:
                        self._log(f"{char.name} hits {targeted.name} for {data['damage']}.", "hit", char, p)
                if char.is_alive() and not char.is_stunned() and char.as_special():
                    payload, message = char.special(player.chars, watcher.chars)
                    if payload["is_a_special"]:
                        self._log(message, "special", char, p)
                        self.king_crimson |= payload.get("king_crimson", False)
                if char.is_alive():
                    for item in char.items:
                        if item.as_special():
                            message = item.special(char, player.chars, watcher.chars)
                            if message and message != "None":
                                self._log(message, "item", char, p)
                self.si += 1

            for c in player.chars + watcher.chars:
                c.end_turn()
            step = 2 if self.king_crimson else 1
            self.king_crimson = False
            self.turn += step
            self.si = 0
            self.round_started = False
            if self.turn > 300:
                self._log("The fight drags on forever. Nobody wins.", "info")
                for c in self.sides[0].chars:
                    c.current_hp = 0
                break
        self._finish()

    def _finish(self):
        if self.finished:
            return
        self.finished = True
        self.winner = 0 if (self.sides[0].alive() and not self.sides[1].alive()) else 1


def fighting_copy(chars: List[Character]) -> List[Character]:
    return [character_from_dict(copy.deepcopy(c.to_dict())) for c in chars]
