// =====================================================
// AQUAMONITOR — script.js
// Dos formas de recibir datos del ESP32:
//   1) WiFi:      el ESP32 envía al servidor (app.py) y este panel lo consulta.
//   2) Bluetooth: este panel se conecta directo al ESP32 (Web Bluetooth).
// =====================================================

const LS_TOKEN = "aquamonitor_token";
const LS_USUARIO = "aquamonitor_usuario";
const LS_DISPOSITIVO = "aquamonitor_dispositivo_activo";
const INTERVALO_LECTURAS_MS = 4000;

// Deben ser iguales a los del código del ESP32
const BLE_SERVICE = "a9e30001-6c1b-4a4e-9a31-5f0b7c2d8e10";
const BLE_CHAR = "a9e30002-6c1b-4a4e-9a31-5f0b7c2d8e10";
const BLE_SIN_DATO = 0x7fff; // valor que usa el ESP32 cuando un sensor no responde

let sensores = { temperatura: null, nivelAgua: null, turbidez: null, ph: null };
let dispositivos = [];
let dispositivoActivoId = Number(localStorage.getItem(LS_DISPOSITIVO)) || null;
let wifiEstado = null; // "en_linea" | "sin_senal" | "sin_datos" | null
let filtroHistorico = "Todos";
let timerLecturas = null;
let timerEscaner = null;
let firmaPendientes = "";

let bleDevice = null;
let bleActivo = false;

const TIPOS = { ok: "estado-ok", alerta: "estado-alerta", off: "estado-off" };

function clamp(val, min, max) {
  return Math.min(Math.max(val, min), max);
}

function formatearFecha(ts) {
  return new Date(ts * 1000).toLocaleString("es-CO", {
    day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit", second: "2-digit"
  });
}

function formatearHora(fecha) {
  return fecha.toLocaleTimeString("es-CO", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

function crearEl(etiqueta, clase, texto) {
  const el = document.createElement(etiqueta);
  if (clase) el.className = clase;
  if (texto !== undefined) el.textContent = texto;
  return el;
}

// -----------------------------------------------------
// COMUNICACIÓN CON EL SERVIDOR
// -----------------------------------------------------
async function api(ruta, opciones = {}) {
  const { sinToken, ...fetchOpts } = opciones;
  const headers = { "Content-Type": "application/json" };
  const token = localStorage.getItem(LS_TOKEN);
  if (token && !sinToken) headers["Authorization"] = "Bearer " + token;

  let resp;
  try {
    resp = await fetch(ruta, { ...fetchOpts, headers });
  } catch (e) {
    throw new Error("No hay conexión con el servidor AquaMonitor.");
  }

  let datos = {};
  try { datos = await resp.json(); } catch (e) { /* respuesta sin JSON */ }

  if (resp.status === 401 && !sinToken) {
    cerrarSesion();
    throw new Error(datos.detail || "Tu sesión expiró.");
  }
  if (!resp.ok) throw new Error(datos.detail || "Error del servidor.");
  return datos;
}

function mostrarAviso(texto) {
  const aviso = document.getElementById("aviso-conexion");
  if (!aviso) return;
  aviso.textContent = texto;
  aviso.classList.remove("hidden");
}

function ocultarAviso() {
  const aviso = document.getElementById("aviso-conexion");
  if (aviso) aviso.classList.add("hidden");
}

// -----------------------------------------------------
// VENTANA DE INFORMACIÓN
// -----------------------------------------------------
const modalInfo = document.getElementById("modal-info");

// "items": textos normales, o { codigo: "texto" } para mostrar un bloque copiable
function mostrarInfo(titulo, items) {
  document.getElementById("info-titulo").textContent = titulo;
  const cuerpo = document.getElementById("info-cuerpo");
  cuerpo.replaceChildren();
  items.forEach((item) => {
    if (typeof item === "string") cuerpo.appendChild(crearEl("p", "", item));
    else cuerpo.appendChild(crearEl("code", "codigo", item.codigo));
  });
  modalInfo.classList.remove("hidden");
}

function cerrarInfo() {
  modalInfo.classList.add("hidden");
}

document.getElementById("btn-cerrar-info").addEventListener("click", cerrarInfo);
modalInfo.addEventListener("click", (e) => { if (e.target === modalInfo) cerrarInfo(); });
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") {
    cerrarInfo();
    cerrarModalEscaner();
  }
});

