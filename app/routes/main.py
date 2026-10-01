"""Public pages: home, stand encyclopedia, leaderboard, public profiles."""
import random

from flask import Blueprint, abort, jsonify, render_template, request, session, url_for

from app.db import get_db, identity, leaderboard as lb
from app.filters import PLAYABLE
from app.game.character import CHARACTER_FILE
from app.game.logic import BANNERS, banner_enabled
from app.game.user import STORAGE_CAPACITY, User
from app.routes.play import TOWER_COST
from app.game.gangs import GANG_COST
from app.routes.social import SHOP_COST
from app import wiki as wiki_data

bp = Blueprint("main", __name__)
RARITY_ORDER = ["R", "SR", "SSR", "UR", "LR"]


@bp.get("/")
def home():
    hand = random.sample([c for c in PLAYABLE if c["rarity"] in ("SSR", "UR", "LR")], 2) + random.sample(
        [c for c in PLAYABLE if c["rarity"] in ("R", "SR")], 3
    )
    random.shuffle(hand)
    registered = bool(session.get("uid")) and get_db().user_exists(session["uid"])
    return render_template("home.html", hand=hand, registered=registered)


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


@bp.get("/wiki")
@bp.get("/wiki/<topic>")
def wiki(topic: str = ""):
    if topic and topic not in wiki_data.TOPIC_SLUGS:
        abort(404)
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
    return render_template(f"wiki/{topic or 'index'}.html", **ctx)


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
    user = User(doc)
    gang = get_db().get_gang(user.gang_id)
    owned = len(user.main_characters) + len(user.storage_characters)
    return render_template("profile.html", u=user, ident=identity(uid), gang=gang, uid=uid, owned=owned)
