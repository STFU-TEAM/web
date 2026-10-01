"""Logged-in game pages. Every mutation goes through `action()`: take the
per-user lock, reload fresh data from Redis, apply the rule, save."""
from flask import Blueprint, flash, redirect, render_template, request, session, url_for

from app.auth import player_required
from app.db import Busy, clear_fight, get_db, load_fight, save_fight, user_lock
from app.game import logic
from app.game import dungeon as dungeon_logic
from app.game.character import character_from_dict
from app.game.fight import Fight, Side, fighting_copy
from app.game.items import item_file, item_from_dict
from app.game.logic import BANNERS, DEFAULT_SHOP, RECIPES, GameError
from app.game.quests import QUEST_BY_ID, ensure_quests_assigned

bp = Blueprint("play", __name__)


def _user():
    return get_db().get_user(session["uid"])


def action(fn):
    """Run fn(user) under lock and save. Returns (user, result, error)."""
    try:
        with user_lock(session["uid"]):
            user = _user()
            try:
                result = fn(user)
            except GameError as e:
                return user, None, str(e)
            user.update()
            return user, result, None
    except Busy:
        return _user(), None, "Hold on, your last action is still running."


def _int(name, default=None):
    try:
        return int(request.values.get(name))
    except (TypeError, ValueError):
        return default


def status(user):
    return {
        "daily": logic.cooldown_left(user.last_adventure, logic.DONOR_ADV_WAIT_TIME + (not user.is_donator()) * logic.NORMAL_ADV_WAIT_TIME),
        "wormhole": logic.cooldown_left(user.last_wormhole, logic.wormhole_wait(user)),
        "energy_in": logic.energy_refill_in(user),
        "free_slots": logic.free_slots(user),
    }


def storage_shelves(user):
    return [("all", 0, "Collection", user.storage_characters)]


def _refill(user):
    """Apply the bot's energy refill on page load (it also runs every minute bot-side)."""
    if logic.refill_energy(user):
        user.update()


# --------------------------------------------------------------------------- #
# Collection
# --------------------------------------------------------------------------- #
@bp.get("/team")
@player_required
def team():
    user = _user()
    _refill(user)
    shelf = "all"
    return render_template("team.html", u=user, st=status(user), shelves=storage_shelves(user), shelf=shelf,
                           fight=load_fight(session["uid"]))


@bp.get("/team/collection")
@player_required
def collection():
    return _collection(_user())


def _collection(user, message=None, error=None):
    return render_template("partials/collection.html", u=user, message=message, error=error,
                           shelves=storage_shelves(user), shelf=request.values.get("shelf", "s0"))


@bp.post("/team/store")
@player_required
def store():
    uuid = request.form.get("uuid")
    user, res, err = action(lambda u: logic.store(u, uuid))
    return _collection(user, f"{res[0].name} moved to {res[1].lower()}." if res else None, err)


@bp.post("/team/main")
@player_required
def to_main():
    uuid, swap = request.form.get("uuid"), request.form.get("swap")
    user, res, err = action(lambda u: logic.to_main(u, uuid, swap))
    return _collection(user, f"{res.name} joined your team." if res else None, err)


@bp.post("/team/release")
@player_required
def release():
    uuids = request.form.getlist("uuid")
    user, res, err = action(lambda u: logic.release(u, uuids))
    msg = None
    if res:
        msg = f"{res[0].name} was released." if len(res) == 1 else f"{len(res)} stands were released."
    return _collection(user, msg, err)


@bp.post("/team/ascend")
@player_required
def ascend():
    uuid = request.form.get("uuid")
    user, res, err = action(lambda u: logic.ascend(u, uuid))
    return _collection(user, f"{res.name} reached awakening {res.awaken}." if res else None, err)


@bp.post("/team/fuse")
@player_required
def fuse():
    a, b = request.form.get("uuid"), request.form.get("fodder")
    user, res, err = action(lambda u: logic.fuse(u, a, b))
    return _collection(user, f"Fused. {res.name} is now awakening {res.awaken}, level {res.level}." if res else None, err)


