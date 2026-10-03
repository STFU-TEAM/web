"""Gangs: members and ranks, guardians, vault, stash, wars and raids (bot /gang)."""
import uuid as uuidlib

from flask import Blueprint, flash, redirect, render_template, request, session, url_for

from app.accounts import resolve_player
from app.auth import player_required
from app.db import Busy, clear_fight, get_db, identity, load_fight, r, save_fight, user_lock, users_lock
from app.game import gangs as G
from app.game import logic
from app.game.character import character_from_dict
from app.game.fight import Fight, Side, fighting_copy
from app.game.items import item_from_dict
from app.game.logic import GameError

bp = Blueprint("gangs", __name__, url_prefix="/gangs")


def _int(name):
    try:
        return int(request.form.get(name))
    except (TypeError, ValueError):
        return None


def _gang_lock(gang_id):
    return f"gang:{gang_id}"


def gang_action(fn, *others, ok=None):
    """Lock me, my gang and any other players, run fn(db, user, gang, *other_users), save everything."""
    uid = session["uid"]
    db = get_db()
    gang_id = db.get_user(uid).gang_id
    try:
        with users_lock(uid, *others, *([_gang_lock(gang_id)] if gang_id else [])):
            user = db.get_user(uid)
            gang = db.get_gang(user.gang_id)
            other_users = [db.get_user(o) for o in others]
            if any(o is None for o in other_users):
                raise GameError("That player doesn't exist.")
            result = fn(db, user, gang, *other_users)
            if gang is not None and db.get_gang(gang["_id"]) is not None:
                db.update_gang(gang)
            user.update()
            for o in other_users:
                o.update()
            if ok:
                flash(ok(result) if callable(ok) else ok, "ok")
            return result
    except GameError as e:
        flash(str(e), "error")
    except Busy:
        flash("Someone in this action is busy. Try again in a moment.", "error")
    return None


def _back():
    return redirect(url_for("gangs.index"))


def _settle_war(db, gang):
    """Close a finished war on the first visit after it ends (both gangs locked)."""
    opp_id = G.opponent_id(r(), gang["_id"]) if gang else None
    if not opp_id or not G.war_over(gang):
        return gang
    try:
        with users_lock(_gang_lock(gang["_id"]), _gang_lock(opp_id)):
            mine, theirs = db.get_gang(gang["_id"]), db.get_gang(opp_id)
            if mine and G.opponent_id(r(), mine["_id"]) == opp_id:
                if theirs:
                    G.settle_war(r(), mine, theirs)
                    db.update_gang(theirs)
                else:  # the other gang disbanded mid-war
                    r().hdel("active_wars", mine["_id"])
                db.update_gang(mine)
            return mine
    except Busy:
        return gang


# --------------------------------------------------------------------------- #
# Page
# --------------------------------------------------------------------------- #
@bp.get("")
@player_required
def index():
    db = get_db()
    user = db.get_user(session["uid"])
    gang = _settle_war(db, db.get_gang(user.gang_id))
    ctx = {"u": user, "gang": gang, "R": G, "fight": load_fight(user.id), "raid_villain": G.weekly_boss(),
           "tiers": [{**t, "text": G.tier_text(t)} for t in G.RAID_TIERS], "week_ends": G.week_ends(),
           "raid_board": G.raid_board(r())}
    if gang:
        me_rank = G.rank_of(gang, user.id)
        roster = sorted(({"id": m, "identity": identity(m), "rank": G.rank_of(gang, m)} for m in G.members(gang)),
                        key=lambda m: (m["rank"], m["identity"]["name"].lower()))
        opp_id = G.opponent_id(r(), gang["_id"])
        opponent = db.get_gang(opp_id) if opp_id else None
        ctx.update(
            me_rank=me_rank, roster=roster,
            guardians=[character_from_dict(c) for c in gang.get("characters", [])],
            stash=[item_from_dict(i) for i in gang.get("items", [])],
            opponent=opponent, queued=bool(r().get(f"web:gang:queued:{gang['_id']}")) and not opponent,
            war_attacked=user.id in [str(x) for x in gang.get("war_attacks", [])],
            last_war=G.last_war(r(), gang["_id"]),
            raid=G.raid_state(gang), raid_ready=G.can_attack(gang, user.id),
            raid_claim=G.claimable_tiers(gang, user.id) + G.claimable_previous(gang, user.id),
            raid_prev_claim=G.claimable_previous(gang, user.id),
            raid_hits=sorted(((identity(m)["name"], d) for m, d in G.raid_state(gang)["hits"].items()), key=lambda x: -x[1]),
            now=logic.now(),
        )
        if ctx["last_war"]:
            for side in ("winner", "loser"):
                other = db.get_gang(ctx["last_war"][side])
                ctx["last_war"][side + "_name"] = other["name"] if other else "a disbanded gang"
    else:
        ctx["invites"] = [g for g in (db.get_gang(gid) for gid in user.gang_invites) if g]
        ctx["directory"] = sorted(db.all_gangs(), key=lambda g: (-int(g.get("war_elo", 0)), g.get("name", "").lower()))[:50]
    return render_template("gangs.html", **ctx)


