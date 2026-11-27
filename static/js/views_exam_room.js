/* Exam room: used by candidates, and by examiners for the sandbox preview.
   The server owns the clock: this file only displays the seconds-remaining it is told,
   counting down with performance.now() (a monotonic timer), never the device date/time. */
const KEYS = 'ABCDEFGH';
const hhmmss = s => {
  s = Math.max(0, Math.floor(s));
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), x = s % 60;
  return (h ? h + ':' + String(m).padStart(2, '0') : String(m).padStart(2, '0')) + ':' + String(x).padStart(2, '0');
};
const store = {
  get(k) { try { return JSON.parse(localStorage.getItem(k)); } catch (e) { return null; } },
  set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) { /* storage may be blocked */ } },
  del(k) { try { localStorage.removeItem(k); } catch (e) { } },
};

App.startExam = async function (examId, sandbox = false) {
  const r = await api('/api/attempts/start', { method: 'POST', body: { exam_id: examId, sandbox } });
  location.hash = '#/exam/' + r.attempt_id;
};

App.stopRoom = function () {
  if (App.room) { App.room.destroy(); App.room = null; }
  App.inRoom = false;
};

App.views.exam = async function (args) {
  const id = +args[0];
  App.inRoom = true;
  $('#root').innerHTML = '<div class="room-msg"><p class="muted">Opening your exam…</p></div>';
  if (!id) { location.hash = HOME[App.user.role]; return; }
  let st;
  try { st = await api('/api/attempts/' + id); }
  catch (e) {
    $('#root').innerHTML = `<div class="room-msg"><div class="banner bad" role="alert">${esc(e.message)}</div><a class="btn" href="#">Back</a></div>`;
    return;
  }
  if (st.status !== 'in_progress') return renderDone(st);
  let prefs = { theme: 'light', text_size: 'md', layout: 'palette-right', question_font: 'serif' };
  try { prefs = await api('/api/preferences'); } catch (e) { /* defaults are fine */ }
  App.room = new Room(st, prefs);
  App.room.mount();
};

function renderDone(st) {
  const expired = st.status === 'expired';
  const back = st.is_sandbox ? `<a class="btn primary" href="#/exams/${st.exam_id}">Back to exam setup</a>` : '<a class="btn primary" href="#/my-exams">Back to my exams</a>';
  $('#root').innerHTML = `<div class="room-msg"><div class="done-card">
    <div class="stamp ${expired ? 'late' : ''}" aria-hidden="true">${expired ? 'Time up' : 'Received'}</div>
    <h1>${st.is_sandbox ? 'Preview finished' : 'Your answers are in.'}</h1>
    <p>${esc(st.title)}</p>
    <p class="muted">${expired ? 'Time ran out, so the attempt was closed automatically using the answers that were saved before the deadline.' : 'Your attempt was submitted.'}
      Recorded at ${fmtDT(st.submitted_at)} (server time). You answered ${st.answered} of ${st.total_questions} questions.</p>
    ${st.is_sandbox ? `<p class="banner warn">Preview only. This attempt is not counted in any result or statistic.${st.preview_score != null ? ` Auto-graded score: ${num(st.preview_score)} of ${num(st.preview_max)} (written answers are not graded in a preview).` : ''}</p>`
      : '<p class="muted">Results appear under My exams once the examiner publishes them.</p>'}
    ${back}</div></div>`;
}

class Room {
  constructor(st, prefs) {
    this.st = st; this.id = st.attempt_id; this.prefs = prefs;
    this.qs = st.questions.map(q => ({ ...q, selected: [...q.selected] }));
    this.cur = 0;
    this.pending = new Map();
    this.inflight = false; this.retry = 0; this.dead = false;
    this.online = navigator.onLine !== false; this.offlineSince = null;
    this.total = st.total_seconds || 1;
    this.clock(st.remaining);
    this.lastAnn = st.announcements.reduce((m, a) => Math.max(m, a.id), 0);
    this.anns = st.announcements.slice(-2);
    this.eventQ = []; this.listeners = []; this.intervals = [];
    this.timeUp = false; this.submitting = false; this.said = new Set();
    this.padValue = st.scratchpad || ''; this.padDirty = false; this.padOpen = false;
    this.pKey = 'exam-pending-' + this.id; this.padKey = 'exam-pad-' + this.id;
    this.restoreLocal();
  }

