// Only one dropdown open at a time: header menus and "Manage" menus.
document.addEventListener("toggle", (e) => {
  for (const kind of ["details.nav-drop", "details.menu"]) {
    if (e.target.matches(kind) && e.target.open) {
      document.querySelectorAll(`${kind}[open]`).forEach((d) => { if (d !== e.target) d.open = false; });
    }
  }
}, true);

// Header dropdowns close on an outside click or Escape.
const closeNavDrops = (except) => document.querySelectorAll("details.nav-drop[open]").forEach((d) => { if (d !== except) d.open = false; });
document.addEventListener("click", (e) => closeNavDrops(e.target.closest("details.nav-drop")));
document.addEventListener("keydown", (e) => {
  if (e.key !== "Escape") return;
  const open = document.querySelector("details.nav-drop[open]");
  if (open) { open.open = false; open.querySelector("summary").focus(); }
});

// Mobile menu sheet. <dialog> handles Escape and focus; a tap on the backdrop closes it.
document.addEventListener("click", (e) => {
  const sheet = document.getElementById("nav-sheet");
  if (!sheet) return;
  if (e.target.closest("[data-sheet-open]")) sheet.showModal();
  else if (e.target.closest("[data-sheet-close]") || e.target === sheet) sheet.close();
});

// Wiki explorers: category chips plus a stand-name search.
function runExplorer(tools) {
  const list = tools.nextElementSibling;
  const filter = tools.querySelector(".filter-chip[aria-pressed=true]")?.dataset.filter || "";
  const query = tools.querySelector("[data-search]").value.trim().toLocaleLowerCase();
  let visible = 0;
  list.querySelectorAll(".explorer-card").forEach((card) => {
    const show = (!filter || card.dataset.key === filter) && card.dataset.search.includes(query);
    card.hidden = !show;
    visible += Number(show);
    card.querySelectorAll("[data-name]").forEach((el) => el.classList.toggle("is-match", Boolean(query) && el.dataset.name.includes(query)));
  });
  list.querySelector(".explorer-empty").hidden = visible > 0;
}
document.addEventListener("click", (e) => {
  const chip = e.target.closest("[data-explorer] .filter-chip");
  if (!chip) return;
  const tools = chip.closest("[data-explorer]");
  tools.querySelectorAll(".filter-chip").forEach((c) => c.setAttribute("aria-pressed", String(c === chip)));
  history.replaceState(null, "", chip.dataset.filter ? `#${chip.dataset.filter}` : location.pathname);
  runExplorer(tools);
});
document.addEventListener("input", (e) => {
  const tools = e.target.closest("[data-explorer]");
  if (tools && e.target.matches("[data-search]")) runExplorer(tools);
});
// Deep links like /wiki/terrains#ocean open with that category selected.
document.addEventListener("DOMContentLoaded", () => {
  const tools = document.querySelector("[data-explorer]");
  const chip = tools && location.hash && tools.querySelector(`.filter-chip[data-filter="${CSS.escape(location.hash.slice(1))}"]`);
  if (chip) chip.click();
});

// Banner details: a tap on a banner's art, its "Details" link or a calendar day opens the dialog; htmx fills it.
document.addEventListener("click", (e) => {
  const panel = document.getElementById("banner-panel");
  if (!panel) return;
  const opener = e.target.closest("[data-open-banner]");
  if (opener) {
    e.preventDefault();  // the link is the no-JS fallback page
    document.getElementById("banner-panel-body").innerHTML = '<p class="muted">Loading…</p>';
    if (!panel.open) panel.showModal();
    return;
  }
  if (e.target.closest("[data-banner-close]") || e.target === panel) panel.close();
});
document.addEventListener("keydown", (e) => {
  const opener = (e.key === "Enter" || e.key === " ") && e.target.matches?.("li[data-open-banner]") && e.target;
  if (opener) { e.preventDefault(); opener.click(); }
});

// Stand panel: a tap on a stand opens the dialog; htmx fills it.
const standPanel = () => document.getElementById("stand-panel");
document.addEventListener("click", (e) => {
  const slot = e.target.closest("[data-open-panel]");
  if (slot && !slot.closest(".selecting")) {
    const panel = standPanel();
    if (panel && !panel.open) {
      document.getElementById("stand-panel-body").innerHTML = '<p class="muted">Loading…</p>';
      panel.showModal();
    }
    return;
  }
  if (e.target.closest("[data-panel-close]") || e.target === standPanel()) standPanel().close();
});
document.addEventListener("keyup", (e) => {
  if (e.key !== "Enter") return;
  const slot = e.target.closest?.("[data-open-panel]");
  if (slot && !slot.closest(".selecting") && standPanel() && !standPanel().open) {
    document.getElementById("stand-panel-body").innerHTML = '<p class="muted">Loading…</p>';
    standPanel().showModal();
  }
});
// Panel actions refresh #collection; close the panel once they land.
document.addEventListener("htmx:afterRequest", (e) => {
  if (e.detail.elt.closest?.("[data-close-panel]") && e.detail.successful && standPanel()?.open) standPanel().close();
});

// Storage toolbar: search, rarity, fusable, group copies, sort, multi-select. State survives htmx refreshes.
const storageState = { q: "", rarity: "", dupe: false, stack: false, sort: "idx", selecting: false };
try { storageState.stack = localStorage.getItem("storage-stack") === "1"; } catch (e) { /* storage blocked */ }
function applyStorage() {
  const grid = document.getElementById("storage-grid");
  const tools = document.querySelector("[data-storage-tools]");
  if (!grid || !tools) return;
  const s = storageState;
  tools.querySelector("[data-storage-search]").value = s.q;
  tools.querySelector("[data-storage-sort]").value = s.sort;
  tools.querySelectorAll("[data-rarity-filter]").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.rarityFilter === s.rarity)));
  tools.querySelector("[data-dupe-filter]").setAttribute("aria-pressed", String(s.dupe));
  tools.querySelector("[data-stack-toggle]").setAttribute("aria-pressed", String(s.stack));
  tools.querySelector("[data-select-toggle]").setAttribute("aria-pressed", String(s.selecting));
  const slots = [...grid.querySelectorAll(".stand-slot")];
  const key = { idx: (el) => +el.dataset.idx, rarity: (el) => -el.dataset.rarity * 1e6 - +el.dataset.level,
                level: (el) => -el.dataset.level, power: (el) => -el.dataset.power, name: (el) => el.dataset.name }[s.sort];
  slots.sort((a, b) => { const x = key(a), y = key(b); return x < y ? -1 : x > y ? 1 : +a.dataset.idx - +b.dataset.idx; });
  // Grouped: one card per stand, its most advanced copy (the card's badge shows the other copies).
  const best = new Map();
  if (s.stack) {
    slots.forEach((el) => {
      const cur = best.get(el.dataset.sid);
      if (!cur || +el.dataset.level > +cur.dataset.level || (+el.dataset.level === +cur.dataset.level && +el.dataset.power > +cur.dataset.power)) best.set(el.dataset.sid, el);
    });
  }
  let shown = 0;
  slots.forEach((el) => {
    const ok = el.dataset.search.includes(s.q) && (!s.rarity || el.dataset.rarity === s.rarity) && (!s.dupe || el.dataset.dupe === "1")
      && (!s.stack || best.get(el.dataset.sid) === el);
    el.hidden = !ok;
    shown += ok;
    grid.appendChild(el);
  });
  grid.closest(".storage").classList.toggle("selecting", s.selecting);
  document.querySelector(".bulk-bar").hidden = !s.selecting;
  document.querySelector(".storage .collection-empty").hidden = shown > 0;
  updateSelected();
}
function updateSelected() {
  const n = document.querySelectorAll("#storage-grid [name=uuid]:checked").length;
  const label = document.querySelector("[data-selected-count]");
  if (label) label.textContent = `${n} selected`;
}
document.addEventListener("input", (e) => {
  if (e.target.matches("[data-storage-search]")) { storageState.q = e.target.value.trim().toLocaleLowerCase(); applyStorage(); }
});
document.addEventListener("change", (e) => {
  if (e.target.matches("[data-storage-sort]")) { storageState.sort = e.target.value; applyStorage(); }
  if (e.target.matches("#storage-grid [name=uuid]")) updateSelected();
});
document.addEventListener("click", (e) => {
  const t = e.target;
  if (t.closest("[data-rarity-filter]")) { storageState.rarity = t.closest("[data-rarity-filter]").dataset.rarityFilter; applyStorage(); }
  else if (t.closest("[data-dupe-filter]")) { storageState.dupe = !storageState.dupe; applyStorage(); }
  else if (t.closest("[data-stack-toggle]")) {
    storageState.stack = !storageState.stack;
    try { localStorage.setItem("storage-stack", storageState.stack ? "1" : "0"); } catch (e) { /* storage blocked */ }
    applyStorage();
  } else if (t.closest("[data-select-none]")) {
    document.querySelectorAll("#storage-grid [name=uuid]").forEach((c) => { c.checked = false; });
    updateSelected();
  }
  else if (t.closest("[data-select-toggle]")) {
    storageState.selecting = !storageState.selecting;
    if (!storageState.selecting) document.querySelectorAll("#storage-grid [name=uuid]").forEach((c) => { c.checked = false; });
    applyStorage();
  } else if (t.closest("[data-select-visible]")) {
    document.querySelectorAll("#storage-grid .stand-slot:not([hidden]) [name=uuid]").forEach((c) => { c.checked = true; });
    updateSelected();
  } else if (storageState.selecting) {
    const slot = t.closest("#storage-grid .stand-slot");
    if (slot && !t.matches("[name=uuid]")) {
      const box = slot.querySelector("[name=uuid]");
      if (box) { box.checked = !box.checked; updateSelected(); }
    }
  }
});
document.addEventListener("htmx:afterSwap", (e) => { if (e.detail.target.id === "collection") applyStorage(); });
document.addEventListener("DOMContentLoaded", applyStorage);

// Items page: show one kind and search by name. State survives the inventory refresh after each action.
const itemState = { kind: "", q: "" };
function applyItems() {
  const tools = document.querySelector("[data-explorer-items]");
  if (!tools) return;
  tools.querySelectorAll("[data-item-filter]").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.itemFilter === itemState.kind)));
  tools.querySelector("[data-item-search]").value = itemState.q;
  document.querySelectorAll("[data-item-section]").forEach((sec) => { sec.hidden = Boolean(itemState.kind) && sec.dataset.itemSection !== itemState.kind; });
  document.querySelectorAll("[data-item-name]").forEach((el) => { el.hidden = !el.dataset.itemName.includes(itemState.q); });
}
document.addEventListener("click", (e) => {
  const chip = e.target.closest("[data-item-filter]");
  if (chip) { itemState.kind = chip.dataset.itemFilter; applyItems(); }
});
document.addEventListener("input", (e) => {
  if (e.target.matches("[data-item-search]")) { itemState.q = e.target.value.trim().toLocaleLowerCase(); applyItems(); }
});
document.addEventListener("htmx:oobAfterSwap", (e) => { if (e.detail.target.id === "inventory") applyItems(); });

// Big stand cards turn over to their parameter chart (macros.card params=True).
document.addEventListener("click", (e) => {
  const btn = e.target.closest("[data-params-flip]");
  if (!btn) return;
  const card = btn.previousElementSibling;
  const back = card?.querySelector(".card-params");
  if (!back) return;
  const on = btn.getAttribute("aria-pressed") !== "true";
  btn.setAttribute("aria-pressed", String(on));
  btn.querySelector("[data-flip-label]").textContent = on ? "Card" : "Parameters";
  const swap = () => { back.hidden = !on; card.classList.toggle("params-on", on); };
  if (matchMedia("(prefers-reduced-motion: reduce)").matches) return swap();
  card.classList.add("turning");
  setTimeout(() => { swap(); card.classList.remove("turning"); }, 180);
});