# --------------------------------------------------------------------------- #
# Joining and leaving
# --------------------------------------------------------------------------- #
@bp.post("/create")
@player_required
def create():
    name = request.form.get("name", "").strip()
    motto = request.form.get("motto", "").strip()
    motd = request.form.get("motd", "").strip()
    if not 2 <= len(name) <= 32 or len(motto) > 120 or len(motd) > 160:
        flash("Gang names are 2-32 characters; the motto and message are limited to 120 and 160.", "error")
        return _back()

    def run(db, user, gang):
        if user.gang_id:
            raise GameError("Leave your current gang before founding another.")
        if user.fragments < G.GANG_COST:
            raise GameError(f"Founding a gang costs {G.GANG_COST:,} Meteor Dust.")
        user.fragments -= G.GANG_COST
        user.gang_id = str(uuidlib.uuid4())
        db.create_gang(G.new_gang(user.gang_id, user.id, name, motto, motd))
        user.gang_invites = []

    gang_action(run, ok=f"{name} was founded.")
    return _back()


@bp.post("/invite")
@player_required
def invite():
    target = resolve_player(request.form.get("user_id", ""))
    if not target or target == session["uid"]:
        flash("Enter the username or Discord ID of another registered player.", "error")
        return _back()

    def run(db, user, gang, other):
        G.require_rank(gang, user.id, G.CAPO)
        if other.gang_id:
            raise GameError("That player is already in a gang.")
        if gang["_id"] in [str(g) for g in other.gang_invites]:
            raise GameError("That player already has an invitation.")
        other.gang_invites.append(gang["_id"])

    gang_action(run, target, ok=f"Invitation sent to {identity(target)['name']}.")
    return _back()


@bp.post("/join/<gang_id>")
@player_required
def join(gang_id):
    uid = session["uid"]
    try:
        with users_lock(uid, _gang_lock(gang_id)):
            db = get_db()
            user, gang = db.get_user(uid), db.get_gang(gang_id)
            if user.gang_id:
                flash("Leave your current gang first.", "error")
            elif not gang or gang_id not in [str(g) for g in user.gang_invites]:
                flash("That invitation is no longer available.", "error")
            else:
                gang["users"].append(uid)
                G._set_rank(gang, uid, G.SOLDIER)
                user.gang_id = gang_id
                user.gang_invites = []
                db.update_gang(gang)
                user.update()
                flash(f"You joined {gang['name']}.", "ok")
    except Busy:
        flash("Your last action is still running. Try again.", "error")
    return _back()


@bp.post("/decline/<gang_id>")
@player_required
def decline(gang_id):
    def run(db, user, gang):
        user.gang_invites = [g for g in user.gang_invites if str(g) != gang_id]
    gang_action(run, ok="Invitation declined.")
    return _back()


@bp.post("/leave")
@player_required
def leave():
    def run(db, user, gang):
        if not gang:
            user.gang_id = None
            return
        if G.rank_of(gang, user.id) == G.BOSS and len(G.members(gang)) > 1:
            raise GameError("Hand the boss seat to a capo before leaving (promote a capo).")
        gang["users"] = [u for u in gang["users"] if str(u) != user.id]
        gang.get("ranks", {}).pop(user.id, None)
        user.gang_id = None
        if not gang["users"]:
            # last member out: guardians go home with them
            for c in gang.get("characters", []):
                user.storage_characters.append(character_from_dict(c))
            user.items.extend(item_from_dict(i) for i in gang.get("items", []))
            db.delete_gang(gang["_id"])

    gang_action(run, ok="You left the gang.")
    return _back()


