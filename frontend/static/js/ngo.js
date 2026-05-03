/**
 * static/js/ngo.js
 *
 * FIXES:
 *  B6 — initPostTaskMap() guards against missing Google Maps API.
 *  B7 — postTask() resets ALL form fields after a successful post.
 *  B8 — changeUrgencyPrompt() dead `opts` variable removed.
 *  S2 — Every user-supplied value inserted via innerHTML is wrapped in
 *        escHtml() so task titles, descriptions, volunteer names, NGO names,
 *        problem descriptions, reporter names, and comments cannot inject
 *        JavaScript into the NGO's browser.
 */

if (!Auth.requireType('ngo')) throw new Error('Not authenticated');

document.getElementById('nav-name').textContent = Auth.getUserName() || 'NGO';

let currentPanel   = 'overview';
let selectedRating = 0;
let postTaskMap    = null;
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
    overview:     loadOverview,
    'post-task':  initPostTaskMap,
    active:       loadActive,
    completed:    loadCompleted,
    reports:      loadReports,
    resources:    loadResources,
    analytics:    loadAnalytics,
    inefficiency: loadInefficiency,
  };
  if (loaders[name]) loaders[name]();
}

// ── B6 FIX: Guard against missing Google Maps ─────────────────
function initPostTaskMap() {
  if (typeof google === 'undefined' || !google.maps) {
    showToast('Google Maps unavailable. Location picker disabled.', 'error');
    return;
  }
  if (postTaskMap) { google.maps.event.trigger(postTaskMap, 'resize'); return; }

  const darkMapStyle = [
    { elementType: "geometry", stylers: [{ color: "#242f3e" }] },
    { elementType: "labels.text.stroke", stylers: [{ color: "#242f3e" }] },
    { elementType: "labels.text.fill", stylers: [{ color: "#746855" }] },
    { featureType: "road", elementType: "geometry", stylers: [{ color: "#38414e" }] },
    { featureType: "water", elementType: "geometry", stylers: [{ color: "#17263c" }] },
  ];

  postTaskMap = new google.maps.Map(document.getElementById('task-picker-map'), {
    center: { lat: 20.5937, lng: 78.9629 }, zoom: 5,
    styles: darkMapStyle, disableDefaultUI: true, zoomControl: true,
  });

  function updateCoords(lat, lng) {
    document.getElementById('t-lat').value = lat;
    document.getElementById('t-lng').value = lng;
    if (postTaskMarker) {
      postTaskMarker.setPosition({ lat, lng });
    } else {
      postTaskMarker = new google.maps.Marker({
        position: { lat, lng }, map: postTaskMap, draggable: true,
        animation: google.maps.Animation.DROP,
      });
      postTaskMarker.addListener('dragend', () => {
        const pos = postTaskMarker.getPosition();
        updateCoords(pos.lat(), pos.lng());
      });
    }
  }

  if ("geolocation" in navigator) {
    navigator.geolocation.getCurrentPosition(pos => {
      postTaskMap.setCenter({ lat: pos.coords.latitude, lng: pos.coords.longitude });
      postTaskMap.setZoom(15);
      updateCoords(pos.coords.latitude, pos.coords.longitude);
    });
  }
  postTaskMap.addListener('click', e => updateCoords(e.latLng.lat(), e.latLng.lng()));
  setTimeout(() => google.maps.event.trigger(postTaskMap, 'resize'), 300);
}

// ── Skill tag toggle ──────────────────────────────────────────
function toggleSkill(el) {
  const on = el.classList.toggle('selected');
  el.style.background  = on ? 'var(--orange-glow)' : '';
  el.style.borderColor = on ? 'var(--orange)'      : 'var(--border)';
  el.style.color       = on ? 'var(--orange)'      : 'var(--text-muted)';
}
document.querySelectorAll('.skill-tag2').forEach(tag => {
  tag.style.cssText = `padding:4px 12px;border-radius:100px;border:1px solid var(--border);
    font-size:0.8rem;cursor:pointer;color:var(--text-muted);transition:all 150ms;user-select:none;`;
  tag.addEventListener('click', () => toggleSkill(tag));
});
function getSelectedSkills() {
  return [...document.querySelectorAll('.skill-tag2.selected')].map(t => t.dataset.s);
}

