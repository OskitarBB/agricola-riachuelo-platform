// web/static/web/mapa.js — Mapa de casos con Leaflet 1.9.4 servido localmente (W-01). Un punto por caso; el color
// indica ESTADO DE REVISIÓN, nunca gravedad (W-12). Borde punteado = ubicación aproximada por marcador.
// Los textos del popup se insertan como nodos de texto (nunca innerHTML con datos del servidor).
(function () {
  "use strict";

  const caja = document.getElementById("mapa");
  if (!caja) return;
  const carga = document.getElementById("mapa-carga");
  const meta = document.getElementById("mapa-meta");
  const filtros = document.getElementById("filtros-mapa");
  const aviso = (o) => window.RiachueloToast && window.RiachueloToast(o);
  const reportar = (t, m, d) => window.RiachueloReportar && window.RiachueloReportar(t, m, d);

  if (!window.L) {
    if (carga) carga.querySelector("span:last-child").textContent = "No se pudo cargar el mapa (falta Leaflet en static/web/vendor).";
    reportar("javascript", "Leaflet no está disponible en la página del mapa", "");
    return;
  }

  const COLORES = {  // mismos tonos que las insignias de estado (DW-22)
    PENDIENTE_REVISION: "#d9a21b",
    CONFIRMADO_POR_ESPECIALISTA: "#d92d20",
    EVIDENCIA_INSUFICIENTE: "#7a5af8",
    DESCARTADO: "#667085",
  };
  const CENTRO = [-13.4099, -76.1323];  // Chincha, Ica (zona del fundo) — solo si aún no hay casos

  const mapa = L.map(caja, { zoomControl: true, preferCanvas: true, attributionControl: true }).setView(CENTRO, 15);
  const calles = L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 20, maxNativeZoom: 19, attribution: "© OpenStreetMap",
  });
  let fallosTeselas = 0;
  calles.on("tileerror", () => {
    fallosTeselas += 1;
    if (fallosTeselas === 6) {
      aviso({ tipo: "warning", texto: "No cargan las teselas del mapa (¿sin internet?). Los puntos se muestran igual." });
      reportar("red", "Fallan las teselas de OpenStreetMap", "");
    }
  });
  calles.addTo(mapa);

  const capaLotes = L.featureGroup().addTo(mapa);
  const capaCasos = L.featureGroup().addTo(mapa);
  let marcadorFoco = null;

  function texto(etiqueta, contenido, clase) {
    const el = document.createElement(etiqueta);
    if (clase) el.className = clase;
    if (contenido !== undefined && contenido !== null) el.textContent = String(contenido);
    return el;
  }
  function popup(p) {
    const div = texto("div", null, "popup-caso");
    const estado = texto("span", p.statusLabel, "badge");
    estado.style.background = COLORES[p.status] || "#667085"; estado.style.color = "#fff";
    div.appendChild(estado);
    div.appendChild(texto("strong", `${p.lot} · Hilera ${p.row} · ${p.lateral}`));
    const detalle = [];
    if (p.segment) detalle.push(`Segmento ${p.segment}`);
    if (p.marker) detalle.push(`Marcador ${p.marker}`);
    detalle.push(p.capturedAt);
    div.appendChild(texto("small", detalle.join(" · ")));
    if (p.locationSource && p.locationSource !== "GPS") div.appendChild(texto("small", "Ubicación aproximada (marcador)", "tenue"));
    else if (p.accuracyM) div.appendChild(texto("small", `GPS ± ${Math.round(p.accuracyM)} m`, "tenue"));
    const a = texto("a", "Abrir el caso →", "btn btn-primario chico");
    a.href = p.url;
    div.appendChild(a);
    return div;
  }

  function parametros() {
    const q = new URLSearchParams();
    if (filtros) new FormData(filtros).forEach((v, k) => { if (v) q.set(k, v); });
    return q;
  }

  let peticion = 0;
  function cargar(ajustar) {
    const id = ++peticion;
    if (carga) carga.classList.remove("oculta");
    const q = parametros();
    const t0 = performance.now();
    fetch(`${caja.dataset.url}?${q.toString()}`, { credentials: "same-origin", headers: { Accept: "application/json" } })
      .then((r) => {
        if (r.status === 403) throw new Error("Tu sesión ya no tiene acceso al mapa. Vuelve a ingresar.");
        if (!r.ok) throw new Error(`El servidor respondió ${r.status}`);
        return r.json();
      })
      .then((datos) => {
        if (id !== peticion) return;
        pintar(datos, ajustar);
        const ms = Math.round(performance.now() - t0);
        if (ms > 3000) reportar("lento", `El mapa tardó ${ms} ms en cargar ${datos.features.length} casos`, q.toString());
      })
      .catch((err) => {
        if (id !== peticion) return;
        aviso({ tipo: "error", titulo: "No se pudo cargar el mapa", texto: err.message });
        reportar("red", `Fallo al cargar datos del mapa: ${err.message}`, q.toString());
      })
      .finally(() => { if (id === peticion && carga) carga.classList.add("oculta"); });
  }

  function pintar(datos, ajustar) {
    capaLotes.clearLayers();
    capaCasos.clearLayers();
    (datos.lots || []).forEach((lot) => {
      if (!lot.geometry) return;
      L.geoJSON(lot.geometry, { style: { color: "#1f6b3a", weight: 2, fillColor: "#8dc63f", fillOpacity: 0.08, dashArray: "4 4" }, interactive: false })
        .bindTooltip(lot.properties.code, { permanent: false }).addTo(capaLotes);
    });
    const conteo = {};
    const focoId = caja.dataset.caso;
    let foco = null;
    datos.features.forEach((f) => {
      const p = f.properties;
      const [lon, lat] = f.geometry.coordinates;
      conteo[p.status] = (conteo[p.status] || 0) + 1;
      const aproximada = p.locationSource && p.locationSource !== "GPS";
      const m = L.circleMarker([lat, lon], {
        radius: 7, color: aproximada ? "#ffffff" : "#0e3b24", weight: 2, dashArray: aproximada ? "3 3" : null,
        fillColor: COLORES[p.status] || "#667085", fillOpacity: 0.92,
      });
      m.bindPopup(() => popup(p), { minWidth: 220 });
      m.bindTooltip(`${p.lot} · H${p.row} · ${p.statusLabel}`, { direction: "top", offset: [0, -6] });
      m.addTo(capaCasos);
      if (focoId && p.id === focoId) foco = { m, lat, lon, p };
    });

    const partes = [`${datos.features.length.toLocaleString("es-PE")} casos en el mapa`];
    if (datos.meta && datos.meta.sinUbicacion) partes.push(`${datos.meta.sinUbicacion} sin coordenadas (ver plano)`);
    if (datos.meta && datos.meta.truncated) partes.push(`mostrando los ${datos.meta.limit} más recientes: acota las fechas`);
    if (meta) meta.textContent = partes.join(" · ");
    if (datos.meta && datos.meta.truncated) aviso({ tipo: "warning", texto: `Hay más de ${datos.meta.limit} casos: se muestran los más recientes.` });

    if (marcadorFoco) { mapa.removeLayer(marcadorFoco); marcadorFoco = null; }
    if (foco) {
      mapa.setView([foco.lat, foco.lon], 19);
      const radio = Math.max(3, Math.min(60, foco.p.accuracyM || 6));
      marcadorFoco = L.layerGroup([
        L.circle([foco.lat, foco.lon], { radius: radio, color: "#1f6b3a", weight: 1, fillColor: "#8dc63f", fillOpacity: 0.15, interactive: false }),
        L.circleMarker([foco.lat, foco.lon], { radius: 14, color: "#1f6b3a", weight: 2, fill: false, className: "pulso-mapa", interactive: false }),
      ]).addTo(mapa);
      foco.m.bringToFront();
      setTimeout(() => foco.m.openPopup(), 350);
      caja.dataset.caso = "";  // solo la primera vez
    } else if (focoId) {
      aviso({ tipo: "info", texto: "El caso pedido no está en el filtro actual o no tiene coordenadas." });
      caja.dataset.caso = "";
      ajustarVista();
    } else if (ajustar) {
      ajustarVista();
    }
  }

  function ajustarVista() {
    const capas = capaCasos.getLayers().length ? capaCasos : capaLotes;
    if (capas.getLayers().length) mapa.fitBounds(capas.getBounds().pad(0.15), { maxZoom: 18, animate: true });
  }

  const botonAjustar = document.getElementById("mapa-ajustar");
  if (botonAjustar) botonAjustar.addEventListener("click", ajustarVista);

  if (filtros) {
    filtros.addEventListener("submit", (e) => { e.preventDefault(); cargar(true); });
    filtros.addEventListener("change", () => {
      const q = parametros();
      history.replaceState(null, "", `${location.pathname}${q.toString() ? "?" + q.toString() : ""}`);
      cargar(true);
    });
  }
  // el mapa se monta dentro de un contenedor que puede cambiar de tamaño (menú lateral, rotación del celular)
  window.addEventListener("resize", () => mapa.invalidateSize());
  setTimeout(() => mapa.invalidateSize(), 300);
  cargar(true);
})();