# --------------------------------------------------------------------------- #
# Management
# --------------------------------------------------------------------------- #
@bp.post("/kick")
@player_required
def kick():
    target = request.form.get("member", "")
    gang_action(lambda db, user, gang, other: G.kick(gang, user.id, other), target,
                ok=f"{identity(target)['name']} was kicked.")
    return _back()


@bp.post("/promote")
@player_required
def promote():
    target = request.form.get("member", "")
    name = identity(target)["name"]
    gang_action(lambda db, user, gang: G.promote(gang, user.id, target),
                ok=lambda res: f"{name} is now the boss. You are a capo." if res == "boss" else f"{name} is now a capo.")
    return _back()


@bp.post("/demote")
@player_required
def demote():
    target = request.form.get("member", "")
    gang_action(lambda db, user, gang: G.demote(gang, user.id, target),
                ok=f"{identity(target)['name']} is now a soldier.")
    return _back()


@bp.post("/profile")
@player_required
def profile():
    f = request.form
    gang_action(lambda db, user, gang: G.edit_profile(gang, user.id, f.get("motto", "").strip(),
                                                      f.get("motd", "").strip(), f.get("image_url", "").strip()),
                ok="Gang profile updated.")
    return _back()


# --------------------------------------------------------------------------- #
# Vault, stash, guardians
# --------------------------------------------------------------------------- #
@bp.post("/vault/deposit")
@player_required
def deposit():
    amount = _int("amount")
    gang_action(lambda db, user, gang: G.deposit(gang, user, amount) if gang else None,
                ok=f"Deposited {amount or 0:,} Meteor Dust.")
    return _back()


@bp.post("/vault/pay")
@player_required
def pay():
    target, amount = request.form.get("member", ""), _int("amount")
    gang_action(lambda db, user, gang, other: G.pay(gang, user.id, other, amount), target,
                ok=f"Paid {amount or 0:,} Meteor Dust to {identity(target)['name']}.")
    return _back()


@bp.post("/stash/give")
@player_required
def give_item():
    target, index = request.form.get("member", ""), _int("index")
    gang_action(lambda db, user, gang, other: G.give_item(gang, user.id, other, index), target,
                ok=f"Item sent to {identity(target)['name']}.")
    return _back()


@bp.post("/guardians/add")
@player_required
def guardian_add():
    stand_uuid = request.form.get("uuid", "")
    gang_action(lambda db, user, gang: G.add_guardian(gang, user, stand_uuid),
                ok=lambda stand: f"{stand.name} now guards the gang.")
    return _back()


@bp.post("/guardians/remove")
@player_required
def guardian_remove():
    index = _int("index")
    gang_action(lambda db, user, gang: G.remove_guardian(gang, user, index, logic.free_slots(user)),
                ok=lambda stand: f"{stand.name} went back to storage.")
    return _back()


# --------------------------------------------------------------------------- #
# Wars and raids
# --------------------------------------------------------------------------- #
@bp.post("/war/start")
@player_required
def war_start():
    def run(db, user, gang):
        if not gang:
            raise GameError("You are not in a gang.")
        other_id = G.queue_war(r(), gang, user.id)
        if not other_id:
            return None
        try:
            with user_lock(_gang_lock(other_id)):
                other = db.get_gang(other_id)
                if not other:
                    raise GameError("The matched gang just disbanded. Try again.")
                G.start_war(r(), gang, other)
                db.update_gang(other)
                return other["name"]
        except Busy:
            G.requeue(r(), other_id)
            raise

    gang_action(run, ok=lambda name: f"War declared on {name}! It lasts {G.WAR_HOURS} hours." if name
                else "Your gang is looking for an opponent. The war starts when another gang looks for one too.")
    return _back()


@bp.post("/raid/claim")
@player_required
def raid_claim():
    def run(db, user, gang):
        if not gang:
            raise GameError("You are not in a gang.")
        tiers = G.claim_raid(gang, user)
        flash("Raid rewards: " + "; ".join(G.tier_text(G.RAID_TIERS[i]) for i in tiers) + ".", "ok")
    gang_action(run)
    return _back()