// Loading: a ドドド in the corner when something the player clicked takes a moment (not for background polling).
(() => {
  let busy = 0, timer;
  const box = () => document.querySelector(".dododo");
  document.addEventListener("htmx:beforeRequest", (e) => {
    if (!e.detail.requestConfig?.triggeringEvent?.isTrusted) return;
    e.detail.elt.dataset.dododo = "1";
    busy += 1;
    clearTimeout(timer);
    timer = setTimeout(() => { if (busy) box()?.classList.add("on"); }, 350);
  });
  document.addEventListener("htmx:afterRequest", (e) => {
    if (!e.detail.elt.dataset.dododo) return;
    delete e.detail.elt.dataset.dododo;
    busy = Math.max(0, busy - 1);
    if (!busy) { clearTimeout(timer); box()?.classList.remove("on"); }
  });
})();

// Pull reveal: tap a card to flip it, or reveal all in sequence (rarest last).
function flip(card) {
  if (card.classList.contains("flipped")) return;
  card.classList.add("flipped");
  card.setAttribute("aria-label", "Revealed");
  if (+card.dataset.rank >= 3) burst(card.closest(".slot"));  // UR and LR: manga speed lines and ドドド
  const batch = card.closest("[data-pull]");
  if (batch && !batch.querySelector("[data-flip]:not(.flipped)")) {
    batch.querySelector("[data-pull-summary]").hidden = false;
    batch.querySelector("[data-reveal-all]").hidden = true;
    batch.querySelectorAll("[data-after-reveal]").forEach((x) => { x.hidden = false; });
    batch.querySelector("[data-cinematic]")?.setAttribute("hidden", "");
    document.dispatchEvent(new CustomEvent("pull:revealed"));
  }
}
// Manga focus lines and sound effects behind a UR / LR card as it turns over in the grid (sample C).
function burst(slot) {
  if (!slot || matchMedia("(prefers-reduced-motion: reduce)").matches) return;
  const el = document.createElement("div");
  el.className = "flip-burst";
  el.setAttribute("aria-hidden", "true");
  el.innerHTML = '<i class="burst-lines"></i><b class="sfx s1">ドド</b><b class="sfx s2">ドドド</b><b class="sfx s3">ゴゴ</b>';
  slot.prepend(el);
  setTimeout(() => el.remove(), 2600);
}
document.addEventListener("click", (e) => {
  const card = e.target.closest("[data-flip]");
  if (card) return flip(card);
  const all = e.target.closest("[data-reveal-all]");
  if (all) {
    const fast = matchMedia("(prefers-reduced-motion: reduce)").matches;
    [...all.closest("[data-pull]").querySelectorAll("[data-flip]:not(.flipped)")]
      .forEach((c, i) => setTimeout(() => flip(c), fast ? 0 : i * 220 + (+c.dataset.rank >= 2 ? 400 : 0)));
  }
});
document.addEventListener("keyup", (e) => { if (e.key === "Enter" && e.target.matches?.("[data-flip]")) flip(e.target); });

// Cinematic pull: one card at a time, full screen. SSR, UR and LR each get a bigger show.
// The grid stays the source of truth: every card shown here is flipped there too.
(() => {
  const PREF = "pull-cinematic";
  const pref = () => { try { return localStorage.getItem(PREF) !== "0"; } catch (e) { return true; } };
  const setPref = (on) => { try { localStorage.setItem(PREF, on ? "1" : "0"); } catch (e) { /* storage blocked */ } };
  const BEAT = { R: 700, SR: 900, SSR: 1900, UR: 2800, LR: 4200 };  // ms before the card turns
  const TITLE = { SSR: "SSR!", UR: "ULTRA RARE!!", LR: "LEGENDARY" };
  const MENACE = { SSR: "ゴゴゴ", UR: "ゴゴゴゴゴ", LR: "ドドドドドド" };
  let state = null;

  function overlay() {
    const el = document.createElement("div");
    el.className = "cine";
    el.setAttribute("role", "dialog");
    el.setAttribute("aria-modal", "true");
    el.setAttribute("aria-label", "Cinematic pull");
    el.innerHTML = `
      <div class="cine-bg"></div><div class="cine-rays"></div><div class="cine-lines"></div><div class="cine-flash"></div>
      <div class="cine-sfx" aria-hidden="true"><b>ドド</b><b>ドドド</b><b>ゴゴ</b><b>ドドドド</b></div>
      <p class="cine-menace" aria-hidden="true"></p>
      <p class="cine-title" aria-hidden="true"></p>
      <div class="cine-stage"><div class="cine-card"><div class="cine-face"></div><div class="cine-back"><span>？</span></div></div></div>
      <div class="cine-caption" aria-live="polite"></div>
      <div class="cine-bar">
        <span class="cine-count"></span>
        <span class="cine-hint">Tap or press Space</span>
        <button type="button" class="btn small ghost" data-cine-skip>Skip ⏭</button>
      </div>`;
    document.body.append(el);
    document.body.classList.add("cine-open");
    return el;
  }

  function start(batch) {
    if (state || !batch || batch.dataset.cineDone) return;  // one show at a time, once per pull
    const cards = [...batch.querySelectorAll("[data-flip]:not(.flipped)")];
    if (!cards.length) return;
    batch.dataset.cineDone = "1";
    state = { batch, cards, i: -1, busy: false, pending: null, el: overlay(), timers: [],
              fast: matchMedia("(prefers-reduced-motion: reduce)").matches };
    state.el.querySelector("[data-cine-skip]").focus({ preventScroll: true });
    next();
  }

  function later(fn, ms) { state.timers.push(setTimeout(fn, state.fast ? Math.min(ms, 150) : ms)); }

  function tap() {
    if (!state) return;
    if (state.pending) {  // still building up: skip straight to the reveal
      state.timers.forEach(clearTimeout);
      state.timers = [];
      const [src, r] = state.pending;
      state.el.classList.add("charge");
      return reveal(src, r);
    }
    next();
  }

  function next() {
    if (!state || state.busy) return;
    state.i += 1;
    if (state.i >= state.cards.length) return close();
    state.busy = true;
    const src = state.cards[state.i];
    const r = src.dataset.rarity;
    const el = state.el;
    el.className = `cine show r-${r}`;
    el.querySelector(".cine-count").textContent = `${state.i + 1} / ${state.cards.length}`;
    el.querySelector(".cine-caption").innerHTML = "";
    el.querySelector(".cine-gif")?.remove();
    el.querySelector(".cine-title").textContent = "";
    el.querySelector(".cine-menace").textContent = MENACE[r] || "";
    const face = el.querySelector(".cine-face");
    face.innerHTML = src.querySelector(".flip-front").innerHTML;
    face.querySelectorAll("a, button").forEach((x) => x.setAttribute("tabindex", "-1"));
    face.querySelectorAll("img[data-anim]").forEach((img) => { img.src = img.dataset.anim; img.removeAttribute("data-anim"); });
    const card = el.querySelector(".cine-card");
    card.className = "cine-card";
    void card.offsetWidth;  // restart the entrance animation
    card.classList.add("enter");
    if (BEAT[r] > 1000) later(() => el.classList.add("charge"), 350);  // the build-up for SSR and above
    state.pending = [src, r];
    later(() => reveal(src, r), BEAT[r] || 700);
  }

  function reveal(src, r) {
    state.pending = null;
    const el = state.el;
    el.classList.add("revealed");
    el.querySelector(".cine-card").classList.add("turned");
    const shiny = src.dataset.shiny === "1";  // 1 in 1000: it gets its own title
    el.classList.toggle("is-shiny", shiny);
    el.querySelector(".cine-title").textContent = shiny ? "✨ SHINY ✨" : TITLE[r] || "";
    if (["SSR", "UR", "LR"].includes(r) && src.dataset.gif) {  // the special's animation fills the background
      const gif = document.createElement("img");
      gif.className = "cine-gif";
      gif.alt = "";
      gif.src = src.dataset.gif;
      gif.onerror = () => gif.remove();
      el.querySelector(".cine-bg").after(gif);
    }
    el.querySelector(".cine-caption").innerHTML = `
      <strong>${src.dataset.name}</strong>
      <span class="cine-rar r-${r}">${r}</span>${shiny ? '<span class="new-tag shiny-tag">✨ SHINY</span>' : ""}${src.dataset.new === "1" ? '<span class="new-tag">NEW</span>' : ""}
      ${["SSR", "UR", "LR"].includes(r) ? `<small>${src.dataset.special}</small>` : ""}`;
    flip(src);
    later(() => { state.busy = false; }, r === "LR" ? 900 : 350);
  }

  function close() {
    if (!state) return;
    state.timers.forEach(clearTimeout);
    state.cards.forEach((c) => flip(c));
    state.el.remove();
    document.body.classList.remove("cine-open");
    const batch = state.batch;
    state = null;
    delete batch.dataset.cineWait;
    batch.scrollIntoView({ block: "start", behavior: "smooth" });
  }

  document.addEventListener("click", (e) => {
    const btn = e.target.closest("[data-cinematic]");
    if (btn) { setPref(true); syncBox(btn.closest("[data-pull]")); return start(btn.closest("[data-pull]")); }
    if (e.target.closest("[data-reveal-all]")) setPref(false);
    if (!state) return;
    if (e.target.closest("[data-cine-skip]")) return close();
    if (e.target.closest(".cine")) tap();
  });
  document.addEventListener("change", (e) => {
    if (e.target.matches("[data-cinematic-auto]")) setPref(e.target.checked);
  });
  document.addEventListener("keydown", (e) => {
    if (!state) return;
    if (e.key === "Escape") { e.preventDefault(); close(); }
    else if (e.key === " " || e.key === "Enter" || e.key === "ArrowRight") { e.preventDefault(); tap(); }
  });
  function syncBox(batch) {
    const box = batch?.querySelector("[data-cinematic-auto]");
    if (box) box.checked = pref();
  }

  // Summon: a slow build before any card. Light gathers, a silver Arrow descends and hovers; for SSR and
  // above the core beats like a heart and each beat upgrades its colour (gold, then magenta, then cyan), the
  // tease; then the Arrow strikes and a soft portal opens. Everything stays dim: the hype is in the waiting.
  const RANK = { R: 0, SR: 1, SSR: 2, UR: 3, LR: 4 };
  const BEATS = { SSR: ["t1"], UR: ["t1", "t2"], LR: ["t1", "t2", "t3"] };  // colour upgrades before the strike
  const GATHER_MS = 1600, BEAT_MS = 850, AFTER_MS = { R: 1000, SR: 1200, SSR: 1600, UR: 1800, LR: 2300 };
  const SPARKS = { SR: [10, "mote"], SSR: [16, ""], UR: [20, ""], LR: [28, ""] };
  let summoning = null;
  const topOf = (batch) => [...batch.querySelectorAll("[data-flip]")].map((c) => c.dataset.rarity)
    .sort((a, b) => (RANK[b] ?? 0) - (RANK[a] ?? 0))[0] || "R";

  function sparks(el, n, cls, box = ".sum-sparks") {
    const host = el.querySelector(box);
    for (let k = 0; k < n; k++) {
      const s = document.createElement("i");
      if (cls) s.className = cls;
      s.style.setProperty("--a", `${(360 / n) * k + Math.random() * 10}deg`);
      s.style.setProperty("--d", `${22 + Math.random() * 20}vmin`);
      s.style.setProperty("--t", `${1.2 + Math.random() * 0.8}s`);
      s.style.setProperty("--w", `${Math.random() * (cls === "gather" ? 1.2 : 0.3)}s`);
      host.append(s);
    }
  }

  function summon(batch, done) {
    if (matchMedia("(prefers-reduced-motion: reduce)").matches) return done();
    const top = topOf(batch);
    const el = document.createElement("div");
    el.className = `summon s-${top}`;
    if (batch.querySelector('[data-flip][data-shiny="1"]')) el.classList.add("has-shiny");  // a faint prismatic hint
    el.setAttribute("role", "dialog");
    el.setAttribute("aria-modal", "true");
    el.setAttribute("aria-label", "Summoning");
    el.innerHTML = `
      <div class="sum-bg"></div><div class="sum-rays"></div>
      <div class="sum-portal"><i></i><i></i><i></i></div>
      <div class="sum-bolts" aria-hidden="true"><i></i><i></i><i></i></div>
      <div class="sum-gather" aria-hidden="true"></div><div class="sum-sparks" aria-hidden="true"></div>
      <div class="sum-arrow" aria-hidden="true"></div>
      <p class="sum-word" aria-hidden="true">${MENACE[top] || ""}</p>
      <p class="sum-hint">Tap to skip</p>`;
    document.body.append(el);
    document.body.classList.add("cine-open");
    sparks(el, 18, "gather", ".sum-gather");
    const timers = [];
    const finish = () => {
      if (summoning?.el !== el) return;
      timers.forEach(clearTimeout);
      summoning = null;
      el.classList.add("out");
      setTimeout(() => { el.remove(); if (!state) document.body.classList.remove("cine-open"); }, 250);
      done();
    };
    summoning = { el, finish };
    let t = GATHER_MS;
    (BEATS[top] || []).forEach((beat) => {  // each heartbeat upgrades the colour: the tease
      timers.push(setTimeout(() => {
        el.classList.add(beat, "beat");
        el.classList.remove("pulse");
        void el.offsetWidth;  // restart the pulse animation
        el.classList.add("pulse");
      }, t));
      t += BEAT_MS;
    });
    timers.push(setTimeout(() => {
      el.classList.add("impact");
      if (SPARKS[top]) sparks(el, ...SPARKS[top]);
    }, t));
    timers.push(setTimeout(() => el.classList.add("burst"), t + 350));
    timers.push(setTimeout(finish, t + (AFTER_MS[top] || 1000)));
  }
  document.addEventListener("click", (e) => { if (summoning && e.target.closest(".summon")) summoning.finish(); });
  document.addEventListener("keydown", (e) => {
    if (summoning && [" ", "Enter", "Escape", "ArrowRight"].includes(e.key)) { e.preventDefault(); summoning.finish(); }
  });
  // a fresh pull opens straight into the cinematic when the player chose it
  document.addEventListener("htmx:afterSwap", (e) => {
    if (e.detail.target.id !== "pull-result") return;
    const batch = e.detail.target.querySelector("[data-pull]");
    if (!batch) return document.dispatchEvent(new CustomEvent("pull:revealed"));  // an error: let held toasts out
    if (batch.dataset.cineSeen) return;  // htmx fires this once per out-of-band swap too
    batch.dataset.cineSeen = "1";
    syncBox(batch);
    // the summon plays first (the grid stays hidden behind it), then the cinematic or the grid
    summon(batch, () => {
      if (pref()) start(batch);
      else delete batch.dataset.cineWait;
    });
  });
})();

