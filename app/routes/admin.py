"""Restricted account tools matching the bot's give_character permission."""
import json
from datetime import datetime, timezone

from flask import Blueprint, flash, redirect, render_template, request, session, url_for

from app.auth import admin_required
from app.db import Busy, get_db, identity, r, user_lock
from app.game.items import item_file, item_from_dict

bp = Blueprint("admin", __name__, url_prefix="/admin")
MAX_CURRENCY_GRANT = 1_000_000
MAX_ITEM_GRANT = 25


def _int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


@bp.get("")
@admin_required
def index():
    target_id = request.args.get("user_id", "").strip()
    target = None
    target_identity = None
    if target_id:
        if not target_id.isdigit():
            flash("Enter a numeric Discord user ID.", "error")
        else:
            target = get_db().get_user(target_id)
            if target:
                target_identity = identity(target_id)
            else:
                flash("No game account was found for that ID.", "error")
    return render_template("admin.html", target_id=target_id, target=target,
                           target_identity=target_identity, items=item_file)


@bp.post("/grant")
@admin_required
def grant():
    target_id = request.form.get("user_id", "").strip()
    kind = request.form.get("kind", "")
    amount = _int(request.form.get("amount"))
    item_id = _int(request.form.get("item_id"))
    if not target_id.isdigit():
        flash("Enter a numeric Discord user ID.", "error")
        return redirect(url_for("admin.index"))
    max_amount = MAX_ITEM_GRANT if kind == "item" else MAX_CURRENCY_GRANT
    if kind not in {"fragments", "super_fragments", "item"} or amount is None or not 1 <= amount <= max_amount:
        flash(f"Choose a valid grant amount from 1 to {max_amount:,}.".replace(",", " "), "error")
        return redirect(url_for("admin.index", user_id=target_id))
    if kind == "item" and (item_id is None or not 1 <= item_id <= len(item_file)):
        flash("Choose an item from the catalog.", "error")
        return redirect(url_for("admin.index", user_id=target_id))

    try:
        with user_lock(target_id):
            db = get_db()
            target = db.get_user(target_id)
            if target is None:
                flash("No game account was found for that ID.", "error")
            else:
                if kind == "fragments":
                    target.fragments += amount
                elif kind == "super_fragments":
                    target.super_fragements += amount
                else:
                    target.items.extend(item_from_dict({"id": item_id}) for _ in range(amount))
                target.update()
                r().lpush("web:admin:audit", json.dumps({
                    "at": datetime.now(timezone.utc).isoformat(),
                    "actor": session["uid"], "target": target_id,
                    "kind": kind, "amount": amount, "item_id": item_id if kind == "item" else None,
                }))
                r().ltrim("web:admin:audit", 0, 99)
                r().expire("web:admin:audit", 365 * 24 * 60 * 60)
                flash(f"Granted {amount} {kind.replace('_', ' ')} to {identity(target_id)['name']}.", "ok")
    except Busy:
        flash("That account is processing another action. Try again.", "error")
    return redirect(url_for("admin.index", user_id=target_id))