// =====================================================
// AQUAMONITOR — script.js
// Dos formas de recibir datos del ESP32:
//   1) WiFi:      el ESP32 envía al servidor (app.py) y este panel lo consulta.
//   2) Bluetooth: este panel se conecta directo al ESP32 (Web Bluetooth).
// =====================================================

let csrfToken = null;
let sessionVersion = 0;
// Remove obsolete browser-readable sessions from the earlier version.
localStorage.removeItem("aquamonitor_token");
const LS_USUARIO = "aquamonitor_usuario";
const LS_DISPOSITIVO = "aquamonitor_dispositivo_activo";
const INTERVALO_LECTURAS_MS = 4000;

// Deben ser iguales a los del código del ESP32
const BLE_SERVICE = "a9e30001-6c1b-4a4e-9a31-5f0b7c2d8e10";
const BLE_CHAR = "a9e30002-6c1b-4a4e-9a31-5f0b7c2d8e10";
const BLE_SIN_DATO = 0x7fff; // valor que usa el ESP32 cuando un sensor no responde

let sensores = { temperatura: null, nivelAgua: null, turbidez: null };
let dispositivos = [];
let dispositivoActivoId = Number(localStorage.getItem(LS_DISPOSITIVO)) || null;
let wifiEstado = null; // "en_linea" | "sin_senal" | "sin_datos" | null
let filtroHistorico = "Todos";
let ultimaRecargaHistoricos = 0;
let cursorHistorico = null;
let historicoCargando = false;
let historicoHaCargadoMas = false;
let solicitudHistorico = 0;
let timerLecturas = null;
let timerVigencia = null;
let lecturaVigenteHasta = 0;
let ultimoTimestampLectura = null;
const MAX_EDAD_LECTURA_S = 30;
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
  const version = sessionVersion;
  if (csrfToken && !sinToken) headers["X-CSRF-Token"] = csrfToken;

  let resp;
  try {
    resp = await fetch(ruta, { ...fetchOpts, headers, credentials: "same-origin" });
    if (version !== sessionVersion) throw new Error("La sesión cambió.");
  } catch (e) {
    throw new Error("No hay conexión con el servidor AquaMonitor.");
  }

  let datos = {};
  try { datos = await resp.json(); } catch (e) { /* respuesta sin JSON */ }
  if (version !== sessionVersion) throw new Error("La sesión cambió.");

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
// ACCESO
// -----------------------------------------------------
const authScreen = document.getElementById("auth-screen");
const appEl = document.getElementById("app");
const formLogin = document.getElementById("form-login");

function guardarSesion(datos) {
  csrfToken = datos.csrf_token;
  sessionVersion++;
  localStorage.setItem(LS_USUARIO, datos.usuario);
}

async function cerrarSesion(servidor = false) {
  if (servidor) {
    try {
      await api("/api/logout", { method: "POST", body: "{}" });
    } catch (err) {
      mostrarAviso(err.message);
      return;
    }
  }
  csrfToken = null;
  sessionVersion++;
  solicitudHistorico++;
  historicoCargando = false;
  document.getElementById("tabla-historicos-body").replaceChildren();
  renderizarGraficas([]);
  document.getElementById("lista-mis-dispositivos").replaceChildren();
  ultimoTimestampLectura = null;
  mostrarSinDatos("Inicia sesión.");
  detenerLecturas();
  cerrarModalEscaner();
  if (bleDevice && bleDevice.gatt.connected) bleDevice.gatt.disconnect();
  bleActivo = false;
  bleDevice = null;
  wifiEstado = null;

  localStorage.removeItem(LS_USUARIO);
  localStorage.removeItem(LS_DISPOSITIVO);
  dispositivos = [];
  dispositivoActivoId = null;
  actualizarEstadoConexion();
  irAVista("dashboard");
  mostrarLogin();
}

