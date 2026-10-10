"""Public pages: home, stand encyclopedia, leaderboard, public profiles."""
import datetime
import random
import time

from markupsafe import Markup

from flask import Blueprint, Response, abort, current_app, flash, jsonify, redirect, render_template, request, session, url_for

from app import social
from app.db import get_db, identity, leaderboard as lb
from app.filters import PLAYABLE
from app.game.character import CHARACTER_FILE
from app.game.logic import BANNERS, banner_enabled
from app.game.user import STORAGE_CAPACITY, User
from app.routes.play import TOWER_COST
from app.game.gangs import GANG_COST
from app.routes.social import SHOP_COST
from app import news, wiki as wiki_data

bp = Blueprint("main", __name__)
RARITY_ORDER = ["R", "SR", "SSR", "UR", "LR"]


@bp.get("/")
def home():
    hand = random.sample([c for c in PLAYABLE if c["rarity"] in ("SSR", "UR", "LR")], 2) + random.sample(
        [c for c in PLAYABLE if c["rarity"] in ("R", "SR")], 3
    )
    random.shuffle(hand)
    registered = bool(session.get("uid")) and get_db().user_exists(session["uid"])
    today_rows = None
    if registered:  # the Today card: every timer and allowance in one place
        from app.game import logic, today
        user = get_db().get_user(session["uid"])
        if logic.refill_energy(user):
            user.update()
        today_rows = today.rows(user, dungeon_on=current_app.config.get("DUNGEON_ENABLED"))
    return render_template("home.html", hand=hand, registered=registered, posts=news.list_posts(4), today=today_rows,
                           patch=news.latest_of("patch"))


@bp.get("/news")
def news_list():
    page = max(0, request.args.get("page", 0, type=int))
    posts = news.list_posts(11, page * 10)
    return render_template("news.html", posts=posts[:10], page=page, more=len(posts) > 10)


@bp.get("/news/<post_id>")
def news_post(post_id):
    post = news.get_post(post_id)
    if not post:
        abort(404)
    return render_template("news_post.html", post=post, others=[p for p in news.list_posts(4) if p["id"] != post_id][:3])


@bp.get("/news/cover/<post_id>")
def news_cover(post_id):
    data, mime = news.cover(post_id)
    if not data:
        abort(404)
    resp = Response(data, mimetype=mime)
    resp.headers["Cache-Control"] = "public, max-age=86400"
    resp.headers["X-Content-Type-Options"] = "nosniff"
    return resp


@bp.get("/manifest.webmanifest")
def manifest():
    """Lets phones install the site as a standalone app."""
    resp = jsonify({
        "name": "STFU Requiem", "short_name": "STFU", "id": "/", "start_url": url_for("main.home"),
        "scope": "/", "display": "standalone",
        "background_color": "#1C0F2E", "theme_color": "#2B1747",
        "description": "Pull JoJo stands, build a team of three and fight.",
        "icons": [
            {"src": url_for("static", filename="img/icon-192.png"), "sizes": "192x192", "type": "image/png"},
            {"src": url_for("static", filename="img/icon-512.png"), "sizes": "512x512", "type": "image/png"},
            {"src": url_for("static", filename="img/icon-maskable-512.png"), "sizes": "512x512",
             "type": "image/png", "purpose": "maskable"},
        ],
        "shortcuts": [
            {"name": "Team", "url": url_for("play.team")},
            {"name": "Battle", "url": url_for("battles.index", mode="dummy")},
            {"name": "Wiki", "url": url_for("main.wiki")},
        ],
    })
    resp.mimetype = "application/manifest+json"
    return resp


