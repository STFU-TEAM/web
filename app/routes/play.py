"""Logged-in game pages. Every mutation goes through `action()`: take the
per-user lock, reload fresh data from Redis, apply the rule, save."""
from flask import Blueprint, current_app, flash, redirect, render_template, request, session, url_for

from app.auth import player_required
from app.db import Busy, clear_fight, get_db, load_fight, r, save_fight, user_lock
from app.game import logic
from app.game import dungeon as dungeon_logic
from app import wiki as wiki_data
from app.filters import power_score
from app.game.character import CHARACTER_FILE, character_from_dict
from app.game.fight import Fight, Side, fighting_copy
from app.game.items import item_file, item_from_dict
from app.game.logic import BANNERS, DEFAULT_SHOP, RECIPES, GameError
from app.game.quests import QUEST_BY_ID, ensure_quests_assigned

from app.routes.fightturn import play_turn  # noqa: E402
from app.game import tower as tower_logic  # noqa: E402

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
        "streak": logic.streak(user), "streak_rewards": logic.STREAK_REWARDS,
    }


def storage_shelves(user):
    return [("all", 0, "Collection", user.storage_characters)]


def _refill(user):
    """Apply the bot's energy refill on page load (it also runs every minute bot-side)."""
    if logic.refill_energy(user):
        user.update()


@bp.before_request
def dungeon_closed():
    if (request.endpoint or "").startswith("play.dungeon") and not current_app.config.get("DUNGEON_ENABLED"):
        flash("The dungeon is closed for now. Try the story or the weekly boss rush.", "error")
        return redirect(url_for("battles.index"))


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
                           fight=load_fight(session["uid"]), **collection_ctx(user))


@bp.get("/team/collection")
@player_required
def collection():
    return _collection(_user())


def collection_ctx(user):
    """Per-stand facts the collection grid shows: copies for fusing, locks, power."""
    counts = {}
    for c in user.storage_characters:
        counts[c.id] = counts.get(c.id, 0) + 1
    fusable = sum(len(f) for _, f in logic.auto_fuse_plan(user))
    return {"locked": logic.locked(user), "copies": counts, "fusable": fusable, "suggested": logic.best_team(user),
            "power": {c.uuid: power_score(c) for c in user.main_characters + user.storage_characters}}


def _collection(user, message=None, error=None):
    return render_template("partials/collection.html", u=user, message=message, error=error,
                           shelves=storage_shelves(user), shelf=request.values.get("shelf", "s0"),
                           **collection_ctx(user))


@bp.get("/team/stand/<uuid>")
@player_required
def stand_panel(uuid):
    user = _user()
    char, lst, _ = user.find_character_by_uuid(uuid)
    if char is None:
        return '<p class="notice">That stand is no longer in your collection.</p>', 404
    in_team = lst is user.main_characters
    return render_template("partials/stand_panel.html", u=user, c=char, in_team=in_team,
                           dupes=[d for d in user.storage_characters if d.id == char.id and d.uuid != char.uuid],
                           is_locked=uuid in logic.locked(user), wiki=wiki_data.stand_links(char.id),
                           equipable=[g for g in _grouped(user.items) if g["item"].is_equipable],
                           power=power_score(char), template=CHARACTER_FILE[char.id - 1])


@bp.post("/team/lock")
@player_required
def lock():
    uuid = request.form.get("uuid")
    user, res, err = action(lambda u: logic.toggle_lock(u, uuid))
    c = user.find_character_by_uuid(uuid)[0] if not err else None
    return _collection(user, (f"{c.name} locked." if res else f"{c.name} unlocked.") if c else None, err)


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
        if len(uuids) > len(res):
            msg += f" {len(uuids) - len(res)} locked or team stand{'s' if len(uuids) - len(res) != 1 else ''} kept."
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


@bp.post("/team/autofuse")
@player_required
def autofuse():
    user, res, err = action(logic.auto_fuse)
    msg = None
    if res:
        msg = (f"Auto-fuse: {res['copies']} duplicate{'s' if res['copies'] != 1 else ''} fused into "
               f"{len(res['stands'])} stand{'s' if len(res['stands']) != 1 else ''}.")
    if request.values.get("view") == "toast":  # from the pull result
        return render_template("partials/autofuse_toast.html", u=user, message=msg, error=err)
    return _collection(user, msg, err)