// PvP turn clock: count down locally (the server holds the real deadline).
setInterval(() => {
  document.querySelectorAll("[data-turn-clock]").forEach((el) => {
    if (document.querySelector("#fight.playing")) return;  // the replay of the last action comes first
    const left = Math.max(0, Number(el.dataset.turnClock) - 1);
    el.dataset.turnClock = left;
    const b = el.querySelector("b");
    if (b) b.textContent = left;
    el.classList.toggle("urgent", left <= 3);
  });
}, 1000);

// Action results (equipped, sold, crafted, socketed...) arrive as [data-float] notes: they float as toasts instead of
// sitting at the top of the swapped block, so the page never moves. A pull reveal or a simulation still scrolls into view.
document.addEventListener("htmx:afterSwap", (e) => {
  const target = e.detail.target;
  const notes = [...target.querySelectorAll("[data-float]")];
  if (notes.length) {
    document.body.dispatchEvent(new CustomEvent("toast", { detail: notes.map((n) => (
      { text: n.textContent.trim(), kind: n.classList.contains("error") ? "flash-error" : "flash-ok" })) }));
    notes.forEach((n) => n.remove());
  }
  if (["use-result", "pull-result", "sim-result"].includes(target.id) && target.firstElementChild) {
    target.scrollIntoView({ behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth", block: "start" });
  }
});

// Wiki search: loads a small index once, then filters as you type (every word must match).
(() => {
  const box = document.querySelector("[data-wiki-search]");
  if (!box) return;
  const input = box.querySelector("input");
  const list = box.querySelector("#wiki-results");
  const count = box.querySelector("#wiki-results-count");
  let index = null;
  const norm = (s) => (s || "").toLowerCase().normalize("NFD").replace(/[\u0300-\u036f]/g, "");
  const load = async () => {
    if (index) return index;
    const data = await (await fetch(box.dataset.index)).json();
    index = data.map((e) => ({ ...e, title: norm(e.t), hay: norm(`${e.t} ${e.k} ${e.s} ${e.x}`) }));
    return index;
  };
  const snippet = (e, words) => {
    const text = e.s || e.x || "";
    const at = words.length ? norm(text).indexOf(words[0]) : -1;
    const from = Math.max(0, at - 40);
    return (from ? "…" : "") + text.slice(from, from + 140) + (text.length > from + 140 ? "…" : "");
  };
  const render = async () => {
    const q = norm(input.value.trim());
    if (q.length < 2) { list.hidden = true; list.innerHTML = ""; count.textContent = ""; return; }
    const words = q.split(/\s+/);
    const hits = (await load()).filter((e) => words.every((w) => e.hay.includes(w)))
      .map((e) => ({ e, score: (e.title.startsWith(q) ? 3 : 0) + (words.every((w) => e.title.includes(w)) ? 2 : 0) + (e.k === "Guide" ? 0.5 : 0) }))
      .sort((a, b) => b.score - a.score).slice(0, 12);
    list.innerHTML = "";
    for (const { e } of hits) {
      const li = document.createElement("li");
      const a = document.createElement("a");
      a.href = e.u;
      const kind = document.createElement("small"); kind.textContent = e.k;
      const title = document.createElement("strong"); title.textContent = e.t;
      const text = document.createElement("span"); text.textContent = snippet(e, words);
      a.append(kind, title, text);
      li.append(a);
      list.append(li);
    }
    if (!hits.length) { const li = document.createElement("li"); li.className = "muted"; li.textContent = "Nothing found. Try a stand name or a word like “stun”."; list.append(li); }
    list.hidden = false;
    count.textContent = `${hits.length} result${hits.length === 1 ? "" : "s"}`;
  };
  input.addEventListener("input", render);
  input.addEventListener("focus", load, { once: true });
  input.addEventListener("keydown", (e) => {
    const links = [...list.querySelectorAll("a")];
    if (e.key === "ArrowDown" && links.length) { e.preventDefault(); links[0].focus(); }
    if (e.key === "Escape") { input.value = ""; render(); }
  });
  list.addEventListener("keydown", (e) => {
    const links = [...list.querySelectorAll("a")];
    const i = links.indexOf(document.activeElement);
    if (e.key === "ArrowDown" && i < links.length - 1) { e.preventDefault(); links[i + 1].focus(); }
    if (e.key === "ArrowUp") { e.preventDefault(); (i > 0 ? links[i - 1] : input).focus(); }
    if (e.key === "Escape") input.focus();
  });
})();

// Phones: the combat log shows its latest lines; the toggle opens the whole log.
document.addEventListener("click", (e) => {
  const btn = e.target.closest("[data-log-toggle]");
  if (!btn) return;
  const open = btn.closest(".log").classList.toggle("open");
  btn.setAttribute("aria-expanded", String(open));
  btn.textContent = open ? "Show less" : "Show full log";
});

// Installable web app: register the service worker and, on phones, offer to install.
if ("serviceWorker" in navigator) {
  addEventListener("load", () => navigator.serviceWorker.register("/sw.js").catch(() => {}));
}
(() => {
  const box = document.querySelector("[data-install]");
  if (!box) return;
  const standalone = matchMedia("(display-mode: standalone)").matches || navigator.standalone;
  const phone = matchMedia("(pointer: coarse)").matches && Math.min(screen.width, screen.height) < 820;
  let snoozed = false;
  try { snoozed = Number(localStorage.getItem("install-snooze") || 0) > Date.now(); } catch (e) { /* storage blocked */ }
  if (standalone || !phone || snoozed) return;
  const text = box.querySelector("[data-install-text]");
  const go = box.querySelector("[data-install-go]");
  let deferred = null;
  const show = () => { if (!document.body.classList.contains("touring")) box.hidden = false; };
  // Chrome / Edge / Samsung Internet hand us a real install prompt.
  addEventListener("beforeinstallprompt", (e) => {
    e.preventDefault();
    deferred = e;
    go.hidden = false;
    show();
  });
  // iOS Safari has no prompt: explain the Share menu instead.
  const ios = /iphone|ipad|ipod/i.test(navigator.userAgent) || (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);
  setTimeout(() => {
    if (deferred || !box.hidden) return;
    text.textContent = ios
      ? "Tap the Share button, then “Add to Home Screen”, to play full screen from your home screen."
      : "Open your browser menu and choose “Install app” or “Add to Home screen”.";
    show();
  }, 4000);
  go.addEventListener("click", async () => {
    if (!deferred) return;
    deferred.prompt();
    await deferred.userChoice.catch(() => null);
    deferred = null;
    box.hidden = true;
  });
  box.querySelector("[data-install-later]").addEventListener("click", () => {
    box.hidden = true;
    try { localStorage.setItem("install-snooze", String(Date.now() + 14 * 24 * 3600 * 1000)); } catch (e) { /* storage blocked */ }
  });
  addEventListener("appinstalled", () => { box.hidden = true; });
})();

// The Forge: stand search, lock toggles with a live price, and slot reels when a new roll lands.
document.addEventListener("input", (e) => {
  if (!e.target.matches("[data-forge-search]")) return;
  const q = e.target.value.trim().toLowerCase();
  document.querySelectorAll(".forge-list li[data-name]").forEach((li) => { li.hidden = !li.dataset.name.includes(q); });
});
document.addEventListener("click", (e) => {
  const pick = e.target.closest("[data-forge-pick]");
  if (!pick) return;
  document.querySelectorAll("[data-forge-pick].on").forEach((a) => a.classList.remove("on"));
  pick.classList.add("on");
});
function forgeLocks(form) {
  const boxes = [...form.querySelectorAll("[data-forge-lock]")];
  const locked = boxes.filter((b) => b.checked).length;
  boxes.forEach((b) => {
    b.closest(".reel").classList.toggle("locked", b.checked);
    b.nextElementSibling.textContent = b.checked ? "\u{1F512}" : "\u{1F513}";
    b.disabled = !b.checked && locked >= boxes.length - 1;  // one pair must stay free to roll
  });
  let costs = [];
  try { costs = JSON.parse(form.dataset.costs || "[]"); } catch (err) { /* keep the server price */ }
  const cost = costs[Math.min(locked, costs.length - 1)];
  const amount = form.querySelector("[data-forge-cost] .cur-amount");
  if (amount && cost !== undefined) amount.firstChild.nodeValue = cost.toLocaleString("en-US");
}
document.addEventListener("change", (e) => {
  if (!e.target.matches("[data-forge-lock]")) return;
  const form = e.target.closest("[data-forge-form]");
  forgeLocks(form);
  // remember the locks right away, so they're still set next time this stand is reforged
  const body = new URLSearchParams([["uuid", form.querySelector("[name=uuid]").value],
    ...[...form.querySelectorAll("[data-forge-lock]:checked")].map((b) => ["lock", b.value])]);
  const token = JSON.parse(document.body.getAttribute("hx-headers") || "{}")["X-CSRF-Token"] || "";
  fetch(form.dataset.locksUrl, { method: "POST", body, headers: { "X-CSRF-Token": token } }).catch(() => {});
});
// remembered locks arrive checked: apply the one-pair-stays-free rule and the price to them
const initForge = (root) => root.querySelectorAll && root.querySelectorAll("[data-forge-form]").forEach(forgeLocks);
initForge(document);
document.addEventListener("htmx:load", (e) => initForge(e.detail.elt));
document.addEventListener("htmx:load", (e) => {
  const reels = e.detail.elt.querySelectorAll ? e.detail.elt.querySelectorAll(".forge-pairs.spin .reel") : [];
  if (!reels.length) return;
  const fast = matchMedia("(prefers-reduced-motion: reduce)").matches;
  const TYPES = ["\u2694\uFE0F Attack", "\u{1F6E1}\uFE0F Defense", "\u{1F4A8} Speed", "\u{1F340} Luck", "\u2696\uFE0F Balance", "\u2764\uFE0F Health"];
  const QUALS = [["A", "Universal"], ["B", "Supreme"], ["C", "Great"], ["D", "Good"], ["E", "Sub Par"], ["F", "Bad"]];
  const show = (reel, type, rank, name) => {
    reel.querySelector(".reel-type").textContent = type;
    const q = reel.querySelector(".reel-quality");
    q.firstElementChild.textContent = rank;
    q.lastChild.nodeValue = " " + name;
    reel.className = reel.className.replace(/\bq-[A-F]\b/, "q-" + rank);
  };
  reels.forEach((reel, i) => {
    const d = reel.dataset;
    const land = () => {
      show(reel, d.type, d.rank, d.quality);
      reel.classList.remove("rolling");
      reel.classList.add("landed");
      if (d.oldRank) reel.classList.add(d.rank < d.oldRank ? "better" : d.rank > d.oldRank ? "worse" : "same");
      else reel.classList.add("fresh");
    };
    if (fast) return land();
    reel.classList.add("rolling");
    const tick = setInterval(() => {
      const [rank, name] = QUALS[Math.floor(Math.random() * QUALS.length)];
      show(reel, TYPES[Math.floor(Math.random() * TYPES.length)], rank, name);
    }, 70);
    setTimeout(() => { clearInterval(tick); land(); }, 900 + i * 450);
  });
});

// The newest post's ribbon: shown until that post is read or the ribbon dismissed (remembered per browser).
(() => {
  const KEY = "news-seen";
  const seen = () => { try { return localStorage.getItem(KEY); } catch (e) { return null; } };
  const mark = (id) => { try { localStorage.setItem(KEY, id); } catch (e) { /* storage blocked */ } };
  const read = document.querySelector("[data-news-read]");
  if (read) mark(read.dataset.newsRead);
  const ribbon = document.querySelector("[data-news-ribbon]");
  if (!ribbon) return;
  if (seen() !== ribbon.dataset.newsRibbon) ribbon.hidden = false;
  ribbon.addEventListener("click", (e) => {
    mark(ribbon.dataset.newsRibbon);
    if (e.target.closest("[data-news-ribbon-x]")) { e.preventDefault(); ribbon.hidden = true; }
  });
})();

// Pop-up toasts: rendered on full pages, or sent with an HTMX response as HX-Trigger {"toast": [...]}.
(() => {
  const box = () => document.getElementById("toasts");
  // Achievements and titles stamp in at the top of the screen as a card (実績解除 / 称号獲得) instead of a plain toast.
  const SLAM = { achievement: ["実績解除", "Achievement unlocked", /^.*?unlocked:\s*/i], title: ["称号獲得", "New title", /^New title:\s*/i] };
  const slamify = (el) => {
    const kind = Object.keys(SLAM).find((k) => el.classList.contains(k));
    if (!kind) return;
    const [jp, en, strip] = SLAM[kind];
    const name = (el.querySelector("span")?.textContent || "").replace(strip, "").replace(/!$/, "").trim();
    const card = document.createElement("span");
    card.className = "slam-card";
    card.innerHTML = '<span class="slam-medal" aria-hidden="true">★</span><span class="slam-jp" aria-hidden="true"></span><span class="slam-en"></span><strong></strong>';
    card.querySelector(".slam-jp").textContent = jp;
    card.querySelector(".slam-en").textContent = en;
    card.querySelector("strong").textContent = name;
    el.querySelector("span")?.replaceWith(card);
    el.classList.add("slam");
    let host = document.getElementById("slams");
    if (!host) { host = document.createElement("div"); host.id = "slams"; host.className = "slams"; host.setAttribute("aria-live", "polite"); document.body.append(host); }
    host.append(el);
  };
  const arm = (el) => {  // errors stay longer; a toast under the pointer or finger waits
    if (el.dataset.armed) return;
    el.dataset.armed = "1";
    slamify(el);
    let left = el.classList.contains("flash-error") ? 12000 : 7000, since = Date.now(), timer;
    const go = () => { timer = setTimeout(() => { el.classList.add("leaving"); setTimeout(() => el.remove(), 600); }, left); };
    el.addEventListener("pointerenter", () => { clearTimeout(timer); left = Math.max(1500, left - (Date.now() - since)); });
    el.addEventListener("pointerleave", () => { since = Date.now(); go(); });
    go();
  };
  document.querySelectorAll("[data-toast]").forEach(arm);
  let held = [];
  document.addEventListener("pull:revealed", () => { const list = held; held = []; if (list.length) show(list); });
  document.body.addEventListener("toast", (e) => {
    const list = Array.isArray(e.detail?.value) ? e.detail.value : Array.isArray(e.detail) ? e.detail : [];
    if (e.target?.closest?.("#pull-result, .banner")) { held = held.concat(list); return; }  // no spoilers mid-pull
    show(list);
  });
  function show(list) {
    for (const t of list) {
      const a = document.createElement(t.url ? "a" : "div");  // never href="#": it would jump to the top
      a.className = `toast-pop ${t.kind || ""}`;
      if (t.url) a.href = t.url;
      a.dataset.toast = "";
      const span = document.createElement("span");
      span.textContent = t.text;
      const x = document.createElement("button");
      x.type = "button";
      x.className = "toast-x";
      x.setAttribute("aria-label", "Dismiss");
      x.dataset.toastX = "";
      x.textContent = "✕";
      a.append(span, x);
      box()?.append(a);
      arm(a);
    }
    const bell = document.querySelector(".bell");  // news rings the bell; the result of your own click doesn't
    if (bell && list.some((t) => !String(t.kind || "").startsWith("flash-"))) bell.classList.add("has-news", "ring");
  }
  document.addEventListener("click", (e) => {
    const x = e.target.closest("[data-toast-x]");
    if (x) { e.preventDefault(); x.closest("[data-toast]").remove(); }
  });
})();

// Plain (non-HTMX) forms post, redirect and reload the page: remember the scroll spot so base.html can put the
// player back where they clicked instead of at the top of the page.
document.addEventListener("submit", (e) => {
  const f = e.target;
  if (!(f instanceof HTMLFormElement) || (f.getAttribute("method") || "").toLowerCase() !== "post") return;
  if (f.matches("[hx-post], [hx-get], [hx-put], [hx-delete], [hx-patch]") || f.target === "_blank") return;
  try {
    sessionStorage.setItem("post-scroll", JSON.stringify({ path: location.pathname, y: Math.round(scrollY), at: Date.now(),
                                                           fight: !!document.getElementById("fight") }));
  } catch (err) { /* storage blocked: the page just opens at the top */ }
});

// Quest tabs (Daily / Weekly / Journey), and "3 h ago" times in the inbox.
document.addEventListener("click", (e) => {
  const tab = e.target.closest("[data-quest-tab]");
  if (!tab) return;
  const root = tab.closest("#quests");
  root.querySelectorAll("[data-quest-tab]").forEach((t) => t.setAttribute("aria-selected", String(t === tab)));
  root.querySelectorAll(".quest-panel").forEach((p) => { p.hidden = p.id !== `qp-${tab.dataset.questTab}`; });
});
function timeAgo(root) {
  root.querySelectorAll?.("[data-ago]").forEach((el) => {
    const s = Math.max(0, Date.now() / 1000 - Number(el.dataset.ago));
    el.textContent = s < 60 ? "just now" : s < 3600 ? `${Math.floor(s / 60)} min ago` : s < 86400 ? `${Math.floor(s / 3600)} h ago` : `${Math.floor(s / 86400)} d ago`;
    el.title = new Date(Number(el.dataset.ago) * 1000).toLocaleString();
  });
}
timeAgo(document);
document.addEventListener("htmx:load", (e) => timeAgo(e.detail.elt));

// Achievements: filter chips (all / to do / done / secret).
document.addEventListener("click", (e) => {
  const chip = e.target.closest("[data-ach-filter]");
  if (!chip) return;
  const key = chip.dataset.achFilter;
  document.querySelectorAll("[data-ach-filter]").forEach((c) => c.setAttribute("aria-pressed", String(c === chip)));
  document.querySelectorAll(".achievements li[data-ach]").forEach((li) => {
    li.hidden = key !== "all" && !li.dataset.ach.split(" ").includes(key);
  });
});

// "Copy link" buttons (profiles): clipboard with a short confirmation.
document.addEventListener("click", async (e) => {
  const btn = e.target.closest("[data-copy]");
  if (!btn) return;
  const label = btn.textContent;
  try { await navigator.clipboard.writeText(btn.dataset.copy); btn.textContent = "✓ Link copied"; }
  catch (err) { btn.textContent = "Copy failed"; }
  setTimeout(() => { btn.textContent = label; }, 1800);
});

// Surface server errors instead of failing silently.
document.addEventListener("htmx:responseError", (e) => {
  const p = document.createElement("p");
  p.className = "toast error floating";
  p.setAttribute("role", "alert");
  p.textContent = e.detail.xhr.status === 400
    ? "Your session token expired. Reload the page and try again."
    : "The server didn't answer properly. Try again in a moment.";
  document.body.appendChild(p);
  setTimeout(() => p.remove(), 5000);
});

// The anime's eyecatch: colour bars sweep across with the fight's name, when a big fight opens (data-eyecatch).
// Resolves when it's over; a click or a key skips it.
function eyecatch(title, label) {
  return new Promise((done) => {
    const el = document.createElement("div");
    el.className = "eyecatch";
    el.setAttribute("aria-hidden", "true");
    el.innerHTML = '<i class="bar b1"></i><i class="bar b2"></i><i class="bar b3"></i><div class="eye-text"><b></b><span></span></div>';
    el.querySelector("b").textContent = title;
    el.querySelector(".eye-text span").textContent = label || "";
    document.body.append(el);
    let over = false;
    const end = () => { if (over) return; over = true; el.remove(); removeEventListener("keydown", end); done(); };
    el.addEventListener("click", end);
    addEventListener("keydown", end);
    setTimeout(end, 1650);
  });
}
const HEAVY_SFX = ["ドゴォ!!", "バァーン!", "メメタァ!", "ドドン!"];

// Fight replay: a fresh turn arrives with its log events as JSON. Rewind the bars to before the turn,
// then play each event (lunge, hit, damage numbers, special GIF in the spotlight) and land on the server's final state.
const FIGHT_STEP = { hit: 700, crit: 950, dodge: 700, special: 1900, item: 1000, info: 600, stun: 700, terrain: 1300, sudden: 900 };
// A crit's colour by how many times it crit: yellow, red (double), rainbow (triple and more).
const critClass = (e) => (e.kind !== "crit" ? "" : e.crit >= 3 ? "crit crit3" : e.crit === 2 ? "crit crit2" : "crit");
function playFight(root) {
  const data = root.querySelector(".fight-replay");
  if (!data || matchMedia("(prefers-reduced-motion: reduce)").matches) return;
  const { start, fromStart, startField, events } = JSON.parse(data.textContent);
  if (!events.length) return;

  const arena = root.querySelector(".arena");
  const banner = root.querySelector(".turn-banner");
  const spot = root.querySelector(".spotlight");
  const spotImg = spot.querySelector(".spotlight-img");
  const spotName = spot.querySelector(".spotlight-name");
  const spotLine = spot.querySelector(".spotlight-line");
  const fighters = [...root.querySelectorAll(".fighter")];
  const byPos = new Map(fighters.map((f) => [`${f.dataset.side}:${f.dataset.idx}`, f]));
  const logItems = [...root.querySelectorAll(".log li.fresh")].sort((a, b) => a.dataset.i - b.dataset.i);
  const EFFECTS = ["lunge", "hurt", "crit", "dodge", "cast", "swap", "flash-special", "shake"];
  const fx = () => root.dataset.fx === "1";  // battle cries, heavy-hit sound effects and the eyecatch (the 💥 Effects toggle)
  const restart = (el, ...cls) => { el.classList.remove(...EFFECTS, ...cls); void el.offsetWidth; el.classList.add(...cls); };

  // The server-rendered end state, restored when the replay finishes or is skipped.
  const final = {
    fighters: fighters.map((f) => ({ f, cls: f.className, width: f.querySelector(".hp i").style.width, num: f.querySelector(".hp-num").textContent })),
    banner: [banner.className, banner.innerHTML],
    spot: [spot.className, spotImg.src, spotImg.alt, spotName.textContent, spotLine.textContent],
  };

  // the arena glows in the terrain's colour: back to the field before the turn, then each change as it happens
  const finalField = arena.dataset.terrain;
  const setField = (name) => {
    if (!name) return;
    arena.className = arena.className.replace(/\bterrain-\w+/g, "").trim() + ` terrain-${name.toLowerCase()}`;
    arena.classList.toggle("has-terrain", name !== "DEFAULT");
  };
  setField(startField);

  const maxes = [[], []];
  fighters.forEach((f) => { maxes[f.dataset.side][f.dataset.idx] = +f.dataset.max; });
  const setHp = (snap) => {
    fighters.forEach((f) => {
      const hp = snap?.[f.dataset.side]?.[f.dataset.idx];
      if (hp === undefined) return;
      f.querySelector(".hp i").style.width = `${Math.min(100, (100 * hp) / f.dataset.max)}%`;
      f.querySelector(".hp-num").textContent = Math.round(hp);
    });
  };
  // A heavy hit (a quarter of the target's health or more): a manga sound effect and a shake (💥 Effects).
  const heavy = (f, lost) => {
    if (!fx() || lost < 0.25 * (+f.dataset.max || Infinity)) return;
    const s = document.createElement("span");
    s.className = "heavy-sfx";
    s.textContent = HEAVY_SFX[Math.floor(Math.random() * HEAVY_SFX.length)];
    s.setAttribute("aria-hidden", "true");
    s.style.left = `${5 + Math.random() * 35}%`;
    s.style.rotate = `${Math.round(Math.random() * 20 - 10)}deg`;
    f.appendChild(s);
    s.addEventListener("animationend", () => s.remove());
    restart(arena, "shake");
  };
  const pop = (f, text, cls) => {
    const p = document.createElement("span");
    p.className = `dmg-pop ${cls}`;
    p.textContent = text;
    p.setAttribute("aria-hidden", "true");
    f.appendChild(p);
    p.addEventListener("animationend", () => p.remove());
  };
  // A special shouts the stand's cry (ORA ORA ORA…), or a plain ドン! for stands without one.
  const shout = (f) => {
    const cry = f.dataset.cry;
    const words = cry ? (cry.length <= 4 ? [cry, cry, cry, `${cry}!!`] : [`${cry}!`]) : ["ドン!"];
    words.forEach((w, n) => setTimeout(() => {
      const s = document.createElement("span");
      s.className = `cry${cry ? "" : " plain"}`;
      s.textContent = w;
      s.setAttribute("aria-hidden", "true");
      s.style.left = `${8 + Math.random() * 60}%`;
      s.style.top = `${4 + Math.random() * 50}%`;
      s.style.rotate = `${Math.round(Math.random() * 24 - 12)}deg`;
      f.appendChild(s);
      s.addEventListener("animationend", () => s.remove());
    }, n * 140 * pace()));
  };
  const showSpot = (f, line, special) => {
    if (!f) return;
    spot.classList.toggle("special", special);
    spot.classList.toggle("shiny-art", !special && f.dataset.hue === "1");  // a shiny without its own art: colours shifted
    spotImg.onerror = special ? () => { spotImg.onerror = null; spotImg.src = f.dataset.img; } : null;
    spotImg.src = special ? f.dataset.gif : f.dataset.img;
    spotImg.alt = f.dataset.name;
    spotName.textContent = f.dataset.name;
    spotLine.textContent = line;
    restart(spot, "swap");
    spotting = f;
  };
  let spotting = null;

  let prev = start || (fromStart ? maxes : null);
  let skipped = false, timer, wake;
  const wait = (ms) => (skipped ? Promise.resolve() : new Promise((r) => { wake = r; timer = setTimeout(r, ms); }));
  const skip = () => { skipped = true; clearTimeout(timer); wake?.(); };

  root.classList.add("playing");
  logItems.forEach((li) => li.classList.add("pending"));
  fighters.forEach((f) => {
    f.classList.remove("acting");
    if (prev?.[f.dataset.side]?.[f.dataset.idx] > 0) f.classList.remove("down");
  });
  setHp(prev);
  arena.addEventListener("click", skip, { once: true });
  const total = events.reduce((sum, e) => sum + (FIGHT_STEP[e.kind] || 600), 0);
  // A turn's replay is squeezed into 8 s; a full replay (data-replay) plays at real pace, times the chosen speed.
  const capped = Math.min(1, 8000 / total);
  const pace = () => (root.dataset.replay ? 1 / (Number(root.dataset.speed) || 1) : capped);
  let lastSpecial = null;

  (async () => {
    if (fromStart && root.dataset.eyecatch && fx()) await eyecatch(root.dataset.eyecatch, root.dataset.eyecatchLabel);
    for (const [k, e] of events.entries()) {
      if (skipped || !root.isConnected) break;
      const text = e.text.replaceAll("`", "");
      const src = e.src && byPos.get(e.src.join(":"));
      const dst = e.dst && byPos.get(e.dst.join(":"));
      banner.className = `turn-banner play ${e.kind} ${critClass(e)}`;
      banner.textContent = text;
      logItems[k]?.classList.remove("pending");

      if (src && e.kind !== "stun") restart(src, e.kind === "special" || e.kind === "item" ? "cast" : "lunge");
      showSpot(src, text, e.kind === "special");
      if (e.kind === "special") { lastSpecial = [src, text]; restart(arena, "flash-special"); if (src && fx()) shout(src); }
      await wait(e.kind === "special" ? 450 * pace() : 200 * pace());

      if (dst && e.kind === "dodge") { restart(dst, "dodge"); pop(dst, "MISS", "miss"); }
      if (src && e.kind === "stun") pop(src, "STUNNED", "stun");
      if (e.kind === "terrain") { restart(arena, "flash-special"); setField(e.field); }
      if (e.kind === "sudden") restart(arena, "shake");
      if (e.kind === "crit") restart(arena, "shake");  // no flash: it was too much on every crit
      // Any HP change since the previous event gets a number; covers specials, items and poison ticks too.
      if (e.hp) {
        fighters.forEach((f) => {
          const before = prev?.[f.dataset.side]?.[f.dataset.idx], after = e.hp[f.dataset.side]?.[f.dataset.idx];
          if (before === undefined || after === undefined || Math.round(before) === Math.round(after)) return;
          const crit = e.kind === "crit" && f === dst;
          if (after < before) { restart(f, "hurt", ...(crit ? ["crit"] : [])); pop(f, `-${Math.round(before - after)}`, crit ? critClass(e) : ""); heavy(f, before - after); }
          else pop(f, `+${Math.round(after - before)}`, "miss");
          if (after <= 0 && before > 0) setTimeout(() => restart(f, "ko"), 300 * pace());
        });
        setHp(e.hp);
        prev = e.hp;
      } else if (dst && e.dmg) {
        restart(dst, "hurt", ...(e.kind === "crit" ? ["crit"] : []));
        pop(dst, `-${e.dmg}`, critClass(e));
        heavy(dst, e.dmg);
      }
      await wait(((FIGHT_STEP[e.kind] || 600) - (e.kind === "special" ? 450 : 200)) * pace());
    }

    if (!root.isConnected) return;
    arena.removeEventListener("click", skip);
    logItems.forEach((li) => li.classList.remove("pending"));
    root.querySelectorAll(".dmg-pop, .cry, .heavy-sfx").forEach((p) => p.remove());
    final.fighters.forEach(({ f, cls, width, num }) => {
      f.className = cls;
      f.querySelector(".hp i").style.width = width;
      f.querySelector(".hp-num").textContent = num;
    });
    [banner.className, banner.innerHTML] = final.banner;
    arena.classList.remove("flash-special", "shake");
    setField(finalField);
    // A special from this turn stays in the spotlight; otherwise show who acts next.
    if (lastSpecial && !skipped) {
      if (spotting !== lastSpecial[0] || !spot.classList.contains("special")) showSpot(lastSpecial[0], lastSpecial[1], true);
    } else {
      [spot.className, spotImg.src, spotImg.alt, spotName.textContent, spotLine.textContent] = final.spot;
      spotImg.onerror = null;
    }
    root.classList.remove("playing");
  })();
}
document.addEventListener("htmx:load", (e) => {
  const root = e.detail.elt.id === "fight" ? e.detail.elt : e.detail.elt.querySelector?.("#fight");
  if (root) playFight(root);
});
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") document.querySelector("#fight.playing .arena")?.click();
});
// Replays: watch again, and 1x / 2x / 4x speed (applies from the next event on).
document.addEventListener("click", (e) => {
  const again = e.target.closest("[data-replay-again]");
  if (again) {
    const root = again.closest("#fight");
    if (root && !root.classList.contains("playing")) {
      root.scrollIntoView({ behavior: "smooth", block: "start" });
      playFight(root);
    }
    return;
  }
  const speed = e.target.closest("[data-replay-speed]");
  if (!speed) return;
  const root = document.querySelector("#fight[data-replay]");
  if (root) root.dataset.speed = speed.dataset.replaySpeed;
  document.querySelectorAll("[data-replay-speed]").forEach((b) => {
    const on = b === speed;
    b.setAttribute("aria-checked", String(on));
    b.classList.toggle("gold", on);
    b.classList.toggle("ghost", !on);
  });
});

