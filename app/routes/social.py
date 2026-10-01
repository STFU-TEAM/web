"""Web access to gangs and player-owned shops shared with the bot."""
import datetime
import uuid

from flask import Blueprint, flash, redirect, render_template, request, session, url_for

from app.auth import player_required
from app.db import Busy, get_db, identity, user_lock, users_lock
from app.game.items import Item, item_file
from app.game.user import User

bp = Blueprint("social", __name__)
GANG_COST = 10000
SHOP_COST = 3000


def _user():
    return get_db().get_user(session["uid"])


def _safe_int(value, default=None):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _gang_context(user):
    db = get_db()
    gang = db.get_gang(user.gang_id)
    members = []
    if gang:
        for uid in gang.get("users", []):
            uid = str(uid)
            members.append({"id": uid, "identity": identity(uid),
                            "rank": int(gang.get("ranks", {}).get(uid, gang.get("ranks", {}).get(int(uid), 2)))})
    invites = [db.get_gang(gid) for gid in user.gang_invites]
    return {"u": user, "gang": gang, "members": members,
            "invites": [g for g in invites if g],
            "gangs": sorted(db.all_gangs(), key=lambda g: (-int(g.get("war_elo", 0)), g.get("name", "").lower()))}


@bp.get("/gangs")
@player_required
def gangs():
    return render_template("gangs.html", **_gang_context(_user()))


@bp.post("/gangs/create")
@player_required
def gang_create():
    name = request.form.get("name", "").strip()
    motto = request.form.get("motto", "").strip()
    motd = request.form.get("motd", "").strip()
    if not 2 <= len(name) <= 32 or len(motto) > 120 or len(motd) > 160:
        flash("Gang name must be 2-32 characters; motto and message have 120 and 160 character limits.", "error")
        return redirect(url_for("social.gangs"))
    try:
        with user_lock(session["uid"]):
            user = _user()
            if user.gang_id:
                flash("Leave your current gang before creating another.", "error")
            elif user.fragments < GANG_COST:
                flash(f"Creating a gang costs {GANG_COST:,} fragments.".replace(",", " "), "error")
            else:
                gang_id = str(uuid.uuid4())
                now = datetime.datetime.min
                gang = {
                    "_id": gang_id, "name": name, "motd": motd, "motto": motto,
                    "image_url": "https://media1.tenor.com/m/-fG6_QSIjZAAAAAC/amicreeper-galaxy.gif",
                    "users": [session["uid"]], "ranks": {session["uid"]: 0},
                    "vault": 0, "characters": [], "items": [], "raid_level": 1,
                    "war_elo": 0, "war_attacks": [], "raid_attacks": [],
                    "damage_to_current_war": 0, "damage_to_current_raid": 0,
                    "end_of_raid": now, "end_of_war": now, "last_raid": now, "last_war": now,
                }
                user.fragments -= GANG_COST
                user.gang_id = gang_id
                get_db().create_gang(gang)
                user.update()
                flash(f"{name} was founded.", "ok")
    except Busy:
        flash("Your last action is still running. Try again.", "error")
    return redirect(url_for("social.gangs"))


@bp.post("/gangs/invite")
@player_required
def gang_invite():
    target_id = request.form.get("user_id", "").strip()
    if not target_id.isdigit() or target_id == session["uid"]:
        flash("Enter the Discord user ID of another registered player.", "error")
        return redirect(url_for("social.gangs"))
    try:
        with users_lock(session["uid"], target_id):
            db = get_db()
            user, target = db.get_user(session["uid"]), db.get_user(target_id)
            gang = db.get_gang(user.gang_id)
            if not gang or int(gang.get("ranks", {}).get(session["uid"], 2)) > 1:
                flash("Only the gang boss or a capo can invite members.", "error")
            elif not target:
                flash("That Discord account has not started playing yet.", "error")
            elif target.gang_id:
                flash("That player is already in a gang.", "error")
            elif gang["_id"] in target.gang_invites:
                flash("That player already has an invitation.", "error")
            else:
                target.gang_invites.append(gang["_id"])
                target.update()
                flash(f"Invitation sent to {identity(target_id)['name']}.", "ok")
    except Busy:
        flash("A player is completing another action. Try again.", "error")
    return redirect(url_for("social.gangs"))


