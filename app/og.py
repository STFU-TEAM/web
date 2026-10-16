"""Link previews: the 1200x630 picture Discord, X, Reddit, WhatsApp and iMessage show under a link to the game.

Each one is drawn here (Pillow) in the game's look: the stand's art in a card frame on the left, the title in Dela
Gothic One with the gold drop shadow, a line of text, a badge and a call to play, over night-purple speed lines with
ゴゴゴ. The fonts (OFL) ship in app/og_fonts so the server draws them the same everywhere.

Pictures are cached in Redis: a shared card never changes; profile, stand and site pictures are redrawn now and then.
    web:og:<key>          the JPEG
    web:og:art:<hash>     a picture fetched from the image server (a day)
"""
import hashlib
import io
import math
import os
from functools import lru_cache
from typing import Callable, Optional

from PIL import Image, ImageDraw, ImageFilter, ImageFont

W, H = 1200, 630
FONTS = os.path.join(os.path.dirname(__file__), "og_fonts")
STATIC = os.path.join(os.path.dirname(__file__), "static")
DISPLAY, BODY = "DelaGothicOne-Regular.ttf", "ZenKakuGothicNew-Bold.ttf"
INK, PAPER, MUTED = (28, 15, 46), (240, 233, 250), (200, 186, 228)
GOLD, MAGENTA, TEAL, VIOLET = (244, 197, 66), (214, 36, 110), (43, 179, 168), (155, 107, 224)
RARITY = {"R": (179, 163, 207), "SR": VIOLET, "SSR": GOLD, "UR": MAGENTA, "LR": TEAL}
MAX_ART_BYTES = 8 * 1024 * 1024
ART_TTL = 86400


@lru_cache(maxsize=None)
def font(name: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(os.path.join(FONTS, name), size)


# ── pieces ──────────────────────────────────────────────────────────────────

def _background(cx: int, cy: int) -> Image.Image:
    """Night purple fading down, a violet glow behind the art, speed lines out of it, halftone in a corner."""
    grad = Image.linear_gradient("L").resize((W, H))
    img = Image.composite(Image.new("RGB", (W, H), (14, 7, 26)), Image.new("RGB", (W, H), (56, 28, 98)), grad)
    glow = Image.new("L", (W, H), 0)
    ImageDraw.Draw(glow).ellipse((cx - 430, cy - 430, cx + 430, cy + 430), fill=170)
    img = Image.composite(Image.new("RGB", (W, H), (122, 63, 184)), img, glow.filter(ImageFilter.GaussianBlur(140)))
    rays = Image.new("L", (W, H), 0)
    d = ImageDraw.Draw(rays)
    for k in range(72):
        a = k * 2 * math.pi / 72
        d.polygon([(cx, cy), (cx + 1800 * math.cos(a), cy + 1800 * math.sin(a)),
                   (cx + 1800 * math.cos(a + 0.02), cy + 1800 * math.sin(a + 0.02))], fill=34)
    img = Image.composite(Image.new("RGB", (W, H), (255, 240, 220)), img, rays)
    dots = Image.new("L", (W, H), 0)
    d = ImageDraw.Draw(dots)
    for y in range(0, H + 18, 18):
        for x in range(0, W + 18, 18):
            r = (x / W + y / H - 1.05) * 7
            if r > 0.5:
                d.ellipse((x - r, y - r, x + r, y + r), fill=46)
    return Image.composite(Image.new("RGB", (W, H), MAGENTA), img, dots)


def _cover(art: Image.Image, w: int, h: int) -> Image.Image:
    """Crop to fill w x h, centred left-right and high up (faces sit near the top of stand art)."""
    art = art.convert("RGBA")
    scale = max(w / art.width, h / art.height)
    art = art.resize((max(w, round(art.width * scale)), max(h, round(art.height * scale))), Image.LANCZOS)
    x, y = (art.width - w) // 2, int((art.height - h) * 0.18)
    return art.crop((x, y, x + w, y + h))


def _rounded(size, radius: int) -> Image.Image:
    mask = Image.new("L", size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, size[0] - 1, size[1] - 1), radius, fill=255)
    return mask


NOTDEF, VS16 = "\U000FFFFF", "\ufe0f"  # a code point no font has; the emoji variation selector


