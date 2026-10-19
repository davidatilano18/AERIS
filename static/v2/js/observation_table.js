import {local,utc,fmt,element} from './format.js';
let rows=[],page=0;
const $=id=>document.getElementById(id);

function render() {
  const body=$('observationRows');body.replaceChildren();
  for(const r of rows.slice(page*100,(page+1)*100)) {
    const tr=element('tr');
    for(const v of [local(r.timestamp_utc),utc(r.timestamp_utc),fmt(r.value),!r.quality.evaluated?'Pendiente':`${r.quality.review?'En revisión':'Evaluada'} · ${r.quality.version}`])tr.append(element('td',v));
    body.append(tr);
  }
  if(!body.children.length){const tr=element('tr'),td=element('td','No hay observaciones seleccionadas para esta tabla.');td.colSpan=4;tr.append(td);body.append(tr);}
  $('tablePageInfo').textContent=rows.length?`Registros ${page*100+1}–${Math.min((page+1)*100,rows.length)} de ${rows.length}. Más recientes primero.`:'Sin registros seleccionados.';
  $('tableNewer').disabled=page===0;$('tableOlder').disabled=(page+1)*100>=rows.length;
}

export function setObservationTable(data) {
  rows=data?.public.selected?data.series.flatMap(s=>s.points.filter(p=>!p.gap)).sort((a,b)=>b.epoch_ms-a.epoch_ms):[];
  page=0;render();
}
for(const [id,step] of [['tableNewer',-1],['tableOlder',1]])$(id).addEventListener('click',()=>{
  page+=step;render();
  if($(id).disabled)$('tablePageInfo').focus({preventScroll:true});
});
