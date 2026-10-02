"""Web fight engine: parallel_process/fighthandler.py::fight_loop as a
resumable state machine (pickled in Redis between requests).
Each side's turn: terrain re-evaluated, then every stand of the acting side
makes a basic attack (human picks a target, taunt forces the choice), its
special when the meter is full, and item specials. Effects and meters tick
only at the end of their owner's turn. Sudden death and a round cap keep
fights short."""
import copy
import random
import uuid
from typing import List, Optional

from app.game.character import Character, character_from_dict
from app.game.effects import Terrain, apply_terrain_bonuses, get_active_terrain, remove_terrain_bonuses

# Fights stay short: from this round every stand loses a growing share of its health
# at the end of its turn and heals for half, and the fight is called at MAX_ROUNDS.
SUDDEN_DEATH_ROUND = 10
SUDDEN_DEATH_STEP = 0.05
SUDDEN_DEATH_HEAL = 0.5
MAX_ROUNDS = 18


class Side:
    def __init__(self, name: str, chars: List[Character], is_human: bool, avatar: Optional[str] = None):
        self.name = name
        self.chars = chars
        self.is_human = is_human
        self.ai = "smart"  # "easy" for gentle PvE opponents
        self.avatar = avatar

    def alive(self) -> bool:
        return any(c.is_alive() for c in self.chars)


def valid_targets(enemies: List[Character]) -> List[int]:
    taunt = any(c.taunt and c.is_alive() for c in enemies)
    return [i for i, c in enumerate(enemies) if c.is_alive() and (not taunt or c.taunt)]


AI_LEVELS = ("easy", "smart")


def _expected_hit(attacker: Optional[Character], target: Character) -> float:
    """Rough damage of one basic attack, with the same armor curve as Character.attack."""
    if attacker is None:
        return 0
    armor = min(max(target.current_armor, 0), 400)
    return attacker.current_damage * 200 / (100 + armor)


def ai_choice(enemies: List[Character], attacker: Optional[Character] = None, level: str = "smart") -> int:
    """Pick a target among the legal ones (taunt first).
    easy: random. smart: finish off anything this hit kills (the most dangerous first),
    otherwise focus the target with the best threat per health left; a charged special
    counts as extra threat."""
    legal = valid_targets(enemies)
    if not legal:
        return 0
    if level == "easy":
        return random.choice(legal)
    hit = {i: _expected_hit(attacker, enemies[i]) for i in legal}

    def threat(c: Character) -> float:
        charged = c.special_meter + 1 >= c.turn_for_ability
        return c.current_damage * (1.5 if charged else 1) + c.current_critical

    killable = [i for i in legal if hit[i] >= enemies[i].current_hp]
    if killable:
        return max(killable, key=lambda i: threat(enemies[i]))
    return max(legal, key=lambda i: threat(enemies[i]) / max(1, enemies[i].current_hp - hit[i]))


