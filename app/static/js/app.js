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

// Pull reveal: tap a card to flip it, or reveal all in sequence (rarest last).
function flip(card) {
  if (card.classList.contains("flipped")) return;
  card.classList.add("flipped");
  card.setAttribute("aria-label", "Revealed");
  const batch = card.closest("[data-pull]");
  if (batch && !batch.querySelector("[data-flip]:not(.flipped)")) {
    batch.querySelector("[data-pull-summary]").hidden = false;
    batch.querySelector("[data-reveal-all]").hidden = true;
    batch.querySelectorAll("[data-after-reveal]").forEach((x) => { x.hidden = false; });
    batch.querySelector("[data-cinematic]")?.setAttribute("hidden", "");
    document.dispatchEvent(new CustomEvent("pull:revealed"));
  }
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
      <div class="cine-bg"></div><div class="cine-rays"></div><div class="cine-flash"></div>
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
    el.querySelector(".cine-title").textContent = TITLE[r] || "";
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
      <span class="cine-rar r-${r}">${r}</span>${src.dataset.new === "1" ? '<span class="new-tag">NEW</span>' : ""}
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
  // a fresh pull opens straight into the cinematic when the player chose it
  document.addEventListener("htmx:afterSwap", (e) => {
    if (e.detail.target.id !== "pull-result") return;
    const batch = e.detail.target.querySelector("[data-pull]");
    if (!batch) return document.dispatchEvent(new CustomEvent("pull:revealed"));  // an error: let held toasts out
    if (batch.dataset.cineSeen) return;  // htmx fires this once per out-of-band swap too
    batch.dataset.cineSeen = "1";
    syncBox(batch);
    if (pref()) start(batch);  // at once, before the grid ever paints
    else delete batch.dataset.cineWait;
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

// Scroll a fresh pull result into view.
document.addEventListener("htmx:afterSwap", (e) => {
  if (["use-result", "pull-result", "sim-result"].includes(e.detail.target.id) && e.detail.target.firstElementChild) {
    e.detail.target.scrollIntoView({ behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth", block: "start" });
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
  if (e.target.matches("[data-forge-lock]")) forgeLocks(e.target.closest("[data-forge-form]"));
});
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

// Pop-up toasts: rendered on full pages, or sent with an HTMX response as HX-Trigger {"toast": [...]}.
(() => {
  const box = () => document.getElementById("toasts");
  const arm = (el) => {
    if (el.dataset.armed) return;
    el.dataset.armed = "1";
    setTimeout(() => el.classList.add("leaving"), 7000);
    setTimeout(() => el.remove(), 7600);
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
      const a = document.createElement("a");
      a.className = `toast-pop ${t.kind || ""}`;
      a.href = t.url || "#";
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
    const bell = document.querySelector(".bell");
    if (bell && list.length) bell.classList.add("has-news", "ring");
  }
  document.addEventListener("click", (e) => {
    const x = e.target.closest("[data-toast-x]");
    if (x) { e.preventDefault(); x.closest("[data-toast]").remove(); }
  });
})();

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

// Fight replay: a fresh turn arrives with its log events as JSON. Rewind the bars to before the turn,
// then play each event (lunge, hit, damage numbers, special GIF in the spotlight) and land on the server's final state.
const FIGHT_STEP = { hit: 700, crit: 950, dodge: 700, special: 1900, item: 1000, info: 600, stun: 700, terrain: 1300, sudden: 900 };
function playFight(root) {
  const data = root.querySelector(".fight-replay");
  if (!data || matchMedia("(prefers-reduced-motion: reduce)").matches) return;
  const { start, fromStart, events } = JSON.parse(data.textContent);
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
  const EFFECTS = ["lunge", "hurt", "crit", "dodge", "cast", "swap", "flash-crit", "flash-special", "shake"];
  const restart = (el, ...cls) => { el.classList.remove(...EFFECTS, ...cls); void el.offsetWidth; el.classList.add(...cls); };

  // The server-rendered end state, restored when the replay finishes or is skipped.
  const final = {
    fighters: fighters.map((f) => ({ f, cls: f.className, width: f.querySelector(".hp i").style.width, num: f.querySelector(".hp-num").textContent })),
    banner: [banner.className, banner.innerHTML],
    spot: [spot.className, spotImg.src, spotImg.alt, spotName.textContent, spotLine.textContent],
  };

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
  const pop = (f, text, cls) => {
    const p = document.createElement("span");
    p.className = `dmg-pop ${cls}`;
    p.textContent = text;
    p.setAttribute("aria-hidden", "true");
    f.appendChild(p);
    p.addEventListener("animationend", () => p.remove());
  };
  const showSpot = (f, line, special) => {
    if (!f) return;
    spot.classList.toggle("special", special);
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
    for (const [k, e] of events.entries()) {
      if (skipped || !root.isConnected) break;
      const text = e.text.replaceAll("`", "");
      const src = e.src && byPos.get(e.src.join(":"));
      const dst = e.dst && byPos.get(e.dst.join(":"));
      banner.className = `turn-banner play ${e.kind}`;
      banner.textContent = text;
      logItems[k]?.classList.remove("pending");

      if (src && e.kind !== "stun") restart(src, e.kind === "special" || e.kind === "item" ? "cast" : "lunge");
      showSpot(src, text, e.kind === "special");
      if (e.kind === "special") { lastSpecial = [src, text]; restart(arena, "flash-special"); }
      await wait(e.kind === "special" ? 450 * pace() : 200 * pace());

      if (dst && e.kind === "dodge") { restart(dst, "dodge"); pop(dst, "MISS", "miss"); }
      if (src && e.kind === "stun") pop(src, "STUNNED", "stun");
      if (e.kind === "terrain") restart(arena, "flash-special");
      if (e.kind === "sudden") restart(arena, "shake");
      if (e.kind === "crit") restart(arena, "flash-crit", "shake");
      // Any HP change since the previous event gets a number; covers specials, items and poison ticks too.
      if (e.hp) {
        fighters.forEach((f) => {
          const before = prev?.[f.dataset.side]?.[f.dataset.idx], after = e.hp[f.dataset.side]?.[f.dataset.idx];
          if (before === undefined || after === undefined || Math.round(before) === Math.round(after)) return;
          const crit = e.kind === "crit" && f === dst;
          if (after < before) { restart(f, "hurt", ...(crit ? ["crit"] : [])); pop(f, `-${Math.round(before - after)}`, crit ? "crit" : ""); }
          else pop(f, `+${Math.round(after - before)}`, "miss");
          if (after <= 0 && before > 0) setTimeout(() => restart(f, "ko"), 300 * pace());
        });
        setHp(e.hp);
        prev = e.hp;
      } else if (dst && e.dmg) {
        restart(dst, "hurt", ...(e.kind === "crit" ? ["crit"] : []));
        pop(dst, `-${e.dmg}`, e.kind === "crit" ? "crit" : "");
      }
      await wait(((FIGHT_STEP[e.kind] || 600) - (e.kind === "special" ? 450 : 200)) * pace());
    }

    if (!root.isConnected) return;
    arena.removeEventListener("click", skip);
    logItems.forEach((li) => li.classList.remove("pending"));
    root.querySelectorAll(".dmg-pop").forEach((p) => p.remove());
    final.fighters.forEach(({ f, cls, width, num }) => {
      f.className = cls;
      f.querySelector(".hp i").style.width = width;
      f.querySelector(".hp-num").textContent = num;
    });
    [banner.className, banner.innerHTML] = final.banner;
    arena.classList.remove("flash-crit", "flash-special", "shake");
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
    if (!el) {
      spot.hidden = true;
      Object.assign(card.style, { left: "50%", top: "50%", transform: "translate(-50%, -50%)" });
      return;
    }
    const r = el.getBoundingClientRect();
    spot.hidden = false;
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

// Gang chat: follow new messages (unless you scrolled up to read), clear the box after a successful send.
(() => {
  let follow = true;
  const list = () => document.querySelector("[data-chat-list]");
  const toBottom = () => { const l = list(); if (l) l.scrollTop = l.scrollHeight; };
  toBottom();
  document.addEventListener("htmx:beforeSwap", (e) => {
    if (e.detail.target.id !== "gang-chat") return;
    const l = list();
    follow = !l || l.scrollHeight - l.scrollTop - l.clientHeight < 60 || e.detail.requestConfig?.verb === "post";
  });
  document.addEventListener("htmx:afterSettle", (e) => {
    if (e.detail.target.id !== "gang-chat" && !e.detail.elt?.matches?.("#gang-chat")) return;
    if (follow) toBottom();
  });
  document.addEventListener("htmx:afterRequest", (e) => {
    const form = e.detail.elt.closest?.("[data-chat-form]");
    if (!form || !e.detail.successful) return;
    if (!document.querySelector("#gang-chat [data-chat-error]")?.dataset.chatError) {
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
