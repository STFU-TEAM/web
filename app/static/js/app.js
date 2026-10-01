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

// Storage toolbar: search, rarity, fusable, sort, multi-select. State survives htmx refreshes.
const storageState = { q: "", rarity: "", dupe: false, sort: "idx", selecting: false };
function applyStorage() {
  const grid = document.getElementById("storage-grid");
  const tools = document.querySelector("[data-storage-tools]");
  if (!grid || !tools) return;
  const s = storageState;
  tools.querySelector("[data-storage-search]").value = s.q;
  tools.querySelector("[data-storage-sort]").value = s.sort;
  tools.querySelectorAll("[data-rarity-filter]").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.rarityFilter === s.rarity)));
  tools.querySelector("[data-dupe-filter]").setAttribute("aria-pressed", String(s.dupe));
  tools.querySelector("[data-select-toggle]").setAttribute("aria-pressed", String(s.selecting));
  const slots = [...grid.querySelectorAll(".stand-slot")];
  const key = { idx: (el) => +el.dataset.idx, rarity: (el) => -el.dataset.rarity * 1e6 - +el.dataset.level,
                level: (el) => -el.dataset.level, power: (el) => -el.dataset.power, name: (el) => el.dataset.name }[s.sort];
  slots.sort((a, b) => { const x = key(a), y = key(b); return x < y ? -1 : x > y ? 1 : +a.dataset.idx - +b.dataset.idx; });
  let shown = 0;
  slots.forEach((el) => {
    const ok = el.dataset.search.includes(s.q) && (!s.rarity || el.dataset.rarity === s.rarity) && (!s.dupe || el.dataset.dupe === "1");
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
  else if (t.closest("[data-select-toggle]")) {
    storageState.selecting = !storageState.selecting;
    if (!storageState.selecting) document.querySelectorAll("#storage-grid [name=uuid]").forEach((c) => { c.checked = false; });
    applyStorage();
  } else if (t.closest("[data-select-visible]")) {
    document.querySelectorAll("#storage-grid .stand-slot:not([hidden]) [name=uuid]:not(:disabled)").forEach((c) => { c.checked = true; });
    updateSelected();
  } else if (storageState.selecting) {
    const slot = t.closest("#storage-grid .stand-slot");
    if (slot && !t.matches("[name=uuid]")) {
      const box = slot.querySelector("[name=uuid]");
      if (box && !box.disabled) { box.checked = !box.checked; updateSelected(); }
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