@bp.post("/<mode>/attack")
@player_required
def attack_start(mode):
    if mode not in ("war", "raid"):
        return _back()
    uid = session["uid"]
    if load_fight(uid):
        flash("Finish your current fight first.", "error")
        return _back()

    def run(db, user, gang):
        if not gang:
            raise GameError("You are not in a gang.")
        if not user.main_characters:
            raise GameError("Put stands in your team before attacking.")
        meta = {"gang": gang["_id"]}
        if mode == "war":
            if user.id in [str(x) for x in gang.get("war_attacks", [])]:
                raise GameError("You already attacked in this war.")
            opp = db.get_gang(G.opponent_id(r(), gang["_id"]))
            if not opp:
                raise GameError("Your gang is not at war.")
            enemies = [character_from_dict(c) for c in opp.get("characters", [])]
            if not enemies:
                raise GameError("The enemy gang has no guardians left to fight.")
            foe = opp["name"]
            gang.setdefault("war_attacks", []).append(user.id)  # one attempt, even if the fight is abandoned
        else:
            G.start_raid_attack(gang, user.id)  # one a day, even if the fight is abandoned
            logic.track_quest_progress(user, "raid_attack")
            enemies, foe = G.raid_team(), G.weekly_boss()["name"]
            meta["week"] = G.week_key()
        fight = Fight(Side(session.get("name", "You"), fighting_copy(user.main_characters), True, session.get("avatar")),
                      Side(foe, enemies, False), kind=f"gang_{mode}", meta=meta)
        fight.advance()
        save_fight(uid, fight)

    gang_action(run)
    return redirect(url_for("gangs.fight_page")) if load_fight(uid) else _back()


def _fight_ctx(fight):
    return {"fight": fight, "fight_action": url_for("gangs.fight_attack"),
            "fight_leave_action": url_for("gangs.fight_leave"), "fight_label": "Gang"}


@bp.get("/fight")
@player_required
def fight_page():
    fight = load_fight(session["uid"])
    if not fight or not fight.kind.startswith("gang_"):
        return _back()
    return render_template("gang_fight.html", **_fight_ctx(fight))


@bp.post("/fight/attack")
@player_required
def fight_attack():
    uid = session["uid"]
    try:
        with user_lock(uid, ttl=5):
            fight = load_fight(uid)
            if fight is None or not fight.kind.startswith("gang_"):
                return '<p class="notice">This gang fight expired. <a href="/gangs">Back to your gang</a></p>'
            if not fight.finished:
                if request.form.get("forfeit"):
                    fight.forfeit()
                else:
                    fight.advance(request.form.get("target", type=int))
            save_fight(uid, fight)
    except Busy:
        fight = load_fight(uid)
    if fight.finished and fight.rewards is None:
        _settle(fight)
        fight = load_fight(uid)
    return render_template("partials/fight.html", fresh_from=request.form.get("log_len", type=int), **_fight_ctx(fight))


def _settle(fight):
    uid = session["uid"]
    gang_id = fight.meta["gang"]
    try:
        with users_lock(uid, _gang_lock(gang_id)):
            fight = load_fight(uid)
            if fight.rewards is not None:
                return
            db = get_db()
            user, gang = db.get_user(uid), db.get_gang(gang_id)
            enemies = fight.sides[1].chars
            won = fight.winner == 0
            if fight.kind == "gang_war":
                damage = G.war_damage(enemies)
                if gang:
                    gang["damage_to_current_war"] = int(gang.get("damage_to_current_war", 0)) + damage
            else:
                damage = G.raid_damage(enemies)
                if gang:
                    G.record_raid_damage(gang, uid, damage, fight.meta.get("week", ""), r())
            if gang:
                db.update_gang(gang)
            fight.rewards = G.attack_rewards(user, won)
            fight.meta["damage"] = damage
            if won:
                logic.track_quest_progress(user, "fight_win")
                logic.check_achievements(user, "fight_win")
            user.update()
            save_fight(uid, fight)
    except Busy:
        pass


@bp.post("/fight/leave")
@player_required
def fight_leave():
    fight = load_fight(session["uid"])
    if fight and fight.kind.startswith("gang_") and fight.finished:
        clear_fight(session["uid"])
    return _back()
