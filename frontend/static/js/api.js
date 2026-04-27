/**
 * static/js/api.js  — FIXED
 * Changes:
 *  1. Auth.save() stores user_type from JWT claim (not dict identity)
 *  2. apiFetch retries on BOTH 401 AND 422 (invalid/expired token)
 *  3. All dashboard loaders have try/catch that clear spinners on error
 */

const API_BASE = '/api';

// ── Token Management ──────────────────────────────────────────
const Auth = {
  getToken()    { return localStorage.getItem('access_token'); },
  getRefresh()  { return localStorage.getItem('refresh_token'); },
  getUserType() { return localStorage.getItem('user_type'); },
  getUserId()   { return localStorage.getItem('user_id'); },
  getUserName() { return localStorage.getItem('user_name'); },

  save({ access_token, refresh_token, id, type, name }) {
    if (access_token)  localStorage.setItem('access_token',  access_token);
    if (refresh_token) localStorage.setItem('refresh_token', refresh_token);
    if (id)   localStorage.setItem('user_id',   id);
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
    else                      window.location.href = '/login.html';
  },

  requireAuth() {
    if (!this.isLoggedIn()) { window.location.href = '/login.html'; return false; }
    return true;
  },

  requireType(type) {
    if (!this.isLoggedIn() || this.getUserType() !== type) {
      window.location.href = '/login.html';
      return false;
    }
    return true;
  },

  logout() { this.clear(); window.location.href = '/login.html'; }
};

// ── Token refresh helper ──────────────────────────────────────
let _refreshing = false;
let _refreshQueue = [];

async function tryRefresh() {
  // Prevent multiple simultaneous refresh calls
  if (_refreshing) {
    return new Promise((resolve) => _refreshQueue.push(resolve));
  }
  _refreshing = true;

  try {
    const res = await fetch(API_BASE + '/auth/refresh', {
      method: 'POST',
      headers: { 'Authorization': `Bearer ${Auth.getRefresh()}` }
    });
    if (res.ok) {
      const data = await res.json();
      localStorage.setItem('access_token', data.access_token);
      _refreshQueue.forEach(r => r(true));
      _refreshQueue = [];
      return true;
    }
    _refreshQueue.forEach(r => r(false));
    _refreshQueue = [];
    return false;
  } catch {
    _refreshQueue.forEach(r => r(false));
    _refreshQueue = [];
    return false;
  } finally {
    _refreshing = false;
  }
}

// ── Core fetch wrapper ────────────────────────────────────────
async function apiFetch(path, options = {}, _retried = false) {
  const token = Auth.getToken();
  const hasBody = options.body !== undefined && options.body !== null;
  const headers = {
    ...(hasBody && !(options.body instanceof FormData) ? { 'Content-Type': 'application/json' } : {}),
    ...(token ? { 'Authorization': `Bearer ${token}` } : {}),
    ...(options.headers || {})
  };

  // FormData must NOT have Content-Type set (browser sets boundary automatically)
  if (options.body instanceof FormData) delete headers['Content-Type'];

  const res = await fetch(API_BASE + path, { ...options, headers });

  // Handle 401 (unauthorized) AND 422 (invalid/malformed token) — FIXED
  if ((res.status === 401 || res.status === 422) && !_retried) {
    if (Auth.getRefresh()) {
      const refreshed = await tryRefresh();
      if (refreshed) {
        // Retry the original request once with the new token
        return apiFetch(path, options, true);
      }
    }
    // Could not refresh — log out cleanly
    Auth.logout();
    return res;
  }

  return res;
}

