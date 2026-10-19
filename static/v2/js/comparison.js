import {fetchObservations} from './api.js';
import {local,utc,fmt,element} from './format.js';
const $=id=>document.getElementById(id);

export function clearComparison(message='Elige una estación para comparar.') {
  $('comparisonSummary').textContent=message;
  $('comparisonState').textContent='Sin comparación';
  $('comparisonPeriods').textContent='';$('comparisonCoverage').textContent='';
  $('comparisonValues').hidden=true;$('previousMean').textContent='—';$('currentMean').textContent='—';
  $('comparisonRows').replaceChildren();$('comparisonMeta').textContent='';
  $('comparisonUtc').textContent='';$('comparisonPanel').setAttribute('aria-busy','false');
}

export async function loadComparison(filters,signal,isCurrent) {
  clearComparison(filters.station==='all'?'Elige una estación para comparar.':'Comprobando si hay horas suficientes para comparar…');
  if(filters.station==='all')return;
  $('comparisonPanel').setAttribute('aria-busy','true');
  try {
    const data=await fetchObservations($('comparisonPanel').dataset.api,{
      source:filters.source,station:filters.station,anchor:$('comparisonAnchor').value},signal);
    if(!isCurrent())return;
    $('comparisonState').textContent=data.status==='compared'?'Comparación descriptiva':'Información insuficiente';
    $('comparisonSummary').textContent=data.summary;
    const period=w=>`${local(w.from_utc)} → ${local(w.to_exclusive_utc)} (fin no incluido)`;
    $('comparisonPeriods').textContent=`${data.station_name} · ${data.source==='OpenAQ-Archive'?'OpenAQ Archive':'OpenAQ'}. Periodo anterior: ${period(data.previous)}. Periodo posterior: ${period(data.current)}. ${data.anchor_note}`;
    $('comparisonCoverage').textContent=`Horas utilizables: ${data.previous.usable_hours}/24 antes y ${data.current.usable_hours}/24 después. Horas emparejadas: ${data.matched_hours}/24. Se excluyen horas ausentes, negativas o sin revisión compatible; no se rellenan.`;
    if(data.status==='compared') {
      $('comparisonValues').hidden=false;
      $('previousMean').textContent=`${data.previous_display} µg/m³`;
      $('currentMean').textContent=`${data.current_display} µg/m³`;
    }
    $('comparisonMeta').textContent=`Método ${data.policy.version}. Dos ventanas UTC de 24 horas, con las mismas posiciones horarias. Mínimo 18 pares y 3 pares por cada tramo de seis horas; una versión de revisión inicial. “Similar” significa que las medias redondeadas a dos decimales coinciden; no es una prueba estadística. Los promedios usan solo los pares incluidos. Estado: ${data.reason_messages.join(' ')||'Suficiencia descriptiva cumplida'}. Versiones de revisión utilizadas: ${data.quality_versions.join(', ')||'ninguna'}.`;
    for(const p of data.pairs) {
      const tr=element('tr');
      for(const v of [local(p.previous_utc),local(p.current_utc),fmt(p.previous_value),fmt(p.current_value),
        p.included?'Sí':p.reason==='missing'?'No · falta una medición':p.reason==='quality_version_mismatch'?'No · revisión de distinta versión':'No · revisión o valor no utilizable'])tr.append(element('td',v));
      $('comparisonRows').append(tr);
    }
    $('comparisonUtc').textContent=`UTC anterior: ${utc(data.previous.from_utc)} → ${utc(data.previous.to_exclusive_utc)}. UTC posterior: ${utc(data.current.from_utc)} → ${utc(data.current.to_exclusive_utc)}. Ambos finales excluidos.`;
  }catch(error) {
    if(error.name==='AbortError'||!isCurrent())return;
    clearComparison(`No pudimos comprobar esta comparación. ${error.message}`);
    $('comparisonState').textContent='Consulta no disponible';
  }finally{if(isCurrent())$('comparisonPanel').setAttribute('aria-busy','false');}
}