@bp.post("/team/reforge")
@player_required
def reforge():
    uuid = request.form.get("uuid")
    user, res, err = action(lambda u: logic.reforge(u, uuid))
    return _collection(user, f"{res.name} was reforged." if res else None, err)


@bp.post("/team/equip")
@player_required
def equip():
    uuid, item_id = request.form.get("uuid"), _int("item")
    user, res, err = action(lambda u: logic.equip(u, uuid, item_id))
    return _collection(user, f"{res[1].name} equipped on {res[0].name}." if res else None, err)


@bp.post("/team/unequip")
@player_required
def unequip():
    uuid, slot = request.form.get("uuid"), _int("slot")
    user, res, err = action(lambda u: logic.unequip(u, uuid, slot))
    return _collection(user, f"{res[1].name} removed from {res[0].name}." if res else None, err)


@bp.post("/team/preset/save")
@player_required
def preset_save():
    name = request.form.get("name", "")
    user, res, err = action(lambda u: logic.team_save(u, name))
    return _collection(user, f"Preset “{res}” saved." if res else None, err)


@bp.post("/team/preset/load")
@player_required
def preset_load():
    name = request.form.get("name", "")
    user, res, err = action(lambda u: logic.team_load(u, name))
    return _collection(user, f"Preset “{name}” loaded." if res is not None and not err else None, err)


@bp.post("/team/preset/delete")
@player_required
def preset_delete():
    name = request.form.get("name", "")
    user, _, err = action(lambda u: logic.team_delete(u, name))
    return _collection(user, None if err else f"Preset “{name}” deleted.", err)


# --------------------------------------------------------------------------- #
# Daily
# --------------------------------------------------------------------------- #
@bp.post("/daily")
@player_required
def daily():
    user, res, err = action(logic.daily)
    return render_template("partials/daily_result.html", u=user, res=res, error=err, st=status(user))


# --------------------------------------------------------------------------- #
# Banners
# --------------------------------------------------------------------------- #
@bp.get("/banners")
@player_required
def banners():
    user = _user()
    active = [b for b in BANNERS if b["enabled"]]
    arrows = sum(1 for i in user.items if i.id == 2)
    return render_template("banners.html", u=user, banners=active, arrows=arrows, st=status(user),
                           welcome=request.args.get("welcome"))


@bp.post("/banners/<int:banner_id>/<mode>")
@player_required
def pull(banner_id: int, mode: str):
    fn = logic.banner_pull if mode == "pull" else logic.arrow_pull
    user, res, err = action(lambda u: fn(u, banner_id))
    arrows = sum(1 for i in user.items if i.id == 2)
    rarity_score = {"R": 0, "SR": 1, "SSR": 2, "UR": 3, "LR": 4}
    top_rarity = max((char.rarity for char, _ in res["drawn"]), key=rarity_score.get) if res else "R"
    opening_id = 6 if top_rarity in ("UR", "LR") else 5 if top_rarity == "SSR" else 4
    return render_template("partials/pull_result.html", u=user, res=res, error=err, arrows=arrows,
                           mode=mode, top_rarity=top_rarity, opening_id=opening_id)


# --------------------------------------------------------------------------- #
# Items & shop
# --------------------------------------------------------------------------- #
def _grouped(items):
    groups = {}
    for it in items:
        groups.setdefault(it.id, {"item": it, "count": 0})["count"] += 1
    return sorted(groups.values(), key=lambda g: (g["item"].is_equipable, g["item"].id))


def _recipes(user):
    have = {}
    for it in user.items:
        have[it.id] = have.get(it.id, 0) + 1
    out = []
    for r in RECIPES:
        parts = [(item_file[i - 1]["name"], n, have.get(i, 0)) for i, n in r["ingredients"]]
        out.append({"name": r["name"], "parts": parts, "ready": all(h >= n for _, n, h in parts)})
    return out


def _items_ctx(user):
    return {"u": user, "groups": _grouped(user.items), "recipes": _recipes(user), "shop": DEFAULT_SHOP}


@bp.get("/items")
@player_required
def items():
    return render_template("items.html", **_items_ctx(_user()))


@bp.post("/items/use")
@player_required
def use():
    item_id, uuid = _int("item"), request.form.get("uuid")
    user, res, err = action(lambda u: logic.use_item(u, item_id, uuid))
    return render_template("partials/use_result.html", res=res, error=err, **_items_ctx(user))


