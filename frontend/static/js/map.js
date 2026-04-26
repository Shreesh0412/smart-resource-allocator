/**
 * static/js/map.js
 * Live map controller — Leaflet + Heatmap + task/volunteer layers.
 * Works for both logged-in users (full data) and public view (task pins only).
 */

// ── Init Map ──────────────────────────────────────────────────
const map = L.map('map', {
  center: [28.9845, 77.7064], // Default: Meerut, UP — will be overridden by geolocation
  zoom:   13,
  zoomControl: true,
});

// Tile layer (dark-friendly OpenStreetMap)
L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
  attribution: '© OpenStreetMap contributors',
  maxZoom: 19,
}).addTo(map);

// ── Layer groups ──────────────────────────────────────────────
const layers = {
  tasks:      L.layerGroup().addTo(map),
  volunteers: L.layerGroup(),
  routes:     L.layerGroup(),
  problems:   L.layerGroup(),
  ngos:       L.layerGroup(),
  heatmap:    null,   // Leaflet.heat layer — managed separately
};

// Track which layers are currently visible
const layerState = {
  tasks:      true,
  heatmap:    true,
  volunteers: false,
  routes:     false,
  problems:   false,
  ngos:       false,
};

// ── Custom icons ──────────────────────────────────────────────
function makeIcon(color, emoji, size = 32) {
  return L.divIcon({
    className: '',
    html: `
      <div style="
        width:${size}px; height:${size}px;
        background:${color};
        border-radius:50% 50% 50% 0;
        transform:rotate(-45deg);
        border:2px solid rgba(0,0,0,0.4);
        display:flex; align-items:center; justify-content:center;
      ">
        <span style="transform:rotate(45deg); font-size:${size*0.45}px; line-height:1;">${emoji}</span>
      </div>`,
    iconSize:   [size, size],
    iconAnchor: [size/2, size],
    popupAnchor:[0, -size],
  });
}

const icons = {
  urgent:    makeIcon('#f44336', '🔥'),
  med:       makeIcon('#ffc107', '⚠️'),
  low:       makeIcon('#4caf50', '✅'),
  volunteer: makeIcon('#00bcd4', '🙋', 28),
  ngo:       makeIcon('#ff5722', '🏢', 28),
  problem:   makeIcon('#7c4dff', '📣', 28),
};

// ── Load Task Pins ────────────────────────────────────────────
async function loadTaskPins() {
  layers.tasks.clearLayers();
  const urgencyFilter = document.getElementById('urgency-filter')?.value || '';

  try {
    let qs = '?status=open';
    if (urgencyFilter) qs += `&urgency=${urgencyFilter}`;
    const data = await api.getTaskGeoJSON(qs);

    let openCount   = 0;
    let urgentCount = 0;

    (data.features || []).forEach(feature => {
      const [lng, lat] = feature.geometry.coordinates;
      const p = feature.properties;
      const urgency = p.urgency || 'low';
      openCount++;
      if (urgency === 'urgent') urgentCount++;

      const marker = L.marker([lat, lng], { icon: icons[urgency] || icons.low });

      const popupHTML = `
        <div style="font-family:system-ui;min-width:220px;">
          <div style="font-weight:700;font-size:0.95rem;margin-bottom:6px;">${p.title}</div>
          <div style="display:flex;gap:6px;flex-wrap:wrap;margin-bottom:8px;">
            <span style="padding:2px 8px;border-radius:100px;font-size:0.7rem;font-weight:700;background:${urgencyBg(urgency)};color:${urgencyFg(urgency)};">${urgency.toUpperCase()}</span>
            <span style="padding:2px 8px;border-radius:100px;font-size:0.7rem;background:#e3e3e3;">${p.task_type}</span>
          </div>
          <div style="font-size:0.8rem;color:#555;margin-bottom:4px;">📍 ${p.address || 'See coordinates'}</div>
          <div style="font-size:0.8rem;color:#555;margin-bottom:4px;">⏰ Deadline: ${p.deadline ? new Date(p.deadline).toLocaleDateString() : '—'}</div>
          <div style="font-size:0.8rem;color:#555;margin-bottom:10px;">👥 ${p.assigned_count}/${p.volunteers_needed} volunteers</div>
          <button onclick="openTaskSidebar('${p.id}')"
            style="background:#ff5722;color:#fff;border:none;border-radius:6px;padding:6px 14px;font-size:0.82rem;font-weight:600;cursor:pointer;width:100%;">
            View Details →
          </button>
        </div>
      `;
      marker.bindPopup(popupHTML, { maxWidth: 260 });
      layers.tasks.addLayer(marker);
    });

    document.getElementById('stat-open').textContent   = openCount;
    document.getElementById('stat-urgent').textContent = urgentCount;
  } catch(e) {
    showToast('Could not load task pins: ' + e.message, 'error');
  }
}

