"""News feed: posts written by admins, each with an optional cover image.

Redis (web-only keys):
    web:news:posts        HASH id -> JSON {id, kind, title, body, cover, author, created, updated}
                          kind: "news", "patch" (patch notes) or "event" (written when an admin schedules one)
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
KINDS = {"news": "News", "patch": "Patch notes", "event": "Event"}
_latest = {"at": 0.0, "post": None}  # the newest post, kept LATEST_SECONDS per worker (every page's ribbon reads it)
LATEST_SECONDS = 60


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


def latest() -> Optional[dict]:
    """The newest post (for the ribbon on every page), cached for a minute."""
    import time
    if time.time() - _latest["at"] > LATEST_SECONDS:
        pid = latest_id()
        _latest.update(at=time.time(), post=get_post(pid) if pid else None)
    return _latest["post"]


def latest_of(kind: str) -> Optional[dict]:
    return next((p for p in list_posts(30) if p.get("kind", "news") == kind), None)


def save_post(author: str, title: str, body: str, cover_url: str = "", upload: Optional[bytes] = None,
              post_id: Optional[str] = None, remove_cover: bool = False, kind: str = "news") -> dict:
    """Create (post_id None) or edit a post. An upload wins over a link."""
    title, body, cover_url = (title or "").strip(), (body or "").strip(), (cover_url or "").strip()
    if not 3 <= len(title) <= 120:
        raise NewsError("The title needs 3 to 120 characters.")
    if not 1 <= len(body) <= 10_000:
        raise NewsError("Write something in the post (up to 10,000 characters).")
    from flask import has_app_context
    bad = broken_links(body) if has_app_context() else []
    if bad:
        raise NewsError(f"No page on the site at {', '.join(dict.fromkeys(bad))}: check the link.")
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
    post.update(title=title, body=body, updated=_now(), kind=kind if kind in KINDS else "news")
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
    _latest["at"] = 0.0
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
# A link goes out (https://...) or to a page of the site (/gauntlet, /stand/12?x=1#top; never //host or /\host).
_TARGET = r"(https://[^\s)]{4,500}|/(?![/\\])[\w\-./?=&;#%~+:]{0,300})"
_LINK = re.compile(r"\[([^\]]{1,200})\]\(" + _TARGET + r"\)")
_BUTTON = re.compile(r"\[\[([^\]]{1,80})\]\]\(" + _TARGET + r"\)")  # [[Play now]](/gauntlet): a button
_ITALIC = re.compile(r"(?<![\w*])[*_](?![\s*_])(.+?)(?<![\s*_])[*_](?![\w*])")
_CODE = re.compile(r"`([^`]{1,200})`")
_HEADING = re.compile(r"^(#{1,4})\s+(.+?)\s*#*$")
_BULLET = re.compile(r"^( *)[-*+]\s+(.*)$")
_NUMBER = re.compile(r"^( *)\d{1,3}[.)]\s+(.*)$")
_RULE = re.compile(r"^\s*([-*_])(\s*\1){2,}\s*$")
_TABLE_SEP = re.compile(r"^\|?\s*:?-+:?\s*(\|\s*:?-+:?\s*)*\|?$")


def _cells(line: str) -> list:
    """A table row's cells: | a | b | -> ['a', 'b']."""
    line = line.strip()
    return [c.strip() for c in line[1 if line.startswith("|") else 0:-1 if line.endswith("|") else None].split("|")]


def _inline(text: str) -> str:
    """One line of Markdown, escaped first so nothing but these tags can come out: `code`, **bold**, *italic*,
    [label](https://link)."""
    html = str(escape(text))
    codes = []

    def keep(m):  # code spans are left exactly as typed
        codes.append(f"<code>{m.group(1)}</code>")
        return f"\x00{len(codes) - 1}\x00"

    def styled(text):
        return _ITALIC.sub(r"<em>\1</em>", _BOLD.sub(r"<strong>\1</strong>", text))

    def link(m, cls=""):  # kept aside too, so an _ in the address can't turn into italics
        href = m.group(2)
        out = ' target="_blank" rel="noopener"' if href.startswith("https://") else ""
        codes.append(f'<a href="{href}"{cls}{out}>{styled(m.group(1))}</a>')
        return f"\x00{len(codes) - 1}\x00"
    html = _CODE.sub(keep, html)
    html = _BUTTON.sub(lambda m: link(m, ' class="btn gold md-btn"'), html)
    html = _LINK.sub(link, html)
    html = styled(html)
    return re.sub("\x00(\\d+)\x00", lambda m: codes[int(m.group(1))], html)


def site_links(text: str) -> List[str]:
    """The site pages a post links to (/gauntlet ...), without their ?query or #anchor."""
    return [re.split(r"[?#]", m.group(2))[0] for m in list(_BUTTON.finditer(text)) + list(_LINK.finditer(text))
            if m.group(2).startswith("/")]


