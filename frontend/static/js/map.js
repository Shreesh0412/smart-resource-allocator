// static/js/map.js

let map;
let markerCluster;
let heatLayer = null;
let currentMarkers = [];
let infoWindow;
let tasksVisible = true;
let heatmapVisible = false;
let refreshInterval = null;

// 🌙 Custom Dark Theme to match the SAARTHI UI perfectly
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

// INIT MAP (This is automatically called by the Google script tag 'callback=initMap')
window.initMap = function() {
  map = new google.maps.Map(document.getElementById('map'), {
    center: { lat: 20.5937, lng: 78.9629 }, // Center of India
    zoom: 5,
    minZoom: 3,
    styles: darkMapStyle,
    disableDefaultUI: true, // Hides default Google Maps UI clutter
    zoomControl: true,
    mapTypeControl: false,
    streetViewControl: false
  });

  infoWindow = new google.maps.InfoWindow();
  
  // Initialize Google's official MarkerClusterer
  markerCluster = new markerClusterer.MarkerClusterer({ map, markers: [] });

  loadTasks();
  startAutoRefresh();
};

// PIN COLORS
function getIconColor(urgency) {
  return urgency === 'urgent' ? '#f44336'
       : urgency === 'med'    ? '#ffc107'
       : '#4caf50';
}

function buildQuery() {
  const urgency = document.getElementById('filter-urgency')?.value || '';
  const type    = document.getElementById('filter-type')?.value || '';
  let qs = '';
  if (urgency) qs += `urgency=${urgency}&`;
  if (type)    qs += `task_type=${type}&`;
  return qs ? '?' + qs.slice(0, -1) : '';
}

// LOAD TASKS
async function loadTasks() {
  try {
    const data = await api.json(`/map/geojson/tasks${buildQuery()}`);
    let count = 0;

    // Clear existing markers from map and cluster
    markerCluster.clearMarkers();
    currentMarkers.forEach(m => m.setMap(null));
    currentMarkers = [];

    (data.features || []).forEach(f => {
      const [lng, lat] = f.geometry.coordinates;
      const p = f.properties;
      if (!lat || !lng) return;

      // Create Crisp Vector Circles as Pins
      const marker = new google.maps.Marker({
        position: { lat, lng },
        icon: {
          path: google.maps.SymbolPath.CIRCLE,
          fillColor: getIconColor(p.urgency),
          fillOpacity: 1,
          strokeColor: 'white',
          strokeWeight: 2,
          scale: 8 // size of the dot
        }
      });

      // Bind the popup card (Inline styled for readability on Google's white popup)
      marker.addListener('click', () => {
        infoWindow.setContent(`
          <div style="min-width:220px;font-family:Arial;color:#111;">
            <div style="font-weight:700;font-size:15px;margin-bottom:6px;border-bottom:1px solid #eee;padding-bottom:6px;">
              ${p.title || "Task"}
            </div>
            <div style="font-size:13px;color:#444;margin-bottom:10px;">
              ${p.description || "No description available"}
            </div>
            <div style="font-size:12px;line-height:1.6;">
              <div><b>🏷 Type:</b> ${p.task_type || '—'}</div>
              <div><b>⚠ Urgency:</b> ${p.urgency || '—'}</div>
              <div><b>⏰ Deadline:</b> ${p.deadline || '—'}</div>
              <div><b>👥 Volunteers:</b> ${(p.assigned_volunteers?.length || 0)} / ${p.volunteers_needed || 1}</div>
            </div>
          </div>
        `);
        infoWindow.open(map, marker);
      });

      currentMarkers.push(marker);
      count++;
    });

    // Add all new markers to the clusterer
    markerCluster.addMarkers(currentMarkers);

    // Update frontend count
    const countEl = document.getElementById('count');
    if(countEl) countEl.innerText = count;

  } catch (e) {
    console.error("Task load error:", e);
  }
}

