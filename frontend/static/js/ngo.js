/**
 * static/js/ngo.js
 * NGO dashboard controller — all panel logic, API calls, and UI rendering.
 */

if (!Auth.requireType('ngo')) throw new Error('Not authenticated');

document.getElementById('nav-name').textContent = Auth.getUserName() || 'NGO';

let currentPanel = 'overview';
let selectedRating = 0;

// ✨ NEW: Map Variables
let postTaskMap = null;
let postTaskMarker = null;

// ── Panel Navigation ──────────────────────────────────────────
function showPanel(name) {
  document.querySelectorAll('[id^="panel-"]').forEach(p => p.style.display = 'none');
  document.querySelectorAll('.sidebar-link').forEach(l => l.classList.remove('active'));

  const panel = document.getElementById(`panel-${name}`);
  const link  = document.getElementById(`link-${name}`);
  if (panel) panel.style.display = 'block';
  if (link)  link.classList.add('active');
  currentPanel = name;

  const loaders = {
    overview:      loadOverview,
    'post-task':   initPostTaskMap, // ✨ Trigger map init when tab opens
    active:        loadActive,
    completed:     loadCompleted,
    reports:       loadReports,
    resources:     loadResources,
    analytics:     loadAnalytics,
    inefficiency:  loadInefficiency,
  };
  if (loaders[name]) loaders[name]();
}

// ✨ NEW: Map Initialization
function initPostTaskMap() {
  if (postTaskMap) {
    // Already initialized, just fix sizing since it was hidden
    setTimeout(() => postTaskMap.invalidateSize(), 100);
    return;
  }
  
  const defaultLat = 20.5937; // India Center
  const defaultLng = 78.9629;
  
  postTaskMap = L.map('task-picker-map').setView([defaultLat, defaultLng], 5);
  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    attribution: '© OpenStreetMap'
  }).addTo(postTaskMap);

  function updateCoords(lat, lng) {
    document.getElementById('t-lat').value = lat;
    document.getElementById('t-lng').value = lng;
    if (postTaskMarker) {
      postTaskMarker.setLatLng([lat, lng]);
    } else {
      postTaskMarker = L.marker([lat, lng], {draggable: true}).addTo(postTaskMap);
      postTaskMarker.on('dragend', function() {
        const pos = postTaskMarker.getLatLng();
        updateCoords(pos.lat, pos.lng);
      });
    }
  }

  // Auto locate if allowed
  if ("geolocation" in navigator) {
    navigator.geolocation.getCurrentPosition(function(pos) {
      const uLat = pos.coords.latitude;
      const uLng = pos.coords.longitude;
      postTaskMap.setView([uLat, uLng], 15);
      updateCoords(uLat, uLng);
    });
  }

  postTaskMap.on('click', function(e) {
    updateCoords(e.latlng.lat, e.latlng.lng);
  });

  setTimeout(() => postTaskMap.invalidateSize(), 100);
}

// ── Skill tag toggle (post task form) ────────────────────────
document.querySelectorAll('.skill-tag2').forEach(tag => {
  tag.style.cssText = `
    padding:4px 12px; border-radius:100px; border:1px solid var(--border);
    font-size:0.8rem; cursor:pointer; color:var(--text-muted);
    transition:all 150ms; user-select:none;
  `;
  tag.addEventListener('click', () => {
    const on = tag.classList.toggle('selected');
    tag.style.background     = on ? 'var(--orange-glow)' : '';
    tag.style.borderColor    = on ? 'var(--orange)'      : 'var(--border)';
    tag.style.color          = on ? 'var(--orange)'      : 'var(--text-muted)';
  });
});

function getSelectedSkills() {
  return [...document.querySelectorAll('.skill-tag2.selected')].map(t => t.dataset.s);
}

// ── Star rating wiring ────────────────────────────────────────
document.querySelectorAll('.star').forEach(star => {
  star.addEventListener('click', () => {
    selectedRating = parseInt(star.dataset.v);
    document.getElementById('rv-rating').value = selectedRating;
    document.querySelectorAll('.star').forEach((s, i) => {
      s.textContent = i < selectedRating ? '★' : '☆';
      s.style.color = i < selectedRating ? 'var(--yellow)' : 'var(--text-dim)';
    });
  });
  star.addEventListener('mouseover', () => {
    const v = parseInt(star.dataset.v);
    document.querySelectorAll('.star').forEach((s, i) => {
      s.textContent = i < v ? '★' : '☆';
      s.style.color = i < v ? 'var(--yellow)' : 'var(--text-dim)';
    });
  });
  star.addEventListener('mouseout', () => {
    document.querySelectorAll('.star').forEach((s, i) => {
      s.textContent = i < selectedRating ? '★' : '☆';
      s.style.color = i < selectedRating ? 'var(--yellow)' : 'var(--text-dim)';
    });
  });
});

