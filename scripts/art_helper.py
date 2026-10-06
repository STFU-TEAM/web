"""Art helper: find artwork for a stand, then save it into the right folder in one click.

    python scripts/art_helper.py          then open http://127.0.0.1:5055

Folders (next to this repo's app/, ignored by git); upload their contents to the image server root:
    art/artwork/{id}.webp   full-art cards (★3+)        -> https://images.stfurequiem.com/artwork/{id}.webp
    art/shiny/{id}.webp     shiny cards                  -> .../shiny/{id}.webp
    art/special/{id}.gif    the special's animation      -> .../special/{id}.gif (replaces the original)

Candidates come from the stand's page on the JoJo wiki (jojo.fandom.com); any other image can be saved
by pasting its URL or dropping the file. Still images are converted to WebP (Pillow) and can be cropped
to the card's 7:12 shape. "Update the game's lists" writes app/game/data/fullart.json, shiny.json and
special.json (each file's exact name) and tells you which files aren't on the image server yet.
A card preview draws the stand with the game's own stylesheet: classic, full art (★3), shiny and both,
from the saved files, a wiki candidate or a dropped file before it is saved.
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
    "special": ("Special (animation)", ".gif", "special.json"),
}
ART_PATH = os.environ.get("ART_PATH", "").rstrip("/")  # artwork/, shiny/, special/ at the image server root
WIKI = "https://jojo.fandom.com/api.php"
UA = {"User-Agent": "STFU-Requiem-art-helper/1.0 (fan game asset tool)"}
MAX_BYTES = 40 * 1024 * 1024
CARD_RATIO = 7 / 12
IMAGE_BASE = os.environ.get("IMAGE_BASE_URL", "https://images.stfurequiem.com").rstrip("/")

with open(os.path.join(DATA, "characters.json"), encoding="utf-8") as fh:
    STANDS = [c for c in json.load(fh)["characters"] if c.get("universe") != "Dummy"]
BY_ID = {c["id"]: c for c in STANDS}
RARITY = {"R": "common", "SR": "rare", "SSR": "epic", "UR": "legend", "LR": "mythic"}  # as app/filters.py
APP_CSS = os.path.join(ROOT, "app", "static", "css")

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
.preview{width:100%;min-height:460px;border:1px solid var(--line);border-radius:10px;background:#1C0F2E}
.cropper{display:flex;gap:1.2rem;flex-wrap:wrap;align-items:flex-start;background:var(--card);border:1px solid var(--line);border-radius:10px;padding:1rem}
.cropper[hidden]{display:none}.crop-tools{flex:1;min-width:280px;display:grid;gap:.6rem;align-content:start}
.crop-tools input[type=range]{width:220px;vertical-align:middle}
.crop-stage{padding:10px;border-radius:14px;background:repeating-conic-gradient(#2a2238 0 25%,#1b1527 0 50%) 0 0/16px 16px}
.crop-frame{--bg:transparent;position:relative;width:280px;height:480px;overflow:hidden;border-radius:10px;outline:2px solid var(--gold);
  background:var(--bg);cursor:grab;touch-action:none;user-select:none}
.crop-frame:active{cursor:grabbing}.crop-frame:focus-visible{outline-color:var(--teal)}
.crop-frame.blur-bg::before{content:"";position:absolute;inset:-20px;background:var(--bg-img) center/cover;filter:blur(14px) brightness(.6)}
.crop-frame img{position:absolute;left:0;top:0;max-width:none;transform-origin:center;pointer-events:none}
.crop-guide{position:absolute;inset:0;pointer-events:none;
  background:linear-gradient(to bottom,rgb(12 6 22/.55) 0%,transparent 15%,transparent 52%,rgb(12 6 22/.82) 76%,rgb(12 6 22/.95) 100%)}
.crop-guide i{position:absolute;left:6%;right:6%;border:1px dashed rgb(255 255 255/.55);border-radius:4px}
.crop-guide .g-top{top:2%;height:8%}.crop-guide .g-name{top:70%;height:11%}.crop-guide .g-stats{top:84%;height:13%}
.crop-thirds{position:absolute;inset:0;pointer-events:none;opacity:.35;
  background:linear-gradient(to right,transparent calc(33.33% - .5px),#fff 0 calc(33.33% + .5px),transparent 0 calc(66.66% - .5px),#fff 0 calc(66.66% + .5px),transparent 0),
             linear-gradient(to bottom,transparent calc(33.33% - .5px),#fff 0 calc(33.33% + .5px),transparent 0 calc(66.66% - .5px),#fff 0 calc(66.66% + .5px),transparent 0)}
.crop-frame.no-guides .crop-guide,.crop-frame.no-guides .crop-thirds{display:none}
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
  <figure><img src="{{ image_base }}/Image/{{ s.id }}.png" alt=""><figcaption class="muted">Current card image (server)
    <button type="button" class="ghost" data-edit="{{ url_for('proxy', u=image_base ~ '/Image/' ~ s.id ~ '.png') }}" data-label="the server image">✂ Edit</button></figcaption></figure>
  {% for k, (label, _e, _l) in kinds.items() %}<figure>{% if have[k] %}<img src="{{ url_for('file', kind=k, name=have[k]) }}" alt="">{% else %}<div class="drop muted" style="height:220px;display:grid;place-items:center">no {{ k }} yet</div>{% endif %}
    <figcaption>{{ label }}{% if have[k] %} · <span class="ok">{{ have[k] }}</span>
      {% if not have[k].endswith('.gif') %}<button type="button" class="ghost" data-edit="{{ url_for('file', kind=k, name=have[k]) }}" data-label="{{ have[k] }}" data-kind="{{ k }}">✂ Edit</button>{% endif %}{% endif %}</figcaption></figure>{% endfor %}
</div>

<h3 id="crop-title">Crop, resize & center <small class="muted" id="crop-note">pick an image with ✂ Edit, or drop one below</small></h3>
<div class="cropper" id="cropper" hidden>
  <div class="crop-stage">
    <div class="crop-frame" id="crop-frame" tabindex="0" aria-label="Crop area: drag to move, scroll to zoom, arrow keys to nudge">
      <img id="crop-img" alt="" draggable="false">
      <div class="crop-guide" id="crop-guide" aria-hidden="true"><i class="g-top"></i><i class="g-name"></i><i class="g-stats"></i></div>
      <div class="crop-thirds" aria-hidden="true"></div>
    </div>
  </div>
  <div class="crop-tools">
    <label>Zoom <input type="range" id="crop-zoom" min="10" max="400" step="1" value="100"> <output id="crop-zoom-out">100%</output></label>
    <div class="row">
      <button type="button" class="ghost" data-op="fill" title="Cover the whole card, centered">▣ Fill</button>
      <button type="button" class="ghost" data-op="fit" title="Show the whole image, centered">▢ Fit</button>
      <button type="button" class="ghost" data-op="center" title="Center both ways">✛ Center</button>
      <button type="button" class="ghost" data-op="hcenter" title="Center left-right">↔ Center</button>
      <button type="button" class="ghost" data-op="vcenter" title="Center top-bottom">↕ Center</button>
      <button type="button" class="ghost" data-op="top" title="Align the top edge (keeps faces in frame)">⤒ Top</button>
      <button type="button" class="ghost" data-op="bottom" title="Align the bottom edge">⤓ Bottom</button>
      <button type="button" class="ghost" data-op="flip" title="Mirror left-right">⇋ Flip</button>
    </div>
    <label class="muted"><input type="checkbox" id="crop-guides" checked> show where the card's name and stats sit</label>
    <label>Background for empty space <select id="crop-bg"><option value="">transparent</option><option value="#120821">card night</option><option value="#000000">black</option><option value="#ffffff">white</option><option value="blur">blurred image</option></select></label>
    <label>Output height <select id="crop-height"><option>1600</option><option selected>1200</option><option>900</option><option>600</option></select> <span class="muted" id="crop-size"></span></label>
    <p class="muted" id="crop-info"></p>
    <div class="row">{% for k, (label, _e, _l) in kinds.items() if k != 'special' %}<button type="button" data-save="{{ k }}">💾 Save as {{ k }}</button>{% endfor %}
      <button type="button" class="ghost" id="crop-preview">👁 Preview on the card</button>
      <button type="button" class="ghost" id="crop-close">Close</button></div>
    <p class="muted">Drag to move · scroll to zoom around the cursor · arrow keys nudge (Shift ×10) · + / − zoom · C centers.</p>
  </div>
</div>

<h3>Card preview <small class="muted" id="preview-note">saved files</small></h3>
<div class="row"><button type="button" class="ghost" data-preview="">Saved files</button>
  <label class="muted"><input type="checkbox" id="preview-big"> big card (stand page)</label></div>
<iframe id="preview" class="preview" src="{{ url_for('preview', stand_id=s.id) }}" title="Card preview"></iframe>

<h3>Search</h3>
<form method="get" class="row"><input name="query" value="{{ query }}" size="40" placeholder="Search the JoJo wiki's files">
  <button>Search the wiki</button>
  <a class="btn ghost" href="{{ url_for('stand', stand_id=s.id) }}">Back to its wiki page</a></form>
<p class="row muted">Elsewhere (opens a tab):
  {% for label, url in links %}<a class="btn ghost" target="_blank" rel="noopener" href="{{ url }}">{{ label }}</a>{% endfor %}</p>

<h3>Save any image</h3>
<form method="post" action="{{ url_for('save_url', stand_id=s.id) }}" class="row">
  <input name="url" id="paste-url" size="50" placeholder="Paste an image URL" required>
  {% for k, (label, _e, _l) in kinds.items() %}<button name="kind" value="{{ k }}">→ {{ k }}</button>{% endfor %}
  <button type="button" class="ghost" id="paste-edit">✂ Edit</button>
  <label class="muted"><input type="checkbox" name="crop" value="1" checked> crop to the card</label></form>
<form method="post" action="{{ url_for('save_file', stand_id=s.id) }}" enctype="multipart/form-data" class="drop" id="drop">
  <p>Drop an image here, or <input type="file" name="file" accept="image/*" required></p>
  <div class="row" style="justify-content:center">{% for k, (label, _e, _l) in kinds.items() %}<button name="kind" value="{{ k }}">Save as {{ k }}</button>{% endfor %}
  <button type="button" class="ghost" id="drop-edit">✂ Edit</button>
  <label class="muted"><input type="checkbox" name="crop" value="1" checked> crop to the card</label></div></form>

<h3>Candidates {% if page %}from the wiki page “{{ page }}”{% else %}for “{{ query }}”{% endif %} <small class="muted">{{ cands|length }}</small></h3>
{% if error %}<p class="flash error">{{ error }}</p>{% endif %}
<div class="grid">{% for c in cands %}
  <div class="cand"><a href="{{ url_for('proxy', u=c.url) }}" target="_blank" rel="noopener"><img src="{{ url_for('proxy', u=c.thumb) }}" alt="" loading="lazy"></a>
    <small>{{ c.title }} · {{ c.w }}×{{ c.h }}{{ ' · GIF' if c.gif }}{{ ' · tall' if c.tall }}</small>
    <form method="post" action="{{ url_for('save_url', stand_id=s.id) }}"><input type="hidden" name="url" value="{{ c.url }}"><input type="hidden" name="crop" value="1">
      {% for k in kinds %}<button name="kind" value="{{ k }}">→ {{ k }}</button>{% endfor %}
      <button type="button" class="ghost" data-preview="{{ url_for('proxy', u=c.url) }}" data-label="{{ c.title }}">👁 Preview</button>
      {% if not c.gif %}<button type="button" class="ghost" data-edit="{{ url_for('proxy', u=c.url) }}" data-label="{{ c.title }}">✂ Edit</button>{% endif %}</form></div>
{% else %}<p class="muted">Nothing found. Try another search, or one of the links above.</p>{% endfor %}</div>
<script>
const drop = document.getElementById("drop"), input = drop.querySelector("input[type=file]");
["dragover", "dragenter"].forEach((t) => drop.addEventListener(t, (e) => { e.preventDefault(); drop.classList.add("over"); }));
["dragleave", "drop"].forEach((t) => drop.addEventListener(t, () => drop.classList.remove("over")));
drop.addEventListener("drop", (e) => { e.preventDefault(); input.files = e.dataTransfer.files; input.dispatchEvent(new Event("change")); });
// Card preview: saved files, a candidate, or the dropped file (a blob URL the same-origin frame can read).
const frame = document.getElementById("preview"), note = document.getElementById("preview-note"), big = document.getElementById("preview-big");
let current = "", currentLabel = "", blob = null;
function show(src, label) {
  current = src; currentLabel = label;
  const q = new URLSearchParams();
  if (src) q.set("src", src);
  if (big.checked) q.set("big", "1");
  frame.src = "{{ url_for('preview', stand_id=s.id) }}?" + q;
  note.textContent = src ? "with " + label + " as the full art and shiny art" : "saved files";
}
document.addEventListener("click", (e) => {
  const b = e.target.closest("[data-preview]");
  if (b) { show(b.dataset.preview, b.dataset.label || "this image"); frame.scrollIntoView({behavior: "smooth", block: "center"}); }
});
big.addEventListener("change", () => show(current, currentLabel));
input.addEventListener("change", () => {
  if (blob) URL.revokeObjectURL(blob);
  if (input.files[0]) { blob = URL.createObjectURL(input.files[0]); show(blob, input.files[0].name); }
});
frame.addEventListener("load", () => { frame.style.height = frame.contentDocument.body.scrollHeight + 24 + "px"; });

// ── Crop, resize & center ──────────────────────────────────────────────
// The frame is the card's 7:12 shape. State: scale (screen px per image px), the image's top-left
// offset inside the frame (ox, oy) and a mirror flag. Saving sends the visible rectangle in image pixels.
const cropper = document.getElementById("cropper"), cframe = document.getElementById("crop-frame"),
      cimg = document.getElementById("crop-img"), zoom = document.getElementById("crop-zoom"),
      zoomOut = document.getElementById("crop-zoom-out"), info = document.getElementById("crop-info"),
      cnote = document.getElementById("crop-note"), bgSel = document.getElementById("crop-bg"),
      heightSel = document.getElementById("crop-height"), sizeOut = document.getElementById("crop-size");
const C = {src: "", label: "", kind: "artwork", nw: 0, nh: 0, s: 1, ox: 0, oy: 0, flip: false};
const FW = () => cframe.clientWidth, FH = () => cframe.clientHeight;
const cover = () => Math.max(FW() / C.nw, FH() / C.nh), contain = () => Math.min(FW() / C.nw, FH() / C.nh);

function draw() {
  cimg.style.width = C.nw * C.s + "px";
  cimg.style.height = C.nh * C.s + "px";
  cimg.style.transform = `translate(${C.ox}px, ${C.oy}px) scaleX(${C.flip ? -1 : 1})`;
  const pct = Math.round(100 * C.s / cover());
  zoom.value = pct; zoomOut.textContent = pct + "%";
  const r = rect(), H = +heightSel.value;
  sizeOut.textContent = `→ ${Math.round(H * 7 / 12)}×${H} WebP`;
  const up = H / r.h;
  info.textContent = `Source ${C.nw}×${C.nh} · taking ${Math.round(r.w)}×${Math.round(r.h)} from (${Math.round(r.x)}, ${Math.round(r.y)})` +
    (up > 1.05 ? ` · upscaled ×${up.toFixed(1)}: may look soft` : "");
  cframe.style.setProperty("--bg", bgSel.value === "blur" ? "transparent" : (bgSel.value || "transparent"));
  cframe.classList.toggle("blur-bg", bgSel.value === "blur");
  cframe.style.setProperty("--bg-img", `url("${C.src}")`);
}
function rect() {  // the visible area, in source pixels (of the mirrored image when flipped)
  return {x: -C.ox / C.s, y: -C.oy / C.s, w: FW() / C.s, h: FH() / C.s};
}
function zoomAt(s, px = FW() / 2, py = FH() / 2) {  // keep the image point under (px, py) in place
  s = Math.max(contain() * 0.25, Math.min(cover() * 8, s));
  const ix = (px - C.ox) / C.s, iy = (py - C.oy) / C.s;
  C.s = s; C.ox = px - ix * s; C.oy = py - iy * s; draw();
}
const ops = {
  fill() { C.s = cover(); ops.center(); },
  fit() { C.s = contain(); ops.center(); },
  center() { ops.hcenter(); ops.vcenter(); },
  hcenter() { C.ox = (FW() - C.nw * C.s) / 2; },
  vcenter() { C.oy = (FH() - C.nh * C.s) / 2; },
  top() { C.oy = 0; },
  bottom() { C.oy = FH() - C.nh * C.s; },
  flip() { C.flip = !C.flip; },
};
function openCrop(src, label, kind) {
  C.src = src; C.label = label; C.kind = kind || "artwork"; C.flip = false;
  cropper.hidden = false;
  cnote.textContent = "editing " + label;
  cimg.onload = () => { C.nw = cimg.naturalWidth; C.nh = cimg.naturalHeight; C.s = cover(); ops.hcenter(); ops.top(); draw(); };
  cimg.onerror = () => { cnote.textContent = "couldn't load " + label + " (an animated GIF, or the site refused it)"; };
  cimg.src = src;
  document.getElementById("crop-title").scrollIntoView({behavior: "smooth"});
  cframe.focus({preventScroll: true});
}
document.addEventListener("click", (e) => {
  const b = e.target.closest("[data-edit]");
  if (b) openCrop(b.dataset.edit, b.dataset.label || "this image", b.dataset.kind);
  const op = e.target.closest("[data-op]");
  if (op) { ops[op.dataset.op](); draw(); }
});
document.getElementById("paste-edit").addEventListener("click", () => {
  const u = document.getElementById("paste-url").value.trim();
  if (u) openCrop("{{ url_for('proxy') }}?u=" + encodeURIComponent(u), "the pasted image");
});
document.getElementById("drop-edit").addEventListener("click", () => {
  if (input.files[0]) openCrop(blob || URL.createObjectURL(input.files[0]), input.files[0].name);
  else input.click();
});
document.getElementById("crop-close").addEventListener("click", () => { cropper.hidden = true; cnote.textContent = "pick an image with ✂ Edit, or drop one below"; });
zoom.addEventListener("input", () => zoomAt(cover() * zoom.value / 100));
[bgSel, heightSel].forEach((el) => el.addEventListener("change", draw));
document.getElementById("crop-guides").addEventListener("change", (e) => cframe.classList.toggle("no-guides", !e.target.checked));

let dragFrom = null;
cframe.addEventListener("pointerdown", (e) => { dragFrom = {x: e.clientX - C.ox, y: e.clientY - C.oy}; cframe.setPointerCapture(e.pointerId); });
cframe.addEventListener("pointermove", (e) => { if (dragFrom) { C.ox = e.clientX - dragFrom.x; C.oy = e.clientY - dragFrom.y; draw(); } });
["pointerup", "pointercancel"].forEach((t) => cframe.addEventListener(t, () => { dragFrom = null; }));
cframe.addEventListener("wheel", (e) => {
  e.preventDefault();
  const r = cframe.getBoundingClientRect();
  zoomAt(C.s * (e.deltaY < 0 ? 1.08 : 1 / 1.08), e.clientX - r.left, e.clientY - r.top);
}, {passive: false});
cframe.addEventListener("keydown", (e) => {
  const step = e.shiftKey ? 10 : 1, k = e.key;
  if (k === "ArrowLeft") C.ox -= step; else if (k === "ArrowRight") C.ox += step;
  else if (k === "ArrowUp") C.oy -= step; else if (k === "ArrowDown") C.oy += step;
  else if (k === "+" || k === "=") return zoomAt(C.s * 1.05);
  else if (k === "-") return zoomAt(C.s / 1.05);
  else if (k === "c" || k === "C") ops.center();
  else return;
  e.preventDefault(); draw();
});

function render() {  // the same crop drawn in the browser: used when the helper runs without Pillow
  const H = +heightSel.value, W = Math.round(H * 7 / 12), r = rect(), k = H / r.h;
  const cv = document.createElement("canvas"), ctx = cv.getContext("2d");
  cv.width = W; cv.height = H;
  ctx.imageSmoothingQuality = "high";
  if (bgSel.value === "blur") {
    const s = Math.max(W / C.nw, H / C.nh);
    ctx.filter = `blur(${H / 40}px) brightness(.6)`;
    ctx.drawImage(cimg, (W - C.nw * s) / 2, (H - C.nh * s) / 2, C.nw * s, C.nh * s);
    ctx.filter = "none";
  } else if (bgSel.value) {
    ctx.fillStyle = bgSel.value; ctx.fillRect(0, 0, W, H);
  }
  ctx.save();
  ctx.translate(-r.x * k + (C.flip ? C.nw * k : 0), -r.y * k);
  if (C.flip) ctx.scale(-1, 1);
  ctx.drawImage(cimg, 0, 0, C.nw * k, C.nh * k);
  ctx.restore();
  return new Promise((ok) => cv.toBlob(ok, "image/webp", 0.9));
}
async function cropForm(kind) {
  const data = await (await fetch(C.src)).blob();
  const r = rect(), f = new FormData();
  f.append("file", data, "source");
  f.append("rendered", await render(), "rendered");
  f.append("kind", kind);
  for (const [k, v] of Object.entries({x: r.x, y: r.y, w: r.w, h: r.h, flip: C.flip ? 1 : "", bg: bgSel.value, height: heightSel.value})) f.append(k, v);
  return f;
}
document.querySelectorAll("[data-save]").forEach((b) => b.addEventListener("click", async () => {
  b.disabled = true;
  try {
    const res = await fetch("{{ url_for('save_crop', stand_id=s.id) }}", {method: "POST", body: await cropForm(b.dataset.save)});
    if (!res.ok) throw new Error(await res.text());
    location.reload();
  } catch (err) { cnote.textContent = "couldn't save: " + err.message; b.disabled = false; }
}));
if (location.hash === "#edit") document.querySelector("[data-edit]")?.click();  // a link straight into the editor
document.getElementById("crop-preview").addEventListener("click", async () => {
  const res = await fetch("{{ url_for('crop_preview') }}", {method: "POST", body: await cropForm("artwork")});
  if (!res.ok) { cnote.textContent = "couldn't preview: " + await res.text(); return; }
  show(URL.createObjectURL(await res.blob()), "the cropped " + C.label);
  frame.scrollIntoView({behavior: "smooth", block: "center"});
});
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


PREVIEW = """<!doctype html><html lang=en><head><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">
<link href="https://fonts.googleapis.com/css2?family=Dela+Gothic+One&family=Zen+Kaku+Gothic+New:wght@400;500;700&display=swap" rel="stylesheet">
<link rel="stylesheet" href="{{ url_for('app_css') }}">
<style>body{margin:0;padding:12px;min-height:0}.previews{display:flex;flex-wrap:wrap;gap:18px;align-items:flex-start}
.previews figure{margin:0;width:{{ 300 if big else 200 }}px}.previews figcaption{margin-top:.5rem;font-size:.8rem;color:var(--muted);text-align:center}</style>
</head><body><div class="previews">
{% for v in variants %}
<figure>
<article class="card {{ rar }}{{ ' big' if big }}{{ ' fullart' if v.full }}{{ ' shiny' if v.shiny }}">
  <div class="card-face">
    <header class="card-top">
      <span class="rar-badge">{{ s.rarity }}</span>
      {% if v.shiny %}<span class="shiny-badge" title="Shiny">✨</span>{% endif %}
      {% if s.taunt %}<span class="tag">🎯</span>{% endif %}
      {% if v.full %}<span class="stars" aria-label="Awakening 3">{% for _ in range(3) %}<i class="st asc"></i>{% endfor %}</span>{% endif %}
    </header>
    <div class="card-window">
      <img src="{{ v.src }}" alt=""{% if v.own %} class="own-art"{% endif %}
           onload="if(this.naturalWidth / this.naturalHeight > 0.84) this.classList.add('cover')" onerror="this.classList.add('missing')">
      <span class="lvl">Lv 100</span>
      <span class="charge-chip">⟳{{ s.turn_for_ability }}</span>
    </div>
    <div class="xp"><i style="width: 60%"></i></div>
    <h3 class="card-name">{{ s.name }}</h3>
    {% if big %}<p class="card-flavor">{{ (s.special_description or '')|replace('`', '') }}</p>{% endif %}
    <dl class="card-stats five">
      <div><dt>HP</dt><dd>{{ s.base_hp }}</dd></div><div><dt>ATK</dt><dd>{{ s.base_damage }}</dd></div>
      <div><dt>ARM</dt><dd>{{ s.armor }}</dd></div><div><dt>SPD</dt><dd>{{ s.base_speed }}</dd></div>
      <div><dt>CRT</dt><dd>{{ s.base_critical }}</dd></div>
    </dl>
  </div>