function urgencyBg(u) { return u==='urgent'?'#ffebee':u==='med'?'#fff8e1':'#e8f5e9'; }
function urgencyFg(u) { return u==='urgent'?'#c62828':u==='med'?'#f57f17':'#2e7d32'; }

// ── Load Heatmap ──────────────────────────────────────────────
async function loadHeatmap() {
  if (layers.heatmap) { map.removeLayer(layers.heatmap); layers.heatmap = null; }
  if (!layerState.heatmap) return;

  try {
    const data = await api.getTaskHeatmap();
    const points = (data.points || []).map(p => [p.lat, p.lng, p.weight]);

    layers.heatmap = L.heatLayer(points, {
      radius:    25,
      blur:      15,
      maxZoom:   17,
      gradient: { 0.2:'#4caf50', 0.5:'#ffc107', 0.8:'#ff5722', 1.0:'#f44336' },
    }).addTo(map);
  } catch(e) {
    console.warn('Heatmap error:', e.message);
  }
}

// ── Load Volunteer Positions ──────────────────────────────────
async function loadVolunteerPositions() {
  layers.volunteers.clearLayers();
  if (!Auth.isLoggedIn()) return;

  try {
    const data = await api.getVolPositions();
    let volCount = 0;

    (data.features || []).forEach(f => {
      const [lng, lat] = f.geometry.coordinates;
      const p = f.properties;
      volCount++;

      const marker = L.marker([lat, lng], { icon: icons.volunteer });
      marker.bindPopup(`
        <div style="font-family:system-ui;min-width:180px;">
          <div style="font-weight:700;">${p.name}</div>
          <div style="font-size:0.8rem;color:#555;">Trust: ${p.trust_score}/100</div>
          <div style="font-size:0.8rem;color:#555;">Last seen: ${p.last_seen ? timeAgo(p.last_seen) : '—'}</div>
          ${p.active_task_id ? `<div style="font-size:0.78rem;color:#ff5722;margin-top:4px;">On task</div>` : '<div style="font-size:0.78rem;color:#4caf50;margin-top:4px;">Available</div>'}
        </div>
      `);
      layers.volunteers.addLayer(marker);
    });

    document.getElementById('stat-vols').textContent = volCount;
  } catch(e) {
    console.warn('Volunteer positions error:', e.message);
  }
}

// ── Load Routing Lines ────────────────────────────────────────
async function loadRoutes() {
  layers.routes.clearLayers();
  try {
    const data = await api.getRoutingLines();
    (data.features || []).forEach(f => {
      const coords = f.geometry.coordinates.map(([lng, lat]) => [lat, lng]);
      const line = L.polyline(coords, {
        color:     '#00bcd4',
        weight:    2,
        opacity:   0.7,
        dashArray: '6 4',
      });
      line.bindTooltip(`${f.properties.volunteer_name} → ${f.properties.task_title}`, { sticky: true });
      layers.routes.addLayer(line);
    });
  } catch(e) {
    console.warn('Routes error:', e.message);
  }
}