// -----------------------------------------------------
// ACCESO (login y registro)
// -----------------------------------------------------
const authScreen = document.getElementById("auth-screen");
const appEl = document.getElementById("app");
const formLogin = document.getElementById("form-login");
const formRegistro = document.getElementById("form-registro");

function guardarSesion(datos) {
  localStorage.setItem(LS_TOKEN, datos.token);
  localStorage.setItem(LS_USUARIO, datos.usuario);
}

function cerrarSesion() {
  detenerLecturas();
  cerrarModalEscaner();
  if (bleDevice && bleDevice.gatt.connected) bleDevice.gatt.disconnect();
  bleActivo = false;
  bleDevice = null;
  wifiEstado = null;
  localStorage.removeItem(LS_TOKEN);
  localStorage.removeItem(LS_USUARIO);
  localStorage.removeItem(LS_DISPOSITIVO);
  dispositivos = [];
  dispositivoActivoId = null;
  mostrarLogin();
}

function mostrarLogin() {
  appEl.classList.add("hidden");
  authScreen.classList.remove("hidden");
  formLogin.classList.remove("hidden");
  formLogin.reset();
  formRegistro.classList.add("hidden");
  document.getElementById("login-error").textContent = "";
  document.getElementById("registro-error").textContent = "";
}

function mostrarApp(usuario) {
  authScreen.classList.add("hidden");
  appEl.classList.remove("hidden");
  document.getElementById("user-nombre").textContent = usuario;
  document.getElementById("user-avatar").textContent = usuario.charAt(0).toUpperCase();
}

async function entrarALaApp(usuario) {
  mostrarApp(usuario);
  ocultarAviso();
  mostrarSinDatos("Esperando conexión.");
  await cargarDispositivos();
  iniciarLecturas();
}

document.getElementById("ir-a-registro").addEventListener("click", (e) => {
  e.preventDefault();
  formLogin.classList.add("hidden");
  formRegistro.classList.remove("hidden");
});

document.getElementById("ir-a-login").addEventListener("click", (e) => {
  e.preventDefault();
  formRegistro.classList.add("hidden");
  formLogin.classList.remove("hidden");
});

formLogin.addEventListener("submit", async (e) => {
  e.preventDefault();
  const errEl = document.getElementById("login-error");
  errEl.textContent = "";
  const usuario = document.getElementById("login-usuario").value.trim();
  const password = document.getElementById("login-password").value.trim();
  try {
    const datos = await api("/api/login", {
      method: "POST",
      body: JSON.stringify({ usuario, password }),
      sinToken: true
    });
    guardarSesion(datos);
    await entrarALaApp(datos.usuario);
  } catch (err) {
    errEl.textContent = err.message;
  }
});

formRegistro.addEventListener("submit", async (e) => {
  e.preventDefault();
  const errEl = document.getElementById("registro-error");
  errEl.textContent = "";
  const usuario = document.getElementById("registro-usuario").value.trim();
  const p1 = document.getElementById("registro-password").value.trim();
  const p2 = document.getElementById("registro-password2").value.trim();

  if (p1 !== p2) {
    errEl.textContent = "Las contraseñas no coinciden.";
    return;
  }
  try {
    const datos = await api("/api/registro", {
      method: "POST",
      body: JSON.stringify({ usuario, password: p1 }),
      sinToken: true
    });
    guardarSesion(datos);
    await entrarALaApp(datos.usuario);
  } catch (err) {
    errEl.textContent = err.message;
  }
});

document.getElementById("btn-logout").addEventListener("click", cerrarSesion);

// -----------------------------------------------------
// MONITOREO
// -----------------------------------------------------
function actualizarUI(idSensor, valor, textoEstado, tipo, pct, desc) {
  const valEl = document.getElementById(`val-${idSensor}`);
  const tagEl = document.getElementById(`tag-${idSensor}`);
  const descEl = document.getElementById(`desc-${idSensor}`);
  if (!valEl) return;

  if (typeof valor === "number") {
    const unidades = { temperatura: "°C", ph: "", nivelAgua: "%", turbidez: "NTU" };
    valEl.textContent = valor.toFixed(1);
    if (unidades[idSensor]) valEl.appendChild(crearEl("small", "", unidades[idSensor]));
  } else {
    valEl.textContent = valor;
  }

  tagEl.textContent = textoEstado;
  tagEl.className = `estado ${TIPOS[tipo]}`;
  descEl.textContent = desc;

  if (idSensor === "nivelAgua") {
    // El tanque se llena según el porcentaje real
    const agua = document.getElementById("agua-nivelAgua");
    agua.style.setProperty("--nivel", `${pct === null ? 0 : clamp(pct, 0, 100)}%`);
    agua.classList.toggle("vacio", pct === null || pct <= 0);
  } else {
    const marcador = document.getElementById(`ptr-${idSensor}`);
    if (pct === null) {
      marcador.style.visibility = "hidden";
    } else {
      marcador.style.visibility = "visible";
      marcador.style.setProperty("--pos", `${clamp(pct, 1.5, 98.5)}%`);
    }
  }
}

