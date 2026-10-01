// Close any open "Manage" menu when another opens, and after an action swaps content.
document.addEventListener("toggle", (e) => {
  if (e.target.matches("details.menu") && e.target.open) {
    document.querySelectorAll("details.menu[open]").forEach((d) => { if (d !== e.target) d.open = false; });
  }
}, true);

// Scroll a fresh pull result into view.
document.addEventListener("htmx:afterSwap", (e) => {
  if (e.detail.target.id === "use-result" && e.detail.target.firstElementChild) {
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