  restoreLocal() {                      // work that never reached the server before a refresh/crash
    for (const it of store.get(this.pKey) || []) {
      const q = this.qs.find(x => x.id === it.aq_id);
      if (!q || it.version <= q.version) continue;
      Object.assign(q, { selected: it.selected, written: it.written, marked: it.marked, version: it.version });
      q.answered = q.type === 'written' ? !!q.written.trim() : q.selected.length > 0;
      this.pending.set(q.id, it);
    }
    const pad = store.get(this.padKey);
    if (pad != null && pad !== this.padValue) { this.padValue = pad; this.padDirty = true; }
  }

  clock(remaining) { this.rem = remaining; this.syncAt = performance.now(); }
  left() { return this.rem - (performance.now() - this.syncAt) / 1000; }

  /* ------------------------------------------------------------ render */
  mount() {
    const s = this.st, p = this.prefs;
    $('#root').innerHTML = `<div class="room" id="room">
      <a class="skip" href="#qpanel">Skip to question</a>
      <header class="room-bar">
        <div class="room-id"><strong class="room-title">${esc(s.title)}</strong>
          ${s.is_sandbox ? '<span class="badge b-published">Preview: not recorded</span>' : ''}</div>
        <div class="room-status"><span class="chip" id="netchip"></span><span class="chip" id="savechip"></span></div>
        <div class="clock" id="clock" role="timer" aria-label="Time remaining">--:--</div>
        <div class="room-tools">
          <button class="btn sm" id="bPrefs" type="button" aria-haspopup="dialog">View</button>
          <button class="btn sm" id="bPad" type="button" aria-pressed="false" aria-controls="pad">Scratchpad</button>
          <button class="btn primary" id="bSubmit" type="button">Review and submit</button>
        </div>
      </header>
      <div class="timebar" aria-hidden="true"><span id="timefill"></span></div>
      <div id="banners"></div>
      <div class="room-body" id="rbody">
        <main class="room-main" id="qpanel" aria-label="Question"></main>
        <nav class="palette" id="palette" aria-label="Question navigator"></nav>
        <aside class="pad" id="pad" hidden aria-label="Scratchpad for rough work">
          <div class="pad-head"><strong>Scratchpad</strong><span class="small muted" id="padstat"></span></div>
          <textarea id="padtext" spellcheck="false" aria-label="Rough work. Only you can see this." placeholder="Rough work goes here. Only you can see it."></textarea>
          <div class="pad-foot"><span class="small muted">Saved with your attempt. It is never graded.</span><button class="linkbtn" id="padclear" type="button">Clear</button></div>
        </aside>
      </div>
      <div class="sr" id="live" aria-live="polite"></div></div>`;
    $('#padtext').value = this.padValue;
    this.applyPrefs();
    this.renderQuestion(); this.renderPalette(); this.renderBanners(); this.updateChips(); this.tick();
    this.bind();
    this.intervals.push(setInterval(() => this.tick(), 500), setInterval(() => this.beat(), 8000), setInterval(() => this.flushEvents(), 6000));
    if (this.pending.size) this.flush();
    if (this.padDirty) this.savePad();
    $('#qbody')?.focus();
  }

  applyPrefs() {
    const r = $('#room'), p = this.prefs;
    r.dataset.theme = p.theme; r.dataset.layout = p.layout; r.dataset.font = p.text_size; r.dataset.qfont = p.question_font;
  }

  qRule(q) {
    if (q.type === 'written') return 'Written answer. Graded by your examiner.';
    if (q.type === 'mcq') return q.negative_marks > 0 ? `Choose one. A wrong answer costs ${num(q.negative_marks)}.` : 'Choose one. No penalty for a wrong answer.';
    const base = q.multi_scheme === 'all_or_nothing' ? 'Select all that apply. You need every correct option and no wrong ones for the marks.'
      : 'Select all that apply. Each wrong pick cancels one right pick.';
    return q.negative_marks > 0 ? `${base} A fully wrong answer costs ${num(q.negative_marks)}.` : base;
  }