// ── Load Problem Reports ──────────────────────────────────────
async function loadProblemReports() {
  layers.problems.clearLayers();
  try {
    const data = await api.getProblemHeatmap();
    (data.points || []).forEach(p => {
      const marker = L.marker([p.lat, p.lng], { icon: icons.problem });
      marker.bindPopup(`
        <div style="font-family:system-ui;">
          <div style="font-weight:700;">Community Report</div>
          <div style="font-size:0.82rem;color:#555;">${p.label || 'Problem reported'}</div>
        </div>
      `);
      layers.problems.addLayer(marker);
    });
  } catch(e) {
    console.warn('Problem reports error:', e.message);
  }
}

// ── Load NGO Locations ────────────────────────────────────────
async function loadNGOs() {
  layers.ngos.clearLayers();
  try {
    const data = await api.json('/map/ngos');
    (data.features || []).forEach(f => {
      const [lng, lat] = f.geometry.coordinates;
      const p = f.properties;
      const marker = L.marker([lat, lng], { icon: icons.ngo });
      marker.bindPopup(`
        <div style="font-family:system-ui;min-width:180px;">
          <div style="font-weight:700;">${p.name}</div>
          <div style="font-size:0.8rem;color:#555;">${p.focus_areas?.join(', ') || '—'}</div>
        </div>
      `);
      layers.ngos.addLayer(marker);
    });
  } catch(e) {
    console.warn('NGOs error:', e.message);
  }
}

// ── Layer toggle ──────────────────────────────────────────────
function toggleLayer(name) {
  const btn = document.getElementById(`btn-${name}`);
  layerState[name] = !layerState[name];
  btn?.classList.toggle('active', layerState[name]);

  if (name === 'heatmap') {
    if (layerState.heatmap) loadHeatmap();
    else if (layers.heatmap) { map.removeLayer(layers.heatmap); layers.heatmap = null; }
    return;
  }

  if (layerState[name]) {
    map.addLayer(layers[name]);
    // Reload data when toggling on
    if (name === 'tasks')     loadTaskPins();
    if (name === 'volunteers')loadVolunteerPositions();
    if (name === 'routes')    loadRoutes();
    if (name === 'problems')  loadProblemReports();
    if (name === 'ngos')      loadNGOs();
  } else {
    map.removeLayer(layers[name]);
  }
}

// ── Filter ────────────────────────────────────────────────────
function applyFilters() {
  if (layerState.tasks)   loadTaskPins();
  if (layerState.heatmap) loadHeatmap();
}

// ── Refresh all active layers ─────────────────────────────────
async function refreshAll() {
  showToast('Refreshing map data…', 'info', 2000);
  const tasks = [];
  if (layerState.tasks)     tasks.push(loadTaskPins());
  if (layerState.heatmap)   tasks.push(loadHeatmap());
  if (layerState.volunteers)tasks.push(loadVolunteerPositions());
  if (layerState.routes)    tasks.push(loadRoutes());
  if (layerState.problems)  tasks.push(loadProblemReports());
  if (layerState.ngos)      tasks.push(loadNGOs());
  await Promise.allSettled(tasks);
  showToast('Map refreshed!', 'success', 1500);
}

