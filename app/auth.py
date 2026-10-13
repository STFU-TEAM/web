"""Logins. Discord OAuth2: the Discord user ID *is* the bot's user _id, so
logging in instantly links the player to their existing data. Username +
password (app/accounts.py) works for web-only saves and for Discord players
who added a password to their save."""
import json
import secrets
import time
from functools import wraps
from urllib.parse import urlencode

import requests
from flask import (
    Blueprint, abort, current_app, flash, redirect, render_template,
    request, session, url_for,
)

from app import accounts
from app.accounts import AccountError
from app.db import Busy, avatar_url, get_db, identity, remember_identity, r, user_lock
from app.game.logic import begin

bp = Blueprint("auth", __name__, url_prefix="/auth")

API = "https://discord.com/api/v10"


@bp.before_app_request
def drop_removed_sessions():
    """A session started before its account was removed (wipe.remove_everything) is logged out."""
    uid = session.get("uid")
    if not uid:
        return
    removed = r().get(f"web:purged:{uid}")
    if removed and session.get("since", 0) <= int(removed):
        session.clear()


def login_required(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        if "uid" not in session:
            if request.headers.get("HX-Request"):
                resp = current_app.response_class(status=204)
                resp.headers["HX-Redirect"] = url_for("auth.login", next=request.path)
                return resp
            return redirect(url_for("auth.login", next=request.path))
        if r().sismember("web:banned", session["uid"]):
            reason = r().hget("web:ban_reason", session["uid"])
            session.clear()
            abort(403, "This account is banned from the website." + (f" Reason: {reason.decode()}" if reason else ""))
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


ADMINS_KEY = "web:admins"  # uid -> {"by", "at"}: admins promoted from the admin panel


def is_owner(uid) -> bool:
    """The configured admins (DISCORD_ADMIN_IDS): always admins, and the only ones who can promote or demote."""
    return bool(uid) and uid in current_app.config["DISCORD_ADMIN_IDS"]


def is_admin(uid) -> bool:
    return is_owner(uid) or (bool(uid) and bool(r().hexists(ADMINS_KEY, uid)))


def admin_required(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        if "uid" not in session:
            return redirect(url_for("auth.login", next=request.path))
        if not is_admin(session["uid"]):
            abort(403, "This account is not allowed to use the admin panel.")
        return view(*args, **kwargs)
    return wrapper


def _safe_next(nxt) -> str:
    nxt = nxt or "/"
    return nxt if nxt.startswith("/") and not nxt.startswith("//") else "/"


def _start_session(uid: str, name: str, avatar, method: str):
    ref = session.get("ref")  # an invite link survives the fresh session; the welcome page uses it
    session.clear()
    session.permanent = True
    if ref:
        session["ref"] = ref
    session["uid"], session["name"], session["avatar"], session["auth"] = uid, name, avatar, method
    session["since"] = int(time.time())  # a session older than its account's removal is logged out (wipe.py)
    try:  # alt-account flags (app/alts.py): a salted hash of the address, never the address itself
        from app import alts
        alts.touch(r(), session, request.remote_addr)  # records, and marks today's address as seen
    except Exception:
        pass


@bp.route("/login", methods=["GET", "POST"])
def login():
    nxt = _safe_next(request.values.get("next"))
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        try:
            account = accounts.authenticate(username, request.form.get("password", ""),
                                            request.remote_addr or "?")
        except AccountError as e:
            flash(str(e), "error")
            return render_template("login.html", next=nxt, username=username), 401
        if r().sismember("web:banned", account["uid"]):
            flash("This account is banned from the website.", "error")
            return render_template("login.html", next=nxt, username=username), 403
        # a web-only player's own picture (set on their profile) lives in their identity too, like Discord's
        avatar = identity(account["uid"]).get("avatar")
        _start_session(account["uid"], account["name"], avatar, "password")
        if not get_db().user_exists(account["uid"]):
            return redirect(url_for("auth.welcome"))
        return redirect(nxt)
    if session.get("uid"):
        return redirect(nxt)
    return render_template("login.html", next=nxt, username="", guest_name=guest_resume_name())


@bp.route("/register", methods=["GET", "POST"])
def register():
    nxt = _safe_next(request.values.get("next"))
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        try:
            if password != request.form.get("confirm", ""):
                raise AccountError("The two passwords don't match.")
            account = accounts.create_account(username, password)
        except AccountError as e:
            flash(str(e), "error")
            return render_template("register.html", next=nxt, username=username), 400
        _start_session(account["uid"], account["name"], None, "password")
        return redirect(url_for("auth.welcome"))
    return render_template("register.html", next=nxt, username="", guest_name=guest_resume_name())


def _set_guest_cookie(resp, token: str):
    resp.set_cookie(accounts.GUEST_COOKIE, token, max_age=accounts.GUEST_DAYS * 86400, httponly=True,
                    secure=current_app.config.get("SESSION_COOKIE_SECURE", False), samesite="Lax")
    return resp


def guest_resume_name():
    """The guest save this browser's cookie points at (its name), for a "Continue as ..." button."""
    uid = accounts.guest_of(request.cookies.get(accounts.GUEST_COOKIE))
    return identity(uid).get("name") if uid else None


@bp.post("/guest")
def guest():
    """Play without an account: a guest save kept by a cookie on this browser (the player agreed to it), or the one
    this browser already has."""
    uid = accounts.guest_of(request.cookies.get(accounts.GUEST_COOKIE))
    if uid:
        if r().sismember("web:banned", uid):
            flash("This guest save is banned from the website.", "error")
            return redirect(url_for("auth.login"))
        _start_session(uid, identity(uid).get("name") or "Guest", None, "guest")
        return redirect(url_for("play.team") if get_db().user_exists(uid) else url_for("auth.welcome"))
    if not request.form.get("agree"):
        flash("Tick the box first: a guest save lives in a cookie on this browser.", "error")
        return redirect(request.referrer or url_for("auth.register"))
    from app import alts
    if alts.too_many_guests(r(), request.remote_addr):
        flash("Too many guest saves from this network today. Create an account instead.", "error")
        return redirect(url_for("auth.register"))
    g = accounts.create_guest()
    _start_session(g["uid"], g["name"], None, "guest")
    return _set_guest_cookie(redirect(url_for("auth.welcome")), g["token"])


def guest_blocked():
    """None, or the message a guest gets when trying what needs a real account (chat, trades, the auction house)."""
    uid = session.get("uid")
    if uid and accounts.is_guest(uid):
        return "Guests can't do that yet: save your progress with a username first (Account, in your menu)."
    return None


def account_required(view):
    """Logged in, registered, and not a guest (chat, DMs, trades, the auction house: anti-spam and anti-alt)."""
    @wraps(view)
    @player_required
    def wrapper(*args, **kwargs):
        msg = guest_blocked()
        if msg:
            if request.headers.get("HX-Request"):
                resp = current_app.response_class(status=204)
                resp.headers["HX-Trigger"] = json.dumps({"toast": [{"text": msg, "kind": "flash-error"}]})
                return resp
            flash(msg, "error")
            return redirect(request.referrer or url_for("auth.account"))
        return view(*args, **kwargs)
    return wrapper


@bp.post("/dev/fresh")
def dev_fresh():
    """Dev mode only (the local server, app.debug): a brand-new account with no save, signed in, at the welcome
    screen, to play the first-player experience from the very start. 404 anywhere else."""
    import secrets
    from flask import abort
    if not current_app.debug:
        abort(404)
    name = f"test{secrets.randbelow(10 ** 6):06d}"
    account = accounts.create_account(name, secrets.token_urlsafe(12))
    _start_session(account["uid"], account["name"], None, "password")
    flash(f"Dev: signed in as {name}, a brand-new player with nothing.", "ok")
    return redirect(url_for("auth.welcome"))


@bp.get("/discord")
def discord_login():
    """Send the player to Discord. ?link=1 from a password-only save links Discord to it."""
    cfg = current_app.config
    if not cfg["DISCORD_CLIENT_ID"]:
        abort(503, "Discord login is not configured")
    state = secrets.token_urlsafe(24)
    payload = {"next": _safe_next(request.args.get("next"))}
    if request.args.get("link") and accounts.is_local(session.get("uid", "")):
        payload["link"] = session["uid"]
    r().set(f"web:oauth:{state}", json.dumps(payload), ex=600)
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
    raw = r().getdel(f"web:oauth:{state}")
    if raw is None or "code" not in request.args:
        flash("Discord login was cancelled or expired. Try again.", "error")
        return redirect(url_for("auth.login"))

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
        return redirect(url_for("auth.login"))

    me = requests.get(
        f"{API}/users/@me",
        headers={"Authorization": f"Bearer {token.json()['access_token']}"},
        timeout=10,
    ).json()

    uid = str(me["id"])
    name = me.get("global_name") or me["username"]
    avatar = avatar_url(me)
    try:
        state_data = json.loads(raw)
    except ValueError:  # state stored before the JSON format: just a path
        state_data = {"next": raw.decode() if isinstance(raw, bytes) else raw}

    if state_data.get("link"):
        local_uid = state_data["link"]
        if session.get("uid") != local_uid:
            flash("Log in to the account you want to link first.", "error")
            return redirect(url_for("auth.login"))
        try:
            with user_lock(local_uid):
                accounts.link_discord(local_uid, uid)
        except AccountError as e:
            flash(str(e), "error")
            return redirect(url_for("auth.account"))
        except Busy:
            flash("Your save is busy with another action. Try again.", "error")
            return redirect(url_for("auth.account"))
        remember_identity(uid, name, avatar)
        _start_session(uid, name, avatar, "discord")
        flash("Discord linked. The bot now sees this save, and you can log in either way.", "ok")
        return redirect(url_for("auth.account"))

    _start_session(uid, name, avatar, "discord")
    remember_identity(uid, name, avatar)
    if not get_db().user_exists(uid):
        return redirect(url_for("auth.welcome"))
    return redirect(_safe_next(state_data.get("next")))


@bp.route("/account", methods=["GET", "POST"])
@login_required
def account():
    uid = session["uid"]
    if request.method == "POST":
        form = request.form
        try:
            if form.get("password") != form.get("confirm"):
                raise AccountError("The two passwords don't match.")
            if form.get("action") == "add":
                was_guest = accounts.is_guest(uid)
                account = accounts.create_account(form.get("username", "").strip(), form.get("password", ""), uid=uid)
                if was_guest:
                    accounts.end_guest(uid)
                    session["name"], session["auth"] = account["name"], "password"
                    flash(f"Progress saved! Log in anywhere as {account['name']}.", "ok")
                else:
                    flash("Username saved. You can now log in without Discord.", "ok")
            elif form.get("action") == "rename":
                session["name"] = accounts.rename(uid, form.get("username", "").strip())
                flash(f"You're now {session['name']}. Log in with that name from now on.", "ok")
            elif form.get("action") == "change":
                accounts.set_password(uid, form.get("current", ""), form.get("password", ""))
                flash("Password changed.", "ok")
        except AccountError as e:
            flash(str(e), "error")
        return redirect(url_for("auth.account"))
    left = r().ttl(f"web:rename:{uid}") if accounts.is_local(uid) else 0
    return render_template("account.html", username=accounts.username_of(uid), local=accounts.is_local(uid),
                           guest=accounts.is_guest(uid), rename_days=max(1, round(left / 86400)) if left and left > 0 else 0,
                           discord_ready=bool(current_app.config["DISCORD_CLIENT_ID"]))


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
                # no auto-tour: the coach (onboarding.coach) walks the first session, and offers the tour at its end
                from app import social
                social.record_referral(session["uid"], session.pop("ref", None))
        except Busy:
            return redirect(url_for("auth.welcome"))
        return redirect(url_for("play.banners", welcome=1))
    return render_template("welcome.html", local=accounts.is_local(session["uid"]))


@bp.post("/logout")
def logout():
    session.clear()
    flash("Arrivederci! Your energy keeps refilling while you're away.", "ok")
    return redirect(url_for("main.home"))
