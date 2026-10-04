// Shared UI behavior for the server-rendered web.
document.addEventListener("DOMContentLoaded", () => {
  if (window.lucide) window.lucide.createIcons();

  const sidebar = document.getElementById("sidebar");
  const toggle = document.getElementById("sidebar-toggle");
  if (sidebar && toggle) {
    toggle.addEventListener("click", () => sidebar.classList.toggle("open"));
  }
});
