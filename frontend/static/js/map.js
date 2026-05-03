// static/js/map.js
// FIX B2: loadHeatmap() now calls /map/heatmap/tasks (the dedicated weighted
//         heatmap endpoint) instead of /map/geojson/tasks.

let map;
let markerCluster;
let heatLayer = null;
let currentMarkers = []; 
let infoWindow;
let refreshInterval = null;

let layers = {
  tasks: true,
  heatmap: false,
  vols: false,
  routes: false,
  ngos: false,
  reports: false
};

let mapObjects = {
  vols: [],
  routes: [],
  ngos: [],
  reports: []
};

// 🌙 Custom Dark Theme
const darkMapStyle = [
  { elementType: "geometry", stylers: [{ color: "#242f3e" }] },
  { elementType: "labels.text.stroke", stylers: [{ color: "#242f3e" }] },
  { elementType: "labels.text.fill", stylers: [{ color: "#746855" }] },
  { featureType: "administrative.locality", elementType: "labels.text.fill", stylers: [{ color: "#d59563" }] },
  { featureType: "road", elementType: "geometry", stylers: [{ color: "#38414e" }] },
  { featureType: "road", elementType: "geometry.stroke", stylers: [{ color: "#212a37" }] },
  { featureType: "road", elementType: "labels.text.fill", stylers: [{ color: "#9ca5b3" }] },
  { featureType: "road.highway", elementType: "geometry", stylers: [{ color: "#746855" }] },
  { featureType: "road.highway", elementType: "geometry.stroke", stylers: [{ color: "#1f2835" }] },
  { featureType: "water", elementType: "geometry", stylers: [{ color: "#17263c" }] },
  { featureType: "water", elementType: "labels.text.fill", stylers: [{ color: "#515c6d" }] },
  { featureType: "water", elementType: "labels.text.stroke", stylers: [{ color: "#17263c" }] }
];

window.initMap = function() {
  if (typeof google === 'undefined') {
    console.error("Google Maps API not loaded.");
    return;
  }

  map = new google.maps.Map(document.getElementById('map'), {
    center: { lat: 20.5937, lng: 78.9629 }, 
    zoom: 5,
    minZoom: 3,
    styles: darkMapStyle,
    disableDefaultUI: true,
    zoomControl: true,
    mapTypeControl: false,
    streetViewControl: false
  });

  infoWindow = new google.maps.InfoWindow();
  markerCluster = new markerClusterer.MarkerClusterer({ map, markers: [] });

  if (layers.tasks) loadTasks();
  startAutoRefresh();
};

function buildQuery() {
  const urgency = document.getElementById('filter-urgency')?.value || '';
  const type    = document.getElementById('filter-type')?.value || '';
  let qs = '';
  if (urgency) qs += `urgency=${urgency}&`;
  if (type)    qs += `task_type=${type}&`;
  return qs ? '?' + qs.slice(0, -1) : '';
}

// ── LAYER DATA FETCHERS ──

async function loadTasks() {
  try {
    const data = await api.json(`/map/geojson/tasks${buildQuery()}`);
    let count = 0;

    markerCluster.clearMarkers();
    currentMarkers.forEach(m => m.setMap(null));
    currentMarkers = [];

    (data.features || []).forEach(f => {
      const [lng, lat] = f.geometry.coordinates;
      const p = f.properties;
      if (!lat || !lng) return;

      const marker = new google.maps.Marker({
        position: { lat, lng },
        icon: {
          path: google.maps.SymbolPath.CIRCLE,
          fillColor: p.urgency === 'urgent' ? '#f44336' : p.urgency === 'med' ? '#ffc107' : '#4caf50',
          fillOpacity: 1, strokeColor: 'white', strokeWeight: 2, scale: 8
        }
      });

      marker.addListener('click', () => {
        infoWindow.setContent(`
          <div style="min-width:200px;color:#111;">
            <div style="font-weight:700;font-size:15px;margin-bottom:6px;border-bottom:1px solid #eee;padding-bottom:6px;">${p.title || "Task"}</div>
            <div style="font-size:12px;line-height:1.6;">
              <div><b>🏷 Type:</b> ${p.task_type || '—'}</div>
              <div><b>⚠ Urgency:</b> ${p.urgency || '—'}</div>
              <div><b>👥 Volunteers:</b> ${p.assigned_count || 0} / ${p.volunteers_needed || 1}</div>
            </div>
          </div>
        `);
        infoWindow.open(map, marker);
      });

      currentMarkers.push(marker);
      count++;
    });

    markerCluster.addMarkers(currentMarkers);
    if(document.getElementById('count')) document.getElementById('count').innerText = count;
  } catch (e) { console.error("Task load error:", e); }
}