// Animated card art (a shiny from a GIF...) sits as a still poster in grids, so 200 cards don't all decode
// animations at once: it plays while the card is pointed at or focused, and in the pull cinematic.
function playArt(card, on) {
  const img = card?.querySelector("img[data-anim]");
  if (!img) return;
  if (on && !img.dataset.still) { img.dataset.still = img.src; img.src = img.dataset.anim; }
  else if (!on && img.dataset.still) { img.src = img.dataset.still; delete img.dataset.still; }
}
document.addEventListener("pointerover", (e) => playArt(e.target.closest?.(".card"), true));
document.addEventListener("pointerout", (e) => {
  const card = e.target.closest?.(".card");
  if (card && !card.contains(e.relatedTarget)) playArt(card, false);
});
document.addEventListener("focusin", (e) => playArt(e.target.closest?.(".card"), true));
document.addEventListener("focusout", (e) => {
  const card = e.target.closest?.(".card");
  if (card && !card.contains(e.relatedTarget)) playArt(card, false);
});

// Ranked roster and bans: pick exactly N ([data-pick-max]); [data-pick-unique] allows one copy of each stand.
function syncPicks(box) {
  const max = Number(box.dataset.pickMax);
  const boxes = [...box.querySelectorAll("input[type=checkbox]")];
  const on = boxes.filter((b) => b.checked);
  const taken = new Set(on.map((b) => b.dataset.stand));
  boxes.forEach((b) => {
    b.disabled = !b.checked && (on.length >= max || (box.hasAttribute("data-pick-unique") && taken.has(b.dataset.stand)));
    b.closest("label")?.classList.toggle("picked", b.checked);
  });
  const submit = box.closest("form")?.querySelector("[data-pick-submit]");
  if (submit) submit.disabled = on.length !== max;
}
document.addEventListener("change", (e) => {
  const box = e.target.closest("[data-pick-max]");
  if (box) syncPicks(box);
});
document.querySelectorAll("[data-pick-max]").forEach(syncPicks);
document.addEventListener("input", (e) => {
  if (!e.target.matches("[data-roster-search]")) return;
  const q = e.target.value.trim().toLocaleLowerCase();
  e.target.closest("form").querySelectorAll(".roster-list li").forEach((li) => { li.hidden = q && !li.dataset.name.includes(q); });
});

