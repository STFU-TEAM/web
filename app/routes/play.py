"""Logged-in game pages. Every mutation goes through `action()`: take the
per-user lock, reload fresh data from Redis, apply the rule, save."""
import json

from flask import Blueprint, abort, current_app, flash, redirect, render_template, request, session, url_for

from app.auth import player_required
from app.db import Busy, clear_fight, get_db, load_fight, r, save_fight, user_lock
from app.game import gear, logic, mastery
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
        "energy_in": logic.energy_refill_in(user), "energy_next": logic.energy_next_in(user),
        "free_slots": logic.free_slots(user),
        "streak": logic.streak(user), "streak_rewards": logic.streak(user)["ladder"],
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
                           fight=load_fight(session["uid"]), gang_hub=_gang_hub(user), **collection_ctx(user))


def _gang_hub(user):
    """The gang banner at the top of the team page: your gang at a glance, or why to join one."""
    from app.game import gangs as G
    from app.game import journey
    db = get_db()
    gang = db.get_gang(user.gang_id)
    hub = {"gang": gang, "journeys_ready": journey.ready_count(user), "journeys": len(journey.journeys(user)),
           "villain": G.weekly_boss()}
    if gang:
        raid = G.raid_state(gang)
        opp = G.opponent_id(r(), gang["_id"])
        hub.update(members=len(G.members(gang)), rank=G.RANK_NAMES.get(G.rank_of(gang, user.id), ""),
                   raid_ready=G.can_attack(gang, user.id), raid_damage=raid.get("damage", 0),
                   at_war=bool(opp), vault=gang.get("vault", 0), claim=len(G.claimable_tiers(gang, user.id)))
    else:
        hub["invites"] = len(user.gang_invites)
    return hub


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
            "power": {c.uuid: power_score(c) for c in user.main_characters + user.storage_characters},
            "max_teams": logic.MAX_TEAMS}


def _collection(user, message=None, error=None):
    return render_template("partials/collection.html", u=user, message=message, error=error,
                           shelves=storage_shelves(user), shelf=request.values.get("shelf", "s0"),
                           **collection_ctx(user))


def _bag_copies(items) -> dict:
    out = {}
    for it in items:
        out[it.id] = out.get(it.id, 0) + 1
    return out


def _panel_items(user, char) -> list:
    """The bag's gear for a stand's panel, each line saying what equipping it would change on this stand."""
    from app.game.items import spare
    from app.game.pickers import owned_items
    opts = owned_items(user.items, equipable=True)
    for o in opts:
        best = spare(user.items, o["id"])[-1]
        o["m"] = f"×{o['q']}{' · +' + str(best.refine) if best.refine else ''} · {gear.preview_line(char, best)}"
    return opts


@bp.get("/team/stand/<uuid>")
@player_required
def stand_panel(uuid):
    user = _user()
    char, lst, _ = user.find_character_by_uuid(uuid)
    if char is None:
        return '<p class="notice">That stand is no longer in your collection.</p>', 404
    in_team = lst is user.main_characters
    from app.game import chips
    return render_template("partials/stand_panel.html", u=user, c=char, in_team=in_team,
                           chip_slots=chips.slots(char), socketed=[chips.view(x) for x in chips.socketed(char)],
                           fitting=[chips.view(x) for x in chips.bag(user) if chips.fits(x, char)],
                           dupes=[d for d in user.storage_characters if d.id == char.id and d.uuid != char.uuid],
                           is_locked=uuid in logic.locked(user), wiki=wiki_data.stand_links(char.id),
                           equipable=[g for g in _grouped(user.items) if g["item"].is_equipable],
                           equip_options=_panel_items(user, char) if in_team else [],
                           sets=gear.active_sets(char.items), bag_copies=_bag_copies(user.items),
                           power=power_score(char), template=CHARACTER_FILE[char.id - 1],
                           mastery=mastery.of(r(), user.id, char.id))


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


@bp.post("/team/arrow")
@player_required
def arrow():
    """A Requiem Arrow from the stand panel: mode "awaken" (+1 star, keeps the stand) or "requiem" (evolve)."""
    uuid, mode = request.form.get("uuid"), request.form.get("mode")
    if mode not in ("awaken", "requiem"):
        return _collection(_user(), None, "Choose to awaken it or to make it Requiem.")
    user, res, err = action(lambda u: logic.use_item(u, 3, uuid, mode))
    msg = None
    if res:
        msg = (f"✧ Requiem! It became {res['stand'].name}." if res["kind"] == "requiem"
               else f"{res['stand'].name} reached awakening {res['stand'].awaken}.")
    return _collection(user, msg, err)


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
        ctx["locks"] = logic.remembered_locks(user, char)
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


