// web/static/web/mapa.js — Mapa satelital del fundo con Leaflet 1.9.4 servido localmente (W-01).
//   · v1.0: un punto por caso; el color indica ESTADO DE REVISIÓN, nunca gravedad (W-12). Borde punteado = ubicación
//     aproximada por marcador.
//   · v1.3 (ADR-W-007): fondo satelital (Esri World Imagery) con capa de nombres, centrado en el fundo; lotes
//     sombreados con su área; hileras como línea entre sus marcadores de inicio y fin; puntos con nombre; medir
//     distancias y distancia entre lotes. Administrador y supervisor dibujan el contorno de los lotes, marcan el inicio
//     y fin de cada hilera y colocan puntos (POST JSON a /mapa/editar/ con X-CSRFToken).
// Los textos del servidor se insertan como nodos de texto (nunca innerHTML con datos del servidor).
(function () {
  "use strict";

  const caja = document.getElementById("mapa");
  if (!caja) return;
  const carga = document.getElementById("mapa-carga");
  const meta = document.getElementById("mapa-meta");
  const filtros = document.getElementById("filtros-mapa");
  const estado = document.getElementById("mapa-estado");
  const panel = document.getElementById("mapa-herramientas");
  const puedeEditar = !!(panel && panel.dataset.puedeEditar);
  const aviso = (o) => window.RiachueloToast && window.RiachueloToast(o);
  const reportar = (t, m, d) => window.RiachueloReportar && window.RiachueloReportar(t, m, d);
  const $ = (id) => document.getElementById(id);

  if (!window.L) {
    if (carga) carga.querySelector("span:last-child").textContent = "No se pudo cargar el mapa (falta Leaflet en static/web/vendor).";
    reportar("javascript", "Leaflet no está disponible en la página del mapa", "");
    return;
  }

  const COLORES = {  // mismos tonos que las insignias de estado (DW-22)
    PENDIENTE_REVISION: "#d9a21b",
    POSIBLE_PLAGA: "#ef6820",
    CONFIRMADO_POR_IA: "#c11574",
    CONFIRMADO_POR_ESPECIALISTA: "#d92d20",
    EVIDENCIA_INSUFICIENTE: "#7a5af8",
    DESCARTADO: "#667085",
  };
  const FUNDO = [-14.027806, -75.699222];  // 14°01'40.1"S 75°41'57.2"W (La Tinguiña, Ica)

  // ------------------------------------------------------------ mapa base: satélite, híbrido y calles
  const mapa = L.map(caja, { zoomControl: true, preferCanvas: false, attributionControl: true, doubleClickZoom: false })
    .setView(FUNDO, 16);
  const ESRI = "https://server.arcgisonline.com/ArcGIS/rest/services";
  const satelite = L.tileLayer(`${ESRI}/World_Imagery/MapServer/tile/{z}/{y}/{x}`, {
    maxZoom: 21, maxNativeZoom: 19, attribution: "Imágenes © Esri, Maxar, Earthstar Geographics",
  });
  const nombres = L.tileLayer(`${ESRI}/Reference/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}`, {
    maxZoom: 21, maxNativeZoom: 19, pane: "overlayPane", opacity: 0.9,
  });
  const vias = L.tileLayer(`${ESRI}/Reference/World_Transportation/MapServer/tile/{z}/{y}/{x}`, {
    maxZoom: 21, maxNativeZoom: 19, opacity: 0.7,
  });
  const calles = L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 21, maxNativeZoom: 19, attribution: "© OpenStreetMap",
  });
  const hibrido = L.layerGroup([satelite, vias, nombres]);
  let fallosTeselas = 0;
  [satelite, calles].forEach((capa) => capa.on("tileerror", () => {
    fallosTeselas += 1;
    if (fallosTeselas === 6) {
      aviso({ tipo: "warning", texto: "No cargan las imágenes del mapa (¿sin internet?). Los datos del fundo se muestran igual." });
      reportar("red", "Fallan las teselas del mapa", "");
    }
  }));
  hibrido.addTo(mapa);
  L.control.layers({ "Satélite con nombres": hibrido, "Satélite": satelite, "Calles": calles }, null,
    { position: "topright", collapsed: true }).addTo(mapa);
  L.control.scale({ imperial: false, position: "bottomright" }).addTo(mapa);

  const capaLotes = L.featureGroup().addTo(mapa);
  const capaEtiquetas = L.layerGroup().addTo(mapa);
  const capaHileras = L.featureGroup().addTo(mapa);
  const capaPuntos = L.featureGroup().addTo(mapa);
  const capaCasos = L.featureGroup().addTo(mapa);
  const capaHerramienta = L.featureGroup().addTo(mapa);
  let marcadorFoco = null;
  let capas = { lots: [], rows: [], points: [], pointKinds: [] };

  // ------------------------------------------------------------ utilidades
  function texto(etiqueta, contenido, clase) {
    const el = document.createElement(etiqueta);
    if (clase) el.className = clase;
    if (contenido !== undefined && contenido !== null) el.textContent = String(contenido);
    return el;
  }
  function decir(t) { if (estado) estado.textContent = t; }
  function metros(m) {
    if (m >= 1000) return `${(m / 1000).toLocaleString("es-PE", { maximumFractionDigits: 2 })} km`;
    return `${Math.round(m).toLocaleString("es-PE")} m`;
  }
  function areaGeodesica(latlngs) {  // m² (exceso esférico, como Leaflet.draw)
    const R = 6378137, rad = Math.PI / 180;
    let area = 0;
    for (let i = 0, n = latlngs.length; i < n; i++) {
      const p1 = latlngs[i], p2 = latlngs[(i + 1) % n];
      area += (p2.lng - p1.lng) * rad * (2 + Math.sin(p1.lat * rad) + Math.sin(p2.lat * rad));
    }
    return Math.abs(area * R * R / 2);
  }
  function anillo(lot) {  // GeoJSON [lon, lat] → [L.LatLng] sin el vértice de cierre
    if (!lot.geometry || lot.geometry.type !== "Polygon") return [];
    const r = lot.geometry.coordinates[0].map(([lon, lat]) => L.latLng(lat, lon));
    if (r.length > 1 && r[0].equals(r[r.length - 1])) r.pop();
    return r;
  }
  function llenar(select, opciones, vacio) {
    if (!select) return;
    const previo = select.value;
    select.textContent = "";
    if (vacio !== undefined) select.appendChild(new Option(vacio, ""));
    opciones.forEach(([v, t]) => select.appendChild(new Option(t, v)));
    if ([...select.options].some((o) => o.value === previo)) select.value = previo;
  }

  // ------------------------------------------------------------ capas del fundo (lotes, hileras, puntos)
  function pintarCapas() {
    capaLotes.clearLayers();
    capaEtiquetas.clearLayers();
    capaHileras.clearLayers();
    capaPuntos.clearLayers();
    const sombrear = !$("ver-sombreado") || $("ver-sombreado").checked;
    capas.lots.forEach((lot) => {
      const r = anillo(lot);
      if (r.length < 3) return;
      const area = areaGeodesica(r);
      let perimetro = 0;
      r.forEach((p, i) => { perimetro += p.distanceTo(r[(i + 1) % r.length]); });
      const pol = L.polygon(r, {
        color: lot.color, weight: 2.5, fillColor: lot.color, fillOpacity: sombrear ? 0.28 : 0, interactive: true,
      }).addTo(capaLotes);
      const info = texto("div", null, "popup-caso");
      info.appendChild(texto("strong", `${lot.code} · ${lot.name}`));
      const n = capas.rows.filter((h) => h.lot === lot.id).length;
      info.appendChild(texto("small", `${(area / 10000).toLocaleString("es-PE", { maximumFractionDigits: 2 })} ha · perímetro ${metros(perimetro)} · ${n} hileras`));
      pol.bindPopup(info);
      lot._area = area;
      L.marker(pol.getBounds().getCenter(), {
        interactive: false, icon: L.divIcon({ className: "etiqueta-lote", html: "", iconSize: null }),
      }).addTo(capaEtiquetas).getElement().textContent = lot.code;
    });
    if (!$("ver-hileras") || $("ver-hileras").checked) {
      capas.rows.forEach((h) => {
        if (!h.ini || !h.fin) {
          [h.ini, h.fin].filter(Boolean).forEach((p) => L.circleMarker(p, { radius: 3, color: "#fff", weight: 1, fillColor: "#fff", fillOpacity: 1 })
            .bindTooltip(`H${String(h.number).padStart(2, "0")} (falta ${h.ini ? "el fin" : "el inicio"})`).addTo(capaHileras));
          return;
        }
        const lot = capas.lots.find((l) => l.id === h.lot);
        L.polyline([h.ini, h.fin], { color: "#ffffff", weight: 2, opacity: 0.85 })
          .bindTooltip(`${lot ? lot.code : h.lot} · H${String(h.number).padStart(2, "0")} · ${h.plants} plantas · ${metros(L.latLng(h.ini).distanceTo(h.fin))}`, { sticky: true })
          .addTo(capaHileras);
      });
    }
    if (!$("ver-puntos") || $("ver-puntos").checked) {
      capas.points.forEach((p) => {
        const m = L.marker([p.lat, p.lon], {
          title: p.name, icon: L.divIcon({ className: `punto-fundo pf-${p.kind}`, html: "", iconSize: [26, 26], iconAnchor: [13, 26] }),
        }).addTo(capaPuntos);
        m.bindTooltip(p.name, { direction: "top", offset: [0, -22] });
        m.bindPopup(() => popupPunto(p));
      });
    }
  }

  function popupPunto(p) {
    const div = texto("div", null, "popup-caso");
    div.appendChild(texto("strong", p.name));
    div.appendChild(texto("small", p.kindLabel));
    if (p.description) div.appendChild(texto("small", p.description, "tenue"));
    div.appendChild(texto("small", `${p.lat.toFixed(6)}, ${p.lon.toFixed(6)}`, "tenue"));
    if (puedeEditar) {
      const b = texto("button", "Eliminar punto", "btn btn-peligro chico");
      b.type = "button";
      b.addEventListener("click", () => {
        window.RiachueloConfirmar({ titulo: "Eliminar punto", texto: `¿Eliminar «${p.name}» del mapa?`, aceptar: "Eliminar" })
          .then((ok) => { if (ok) enviar({ accion: "punto_eliminar", id: p.id }); });
      });
      div.appendChild(b);
    }
    return div;
  }

  function actualizarSelects() {
    const lotes = capas.lots.map((l) => [l.id, `${l.code} · ${l.name}`]);
    llenar($("dist-a"), lotes, "—");
    llenar($("dist-b"), lotes, "—");
    llenar($("ed-lote"), lotes.map(([v, t]) => [v, `${t}${capas.lots.find((l) => l.id === v).geometry ? " ✓" : ""}`]));
    llenar($("hil-lote"), lotes);
    llenar($("pto-tipo"), capas.pointKinds.map((k) => [k.value, k.label]));
    llenarHileras();
  }
  function llenarHileras() {
    const lote = $("hil-lote") && $("hil-lote").value;
    llenar($("hil-hilera"), capas.rows.filter((h) => h.lot === lote)
      .map((h) => [h.id, `H${String(h.number).padStart(2, "0")}${h.ini && h.fin ? " ✓" : ""}`]));
  }
  if ($("hil-lote")) $("hil-lote").addEventListener("change", llenarHileras);
  ["ver-sombreado", "ver-hileras", "ver-puntos"].forEach((id) => { if ($(id)) $(id).addEventListener("change", pintarCapas); });

  function cargarCapas() {
    return fetch(caja.dataset.capas, { credentials: "same-origin", headers: { Accept: "application/json" } })
      .then((r) => { if (!r.ok) throw new Error(`El servidor respondió ${r.status}`); return r.json(); })
      .then((datos) => { capas = datos; pintarCapas(); actualizarSelects(); })
      .catch((err) => {
        aviso({ tipo: "error", titulo: "No se pudieron cargar los lotes del mapa", texto: err.message });
        reportar("red", `Fallo al cargar las capas del mapa: ${err.message}`, "");
      });
  }

  function enviar(cuerpo) {
    decir("Guardando…");
    return fetch(caja.dataset.editar, {
      method: "POST", credentials: "same-origin",
      headers: { "Content-Type": "application/json", Accept: "application/json", "X-CSRFToken": document.body.dataset.csrf || "" },
      body: JSON.stringify(cuerpo),
    }).then((r) => r.json().catch(() => ({ ok: false, error: `El servidor respondió ${r.status}` })).then((d) => {
      if (!d.ok) throw new Error(d.error || "No se pudo guardar.");
      capas = d.capas; pintarCapas(); actualizarSelects();
      aviso({ tipo: "success", texto: d.texto });
      decir(d.texto);
      return d;
    })).catch((err) => {
      aviso({ tipo: "error", titulo: "No se guardó", texto: err.message });
      decir(err.message);
      throw err;
    });
  }

  // ------------------------------------------------------------ casos
  function popup(p) {
    const div = texto("div", null, "popup-caso");
    const est = texto("span", p.statusLabel, "badge");
    est.style.background = COLORES[p.status] || "#667085"; est.style.color = "#fff";
    div.appendChild(est);
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
    return fetch(`${caja.dataset.url}?${q.toString()}`, { credentials: "same-origin", headers: { Accept: "application/json" } })
      .then((r) => {
        if (r.status === 403) throw new Error("Tu sesión ya no tiene acceso al mapa. Vuelve a ingresar.");
        if (!r.ok) throw new Error(`El servidor respondió ${r.status}`);
        return r.json();
      })
      .then((datos) => {
        if (id !== peticion) return;
        pintarCasos(datos, ajustar);
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

  function pintarCasos(datos, ajustar) {
    capaCasos.clearLayers();
    const focoId = caja.dataset.caso;
    let foco = null;
    datos.features.forEach((f) => {
      const p = f.properties;
      const [lon, lat] = f.geometry.coordinates;
      const aproximada = p.locationSource && p.locationSource !== "GPS";
      const m = L.circleMarker([lat, lon], {
        radius: 8, color: aproximada ? "#ffffff" : "#0e3b24", weight: 2, dashArray: aproximada ? "3 3" : null,
        fillColor: COLORES[p.status] || "#667085", fillOpacity: 0.95,
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
        L.circle([foco.lat, foco.lon], { radius: radio, color: "#ffffff", weight: 1, fillColor: "#8dc63f", fillOpacity: 0.2, interactive: false }),
        L.circleMarker([foco.lat, foco.lon], { radius: 14, color: "#ffffff", weight: 2, fill: false, className: "pulso-mapa", interactive: false }),
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
    const grupo = L.featureGroup([...capaLotes.getLayers(), ...capaHileras.getLayers(), ...capaPuntos.getLayers(), ...capaCasos.getLayers()]);
    if (grupo.getLayers().length) mapa.fitBounds(grupo.getBounds().pad(0.12), { maxZoom: 18, animate: true });
    else mapa.setView(FUNDO, 16);
  }

  // ------------------------------------------------------------ herramientas (medir, contorno, hilera, punto)
  const acciones = $("herr-acciones");
  const botonTerminar = $("herr-terminar");
  let herramienta = null;  // { tipo, puntos: [LatLng], ... }

  function dibujarHerramienta() {
    capaHerramienta.clearLayers();
    if (!herramienta) return;
    const pts = herramienta.puntos;
    pts.forEach((p, i) => L.circleMarker(p, { radius: 5, color: "#fff", weight: 2, fillColor: "#0e3b24", fillOpacity: 1, interactive: false })
      .bindTooltip(herramienta.tipo === "hilera" ? (i === 0 ? "Inicio" : "Fin") : String(i + 1), { permanent: herramienta.tipo === "hilera", direction: "right" })
      .addTo(capaHerramienta));
    if (pts.length < 2) return;
    if (herramienta.tipo === "contorno") {
      L.polygon(pts, { color: "#fde047", weight: 2, dashArray: "6 4", fillOpacity: 0.15, interactive: false }).addTo(capaHerramienta);
    } else {
      L.polyline(pts, { color: "#fde047", weight: 3, dashArray: herramienta.tipo === "medir" ? "6 4" : null, interactive: false }).addTo(capaHerramienta);
    }
    if (herramienta.tipo === "medir") {
      let total = 0;
      for (let i = 1; i < pts.length; i++) total += pts[i - 1].distanceTo(pts[i]);
      L.tooltip({ permanent: true, direction: "top", className: "etiqueta-medida" }).setLatLng(pts[pts.length - 1])
        .setContent(metros(total)).addTo(capaHerramienta);
      decir(`Distancia: ${metros(total)} (${pts.length} puntos). Doble clic o «Terminar» para cerrar.`);
    }
    if (herramienta.tipo === "contorno" && pts.length >= 3) {
      decir(`${pts.length} vértices · ${(areaGeodesica(pts) / 10000).toLocaleString("es-PE", { maximumFractionDigits: 2 })} ha. «Guardar» cuando termines.`);
    }
  }

  function iniciar(tipo) {
    cancelar();
    herramienta = { tipo, puntos: [] };
    caja.classList.add("mapa-dibujando");
    if (acciones) acciones.hidden = false;
    const etiqueta = { medir: "Terminar", contorno: "Guardar contorno", hilera: "Guardar", punto: "Guardar" }[tipo];
    if (botonTerminar) botonTerminar.querySelector("span").textContent = etiqueta;
    if (tipo === "medir") decir("Haz clic en el mapa para medir. Doble clic o «Terminar» para cerrar.");
    if (tipo === "contorno") {
      const lot = capas.lots.find((l) => l.id === $("ed-lote").value);
      if (!lot) { cancelar(); aviso({ tipo: "warning", texto: "Elige un lote." }); return; }
      herramienta.lote = lot.id;
      decir(`Dibuja el contorno de ${lot.code}: clic en cada esquina sobre la imagen.`);
    }
    if (tipo === "hilera") {
      const h = capas.rows.find((r) => r.id === $("hil-hilera").value);
      if (!h) { cancelar(); aviso({ tipo: "warning", texto: "Elige un lote y una hilera." }); return; }
      herramienta.hilera = h;
      decir(`H${String(h.number).padStart(2, "0")}: clic en el INICIO de la hilera.`);
    }
    if (tipo === "punto") {
      if (!$("pto-nombre").value.trim()) { cancelar(); aviso({ tipo: "warning", texto: "Escribe el nombre del punto." }); $("pto-nombre").focus(); return; }
      decir("Haz clic en el mapa donde va el punto.");
    }
  }

  function cancelar() {
    herramienta = null;
    capaHerramienta.clearLayers();
    caja.classList.remove("mapa-dibujando");
    if (acciones) acciones.hidden = true;
  }

  function terminar() {
    if (!herramienta) return;
    const h = herramienta;
    if (h.tipo === "medir") { herramienta = null; caja.classList.remove("mapa-dibujando"); if (acciones) acciones.hidden = true; return; }
    if (h.tipo === "contorno") {
      if (h.puntos.length < 3) { aviso({ tipo: "warning", texto: "Marca al menos 3 esquinas." }); return; }
      const ring = h.puntos.map((p) => [p.lng, p.lat]);
      ring.push(ring[0]);
      enviar({ accion: "contorno", lote: h.lote, geometry: { type: "Polygon", coordinates: [ring] } }).then(cancelar, () => {});
    }
    if (h.tipo === "hilera") guardarHilera();
  }

  function guardarHilera() {
    const h = herramienta;
    if (!h || h.puntos.length < 2) { aviso({ tipo: "warning", texto: "Marca el inicio y el fin." }); return; }
    const fila = h.hilera;
    enviar({ accion: "hilera", hilera: fila.id, inicio: [h.puntos[0].lat, h.puntos[0].lng], fin: [h.puntos[1].lat, h.puntos[1].lng] })
      .then(() => {
        cancelar();
        if ($("hil-siguiente") && $("hil-siguiente").checked) {
          const sel = $("hil-hilera");
          const i = [...sel.options].findIndex((o) => o.value === fila.id);
          if (i >= 0 && i + 1 < sel.options.length) { sel.selectedIndex = i + 1; iniciar("hilera"); }
        }
      }, () => {});
  }

  mapa.on("click", (e) => {
    if (!herramienta) return;
    setTimeout(() => mapa.closePopup(), 0);  // al dibujar, un clic sobre un lote no abre su ficha
    const h = herramienta;
    if (h.tipo === "punto") {
      cancelar();
      enviar({ accion: "punto_crear", name: $("pto-nombre").value, kind: $("pto-tipo").value, description: $("pto-desc").value,
        lat: e.latlng.lat, lon: e.latlng.lng }).then(() => { $("pto-nombre").value = ""; $("pto-desc").value = ""; }, () => {});
      return;
    }
    h.puntos.push(e.latlng);
    dibujarHerramienta();
    if (h.tipo === "hilera") {
      if (h.puntos.length === 1) decir(`H${String(h.hilera.number).padStart(2, "0")}: ahora clic en el FIN de la hilera.`);
      if (h.puntos.length === 2) guardarHilera();
    }
  });
  mapa.on("dblclick", () => { if (herramienta && herramienta.tipo === "medir") terminar(); });

  document.querySelectorAll("[data-herr]").forEach((b) => b.addEventListener("click", () => iniciar(b.dataset.herr)));
  if (botonTerminar) botonTerminar.addEventListener("click", terminar);
  if ($("herr-cancelar")) $("herr-cancelar").addEventListener("click", () => { cancelar(); decir("Cancelado."); });
  if ($("herr-deshacer")) $("herr-deshacer").addEventListener("click", () => { if (herramienta) { herramienta.puntos.pop(); dibujarHerramienta(); } });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && herramienta) { cancelar(); decir("Cancelado."); } });

  if ($("contorno-borrar")) $("contorno-borrar").addEventListener("click", () => {
    const lot = capas.lots.find((l) => l.id === $("ed-lote").value);
    if (!lot || !lot.geometry) { aviso({ tipo: "info", texto: "Ese lote no tiene contorno." }); return; }
    window.RiachueloConfirmar({ titulo: "Borrar contorno", texto: `¿Borrar el contorno de ${lot.code}?`, aceptar: "Borrar" })
      .then((ok) => { if (ok) enviar({ accion: "contorno", lote: lot.id, geometry: null }).catch(() => {}); });
  });

  // distancia más corta entre dos lotes (vértice–lado, en metros sobre una proyección local)
  function distanciaLotes(a, b) {
    const ra = anillo(a), rb = anillo(b);
    if (ra.length < 3 || rb.length < 3) return null;
    const lat0 = ra[0].lat * Math.PI / 180, k = 111320;
    const xy = (p) => [p.lng * k * Math.cos(lat0), p.lat * k];
    const ll = ([x, y]) => L.latLng(y / k, x / (k * Math.cos(lat0)));
    function cerca(p, s1, s2) {
      const [px, py] = p, [ax, ay] = s1, [bx, by] = s2;
      const dx = bx - ax, dy = by - ay, l2 = dx * dx + dy * dy;
      const t = l2 ? Math.max(0, Math.min(1, ((px - ax) * dx + (py - ay) * dy) / l2)) : 0;
      return [ax + t * dx, ay + t * dy];
    }
    let mejor = null;
    const prueba = (pts, otros) => pts.forEach((p) => {
      const P = xy(p);
      otros.forEach((q, i) => {
        const Q = cerca(P, xy(q), xy(otros[(i + 1) % otros.length]));
        const d = Math.hypot(P[0] - Q[0], P[1] - Q[1]);
        if (!mejor || d < mejor.d) mejor = { d, a: p, b: ll(Q) };
      });
    });
    prueba(ra, rb); prueba(rb, ra);
    return mejor;
  }
  if ($("dist-lotes")) $("dist-lotes").addEventListener("click", () => {
    const a = capas.lots.find((l) => l.id === $("dist-a").value), b = capas.lots.find((l) => l.id === $("dist-b").value);
    if (!a || !b || a === b) { aviso({ tipo: "warning", texto: "Elige dos lotes distintos." }); return; }
    const r = distanciaLotes(a, b);
    if (!r) { aviso({ tipo: "warning", texto: "Los dos lotes necesitan su contorno dibujado." }); return; }
    cancelar();
    L.polyline([r.a, r.b], { color: "#fde047", weight: 3, dashArray: "6 4", interactive: false }).addTo(capaHerramienta);
    const txt = r.d < 0.5 ? "colindantes" : metros(r.d);
    L.tooltip({ permanent: true, direction: "top", className: "etiqueta-medida" })
      .setLatLng(L.latLngBounds(r.a, r.b).getCenter()).setContent(`${a.code} ↔ ${b.code}: ${txt}`).addTo(capaHerramienta);
    mapa.fitBounds(L.latLngBounds([r.a, r.b]).pad(1.5), { maxZoom: 18 });
    decir(`Distancia más corta entre ${a.code} y ${b.code}: ${txt}.`);
  });

  // ------------------------------------------------------------ arranque
  const botonAjustar = $("mapa-ajustar");
  if (botonAjustar) botonAjustar.addEventListener("click", ajustarVista);
  if ($("mapa-fundo")) $("mapa-fundo").addEventListener("click", () => mapa.setView(FUNDO, 17));

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
  cargarCapas().then(() => cargar(true));
})();
