'use strict';
// AERIS · Aprende: simulador de la escala oficial y recorrido paso a paso de días reales.
// Los límites son los de la Tabla 5 de la NOM-172-SEMARNAT-2023 (2026) y la guía OMS 2021 de 24 h.
(() => {
  const $ = id => document.getElementById(id);
  const BANDAS = [
    {nombre: 'Buena', riesgo: 'Bajo', tope: 15, clase: 'b-buena'},
    {nombre: 'Aceptable', riesgo: 'Moderado', tope: 25, clase: 'b-aceptable'},
    {nombre: 'Mala', riesgo: 'Alto', tope: 79, clase: 'b-mala'},
    {nombre: 'Muy mala', riesgo: 'Muy alto', tope: 130, clase: 'b-muymala'},
    {nombre: 'Extremadamente mala', riesgo: 'Extremadamente alto', tope: Infinity, clase: 'b-extrema'},
  ];
  const NORMA = 25, OMS = 15, MAXIMO = 150, MINIMAS = 18;
  const banda = v => BANDAS.find(b => v <= b.tope);
  const fmt = (v, d = 1) => v.toLocaleString('es-MX', {minimumFractionDigits: d, maximumFractionDigits: d});

  // 1) Simulador.
  const control = $('apValor');
  if (control) {
    const actualizar = () => {
      const v = Number(control.value), b = banda(v);
      $('apNumero').textContent = fmt(v);
      const cat = $('apCategoria');
      cat.textContent = b.nombre; cat.className = b.clase;
      $('apRiesgo').textContent = 'Riesgo para la salud: ' + b.riesgo.toLowerCase();
      $('apNorma').textContent = v <= NORMA
        ? `Cumple el límite de 24 h de la norma mexicana (${NORMA} µg/m³).`
        : `Supera en ${fmt(v - NORMA)} µg/m³ el límite de 24 h de la norma mexicana (${NORMA}).`;
      $('apOms').textContent = v <= OMS
        ? `Está dentro de la guía de la OMS (${OMS} µg/m³).`
        : `Es ${fmt(v / OMS)} veces la guía de la OMS (${OMS} µg/m³).`;
      $('apMarca').style.left = (Math.min(v, MAXIMO) / MAXIMO * 100) + '%';
      control.setAttribute('aria-valuetext', `${fmt(v)} microgramos por metro cúbico: ${b.nombre}`);
    };
    control.addEventListener('input', actualizar);
    actualizar();
  }

  // 2) Recorrido de un día real.
  const datos = $('apEjemplos');
  if (!datos) return;
  const ejemplos = JSON.parse(datos.textContent);
  let actual = 0, paso = 0;
  const pasos = [...document.querySelectorAll('#apPasos li')];

  function dibujar() {
    const e = ejemplos[actual];
    const tope = Math.max(30, ...e.horas.filter(h => h.valor !== null && !h.revision).map(h => h.valor), e.media || 0);
    const cont = $('apHoras');
    cont.replaceChildren(...e.horas.map(h => {
      const barra = document.createElement('span');
      barra.className = 'ap-hora' + (h.valor === null ? ' sin-dato' : '') + (h.revision ? ' marcada' : '');
      const alto = h.valor === null ? 100 : Math.min(100, h.valor / tope * 100);
      barra.style.setProperty('--alto', alto + '%');
      if (h.revision && h.valor > tope) barra.dataset.recorte = fmt(h.valor, 0);
      barra.title = `${h.hora}:00 · ` + (h.valor === null ? 'sin medición' : `${fmt(h.valor)} µg/m³${h.revision ? ' · marcada' : ''}`);
      return barra;
    }));
    if (e.media !== null) {
      const linea = document.createElement('i');
      linea.className = 'ap-media'; linea.style.setProperty('--nivel', Math.min(100, e.media / tope * 100) + '%');
      linea.dataset.texto = `promedio ${fmt(e.media)}`;
      cont.append(linea);
    }
    const textos = {
      con_dato: `${e.con_dato} de 24 horas tienen medición.`,
      marcadas: e.marcadas ? `${e.marcadas} horas marcadas como sospechosas no se usan.` : 'Ninguna hora está marcada.',
      validas: e.validas >= MINIMAS ? `Sí: ${e.validas} horas válidas.` : `No: solo ${e.validas}. El día no se califica.`,
      media: e.media !== null ? `${fmt(e.media)} µg/m³.` : 'No se calcula: faltan horas válidas.',
      banda: e.banda ? `${e.banda}.` : `Sin categoría (${e.clasificacion}).`,
    };
    pasos.forEach(li => { li.querySelector('[data-dato]').textContent = textos[li.querySelector('[data-dato]').dataset.dato]; });
    $('apDiaTitulo').textContent = `${e.estacion} · ${e.dia} · ${e.fuente}`;
    $('apLeccion').textContent = e.leccion;
    mostrar();
  }

  function mostrar() {
    const panel = $('apDia');
    panel.dataset.paso = String(paso);
    pasos.forEach((li, i) => { li.classList.toggle('hecho', i < paso); li.classList.toggle('activo', i === paso - 1); });
    $('apAnterior').disabled = paso === 0;
    $('apSiguiente').disabled = paso >= pasos.length;
    $('apSiguiente').textContent = paso === 0 ? 'Empezar →' : paso >= pasos.length ? 'Listo' : 'Siguiente paso →';
  }

  document.querySelectorAll('[data-ejemplo]').forEach(boton => boton.addEventListener('click', () => {
    actual = Number(boton.dataset.ejemplo); paso = 0;
    document.querySelectorAll('[data-ejemplo]').forEach(b => b.setAttribute('aria-selected', String(b === boton)));
    $('apDia').setAttribute('aria-labelledby', boton.id);
    dibujar();
  }));
  $('apSiguiente').addEventListener('click', () => { paso = Math.min(pasos.length, paso + 1); mostrar(); });
  $('apAnterior').addEventListener('click', () => { paso = Math.max(0, paso - 1); mostrar(); });
  document.documentElement.classList.add('ap-interactivo');
  dibujar();
})();