function sinSensor(idSensor) {
  actualizarUI(idSensor, "--", "Sin sensor", "off", null, "Este dispositivo todavía no envía este dato.");
}

function mostrarSinDatos(mensaje) {
  ["temperatura", "nivelAgua", "turbidez", "ph"].forEach((id) => {
    actualizarUI(id, "--", "Sin datos", "off", null, mensaje);
  });
  marcarActualizacion(null);
}

function marcarActualizacion(fecha) {
  document.getElementById("ultima-actualizacion").textContent =
    fecha ? "Actualizado " + formatearHora(fecha) : "";
}

function procesarSensores() {
  const { temperatura: t, nivelAgua: n, turbidez: tb, ph } = sensores;

  if (t === null) sinSensor("temperatura");
  else if (t < 16) actualizarUI("temperatura", t, "Baja", "alerta", (t / 40) * 100, "Temperatura demasiado baja.");
  else if (t <= 26) actualizarUI("temperatura", t, "Normal", "ok", (t / 40) * 100, "Temperatura idónea.");
  else actualizarUI("temperatura", t, "Alta", "alerta", (t / 40) * 100, "Temperatura demasiado alta.");

  if (n === null) sinSensor("nivelAgua");
  else if (n < 45) actualizarUI("nivelAgua", n, "Bajo", "alerta", n, "Nivel bajo. Inicia el llenado.");
  else if (n <= 85) actualizarUI("nivelAgua", n, "Normal", "ok", n, "Nivel de agua idóneo.");
  else actualizarUI("nivelAgua", n, "Alto", "alerta", n, "Nivel en el límite alto.");

  if (tb === null) sinSensor("turbidez");
  else if (tb <= 30) actualizarUI("turbidez", tb, "Normal", "ok", tb, "Agua transparente.");
  else actualizarUI("turbidez", tb, "Alta", "alerta", tb, "Agua con alta turbidez.");

  if (ph === null) sinSensor("ph");
  else if (ph < 6.5) actualizarUI("ph", ph, "Bajo", "alerta", (ph / 14) * 100, "pH ácido.");
  else if (ph <= 8.0) actualizarUI("ph", ph, "Normal", "ok", (ph / 14) * 100, "pH óptimo.");
  else actualizarUI("ph", ph, "Alto", "alerta", (ph / 14) * 100, "pH alcalino.");
}

// Muestra el estado de la conexión (WiFi o Bluetooth) y el nombre del dispositivo
function actualizarEstadoConexion() {
  const pill = document.getElementById("estado-conexion");
  const texto = document.getElementById("estado-conexion-texto");
  const chip = document.getElementById("dispositivo-actual-tag");
  const banner = document.getElementById("conexion-banner");
  const activo = dispositivos.find((d) => d.id === dispositivoActivoId);

  let clase = "pill-off";
  let mensaje = "Sin conexión";
  let nombre = activo ? activo.nombre : "Ningún dispositivo";

  if (bleActivo) {
    clase = "pill-ble";
    nombre = (bleDevice && bleDevice.name) || "ESP32";
    mensaje = "Bluetooth conectado";
  } else if (activo) {
    if (wifiEstado === "en_linea") {
      clase = "pill-ok";
      mensaje = "WiFi conectado";
    } else if (wifiEstado === "sin_senal") {
      clase = "pill-warn";
      mensaje = "Sin señal";
    } else if (wifiEstado === "sin_datos") {
      clase = "pill-warn";
      mensaje = "Esperando datos";
    }
  }

  pill.className = `pill ${clase}`;
  texto.textContent = mensaje;
  chip.textContent = nombre;
  banner.classList.toggle("hidden", bleActivo || !!dispositivoActivoId);

  document.querySelectorAll(".js-btn-ble").forEach((btn) => {
    const etiqueta = btn.querySelector(".btn-texto");
    if (!btn.dataset.etiqueta) btn.dataset.etiqueta = etiqueta.textContent;
    etiqueta.textContent = bleActivo ? "Desconectar Bluetooth" : btn.dataset.etiqueta;
    btn.classList.toggle("activo", bleActivo);
  });
}

