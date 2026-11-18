const renderizarGraficas = (() => {
  const cards = [...document.querySelectorAll("[data-chart]")];
  const units = { temperatura: "°C", turbidez: "NTU", nivel_agua: "%", distancia_cm: "cm" };
  const number = new Intl.NumberFormat("es-CO", { maximumFractionDigits: 2 });
  let readings = [];
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

  const drawAll = () => cards.forEach(draw);
  new ResizeObserver(drawAll).observe(document.querySelector(".history-charts"));
  return (rows) => {
    readings = rows;
    drawAll();
  };
})();