SERVICE_WORKER = """// STFU Requiem service worker: makes the site installable and survives a dropped connection.
// Pages are always fetched fresh (they hold your save); only static files are cached.
const CACHE = "stfu-static-v2";
self.addEventListener("install", (e) => self.skipWaiting());
self.addEventListener("activate", (e) => e.waitUntil(
  caches.keys().then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
    .then(() => self.clients.claim())));
self.addEventListener("push", (e) => {
  let data = {};
  try { data = e.data ? e.data.json() : {}; } catch (_) { data = {body: e.data && e.data.text()}; }
  e.waitUntil(self.registration.showNotification(data.title || "STFU Requiem", {
    body: data.body || "", tag: data.tag, renotify: !!data.tag, data: {url: data.url || "/"},
    icon: "/static/img/icon-192.png", badge: "/static/img/icon-192.png"}));
});
self.addEventListener("notificationclick", (e) => {
  e.notification.close();
  const url = new URL((e.notification.data && e.notification.data.url) || "/", location.origin).href;
  e.waitUntil(clients.matchAll({type: "window", includeUncontrolled: true}).then((list) => {
    const open = list.find((c) => c.url.startsWith(location.origin));
    return open ? open.navigate(url).then((c) => c && c.focus()) : clients.openWindow(url);
  }));
});
self.addEventListener("fetch", (e) => {
  const req = e.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);
  if (url.origin === location.origin && url.pathname.startsWith("/static/")) {
    e.respondWith(caches.open(CACHE).then(async (cache) => {
      const hit = await cache.match(req);
      const fresh = fetch(req).then((res) => {
        if (res.ok) {
          cache.put(req, res.clone());
          // a new ?v= version replaces the old copies of the same file
          cache.keys().then((keys) => keys.forEach((k) => { const u = new URL(k.url); if (u.pathname === url.pathname && u.search !== url.search) cache.delete(k); }));
        }
        return res;
      }).catch(() => hit);
      return hit || fresh;
    }));
  } else if (req.mode === "navigate") {
    e.respondWith(fetch(req).catch(() => new Response(
      '<!doctype html><meta name=viewport content="width=device-width"><body style="font-family:sans-serif;background:#1C0F2E;color:#EDE6F7;display:grid;place-items:center;min-height:90vh;text-align:center"><div><h1>You are offline</h1><p>STFU Requiem needs a connection. Try again in a moment.</p></div>',
      {headers: {"Content-Type": "text/html; charset=utf-8"}})));
  }
});
"""


@bp.get("/sw.js")
def service_worker():
    resp = Response(SERVICE_WORKER, mimetype="text/javascript")
    resp.headers["Cache-Control"] = "no-cache"
    resp.headers["Service-Worker-Allowed"] = "/"
    return resp


@bp.post("/prefs/fight-cosmetics")
def pref_fight_cosmetics():
    """Draw fighters with their shiny / full art (on) or their classic picture (off). Kept in the session."""
    session["fight_cosmetics"] = request.form.get("on") == "1"
    return "", 204


@bp.post("/prefs/fight-fx")
def pref_fight_fx():
    """Battle cries, heavy-hit sound effects and the eyecatch (on), or plain fights (off). Kept in the session."""
    session["fight_fx"] = request.form.get("on") == "1"
    return "", 204


@bp.get("/stands")
def stands():
    q = request.args.get("q", "").strip()
    rarity = request.args.get("rarity", "")
    look = request.args.get("look", "")
    look = look if look in LOOKS else ""
    unique = bool(request.args.get("unique"))
    result = PLAYABLE
    if rarity in RARITY_ORDER:
        result = [c for c in result if c["rarity"] == rarity]
    if q:
        ql = q.lower()
        result = [c for c in result if ql in c["name"].lower() or ql in c["special_description"].lower()]
    if unique:  # only stands with their own illustration for the look (any of them for "classic")
        art = current_app.extensions.get("art_files", {})
        kinds = {"": ("artwork", "shiny"), "full": ("artwork",), "shiny": ("shiny",), "both": ("artwork", "shiny")}[look]
        result = [c for c in result if any(c["id"] in art.get(k, {}) for k in kinds)]
    # The grid is the same for everyone (public data): rendered once per filter and kept GRID_TTL seconds.
    key = (q.lower(), rarity, look, unique)
    hit = _grid_cache.get(key)
    if hit and time.time() - hit[0] < GRID_TTL:
        grid = hit[1]
    else:
        grid = Markup(render_template("partials/stand_grid.html", stands=result, look=look, unique=unique, looks=LOOKS))
        if len(_grid_cache) >= 256:
            _grid_cache.clear()
        _grid_cache[key] = (time.time(), grid)
    if request.headers.get("HX-Request"):
        return grid
    return render_template("stands.html", stands=result, q=q, rarity=rarity, rarities=RARITY_ORDER, look=look, unique=unique,
                           looks=LOOKS, grid=grid)


