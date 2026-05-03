/**
 * static/js/volunteer.js
 *
 * FIXES:
 *  B1  — Notification badge IIFE uses api.getMyNotifications() directly
 *         (parsed JSON), not api.get() treated as a Response object.
 *  S2  — Every user-supplied value inserted via innerHTML is wrapped in
 *         escHtml() so a malicious task title / description / name cannot
 *         inject and execute arbitrary JavaScript in the volunteer's browser.
 *  S5  — Auth.save() called with { id, type, name } only (no tokens).
 *         Tokens are now HttpOnly cookies set by the server.
 */

if (!Auth.requireType('volunteer')) throw new Error('Not authenticated');

document.getElementById('nav-name').textContent = Auth.getUserName() || 'Volunteer';

let currentPanel = 'overview';

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
    tasks:         loadTasks,
    suggestions:   loadSuggestions,
    history:       loadHistory,
    notifications: loadNotifications,
    profile:       loadProfile,
  };
  if (loaders[name]) loaders[name]();
}

// ── Overview ──────────────────────────────────────────────────
async function loadOverview() {
  try {
    let profile = {};
    let stats   = {};
    try { profile = await api.getVolunteerProfile(); } catch (_) {}
    try { stats   = await api.getVolunteerStats();   } catch (_) {}

    // S2: use textContent for plain text, escHtml for anything in innerHTML
    document.getElementById('avatar').textContent       = initials(profile.name);
    document.getElementById('profile-name').textContent = profile.name || '—';
    document.getElementById('profile-meta').innerHTML   = `
      <span>📱 ${escHtml(profile.phone || '—')}</span>
      <span>📍 ${escHtml(String(profile.lat?.toFixed(3) ?? '?'))}, ${escHtml(String(profile.lng?.toFixed(3) ?? '?'))}</span>
      ${profile.verified_badge ? '<span style="color:var(--orange)">✅ Verified</span>' : ''}
      <span>${(profile.skills || []).map(s => escHtml(s)).join(' · ') || 'No skills listed'}</span>
    `;

    document.getElementById('trust-val').textContent  = stats.trust_score ?? '—';
    document.getElementById('trust-bar').style.width  = (stats.trust_score ?? 0) + '%';
    document.getElementById('conf-val').textContent   = stats.confidence_score ?? '—';
    document.getElementById('stat-done').textContent   = stats.total_tasks_done   ?? '—';
    document.getElementById('stat-ontime').textContent = stats.tasks_on_time      ?? '—';
    document.getElementById('stat-rating').textContent = (stats.avg_rating?.toFixed(1) ?? '0.0') + '⭐';
    document.getElementById('stat-badge').textContent  = badgeLabel(stats);
  } catch (e) {
    showToast('Could not load profile: ' + e.message, 'error');
  }
  await loadUrgentPreview();
}

async function loadUrgentPreview() {
  const el = document.getElementById('urgent-preview');
  el.innerHTML = spinnerHTML();
  try {
    const data = await api.getAvailableTasks('?urgency=urgent&per_page=3');
    if (!data.tasks?.length) { showEmpty(el, '✅', 'No urgent tasks near you right now.'); return; }
    el.innerHTML = data.tasks.map(renderTaskCard).join('');
  } catch (e) { showError(el, e.message); }
}

// ── Tasks ─────────────────────────────────────────────────────
async function loadTasks() {
  const el = document.getElementById('tasks-list');
  el.innerHTML = spinnerHTML();

  const urgency = document.getElementById('filter-urgency')?.value || '';
  const type    = document.getElementById('filter-type')?.value    || '';
  const radius  = document.getElementById('filter-radius')?.value  || '10';

  let qs = `?radius_km=${encodeURIComponent(radius)}`;
  if (urgency) qs += `&urgency=${encodeURIComponent(urgency)}`;
  if (type)    qs += `&task_type=${encodeURIComponent(type)}`;

  try {
    const data = await api.getAvailableTasks(qs);
    if (!data.tasks?.length) { showEmpty(el, '📭', 'No tasks found. Try expanding the radius.'); return; }
    el.innerHTML = data.tasks.map(renderTaskCard).join('');
  } catch (e) { showError(el, e.message); }
}