</article>
<figcaption>{{ v.label }}</figcaption>
</figure>
{% endfor %}
</div></body></html>"""


@app.get("/stand/<int:stand_id>/preview")
def preview(stand_id):
    """The stand as the game draws it: classic, full art (★3), shiny, shiny full art.
    src: an image to try as the full art and the shiny art (a candidate, or a dropped file's blob URL);
    without it, the files saved in art/ (or the server image when there are none)."""
    s = BY_ID.get(stand_id) or abort(404)
    base = f"{IMAGE_BASE}/Image/{stand_id}.png"
    src = request.args.get("src", "")
    if src and not src.startswith(("/proxy?", "blob:", "/art/")):
        abort(400)

    def art(kind):
        if src:
            return src, True
        name = existing(kind, stand_id)
        return (url_for("file", kind=kind, name=name), True) if name else (base, False)

    full, shiny = art("artwork"), art("shiny")
    shiny_full = shiny if shiny[1] else full  # the game prefers the shiny art, then the full art
    variants = [
        {"label": "Classic (below ★3)", "src": base, "own": False, "full": False, "shiny": False},
        {"label": "Full art (★3)" + ("" if full[1] else " · no artwork yet"), "src": full[0], "own": full[1], "full": True, "shiny": False},
        {"label": "Shiny" + ("" if shiny[1] else " · colours shifted"), "src": shiny[0], "own": shiny[1], "full": False, "shiny": True},
        {"label": "Shiny full art", "src": shiny_full[0], "own": shiny_full[1], "full": True, "shiny": True},
    ]
    return render_template_string(PREVIEW, s=s, rar=RARITY.get(s["rarity"], "common"), variants=variants,
                                  big=bool(request.args.get("big")))


@app.get("/app.css")
def app_css():
    """The game's own stylesheet, so the preview matches the site."""
    from flask import send_from_directory
    return send_from_directory(APP_CSS, "app.css", max_age=0)


def crop_image(data: bytes, form) -> bytes:
    """Cut the crop tool's rectangle (source pixels, may reach past the edges) out of an image and resize it
    to the card's 7:12 shape. Space past the edges is transparent, a colour, or a blurred copy of the image."""
    if Image is None:
        raise ValueError("The crop tool needs Pillow: pip install pillow")
    from PIL import ImageFilter, ImageOps
    img = Image.open(io.BytesIO(data))
    if getattr(img, "is_animated", False):
        raise ValueError("Animated images can't be cropped here.")
    img = img.convert("RGBA")
    if form.get("flip"):
        img = ImageOps.mirror(img)
    x, y, w, h = (float(form[k]) for k in ("x", "y", "w", "h"))
    if w <= 0 or h <= 0:
        raise ValueError("Empty crop.")
    out_h = max(200, min(2400, int(form.get("height") or 1200)))
    size = (round(out_h * CARD_RATIO), out_h)
    box = (round(x), round(y), round(x + w), round(y + h))
    piece = img.crop(box).resize(size, Image.LANCZOS)
    bg = form.get("bg", "")
    if bg == "blur":
        back = ImageOps.fit(img, size, Image.LANCZOS).filter(ImageFilter.GaussianBlur(out_h / 40))
        back = Image.blend(Image.new("RGBA", size, (0, 0, 0, 255)), back, 0.6)
        piece = Image.alpha_composite(back, piece)
    elif bg.startswith("#") and len(bg) == 7:
        piece = Image.alpha_composite(Image.new("RGBA", size, bg), piece)
    buf = io.BytesIO()
    piece.save(buf, "WEBP", quality=90, method=6)
    return buf.getvalue()


def _crop_request() -> bytes:
    """The cropped image: cut by Pillow from the source, or, without Pillow, the browser's own render."""
    if Image is None:
        rendered = request.files.get("rendered")
        if not rendered:
            raise ValueError("No image. Install Pillow (pip install pillow) or use a recent browser.")
        return rendered.read(MAX_BYTES + 1)
    f = request.files.get("file")
    if not f:
        raise ValueError("No image.")
    return crop_image(f.read(MAX_BYTES + 1), request.form)


def _ext(data: bytes) -> str:
    return ".webp" if data[8:12] == b"WEBP" else ".png" if data[1:4] == b"PNG" else ".jpg"


@app.post("/stand/<int:stand_id>/crop")
def save_crop(stand_id):
    from flask import Response
    kind = request.form.get("kind")
    if stand_id not in BY_ID or kind not in KINDS or kind == "special":
        return Response("Pick artwork or shiny.", status=400, mimetype="text/plain")
    try:
        data = _crop_request()
    except Exception as exc:
        return Response(str(exc), status=400, mimetype="text/plain")
    old = existing(kind, stand_id)
    if old:
        os.remove(os.path.join(folder(kind), old))
    name = f"{stand_id}{_ext(data)}"
    open(os.path.join(folder(kind), name), "wb").write(data)
    flash(f"Saved the crop to art/{kind}/{name}.")
    return Response("ok", mimetype="text/plain")


@app.post("/crop-preview")
def crop_preview():
    """The crop as it would be saved, without saving it (for the card preview)."""
    from flask import Response
    try:
        data = _crop_request()
        return Response(data, mimetype="image/" + _ext(data)[1:].replace("jpg", "jpeg"))
    except Exception as exc:
        return Response(str(exc), status=400, mimetype="text/plain")


@app.get("/proxy")
def proxy():
    """Wiki images refuse requests from other sites, and the crop tool can only read same-origin images:
    fetch them here and pass them on."""
    from flask import Response
    url = request.args.get("u", "")
    if not url.startswith(("http://", "https://")):
        abort(400)
    try:
        data = fetch(url)
    except Exception as exc:
        return Response(f"Couldn't fetch that image: {exc}", status=502, mimetype="text/plain")
    kind = ("image/gif" if data[:3] == b"GIF" else "image/png" if data[1:4] == b"PNG"
            else "image/webp" if data[8:12] == b"WEBP" else "image/jpeg")
    return Response(data, mimetype=kind, headers={"Cache-Control": "max-age=86400"})


@app.get("/art/<kind>/<name>")
def file(kind, name):
    from flask import send_from_directory
    if kind not in KINDS:
        abort(404)
    return send_from_directory(folder(kind), name)


def on_server(kind: str, name: str) -> bool:
    try:
        req = urllib.request.Request(f"{IMAGE_BASE}{ART_PATH}/{kind}/{name}", method="HEAD", headers=UA)
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status == 200
    except Exception:
        return False


@app.post("/sync")
def sync():
    """Write each folder's exact file names into the game's lists, checking what's already on the image server.
    If the server has the stand under another name (say 109.webp for a local 109.png), that one is used."""
    from concurrent.futures import ThreadPoolExecutor
    done, missing = [], []
    for kind, (_label, _ext, listname) in KINDS.items():
        local = {}
        for name in sorted(os.listdir(folder(kind))):
            stem = os.path.splitext(name)[0]
            if stem.isdigit():
                local[int(stem)] = name

        def resolve(item):
            sid, name = item
            if on_server(kind, name):
                return sid, name, True
            for ext in (".webp", ".png", ".jpg", ".gif"):
                alt = f"{sid}{ext}"
                if alt != name and on_server(kind, alt):
                    return sid, alt, True
            return sid, name, False

        with ThreadPoolExecutor(12) as pool:
            rows = list(pool.map(resolve, sorted(local.items())))
        path = os.path.join(DATA, listname)
        data = json.load(open(path, encoding="utf-8")) if os.path.exists(path) else {}
        data["_comment"] = (f"Custom {kind} files on the image server at {ART_PATH}/{kind}/<file>. "
                            "Written by scripts/art_helper.py from the art/ folder.")
        data.pop("ids", None)
        data["files"] = {str(sid): name for sid, name, _up in rows}
        open(path, "w", encoding="utf-8").write(json.dumps(data, indent=4, ensure_ascii=False) + "\n")
        done.append(f"{kind} {len(rows)}")
        missing += [f"{kind}/{name}" for _sid, name, up in rows if not up]
    msg = "Updated the game's lists: " + ", ".join(done) + ". Restart the site to use them."
    if missing:
        flash(msg + f" Not on the image server yet ({len(missing)}): " + ", ".join(missing[:12])
              + ("…" if len(missing) > 12 else "") + f". Upload them to {IMAGE_BASE}{ART_PATH}/<folder>/.", "error")
    else:
        flash(msg + " Every file is on the image server.")
    return redirect(url_for("index"))


if __name__ == "__main__":
    if Image is None:
        print("Pillow isn't installed: images are saved as downloaded (pip install pillow to convert to WebP).")
    print("Art helper on http://127.0.0.1:5055  (files go to", ART + ")")
    app.run(host="127.0.0.1", port=5055, debug=False)