  renderQuestion() {
    const q = this.qs[this.cur], n = this.qs.length, multi = q.type === 'multi';
    const body = q.type === 'written'
      ? `<label class="sr" for="wans">Your answer</label>
         <textarea id="wans" class="written" maxlength="20000" placeholder="Write your answer here. It saves as you type.">${esc(q.written)}</textarea>
         <p class="small muted" id="wcount"></p>`
      : `<fieldset class="opts"><legend class="sr">${multi ? 'Select all that apply' : 'Select one answer'}</legend>
         ${q.options.map((o, i) => `<label class="opt ${q.selected.includes(o.id) ? 'on' : ''}">
           <input type="${multi ? 'checkbox' : 'radio'}" name="q${q.id}" value="${o.id}" ${q.selected.includes(o.id) ? 'checked' : ''}>
           <span class="key ${multi ? 'sq' : ''}" aria-hidden="true">${KEYS[i] || i + 1}</span><span class="otext">${esc(o.text)}</span></label>`).join('')}</fieldset>`;
    $('#qpanel').innerHTML = `
      <div class="q-head"><span class="q-count">Question ${this.cur + 1} of ${n}</span>
        <span class="q-marks">${num(q.marks)} mark${q.marks == 1 ? '' : 's'}</span>${badge('type', TYPE_LABEL[q.type])}</div>
      <p class="q-rule">${esc(this.qRule(q))}</p>
      <h2 class="q-body" id="qbody" tabindex="-1">${esc(q.body)}</h2>
      ${body}
      <div class="q-nav">
        <button class="btn" type="button" data-nav="-1" ${this.cur === 0 ? 'disabled' : ''}>Previous</button>
        <button class="btn mark ${q.marked ? 'on' : ''}" type="button" id="bMark" aria-pressed="${q.marked}">${q.marked ? 'Marked for review' : 'Mark for review'}</button>
        ${q.type !== 'written' ? '<button class="linkbtn" type="button" id="bClear">Clear answer</button>' : ''}
        <button class="btn ${this.cur === n - 1 ? '' : 'primary'}" type="button" data-nav="1" ${this.cur === n - 1 ? 'disabled' : ''}>Next</button>
      </div>`;
    this.wordCount();
  }

  wordCount() {
    const el = $('#wcount'); if (!el) return;
    const w = this.qs[this.cur].written.trim();
    el.textContent = w ? `${w.split(/\s+/).length} words` : 'Nothing written yet';
  }

  renderPalette() {
    const a = this.qs.filter(q => q.answered).length, m = this.qs.filter(q => q.marked).length, n = this.qs.length;
    $('#palette').innerHTML = `<h2 class="pal-title">Questions</h2>
      <div class="pal-grid">${this.qs.map((q, i) => `<button type="button" class="pq ${q.answered ? 'ans' : ''} ${q.marked ? 'mk' : ''} ${i === this.cur ? 'cur' : ''}"
        data-go="${i}" ${i === this.cur ? 'aria-current="true"' : ''}
        aria-label="Question ${i + 1}, ${q.answered ? 'answered' : 'not answered'}${q.marked ? ', marked for review' : ''}">${i + 1}</button>`).join('')}</div>
      <ul class="pal-key"><li><span class="pq ans" aria-hidden="true"></span>Answered (${a})</li>
        <li><span class="pq" aria-hidden="true"></span>Not answered (${n - a})</li>
        <li><span class="pq mk" aria-hidden="true"></span>Marked for review (${m})</li></ul>`;
  }

  renderBanners() {
    const off = !this.online ? `<div class="banner warn" role="status"><strong>You are offline.</strong> Keep answering: your work is kept on this device and syncs when the connection returns.
      The exam clock keeps running on the server, so time is not paused or extended.</div>` : '';
    const msgs = this.anns.map(a => `<div class="banner info" role="status"><strong>Message from ${esc(a.author)}:</strong> ${esc(a.message)}
      <button class="linkbtn" type="button" data-dismiss="${a.id}">Dismiss</button></div>`).join('');
    const mon = this.st.integrity_monitoring && !this.noticeGone ? `<div class="banner plain" role="note">Integrity indicators are recorded: when this page is hidden or loses focus, and the size (never the content) of pasted text.
      A person reviews them, and they are not proof of anything. No camera, screen capture or keystroke logging is used.
      <button class="linkbtn" type="button" data-dismiss="notice">Got it</button></div>` : '';
    $('#banners').innerHTML = off + msgs + mon;
  }

