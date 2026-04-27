// INIT MAP
const map = L.map('map', {
  center: [22.9734, 78.6569],
  zoom: 5,
  minZoom: 2
});

// TILE
L.tileLayer(
  'https://tiles.stadiamaps.com/tiles/alidade_smooth_dark/{z}/{x}/{y}{r}.png?api_key=9c4f80bd-95f6-485e-9c8b-9f88d3c4586f',
  {
    maxZoom: 20,
    tileSize: 512,
    zoomOffset: -1
  }
).addTo(map);

// CLUSTER
const markers = L.markerClusterGroup();
map.addLayer(markers);

// HEATMAP LAYER
let heatLayer = null;

// FIX CLICK BLOCKING
setTimeout(() => {
  const panel = document.getElementById('map-panel');
  if (panel) {
    L.DomEvent.disableClickPropagation(panel);
    L.DomEvent.disableScrollPropagation(panel);
  }
}, 300);

// COLOR
function getColor(u) {
  return u === 'urgent' ? '#f44336'
       : u === 'med'    ? '#ffc107'
       : '#4caf50';
}

// STATE
let tasksVisible = true;
let heatmapVisible = false;
let refreshInterval = null;

// BUILD QUERY
function buildQuery() {
  const urgency = document.getElementById('filter-urgency')?.value || '';
  const type    = document.getElementById('filter-type')?.value || '';

  let qs = '';
  if (urgency) qs += `urgency=${urgency}&`;
  if (type)    qs += `task_type=${type}&`;

  return qs ? '?' + qs.slice(0, -1) : '';
}

// LOAD TASK MARKERS
async function loadTasks() {
  markers.clearLayers();

  try {
    const data = await api.json(`/map/geojson/tasks${buildQuery()}`);

    (data.features || []).forEach(f => {
      const [lng, lat] = f.geometry.coordinates;
      const p = f.properties;

      if (!lat || !lng) return;

      const marker = L.circleMarker([lat, lng], {
        radius: 8,
        color: getColor(p.urgency),
        fillColor: getColor(p.urgency),
        fillOpacity: 0.9
      });

      marker.bindPopup(`
  <div style="min-width:220px;font-family:Arial;">
    <div style="font-weight:700;font-size:14px;margin-bottom:6px;">
      ${p.title || "Task"}
    </div>

    <div style="font-size:12px;color:#555;margin-bottom:6px;">
      ${p.description || "No description available"}
    </div>

    <div style="font-size:12px;line-height:1.5;">
      <div><b>🏷 Type:</b> ${p.task_type || '—'}</div>
      <div><b>⚠ Urgency:</b> ${p.urgency || '—'}</div>
      <div><b>⏰ Deadline:</b> ${p.deadline || '—'}</div>
      <div><b>👥 Volunteers:</b> ${(p.assigned_volunteers?.length || 0)} / ${p.volunteers_needed || 1}</div>
    </div>
  </div>
`);
      markers.addLayer(marker);
    });

  } catch (e) {
    console.error("Task load error:", e);
  }
}

// LOAD HEATMAP
async function loadHeatmap() {
  try {
    const res = await api.get(`/map/heatmap/tasks${buildQuery()}`);
    const data = await res.json();

    const points = (data.points || []).map(p => [
      p.lat,
      p.lng,
      p.weight || 1
    ]);

    if (heatLayer) {
      map.removeLayer(heatLayer);
    }

    heatLayer = L.heatLayer(points, {
      radius: 25,
      blur: 20,
      maxZoom: 10
    });

    map.addLayer(heatLayer);

  } catch (e) {
    console.error("Heatmap error:", e);
  }
}

// AUTO REFRESH
function startAutoRefresh() {
  stopAutoRefresh();
  refreshInterval = setInterval(() => {
    if (tasksVisible) loadTasks();
    if (heatmapVisible) loadHeatmap();
  }, 15000);
}

function stopAutoRefresh() {
  if (refreshInterval) {
    clearInterval(refreshInterval);
    refreshInterval = null;
  }
}

// TOGGLE TASKS
window.toggleTasks = function () {
  const btn = document.getElementById("taskBtn");

  if (tasksVisible) {
    markers.clearLayers();
    if (btn) btn.classList.remove("active");
  } else {
    loadTasks();
    if (btn) btn.classList.add("active");
  }

  tasksVisible = !tasksVisible;
};

// TOGGLE HEATMAP
window.toggleHeatmap = function () {
  const btn = document.getElementById("heatBtn");

  if (heatmapVisible) {
    if (heatLayer) map.removeLayer(heatLayer);
    if (btn) btn.classList.remove("active");
  } else {
    loadHeatmap();
    if (btn) btn.classList.add("active");
  }

  heatmapVisible = !heatmapVisible;
};

// FILTER CHANGE
document.addEventListener('change', (e) => {
  if (e.target.id === 'filter-urgency' || e.target.id === 'filter-type') {
    if (tasksVisible) loadTasks();
    if (heatmapVisible) loadHeatmap();
  }
});

// INIT
loadTasks();
startAutoRefresh();