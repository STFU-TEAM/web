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

from app.game.character import Character, character_from_dict, share_hp
from app.game.effects import Terrain, apply_terrain_bonuses, get_active_terrain, remove_terrain_bonuses

# Fights stay short: from this round every stand loses a growing share of its health
# at the end of its turn and heals for half, and the fight is called at MAX_ROUNDS.
SUDDEN_DEATH_ROUND = 10
SUDDEN_DEATH_STEP = 0.05
SUDDEN_DEATH_HEAL = 0.5
MAX_ROUNDS = 18
# PvP duels are paced for 1-2 minutes (5 at most: battles.PVP_MAX_SECONDS): stands hit harder, sudden death comes
# sooner and the round cap is lower. PvE fights already take under a minute and keep the numbers above.
# Tuned with a pacing model (log replay as the client plays it, ~4 s a human pick): about 1.8 min on average.
PVP_DAMAGE = 1.3  # was 1.6: maxed teams ended duels in 3 rounds; now about 5
PVP_SUDDEN_DEATH_ROUND = 5
PVP_SUDDEN_DEATH_STEP = 0.10
PVP_MAX_ROUNDS = 10
PVP_MAX_SECONDS = 300  # a duel never runs past 5 minutes: then the side with more health left wins (battles.py)
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
    from app.game.character import ARMOR_CAP, soften
    armor = min(max(target.current_armor, 0), ARMOR_CAP)
    return soften(attacker.current_damage * 200 / (100 + armor))


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
SIMULATABLE = ("wormhole", "story", "tower", "rush", "dungeon", "alt_universe", "over_heaven", "training", "carry_me", "requiem",
               "heaven")  # PvE a loss can replay
CRIT_WORDS = {1: "", 2: "DOUBLE", 3: "TRIPLE"}


