const API_BASE = '/api';

// ── Auth ─────────────────────────────────────────
const Auth = {
  getToken()    { return localStorage.getItem('access_token'); },
  getRefresh()  { return localStorage.getItem('refresh_token'); },
  getUserType() { return localStorage.getItem('user_type'); },
  getUserId()   { return localStorage.getItem('user_id'); },
  getUserName() { return localStorage.getItem('user_name'); },

  save({ access_token, refresh_token, id, type, name }) {
    if (access_token)  localStorage.setItem('access_token', access_token);
    if (refresh_token) localStorage.setItem('refresh_token', refresh_token);
    if (id)   localStorage.setItem('user_id', id);
    if (type)  localStorage.setItem('user_type', type);
    if (name)  localStorage.setItem('user_name', name);
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

  requireAuth() {
    if (!this.isLoggedIn()) {
      window.location.href = '/login.html';
      return false;
    }
    return true;
  },

  requireType(type) {
    if (!this.isLoggedIn() || this.getUserType() !== type) {
      window.location.href = '/login.html';
      return false;
    }
    return true;
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
  const hasBody = options.body !== undefined && options.body !== null;

  const headers = {
    'X-Requested-With': 'XMLHttpRequest',
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
    ...(hasBody && !(options.body instanceof FormData) ? { 'Content-Type': 'application/json' } : {}),
    ...(options.headers || {})
  };

  if (options.body instanceof FormData) {
    delete headers['Content-Type'];
  }

  const res = await fetch(API_BASE + path, { ...options, headers });

  // FIX 8: Automatically attempt to refresh token if 401/422 Unauthorized is encountered
  if ((res.status === 401 || res.status === 422) && !retried) {
    const refresh = Auth.getRefresh();
    if (refresh) {
      const refreshRes = await fetch(API_BASE + '/auth/refresh', {
        method: 'POST',
        headers: { 'Authorization': `Bearer ${refresh}` }
      });
      if (refreshRes.ok) {
        const data = await refreshRes.json();
        Auth.save({ access_token: data.access_token });
        // Retry the original request
        return apiFetch(path, options, true);
      }
    }
    Auth.logout();
    return res;
  }

  return res;
}

async function json(path, options = {}) {
  const res = await apiFetch(path, options);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error(data.error || data.message || `Request failed (${res.status})`);
  }
  return data;
}

// ── API OBJECT ──────────────────────────────────
// FIX 7: Use `json` instead of `apiFetch` in generic REST wrappers so errors are correctly thrown
const api = {
  get:    (path) => json(path),
  post:   (path, body) => json(path, { method: 'POST', body: body instanceof FormData ? body : JSON.stringify(body) }),
  put:    (path, body) => json(path, { method: 'PUT', body: body instanceof FormData ? body : JSON.stringify(body) }),
  patch:  (path, body) => json(path, { method: 'PATCH', body: body instanceof FormData ? body : JSON.stringify(body) }),
  delete: (path) => json(path, { method: 'DELETE' }),
  upload: (path, fd) => json(path, { method: 'POST', body: fd }),
  json: json,

  volunteerLogin: (email, password) =>
    json('/auth/volunteer/login', { method: 'POST', body: JSON.stringify({ email, password }) }),

  ngoLogin: (email, password) =>
    json('/auth/ngo/login', { method: 'POST', body: JSON.stringify({ email, password }) }),

  volunteerSignup: (payload) =>
    json('/auth/volunteer/signup', { method: 'POST', body: JSON.stringify(payload) }),

  ngoSignup: (payload) =>
    json('/auth/ngo/signup', { method: 'POST', body: JSON.stringify(payload) }),

  getVolunteerProfile: () => json('/volunteer/profile'),
  getVolunteerStats: () => json('/volunteer/stats'),
  getAvailableTasks: (qs = '') => json('/volunteer/tasks/available' + qs),
  getAiSuggestions: () => json('/volunteer/ai-suggestions'),
  getMyNotifications: () => json('/volunteer/notifications'),
  getTaskHistory: () => json('/volunteer/tasks/history'),
  applyForTask: (taskId) => json(`/volunteer/tasks/${taskId}/apply`, { method: 'POST' }),
  acceptTask: (taskId) => json(`/volunteer/tasks/${taskId}/accept`, { method: 'POST' }),
  rejectTask: (taskId) => json(`/volunteer/tasks/${taskId}/reject`, { method: 'POST' }),

  getNGOProfile: () => json('/ngo/profile'),
  postTask: (data) => json('/ngo/tasks', { method: 'POST', body: JSON.stringify(data) }),
  getActiveRequests: () => json('/ngo/dashboard/active'),
  getCompletedRequests: () => json('/ngo/dashboard/completed'),
  getPendingReports: () => json('/ngo/reports'),
  getTaskApplicants: (taskId) => json(`/ngo/tasks/${taskId}/applicants`),
  assignVolunteer: (taskId, volId) => json(`/ngo/tasks/${taskId}/assign/${volId}`, { method: 'POST' }),
  changeUrgency: (taskId, urg) => json(`/ngo/tasks/${taskId}/urgency`, { method: 'PATCH', body: JSON.stringify({ urgency: urg }) }),
  
  // FIX 5: Ensure 'deadline' is accepted and sent to the server when converting report to task
  reviewReport: (id, action, note, deadline) => json(`/ngo/reports/${id}/review`, { method: 'POST', body: JSON.stringify({ action, note, deadline }) }),
  
  getNGOAiSuggestions: (taskId) => json(`/ngo/tasks/${taskId}/ai-suggestions`),
  getNGOAnalytics: () => json('/ngo/analytics'),
  predictTask: (taskId) => json(`/ngo/tasks/${taskId}/predict`),

  getTaskGeoJSON: (qs = '') => json('/map/geojson/tasks' + qs),
  getTaskHeatmap: (qs = '') => json('/map/heatmap/tasks' + qs),
  getProblemHeatmap: (qs = '') => json('/map/heatmap/problems' + qs),
  getVolPositions: (qs = '') => json('/map/volunteers/positions' + qs),
  getRoutingLines: (qs = '') => json('/map/lines/volunteer-to-task' + qs),
  getClusters: (qs = '') => json('/map/clusters' + qs)
};

window.api = api;

// Toasts / helpers
function showToast(message, type = 'info', duration = 4000) {
  const icons = { success: '✓', error: '✕', info: 'ℹ', warning: '⚠' };
  let container = document.getElementById('toast-container');
  if (!container) {
    container = document.createElement('div');
    container.id = 'toast-container';
    document.body.appendChild(container);
  }

  const toast = document.createElement('div');
  toast.className = `toast ${type}`;
  toast.innerHTML = `<span>${icons[type] || 'ℹ'}</span><span>${message}</span>`;
  container.appendChild(toast);

  setTimeout(() => {
    toast.style.animation = 'slideOut 0.3s both';
    setTimeout(() => toast.remove(), 300);
  }, duration);
}

function showError(el, message) {
  if (!el) return;
  el.innerHTML = `<div class="empty-state"><div class="icon">⚠️</div><p style="color:var(--red);">${message}</p></div>`;
}

function showEmpty(el, icon, message) {
  if (!el) return;
  el.innerHTML = `<div class="empty-state"><div class="icon">${icon}</div><p>${message}</p></div>`;
}

function spinnerHTML() {
  return '<div class="loader"><div class="spinner"></div></div>';
}

function formatDate(iso) {
  if (!iso) return '—';
  return new Date(iso).toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric' });
}

function timeAgo(iso) {
  if (!iso) return '';
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1)    return 'just now';
  if (mins < 60)   return `${mins}m ago`;
  if (mins < 1440) return `${Math.floor(mins / 60)}h ago`;
  return `${Math.floor(mins / 1440)}d ago`;
}

function urgencyBadge(u = 'low') {
  return `<span class="badge badge-${u}">${u.toUpperCase()}</span>`;
}

function statusBadge(s = '') {
  return `<span class="badge badge-${s}">${s.replace('_', ' ')}</span>`;
}

function initials(name = '') {
  return name.split(' ').map(w => w[0]).join('').slice(0, 2).toUpperCase() || '?';
}

function getUserLocation() {
  return new Promise((resolve, reject) => {
    if (!navigator.geolocation) {
      reject('Geolocation not supported by this browser');
      return;
    }
    navigator.geolocation.getCurrentPosition(
      pos => resolve({ lat: pos.coords.latitude, lng: pos.coords.longitude }),
      err => reject(err.message),
      { timeout: 8000 }
    );
  });
}