async function actualizarLecturas() {
  if (bleActivo) return; // con Bluetooth los datos llegan directo del ESP32
  if (!dispositivoActivoId) {
    wifiEstado = null;
    mostrarSinDatos("Esperando conexión.");
    actualizarEstadoConexion();
    return;
  }
  try {
    const d = await api(`/api/lecturas/ultima?device_id=${dispositivoActivoId}`);
    if (bleActivo) return;
    ocultarAviso();
    if (d.sin_datos) {
      wifiEstado = "sin_datos";
      mostrarSinDatos("Esperando datos del dispositivo.");
    } else if (!d.en_linea) {
      wifiEstado = "sin_senal";
      mostrarSinDatos("Sin señal. Última lectura: " + formatearFecha(d.ts) + ".");
    } else {
      wifiEstado = "en_linea";
      sensores = {
        temperatura: d.temperatura,
        nivelAgua: d.nivel_agua,
        turbidez: d.turbidez,
        ph: d.ph
      };
      procesarSensores();
      marcarActualizacion(new Date(d.ts * 1000));
    }
  } catch (err) {
    mostrarAviso(err.message);
  }
  actualizarEstadoConexion();
}

async function ciclo() {
  await actualizarLecturas();
  // Si estás viendo la lista de dispositivos, refresca su estado (en línea / sin señal)
  if (!vistas.dispositivos.classList.contains("hidden")) await cargarDispositivos();
}

function iniciarLecturas() {
  detenerLecturas();
  ciclo();
  timerLecturas = setInterval(ciclo, INTERVALO_LECTURAS_MS);
}

function detenerLecturas() {
  if (timerLecturas) clearInterval(timerLecturas);
  timerLecturas = null;
}

// -----------------------------------------------------
// BLUETOOTH (Web Bluetooth)
// El ESP32 envía 8 bytes: 4 números de 16 bits (little-endian):
//   temperatura x10, nivel x10, turbidez x10, pH x100   (0x7FFF = sin dato)
// -----------------------------------------------------
function recibirPaqueteBle(vista) {
  if (!vista || vista.byteLength < 8) return;
  const leer = (pos, divisor) => {
    const crudo = vista.getInt16(pos, true);
    return crudo === BLE_SIN_DATO ? null : crudo / divisor;
  };
  sensores = {
    temperatura: leer(0, 10),
    nivelAgua: leer(2, 10),
    turbidez: leer(4, 10),
    ph: leer(6, 100)
  };
  procesarSensores();
  marcarActualizacion(new Date());
}

function alDesconectarBle() {
  bleActivo = false;
  bleDevice = null;
  mostrarSinDatos("Bluetooth desconectado.");
  actualizarEstadoConexion();
  actualizarLecturas(); // si hay un dispositivo WiFi vinculado, vuelve a usarlo
}

function desconectarBluetooth() {
  if (bleDevice && bleDevice.gatt.connected) bleDevice.gatt.disconnect();
  else alDesconectarBle();
}