class Fight:
    sudden_death_round = SUDDEN_DEATH_ROUND
    sudden_death_step = SUDDEN_DEATH_STEP
    max_rounds = MAX_ROUNDS
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
        if kind in PVP_KINDS:
            self._pvp_pace()
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

    def _pvp_pace(self) -> None:
        self.sudden_death_round, self.sudden_death_step = PVP_SUDDEN_DEATH_ROUND, PVP_SUDDEN_DEATH_STEP
        self.max_rounds = PVP_MAX_ROUNDS
        for side in self.sides:
            for c in side.chars:
                c.current_damage = int(c.current_damage * PVP_DAMAGE)
                c.start_damage = int(c.start_damage * PVP_DAMAGE)  # % buffs read it: they keep pace with the duel
        self._log(f"⚔️ Duel pace: +{PVP_DAMAGE - 1:.0%} damage on both sides, sudden death from round "
                  f"{PVP_SUDDEN_DEATH_ROUND}.", "terrain")

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
            for c in side.chars:  # computer PvE teams: no part or cross synergies, in stats or in specials
                c._computer = not uses_parts(side)
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
            for c in side.chars:  # the New Rokakaka: low on health, trade it for an enemy's
                if c.items and c.is_alive():
                    from app.game.itemabilities import equivalent_exchange
                    text = equivalent_exchange(c, self.sides[1 - s].chars)
                    if text:
                        self._log(text, "item", c, s)
            for i, c in enumerate(side.chars):
                if c.is_alive() or (s, i) in down:
                    continue
                if c.__dict__.pop("_g_zip", False):  # the Gauntlet's Zipper: once a fight, the finishing blow misses
                    c.current_hp = 1
                    self._log(f"🤐 Sticky Fingers zips {c.name} out of the way: it hangs on at 1 health!", "terrain", c, s)
                    continue
                if c.__dict__.pop("_g_bomb", 0):  # the Gauntlet's Killer Queen switch: it detonates as it falls
                    blast = c.start_hp * 0.6
                    total = sum(e.take(blast) for e in self.sides[1 - s].chars if e.is_alive())
                    self._log(f"💣 {c.name} falls, and the switch clicks: {total} damage to every enemy!", "special", c, s,
                              src=[s, i])
                if c.__dict__.pop("_g_revive", False):  # the Gauntlet's Saint's Spine: once a run, it gets back up
                    c.effects = []
                    c.current_hp = c.start_hp // 2
                    self.meta["revived"] = True
                    self._log(f"✝️ The Saint's Spine glows: {c.name} gets back up at half health, every debuff gone!",
                              "terrain", c, s)
                    continue
                if c.items:
                    from app.game.itemabilities import cheat_death
                    text = cheat_death(c, self.sides[1 - s].chars)
                    if text:
                        self._log(text, "item", c, s)
                        continue
                down.add((s, i))
                if "golden_spirit" in getattr(self, "resonances", {}).get(s, ()) and side.alive():
                    rallied = resonance.second_wind(side.chars, c)
                    if rallied:
                        self._log(f"✨ {c.name} falls, and {', '.join(rallied)} rally with a Second Wind!", "terrain", side=s)
        self._down = down

    # ── the Gauntlet's prototype items (app/game/gauntlet.py apply_item sets the _g_* flags) ──
    def _gauntlet_hit(self, char, targeted, data, p, idx) -> None:
        """After a basic attack: the hat's counter on a dodge, the steel ball's chain, the red stone's blinding, the
        lipstick's heal, the ACT 3 seal's weight, the Hand's erasure."""
        from app.game.effects import Effect, EffectType
        watcher = self.sides[1 - p]
        if data["dodged"] and getattr(targeted, "_g_counter", 0) and targeted.is_alive() and char.is_alive():
            back = targeted.attack(char, multiplier=targeted._g_counter)
            if back["damage"]:
                self._log(f"🎩 {targeted.name} dodges and counters {char.name} for {back['damage']}!", "hit", targeted,
                          1 - p, dmg=back["damage"], src=[1 - p, idx], dst=[p, self.si])
        if data["damage"] and getattr(char, "_g_chain", 0):
            amount = data["damage"]
            for j, other in enumerate(watcher.chars):
                if other is targeted or not other.is_alive():
                    continue
                amount *= char._g_chain
                dealt = other.take(amount)
                if dealt:
                    self._log(f"🌀 The steel ball spins on into {other.name} for {dealt}.", "hit", char, p, dmg=dealt,
                              src=[p, self.si], dst=[1 - p, j])
        if data.get("critical") and getattr(char, "_g_blind", False) and targeted.is_alive():
            targeted._g_blinded = True
            self._log(f"🔴 The Red Stone flashes: {targeted.name} is blinded and will miss its next attack.", "info", char, p)
        if data.get("critical") and getattr(char, "_g_lips", 0):
            healed = sum(a.heal(a.start_hp * char._g_lips) for a in self.sides[p].chars if a.is_alive())
            if healed:
                self._log(f"💄 Cinderella's Lipstick: the critical hit heals the team for {healed}.", "info", char, p)
        if data["damage"] and getattr(char, "_g_freeze", 0) and targeted.is_alive():
            targeted.add_effect(Effect(EffectType.SLOW, 1, int(targeted.current_speed * char._g_freeze) + 1, char))
        if data["damage"] and getattr(char, "_g_erase", 0) and targeted.is_alive():
            erased = targeted.take(share_hp(targeted) * char._g_erase)
            if erased:
                self._log(f"✋ The Hand erases {erased} more from {targeted.name}.", "hit", char, p, dmg=erased,
                          src=[p, self.si], dst=[1 - p, idx])

    def _disc_copy(self, caster, p) -> None:
        """Blank DISC: the first special an enemy uses each fight is copied and fired back, 50% stronger."""
        from app.game import characterabilities as abilities
        from app.game.character import specials
        mine = self.sides[1 - p]
        for j, holder in enumerate(mine.chars):
            if not holder.is_alive() or not holder.__dict__.pop("_g_disc", False):
                continue
            func = specials.get(str(caster.id))
            if not func:
                return
            holder.current_damage *= 1.5
            abilities.begin_special(holder)
            try:
                payload, message = func(holder, mine.chars, self.sides[p].chars)
            finally:
                abilities.end_special()
                holder.current_damage /= 1.5
            if payload.get("is_a_special", True):
                self._log(f"💿 {holder.name}'s Blank DISC copies {caster.name}'s special! {message}", "special", holder,
                          1 - p, src=[1 - p, j])
            return

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

    def damage_dealt(self, side: int) -> dict:
        """{fighter index: health it took off the other side} over the whole fight: every event's losses go to the
        fighter that caused it (its src). Poison ticks and sudden death have no source and count for nobody."""
        out, prev = {}, None
        for e in self.log:
            hp = e.get("hp")
            if not hp:
                continue
            src = e.get("src")
            if prev is not None and src and src[0] == side:
                lost = sum(max(0, a - b) for a, b in zip(prev[1 - side], hp[1 - side]))
                if lost:
                    out[src[1]] = out.get(src[1], 0) + lost
            prev = hp
        return out

    def mvp(self, side: int):
        """(fighter, damage) of side's top damage dealer, or (None, 0)."""
        dealt = self.damage_dealt(side)
        if not dealt:
            return None, 0
        idx = max(dealt, key=dealt.get)
        return self.sides[side].chars[idx], int(dealt[idx])

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

    def _foretell(self) -> None:
        """Epitaph (Heaven's Gate): who each enemy stand will strike on its next turn. Fate holds them to it."""
        me, foe = self.sides[self.human_side], self.sides[1 - self.human_side]
        self._fate = {i: ai_choice(me.chars, c, getattr(foe, "ai", "smart"))
                      for i, c in enumerate(foe.chars) if c.is_alive() and valid_targets(me.chars)}

    def _heaven_step(self, p: int, step: int) -> int:
        """Heaven's Gate: after a turn, time may stop (the enemy acts again) or be erased (your next turn is skipped)."""
        rules = self.__dict__.get("rules") or {}
        foe = 1 - self.human_side
        if p != foe or not self._on():
            return step
        if rules.get("time_stop"):
            left = self.__dict__.get("_ts_left")
            if left is None and self.round % rules["time_stop"] == 0:
                self._ts_left = 1  # one extra turn: the enemy acts twice in a row
                self._log(f"⏱️ ZA WARUDO! Time stops: {self.sides[foe].name} moves again.", "terrain", side=foe)
                self.log[-1]["fx"] = "timestop"
                return 0
            if left:
                self._ts_left = left - 1
                if self._ts_left > 0:
                    self._log("⏱️ Time is still stopped…", "terrain", side=foe)
                    self.log[-1]["fx"] = "timestop"
                    return 0
                self._ts_left = None
                self._log("⏱️ …and time moves again.", "terrain", side=foe)
                self.log[-1]["fx"] = "timeflow"
        if rules.get("erase") and self.round % rules["erase"] == 0 and step == 1:
            self._log("👁️ King Crimson! Time is erased: your next turn never happened.", "terrain", side=foe)
            self.log[-1]["fx"] = "erase"
            return 2
        return step

    def _start_turn(self, p: int) -> None:
        if p == self.human_side and (self.__dict__.get("rules") or {}).get("epitaph"):
            self._foretell()
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
            self.log[-1]["field"] = self.terrain.name  # the web replay recolours the arena (app.js)
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
        for c in side.chars:  # the Gauntlet's Crazy Diamond fist and Sheer Heart Attack
            if not c.is_alive():
                continue
            if getattr(c, "_g_restore", 0):
                hurt = min((a for a in side.chars if a.is_alive()), key=lambda a: a.current_hp / max(1, a.start_hp))
                fixed = hurt.heal(hurt.start_hp * c._g_restore)
                if fixed:
                    self._log(f"💎 Crazy Diamond restores {hurt.name} by {fixed}.", "info", c, p)
            if getattr(c, "_g_sha", 0):
                foes = [e for e in self.sides[1 - p].chars if e.is_alive()]
                if foes:
                    fastest = max(foes, key=lambda e: e.current_speed)
                    dealt = fastest.take(c.current_damage * c._g_sha)
                    if dealt:
                        self._log(f"🎯 Sheer Heart Attack homes in on {fastest.name} for {dealt}! (KOCCHI WO MIRO!)", "hit", c, p,
                                  dmg=dealt)
        drained = [c for c in side.chars if c.is_alive() and getattr(c, "_g_drain", 0)]
        for c in drained:  # the Gauntlet's Stone Mask feeds on its wearer
            c.take(c.start_hp * c._g_drain)
        if drained:
            self._log(f"🎭 The Stone Mask feeds on {', '.join(c.name for c in drained)}.", "info", side=p)
        if self.__dict__.get("rules"):
            from app.game import overheaven
            text = overheaven.end_turn(self, p)
            if text:
                self._log(text, "terrain", side=p)
        if self.sudden_death and self._on():  # a side that just won isn't dragged into a draw by the tick
            pct = self.sudden_death_step * (self.round - self.sudden_death_round + 1)
            for c in side.chars:
                if c.is_alive():
                    c.take(share_hp(c) * pct)
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
                        fated = (self.__dict__.get("_fate") or {}).get(self.si)
                        if fated is not None and fated in valid_targets(watcher.chars):
                            idx = fated  # Epitaph: what was foretold happens
                    targeted = watcher.chars[idx]
                    char._focus = targeted  # single-target specials follow the chosen target
                    if p == self.human_side and self.__dict__.pop("_whiff", False):
                        # Made in Heaven (Heaven's Gate): out of time, the attack lands on nothing
                        data = {"dodged": True, "critical": False, "damage": 0, "whiff": True}
                    else:
                        data = char.attack(targeted)
                    hit = {"src": [p, self.si], "dst": [1 - p, idx]}
                    if data.get("whiff"):
                        self._log(f"⏳ Out of time! {char.name}'s attack lands on nothing.", "dodge", char, p, **hit)
                    elif data["dodged"]:
                        self._log(f"{targeted.name} dodged {char.name}'s attack.", "dodge", char, p, **hit)
                    elif data["critical"]:
                        tier = data.get("crit", 1)
                        strike = " ".join(filter(None, [CRIT_WORDS.get(tier, f"×{tier}"), "critical strike"]))
                        self._log(f"{char.name} lands a {strike} on {targeted.name} for {data['damage']}.", "crit", char, p,
                                  dmg=data["damage"], crit=tier, **hit)
                    else:
                        self._log(f"{char.name} hits {targeted.name} for {data['damage']}.", "hit", char, p,
                                  dmg=data["damage"], **hit)
                    if (self.__dict__.get("rules") or {}).get("hidden_hp") and p == self.human_side:
                        targeted._read = getattr(targeted, "_read", 0) + 1  # Heaven's Door: hits read its book
                    if self.kind == "gauntlet":
                        self._gauntlet_hit(char, targeted, data, p, idx)
                    if data["damage"] and (char.items or targeted.items):  # gear passives: the comb, slime, goggles...
                        from app.game.itemabilities import on_hit
                        for line in on_hit(char, targeted, data):
                            self._log(line, "item", char, p)
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
                        if self.kind == "gauntlet" and p != self.human_side:
                            self._disc_copy(char, p)
                        if getattr(char, "_g_tax", 0) and char.is_alive():  # the Gauntlet's Pact of the Arrow
                            paid = char.take(char.start_hp * char._g_tax)
                            if paid:
                                self._log(f"🏹 The Arrow collects its due: {char.name} loses {paid}.", "info", char, p)
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
            if p != self.human_side:
                self._fate = {}  # the foretold turn is over
            step = self._heaven_step(p, step)
            self.turn += step
            self.si = 0
            self.round_started = False
            if self._on() and self.round > self.max_rounds:
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