function mostrarLogin() {
  appEl.classList.add("hidden");
  authScreen.classList.remove("hidden");
  formLogin.classList.remove("hidden");
  formLogin.reset();
  document.getElementById("login-error").textContent = "";
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
  // A user may open history while their device list is still loading.
  if (!vistas.historicos.classList.contains("hidden")) await cargarHistoricos();
  iniciarLecturas();
}

formLogin.addEventListener("submit", async (e) => {
  e.preventDefault();
  const errEl = document.getElementById("login-error");
  errEl.textContent = "";
  const usuario = document.getElementById("login-usuario").value.trim();
  const password = document.getElementById("login-password").value;
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

document.getElementById("btn-logout").addEventListener("click", () => cerrarSesion(true));

// -----------------------------------------------------
// MONITOREO
// -----------------------------------------------------
function sinSensor(idSensor) {
  actualizarUI(idSensor, "--", "Sin sensor", "off", null, "Este dispositivo todavía no envía este dato.");
}

function mostrarDetalleNivel(distancia, calibracion) {
  const el = document.getElementById("distancia-nivelAgua");
  if (!el) return;
  const valida = typeof distancia === "number" && Number.isFinite(distancia) && distancia >= 2 && distancia <= 400;
  const referencia = calibracion === "provisional-7.8-2.0"
    ? "Calibración provisional: vacío 7,8 cm / lleno 2,0 cm."
    : "Calibración de origen no identificada.";
  el.textContent = (valida ? `Distancia: ${distancia.toFixed(2)} cm. ` : "Distancia del HC-SR04 no disponible en esta lectura. ") + referencia;
}

function lecturaActual(d) {
  const edad = typeof d.edad_s === "number" ? d.edad_s : Date.now()/1000-d.ts;
  return d.en_linea === true && Number.isFinite(d.ts) && Number.isFinite(edad) && edad >= 0 && edad <= MAX_EDAD_LECTURA_S;
}

function verificarVigenciaLectura() {
  if (!lecturaVigenteHasta || performance.now() < lecturaVigenteHasta) return;
  wifiEstado = "sin_senal";
  mostrarSinDatos("Medición antigua. Última lectura: " + formatearFecha(ultimoTimestampLectura) + ".");
  actualizarEstadoConexion();
}

function mostrarSinDatos(mensaje) {
  lecturaVigenteHasta = 0;
  const detalle = document.getElementById("distancia-nivelAgua");
  if (detalle) detalle.textContent = "Distancia: sin medición actual.";
  ["temperatura", "nivelAgua", "turbidez"].forEach((id) => {
    actualizarUI(id, "--", "Sin datos", "off", null, mensaje);
  });
  marcarActualizacion(Number.isFinite(ultimoTimestampLectura) ? new Date(ultimoTimestampLectura*1000) : null, false);
}

function marcarActualizacion(fecha, actual = true) {
  document.getElementById("ultima-actualizacion").textContent = fecha
    ? "Última recepción: " + formatearFecha(fecha.getTime()/1000) + (actual ? "" : " · sin lectura actual")
    : "Sin mediciones recibidas.";
}

function procesarSensores() {
  const { temperatura: t, turbidez: tb } = sensores;
  const digital = typeof t === "number" && Number.isFinite(t) && t >= -55 && t <= 125 && t !== 85;
  const derivada = t === null ? "sin_datos" : !digital ? "invalida" : t >= 0 && t <= 50 ? "valida" : "sospechosa";
  const calidad = derivada === "valida" || t === null ? sensores.temperaturaEstado || derivada : derivada;
  const recibido = sensores.nivelAgua;
  const distancia = sensores.distanciaCm;
  const compatible = sensores.nivelEstado === "valida" && sensores.nivelCalibracion === "provisional-7.8-2.0"
    && typeof distancia === "number" && Number.isFinite(distancia) && distancia >= 2 && distancia <= 400;
  const n = compatible && typeof recibido === "number" && Number.isFinite(recibido) && recibido >= 0 && recibido <= 100 ? recibido : null;

  if (calidad === "sospechosa") {
    const observada = typeof t === "number" && Number.isFinite(t) ? t : sensores.temperaturaObservada;
    const detalle = typeof observada === "number" && Number.isFinite(observada) ? `Recibida ${observada.toFixed(1)} °C; ` : "";
    actualizarUI("temperatura", "--", "Sospechosa", "alerta", null, detalle + "no se muestra como temperatura actual. Revisar sonda y contrastar con termómetro.");
  } else if (calidad === "invalida") {
    actualizarUI("temperatura", "--", "Lectura inválida", "alerta", null, "DS18B20 sin lectura válida: revisar conexión, conversión y alimentación.");
  } else if (t === null) actualizarUI("temperatura", "--", "Sin dato válido", "off", null, "No se recibió una temperatura utilizable; no se reutiliza una lectura anterior.");
  else if (t < 16) actualizarUI("temperatura", t, "Baja", "alerta", (t / 40) * 100, "Temperatura demasiado baja.");
  else if (t <= 26) actualizarUI("temperatura", t, "Normal", "ok", (t / 40) * 100, "Temperatura idónea.");
  else actualizarUI("temperatura", t, "Alta", "alerta", (t / 40) * 100, "Temperatura demasiado alta.");

  if (n === null) {
    const motivos = {
      sin_distancia_valida: "Falta una distancia válida del HC-SR04.",
      calibracion_no_identificada: "No está identificada la referencia 7,8/2,0 cm.",
      calibracion_incompatible: "El porcentaje recibido no corresponde a la distancia y referencia declaradas.",
      porcentaje_no_valido: "El porcentaje recibido no es válido."
    };
    actualizarUI("nivelAgua", "--", "Sin lectura válida", "off", null, "Sin lectura válida de nivel de agua. " + (motivos[sensores.nivelEstado] || "Faltan distancia y calibración verificables."));
  }
  else if (n < 45) actualizarUI("nivelAgua", n, "Bajo", "alerta", n, "Nivel bajo. Inicia el llenado.");
  else if (n <= 85) actualizarUI("nivelAgua", n, "Normal", "ok", n, "Nivel de agua idóneo.");
  else actualizarUI("nivelAgua", n, "Alto", "alerta", n, "Nivel en el límite alto.");

  if (tb === null) sinSensor("turbidez");
  else if (tb <= 50) actualizarUI("turbidez", tb, "Normal", "ok", tb, "Agua transparente.");
  else actualizarUI("turbidez", tb, "Alta", "alerta", tb, "Agua con alta turbidez.");
}

// Muestra el estado de la conexión (WiFi o Bluetooth) y el nombre del dispositivo
function actualizarEstadoConexion() {
  const pill = document.getElementById("estado-conexion");
  const texto = document.getElementById("estado-conexion-texto");
  const chip = document.getElementById("dispositivo-actual-tag");
  const banner = document.getElementById("conexion-banner");
  const activo = dispositivos.find((d) => d.asignacion_id === dispositivoActivoId);

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
  const assignment = dispositivoActivoId;
  try {
    const d = await api(`/api/lecturas/ultima?asignacion_id=${assignment}`);
    if (bleActivo || assignment !== dispositivoActivoId) return;
    ocultarAviso();
    if (!d.sin_datos && Number.isFinite(d.ts)) ultimoTimestampLectura = d.ts;
    if (d.sin_datos) {
      wifiEstado = "sin_datos";
      mostrarSinDatos("Esperando datos del dispositivo.");
    } else if (dispositivos.find((item) => item.asignacion_id === dispositivoActivoId)?.anterior) {
      wifiEstado = "sin_senal";
      mostrarSinDatos("Periodo anterior. Consulta sus registros en Históricos.");
    } else if (!lecturaActual(d)) {
      wifiEstado = "sin_senal";
      mostrarSinDatos("Sin señal. Última lectura: " + formatearFecha(d.ts) + ".");
    } else {
      wifiEstado = "en_linea";
      const edad = typeof d.edad_s === "number" ? d.edad_s : Date.now()/1000-d.ts;
      lecturaVigenteHasta = performance.now() + (MAX_EDAD_LECTURA_S-edad)*1000;
      ultimoTimestampLectura = d.ts;
      sensores = {
        temperatura: d.temperatura,
        temperaturaEstado: d.temperatura_estado,
        temperaturaObservada: d.temperatura_observada,
        nivelAgua: d.nivel_agua,
        nivelEstado: d.nivel_estado,
        distanciaCm: d.distancia_cm,
        nivelCalibracion: d.nivel_calibracion,
        turbidez: d.turbidez
      };
      procesarSensores();
      mostrarDetalleNivel(d.distancia_cm, d.nivel_calibracion);
      marcarActualizacion(new Date(d.ts * 1000));
    }
  } catch (err) {
    if (bleActivo || assignment !== dispositivoActivoId) return;
    wifiEstado = "sin_senal";
    mostrarSinDatos("No se pudo verificar una medición actual. Consulta el historial para lecturas anteriores.");
    mostrarAviso(err.message);
  }
  actualizarEstadoConexion();
}

async function ciclo() {
  await actualizarLecturas();
  // Si estás viendo los históricos, se actualizan solos (llega un registro nuevo cada 2 minutos)
  if (!vistas.historicos.classList.contains("hidden")
      && !historicoCargando
      && !historicoHaCargadoMas
      && Date.now() - ultimaRecargaHistoricos >= 30000) {
    await cargarHistoricos();
  }
}

function iniciarLecturas() {
  detenerLecturas();
  ciclo();
  timerLecturas = setInterval(ciclo, INTERVALO_LECTURAS_MS);
  timerVigencia = setInterval(verificarVigenciaLectura, 1000);
}

function detenerLecturas() {
  clearInterval(timerVigencia);
  timerVigencia = null;
  lecturaVigenteHasta = 0;
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
    turbidez: leer(4, 10)
  };
  lecturaVigenteHasta = performance.now()+MAX_EDAD_LECTURA_S*1000;
  ultimoTimestampLectura = Date.now()/1000;
  procesarSensores();
  mostrarDetalleNivel(null, null);
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
      "Mientras tanto puedes conectar el ESP32 por WiFi con el botón «Conectar por WiFi» del panel de monitoreo."
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
    renderizarMisDispositivos();
  } catch (err) {
    mostrarAviso(err.message);
    return;
  }

  // Si el dispositivo guardado ya no existe, usar el primero de la lista
  if (!dispositivos.some((d) => d.asignacion_id === dispositivoActivoId)) {
    ultimoTimestampLectura = null;
    lecturaVigenteHasta = 0;
    dispositivoActivoId = dispositivos.length ? dispositivos[0].asignacion_id : null;
    if (dispositivoActivoId) localStorage.setItem(LS_DISPOSITIVO, dispositivoActivoId);
    else localStorage.removeItem(LS_DISPOSITIVO);
  }
  actualizarEstadoConexion();
}