// ── Overview ──────────────────────────────────────────────────
async function loadOverview() {
  try {
    const profile = await api.getNGOProfile();
    document.getElementById('ngo-title').textContent  = profile.name + ' — Dashboard';
    document.getElementById('ngo-subtitle').textContent =
      `${profile.focus_areas?.join(' · ') || ''} · Reg: ${profile.registration_number || '—'}`;

    document.getElementById('ov-posted').textContent    = profile.total_tasks_posted    || 0;
    document.getElementById('ov-completed').textContent = profile.total_tasks_completed || 0;
    document.getElementById('ov-volunteers').textContent= profile.active_volunteers     || 0;

    await loadUrgencyBoard();

    // Count urgent open tasks for the stat card
    const active = await api.getActiveRequests();
    const urgent = (active.tasks || []).filter(t => t.urgency === 'urgent').length;
    document.getElementById('ov-urgent').textContent = urgent;

    // Check pending reports
    const reports = await api.json('/ngo/reports'); // Fixed standard JSON call
    const pending = (reports.reports || []).length;
    if (pending > 0) {
      const badge = document.getElementById('reports-count');
      badge.style.display = 'inline-block';
    }
  } catch(e) {
    showToast('Failed to load overview: ' + e.message, 'error');
  }
}

// ── Urgency Board ─────────────────────────────────────────────
async function loadUrgencyBoard() {
  const board = document.getElementById('urgency-board');
  board.innerHTML = '<div class="loader"><div class="spinner"></div></div>';

  try {
    const res  = await api.json('/tasks/urgency-board');
    const data = res.urgency_board || { urgent:[], med:[], low:[] };

    board.innerHTML = `
      <div class="urgency-col urgent">
        <div class="urgency-col-header">
          🔴 Urgent <span>${data.urgent.length}</span>
        </div>
        <div id="ub-urgent">${renderMiniTasks(data.urgent)}</div>
      </div>
      <div class="urgency-col med">
        <div class="urgency-col-header">
          🟡 Medium <span>${data.med.length}</span>
        </div>
        <div id="ub-med">${renderMiniTasks(data.med)}</div>
      </div>
      <div class="urgency-col low">
        <div class="urgency-col-header">
          🟢 Low <span>${data.low.length}</span>
        </div>
        <div id="ub-low">${renderMiniTasks(data.low)}</div>
      </div>
    `;
  } catch(e) {
    board.innerHTML = `<p style="color:var(--text-muted);padding:20px;">${e.message}</p>`;
  }
}

function renderMiniTasks(tasks) {
  if (!tasks.length) return '<p style="font-size:0.8rem;color:var(--text-dim);padding:8px 0;">No tasks</p>';
  return tasks.map(t => `
    <div class="mini-task" onclick="openNGOTaskModal('${t._id}')">
      <div class="mini-task-title">${t.title}</div>
      <div class="mini-task-meta">
        <span>👥 ${(t.assigned_volunteers?.length||0)}/${t.volunteers_needed}</span>
        <span>⏰ ${formatDate(t.deadline)}</span>
        ${t.prediction?.risk_level ? `<span class="risk-${t.prediction.risk_level}">${riskIcon(t.prediction.risk_level)} ${t.prediction.risk_level.replace('_',' ')}</span>` : ''}
      </div>
    </div>
  `).join('');
}

function riskIcon(r) {
  return r === 'on_track' ? '✅' : r === 'at_risk' ? '⚠️' : '🚨';
}


function toggleSkill(el) {
  const on = el.classList.toggle('selected');
  el.style.background  = on ? 'var(--orange-glow)' : '';
  el.style.borderColor = on ? 'var(--orange)'      : 'var(--border)';
  el.style.color       = on ? 'var(--orange)'      : 'var(--text-muted)';
}

async function postTask(e) {
  e.preventDefault();
  const btn   = document.getElementById('post-btn');
  const errEl = document.getElementById('post-error');
  errEl.style.display = 'none';

  // ✨ Ensure a location was selected
  const latVal = document.getElementById('t-lat').value;
  const lngVal = document.getElementById('t-lng').value;
  if (!latVal || !lngVal) {
    errEl.textContent = "Please set the exact location on the map.";
    errEl.style.display = 'block';
    return;
  }

  btn.disabled = true;
  btn.textContent = 'Posting & matching…';

  try {
    const payload = {
      title:             document.getElementById('t-title').value,
      description:       document.getElementById('t-desc').value,
      task_type:         document.getElementById('t-type').value,
      volunteers_needed: parseInt(document.getElementById('t-volunteers').value),
      urgency:           document.getElementById('t-urgency').value || undefined,
      deadline:          document.getElementById('t-deadline').value,
      address:           document.getElementById('t-address').value,
      pincode:           document.getElementById('t-pincode').value.trim(),
      required_skills:   getSelectedSkills(),
      // ✨ Send actual map coordinates
      lat:               parseFloat(latVal),
      lng:               parseFloat(lngVal)
    };

    const data = await api.postTask(payload);
    showToast(
      `Task posted! ${data.auto_matched_volunteers} volunteers auto-matched & notified via WhatsApp.`,
      'success', 6000
    );

    // Reset form and go to active panel
    document.getElementById('t-title').value = '';
    document.getElementById('t-desc').value  = '';
    setTimeout(() => showPanel('active'), 1200);
  } catch(err) {
    errEl.textContent   = err.message;
    errEl.style.display = 'block';
  } finally {
    btn.disabled = false;
    btn.textContent = '🚀 Post Task & Auto-Match Volunteers';
  }
}

