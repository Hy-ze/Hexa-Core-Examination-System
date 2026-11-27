/* Core helpers: API, formatting, toast, modal, router. */
const App = { user: null, views: {} };
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const fmtDT = iso => iso ? new Date(iso).toLocaleString([], { dateStyle: 'medium', timeStyle: 'short' }) : '–';
const toLocalInput = iso => { const d = new Date(iso); d.setMinutes(d.getMinutes() - d.getTimezoneOffset()); return d.toISOString().slice(0, 16); };
const fromLocalInput = v => new Date(v).toISOString();
const num = n => (Math.round(Number(n) * 100) / 100).toString();
const TYPE_LABEL = { mcq: 'Single answer', multi: 'Multiple select', written: 'Written' };
const STATUS_LABEL = { draft: 'Draft', published: 'Published', ongoing: 'Ongoing', completed: 'Completed' };
const badge = (cls, text) => `<span class="badge b-${cls}">${esc(text)}</span>`;

class ApiError extends Error { constructor(msg, status) { super(msg); this.status = status; } }

function detailText(d) {
  if (!d) return '';
  if (typeof d.detail === 'string') return d.detail;
  if (Array.isArray(d.detail)) return d.detail.map(e => `${(e.loc || []).slice(1).join(' › ')}: ${e.msg}`).join('. ');
  return '';
}

async function api(path, { method = 'GET', body } = {}) {
  let res;
  try {
    res = await fetch(path, {
      method, credentials: 'same-origin',
      headers: body ? { 'Content-Type': 'application/json' } : {},
      body: body ? JSON.stringify(body) : undefined,
    });
  } catch (e) {
    throw new ApiError('Cannot reach the server. Check your connection and try again.', 0);
  }
  let data = null;
  try { data = await res.json(); } catch (e) { /* no body */ }
  if (!res.ok) {
    if (res.status === 401 && App.user && !path.includes('/auth/login')) {
      App.user = null; App.showLogin('Your session ended. Please sign in again.');
    }
    throw new ApiError(detailText(data) || `Request failed (${res.status}).`, res.status);
  }
  return data;
}

function toast(msg, isErr = false) {
  const t = document.createElement('div');
  t.className = 'toast' + (isErr ? ' err' : '');
  t.textContent = msg;
  $('#toasts').appendChild(t);
  setTimeout(() => t.remove(), isErr ? 7000 : 3500);
}
const fail = e => toast(e.message || 'Something went wrong.', true);

/* ---------- modal ---------- */
let _lastFocus = null;
function openModal({ title, body, wide = false, footer = '' }) {
  closeModal();
  _lastFocus = document.activeElement;
  const root = $('#modal-root');
  root.innerHTML = `<div class="overlay" data-overlay>
    <div class="dialog ${wide ? 'wide' : ''}" role="dialog" aria-modal="true" aria-labelledby="dlg-title">
      <div class="dialog-head"><h2 id="dlg-title">${esc(title)}</h2><button class="x" type="button" aria-label="Close" data-close>&times;</button></div>
      <div class="dialog-body">${body}</div>
      ${footer ? `<div class="dialog-foot">${footer}</div>` : ''}
    </div></div>`;
  const dlg = $('.dialog', root);
  const first = $('input:not([type=hidden]),select,textarea,button:not(.x)', dlg);
  (first || $('.x', dlg)).focus();
  return dlg;
}
function closeModal() {
  $('#modal-root').innerHTML = '';
  if (_lastFocus && document.contains(_lastFocus)) _lastFocus.focus();
  _lastFocus = null;
}
document.addEventListener('click', e => {
  if (e.target.closest('[data-close]') || e.target.matches('[data-overlay]')) closeModal();
});
document.addEventListener('keydown', e => {
  if (e.key === 'Escape' && $('.dialog')) closeModal();
  if (e.key === 'Tab' && $('.dialog')) {            // keep focus inside the dialog
    const f = $$('button,input,select,textarea,a[href]', $('.dialog')).filter(x => !x.disabled && x.offsetParent !== null);
    if (!f.length) return;
    const first = f[0], last = f[f.length - 1];
    if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
    else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
  }
});

function confirmBox(message, label = 'Confirm', danger = false) {
  return new Promise(resolve => {
    const dlg = openModal({
      title: 'Please confirm', body: `<p>${esc(message)}</p>`,
      footer: `<button class="btn" data-no>Cancel</button><button class="btn ${danger ? 'danger' : 'primary'}" data-yes>${esc(label)}</button>`
    });
    $('[data-yes]', dlg).onclick = () => { closeModal(); resolve(true); };
    $('[data-no]', dlg).onclick = () => { closeModal(); resolve(false); };
  });
}

