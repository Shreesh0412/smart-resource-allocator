const API_BASE = '/api';

// ── Auth ─────────────────────────────────────────
const Auth = {
  getToken()    { return localStorage.getItem('access_token'); },
  getRefresh()  { return localStorage.getItem('refresh_token'); },
  getUserType() { return localStorage.getItem('user_type'); },

  save({ access_token, refresh_token, id, type, name }) {
    if (access_token)  localStorage.setItem('access_token', access_token);
    if (refresh_token) localStorage.setItem('refresh_token', refresh_token);
    if (id)   localStorage.setItem('user_id', id);
    if (type) localStorage.setItem('user_type', type);
    if (name) localStorage.setItem('user_name', name);
  },

  clear() {
    ['access_token','refresh_token','user_id','user_type','user_name']
      .forEach(k => localStorage.removeItem(k));
  },

  isLoggedIn() { return !!this.getToken(); },

  redirect() {
    const type = this.getUserType();
    if (type === 'volunteer') window.location.href = '/volunteer-dashboard.html';
    else if (type === 'ngo')  window.location.href = '/ngo-dashboard.html';
    else window.location.href = '/login.html';
  },

  logout() {
    this.clear();
    window.location.href = '/login.html';
  }
};

window.Auth = Auth;

// ── Core Fetch ──────────────────────────────────
async function apiFetch(path, options = {}, retried = false) {
  const token = Auth.getToken();

  const headers = {
    'X-Requested-With': 'XMLHttpRequest',
    ...(token && { Authorization: `Bearer ${token}` }),
    ...(options.body && !(options.body instanceof FormData)
      ? { 'Content-Type': 'application/json' }
      : {}),
    ...(options.headers || {})
  };

  const res = await fetch(API_BASE + path, { ...options, headers });

  if ((res.status === 401 || res.status === 422) && !retried) {
    Auth.logout();
    return res;
  }

  return res;
}

// ── JSON helper ─────────────────────────────────
async function json(path, options = {}) {
  const res = await apiFetch(path, options);
  const data = await res.json().catch(() => ({}));

  if (!res.ok) {
    throw new Error(data.error || data.message || 'Request failed');
  }

  return data;
}

// ── API OBJECT ──────────────────────────────────
const api = {

  // AUTH
  volunteerLogin: (email, password) =>
    json('/auth/volunteer/login', {
      method: 'POST',
      body: JSON.stringify({ email, password })
    }),

  ngoLogin: (email, password) =>
    json('/auth/ngo/login', {
      method: 'POST',
      body: JSON.stringify({ email, password })
    }),

  // VOLUNTEER
  getVolunteerProfile: () => json('/volunteer/profile'),

  getAvailableTasks: (qs = '') =>
    json('/volunteer/tasks/available' + qs),

  getTaskHistory: () =>
    json('/volunteer/tasks/history'),

  // ✅ FIXED — correct endpoint
  getAiSuggestions: () =>
    json('/volunteer/ai-suggestions'),

  applyForTask: (taskId) =>
    json(`/volunteer/tasks/${taskId}/apply`, { method: 'POST' }),

  // NGO
  getNGOProfile: () => json('/ngo/profile'),

  postTask: (data) =>
    json('/ngo/tasks', {
      method: 'POST',
      body: JSON.stringify(data)
    }),

  getActiveRequests: () =>
    json('/ngo/dashboard/active'),

  // MAP
  getTaskGeoJSON: (qs = '') =>
    json('/map/geojson/tasks' + qs),

  getTaskHeatmap: (qs = '') =>
    json('/map/heatmap/tasks' + qs)
};

window.api = api;
// Generic GET (used by map.js)
api.get = (path) => apiFetch(path);

// Volunteer stats
api.getVolunteerStats = () =>
  json('/volunteer/stats');

// AI Suggestions
api.getAiSuggestions = () =>
  json('/volunteer/ai-suggestions');

// NGO
api.getNGOProfile = () =>
  json('/ngo/profile');

api.getActiveRequests = () =>
  json('/ngo/dashboard/active');

api.getPendingReports = () =>
  json('/ngo/reports');

// POST task
api.postTask = (data) =>
  json('/ngo/tasks', {
    method: 'POST',
    body: JSON.stringify(data)
  });