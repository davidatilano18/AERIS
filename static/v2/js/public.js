import {fetchObservations} from './api.js';
import {fmt,local,utc,element} from './format.js';
import {initializeMap,renderStations,clearMap} from './map.js';
import {renderPublicChart,clearPublicChart} from './public_chart.js';
import {loadComparison,clearComparison} from './comparison.js';
import {setObservationTable} from './observation_table.js';
const $=id=>document.getElementById(id);
const query=new URLSearchParams(location.search);
let catalog=[],inventory=[],sequence=0,controller;
const sourceName=s=>s==='OpenAQ-Archive'?'OpenAQ Archive':'OpenAQ · fuente registrada';
const elapsed=h=>h===null?'Sin observaciones':h>=48?`${fmt(h/24)} días`:h<1?`${fmt(h*60)} minutos`:`${fmt(h)} horas`;
if (['OpenAQ','OpenAQ-Archive'].includes(query.get('source'))) $('source').value=query.get('source');
if (['24h','7d','30d','all'].includes(query.get('period'))) $('period').value=query.get('period');
else if ($('source').value==='OpenAQ-Archive') $('period').value='all';
if (/^\d+$/.test(query.get('station')||'')) { $('station').append(new Option('Estación seleccionada',query.get('station'))); $('station').value=query.get('station'); }
if (['recent','latest'].includes(query.get('comparison'))) $('comparisonAnchor').value=query.get('comparison');
else if ($('period').value==='all') $('comparisonAnchor').value='latest';

function populate(selected) {
  const municipality=selected!=='all'?catalog.find(s=>String(s.sensor_id)===selected)?.municipality:$('municipality').value;
  const names=[...new Set(catalog.map(s=>s.municipality))].sort((a,b)=>a.localeCompare(b,'es'));
  $('municipality').replaceChildren(new Option('Todos los municipios disponibles','all'),...names.map(n=>new Option(n,n)));
  $('municipality').value=names.includes(municipality)?municipality:'all';
  $('station').replaceChildren(new Option('Elige una estación','all'));
  for (const station of catalog.filter(s=>$('municipality').value==='all'||s.municipality===$('municipality').value))
    $('station').append(new Option(`${station.name} · ${station.municipality}`,String(station.sensor_id)));
  $('station').value=selected;
}

function renderHistory(data) {
  const box=$('historyOptions'); box.replaceChildren();
  const rows=inventory.filter(r=>String(r.sensor_id)===data.selection.station);
  if (!rows.length) box.append(element('p',data.public.selected?'No tenemos observaciones de esta estación en ninguna de las dos fuentes.':'Elige una estación para ver sus fechas disponibles.'));
  for (const source of [...new Set(rows.map(r=>r.source))]) {
    const group=rows.filter(r=>r.source===source), count=group.reduce((n,r)=>n+r.count,0);
    const button=element('button',undefined,'history-option');button.type='button';
    button.dataset.historySource=source;
    button.append(element('strong',`${sourceName(source)} · ${group.map(r=>r.year).join(', ')}`),
      element('small',`${fmt(count)} registros · explorar historial, no actualidad`));
    button.addEventListener('click',()=>choose(data.selection.station,source,'all'));box.append(button);
  }
  const marques=catalog.find(s=>s.sensor_id===1352686);
  const historical=inventory.filter(r=>r.sensor_id===1352686&&r.source==='OpenAQ');
  $('marquesHistory').hidden=!marques||!historical.length;
  $('marquesNote').textContent=historical.length?`${fmt(historical.reduce((n,r)=>n+r.count,0))} registros de ${historical.map(r=>r.year).join(', ')}. No son datos actuales.`:'';
}