@bp.post("/team/lock-many")
@player_required
def lock_many():
    uuids, lock_them = request.form.getlist("uuid"), request.form.get("lock") == "1"
    user, res, err = action(lambda u: logic.set_locks(u, uuids, lock_them))
    msg = None if err else f"{res} stand{'s' if res != 1 else ''} {'locked' if lock_them else 'unlocked'}."
    return _collection(user, msg, err)


# --------------------------------------------------------------------------- #
# Reforge
# --------------------------------------------------------------------------- #
def _forge_ctx(user, uuid=None, rolled=False, error=None, message=None):
    stands = user.main_characters + user.storage_characters
    pending = logic.reforge_pending(user)
    uuid = uuid or (pending["uuid"] if pending else None) or (stands[0].uuid if stands else None)
    char = next((c for c in stands if c.uuid == uuid), None)
    pending = logic.reforge_pending(user, uuid) if char else None
    ctx = {"u": user, "stands": stands, "char": char, "pending": pending, "rolled": rolled, "error": error,
           "message": message, "price": logic.REFORGE_PRICE, "lock_mult": logic.REFORGE_LOCK_MULT,
           "power": {c.uuid: power_score(c) for c in stands}, "team": {c.uuid for c in user.main_characters}}
    if char:
        ctx["costs"] = [logic.reforge_cost(char, n) for n in range(max(1, len(char.types)))]
        if pending:
            ctx["new"] = logic.preview_with(char, pending["types"], pending["qualities"])
            ctx["old_power"], ctx["new_power"] = power_score(char), power_score(ctx["new"])
    return ctx


@bp.get("/reforge")
@player_required
def reforge_page():
    return render_template("reforge.html", **_forge_ctx(_user(), request.args.get("uuid")))


@bp.get("/reforge/panel")
@player_required
def reforge_panel():
    return render_template("partials/forge_panel.html", **_forge_ctx(_user(), request.args.get("uuid")))


@bp.post("/reforge/roll")
@player_required
def reforge_roll():
    uuid = request.form.get("uuid")
    locked = [int(i) for i in request.form.getlist("lock") if i.isdigit()]
    user, res, err = action(lambda u: logic.reforge_roll(u, uuid, locked))
    return render_template("partials/forge_panel.html", **_forge_ctx(user, uuid, rolled=bool(res), error=err))


@bp.post("/reforge/keep")
@player_required
def reforge_keep():
    keep_new = request.form.get("keep") == "new"
    user, res, err = action(lambda u: logic.reforge_keep(u, keep_new))
    msg = None
    if res:
        msg = f"{res.name} keeps the new roll." if keep_new else f"{res.name} keeps its old roll."
    return render_template("partials/forge_panel.html", **_forge_ctx(user, res.uuid if res else None, error=err, message=msg))


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


@bp.post("/team/suggested")
@player_required
def use_suggested():
    uuids = request.form.getlist("uuid")
    user, res, err = action(lambda u: logic.use_team(u, uuids))
    return _collection(user, "Suggested team in place: " + ", ".join(c.name for c in res) + "." if res else None, err)


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
    active = [b for b in BANNERS if logic.banner_enabled(b)]
    arrows = sum(1 for i in user.items if i.id == 2)
    rank = {"R": 0, "SR": 1, "SSR": 2, "UR": 3, "LR": 4}
    history = [{**h, "rarities": sorted(h["rarities"], key=lambda x: -rank.get(x, 0))}
               for h in user.data.get("web_pull_history", [])[:10]]
    return render_template("banners.html", u=user, banners=active, arrows=arrows, st=status(user),
                           sparks=logic.sparks(user), SPARK_COST=logic.SPARK_COST,
                           welcome=request.args.get("welcome"), history=history)


