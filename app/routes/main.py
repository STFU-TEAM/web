"""Public pages: home, stand encyclopedia, leaderboard, public profiles."""
import random

from flask import Blueprint, Response, abort, jsonify, render_template, request, session, url_for

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
    return render_template("home.html", hand=hand, registered=registered, posts=news.list_posts(3))


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
const CACHE = "stfu-static-v1";
self.addEventListener("install", (e) => self.skipWaiting());
self.addEventListener("activate", (e) => e.waitUntil(
  caches.keys().then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
    .then(() => self.clients.claim())));
self.addEventListener("fetch", (e) => {
  const req = e.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);
  if (url.origin === location.origin && url.pathname.startsWith("/static/")) {
    e.respondWith(caches.open(CACHE).then(async (cache) => {
      const hit = await cache.match(req);
      const fresh = fetch(req).then((res) => { if (res.ok) cache.put(req, res.clone()); return res; }).catch(() => hit);
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


@bp.get("/stands")
def stands():
    q = request.args.get("q", "").strip()
    rarity = request.args.get("rarity", "")
    result = PLAYABLE
    if rarity in RARITY_ORDER:
        result = [c for c in result if c["rarity"] == rarity]
    if q:
        ql = q.lower()
        result = [c for c in result if ql in c["name"].lower() or ql in c["special_description"].lower()]
    tpl = "partials/stand_grid.html" if request.headers.get("HX-Request") else "stands.html"
    return render_template(tpl, stands=result, q=q, rarity=rarity, rarities=RARITY_ORDER)


def _wiki_ctx(topic: str) -> dict:
    facts = {**wiki_data.facts(), "tower_cost": TOWER_COST, "gang_cost": GANG_COST,
             "shop_cost": SHOP_COST, "storage_capacity": STORAGE_CAPACITY}
    ctx = {"topics": wiki_data.TOPIC_GROUPS, "topic": topic, "facts": facts}
    if topic == "terrains":
        ctx["terrains"] = wiki_data.terrain_rows()
    elif topic == "synergies":
        ctx["synergies"] = wiki_data.synergy_rows()
    elif topic == "combat":
        ctx["effects"] = wiki_data.effect_rows()
    elif topic == "types":
        ctx["types"], ctx["qualities"] = wiki_data.type_rows(), wiki_data.quality_rows()
    elif topic == "ranked":
        ctx["ranks"] = wiki_data.rank_rows()
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
        for it in item_file:
            if it.get("name"):
                entries.append({"t": it["name"], "k": "Item", "u": url_for("main.wiki", topic="items"), "s": "", "x": ""})
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
    banners = [b for b in BANNERS if banner_enabled(b) and stand_id in b["cards"]]
    return render_template("stand.html", s=s, banners=banners, wiki=wiki_data.stand_links(stand_id))


@bp.get("/leaderboard")
def leaderboard():
    by = request.args.get("by", "global_elo")
    rows = []
    for rank, row in enumerate(lb(by), start=1):
        ident = identity(row["id"])
        value = row["value"]
        if by == "xp":
            value = min(100, int(0.09 * value ** 0.5))
        rows.append({**row, "rank": rank, "name": ident["name"], "avatar": ident["avatar"], "value": value})
    tpl = "partials/leaderboard_rows.html" if request.headers.get("HX-Request") else "leaderboard.html"
    return render_template(tpl, rows=rows, by=by)


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
    unique = {c.id for c in stands}
    collection = []
    for r in RARITY_ORDER:
        pool = {c["id"] for c in PLAYABLE if c["rarity"] == r}
        if pool:
            collection.append({"rarity": r, "have": len(unique & pool), "total": len(pool)})
    showcase = sorted(stands, key=lambda c: (rank.get(c.rarity, 0), c.awaken, c.level), reverse=True)[:6]
    # progress inside the current level (the level curve is LVLSCALING * sqrt(xp))
    lvl = user.level
    next_xp = ((lvl + 1) / LVLSCALING) ** 2 if lvl < USRXPTOLEVEL else None
    this_xp = (lvl / LVLSCALING) ** 2
    level_pct = 100 if next_xp is None else max(0, min(100, 100 * (user.xp - this_xp) / max(1, next_xp - this_xp)))
    achievements = get_all_achievements_status(user)
    unlocked_ids = user.achievement_data.get("unlocked", [])
    recent = [a for a in achievements if a["unlocked"]]
    recent.sort(key=lambda a: unlocked_ids.index(a["id"]) if a["id"] in unlocked_ids else -1, reverse=True)
    return render_template(
        "profile.html", u=user, ident=identity(uid), gang=gang, uid=uid, owned=len(stands), unique=len(unique),
        playable=len(PLAYABLE), collection=collection, showcase=showcase, level_pct=round(level_pct),
        story_cleared=story.cleared(user), story_total=story.TOTAL,
        tower_week=tower.state(user)["best"], rush_best=rush.state(user)["best"], rush_total=len(rush.BOSS_STAGES),
        achievements_done=len(recent), achievements_total=len(achievements), recent=recent[:4],
        is_me=session.get("uid") == uid)