def broken_links(text: str) -> List[str]:
    """The site pages a post links to that no route answers (a typo would make a dead button)."""
    from flask import current_app
    from werkzeug.exceptions import HTTPException
    from werkzeug.routing import RequestRedirect
    urls, bad = current_app.url_map.bind("localhost"), []
    for path in site_links(text):
        try:
            urls.match(path, "GET")
        except RequestRedirect:
            pass  # /page -> /page/: it exists
        except HTTPException:  # no such page, or one you can only POST to (the link would 404 or 405)
            bad.append(path)
    return bad


def render_body(text: str) -> Markup:
    """The post's Markdown, the common part of it: # headings, - and 1. lists (indent two spaces to nest), > quotes,
    --- dividers, | tables | (a header row, then |---|:---:|---:| for the alignment), **bold**, *italic*, `code` and
    [label](https://link). A line break inside a paragraph is kept.
    Raw HTML is never let through: everything is escaped before the tags above are added."""
    out, para, quote, table = [], [], [], []
    lists = []  # open lists, innermost last: (tag, indent)

    def flush_para():
        if para:
            only_buttons = all(_BUTTON.sub("", line).strip() == "" for line in para)  # a row of buttons
            out.append(('<p class="md-buttons">' + " ".join(_inline(line) for line in para) if only_buttons else
                        "<p>" + "<br>".join(_inline(line) for line in para)) + "</p>")
            para.clear()

    def flush_quote():
        if quote:
            out.append("<blockquote>" + "<br>".join(_inline(line) for line in quote) + "</blockquote>")
            quote.clear()

    def flush_table():
        if not table:
            return
        if len(table) >= 2 and _TABLE_SEP.match(table[1].strip()):
            aligns = ["center" if c.startswith(":") and c.endswith(":") else "right" if c.endswith(":") else ""
                      for c in _cells(table[1])]

            def row(line, tag):
                cells = _cells(line)[:len(aligns)]
                cells += [""] * (len(aligns) - len(cells))
                return "<tr>" + "".join(f'<{tag}{f" style=\"text-align: {a}\"" if a else ""}>{_inline(c)}</{tag}>'
                                        for c, a in zip(cells, aligns)) + "</tr>"
            body = "".join(row(line, "td") for line in table[2:])
            out.append('<div class="md-table"><table><thead>' + row(table[0], "th") + "</thead>"
                       + (f"<tbody>{body}</tbody>" if body else "") + "</table></div>")
        else:  # pipes without a separator row: just text
            para.extend(line.strip() for line in table)
            flush_para()
        table.clear()

    def close_lists(to_indent=-1):
        while lists and lists[-1][1] > to_indent:
            out.append(f"</li></{lists.pop()[0]}>")

    for raw in text.replace("\r\n", "\n").split("\n"):
        line = raw.rstrip()
        if line.lstrip().startswith("|"):
            flush_para(), flush_quote(), close_lists()
            table.append(line)
            continue
        flush_table()
        item = _BULLET.match(line) or _NUMBER.match(line)
        if item and not _RULE.match(line):
            flush_para(), flush_quote()
            indent, tag = len(item.group(1)), "ul" if _BULLET.match(line) else "ol"
            if lists and indent > lists[-1][1]:  # a nested list inside the open item
                out.append(f"<{tag}>")
                lists.append((tag, indent))
            else:
                close_lists(indent)
                if lists and lists[-1][1] == indent and lists[-1][0] == tag:
                    out.append("</li>")
                else:
                    close_lists(indent - 1)
                    out.append(f"<{tag}>")
                    lists.append((tag, indent))
            out.append("<li>" + _inline(item.group(2)))
            continue
        if lists and line.startswith(" ") and line.strip():  # a wrapped line of the open item
            out.append("<br>" + _inline(line.strip()))
            continue
        if not line.strip():
            flush_para(), flush_quote()
            continue
        close_lists()
        heading = _HEADING.match(line)
        if _RULE.match(line):
            flush_para(), flush_quote()
            out.append("<hr>")
        elif heading:
            flush_para(), flush_quote()
            level = min(4, len(heading.group(1)) + 1)  # the page title is the h1: # is a section
            out.append(f"<h{level}>{_inline(heading.group(2))}</h{level}>")
        elif line.startswith(">"):
            flush_para()
            quote.append(line[1:].strip())
        else:
            flush_quote()
            para.append(line.strip())
    flush_table(), flush_para(), flush_quote(), close_lists()
    return Markup("".join(out))


def summary(text: str, length: int = 180) -> str:
    """The post as one line of plain text: its Markdown marks taken off."""
    lines = []
    for line in text.replace("\r\n", "\n").split("\n"):
        if _RULE.match(line) or _TABLE_SEP.match(line.strip()):
            continue
        if line.lstrip().startswith("|"):
            line = " · ".join(c for c in _cells(line) if c)
        line = re.sub(r"^\s*(#{1,4}\s+|[-*+]\s+|\d{1,3}[.)]\s+|>\s?)", "", line)
        lines.append(line.strip())
    plain = " ".join(x for x in lines if x)
    plain = _CODE.sub(r"\1", _ITALIC.sub(r"\1", _LINK.sub(r"\1", _BUTTON.sub(r"\1", _BOLD.sub(r"\1", plain)))))
    return plain if len(plain) <= length else plain[:length].rsplit(" ", 1)[0] + "…"
