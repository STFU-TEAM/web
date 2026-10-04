"""Art helper: find artwork for a stand, then save it into the right folder in one click.

    python scripts/art_helper.py          then open http://127.0.0.1:5055

Folders (next to this repo's app/, ignored by git):
    art/artwork/{id}.webp   full-art cards (★3+)        -> upload to the image server as artwork/{id}.webp
    art/shiny/{id}.webp     shiny cards                  -> upload as shiny/{id}.webp
    art/special/{id}.gif    the special's animation      -> upload as special/{id}.gif

Candidates come from the stand's page on the JoJo wiki (jojo.fandom.com); any other image can be saved
by pasting its URL or dropping the file. Still images are converted to WebP (Pillow) and can be cropped
to the card's 7:12 shape. "Update the game's lists" writes app/game/data/fullart.json and shiny.json from
the folders, so cards switch to the new art once the files are on the image server.
"""
import io
import json
import os
import sys
import urllib.parse
import urllib.request

from flask import Flask, abort, flash, redirect, render_template_string, request, url_for

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
DATA = os.path.join(ROOT, "app", "game", "data")
ART = os.path.join(ROOT, "art")
KINDS = {  # folder: (label, extension of still images, game list)
    "artwork": ("Artwork (full art)", ".webp", "fullart.json"),
    "shiny": ("Shiny", ".webp", "shiny.json"),
    "special": ("Special (animation)", ".gif", None),
}
WIKI = "https://jojo.fandom.com/api.php"
UA = {"User-Agent": "STFU-Requiem-art-helper/1.0 (fan game asset tool)"}
MAX_BYTES = 40 * 1024 * 1024
CARD_RATIO = 7 / 12
IMAGE_BASE = os.environ.get("IMAGE_BASE_URL", "https://images.stfurequiem.com").rstrip("/")

with open(os.path.join(DATA, "characters.json"), encoding="utf-8") as fh:
    STANDS = [c for c in json.load(fh)["characters"] if c.get("universe") != "Dummy"]
BY_ID = {c["id"]: c for c in STANDS}

try:
    from PIL import Image, ImageSequence  # noqa: F401
except ImportError:  # still works: files are saved as downloaded
    Image = None

app = Flask(__name__)
app.secret_key = "art-helper-local-only"


# ── files ───────────────────────────────────────────────────────────────────

def folder(kind: str) -> str:
    path = os.path.join(ART, kind)
    os.makedirs(path, exist_ok=True)
    return path


def existing(kind: str, stand_id: int):
    for name in os.listdir(folder(kind)):
        if os.path.splitext(name)[0] == str(stand_id):
            return name
    return None


def coverage():
    return {kind: {int(os.path.splitext(n)[0]) for n in os.listdir(folder(kind)) if os.path.splitext(n)[0].isdigit()}
            for kind in KINDS}


def _curl(url: str, referer: str) -> bytes:
    """Cloudflare turns Python's own HTTP client away from the wiki's images; curl (built into Windows 10+) gets in."""
    import subprocess
    out = subprocess.run(["curl", "-sSfL", "--max-time", "60", "--max-filesize", str(MAX_BYTES),
                          "-A", "Mozilla/5.0", "-e", referer, url], capture_output=True)
    if out.returncode != 0:
        raise ValueError(out.stderr.decode(errors="replace").strip() or f"curl failed ({out.returncode})")
    return out.stdout


def fetch(url: str) -> bytes:
    headers = dict(UA)
    if "static.wikia.nocookie.net" in url:
        # the wiki's image host only answers requests that come from the wiki, and serves WebP copies
        # unless asked for the original (which keeps GIFs animated)
        if "format=original" not in url and "/scale-to-width" not in url:
            url += ("&" if "?" in url else "?") + "format=original"
        return _curl(url, "https://jojo.fandom.com/")
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = resp.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise ValueError("That file is larger than 40 MB.")
    return data


