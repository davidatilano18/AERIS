export async function fetchObservations(url, filters, signal) {
  const response = await fetch(`${url}?${new URLSearchParams(filters)}`, {signal, cache: 'no-store', headers: {'Accept': 'application/json'}});
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || 'No se pudo consultar la base local.');
  return data;
}