async function conectarBluetooth() {
  if (!navigator.bluetooth) {
    mostrarInfo("Este navegador no permite Bluetooth", [
      "El panel usa Web Bluetooth, que funciona en Chrome y Edge (Android, Windows, Mac y Linux). No está disponible en iPhone ni en iPad.",
      "Mientras tanto puedes conectar el ESP32 por WiFi desde la sección Dispositivos."
    ]);
    return;
  }

  if (!window.isSecureContext) {
    mostrarInfo("Chrome pide una página segura para usar Bluetooth", [
      "Desde el computador, abre el panel con esta dirección y el Bluetooth funcionará:",
      { codigo: `http://localhost:${location.port || 80}` },
      "En un celular Android: abre chrome://flags/#unsafely-treat-insecure-origin-as-secure en Chrome, escribe esta dirección en la casilla, cambia a Enabled y reinicia Chrome:",
      { codigo: location.origin },
      "Por WiFi no necesitas hacer nada de esto."
    ]);
    return;
  }

  const botones = document.querySelectorAll(".js-btn-ble");
  botones.forEach((b) => (b.disabled = true));
  try {
    const dispositivo = await navigator.bluetooth.requestDevice({
      filters: [{ services: [BLE_SERVICE] }]
    });
    dispositivo.addEventListener("gattserverdisconnected", alDesconectarBle);

    const servidor = await dispositivo.gatt.connect();
    const servicio = await servidor.getPrimaryService(BLE_SERVICE);
    const caracteristica = await servicio.getCharacteristic(BLE_CHAR);
    caracteristica.addEventListener("characteristicvaluechanged", (e) => recibirPaqueteBle(e.target.value));
    await caracteristica.startNotifications();

    bleDevice = dispositivo;
    bleActivo = true;
    ocultarAviso();
    recibirPaqueteBle(await caracteristica.readValue());
    actualizarEstadoConexion();
  } catch (err) {
    if (err.name !== "NotFoundError") {
      mostrarInfo("No se pudo conectar por Bluetooth", [
        "Acércate al ESP32, verifica que esté encendido y que no esté conectado a otro teléfono o computador. Luego intenta de nuevo.",
        { codigo: err.message || String(err) }
      ]);
    }
  } finally {
    botones.forEach((b) => (b.disabled = false));
  }
}

document.querySelectorAll(".js-btn-ble").forEach((btn) => {
  btn.addEventListener("click", () => (bleActivo ? desconectarBluetooth() : conectarBluetooth()));
});

// -----------------------------------------------------
// DISPOSITIVOS WIFI
// -----------------------------------------------------
async function cargarDispositivos() {
  try {
    const datos = await api("/api/dispositivos");
    dispositivos = datos.dispositivos;
    ocultarAviso();
  } catch (err) {
    mostrarAviso(err.message);
    return;
  }

  // Si el dispositivo guardado ya no existe, usar el primero de la lista
  if (!dispositivos.some((d) => d.id === dispositivoActivoId)) {
    dispositivoActivoId = dispositivos.length ? dispositivos[0].id : null;
    if (dispositivoActivoId) localStorage.setItem(LS_DISPOSITIVO, dispositivoActivoId);
    else localStorage.removeItem(LS_DISPOSITIVO);
  }
  actualizarEstadoConexion();
  renderizarDispositivos();
}

function seleccionarDispositivo(id) {
  dispositivoActivoId = id;
  localStorage.setItem(LS_DISPOSITIVO, id);
  wifiEstado = null;
  if (!bleActivo) mostrarSinDatos("Cargando datos...");
  actualizarEstadoConexion();
  renderizarDispositivos();
  actualizarLecturas();
}

async function desvincularDispositivo(dev) {
  if (!confirm(`¿Desvincular "${dev.nombre}"? Se borrarán sus lecturas guardadas.`)) return;
  try {
    await api(`/api/dispositivos/${dev.id}`, { method: "DELETE" });
    await cargarDispositivos();
    actualizarLecturas();
  } catch (err) {
    mostrarAviso(err.message);
  }
}

function crearSenal(nivel) {
  const NS = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(NS, "svg");
  svg.setAttribute("viewBox", "0 0 24 20");
  svg.setAttribute("class", "senal");
  svg.setAttribute("aria-hidden", "true");
  [6, 10, 14, 18].forEach((alto, i) => {
    const barra = document.createElementNS(NS, "rect");
    barra.setAttribute("x", i * 6);
    barra.setAttribute("y", 20 - alto);
    barra.setAttribute("width", 4);
    barra.setAttribute("height", alto);
    barra.setAttribute("rx", 1);
    if (i >= nivel) barra.setAttribute("class", "apagada");
    svg.appendChild(barra);
  });
  return svg;
}

function nivelSenal(dev) {
  if (!dev.en_linea) return 0;
  return { Excelente: 4, Buena: 3, Regular: 2, "Débil": 1 }[dev.senal] || 1;
}

