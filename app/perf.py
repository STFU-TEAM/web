"""Transfer speed: gzip for text responses, and long-lived caching for static files.

- Every text response (pages, HTMX fragments, CSS, JS, JSON, SVG) over MIN_SIZE is gzipped when the browser accepts
  it. Pages are mostly repeated card markup, so they shrink about tenfold. Static files are compressed once per
  version and kept in memory.
- url_for('static', ...) adds ?v=<content hash>, and a versioned static request is cached for a year: a new deploy
  changes the hash, so browsers fetch the new file and never ask about the old one again.
"""
import gzip
import hashlib
import os
from functools import lru_cache

from flask import request

MIN_SIZE = 1024
SLOW_SECONDS = 1.5  # a page slower than this is logged (admin Logs tab, WARNING) with how long it took
COMPRESSIBLE = {"text/html", "text/css", "text/javascript", "application/javascript", "application/json",
                "image/svg+xml", "application/manifest+json", "text/plain", "application/xml"}
YEAR = 365 * 24 * 3600
_static_gz = {}  # (path, version) -> gzipped bytes


def install(app):
    static_dir = app.static_folder

    @lru_cache(maxsize=512)
    def hashed(path: str, mtime: float) -> str:
        with open(path, "rb") as fh:
            return hashlib.md5(fh.read()).hexdigest()[:10]

    def version(filename: str) -> str:
        """The file's content hash, recomputed when the file changes (an edit on the dev server, a hot patch)."""
        path = os.path.join(static_dir, filename)
        try:
            return hashed(path, os.stat(path).st_mtime)
        except OSError:
            return ""

    @app.url_defaults
    def static_version(endpoint, values):
        if endpoint == "static" and "filename" in values and "v" not in values:
            v = version(values["filename"])
            if v:
                values["v"] = v

    @app.before_request
    def started():
        from flask import g
        import time
        g._t0 = time.perf_counter()

    @app.after_request
    def slow_log(resp):
        from flask import g
        import time
        t0 = getattr(g, "_t0", None)
        if t0 is not None and request.endpoint != "static":
            took = time.perf_counter() - t0
            if took > SLOW_SECONDS:
                app.logger.warning("slow request: %s %s took %.1fs (status %s)", request.method, request.path, took,
                                   resp.status_code)
        return resp

    @app.after_request
    def speed(resp):
        if request.endpoint == "static" and request.args.get("v") and resp.status_code in (200, 304):
            resp.headers["Cache-Control"] = f"public, max-age={YEAR}, immutable"
        return compress(resp)


def compress(resp):
    if (resp.status_code != 200 or request.method == "HEAD" or "gzip" not in request.headers.get("Accept-Encoding", "")
            or resp.mimetype not in COMPRESSIBLE or "Content-Encoding" in resp.headers or resp.is_streamed and not resp.direct_passthrough):
        return resp
    static = request.endpoint == "static"
    key = (request.path, request.args.get("v") or resp.headers.get("ETag", "")) if static else None
    if key and key in _static_gz:
        body = _static_gz[key]
    else:
        resp.direct_passthrough = False  # a static file is a file wrapper: read it
        data = resp.get_data()
        if len(data) < MIN_SIZE:
            return resp
        body = gzip.compress(data, compresslevel=6 if static else 4)  # pages: nearly the same size, far less CPU
        if key:
            if len(_static_gz) > 200:
                _static_gz.clear()
            _static_gz[key] = body
    resp.direct_passthrough = False
    resp.set_data(body)
    resp.headers["Content-Encoding"] = "gzip"
    resp.headers["Content-Length"] = str(len(body))
    resp.vary.add("Accept-Encoding")
    etag, weak = resp.get_etag()
    if etag and not weak:  # the same ETag for both encodings is only allowed as a weak one
        resp.set_etag(etag, weak=True)
    return resp