function renderReading(data) {
  const p=data.public, last=data.station_latest;
  const labels={unselected:'Elige una estación',no_observations:'Sin observaciones',historical:'Registro histórico',recent:'Medición reciente · ≤2 h',stale:'Última medición antigua · >2 h'};
  $('readingState').textContent=labels[p.state];$('readingState').dataset.state=p.state;
  $('latestValue').textContent=last?fmt(last.value):'—';
  $('readingTitle').textContent=p.state==='historical'?'¿Qué se registró en ese momento?':'¿Qué registró esta estación?';
  $('stationName').textContent=catalog.find(s=>String(s.sensor_id)===data.selection.station)?.name||'Por seleccionar';
  $('measuredAt').textContent=last?local(last.timestamp_utc):'Sin observaciones';
  $('ageValue').textContent=elapsed(p.age_hours);$('sourceLabel').textContent=sourceName(data.source);
  const messages={unselected:'Selecciona una estación. No calculamos un valor que represente todo Querétaro.',
    no_observations:'Esta estación está en el catálogo, pero no tiene mediciones en esta fuente. Revisa si existe historial en otra fuente.',
    historical:'Es un dato histórico: no describe el aire de hoy. Su fuente no se mezcla con otras series.',
    stale:'No tenemos una medición suficientemente reciente para describir la situación actual. Este es el último valor disponible.',
    recent:'Esta es la última concentración disponible de esta estación. Su antigüedad no determina una categoría de salud.'};
  $('readingMessage').textContent=messages[p.state]+(last&&(!data.stats.latest||last.timestamp_utc!==data.stats.latest.timestamp_utc)?' La lectura está fuera del periodo elegido para la gráfica.':'');
  $('qualityNote').textContent=last?`${!last.quality.evaluated?'Revisión inicial pendiente':last.quality.review?'Tiene una alerta de revisión automática':'Revisión automática inicial disponible'} · No acredita validación oficial.${last.sensor_id===1352686?' El historial heredado no tiene recibos API asociados; la trazabilidad es limitada.':''}`:'La ausencia de observaciones no demuestra que una estación esté averiada.';
  $('dataStatus').textContent=`${labels[p.state]} · La vista consulta registros locales; no descarga nuevas mediciones.`;
  $('consultedAt').textContent=`Vista consultada: ${local(data.generated_at_utc)}. No es la fecha de medición.`;
}

function renderDetails(data) {
  const p=data.public,c=p.coverage;
  $('historicalNotice').hidden=!(p.state==='historical'||data.selection.period==='all'&&data.source==='OpenAQ-Archive');
  $('chartContext').textContent=p.selected?`${catalog.find(s=>String(s.sensor_id)===data.selection.station)?.name} · ${data.stats.count?`${local(c.from_utc)} a ${local(Date.parse(c.to_exclusive_utc)-3600000)}`:'Sin mediciones en el periodo elegido'}`:'Una estación a la vez. Sin promedios municipales.';
  $('chartSource').textContent=sourceName(data.source);
  $('chartSummary').textContent=p.explanation;
  $('pmChart').setAttribute('aria-label',`Evolución de PM2.5. ${$('chartContext').textContent}. ${p.explanation}`);
  $('observedHours').textContent=p.selected?`${fmt(c.observed_hours)} de ${fmt(c.expected_hours)}`:'Elige estación';
  $('missingHours').textContent=p.selected?fmt(c.missing_hours):'—';
  $('periodMean').textContent=p.descriptive_mean!==null?`${fmt(p.descriptive_mean)} µg/m³`:'Sin datos suficientes';
  $('coverageBasis').textContent=p.selected?(c.basis==='observed_span'?'Cobertura entre primera y última medición del historial, incluidos los extremos. No equivale a cobertura mensual o anual.':'Cobertura de todas las horas del periodo elegido, incluidos los huecos al inicio y al final.')+' La media requiere al menos 18 horas, 75% de cobertura y revisión sin alertas: es una regla descriptiva, no sanitaria.':'La cobertura se calcula por estación y fuente.';
  $('gapDetails').textContent=p.gaps.length?`${p.gaps.length} periodos sin registros. `+p.gaps.slice(0,12).map(g=>`${local(g.from_utc)} → ${local(g.to_exclusive_utc)} (fin exclusivo): ${fmt(g.hours)} h`).join('; ')+(p.gaps.length>12?'. Hay más huecos; el total de horas incluye todos.':''):'No hay huecos en las horas consultadas, o no hay una ventana con observaciones seleccionada.';
  setObservationTable(data);
  const inventoryBody=$('inventoryRows');inventoryBody.replaceChildren();
  for(const s of catalog){const rows=inventory.filter(r=>r.sensor_id===s.sensor_id);
    for(const r of rows.length?rows:[null]){const tr=element('tr');for(const v of [`${s.name} / ${s.municipality}`,r?`${sourceName(r.source)} / ${r.year}`:'Sin observaciones locales',r?fmt(r.count):'0',r?`${utc(r.first_utc)} → ${utc(r.latest_utc)}`:'No hay fechas disponibles'])tr.append(element('td',v));inventoryBody.append(tr);}}
  $('explorerLink').href=`/v2/datos?${new URLSearchParams({source:data.source,station:data.selection.station,period:data.selection.period})}`;
}

