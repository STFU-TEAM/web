import secrets

from flask import abort, current_app, request, session

from app.game.character import CHARACTER_FILE, Qualities, Types
from app.game.logic import fmt_delta, rank_name

RARITY = {"R": "common", "SR": "rare", "SSR": "epic", "UR": "legend", "LR": "mythic"}
PLAYABLE = [c for c in CHARACTER_FILE if c["universe"] != "Dummy"]
TAROT = [
    "0", "I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X",
    "XI", "XII", "XIII", "XIV", "XV", "XVI", "XVII", "XVIII", "XIX", "XX", "XXI",
]


def roman(n: int) -> str:
    vals = [(1000, "M"), (900, "CM"), (500, "D"), (400, "CD"), (100, "C"), (90, "XC"),
            (50, "L"), (40, "XL"), (10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I")]
    out = ""
    for v, s in vals:
        while n >= v:
            out += s
            n -= v
    return out


def register(app):
    @app.template_filter("stand_img")
    def stand_img(stand_id):
        cfg = current_app.config
        return cfg["IMAGE_BASE_URL"] + cfg["IMAGE_PATH"].format(id=stand_id)

    @app.template_filter("asset")
    def asset(path):
        return current_app.config["IMAGE_BASE_URL"] + "/" + path.lstrip("/")

    @app.template_filter("banner_stands")
    def banner_stands(banner):
        order = ["LR", "UR", "SSR", "SR", "R"]
        chars = [CHARACTER_FILE[i - 1] for i in banner["cards"]]
        return sorted(chars, key=lambda c: order.index(c["rarity"]))

    @app.template_filter("rarity")
    def rarity(r):
        return RARITY.get(r, "common")

    @app.template_filter("traits")
    def traits(char):
        """[(emoji, type, quality, rank letter)] for a character or its dict."""
        types = getattr(char, "types", None) or []
        quals = getattr(char, "qualities", None) or []
        out = []
        for t, q in zip(types, quals):
            try:
                T, Q = Types.from_string(t), Qualities.from_string(q)
                out.append((T.emoji, t.title(), q.replace("_", " ").title(), Q.rank, Q.emoji))
            except ValueError:
                pass
        return out

    @app.template_filter("copies")
    def copies(c, u):
        """Other copies of the same stand sitting in storage (fuse candidates)."""
        out = []
        for o in u.storage_characters:
            if o.id == c.id and o.uuid != c.uuid:
                out.append(o)
        return out

    @app.template_filter("rank")
    def rank_f(elo):
        return rank_name(int(elo or 0))

    @app.template_filter("roman")
    def roman_f(n):
        return roman(int(n))

    @app.template_filter("num")
    def num(n):
        return f"{int(n):,}".replace(",", "\u202f")

    @app.template_filter("stat")
    def stat(n):
        n = int(n)
        if n >= 1_000_000:
            return f"{n / 1_000_000:.1f}M"
        if n >= 10_000:
            return f"{n // 1000}k"
        return str(n)

    @app.template_filter("delta")
    def delta(td):
        return fmt_delta(td)

    @app.template_filter("unique_equipable")
    def unique_equipable(items):
        seen, out = set(), []
        for it in items:
            if it.is_equipable and it.id not in seen:
                seen.add(it.id)
                out.append(it)
        return out

    @app.context_processor
    def inject():
        if "csrf" not in session:
            session["csrf"] = secrets.token_urlsafe(24)
        return {
            "me": {"id": session.get("uid"), "name": session.get("name"), "avatar": session.get("avatar")},
            "csrf_token": session["csrf"],
            "STAND_COUNT": len(PLAYABLE),
        }

    @app.before_request
    def csrf_protect():
        if request.method == "POST" and not request.path.startswith("/auth/callback"):
            sent = request.headers.get("X-CSRF-Token") or request.form.get("csrf")
            if not sent or not secrets.compare_digest(sent, session.get("csrf", "")):
                abort(400, "Invalid form token. Reload the page.")
