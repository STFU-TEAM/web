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
# The side that moves second: its specials start one turn closer, and it opens in a counter stance
# (more armor and damage for its first turns), so a faster team wins the tempo, not the fight.
COUNTER_ARMOR, COUNTER_DAMAGE, COUNTER_TURNS = 0.05, 0.05, 2
COUNTER_CRIT_PER_GAP, COUNTER_CRIT_MAX = 1, 15  # +1 critical per point of team speed it gave up, for the fight


class Side:
    def __init__(self, name: str, chars: List[Character], is_human: bool, avatar: Optional[str] = None,
                 parts: Optional[bool] = None):
        self.name = name
        self.chars = chars
        self.is_human = is_human
        self.parts = parts  # part synergies: None = only if a player built the team (is_human)
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


PVP_KINDS = ("ranked", "friend")
SIMULATABLE = ("wormhole", "story", "tower", "rush", "dungeon", "alt_universe", "over_heaven", "training")  # PvE a loss can replay
CRIT_WORDS = {1: "", 2: "DOUBLE", 3: "TRIPLE"}


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
        # Both teams as they walked in (carried health, tower growth), before any boost, for "Simulate this fight"
        self.start_teams = [copy.deepcopy(human.chars), copy.deepcopy(opponent.chars)] if kind in SIMULATABLE else None

        from app.game import events
        boosted = events.apply_to_fight(self)
        if boosted:
            ev = events.cached()
            self._log(f"🎉 {ev['name']}: {', '.join(boosted)} {'is' if len(boosted) == 1 else 'are'} in the spotlight "
                      f"(+{events.BOOST:.0%} damage and speed).", "terrain")

        self.rules = dict(self.meta.get("rules") or {})  # Over Heaven fight rules (app/game/overheaven.py)
        self._apply_synergies()
        self._apply_resonances()
        if self.rules:
            from app.game import overheaven
            for text in overheaven.apply_rules(self):
                self._log(text, "terrain")

        # Who moves first is decided after synergies and ambushes, so slowing a fast team can steal the tempo.
        s0 = sum(c.current_speed for c in human.chars if c.is_alive())
        s1 = sum(c.current_speed for c in opponent.chars if c.is_alive())
        self.order = [0, 1]
        if self.rules.get("enemy_first"):
            self.order = [1 - human_side, human_side]
        elif s1 > s0 or (s1 == s0 and random.random() < 0.5):
            self.order = [1, 0]
        self._counter_stance(self.order[1], abs(s1 - s0))
        self._down = set()

    def _counter_stance(self, s: int, gap: float) -> None:
        from app.game.effects import Effect, EffectType
        side = self.sides[s]
        crit = min(COUNTER_CRIT_MAX, int(gap * COUNTER_CRIT_PER_GAP))
        for c in side.chars:
            c.special_meter += 1
            if not c.is_alive():
                continue
            c.add_effect(Effect(EffectType.ARMORUP, COUNTER_TURNS, int(c.current_armor * COUNTER_ARMOR)))
            c.add_effect(Effect(EffectType.DAMAGEUP, COUNTER_TURNS, int(c.current_damage * COUNTER_DAMAGE)))
            if crit:
                c.add_effect(Effect(EffectType.CRITUP, MAX_ROUNDS + 2, crit))
        extra = f", +{crit} critical for the speed it gave up" if crit else ""
        self._log(f"🛡️ {side.name} moves second and opens in a counter stance: specials one turn closer, "
                  f"+{COUNTER_ARMOR:.0%} armor and +{COUNTER_DAMAGE:.0%} damage for {COUNTER_TURNS} turns{extra}.",
                  "terrain", side=s)

    def _apply_synergies(self) -> None:
        from app.game.characterabilities import SYNERGY_BONUS, SYNERGY_INFO, apply_synergy_bonuses
        from app.game.effects import fmt_perk
        from app.game.resonance import uses_parts
        for s, side in enumerate(self.sides):
            for name, members in apply_synergy_bonuses(side.chars, parts=uses_parts(side)):
                label, icon = SYNERGY_INFO.get(name, (name, "✶"))
                perks = ", ".join(fmt_perk(stat, v) for stat, v in SYNERGY_BONUS.get(name, []))
                self._log(f"{icon} {label} synergy for {side.name}: {', '.join(members)} gain {perks} "
                          f"(more for lower rarities).", "terrain", side=s)

    def _apply_resonances(self) -> None:
        from app.game import resonance
        self.resonances = resonance.apply(self)
        for s, keys in self.resonances.items():
            for key in keys:
                label, icon, _needs, effect = resonance.RESONANCES[key]
                self._log(f"{icon} {label} resonates for {self.sides[s].name}! {effect}", "terrain", side=s)

    def _check_falls(self) -> None:
        """Golden Spirit: rally the survivors of a side whenever one of its stands falls."""
        from app.game import resonance
        down = getattr(self, "_down", set())
        for s, side in enumerate(self.sides):
            for i, c in enumerate(side.chars):
                if c.is_alive() or (s, i) in down:
                    continue
                down.add((s, i))
                if "golden_spirit" in getattr(self, "resonances", {}).get(s, ()) and side.alive():
                    rallied = resonance.second_wind(side.chars, c)
                    if rallied:
                        self._log(f"✨ {c.name} falls, and {', '.join(rallied)} rally with a Second Wind!", "terrain", side=s)
        self._down = down

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

    def _log(self, text, kind, char=None, side=None, src=None, dst=None, dmg=None, crit=None):
        """src/dst are [side, index] so the web view can animate who hit whom;
        hp is every fighter's HP right after the event, to replay the bars; crit counts a hit's crits
        (1 yellow, 2 red, 3+ rainbow)."""
        for s in self.sides:  # safety net: nothing heals past max health
            for c in s.chars:
                c.current_hp = min(c.current_hp, c.start_hp)
        self.log.append({"turn": self.turn + 1, "text": text, "kind": kind,
                         "char_id": char.id if char else None, "side": side,
                         "src": src, "dst": dst, "dmg": dmg, "crit": crit,
                         "hp": [[max(c.current_hp, 0) for c in s.chars] for s in self.sides]})

    @property
    def round(self) -> int:
        return self.turn // 2 + 1

    @property
    def sudden_death(self) -> bool:
        return self.round >= self.sudden_death_round

    def forfeit(self, side: int = 0):
        self.forfeited = True  # left out of the balance stats
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
        self.terrain = self._field(everyone)
        apply_terrain_bonuses(everyone, self.terrain)
        if self.terrain != before:
            self._log(f"{self.terrain.emoji} The field becomes {self.terrain.display_name}. {self.terrain.rule}"
                      if self.terrain != Terrain.DEFAULT else "🏞️ The field returns to neutral ground.", "terrain")
        self.round_started = True

    def _field(self, everyone: List[Character]) -> Terrain:
        """A locked field (Over Heaven) beats Home Field, which beats the fastest setter."""
        if self.__dict__.get("rules", {}).get("terrain"):
            return Terrain.from_string(self.rules["terrain"])
        from app.game.effects import TERRAIN_SETTERS
        held = []
        for s, terrain in getattr(self, "home", {}).items():
            setters = [c for c in self.sides[s].chars if c.is_alive() and TERRAIN_SETTERS.get(c.id) == terrain]
            if setters:
                held.append((max(c.current_speed for c in setters), terrain))
        if held:
            return max(held, key=lambda h: h[0])[1]
        return get_active_terrain(everyone)

    def _end_turn(self, p: int) -> None:
        side = self.sides[p]
        for c in side.chars:
            c.end_turn()
        if self.__dict__.get("rules"):
            from app.game import overheaven
            text = overheaven.end_turn(self, p)
            if text:
                self._log(text, "terrain", side=p)
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
                        tier = data.get("crit", 1)
                        strike = " ".join(filter(None, [CRIT_WORDS.get(tier, f"×{tier}"), "critical strike"]))
                        self._log(f"{char.name} lands a {strike} on {targeted.name} for {data['damage']}.", "crit", char, p,
                                  dmg=data["damage"], crit=tier, **hit)
                    else:
                        self._log(f"{char.name} hits {targeted.name} for {data['damage']}.", "hit", char, p,
                                  dmg=data["damage"], **hit)
                    if data["damage"] and getattr(char, "_lifesteal", 0):
                        char.heal(data["damage"] * char._lifesteal)
                    if data["damage"] and self.__dict__.get("rules"):
                        from app.game import overheaven
                        text = overheaven.after_hit(self, char, targeted, data["damage"])
                        if text:
                            self._log(text, "terrain", side=1 - p)
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
                self._check_falls()
                self.si += 1

            self._end_turn(p)
            self._check_falls()
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
        elif self.kind in PVP_KINDS:  # both teams fell together: a draw, so a self-damaging special can't steal Elo
            self.winner = None
        else:  # PvE: it goes to whoever made the move
            self.winner = getattr(self, "_last_actor", None)


def fighting_copy(chars: List[Character]) -> List[Character]:
    return [character_from_dict(copy.deepcopy(c.to_dict())) for c in chars]