// ── Active Tasks ──────────────────────────────────────────────
async function loadActive() {
  const el = document.getElementById('active-list');
  el.innerHTML = '<div class="loader"><div class="spinner"></div></div>';
  try {
    const data = await api.getActiveRequests();
    if (!data.tasks?.length) {
      el.innerHTML = '<div class="empty-state"><div class="icon">📋</div><p>No active tasks. Post a need to get started.</p></div>';
      return;
    }
    el.innerHTML = data.tasks.map(renderActiveTask).join('');
  } catch(e) {
    el.innerHTML = `<p style="color:var(--red);padding:20px;">${e.message}</p>`;
  }
}

function renderActiveTask(t) {
  const assigned = t.assigned_volunteers?.length || 0;
  const needed   = t.volunteers_needed || 1;
  const pred     = t.prediction || {};
  const volCards = (t.volunteer_details || []).map(v => `
    <div style="display:flex;align-items:center;gap:8px;padding:6px 0;border-top:1px solid var(--border);">
      <div class="vol-avatar" style="width:32px;height:32px;font-size:0.8rem;">${initials(v.name)}</div>
      <div style="flex:1;">
        <div style="font-size:0.85rem;font-weight:600;">${v.name}</div>
        <div style="font-size:0.75rem;color:var(--text-muted);">Trust: ${v.trust_score}/100</div>
      </div>
      <button class="btn btn-sm btn-secondary" onclick="openReviewModal('${v._id}','${t._id}')">⭐ Review</button>
    </div>
  `).join('');

  return `
    <div class="card fade-in" style="border-left:3px solid ${urgencyColor(t.urgency)};">
      <div style="display:flex;justify-content:space-between;align-items:flex-start;flex-wrap:wrap;gap:10px;margin-bottom:14px;">
        <div>
          <div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:8px;">
            ${urgencyBadge(t.urgency)} ${statusBadge(t.status)}
            ${pred.risk_level ? `<span class="risk-${pred.risk_level}" style="font-size:0.8rem;font-weight:700;">${riskIcon(pred.risk_level)} ${pred.risk_level.replace('_',' ')}</span>` : ''}
          </div>
          <div style="font-size:1.05rem;font-weight:700;">${t.title}</div>
        </div>
        <div style="display:flex;gap:8px;flex-wrap:wrap;">
          <button class="btn btn-secondary btn-sm" onclick="openNGOTaskModal('${t._id}')">Manage →</button>
          <button class="btn btn-secondary btn-sm" onclick="changeUrgencyPrompt('${t._id}','${t.urgency}')">⚡ Change Urgency</button>
        </div>
      </div>

      <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin-bottom:14px;">
        <div class="score-bar">
          <div class="score-lbl">Volunteers</div>
          <div style="font-weight:700;font-size:1.1rem;">${assigned}/${needed}</div>
          <div class="progress-bar mt-1"><div class="progress-fill" style="width:${Math.min(100,(assigned/needed)*100)}%"></div></div>
        </div>
        <div class="score-bar">
          <div class="score-lbl">Deadline</div>
          <div style="font-weight:600;">${formatDate(t.deadline)}</div>
        </div>
        <div class="score-bar">
          <div class="score-lbl">Risk Score</div>
          <div style="font-weight:700;font-size:1.1rem;color:${riskColor(pred.risk_level)};">${pred.risk_score ?? '—'}</div>
        </div>
      </div>

      ${pred.recommendations?.length ? `
        <div style="background:var(--surface);border-radius:var(--radius-sm);padding:10px 14px;font-size:0.82rem;color:var(--text-muted);margin-bottom:14px;">
          <strong>💡 Recommendation:</strong> ${pred.recommendations[0]}
        </div>` : ''}

      ${volCards ? `
        <div>
          <div style="font-size:0.72rem;font-weight:700;text-transform:uppercase;letter-spacing:0.1em;color:var(--text-dim);margin-bottom:8px;">Assigned Volunteers</div>
          ${volCards}
        </div>` : ''}

      <div style="display:flex;gap:8px;margin-top:14px;flex-wrap:wrap;">
        <button class="btn btn-cyan btn-sm" onclick="openApplicantsModal('${t._id}')">👥 View Applicants</button>
        <button class="btn btn-secondary btn-sm" onclick="openAISuggestionsModal('${t._id}')">🤖 AI Match</button>
        <a href="/map.html?task=${t._id}" class="btn btn-secondary btn-sm">📍 Map</a>
      </div>
    </div>
  `;
}

