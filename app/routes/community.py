"""Community hub: find players, friends (with invite links) and the inbox of everything waiting on you."""
import json

from flask import Blueprint, flash, redirect, render_template, request, session, url_for

from app import social
from app.accounts import resolve_player
from app.auth import player_required
from app.db import Busy, get_db, identity, r, user_lock
from app.game import story
from app.game import trades as T
from app.routes.battles import CHALLENGE_INBOX, CHALLENGE_KEY

bp = Blueprint("community", __name__, url_prefix="/community")


def _card(uid: str, me: str, db=None) -> dict:
    """What a player row shows: name, avatar, level, story, collection and how they relate to me."""
    db = db or get_db()
    user = db.get_user(uid)
    who = identity(uid)
    return {"id": uid, "name": who["name"], "avatar": who.get("avatar"),
            "level": user.level if user else 0, "story": story.cleared(user) if user else 0,
            "stands": len(user.main_characters) + len(user.storage_characters) if user else 0,
            "elo": int(getattr(user, "global_elo", 0) or 0) if user else 0,
            "gang": bool(user and user.gang_id), "relation": social.relation(me, uid)}


def _back(default="community.friends"):
    target = request.form.get("back") or request.referrer
    return redirect(target if target and target.startswith(request.host_url) else url_for(default))


# ── Find players ─────────────────────────────────────────────────────────────

@bp.get("/players")
@player_required
def players():
    me = session["uid"]
    q = request.args.get("q", "").strip()
    found = []
    if q:
        exact = resolve_player(q)
        ids = ([exact] if exact else []) + [u for u in social.search(q) if u != exact]
        db = get_db()
        found = [_card(u, me, db) for u in ids if u != me][:20]
    if request.headers.get("HX-Request"):
        return render_template("community/_player_results.html", q=q, found=found)
    return render_template("community/players.html", q=q, found=found)


# ── Friends ──────────────────────────────────────────────────────────────────

@bp.get("/friends")
@player_required
def friends():
    me = session["uid"]
    db = get_db()
    return render_template(
        "community/friends.html",
        friends=sorted((_card(u, me, db) for u in social.friends(me)), key=lambda c: c["name"].lower()),
        incoming=[_card(u, me, db) for u in social.incoming(me)],
        outgoing=[_card(u, me, db) for u in social.outgoing(me)],
        invite_url=url_for("community.join", ref=me, _external=True),
        pending_refs=[identity(u)["name"] for u in social.referral_stats(me)["pending"]],
        ref_stage=social.REFERRAL_STAGE, gifted=social.gifted_today(me), gifts=social.pending_gifts(me),
        gift_kinds=social.GIFTS, gift_cap=social.GIFT_RECEIVE_CAP,
        can_gift=story.cleared(db.get_user(me)) >= social.REFERRAL_STAGE)


@bp.post("/gift")
@player_required
def gift():
    me = session["uid"]
    other = resolve_player(request.form.get("user_id", ""))
    if not other:
        flash("That player doesn't exist.", "error")
        return _back()
    try:
        sent = social.send_gift(me, other, request.form.get("kind", "dust"))
        flash(f"🎁 {sent['label']} sent to {identity(other)['name']}.", "ok")
    except social.SocialError as e:
        flash(str(e), "error")
    return _back()


@bp.post("/gifts/open")
@player_required
def open_gifts():
    me = session["uid"]
    try:
        with user_lock(me):
            user = get_db().get_user(me)
            got = social.open_gifts(user)
            user.update()
        parts = ([f"{got['fragments']:,} Meteor Dust"] if got["fragments"] else []) + \
                ([f"{got['energy']} energy"] if got["energy"] else [])
        flash(f"🎁 You opened {got['count']} gift{'s' if got['count'] > 1 else ''}: {' and '.join(parts) or 'your energy was already full'}.", "ok")
    except social.SocialError as e:
        flash(str(e), "error")
    except Busy:
        flash("Your last action is still running.", "error")
    return _back()


@bp.post("/friends/<verb>")
@player_required
def friend_action(verb):
    me = session["uid"]
    other = resolve_player(request.form.get("user_id", ""))
    if not other:
        flash("That player doesn't exist.", "error")
        return _back()
    name = identity(other)["name"]
    try:
        if verb == "add":
            result = social.request_friend(me, other)
            flash(f"You and {name} are now friends." if result == "friends" else f"Friend request sent to {name}.", "ok")
        elif verb == "accept":
            social.accept_friend(me, other)
            flash(f"You and {name} are now friends.", "ok")
        elif verb == "decline":
            social.decline_friend(me, other)
            flash(f"Request from {name} declined.", "ok")
        elif verb == "cancel":
            social.cancel_request(me, other)
            flash(f"Request to {name} cancelled.", "ok")
        elif verb == "remove":
            social.remove_friend(me, other)
            flash(f"{name} was removed from your friends.", "ok")
    except social.SocialError as e:
        flash(str(e), "error")
    return _back()