// ── Star rating ───────────────────────────────────────────────
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
    // S2: textContent for plain strings
    document.getElementById('ngo-title').textContent    = (profile.name || '—') + ' — Dashboard';
    document.getElementById('ngo-subtitle').textContent =
      `${(profile.focus_areas || []).join(' · ')} · Reg: ${profile.registration_number || '—'}`;
    document.getElementById('ov-posted').textContent     = profile.total_tasks_posted    || 0;
    document.getElementById('ov-completed').textContent  = profile.total_tasks_completed || 0;
    document.getElementById('ov-volunteers').textContent = profile.active_volunteers     || 0;

    await loadUrgencyBoard();

    const active  = await api.getActiveRequests();
    document.getElementById('ov-urgent').textContent =
      (active.tasks || []).filter(t => t.urgency === 'urgent').length;

    const reports = await api.json('/ngo/reports');
    if ((reports.reports || []).length > 0) {
      const badge = document.getElementById('reports-count');
      if (badge) badge.style.display = 'inline-block';
    }
  } catch (e) { showToast('Failed to load overview: ' + e.message, 'error'); }
}

// ── Urgency Board ─────────────────────────────────────────────
async function loadUrgencyBoard() {
  const board = document.getElementById('urgency-board');
  board.innerHTML = spinnerHTML();
  try {
    const res  = await api.json('/tasks/urgency-board');
    const data = res.urgency_board || { urgent: [], med: [], low: [] };
    board.innerHTML = `
      <div class="urgency-col urgent">
        <div class="urgency-col-header">🔴 Urgent <span>${escHtml(String(data.urgent.length))}</span></div>
        <div id="ub-urgent">${renderMiniTasks(data.urgent)}</div>
      </div>
      <div class="urgency-col med">
        <div class="urgency-col-header">🟡 Medium <span>${escHtml(String(data.med.length))}</span></div>
        <div id="ub-med">${renderMiniTasks(data.med)}</div>
      </div>
      <div class="urgency-col low">
        <div class="urgency-col-header">🟢 Low <span>${escHtml(String(data.low.length))}</span></div>
        <div id="ub-low">${renderMiniTasks(data.low)}</div>
      </div>
    `;
  } catch (e) {
    board.innerHTML = `<p style="color:var(--text-muted);padding:20px;">${escHtml(e.message)}</p>`;
  }
}

function renderMiniTasks(tasks) {
  if (!tasks.length) return '<p style="font-size:0.8rem;color:var(--text-dim);padding:8px 0;">No tasks</p>';
  return tasks.map(t => `
    <div class="mini-task" onclick="openNGOTaskModal('${escHtml(t._id)}')">
      <div class="mini-task-title">${escHtml(t.title)}</div>
      <div class="mini-task-meta">
        <span>👥 ${escHtml(String(t.assigned_volunteers?.length || 0))}/${escHtml(String(t.volunteers_needed || 1))}</span>
        <span>⏰ ${escHtml(formatDate(t.deadline))}</span>
        ${t.prediction?.risk_level ? `<span>${riskIcon(t.prediction.risk_level)} ${escHtml(t.prediction.risk_level.replace('_', ' '))}</span>` : ''}
      </div>
    </div>
  `).join('');
}

function riskIcon(r) {
  return r === 'on_track' ? '✅' : r === 'at_risk' ? '⚠️' : '🚨';
}
function urgencyColor(u) {
  return u === 'urgent' ? 'var(--red)' : u === 'med' ? 'var(--yellow)' : 'var(--green)';
}
function riskColor(r) {
  return r === 'on_track' ? 'var(--green)' : r === 'at_risk' ? 'var(--yellow)' : 'var(--red)';
}

// ── Post Task ─────────────────────────────────────────────────
async function postTask(e) {
  e.preventDefault();
  const btn   = document.getElementById('post-btn');
  const errEl = document.getElementById('post-error');
  errEl.style.display = 'none';

  const latVal = document.getElementById('t-lat').value;
  const lngVal = document.getElementById('t-lng').value;
  if (!latVal || !lngVal) {
    errEl.textContent = 'Please set the exact location on the map.';
    errEl.style.display = 'block'; return;
  }

  btn.disabled = true; btn.textContent = 'Posting & matching…';

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
      lat:               parseFloat(latVal),
      lng:               parseFloat(lngVal),
    };

    const data = await api.postTask(payload);
    showToast(`Task posted! ${data.auto_matched_volunteers} volunteers auto-matched & notified.`, 'success', 6000);

    // B7 FIX: Reset ALL fields — type, urgency, deadline, volunteers were
    // previously left with stale values from the last post.
    document.getElementById('t-title').value      = '';
    document.getElementById('t-desc').value       = '';
    document.getElementById('t-address').value    = '';
    document.getElementById('t-pincode').value    = '';
    document.getElementById('t-type').selectedIndex    = 0;
    document.getElementById('t-urgency').selectedIndex = 0;
    document.getElementById('t-deadline').value   = '';
    document.getElementById('t-volunteers').value = '1';
    document.getElementById('t-lat').value        = '';
    document.getElementById('t-lng').value        = '';
    document.querySelectorAll('.skill-tag2.selected').forEach(el => toggleSkill(el));
    if (postTaskMarker) { postTaskMarker.setMap(null); postTaskMarker = null; }

    setTimeout(() => showPanel('active'), 1200);
  } catch (err) {
    errEl.textContent   = err.message;
    errEl.style.display = 'block';
  } finally {
    btn.disabled = false; btn.textContent = '🚀 Post Task & Auto-Match Volunteers';
  }
}

