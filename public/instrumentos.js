function actualizarUI(idSensor, valor, textoEstado, tipo, pct, desc) {
  const valEl = document.getElementById(`val-${idSensor}`);
  const tagEl = document.getElementById(`tag-${idSensor}`);
  const descEl = document.getElementById(`desc-${idSensor}`);
  if (!valEl) return;

  if (typeof valor === "number") {
    const unidades = { temperatura: "°C", nivelAgua: "%", turbidez: "NTU" };
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
    agua.classList.toggle("sin-lectura", pct === null);
    const avisoNivel = document.getElementById("nivel-sin-lectura");
    if (avisoNivel) avisoNivel.classList.toggle("hidden", pct !== null);
    agua.parentElement.setAttribute("aria-label", pct === null ? "Sin lectura válida de nivel de agua" : `Nivel de agua: ${valor.toFixed(1)} %`);
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
