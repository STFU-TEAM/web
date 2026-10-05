import re
import secrets

from flask import abort, current_app, request, session
from markupsafe import Markup, escape

from app.game.character import CHARACTER_FILE, MAX_LEVEL, STXPTOLEVEL, Qualities, Types
from app.game.logic import ARROW_ODDS, BANNER_ODDS, PITY_LIMIT, PITY_ODDS, fmt_delta, rank_name

RARITY = {"R": "common", "SR": "rare", "SSR": "epic", "UR": "legend", "LR": "mythic"}
RARITY_RANK = {"R": 0, "SR": 1, "SSR": 2, "UR": 3, "LR": 4}
CUSTOM_EMOJI = re.compile(r"&lt;(a?):(\w+):(\d+)&gt;")  # matched after escaping


def power_score(char) -> int:
    """HP counts less (it's scaled x3 in the engine); speed and crit matter a lot per point.
    A special built up by its stat and type adds 40% of its extra power."""
    from app.game.characterabilities import special_power
    raw = (char.start_hp / 3 + char.start_damage * 2 + char.start_armor / 2
           + char.start_speed * 6 + char.start_critical * 3)
    return int(raw * (1 + 0.4 * (special_power(char)["power"] - 1)))


SPECIAL_TOKEN = re.compile(r"`([^`]+)`")
SPECIAL_NUMBER = re.compile(r"^([+-]?)(\d[\d,.]*)(?:-(\d[\d,.]*))?(%?)$")


def _calc_token(char, sp, sign, num, pct, before, after):
    """(value text, formula) for one number of a special description, or None when it doesn't scale."""
    from app.game.characterabilities import ARMOR_BASE, DEBUFF_CAP, HEALING_STATS, SPEED_FLOOR
    p, x = sp["power"], num / 100
    stat = sp["stat"]
    mult = f" × {p:.2f} power" if round(p, 2) != 1 else ""
    sentence = before[before.rfind(".") + 1:].lower()
    if not pct:
        if sign == "+" and after.startswith("crit"):
            return f"+{num * p:.0f} crit", f"{num:g} crit{mult}"
        return None
    if sign == "-" or after.startswith(("slow", "and are slowed")) or " by " in before[-12:]:
        cut = min(DEBUFF_CAP, x * p)
        return f"−{cut * 100:.0f}%", f"{num:g}%{mult} of the enemy's stat, at most {DEBUFF_CAP:.0%}"
    if sign == "+":
        if after.startswith("damage"):
            return f"+{char.start_damage * x * p:.0f} ATK", f"{num:g}% × {char.start_damage:.0f} ATK{mult}"
        if after.startswith("armor"):
            if "for good" in after[:30]:
                return f"+{char.start_armor * x * p:.0f} ARM", f"{num:g}% × {char.start_armor:.0f} ARM{mult}"
            return f"+{ARMOR_BASE * x * p:.0f} ARM", f"{num:g}% × {ARMOR_BASE} base armor{mult}"
        if after.startswith("speed"):
            base = max(char.start_speed, SPEED_FLOOR)
            return f"+{base * x * p:.0f} SPD", f"{num:g}% × {base:.0f} SPD{mult}"
        return f"+{num * p:.0f}%", f"{num:g}% × {p:.2f} power"
    if after.startswith("damage") or (after.startswith(("burn", "poison", "bleed")) and "damage" not in after[:8]):
        return f"{char.start_damage * x * p:,.0f}", f"{num:g}% × {char.start_damage:.0f} ATK{mult}"
    if after.startswith(("of its max health", "of its own max health", "of max health", "of their max health")):
        healing = "heal" in sentence or "regen" in sentence
        hp_mult = mult if not healing or stat in HEALING_STATS else ""
        who = "its" if "their" not in after[:12] else "their"
        if who == "their":
            return (f"{num * p:.0f}%", f"{num:g}%{hp_mult} of their max health") if hp_mult else None
        return f"{char.start_hp * x * (p if hp_mult else 1):,.0f} HP", f"{num:g}% × {char.start_hp:.0f} HP{hp_mult}"
    return f"{num * p:.0f}%", f"{num:g}% × {p:.2f} power"


