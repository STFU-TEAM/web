"""Chat pages: the global chat, private messages, and the endpoints every chat box polls and posts to (global,
private, co-op raid). The rules live in app/game/chat.py."""
from flask import Blueprint, Response, flash, redirect, render_template, request, session, url_for

from app.auth import is_admin, player_required
from app.db import get_db, identities, identity, r
from app.game import chat as C
from app.game.logic import GameError

bp = Blueprint("chat", __name__, url_prefix="/chat")


def _channel(token: str) -> C.Channel:
    from app.game import coop
    return C.resolve(token, session["uid"], raid_members=coop.chat_members)


def box_ctx(ch: C.Channel, error=None) -> dict:
    """What partials/chat_box.html needs for one channel."""
    from app.game import titles
    msgs = C.messages(ch)
    uids = {m["uid"] for m in msgs}
    who = identities(uids)
    return {"ch": ch, "msgs": msgs, "names": {u: who[u]["name"] for u in uids}, "titles": titles.shown_of(uids),
            "seq": C.seq(ch), "chat_error": error, "chat_admin": is_admin(session["uid"]) and ch.kind != "dm"}


def _box(ch, error=None):
    return render_template("partials/chat_box.html", **box_ctx(ch, error))


@bp.get("")
@player_required
def index():
    me = session["uid"]
    convs = C.conversations(me)
    who = identities(c["uid"] for c in convs)
    for c in convs:
        c["name"], c["avatar"] = who[c["uid"]]["name"], who[c["uid"]].get("avatar")
    tab = "messages" if request.args.get("tab") == "messages" else "global"
    return render_template("chat.html", tab=tab, convs=convs, friends_only=C.friends_only(me), mute=C.muted(me),
                           **(box_ctx(_channel("global")) if tab == "global" else {}))


@bp.get("/dm/<uid>")
@player_required
def dm(uid):
    me = session["uid"]
    try:
        ch = _channel(f"dm-{uid}")
    except GameError as e:
        flash(str(e), "error")
        return redirect(url_for("chat.index", tab="messages"))
    C.mark_read(me, uid)
    return render_template("chat_dm.html", other=uid, ident=identity(uid), blocked=C.blocked(me, uid),
                           cant=C.can_message(me, uid), **box_ctx(ch))


@bp.get("/c/<token>")
@player_required
def feed(token):
    """Polled every few seconds: 204 when nothing changed since ?seq."""
    try:
        ch = _channel(token)
    except GameError:
        return Response(status=286)  # htmx stops polling
    if ch.kind == "dm":
        C.mark_read(session["uid"], ch.other)  # you're looking at it
    if request.args.get("seq", type=int) == C.seq(ch):
        return Response(status=204)
    return _box(ch)


@bp.post("/c/<token>")
@player_required
def post(token):
    error = None
    try:
        ch = _channel(token)
        C.post(ch, session["uid"], request.form.get("text", ""))
    except GameError as e:
        error = str(e)
        try:
            ch = _channel(token)
        except GameError:
            return Response(status=286)
    if not request.headers.get("HX-Request"):
        if error:
            flash(error, "error")
        return redirect(request.referrer or url_for("chat.index"))
    return _box(ch, error)


@bp.post("/c/<token>/<int:msg_id>/delete")
@player_required
def delete(token, msg_id):
    try:
        ch = _channel(token)
        msg = C.delete(ch, session["uid"], msg_id, admin=is_admin(session["uid"]))
        if msg["uid"] != session["uid"]:
            from app.routes.admin import audit
            audit("chat_delete", msg["uid"], chat=ch.kind, text=msg["text"][:200])
    except GameError as e:
        if not request.headers.get("HX-Request"):
            flash(str(e), "error")
        ch = None
    if not request.headers.get("HX-Request") or ch is None:
        return redirect(request.referrer or url_for("chat.index"))
    return _box(ch)


@bp.post("/c/<token>/<int:msg_id>/report")
@player_required
def report(token, msg_id):
    from app.game import profile as P
    try:
        ch = _channel(token)
        msg = C.find(ch, msg_id)
        if not msg:
            raise GameError("That message is gone.")
        P.report(session["uid"], msg["uid"], "chat", request.form.get("note", ""),
                 message={"text": msg["text"], "chat": ch.kind, "at": msg["at"]})
        flash("Thanks: an admin will look at this message.", "ok")
    except GameError as e:
        flash(str(e), "error")
    return redirect(request.referrer or url_for("chat.index"))


@bp.post("/dm/<uid>/block")
@player_required
def block(uid):
    me = session["uid"]
    if request.form.get("on") == "1":
        C.block(me, uid)
        flash(f"{identity(uid)['name']} can't message you any more.", "ok")
    else:
        C.unblock(me, uid)
        flash(f"{identity(uid)['name']} is unblocked.", "ok")
    return redirect(url_for("chat.dm", uid=uid))


@bp.post("/settings")
@player_required
def settings():
    C.set_friends_only(session["uid"], request.form.get("friends_only") == "1")
    flash("Only friends can start a conversation with you now." if request.form.get("friends_only") == "1"
          else "Anyone can start a conversation with you now.", "ok")
    return redirect(url_for("chat.index", tab="messages"))