def save(kind: str, stand_id: int, data: bytes, crop: bool) -> str:
    """Write the image into art/<kind>/<id>.<ext>; returns the file name."""
    out_dir = folder(kind)
    old = existing(kind, stand_id)
    if old:
        os.remove(os.path.join(out_dir, old))
    if Image is None:
        ext = ".gif" if data[:3] == b"GIF" else ".webp" if data[8:12] == b"WEBP" else ".png" if data[:4] == b"\x89PNG" else ".jpg"
        name = f"{stand_id}{ext}"
        open(os.path.join(out_dir, name), "wb").write(data)
        return name
    img = Image.open(io.BytesIO(data))
    animated = getattr(img, "is_animated", False)
    if kind == "special" or animated:
        if animated or img.format == "GIF":  # keep animations as they are
            name = f"{stand_id}.gif" if img.format == "GIF" else f"{stand_id}.webp"
            open(os.path.join(out_dir, name), "wb").write(data)
            return name
    img = img.convert("RGBA" if img.mode in ("RGBA", "LA", "P") else "RGB")
    if crop:  # the card's 7:12 shape, keeping the top (faces) in frame
        w, h = img.size
        if w / h > CARD_RATIO:
            nw = int(h * CARD_RATIO)
            left = (w - nw) // 2
            img = img.crop((left, 0, left + nw, h))
        else:
            img = img.crop((0, 0, w, int(w / CARD_RATIO)))
    if img.height > 1600:
        img = img.resize((int(img.width * 1600 / img.height), 1600), Image.LANCZOS)
    name = f"{stand_id}.webp"
    img.save(os.path.join(out_dir, name), "WEBP", quality=88, method=6)
    return name


# ── the JoJo wiki ───────────────────────────────────────────────────────────

def wiki(**params):
    params.update(format="json")
    return json.loads(fetch(WIKI + "?" + urllib.parse.urlencode(params)).decode("utf-8"))


def wiki_page(name: str):
    """The wiki page that best matches a stand name (titles are case sensitive, so search first)."""
    hits = wiki(action="query", list="search", srsearch=name, srlimit=5).get("query", {}).get("search", [])
    return hits[0]["title"] if hits else None


def candidates(query: str, page: str = None, limit: int = 60):
    """Images on the stand's wiki page (or a free file search), biggest first, with thumbnails."""
    if page:
        params = dict(action="query", generator="images", titles=page, gimlimit=limit)
    else:
        params = dict(action="query", generator="search", gsrsearch=query, gsrnamespace=6, gsrlimit=limit)
    params.update(prop="imageinfo", iiprop="url|size|mime", iiurlwidth=320)
    pages = wiki(**params).get("query", {}).get("pages", {}).values()
    out = []
    for p in pages:
        info = (p.get("imageinfo") or [{}])[0]
        mime = info.get("mime", "")
        if not mime.startswith("image/") or mime == "image/svg+xml" or info.get("width", 0) < 250:
            continue
        out.append({"title": p["title"].replace("File:", ""), "url": info["url"], "thumb": info.get("thumburl", info["url"]),
                    "w": info.get("width", 0), "h": info.get("height", 0), "gif": mime == "image/gif",
                    "tall": info.get("height", 0) >= info.get("width", 1)})
    return sorted(out, key=lambda c: (not c["gif"] if query.endswith(" gif") else 0, -(c["w"] * c["h"])))


# ── pages ───────────────────────────────────────────────────────────────────