// Fight cosmetics: shiny and full-art stands fight with their own art, or everyone with the classic picture.
// Every portrait carries both, so the switch is instant; the choice is saved for the next fight screens.
document.addEventListener("click", (e) => {
  const btn = e.target.closest("[data-cosmetics-toggle]");
  if (!btn) return;
  const on = btn.getAttribute("aria-pressed") !== "true";
  btn.setAttribute("aria-pressed", String(on));
  btn.textContent = `✨ Cosmetics ${on ? "on" : "off"}`;
  const root = btn.closest("#fight") || document;
  root.querySelectorAll(".fighter[data-art-classic]").forEach((f) => {
    const d = f.dataset;
    f.classList.toggle("shiny", on && d.artShiny === "1");
    f.classList.toggle("fullart", on && d.artFull === "1");
    const hue = on && d.artShiny === "1" && d.artOwn !== "1";
    if (hue) d.hue = "1"; else delete d.hue;
    d.img = on ? d.artSpot : d.artClassic;
    const img = f.querySelector(".fighter-portrait img");
    if (img) img.src = on ? d.artPortrait : d.artClassic;
  });
  const spot = root.querySelector(".spotlight");
  const shown = spot && [...root.querySelectorAll(".fighter")].find((f) => f.dataset.name === spot.querySelector(".spotlight-name")?.textContent);
  if (shown && !spot.classList.contains("special")) {
    spot.querySelector(".spotlight-img").src = shown.dataset.img;
    spot.classList.toggle("shiny-art", shown.dataset.hue === "1");
  }
  const token = JSON.parse(document.body.getAttribute("hx-headers") || "{}")["X-CSRF-Token"] || "";
  fetch(btn.dataset.url, { method: "POST", headers: { "X-CSRF-Token": token }, body: new URLSearchParams({ on: on ? "1" : "0" }) })
    .catch(() => {});
});