/* Run an async action on a button without allowing double clicks. */
async function busy(btn, fn) {
  if (btn.disabled) return;
  btn.disabled = true;
  try { return await fn(); } catch (e) { fail(e); } finally { btn.disabled = false; }
}

/* ---------- view helpers ---------- */
const setView = html => { $('#view').innerHTML = html; $('#view').focus?.(); };
const loadingView = () => setView('<p class="muted">Loading…</p>');
const pageHead = (title, sub = '', actions = '') =>
  `<div class="page-head"><div><h1>${esc(title)}</h1>${sub ? `<p class="muted">${sub}</p>` : ''}</div><div class="actions">${actions}</div></div>`;
const empty = (title, text) => `<div class="empty"><h3>${esc(title)}</h3><p>${text}</p></div>`;

/* ---------- router ---------- */
const NAV = {
  admin: [['#/users', 'Users'], ['#/exams', 'Exams'], ['#/imports', 'Bulk imports'], ['#/analytics', 'Analytics'], ['#/grading', 'Grading']],
  examiner: [['#/exams', 'Exams'], ['#/questions', 'Question bank'], ['#/imports', 'Bulk imports'], ['#/analytics', 'Analytics'], ['#/grading', 'Grading']],
  candidate: [['#/my-exams', 'My exams'], ['#/results', 'My results']],
};
const HOME = { admin: '#/users', examiner: '#/exams', candidate: '#/my-exams' };

async function route() {
  if (!App.user) return;
  const hash = location.hash || HOME[App.user.role];
  const parts = hash.replace(/^#\//, '').split('/');
  const base = parts[0];
  clearInterval(App.monTimer);
  if (base === 'exam') {                       // the exam room is full screen, outside the normal shell
    App.stopRoom?.();
    try { await App.views.exam(parts.slice(1)); } catch (e) { $('#root').innerHTML = `<div class="room-msg"><div class="banner bad">${esc(e.message)}</div></div>`; }
    return;
  }
  if (App.inRoom) { App.stopRoom(); showShell(); return; }   // leaving the room: bring the shell back
  const allowed = NAV[App.user.role].map(n => n[0].slice(2));
  if (!allowed.includes(base)) { location.hash = HOME[App.user.role]; return; }
  $$('.nav a').forEach(a => a.removeAttribute('aria-current'));
  const link = $(`.nav a[href="#/${base}"]`); if (link) link.setAttribute('aria-current', 'page');
  const view = App.views[base];
  loadingView();
  try { await view(parts.slice(1)); } catch (e) { setView(`<div class="banner bad">${esc(e.message)}</div>`); }
}
window.addEventListener('hashchange', route);

/* ---------- shell ---------- */
function showShell() {
  const u = App.user;
  $('#root').innerHTML = `<div class="app">
    <aside class="rail">
      <div class="brand"><span class="brand-mark" aria-hidden="true"></span>ExamDesk</div>
      <nav class="nav" aria-label="Main">${NAV[u.role].map(([h, l]) => `<a href="${h}">${l}</a>`).join('')}</nav>
      <div class="who"><div><strong>${esc(u.full_name)}</strong><span class="muted small">${esc(u.role)}</span></div>
        <button class="linkbtn" id="chpw" type="button">Change password</button>
        <button class="linkbtn" id="logout" type="button">Sign out</button></div>
    </aside>
    <main id="view" tabindex="-1"></main></div>`;
  $('#logout').onclick = async () => { try { await api('/api/auth/logout', { method: 'POST' }); } catch (e) { } App.user = null; App.showLogin(); };
  $('#chpw').onclick = changePassword;
  route();
}

function changePassword() {
  const dlg = openModal({
    title: 'Change password',
    body: `<form id="pwf"><div class="field"><label for="p1">Current password</label><input id="p1" type="password" required autocomplete="current-password"></div>
      <div class="field"><label for="p2">New password</label><input id="p2" type="password" minlength="8" required autocomplete="new-password"><span class="hint">At least 8 characters.</span></div></form>`,
    footer: `<button class="btn" data-close>Cancel</button><button class="btn primary" id="pwsave">Save password</button>`
  });
  $('#pwsave', dlg).onclick = e => busy(e.target, async () => {
    const f = $('#pwf', dlg); if (!f.reportValidity()) return;
    await api('/api/auth/change-password', { method: 'POST', body: { current_password: $('#p1').value, new_password: $('#p2').value } });
    closeModal(); toast('Password changed.');
  });
}
