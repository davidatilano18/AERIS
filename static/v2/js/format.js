const number = new Intl.NumberFormat('es-MX', {maximumFractionDigits: 2});
const localTime = new Intl.DateTimeFormat('es-MX', {timeZone: 'America/Mexico_City', year: 'numeric', month: 'short', day: '2-digit', hour: '2-digit', minute: '2-digit', hourCycle: 'h23'});
export const fmt = value => value === null || value === undefined ? '—' : number.format(value);
export const utc = value => value ? `${new Date(value).toISOString().slice(0, 16).replace('T', ' ')} UTC` : 'Sin observaciones';
export const local = value => value ? `${localTime.format(new Date(value))} · Querétaro` : '—';
export const age = value => value === null || value === undefined ? 'Sin datos' : value < 1 ? `${fmt(value * 60)} min` : `${fmt(value)} h`;
export function element(tag, text, className) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (className) node.className = className;
  return node;
}