function renderizarDispositivos() {
  const grid = document.getElementById("dispositivos-grid");
  grid.replaceChildren();

  if (dispositivos.length === 0) {
    grid.appendChild(crearEl(
      "div", "dispositivos-vacio",
      "Todavía no hay dispositivos. Enciende el ESP32 y toca «Vincular por WiFi»."
    ));
    return;
  }

  dispositivos.forEach((dev) => {
    const activo = dev.id === dispositivoActivoId;
    const card = crearEl("div", "dispositivo-card" + (activo ? " activo" : ""));
    card.addEventListener("click", () => seleccionarDispositivo(dev.id));

    const top = crearEl("div", "dispositivo-top");
    top.appendChild(crearSenal(nivelSenal(dev)));
    top.appendChild(crearEl("span", "dispositivo-nombre", dev.nombre));
    top.appendChild(crearEl(
      "span", "estado " + (dev.en_linea ? "estado-ok" : "estado-off"),
      dev.en_linea ? "En línea" : "Sin señal"
    ));
    card.appendChild(top);

    const datos = crearEl("dl", "dispositivo-datos");
    const filas = [
      ["Señal", dev.rssi !== null ? `${dev.senal} (${dev.rssi} dBm)` : dev.senal],
      ["IP", dev.ip || "—"],
      ["MAC", dev.mac],
      ["Última vez", formatearFecha(dev.ultima)]
    ];
    filas.forEach(([etiqueta, valor]) => {
      datos.appendChild(crearEl("dt", "", etiqueta));
      datos.appendChild(crearEl("dd", "", valor));
    });
    card.appendChild(datos);

    const pie = crearEl("div", "dispositivo-pie");
    pie.appendChild(crearEl("span", "dispositivo-en-panel", activo ? "Se ve en el panel" : ""));
    const btnDesv = crearEl("button", "btn btn-danger btn-small", "Desvincular");
    btnDesv.type = "button";
    btnDesv.addEventListener("click", (e) => {
      e.stopPropagation();
      desvincularDispositivo(dev);
    });
    pie.appendChild(btnDesv);
    card.appendChild(pie);

    grid.appendChild(card);
  });
}

// -----------------------------------------------------
// NAVEGACIÓN
// -----------------------------------------------------
const menuItems = document.querySelectorAll(".menu-item");
const vistas = {
  dashboard: document.getElementById("view-dashboard"),
  historicos: document.getElementById("view-historicos"),
  dispositivos: document.getElementById("view-dispositivos")
};

function irAVista(vista) {
  menuItems.forEach((i) => i.classList.toggle("active", i.dataset.view === vista));
  Object.keys(vistas).forEach((k) => vistas[k].classList.toggle("hidden", k !== vista));
  if (vista === "dispositivos") cargarDispositivos();
  if (vista === "historicos") cargarHistoricos();
  window.scrollTo(0, 0);
}

menuItems.forEach((item) => {
  item.addEventListener("click", (e) => {
    e.preventDefault();
    irAVista(item.dataset.view);
  });
});

// -----------------------------------------------------
// VINCULAR DISPOSITIVOS POR WIFI
// -----------------------------------------------------
const btnEscanear = document.getElementById("btn-escanear-dispositivo");
const modalScanner = document.getElementById("modal-scanner");
const listaEncontrados = document.getElementById("lista-dispositivos-encontrados");

function mensajeEscaner(texto) {
  listaEncontrados.replaceChildren(crearEl("p", "scanner-vacio", texto));
}

function renderizarPendientes(lista) {
  // Solo se redibuja si cambió la lista, para no borrar el nombre que estás escribiendo
  const firma = lista.map((d) => d.mac).join(",");
  if (firma === firmaPendientes) return;
  firmaPendientes = firma;

  if (lista.length === 0) {
    mensajeEscaner("No hay dispositivos nuevos. Enciende el ESP32 y revisa que esté en la misma red WiFi.");
    return;
  }

  listaEncontrados.replaceChildren();
  lista.forEach((dev) => {
    const item = crearEl("div", "scanner-item");

    const info = crearEl("div");
    info.appendChild(crearEl("strong", "", dev.nombre));
    info.appendChild(crearEl("small", "", `${dev.ip || "—"}, señal ${dev.senal.toLowerCase()}`));
    item.appendChild(info);

    const acciones = crearEl("div", "scanner-acciones");
    const input = crearEl("input", "auth-input");
    input.type = "text";
    input.placeholder = "Nombre";
    input.maxLength = 40;
    input.setAttribute("aria-label", "Nombre del dispositivo");
    const btn = crearEl("button", "btn btn-primary btn-small", "Vincular");
    btn.type = "button";
    btn.addEventListener("click", () => vincularDispositivo(dev, input.value.trim(), btn));
    acciones.appendChild(input);
    acciones.appendChild(btn);
    item.appendChild(acciones);

    listaEncontrados.appendChild(item);
  });
}

