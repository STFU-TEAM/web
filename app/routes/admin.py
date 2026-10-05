"""Admin panel: dashboard, player management, gangs, shops, banners and the audit log.
Restricted to DISCORD_ADMIN_IDS (the bot's give_character permission). Every change is audited."""
import datetime
import json

from flask import Blueprint, flash, redirect, render_template, request, session, url_for

from app import accounts
from app.accounts import resolve_player
from app.auth import admin_required
from app.db import Busy, clear_fight, get_db, identity, load_fight, r, user_lock
from app.filters import PLAYABLE, RARITY_RANK
from app.game import logic
from app.game.character import CHARACTER_FILE, get_character_from_template
from app.game.items import item_file, item_from_dict
from app.game.logic import BANNERS
from app.game import story

bp = Blueprint("admin", __name__, url_prefix="/admin")
MAX_CURRENCY_GRANT = 1_000_000
MAX_ITEM_GRANT = 25
AUDIT_KEY = "web:admin:audit"
STATS_KEY = "web:admin:stats"
EDITABLE = {  # field -> (label, min, max)
    "fragments": ("Fragments", 0, 1_000_000_000),
    "super_fragments": ("Arrowheads", 0, 100_000),
    "energy": ("Energy", 0, 1000),
    "pity": ("Pity", 0, 1000),
    "global_elo": ("Ranked elo", 0, 100_000),
    "xp": ("Player XP", 0, 10_000_000),
    "tower_level": ("Tower level", 0, 10_000),
}