// ── Active Tasks ──────────────────────────────────────────────
async function loadActive() {
  const el = document.getElementById('active-list');
  el.innerHTML = spinnerHTML();
  try {
    const data = await api.getActiveRequests();
    if (!data.tasks?.length) {
      el.innerHTML = '<div class="empty-state"><div class="icon">📋</div><p>No active tasks.</p></div>'; return;
    }
    el.innerHTML = data.tasks.map(renderActiveTask).join('');
  } catch (e) { el.innerHTML = `<p style="color:var(--red);padding:20px;">${escHtml(e.message)}</p>`; }
}

function renderActiveTask(t) {
  const assigned = t.assigned_volunteers?.length || 0;
  const needed   = t.volunteers_needed || 1;
  const pred     = t.prediction || {};

  // S2: volunteer names and task fields escaped
  const volCards = (t.volunteer_details || []).map(v => `
    <div style="display:flex;align-items:center;gap:8px;padding:6px 0;border-top:1px solid var(--border);">
      <div class="vol-avatar" style="width:32px;height:32px;font-size:0.8rem;">${escHtml(initials(v.name))}</div>
      <div style="flex:1;">
        <div style="font-size:0.85rem;font-weight:600;">${escHtml(v.name || '—')}</div>
        <div style="font-size:0.75rem;color:var(--text-muted);">Trust: ${escHtml(String(v.trust_score ?? '?'))}/100</div>
      </div>
      <button class="btn btn-sm btn-secondary" onclick="openReviewModal('${escHtml(v._id)}','${escHtml(t._id)}')">⭐ Review</button>
    </div>
  `).join('');

  return `
    <div class="card fade-in" style="border-left:3px solid ${urgencyColor(t.urgency)};">
      <div style="display:flex;justify-content:space-between;align-items:flex-start;flex-wrap:wrap;gap:10px;margin-bottom:14px;">
        <div>
          <div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:8px;">
            ${urgencyBadge(t.urgency)} ${statusBadge(t.status)}
            ${pred.risk_level ? `<span style="font-size:0.8rem;font-weight:700;color:${riskColor(pred.risk_level)};">${riskIcon(pred.risk_level)} ${escHtml(pred.risk_level.replace('_', ' '))}</span>` : ''}
          </div>
          <div style="font-size:1.05rem;font-weight:700;">${escHtml(t.title)}</div>
        </div>
        <div style="display:flex;gap:8px;flex-wrap:wrap;">
          <button class="btn btn-secondary btn-sm" onclick="openNGOTaskModal('${escHtml(t._id)}')">Manage →</button>
          <button class="btn btn-secondary btn-sm" onclick="changeUrgencyPrompt('${escHtml(t._id)}','${escHtml(t.urgency)}')">⚡ Change Urgency</button>
        </div>
      </div>
      <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin-bottom:14px;">
        <div class="score-bar">
          <div class="score-lbl">Volunteers</div>
          <div style="font-weight:700;font-size:1.1rem;">${escHtml(String(assigned))}/${escHtml(String(needed))}</div>
          <div class="progress-bar mt-1"><div class="progress-fill" style="width:${Math.min(100,(assigned/needed)*100)}%"></div></div>
        </div>
        <div class="score-bar"><div class="score-lbl">Deadline</div><div style="font-weight:600;">${escHtml(formatDate(t.deadline))}</div></div>
        <div class="score-bar">
          <div class="score-lbl">Risk Score</div>
          <div style="font-weight:700;font-size:1.1rem;color:${riskColor(pred.risk_level)};">${escHtml(String(pred.risk_score ?? '—'))}</div>
        </div>
      </div>
      ${volCards ? `<div>${volCards}</div>` : ''}
      <div style="display:flex;gap:8px;margin-top:14px;flex-wrap:wrap;">
        <button class="btn btn-cyan btn-sm" onclick="openApplicantsModal('${escHtml(t._id)}')">👥 Applicants</button>
        <button class="btn btn-secondary btn-sm" onclick="openAISuggestionsModal('${escHtml(t._id)}')">🤖 AI Match</button>
        <a href="/map.html?task=${encodeURIComponent(t._id)}" class="btn btn-secondary btn-sm">📍 Map</a>
      </div>
    </div>
  `;
}