// ── AI Suggestions ────────────────────────────────────────────
async function loadSuggestions() {
  const el = document.getElementById('suggestions-list');
  el.innerHTML = spinnerHTML();
  try {
    const data = await api.getAiSuggestions();
    if (!data.suggestions?.length) {
      showEmpty(el, '🤖', 'No suggestions yet. Update your location and skills in Profile.');
      return;
    }
    // S2: every field from the API is passed through escHtml
    el.innerHTML = data.suggestions.map(t => `
      <div class="task-card fade-in" data-urgency="${escHtml(t.urgency)}" onclick="openTaskModal('${escHtml(t._id)}')">
        <div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:10px;">
          <div>${urgencyBadge(t.urgency)}<div class="task-card-title mt-2">${escHtml(t.title)}</div></div>
          <div style="text-align:right;">
            <div style="font-family:var(--font-display);font-size:1.4rem;color:var(--cyan);">${escHtml(String(t.match_pct ?? '?'))}%</div>
            <div style="font-size:0.7rem;color:var(--text-muted);">match</div>
          </div>
        </div>
        <div class="task-card-meta">
          <span>📍 ${t.distance_km != null ? escHtml(String(t.distance_km)) : '?'} km away</span>
          <span>🏷️ ${escHtml(t.task_type || '—')}</span>
          <span>⏰ ${escHtml(formatDate(t.deadline))}</span>
          <span>👥 ${escHtml(String(t.assigned_volunteers?.length || 0))}/${escHtml(String(t.volunteers_needed || 1))} assigned</span>
        </div>
        <div class="task-card-actions">
          <button class="btn btn-sm apply-btn" onclick="event.stopPropagation();applyForTask('${escHtml(t._id)}',this)">Apply Now</button>
          <button class="btn btn-secondary btn-sm" onclick="event.stopPropagation();openTaskModal('${escHtml(t._id)}')">Details</button>
        </div>
      </div>
    `).join('');
  } catch (e) { showError(el, e.message); }
}

// ── History ───────────────────────────────────────────────────
async function loadHistory() {
  const tbody = document.getElementById('history-tbody');
  tbody.innerHTML = `<tr><td colspan="5">${spinnerHTML()}</td></tr>`;
  try {
    const data = await api.getTaskHistory();
    if (!data.tasks?.length) {
      tbody.innerHTML = '<tr><td colspan="5"><div class="empty-state"><div class="icon">📁</div><p>No completed tasks yet.</p></div></td></tr>';
      return;
    }
    // S2: escHtml on title, task_type, deadline, status, urgency
    tbody.innerHTML = data.tasks.map(t => `
      <tr>
        <td><strong>${escHtml(t.title)}</strong></td>
        <td><span class="badge badge-open">${escHtml(t.task_type || '—')}</span></td>
        <td>${escHtml(formatDate(t.deadline))}</td>
        <td>${statusBadge(t.status)}</td>
        <td>${urgencyBadge(t.urgency || 'low')}</td>
      </tr>
    `).join('');
  } catch (e) {
    tbody.innerHTML = `<tr><td colspan="5" style="color:var(--red);padding:20px;">${escHtml(e.message)}</td></tr>`;
  }
}

// ── Notifications ─────────────────────────────────────────────
async function loadNotifications() {
  const el = document.getElementById('notif-list');
  el.innerHTML = spinnerHTML();
  try {
    // B1 FIX: api.getMyNotifications() returns parsed JSON directly.
    const data = await api.getMyNotifications();
    document.getElementById('notif-count').style.display = 'none';

    if (!data.notifications?.length) { showEmpty(el, '🔔', 'No notifications yet.'); return; }

    // S2: escHtml on title, message (both are user-influenced API strings)
    el.innerHTML = data.notifications.map(n => `
      <div class="notif-item ${n.is_read ? '' : 'unread'}">
        <div class="notif-title">${escHtml(n.title)}</div>
        <div class="notif-msg">${escHtml(n.message)}</div>
        <div class="notif-time">${escHtml(timeAgo(n.created_at))}</div>
      </div>
    `).join('');
  } catch (e) { showError(el, e.message); }
}

// ── Profile ───────────────────────────────────────────────────
async function loadProfile() {
  try {
    const p = await api.getVolunteerProfile();
    document.getElementById('p-name').value       = p.name    || '';
    document.getElementById('p-phone').value      = p.phone   || '';
    document.getElementById('p-whatsapp').checked = p.whatsapp_opt_in !== false;

    // S2: scores are numbers — safe, but escHtml for belt-and-suspenders
    document.getElementById('reputation-detail').innerHTML = `
      <div style="display:flex;flex-direction:column;gap:12px;">
        <div class="score-bar">
          <div style="display:flex;justify-content:space-between;align-items:center;">
            <span class="score-lbl">Trust Score</span>
            <span style="font-family:var(--font-display);font-size:1.4rem;color:var(--orange);">${escHtml(String(p.trust_score ?? 50))}/100</span>
          </div>
          <div class="progress-bar mt-2"><div class="progress-fill" style="width:${escHtml(String(p.trust_score ?? 0))}%"></div></div>
        </div>
        <div class="score-bar">
          <div style="display:flex;justify-content:space-between;align-items:center;">
            <span class="score-lbl">Confidence Score</span>
            <span style="font-family:var(--font-display);font-size:1.4rem;color:var(--cyan);">${escHtml(String(p.confidence_score ?? 50))}/100</span>
          </div>
          <div class="progress-bar mt-2">
            <div style="height:100%;background:var(--cyan);width:${escHtml(String(p.confidence_score ?? 0))}%;border-radius:3px;transition:width 0.5s;"></div>
          </div>
        </div>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;">
          <div class="score-bar text-center">
            <div style="font-size:1.2rem;font-weight:700;color:var(--green);">${escHtml(String(p.total_tasks_done ?? 0))}</div>
            <div class="score-lbl">Completed</div>
          </div>
          <div class="score-bar text-center">
            <div style="font-size:1.2rem;font-weight:700;color:var(--yellow);">${escHtml(String(p.avg_rating?.toFixed(1) ?? '—'))}⭐</div>
            <div class="score-lbl">Avg Rating</div>
          </div>
        </div>
        ${p.verified_badge ? '<div style="text-align:center;padding:8px;background:var(--orange-glow);border-radius:var(--radius-sm);color:var(--orange);font-weight:700;">✅ Verified Volunteer Badge</div>' : ''}
      </div>
    `;
  } catch (e) { showToast('Failed to load profile: ' + e.message, 'error'); }
}