function urgencyColor(u) {
  return u === 'urgent' ? 'var(--red)' : u === 'med' ? 'var(--yellow)' : 'var(--green)';
}
function riskColor(r) {
  return r === 'on_track' ? 'var(--green)' : r === 'at_risk' ? 'var(--yellow)' : 'var(--red)';
}

// ── Change Urgency ────────────────────────────────────────────
async function changeUrgencyPrompt(taskId, current) {
  const opts  = ['low','med','urgent'].filter(u => u !== current);
  const choice = prompt(`Current urgency: ${current}\nChange to (type: low / med / urgent):`);
  if (!choice || !['low','med','urgent'].includes(choice.trim())) return;
  try {
    await api.changeUrgency(taskId, choice.trim());
    showToast(`Urgency changed to ${choice.trim()}. WhatsApp alerts sent if escalated.`, 'success');
    loadActive();
  } catch(e) {
    showToast(e.message, 'error');
  }
}

// ── Completed Tasks ───────────────────────────────────────────
async function loadCompleted() {
  const tbody = document.getElementById('completed-tbody');
  try {
    const data = await api.getCompletedRequests();
    if (!data.tasks?.length) {
      tbody.innerHTML = '<tr><td colspan="5"><div class="empty-state"><div class="icon">✅</div><p>No completed tasks yet.</p></div></td></tr>';
      return;
    }
    tbody.innerHTML = data.tasks.map(t => `
      <tr>
        <td><strong>${t.title}</strong></td>
        <td><span class="badge badge-open">${t.task_type}</span></td>
        <td>${formatDate(t.completed_at)}</td>
        <td>${(t.assigned_volunteers?.length||0)} volunteer(s)</td>
        <td>
          <button class="btn btn-secondary btn-sm" onclick="openNGOTaskModal('${t._id}')">View</button>
        </td>
      </tr>
    `).join('');
  } catch(e) {
    tbody.innerHTML = `<tr><td colspan="5" style="color:var(--red);padding:20px;">${e.message}</td></tr>`;
  }
}

// ── Community Reports Queue ────────────────────────────────────
async function loadReports() {
  const el = document.getElementById('reports-list');
  el.innerHTML = '<div class="loader"><div class="spinner"></div></div>';
  try {
    const data = await api.json('/ngo/reports'); // Fixed api.json wrapper
    if (!data.reports?.length) {
      el.innerHTML = '<div class="empty-state"><div class="icon">📭</div><p>No pending reports in your area.</p></div>';
      return;
    }
    el.innerHTML = data.reports.map(r => `
      <div class="report-card">
        <div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:10px;flex-wrap:wrap;gap:8px;">
          <div>
            <span class="badge badge-${r.urgency_self_reported || 'low'}">${(r.urgency_self_reported||'low').toUpperCase()}</span>
            <span class="badge badge-open" style="margin-left:6px;">${r.problem_type}</span>
          </div>
          <span style="font-size:0.78rem;color:var(--text-muted);">${timeAgo(r.created_at)}</span>
        </div>
        <p style="font-size:0.9rem;margin-bottom:10px;">${r.description}</p>
        <div style="font-size:0.8rem;color:var(--text-muted);margin-bottom:14px;">
          📍 ${r.address || `${r.lat?.toFixed(4)}, ${r.lng?.toFixed(4)}`} &nbsp;·&nbsp;
          👤 ${r.reporter_name} (${r.reporter_contact})
        </div>
        <div style="display:flex;gap:8px;flex-wrap:wrap;">
          <button class="btn btn-primary btn-sm" onclick="reviewReport('${r._id}','convert_to_task')">➕ Convert to Task</button>
          <button class="btn btn-secondary btn-sm" onclick="reviewReport('${r._id}','approve')">✅ Approve</button>
          <button class="btn btn-danger btn-sm" onclick="reviewReport('${r._id}','reject')">✕ Reject</button>
          <a href="/map.html?lat=${r.lat}&lng=${r.lng}" class="btn btn-secondary btn-sm">📍 Map</a>
        </div>
      </div>
    `).join('');
  } catch(e) {
    el.innerHTML = `<div class="empty-state"><p>${e.message}</p></div>`;
  }
}

async function reviewReport(reportId, action) {
  let note = '';
  let deadline = '';
  if (action === 'reject') {
    note = prompt('Reason for rejection (optional):') || '';
  }
  if (action === 'convert_to_task') {
    deadline = prompt('Deadline for the task (YYYY-MM-DDTHH:MM):', new Date(Date.now()+7*86400000).toISOString().slice(0,16));
    if (!deadline) return;
  }
  try {
    await api.reviewReport(reportId, action, note, deadline);
    showToast(`Report ${action.replace('_',' ')}d successfully!`, 'success');
    loadReports();
  } catch(e) {
    showToast(e.message, 'error');
  }
}