// B8 FIX: dead `opts` variable removed. Validates input directly.
async function changeUrgencyPrompt(taskId, current) {
  const choice = prompt(`Current urgency: ${current}\nChange to (type: low / med / urgent):`);
  if (!choice || !['low', 'med', 'urgent'].includes(choice.trim())) return;
  try {
    await api.changeUrgency(taskId, choice.trim());
    showToast(`Urgency changed to ${choice.trim()}.`, 'success');
    loadActive();
  } catch (e) { showToast(e.message, 'error'); }
}

// ── Completed Tasks ───────────────────────────────────────────
async function loadCompleted() {
  const tbody = document.getElementById('completed-tbody');
  try {
    const data = await api.getCompletedRequests();
    if (!data.tasks?.length) {
      tbody.innerHTML = '<tr><td colspan="5"><div class="empty-state"><div class="icon">✅</div><p>No completed tasks yet.</p></div></td></tr>'; return;
    }
    tbody.innerHTML = data.tasks.map(t => `
      <tr>
        <td><strong>${escHtml(t.title)}</strong></td>
        <td><span class="badge badge-open">${escHtml(t.task_type || '—')}</span></td>
        <td>${escHtml(formatDate(t.completed_at))}</td>
        <td>${escHtml(String(t.assigned_volunteers?.length || 0))} volunteer(s)</td>
        <td><button class="btn btn-secondary btn-sm" onclick="openNGOTaskModal('${escHtml(t._id)}')">View</button></td>
      </tr>
    `).join('');
  } catch (e) {
    tbody.innerHTML = `<tr><td colspan="5" style="color:var(--red);padding:20px;">${escHtml(e.message)}</td></tr>`;
  }
}

// ── Reports ───────────────────────────────────────────────────
async function loadReports() {
  const el = document.getElementById('reports-list');
  el.innerHTML = spinnerHTML();
  try {
    const data = await api.json('/ngo/reports');
    if (!data.reports?.length) {
      el.innerHTML = '<div class="empty-state"><div class="icon">📭</div><p>No pending reports.</p></div>'; return;
    }
    el.innerHTML = data.reports.map(r => `
      <div class="report-card">
        <div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:10px;flex-wrap:wrap;gap:8px;">
          <div>
            <span class="badge badge-${escHtml(r.urgency_self_reported || 'low')}">${escHtml((r.urgency_self_reported || 'low').toUpperCase())}</span>
            <span class="badge badge-open" style="margin-left:6px;">${escHtml(r.problem_type || '—')}</span>
          </div>
          <span style="font-size:0.78rem;color:var(--text-muted);">${escHtml(timeAgo(r.created_at))}</span>
        </div>
        <p style="font-size:0.9rem;margin-bottom:10px;">${escHtml(r.description || '')}</p>
        <div style="font-size:0.8rem;color:var(--text-muted);margin-bottom:14px;">
          📍 ${escHtml(r.address || `${r.lat?.toFixed(4) ?? '?'}, ${r.lng?.toFixed(4) ?? '?'}`)} &nbsp;·&nbsp;
          👤 ${escHtml(r.reporter_name || '—')}
          ${r.reporter_contact ? ` · 📞 ${escHtml(r.reporter_contact)}` : ''}
        </div>
        <div style="display:flex;gap:8px;flex-wrap:wrap;">
          <button class="btn btn-primary btn-sm" onclick="reviewReport('${escHtml(r._id)}','convert_to_task')">➕ Convert to Task</button>
          <button class="btn btn-secondary btn-sm" onclick="reviewReport('${escHtml(r._id)}','approve')">✅ Approve</button>
          <button class="btn btn-danger btn-sm" onclick="reviewReport('${escHtml(r._id)}','reject')">✕ Reject</button>
        </div>
      </div>
    `).join('');
  } catch (e) { el.innerHTML = `<div class="empty-state"><p>${escHtml(e.message)}</p></div>`; }
}

async function reviewReport(reportId, action) {
  let note = '', deadline = '';
  if (action === 'reject') note = prompt('Reason for rejection (optional):') || '';
  if (action === 'convert_to_task') {
    deadline = prompt('Deadline for the task (YYYY-MM-DDTHH:MM):',
      new Date(Date.now() + 7 * 86400000).toISOString().slice(0, 16));
    if (!deadline) return;
  }
  try {
    await api.reviewReport(reportId, action, note, deadline);
    showToast(`Report ${action.replace('_', ' ')}d successfully!`, 'success');
    loadReports();
  } catch (e) { showToast(e.message, 'error'); }
}