BASE = """<!doctype html><html lang=en><head><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">
<title>Art helper</title><style>
:root{color-scheme:dark;--bg:#1C0F2E;--card:#2A1745;--line:#3D2263;--text:#EDE6F7;--muted:#B3A3CF;--gold:#F4C542;--pink:#D6246E;--teal:#2BB3A8}
*{box-sizing:border-box}body{margin:0;font:15px/1.5 system-ui,sans-serif;background:var(--bg);color:var(--text)}
a{color:var(--gold)}main{max-width:1200px;margin:0 auto;padding:1.2rem}h1{margin:.2rem 0 1rem}
input,select,button{font:inherit;color:var(--text);background:var(--card);border:1px solid var(--line);border-radius:8px;padding:.45rem .7rem}
button,.btn{cursor:pointer;background:var(--gold);color:#1C0F2E;border:0;font-weight:700;text-decoration:none;border-radius:8px;padding:.45rem .8rem;display:inline-block}
.ghost{background:var(--card);color:var(--text);border:1px solid var(--line)}.muted{color:var(--muted)}
.flash{padding:.6rem .9rem;border-radius:8px;background:var(--card);border-left:4px solid var(--teal);margin:.5rem 0}.flash.error{border-color:var(--pink)}
table{width:100%;border-collapse:collapse}td,th{padding:.4rem .5rem;border-bottom:1px solid var(--line);text-align:left}
.ok{color:var(--teal);font-weight:700}.no{color:var(--muted)}.row{display:flex;gap:.5rem;flex-wrap:wrap;align-items:center}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(210px,1fr));gap:.8rem}
.cand{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:.5rem;display:grid;gap:.4rem}
.cand img{width:100%;height:240px;object-fit:contain;background:#120821;border-radius:6px}
.cand small{color:var(--muted);word-break:break-all}.cand form{display:flex;gap:.3rem;flex-wrap:wrap}
.cand button{padding:.3rem .5rem;font-size:.82rem}.current{display:flex;gap:.8rem;flex-wrap:wrap}
.current figure{margin:0;background:var(--card);border:1px solid var(--line);border-radius:10px;padding:.5rem;width:200px}
.current img{width:100%;height:220px;object-fit:contain;background:#120821;border-radius:6px}
.drop{border:2px dashed var(--line);border-radius:10px;padding:1rem;text-align:center}.drop.over{border-color:var(--gold)}
</style></head><body><main>
{% with msgs = get_flashed_messages(with_categories=true) %}{% for cat, m in msgs %}<p class="flash {{ cat }}">{{ m }}</p>{% endfor %}{% endwith %}
{{ body|safe }}</main></body></html>"""

INDEX = """<h1>🎨 Art helper</h1>
<p class="muted">Pick a stand to find art for it. Files land in <code>{{ art }}</code>: <b>artwork</b> (full art), <b>shiny</b>, <b>special</b>.</p>
<div class="row">
  <form method="get" class="row"><input name="q" value="{{ q }}" placeholder="Name, id or rarity" autofocus>
    <select name="missing"><option value="">All stands</option>{% for k, (label, _e, _l) in kinds.items() %}<option value="{{ k }}" {{ 'selected' if missing == k }}>Missing {{ label|lower }}</option>{% endfor %}</select>
    <button>Search</button></form>
  <form method="post" action="{{ url_for('sync') }}"><button class="ghost" title="Write fullart.json and shiny.json from the folders">⟳ Update the game's lists</button></form>
</div>
<p class="muted">{% for k in kinds %}{{ k }}: <b>{{ cov[k]|length }}</b>/{{ total }}{{ ' · ' if not loop.last }}{% endfor %}</p>
<table><thead><tr><th>#</th><th>Stand</th><th>Rarity</th>{% for k in kinds %}<th>{{ k }}</th>{% endfor %}<th></th></tr></thead><tbody>
{% for s in rows %}<tr><td>{{ s.id }}</td><td>{{ s.name }}</td><td>{{ s.rarity }}</td>
  {% for k in kinds %}<td>{% if s.id in cov[k] %}<span class="ok">✓</span>{% else %}<span class="no">–</span>{% endif %}</td>{% endfor %}
  <td><a class="btn" href="{{ url_for('stand', stand_id=s.id) }}">Find art</a></td></tr>{% endfor %}
</tbody></table>"""