def special_text(char, owned=True):
    """The special's description with its numbers highlighted. Numbers that scale are marked; on an owned
    stand each one also shows what it's worth for this copy (its stats and special power)."""
    from app.game.characterabilities import special_power
    text = str(getattr(char, "special_description", None) or char.get("special_description", ""))
    sp = special_power(char) if owned else None
    out, last = [], 0
    for m in SPECIAL_TOKEN.finditer(text):
        out.append(escape(text[last:m.start()]))
        token, last = m.group(1), m.end()
        num = SPECIAL_NUMBER.match(token)
        after = text[m.end():].lstrip()
        if not num or after.startswith(("turn", "time", "bullet")):
            out.append(Markup('<b class="sp-fixed">{}</b>').format(token))
            continue
        sign, value, pct = num.group(1), float(num.group(2).replace(",", "")), num.group(4)
        if not owned:
            out.append(Markup('<b class="sp-scales" title="Grows with this stand\'s stats and special power">{}</b>')
                       .format(token))
            continue
        calc = None if num.group(3) else _calc_token(char, sp, sign, value, pct, text[:m.start()], after)
        if calc is None:
            out.append(Markup('<b class="sp-fixed">{}</b>').format(token))
        elif calc[0].replace("−", "-") == token:
            out.append(Markup('<b class="sp-scales" title="{1} = {2}">{0}</b>').format(token, calc[1], calc[0]))
        else:
            out.append(Markup('<b class="sp-scales" title="{1} = {2}">{0}<span class="sp-calc">{2}</span></b>')
                       .format(token, calc[1], calc[0]))
    out.append(escape(text[last:]))
    return Markup("").join(out)