// Fight effects on / off (battle cries, heavy-hit sound effects, the eyecatch): kept in the session like cosmetics.
document.addEventListener("click", (e) => {
  const btn = e.target.closest("[data-fx-toggle]");
  if (!btn) return;
  const on = btn.getAttribute("aria-pressed") !== "true";
  btn.setAttribute("aria-pressed", String(on));
  btn.textContent = `💥 Effects ${on ? "on" : "off"}`;
  const root = btn.closest("#fight");
  if (root) root.dataset.fx = on ? "1" : "0";
  const token = JSON.parse(document.body.getAttribute("hx-headers") || "{}")["X-CSRF-Token"] || "";
  fetch(btn.dataset.url, { method: "POST", headers: { "X-CSRF-Token": token }, body: new URLSearchParams({ on: on ? "1" : "0" }) })
    .catch(() => {});
});

// Desktop sidebar: groups open and close (remembered per player), and the whole bar collapses to an icon rail.
document.addEventListener("click", (e) => {
  const head = e.target.closest("[data-side-head]");
  if (head) {
    const group = head.closest("[data-side-group]");
    const open = group.classList.toggle("open");
    head.setAttribute("aria-expanded", String(open));
    try {
      const saved = JSON.parse(localStorage.getItem("side-open") || "{}");
      saved[group.dataset.sideGroup] = open;
      localStorage.setItem("side-open", JSON.stringify(saved));
    } catch (err) { /* storage blocked */ }
    return;
  }
  const toggle = e.target.closest("[data-side-toggle]");
  if (toggle) {
    const mini = document.documentElement.classList.toggle("side-mini");
    toggle.setAttribute("aria-label", mini ? "Expand the sidebar" : "Collapse the sidebar");
    toggle.title = toggle.getAttribute("aria-label");
    try { localStorage.setItem("side-mini", mini ? "1" : "0"); } catch (err) { /* storage blocked */ }
  }
});

// New-player tour: spotlight each nav tab (desktop bar or mobile dock) with a card saying why it matters.
(() => {
  const tour = document.getElementById("tour");
  const data = document.getElementById("tour-steps");
  if (!tour || !data) return;
  const steps = JSON.parse(data.textContent);
  const spot = tour.querySelector(".tour-spot");
  const card = tour.querySelector(".tour-card");
  const $ = (sel) => tour.querySelector(sel);
  let i = 0;

  const targetOf = (step) => {
    for (const key of step.target || []) {
      const el = [...document.querySelectorAll(`[data-tour="${key}"]`)].find((e) => e.offsetParent !== null && e.getClientRects().length);
      if (el) return el;
    }
    return null;
  };
  const place = () => {
    const el = targetOf(steps[i]);
    if (!el) {  // no target: the spotlight shrinks to the middle, ringless (never toggled hidden: see .tour-spot)
      spot.classList.add("is-off");
      Object.assign(spot.style, { left: "50%", top: "50%", width: "0px", height: "0px" });
      Object.assign(card.style, { left: "50%", top: "50%", bottom: "auto", transform: "translate(-50%, -50%)" });
      return;
    }
    const r = el.getBoundingClientRect();
    spot.classList.remove("is-off");
    Object.assign(spot.style, { left: `${r.left - 6}px`, top: `${r.top - 6}px`, width: `${r.width + 12}px`, height: `${r.height + 12}px` });
    const w = Math.min(340, innerWidth - 24);
    const left = Math.max(12, Math.min(innerWidth - w - 12, r.left + r.width / 2 - w / 2));
    const below = r.top < innerHeight / 2;
    Object.assign(card.style, { left: `${left}px`, transform: "none", top: below ? `${r.bottom + 16}px` : "auto",
                                bottom: below ? "auto" : `${innerHeight - r.top + 16}px` });
  };
  const show = () => {
    const step = steps[i];
    $(".tour-count").textContent = `${i + 1} / ${steps.length}`;
    $("#tour-title").textContent = step.title;
    $(".tour-text").textContent = step.text;
    $("[data-tour-back]").hidden = i === 0;
    const last = i === steps.length - 1;
    $("[data-tour-next]").hidden = last;
    for (const [sel, key] of [["[data-tour-cta]", "cta"], ["[data-tour-cta2]", "cta2"]]) {
      const a = $(sel);
      a.hidden = !(last && step[key]);
      if (step[key]) { a.href = step[key][0]; a.textContent = step[key][1]; }
    }
    card.style.bottom = "auto";
    place();
    (last ? $("[data-tour-cta2]") : $("[data-tour-next]")).focus({ preventScroll: true });
  };
  // Returns the "done" request so a link can wait for it: navigating at once used to cancel it,
  // and the next page started the tour all over again.
  const finish = () => {
    tour.hidden = true;
    document.body.classList.remove("touring");
    try { sessionStorage.setItem("tour-done", "1"); } catch (err) { /* storage blocked */ }
    if (location.search.includes("tour=1")) history.replaceState(null, "", location.pathname);
    const token = JSON.parse(document.body.getAttribute("hx-headers") || "{}")["X-CSRF-Token"];
    return fetch(tour.dataset.done, { method: "POST", keepalive: true, headers: { "X-CSRF-Token": token || "" } }).catch(() => {});
  };
  const start = () => { i = 0; tour.hidden = false; document.body.classList.add("touring"); show(); };

  tour.addEventListener("click", (e) => {
    if (e.target.closest("[data-tour-next]")) { i = Math.min(steps.length - 1, i + 1); show(); }
    else if (e.target.closest("[data-tour-back]")) { i = Math.max(0, i - 1); show(); }
    else if (e.target.closest("[data-tour-skip]")) finish();
    else if (e.target.closest("[data-tour-cta], [data-tour-cta2]")) {
      e.preventDefault();
      const href = e.target.closest("a").href;
      finish().finally(() => { location.href = href; });
    }
  });
  document.addEventListener("keydown", (e) => {
    if (tour.hidden) return;
    if (e.key === "Escape") finish();
    else if (e.key === "ArrowRight" && i < steps.length - 1) { i += 1; show(); }
    else if (e.key === "ArrowLeft" && i > 0) { i -= 1; show(); }
  });
  addEventListener("resize", () => { if (!tour.hidden) place(); });
  document.addEventListener("click", (e) => {
    if (e.target.closest("[data-tour-start]")) { e.preventDefault(); document.getElementById("nav-sheet")?.close(); closeNavDrops(); start(); }
  });
  let doneThisSession = false;
  try { doneThisSession = sessionStorage.getItem("tour-done") === "1"; } catch (err) { /* storage blocked */ }
  if (new URLSearchParams(location.search).get("tour") === "1") start();
  else if (tour.dataset.autostart === "1") {
    if (doneThisSession) finish();  // the server missed the last "done": tell it again, quietly
    else start();
  }
})();

// Cooldown notices count down live and reload the page once the wait is over.
function cooldownReload(root) {
  root.querySelectorAll("[data-reload-in]").forEach((el) => {
    if (el.dataset.ticking) return;
    el.dataset.ticking = "1";
    const end = Date.now() + Number(el.dataset.reloadIn) * 1000;
    const out = el.querySelector("[data-countdown]");
    const tick = () => {
      const left = Math.max(0, Math.round((end - Date.now()) / 1000));
      const h = Math.floor(left / 3600), m = Math.floor(left % 3600 / 60), sec = left % 60;  // same wording as fmt_delta
      if (out) out.textContent = h ? `${h} h ${String(m).padStart(2, "0")} min`
        : m ? `${m} min ${String(sec).padStart(2, "0")} s` : `${sec} s`;
      if (left <= 0) location.reload();
      else setTimeout(tick, 1000);
    };
    tick();
  });
}
cooldownReload(document);
document.addEventListener("htmx:load", (e) => cooldownReload(e.detail.elt));

// Timed progress bars (Crusaders' Journey): fill live from data-progress-start to data-progress-end (unix seconds).
function liveProgress(root) {
  const bars = [...root.querySelectorAll("[data-progress-end]")].filter((el) => !el.dataset.live);
  if (!bars.length) return;
  const clock = document.querySelector("[data-server-now]");  // trust the server's clock, not the device's
  const skew = clock ? Date.now() / 1000 - Number(clock.dataset.serverNow) : 0;
  const tick = () => {
    const now = Date.now() / 1000 - skew;
    bars.forEach((el) => {
      const start = Number(el.dataset.progressStart), end = Number(el.dataset.progressEnd);
      const pct = Math.min(100, Math.max(0, (100 * (now - start)) / Math.max(1, end - start)));
      el.firstElementChild.style.width = `${pct}%`;
    });
    if (bars.some((el) => el.isConnected)) setTimeout(tick, 1000);
  };
  bars.forEach((el) => (el.dataset.live = "1"));
  tick();
}
liveProgress(document);
document.addEventListener("htmx:load", (e) => liveProgress(e.detail.elt));

