"""News feed: posts written by admins, each with an optional cover image.

Redis (web-only keys):
    web:news:posts        HASH id -> JSON {id, title, body, cover, author, created, updated}
    web:news:order        ZSET id -> created timestamp (newest first)
    web:news:cover:<id>   uploaded cover bytes; web:news:cover_type:<id> its MIME type
A cover is either an uploaded image (served from /news/cover/<id>) or an https link.
"""
import datetime
import json
import re
import secrets
from typing import List, Optional

from markupsafe import Markup, escape

from app.db import r

POSTS, ORDER = "web:news:posts", "web:news:order"
MAX_COVER_BYTES = 3 * 1024 * 1024
# Magic bytes of the formats we accept, so a renamed file can't pass as an image.
IMAGE_SIGNATURES = {
    b"\x89PNG\r\n\x1a\n": "image/png",
    b"\xff\xd8\xff": "image/jpeg",
    b"GIF87a": "image/gif",
    b"GIF89a": "image/gif",
}
URL_RE = re.compile(r"^https://[^\s\"'<>]{4,500}$")


class NewsError(Exception):
    pass


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="minutes")


def image_type(data: bytes) -> Optional[str]:
    for sig, mime in IMAGE_SIGNATURES.items():
        if data.startswith(sig):
            return mime
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def get_post(post_id: str) -> Optional[dict]:
    raw = r().hget(POSTS, post_id)
    return json.loads(raw) if raw else None


def list_posts(limit: int = 20, offset: int = 0) -> List[dict]:
    ids = r().zrevrange(ORDER, offset, offset + limit - 1)
    posts = []
    for raw_id in ids:
        post = get_post(raw_id.decode() if isinstance(raw_id, bytes) else raw_id)
        if post:
            posts.append(post)
    return posts


def latest_id() -> Optional[str]:
    ids = r().zrevrange(ORDER, 0, 0)
    return (ids[0].decode() if isinstance(ids[0], bytes) else ids[0]) if ids else None


def save_post(author: str, title: str, body: str, cover_url: str = "", upload: Optional[bytes] = None,
              post_id: Optional[str] = None, remove_cover: bool = False) -> dict:
    """Create (post_id None) or edit a post. An upload wins over a link."""
    title, body, cover_url = (title or "").strip(), (body or "").strip(), (cover_url or "").strip()
    if not 3 <= len(title) <= 120:
        raise NewsError("The title needs 3 to 120 characters.")
    if not 1 <= len(body) <= 10_000:
        raise NewsError("Write something in the post (up to 10,000 characters).")
    if cover_url and not URL_RE.match(cover_url):
        raise NewsError("The cover link must be an https:// address.")
    mime = None
    if upload:
        if len(upload) > MAX_COVER_BYTES:
            raise NewsError("The cover image must be 3 MB or smaller.")
        mime = image_type(upload)
        if not mime:
            raise NewsError("The cover must be a PNG, JPEG, GIF or WebP image.")

    post = get_post(post_id) if post_id else None
    if post_id and not post:
        raise NewsError("That post no longer exists.")
    if post is None:
        post = {"id": secrets.token_hex(6), "created": _now(), "author": author, "cover": ""}
    post.update(title=title, body=body, updated=_now())
    if upload:
        r().set(f"web:news:cover:{post['id']}", upload)
        r().set(f"web:news:cover_type:{post['id']}", mime)
        post["cover"] = f"/news/cover/{post['id']}"
    elif cover_url:
        r().delete(f"web:news:cover:{post['id']}", f"web:news:cover_type:{post['id']}")
        post["cover"] = cover_url
    elif remove_cover:
        r().delete(f"web:news:cover:{post['id']}", f"web:news:cover_type:{post['id']}")
        post["cover"] = ""
    r().hset(POSTS, post["id"], json.dumps(post))
    if not r().zscore(ORDER, post["id"]):
        r().zadd(ORDER, {post["id"]: datetime.datetime.now(datetime.timezone.utc).timestamp()})
    return post


def delete_post(post_id: str):
    r().hdel(POSTS, post_id)
    r().zrem(ORDER, post_id)
    r().delete(f"web:news:cover:{post_id}", f"web:news:cover_type:{post_id}")


def cover(post_id: str):
    data = r().get(f"web:news:cover:{post_id}")
    mime = r().get(f"web:news:cover_type:{post_id}")
    return (data, mime.decode() if isinstance(mime, bytes) else mime) if data and mime else (None, None)


_BOLD = re.compile(r"\*\*(.+?)\*\*")
_LINK = re.compile(r"\[([^\]]{1,200})\]\((https://[^\s)]{4,500})\)")


def render_body(text: str) -> Markup:
    """Plain text with blank-line paragraphs, **bold** and [label](https://link). Everything else is escaped."""
    out = []
    for para in re.split(r"\n\s*\n", text.strip()):
        html = str(escape(para))
        html = _BOLD.sub(r"<strong>\1</strong>", html)
        html = _LINK.sub(r'<a href="\2" target="_blank" rel="noopener">\1</a>', html)
        out.append("<p>" + html.replace("\n", "<br>") + "</p>")
    return Markup("".join(out))


def summary(text: str, length: int = 180) -> str:
    plain = _LINK.sub(r"\1", _BOLD.sub(r"\1", text)).replace("\n", " ")
    return plain if len(plain) <= length else plain[:length].rsplit(" ", 1)[0] + "…"