@bp.post("/reforge/locks")
@player_required
def reforge_locks():
    """Remember the locks as they're toggled, so they're still there next time (even without a reforge)."""
    uuid = request.form.get("uuid")
    locked = [int(i) for i in request.form.getlist("lock") if i.isdigit()]
    action(lambda u: logic.remember_locks(u, uuid, locked))
    return "", 204


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
    return _collection(user, f"{res[1].label} equipped on {res[0].name}." if res else None, err)


@bp.post("/team/refine")
@player_required
def refine_equipped():
    uuid, item_id, slot = request.form.get("uuid"), _int("item"), _int("slot")
    user, res, err = action(lambda u: gear.refine(u, item_id, uuid, slot))
    return _collection(user, f"{res.label} refined." if res else None, err)


@bp.post("/team/unequip")
@player_required
def unequip():
    uuid, slot = request.form.get("uuid"), _int("slot")
    user, res, err = action(lambda u: logic.unequip(u, uuid, slot))
    return _collection(user, f"{res[1].name} removed from {res[0].name}." if res else None, err)


@bp.post("/team/chip/socket")
@player_required
def chip_socket():
    from app.game import chips
    uuid, chip_id = request.form.get("uuid"), request.form.get("chip", "")
    user, res, err = action(lambda u: chips.socket(u, uuid, chip_id))
    return _collection(user, f"{chips.view(res[1])['label']} chip socketed into {res[0].name}." if res else None, err)


@bp.post("/team/chip/unsocket")
@player_required
def chip_unsocket():
    from app.game import chips
    uuid, chip_id = request.form.get("uuid"), request.form.get("chip", "")
    user, res, err = action(lambda u: chips.unsocket(u, uuid, chip_id))
    return _collection(user, f"{chips.view(res[1])['label']} chip back in your bag." if res else None, err)


# --------------------------------------------------------------------------- #
# Stand chips (app/game/chips.py)
# --------------------------------------------------------------------------- #
def _chips_ctx(user, message=None, error=None):
    from app.game import chips
    owned = user.main_characters + user.storage_characters
    tier_rank = list(chips.TIERS)
    shown = sorted(chips.bag(user), key=lambda x: (-tier_rank.index(x["tier"]), x["syn"]))
    rows = [{**chips.view(x), "fits": [c.name for c in owned if chips.fits(x, c)]} for x in shown]
    worn = [{"stand": c, "chips": [chips.view(x) for x in chips.socketed(c)], "slots": chips.slots(c)}
            for c in owned if c.data.get("chips")]
    return {"u": user, "rows": rows, "worn": worn, "bag_max": chips.BAG_MAX, "message": message, "error": error,
            "slot_max": chips.SLOT_MAX}


@bp.get("/chips")
@player_required
def chips_page():
    return render_template("chips.html", **_chips_ctx(_user()))


@bp.post("/chips/scrap")
@player_required
def chips_scrap():
    from app.game import chips
    ids = request.form.getlist("chip")
    if request.form.get("tier"):  # scrap every spare chip of one tier
        ids = [x["id"] for x in chips.bag(_user()) if x["tier"] == request.form["tier"]]
    user, dust, err = action(lambda u: chips.scrap(u, ids))
    return render_template("partials/chip_bag.html", **_chips_ctx(
        user, f"Scrapped {len(ids)} chip{'s' if len(ids) != 1 else ''} for {dust:,} Meteor Dust." if dust else None, err))


@bp.post("/chips/reroll")
@player_required
def chips_reroll():
    from app.game import chips
    user, chip, err = action(lambda u: chips.reroll(u, request.form.get("chip", "")))
    msg = f"New roll: {', '.join(chips.view(chip)['lines'])}." if chip else None
    return render_template("partials/chip_bag.html", **_chips_ctx(user, msg, err))


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