async function updateProfile(e) {
  e.preventDefault();
  try {
    await api.put('/volunteer/profile', {
      name:            document.getElementById('p-name').value,
      phone:           document.getElementById('p-phone').value,
      whatsapp_opt_in: document.getElementById('p-whatsapp').checked,
    });
    showToast('Profile updated!', 'success');
  } catch (err) { showToast('Update failed: ' + err.message, 'error'); }
}

// ── Task Card renderer ────────────────────────────────────────
// S2: all API-supplied fields escaped
function renderTaskCard(t) {
  const assigned = t.assigned_volunteers?.length || 0;
  const needed   = t.volunteers_needed || 1;
  const full     = assigned >= needed;
  return `
    <div class="task-card fade-in" data-urgency="${escHtml(t.urgency)}" onclick="openTaskModal('${escHtml(t._id)}')">
      <div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:10px;">
        <div>${urgencyBadge(t.urgency)} ${statusBadge(t.status)}</div>
        ${t.distance_km != null ? `<span style="font-size:0.8rem;color:var(--text-muted);">📍 ${escHtml(String(t.distance_km))} km</span>` : ''}
      </div>
      <div class="task-card-title">${escHtml(t.title)}</div>
      <p style="font-size:0.85rem;color:var(--text-muted);margin:8px 0;line-height:1.5;">${escHtml((t.description || '').slice(0, 100))}…</p>
      <div class="task-card-meta">
        <span>🏷️ ${escHtml(t.task_type || '—')}</span>
        <span>⏰ ${escHtml(formatDate(t.deadline))}</span>
        <span>👥 ${escHtml(String(assigned))}/${escHtml(String(needed))} volunteers</span>
        <span>📍 ${escHtml(t.address || 'See map')}</span>
      </div>
      <div class="task-card-actions">
        ${!full
          ? `<button class="btn btn-sm apply-btn" onclick="event.stopPropagation();applyForTask('${escHtml(t._id)}',this)">✋ Apply</button>`
          : '<span style="font-size:0.8rem;color:var(--text-muted);">Slots full</span>'
        }
        <button class="btn btn-secondary btn-sm" onclick="event.stopPropagation();openTaskModal('${escHtml(t._id)}')">Details →</button>
      </div>
    </div>
  `;
}

