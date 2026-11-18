const cards = [...document.querySelectorAll("[data-chart]")];
const menu = [...document.querySelectorAll(".menu-item[data-view]")];
const tabs = [...document.querySelectorAll(".tab[data-sensor]")];
const units = { temperatura: "°C", turbidez: "NTU", nivel_agua: "%", distancia_cm: "cm" };
const labels = { temperatura: "Temperatura", turbidez: "Turbidez", nivel_agua: "Nivel de Agua", distancia_cm: "Distancia" };
const TIPOS = { ok: "estado-ok", alerta: "estado-alerta", off: "estado-off" };
const number = new Intl.NumberFormat("es-CO", { maximumFractionDigits: 2 });
const displayDate = new Intl.DateTimeFormat("es-CO", { dateStyle: "medium", timeStyle: "medium", timeZone: "America/Bogota" });
let readings = [];
let selectedSensor = "Todos";

function clamp(value, min, max) { return Math.max(min, Math.min(max, value)); }

function crearEl(tag, classes, content) {
  const el = document.createElement(tag);
  if (classes) el.className = classes;
  el.textContent = content;
  return el;
}

function stateFor(key, value) {
  if (key === "temperatura") return value < 16 ? "Baja" : value <= 26 ? "Normal" : "Alta";
  if (key === "nivel_agua") return value < 45 ? "Bajo" : value <= 85 ? "Normal" : "Alto";
  if (key === "turbidez") return value <= 50 ? "Normal" : "Alta";
  return "Medida";
}

function renderMonitoring() {
  const latest = readings.at(-1);
  const age = latest ? Date.now() / 1000 - latest.ts : Infinity;
  const fresh = age >= -5 && age <= 30;
  const status = fresh ? "Recepción reciente" : latest ? "Sin señal reciente" : "Sin mediciones";
  const date = latest ? displayDate.format(new Date(latest.ts * 1000)) + " (Colombia)" : "—";
  document.querySelector("#estado-conexion").classList.toggle("pill-off", !fresh);
  document.querySelector("#estado-conexion").classList.toggle("pill-ok", fresh);
  document.querySelector("#estado-conexion-texto").textContent = status;
  document.querySelector("#ultima-actualizacion").textContent = latest ? " · Última recepción: " + date : "";
  document.querySelector("#public-device-state").textContent = status;
  document.querySelector("#public-device-time").textContent = date;

  for (const [key, id, scale] of [["temperatura","temperatura",2.5],["nivel_agua","nivelAgua",1],["turbidez","turbidez",1]]) {
    const value = latest?.[key];
    if (!Number.isFinite(value)) {
      actualizarUI(id,"—","Sin dato válido","off",null,"Sin lectura válida del sensor.");
      continue;
    }
    const state = stateFor(key, value);
    const desc = key === "nivel_agua" ? "Porcentaje recibido de la estación." : "Lectura de la estación.";
    actualizarUI(id,value,state,state === "Normal" ? "ok" : "alerta",value * scale,
      fresh ? desc : "Última lectura registrada. " + desc);
  }
  const distance = latest?.distancia_cm;
  document.querySelector("#distancia-nivelAgua").textContent = Number.isFinite(distance) ? "Distancia: " + number.format(distance) + (fresh ? " cm." : " cm (última lectura).") : "Distancia: sin medición válida.";
}

function renderHistory() {
  const fragment = document.createDocumentFragment();
  for (const row of [...readings].reverse()) {
    for (const key of Object.keys(labels)) {
      if (selectedSensor !== "Todos" && selectedSensor !== labels[key]) continue;
      if (!Number.isFinite(row[key])) continue;
      const tr = document.createElement("tr");
      for (const text of [displayDate.format(new Date(row.ts * 1000)), labels[key], number.format(row[key]) + " " + units[key], stateFor(key,row[key])]) {
        tr.append(crearEl("td","",text));
      }
      fragment.append(tr);
    }
  }
  if (!fragment.childNodes.length) {
    const tr = document.createElement("tr");
    const td = crearEl("td","tabla-vacia","No hay lecturas válidas para este filtro.");
    td.colSpan = 4;
    tr.append(td);
    fragment.append(tr);
  }
  document.querySelector("#tabla-historicos-body").replaceChildren(fragment);
  cards.forEach(draw);
}