class Fight:
    sudden_death_round = SUDDEN_DEATH_ROUND
    def __init__(self, human: Side, opponent: Side, kind: str = "wormhole", meta: Optional[dict] = None,
                 human_side: int = 0):
        self.id = uuid.uuid4().hex
        self.kind = kind
        self.meta = meta or {}
        self.sides = [human, opponent]
        self.human_side = human_side
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
        return not self.finished and self.sides[self.acting_side].is_human

    @property
    def acting_char(self) -> Optional[Character]:
        side = self.sides[self.acting_side]
        return side.chars[self.si] if self.si < len(side.chars) else None

    def expected_hit(self, idx: int) -> int:
        """What the acting stand's basic attack should deal to enemy idx (before crits and dodges)."""
        watcher = self.sides[1 - self.acting_side]
        return int(_expected_hit(self.acting_char, watcher.chars[idx]))

    @property
    def special_ready(self) -> bool:
        """The acting stand fires its special right after this attack."""
        char = self.acting_char
        return bool(char) and char.is_alive() and char.as_special()

    def targets(self) -> List[int]:
        if not self.awaiting_input:
            return []
        watcher = self.sides[1 - self.acting_side]
        return valid_targets(watcher.chars)

    def _on(self) -> bool:
        return self.sides[0].alive() and self.sides[1].alive()

    def _log(self, text, kind, char=None, side=None, src=None, dst=None, dmg=None):
        """src/dst are [side, index] so the web view can animate who hit whom;
        hp is every fighter's HP right after the event, to replay the bars."""
        for s in self.sides:  # safety net: nothing heals past max health
            for c in s.chars:
                c.current_hp = min(c.current_hp, c.start_hp)
        self.log.append({"turn": self.turn + 1, "text": text, "kind": kind,
                         "char_id": char.id if char else None, "side": side,
                         "src": src, "dst": dst, "dmg": dmg,
                         "hp": [[max(c.current_hp, 0) for c in s.chars] for s in self.sides]})

    @property
    def round(self) -> int:
        return self.turn // 2 + 1

    @property
    def sudden_death(self) -> bool:
        return self.round >= self.sudden_death_round

    def forfeit(self, side: int = 0):
        for c in self.sides[side].chars:
            c.current_hp = 0
        self._log(f"{self.sides[side].name} surrendered.", "info", side=side)
        self._finish()

    def _start_turn(self, p: int) -> None:
        for s, side in enumerate(self.sides):
            for c in side.chars:
                c._my_turn = s == p  # effects landing on your own turn don't tick away at its end
                c._heal_mult = SUDDEN_DEATH_HEAL if self.sudden_death else 1
        everyone = self.sides[0].chars + self.sides[1].chars
        before = self.terrain
        remove_terrain_bonuses(everyone)
        self.terrain = get_active_terrain(everyone)
        apply_terrain_bonuses(everyone, self.terrain)
        if self.terrain != before:
            self._log(f"{self.terrain.emoji} The field becomes {self.terrain.display_name}. {self.terrain.rule}"
                      if self.terrain != Terrain.DEFAULT else "🏞️ The field returns to neutral ground.", "terrain")
        self.round_started = True

    def _end_turn(self, p: int) -> None:
        side = self.sides[p]
        for c in side.chars:
            c.end_turn()
        if self.sudden_death and side.alive():
            pct = SUDDEN_DEATH_STEP * (self.round - SUDDEN_DEATH_ROUND + 1)
            for c in side.chars:
                if c.is_alive():
                    c.take(c.start_hp * pct)
            self._log(f"⏳ Sudden death: {side.name}'s stands lose {round(pct * 100)}% of their health.", "sudden", side=p)

    def _time_up(self) -> None:
        share = [sum(max(c.current_hp, 0) for c in s.chars) / max(1, sum(c.start_hp for c in s.chars))
                 for s in self.sides]
        loser = 0 if share[0] < share[1] else 1
        self._log(f"Time is up! {self.sides[1 - loser].name} wins with more health left.", "info")
        for c in self.sides[loser].chars:
            c.current_hp = 0

    def advance(self, target: Optional[int] = None) -> None:
        while self._on():
            p = self._last_actor = self.acting_side
            player, watcher = self.sides[p], self.sides[1 - p]

            if not self.round_started:
                self._start_turn(p)

            while self.si < len(player.chars):
                if not self._on():
                    break
                char = player.chars[self.si]
                stunned = char.is_alive() and char.is_stunned()
                if stunned:
                    char._skipped = True
                    self._log(f"{char.name} is stunned and loses its turn.", "stun", char, p, src=[p, self.si])
                elif char.is_alive():
                    if player.is_human:
                        if target is None or target not in valid_targets(watcher.chars):
                            return  # wait for a (valid) pick
                        idx, target = target, None
                    else:
                        idx = ai_choice(watcher.chars, char, getattr(player, "ai", "smart"))
                    targeted = watcher.chars[idx]
                    char._focus = targeted  # single-target specials follow the chosen target
                    data = char.attack(targeted)
                    hit = {"src": [p, self.si], "dst": [1 - p, idx]}
                    if data["dodged"]:
                        self._log(f"{targeted.name} dodged {char.name}'s attack.", "dodge", char, p, **hit)
                    elif data["critical"]:
                        self._log(f"{char.name} lands a critical strike on {targeted.name} for {data['damage']}.", "crit", char, p,
                                  dmg=data["damage"], **hit)
                    else:
                        self._log(f"{char.name} hits {targeted.name} for {data['damage']}.", "hit", char, p,
                                  dmg=data["damage"], **hit)
                if char.is_alive() and not stunned and char.as_special():
                    payload, message = char.special(player.chars, watcher.chars)
                    if payload["is_a_special"]:
                        self._log(message, "special", char, p, src=[p, self.si])
                        self.king_crimson |= payload.get("king_crimson", False)
                if char.is_alive():
                    for item in char.items:
                        if item.as_special():
                            message = item.special(char, player.chars, watcher.chars)
                            if message and message != "None":
                                self._log(message, "item", char, p, src=[p, self.si])
                self.si += 1

            self._end_turn(p)
            step = 2 if self.king_crimson else 1
            self.king_crimson = False
            self.turn += step
            self.si = 0
            self.round_started = False
            if self._on() and self.round > MAX_ROUNDS:
                self._time_up()
                break
        self._finish()

    def _finish(self):
        if self.finished:
            return
        self.finished = True
        alive = [index for index, side in enumerate(self.sides) if side.alive()]
        if alive:
            self.winner = alive[0]
        else:  # both teams fell on the same move: it goes to whoever made it
            self.winner = getattr(self, "_last_actor", None)


def fighting_copy(chars: List[Character]) -> List[Character]:
    return [character_from_dict(copy.deepcopy(c.to_dict())) for c in chars]