@lru_cache(maxsize=4096)
def _has_glyph(name: str, size: int, ch: str) -> bool:
    """Whether the font draws ch (an emoji it lacks comes out as an empty box: leave it out)."""
    def ink(c):
        im = Image.new("L", (size * 2, size * 2), 0)
        ImageDraw.Draw(im).text((size // 4, size // 4), c, font=font(name, size), fill=255)
        return im.tobytes()
    return ch.isspace() or ink(ch) != ink(NOTDEF)


def _clean(text: str, name: str, size: int) -> str:
    out = "".join(ch for ch in (text or "") if ch != VS16 and _has_glyph(name, size, ch))
    return " ".join(out.split())


def _wrap(draw, text: str, f, width: int, max_lines: int) -> list:
    """Words into lines no wider than width (long words broken by character); the last line ellipsed if cut."""
    words, lines, line = text.split(), [], ""
    for word in words:
        trial = f"{line} {word}".strip()
        if draw.textlength(trial, font=f) <= width:
            line = trial
            continue
        if line:
            lines.append(line)
        line = word
        while draw.textlength(line, font=f) > width and len(line) > 1:  # one word wider than the line
            cut = len(line)
            while cut > 1 and draw.textlength(line[:cut], font=f) > width:
                cut -= 1
            lines.append(line[:cut])
            line = line[cut:]
    if line:
        lines.append(line)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        last = lines[-1]
        while last and draw.textlength(last + "…", font=f) > width:
            last = last[:-1].rstrip()
        lines[-1] = last + "…"
    return lines


def _spaced(draw, xy, text: str, f, fill, spacing: float) -> None:
    x, y = xy
    for ch in text:
        draw.text((x, y), ch, font=f, fill=fill)
        x += draw.textlength(ch, font=f) + spacing


def _pill(img, draw, xy, text: str, f, fill, color=INK, shadow=None, pad=(22, 10)) -> int:
    """A rounded label with an ink outline (and a hard offset shadow, the game's button look). Returns its width."""
    x, y = xy
    l, t, r, b = draw.textbbox((0, 0), text, font=f)
    w, h = r - l + 2 * pad[0], b - t + 2 * pad[1]
    if shadow:
        draw.rounded_rectangle((x + 7, y + 7, x + w + 7, y + h + 7), h // 2, fill=shadow)
    draw.rounded_rectangle((x, y, x + w, y + h), h // 2, fill=fill, outline=INK, width=4)
    draw.text((x + pad[0] - l, y + pad[1] - t), text, font=f, fill=color)
    return w


# ── the picture ─────────────────────────────────────────────────────────────

def draw(title: str, text: str = "", *, kicker: str = "STAND USER", badge: Optional[str] = None,
         rarity: Optional[str] = None, art: Optional[bytes] = None, cta: str = "Play free in your browser →") -> bytes:
    """The preview as a JPEG: art (image bytes) in a frame on the left, the words on the right. kicker: a few words
    above the title (the brand sits in the corner already)."""
    title, text = _clean(title, DISPLAY, 60), _clean(text, BODY, 29)
    kicker, cta, badge = _clean(kicker, BODY, 24), _clean(cta, BODY, 30), _clean(badge or "", BODY, 26)
    fx, fy, fw, fh = 64, 58, 400, 514  # the card frame
    img = _background(fx + fw // 2, fy + fh // 2)
    d = ImageDraw.Draw(img)
    edge = RARITY.get((rarity or "").upper(), GOLD)

    # the card: a hard magenta shadow, the rarity frame, the art in its window
    d.rounded_rectangle((fx + 14, fy + 14, fx + fw + 14, fy + fh + 14), 28, fill=MAGENTA)
    d.rounded_rectangle((fx, fy, fx + fw, fy + fh), 28, fill=edge, outline=INK, width=5)
    inner = (fw - 28, fh - 28)
    window = Image.linear_gradient("L").resize(inner)
    window = Image.composite(Image.new("RGBA", inner, (196, 170, 236, 255)), Image.new("RGBA", inner, (246, 241, 252, 255)), window)
    try:
        picture = Image.open(io.BytesIO(art)) if art else None
        if picture is not None:
            picture.seek(0)  # an animation: its first frame
            window.alpha_composite(_cover(picture, *inner))
    except Exception:
        picture = None
    if picture is None:
        mascot = os.path.join(STATIC, "img", "mascot-face.webp")
        try:
            face = Image.open(mascot).convert("RGBA")
            face.thumbnail((inner[0] - 60, inner[1] - 60))
            window.alpha_composite(face, ((inner[0] - face.width) // 2, (inner[1] - face.height) // 2))
        except OSError:
            pass
    img.paste(window.convert("RGB"), (fx + 14, fy + 14), _rounded(inner, 18))
    d = ImageDraw.Draw(img)
    if badge:
        _pill(img, d, (fx + 28, fy + 28), badge.upper(), font(BODY, 26), edge if rarity else GOLD)

    # ゴゴゴ over the card's lower corner
    menace = Image.new("RGBA", (300, 120), (0, 0, 0, 0))
    ImageDraw.Draw(menace).text((10, 10), "ゴゴゴ", font=font(DISPLAY, 62), fill=(194, 59, 255), stroke_width=7, stroke_fill=INK)
    menace = menace.rotate(9, expand=True, resample=Image.BICUBIC)
    img.paste(menace, (fx + fw - 236, fy + fh - 100), menace)
    d = ImageDraw.Draw(img)

    # the words
    x0, width = 530, W - 530 - 60
    kick = font(BODY, 24)
    kicker = kicker.upper()
    while " " in kicker and d.textlength(kicker, font=kick) + 3.2 * len(kicker) > 300:  # clear of the brand:
        kicker = kicker.rsplit(" ", 1)[0].rstrip(" ·")                                 # whole words only
    _spaced(d, (x0, 62), kicker, kick, GOLD, 3.2)
    size, lines = 68, []
    while size >= 38:
        f = font(DISPLAY, size)
        lines = _wrap(d, title, f, width, 3)
        if len(lines) <= 3 and not lines[-1].endswith("…"):
            break
        size -= 4
    f = font(DISPLAY, size)
    y = 108
    step = int(size * 1.16)
    for line in lines:
        d.text((x0 + 5, y + 6), line, font=f, fill=GOLD, stroke_width=6, stroke_fill=INK)
        d.text((x0, y), line, font=f, fill=PAPER, stroke_width=6, stroke_fill=INK)
        y += step
    if text:
        y += 14
        for line in _wrap(d, text, font(BODY, 29), width, 3 if len(lines) < 3 else 2):
            d.text((x0, y), line, font=font(BODY, 29), fill=MUTED)
            y += 40

    # the call to play, and the brand
    _pill(img, d, (x0, 502), cta, font(BODY, 30), GOLD, shadow=MAGENTA, pad=(26, 14))
    try:
        icon = Image.open(os.path.join(STATIC, "img", "icon-192.png")).convert("RGBA").resize((54, 54), Image.LANCZOS)
        img.paste(icon, (W - 60 - 54, 30), _rounded((54, 54), 14))
    except OSError:
        pass
    brand = font(DISPLAY, 22)
    bw = d.textlength("STFU REQUIEM", font=brand)
    d.text((W - 60 - 54 - 14 - bw, 44), "STFU REQUIEM", font=brand, fill=PAPER, stroke_width=3, stroke_fill=INK)

    out = io.BytesIO()
    img.save(out, "JPEG", quality=86, optimize=True, progressive=True)
    return out.getvalue()


# ── art and cache ───────────────────────────────────────────────────────────

def fetch_art(redis, url: Optional[str]) -> Optional[bytes]:
    """A picture by URL (the image server, or one of the site's own /static files), cached a day. None on failure."""
    if not url:
        return None
    if url.startswith("/static/"):
        path = os.path.normpath(os.path.join(STATIC, url[len("/static/"):].split("?")[0]))
        if not path.startswith(STATIC) or not os.path.isfile(path):
            return None
        with open(path, "rb") as fh:
            return fh.read()
    if not url.startswith("https://"):
        return None
    key = "web:og:art:" + hashlib.sha1(url.encode()).hexdigest()[:24]
    cached = redis.get(key)
    if cached:
        return cached
    try:
        import requests
        res = requests.get(url, timeout=6, headers={"User-Agent": "STFU-Requiem-previews/1.0"})
        if res.status_code != 200 or not res.headers.get("Content-Type", "").startswith("image/") or len(res.content) > MAX_ART_BYTES:
            return None
        data = res.content
    except Exception:
        return None
    redis.set(key, data, ex=ART_TTL)
    return data


def cached(redis, key: str, ttl: int, make: Callable[[], bytes]) -> bytes:
    """The picture under key, drawn by make() the first time (and again after ttl seconds)."""
    full = f"web:og:{key}"
    data = redis.get(full)
    if data:
        return data
    data = make()
    redis.set(full, data, ex=ttl)
    return data