function navigate() {
  const hash = location.hash;
  const view = hash === "#historicos" ? "historicos" : hash === "#dispositivos" ? "dispositivos" : "dashboard";
  for (const link of menu) {
    const active = link.dataset.view === view;
    link.classList.toggle("active", active);
    if (active) link.setAttribute("aria-current","page");
    else link.removeAttribute("aria-current");
    document.querySelector("#view-" + link.dataset.view).classList.toggle("hidden", !active);
  }
  if (view === "historicos") renderHistory();
}

for (const tab of tabs) {
  tab.setAttribute("aria-pressed", String(tab.classList.contains("active")));
  tab.addEventListener("click", () => {
    selectedSensor = tab.dataset.sensor;
    for (const choice of tabs) {
      choice.classList.toggle("active", choice === tab);
      choice.setAttribute("aria-pressed", String(choice === tab));
    }
    renderHistory();
  });
}
window.addEventListener("hashchange", navigate);

function draw(card) {
  const key = card.dataset.chart;
  const format = value => number.format(value) + " " + units[key];
  const values = readings.map(row => row[key]).filter(Number.isFinite);
  const canvas = card.querySelector("canvas");
  const width = canvas.clientWidth;
  const height = canvas.clientHeight;
  if (!width || !height) return;
  const ratio = window.devicePixelRatio || 1;
  canvas.width = Math.round(width * ratio);
  canvas.height = Math.round(height * ratio);
  const ctx = canvas.getContext("2d");
  ctx.scale(ratio, ratio);
  const description = card.querySelector(".range");
  if (!values.length) {
    description.textContent = "Sin mediciones válidas en el historial reciente.";
    return;
  }
  const min = Math.min(...values);
  const max = Math.max(...values);
  const first = readings[0].ts;
  const duration = Math.max(1, readings.at(-1).ts - first);
  description.textContent = values.length + " lecturas · " + format(min) + " a " + format(max);
  canvas.setAttribute("aria-label", card.querySelector("h2").textContent + ". " + description.textContent);
  ctx.strokeStyle = "#d8e8e8";
  for (let i = 0; i < 3; i++) {
    const y = 10 + (height - 20) * i / 2;
    ctx.beginPath();
    ctx.moveTo(5, y);
    ctx.lineTo(width - 5, y);
    ctx.stroke();
  }
  ctx.strokeStyle = "#087e69";
  ctx.fillStyle = "#087e69";
  ctx.lineWidth = 2;
  ctx.beginPath();
  let previous;
  const points = [];
  for (const row of readings) {
    const value = row[key];
    if (!Number.isFinite(value)) { previous = undefined; continue; }
    const x = 5 + (width - 10) * (row.ts - first) / duration;
    const y = max === min ? height / 2 : height - 10 - (height - 20) * (value - min) / (max - min);
    if (!previous || row.ts - previous.ts > 30) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
    points.push([x, y]);
    previous = row;
  }
  ctx.stroke();
  for (const [x, y] of points) {
    ctx.beginPath();
    ctx.arc(x, y, 2, 0, Math.PI * 2);
    ctx.fill();
  }
}

async function refresh() {
  const notice = document.querySelector("#aviso-conexion");
  try {
    const response = await fetch("/api/publica/lecturas", { credentials: "omit", signal: AbortSignal.timeout(8000) });
    if (!response.ok) throw new Error("Datos no disponibles");
    readings = (await response.json()).lecturas;
    notice.classList.add("hidden");
    renderMonitoring();
    if (location.hash === "#historicos") renderHistory();
  } catch {
    notice.textContent = "No se pudieron actualizar las mediciones. Reintentando…";
    notice.classList.remove("hidden");
    renderMonitoring();
  } finally {
    setTimeout(refresh, 5000);
  }
}
new ResizeObserver(() => cards.forEach(draw)).observe(document.querySelector(".public-charts"));
navigate();
refresh();