  updateChips() {
    const net = $('#netchip'), sv = $('#savechip'); if (!net) return;
    net.className = 'chip ' + (this.online ? 'ok' : 'bad');
    net.textContent = this.online ? 'Connected' : 'Connection lost';
    const n = this.pending.size + (this.padDirty ? 1 : 0);
    sv.className = 'chip ' + (n ? (this.online ? 'info' : 'warn') : 'ok');
    sv.textContent = n ? (this.online ? 'Saving…' : `${n} change${n > 1 ? 's' : ''} waiting to sync`) : 'All changes saved';
  }

  /* ------------------------------------------------------------ interaction */
  bind() {
    const on = (t, ev, fn, opt) => { t.addEventListener(ev, fn, opt); this.listeners.push([t, ev, fn, opt]); };
    on($('#qpanel'), 'change', e => {
      const q = this.qs[this.cur];
      if (e.target.matches('input[type=radio]')) { q.selected = [+e.target.value]; }
      else if (e.target.matches('input[type=checkbox]')) { q.selected = $$('input:checked', $('#qpanel')).map(i => +i.value); }
      else return;
      $$('.opt', $('#qpanel')).forEach(l => l.classList.toggle('on', l.querySelector('input').checked));
      this.changed(q);
    });
    on($('#qpanel'), 'input', e => {
      if (!e.target.matches('#wans')) return;
      const q = this.qs[this.cur]; q.written = e.target.value; this.wordCount(); this.changed(q, true);
    });
    on($('#qpanel'), 'click', e => {
      const q = this.qs[this.cur];
      const nav = e.target.closest('[data-nav]');
      if (nav) return this.go(this.cur + +nav.dataset.nav);
      if (e.target.closest('#bMark')) { q.marked = !q.marked; this.renderQuestion(); $('#bMark').focus(); return this.changed(q); }
      if (e.target.closest('#bClear')) { q.selected = []; this.renderQuestion(); $('#bClear').focus(); this.changed(q); }
    });
    on($('#palette'), 'click', e => { const b = e.target.closest('[data-go]'); if (b) this.go(+b.dataset.go); });
    on($('#banners'), 'click', e => {
      const d = e.target.closest('[data-dismiss]'); if (!d) return;
      if (d.dataset.dismiss === 'notice') this.noticeGone = true; else this.anns = this.anns.filter(a => a.id !== +d.dataset.dismiss);
      this.renderBanners();
    });
    on($('#bSubmit'), 'click', () => this.reviewDialog());
    on($('#bPrefs'), 'click', () => this.prefsDialog());
    on($('#bPad'), 'click', () => this.togglePad());
    on($('#padtext'), 'input', e => this.padInput(e.target.value));
    on($('#padclear'), 'click', () => { $('#padtext').value = ''; this.padInput(''); $('#padtext').focus(); });
    on(window, 'online', () => { this.setNet(true); this.beat(); this.flush(); });
    on(window, 'offline', () => this.setNet(false));
    on(window, 'beforeunload', e => { if (!this.dead && (this.pending.size || this.padDirty)) { e.preventDefault(); e.returnValue = ''; } });
    on(window, 'pagehide', () => this.beacon());
    on(document, 'keydown', e => this.onKey(e));
    if (this.st.integrity_monitoring) this.bindIntegrity(on);
  }

  bindIntegrity(on) {
    let hiddenAt = null, blurAt = null;
    on(document, 'visibilitychange', () => {
      if (document.hidden) { hiddenAt = performance.now(); blurAt = null; this.queueEvent('tab_hidden'); }
      else if (hiddenAt != null) { this.queueEvent('tab_visible', `away=${Math.round((performance.now() - hiddenAt) / 1000)}`); hiddenAt = null; }
    });
    on(window, 'blur', () => { if (!document.hidden) blurAt = performance.now(); });
    on(window, 'focus', () => {
      if (blurAt != null) { const s = (performance.now() - blurAt) / 1000; if (s >= 3) this.queueEvent('window_blur', `away=${Math.round(s)}`); }
      blurAt = null;
    });
    on(document, 'paste', e => {
      if (!e.target.closest?.('#qpanel, #pad')) return;
      const len = (e.clipboardData?.getData('text') || '').length;      // only the size is recorded, never the text
      this.queueEvent('paste', `len=${len};q=${this.qs[this.cur].position}${e.target.id === 'padtext' ? ';in=pad' : ''}`);
    });
    on(document, 'copy', e => {
      if (!e.target.closest?.('#qpanel')) return;
      const len = String(getSelection()).length;
      if (len >= 20) this.queueEvent('copy', `len=${len};q=${this.qs[this.cur].position}`);
    });
  }