@bp.post("/team/preset/update")
@player_required
def preset_update():
    name = request.form.get("name", "")
    user, res, err = action(lambda u: logic.team_update(u, name))
    return _collection(user, f"Preset “{res}” now holds your current team." if res else None, err)


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
    active.sort(key=lambda b: (bool(b.get("theme")), b["id"]))  # the Parts, then the theme
    return render_template("banners.html", u=user, banners=active, arrows=arrows, st=status(user),
                           sparks=logic.sparks(user), SPARK_COST=logic.SPARK_COST,
                           welcome=request.args.get("welcome"), history=history,
                           schedule=logic.banner_schedule(7), rotates_in=logic.rotation_ends() - logic.now(),
                           forced=_forced_rarity(), FORCE_RARITIES=FORCE_RARITIES, PITY_ODDS=logic.PITY_ODDS)


def banner_odds(banner: dict) -> dict:
    """Per-rarity and per-stand chances for a banner, as the draw code applies them."""
    order = ["LR", "UR", "SSR", "SR", "R"]
    pools = {r: [CHARACTER_FILE[i - 1] for i in banner["cards"] if CHARACTER_FILE[i - 1]["rarity"] == r] for r in order}

    def effective(odds):
        """A rarity the banner lacks falls to the nearest one below, then above (logic._template_of)."""
        up = ["R", "SR", "SSR", "UR", "LR"]
        out = dict.fromkeys(up, 0.0)
        for r, p in odds.items():
            i = up.index(r)
            target = next((x for x in up[i::-1] + up[i + 1:] if pools[x]), r)
            out[target] += p
        return out
    pulls, palms = effective(logic.BANNER_ODDS), effective(logic.ARROW_ODDS)
    rows = []
    for r in order:
        n = len(pools[r])
        pull, palm = pulls[r], palms[r]
        if n or pull or palm:
            rows.append({"rarity": r, "count": n, "pull": pull if n else 0, "palm": palm if n else 0,
                         "pull_each": pull / n if n else 0, "palm_each": palm / n if n else 0})
    groups = [{"rarity": r, "stands": pools[r],
               "each": (pulls[r] or logic.PITY_ODDS.get(r, 0)) / len(pools[r])} for r in order if pools[r]]
    missing = [r for r in ("R", "SR", "SSR", "UR") if not pools[r]]
    return {"rows": rows, "groups": groups, "missing": missing, "has_lr": bool(pools["LR"])}


@bp.get("/banners/<int:banner_id>/details")
@player_required
def banner_details(banner_id: int):
    """Odds and the full stand list of any banner (today's or a later one from the calendar)."""
    b = next((x for x in BANNERS if x["id"] == banner_id), None)
    if b is None:
        abort(404)
    user = _user()
    owned = {c.id for c in user.main_characters + user.storage_characters}
    ctx = {"u": user, "b": b, "owned": owned, "owned_here": len(owned & set(b["cards"])),
           "active": logic.banner_enabled(b), "next": logic.next_appearance(b["id"]),
           "rotates_in": logic.rotation_ends() - logic.now(), "PITY_ODDS": logic.PITY_ODDS, **banner_odds(b)}
    if request.headers.get("HX-Request"):
        return render_template("partials/banner_details.html", **ctx)
    return render_template("banner_page.html", **ctx)


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


FORCE_KEY = "web:admin:force_rarity:{}"
FORCE_RARITIES = ("R", "SR", "SSR", "UR", "LR")


def _is_admin() -> bool:
    from app.auth import is_admin
    return is_admin(session.get("uid"))


def _forced_rarity():
    """An admin's test setting for their own pulls: {"rarity", "scope"} or None."""
    if not _is_admin():
        return None
    raw = r().get(FORCE_KEY.format(session["uid"]))
    return json.loads(raw) if raw else None


@bp.post("/banners/force")
@player_required
def force_rarity():
    """Admins only: make their own next pulls land a chosen rarity (to test reveals and drops)."""
    if not _is_admin():
        abort(403)
    from app.routes.admin import audit
    rarity, scope = request.form.get("rarity", ""), request.form.get("scope", "last")
    key = FORCE_KEY.format(session["uid"])
    if rarity in FORCE_RARITIES:
        r().set(key, json.dumps({"rarity": rarity, "scope": "all" if scope == "all" else "last"}), ex=3600)
        audit("force_rarity", session["uid"], rarity=rarity, scope=scope)
        flash(f"Your pulls now force {rarity} on {'every card' if scope == 'all' else 'the last card'} (for an hour).", "ok")
    else:
        r().delete(key)
        flash("Forced rarity cleared: your pulls use the normal odds again.", "ok")
    return redirect(url_for("play.banners"))