@bp.post("/gangs/join/<gang_id>")
@player_required
def gang_join(gang_id):
    try:
        with user_lock(session["uid"]):
            db = get_db()
            user = db.get_user(session["uid"])
            gang = db.get_gang(gang_id)
            if user.gang_id:
                flash("Leave your current gang first.", "error")
            elif not gang or gang_id not in user.gang_invites:
                flash("That gang invitation is no longer available.", "error")
            else:
                gang["users"].append(session["uid"])
                gang.setdefault("ranks", {})[session["uid"]] = 2
                user.gang_id = gang_id
                user.gang_invites = [invite for invite in user.gang_invites if str(invite) != gang_id]
                db.update_gang(gang)
                user.update()
                flash(f"You joined {gang['name']}.", "ok")
    except Busy:
        flash("Your last action is still running. Try again.", "error")
    return redirect(url_for("social.gangs"))


@bp.post("/gangs/leave")
@player_required
def gang_leave():
    try:
        with user_lock(session["uid"]):
            db = get_db()
            user = db.get_user(session["uid"])
            gang = db.get_gang(user.gang_id)
            if not gang:
                user.gang_id = None
                user.update()
                flash("You are not in a gang.", "error")
            else:
                members = [str(uid) for uid in gang.get("users", [])]
                is_boss = int(gang.get("ranks", {}).get(session["uid"], 2)) == 0
                if is_boss and len(members) > 1:
                    flash("Promote another member before leaving as boss.", "error")
                else:
                    gang["users"] = [uid for uid in gang["users"] if str(uid) != session["uid"]]
                    gang.get("ranks", {}).pop(session["uid"], None)
                    user.gang_id = None
                    user.update()
                    if gang["users"]:
                        db.update_gang(gang)
                    else:
                        db.delete_gang(gang["_id"])
                    flash("You left the gang.", "ok")
    except Busy:
        flash("Your last action is still running. Try again.", "error")
    return redirect(url_for("social.gangs"))


def _shop_context(shop):
    return {"shop": shop, "items": [
        {"item": Item(item), "price": price, "index": index}
        for index, (item, price) in enumerate(zip(shop.get("items", []), shop.get("prices", [])))
    ], "owner": identity(shop["owner"])}


@bp.get("/shops")
@player_required
def shops():
    db = get_db()
    user = _user()
    own_shop = db.get_shop(user.shop_id)
    shops = [shop for shop in db.all_shops() if shop.get("items")]
    return render_template("shops.html", u=user, own_shop=own_shop, shops=shops,
                           identities={shop["_id"]: identity(shop["owner"]) for shop in shops})


@bp.get("/shops/<shop_id>")
@player_required
def shop_view(shop_id):
    shop = get_db().get_shop(shop_id)
    if not shop:
        return render_template("error.html", code=404, message="This shop doesn't exist."), 404
    return render_template("shop.html", u=_user(), **_shop_context(shop))


@bp.post("/shops/create")
@player_required
def shop_create():
    name = request.form.get("name", "").strip()
    description = request.form.get("description", "").strip()
    if not 2 <= len(name) <= 40 or len(description) > 180:
        flash("Shop name must be 2-40 characters; description is limited to 180.", "error")
        return redirect(url_for("social.shops"))
    try:
        with user_lock(session["uid"]):
            user = _user()
            if get_db().get_shop(user.shop_id):
                flash("You already own a shop.", "error")
            elif user.fragments < SHOP_COST:
                flash(f"Creating a shop costs {SHOP_COST:,} fragments.".replace(",", " "), "error")
            else:
                shop_id = str(uuid.uuid4())
                shop = {"_id": shop_id, "owner": session["uid"], "name": name,
                        "description": description,
                        "image_url": "https://storage.stfurequiem.com/randomAsset/shop.gif",
                        "items": [], "prices": []}
                user.fragments -= SHOP_COST
                user.shop_id = shop_id
                get_db().create_shop(shop)
                user.update()
                flash(f"{name} is open for business.", "ok")
    except Busy:
        flash("Your last action is still running. Try again.", "error")
    return redirect(url_for("social.shops"))