// Auction sell form: show only the fields of the chosen sale type (without JS both show; the server reads "mode").
function saleForms(root) {
  root.querySelectorAll("[data-sale-form]").forEach((form) => {
    const sync = () => { form.dataset.active = form.querySelector("input[name=mode]:checked")?.value || "fixed"; };
    form.querySelectorAll("input[name=mode]").forEach((r) => r.addEventListener("change", sync));
    sync();
  });
}
saleForms(document);
document.addEventListener("htmx:load", (e) => saleForms(e.detail.elt));

// Team simulator: the player field only matters when "Another player's team" is picked.
document.addEventListener("change", (e) => {
  const vs = e.target.closest("[data-sim-vs]");
  if (!vs) return;
  const field = vs.form.querySelector("[data-sim-player]");
  field.hidden = vs.value !== "player";
  if (!field.hidden) field.querySelector("input").focus();
});

// Chats (gang, global, private, raid): follow new messages (unless you scrolled up to read), clear the box after
// a successful send. Every chat box is a [data-chat] swapped whole; its form targets it by id.
(() => {
  const follow = new Map();
  const toBottom = (box) => { const l = box?.querySelector("[data-chat-list]"); if (l) l.scrollTop = l.scrollHeight; };
  document.querySelectorAll("[data-chat]").forEach(toBottom);
  document.addEventListener("htmx:load", (e) => { if (e.detail.elt?.matches?.("[data-chat]")) toBottom(e.detail.elt); });  // a chat that just loaded (the bubble)
  document.addEventListener("htmx:beforeSwap", (e) => {
    const box = e.detail.target;
    if (!box?.matches?.("[data-chat]")) return;
    const l = box.querySelector("[data-chat-list]");
    follow.set(box.id, !l || l.scrollHeight - l.scrollTop - l.clientHeight < 60 || e.detail.requestConfig?.verb === "post");
  });
  document.addEventListener("htmx:afterSettle", (e) => {
    const id = e.detail.target?.id;
    if (!id || !follow.has(id)) return;
    if (follow.get(id)) toBottom(document.getElementById(id));
  });
  document.addEventListener("htmx:afterRequest", (e) => {
    const form = e.detail.elt.closest?.("[data-chat-form]");
    if (!form || !e.detail.successful) return;
    const box = document.querySelector(form.getAttribute("hx-target"));
    if (!box?.querySelector("[data-chat-error]")?.dataset.chatError) {
      form.reset();
      form.querySelector("[name=text]")?.focus();
    }
  });
  // Enter sends, Shift+Enter makes a new line
  document.addEventListener("keydown", (e) => {
    if (e.key !== "Enter" || e.shiftKey || e.isComposing || !e.target.matches?.("[data-chat-form] textarea")) return;
    e.preventDefault();
    e.target.form.requestSubmit();
  });
})();

// Dungeon: arrow keys / WASD press the matching move button.
document.addEventListener("keydown", (e) => {
  if (e.target.closest?.("input, textarea, select") || e.ctrlKey || e.metaKey || e.altKey) return;
  const dir = {ArrowUp: "up", ArrowDown: "down", ArrowLeft: "left", ArrowRight: "right", w: "up", s: "down", a: "left", d: "right"}[e.key];
  const btn = dir && document.querySelector(`.move-button[data-move="${dir}"]:not(:disabled)`);
  if (btn) { e.preventDefault(); btn.click(); }
});

// Training ground: a pick list that stops at its max (data-pick-max on each checkbox).
document.addEventListener("change", (e) => {
  const box = e.target.closest?.("input[type=checkbox][data-pick-max]");
  if (!box || !box.checked) return;
  const all = [...document.querySelectorAll(`input[name="${box.name}"][data-pick-max]`)];
  if (all.filter((b) => b.checked).length > Number(box.dataset.pickMax)) box.checked = false;
});

// Web push. A subscription is tied to the VAPID key it was made with: after the server's keys change, push services
// answer 401 "VAPID public key mismatch" for it. So every page of a player with push on (the push-key meta) checks
// this browser's subscription and swaps an outdated one for a fresh one (permission is already granted: no prompt).
const pushB64 = (s) => { const p = "=".repeat((4 - (s.length % 4)) % 4);
  const raw = atob((s + p).replace(/-/g, "+").replace(/_/g, "/")); return Uint8Array.from(raw, (c) => c.charCodeAt(0)); };
const pushPost = (url, body) => fetch(url, { method: "POST", body: JSON.stringify(body || {}), headers: { "Content-Type": "application/json",
  "X-CSRF-Token": JSON.parse(document.body.getAttribute("hx-headers") || "{}")["X-CSRF-Token"] || "" } });
const pushSameKey = (sub, key) => {
  const k = sub.options && sub.options.applicationServerKey;
  if (!k) return true;  // this browser doesn't say: keep it
  const a = new Uint8Array(k), b = pushB64(key);
  return a.length === b.length && a.every((x, i) => x === b[i]);
};
// This browser's subscription made with `key` (renewed if it was made with another one), or null. urls: {sub, unsub}.
// The browser's push subscription, as a cookie the server reads to skip pushes to the device in use (push.py).
async function pushDevice(sub) {
  try {
    if (!sub) { document.cookie = "pdev=; path=/; max-age=0; SameSite=Lax"; return; }
    const hash = await crypto.subtle.digest("SHA-1", new TextEncoder().encode(sub.endpoint));
    const hex = [...new Uint8Array(hash)].map((b) => b.toString(16).padStart(2, "0")).join("");
    document.cookie = `pdev=${hex}; path=/; max-age=31536000; SameSite=Lax; Secure`;
  } catch (e) { /* no SubtleCrypto (plain http): pushes then follow the old rule */ }
}
async function pushSync(key, urls, report) {
  const reg = await navigator.serviceWorker.ready;
  let sub = await reg.pushManager.getSubscription();
  if (!sub) return null;
  if (!pushSameKey(sub, key)) {
    await pushPost(urls.unsub, { endpoint: sub.endpoint }).catch(() => {});
    await sub.unsubscribe();
    sub = await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: pushB64(key) });
    report = true;
  }
  if (report) await pushPost(urls.sub, sub.toJSON());
  pushDevice(sub);
  return sub;
}
(() => {
  const meta = document.querySelector('meta[name="push-key"]');
  if (!meta || document.querySelector("[data-push]") || !("serviceWorker" in navigator) || !("PushManager" in window)
      || !("Notification" in window) || Notification.permission !== "granted") return;
  pushSync(meta.content, { sub: meta.dataset.sub, unsub: meta.dataset.unsub }, false).catch(() => {});
})();

// The inbox's "Notifications on this device" card (data-push): turn push on or off for this browser, send a test.
(() => {
  const card = document.querySelector("[data-push]");
  if (!card) return;
  const $ = (s) => card.querySelector(s);
  const status = $("[data-push-status]");
  const supported = "serviceWorker" in navigator && "PushManager" in window && "Notification" in window;
  const ios = /iphone|ipad|ipod/i.test(navigator.userAgent) && !matchMedia("(display-mode: standalone)").matches;
  const urls = { sub: card.dataset.sub, unsub: card.dataset.unsub };
  const show = (on, text) => {
    $("[data-push-on]").hidden = on; $("[data-push-off]").hidden = !on; $("[data-push-test]").hidden = !on;
    if (text) status.textContent = text;
  };
  if (!supported) {
    $("[data-push-on]").hidden = true;
    $("[data-push-ios]").hidden = !ios;
    status.textContent = ios ? "Your browser can't receive notifications from a tab." : "This browser can't receive push notifications.";
    return;
  }
  pushSync(card.dataset.key, urls, true).then((sub) => {
    if (sub) show(true, "On for this device.");
    else if (Notification.permission === "denied") show(false, "Notifications are blocked for this site in your browser settings.");
  }).catch(() => show(false, "Notifications stopped working on this device: turn them on again."));
  $("[data-push-on]").addEventListener("click", async () => {
    try {
      if ((await Notification.requestPermission()) !== "granted") return show(false, "Permission refused: allow notifications for this site to turn them on.");
      const reg = await navigator.serviceWorker.ready;
      const old = await reg.pushManager.getSubscription();
      if (old && !pushSameKey(old, card.dataset.key)) await old.unsubscribe();
      const sub = await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: pushB64(card.dataset.key) });
      const res = await pushPost(urls.sub, sub.toJSON());
      if (res.ok) pushDevice(sub);
      show(res.ok, res.ok ? "On for this device." : "The server refused this device. Try again later.");
    } catch (err) { show(false, "Couldn't turn notifications on in this browser."); }
  });
  $("[data-push-off]").addEventListener("click", async () => {
    const reg = await navigator.serviceWorker.ready;
    const sub = await reg.pushManager.getSubscription();
    if (sub) { await pushPost(urls.unsub, { endpoint: sub.endpoint }); await sub.unsubscribe(); }
    pushDevice(null);
    show(false, "Off for this device.");
  });
  $("[data-push-test]").addEventListener("click", () => pushPost(card.dataset.test));
})();

// Click to copy (the co-op lobby code).
document.addEventListener("click", (e) => {
  const el = e.target.closest("[data-copy]");
  if (!el || !navigator.clipboard) return;
  navigator.clipboard.writeText(el.dataset.copy).then(() => { const t = el.textContent; el.textContent = "Copied!"; setTimeout(() => { el.textContent = t; }, 1200); });
});