// ── Resources ─────────────────────────────────────────────────
async function loadResources() {
  const el = document.getElementById('resources-list');
  el.innerHTML = spinnerHTML();
  try {
    const data = await api.json('/ngo/resources');
    if (!data.resources?.length) {
      el.innerHTML = '<div class="empty-state"><div class="icon">📦</div><p>No resources added yet.</p></div>'; return;
    }
    el.innerHTML = data.resources.map(r => {
      const statusColor = r.status === 'available' ? 'var(--green)' : r.status === 'depleted' ? 'var(--red)' : 'var(--yellow)';
      return `
        <div class="resource-bar">
          <div>
            <div style="font-weight:600;">${escHtml(r.name)}</div>
            <div style="font-size:0.78rem;color:var(--text-muted);">${escHtml(r.category)} · ${escHtml(r.notes || '')}</div>
          </div>
          <div style="text-align:center;">
            <div style="font-family:var(--font-display);font-size:1.4rem;">${escHtml(String(r.quantity))} <span style="font-size:0.85rem;font-weight:400;">${escHtml(r.unit)}</span></div>
            <div style="font-size:0.72rem;color:${statusColor};font-weight:700;text-transform:uppercase;">${escHtml(r.status)}</div>
          </div>
          <button class="btn btn-secondary btn-sm" onclick="allocateResource('${escHtml(r._id)}','${escHtml(r.name)}',${Number(r.quantity)})">Allocate</button>
        </div>
      `;
    }).join('');
  } catch (e) { el.innerHTML = `<p style="color:var(--red);padding:20px;">${escHtml(e.message)}</p>`; }
}

async function addResource(e) {
  e.preventDefault();
  try {
    await api.json('/ngo/resources', {
      method: 'POST', body: JSON.stringify({
        name:     document.getElementById('r-name').value,
        category: document.getElementById('r-cat').value,
        quantity: parseFloat(document.getElementById('r-qty').value),
        unit:     document.getElementById('r-unit').value,
      })
    });
    showToast('Resource added!', 'success');
    document.getElementById('add-resource-modal').style.display = 'none';
    loadResources();
  } catch (err) { showToast(err.message, 'error'); }
}

async function allocateResource(resourceId, name, maxQty) {
  const taskId = prompt(`Allocate "${name}" to which Task ID?`);
  if (!taskId) return;
  const amount = parseFloat(prompt(`How much to allocate? (Max: ${maxQty})`));
  if (isNaN(amount) || amount <= 0) return;
  try {
    await api.json(`/ngo/resources/${encodeURIComponent(resourceId)}/allocate`, {
      method: 'POST', body: JSON.stringify({ task_id: taskId, amount })
    });
    showToast(`Allocated ${amount} units.`, 'success');
    loadResources();
  } catch (err) { showToast(err.message, 'error'); }
}

// ── Analytics ─────────────────────────────────────────────────
async function loadAnalytics() {
  const el = document.getElementById('analytics-content');
  el.innerHTML = spinnerHTML();
  try {
    const data      = await api.getNGOAnalytics();
    const posted    = data.total_tasks_posted    || 0;
    const completed = data.total_tasks_completed || 0;
    const rate      = posted > 0 ? Math.round(completed / posted * 100) : 0;

    const typeRows = (data.tasks_by_type || []).map(t => {
      const pct = posted > 0 ? Math.round(t.count / posted * 100) : 0;
      return `
        <div class="chart-bar-row">
          <div class="chart-bar-label">${escHtml(t.task_type || '—')}</div>
          <div class="chart-bar-track"><div class="chart-bar-fill" style="width:${pct}%"></div></div>
          <div class="chart-bar-val">${escHtml(String(t.count))}</div>
        </div>`;
    }).join('');

    const topVols = (data.top_volunteers || []).map((v, i) => `
      <div style="display:flex;align-items:center;gap:12px;padding:8px 0;border-bottom:1px solid var(--border);">
        <div style="font-family:var(--font-display);font-size:1rem;color:var(--text-dim);width:24px;">${i + 1}</div>
        <div class="vol-avatar" style="width:34px;height:34px;font-size:0.8rem;">${escHtml(initials(v.name))}</div>
        <div style="flex:1;">
          <div style="font-weight:600;font-size:0.9rem;">${escHtml(v.name || '—')}</div>
          <div style="font-size:0.75rem;color:var(--text-muted);">${escHtml(String(v.total_tasks_done || 0))} tasks done</div>
        </div>
        <div style="font-family:var(--font-display);color:var(--orange);">${escHtml(String(v.trust_score || 0))}</div>
      </div>`).join('');

    el.innerHTML = `
      <div class="grid-2 gap-6 mb-6">
        <div class="stat-card" style="--accent:var(--orange)"><div class="stat-value">${escHtml(String(posted))}</div><div class="stat-label">Total Posted</div></div>
        <div class="stat-card" style="--accent:var(--green)"><div class="stat-value" style="color:var(--green);">${escHtml(String(completed))}</div><div class="stat-label">Completed</div></div>
        <div class="stat-card" style="--accent:var(--cyan)"><div class="stat-value" style="color:var(--cyan);">${escHtml(String(data.active_volunteers || 0))}</div><div class="stat-label">Active Volunteers</div></div>
        <div class="stat-card" style="--accent:var(--yellow)"><div class="stat-value" style="color:var(--yellow);">${escHtml(String(rate))}%</div><div class="stat-label">Completion Rate</div>
          <div class="progress-bar mt-2"><div class="progress-fill" style="width:${rate}%"></div></div>
        </div>
      </div>
      <div class="grid-2 gap-6">
        <div class="card">
          <div class="card-header"><span class="card-title">Tasks by Type</span></div>
          <div style="display:flex;flex-direction:column;gap:10px;">${typeRows || '<p style="color:var(--text-muted);font-size:0.85rem;">No data yet</p>'}</div>
        </div>
        <div class="card">
          <div class="card-header"><span class="card-title">🏆 Top Volunteers</span></div>
          ${topVols || '<p style="color:var(--text-muted);font-size:0.85rem;">No volunteers yet</p>'}
        </div>
      </div>`;
  } catch (e) { el.innerHTML = `<div class="empty-state"><p>${escHtml(e.message)}</p></div>`; }
}

