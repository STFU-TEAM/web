"""Public pages: home, stand encyclopedia, leaderboard, public profiles."""
import random

from flask import Blueprint, abort, render_template, request, session

from app.db import get_db, identity, leaderboard as lb
from app.filters import PLAYABLE
from app.game.character import CHARACTER_FILE
from app.game.effects import TERRAIN_BENEFITS, TERRAIN_SETTERS
from app.game.logic import BANNERS
from app.game.user import User

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


@bp.get("/stands/<int:stand_id>")
def stand(stand_id: int):
    if not (1 <= stand_id <= len(CHARACTER_FILE)):
        abort(404)
    s = CHARACTER_FILE[stand_id - 1]
    banners = [b for b in BANNERS if b["enabled"] and stand_id in b["cards"]]
    terrain = TERRAIN_SETTERS.get(stand_id)
    boosts = TERRAIN_BENEFITS.get(stand_id, {})
    return render_template("stand.html", s=s, banners=banners, terrain=terrain, boosts=boosts)


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