@bp.post("/banners/<int:banner_id>/<mode>")
@player_required
def pull(banner_id: int, mode: str):
    fn = logic.banner_pull if mode == "pull" else logic.arrow_pull
    force = _forced_rarity()
    user, res, err = action(lambda u: fn(u, banner_id, force))
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
                           fusable=fusable, free=logic.free_slots(user),
                           banner_ids=[b["id"] for b in BANNERS if logic.banner_enabled(b)])


# --------------------------------------------------------------------------- #
# Items & shop
# --------------------------------------------------------------------------- #
def _grouped(items):
    """One entry per item and refine level (a refined copy has its own card)."""
    groups = {}
    for it in items:
        groups.setdefault((it.id, it.refine), {"item": it, "count": 0})["count"] += 1
    return sorted(groups.values(), key=lambda g: (g["item"].is_equipable, g["item"].id, -g["item"].refine))


def _refinable(items) -> dict:
    """item id -> {level, cost, spares}: refining takes the best copy up a level with a spare copy."""
    out = {}
    for it in items:
        if it.is_equipable:
            row = out.setdefault(it.id, {"level": it.refine, "copies": 0})
            row["level"] = max(row["level"], it.refine)
            row["copies"] += 1
    return {iid: {"level": r["level"], "cost": gear.refine_cost(r["level"]), "spares": r["copies"] - 1}
            for iid, r in out.items()}


def _equip_options(user, groups) -> dict:
    """"id-refine" -> team stand options whose line says what equipping that copy would change."""
    from app.game.pickers import owned
    full = {c.uuid: "Holds 3 items already" for c in user.main_characters if len(c.items) >= 3}
    return {f"{g['item'].id}-{g['item'].refine}": owned(
                user.main_characters, sort=False, blocked=full,
                notes={c.uuid: gear.preview_line(c, g["item"]) for c in user.main_characters if c.uuid not in full})
            for g in groups if g["item"].is_equipable}


def _recipes(user):
    have = {}
    for it in user.items:
        have[it.id] = have.get(it.id, 0) + 1
    out = []
    for r in RECIPES:
        parts = [(item_file[i - 1]["name"], n, have.get(i, 0)) for i, n in r["ingredients"]]
        result = item_from_dict({"id": r["result"]})
        out.append({"name": r["name"], "parts": parts, "ready": all(h >= n for _, n, h in parts), "result": result,
                    "max": logic.craftable(user, r)})
    return out


def _items_ctx(user):
    groups = _grouped(user.items)
    remember_craftable(user)
    return {"u": user, "groups": groups, "recipes": _recipes(user), "shop": DEFAULT_SHOP,
            "sell_price": logic.sell_price, "equip_opts": _equip_options(user, groups), "refinable": _refinable(user.items)}


CRAFTABLE_KEY = "web:craftable:{}"


def remember_craftable(user) -> int:
    """How many recipes the bag can craft now, cached for the Items nav badge (filters.py)."""
    n = sum(1 for rec in RECIPES if logic.craftable(user, rec) > 0)
    r().set(CRAFTABLE_KEY.format(user.id), n, ex=600)
    return n


@bp.get("/items")
@player_required
def items():
    return render_template("items.html", **_items_ctx(_user()))


@bp.post("/items/use")
@player_required
def use():
    item_id, uuid, mode = _int("item"), request.form.get("uuid"), request.form.get("mode")
    user, res, err = action(lambda u: logic.use_item(u, item_id, uuid, mode if mode in ("awaken", "requiem") else None))
    return render_template("partials/use_result.html", res=res, error=err, **_items_ctx(user))


@bp.post("/items/craft")
@player_required
def craft():
    name, count = request.form.get("recipe", ""), max(1, min(99, _int("count", 1) or 1))
    user, res, err = action(lambda u: logic.craft_many(u, name, count))
    return render_template("partials/use_result.html", res={"kind": "crafted", "item": res[0], "count": len(res)} if res else None,
                           error=err, **_items_ctx(user))


@bp.post("/items/refine")
@player_required
def item_refine():
    item_id = _int("item")
    user, res, err = action(lambda u: gear.refine(u, item_id))
    return render_template("partials/use_result.html", res={"kind": "refined", "item": res} if res else None,
                           error=err, **_items_ctx(user))