// ── Resources ─────────────────────────────────────────────────
async function loadResources() {
  const el = document.getElementById('resources-list');
  el.innerHTML = '<div class="loader"><div class="spinner"></div></div>';
  try {
    const data = await api.json('/ngo/resources');
    if (!data.resources?.length) {
      el.innerHTML = '<div class="empty-state"><div class="icon">📦</div><p>No resources added yet. Click "+ Add Resource" to start tracking.</p></div>';
      return;
    }
    el.innerHTML = data.resources.map(r => {
      const pct = Math.min(100, r.quantity > 0 ? 100 : 0);
      const statusColor = r.status === 'available' ? 'var(--green)' : r.status === 'depleted' ? 'var(--red)' : 'var(--yellow)';
      return `
        <div class="resource-bar">
          <div>
            <div style="font-weight:600;">${r.name}</div>
            <div style="font-size:0.78rem;color:var(--text-muted);">${r.category} · ${r.notes || ''}</div>
          </div>
          <div style="text-align:center;">
            <div style="font-family:var(--font-display);font-size:1.4rem;">${r.quantity} <span style="font-size:0.85rem;font-weight:400;">${r.unit}</span></div>
            <div style="font-size:0.72rem;color:${statusColor};font-weight:700;text-transform:uppercase;">${r.status}</div>
          </div>
          <button class="btn btn-secondary btn-sm" onclick="allocateResource('${r._id}','${r.name}',${r.quantity})">Allocate</button>
        </div>
      `;
    }).join('');
  } catch(e) {
    el.innerHTML = `<p style="color:var(--red);padding:20px;">${e.message}</p>`;
  }
}

async function addResource(e) {
  e.preventDefault();
  try {
    await api.json('/ngo/resources', {
      method: 'POST',
      body: JSON.stringify({
        name:     document.getElementById('r-name').value,
        category: document.getElementById('r-cat').value,
        quantity: parseFloat(document.getElementById('r-qty').value),
        unit:     document.getElementById('r-unit').value,
      })
    });
    showToast('Resource added!', 'success');
    document.getElementById('add-resource-modal').style.display = 'none';
    loadResources();
  } catch(err) {
    showToast(err.message, 'error');
  }
}

async function allocateResource(resourceId, name, maxQty) {
  const taskId = prompt(`Allocate "${name}" to which Task ID?`);
  if (!taskId) return;
  const amount = parseFloat(prompt(`How much to allocate? (Max: ${maxQty})`));
  if (isNaN(amount) || amount <= 0) return;
  try {
    await api.json(`/ngo/resources/${resourceId}/allocate`, {
      method:'POST', body:JSON.stringify({task_id:taskId, amount})
    });
    showToast(`Allocated ${amount} units to task.`, 'success');
    loadResources();
  } catch(err) {
    showToast(err.message, 'error');
  }
}

// ── Analytics ─────────────────────────────────────────────────
async function loadAnalytics() {
  const el = document.getElementById('analytics-content');
  el.innerHTML = '<div class="loader"><div class="spinner"></div></div>';
  try {
    const data = await api.getNGOAnalytics();

    const posted    = data.total_tasks_posted    || 0;
    const completed = data.total_tasks_completed || 0;
    const rate      = posted > 0 ? Math.round(completed/posted*100) : 0;

    const typeRows = (data.tasks_by_type || []).map(t => {
      const pct = posted > 0 ? Math.round(t.count/posted*100) : 0;
      return `
        <div class="chart-bar-row">
          <div class="chart-bar-label">${t.task_type}</div>
          <div class="chart-bar-track"><div class="chart-bar-fill" style="width:${pct}%"></div></div>
          <div class="chart-bar-val">${t.count}</div>
        </div>
      `;
    }).join('');

    const topVols = (data.top_volunteers || []).map((v, i) => `
      <div style="display:flex;align-items:center;gap:12px;padding:8px 0;border-bottom:1px solid var(--border);">
        <div style="font-family:var(--font-display);font-size:1rem;color:var(--text-dim);width:24px;">${i+1}</div>
        <div class="vol-avatar" style="width:34px;height:34px;font-size:0.8rem;">${initials(v.name)}</div>
        <div style="flex:1;">
          <div style="font-weight:600;font-size:0.9rem;">${v.name}</div>
          <div style="font-size:0.75rem;color:var(--text-muted);">${v.total_tasks_done} tasks done</div>
        </div>
        <div style="font-family:var(--font-display);color:var(--orange);">${v.trust_score}</div>
      </div>
    `).join('');

    el.innerHTML = `
      <div class="grid-2 gap-6 mb-6">
        <div class="stat-card" style="--accent:var(--orange)">
          <div class="stat-value">${posted}</div>
          <div class="stat-label">Total Tasks Posted</div>
        </div>
        <div class="stat-card" style="--accent:var(--green)">
          <div class="stat-value" style="color:var(--green);">${completed}</div>
          <div class="stat-label">Tasks Completed</div>
        </div>
        <div class="stat-card" style="--accent:var(--cyan)">
          <div class="stat-value" style="color:var(--cyan);">${data.active_volunteers || 0}</div>
          <div class="stat-label">Active Volunteers</div>
        </div>
        <div class="stat-card" style="--accent:var(--yellow)">
          <div class="stat-value" style="color:var(--yellow);">${rate}%</div>
          <div class="stat-label">Completion Rate</div>
          <div class="progress-bar mt-2"><div class="progress-fill" style="width:${rate}%"></div></div>
        </div>
      </div>

      <div class="grid-2 gap-6">
        <div class="card">
          <div class="card-header"><span class="card-title">Tasks by Type</span></div>
          <div style="display:flex;flex-direction:column;gap:10px;">
            ${typeRows || '<p style="color:var(--text-muted);font-size:0.85rem;">No data yet</p>'}
          </div>
        </div>
        <div class="card">
          <div class="card-header"><span class="card-title">🏆 Top Volunteers</span></div>
          ${topVols || '<p style="color:var(--text-muted);font-size:0.85rem;">No volunteers yet</p>'}
        </div>
      </div>
    `;
  } catch(e) {
    el.innerHTML = `<div class="empty-state"><p>${e.message}</p></div>`;
  }
}

