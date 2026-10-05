// web/static/web/caso.js — Visor de evidencia del caso (zoom, desplazamiento, pantalla completa, cajas de la IA,
// foto original) y atajos de la decisión. Las cajas viven en un SVG con el viewBox de la imagen analizada, así que
// escalan junto con la foto sin recalcular coordenadas (W-16: los números llegan sin localizar desde la plantilla).
(function () {
  "use strict";

  const visor = document.getElementById("visor");
  if (!visor) return;
  const lienzo = visor.querySelector(".lienzo");
  const img = lienzo.querySelector("img");
  const nivel = visor.querySelector(".zoom-nivel");
  const sonar = (n) => window.RiachueloSonido && window.RiachueloSonido(n);
  const aviso = (o) => window.RiachueloToast && window.RiachueloToast(o);
  const ancho = parseFloat(visor.dataset.ancho) || 0, alto = parseFloat(visor.dataset.alto) || 0;
  if (ancho && alto) visor.style.setProperty("--ar", String(ancho / alto));

  const MIN = 1, MAX = 6;
  let escala = 1, x = 0, y = 0;

  function limitar() {
    const w = visor.clientWidth, h = lienzo.offsetHeight;
    const maxX = 0, minX = w - w * escala;
    const maxY = 0, minY = Math.min(0, visor.clientHeight - h * escala);
    x = Math.min(maxX, Math.max(minX, x));
    y = Math.min(maxY, Math.max(minY, y));
  }
  function pintar() {
    limitar();
    lienzo.style.transform = `translate(${x}px, ${y}px) scale(${escala})`;
    if (nivel) nivel.textContent = `${Math.round(escala * 100)} %`;
  }
  function zoom(factor, cx, cy) {
    const r = visor.getBoundingClientRect();
    const px = cx === undefined ? r.width / 2 : cx - r.left;
    const py = cy === undefined ? r.height / 2 : cy - r.top;
    const nueva = Math.min(MAX, Math.max(MIN, escala * factor));
    if (nueva === escala) return;
    x = px - (px - x) * (nueva / escala);
    y = py - (py - y) * (nueva / escala);
    escala = nueva;
    pintar();
  }
  function reiniciar() { escala = 1; x = 0; y = 0; pintar(); }

  // rueda (con o sin Ctrl): acerca hacia el puntero
  visor.addEventListener("wheel", (e) => { e.preventDefault(); zoom(e.deltaY < 0 ? 1.18 : 1 / 1.18, e.clientX, e.clientY); }, { passive: false });

  // arrastre y pellizco con Pointer Events (ratón, lápiz y dedos)
  const punteros = new Map();
  let inicio = null, distancia0 = 0, escala0 = 1;
  visor.addEventListener("pointerdown", (e) => {
    if (e.target.closest(".controles")) return;
    visor.setPointerCapture(e.pointerId);
    punteros.set(e.pointerId, { x: e.clientX, y: e.clientY });
    if (punteros.size === 1) inicio = { px: e.clientX, py: e.clientY, x, y };
    if (punteros.size === 2) { const [a, b] = [...punteros.values()]; distancia0 = Math.hypot(a.x - b.x, a.y - b.y); escala0 = escala; }
    visor.classList.add("arrastrando");
  });
  visor.addEventListener("pointermove", (e) => {
    if (!punteros.has(e.pointerId)) return;
    punteros.set(e.pointerId, { x: e.clientX, y: e.clientY });
    if (punteros.size === 2) {
      const [a, b] = [...punteros.values()];
      const d = Math.hypot(a.x - b.x, a.y - b.y);
      if (distancia0 > 0) zoom((escala0 * d / distancia0) / escala, (a.x + b.x) / 2, (a.y + b.y) / 2);
      return;
    }
    if (inicio && escala > 1) { x = inicio.x + (e.clientX - inicio.px); y = inicio.y + (e.clientY - inicio.py); pintar(); }
  });
  const soltar = (e) => {
    punteros.delete(e.pointerId);
    if (punteros.size === 0) { inicio = null; visor.classList.remove("arrastrando"); }
    else { const [p] = [...punteros.values()]; inicio = { px: p.x, py: p.y, x, y }; }
  };
  visor.addEventListener("pointerup", soltar);
  visor.addEventListener("pointercancel", soltar);
  visor.addEventListener("dblclick", (e) => { if (e.target.closest(".controles")) return; if (escala > 1) reiniciar(); else zoom(2.5, e.clientX, e.clientY); });
  window.addEventListener("resize", pintar);

  // controles
  const botonCajas = visor.querySelector('[data-accion="cajas"]');
  function alternarCajas() {
    const ocultas = visor.classList.toggle("sin-cajas");
    if (botonCajas) botonCajas.setAttribute("aria-pressed", ocultas ? "false" : "true");
    sonar("toggle");
  }
  function pantalla() {
    if (document.fullscreenElement) { document.exitFullscreen(); return; }
    if (visor.requestFullscreen) visor.requestFullscreen().catch(() => aviso({ tipo: "warning", texto: "Este navegador no permite pantalla completa." }));
  }
  document.addEventListener("fullscreenchange", () => setTimeout(reiniciar, 60));
  function original() {
    const url = visor.dataset.original;
    const boton = visor.querySelector('[data-accion="original"]');
    if (!url || img.dataset.original === "1") return;
    if (boton) boton.setAttribute("aria-busy", "true");
    const nueva = new Image();
    nueva.onload = () => {
      img.src = url; img.dataset.original = "1";
      if (boton) { boton.removeAttribute("aria-busy"); boton.setAttribute("aria-pressed", "true"); boton.disabled = true; }
      aviso({ tipo: "success", texto: "Foto original cargada a resolución completa.", duracion: 3500 });
    };
    nueva.onerror = () => {
      if (boton) boton.removeAttribute("aria-busy");
      aviso({ tipo: "error", texto: "No se pudo cargar la foto original. El problema quedó registrado." });
      if (window.RiachueloReportar) window.RiachueloReportar("foto", "No cargó la foto original del caso", location.pathname);
    };
    nueva.src = url;
  }
  visor.addEventListener("click", (e) => {
    const b = e.target.closest("[data-accion]");
    if (!b) return;
    const a = b.dataset.accion;
    if (a === "cajas") alternarCajas();
    else if (a === "mas") zoom(1.4);
    else if (a === "menos") zoom(1 / 1.4);
    else if (a === "reiniciar") reiniciar();
    else if (a === "pantalla") pantalla();
    else if (a === "original") original();
  });

  // la foto revisión puede tardar: indicador de carga y aviso si falla
  if (!img.complete) {
    visor.classList.add("cargando");
    img.addEventListener("load", () => visor.classList.remove("cargando"), { once: true });
  }
  img.addEventListener("error", () => {
    visor.classList.remove("cargando");
    visor.classList.add("foto-fallo");
    if (window.RiachueloReportar) window.RiachueloReportar("foto", "No cargó la foto de revisión del caso (transformación «revision» de Cloudinary)", location.pathname);
  }, { once: true });

  // resaltar caja ↔ fila de la tabla
  function resaltar(n, si) {
    document.querySelectorAll(`[data-caja="${n}"]`).forEach((el) => el.classList.toggle("resaltada", si));
  }
  document.querySelectorAll(".tabla-cajas tr[data-caja]").forEach((tr) => {
    tr.addEventListener("mouseenter", () => resaltar(tr.dataset.caja, true));
    tr.addEventListener("mouseleave", () => resaltar(tr.dataset.caja, false));
    tr.addEventListener("click", () => {
      const rect = visor.querySelector(`rect[data-caja="${tr.dataset.caja}"]`);
      if (!rect || !ancho) return;
      // centra y acerca la caja elegida
      const bx = parseFloat(rect.getAttribute("x")), by = parseFloat(rect.getAttribute("y"));
      const bw = parseFloat(rect.getAttribute("width")), bh = parseFloat(rect.getAttribute("height"));
      const k = visor.clientWidth / ancho;
      const objetivo = Math.min(MAX, Math.max(1.5, Math.min(visor.clientWidth / (bw * k * 2.2), lienzo.offsetHeight / (bh * k * 2.2))));
      escala = objetivo;
      x = visor.clientWidth / 2 - (bx + bw / 2) * k * escala;
      y = visor.clientHeight / 2 - (by + bh / 2) * k * escala;
      if (visor.classList.contains("sin-cajas")) alternarCajas();
      pintar();
      resaltar(tr.dataset.caja, true);
      setTimeout(() => resaltar(tr.dataset.caja, false), 1600);
      visor.scrollIntoView({ behavior: "smooth", block: "nearest" });
    });
  });

  // ------------------------------------------------------------ panel de decisión (se reemplaza por HTMX)
  const OBLIGATORIA = ["CONFIRMADO_POR_ESPECIALISTA", "EVIDENCIA_INSUFICIENTE"];
  function prepararPanel() {
    const form = document.getElementById("form-decision");
    if (!form || form.dataset.listo) return;
    form.dataset.listo = "1";
    const marca = form.querySelector("[data-obligatoria]");
    const obs = form.querySelector("#id_observation");
    const actualizar = () => {
      const elegido = form.querySelector('input[name="decision"]:checked');
      const oblig = !!elegido && OBLIGATORIA.includes(elegido.value);
      if (marca) marca.hidden = !oblig;
      if (obs) {
        obs.placeholder = oblig ? "Describe lo que observas en la foto (obligatoria)…" : "Observación opcional…";
        obs.toggleAttribute("aria-required", oblig);
      }
    };
    form.addEventListener("change", actualizar);
    actualizar();
  }
  prepararPanel();
  document.addEventListener("riachuelo:panel", prepararPanel);

  function elegir(valor) {
    const form = document.getElementById("form-decision");
    if (!form) return false;
    const radio = form.querySelector(`input[name="decision"][value="${valor}"]`);
    if (!radio) return false;
    radio.checked = true;
    radio.dispatchEvent(new Event("change", { bubbles: true }));
    const label = radio.closest("label");
    if (label && label.animate) label.animate([{ transform: "scale(.97)" }, { transform: "scale(1)" }], { duration: 180 });
    sonar("toggle");
    const obs = form.querySelector("#id_observation");
    if (obs && OBLIGATORIA.includes(valor) && !obs.value.trim()) obs.focus();
    return true;
  }

  document.addEventListener("keydown", (e) => {
    const activo = document.activeElement;
    const escribiendo = activo && (["INPUT", "TEXTAREA", "SELECT"].includes(activo.tagName) || activo.isContentEditable) &&
      !(activo.type === "radio" || activo.type === "checkbox");
    if ((e.ctrlKey || e.metaKey) && e.key === "Enter") {
      const form = document.getElementById("form-decision");
      if (form) { e.preventDefault(); const b = form.querySelector('button[type="submit"]'); if (form.requestSubmit) form.requestSubmit(b); else b.click(); }
      return;
    }
    if (escribiendo || e.ctrlKey || e.metaKey || e.altKey) return;
    const k = e.key.toLowerCase();
    if (k === "c" && elegir("CONFIRMADO_POR_ESPECIALISTA")) e.preventDefault();
    else if (k === "d" && elegir("DESCARTADO")) e.preventDefault();
    else if (k === "i" && elegir("EVIDENCIA_INSUFICIENTE")) e.preventDefault();
    else if (k === "b") { e.preventDefault(); alternarCajas(); }
    else if (e.key === "+" || e.key === "=") { e.preventDefault(); zoom(1.4); }
    else if (e.key === "-" || e.key === "_") { e.preventDefault(); zoom(1 / 1.4); }
    else if (e.key === "0") { e.preventDefault(); reiniciar(); }
    else if (k === "f") { e.preventDefault(); pantalla(); }
  });

  pintar();
})();