STAND = """<p><a href="{{ url_for('index') }}">← All stands</a></p>
<h1>#{{ s.id }} {{ s.name }} <small class="muted">{{ s.rarity }}</small></h1>
<h3>What you have</h3>
<div class="current">
  <figure><img src="{{ image_base }}/Image/{{ s.id }}.png" alt=""><figcaption class="muted">Current card image (server)</figcaption></figure>
  {% for k, (label, _e, _l) in kinds.items() %}<figure>{% if have[k] %}<img src="{{ url_for('file', kind=k, name=have[k]) }}" alt="">{% else %}<div class="drop muted" style="height:220px;display:grid;place-items:center">no {{ k }} yet</div>{% endif %}
    <figcaption>{{ label }}{% if have[k] %} · <span class="ok">{{ have[k] }}</span>{% endif %}</figcaption></figure>{% endfor %}
</div>

<h3>Search</h3>
<form method="get" class="row"><input name="query" value="{{ query }}" size="40" placeholder="Search the JoJo wiki's files">
  <button>Search the wiki</button>
  <a class="btn ghost" href="{{ url_for('stand', stand_id=s.id) }}">Back to its wiki page</a></form>
<p class="row muted">Elsewhere (opens a tab):
  {% for label, url in links %}<a class="btn ghost" target="_blank" rel="noopener" href="{{ url }}">{{ label }}</a>{% endfor %}</p>

<h3>Save any image</h3>
<form method="post" action="{{ url_for('save_url', stand_id=s.id) }}" class="row">
  <input name="url" size="50" placeholder="Paste an image URL" required>
  {% for k, (label, _e, _l) in kinds.items() %}<button name="kind" value="{{ k }}">→ {{ k }}</button>{% endfor %}
  <label class="muted"><input type="checkbox" name="crop" value="1" checked> crop to the card</label></form>
<form method="post" action="{{ url_for('save_file', stand_id=s.id) }}" enctype="multipart/form-data" class="drop" id="drop">
  <p>Drop an image here, or <input type="file" name="file" accept="image/*" required></p>
  <div class="row" style="justify-content:center">{% for k, (label, _e, _l) in kinds.items() %}<button name="kind" value="{{ k }}">Save as {{ k }}</button>{% endfor %}
  <label class="muted"><input type="checkbox" name="crop" value="1" checked> crop to the card</label></div></form>

<h3>Candidates {% if page %}from the wiki page “{{ page }}”{% else %}for “{{ query }}”{% endif %} <small class="muted">{{ cands|length }}</small></h3>
{% if error %}<p class="flash error">{{ error }}</p>{% endif %}
<div class="grid">{% for c in cands %}
  <div class="cand"><a href="{{ url_for('proxy', u=c.url) }}" target="_blank" rel="noopener"><img src="{{ url_for('proxy', u=c.thumb) }}" alt="" loading="lazy"></a>
    <small>{{ c.title }} · {{ c.w }}×{{ c.h }}{{ ' · GIF' if c.gif }}{{ ' · tall' if c.tall }}</small>
    <form method="post" action="{{ url_for('save_url', stand_id=s.id) }}"><input type="hidden" name="url" value="{{ c.url }}"><input type="hidden" name="crop" value="1">
      {% for k in kinds %}<button name="kind" value="{{ k }}">→ {{ k }}</button>{% endfor %}</form></div>
{% else %}<p class="muted">Nothing found. Try another search, or one of the links above.</p>{% endfor %}</div>
<script>
const drop = document.getElementById("drop"), input = drop.querySelector("input[type=file]");
["dragover", "dragenter"].forEach((t) => drop.addEventListener(t, (e) => { e.preventDefault(); drop.classList.add("over"); }));
["dragleave", "drop"].forEach((t) => drop.addEventListener(t, () => drop.classList.remove("over")));
drop.addEventListener("drop", (e) => { e.preventDefault(); input.files = e.dataTransfer.files; });
</script>"""


def page(template, **ctx):
    return render_template_string(BASE, body=render_template_string(template, kinds=KINDS, **ctx))


@app.get("/")
def index():
    q, missing = request.args.get("q", "").strip().lower(), request.args.get("missing", "")
    cov = coverage()
    rows = [s for s in STANDS if not q or q in s["name"].lower() or q == str(s["id"]) or q == s["rarity"].lower()]
    if missing in KINDS:
        rows = [s for s in rows if s["id"] not in cov[missing]]
    return page(INDEX, rows=rows, q=q, missing=missing, cov=cov, total=len(STANDS), art=ART)