// Stand / item picker (templates/partials/picker.html): a big trigger that shows the choice and a sheet with search,
// group tabs, rarity filters and portrait tiles. Single pick closes on tap; multi pick numbers the order (ranked uses
// it) and stops at data-sp-max; data-sp-unique allows one copy of each stand. The choice lives in hidden inputs.
(() => {
  const RAR = { R: "common", SR: "rare", SSR: "epic", UR: "legend", LR: "mythic" };
  const GROUP = { mine: "My stands", any: "Any stand", item: "Items", gear: "Gear", usable: "Consumables & materials" };
  const FALLBACK = "/static/img/stand-fallback.svg";
  // options are parsed once per data element: a re-rendered section brings fresh ones
  const load = (sel) => {
    const el = document.querySelector(sel);
    if (!el) return { opts: [], byV: new Map() };
    if (!el._sp) {
      const opts = JSON.parse(el.textContent);
      el._sp = { opts, byV: new Map(opts.map((o) => [o.v, o])) };
    }
    return el._sp;
  };
  const ESC = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ESC[c]);
  const fold = (s) => String(s || "").normalize("NFKD").replace(/[̀-ͯ]/g, "").toLowerCase();
  const thumb = (o) => o.img
    ? `<img src="${esc(o.img)}" alt="" loading="lazy" decoding="async" data-fallback="${FALLBACK}">`
    : `<span class="sp-emoji" aria-hidden="true">${esc(o.e || "◈")}</span>`;
  // in quantity mode (data-sp-qty) an input holds "value:count"; values() gives the values, counts() the counts
  const qtyMode = (sp) => "spQty" in sp.dataset;
  const values = (sp) => [...sp.querySelector(".sp-inputs").children].map((i) => (qtyMode(sp) ? i.value.split(":")[0] : i.value));
  const counts = (sp) => Object.fromEntries([...sp.querySelector(".sp-inputs").children].map((i) => {
    const [v, q] = i.value.split(":");
    return [v, Math.max(1, Number(q) || 1)];
  }));
  const max = (sp) => Number(sp.dataset.spMax) || 1;
  // broken pictures fall back to the stand silhouette (no inline handlers in the generated markup)
  document.addEventListener("error", (e) => {
    const img = e.target;
    if (img.tagName === "IMG" && img.dataset.fallback && img.src.indexOf(img.dataset.fallback) < 0) img.src = img.dataset.fallback;
  }, true);

  const render = (sp) => {
    const { byV } = load(sp.dataset.spSource);
    const picked = values(sp).map((v) => byV.get(v)).filter(Boolean);
    const btn = sp.querySelector("[data-sp-open]");
    sp.classList.toggle("is-set", picked.length > 0);
    if (!picked.length) {
      btn.innerHTML = `<span class="sp-plus" aria-hidden="true">＋</span><span class="sp-placeholder">${esc(sp.dataset.spPlaceholder)}</span>`;
    } else if (max(sp) === 1) {
      const o = picked[0];
      btn.innerHTML = `<span class="sp-face ${RAR[o.r] || ""}">${thumb(o)}</span><span class="sp-text"><strong>${esc(o.n)}</strong>`
        + `<small>${o.r ? `<span class="rar-tag ${RAR[o.r]}">${o.r}</span> ` : ""}${esc(o.m || "")}</small></span><span class="sp-change">Change</span>`;
    } else {
      const items = sp.dataset.spKind === "item", q = counts(sp);
      // stands show their pick order (ranked uses it); items show how many go (trades) or nothing
      const badge = (o, i) => (qtyMode(sp) ? `<b>×${q[o.v] || 1}</b>` : items ? "" : `<b>${i + 1}</b>`);
      btn.innerHTML = `<span class="sp-chips">${picked.map((o, i) => `<span class="sp-chip ${RAR[o.r] || ""}" title="${esc(o.n)}">`
        + `${thumb(o)}${badge(o, i)}<span>${esc(o.n)}</span></span>`).join("")}</span>`
        + `<span class="sp-change">${items ? "Change" : `${picked.length}/${max(sp)} · Change`}</span>`;
    }
    btn.setAttribute("aria-label", `${sp.dataset.spTitle}: ${picked.map((o) => o.n).join(", ") || "none"}`);
    const list = sp.querySelector("[data-sp-qty-list]");
    if (list) {  // a row per picked item: how many, up to what's owned
      const q = counts(sp);
      list.innerHTML = picked.map((o) => `<div class="sp-qty-row" data-v="${esc(o.v)}"><span class="sp-qty-art">${thumb(o)}</span>
        <span class="sp-qty-name">${esc(o.n)}</span>
        <span class="sp-stepper"><button type="button" data-sp-step="-1" aria-label="One fewer ${esc(o.n)}" ${q[o.v] <= 1 ? "disabled" : ""}>−</button>
          <b>${q[o.v]}</b><small>/ ${o.q || 1}</small>
          <button type="button" data-sp-step="1" aria-label="One more ${esc(o.n)}" ${q[o.v] >= (o.q || 1) ? "disabled" : ""}>+</button></span>
        <button type="button" class="sp-qty-x" data-sp-step="0" aria-label="Remove ${esc(o.n)}">✕</button></div>`).join("");
    }
  };

  const commit = (sp, vals, qty) => {
    const box = sp.querySelector(".sp-inputs");
    const q = qty || (qtyMode(sp) ? counts(sp) : {});
    box.replaceChildren(...vals.map((v) => Object.assign(document.createElement("input"), {
      type: "hidden", name: sp.dataset.spName, value: qtyMode(sp) ? `${v}:${q[v] || 1}` : v })));
    render(sp);
    const { byV } = load(sp.dataset.spSource);
    sp.dispatchEvent(new CustomEvent("sp:change", { bubbles: true, detail: { values: vals, options: vals.map((v) => byV.get(v)) } }));
    sp.dispatchEvent(new Event("change", { bubbles: true }));
    sp.classList.remove("sp-missing");
    const form = sp.closest("form");
    if ("spSubmit" in sp.dataset && form && vals.length) form.requestSubmit();  // forms that act on the pick
  };

  let dlg, state;
  const build = () => {
    dlg = document.createElement("dialog");
    dlg.className = "sp-dialog";
    dlg.innerHTML = `<div class="sp-sheet">
      <header class="sp-head"><h2 class="sp-title"></h2><span class="sp-count" aria-live="polite"></span>
        <button type="button" class="sp-x" data-sp-close aria-label="Close">✕</button></header>
      <div class="sp-tools"><input type="search" class="sp-search" placeholder="Search by name" autocomplete="off" spellcheck="false" aria-label="Search">
        <div class="sp-tabs" role="tablist"></div><div class="sp-rar" role="group" aria-label="Rarity"></div></div>
      <div class="sp-grid" role="listbox"></div>
      <footer class="sp-foot"><button type="button" class="btn ghost small" data-sp-clear>Clear</button>
        <button type="button" class="btn gold" data-sp-close>Done</button></footer></div>`;
    document.body.appendChild(dlg);
    dlg.addEventListener("click", (e) => {
      if (e.target === dlg || e.target.closest("[data-sp-close]")) return dlg.close();
      if (e.target.closest("[data-sp-clear]")) { state.sel = []; commit(state.sp, []); return draw(); }
      const tab = e.target.closest("[data-group]");
      if (tab) { state.group = tab.dataset.group; return draw(); }
      const rar = e.target.closest("[data-rar]");
      if (rar) { state.rar = rar.dataset.rar; return draw(); }
      const tile = e.target.closest(".sp-tile");
      if (tile && !tile.disabled) pick(tile.dataset.v);
    });
    dlg.querySelector(".sp-search").addEventListener("input", (e) => { state.q = fold(e.target.value.trim()); draw(); });
    dlg.addEventListener("close", () => { if (state) state.sp.querySelector("[data-sp-open]").focus({ preventScroll: true }); });
  };

  const pick = (v) => {
    const sp = state.sp, m = max(sp);
    if (m === 1) { state.sel = v === "" ? [] : [v]; commit(sp, state.sel); return dlg.close(); }
    const i = state.sel.indexOf(v);
    if (i >= 0) state.sel.splice(i, 1);
    else if (state.sel.length < m) state.sel.push(v);
    commit(sp, state.sel.slice());
    draw();
  };

  const draw = () => {
    const sp = state.sp, { opts, byV } = load(sp.dataset.spSource), m = max(sp);
    const groups = [...new Set(opts.map((o) => o.g))];
    dlg.querySelector(".sp-tabs").innerHTML = groups.length > 1 ? groups.map((g) =>
      `<button type="button" role="tab" class="filter-chip" data-group="${g}" aria-selected="${g === state.group}" aria-pressed="${g === state.group}">`
      + `${GROUP[g] || g} <small>${opts.filter((o) => o.g === g).length}</small></button>`).join("") : "";
    const inGroup = opts.filter((o) => groups.length < 2 || o.g === state.group);
    const rars = ["R", "SR", "SSR", "UR", "LR"].filter((r) => inGroup.some((o) => o.r === r));
    dlg.querySelector(".sp-rar").innerHTML = rars.length > 1 ? ["all", ...rars].map((r) =>
      `<button type="button" class="filter-chip" data-rar="${r}" aria-pressed="${r === state.rar}">${r === "all" ? "All" : r}</button>`).join("") : "";
    const takenIds = new Set(state.sel.map((v) => byV.get(v) && byV.get(v).id));
    const shown = inGroup.filter((o) => (state.rar === "all" || o.r === state.rar)
      && (!state.q || fold(o.n).includes(state.q) || fold(o.m).includes(state.q)));
    const full = m > 1 && state.sel.length >= m;
    const tiles = shown.map((o) => {
      const at = state.sel.indexOf(o.v), on = at >= 0;
      const dupe = !on && "spUnique" in sp.dataset && takenIds.has(o.id);
      const why = o.x || (dupe ? "A copy is already picked" : "");
      const off = !on && (why || full);
      return `<button type="button" class="sp-tile ${RAR[o.r] || "item"}${on ? " is-on" : ""}${off ? " is-off" : ""}" data-v="${esc(o.v)}"
        role="option" aria-selected="${on}" ${why ? "disabled" : ""}>
        <span class="sp-tile-art">${thumb(o)}${on ? `<b class="sp-mark">${qtyMode(sp) ? "×" + (counts(sp)[o.v] || 1) : m > 1 ? at + 1 : "✓"}</b>` : ""}
          ${o.sh ? '<i class="sp-badge" title="Shiny">✨</i>' : ""}${o.t ? '<i class="sp-badge sp-taunt" title="Taunt">🎯</i>' : ""}</span>
        <span class="sp-tile-name">${esc(o.n)}</span>
        <small>${o.r ? `<span class="rar-tag ${RAR[o.r]}">${o.r}</span> ` : ""}${esc(o.m || "")}</small>
        ${why ? `<em class="sp-why">${esc(why)}</em>` : ""}</button>`;
    });
    if (sp.dataset.spEmpty && m === 1 && !state.q) {  // the empty choice, unless searching
      tiles.unshift(`<button type="button" class="sp-tile sp-none${state.sel.length ? "" : " is-on"}" data-v="">
        <span class="sp-tile-art"><span class="sp-emoji">∅</span></span><span class="sp-tile-name">${esc(sp.dataset.spEmpty)}</span><small>No stand here</small></button>`);
    }
    dlg.querySelector(".sp-grid").innerHTML = tiles.join("") || `<p class="muted sp-nothing">Nothing matches.</p>`;
    dlg.querySelector(".sp-count").textContent = m > 1 ? `${state.sel.length}/${m} picked` : "";
    dlg.querySelector(".sp-foot").hidden = m === 1;
  };

  const open = (sp) => {
    if (!dlg) build();
    const { byV, opts } = load(sp.dataset.spSource);
    const sel = values(sp).filter((v) => byV.has(v));
    const first = byV.get(sel[0]);
    state = { sp, sel, q: "", rar: "all", group: first ? first.g : (opts[0] && opts[0].g) };
    dlg.querySelector(".sp-title").textContent = sp.dataset.spTitle;
    dlg.querySelector(".sp-search").value = "";
    draw();
    dlg.showModal();
    if (matchMedia("(pointer: fine)").matches) dlg.querySelector(".sp-search").focus();
    dlg.querySelector(".sp-grid").scrollTop = 0;
  };

  const init = (root) => {
    if (!root || !root.querySelectorAll) return;
    const list = root.matches && root.matches("[data-sp]") ? [root] : [];
    list.concat([...root.querySelectorAll("[data-sp]")]).forEach((sp) => {
      if (sp.dataset.spReady) return;
      sp.dataset.spReady = "1";
      render(sp);
    });
  };
  // quantity steppers (− / + / ✕) under a picker in quantity mode
  document.addEventListener("click", (e) => {
    const step = e.target.closest("[data-sp-step]");
    if (!step) return;
    const sp = step.closest("[data-sp]"), v = step.closest("[data-v]").dataset.v;
    const { byV } = load(sp.dataset.spSource);
    const q = counts(sp), d = Number(step.dataset.spStep);
    const vals = values(sp).filter((x) => d !== 0 || x !== v);
    if (d) q[v] = Math.min(byV.get(v)?.q || 1, Math.max(1, (q[v] || 1) + d));
    commit(sp, vals, q);
  });
  // a required picker left empty stops its form and opens itself
  document.addEventListener("submit", (e) => {
    const empty = [...e.target.querySelectorAll("[data-sp][data-sp-required]")].find((sp) => !values(sp).length);
    if (!empty) return;
    e.preventDefault();
    e.stopImmediatePropagation();
    empty.classList.add("sp-missing");
    open(empty);
  }, true);
  document.addEventListener("click", (e) => {
    const btn = e.target.closest("[data-sp-open]");
    if (btn && !btn.closest("[disabled]")) { e.preventDefault(); open(btn.closest("[data-sp]")); }
  });
  init(document);
  document.addEventListener("htmx:load", (e) => init(e.detail.elt));
  window.stfuPicker = { set: (sp, vals) => commit(sp, vals) };  // e.g. the planner's suggestions
})();