  onKey(e) {
    if ($('.dialog') || e.altKey || e.ctrlKey || e.metaKey) return;
    if (!(e.target === document.body || e.target.tagName === 'BUTTON')) return;
    const q = this.qs[this.cur];
    if (e.key === 'ArrowRight') this.go(this.cur + 1);
    else if (e.key === 'ArrowLeft') this.go(this.cur - 1);
    else if (e.key.toLowerCase() === 'm') { q.marked = !q.marked; this.renderQuestion(); this.changed(q); }
    else if (q.type !== 'written' && /^[a-h]$/i.test(e.key)) {
      const o = q.options[KEYS.indexOf(e.key.toUpperCase())]; if (!o) return;
      const input = $(`input[value="${o.id}"]`, $('#qpanel'));
      if (input) { input.click(); input.focus(); }
    }
  }

  go(i) {
    if (i < 0 || i >= this.qs.length || i === this.cur) return;
    this.cur = i; this.renderQuestion(); this.renderPalette(); $('#qbody').focus(); window.scrollTo({ top: 0 });
  }

  /* ------------------------------------------------------------ autosave (4.1) */
  changed(q, typing = false) {
    q.version += 1;
    q.answered = q.type === 'written' ? !!q.written.trim() : q.selected.length > 0;
    this.pending.set(q.id, { aq_id: q.id, version: q.version, selected: [...q.selected], written: q.written, marked: q.marked });
    store.set(this.pKey, [...this.pending.values()]);
    this.updateChips(); this.renderPalette();
    clearTimeout(this.flushT);
    this.flushT = setTimeout(() => this.flush(), typing ? 900 : 150);
    if (typing && !this.maxT) this.maxT = setTimeout(() => { this.maxT = null; this.flush(); }, 4000);
  }

  async flush() {
    clearTimeout(this.flushT); clearTimeout(this.maxT); this.maxT = null;
    if (this.inflight || this.dead || !this.pending.size) return;
    this.inflight = true;
    const items = [...this.pending.values()];
    try {
      const r = await api(`/api/attempts/${this.id}/save`, { method: 'POST', body: { items } });
      for (const it of items) { const cur = this.pending.get(it.aq_id); if (cur && cur.version <= it.version) this.pending.delete(it.aq_id); }
      this.clock(r.remaining); this.retry = 0; this.setNet(true);
      this.pending.size ? store.set(this.pKey, [...this.pending.values()]) : store.del(this.pKey);
    } catch (e) {
      if (e.status === 409) { this.inflight = false; return this.reload(); }      // closed on the server
      if (e.status >= 400 && e.status < 500 && e.status !== 429 && e.status !== 401) {
        items.forEach(it => this.pending.delete(it.aq_id)); store.del(this.pKey);   // will never succeed: don't loop forever
        toast('One answer could not be saved: ' + e.message, true);
      } else { this.retry++; this.setNet(false); }
    }
    this.inflight = false;
    this.updateChips();
    if (this.pending.size && !this.dead) this.flushT = setTimeout(() => this.flush(), Math.min(1000 * 2 ** Math.min(this.retry, 4), 10000));
  }

  setNet(ok) {
    if (ok === this.online) return;
    this.online = ok;
    if (!ok) { this.offlineSince = performance.now(); this.queueEvent('offline'); }
    else { this.queueEvent('online', `down=${Math.round((performance.now() - (this.offlineSince || performance.now())) / 1000)}`); }
    this.renderBanners(); this.updateChips();
    $('#live').textContent = ok ? 'Connection restored.' : 'Connection lost. Your answers are kept on this device.';
  }