@bp.post("/items/craft")
@player_required
def craft():
    name = request.form.get("recipe", "")
    user, res, err = action(lambda u: logic.craft(u, name))
    return render_template("partials/use_result.html", res={"kind": "crafted", "item": res} if res else None,
                           error=err, **_items_ctx(user))


@bp.post("/shop/buy")
@player_required
def shop_buy():
    key = request.form.get("key", "")
    user, res, err = action(lambda u: logic.shop_buy(u, key))
    return render_template("partials/use_result.html", res={"kind": "bought", "name": res} if res else None,
                           error=err, **_items_ctx(user))


# --------------------------------------------------------------------------- #
# Quests
# --------------------------------------------------------------------------- #
def _quest_rows(user):
    ensure_quests_assigned(user)
    out = {}
    for key, label in (("active_daily", "Daily"), ("active_weekly", "Weekly"), ("active_permanent", "Permanent")):
        rows = []
        for e in user.quests.get(key, []):
            q = QUEST_BY_ID.get(e["quest_id"])
            if q:
                rows.append({"q": q, "progress": min(e["progress"], q["target"]), "claimed": e["claimed"],
                             "ready": e["progress"] >= q["target"] and not e["claimed"]})
        out[label] = rows
    return out


@bp.get("/quests")
@player_required
def quests():
    user, _, _ = action(lambda u: ensure_quests_assigned(u))  # assignment is saved, like /quest view
    return render_template("quests.html", u=user, groups=_quest_rows(user))


@bp.post("/quests/claim")
@player_required
def quest_claim():
    qid = _int("quest")
    if qid is None:
        user, res, err = action(logic.quest_claim_all)
    else:
        user, res, err = action(lambda u: [logic.quest_claim(u, qid)])
    return render_template("partials/quests_body.html", u=user, groups=_quest_rows(user), claimed=res, error=err)


# --------------------------------------------------------------------------- #
# Wormhole (PvE fight)
# --------------------------------------------------------------------------- #
@bp.get("/wormhole")
@player_required
def wormhole():
    user = _user()
    _refill(user)
    fight = load_fight(session["uid"])
    other_fight = None
    if fight and fight.kind != "wormhole":
        other_fight = fight.kind
        fight = None
    return render_template("wormhole.html", u=user, fight=fight, st=status(user),
                           other_fight=other_fight,
                           fight_action=url_for("play.wormhole_attack"),
                           fight_leave_action=url_for("play.wormhole_leave"), fight_label="Wormhole")


@bp.post("/wormhole/start")
@player_required
def wormhole_start():
    uid = session["uid"]
    if load_fight(uid):
        return redirect(url_for("play.wormhole"))

    def start(u):
        name, enemies, multi = logic.wormhole_start(u)
        fight = Fight(Side(session.get("name", "You"), fighting_copy(u.main_characters), True, session.get("avatar")),
                      Side(name, enemies, False), meta={"multi": multi})
        fight.advance()
        return fight

    user, fight, err = action(start)
    if err:
        return render_template("wormhole.html", u=user, fight=None, st=status(user), error=err)
    save_fight(uid, fight)
    return redirect(url_for("play.wormhole"))


@bp.post("/wormhole/attack")
@player_required
def wormhole_attack():
    uid = session["uid"]
    try:
        with user_lock(uid, ttl=5):
            fight = load_fight(uid)
            if fight is None or fight.kind != "wormhole":
                return '<p class="notice">This wormhole fight is not active. <a href="/wormhole">Back to the wormhole</a></p>', 409
            if not fight.finished:
                if request.form.get("forfeit"):
                    fight.forfeit()
                else:
                    fight.advance(_int("target"))
            if fight.finished and fight.rewards is None:
                u = get_db().get_user(uid)
                fight.rewards = logic.wormhole_reward(u, fight.winner == 0, fight.meta.get("multi", 1))
                u.update()
            save_fight(uid, fight)
    except Busy:
        fight = load_fight(uid)
    return render_template("partials/fight.html", fight=fight, fresh_from=_int("log_len"),
                           fight_action=url_for("play.wormhole_attack"),
                           fight_leave_action=url_for("play.wormhole_leave"), fight_label="Wormhole")