// ── Inefficiency ──────────────────────────────────────────────
async function loadInefficiency() {
  const el = document.getElementById('inefficiency-list');
  el.innerHTML = spinnerHTML();
  try {
    const data = await api.json('/ngo/inefficiency-reports');
    const logs = data.inefficiency_reports || [];
    if (!logs.length) {
      el.innerHTML = '<div class="empty-state"><div class="icon">✅</div><p>No inefficiency flags.</p></div>'; return;
    }
    el.innerHTML = `
      <div class="card"><div class="table-wrap"><table>
        <thead><tr><th>Task</th><th>Volunteer</th><th>Actual km</th><th>Optimal km</th><th>Excess km</th></tr></thead>
        <tbody>${logs.map(l => `
          <tr>
            <td>${escHtml(l.task_id || '—')}</td>
            <td>${escHtml(l.volunteer_id || '—')}</td>
            <td>${escHtml(String(l.actual_distance_km?.toFixed(1) ?? '?'))}</td>
            <td>${escHtml(String(l.optimal_distance_km?.toFixed(1) ?? '?'))}</td>
            <td style="color:var(--red);font-weight:700;">+${escHtml(String(l.excess_km?.toFixed(1) ?? '?'))}</td>
          </tr>`).join('')}
        </tbody>
      </table></div></div>`;
  } catch (e) { el.innerHTML = `<div class="empty-state"><p>${escHtml(e.message)}</p></div>`; }
}