  async beat() {
    if (this.dead) return;
    try {
      const r = await api(`/api/attempts/${this.id}/heartbeat?since=${this.lastAnn}`, { method: 'POST' });
      this.setNet(true); this.clock(r.remaining);
      if (r.status !== 'in_progress') return this.reload();
      if (r.announcements.length) {
        this.lastAnn = r.announcements.at(-1).id; this.anns = [...this.anns, ...r.announcements].slice(-2); this.renderBanners();
        $('#live').textContent = 'New message from your examiner.'; toast('New message from your examiner.');
      }
      if (this.pending.size) this.flush();
      if (this.padDirty) this.savePad();
      this.flushEvents();
    } catch (e) { if (e.status !== 401) this.setNet(false); }
  }

  /* ------------------------------------------------------------ integrity events (5.1) */
  queueEvent(type, detail) { this.eventQ.push({ type, detail: detail || null }); if (this.eventQ.length > 120) this.eventQ.shift(); }
  async flushEvents() {
    if (this.dead || !this.eventQ.length || !this.online) return;
    const batch = this.eventQ.splice(0, 50);
    try { await api(`/api/attempts/${this.id}/events`, { method: 'POST', body: { events: batch } }); }
    catch (e) { if (e.status !== 409) this.eventQ.unshift(...batch); }
  }
  beacon() {
    if (this.dead || !navigator.sendBeacon) return;
    const send = (path, body) => navigator.sendBeacon(`/api/attempts/${this.id}/${path}`, new Blob([JSON.stringify(body)], { type: 'application/json' }));
    if (this.pending.size) send('save', { items: [...this.pending.values()] });
    if (this.eventQ.length) send('events', { events: this.eventQ.splice(0, 50) });
  }

  /* ------------------------------------------------------------ scratchpad (4.8) */
  togglePad() {
    this.padOpen = !this.padOpen;
    $('#pad').hidden = !this.padOpen; $('#rbody').classList.toggle('with-pad', this.padOpen);
    $('#bPad').setAttribute('aria-pressed', this.padOpen);
    if (this.padOpen) $('#padtext').focus(); else $('#bPad').focus();
  }
  padInput(v) {
    this.padValue = v; this.padDirty = true; store.set(this.padKey, v);
    $('#padstat').textContent = 'Typing…'; this.updateChips();
    clearTimeout(this.padT); this.padT = setTimeout(() => this.savePad(), 1200);
  }
  async savePad() {
    if (this.padSaving || this.dead) return;
    this.padSaving = true; const sent = this.padValue;
    try {
      await api(`/api/attempts/${this.id}/scratchpad`, { method: 'PUT', body: { content: sent } });
      if (this.padValue === sent) { this.padDirty = false; store.del(this.padKey); const s = $('#padstat'); if (s) s.textContent = 'Saved'; }
    } catch (e) { const s = $('#padstat'); if (s) s.textContent = 'Not synced yet, kept on this device'; if (e.status === 409) { this.padSaving = false; return this.reload(); } }
    this.padSaving = false; this.updateChips();
  }

  /* ------------------------------------------------------------ preferences (4.7) */
  prefsDialog() {
    const p = this.prefs;
    const group = (name, label, opts) => `<fieldset class="field"><legend class="label">${label}</legend><div class="seg">${opts.map(([v, t]) =>
      `<label><input type="radio" name="${name}" value="${v}" ${p[name] === v ? 'checked' : ''}><span>${t}</span></label>`).join('')}</div></fieldset>`;
    const dlg = openModal({
      title: 'Workspace view', body: `<form id="pf">
      ${group('theme', 'Colour', [['light', 'Light'], ['dark', 'Dark'], ['sepia', 'Sepia']])}
      ${group('text_size', 'Text size', [['sm', 'Small'], ['md', 'Medium'], ['lg', 'Large'], ['xl', 'Extra large']])}
      ${group('layout', 'Layout', [['palette-right', 'Navigator right'], ['palette-left', 'Navigator left'], ['palette-top', 'Navigator on top'], ['focus', 'Focus (hide navigator)']])}
      ${group('question_font', 'Question font', [['serif', 'Serif'], ['sans', 'Sans-serif']])}
      <p class="small muted">Saved to your account and used in every exam. Keyboard: left and right arrows move between questions, A to H choose an option, M marks for review.</p></form>`,
      footer: '<button class="btn primary" data-close>Done</button>'
    });
    $('#pf', dlg).onchange = e => {
      if (!e.target.name) return;
      this.prefs[e.target.name] = e.target.value; this.applyPrefs();
      clearTimeout(this.prefT);
      this.prefT = setTimeout(() => api('/api/preferences', { method: 'PUT', body: this.prefs }).catch(() => toast('Could not save your view settings, but they still apply now.', true)), 500);
    };
  }