// ── Convenience wrappers ──────────────────────────────────────
const api = {
  get:    (path)         => apiFetch(path),
  post:   (path, body)   => apiFetch(path, { method: 'POST',   body: JSON.stringify(body) }),
  put:    (path, body)   => apiFetch(path, { method: 'PUT',    body: JSON.stringify(body) }),
  patch:  (path, body)   => apiFetch(path, { method: 'PATCH',  body: JSON.stringify(body) }),
  delete: (path)         => apiFetch(path, { method: 'DELETE' }),
  upload: (path, fd)     => apiFetch(path, { method: 'POST',   body: fd }),

  /**
   * Fetch + parse JSON in one call.
   * Throws a user-friendly Error on non-2xx responses.
   */
  async json(path, options) {
    const res  = await apiFetch(path, options);
    let data;
    try {
      data = await res.json();
    } catch {
      throw new Error(`Server error (${res.status})`);
    }
    if (!res.ok) {
      throw new Error(data.error || data.message || `Request failed (${res.status})`);
    }
    return data;
  },

  // ── Auth ────────────────────────────────────────────────────
  async volunteerLogin(email, password) {
    return this.json('/auth/volunteer/login', {
      method: 'POST', body: JSON.stringify({ email, password })
    });
  },
  async ngoLogin(email, password) {
    return this.json('/auth/ngo/login', {
      method: 'POST', body: JSON.stringify({ email, password })
    });
  },
  async volunteerSignup(payload) {
    return this.json('/auth/volunteer/signup', {
      method: 'POST', body: JSON.stringify(payload)
    });
  },
  async ngoSignup(payload) {
    return this.json('/auth/ngo/signup', {
      method: 'POST', body: JSON.stringify(payload)
    });
  },

  // ── Volunteer ───────────────────────────────────────────────
  async getVolunteerProfile()        { return this.json('/volunteer/profile'); },
  async getVolunteerStats()          { return this.json('/volunteer/stats'); },
  async getAvailableTasks(qs = '')   { return this.json('/volunteer/tasks/available' + qs); },
  async getAiSuggestions()           { return this.json('/volunteer/ai-suggestions'); },
  async getMyNotifications()         { return this.json('/volunteer/notifications'); },
  async getTaskHistory()             { return this.json('/volunteer/tasks/history'); },
  async applyForTask(taskId)         { return this.json(`/volunteer/tasks/${taskId}/apply`, { method: 'POST' }); },
  async acceptTask(taskId)           { return this.json(`/volunteer/tasks/${taskId}/accept`, { method: 'POST' }); },
  async rejectTask(taskId)           { return this.json(`/volunteer/tasks/${taskId}/reject`, { method: 'POST' }); },

  // ── NGO ─────────────────────────────────────────────────────
  async getNGOProfile()                { return this.json('/ngo/profile'); },
  async postTask(payload)              { return this.json('/ngo/tasks', { method: 'POST', body: JSON.stringify(payload) }); },
  async getActiveRequests()            { return this.json('/ngo/dashboard/active'); },
  async getCompletedRequests()         { return this.json('/ngo/dashboard/completed'); },
  async getPendingReports()            { return this.json('/ngo/reports'); },
  async getTaskApplicants(taskId)      { return this.json(`/ngo/tasks/${taskId}/applicants`); },
  async assignVolunteer(taskId, volId) { return this.json(`/ngo/tasks/${taskId}/assign/${volId}`, { method: 'POST' }); },
  async changeUrgency(taskId, urg)     { return this.json(`/ngo/tasks/${taskId}/urgency`, { method: 'PATCH', body: JSON.stringify({ urgency: urg }) }); },
  async reviewReport(id, action, note) { return this.json(`/ngo/reports/${id}/review`, { method: 'POST', body: JSON.stringify({ action, note }) }); },
  async getNGOAiSuggestions(taskId)    { return this.json(`/ngo/tasks/${taskId}/ai-suggestions`); },
  async getNGOAnalytics()              { return this.json('/ngo/analytics'); },
  async predictTask(taskId)            { return this.json(`/ngo/tasks/${taskId}/predict`); },

  // ── Map ─────────────────────────────────────────────────────
  async getTaskHeatmap(qs = '')  { return this.json('/map/heatmap/tasks' + qs); },
  async getProblemHeatmap()      { return this.json('/map/heatmap/problems'); },
  async getTaskGeoJSON(qs = '')  { return this.json('/map/geojson/tasks' + qs); },
  async getVolPositions()        { return this.json('/map/volunteers/positions'); },
  async getRoutingLines()        { return this.json('/map/lines/volunteer-to-task'); },
  async getClusters()            { return this.json('/map/clusters'); },
};

// ── Toast Notifications ───────────────────────────────────────
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

// ── Shared DOM helpers ────────────────────────────────────────

/** Replace an element's innerHTML with a centred error message. */
function showError(el, message) {
  if (!el) return;
  el.innerHTML = `
    <div class="empty-state">
      <div class="icon">⚠️</div>
      <p style="color:var(--red);">${message}</p>
    </div>`;
}

/** Replace an element's innerHTML with an empty-state block. */
function showEmpty(el, icon, message) {
  if (!el) return;
  el.innerHTML = `
    <div class="empty-state">
      <div class="icon">${icon}</div>
      <p>${message}</p>
    </div>`;
}

/** Spinner markup — drop into any container while data is loading. */
function spinnerHTML() {
  return '<div class="loader"><div class="spinner"></div></div>';
}

// ── Date / string helpers ─────────────────────────────────────
function formatDate(iso) {
  if (!iso) return '—';
  return new Date(iso).toLocaleDateString('en-IN', {
    day: 'numeric', month: 'short', year: 'numeric'
  });
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

// ── Geolocation ───────────────────────────────────────────────
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