// ── Inefficiency Reports ──────────────────────────────────────
async function loadInefficiency() {
  const el = document.getElementById('inefficiency-list');
  el.innerHTML = '<div class="loader"><div class="spinner"></div></div>';
  try {
    const data = await api.json('/ngo/inefficiency-reports');
    const logs = data.inefficiency_reports || [];
    if (!logs.length) {
      el.innerHTML = '<div class="empty-state"><div class="icon">✅</div><p>No inefficiency flags. Travel routes look optimal!</p></div>';
      return;
    }
    el.innerHTML = `
      <div class="card">
        <div class="table-wrap">
          <table>
            <thead><tr><th>Task</th><th>Volunteer</th><th>Actual km</th><th>Optimal km</th><th>Excess km</th></tr></thead>
            <tbody>
              ${logs.map(l => `
                <tr>
                  <td>${l.task_id}</td>
                  <td>${l.volunteer_id}</td>
                  <td>${l.actual_distance_km?.toFixed(1)}</td>
                  <td>${l.optimal_distance_km?.toFixed(1)}</td>
                  <td style="color:var(--red);font-weight:700;">+${l.excess_km?.toFixed(1)}</td>
                </tr>
              `).join('')}
            </tbody>
          </table>
        </div>
      </div>
    `;
  } catch(e) {
    el.innerHTML = `<div class="empty-state"><p>${e.message}</p></div>`;
  }
}

