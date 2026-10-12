"""Chat emotes and stickers: images and GIFs an admin uploads, stored in Redis (bytes and all), used in any chat as
:name:. Inside a sentence one shows as a small emote; a message that is only one shows big (a sticker).

    web:stickers                hash name -> JSON {name, kind: "emote"|"sticker", mime, size, by, at, v}
    web:sticker:img:<name>      the image bytes

Served by /stickers/<name>?v=<version> with a long cache, so each image is fetched once per browser.
"""
import io
import json
import re
import time
from typing import Dict, Optional

from markupsafe import Markup, escape

META_KEY = "web:stickers"
IMG_KEY = "web:sticker:img:{}"
NAME_RE = re.compile(r"^[a-z0-9_]{2,24}$")
CODE_RE = re.compile(r":([a-z0-9_]{2,24}):")
MAX_BYTES = 600 * 1024
MAX_COUNT = 300
KINDS = ("emote", "sticker")
FORMATS = {"PNG": "image/png", "GIF": "image/gif", "WEBP": "image/webp", "JPEG": "image/jpeg"}
CACHE_SECONDS = 20
_cache = {"at": 0.0, "db": None, "rows": None}


class StickerError(ValueError):
    pass


def all_stickers(redis) -> Dict[str, dict]:
    """name -> meta, cached a few seconds per worker (every chat message render reads it)."""
    if _cache["rows"] is not None and _cache["db"] is redis and time.time() - _cache["at"] < CACHE_SECONDS:
        return _cache["rows"]
    rows = {}
    for name, raw in (redis.hgetall(META_KEY) or {}).items():
        try:
            meta = json.loads(raw)
        except (TypeError, ValueError):
            continue
        rows[name.decode() if isinstance(name, bytes) else name] = meta
    _cache.update(at=time.time(), db=redis, rows=rows)
    return rows


def _forget():
    _cache["rows"] = None


def add(redis, name: str, kind: str, data: bytes, by: str) -> dict:
    name = (name or "").strip().lower().strip(":")
    if not NAME_RE.match(name):
        raise StickerError("Names are 2-24 lowercase letters, digits or _ (used in chat as :name:).")
    if kind not in KINDS:
        raise StickerError("Pick emote or sticker.")
    if not data:
        raise StickerError("Choose an image or GIF to upload.")
    if len(data) > MAX_BYTES:
        raise StickerError(f"That file is {len(data) // 1024} KB: the limit is {MAX_BYTES // 1024} KB.")
    if len(all_stickers(redis)) >= MAX_COUNT and not redis.hexists(META_KEY, name):
        raise StickerError(f"There are already {MAX_COUNT} stickers: delete some first.")
    try:  # only real images go in, whatever the file claims to be
        from PIL import Image
        with Image.open(io.BytesIO(data)) as img:
            fmt = img.format
            img.verify()
    except Exception:
        raise StickerError("That file isn't an image Pillow can read.")
    if fmt not in FORMATS:
        raise StickerError("Use a PNG, GIF, WEBP or JPEG.")
    meta = {"name": name, "kind": kind, "mime": FORMATS[fmt], "size": len(data), "by": str(by),
            "at": int(time.time()), "v": int(time.time())}
    pipe = redis.pipeline()
    pipe.set(IMG_KEY.format(name), data)
    pipe.hset(META_KEY, name, json.dumps(meta))
    pipe.execute()
    _forget()
    return meta


def delete(redis, name: str) -> bool:
    gone = bool(redis.hdel(META_KEY, name))
    redis.delete(IMG_KEY.format(name))
    _forget()
    return gone


def image(redis, name: str) -> Optional[tuple]:
    """(bytes, mime) of a sticker, or None."""
    meta = all_stickers(redis).get(name)
    if not meta:
        return None
    data = redis.get(IMG_KEY.format(name))
    return (data, meta["mime"]) if data else None


def url(meta: dict) -> str:
    from flask import url_for
    return url_for("chat.sticker", name=meta["name"], v=meta.get("v", 0))


def render(text: str, stickers: Dict[str, dict]) -> Markup:
    """A chat message as HTML: escaped, with every known :name: drawn as its image (big when it's the whole message)."""
    text = text or ""
    alone = CODE_RE.fullmatch(text.strip())
    if alone and alone.group(1) in stickers:
        meta = stickers[alone.group(1)]
        return Markup(f'<img class="chat-sticker" src="{escape(url(meta))}" alt=":{escape(meta["name"])}:" '
                      f'title=":{escape(meta["name"])}:" loading="lazy">')
    out, last = [], 0
    for m in CODE_RE.finditer(text):
        meta = stickers.get(m.group(1))
        if not meta:
            continue
        out.append(escape(text[last:m.start()]))
        out.append(Markup(f'<img class="chat-emote" src="{escape(url(meta))}" alt=":{escape(meta["name"])}:" '
                          f'title=":{escape(meta["name"])}:" loading="lazy">'))
        last = m.end()
    out.append(escape(text[last:]))
    return Markup("").join(out)