function choose(station,source=$('source').value,period=$('period').value) {
  if(period==='all')$('comparisonAnchor').value='latest';
  populate(station);$('station').value=station;$('source').value=source;$('period').value=period;load();
}
function clearReading(message) {
  for(const id of ['latestValue','measuredAt','ageValue','sourceLabel','observedHours','missingHours','periodMean'])$(id).textContent='—';
  $('readingState').textContent=message.startsWith('Consulta no disponible')?'Consulta no disponible':message;delete $('readingState').dataset.state;
  $('readingTitle').textContent='¿Qué registró esta estación?';$('readingMessage').textContent=message;
  $('stationName').textContent='Consultando…';$('qualityNote').textContent='';$('chartSummary').textContent=message;
  $('chartContext').textContent='';$('chartSource').textContent='Sin consulta actualizada';$('coverageBasis').textContent='';
  $('consultedAt').textContent=message;$('gapDetails').textContent='';$('historicalNotice').hidden=true;
  $('historyOptions').replaceChildren();$('marquesHistory').hidden=true;$('inventoryRows').replaceChildren();$('observationRows').replaceChildren();
  clearPublicChart(message);clearMap();
  clearComparison(message);$('comparisonUtc').textContent='';
  setObservationTable(null);
}
async function load() {
  const focused=document.activeElement;
  const focusKey=focused?.dataset.historySource?['historySource',focused.dataset.historySource]:
    focused?.dataset.stationFocus?['stationFocus',focused.dataset.stationFocus]:focused?.id==='openMarques'?['id','openMarques']:null;
  const id=++sequence;controller?.abort();controller=new AbortController();
  const filters={source:$('source').value,station:$('station').value,period:$('period').value};
  document.documentElement.dataset.loadState='loading';$('observedContent').setAttribute('aria-busy','true');
  $('refresh').disabled=true;$('error').hidden=true;clearReading('Consultando la selección…');$('dataStatus').textContent='Consultando la base local…';
  try {
    const data=await fetchObservations($('contenido').dataset.api,filters,controller.signal);
    if(id!==sequence)return;
    catalog=data.stations;inventory=data.inventory;populate(data.selection.station);data.source_label=sourceName(data.source);
    renderReading(data);renderHistory(data);renderDetails(data);renderPublicChart(data);
    renderStations(data,sid=>choose(sid));
    // Public list uses ordinary language and local time; detailed identifiers remain in the explorer.
    [...$('stationList').children].forEach((button,i)=>{
      const s=data.stations[i];const lines=button.querySelectorAll('small');
      button.dataset.stationFocus=String(s.sensor_id);
      if(lines[0])lines[0].textContent=s.municipality;
      if(lines[1])lines[1].textContent=!s.count?'Sin observaciones en esta fuente':s.fresh?'Medición reciente · hasta 2 horas':`Última medición hace ${elapsed(s.age_hours)}`;
      if(lines[2])lines[2].textContent=local(s.latest_utc);
    });
    await loadComparison(filters,controller.signal,()=>id===sequence);
    if(id!==sequence)return;
    if(focusKey&&document.activeElement===document.body){
      const [kind,key]=focusKey;
      const target=kind==='id'?$(key):[...document.querySelectorAll(kind==='historySource'?'[data-history-source]':'[data-station-focus]')].find(n=>n.dataset[kind]===key);
      if(target&&!target.hidden)target.focus({preventScroll:true});
    }
    history.replaceState(null,'',`${location.pathname}?${new URLSearchParams({...filters,comparison:$('comparisonAnchor').value})}${location.hash}`);
    document.documentElement.dataset.loadState='ready';
  } catch(error) {
    if(error.name==='AbortError'||id!==sequence)return;
    clearReading('Consulta no disponible. No mostramos cifras anteriores como actuales.');
    $('stationList').replaceChildren(element('p','Catálogo no disponible en esta consulta.','muted'));
    $('dataStatus').textContent='No se pudo consultar la selección';$('error').textContent=`${error.message} Cambia la selección o pulsa Actualizar vista.`;$('error').hidden=false;
    document.documentElement.dataset.loadState='error';
  } finally {if(id===sequence){$('refresh').disabled=false;$('observedContent').setAttribute('aria-busy','false');}}
}
$('filters').addEventListener('submit',e=>e.preventDefault());
$('municipality').addEventListener('change',()=>{populate('all');load();});
for(const id of ['station','period','comparisonAnchor'])$(id).addEventListener('change',load);
$('refresh').addEventListener('click',load);
$('openMarques').addEventListener('click',()=>choose('1352686','OpenAQ','all'));
initializeMap();load();