// ── NGO Task Detail Modal ──────────────────────────────────────
async function openNGOTaskModal(taskId) {
  document.getElementById('ngo-task-modal').style.display = 'flex';
  document.getElementById('ngo-modal-title').textContent  = 'Loading…';
  document.getElementById('ngo-modal-body').innerHTML     = '<div class="loader"><div class="spinner"></div></div>';

  try {
    const [taskData, prediction] = await Promise.all([
      api.json(`/tasks/${taskId}`),
      api.predictTask(taskId),
    ]);
    const t    = taskData.task;
    const pred = prediction;

    document.getElementById('ngo-modal-title').textContent = t.title;
    document.getElementById('ngo-modal-body').innerHTML = `
      <div style="display:flex;flex-direction:column;gap:16px;">
        <div style="display:flex;gap:8px;flex-wrap:wrap;">
          ${urgencyBadge(t.urgency)} ${statusBadge(t.status)}
          <span class="risk-${pred.risk_level}" style="font-size:0.8rem;font-weight:700;">
            ${riskIcon(pred.risk_level)} ${pred.risk_level?.replace('_',' ').toUpperCase()} (score: ${pred.risk_score}/100)
          </span>
        </div>

        <p style="font-size:0.9rem;color:var(--text-muted);">${t.description}</p>

        <div style="background:var(--surface);border-radius:var(--radius-sm);padding:12px 16px;">
          <div style="font-size:0.75rem;font-weight:700;color:var(--text-dim);text-transform:uppercase;margin-bottom:8px;">Predictor Analysis</div>
          <div style="font-size:0.85rem;margin-bottom:6px;">${pred.summary}</div>
          ${(pred.reasons||[]).map(r=>`<div style="font-size:0.8rem;color:var(--text-muted);">• ${r}</div>`).join('')}
        </div>

        <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;">
          <div class="score-bar"><div class="score-lbl">Deadline</div><div style="font-weight:600;">${formatDate(t.deadline)}</div></div>
          <div class="score-bar"><div class="score-lbl">Days Left</div><div style="font-weight:700;font-size:1.1rem;">${pred.days_remaining}</div></div>
          <div class="score-bar"><div class="score-lbl">Assigned</div><div style="font-weight:700;">${(t.assigned_volunteers?.length||0)} / ${t.volunteers_needed}</div></div>
          <div class="score-bar"><div class="score-lbl">Address</div><div style="font-weight:600;font-size:0.85rem;">${t.address||'—'}</div></div>
        </div>

        ${t.proof_of_work?.length ? `
          <div>
            <div style="font-size:0.75rem;font-weight:700;color:var(--text-dim);text-transform:uppercase;margin-bottom:8px;">Proof of Work</div>
            ${t.proof_of_work.map(p => `
              <div style="background:var(--surface);border-radius:var(--radius-sm);padding:10px 14px;display:flex;align-items:center;justify-content:space-between;margin-bottom:6px;">
                <div>
                  <div style="font-size:0.85rem;font-weight:600;">Volunteer: ${p.volunteer_id}</div>
                  <div style="font-size:0.78rem;color:var(--text-muted);">${p.notes || 'No notes'}</div>
                  <a href="${p.file_url}" target="_blank" style="font-size:0.78rem;color:var(--cyan);">View File ↗</a>
                </div>
                ${p.approved === null ? `
                  <div style="display:flex;gap:6px;">
                    <button class="btn btn-sm" style="background:var(--green);color:#fff;" onclick="reviewProof('${taskId}','${p.volunteer_id}',true)">✓ Approve</button>
                    <button class="btn btn-danger btn-sm" onclick="reviewProof('${taskId}','${p.volunteer_id}',false)">✕ Reject</button>
                  </div>` : `<span style="color:${p.approved?'var(--green)':'var(--red)'};">${p.approved?'✅ Approved':'✕ Rejected'}</span>`}
              </div>
            `).join('')}
          </div>
        ` : ''}

        <div style="display:flex;gap:8px;flex-wrap:wrap;">
          <button class="btn btn-primary btn-sm" onclick="openApplicantsModal('${t._id}')">👥 Manage Volunteers</button>
          <button class="btn btn-secondary btn-sm" onclick="openAISuggestionsModal('${t._id}')">🤖 AI Suggestions</button>
          <button class="btn btn-secondary btn-sm" onclick="changeUrgencyPrompt('${t._id}','${t.urgency}')">⚡ Change Urgency</button>
          ${t.status !== 'completed' && t.status !== 'cancelled' ? `
            <button class="btn btn-secondary btn-sm" onclick="markComplete('${t._id}')">✅ Mark Complete</button>
          ` : ''}
        </div>
      </div>
    `;
  } catch(err) {
    document.getElementById('ngo-modal-body').innerHTML = `<p style="color:var(--red);">${err.message}</p>`;
  }
}

async function reviewProof(taskId, volId, approved) {
  const notes = approved ? '' : (prompt('Reason for rejection:') || '');
  try {
    await api.json(`/ngo/tasks/${taskId}/proof/${volId}/review`, {
      method:'POST', body: JSON.stringify({ approved, notes })
    });
    showToast(approved ? 'Proof approved! Task marked complete.' : 'Proof rejected.', approved ? 'success' : 'warning');
    openNGOTaskModal(taskId);
    if (approved) loadActive();
  } catch(e) {
    showToast(e.message, 'error');
  }
}

async function markComplete(taskId) {
  if (!confirm('Mark this task as complete?')) return;
  try {
    await api.json(`/tasks/${taskId}/complete`, { method:'POST' });
    showToast('Task marked complete!', 'success');
    document.getElementById('ngo-task-modal').style.display = 'none';
    loadActive();
  } catch(e) {
    showToast(e.message, 'error');
  }
}

// ── Applicants Modal ──────────────────────────────────────────
async function openApplicantsModal(taskId) {
  document.getElementById('ngo-task-modal').style.display = 'flex';
  document.getElementById('ngo-modal-title').textContent  = 'Applicants & Assignment';
  document.getElementById('ngo-modal-body').innerHTML     = '<div class="loader"><div class="spinner"></div></div>';

  try {
    const data = await api.getTaskApplicants(taskId);
    const applicants = data.applicants || [];

    if (!applicants.length) {
      document.getElementById('ngo-modal-body').innerHTML =
        '<div class="empty-state"><div class="icon">👥</div><p>No applicants yet. Use AI suggestions below.</p></div>' +
        `<button class="btn btn-primary mt-4" onclick="openAISuggestionsModal('${taskId}')">🤖 AI Suggestions</button>`;
      return;
    }

    document.getElementById('ngo-modal-body').innerHTML = `
      <div style="display:flex;flex-direction:column;gap:12px;">
        ${applicants.map(a => {
          const v = a.volunteer || {};
          return `
            <div class="applicant-card">
              <div class="vol-avatar">${initials(v.name)}</div>
              <div style="flex:1;">
                <div style="font-weight:700;">${v.name || '—'}</div>
                <div style="font-size:0.78rem;color:var(--text-muted);">
                  Trust: ${v.trust_score || 0}/100 ·
                  ${v.verified_badge ? '✅ Verified · ' : ''}
                  Skills: ${v.skills?.join(', ') || 'none'} ·
                  Applied: ${timeAgo(a.applied_at)}
                </div>
              </div>
              <div style="display:flex;gap:6px;">
                ${a.status === 'pending' ? `
                  <button class="btn btn-primary btn-sm" onclick="assignVolunteer('${taskId}','${v._id}',this)">Assign</button>
                ` : `<span class="badge badge-${a.status}">${a.status}</span>`}
              </div>
            </div>
          `;
        }).join('')}
      </div>
    `;
  } catch(e) {
    document.getElementById('ngo-modal-body').innerHTML = `<p style="color:var(--red);">${e.message}</p>`;
  }
}