// ── Task Detail Modal ─────────────────────────────────────────
async function openTaskModal(taskId) {
  document.getElementById('task-modal').style.display = 'flex';
  document.getElementById('modal-task-title').textContent = 'Loading…';
  document.getElementById('modal-task-body').innerHTML    = spinnerHTML();

  try {
    const data = await api.json(`/tasks/${encodeURIComponent(taskId)}`);
    const t    = data.task;
    const pred = t.prediction || {};

    // S2: task title set via textContent (no innerHTML injection possible)
    document.getElementById('modal-task-title').textContent = t.title;

    document.getElementById('modal-task-body').innerHTML = `
      <div style="display:flex;flex-direction:column;gap:16px;">
        <div style="display:flex;gap:8px;flex-wrap:wrap;">
          ${urgencyBadge(t.urgency)} ${statusBadge(t.status)}
          ${pred.risk_level ? `<span style="font-size:0.8rem;font-weight:700;">
            ${pred.risk_level === 'on_track' ? '✅' : pred.risk_level === 'at_risk' ? '⚠️' : '🚨'}
            ${escHtml(pred.risk_level.replace('_', ' ').toUpperCase())}
          </span>` : ''}
        </div>
        <p style="color:var(--text-muted);font-size:0.9rem;line-height:1.7;">${escHtml(t.description || '')}</p>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;">
          <div class="score-bar"><div class="score-lbl">Type</div><div style="font-weight:600;">${escHtml(t.task_type || '—')}</div></div>
          <div class="score-bar"><div class="score-lbl">Deadline</div><div style="font-weight:600;">${escHtml(formatDate(t.deadline))}</div></div>
          <div class="score-bar"><div class="score-lbl">Volunteers</div><div style="font-weight:700;">${escHtml(String(t.assigned_volunteers?.length || 0))} / ${escHtml(String(t.volunteers_needed || 1))}</div></div>
          <div class="score-bar"><div class="score-lbl">Location</div><div style="font-weight:600;font-size:0.85rem;">${escHtml(t.address || `${t.lat?.toFixed(4)}, ${t.lng?.toFixed(4)}`)}</div></div>
        </div>
        ${t.required_skills?.length ? `
          <div>
            <div style="font-size:0.75rem;font-weight:600;color:var(--text-muted);text-transform:uppercase;letter-spacing:0.08em;margin-bottom:8px;">Required Skills</div>
            <div style="display:flex;gap:6px;flex-wrap:wrap;">
              ${t.required_skills.map(s => `<span class="badge badge-open">${escHtml(s)}</span>`).join('')}
            </div>
          </div>` : ''}
        ${pred.summary ? `
          <div style="background:var(--surface);border-radius:var(--radius-sm);padding:12px 16px;font-size:0.85rem;">
            <strong>⚡ Predictor:</strong> ${escHtml(pred.summary)}
          </div>` : ''}
        <div style="display:flex;gap:10px;flex-wrap:wrap;">
          <button class="btn btn-primary btn-sm" onclick="applyForTask('${escHtml(t._id)}',this)">✋ Apply for Task</button>
          <a href="/map.html?task=${encodeURIComponent(t._id)}" class="btn btn-secondary btn-sm">📍 View on Map</a>
          ${t.status === 'in_progress' ? `<button class="btn btn-cyan btn-sm" onclick="openProofModal('${escHtml(t._id)}')">📸 Upload Proof</button>` : ''}
        </div>
      </div>
    `;
  } catch (e) {
    document.getElementById('modal-task-body').innerHTML = `<p style="color:var(--red);">${escHtml(e.message)}</p>`;
  }
}

function closeModal() {
  document.getElementById('task-modal').style.display = 'none';
}

// ── Apply for Task ────────────────────────────────────────────
async function applyForTask(taskId, btn) {
  if (btn) { btn.disabled = true; btn.textContent = 'Applying…'; }
  try {
    await api.applyForTask(taskId);
    showToast('Application submitted! The NGO will review it.', 'success');
    closeModal();
    if (currentPanel === 'tasks')    loadTasks();
    if (currentPanel === 'overview') loadUrgentPreview();
  } catch (e) {
    showToast(e.message, 'error');
    if (btn) { btn.disabled = false; btn.textContent = '✋ Apply'; }
  }
}

// ── Proof of Work ─────────────────────────────────────────────
function openProofModal(taskId) {
  document.getElementById('proof-task-id').value = taskId;
  document.getElementById('proof-modal').style.display = 'flex';
  closeModal();
}

async function uploadProof(e) {
  e.preventDefault();
  const taskId = document.getElementById('proof-task-id').value;
  const file   = document.getElementById('proof-file').files[0];
  const notes  = document.getElementById('proof-notes').value;
  if (!file) { showToast('Please select a file', 'error'); return; }

  const fd = new FormData();
  fd.append('file', file);
  fd.append('notes', notes);
  try {
    await api.json(`/volunteer/tasks/${encodeURIComponent(taskId)}/proof`, { method: 'POST', body: fd });
    showToast('Proof uploaded! Awaiting NGO approval.', 'success');
    document.getElementById('proof-modal').style.display = 'none';
  } catch (err) { showToast('Upload failed: ' + err.message, 'error'); }
}

// ── Badge label ───────────────────────────────────────────────
function badgeLabel(stats) {
  const trust    = stats.trust_score || 50;
  const verified = stats.verified_badge;
  if (verified && trust >= 80) return '⭐ Champion';
  if (verified)                 return '✅ Verified';
  if (trust >= 80)              return '🏆 Top Vol';
  if (trust >= 60)              return '🌟 Trusted';
  return '🙂 Active';
}

// ── Init ──────────────────────────────────────────────────────
loadOverview();

// B1 FIX + S5: api.getMyNotifications() returns parsed JSON directly.
// No token read needed — HttpOnly cookie sent automatically.
(async () => {
  try {
    const data   = await api.getMyNotifications();
    const unread = (data.notifications || []).filter(n => !n.is_read).length;
    if (unread > 0) {
      const badge = document.getElementById('notif-count');
      if (badge) { badge.textContent = unread; badge.style.display = 'inline-block'; }
    }
  } catch (_) {}
})();