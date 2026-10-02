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

// Scroll a fresh pull result into view.
document.addEventListener("htmx:afterSwap", (e) => {
  if (["use-result", "pull-result"].includes(e.detail.target.id) && e.detail.target.firstElementChild) {
    e.detail.target.scrollIntoView({ behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth", block: "start" });
  }
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
  const pace = Math.min(1, 8000 / total);
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
      await wait(e.kind === "special" ? 450 * pace : 200 * pace);

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
          if (after <= 0 && before > 0) setTimeout(() => restart(f, "ko"), 300 * pace);
        });
        setHp(e.hp);
        prev = e.hp;
      } else if (dst && e.dmg) {
        restart(dst, "hurt", ...(e.kind === "crit" ? ["crit"] : []));
        pop(dst, `-${e.dmg}`, e.kind === "crit" ? "crit" : "");
      }
      await wait(((FIGHT_STEP[e.kind] || 600) - (e.kind === "special" ? 450 : 200)) * pace);
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
  const finish = () => {
    tour.hidden = true;
    document.body.classList.remove("touring");
    const token = JSON.parse(document.body.getAttribute("hx-headers") || "{}")["X-CSRF-Token"];
    fetch(tour.dataset.done, { method: "POST", headers: { "X-CSRF-Token": token || "" } }).catch(() => {});
    if (location.search.includes("tour=1")) history.replaceState(null, "", location.pathname);
  };
  const start = () => { i = 0; tour.hidden = false; document.body.classList.add("touring"); show(); };

  tour.addEventListener("click", (e) => {
    if (e.target.closest("[data-tour-next]")) { i = Math.min(steps.length - 1, i + 1); show(); }
    else if (e.target.closest("[data-tour-back]")) { i = Math.max(0, i - 1); show(); }
    else if (e.target.closest("[data-tour-skip]") || e.target.closest("[data-tour-cta], [data-tour-cta2]")) finish();
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
  if (tour.dataset.autostart === "1" || new URLSearchParams(location.search).get("tour") === "1") start();
})();