GRID_TTL = 600
_grid_cache = {}  # (query, rarity, look, unique) -> (rendered at, grid HTML)


# Cosmetic previews on the stands page: how each card looks at ★3 (full art), shiny, or both
LOOKS = {"": "Classic", "full": "Full art", "shiny": "Shiny", "both": "Shiny full art"}


def _wiki_ctx(topic: str) -> dict:
    facts = {**wiki_data.facts(), "tower_cost": TOWER_COST, "gang_cost": GANG_COST,
             "shop_cost": SHOP_COST, "storage_capacity": STORAGE_CAPACITY}
    ctx = {"topics": wiki_data.TOPIC_GROUPS, "topic": topic, "facts": facts}
    if topic == "terrains":
        ctx["terrains"] = wiki_data.terrain_rows()
    elif topic == "synergies":
        ctx["synergies"] = wiki_data.synergy_rows()
        ctx["resonances"], ctx["leverage"] = wiki_data.resonance_rows(), wiki_data.leverage_rows()
    elif topic == "combat":
        ctx["effects"] = wiki_data.effect_rows()
    elif topic == "types":
        ctx["types"], ctx["qualities"] = wiki_data.type_rows(), wiki_data.quality_rows()
    elif topic == "ranked":
        ctx["ranks"], ctx["seasons"] = wiki_data.rank_rows(), wiki_data.season_rows()
    elif topic == "events":
        ctx["shop"] = wiki_data.event_shop_rows()
    elif topic == "progress":
        ctx["mastery"], ctx["sets"] = wiki_data.mastery_rows(), wiki_data.dex_rows()
    elif topic == "guide":
        ctx["g"] = wiki_data.guide_rows()
    elif topic == "items":
        ctx["items"] = wiki_data.item_rows()
    return ctx


@bp.get("/wiki")
@bp.get("/wiki/<topic>")
def wiki(topic: str = ""):
    if topic and topic not in wiki_data.TOPIC_SLUGS:
        abort(404)
    return render_template(f"wiki/{topic or 'index'}.html", **_wiki_ctx(topic))


_SEARCH_INDEX = None


@bp.get("/wiki/search.json")
def wiki_search_index():
    """Everything the wiki search box can find, built once: guide pages (full text), stands, items,
    terrains, synergies and status effects."""
    global _SEARCH_INDEX
    if _SEARCH_INDEX is None:
        import re
        from app.game.items import item_file
        entries = []
        for slug, title, blurb, _group in wiki_data.TOPICS:
            html = render_template(f"wiki/{slug}.html", **_wiki_ctx(slug))
            body = html.split('<article class="wiki-body">', 1)[-1].split("</article>", 1)[0]
            text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", body)).strip()
            entries.append({"t": title, "k": "Guide", "u": url_for("main.wiki", topic=slug), "s": blurb, "x": text})
        for c in PLAYABLE:
            entries.append({"t": c["name"], "k": f"Stand · {c['rarity']}", "u": url_for("main.stand", stand_id=c["id"]),
                            "s": c["special_description"].replace("`", ""), "x": c["universe"]})
        for it in wiki_data.item_rows():
            entries.append({"t": it["name"], "k": f"Item · {it['kind']}", "u": url_for("main.wiki", topic="items") + f"#item-{it['id']}",
                            "s": it["ability"] or it["use"] or " · ".join(it["bonus"]),
                            "x": " ".join(w for w, _ in it["sources"])})
        for t in wiki_data.terrain_rows():
            entries.append({"t": t["name"], "k": "Terrain", "u": url_for("main.wiki", topic="terrains") + "#" + t["key"],
                            "s": t.get("rule") or t["blurb"], "x": " ".join(s["name"] for s in t["setters"])})
        for g in wiki_data.synergy_rows():
            entries.append({"t": g["name"], "k": "Synergy", "u": url_for("main.wiki", topic="synergies") + "#" + g["key"],
                            "s": g["rule"], "x": " ".join(m["stand"]["name"] for m in g["members"])})
        for e in wiki_data.effect_rows():
            entries.append({"t": e["name"], "k": "Status effect", "u": url_for("main.wiki", topic="combat"),
                            "s": e["text"], "x": ""})
        _SEARCH_INDEX = entries
    resp = jsonify(_SEARCH_INDEX)
    resp.headers["Cache-Control"] = "public, max-age=3600"
    return resp


