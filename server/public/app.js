/*
 * The dashboard stand-in.
 *
 * The cards ask their host for five things: the entity states, a service
 * call, a REST call, a signed URL for an image, and an auth token for the
 * upload. All five are answered from this server, so the cards themselves
 * are the same files the integration ships — no fork, no edits.
 */
const api = async (path, opts) => {
  const res = await fetch(path, opts);
  const text = await res.text();
  let body;
  try { body = text ? JSON.parse(text) : null; } catch (e) { body = text; }
  if (!res.ok) {
    const message = (body && (body.message || body.error)) || `HTTP ${res.status}`;
    throw new Error(message);
  }
  return body;
};

let states = {};
let config = { title: 'Park Visits', people: [] };
let cards = [];
let refreshing = false;

function hass() {
  return {
    states,
    language: navigator.language || 'en',
    themes: { darkMode: matchMedia('(prefers-color-scheme: dark)').matches },
    // Signed paths are a Home Assistant idea (a token on an <img> URL). Here
    // the server needs no token, so the path is already usable as-is.
    async callWS(msg) {
      if (msg && msg.type === 'auth/sign_path') return { path: msg.path };
      throw new Error(`unsupported websocket call ${msg && msg.type}`);
    },
    async callService(domain, service, data) {
      const body = await api(`/api/services/${domain}/${service}`, {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify(data || {}),
      });
      // Services change parks, so take the fresh states with the response
      // rather than waiting for the next poll.
      if (body && body.states) apply(body.states);
      return body;
    },
    async callApi(method, path, data) {
      return api(`/api/${path}`, data === undefined ? { method } : {
        method,
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify(data),
      });
    },
    // The upload posts with this token; the server doesn't check it.
    auth: { data: { access_token: 'standalone' }, accessToken: 'standalone' },
  };
}

function apply(list) {
  const next = {};
  for (const state of list) next[state.entity_id] = state;
  states = next;
  const h = hass();
  for (const card of cards) card.hass = h;
  const parks = list.filter((s) => s.attributes && s.attributes.source === 'park_visits');
  const counter = document.getElementById('count');
  if (counter) counter.textContent = `${parks.length} park${parks.length === 1 ? '' : 's'}`;
}

function status(text, kind = 'info') {
  const el = document.getElementById('status');
  if (!el) return;
  el.textContent = text || '';
  el.className = kind;
  el.style.display = text ? 'block' : 'none';
}

async function poll() {
  for (;;) {
    try {
      apply(await api('/api/states'));
      status('');
    } catch (err) {
      status(`Lost contact with the server — retrying. (${err.message})`, 'warn');
    }
    // Parks only change when somebody records a visit, so a slow poll is
    // plenty to keep a second phone or a wall tablet in step.
    await new Promise((r) => setTimeout(r, 5000));
  }
}

async function refresh() {
  if (refreshing) return;
  refreshing = true;
  const button = document.getElementById('refresh');
  if (button) { button.disabled = true; button.textContent = 'Fetching…'; }
  status('Fetching parks from Google — this uses your API quota.', 'info');
  try {
    const out = await api('/api/refresh', { method: 'POST' });
    apply(await api('/api/states'));
    status(`Updated — ${out.parks} parks.`, 'ok');
    setTimeout(() => status(''), 4000);
  } catch (err) {
    status(`Refresh failed: ${err.message}`, 'warn');
  } finally {
    refreshing = false;
    if (button) { button.disabled = false; button.textContent = 'Refresh from Google'; }
  }
}

async function main() {
  config = await api('/api/config');
  document.title = config.title;
  document.getElementById('title').textContent = config.title;
  document.getElementById('where').textContent = config.location
    ? `${config.location} · ${config.radius_km} km` : '';

  const tab = new URLSearchParams(location.search).get('view') || 'parks';
  const wrap = document.getElementById('cards');

  const table = document.createElement('park-visits-table-card');
  table.setConfig({
    type: 'custom:park-visits-table-card',
    source: 'park_visits',
    title: '',
    show_filter: true,
    show_status_strip: true,
    show_progress: true,
    show_add_park: true,
    show_upload: true,
    hide_visited: tab === 'todo',
    only_visited: tab === 'visited',
  });

  const gallery = document.createElement('park-visits-gallery-card');
  gallery.setConfig({ type: 'custom:park-visits-gallery-card', title: '', show_filter: true });

  cards = [table, gallery];
  wrap.append(tab === 'gallery' ? gallery : table);
  apply(await api('/api/states'));
  poll();

  for (const link of document.querySelectorAll('[data-view]')) {
    link.classList.toggle('on', link.dataset.view === tab);
  }
  document.getElementById('refresh').onclick = refresh;
}

main().catch((err) => {
  status(`Failed to start: ${err.message}`, 'warn');
  console.error(err);
});
