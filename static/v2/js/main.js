import {fetchObservations} from './api.js';
import {fmt, utc, local, age, element} from './format.js';
import {renderChart, clearChart} from './chart.js';
import {initializeMap, renderStations, clearMap} from './map.js';

const $ = id => document.getElementById(id);
const controls = ['source', 'station', 'period'];
let sequence = 0, controller;
const query = new URLSearchParams(location.search);
if (['OpenAQ', 'OpenAQ-Archive'].includes(query.get('source'))) $('source').value = query.get('source');
if (['24h', '7d', '30d', 'all'].includes(query.get('period'))) $('period').value = query.get('period');
if ($('source').value === 'OpenAQ-Archive' && !query.has('period')) $('period').value = 'all';
if (/^\d+$/.test(query.get('station') || '')) {
  $('station').append(new Option(`Sensor ${query.get('station')}`, query.get('station'))); $('station').value = query.get('station');
}

function populateSelect(stations, selection) {
  $('station').replaceChildren(new Option('Todas las estaciones', 'all'));
  for (const station of stations) $('station').append(new Option(station.name, String(station.sensor_id)));
  $('station').value = selection.station;
}

function renderStats(data) {
  const stats = data.stats, latest = stats.latest;
  $('latestValue').textContent = latest ? utc(latest.timestamp_utc).replace(' UTC', '') : 'Sin datos';
  $('latestDetail').textContent = latest ? `${latest.name} · UTC / ${local(latest.timestamp_utc)}` : 'No hay observaciones en el periodo seleccionado';
  $('stationCount').textContent = fmt(stats.stations_with_data);
  $('stationDetail').textContent = `${fmt(stats.count)} observaciones · ${data.selection.station === 'all' ? `${fmt(data.stations.length)} sensores catalogados` : 'sensor seleccionado'}`;
  $('meanValue').textContent = fmt(stats.mean);
  $('meanDetail').textContent = 'µg/m³ · media de registros, no espacial';
  $('ageValue').textContent = age(stats.age_hours);
  $('ageDetail').textContent = 'De la lectura más reciente del filtro';
  $('reviewCount').textContent = fmt(stats.review); $('pendingCount').textContent = fmt(stats.pending_quality);
  const fresh = data.source === 'OpenAQ' && stats.age_hours !== null && stats.age_hours >= 0 && stats.age_hours <= 2;
  $('dataStatus').dataset.state = fresh ? 'fresh' : 'stale';
  $('dataStatus').textContent = !latest ? 'Sin datos en el filtro' : data.source === 'OpenAQ-Archive' ? 'Archivo histórico · no actualidad' : fresh ? 'Última lectura ≤2 h' : 'Última lectura >2 h';
  $('selectionNote').textContent = `${data.source_label} · ${stats.count ? `${fmt(stats.count)} observaciones reales en el filtro` : 'Sin observaciones en este rango'} · Fechas UTC. Los últimos días se calculan respecto de hoy; “Todo lo disponible” permite consultar periodos históricos.`;
  $('chartSource').textContent = data.source_label;
  $('provenanceSource').textContent = data.source_label;
  $('generatedAt').textContent = utc(data.generated_at_utc);
  $('windowText').textContent = `${data.window.from_utc ? utc(data.window.from_utc) : 'Inicio disponible de esta fuente'} → ${utc(data.window.to_exclusive_utc)} (fin exclusivo)`;
}

function renderTable(data) {
  const body = $('observationsTable'); body.replaceChildren();
  $('tableCount').textContent = `(${data.recent_observations.length})`;
  for (const row of data.recent_observations) {
    const tr = element('tr');
    for (const value of [row.name, utc(row.timestamp_utc), local(row.timestamp_utc), fmt(row.value)]) tr.append(element('td', value));
    const cell = element('td'), q = row.quality;
    const tag = element('span', !q.evaluated ? 'Pendiente' : q.review ? 'En revisión' : 'Evaluada', `quality-tag${!q.evaluated ? ' pending' : q.review ? ' review' : ''}`);
    cell.append(tag, element('small', ` ${q.version || ''}${q.zero ? ' · cero observado' : ''}${q.extreme ? ' · extremo' : ''}${q.jump ? ' · salto' : ''}`));
    tr.append(cell); body.append(tr);
  }
  if (!data.recent_observations.length) {
    const row = element('tr'), cell = element('td', 'Sin observaciones para esta combinación de filtros.'); cell.colSpan = 5; row.append(cell); body.append(row);
  }
}

async function load() {
  const requestId = ++sequence;
  if (controller) controller.abort(); controller = new AbortController();
  const filters = Object.fromEntries(controls.map(id => [id, $(id).value]));
  $('observedContent').setAttribute('aria-busy', 'true'); $('error').hidden = true; $('refresh').disabled = true;
  $('dataStatus').textContent = 'Consultando base local…'; delete $('dataStatus').dataset.state;
  $('selectionNote').textContent = 'Cargando la selección. Las cifras anteriores no se consideran actualizadas.';
  for (const id of ['latestValue', 'stationCount', 'meanValue', 'ageValue', 'reviewCount', 'pendingCount']) $(id).textContent = '—';
  for (const id of ['latestDetail', 'stationDetail', 'generatedAt', 'windowText', 'provenanceSource']) $(id).textContent = 'Consultando…';
  $('observationsTable').replaceChildren(); clearChart(); clearMap();
  document.documentElement.dataset.loadState = 'loading';
  try {
    const data = await fetchObservations($('contenido').dataset.api, filters, controller.signal);
    if (requestId !== sequence) return;
    populateSelect(data.stations, data.selection); renderStats(data); renderTable(data);
    renderChart(data); renderStations(data, id => { $('station').value = id; load(); });
    history.replaceState(null, '', `${location.pathname}?${new URLSearchParams(filters)}${location.hash}`);
    document.documentElement.dataset.loadState = 'ready';
  } catch (error) {
    if (error.name === 'AbortError' || requestId !== sequence) return;
    $('error').textContent = `${error.message} Puedes cambiar los filtros o volver a actualizar la vista.`; $('error').hidden = false;
    $('dataStatus').textContent = 'No se pudo actualizar'; delete $('dataStatus').dataset.state;
    $('selectionNote').textContent = 'Consulta no disponible. No se muestran valores de una selección anterior como actuales.';
    clearChart('No se pudo cargar la serie. Ninguna observación ha sido modificada.');
    $('stationList').replaceChildren(element('p', 'Catálogo no disponible en esta consulta.', 'muted'));
    document.documentElement.dataset.loadState = 'error';
  } finally {
    if (requestId === sequence) { $('observedContent').setAttribute('aria-busy', 'false'); $('refresh').disabled = false; }
  }
}

$('filters').addEventListener('submit', event => event.preventDefault());
for (const id of controls) $(id).addEventListener('change', () => {
  if (id === 'source') $('period').value = $('source').value === 'OpenAQ-Archive' ? 'all' : '7d';
  load();
});
$('refresh').addEventListener('click', load);
initializeMap(); load();