// ── Task Sidebar ──────────────────────────────────────────────
async function openTaskSidebar(taskId) {
  const sidebar  = document.getElementById('task-sidebar');
  const content  = document.getElementById('sidebar-content');
  sidebar.classList.add('open');
  content.innerHTML = '<div class="loader"><div class="spinner"></div></div>';

  try {
    const data = await api.json(`/tasks/${taskId}`);
    const t    = data.task;
    const pred = t.prediction || {};

    content.innerHTML = `
      <div style="display:flex;flex-direction:column;gap:14px;">
        <div>
          <div style="display:flex;gap:6px;flex-wrap:wrap;margin-bottom:10px;">
            ${urgencyBadge(t.urgency)} ${statusBadge(t.status)}
          </div>
          <div style="font-size:1.1rem;font-weight:700;margin-bottom:6px;">${t.title}</div>
          <p style="font-size:0.85rem;color:var(--text-muted);line-height:1.6;">${t.description}</p>
        </div>

        <div style="display:flex;flex-direction:column;gap:8px;">
          <div class="score-bar"><div class="score-lbl">Type</div><div style="font-weight:600;">${t.task_type}</div></div>
          <div class="score-bar"><div class="score-lbl">Deadline</div><div style="font-weight:600;">${formatDate(t.deadline)}</div></div>
          <div class="score-bar"><div class="score-lbl">Volunteers</div><div style="font-weight:700;">${(t.assigned_volunteers?.length||0)} / ${t.volunteers_needed}</div></div>
          <div class="score-bar"><div class="score-lbl">Location</div><div style="font-size:0.85rem;">${t.address || `${t.lat?.toFixed(4)}, ${t.lng?.toFixed(4)}`}</div></div>
        </div>

        ${pred.risk_level ? `
          <div style="background:var(--surface);border-radius:var(--radius-sm);padding:10px 14px;font-size:0.82rem;">
            <strong class="risk-${pred.risk_level}">
              ${pred.risk_level==='on_track'?'✅':pred.risk_level==='at_risk'?'⚠️':'🚨'}
              ${pred.risk_level.replace('_',' ').toUpperCase()}
            </strong>
            <div style="color:var(--text-muted);margin-top:4px;">${pred.summary}</div>
          </div>
        ` : ''}

        ${Auth.isLoggedIn() && Auth.getUserType() === 'volunteer' ? `
          <button class="btn btn-primary btn-full" onclick="applyFromMap('${t._id}')">✋ Apply for this Task</button>
        ` : ''}
        ${!Auth.isLoggedIn() ? `
          <a href="/templates/login.html?type=volunteer" class="btn btn-primary btn-full">Login to Apply</a>
        ` : ''}

        <button class="btn btn-secondary btn-full" onclick="map.flyTo([${t.lat},${t.lng}],16)">🎯 Zoom to Task</button>
      </div>
    `;
  } catch(e) {
    content.innerHTML = `<p style="color:var(--red);">${e.message}</p>`;
  }
}

async function applyFromMap(taskId) {
  try {
    await api.applyForTask(taskId);
    showToast('Application submitted!', 'success');
    closeSidebar();
  } catch(e) {
    showToast(e.message, 'error');
  }
}

function closeSidebar() {
  document.getElementById('task-sidebar').classList.remove('open');
}

// ── URL params — jump to a specific task or location ──────────
function handleURLParams() {
  const params = new URLSearchParams(window.location.search);

  const taskId = params.get('task');
  if (taskId) {
    setTimeout(() => openTaskSidebar(taskId), 1000);
  }

  const lat = parseFloat(params.get('lat'));
  const lng = parseFloat(params.get('lng'));
  if (lat && lng) {
    map.flyTo([lat, lng], 16);
  }
}

// ── Geolocation — center map on user ─────────────────────────
async function centerOnUser() {
  try {
    const loc = await getUserLocation();
    map.flyTo([loc.lat, loc.lng], 14);

    // Blue "you are here" dot
    L.circleMarker([loc.lat, loc.lng], {
      radius:      10,
      color:       '#00bcd4',
      fillColor:   '#00bcd4',
      fillOpacity: 0.3,
      weight:      2,
    }).addTo(map).bindPopup('📍 You are here');
  } catch(e) {
    // Keep default center
  }
}

// ── Auto-refresh volunteers every 30 s ───────────────────────
setInterval(() => {
  if (layerState.volunteers) loadVolunteerPositions();
}, 30000);

// ── Init ──────────────────────────────────────────────────────
(async () => {
  await centerOnUser();
  await Promise.allSettled([
    loadTaskPins(),
    loadHeatmap(),
  ]);
  handleURLParams();
})();