async function buscarPendientes() {
  try {
    const datos = await api("/api/dispositivos/pendientes");
    renderizarPendientes(datos.dispositivos);
  } catch (err) {
    firmaPendientes = "";
    mensajeEscaner(err.message);
  }
}

async function vincularDispositivo(dev, nombre, btn) {
  btn.disabled = true;
  try {
    const datos = await api("/api/dispositivos/vincular", {
      method: "POST",
      body: JSON.stringify({ mac: dev.mac, nombre })
    });
    cerrarModalEscaner();
    await cargarDispositivos();
    seleccionarDispositivo(datos.dispositivo.id);
  } catch (err) {
    btn.disabled = false;
    firmaPendientes = "";
    mensajeEscaner(err.message);
  }
}

function abrirModalEscaner() {
  modalScanner.classList.remove("hidden");
  firmaPendientes = "";
  mensajeEscaner("Buscando dispositivos en tu red WiFi...");
  buscarPendientes();
  timerEscaner = setInterval(buscarPendientes, 2000);
}

function cerrarModalEscaner() {
  if (timerEscaner) clearInterval(timerEscaner);
  timerEscaner = null;
  modalScanner.classList.add("hidden");
}

btnEscanear.addEventListener("click", abrirModalEscaner);
document.getElementById("btn-cerrar-modal").addEventListener("click", cerrarModalEscaner);
modalScanner.addEventListener("click", (e) => { if (e.target === modalScanner) cerrarModalEscaner(); });

document.getElementById("btn-banner-wifi").addEventListener("click", () => {
  irAVista("dispositivos");
  abrirModalEscaner();
});

// -----------------------------------------------------
// REGISTROS HISTÓRICOS
// -----------------------------------------------------
function mensajeTabla(texto) {
  const tbody = document.getElementById("tabla-historicos-body");
  tbody.replaceChildren();
  const fila = document.createElement("tr");
  const celda = crearEl("td", "tabla-vacia", texto);
  celda.colSpan = 4;
  fila.appendChild(celda);
  tbody.appendChild(fila);
}

function renderizarTablaHistoricos(lista) {
  if (lista.length === 0) {
    mensajeTabla("Todavía no hay registros para este sensor.");
    return;
  }

  const tbody = document.getElementById("tabla-historicos-body");
  tbody.replaceChildren();
  lista.forEach((reg) => {
    const fila = document.createElement("tr");
    fila.appendChild(crearEl("td", "", formatearFecha(reg.ts)));
    fila.appendChild(crearEl("td", "", reg.sensor));
    fila.appendChild(crearEl("td", "", reg.valor));

    const celdaEstado = document.createElement("td");
    const tipo = reg.clase === "tag-red" ? "estado-alerta" : "estado-ok";
    celdaEstado.appendChild(crearEl("span", `estado ${tipo}`, reg.estado));
    fila.appendChild(celdaEstado);

    tbody.appendChild(fila);
  });
}

async function cargarHistoricos() {
  if (!dispositivoActivoId) {
    mensajeTabla("Vincula un dispositivo por WiFi para ver sus registros. Las lecturas por Bluetooth no se guardan.");
    return;
  }
  try {
    const url = `/api/lecturas?device_id=${dispositivoActivoId}&sensor=${encodeURIComponent(filtroHistorico)}`;
    const datos = await api(url);
    renderizarTablaHistoricos(datos.registros);
  } catch (err) {
    mensajeTabla(err.message);
  }
}

document.querySelectorAll(".tab").forEach((tab) => {
  tab.addEventListener("click", () => {
    filtroHistorico = tab.dataset.sensor;
    document.querySelectorAll(".tab").forEach((t) => t.classList.toggle("active", t === tab));
    document.getElementById("titulo-historicos").textContent =
      filtroHistorico === "Todos" ? "Registros históricos" : `Historial de ${tab.textContent.toLowerCase()}`;
    cargarHistoricos();
  });
});

// -----------------------------------------------------
// INICIO
// -----------------------------------------------------
document.addEventListener("DOMContentLoaded", async () => {
  if (!localStorage.getItem(LS_TOKEN)) {
    mostrarLogin();
    return;
  }
  try {
    const yo = await api("/api/me");
    await entrarALaApp(yo.usuario);
  } catch (err) {
    mostrarLogin();
    document.getElementById("login-error").textContent = err.message;
  }
});
