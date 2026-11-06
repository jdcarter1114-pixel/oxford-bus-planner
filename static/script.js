/* Oxford Move — browser interface, geolocation, route rendering, map markers. */
const el = id => document.getElementById(id);
const input = { start: el('start'), end: el('end') };
const selected = {start: null, end: null};
let pickMode = null;
let routeOptions = [];
let routeLineGroup, endpointGroup, stopGroup, map;

const escapeHTML = (value) => String(value ?? '').replace(/[&<>"']/g, ch =>
  ({'&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;'}[ch]));

const localDateTime = () => {
  const parts = new Intl.DateTimeFormat('en-GB', {
    timeZone: 'Europe/London', year:'numeric', month:'2-digit', day:'2-digit',
    hour:'2-digit', minute:'2-digit', hourCycle:'h23'
  }).formatToParts(new Date());
  const v = Object.fromEntries(parts.filter(p => p.type !== 'literal').map(p => [p.type, p.value]));
  return `${v.year}-${v.month}-${v.day}T${v.hour}:${v.minute}`;
};

function setStatus(message, kind = '') {
  el('status').className = `status ${kind}`;
  el('status').textContent = message;
}

function markerIcon(finish=false) {
  return L.divIcon({className:'', html:`<div class="custom-marker ${finish?'finish':''}"></div>`, iconSize:[20,20], iconAnchor:[10,10]});
}

function setPoint(which, lat, lon, name) {
  if (!Number.isFinite(lat) || !Number.isFinite(lon)) return;
  selected[which] = {lat, lon, label:name};
  input[which].value = name;
  input[which].dataset.resolved = name;
  drawEndpoints();
  setStatus(`${which === 'start' ? 'Starting point' : 'Destination'} selected.`, 'ok');
}

function drawEndpoints() {
  if (!endpointGroup) return;
  endpointGroup.clearLayers();
  for (const which of ['start', 'end']) {
    const p = selected[which];
    if (p) L.marker([p.lat,p.lon],{icon:markerIcon(which==='end')})
       .bindPopup(escapeHTML(p.label)).addTo(endpointGroup);
  }
}

function pick(which) {
  pickMode = pickMode === which ? null : which;
  el('choose-start').classList.toggle('active', pickMode === 'start');
  el('choose-end').classList.toggle('active', pickMode === 'end');
  map.getContainer().style.cursor = pickMode ? 'crosshair' : '';
  if(pickMode) setStatus(`Click anywhere in Oxford to select your ${pickMode === 'start' ? 'starting point' : 'destination'}.`);
}

async function getJSON(path) {
  const res = await fetch(path);
  const payload = await res.json();
  if (!res.ok) throw new Error(payload.error || payload.message || `HTTP ${res.status}`);
  return payload;
}

async function lookup(which) {
  const typed = input[which].value.trim();
  if (selected[which] && input[which].dataset.resolved === typed) return selected[which];
  setStatus(`Finding ${which === 'start' ? 'starting address' : 'destination'}…`);
  const found = await getJSON(`/api/geocode?q=${encodeURIComponent(typed)}`);
  setPoint(which, found.lat, found.lon, found.label);
  return selected[which];
}

function routeTags(route) {
  const labels = route.steps.filter(s=>s.mode==='bus').map(s=>s.route);
  return [...new Set(labels)].map(text=>`<span class="route-pill">${escapeHTML(text)}</span>`).join('');
}

function renderOptions() {
  el('results').hidden = false;
  el('results-count').textContent = `${routeOptions.length} result${routeOptions.length !== 1 ? 's':''}`;
  el('options').innerHTML = routeOptions.map((r,i) => `
    <button type="button" class="option ${i===0?'selected':''}" data-index="${i}">
      <div class="option-top"><span class="option-duration">${r.duration_minutes} min</span>
      <span class="option-label">${i === 0 ? 'QUICKEST' : 'ALTERNATIVE'}</span></div>
      <div class="option-description">${escapeHTML(r.departure)} – ${escapeHTML(r.arrival)} · ${r.buses} bus${r.buses!==1?'es':''} · ${r.walking_minutes} min walking · ${r.transfers} transfers</div>
      <div class="option-buses">${routeTags(r)}</div>
    </button>`).join('');
  el('options').querySelectorAll('.option').forEach(btn => btn.addEventListener('click', () => selectRoute(Number(btn.dataset.index))));
  selectRoute(0);
}

function selectRoute(index) {
  el('options').querySelectorAll('.option').forEach((btn,i) => btn.classList.toggle('selected', i===index));
  const route = routeOptions[index];
  el('instructions').innerHTML = `<h3>Step-by-step journey</h3>${route.steps.map(s => `
    <div class="step">
      <div class="step-symbol">${s.mode==='bus'?'▣':s.mode==='wait'?'◷':'↗'}</div>
      <div class="step-info"><div class="step-title">${s.mode==='bus' ? `Take bus ${escapeHTML(s.route)}${s.headsign ? ` towards ${escapeHTML(s.headsign)}`:''}` : s.mode==='wait' ? `Wait for your connection` : `Walk to ${escapeHTML(s.to)}`}</div>
      <div class="step-sub">${s.mode==='bus' ? `Board at ${escapeHTML(s.from)}<br>Get off at ${escapeHTML(s.to)}<br>` : s.mode==='wait' ? `At ${escapeHTML(s.from)}<br>` : `${escapeHTML(s.from)} → ${escapeHTML(s.to)}<br>`}
      <span class="step-time">${escapeHTML(s.departure)} – ${escapeHTML(s.arrival)}</span> · ${s.minutes} min</div></div>
    </div>`).join('')}`;

  routeLineGroup.clearLayers();
  stopGroup.clearLayers();
  const positions = [];
  for (const s of route.steps) {
    if(s.mode === 'wait') continue;
    const pts = s.geometry.map(p => [p.lat,p.lon]);
    pts.forEach(p => positions.push(p));
    L.polyline(pts, s.mode==='bus' ? {color:'#147c59',weight:6,opacity:.91}
                    : {color:'#e4aa47',weight:4,dashArray:'8 7',opacity:.9}).addTo(routeLineGroup);
    if(s.mode==='bus') {
      for (const p of [pts[0],pts[pts.length-1]]) {
        L.circleMarker(p,{radius:6,weight:3,color:'#147c59',fillColor:'#fff',fillOpacity:1}).addTo(stopGroup);
      }
    }
  }
  drawEndpoints();
  if (selected.start) positions.push([selected.start.lat, selected.start.lon]);
  if (selected.end) positions.push([selected.end.lat, selected.end.lon]);
  if(positions.length > 1) map.fitBounds(L.latLngBounds(positions).pad(.16), {maxZoom:15});
}

async function submitJourney(e) {
  e.preventDefault();
  const button = el('search-btn');
  button.disabled = true;
  try {
    const a = await lookup('start');
    const b = await lookup('end');
    const params = new URLSearchParams({start_lat:a.lat,start_lon:a.lon,end_lat:b.lat,end_lon:b.lon,depart:el('depart').value});
    setStatus('Calculating the earliest arrival from published bus timetables…');
    const result = await getJSON(`/api/routes?${params}`);
    routeOptions = result.routes;
    if (!routeOptions.length) {
      el('results').hidden = true;
      routeLineGroup.clearLayers();
      setStatus('No scheduled route was found within the next five hours. Try a different departure time or points closer to bus stops.', 'error');
      return;
    }
    renderOptions();
    setStatus(`Found ${routeOptions.length} journey option(s). Scheduled times only; walking distances are estimates.`, 'ok');
  } catch (error) {
    setStatus(error.message, 'error');
  } finally {
    button.disabled = false;
  }
}

function init() {
  if (typeof L === 'undefined') {setStatus('Map library could not be loaded. Check your internet connection.', 'error'); return;}
  map = L.map('map',{zoomControl:false}).setView([51.7520,-1.2577],13);
  L.control.zoom({position:'topright'}).addTo(map);
  L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom:19, attribution:'© OpenStreetMap contributors'
  }).addTo(map);
  endpointGroup = L.layerGroup().addTo(map);
  routeLineGroup = L.layerGroup().addTo(map);
  stopGroup = L.layerGroup().addTo(map);
  map.on('click', e => {
    if(!pickMode) return;
    const which = pickMode;
    setPoint(which, e.latlng.lat, e.latlng.lng, `${e.latlng.lat.toFixed(5)}, ${e.latlng.lng.toFixed(5)}`);
    pick(which);
  });
  input.start.addEventListener('input', () => {selected.start = null; input.start.dataset.resolved=''; drawEndpoints();});
  input.end.addEventListener('input', () => {selected.end = null; input.end.dataset.resolved=''; drawEndpoints();});
  el('choose-start').addEventListener('click', () => pick('start'));
  el('choose-end').addEventListener('click', () => pick('end'));
  el('depart').value = localDateTime();
  el('journey-form').addEventListener('submit', submitJourney);
  el('location-btn').addEventListener('click', () => {
    if(!navigator.geolocation) {setStatus('Your browser does not support geolocation.', 'error'); return;}
    setStatus('Requesting permission to access your location…');
    navigator.geolocation.getCurrentPosition(pos => {
      const {latitude,longitude} = pos.coords;
      setPoint('start',latitude,longitude,'My current location');
      map.setView([latitude,longitude],15);
    }, error => setStatus(`Could not retrieve location: ${error.message}. You can select a point on the map instead.`, 'error'),
    {enableHighAccuracy:true,timeout:12000,maximumAge:60000});
  });
  getJSON('/api/health').then(data => setStatus(`${data.stops.toLocaleString()} bus stops loaded. Ready to plan.`, 'ok'))
    .catch(e => setStatus(`${e.message} You can import the GTFS feed using the README instructions.`, 'error'));
}

document.addEventListener('DOMContentLoaded', init);