PLAYABLE = [c for c in CHARACTER_FILE if c["universe"] != "Dummy"]
FULLART_STARS = 3  # owned copies at this awakening or more are drawn as full-art cards
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
    from app import branding
    app.jinja_env.globals.update(icon=branding.icon, DUST=branding.DUST, HEAD=branding.HEAD, HEADS=branding.HEADS,
                                 PALM=branding.PALM, PALMS=branding.PALMS)
    from app.game import logic
    app.jinja_env.globals.update(awaken_gate=logic.awaken_gate, shop_heads_left=logic.shop_heads_left,
                                 FULLART_STARS=FULLART_STARS)
    from app.game import status
    app.jinja_env.globals.update(fighter_status=status.view)
    from app.game import events
    app.jinja_env.globals.update(event_rule=events.describe)
    from app.game import characterabilities as abilities
    app.jinja_env.globals.update(special_power=abilities.special_power, scaling_of=abilities.scaling_of,
                                 STAT_INFO=abilities.STAT_INFO, special_text=special_text)
    app.add_template_filter(lambda n: branding.amount(n, "dust"), "dust")
    app.add_template_filter(lambda n: branding.amount(n, "head"), "heads")
    app.add_template_filter(lambda n: branding.amount(n, "palm"), "palms")

    @app.template_filter("stand_img")
    def stand_img(stand_id):
        cfg = current_app.config
        return cfg["IMAGE_BASE_URL"] + cfg["IMAGE_PATH"].format(id=stand_id)

    import json as _json
    import os as _os
    def _files(name):
        """{stand id: file name} from fullart.json / shiny.json / special.json (older lists: ids -> {id}.webp)."""
        path = _os.path.join(_os.path.dirname(__file__), "game", "data", name)
        if not _os.path.exists(path):
            return {}
        with open(path, encoding="utf-8") as fh:
            data = _json.load(fh)
        files = {int(k): v for k, v in (data.get("files") or {}).items()}
        files.update({int(i): f"{i}.webp" for i in data.get("ids", []) if int(i) not in files})
        return files
    art_files = {"artwork": _files("fullart.json"), "shiny": _files("shiny.json"), "special": _files("special.json")}

    def art_url(kind, stand_id):
        name = art_files[kind].get(int(stand_id))
        cfg = current_app.config
        return f"{cfg['IMAGE_BASE_URL']}{cfg['ART_PATH']}/{kind}/{name}" if name else None

    @app.template_global("card_art")
    def card_art(stand_id, full=False, shiny=False):
        """(url, own art?) for a card: a dedicated shiny or full-art illustration if one was uploaded, else the
        regular image (shiny copies then get their colours shifted by CSS)."""
        url = (shiny and art_url("shiny", stand_id)) or (full and art_url("artwork", stand_id))
        return (url, True) if url else (stand_img(stand_id), False)

    @app.template_filter("special_gif")
    def special_gif(stand_id):
        """The special's animation: a custom one from art/special if uploaded, else the original."""
        return art_url("special", stand_id) or asset(f"special/{stand_id}.gif")

    @app.template_filter("asset")
    def asset(path):
        return current_app.config["IMAGE_BASE_URL"] + "/" + path.lstrip("/")

    @app.template_filter("banner_stands")
    def banner_stands(banner):
        order = ["LR", "UR", "SSR", "SR", "R"]
        chars = [CHARACTER_FILE[i - 1] for i in banner["cards"]]
        return sorted(chars, key=lambda c: order.index(c["rarity"]))

    @app.template_filter("news_body")
    def news_body(text):
        from app.news import render_body
        return render_body(text or "")

    @app.template_filter("news_summary")
    def news_summary(text, length=180):
        from app.news import summary
        return summary(text or "", length)

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

    @app.template_filter("stand_tags")
    def stand_tags(stand_id):
        from app.wiki import STAND_TAGS
        return STAND_TAGS.get(int(stand_id), [])

    @app.template_filter("xp_pct")
    def xp_pct(char):
        if getattr(char, "level", 0) >= MAX_LEVEL:
            return 100
        return int(getattr(char, "xp", 0)) % STXPTOLEVEL * 100 // STXPTOLEVEL

    @app.template_filter("emoji")
    def emoji(text):
        """Discord custom emoji codes (<:name:id>) as CDN images; plain emoji pass through."""
        text = str(text or "")
        return Markup(CUSTOM_EMOJI.sub(
            lambda m: f'<img class="emoji" src="https://cdn.discordapp.com/emojis/{m.group(3)}.{"gif" if m.group(1) else "webp"}?size=48" '
                      f'alt="" loading="lazy">', escape(text)))

    @app.template_filter("power")
    def power(char):
        """Rough single number for sorting a collection."""
        return power_score(char)

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

    @app.after_request
    def toast_htmx(resp):
        """Pop-ups (quest complete, friend request...) ride on HTMX responses as an HX-Trigger event."""
        uid = session.get("uid")
        if uid and request.headers.get("HX-Request") and resp.status_code < 400 and "HX-Trigger" not in resp.headers:
            from app import social
            try:
                toasts = social.take_toasts(uid)
            except Exception:
                toasts = []
            if toasts:
                import json
                resp.headers["HX-Trigger"] = json.dumps({"toast": toasts})
        return resp

    @app.context_processor
    def inject():
        if "csrf" not in session:
            session["csrf"] = secrets.token_urlsafe(24)
        uid = session.get("uid")
        story_hot = tour_pending = False
        inbox_count, toasts, duel_waiting = 0, [], False
        if uid and request.endpoint != "static":
            from app.db import r  # the nav highlights the story until it's done; the tour runs once per new save
            from app import social
            from app.routes.community import pending_count
            story_hot = not r().exists(f"web:story_done:{uid}")
            tour_pending = bool(r().exists(f"web:tour:{uid}"))
            inbox_count = pending_count(uid)
            from app.routes.battles import pvp_waiting
            duel_waiting = pvp_waiting(uid)
            if not request.headers.get("HX-Request"):  # HTMX responses get theirs through HX-Trigger
                toasts = social.take_toasts(uid)
        from app.game import events
        return {
            "live_event": events.cached(),
            "story_hot": story_hot, "tour_pending": tour_pending, "inbox_count": inbox_count, "toasts": toasts, "duel_waiting": duel_waiting,
            "me": {"id": session.get("uid"), "name": session.get("name"), "avatar": session.get("avatar")},
            "csrf_token": session["csrf"],
            "STAND_COUNT": len(PLAYABLE),
            "PITY_LIMIT": PITY_LIMIT, "PITY_ODDS": PITY_ODDS, "BANNER_ODDS": BANNER_ODDS, "ARROW_ODDS": ARROW_ODDS,
        }

    @app.before_request
    def csrf_protect():
        if request.method == "POST" and not request.path.startswith("/auth/callback"):
            sent = request.headers.get("X-CSRF-Token") or request.form.get("csrf")
            if not sent or not secrets.compare_digest(sent, session.get("csrf", "")):
                abort(400, "Invalid form token. Reload the page.")