// LOAD HEATMAP
async function loadHeatmap() {
  try {
    // 1. Fetch via the auth-aware api helper (same as loadTasks)
    const data = await api.json(`/map/geojson/tasks${buildQuery()}`);

    // 2. Parse the GeoJSON features into Google Maps LatLng points
    const points = (data.features || []).map(f => {
      // GeoJSON stores coordinates as [longitude, latitude]
      const [lng, lat] = f.geometry.coordinates;
      const urgency = f.properties.urgency;
      
      // Assign weight based on urgency (Urgent tasks glow hotter)
      let pointWeight = 1;
      if (urgency === 'urgent') pointWeight = 3;
      if (urgency === 'med') pointWeight = 2;

      return {
        location: new google.maps.LatLng(lat, lng),
        weight: pointWeight
      };
    }).filter(p => !isNaN(p.location.lat()) && !isNaN(p.location.lng()));

    if (heatLayer) {
      heatLayer.setMap(null); // Remove old layer
    }

    // 3. Generate new heatmap layer
    heatLayer = new google.maps.visualization.HeatmapLayer({
      data: points,
      radius: 35, // Adjust this if the glow is too big or small
      opacity: 0.8,
      gradient: [
        'rgba(0, 255, 255, 0)',
        'rgba(0, 255, 255, 1)',
        'rgba(0, 191, 255, 1)',
        'rgba(0, 127, 255, 1)',
        'rgba(0, 63, 255, 1)',
        'rgba(0, 0, 255, 1)',
        'rgba(0, 0, 223, 1)',
        'rgba(0, 0, 191, 1)',
        'rgba(0, 0, 159, 1)',
        'rgba(0, 0, 127, 1)',
        'rgba(63, 0, 91, 1)',
        'rgba(127, 0, 63, 1)',
        'rgba(191, 0, 31, 1)',
        'rgba(255, 0, 0, 1)'
      ]
    });

    heatLayer.setMap(map);

  } catch (e) {
    console.error("Heatmap error:", e);
  }
}

// FIX CONTROL PANEL CLICK PROPAGATION
setTimeout(() => {
  const panel = document.getElementById('map-panel');
  if (panel) {
    // Stops the map from panning/zooming when clicking inside the panel
    panel.addEventListener('mousedown', (e) => e.stopPropagation());
    panel.addEventListener('touchstart', (e) => e.stopPropagation());
    panel.addEventListener('dblclick', (e) => e.stopPropagation());
    panel.addEventListener('wheel', (e) => e.stopPropagation());
  }
}, 500);

// TOGGLE TASKS BUTTON
window.toggleTasks = function () {
  const btn = document.getElementById("taskBtn");
  if (tasksVisible) {
    markerCluster.clearMarkers();
    currentMarkers.forEach(m => m.setMap(null));
    if (btn) btn.classList.remove("active");
  } else {
    loadTasks();
    if (btn) btn.classList.add("active");
  }
  tasksVisible = !tasksVisible;
};

// TOGGLE HEATMAP BUTTON
window.toggleHeatmap = function () {
  const btn = document.getElementById("heatBtn");
  if (heatmapVisible) {
    if (heatLayer) heatLayer.setMap(null);
    if (btn) btn.classList.remove("active");
  } else {
    loadHeatmap();
    if (btn) btn.classList.add("active");
  }
  heatmapVisible = !heatmapVisible;
};

// AUTO-RELOAD ON FILTER CHANGE
document.addEventListener('change', (e) => {
  if (e.target.id === 'filter-urgency' || e.target.id === 'filter-type') {
    if (tasksVisible) loadTasks();
    if (heatmapVisible) loadHeatmap();
  }
});

// AUTO REFRESH LOOP
function startAutoRefresh() {
  if (refreshInterval) clearInterval(refreshInterval);
  refreshInterval = setInterval(() => {
    if (tasksVisible) loadTasks();
    if (heatmapVisible) loadHeatmap();
  }, 15000);
}