@bp.post("/shops/<shop_id>/list")
@player_required
def shop_list_item(shop_id):
    item_id, price = _safe_int(request.form.get("item")), _safe_int(request.form.get("price"))
    try:
        with user_lock(session["uid"]):
            db = get_db()
            user, shop = _user(), db.get_shop(shop_id)
            if not shop or shop.get("owner") != session["uid"] or user.shop_id != shop_id:
                flash("You cannot list items in that shop.", "error")
            elif item_id is None or not 1 <= item_id <= len(item_file) or price is None or not 1 <= price <= 10000000:
                flash("Choose an owned item and a price from 1 to 10,000,000 fragments.", "error")
            elif len(shop.get("items", [])) >= 30:
                flash("Your shop can hold up to 30 listings.", "error")
            else:
                item = next((item for item in user.items if item.id == item_id), None)
                if not item:
                    flash("You no longer own that item.", "error")
                else:
                    user.items.remove(item)
                    shop.setdefault("items", []).append(item.to_dict())
                    shop.setdefault("prices", []).append(price)
                    user.update()
                    db.update_shop(shop)
                    flash(f"{item.name} listed for {price:,} fragments.".replace(",", " "), "ok")
    except Busy:
        flash("Your last action is still running. Try again.", "error")
    return redirect(url_for("social.shop_view", shop_id=shop_id))


@bp.post("/shops/<shop_id>/unlist/<int:index>")
@player_required
def shop_unlist_item(shop_id, index):
    try:
        with user_lock(session["uid"]):
            db = get_db()
            user, shop = _user(), db.get_shop(shop_id)
            if not shop or shop.get("owner") != session["uid"] or user.shop_id != shop_id:
                flash("You cannot edit that shop.", "error")
            elif not 0 <= index < len(shop.get("items", [])):
                flash("That listing is no longer available.", "error")
            else:
                user.items.append(Item(shop["items"].pop(index)))
                shop["prices"].pop(index)
                user.update()
                db.update_shop(shop)
                flash("Item returned to your inventory.", "ok")
    except Busy:
        flash("Your last action is still running. Try again.", "error")
    return redirect(url_for("social.shop_view", shop_id=shop_id))


@bp.post("/shops/<shop_id>/buy/<int:index>")
@player_required
def shop_buy_item(shop_id, index):
    db = get_db()
    shop = db.get_shop(shop_id)
    if not shop:
        flash("That shop no longer exists.", "error")
        return redirect(url_for("social.shops"))
    owner_id = str(shop.get("owner", ""))
    try:
        with users_lock(session["uid"], owner_id):
            buyer, seller, shop = db.get_user(session["uid"]), db.get_user(owner_id), db.get_shop(shop_id)
            if not buyer or not seller or not shop or shop.get("owner") != owner_id:
                flash("The shop owner is no longer available.", "error")
            elif buyer.id == owner_id:
                flash("You cannot buy from your own shop.", "error")
            elif not 0 <= index < min(len(shop.get("items", [])), len(shop.get("prices", []))):
                flash("That listing is no longer available.", "error")
            else:
                price = int(shop["prices"][index])
                if buyer.fragments < price:
                    flash("You do not have enough fragments.", "error")
                else:
                    item = Item(shop["items"].pop(index))
                    shop["prices"].pop(index)
                    buyer.fragments -= price
                    seller.fragments += price
                    buyer.items.append(item)
                    buyer.update()
                    seller.update()
                    db.update_shop(shop)
                    flash(f"Bought {item.name} for {price:,} fragments.".replace(",", " "), "ok")
    except Busy:
        flash("The buyer or seller is completing another action. Try again.", "error")
    return redirect(url_for("social.shop_view", shop_id=shop_id))