function seleccionarDispositivo(id) {
  ultimoTimestampLectura = null;
  lecturaVigenteHasta = 0;
  dispositivoActivoId = id;
  localStorage.setItem(LS_DISPOSITIVO, id);
  cursorHistorico = null;
  historicoHaCargadoMas = false;
  wifiEstado = null;
  if (!bleActivo) mostrarSinDatos("Cargando datos...");
  actualizarEstadoConexion();
  actualizarLecturas();
  if (!vistas.historicos.classList.contains("hidden")) cargarHistoricos();
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
  if (vista === "historicos") cargarHistoricos();
  if (vista === "dispositivos") cargarDispositivos();
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
const modalScanner = document.getElementById("modal-scanner");

function abrirModalEscaner() {
  modalScanner.classList.remove("hidden");
  document.getElementById("form-vincular").reset();
  document.getElementById("vincular-error").textContent = "";
  document.getElementById("vincular-codigo").focus();
}

document.getElementById("form-vincular").addEventListener("submit", async (event) => {
  event.preventDefault();
  const button = document.getElementById("btn-vincular-codigo");
  const error = document.getElementById("vincular-error");
  button.disabled = true;
  error.textContent = "";
  try {
    const result = await api("/api/dispositivos/vincular", {
      method: "POST",
      body: JSON.stringify({
        codigo: document.getElementById("vincular-codigo").value.replace(/[ -]/g, "").toUpperCase(),
        nombre: document.getElementById("vincular-nombre").value.trim()
      })
    });
    cerrarModalEscaner();
    await cargarDispositivos();
    seleccionarDispositivo(result.dispositivo.asignacion_id);
  } catch (err) {
    error.textContent = err.message;
  } finally {
    button.disabled = false;
  }
});

function renderizarMisDispositivos() {
  const list = document.getElementById("lista-mis-dispositivos");
  list.replaceChildren();
  if (!dispositivos.length) {
    list.appendChild(crearEl("p", "dispositivos-vacio", "Aún no tienes dispositivos. Añade tu ESP32 mediante su código temporal."));
  }
  dispositivos.forEach((device) => {
    const card = crearEl("article", "dispositivo-card");
    const label = device.anterior ? "Anterior · historial conservado" : device.envios_activos ? (device.en_linea ? "En línea" : "Sin señal") : "Envíos deshabilitados";
    card.appendChild(crearEl("h2", "dispositivo-nombre", device.nombre));
    card.appendChild(crearEl("p", "", label));
    const select = crearEl("button", "btn btn-ghost btn-small", device.anterior ? "Consultar historial" : "Seleccionar");
    select.type = "button";
    select.addEventListener("click", () => {
      seleccionarDispositivo(device.asignacion_id);
      irAVista(device.anterior ? "historicos" : "dashboard");
    });
    card.appendChild(select);
    if (!device.anterior) {
      const details = crearEl("details", "device-actions");
      details.appendChild(crearEl("summary", "", "Gestionar dispositivo"));
      details.appendChild(crearEl("p", "", "Confirma tu contraseña. Revocar detiene los envíos; recuperar los autoriza durante 10 minutos. Liberar permite transferir el equipo y conserva tu historial."));
      const password = crearEl("input", "auth-input");
      password.type = "password";
      password.autocomplete = "current-password";
      password.placeholder = "Tu contraseña";
      password.setAttribute("aria-label", "Confirma tu contraseña para " + device.nombre);
      details.appendChild(password);
      const message = crearEl("p", "auth-error");
      message.setAttribute("role", "alert");
      const actions = crearEl("div", "device-action-buttons");
      [["revocar", "Revocar envíos"], ["recuperar", "Autorizar recuperación"], ["liberar", "Liberar para transferencia"], ["bloquear", "Bloquear identidad"]].forEach(([action,title]) => {
        const button = crearEl("button", "btn btn-ghost btn-small", title);
        button.type = "button";
        button.addEventListener("click", async () => {
          if (!password.value) { message.textContent = "Escribe tu contraseña."; return; }
          if ((action === "liberar" || action === "bloquear") && !window.confirm(action === "liberar" ? "¿Liberar este dispositivo? Conservarás tu historial y el nuevo propietario no podrá verlo." : "¿Bloquear toda la identidad? Se detendrán los envíos y la configuración remota. Requerirá reprovisionamiento físico.")) return;
          const buttons = actions.querySelectorAll("button");
          buttons.forEach((item) => item.disabled = true);
          try {
            await api(`/api/dispositivos/${device.id}/${action}`, { method: "POST", body: JSON.stringify({ password: password.value }) });
            password.value = "";
            await cargarDispositivos();
            await actualizarLecturas();
          } catch (err) {
            message.textContent = err.message;
            buttons.forEach((item) => item.disabled = false);
          }
        });
        actions.appendChild(button);
      });
      details.appendChild(actions);
      details.appendChild(message);
      card.appendChild(details);
    }
    list.appendChild(card);
  });
}

function cerrarModalEscaner() {
  if (timerEscaner) clearInterval(timerEscaner);
  timerEscaner = null;
  modalScanner.classList.add("hidden");
}

document.getElementById("btn-cerrar-modal").addEventListener("click", cerrarModalEscaner);
modalScanner.addEventListener("click", (e) => { if (e.target === modalScanner) cerrarModalEscaner(); });

document.getElementById("btn-banner-wifi").addEventListener("click", abrirModalEscaner);

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
  document.getElementById("btn-mas-historicos").classList.add("hidden");
}

