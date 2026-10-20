'use strict';
(() => {
  const motion = document.getElementById('motionToggle');
  const reduced = window.matchMedia('(prefers-reduced-motion: reduce)');
  const updateMotion = () => {
    const paused = reduced.matches || document.body.classList.contains('motion-paused');
    motion.textContent = reduced.matches ? 'Movimiento reducido' : paused ? 'Reanudar movimiento' : 'Pausar movimiento';
    motion.setAttribute('aria-pressed', String(paused));
    motion.disabled = reduced.matches;
  };
  motion.addEventListener('click', () => { document.body.classList.toggle('motion-paused'); updateMotion(); });
  reduced.addEventListener('change', updateMotion); updateMotion();
  const status = document.getElementById('mapStatus');
  const tileButton = document.getElementById('tilesToggle');
  if(document.body.dataset.offline==='true'){tileButton.disabled=true;tileButton.textContent='Mapa base desactivado · sin conexión';}
  if (!window.L) { status.textContent = 'No se pudo cargar el mapa. Usa la lista de estaciones.'; tileButton.disabled = true; return; }
  const stations = JSON.parse(document.getElementById('stationData').textContent);
  const valid = stations.filter(s => Number.isFinite(s.lat) && Number.isFinite(s.lon));
  const map = L.map('homeMap', {scrollWheelZoom: false, zoomAnimation: false, fadeAnimation: false});
  map.attributionControl.addAttribution('Ubicaciones: catálogo OpenAQ · no es un mapa de concentraciones');
  if (valid.length) map.fitBounds(valid.map(s => [s.lat, s.lon]), {padding: [40, 40], maxZoom: 11, animate: false});
  else { map.setView([20.6, -100.4], 9); status.textContent = 'No hay ubicaciones verificadas para mostrar. La vista geográfica de referencia no implica estaciones.'; }
  // Geographic reference only: these lines are coordinates, never a measured surface.
  const bounds = map.getBounds();
  for (let lat=Math.ceil(bounds.getSouth()*10)/10;lat<bounds.getNorth();lat+=.1) {
    L.polyline([[lat,bounds.getWest()],[lat,bounds.getEast()]], {interactive:false,
      color:'#91c6c7',opacity:.15,weight:.6}).addTo(map);
    L.marker([lat,bounds.getEast()-.10], {interactive:false,keyboard:false,
      icon:L.divIcon({className:'coordinate-label',html:lat.toFixed(1)+'° N',iconSize:[45,12],iconAnchor:[0,6]})}).addTo(map);
  }
  for (let lon=Math.ceil(bounds.getWest()*10)/10;lon<bounds.getEast();lon+=.1) {
    L.polyline([[bounds.getSouth(),lon],[bounds.getNorth(),lon]], {interactive:false,
      color:'#91c6c7',opacity:.15,weight:.6}).addTo(map);
  }
  for (const station of valid) {
    const marker = L.circleMarker([station.lat, station.lon], {radius: station.sensor_id === 1352686 ? 9 : 6,
      color: station.records ? '#65ead1' : '#b2c6d1', fillColor: '#65ead1',
      fillOpacity: station.records ? .75 : 0, weight: 2});
    const box = document.createElement('div');
    const name = document.createElement('strong'); name.textContent = station.name; box.append(name);
    const place = document.createElement('p'); place.textContent = station.municipality; box.append(place);
    const dates = document.createElement('p'); dates.textContent = station.records ?
      `Con registros locales. Último instante: ${station.latest}. No indica frescura ni validación oficial.` : 'Sin observaciones locales. No describe el aire actual.';
    box.append(dates);
    const link = document.createElement('a'); link.textContent = 'Explorar esta estación →';
    const source = station.sources.some(s => s.source === 'OpenAQ') ? 'OpenAQ' : station.sources[0]?.source || 'OpenAQ';
    link.href = '/v2?' + new URLSearchParams({source, station: String(station.sensor_id), period: 'all'}); box.append(link);
    marker.bindPopup(box); marker.bindTooltip(() => { const label=document.createElement('span'); label.textContent=station.name; return label; }, {className: 'station-label'});
    marker.addTo(map);
    // Circle markers also need explicit keyboard access, not only pointer events.
    const path = marker.getElement(); path.setAttribute('tabindex', '0'); path.setAttribute('role', 'button');
    path.setAttribute('aria-label', `${station.name}, ${station.municipality}. ${station.records ? 'Con registros' : 'Sin registros locales'}`);
    path.addEventListener('keydown', event => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); marker.openPopup(); } });
  }
  if (valid.length) status.textContent=`${valid.length} ubicaciones catalogadas. Retícula de coordenadas, sin mapa de concentraciones.`;
  // Estaciones meteorológicas observadas (cuadrado): miden el tiempo, no contaminantes.
  fetch('/api/ambiental/v1/estaciones?fuente=noaa-ghcnh', {cache: 'no-store'}).then(r => r.ok ? r.json() : null).then(data => {
    for (const site of data?.estaciones || []) {
      const icon = L.divIcon({className: 'weather-mmqt-icon', iconSize: [16, 16], iconAnchor: [8, 8]});
      const marker = L.marker([site.latitud, site.longitud], {icon, keyboard: true, title: site.nombre});
      const box = document.createElement('div');
      const name = document.createElement('strong'); name.textContent = site.nombre;
      const place = document.createElement('p'); place.textContent = site.municipio + ' · estación meteorológica (NOAA GHCNh)';
      const note = document.createElement('p'); note.textContent = 'Mide temperatura, humedad, viento y presión. No mide PM2.5.';
      const link = document.createElement('a'); link.href = '#tiempo'; link.textContent = 'Ver el tiempo en El Marqués →';
      box.append(name, place, note, link);
      marker.bindPopup(box).bindTooltip(site.nombre, {className: 'station-label'}).addTo(map);
    }
    if (data?.estaciones?.length) {
      const key = document.createElement('span'); key.innerHTML = '<i class="key weather-key" aria-hidden="true"></i> Estación meteorológica (no mide contaminantes)';
      document.querySelector('.map-aside .legend')?.append(key);
    }
  }).catch(() => {});
  let tiles;
  tileButton.addEventListener('click', () => {
    if (tiles) { map.removeLayer(tiles); tiles = null; tileButton.setAttribute('aria-pressed','false'); tileButton.textContent='Activar mapa base en línea'; status.textContent='Mapa base desactivado. Los puntos y la lista permanecen disponibles.'; return; }
    tiles = L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {maxZoom: 18, attribution: '© OpenStreetMap contributors'}).addTo(map);
    tiles.on('tileerror', () => { status.textContent='No se pudo cargar el mapa base. Usa los puntos o la lista de estaciones.'; });
    tileButton.setAttribute('aria-pressed','true'); tileButton.textContent='Desactivar mapa base'; status.textContent='Mapa base en línea activado; requiere conexión externa.';
  });
})();