@bp.post("/items/equip")
@player_required
def item_equip():
    uuid, item_id = request.form.get("uuid"), _int("item")
    user, res, err = action(lambda u: logic.equip(u, uuid, item_id, _int("refine")))
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
    refine = _int("refine")
    count = len([i for i in _user().items if i.id == item_id and (refine is None or i.refine == refine)])         if request.form.get("all") else 1
    user, res, err = action(lambda u: logic.sell_item(u, item_id, count, refine))
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
QUEST_ICONS = {"wormhole": "🪞", "tower": "▲", "rush": "♛", "story": "📜", "raid": "⚑", "banner": "✦", "reforge": "⚒",
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
    from app.game import bounty
    return render_template("quests.html", bounty=bounty.view(user), **_quests_ctx(user))


@bp.post("/bounty/claim")
@player_required
def bounty_claim():
    from app.game import bounty
    _, res, err = action(bounty.claim)
    flash(err or f"{res['icon']} {res['name']} bounty claimed: {res['reward_text']}.", "error" if err else "ok")
    return redirect(url_for("play.quests", _anchor="bounty"))


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
# Mirror World (PvE fight; was the wormhole)
# --------------------------------------------------------------------------- #
@bp.get("/wormhole")
def wormhole_old():
    return redirect(url_for("play.mirror"), 301)


@bp.get("/mirror-world")
@player_required
def mirror():
    user = _user()
    _refill(user)
    fight = load_fight(session["uid"])
    other_fight = None
    if fight and fight.kind != "wormhole":
        other_fight = fight.kind
        fight = None
    team = user.main_characters
    return render_template("mirror.html", u=user, fight=fight, st=status(user), other_fight=other_fight,
                           team_level=round(sum(c.level for c in team) / len(team)) if team else 0,
                           difficulties=logic.MIRROR_DIFFICULTIES,
                           fight_action=url_for("play.mirror_attack"),
                           fight_leave_action=url_for("play.mirror_leave"), fight_label="Mirror World")


@bp.post("/mirror-world/start")
@player_required
def mirror_start():
    uid = session["uid"]
    existing = load_fight(uid)
    if existing and not (existing.kind == "wormhole" and existing.finished):  # a finished one: "Fight again"
        return redirect(url_for("play.mirror"))

    def start(u):
        name, enemies, multi, difficulty = logic.wormhole_start(u)
        foes = Side(f"{name} · {difficulty}", enemies, False)
        foes.ai = "easy" if difficulty == "Faded" or u.level < 5 else "smart"
        fight = Fight(Side(session.get("name", "You"), fighting_copy(u.main_characters), True, session.get("avatar")),
                      foes, meta={"multi": multi, "difficulty": difficulty})
        fight.advance()
        return fight

    user, fight, err = action(start)
    if err:
        flash(err, "error")
        return redirect(url_for("play.mirror"))
    save_fight(uid, fight)
    return redirect(url_for("play.mirror"))


@bp.post("/mirror-world/attack")
@player_required
def mirror_attack():
    return play_turn("wormhole", url_for("play.mirror"), "Mirror World", "play.mirror_attack", "play.mirror_leave",
                     lambda user, fight: logic.wormhole_reward(user, fight.winner == 0, fight.meta.get("multi", 1)))

@bp.post("/mirror-world/leave")
@player_required
def mirror_leave():
    fight = load_fight(session["uid"])
    if fight and fight.kind == "wormhole" and fight.finished:
        clear_fight(session["uid"])
    return redirect(url_for("play.mirror"))


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
                           milestones=tower_logic.milestones(max(floor - 1, s["paid"])),
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


# --------------------------------------------------------------------------- #
# Dungeon: the free daily delve (app/game/dungeon.py)
# --------------------------------------------------------------------------- #
@bp.get("/adventure/dungeon")
@player_required
def dungeon():
    uid = session["uid"]
    user = _user()
    if dungeon_logic.state(user).get("run") and not dungeon_logic.load_team(r(), uid):
        def settle(u):  # a run whose fighters expired: close it (and pay half the bag) once, saved
            msg = dungeon_logic.close_if_stale(u, r())
            if msg:
                u.data["web_dungeon_message"] = msg
        user, _, _ = action(settle)
    s = dungeon_logic.state(user)
    run = s.get("run")
    fight = load_fight(uid)
    other_fight = fight.kind if fight and fight.kind != "dungeon" and not fight.finished else None
    fight = fight if fight and fight.kind == "dungeon" else None
    plan = dungeon_logic.floor_plan(run["day"], run["depth"]) if run else None
    return render_template("dungeon.html", u=user, s=s, run=run, fight=fight, other_fight=other_fight,
                           team=dungeon_logic.load_team(r(), uid) if run else None,
                           cells=dungeon_logic.cells(run) if run else [],
                           moves=dungeon_logic.allowed_moves(run) if run else [],
                           on_stairs=bool(run and tuple(run["pos"]) == plan["stairs"]),
                           waiting=dungeon_logic.fight_tile(user), bag=dungeon_logic.bag_view(run["bag"]) if run else None,
                           message=user.data.pop("web_dungeon_message", None), runs_left=dungeon_logic.runs_left(user),
                           D=dungeon_logic, fight_action=url_for("play.dungeon_attack"),
                           fight_leave_action=url_for("play.dungeon_leave"), fight_label="Dungeon")


def _dungeon_fight(user, kind, enemies):
    team = dungeon_logic.load_team(r(), user.id)
    if not team:
        raise GameError(dungeon_logic.EXPIRED)
    names = {"fight": "Dungeon monsters", "elite": "Dungeon elite", "boss": "Dungeon boss"}
    fight = Fight(Side(session.get("name", "You"), team, True, session.get("avatar")),
                  Side(names[kind], enemies, False), kind="dungeon", meta={"event": kind})
    fight.advance()
    save_fight(session["uid"], fight)


def _dungeon_busy():
    fight = load_fight(session["uid"])
    if fight and not fight.finished:
        flash("Finish the fight you're in first.", "busy")
        return True
    return False


@bp.post("/adventure/dungeon/start")
@player_required
def dungeon_start():
    if _dungeon_busy():
        return redirect(url_for("play.dungeon"))

    def start(user):
        dungeon_logic.start(user, r(), fighting_copy(user.main_characters))

    _, _, error = action(start)
    flash(error or "You step into the dark. Find the stairs.", "error" if error else "ok")
    return redirect(url_for("play.dungeon"))


@bp.post("/adventure/dungeon/move")
@player_required
def dungeon_move():
    if _dungeon_busy():
        return redirect(url_for("play.dungeon"))
    direction = request.form.get("direction", "")

    def move(user):
        result = dungeon_logic.move(user, r(), direction)
        if result["message"]:
            user.data["web_dungeon_message"] = result["message"]
        if result["kind"] == "fight":
            _dungeon_fight(user, result["event"], result["enemies"])
        return result

    _, _, error = action(move)
    if error:
        flash(error, "error")
    return redirect(url_for("play.dungeon"))


@bp.post("/adventure/dungeon/fight")
@player_required
def dungeon_fight():
    """Fight the enemies on your tile again (after a reload, or a fight that expired)."""
    if _dungeon_busy():
        return redirect(url_for("play.dungeon"))

    def fight(user):
        expired = dungeon_logic.close_if_stale(user, r())
        if expired:
            user.data["web_dungeon_message"] = expired
            return
        kind = dungeon_logic.fight_tile(user)
        if not kind:
            raise GameError("Nothing to fight here.")
        run = dungeon_logic.state(user)["run"]
        _dungeon_fight(user, kind, dungeon_logic.enemies(run, tuple(run["pos"]), kind))

    _, _, error = action(fight)
    if error:
        flash(error, "error")
    return redirect(url_for("play.dungeon"))


def _dungeon_step(fn, done_message):
    if _dungeon_busy():
        return redirect(url_for("play.dungeon"))
    _, _, error = action(lambda user: fn(user, r()))
    flash(error or done_message, "error" if error else "ok")
    return redirect(url_for("play.dungeon"))


@bp.post("/adventure/dungeon/descend")
@player_required
def dungeon_descend():
    return _dungeon_step(dungeon_logic.descend, "Deeper you go. The monsters grow stronger, and so does the loot.")


@bp.post("/adventure/dungeon/cashout")
@player_required
def dungeon_cashout():
    return _dungeon_step(dungeon_logic.cash_out, "You climb out with the whole loot bag.")


@bp.post("/adventure/dungeon/giveup")
@player_required
def dungeon_giveup():
    return _dungeon_step(dungeon_logic.give_up, "You fled the dungeon with half the loot bag.")


def _dungeon_settle(user, fight):
    return dungeon_logic.finish_fight(user, fight, r())


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