function renderizarTablaHistoricos(lista, anexar = false) {
  if (lista.length === 0 && !anexar) {
    mensajeTabla("Todavía no hay registros para este sensor.");
    return;
  }

  const tbody = document.getElementById("tabla-historicos-body");
  if (!anexar || tbody.querySelector(".tabla-vacia")) tbody.replaceChildren();
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

async function cargarHistoricos(reiniciar = true) {
  if (historicoCargando && !reiniciar) return;
  const solicitud = ++solicitudHistorico;
  ultimaRecargaHistoricos = Date.now();
  if (!dispositivoActivoId) {
    renderizarGraficas([]);
    cursorHistorico = null;
    historicoHaCargadoMas = false;
    historicoCargando = false;
    mensajeTabla("Vincula un dispositivo por WiFi para ver sus registros. Las lecturas por Bluetooth no se guardan.");
    return;
  }
  if (reiniciar) {
    cursorHistorico = null;
    historicoHaCargadoMas = false;
    document.getElementById("btn-mas-historicos").classList.add("hidden");
  } else if (!cursorHistorico) {
    return;
  }

  const botonMas = document.getElementById("btn-mas-historicos");
  historicoCargando = true;
  botonMas.disabled = true;
  try {
    const parametros = new URLSearchParams({
      asignacion_id: dispositivoActivoId,
      sensor: filtroHistorico
    });
    if (!reiniciar && cursorHistorico) {
      parametros.set("cursor_ts", cursorHistorico.ts);
      parametros.set("cursor_id", cursorHistorico.id);
      parametros.set("snapshot_id", cursorHistorico.snapshot_id);
    }
    const url = `/api/lecturas?${parametros}`;
    const graficas = reiniciar ? api("/api/lecturas/graficas?" + new URLSearchParams({ asignacion_id: dispositivoActivoId })).catch(() => null) : null;
    const [datos, serie] = await Promise.all([api(url), graficas]);
    if (solicitud !== solicitudHistorico) return;
    if (reiniciar) renderizarGraficas(serie?.lecturas || []);
    renderizarTablaHistoricos(datos.registros, !reiniciar);
    cursorHistorico = datos.cursor;
    if (!reiniciar) historicoHaCargadoMas = true;
    botonMas.classList.toggle("hidden", !cursorHistorico);
  } catch (err) {
    if (solicitud !== solicitudHistorico) return;
    if (reiniciar) mensajeTabla(err.message);
    else mostrarAviso(err.message);
  } finally {
    if (solicitud === solicitudHistorico) {
      historicoCargando = false;
      botonMas.disabled = false;
    }
  }
}

document.getElementById("btn-mas-historicos").addEventListener("click", () => {
  cargarHistoricos(false);
});

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
  try {
    const yo = await api("/api/me", { sinToken: true });
    csrfToken = yo.csrf_token;
    await entrarALaApp(yo.usuario);
  } catch (err) {
    mostrarLogin();
  }
});

document.getElementById("btn-anadir-dispositivo").addEventListener("click", abrirModalEscaner);

document.getElementById("btn-refrescar-dispositivos").addEventListener("click", cargarDispositivos);
