// Leaflet map: fetches GeoJSON from Django and never talks to Supabase directly.
document.addEventListener("DOMContentLoaded", () => {
  const el = document.getElementById("mapa");
  if (!el || !window.L) return;

  const colors = {
    PENDIENTE_REVISION: "#f59e0b",
    CONFIRMADO_POR_ESPECIALISTA: "#ef4444",
    DESCARTADO: "#64748b",
    EVIDENCIA_INSUFICIENTE: "#38bdf8",
  };
  const map = L.map(el, { preferCanvas: true }).setView([-14.07, -75.73], 13);
  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 19,
    attribution: "&copy; OpenStreetMap",
  }).addTo(map);

  const layer = L.layerGroup().addTo(map);
  const form = document.getElementById("filtros-mapa");
  const meta = document.getElementById("mapa-meta");

  async function load() {
    const params = form ? new URLSearchParams(new FormData(form)) : new URLSearchParams();
    const response = await fetch(`${el.dataset.url}?${params.toString()}`, { headers: { Accept: "application/json" } });
    const data = await response.json();
    layer.clearLayers();
    const points = [];
    data.features.forEach((feature) => {
      const [lon, lat] = feature.geometry.coordinates;
      points.push([lat, lon]);
      const status = feature.properties.status;
      const marker = L.circleMarker([lat, lon], {
        radius: 8,
        color: colors[status] || "#22c55e",
        fillColor: colors[status] || "#22c55e",
        fillOpacity: 0.9,
        weight: 2,
      }).addTo(layer);
      marker.bindPopup(
        `<strong>${feature.properties.disease}</strong><br>${feature.properties.lot} · ${feature.properties.row}<br><a href="${feature.properties.url}">Abrir caso</a>`,
      );
    });
    if (points.length) map.fitBounds(points, { padding: [30, 30], maxZoom: 17 });
    if (meta) meta.textContent = `${data.features.length} caso(s) en el mapa · ${data.meta.sinUbicacion} sin ubicacion`;
  }

  if (form) form.addEventListener("change", load);
  load().catch(() => {
    if (meta) meta.textContent = "No se pudo cargar el GeoJSON.";
  });
});