@bp.post("/banners/<int:banner_id>/spark")
@player_required
def spark(banner_id: int):
    stand_id = _int("stand")
    user, res, err = action(lambda u: logic.spark_exchange(u, banner_id, stand_id))
    if err:
        flash(err, "error")
    else:
        flash(f"Spark exchange: {res.name} joined your collection.", "ok")
    return redirect(url_for("play.banners") + f"#banner-{banner_id}")


@bp.post("/banners/<int:banner_id>/<mode>")
@player_required
def pull(banner_id: int, mode: str):
    fn = logic.banner_pull if mode == "pull" else logic.arrow_pull
    user, res, err = action(lambda u: fn(u, banner_id))
    arrows = sum(1 for i in user.items if i.id == 2)
    rarity_score = {"R": 0, "SR": 1, "SSR": 2, "UR": 3, "LR": 4}
    top_rarity = max((char.rarity for char, _ in res["drawn"]), key=rarity_score.get) if res else "R"
    if res:  # rarest last: reveal builds up to the best card
        res["cards"].sort(key=lambda e: rarity_score.get(e["stand"].rarity, 0))
    opening_id = 6 if top_rarity in ("UR", "LR") else 5 if top_rarity == "SSR" else 4
    banner = next((b for b in BANNERS if b["id"] == banner_id), None)
    fusable = sum(len(f) for _, f in logic.auto_fuse_plan(user))
    return render_template("partials/pull_result.html", u=user, res=res, error=err, arrows=arrows,
                           mode=mode, top_rarity=top_rarity, opening_id=opening_id, banner=banner,
                           fusable=fusable, free=logic.free_slots(user))


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
        result = item_from_dict({"id": r["result"]})
        out.append({"name": r["name"], "parts": parts, "ready": all(h >= n for _, n, h in parts), "result": result})
    return out


def _items_ctx(user):
    return {"u": user, "groups": _grouped(user.items), "recipes": _recipes(user), "shop": DEFAULT_SHOP,
            "sell_price": logic.sell_price}


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


@bp.post("/items/equip")
@player_required
def item_equip():
    uuid, item_id = request.form.get("uuid"), _int("item")
    user, res, err = action(lambda u: logic.equip(u, uuid, item_id))
    return render_template("partials/use_result.html", res={"kind": "equipped", "stand": res[0], "item": res[1]} if res else None,
                           error=err, **_items_ctx(user))


@bp.post("/items/unequip")
@player_required
def item_unequip():
    uuid, slot = request.form.get("uuid"), _int("slot")
    user, res, err = action(lambda u: logic.unequip(u, uuid, slot))
    return render_template("partials/use_result.html", res={"kind": "unequipped", "stand": res[0], "item": res[1]} if res else None,
                           error=err, **_items_ctx(user))


