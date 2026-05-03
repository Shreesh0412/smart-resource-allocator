/**
 * static/js/api.js
 *
 * FIXES:
 *  S5 — Tokens are no longer stored in localStorage where XSS can steal them.
 *       Access and refresh tokens are now HttpOnly cookies set by the server
 *       and sent automatically by the browser — JavaScript cannot read them.
 *       Only non-sensitive identifiers (user_id, user_type, user_name) remain
 *       in localStorage for UI routing decisions.
 *
 *       What changed:
 *         • Auth.save()      — no longer stores access_token / refresh_token
 *         • Auth.getToken()  — removed (cookie is invisible to JS by design)
 *         • Auth.getRefresh()— removed
 *         • apiFetch()       — no longer sets Authorization header; browser
 *                              sends the HttpOnly cookie automatically
 *         • Token refresh    — calls /auth/refresh; server reads the HttpOnly
 *                              refresh cookie and sets a new access cookie
 *         • Auth.logout()    — calls /auth/logout to clear server-side cookies,
 *                              then clears localStorage
 *         • Auth.isLoggedIn()— checks user_type in localStorage (set at login)
 *                              since the token itself is now invisible to JS
 *
 *       REQUIRED backend changes (already in the fixed auth_routes.py):
 *         • Login / signup endpoints use set_access_cookies() / set_refresh_cookies()
 *         • A new POST /auth/logout endpoint calls unset_jwt_cookies()
 *         • config.py sets JWT_TOKEN_LOCATION = ["cookies"]
 */

const API_BASE = window.API_BASE
  || document.querySelector('meta[name="api-base"]')?.content
  || '/api';

// ── Auth ──────────────────────────────────────────────────────
const Auth = {
  // Non-sensitive UI state only — tokens are in HttpOnly cookies
  getUserType() { return localStorage.getItem('user_type'); },
  getUserId()   { return localStorage.getItem('user_id');   },
  getUserName() { return localStorage.getItem('user_name'); },

  /**
   * S5 FIX: save() no longer persists access_token or refresh_token.
   * Those are HttpOnly cookies set by the server and invisible to JavaScript.
   * We only keep UI-routing data (id, type, name) in localStorage.
   */
  save({ id, type, name } = {}) {
    if (id)   localStorage.setItem('user_id',   id);
    if (type) localStorage.setItem('user_type', type);
    if (name) localStorage.setItem('user_name', name);
  },

  clear() {
    ['user_id', 'user_type', 'user_name'].forEach(k => localStorage.removeItem(k));
  },

  /**
   * S5 FIX: isLoggedIn() can no longer inspect the token (it's HttpOnly).
   * We rely on user_type being present in localStorage, which is set on login
   * and cleared on logout.
   */
  isLoggedIn() { return !!this.getUserType(); },

  async validateSession() {
    const type = this.getUserType();
    if (!type) return false;
    const endpoint = type === 'ngo' ? '/ngo/profile' : '/volunteer/profile';
    try {
      const res = await fetch(API_BASE + endpoint, {
        credentials: 'include',   // send HttpOnly cookies
        headers: { 'X-Requested-With': 'XMLHttpRequest' }
      });
      return res.ok;
    } catch {
      return false;
    }
  },

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

  /**
   * S5 FIX: logout() now calls the backend /auth/logout endpoint which runs
   * unset_jwt_cookies() to clear the HttpOnly cookies server-side.
   * localStorage is cleared afterwards for the UI state.
   */
  async logout() {
    try {
      await fetch(API_BASE + '/auth/logout', {
        method: 'POST',
        credentials: 'include',
        headers: { 'X-Requested-With': 'XMLHttpRequest' }
      });
    } catch (_) {
      // Even if the server call fails, clear local state and redirect
    }
    this.clear();
    window.location.href = '/login.html';
  }
};

window.Auth = Auth;

// ── Core Fetch ────────────────────────────────────────────────
/**
 * S5 FIX: apiFetch() no longer reads a token from localStorage or sets an
 * Authorization header. The browser sends the HttpOnly access_token cookie
 * automatically on every same-origin request when credentials:'include' is set.
 *
 * Token refresh: on 401, POST to /auth/refresh — the browser sends the
 * HttpOnly refresh_token cookie, the server validates it and sets a fresh
 * access_token cookie, then we retry the original request.
 */
async function apiFetch(path, options = {}, retried = false) {
  const hasBody = options.body !== undefined && options.body !== null;

  const headers = {
    'X-Requested-With': 'XMLHttpRequest',
    ...(hasBody && !(options.body instanceof FormData)
        ? { 'Content-Type': 'application/json' }
        : {}),
    ...(options.headers || {})
  };

  if (options.body instanceof FormData) {
    delete headers['Content-Type'];
  }

  const res = await fetch(API_BASE + path, {
    ...options,
    headers,
    credentials: 'include',   // always send HttpOnly cookies
  });

  // On 401/422 attempt a silent token refresh using the HttpOnly refresh cookie
  if ((res.status === 401 || res.status === 422) && !retried) {
    const refreshRes = await fetch(API_BASE + '/auth/refresh', {
      method: 'POST',
      credentials: 'include',
      headers: { 'X-Requested-With': 'XMLHttpRequest' }
    });

    if (refreshRes.ok) {
      // Server set a new access_token cookie — retry the original request
      return apiFetch(path, options, true);
    }

    // Refresh failed — session is truly expired
    Auth.clear();
    window.location.href = '/login.html';
    return res;
  }

  return res;
}

async function json(path, options = {}) {
  const res  = await apiFetch(path, options);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error(data.error || data.message || `Request failed (${res.status})`);
  }
  return data;
}