// ── NGO Task Modal ────────────────────────────────────────────
async function openNGOTaskModal(taskId) {
  document.getElementById('ngo-task-modal').style.display = 'flex';
  document.getElementById('ngo-modal-title').textContent  = 'Loading…';
  document.getElementById('ngo-modal-body').innerHTML     = spinnerHTML();
  try {
    const [taskData, pred] = await Promise.all([api.json(`/tasks/${encodeURIComponent(taskId)}`), api.predictTask(taskId)]);
    const t = taskData.task;
    document.getElementById('ngo-modal-title').textContent = t.title;
    document.getElementById('ngo-modal-body').innerHTML = `
      <div style="display:flex;flex-direction:column;gap:16px;">
        <div style="display:flex;gap:8px;flex-wrap:wrap;">
          ${urgencyBadge(t.urgency)} ${statusBadge(t.status)}
          <span style="font-size:0.8rem;font-weight:700;color:${riskColor(pred.risk_level)};">
            ${riskIcon(pred.risk_level)} ${escHtml((pred.risk_level || '').replace('_', ' ').toUpperCase())} (${escHtml(String(pred.risk_score ?? '?'))}/100)
          </span>
        </div>
        <p style="font-size:0.9rem;color:var(--text-muted);">${escHtml(t.description || '')}</p>
        <div style="background:var(--surface);border-radius:var(--radius-sm);padding:12px 16px;">
          <div style="font-size:0.85rem;">${escHtml(pred.summary || '—')}</div>
        </div>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;">
          <div class="score-bar"><div class="score-lbl">Deadline</div><div>${escHtml(formatDate(t.deadline))}</div></div>
          <div class="score-bar"><div class="score-lbl">Assigned</div><div>${escHtml(String(t.assigned_volunteers?.length || 0))} / ${escHtml(String(t.volunteers_needed || 1))}</div></div>
        </div>
        ${t.proof_of_work?.length ? `
          <div>${t.proof_of_work.map(p => `
            <div style="background:var(--surface);border-radius:var(--radius-sm);padding:10px 14px;display:flex;align-items:center;justify-content:space-between;margin-bottom:6px;">
              <div>
                <div style="font-size:0.85rem;font-weight:600;">Volunteer: ${escHtml(p.volunteer_id)}</div>
                <div style="font-size:0.78rem;color:var(--text-muted);">${escHtml(p.notes || 'No notes')}</div>
                <a href="${encodeURI(p.file_url)}" target="_blank" rel="noopener noreferrer" style="font-size:0.78rem;color:var(--cyan);">View File ↗</a>
              </div>
              ${p.approved === null ? `
                <div style="display:flex;gap:6px;">
                  <button class="btn btn-sm" style="background:var(--green);color:#fff;" onclick="reviewProof('${escHtml(taskId)}','${escHtml(p.volunteer_id)}',true)">✓ Approve</button>
                  <button class="btn btn-danger btn-sm" onclick="reviewProof('${escHtml(taskId)}','${escHtml(p.volunteer_id)}',false)">✕ Reject</button>
                </div>` : `<span style="color:${p.approved ? 'var(--green)' : 'var(--red)'};">${p.approved ? '✅ Approved' : '✕ Rejected'}</span>`}
            </div>`).join('')}
          </div>` : ''}
        <div style="display:flex;gap:8px;flex-wrap:wrap;">
          <button class="btn btn-primary btn-sm" onclick="openApplicantsModal('${escHtml(taskId)}')">👥 Volunteers</button>
          <button class="btn btn-secondary btn-sm" onclick="openAISuggestionsModal('${escHtml(taskId)}')">🤖 AI Match</button>
          <button class="btn btn-secondary btn-sm" onclick="changeUrgencyPrompt('${escHtml(taskId)}','${escHtml(t.urgency)}')">⚡ Urgency</button>
          ${t.status !== 'completed' && t.status !== 'cancelled'
            ? `<button class="btn btn-secondary btn-sm" onclick="markComplete('${escHtml(taskId)}')">✅ Complete</button>` : ''}
        </div>
      </div>`;
  } catch (err) {
    document.getElementById('ngo-modal-body').innerHTML = `<p style="color:var(--red);">${escHtml(err.message)}</p>`;
  }
}

async function reviewProof(taskId, volId, approved) {
  const notes = approved ? '' : (prompt('Reason for rejection:') || '');
  try {
    await api.json(`/ngo/tasks/${encodeURIComponent(taskId)}/proof/${encodeURIComponent(volId)}/review`,
      { method: 'POST', body: JSON.stringify({ approved, notes }) });
    showToast(approved ? 'Proof approved!' : 'Proof rejected.', approved ? 'success' : 'warning');
    openNGOTaskModal(taskId);
  } catch (e) { showToast(e.message, 'error'); }
}

async function markComplete(taskId) {
  if (!confirm('Mark this task as complete?')) return;
  try {
    await api.json(`/tasks/${encodeURIComponent(taskId)}/complete`, { method: 'POST' });
    showToast('Task marked complete!', 'success');
    document.getElementById('ngo-task-modal').style.display = 'none';
    loadActive();
  } catch (e) { showToast(e.message, 'error'); }
}

// ── Applicants Modal ──────────────────────────────────────────
async function openApplicantsModal(taskId) {
  document.getElementById('ngo-task-modal').style.display = 'flex';
  document.getElementById('ngo-modal-title').textContent  = 'Applicants & Assignment';
  document.getElementById('ngo-modal-body').innerHTML     = spinnerHTML();
  try {
    const data       = await api.getTaskApplicants(taskId);
    const applicants = data.applicants || [];
    if (!applicants.length) {
      document.getElementById('ngo-modal-body').innerHTML =
        `<div class="empty-state"><div class="icon">👥</div><p>No applicants yet.</p></div>
         <button class="btn btn-primary mt-4" onclick="openAISuggestionsModal('${escHtml(taskId)}')">🤖 AI Suggestions</button>`;
      return;
    }
    document.getElementById('ngo-modal-body').innerHTML = `
      <div style="display:flex;flex-direction:column;gap:12px;">
        ${applicants.map(a => {
          const v = a.volunteer || {};
          return `
            <div class="applicant-card">
              <div class="vol-avatar">${escHtml(initials(v.name))}</div>
              <div style="flex:1;">
                <div style="font-weight:700;">${escHtml(v.name || '—')}</div>
                <div style="font-size:0.78rem;color:var(--text-muted);">
                  Trust: ${escHtml(String(v.trust_score || 0))}/100 ·
                  ${v.verified_badge ? '✅ Verified · ' : ''}
                  Skills: ${(v.skills || []).map(s => escHtml(s)).join(', ') || 'none'} ·
                  Applied: ${escHtml(timeAgo(a.applied_at))}
                </div>
              </div>
              ${a.status === 'pending'
                ? `<button class="btn btn-primary btn-sm" onclick="assignVolunteer('${escHtml(taskId)}','${escHtml(v._id)}',this)">Assign</button>`
                : `<span class="badge badge-${escHtml(a.status)}">${escHtml(a.status)}</span>`}
            </div>`;
        }).join('')}
      </div>`;
  } catch (e) {
    document.getElementById('ngo-modal-body').innerHTML = `<p style="color:var(--red);">${escHtml(e.message)}</p>`;
  }
}