@app.get("/stand/<int:stand_id>")
def stand(stand_id):
    s = BY_ID.get(stand_id) or abort(404)
    query = request.args.get("query", "").strip()
    cands, page_title, error = [], None, None
    try:
        if query:
            cands = candidates(query)
        else:
            page_title = wiki_page(s["name"])
            cands = candidates(s["name"], page=page_title) if page_title else []
    except Exception as exc:  # offline, or the wiki is down
        error = f"The JoJo wiki didn't answer ({exc}). Use the links or paste a URL."
    q = urllib.parse.quote_plus
    links = [("Google Images", f"https://www.google.com/search?tbm=isch&q={q(s['name'] + ' jojo stand')}"),
             ("Danbooru", f"https://danbooru.donmai.us/posts?tags={q(s['name'].lower().replace(' ', '_') + '_(stand)')}"),
             ("Pixiv", f"https://www.pixiv.net/en/tags/{q(s['name'])}/artworks"),
             ("DeviantArt", f"https://www.deviantart.com/search?q={q(s['name'] + ' jojo')}"),
             ("Tenor GIFs", f"https://tenor.com/search/{q(s['name'].lower().replace(' ', '-'))}-gifs")]
    have = {k: existing(k, stand_id) for k in KINDS}
    return page(STAND, s=s, cands=cands, page=page_title, query=query or s["name"], links=links, have=have,
                error=error, image_base=IMAGE_BASE)


@app.post("/stand/<int:stand_id>/url")
def save_url(stand_id):
    kind, url = request.form.get("kind"), request.form.get("url", "").strip()
    if kind not in KINDS or not url.startswith(("http://", "https://")):
        flash("Pick a folder and give an http(s) image URL.", "error")
        return redirect(url_for("stand", stand_id=stand_id))
    try:
        name = save(kind, stand_id, fetch(url), bool(request.form.get("crop")))
        flash(f"Saved art/{kind}/{name}.")
    except Exception as exc:
        flash(f"Couldn't save that image: {exc}", "error")
    return redirect(url_for("stand", stand_id=stand_id))


@app.post("/stand/<int:stand_id>/file")
def save_file(stand_id):
    kind, f = request.form.get("kind"), request.files.get("file")
    if kind not in KINDS or not f:
        flash("Pick a folder and a file.", "error")
        return redirect(url_for("stand", stand_id=stand_id))
    try:
        name = save(kind, stand_id, f.read(MAX_BYTES + 1), bool(request.form.get("crop")))
        flash(f"Saved art/{kind}/{name}.")
    except Exception as exc:
        flash(f"Couldn't save that file: {exc}", "error")
    return redirect(url_for("stand", stand_id=stand_id))


@app.get("/proxy")
def proxy():
    """Wiki images refuse requests from other sites: fetch them here and pass them on."""
    from flask import Response
    url = request.args.get("u", "")
    if not url.startswith("https://static.wikia.nocookie.net/"):
        abort(400)
    data = _curl(url, "https://jojo.fandom.com/")
    kind = ("image/gif" if data[:3] == b"GIF" else "image/png" if data[1:4] == b"PNG"
            else "image/webp" if data[8:12] == b"WEBP" else "image/jpeg")
    return Response(data, mimetype=kind, headers={"Cache-Control": "max-age=86400"})


@app.get("/art/<kind>/<name>")
def file(kind, name):
    from flask import send_from_directory
    if kind not in KINDS:
        abort(404)
    return send_from_directory(folder(kind), name)


@app.post("/sync")
def sync():
    """Write the ids found in art/artwork and art/shiny into the game's lists."""
    cov = coverage()
    done = []
    for kind, (_label, _ext, listname) in KINDS.items():
        if not listname:
            continue
        path = os.path.join(DATA, listname)
        data = json.load(open(path, encoding="utf-8"))
        data["ids"] = sorted(cov[kind])
        open(path, "w", encoding="utf-8").write(json.dumps(data, indent=4, ensure_ascii=False) + "\n")
        done.append(f"{listname}: {len(cov[kind])}")
    flash("Updated " + ", ".join(done) + ". Upload the files to the image server, then restart the site.")
    return redirect(url_for("index"))


if __name__ == "__main__":
    if Image is None:
        print("Pillow isn't installed: images are saved as downloaded (pip install pillow to convert to WebP).")
    print("Art helper on http://127.0.0.1:5055  (files go to", ART + ")")
    app.run(host="127.0.0.1", port=5055, debug=False)