  /* ------------------------------------------------------------ timer */
  tick() {
    const left = this.left(), clock = $('#clock'); if (!clock) return;
    const txt = hhmmss(left);
    if (clock.textContent !== txt) clock.textContent = txt;
    clock.classList.toggle('warn', left < 300 && left >= 60); clock.classList.toggle('crit', left < 60);
    $('#timefill').style.width = Math.min(100, Math.max(0, (1 - left / this.total) * 100)) + '%';
    for (const [t, msg] of [[600, '10 minutes remaining.'], [300, '5 minutes remaining.'], [60, '1 minute remaining.']]) {
      if (left <= t && left > t - 5 && !this.said.has(t)) { this.said.add(t); $('#live').textContent = msg; }
    }
    if (left <= 0 && !this.timeUp) { this.timeUp = true; this.timeUpScreen(); this.doSubmit(true); }
  }
  timeUpScreen() {
    closeModal();
    openModal({ title: 'Time is up', body: '<p>Your answers are being submitted. Answers that reached the server before time ran out are kept.</p>', footer: '' });
    $('.dialog .x')?.remove();
  }

  /* ------------------------------------------------------------ submit */
  reviewDialog() {
    const un = this.qs.map((q, i) => [q, i]).filter(([q]) => !q.answered), mk = this.qs.map((q, i) => [q, i]).filter(([q]) => q.marked);
    const list = items => items.map(([, i]) => `<button type="button" class="pq" data-jump="${i}" aria-label="Go to question ${i + 1}">${i + 1}</button>`).join('');
    const dlg = openModal({
      title: 'Review before you submit', body: `
      <p><strong>${this.qs.length - un.length} of ${this.qs.length}</strong> questions answered.</p>
      ${un.length ? `<p class="label" style="margin-top:14px">Not answered</p><div class="pal-grid">${list(un)}</div>` : '<p class="banner good" style="margin-top:12px">Every question has an answer.</p>'}
      ${mk.length ? `<p class="label" style="margin-top:14px">Marked for review</p><div class="pal-grid">${list(mk)}</div>` : ''}
      ${!this.online || this.pending.size ? '<p class="banner warn" style="margin-top:14px">Some answers have not synced yet. They will be sent with your submission if the connection allows.</p>' : ''}
      <p class="muted small" style="margin-top:14px">You cannot change your answers after submitting.</p>`,
      footer: '<button class="btn" data-close>Keep working</button><button class="btn primary" id="finalgo">Submit final answers</button>'
    });
    dlg.addEventListener('click', e => { const j = e.target.closest('[data-jump]'); if (j) { closeModal(); this.go(+j.dataset.jump); } });
    $('#finalgo', dlg).onclick = e => { e.target.disabled = true; e.target.textContent = 'Submitting…'; this.doSubmit(false, () => { e.target.disabled = false; e.target.textContent = 'Submit final answers'; }); };
  }

  async doSubmit(auto, onFail) {
    if (this.submitting) return;
    this.submitting = true;
    try {
      if (this.padDirty) await this.savePad();
      const items = [...this.pending.values()];
      await api(`/api/attempts/${this.id}/submit`, { method: 'POST', body: { items } });
      this.reload();
    } catch (e) {
      this.submitting = false;
      if (e.status === 409) return this.reload();
      if (onFail) onFail();
      if (auto) setTimeout(() => this.doSubmit(true), 3000);
      else toast(e.status === 0 ? 'Cannot reach the server. Your answers are kept on this device. Try again when you are connected.' : e.message, true);
    }
  }

  reload() {                    // leave the room and show the server's view of the attempt (done screen)
    store.del(this.pKey); store.del(this.padKey);
    this.destroy(); closeModal(); App.views.exam([this.id]);
  }

  destroy() {
    this.dead = true;
    this.intervals.forEach(clearInterval);
    [this.flushT, this.maxT, this.padT, this.prefT].forEach(clearTimeout);
    this.listeners.forEach(([t, ev, fn, opt]) => t.removeEventListener(ev, fn, opt));
    this.listeners = []; this.intervals = [];
  }
}