// FIX B2: Use /map/heatmap/tasks which returns {points: [{lat, lng, weight}]}
// instead of the GeoJSON tasks endpoint which doesn't provide proper weights.
async function loadHeatmap() {
  try {
    if (!google.maps.visualization) {
      console.error("Heatmap library not loaded.");
      return;
    }

    const data = await api.json(`/map/heatmap/tasks${buildQuery()}`);
    const points = (data.points || []).map(p => ({
      location: new google.maps.LatLng(p.lat, p.lng),
      weight: p.weight || 1,
    })).filter(p => !isNaN(p.location.lat()));

    if (heatLayer) heatLayer.setMap(null);

    heatLayer = new google.maps.visualization.HeatmapLayer({
      data: points, radius: 35, opacity: 0.8,
      gradient: [ 'rgba(0,255,255,0)', 'rgba(0,255,255,1)', 'rgba(0,191,255,1)', 'rgba(0,127,255,1)', 'rgba(0,0,255,1)', 'rgba(127,0,63,1)', 'rgba(255,0,0,1)' ]
    });
    heatLayer.setMap(map);
  } catch (e) { console.error("Heatmap error:", e); }
}

async function loadVolunteers() {
  try {
    const data = await api.json(`/map/volunteers/positions`);
    clearObjects('vols');
    
    (data.features || []).forEach(f => {
      const [lng, lat] = f.geometry.coordinates;
      const marker = new google.maps.Marker({
        position: { lat, lng }, map: map,
        icon: { path: google.maps.SymbolPath.CIRCLE, fillColor: '#2196f3', fillOpacity: 1, strokeColor: 'white', strokeWeight: 2, scale: 6 } 
      });
      marker.addListener('click', () => {
        infoWindow.setContent(`<div style="color:#111;padding:5px;"><b>🏃 Volunteer:</b> ${f.properties.name}<br><b>Trust Score:</b> ${f.properties.trust_score}</div>`);
        infoWindow.open(map, marker);
      });
      mapObjects.vols.push(marker);
    });
  } catch(e) { console.error(e); }
}

async function loadRoutes() {
  try {
    const data = await api.json(`/map/lines/volunteer-to-task`);
    clearObjects('routes');

    (data.features || []).forEach(f => {
      const path = f.geometry.coordinates.map(c => ({ lat: c[1], lng: c[0] }));
      const polyline = new google.maps.Polyline({
        path: path, geodesic: true, strokeColor: '#00bcd4', strokeOpacity: 0.8, strokeWeight: 3, map: map 
      });
      polyline.addListener('click', (e) => {
        infoWindow.setContent(`<div style="color:#111;padding:5px;"><b>🔗 Active Route</b><br>${f.properties.volunteer_name} → ${f.properties.task_title}</div>`);
        infoWindow.setPosition(e.latLng);
        infoWindow.open(map);
      });
      mapObjects.routes.push(polyline);
    });
  } catch(e) { console.error(e); }
}

