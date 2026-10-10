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


# --------------------------------------------------------------------------- #
# The chat bubble: every chat in one corner panel. Tabs: global, gang (if in one), messages (your conversations,
# each opening inside the bubble). Red dots on the bubble and its tabs for unread private and gang messages.
# --------------------------------------------------------------------------- #
def dots(uid) -> dict:
    from app.game import gangs as G
    return {"dm": C.unread_total(uid), "gang": G.chat_unread(r(), uid)}


def _bubble(tab: str, **extra):
    me = session["uid"]
    ctx = {"tab": tab, "dots": dots(me), "here": request.args.get("here", ""), **extra}
    from app.db import get_db
    from app.game import gangs as G
    user = get_db().get_user(me)
    gang = get_db().get_gang(user.gang_id) if user and user.gang_id else None
    ctx["has_gang"] = bool(gang)
    if tab == "gang" and gang:
        if ctx["here"] != "gangs.index":  # the gang page has its own box (one #gang-chat per page)
            msgs = G.chat_messages(r(), gang["_id"])
            who = identities(m["uid"] for m in msgs)
            ctx.update(gang=gang, msgs=msgs, names={u: who[u]["name"] for u in who}, chat_error=None,
                       seq=G.chat_seq(r(), gang["_id"]), me_rank=G.rank_of(gang, me), R=G)
        G.chat_mark_read(r(), me)
        ctx["dots"]["gang"] = 0
    elif tab == "messages":
        convs = C.conversations(me, 30)
        who = identities(c["uid"] for c in convs)
        for c in convs:
            c["name"], c["avatar"] = who[c["uid"]]["name"], who[c["uid"]].get("avatar")
        ctx["convs"] = convs
    elif tab == "dm":
        pass  # filled by bubble_dm
    else:
        ctx["tab"] = "global"
        ctx.update(box_ctx(_channel("global")))
    return render_template("partials/chat_bubble.html", **ctx)


@bp.get("/bubble")
@player_required
def bubble():
    tab = request.args.get("tab", "global")
    return _bubble(tab if tab in ("global", "gang", "messages") else "global")


@bp.get("/bubble/dm/<uid>")
@player_required
def bubble_dm(uid):
    me = session["uid"]
    try:
        ch = _channel(f"dm-{uid}")
    except GameError as e:
        return _bubble("messages", bubble_error=str(e))
    C.mark_read(me, uid)
    return _bubble("dm", other=uid, ident=identity(uid), cant=C.can_message(me, uid), **box_ctx(ch))


@bp.get("/dots")
@player_required
def dots_view():
    """Polled by the bubble: the red dots, 204 while they haven't changed."""
    d = dots(session["uid"])
    if request.args.get("v") == f"{d['dm']}-{d['gang']}":
        return Response(status=204)
    return render_template("partials/chat_dots.html", dots=d)


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