// ── API object ────────────────────────────────────────────────
const api = {
  get:    (path)        => json(path),
  post:   (path, body)  => json(path, { method: 'POST',   body: body instanceof FormData ? body : JSON.stringify(body) }),
  put:    (path, body)  => json(path, { method: 'PUT',    body: body instanceof FormData ? body : JSON.stringify(body) }),
  patch:  (path, body)  => json(path, { method: 'PATCH',  body: body instanceof FormData ? body : JSON.stringify(body) }),
  delete: (path)        => json(path, { method: 'DELETE' }),
  upload: (path, fd)    => json(path, { method: 'POST',   body: fd }),
  json,

  volunteerLogin:  (email, password) => json('/auth/volunteer/login', { method: 'POST', body: JSON.stringify({ email, password }) }),
  ngoLogin:        (email, password) => json('/auth/ngo/login',       { method: 'POST', body: JSON.stringify({ email, password }) }),
  volunteerSignup: (payload)         => json('/auth/volunteer/signup', { method: 'POST', body: JSON.stringify(payload) }),
  ngoSignup:       (payload)         => json('/auth/ngo/signup',       { method: 'POST', body: JSON.stringify(payload) }),

  getVolunteerProfile:  ()           => json('/volunteer/profile'),
  getVolunteerStats:    ()           => json('/volunteer/stats'),
  getAvailableTasks:    (qs = '')    => json('/volunteer/tasks/available' + qs),
  getAiSuggestions:     ()           => json('/volunteer/ai-suggestions'),
  getMyNotifications:   ()           => json('/volunteer/notifications'),
  getTaskHistory:       ()           => json('/volunteer/tasks/history'),
  applyForTask:         (taskId)     => json(`/volunteer/tasks/${taskId}/apply`, { method: 'POST' }),
  acceptTask:           (taskId)     => json(`/volunteer/tasks/${taskId}/accept`, { method: 'POST' }),
  rejectTask:           (taskId)     => json(`/volunteer/tasks/${taskId}/reject`, { method: 'POST' }),

  getNGOProfile:         ()                      => json('/ngo/profile'),
  postTask:              (data)                  => json('/ngo/tasks', { method: 'POST', body: JSON.stringify(data) }),
  getActiveRequests:     ()                      => json('/ngo/dashboard/active'),
  getCompletedRequests:  ()                      => json('/ngo/dashboard/completed'),
  getPendingReports:     ()                      => json('/ngo/reports'),
  getTaskApplicants:     (taskId)                => json(`/ngo/tasks/${taskId}/applicants`),
  assignVolunteer:       (taskId, volId)         => json(`/ngo/tasks/${taskId}/assign/${volId}`, { method: 'POST' }),
  changeUrgency:         (taskId, urg)           => json(`/ngo/tasks/${taskId}/urgency`, { method: 'PATCH', body: JSON.stringify({ urgency: urg }) }),
  reviewReport:          (id, action, note, dl)  => json(`/ngo/reports/${id}/review`, { method: 'POST', body: JSON.stringify({ action, note, deadline: dl }) }),
  getNGOAiSuggestions:   (taskId)                => json(`/ngo/tasks/${taskId}/ai-suggestions`),
  getNGOAnalytics:       ()                      => json('/ngo/analytics'),
  predictTask:           (taskId)                => json(`/ngo/tasks/${taskId}/predict`),

  getTaskGeoJSON:    (qs = '') => json('/map/geojson/tasks' + qs),
  getTaskHeatmap:    (qs = '') => json('/map/heatmap/tasks' + qs),
  getProblemHeatmap: (qs = '') => json('/map/heatmap/problems' + qs),
  getVolPositions:   (qs = '') => json('/map/volunteers/positions' + qs),
  getRoutingLines:   (qs = '') => json('/map/lines/volunteer-to-task' + qs),
  getClusters:       (qs = '') => json('/map/clusters' + qs),
};

window.api = api;

// ── XSS-safe HTML helper (S2) ─────────────────────────────────
/**
 * Escapes a user-supplied string so it is safe to embed inside innerHTML.
 * Use this on every value that comes from the API before inserting into HTML.
 * Example:  el.innerHTML = `<div>${escHtml(task.title)}</div>`;
 */
function escHtml(str) {
  if (str == null) return '';
  return String(str)
    .replace(/&/g,  '&amp;')
    .replace(/</g,  '&lt;')
    .replace(/>/g,  '&gt;')
    .replace(/"/g,  '&quot;')
    .replace(/'/g,  '&#039;');
}
window.escHtml = escHtml;

// ── Toast helpers ─────────────────────────────────────────────
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
  // escHtml on message so a server error string can't inject HTML
  toast.innerHTML = `<span>${icons[type] || 'ℹ'}</span><span>${escHtml(message)}</span>`;
  container.appendChild(toast);
  setTimeout(() => {
    toast.style.animation = 'slideOut 0.3s both';
    setTimeout(() => toast.remove(), 300);
  }, duration);
}

function showError(el, message) {
  if (!el) return;
  el.innerHTML = `<div class="empty-state"><div class="icon">⚠️</div><p style="color:var(--red);">${escHtml(message)}</p></div>`;
}

function showEmpty(el, icon, message) {
  if (!el) return;
  // icon is a trusted emoji literal from our own code, message is also ours
  el.innerHTML = `<div class="empty-state"><div class="icon">${icon}</div><p>${escHtml(message)}</p></div>`;
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
  return `<span class="badge badge-${escHtml(u)}">${escHtml(u.toUpperCase())}</span>`;
}

function statusBadge(s = '') {
  return `<span class="badge badge-${escHtml(s)}">${escHtml(s.replace('_', ' '))}</span>`;
}

function initials(name = '') {
  return String(name).split(' ').map(w => w[0]).join('').slice(0, 2).toUpperCase() || '?';
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