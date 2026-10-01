// Close any open "Manage" menu when another opens, and after an action swaps content.
document.addEventListener("toggle", (e) => {
  if (e.target.matches("details.nav-group") && e.target.open) {
    document.querySelectorAll("details.nav-group[open]").forEach((group) => { if (group !== e.target) group.open = false; });
  }
  if (e.target.matches("details.menu") && e.target.open) {
    document.querySelectorAll("details.menu[open]").forEach((d) => { if (d !== e.target) d.open = false; });
  }
}, true);

document.addEventListener("input", (e) => {
  if (e.target.id !== "collection-filter") return;
  const query = e.target.value.trim().toLocaleLowerCase();
  const cards = [...document.querySelectorAll("#collection .collection-card")];
  let visible = 0;
  cards.forEach((card) => {
    const show = card.dataset.search.includes(query);
    card.hidden = !show;
    visible += Number(show);
  });
  const empty = document.querySelector("#collection .collection-empty");
  if (empty) empty.hidden = visible > 0 || cards.length === 0;
});

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