@bp.post("/wormhole/leave")
@player_required
def wormhole_leave():
    fight = load_fight(session["uid"])
    if fight and fight.kind == "wormhole" and fight.finished:
        clear_fight(session["uid"])
    return redirect(url_for("play.wormhole"))


TOWER_WAVES = (
    ((8, "SPEED", "GOOD", 0), (11, "ATTACK", "GOOD", 0), (12, "DEFENSE", "GOOD", 0)),
    ((7, "SPEED", "GREAT", 1), (13, "ATTACK", "GREAT", 1), (18, "ATTACK", "GOOD", 1)),
    ((19, "LUCK", "GREAT", 2), (22, "SPEED", "GREAT", 2), (25, "ATTACK", "SUPREME", 1)),
    ((27, "ATTACK", "SUPREME", 2), (28, "LUCK", "SUPREME", 2), (29, "ATTACK", "GREAT", 2)),
    ((14, "ATTACK", "SUPREME", 2), (30, "ATTACK", "SUPREME", 2), (16, "DEFENSE", "SUPREME", 2)),
    ((10, "ATTACK", "UNIVERSAL", 3), (30, "ATTACK", "SUPREME", 2), (21, "DEFENSE", "SUPREME", 2)),
)
TOWER_COST = 500


def _tower_team(stage, completed_towers):
    enemies = []
    for char_id, type_name, quality, awaken in TOWER_WAVES[stage]:
        data = {"id": char_id, "xp": (2000 + stage * 1000) + completed_towers * 2000,
                "awaken": min(3, awaken + completed_towers // 2), "types": [type_name],
                "qualities": [quality], "items": [{"id": 1}]}
        enemies.append(character_from_dict(data))
    return enemies


@bp.get("/tower")
@player_required
def tower():
    user = _user()
    fight = load_fight(session["uid"])
    other_fight = None
    if fight and fight.kind != "tower":
        other_fight = fight.kind
        fight = None
    stage = int(user.data.get("web_tower_floor", 0)) % len(TOWER_WAVES)
    return render_template("tower.html", u=user, fight=fight, stage=stage, other_fight=other_fight,
                           climb_active=bool(user.data.get("web_tower_active")),
                           fight_action=url_for("play.tower_attack"),
                           fight_leave_action=url_for("play.tower_leave"), fight_label="Tower")


@bp.post("/tower/start")
@player_required
def tower_start():
    uid = session["uid"]
    if load_fight(uid):
        return redirect(url_for("play.tower"))

    def start(user):
        if not user.main_characters:
            raise GameError("Set up a team before entering the tower.")
        active = bool(user.data.get("web_tower_active"))
        if not active and user.fragments < TOWER_COST:
            raise GameError(f"A tower climb costs {TOWER_COST} fragments.")
        if not active:
            user.fragments -= TOWER_COST
            user.data["web_tower_active"] = True
            logic.track_quest_progress(user, "tower_attempt")
            logic.check_achievements(user, "tower_attempt")
        stage = int(user.data.get("web_tower_floor", 0)) % len(TOWER_WAVES)
        enemies = _tower_team(stage, user.tower_level)
        fight = Fight(Side(session.get("name", "You"), fighting_copy(user.main_characters), True,
                           session.get("avatar")),
                      Side(f"Floor {stage + 1}", enemies, False), kind="tower",
                      meta={"stage": stage, "tower_level": user.tower_level})
        fight.advance()
        return fight

    user, fight, err = action(start)
    if err:
        return render_template("tower.html", u=user, fight=None,
                               stage=int(user.data.get("web_tower_floor", 0)) % len(TOWER_WAVES),
                               climb_active=bool(user.data.get("web_tower_active")), error=err)
    save_fight(uid, fight)
    return redirect(url_for("play.tower"))


@bp.post("/tower/attack")
@player_required
def tower_attack():
    uid = session["uid"]
    try:
        with user_lock(uid, ttl=5):
            fight = load_fight(uid)
            if fight is None or fight.kind != "tower":
                return '<p class="notice">This tower fight expired. <a href="/tower">Back to the tower</a></p>'
            if not fight.finished:
                if request.form.get("forfeit"):
                    fight.forfeit()
                else:
                    fight.advance(_int("target"))
            if fight.finished and fight.rewards is None:
                user = get_db().get_user(uid)
                won = fight.winner == 0
                rewards = {"won": won, "fragments": 0, "xp": 0, "stand_xp": 0, "item": None}
                if won:
                    stage = int(fight.meta["stage"])
                    rewards["fragments"] = 150 + stage * 50
                    rewards["xp"] = 100 + stage * 50
                    rewards["stand_xp"] = 10 + stage * 5
                    user.fragments += rewards["fragments"]
                    user.xp += rewards["xp"]
                    for char in user.main_characters:
                        char.xp += rewards["stand_xp"]
                    item = item_from_dict({"id": (13, 1, 2, 7, 9)[stage % 5]})
                    user.items.append(item)
                    rewards["item"] = item.name
                    if stage == len(TOWER_WAVES) - 1:
                        user.tower_level = max(user.tower_level, int(fight.meta["tower_level"]) + 1)
                        user.data["web_tower_floor"] = 0
                        user.data["web_tower_active"] = False
                        logic.track_quest_progress(user, "tower_complete")
                    else:
                        user.data["web_tower_floor"] = stage + 1
                else:
                    user.data["web_tower_active"] = False
                fight.rewards = rewards
                user.update()
            save_fight(uid, fight)
    except Busy:
        fight = load_fight(uid)
    return render_template("partials/fight.html", fight=fight, fresh_from=_int("log_len"),
                           fight_action=url_for("play.tower_attack"),
                           fight_leave_action=url_for("play.tower_leave"), fight_label="Tower")


@bp.post("/tower/leave")
@player_required
def tower_leave():
    fight = load_fight(session["uid"])
    if fight and fight.kind == "tower" and fight.finished:
        clear_fight(session["uid"])
    return redirect(url_for("play.tower"))


@bp.get("/adventure/dungeon")
@player_required
def dungeon():
    user = _user()
    state = user.data.get("web_dungeon")
    fight = load_fight(session["uid"])
    if fight and fight.kind != "dungeon":
        fight = None
    return render_template("dungeon.html", u=user, state=state,
                           cells=dungeon_logic.map_cells(state["position"], state["triggered"]) if state else [],
                           moves=dungeon_logic.allowed_moves(state["position"]) if state else [],
                           message=user.data.pop("web_dungeon_message", None),
                           fight=fight, fight_action=url_for("play.dungeon_attack"),
                           fight_leave_action=url_for("play.dungeon_leave"), fight_label="Dungeon")


@bp.post("/adventure/dungeon/start")
@player_required
def dungeon_start():
    wager = _int("energy")

    def start(user):
        if not user.main_characters:
            raise GameError("Set up a team before entering the dungeon.")
        if user.data.get("web_dungeon"):
            raise GameError("You are already exploring the dungeon.")
        if wager is None or not 1 <= wager <= user.energy:
            raise GameError("Choose a valid energy wager.")
        user.energy -= wager
        user.data.pop("web_dungeon_message", None)
        user.data["web_dungeon"] = {
            "position": list(dungeon_logic.START), "energy": wager,
            "triggered": [f"{dungeon_logic.START[0]}:{dungeon_logic.START[1]}"],
        }
        return wager

    user, _, error = action(start)
    if error:
        flash(error, "error")
    else:
        flash("Dungeon entered. Reach the exit before your wager runs out.", "ok")
    return redirect(url_for("play.dungeon"))


@bp.post("/adventure/dungeon/move")
@player_required
def dungeon_move():
    direction = request.form.get("direction", "")

    def move(user):
        state = user.data.get("web_dungeon")
        if not state:
            raise GameError("Start a dungeon run first.")
        user.data.pop("web_dungeon_message", None)
        position = tuple(state["position"])
        target = dungeon_logic.moved_position(position, direction)
        if target is None:
            raise GameError("That tile is blocked.")
        state["position"] = list(target)
        state["energy"] -= 1
        key = f"{target[0]}:{target[1]}"
        event = dungeon_logic.event_at(target) if key not in state["triggered"] else None
        if event:
            state["triggered"].append(key)
        if event == "fight":
            return {"kind": "fight", "position": target, "enemy_ids": dungeon_logic.FIGHTS[target]}
        if event == "chest":
            item = item_from_dict({"id": dungeon_logic.chest_item(target)})
            user.items.append(item)
            user.data["web_dungeon_message"] = f"Chest found: {item.name} {item.emoji}."
        elif event == "bomb":
            state["energy"] -= 2
            user.data["web_dungeon_message"] = "A bomb costs 2 more energy."
        elif event == "exit":
            user.energy += max(0, state["energy"])
            user.data.pop("web_dungeon", None)
            user.data["web_dungeon_completions"] = int(user.data.get("web_dungeon_completions", 0)) + 1
            user.data["web_dungeon_message"] = "Dungeon cleared. Unspent wagered energy was returned."
            logic.track_quest_progress(user, "dungeon_complete")
            logic.check_achievements(user, "dungeon_complete")
            return {"kind": "complete"}
        if state["energy"] <= 0:
            user.data.pop("web_dungeon", None)
            user.data["web_dungeon_message"] = "The expedition ran out of energy before reaching the exit."
            return {"kind": "exhausted"}
        return {"kind": event or "move"}

    user, result, error = action(move)
    if error:
        flash(error, "error")
        return redirect(url_for("play.dungeon"))
    if result and result["kind"] == "fight":
        enemies = []
        for char_id in result["enemy_ids"]:
            enemies.append(character_from_dict({"id": char_id, "xp": 100, "types": [], "qualities": [],
                                                "awaken": 3, "items": [{"id": 1}, {"id": 1}, {"id": 1}]}))
        fight = Fight(Side(session.get("name", "You"), fighting_copy(user.main_characters), True,
                           session.get("avatar")),
                      Side("Dungeon monsters", enemies, False), kind="dungeon",
                      meta={"position": list(result["position"])})
        fight.advance()
        save_fight(session["uid"], fight)
    return redirect(url_for("play.dungeon"))


@bp.post("/adventure/dungeon/attack")
@player_required
def dungeon_attack():
    uid = session["uid"]
    try:
        with user_lock(uid, ttl=5):
            fight = load_fight(uid)
            if fight is None or fight.kind != "dungeon":
                return '<p class="notice">This dungeon fight is no longer active. <a href="/adventure/dungeon">Back to dungeon</a></p>', 409
            if not fight.finished:
                if request.form.get("forfeit"):
                    fight.forfeit()
                else:
                    fight.advance(_int("target"))
            if fight.finished and fight.rewards is None:
                user = get_db().get_user(uid)
                won = fight.winner == 0
                for char in user.main_characters:
                    char.xp += 10
                user.xp += 100
                state = user.data.get("web_dungeon")
                if state and not won:
                    state["energy"] -= 2
                exhausted = bool(state and state["energy"] <= 0)
                if exhausted:
                    user.data.pop("web_dungeon", None)
                    user.data["web_dungeon_message"] = "The expedition ran out of energy before reaching the exit."
                elif won:
                    user.data["web_dungeon_message"] = "Monsters defeated. Continue toward the exit."
                else:
                    user.data["web_dungeon_message"] = "The team was defeated and lost 2 more energy."
                fight.rewards = {"won": won, "fragments": 0, "xp": 100,
                                 "stand_xp": 10, "item": None, "dungeon_exhausted": exhausted}
                user.update()
            save_fight(uid, fight)
    except Busy:
        fight = load_fight(uid)
    return render_template("partials/fight.html", fight=fight, fresh_from=_int("log_len"),
                           fight_action=url_for("play.dungeon_attack"),
                           fight_leave_action=url_for("play.dungeon_leave"), fight_label="Dungeon")


@bp.post("/adventure/dungeon/leave")
@player_required
def dungeon_leave():
    fight = load_fight(session["uid"])
    if fight and fight.kind == "dungeon" and fight.finished:
        clear_fight(session["uid"])
    return redirect(url_for("play.dungeon"))
