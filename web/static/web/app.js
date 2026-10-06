// web/static/web/app.js — Comportamiento común de la web (sin frameworks, W-01; sin JavaScript en línea, W-17).
// Animaciones, sonidos, avisos flotantes, barra de progreso, actividad en vivo, confirmaciones, reporte de errores del
// navegador a la consola del servidor y mejoras de formularios. Todo es progresivo: sin JavaScript la web funciona igual.
(function () {
  "use strict";

  const body = document.body;
  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));
  const reducido = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const almacen = {  // localStorage puede no estar disponible (modo privado, políticas): nunca debe romper la página
    get(k, d) { try { const v = window.localStorage.getItem(k); return v === null ? d : v; } catch (e) { return d; } },
    set(k, v) { try { window.localStorage.setItem(k, v); } catch (e) { /* sin almacenamiento */ } },
  };

  // ---------------------------------------------------------------- reporte de errores al servidor (consola)
  let reportes = 0;
  function reportar(tipo, mensaje, detalle) {
    const url = body.dataset.errorUrl;
    if (!url || reportes >= 12) return;
    reportes += 1;
    try {
      fetch(url, {
        method: "POST", credentials: "same-origin", keepalive: true,
        headers: { "Content-Type": "application/json", "X-CSRFToken": body.dataset.csrf || "" },
        body: JSON.stringify({ tipo, mensaje: String(mensaje || "").slice(0, 500), detalle: String(detalle || "").slice(0, 1500),
          pagina: location.pathname + location.search }),
      }).catch(() => {});
    } catch (e) { /* nada */ }
  }
  window.addEventListener("error", (e) => {
    if (e.target && e.target !== window && e.target.tagName) return;  // recursos: se tratan aparte
    reportar("javascript", e.message, `${e.filename || ""}:${e.lineno || ""}:${e.colno || ""} ${e.error && e.error.stack ? e.error.stack : ""}`);
  });
  window.addEventListener("unhandledrejection", (e) => reportar("promesa", e.reason && e.reason.message ? e.reason.message : e.reason,
    e.reason && e.reason.stack ? e.reason.stack : ""));
  window.RiachueloReportar = reportar;

  // ---------------------------------------------------------------- sonidos (mismos archivos que la app móvil)
  const Sonidos = (() => {
    const base = body.dataset.sonidos || "";
    const nombres = ["tap", "toggle", "confirm", "success", "error", "notify"];
    const volumen = { tap: 0.22, toggle: 0.3, confirm: 0.4, success: 0.45, error: 0.4, notify: 0.5 };
    const cache = {};
    let activo = almacen.get("riachuelo.sonido", "1") === "1";
    let listo = false;
    function preparar() {
      if (listo || !base) return;
      listo = true;
      nombres.forEach((n) => { const a = new Audio(`${base}${n}.wav`); a.preload = "auto"; a.volume = volumen[n]; cache[n] = a; });
    }
    function play(n) {
      if (!activo) return;
      preparar();
      const a = cache[n];
      if (!a) return;
      try { const c = a.cloneNode(); c.volume = volumen[n]; const p = c.play(); if (p && p.catch) p.catch(() => {}); } catch (e) { /* sin audio */ }
    }
    function alternar() { activo = !activo; almacen.set("riachuelo.sonido", activo ? "1" : "0"); pintar(); if (activo) play("toggle"); }
    function pintar() {
      const b = $("#boton-sonido");
      if (!b) return;
      b.dataset.sonido = activo ? "1" : "0";
      b.setAttribute("aria-pressed", activo ? "true" : "false");
      b.title = activo ? "Sonidos activados (clic para silenciar)" : "Sonidos silenciados (clic para activar)";
    }
    document.addEventListener("pointerdown", preparar, { once: true, passive: true });
    document.addEventListener("keydown", preparar, { once: true });
    return { play, alternar, pintar };
  })();
  window.RiachueloSonido = Sonidos.play;

  // ---------------------------------------------------------------- barra de progreso
  const Progreso = (() => {
    const barra = $("#barra-progreso");
    let timer = null, valor = 0, activas = 0;
    function avanzar() { valor = Math.min(90, valor + (90 - valor) * 0.12); if (barra) barra.style.width = `${valor}%`; }
    function iniciar() {
      if (!barra) return;
      activas += 1;
      if (activas > 1) return;
      valor = 8; barra.classList.add("activa"); barra.style.width = "8%";
      clearInterval(timer); timer = setInterval(avanzar, 180);
    }
    function terminar(forzar) {
      if (!barra) return;
      activas = forzar ? 0 : Math.max(0, activas - 1);
      if (activas) return;
      clearInterval(timer); barra.style.width = "100%";
      setTimeout(() => { barra.classList.remove("activa"); barra.style.width = "0"; }, 260);
    }
    return { iniciar, terminar };
  })();

  // ---------------------------------------------------------------- avisos flotantes (toasts)
  const ICONOS = { success: "ok", info: "info", warning: "alerta", error: "circulo-alerta", actividad: "campana" };
  function icono(nombre) {
    const sprite = document.querySelector("use[href*='iconos.svg']");
    const href = sprite ? sprite.getAttribute("href").split("#")[0] : "";
    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("class", "ico"); svg.setAttribute("aria-hidden", "true");
    const use = document.createElementNS("http://www.w3.org/2000/svg", "use");
    use.setAttribute("href", `${href}#i-${nombre}`);
    svg.appendChild(use);
    return svg;
  }
  window.RiachueloIcono = icono;
  function toast({ tipo = "info", titulo = "", texto = "", url = null, persistente = false, duracion = 6000, copiar = null, sonido = true }) {
    const cont = $("#toasts");
    if (!cont) return null;
    const t = document.createElement("div");
    t.className = `toast ${tipo}`;
    t.setAttribute("role", tipo === "error" || tipo === "warning" ? "alert" : "status");
    const ico = document.createElement("span"); ico.className = "t-ico"; ico.appendChild(icono(ICONOS[tipo] || "info"));
    const txt = document.createElement("div"); txt.className = "t-txt";
    if (titulo) { const s = document.createElement("strong"); s.textContent = titulo; txt.appendChild(s); }
    if (texto) {
      if (url) { const a = document.createElement("a"); a.href = url; a.textContent = texto; txt.appendChild(a); }
      else { const sp = document.createElement("span"); sp.textContent = texto; txt.appendChild(sp); }
    }
    if (copiar) {
      const b = document.createElement("button"); b.type = "button"; b.className = "btn btn-secundario chico copiar";
      b.textContent = "Copiar contraseña";
      b.addEventListener("click", () => {
        (navigator.clipboard ? navigator.clipboard.writeText(copiar) : Promise.reject()).then(() => { b.textContent = "Copiada ✓"; Sonidos.play("success"); })
          .catch(() => { b.textContent = copiar; });
      });
      txt.appendChild(b);
    }
    const cerrar = document.createElement("button"); cerrar.type = "button"; cerrar.className = "t-cerrar"; cerrar.title = "Cerrar";
    cerrar.appendChild(icono("x"));
    const quitar = () => { t.classList.add("sale"); setTimeout(() => t.remove(), 320); };
    cerrar.addEventListener("click", quitar);
    t.append(ico, txt, cerrar);
    if (!persistente) {
      const barra = document.createElement("span"); barra.className = "t-tiempo"; barra.style.setProperty("--dur", `${duracion}ms`);
      t.appendChild(barra);
      let restante = duracion, inicio = Date.now(), id = setTimeout(quitar, restante);
      t.addEventListener("mouseenter", () => { clearTimeout(id); restante -= Date.now() - inicio; });
      t.addEventListener("mouseleave", () => { inicio = Date.now(); id = setTimeout(quitar, Math.max(1200, restante)); });
    }
    cont.appendChild(t);
    while (cont.children.length > 5) cont.firstElementChild.remove();
    if (sonido) Sonidos.play(tipo === "success" ? "success" : tipo === "error" || tipo === "warning" ? "error" : tipo === "actividad" ? "notify" : "tap");
    return t;
  }
  window.RiachueloToast = toast;

  function mensajesAToasts(root) {
    $$(".mensajes li", root).forEach((li) => {
      if (li.dataset.sinToast || li.dataset.convertido) return;
      li.dataset.convertido = "1";
      const tipo = li.dataset.tipo || "info";
      const persistente = li.classList.contains("persistente");
      const texto = li.textContent.trim();
      const m = persistente ? texto.match(/:\s([A-Za-z0-9]{12})\s—/) : null;  // contraseña temporal: botón «Copiar»
      toast({ tipo, texto, persistente, copiar: m ? m[1] : null, duracion: tipo === "error" ? 9000 : 6500 });
      const lista = li.closest(".mensajes");
      if (!persistente && lista && !lista.closest(".form-tarjeta")) li.hidden = true;
      if (lista && $$("li", lista).every((x) => x.hidden)) lista.hidden = true;
    });
  }

  // ---------------------------------------------------------------- diálogo de confirmación
  function confirmar({ titulo = "¿Confirmas?", texto = "", aceptar = "Sí, continuar", peligro = true, soloAceptar = false }) {
    return new Promise((resolver) => {
      const fondo = document.createElement("div"); fondo.className = "dialogo-fondo";
      const d = document.createElement("div"); d.className = "dialogo"; d.setAttribute("role", "dialog"); d.setAttribute("aria-modal", "true");
      const ico = document.createElement("div"); ico.className = peligro ? "d-ico" : "d-ico info"; ico.appendChild(icono(peligro ? "alerta" : "teclado"));
      const h = document.createElement("h3"); h.textContent = titulo;
      const p = document.createElement("p"); p.textContent = texto;
      const fila = document.createElement("div"); fila.className = "fila-botones";
      const no = document.createElement("button"); no.type = "button"; no.className = "btn btn-secundario"; no.textContent = "Cancelar";
      const si = document.createElement("button"); si.type = "button"; si.className = `btn ${peligro ? "btn-peligro" : "btn-primario"}`; si.textContent = aceptar;
      if (soloAceptar) fila.append(si); else fila.append(no, si);
      d.append(ico, h, p, fila); fondo.appendChild(d); body.appendChild(fondo);
      const previo = document.activeElement;
      const fin = (v) => { fondo.remove(); document.removeEventListener("keydown", tecla); if (previo && previo.focus) previo.focus(); resolver(v); };
      const tecla = (e) => { if (e.key === "Escape") fin(false); };
      no.addEventListener("click", () => fin(false));
      si.addEventListener("click", () => fin(true));
      fondo.addEventListener("click", (e) => { if (e.target === fondo) fin(false); });
      document.addEventListener("keydown", tecla);
      Sonidos.play("toggle");
      setTimeout(() => si.focus(), 30);
    });
  }
  window.RiachueloConfirmar = confirmar;

  document.addEventListener("submit", (e) => {
    const form = e.target;
    if (form.dataset.confirmar && !form.dataset.confirmado) {
      e.preventDefault();
      const boton = e.submitter;
      confirmar({ titulo: "Confirma la acción", texto: form.dataset.confirmar, aceptar: boton ? boton.textContent.trim() : "Continuar" })
        .then((ok) => { if (ok) { form.dataset.confirmado = "1"; if (boton) boton.setAttribute("aria-busy", "true"); Progreso.iniciar(); form.submit(); } });
      return;
    }
    if (!form.hasAttribute("hx-post") && !form.hasAttribute("hx-get") && !e.defaultPrevented) {
      const boton = e.submitter;
      if (boton && form.method.toLowerCase() === "post") boton.setAttribute("aria-busy", "true");
      if (!(boton && boton.hasAttribute("data-descarga")) && !form.action.endsWith(".csv")) Progreso.iniciar();
    }
  }, true);

  // ---------------------------------------------------------------- clics: navegación, ondas y sonidos
  document.addEventListener("pointerdown", (e) => {
    const b = e.target.closest(".btn, .boton-icono");
    if (!b || reducido) return;
    const r = b.getBoundingClientRect();
    const onda = document.createElement("span");
    const lado = Math.max(r.width, r.height);
    onda.className = "onda";
    onda.style.width = onda.style.height = `${lado}px`;
    onda.style.left = `${e.clientX - r.left - lado / 2}px`;
    onda.style.top = `${e.clientY - r.top - lado / 2}px`;
    b.appendChild(onda);
    setTimeout(() => onda.remove(), 650);
  }, { passive: true });

  document.addEventListener("click", (e) => {
    const sonidoBtn = e.target.closest("#boton-sonido");
    if (sonidoBtn) { Sonidos.alternar(); return; }
    const conSonido = e.target.closest("[data-sonido]:not(#boton-sonido)");
    if (conSonido) Sonidos.play(conSonido.dataset.sonido);
    else if (e.target.closest(".lateral a.item, .btn, .paginacion a, .boton-icono")) Sonidos.play("tap");
    const imprimir = e.target.closest("[data-imprimir]");
    if (imprimir) { e.preventDefault(); window.print(); return; }
    const descarga = e.target.closest("a[data-descarga]");
    if (descarga) toast({ tipo: "info", texto: "Preparando la descarga del CSV…", duracion: 3500, sonido: false });
    // filas de tabla clicables (sin JS cada celda tiene su propio enlace)
    const fila = e.target.closest("tr[data-href]");
    if (fila && !e.target.closest("a, button, input, select, textarea, label, summary, form")) {
      if (e.ctrlKey || e.metaKey) window.open(fila.dataset.href, "_blank"); else { Progreso.iniciar(); location.href = fila.dataset.href; }
      return;
    }
    const enlace = e.target.closest("a[href]");
    if (enlace && !e.defaultPrevented && !enlace.target && !e.ctrlKey && !e.metaKey && !e.shiftKey && e.button === 0 &&
        enlace.origin === location.origin && !enlace.hasAttribute("download") && !enlace.hasAttribute("hx-get") &&
        !enlace.pathname.endsWith(".csv") && !(enlace.pathname === location.pathname && enlace.hash)) {
      Progreso.iniciar();
    }
  });
  document.addEventListener("change", (e) => {
    if (e.target.matches("input[type=checkbox], input[type=radio]")) Sonidos.play("toggle");
    if (e.target.matches("select[data-autoenviar]")) { Progreso.iniciar(); e.target.form.submit(); }
  });
  window.addEventListener("pageshow", () => { Progreso.terminar(true); $$("[aria-busy=true]").forEach((b) => b.removeAttribute("aria-busy")); });

  // ---------------------------------------------------------------- HTMX: progreso, errores y fragmentos
  document.addEventListener("htmx:beforeRequest", (e) => {
    const elt = e.detail.elt;
    if (elt && elt.id === "actividad-poll") return;  // los sondeos no muestran barra
    if (elt && elt.id === "bandeja" && !e.detail.requestConfig.triggeringEvent) return;
    Progreso.iniciar();
    const ev = e.detail.requestConfig && e.detail.requestConfig.triggeringEvent;
    const boton = ev && ev.submitter;
    if (boton) { boton.setAttribute("aria-busy", "true"); e.detail.elt._boton = boton; }
  });
  document.addEventListener("htmx:afterRequest", (e) => {
    const elt = e.detail.elt;
    if (!(elt && elt.id === "actividad-poll")) Progreso.terminar();
    if (elt && elt._boton) { elt._boton.removeAttribute("aria-busy"); elt._boton = null; }
    const xhr = e.detail.xhr;
    if (xhr && xhr.status >= 500) {
      toast({ tipo: "error", titulo: "Error del servidor", texto: "La acción no se completó. El problema quedó registrado en la consola de la plataforma." });
      reportar("htmx", `HTTP ${xhr.status} en ${e.detail.pathInfo ? e.detail.pathInfo.requestPath : ""}`, xhr.getResponseHeader("X-Trace-Id") || "");
    }
  });
  document.addEventListener("htmx:sendError", (e) => {
    const silencioso = e.detail.elt && (e.detail.elt.id === "actividad-poll" || e.detail.elt.id === "bandeja");
    marcarRed(false);
    if (!silencioso) toast({ tipo: "error", titulo: "Sin conexión", texto: "No se pudo contactar al servidor. Revisa tu internet e inténtalo de nuevo." });
  });
  document.addEventListener("htmx:afterSwap", (e) => {
    marcarRed(true);
    const t = e.detail.target;
    const xhr = e.detail.xhr;
    if (t && t.id === "panel-decision" || (e.detail.elt && e.detail.elt.id === "panel-decision")) {
      const panel = $("#panel-decision");
      if (panel) {
        mensajesAToasts(panel);
        if (xhr && (xhr.status === 409 || xhr.status === 422)) {
          panel.classList.remove("agitar"); void panel.offsetWidth; panel.classList.add("agitar");
          if (xhr.status === 422) { Sonidos.play("error"); const err = $(".errorlist", panel); if (err) err.scrollIntoView({ behavior: "smooth", block: "center" }); }
        }
        document.dispatchEvent(new CustomEvent("riachuelo:panel"));
      }
    }
  });
  document.addEventListener("htmx:load", (e) => {
    const elt = e.detail.elt;
    if (!elt || !elt.querySelectorAll) return;
    if (elt.id === "actividad-poll") Actividad.recibir(elt);
    if (elt.id === "bandeja") Bandeja.recibir(elt);
    prepararImagenes(elt);
    tiemposRelativos(elt);
  });

  // ---------------------------------------------------------------- estado de la conexión
  const indicador = $("#indicador-vivo");
  function marcarRed(ok) {
    if (!indicador) return;
    indicador.classList.toggle("sin-red", !ok);
    const t = $(".txt-vivo", indicador);
    if (t) t.textContent = ok ? "En vivo" : "Sin conexión";
  }
  window.addEventListener("offline", () => { marcarRed(false); toast({ tipo: "warning", texto: "Te quedaste sin internet: la web se actualizará cuando vuelva la conexión." }); });
  window.addEventListener("online", () => { marcarRed(true); toast({ tipo: "success", texto: "Conexión recuperada.", sonido: false }); });
  const estadoRed = $("#estado-red");
  function pintarRedLogin() {
    if (!estadoRed) return;
    estadoRed.lastChild.textContent = navigator.onLine ? " Con internet" : " Sin internet";
    estadoRed.style.background = navigator.onLine ? "" : "var(--err-bg)";
    estadoRed.style.color = navigator.onLine ? "" : "var(--err-fg)";
  }
  window.addEventListener("online", pintarRedLogin); window.addEventListener("offline", pintarRedLogin);

  // ---------------------------------------------------------------- actividad en vivo (sondeo P-2)
  const Actividad = (() => {
    let primera = true;
    const boton = $("#boton-actividad"), panel = $("#panel-actividad"), lista = $("#lista-actividad"), panelDash = $("#actividad-panel");
    if (boton && panel) {
      boton.addEventListener("click", (e) => {
        e.stopPropagation();
        const abrir = panel.hidden;
        panel.hidden = !abrir; boton.setAttribute("aria-expanded", abrir ? "true" : "false");
        if (abrir) boton.classList.remove("con-nuevo");
      });
      document.addEventListener("click", (e) => { if (!panel.hidden && !e.target.closest(".desplegable")) { panel.hidden = true; boton.setAttribute("aria-expanded", "false"); } });
      document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !panel.hidden) { panel.hidden = true; boton.focus(); } });
    }
    function contador(n) {
      const c = $("#contador-pendientes");
      if (!c) return;
      const previo = c.textContent === "" ? null : parseInt(c.textContent, 10);
      c.textContent = n > 0 ? String(n) : "";
      if (previo !== null && n > previo) { c.classList.remove("salta"); void c.offsetWidth; c.classList.add("salta"); }
      // el panel guarda sus indicadores 60 s en caché: el total de pendientes se mantiene al día con el sondeo
      $$("[data-pendientes-vivo]").forEach((el) => { el.textContent = new Intl.NumberFormat("es-PE").format(n); });
    }
    function recibir(elt) {
      contador(parseInt(elt.dataset.pendientes || "0", 10));
      const nuevos = $$("li[data-evento]", elt);
      if (!nuevos.length) { primera = false; return; }
      nuevos.forEach((li) => {
        [lista, panelDash].forEach((dest) => {
          if (!dest || dest.querySelector(`[data-evento="${li.dataset.evento}"]`)) return;
          const vacio = dest.querySelector("[data-vacio], .tenue-3");
          if (vacio && dest === lista) vacio.remove();
          if (vacio && dest === panelDash) vacio.remove();
          const copia = li.cloneNode(true); copia.classList.add("nuevo");
          dest.insertBefore(copia, dest.firstChild);
          while (dest.children.length > 15) dest.lastElementChild.remove();
          tiemposRelativos(copia);
        });
      });
      if (!primera) {
        nuevos.slice(-3).forEach((li, i) => setTimeout(() => toast({ tipo: "actividad", titulo: li.dataset.titulo,
          texto: li.dataset.detalle || (li.dataset.url ? "Abrir" : ""), url: li.dataset.url || null, duracion: 7000,
          sonido: i === 0 }), i * 350));
        if (boton && panel && panel.hidden) boton.classList.add("con-nuevo");
      }
      primera = false;
    }
    return { recibir };
  })();

  // ---------------------------------------------------------------- bandeja: casos nuevos en el sondeo
  const Bandeja = (() => {
    let url = null, conocidos = null;
    function ids(elt) { return new Set($$("tr[data-caso]", elt).map((tr) => tr.dataset.caso)); }
    function recibir(elt) {
      const actual = elt.getAttribute("hx-get");
      const set = ids(elt);
      if (conocidos && actual === url) {
        const nuevos = [...set].filter((x) => !conocidos.has(x));
        nuevos.forEach((id) => { const tr = elt.querySelector(`tr[data-caso="${id}"]`); if (tr) tr.classList.add("recien"); });
        if (nuevos.length) toast({ tipo: "actividad", titulo: nuevos.length === 1 ? "Llegó un caso nuevo" : `Llegaron ${nuevos.length} casos nuevos`,
          texto: "La bandeja ya se actualizó.", duracion: 6000 });
      }
      url = actual; conocidos = set;
    }
    const inicial = $("#bandeja");
    if (inicial) recibir(inicial);
    return { recibir };
  })();

  // ---------------------------------------------------------------- imágenes: carga suave y fotos rotas
  function prepararImagenes(root) {
    $$("img.foto-carga", root).forEach((img) => {
      if (img.dataset.preparada) return;
      img.dataset.preparada = "1";
      const ok = () => { img.classList.add("cargada"); const m = img.closest(".marco-mini"); if (m) m.classList.add("con-foto"); };
      const mal = () => {
        img.classList.add("cargada");
        const m = img.closest(".marco-mini, .galeria a");
        if (m && !m.querySelector(".foto-rota")) { const r = document.createElement("span"); r.className = "foto-rota"; r.title = "La foto no cargó"; r.appendChild(icono("imagen")); m.appendChild(r); m.classList.add("con-foto"); }
        reportar("foto", "Una foto no cargó (revisa Cloudinary: transformaciones «miniatura» y «revision»)", img.currentSrc ? img.currentSrc.split("?")[0].slice(0, 160) : "");
      };
      if (img.complete) { if (img.naturalWidth) ok(); else mal(); } else { img.addEventListener("load", ok, { once: true }); img.addEventListener("error", mal, { once: true }); }
    });
  }

  // ---------------------------------------------------------------- tiempos relativos y contadores animados
  const rtf = window.Intl && Intl.RelativeTimeFormat ? new Intl.RelativeTimeFormat("es-PE", { numeric: "auto" }) : null;
  function relativo(fecha) {
    const s = (fecha.getTime() - Date.now()) / 1000;
    const abs = Math.abs(s);
    if (!rtf) return fecha.toLocaleString("es-PE");
    if (abs < 45) return "hace un momento";
    if (abs < 3600) return rtf.format(Math.round(s / 60), "minute");
    if (abs < 86400) return rtf.format(Math.round(s / 3600), "hour");
    if (abs < 86400 * 30) return rtf.format(Math.round(s / 86400), "day");
    return fecha.toLocaleDateString("es-PE");
  }
  function tiemposRelativos(root) {
    $$("time[data-relativo]", root).forEach((t) => {
      const f = new Date(t.getAttribute("datetime"));
      if (isNaN(f)) return;
      if (!t.title) t.title = t.textContent;
      t.textContent = relativo(f);
    });
  }
  setInterval(() => tiemposRelativos(document), 30000);

  function contarHasta(el) {
    const fin = parseInt(el.dataset.contar, 10);
    if (!isFinite(fin) || fin <= 0 || reducido) return;
    const fmt = new Intl.NumberFormat("es-PE");
    const dur = Math.min(1400, 500 + fin * 6);
    const t0 = performance.now();
    function paso(t) {
      const p = Math.min(1, (t - t0) / dur);
      const v = Math.round(fin * (1 - Math.pow(1 - p, 3)));
      el.textContent = fmt.format(v);
      if (p < 1) requestAnimationFrame(paso);
    }
    el.textContent = "0";
    requestAnimationFrame(paso);
  }

  // ---------------------------------------------------------------- formularios: contraseñas, cuentas demo, contador
  document.addEventListener("click", (e) => {
    const b = e.target.closest("button[data-mostrar]");
    if (b) {
      const input = document.getElementById(b.dataset.mostrar);
      if (!input) return;
      const ver = input.type === "password";
      input.type = ver ? "text" : "password";
      b.textContent = ver ? "Ocultar" : "Mostrar";
      b.setAttribute("aria-pressed", ver ? "true" : "false");
      input.focus();
      return;
    }
    const cuenta = e.target.closest("button[data-cuenta]");
    if (cuenta) {
      const email = $("#id_email"), clave = $("#id_password");
      if (email && clave) {
        email.value = cuenta.dataset.cuenta; clave.value = cuenta.dataset.clave;
        [email, clave].forEach((x) => { x.animate && x.animate([{ boxShadow: "0 0 0 4px rgba(141,198,63,.6)" }, { boxShadow: "0 0 0 0 rgba(141,198,63,0)" }], { duration: 700 }); });
        const enviar = $("#form-ingreso button[type=submit]");
        if (enviar) enviar.focus();
      }
    }
  });
  function contadores(root) {
    $$("[data-contador-de]", root).forEach((c) => {
      const input = document.getElementById(c.dataset.contadorDe);
      if (!input || input.dataset.contado) return;
      input.dataset.contado = "1";
      const max = parseInt(c.dataset.max || "0", 10);
      const pintar = () => { c.textContent = `${input.value.length} / ${max}`; c.style.color = input.value.length > max ? "var(--conf-fg)" : ""; };
      input.addEventListener("input", pintar); pintar();
    });
  }
  document.addEventListener("riachuelo:panel", () => contadores(document));

  const requisitos = $("#requisitos");
  if (requisitos) {
    const p1 = $("#id_new_password1"), p2 = $("#id_new_password2");
    const reglas = {
      largo: (v) => v.length >= 8,
      letras: (v) => /[A-Za-zÁÉÍÓÚÑáéíóúñ]/.test(v) && /\d/.test(v),
      espacios: (v) => v.length > 0 && v.trim() === v,
      iguales: (v, w) => v.length > 0 && v === w,
    };
    const pintar = () => {
      $$("li[data-regla]", requisitos).forEach((li) => {
        const ok = reglas[li.dataset.regla](p1.value, p2.value);
        if (ok && !li.classList.contains("cumple")) Sonidos.play("toggle");
        li.classList.toggle("cumple", ok);
      });
    };
    [p1, p2].forEach((x) => x && x.addEventListener("input", pintar));
  }

  // ---------------------------------------------------------------- v1.1: alta de cuentas (Usuarios → Nueva cuenta)
  // Con «App móvil» se ocultan y desmarcan los roles de la web: el operador de campo va solo (ADR-W-005).
  // Sin JavaScript el formulario funciona igual y el servidor valida la combinación.
  function tipoCuenta(root) {
    $$("[data-tipo-cuenta]", root).forEach((form) => {
      if (form.dataset.tipoListo) return;
      form.dataset.tipoListo = "1";
      const roles = $("[data-solo-web]", form);
      const pintar = () => {
        const elegido = $("input[name=tipo]:checked", form);
        const app = !!elegido && elegido.value === "APP";
        if (!roles) return;
        roles.hidden = app;
        if (app) $$("input[name=roles]", roles).forEach((c) => { c.checked = false; });
      };
      form.addEventListener("change", (e) => { if (e.target.name === "tipo") pintar(); });  // el sonido ya lo pone el oyente global
      pintar();
    });
  }

  // ---------------------------------------------------------------- atajos globales
  document.addEventListener("keydown", (e) => {
    const escribiendo = ["INPUT", "TEXTAREA", "SELECT"].includes(document.activeElement && document.activeElement.tagName);
    if (escribiendo || e.ctrlKey || e.metaKey || e.altKey) return;
    if (e.key === "?") {
      e.preventDefault();
      document.dispatchEvent(new CustomEvent("riachuelo:atajos"));
    }
  });
  document.addEventListener("click", (e) => { if (e.target.closest("[data-atajos]")) document.dispatchEvent(new CustomEvent("riachuelo:atajos")); });
  document.addEventListener("riachuelo:atajos", () => {
    const enCaso = !!$("#visor");
    confirmar({ titulo: "Atajos de teclado", peligro: false, aceptar: "Entendido", soloAceptar: true,
      texto: enCaso ? "C confirmar · D descartar · I evidencia insuficiente · Ctrl+Enter guardar · B mostrar u ocultar cajas · + / − zoom · 0 ajustar · F pantalla completa · ? esta ayuda"
        : "? esta ayuda · En un caso: C, D, I para elegir la decisión y Ctrl+Enter para guardar." });
  });

  // ---------------------------------------------------------------- arranque
  function iniciar() {
    Sonidos.pintar();
    pintarRedLogin();
    mensajesAToasts(document);
    prepararImagenes(document);
    tiemposRelativos(document);
    contadores(document);
    tipoCuenta(document);
    if ("IntersectionObserver" in window) {
      const io = new IntersectionObserver((entradas) => entradas.forEach((en) => { if (en.isIntersecting) { contarHasta(en.target); io.unobserve(en.target); } }), { threshold: 0.4 });
      $$("[data-contar]").forEach((el) => io.observe(el));
    }
    setTimeout(() => body.classList.remove("entrada"), 1100);
    const splash = $("#splash");
    if (splash) {
      const t0 = performance.now();
      const ocultar = () => setTimeout(() => { splash.classList.add("fuera"); setTimeout(() => splash.remove(), 600); },
        Math.max(0, 900 - (performance.now() - t0)));
      if (document.readyState === "complete") ocultar(); else window.addEventListener("load", ocultar, { once: true });
      setTimeout(() => splash.classList.add("fuera"), 3500);
    }
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", iniciar); else iniciar();
})();