async function loadNGOs() {
  try {
    const data = await api.json(`/map/ngos`);
    clearObjects('ngos');

    (data.features || []).forEach(f => {
      const [lng, lat] = f.geometry.coordinates;
      const marker = new google.maps.Marker({
        position: { lat, lng }, map: map,
        icon: { path: google.maps.SymbolPath.CIRCLE, fillColor: '#9c27b0', fillOpacity: 1, strokeColor: 'white', strokeWeight: 2, scale: 8 } 
      });
      marker.addListener('click', () => {
        infoWindow.setContent(`<div style="color:#111;padding:5px;"><b>🏢 NGO:</b> ${f.properties.name}<br><b>Focus:</b> ${(f.properties.focus_areas||[]).join(', ')}</div>`);
        infoWindow.open(map, marker);
      });
      mapObjects.ngos.push(marker);
    });
  } catch(e) { console.error(e); }
}

async function loadReports() {
  try {
    const data = await api.json(`/map/heatmap/problems`);
    clearObjects('reports');

    const reportPoints = data.points || (data.features ? data.features.map(f => ({
        lat: f.geometry.coordinates[1],
        lng: f.geometry.coordinates[0],
        label: f.properties.problem_type
    })) : []);

    reportPoints.forEach(p => {
      const marker = new google.maps.Marker({
        position: { lat: p.lat, lng: p.lng }, map: map,
        icon: { path: google.maps.SymbolPath.CIRCLE, fillColor: '#ff9800', fillOpacity: 1, strokeColor: 'white', strokeWeight: 2, scale: 7 } 
      });
      marker.addListener('click', () => {
        infoWindow.setContent(`<div style="color:#111;padding:5px;"><b>⚠️ Unverified Report</b><br>${p.label || 'Community Issue'}</div>`);
        infoWindow.open(map, marker);
      });
      mapObjects.reports.push(marker);
    });
  } catch(e) { console.error(e); }
}

// ── LAYER MANAGEMENT ENGINE ──

function clearObjects(layerName) {
  if (mapObjects[layerName]) {
    mapObjects[layerName].forEach(obj => obj.setMap(null));
    mapObjects[layerName] = [];
  }
}

window.toggleLayer = function(layerName) {
  layers[layerName] = !layers[layerName];
  const btn = document.getElementById(`btn-${layerName}`);
  
  if (layers[layerName]) {
    btn.classList.add('active');
    if (layerName === 'tasks') loadTasks();
    if (layerName === 'heatmap') loadHeatmap();
    if (layerName === 'vols') loadVolunteers();
    if (layerName === 'routes') loadRoutes();
    if (layerName === 'ngos') loadNGOs();
    if (layerName === 'reports') loadReports();
  } else {
    btn.classList.remove('active');
    if (layerName === 'tasks') {
      if(markerCluster) markerCluster.clearMarkers();
      currentMarkers.forEach(m => m.setMap(null));
      currentMarkers = [];
    } else if (layerName === 'heatmap') {
      if(heatLayer) heatLayer.setMap(null);
    } else {
      clearObjects(layerName);
    }
  }
};

setTimeout(() => {
  const panel = document.getElementById('map-panel');
  if (panel) {
    ['mousedown', 'touchstart', 'dblclick', 'wheel'].forEach(evt => {
      panel.addEventListener(evt, e => e.stopPropagation());
    });
  }
}, 500);

document.addEventListener('change', (e) => {
  if (e.target.id === 'filter-urgency' || e.target.id === 'filter-type') {
    if (layers.tasks) loadTasks();
    if (layers.heatmap) loadHeatmap();
  }
});

function startAutoRefresh() {
  if (refreshInterval) clearInterval(refreshInterval);
  refreshInterval = setInterval(() => {
    if (layers.tasks) loadTasks();
    if (layers.heatmap) loadHeatmap();
    if (layers.vols) loadVolunteers();
    if (layers.routes) loadRoutes();
    if (layers.ngos) loadNGOs();
    if (layers.reports) loadReports();
  }, 15000);
}