def _int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def audit(kind: str, target: str = "", **details):
    r().lpush(AUDIT_KEY, json.dumps({"at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                                     "actor": session["uid"], "target": target, "kind": kind, **details}))
    r().ltrim(AUDIT_KEY, 0, 999)
    r().expire(AUDIT_KEY, 365 * 24 * 3600)


def _audit_rows(limit=10, kind=None, target=None):
    rows = []
    for raw in r().lrange(AUDIT_KEY, 0, 999 if (kind or target) else limit - 1):
        try:
            row = json.loads(raw)
        except (TypeError, ValueError):
            continue
        if (kind and row.get("kind") != kind) or (target and row.get("target") != target):
            continue
        rows.append(row)
        if len(rows) >= limit:
            break
    return rows


def _economy():
    """Scan every save once per 5 minutes: totals, rarity spread, richest, newest."""
    cached = r().get(STATS_KEY)
    if cached:
        return json.loads(cached)
    totals = {"fragments": 0, "super": 0, "stands": 0, "items": 0, "web_only": 0, "supporters": 0}
    rarity = {k: 0 for k in RARITY_RANK}
    rich, newest = [], []
    now = logic.now()
    for uid, doc in get_db().all_user_docs():
        totals["fragments"] += int(doc.get("fragments", 0) or 0)
        totals["super"] += int(doc.get("super_fragments", doc.get("super_fragments", 0)) or 0)
        totals["items"] += len(doc.get("items", []))
        totals["web_only"] += uid.startswith("acc")
        if doc.get("early_supporter") or (doc.get("donor_status") or datetime.datetime.min) > now:
            totals["supporters"] += 1
        stands = doc.get("main_characters", []) + doc.get("storage_characters", [])
        totals["stands"] += len(stands)
        for s in stands:
            try:
                rarity[CHARACTER_FILE[s["id"] - 1]["rarity"]] += 1
            except (KeyError, IndexError, TypeError):
                pass
        rich.append((int(doc.get("fragments", 0) or 0), uid))
        joined = doc.get("join_date")
        if isinstance(joined, datetime.datetime):
            newest.append((joined.isoformat(), uid))
    rich.sort(reverse=True)
    newest.sort(reverse=True)
    data = {"totals": totals, "rarity": rarity, "rich": rich[:8], "newest": newest[:8],
            "at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="minutes")}
    r().set(STATS_KEY, json.dumps(data), ex=300)
    return data


def _find_by_name(query: str, limit=12):
    """Display-name search over remembered identities (players who logged in on the web)."""
    q = query.lower()
    found = []
    for key in r().scan_iter("web:identity:*", count=500):
        uid = key.decode().split(":", 2)[2]
        try:
            name = json.loads(r().get(key) or "{}").get("name", "")
        except ValueError:
            continue
        if q in name.lower() and get_db().user_exists(uid):
            found.append({"id": uid, "name": name})
            if len(found) >= limit:
                break
    return found


# --------------------------------------------------------------------------- #
# Dashboard and search
# --------------------------------------------------------------------------- #
@bp.get("")
@admin_required
def index():
    query = request.args.get("q", "").strip()
    if query:
        uid = resolve_player(query)
        if uid:
            return redirect(url_for("admin.player", uid=uid))
        matches = _find_by_name(query)
        if len(matches) == 1:
            return redirect(url_for("admin.player", uid=matches[0]["id"]))
        if not matches:
            flash("No player found by username, ID or display name.", "error")
    else:
        matches = []
    if request.args.get("refresh"):
        r().delete(STATS_KEY)
    counts = {"players": r().hlen("users"), "gangs": r().hlen("gangs"), "shops": r().hlen("shops"),
              "banned": r().scard("web:banned"), "wars": r().hlen("active_wars") // 2}
    stats = _economy()
    for key in ("rich", "newest"):
        stats[key] = [(value, uid, identity(uid)["name"]) for value, uid in stats[key]]
    return render_template("admin/index.html", q=query, matches=matches, counts=counts, stats=stats,
                           audit=_audit_rows(8), section="dashboard")


# --------------------------------------------------------------------------- #
# One player
# --------------------------------------------------------------------------- #
@bp.get("/player/<uid>")
@admin_required
def player(uid):
    db = get_db()
    target = db.get_user(uid)
    if not target:
        flash("No save for that ID.", "error")
        return redirect(url_for("admin.index"))
    gang = db.get_gang(target.gang_id)
    counts = {}
    for it in target.items:
        counts.setdefault(it.id, [it, 0])[1] += 1
    stands = sorted([(c, True) for c in target.main_characters] + [(c, False) for c in target.storage_characters],
                    key=lambda x: (not x[1], -RARITY_RANK.get(x[0].rarity, 0), -x[0].level))
    return render_template("admin/player.html", t=target, uid=uid, ident=identity(uid), gang=gang,
                           username=accounts.username_of(uid), banned=r().sismember("web:banned", uid),
                           items=sorted(counts.values(), key=lambda x: x[0].id), stands=stands,
                           catalog=item_file, STANDS=PLAYABLE, EDITABLE=EDITABLE, MAX_AWAKEN=logic.MAX_AWAKEN, fight=load_fight(uid),
                           history=_audit_rows(15, target=uid), now=logic.now(), story_total=story.TOTAL,
                           section="players")


@bp.get("/player/<uid>/raw")
@admin_required
def player_raw(uid):
    doc = get_db().get_user_doc(uid)
    if doc is None:
        return "No save", 404
    audit("view_raw", uid)
    return render_template("admin/raw.html", uid=uid, ident=identity(uid),
                           raw=json.dumps(doc, indent=2, default=str, ensure_ascii=False), section="players")


def _edit(uid, fn, kind, ok, **details):
    try:
        with user_lock(uid):
            target = get_db().get_user(uid)
            if target is None:
                flash("No save for that ID.", "error")
                return
            msg = fn(target)
            target.update()
            audit(kind, uid, **details)
            flash(msg or ok, "ok")
    except logic.GameError as e:
        flash(str(e), "error")
    except Busy:
        flash("That account is busy with another action. Try again.", "error")


@bp.post("/player/<uid>/<op>")
@admin_required
def player_action(uid, op):
    f = request.form
    back = redirect(url_for("admin.player", uid=uid) + f.get("anchor", ""))
    name = identity(uid)["name"]

    if op == "set":
        field, value = f.get("field"), _int(f.get("value"))
        if field not in EDITABLE or value is None or not EDITABLE[field][1] <= value <= EDITABLE[field][2]:
            flash("Pick a field and a value in range.", "error")
            return back

        def run(t):
            before = getattr(t, field)
            setattr(t, field, value)
            return f"{EDITABLE[field][0]}: {before:,} → {value:,}."
        _edit(uid, run, "set", "", field=field, value=value)

    elif op == "grant":
        kind, amount, item_id = f.get("kind"), _int(f.get("amount")), _int(f.get("item_id"))
        cap = MAX_ITEM_GRANT if kind == "item" else MAX_CURRENCY_GRANT
        if kind not in {"fragments", "super_fragments", "item"} or amount is None or not 1 <= amount <= cap:
            flash(f"Choose an amount from 1 to {cap:,}.", "error")
            return back
        if kind == "item" and not (item_id and 1 <= item_id <= len(item_file)):
            flash("Choose an item.", "error")
            return back

        def run(t):
            if kind == "fragments":
                t.fragments += amount
            elif kind == "super_fragments":
                t.super_fragments += amount
            else:
                t.items.extend(item_from_dict({"id": item_id}) for _ in range(amount))
        _edit(uid, run, kind, f"Granted {amount:,} {item_file[item_id - 1]['name'] if kind == 'item' else kind.replace('_', ' ')} to {name}.",
              amount=amount, item_id=item_id if kind == "item" else None)

    elif op == "take_item":
        item_id, amount = _int(f.get("item_id")), _int(f.get("amount")) or 1

        def run(t):
            owned = [i for i in t.items if i.id == item_id]
            if not owned:
                raise logic.GameError("They don't have that item.")
            for it in owned[:amount]:
                t.items.remove(it)
            return f"Removed {min(amount, len(owned))} × {owned[0].name}."
        _edit(uid, run, "take_item", "", item_id=item_id, amount=amount)

    elif op == "grant_stand":
        stand_id, level, awaken = _int(f.get("stand_id")), _int(f.get("level")), _int(f.get("awaken"))
        shiny = bool(f.get("shiny"))
        if (stand_id not in {s["id"] for s in PLAYABLE} or level is None or not 0 <= level <= 100
                or awaken not in range(logic.MAX_AWAKEN + 1)):
            flash(f"Choose a stand, a level (0-100) and an awakening (0-{logic.MAX_AWAKEN}).", "error")
            return back

        def run(t):
            types, qualities = logic.roll_types_qualities() if f.get("roll") else ([], [])
            stand = get_character_from_template(CHARACTER_FILE[stand_id - 1], types, qualities)
            stand.xp, stand.awaken, stand.shiny = level * 100, awaken, shiny
            if not logic.add_to_available_storage(t, stand, skip_main=True):
                raise logic.GameError("Their storage is full.")
            return f"Granted {'✨ shiny ' if shiny else ''}{stand.name} (Lv {level}, ★{awaken}) to {name}."
        _edit(uid, run, "stand", "", stand_id=stand_id, level=level, awaken=awaken, shiny=shiny)

    elif op == "stand_edit":
        stand_uuid, level, awaken = f.get("uuid"), _int(f.get("level")), _int(f.get("awaken"))
        shiny = bool(f.get("shiny"))

        def run(t):
            c = t.find_character_by_uuid(stand_uuid)[0]
            if c is None:
                raise logic.GameError("That stand is gone.")
            if level is not None and 0 <= level <= 100:
                c.xp = level * 100
            if awaken is not None and 0 <= awaken <= logic.MAX_AWAKEN:
                c.awaken = awaken
            c.shiny = shiny
            return f"{c.name} set to Lv {c.xp // 100}, ★{c.awaken}{', shiny' if shiny else ''}."
        _edit(uid, run, "stand_edit", "", uuid=stand_uuid, level=level, awaken=awaken, shiny=shiny)

    elif op == "stand_remove":
        stand_uuid = f.get("uuid")

        def run(t):
            c, lst, idx = t.find_character_by_uuid(stand_uuid)
            if c is None:
                raise logic.GameError("That stand is gone.")
            lst.pop(idx)
            for team in t.teams.values():
                if stand_uuid in team:
                    team.remove(stand_uuid)
            t.items.extend(c.items)  # equipped items go back to the inventory
            return f"Removed {c.name}; its items went back to the inventory."
        _edit(uid, run, "stand_remove", "", uuid=stand_uuid)

    elif op == "cooldowns":
        def run(t):
            t.last_adventure = t.last_wormhole = datetime.datetime.min
            t.last_full_energy = datetime.datetime.min
            t.energy = t.total_energy
        _edit(uid, run, "cooldowns", f"Cooldowns reset and energy refilled for {name}.")

    elif op == "story_reset":
        def run(t):
            t.data["web_story"] = {"cleared": 0}
            r().delete(f"web:story_done:{uid}")
        _edit(uid, run, "story_reset", f"Story reset for {name}.")

    elif op == "supporter":
        days = _int(f.get("days"))

        def run(t):
            if days and days > 0:
                base = max(t.donor_status, logic.now())
                t.donor_status = base + datetime.timedelta(days=days)
                return f"Supporter until {t.donor_status:%Y-%m-%d}."
            t.donor_status = datetime.datetime.min
            return "Supporter status removed."
        _edit(uid, run, "supporter", "", days=days or 0)

    elif op == "clear_fight":
        clear_fight(uid)
        audit("clear_fight", uid)
        flash("Active web fight cleared.", "ok")

    elif op == "ban":
        if uid == session["uid"]:
            flash("You can't ban yourself.", "error")
        elif r().sismember("web:banned", uid):
            r().srem("web:banned", uid)
            audit("unban", uid)
            flash(f"{name} can use the website again.", "ok")
        else:
            r().sadd("web:banned", uid)
            r().hset("web:ban_reason", uid, f.get("reason", "")[:200])
            audit("ban", uid, reason=f.get("reason", "")[:200])
            flash(f"{name} is banned from the website (the bot is unaffected).", "ok")
    else:
        flash("Unknown action.", "error")
    return back


# --------------------------------------------------------------------------- #
# Gangs, shops, banners, audit
# --------------------------------------------------------------------------- #
@bp.get("/gangs")
@admin_required
def gangs():
    rows = sorted(get_db().all_gangs(), key=lambda g: (-int(g.get("war_elo", 0)), g.get("name", "").lower()))
    return render_template("admin/gangs.html", gangs=rows, section="gangs",
                           boss_of={g["_id"]: identity(next((u for u, rk in g.get("ranks", {}).items() if int(rk) == 0),
                                                            (g.get("users") or ["?"])[0]))["name"] for g in rows})


@bp.post("/gangs/<gang_id>/<op>")
@admin_required
def gang_action(gang_id, op):
    db = get_db()
    try:
        with user_lock(f"gang:{gang_id}"):
            gang = db.get_gang(gang_id)
            if not gang:
                flash("That gang is gone.", "error")
            elif op == "vault":
                value = _int(request.form.get("value"))
                if value is None or not 0 <= value <= 1_000_000_000:
                    flash("Enter a vault amount.", "error")
                else:
                    audit("gang_vault", gang_id, before=gang.get("vault", 0), value=value)
                    gang["vault"] = value
                    db.update_gang(gang)
                    flash(f"{gang['name']}'s vault set to {value:,}.", "ok")
            elif op == "disband":
                for member in [str(u) for u in gang.get("users", [])]:
                    with user_lock(member):
                        u = db.get_user(member)
                        if u and u.gang_id == gang_id:
                            u.gang_id = None
                            u.update()
                db.delete_gang(gang_id)
                r().hdel("active_wars", gang_id)
                audit("gang_disband", gang_id, name=gang.get("name"))
                flash(f"{gang['name']} was disbanded. Guardians and stash were deleted with it.", "ok")
    except Busy:
        flash("Someone in that gang is busy. Try again.", "error")
    return redirect(url_for("admin.gangs"))


@bp.get("/shops")
@admin_required
def shops():
    rows = []
    for shop in get_db().all_shops():
        rows.append({"shop": shop, "owner": identity(shop.get("owner", "?")),
                     "listings": [(i, item_file[it["id"] - 1]["name"], price)
                                  for i, (it, price) in enumerate(zip(shop.get("items", []), shop.get("prices", [])))]})
    return render_template("admin/shops.html", rows=rows, section="shops")


@bp.post("/shops/<shop_id>/unlist/<int:index>")
@admin_required
def shop_unlist(shop_id, index):
    db = get_db()
    shop = db.get_shop(shop_id)
    if not shop or not 0 <= index < len(shop.get("items", [])):
        flash("That listing is gone.", "error")
        return redirect(url_for("admin.shops"))
    owner = str(shop.get("owner"))
    try:
        with user_lock(owner):
            item = shop["items"].pop(index)
            shop["prices"].pop(index)
            u = db.get_user(owner)
            if u:
                u.items.append(item_from_dict(item))  # back to the seller
                u.update()
            db.update_shop(shop)
            audit("shop_unlist", owner, shop=shop_id, item_id=item["id"])
            flash("Listing removed and the item returned to the seller.", "ok")
    except Busy:
        flash("The seller is busy. Try again.", "error")
    return redirect(url_for("admin.shops"))


@bp.get("/stats")
@admin_required
def stats():
    from app.game import stats as balance
    weeks = request.args.get("weeks", 4, type=int)
    weeks = weeks if weeks in (1, 4, 12) else 4
    return render_template("admin/stats.html", data=balance.report(r(), logic.now(), weeks), weeks=weeks, section="stats")


@bp.route("/banners", methods=["GET", "POST"])
@admin_required
def banners():
    if request.method == "POST":
        banner_id = request.form.get("id", "")
        state = request.form.get("state")
        if state in ("0", "1"):
            r().hset("web:banner_state", banner_id, state)
        else:
            r().hdel("web:banner_state", banner_id)
        audit("banner", banner_id, state=state or "default")
        flash("Banner updated.", "ok")
        return redirect(url_for("admin.banners"))
    week = logic.rotation_ids(logic.rotation_day())
    rows = [{"b": b, "on": logic.banner_enabled(b), "override": r().hget("web:banner_state", str(b["id"])),
             "rotation": b["id"] in week, "next": logic.next_appearance(b["id"])} for b in BANNERS]
    return render_template("admin/banners.html", rows=rows, section="banners", schedule=logic.banner_schedule(7))


@bp.route("/news", methods=["GET", "POST"])
@admin_required
def news_admin():
    from app import news
    editing = news.get_post(request.args.get("edit", "")) if request.args.get("edit") else None
    if request.method == "POST":
        f = request.form
        upload = request.files.get("cover_file")
        data = upload.read() if upload and upload.filename else None
        try:
            post = news.save_post(session["uid"], f.get("title", ""), f.get("body", ""), f.get("cover_url", ""),
                                  data, post_id=f.get("id") or None, remove_cover=bool(f.get("remove_cover")))
        except news.NewsError as e:
            flash(str(e), "error")
            return render_template("admin/news.html", posts=news.list_posts(50), editing=editing, form=f,
                                   section="news"), 400
        audit("news_edit" if f.get("id") else "news_post", post["id"], title=post["title"])
        flash("Post updated." if f.get("id") else "Post published.", "ok")
        return redirect(url_for("main.news_post", post_id=post["id"]))
    return render_template("admin/news.html", posts=news.list_posts(50), editing=editing, form={}, section="news")


@bp.post("/news/<post_id>/delete")
@admin_required
def news_delete(post_id):
    from app import news
    post = news.get_post(post_id)
    if post:
        news.delete_post(post_id)
        audit("news_delete", post_id, title=post["title"])
        flash("Post deleted.", "ok")
    return redirect(url_for("admin.news_admin"))


@bp.get("/audit")
@admin_required
def audit_log():
    kind = request.args.get("kind") or None
    target = request.args.get("target") or None
    rows = _audit_rows(200, kind=kind, target=target)
    kinds = sorted({row.get("kind", "") for row in _audit_rows(1000)})
    names = {uid: identity(uid)["name"] for uid in {row.get("actor") for row in rows} if uid}
    return render_template("admin/audit.html", rows=rows, kinds=kinds, kind=kind, target=target,
                           names=names, section="audit")


@bp.route("/events", methods=["GET", "POST"])
@admin_required
def events_admin():
    from app.game import events
    from app.game.characterabilities import SYNERGIES, SYNERGY_INFO
    if request.method == "POST":
        f = request.form
        try:
            if f.get("op") == "create":
                ev = events.create(r(), f.get("name", ""), f.get("blurb", ""), f.get("start", ""), f.get("end", ""),
                                   f.get("kind", ""), f.get("rarity") if f.get("kind") == "rarity" else f.get("synergy", ""))
                audit("event_create", ev["id"], name=ev["name"], modifier=ev["kind"], spotlight=ev["target"],
                      start=ev["start"], end=ev["end"])
                flash(f"Event “{ev['name']}” scheduled.", "ok")
            elif f.get("op") == "end":
                events.end_now(r(), f.get("id", ""))
                audit("event_end", f.get("id", ""))
                flash("Event ended.", "ok")
            elif f.get("op") == "delete":
                events.delete(r(), f.get("id", ""))
                audit("event_delete", f.get("id", ""))
                flash("Event deleted.", "ok")
        except logic.GameError as e:
            flash(str(e), "error")
        return redirect(url_for("admin.events_admin"))
    today = logic.now().date()
    return render_template("admin/events.html", section="events", E=events, rows=events.all_events(r()),
                           today=today, rarities=logic.RARITIES, kinds=events.KINDS,
                           synergies=sorted(((k, SYNERGY_INFO.get(k, (k, ""))[0]) for k in SYNERGIES), key=lambda x: x[1]),
                           default_end=(today + datetime.timedelta(days=7)).isoformat())