@bp.get("/stands/<int:stand_id>")
def stand(stand_id: int):
    if not (1 <= stand_id <= len(CHARACTER_FILE)):
        abort(404)
    s = CHARACTER_FILE[stand_id - 1]
    from app.game.logic import next_appearance
    banners = [{"b": b, "on": banner_enabled(b), "next": next_appearance(b["id"])}
               for b in BANNERS if stand_id in b["cards"]]
    banners.sort(key=lambda x: (not x["on"], x["next"] or datetime.date.max))
    return render_template("stand.html", s=s, banners=banners, wiki=wiki_data.stand_links(stand_id))


@bp.get("/leaderboard")
def leaderboard():
    by = request.args.get("by", "global_elo")
    rows = []
    if by == "season":
        from app.db import r
        from app.game import seasons
        source, season = seasons.board(r()), seasons.standing(r(), "", 0)
    else:
        source, season = lb(by), None
    from app.db import identities
    who = identities(row["id"] for row in source)
    for rank, row in enumerate(source, start=1):
        ident = who[str(row["id"])]
        value = row["value"]
        if by == "xp":
            value = min(100, int(0.09 * value ** 0.5))
        rows.append({**row, "rank": rank, "name": ident["name"], "avatar": ident["avatar"], "value": value})
    tpl = "partials/leaderboard_rows.html" if request.headers.get("HX-Request") else "leaderboard.html"
    return render_template(tpl, rows=rows, by=by, season=season)


