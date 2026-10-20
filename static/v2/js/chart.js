import {utc, local, fmt} from './format.js';
let chart = null;
const colors = ['#0f766e', '#3159a5', '#9b5720', '#8851a0', '#306b83', '#695723', '#a13950', '#536372'];

export function clearChart(message = 'Consultando observaciones…') {
  if (chart) { chart.destroy(); chart = null; }
  document.getElementById('chartMessage').textContent = message;
  document.getElementById('chartMessage').hidden = false;
}

export function renderChart(data) {
  clearChart();
  const message = document.getElementById('chartMessage');
  if (!data.stats.count) {
    message.textContent = 'No hay observaciones en este periodo. Prueba otro rango o selecciona “Todo lo disponible”.';
    return;
  }
  if (!window.Chart) {
    message.textContent = 'No se pudo cargar la biblioteca local de gráficas. Consulta la tabla de observaciones.';
    return;
  }
  message.hidden = true;
  chart = new window.Chart(document.getElementById('pmChart'), {
    type: 'line',
    data: {datasets: data.series.map((series, i) => ({
      label: series.name, data: series.points.map(point => ({x: point.epoch_ms, y: point.value, observation: point})),
      parsing: false, borderColor: colors[i % colors.length], backgroundColor: colors[i % colors.length],
      borderWidth: 1.8, tension: 0, spanGaps: false, fill: false,
      pointRadius: data.stats.count > 600 ? 0 : 2, pointHitRadius: 7,
    }))},
    options: {
      responsive: true, maintainAspectRatio: false, animation: false,
      interaction: {mode: 'nearest', axis: 'x', intersect: false},
      plugins: {
        legend: {position: 'bottom', labels: {usePointStyle: true, pointStyle: 'line', boxWidth: 16, font: {size: 10}, padding: 16, color: '#526477'}},
        tooltip: {callbacks: {
          title: items => items.length ? utc(items[0].parsed.x) : '',
          label: context => `${context.dataset.label}: ${fmt(context.parsed.y)} µg/m³`,
          afterLabel: context => {
            const row = context.raw.observation;
            if (row.gap) return 'Hora sin observación';
            const q = row.quality;
            return [local(row.timestamp_utc), `${data.source_label} · ${q.version || 'Calidad pendiente'}`, q.review ? 'Alerta de revisión técnica' : q.evaluated ? 'Evaluada; sin alerta de revisión' : 'Sin evaluación inicial'];
          },
        }},
      },
      scales: {
        x: {type: 'linear', grid: {display: false}, title: {display: true, text: 'Tiempo de observación · UTC', color: '#526477', font: {size: 10}}, ticks: {
          maxTicksLimit: 7, color: '#526477', font: {size: 9},
          callback: value => new Date(value).toISOString().slice(5, 16).replace('T', ' '),
        }},
        y: {beginAtZero: true, grid: {color: '#edf1f5'}, title: {display: true, text: 'PM2.5 (µg/m³)', color: '#526477', font: {size: 10}}, ticks: {font: {size: 10}, color: '#526477'}},
      },
    },
  });
}