@bp.get("/join")
def join():
    """An invite link: remember who sent it, then sign up (the save's creation records the referral)."""
    ref = request.args.get("ref", "")
    if ref and get_db().user_exists(ref):
        session["ref"] = ref
    if session.get("uid"):
        return redirect(url_for("auth.welcome") if not get_db().user_exists(session["uid"]) else url_for("main.home"))
    return render_template("community/join.html", inviter=identity(ref) if session.get("ref") else None)


# ── Inbox ────────────────────────────────────────────────────────────────────

def _challenges(uid: str) -> list:
    out = []
    for cid in r().smembers(CHALLENGE_INBOX.format(uid)):
        cid = cid.decode() if isinstance(cid, bytes) else str(cid)
        raw = r().get(CHALLENGE_KEY.format(cid))
        if not raw:
            r().srem(CHALLENGE_INBOX.format(uid), cid)
            continue
        c = json.loads(raw)
        out.append({"id": cid, "from": c["from"], "name": identity(c["from"])["name"]})
    return out


def pending_count(uid: str) -> int:
    """Things waiting on the player (the bell badge): unread news plus open requests."""
    from app import rewards
    pipe = r().pipeline(transaction=False)  # every page shows this badge: one round trip for its counters
    pipe.get(f"web:notif:seen:{uid}")
    pipe.lrange(f"web:notif:{uid}", 0, 19)
    pipe.scard(f"web:friendreq:in:{uid}")
    pipe.scard(CHALLENGE_INBOX.format(uid))
    pipe.scard(f"web:trades:in:{uid}")
    pipe.llen(f"web:gifts:{uid}")
    seen, recent, *counts = pipe.execute()
    return social.unread_in(recent, int(seen or 0)) + sum(counts) + rewards.count(uid)


@bp.post("/push/subscribe")
@player_required
def push_subscribe():
    from app import push
    ok = push.enabled() and push.subscribe(session["uid"], request.get_json(silent=True) or {})
    return ({"ok": True, "devices": push.devices(session["uid"])}, 200) if ok else ({"ok": False}, 400)


@bp.post("/push/unsubscribe")
@player_required
def push_unsubscribe():
    from app import push
    push.unsubscribe(session["uid"], (request.get_json(silent=True) or {}).get("endpoint", ""))
    return {"ok": True, "devices": push.devices(session["uid"])}


@bp.post("/push/energy")
@player_required
def push_energy():
    from app import push
    push.set_energy(session["uid"], request.form.get("on") == "1")
    return {"ok": True}


@bp.post("/push/test")
@player_required
def push_test():
    from app import push
    push.send(session["uid"], "friend", "Push notifications work on this device. ✨", "/community/inbox", force=True)
    return {"ok": True}


@bp.post("/rewards/claim")
@player_required
def claim_rewards():
    """Claim one reward (id) or every waiting one (no id) from the inbox."""
    from app import rewards
    me = session["uid"]
    wanted = request.form.get("id")
    try:
        with user_lock(me):
            user = get_db().get_user(me)
            if not user:
                raise rewards.RewardError("You need a save first.")
            ids = [wanted] if wanted else [m["id"] for m in rewards.claimable(me)]
            got, failed = [], None
            for mail_id in ids:
                try:
                    got.append(rewards.claim(user, mail_id))
                except rewards.RewardError as e:
                    failed = str(e)
                    if wanted:
                        raise
                    break  # the rest stays waiting (storage full)
            if got:
                user.update()
        if got:
            lines = [l["text"] for m in got for l in rewards.describe(m["rewards"])]
            flash(f"🎁 Claimed {got[0]['title'] if len(got) == 1 else f'{len(got)} rewards'}: {', '.join(lines)}.", "ok")
        if failed:
            flash(failed, "error")
        elif not got:
            flash("No reward is waiting.", "error")
    except rewards.RewardError as e:
        flash(str(e), "error")
    except Busy:
        flash("Your last action is still running.", "error")
    return redirect(url_for("community.inbox"))


@bp.get("/inbox")
@player_required
def inbox():
    from app import push, rewards
    me = session["uid"]
    db = get_db()
    user = db.get_user(me)
    seen_before = int(r().get(f"web:notif:seen:{me}") or 0)
    gang_invites = [g for g in (db.get_gang(gid) for gid in (user.gang_invites if user else [])) if g]
    ctx = {
        "challenges": _challenges(me),
        "trades": [{"id": o["id"], "name": identity(o["from"])["name"]} for o in T.listing(r(), me, "in")],
        "friend_requests": [_card(u, me, db) for u in social.incoming(me)],
        "gang_invites": gang_invites,
        "feed": social.feed(me),
        "rewards": rewards.claimable(me),
        "seen_before": seen_before,
        "push_key": push.keys()["public"] if push.enabled() else None,
        "push_energy": push.wants_energy(me),
    }
    social.mark_seen(me)
    return render_template("community/inbox.html", **ctx)