async function assignVolunteer(taskId, volId, btn) {
  btn.disabled = true; btn.textContent = 'Assigning…';
  try {
    await api.assignVolunteer(taskId, volId);
    showToast('Volunteer assigned!', 'success');
    openApplicantsModal(taskId); loadActive();
  } catch (e) {
    showToast(e.message, 'error');
    btn.disabled = false; btn.textContent = 'Assign';
  }
}

// ── AI Suggestions Modal ──────────────────────────────────────
async function openAISuggestionsModal(taskId) {
  document.getElementById('ngo-task-modal').style.display = 'flex';
  document.getElementById('ngo-modal-title').textContent  = '🤖 AI-Matched Volunteers';
  document.getElementById('ngo-modal-body').innerHTML     = spinnerHTML();
  try {
    const data        = await api.getNGOAiSuggestions(taskId);
    const suggestions = data.suggestions || [];
    if (!suggestions.length) {
      document.getElementById('ngo-modal-body').innerHTML =
        '<div class="empty-state"><div class="icon">🤖</div><p>No volunteers found nearby.</p></div>'; return;
    }
    document.getElementById('ngo-modal-body').innerHTML = `
      <p style="font-size:0.85rem;color:var(--text-muted);margin-bottom:16px;">Ranked by proximity, skill, trust, availability.</p>
      <div style="display:flex;flex-direction:column;gap:10px;">
        ${suggestions.map((s, i) => `
          <div class="volunteer-card">
            <div style="font-family:var(--font-display);font-size:1.2rem;color:var(--text-dim);width:28px;">${i + 1}</div>
            <div class="vol-avatar">${escHtml(initials(s.name))}</div>
            <div class="vol-info">
              <div class="vol-name">${escHtml(s.name)} ${s.verified_badge ? '✅' : ''}</div>
              <div class="vol-meta">📍 ${escHtml(String(s.distance_km))} km · Trust ${escHtml(String(s.trust_score))}/100 · Match ${escHtml(String(s.score_pct))}%</div>
              <div class="progress-bar" style="width:120px;display:inline-block;margin-top:4px;">
                <div class="progress-fill" style="width:${escHtml(String(s.score_pct))}%;background:var(--cyan);"></div>
              </div>
            </div>
            <button class="btn btn-primary btn-sm" onclick="assignVolunteer('${escHtml(taskId)}','${escHtml(s.volunteer_id)}',this)">Assign</button>
          </div>`).join('')}
      </div>`;
  } catch (e) {
    document.getElementById('ngo-modal-body').innerHTML = `<p style="color:var(--red);">${escHtml(e.message)}</p>`;
  }
}

// ── Review Modal ──────────────────────────────────────────────
function openReviewModal(volId, taskId) {
  selectedRating = 0;
  document.getElementById('rv-vol-id').value  = volId;
  document.getElementById('rv-task-id').value = taskId;
  document.getElementById('rv-comment').value = '';
  document.querySelectorAll('.star').forEach(s => { s.textContent = '☆'; s.style.color = 'var(--text-dim)'; });
  document.getElementById('review-modal').style.display = 'flex';
}

async function submitReview(e) {
  e.preventDefault();
  const volId  = document.getElementById('rv-vol-id').value;
  const taskId = document.getElementById('rv-task-id').value;
  const rating = parseInt(document.getElementById('rv-rating').value);
  if (!rating) { showToast('Please select a star rating', 'error'); return; }
  try {
    await api.json(`/ngo/volunteers/${encodeURIComponent(volId)}/review`, {
      method: 'POST', body: JSON.stringify({ rating, comment: document.getElementById('rv-comment').value, task_id: taskId })
    });
    showToast('Review submitted!', 'success');
    document.getElementById('review-modal').style.display = 'none';
  } catch (err) { showToast(err.message, 'error'); }
}

// ── Init ──────────────────────────────────────────────────────
loadOverview();