// Compact municipality navigation; existing station links remain available.
(() => {
  const mobile = matchMedia('(max-width: 760px)');
  const entries=[];
  for (const card of document.querySelectorAll('.municipality:not(.featured)')) {
    const list=card.querySelector('ul');if(!list)continue;
    const details=document.createElement('details');const summary=document.createElement('summary');
    summary.textContent='Explorar estaciones';list.before(details);details.append(summary,list);entries.push(details);
  }
  const sync=()=>entries.forEach(d=>d.open=!mobile.matches);
  mobile.addEventListener('change',sync);sync();
})();

// Entrada suave de secciones y navegación que sigue la lectura; sin JS todo queda visible.
(() => {
  const sections = [...document.querySelectorAll('main > section, main > .section')];
  if ('IntersectionObserver' in window) {
    document.documentElement.classList.add('js-reveal');
    const reveal = new IntersectionObserver(entries => {
      for (const entry of entries) if (entry.isIntersecting) { entry.target.classList.add('is-visible'); reveal.unobserve(entry.target); }
    }, {rootMargin: '0px 0px -8% 0px', threshold: .06});
    for (const section of sections) {
      if (section.classList.contains('hero')) continue;
      section.classList.add('reveal');
      reveal.observe(section);
    }
    const links = new Map([...document.querySelectorAll('.site-header nav a[href^="#"]')].map(a => [a.getAttribute('href').slice(1), a]));
    const current = new IntersectionObserver(entries => {
      for (const entry of entries) if (entry.isIntersecting && links.has(entry.target.id)) {
        links.forEach(a => a.classList.remove('is-current')); links.get(entry.target.id).classList.add('is-current');
      }
    }, {rootMargin: '-40% 0px -55% 0px'});
    sections.filter(s => links.has(s.id)).forEach(s => current.observe(s));
  }
})();