async function assignVolunteer(taskId, volId, btn) {
  btn.disabled = true; btn.textContent = 'Assigning…';
  try {
    await api.assignVolunteer(taskId, volId);
    showToast('Volunteer assigned! WhatsApp notification sent.', 'success');
    openApplicantsModal(taskId);
    loadActive();
  } catch(e) {
    showToast(e.message, 'error');
    btn.disabled = false; btn.textContent = 'Assign';
  }
}

// ── AI Suggestions Modal ──────────────────────────────────────
async function openAISuggestionsModal(taskId) {
  document.getElementById('ngo-task-modal').style.display = 'flex';
  document.getElementById('ngo-modal-title').textContent  = '🤖 AI-Matched Volunteers';
  document.getElementById('ngo-modal-body').innerHTML     = '<div class="loader"><div class="spinner"></div></div>';

  try {
    const data = await api.getNGOAiSuggestions(taskId);
    const suggestions = data.suggestions || [];

    if (!suggestions.length) {
      document.getElementById('ngo-modal-body').innerHTML =
        '<div class="empty-state"><div class="icon">🤖</div><p>No volunteers found nearby for this task. Try expanding the radius or post without required skills.</p></div>';
      return;
    }

    document.getElementById('ngo-modal-body').innerHTML = `
      <p style="font-size:0.85rem;color:var(--text-muted);margin-bottom:16px;">
        Ranked by proximity, skill match, trust score, and availability.
      </p>
      <div style="display:flex;flex-direction:column;gap:10px;">
        ${suggestions.map((s, i) => `
          <div class="volunteer-card">
            <div style="font-family:var(--font-display);font-size:1.2rem;color:var(--text-dim);width:28px;">${i+1}</div>
            <div class="vol-avatar">${initials(s.name)}</div>
            <div class="vol-info">
              <div class="vol-name">${s.name} ${s.verified_badge ? '✅' : ''}</div>
              <div class="vol-meta">
                📍 ${s.distance_km} km away ·
                Trust ${s.trust_score}/100 ·
                Match ${s.score_pct}%
              </div>
              <div style="margin-top:4px;">
                <div class="progress-bar" style="width:120px;display:inline-block;">
                  <div class="progress-fill" style="width:${s.score_pct}%;background:var(--cyan);"></div>
                </div>
              </div>
            </div>
            <button class="btn btn-primary btn-sm" onclick="assignVolunteer('${taskId}','${s.volunteer_id}',this)">Assign</button>
          </div>
        `).join('')}
      </div>
    `;
  } catch(e) {
    document.getElementById('ngo-modal-body').innerHTML = `<p style="color:var(--red);">${e.message}</p>`;
  }
}

// ── Review Modal ──────────────────────────────────────────────
function openReviewModal(volId, taskId) {
  selectedRating = 0;
  document.getElementById('rv-vol-id').value  = volId;
  document.getElementById('rv-task-id').value = taskId;
  document.getElementById('rv-comment').value = '';
  document.querySelectorAll('.star').forEach(s => { s.textContent='☆'; s.style.color='var(--text-dim)'; });
  document.getElementById('review-modal').style.display = 'flex';
}

async function submitReview(e) {
  e.preventDefault();
  const volId  = document.getElementById('rv-vol-id').value;
  const taskId = document.getElementById('rv-task-id').value;
  const rating = parseInt(document.getElementById('rv-rating').value);
  if (!rating) { showToast('Please select a star rating', 'error'); return; }

  try {
    await api.json(`/ngo/volunteers/${volId}/review`, {
      method:'POST',
      body: JSON.stringify({
        rating,
        comment: document.getElementById('rv-comment').value,
        task_id: taskId,
      })
    });
    showToast('Review submitted! Volunteer trust score updated.', 'success');
    document.getElementById('review-modal').style.display = 'none';
  } catch(err) {
    showToast(err.message, 'error');
  }
}

// ── Init ──────────────────────────────────────────────────────
loadOverview();