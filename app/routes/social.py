"""Player-owned shops shared with the bot (gangs live in routes/gangs.py)."""
import datetime
import uuid

from flask import Blueprint, flash, redirect, render_template, request, session, url_for

from app.auth import player_required
from app.db import Busy, get_db, identity, user_lock, users_lock
from app.game.items import Item, item_file
from app.game.user import User

bp = Blueprint("social", __name__)
SHOP_COST = 3000


def _user():
    return get_db().get_user(session["uid"])


def _safe_int(value, default=None):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


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
                flash(f"Creating a shop costs {SHOP_COST:,} Meteor Dust.".replace(",", " "), "error")
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
                flash("Choose an owned item and a price from 1 to 10,000,000 Meteor Dust.", "error")
            elif len(shop.get("items", [])) >= 30:
                flash("Your shop can hold up to 30 listings.", "error")
            else:
                item = next((item for item in user.items if item.id == item_id), None)
                if not item:
                    flash("You no longer own that item.", "error")
                elif item.bound:
                    flash(f"{item.name} is bound to you: it can't be sold.", "error")
                else:
                    user.items.remove(item)
                    shop.setdefault("items", []).append(item.to_dict())
                    shop.setdefault("prices", []).append(price)
                    user.update()
                    db.update_shop(shop)
                    flash(f"{item.name} listed for {price:,} Meteor Dust.".replace(",", " "), "ok")
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
                    flash("You do not have enough Meteor Dust.", "error")
                else:
                    item = Item(shop["items"].pop(index))
                    shop["prices"].pop(index)
                    buyer.fragments -= price
                    seller.fragments += price
                    buyer.items.append(item)
                    buyer.update()
                    seller.update()
                    db.update_shop(shop)
                    flash(f"Bought {item.name} for {price:,} Meteor Dust.".replace(",", " "), "ok")
    except Busy:
        flash("The buyer or seller is completing another action. Try again.", "error")
    return redirect(url_for("social.shop_view", shop_id=shop_id))