@bp.post("/items/sell")
@player_required
def sell():
    item_id = _int("item")
    count = len([i for i in _user().items if i.id == item_id]) if request.form.get("all") else 1
    user, res, err = action(lambda u: logic.sell_item(u, item_id, count))
    return render_template("partials/use_result.html", res={"kind": "sold", **res} if res else None,
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
QUEST_ICONS = {"wormhole": "◎", "tower": "▲", "rush": "♛", "story": "📜", "raid": "⚑", "banner": "✦", "reforge": "⚒",
               "fuse": "♟", "item": "◈", "shop": "⚖", "daily": "🎁", "ranked": "⚔", "fight": "⚔", "invite": "♥",
               "friends": "♥", "level": "★", "requiem": "✧"}


def _quest_icon(action: str) -> str:
    return next((icon for key, icon in QUEST_ICONS.items() if key in action), "☑")


def _reward_chips(rewards: dict) -> list:
    """[(kind, text)] for the reward line: dust / head / palm get currency icons, other items their name."""
    chips = []
    if rewards.get("fragments"):
        chips.append(("dust", rewards["fragments"]))
    if rewards.get("super_fragments"):
        chips.append(("head", rewards["super_fragments"]))
    palms = sum(1 for i in rewards.get("items", []) if i["id"] == 2)
    if palms:
        chips.append(("palm", palms))
    for i in rewards.get("items", []):
        if i["id"] != 2:
            chips.append(("item", item_file[i["id"] - 1]["name"]))
    if rewards.get("xp"):
        chips.append(("xp", rewards["xp"]))
    return chips


def _quest_rows(user):
    ensure_quests_assigned(user)
    out = {}
    for key, label in (("active_daily", "Daily"), ("active_weekly", "Weekly"), ("active_permanent", "Journey")):
        rows = []
        for e in user.quests.get(key, []):
            q = QUEST_BY_ID.get(e["quest_id"])
            if q:
                rows.append({"q": q, "progress": min(e["progress"], q["target"]), "claimed": e["claimed"],
                             "ready": e["progress"] >= q["target"] and not e["claimed"],
                             "icon": _quest_icon(q["action"]), "chips": _reward_chips(q["rewards"])})
        # ready first, then closest to done, claimed last
        rows.sort(key=lambda r: (r["claimed"], not r["ready"], -r["progress"] / max(1, r["q"]["target"])))
        out[label] = rows
    return out


def _resets():
    """Time left until the daily and weekly quest resets (quests run on server time + 2h, like the bot did)."""
    import datetime
    now = datetime.datetime.now() + datetime.timedelta(hours=2)
    midnight = datetime.datetime.combine(now.date() + datetime.timedelta(days=1), datetime.time())
    monday = datetime.datetime.combine(now.date() + datetime.timedelta(days=7 - now.weekday()), datetime.time())
    return {"Daily": midnight - now, "Weekly": monday - now}


def _sync_social_quests(u):
    """Quests fed by other players' actions: friends made and invited friends who got going."""
    from app import social
    ensure_quests_assigned(u)
    logic.track_quest_progress(u, "reach_friends", len(social.friends(str(u.id))))
    logic.check_achievements(u, "reach_friends", len(social.friends(str(u.id))))
    invited = social.take_referrals(str(u.id))
    if invited:
        logic.track_quest_progress(u, "invite_friend", invited)


def _quests_ctx(user, **extra):
    from app.game.quests import locked_preview, story_progress
    groups = _quest_rows(user)
    ready = {label: sum(r["ready"] for r in rows) for label, rows in groups.items()}
    tab = request.values.get("tab", "")
    if tab not in groups:  # open the first list with something to claim
        tab = next((label for label, n in ready.items() if n), "Daily")
    return {"u": user, "groups": groups, "locked": locked_preview(user), "story_done": story_progress(user),
            "resets": _resets(), "open_tab": tab, "ready_total": sum(ready.values()),
            "invite_url": url_for("community.join", ref=user.id, _external=True), **extra}


@bp.get("/quests")
@player_required
def quests():
    user, _, _ = action(_sync_social_quests)  # assignment is saved, like /quest view
    return render_template("quests.html", **_quests_ctx(user))


@bp.post("/quests/claim")
@player_required
def quest_claim():
    qid = _int("quest")
    if qid is None:
        user, res, err = action(logic.quest_claim_all)
    else:
        user, res, err = action(lambda u: [logic.quest_claim(u, qid)])
    return render_template("partials/quests_body.html", **_quests_ctx(user, claimed=res, error=err))


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
        foes = Side(name, enemies, False)
        foes.ai = "easy" if u.level < 5 else "smart"
        fight = Fight(Side(session.get("name", "You"), fighting_copy(u.main_characters), True, session.get("avatar")),
                      foes, meta={"multi": multi})
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
    return play_turn("wormhole", url_for("play.wormhole"), "Wormhole", "play.wormhole_attack", "play.wormhole_leave",
                     lambda user, fight: logic.wormhole_reward(user, fight.winner == 0, fight.meta.get("multi", 1)))

@bp.post("/wormhole/leave")
@player_required
def wormhole_leave():
    fight = load_fight(session["uid"])
    if fight and fight.kind == "wormhole" and fight.finished:
        clear_fight(session["uid"])
    return redirect(url_for("play.wormhole"))


# --------------------------------------------------------------------------- #
# Tower: endless weekly climb (app/game/tower.py)
# --------------------------------------------------------------------------- #
TOWER_COST = tower_logic.CLIMB_COST


@bp.get("/tower")
@player_required
def tower():
    user = _user()
    uid = session["uid"]
    fight = load_fight(uid)
    other_fight = fight.kind if fight and fight.kind != "tower" and not fight.finished else None
    fight = fight if fight and fight.kind == "tower" else None
    s = tower_logic.state(user)
    floor = s["run"]["floor"] if s.get("run") else 1
    team = tower_logic.load_team(r(), uid) if s.get("run") else None
    shown = range(max(1, floor - 2), floor + 5)
    return render_template("tower.html", u=user, s=s, floor=floor, team=team, fight=fight, other_fight=other_fight,
                           floors=[tower_logic.preview(f) for f in reversed(shown)], cost=TOWER_COST,
                           reward=tower_logic.reward_text(floor), board=tower_logic.leaderboard(r()),
                           ends_in=tower_logic.ends_in(), rest_heal=round(tower_logic.REST_HEAL * 100),
                           floor_heal=round(tower_logic.FLOOR_HEAL * 100), revive=round(tower_logic.REVIVE * 100),
                           fight_action=url_for("play.tower_attack"),
                           fight_leave_action=url_for("play.tower_leave"), fight_label="Tower")


@bp.post("/tower/start")
@player_required
def tower_start():
    """Begin a climb (pays the entry) or fight the next floor of the climb in progress."""
    uid = session["uid"]
    existing = load_fight(uid)
    if existing and not existing.finished:
        return redirect(url_for("play.tower"))

    def start(user):
        s = tower_logic.state(user)
        if not s.get("run"):
            tower_logic.start_climb(user, r(), fighting_copy(user.main_characters))
            logic.track_quest_progress(user, "tower_attempt")
            logic.check_achievements(user, "tower_attempt")
        team = tower_logic.load_team(r(), uid)
        if not team or not any(c.is_alive() for c in team):
            tower_logic.abandon(user, r())
            raise GameError("Your climb expired or your team is down. Start a new climb.")
        floor = s["run"]["floor"]
        fight = Fight(Side(session.get("name", "You"), team, True, session.get("avatar")),
                      Side(f"Floor {floor}", tower_logic.floor_team(floor), False), kind="tower",
                      meta={"floor": floor})
        fight.advance()
        save_fight(uid, fight)

    _, _, err = action(start)
    if err:
        flash(err, "error")
    return redirect(url_for("play.tower"))


@bp.post("/tower/abandon")
@player_required
def tower_abandon():
    if load_fight(session["uid"]) and not load_fight(session["uid"]).finished:
        flash("Finish the floor you're on first.", "error")
        return redirect(url_for("play.tower"))
    action(lambda u: tower_logic.abandon(u, r()))
    flash("Climb ended. Your best floor this week still counts.", "ok")
    return redirect(url_for("play.tower"))


def _tower_settle(user, fight):
    rewards = tower_logic.finish_floor(user, fight, r(), session.get("name", "?"))
    if rewards["won"]:
        logic.track_quest_progress(user, "tower_floor")
        logic.track_quest_progress(user, "reach_tower", rewards.get("tower", {}).get("floor", 0))
    return rewards


@bp.post("/tower/attack")
@player_required
def tower_attack():
    return play_turn("tower", url_for("play.tower"), "Tower", "play.tower_attack", "play.tower_leave", _tower_settle)


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


def _dungeon_settle(user, fight):
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
    return {"won": won, "fragments": 0, "xp": 100, "stand_xp": 10, "item": None, "dungeon_exhausted": exhausted}


@bp.post("/adventure/dungeon/attack")
@player_required
def dungeon_attack():
    return play_turn("dungeon", url_for("play.dungeon"), "Dungeon", "play.dungeon_attack", "play.dungeon_leave",
                     _dungeon_settle)

@bp.post("/adventure/dungeon/leave")
@player_required
def dungeon_leave():
    fight = load_fight(session["uid"])
    if fight and fight.kind == "dungeon" and fight.finished:
        clear_fight(session["uid"])
    return redirect(url_for("play.dungeon"))