@bp.get("/u/<uid>")
def profile(uid: str):
    doc = get_db().get_user_doc(uid)
    if not doc:
        abort(404)
    from math import sqrt
    from app.game import rush, story, tower
    from app.game.achievements import get_all_achievements_status
    from app.game.user import LVLSCALING, USRXPTOLEVEL
    user = User(doc)
    gang = get_db().get_gang(user.gang_id)
    stands = user.main_characters + user.storage_characters
    rank = {r: i for i, r in enumerate(RARITY_ORDER)}
    unique = {c.id for c in stands} | set(user.data.get("web_dex") or [])  # every stand ever owned here
    collection = []
    for r in RARITY_ORDER:
        pool = {c["id"] for c in PLAYABLE if c["rarity"] == r}
        if pool:
            collection.append({"rarity": r, "have": len(unique & pool), "total": len(pool)})
    from app.game import profile as P
    pv = P.view(user)
    showcase = pv["showcase"] or sorted(stands, key=lambda c: (rank.get(c.rarity, 0), c.awaken, c.level), reverse=True)[:6]
    # progress inside the current level (the level curve is LVLSCALING * sqrt(xp))
    lvl = user.level
    next_xp = ((lvl + 1) / LVLSCALING) ** 2 if lvl < USRXPTOLEVEL else None
    this_xp = (lvl / LVLSCALING) ** 2
    level_pct = 100 if next_xp is None else max(0, min(100, 100 * (user.xp - this_xp) / max(1, next_xp - this_xp)))
    achievements = get_all_achievements_status(user)
    unlocked_ids = user.achievement_data.get("unlocked", [])
    recent = [a for a in achievements if a["unlocked"]]
    recent.sort(key=lambda a: unlocked_ids.index(a["id"]) if a["id"] in unlocked_ids else -1, reverse=True)
    from app.db import r
    from app.game import history, mastery, seasons, titles
    from app.routes.battles import live_fight_of
    mastery_titles = mastery.titles(r(), uid)
    is_me = session.get("uid") == uid
    battles = history.recent(r(), uid, limit=6, viewer=session.get("uid"))
    shown_title = titles.shown(user, mastery_titles)
    if is_me:
        titles.remember(uid, shown_title)  # chats show it next to the name
    return render_template(
        "profile.html", season=seasons.standing(r(), uid, user.global_elo),
        title=shown_title, my_titles=titles.available(user, mastery_titles) if is_me else [],
        title_goals=titles.progress(user) if is_me else [],
        mastery=mastery.ranking(r(), uid, limit=6), battles=battles, battle_record=history.summary(battles),
        live_fight=live_fight_of(uid) if session.get("uid") else None,
        u=user, ident=identity(uid), gang=gang, uid=uid, owned=len(stands), unique=len(unique),
        playable=len(PLAYABLE), collection=collection, showcase=showcase, level_pct=round(level_pct),
        story_cleared=story.cleared(user), story_total=story.TOTAL,
        tower_week=tower.state(user)["best"], rush_best=rush.state(user)["best"], rush_total=len(rush.BOSSES),
        achievements_done=len(recent), achievements_total=len(achievements), recent=recent[:4],
        is_me=is_me, pv=pv, best=pv["stand"] or (showcase[0] if showcase else None),
        themes=P.themes(user) if is_me else [], unlocked_achievements=[a for a in achievements if a["unlocked"]] if is_me else [],
        my_profile=P.get(user) if is_me else {}, stands=stands if is_me else [], report_reasons=P.REASONS,
        web_only=uid.startswith("acc"),
        quote_max=P.QUOTE_MAX, showcase_max=P.SHOWCASE_MAX, pin_max=P.PIN_MAX,
        relation=social.relation(session["uid"], uid) if session.get("uid") else None)


@bp.post("/profile")
def profile_edit():
    """Save the Stand User file: catchphrase, theme, signature stand, showcase, pinned achievements and title."""
    from app.db import Busy, user_lock
    from app.game import mastery, profile as P, titles
    from app.game.logic import GameError
    uid = session.get("uid")
    if not uid or not get_db().user_exists(uid):
        abort(403)
    f = request.form
    try:
        with user_lock(uid):
            user = get_db().get_user(uid)
            P.save(user, f.get("quote", ""), f.get("theme", ""), f.get("stand", ""), f.getlist("showcase"), f.getlist("pins"),
                   f.get("image", ""), f.get("avatar"))
            if "avatar" in f:  # the nav's picture follows at once
                session["avatar"] = (user.data.get("web_profile") or {}).get("avatar") or None
            from app.db import r
            titles.choose(user, f.get("title", ""), mastery.titles(r(), uid))
            user.update()
        flash("Profile saved.", "ok")
    except GameError as e:
        flash(str(e), "error")
    except Busy:
        flash("Your last action is still running.", "error")
    return redirect(url_for("main.profile", uid=uid) + "#customize")


@bp.post("/u/<uid>/report")
def profile_report(uid: str):
    from app.game import profile as P
    from app.game.logic import GameError
    me = session.get("uid")
    if not me or not get_db().user_exists(me):
        abort(403)
    if not get_db().user_exists(uid):
        abort(404)
    try:
        P.report(me, uid, request.form.get("reason", ""), request.form.get("note", ""))
        flash("Thanks: an admin will look at this profile.", "ok")
    except GameError as e:
        flash(str(e), "error")
    return redirect(url_for("main.profile", uid=uid))
