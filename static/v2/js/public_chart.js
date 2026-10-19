import {fmt, local, utc} from './format.js';
let chart;
export function clearPublicChart(message='Consultando mediciones…') {
  if (chart) chart.destroy(); chart=null;
  const node=document.getElementById('chartMessage'); node.hidden=false; node.textContent=message;
  document.getElementById('pmChart').hidden=true;
}

export function renderPublicChart(data) {
  clearPublicChart();
  if (!data.public.selected || !data.stats.count) {
    document.getElementById('chartMessage').textContent=data.public.selected ? 'No hay mediciones en este periodo. Explora las fechas disponibles de esta estación.' : 'Elige una estación para explorar sus mediciones.';
    return;
  }
  if (!window.Chart) { clearPublicChart('No se pudo cargar la gráfica local. Consulta la tabla de datos.'); return; }
  document.getElementById('chartMessage').hidden=true;
  document.getElementById('pmChart').hidden=false;
  const series=data.series[0], coverage=data.public.coverage;
  let min=Date.parse(coverage.from_utc), max=Date.parse(coverage.to_exclusive_utc)-3600000;
  if (min===max) {min-=1800000; max+=1800000;}
  const gaps={id:'missingHours',beforeDatasetsDraw(c) {
    const {ctx,chartArea:a,scales:{x}}=c;
    ctx.save();ctx.beginPath();ctx.rect(a.left,a.top,a.right-a.left,a.bottom-a.top);ctx.clip();
    for (const gap of data.public.gaps) {
      const left=Math.max(a.left,x.getPixelForValue(Date.parse(gap.from_utc)-1800000));
      const right=Math.min(a.right,x.getPixelForValue(Date.parse(gap.to_exclusive_utc)-1800000));
      ctx.fillStyle='#f0f3f5';ctx.fillRect(left,a.top,right-left,a.bottom-a.top);
      ctx.save();ctx.beginPath();ctx.rect(left,a.top,Math.max(0,right-left),a.bottom-a.top);ctx.clip();
      ctx.strokeStyle='#dce4e8';ctx.lineWidth=1;
      for (let i=left-(a.bottom-a.top);i<right;i+=9) {ctx.beginPath();ctx.moveTo(i,a.bottom);ctx.lineTo(i+(a.bottom-a.top),a.top);ctx.stroke();}
      ctx.restore();
    }ctx.restore();
  }};
  chart=new Chart(document.getElementById('pmChart'),{type:'line',plugins:[gaps],
    data:{datasets:[{label:`PM2.5 · ${series.name}`,data:series.points.map(p=>({x:p.epoch_ms,y:p.value,observation:p})),
      parsing:false,borderColor:'#087d76',backgroundColor:'#087d76',borderWidth:2,tension:0,spanGaps:false,
      pointRadius:data.stats.count>400?0:2,pointHitRadius:8}]},
    options:{responsive:true,maintainAspectRatio:false,animation:false,
      interaction:{mode:'nearest',axis:'x',intersect:false},
      plugins:{legend:{display:false},tooltip:{callbacks:{title:rows=>rows.length?local(rows[0].parsed.x):'',
        label:c=>`${fmt(c.parsed.y)} µg/m³ · ${data.source_label}`,
        afterLabel:c=>c.raw.observation.gap?'Sin medición':[
          utc(c.raw.observation.timestamp_utc),c.raw.observation.quality.review?'Dato con alerta de revisión':
          c.raw.observation.quality.evaluated?'Revisión automática inicial disponible':'Revisión inicial pendiente']}}},
      scales:{x:{type:'linear',min,max,grid:{display:false},
        title:{display:true,text:'Fecha y hora de Querétaro · America/Mexico_City',font:{size:11},color:'#536879'},
        ticks:{maxTicksLimit:innerWidth<600?3:6,font:{size:11},color:'#536879',callback:v=>new Intl.DateTimeFormat('es-MX',{
          timeZone:'America/Mexico_City',year:'numeric',month:'short',day:'numeric',hour:'2-digit',hourCycle:'h23'}).format(new Date(v))}},
        y:{beginAtZero:true,title:{display:true,text:'Concentración de PM2.5 · µg/m³',font:{size:11},color:'#536879'},
          ticks:{font:{size:11},color:'#536879'},grid:{color:'#eaf0f2'}}}}
  });
}
