"""Discord OAuth2 login. The Discord user ID *is* the bot's user _id,
so logging in instantly links the player to their existing data."""
import secrets
from functools import wraps
from urllib.parse import urlencode

import requests
from flask import (
    Blueprint, abort, current_app, flash, redirect, render_template,
    request, session, url_for,
)

from app.db import Busy, avatar_url, get_db, remember_identity, r, user_lock
from app.game.logic import begin

bp = Blueprint("auth", __name__, url_prefix="/auth")

API = "https://discord.com/api/v10"


def login_required(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        if "uid" not in session:
            if request.headers.get("HX-Request"):
                resp = current_app.response_class(status=204)
                resp.headers["HX-Redirect"] = url_for("auth.login", next=request.path)
                return resp
            return redirect(url_for("auth.login", next=request.path))
        return view(*args, **kwargs)
    return wrapper


def player_required(view):
    """Logged in AND registered in the game."""
    @wraps(view)
    @login_required
    def wrapper(*args, **kwargs):
        if not get_db().user_exists(session["uid"]):
            return redirect(url_for("auth.welcome"))
        return view(*args, **kwargs)
    return wrapper


def admin_required(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        if "uid" not in session:
            return redirect(url_for("auth.login", next=request.path))
        if session["uid"] not in current_app.config["DISCORD_ADMIN_IDS"]:
            abort(403, "This Discord account is not allowed to use the admin panel.")
        return view(*args, **kwargs)
    return wrapper


@bp.get("/login")
def login():
    cfg = current_app.config
    if not cfg["DISCORD_CLIENT_ID"]:
        abort(500, "DISCORD_CLIENT_ID is not configured")
    state = secrets.token_urlsafe(24)
    nxt = request.args.get("next", "/")
    if not nxt.startswith("/") or nxt.startswith("//"):
        nxt = "/"
    r().set(f"web:oauth:{state}", nxt, ex=600)
    params = {
        "client_id": cfg["DISCORD_CLIENT_ID"],
        "redirect_uri": cfg["DISCORD_REDIRECT_URI"],
        "response_type": "code",
        "scope": "identify",
        "state": state,
        "prompt": "none",
    }
    return redirect(f"https://discord.com/oauth2/authorize?{urlencode(params)}")


@bp.get("/bot")
def bot_invite():
    """Offer the Discord application's standard bot-install authorization."""
    client_id = current_app.config["DISCORD_CLIENT_ID"]
    if not client_id:
        abort(503, "DISCORD_CLIENT_ID is not configured")
    params = urlencode({"client_id": client_id, "scope": "bot applications.commands"})
    return redirect(f"https://discord.com/oauth2/authorize?{params}")


@bp.get("/callback")
def callback():
    cfg = current_app.config
    state = request.args.get("state", "")
    nxt = r().getdel(f"web:oauth:{state}")
    if nxt is None or "code" not in request.args:
        flash("Discord login was cancelled or expired. Try again.", "error")
        return redirect(url_for("main.home"))

    token = requests.post(
        f"{API}/oauth2/token",
        data={
            "client_id": cfg["DISCORD_CLIENT_ID"],
            "client_secret": cfg["DISCORD_CLIENT_SECRET"],
            "grant_type": "authorization_code",
            "code": request.args["code"],
            "redirect_uri": cfg["DISCORD_REDIRECT_URI"],
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=10,
    )
    if not token.ok:
        flash("Discord refused the login. Try again.", "error")
        return redirect(url_for("main.home"))

    me = requests.get(
        f"{API}/users/@me",
        headers={"Authorization": f"Bearer {token.json()['access_token']}"},
        timeout=10,
    ).json()

    uid = str(me["id"])

    name = me.get("global_name") or me["username"]
    session.clear()
    session.permanent = True
    session["uid"] = uid
    session["name"] = name
    session["avatar"] = avatar_url(me)
    remember_identity(uid, name, session["avatar"])

    if not get_db().user_exists(uid):
        return redirect(url_for("auth.welcome"))
    return redirect(nxt.decode() if isinstance(nxt, bytes) else nxt)


@bp.route("/welcome", methods=["GET", "POST"])
@login_required
def welcome():
    """Account creation = the bot's /adventure begin."""
    db = get_db()
    if db.user_exists(session["uid"]):
        return redirect(url_for("play.team"))
    if request.method == "POST":
        try:
            with user_lock(session["uid"]):
                if db.user_exists(session["uid"]):
                    return redirect(url_for("play.team"))
                user = db.add_user(session["uid"])
                begin(user)
                user.update()
        except Busy:
            return redirect(url_for("auth.welcome"))
        return redirect(url_for("play.banners", welcome=1))
    return render_template("welcome.html")


@bp.post("/logout")
def logout():
    session.clear()
    return redirect(url_for("main.home"))
