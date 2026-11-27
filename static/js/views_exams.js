/* Examiner/admin: exam list, setup form, exam detail (settings, questions, candidates, review). */
const statusBadge = s => badge(s, STATUS_LABEL[s] || s);

App.views.exams = async function (args) {
  if (args[0]) return examDetail(+args[0]);
  const list = await api('/api/exams');
  const isAdmin = App.user.role === 'admin';
  setView(pageHead('Exams', 'Create, schedule and manage examinations.', '<button class="btn primary" id="newexam">New exam</button>') +
    `<div class="panel tablewrap">${!list.length ? empty('No exams yet', 'Create your first exam, add questions from the bank, then enroll candidates.') :
      `<table><thead><tr><th>Exam</th><th>Status</th><th>Opens</th><th>Closes</th><th>Duration</th><th>Questions</th><th>Candidates</th>${isAdmin ? '<th>Examiner</th>' : ''}</tr></thead><tbody>
      ${list.map(e => `<tr class="click" tabindex="0" data-go="${e.id}"><td><strong>${esc(e.title)}</strong></td><td>${statusBadge(e.eff_status)}</td>
        <td>${fmtDT(e.start_time)}</td><td>${fmtDT(e.end_time)}</td><td>${e.duration_minutes} min</td>
        <td>${e.paper_size ? `${e.paper_size} of ${e.pool_count}` : e.pool_count}</td><td>${e.enrolled_count}</td>${isAdmin ? `<td>${esc(e.examiner)}</td>` : ''}</tr>`).join('')}</tbody></table>`}</div>`);
  $$('[data-go]').forEach(r => { const go = () => location.hash = '#/exams/' + r.dataset.go; r.onclick = go; r.onkeydown = e => { if (e.key === 'Enter') go(); }; });
  $('#newexam').onclick = () => examForm(null, id => { location.hash = '#/exams/' + id; });
};

/* ---------- create / edit form ---------- */
function examForm(exam, onSaved) {
  const start = exam ? new Date(exam.start_time) : new Date(Date.now() + 3600e3);
  const end = exam ? new Date(exam.end_time) : new Date(start.getTime() + 24 * 3600e3);
  const x = exam || { title: '', instructions: '', duration_minutes: 60, total_marks: 0, paper_size: null, randomize_questions: 1, randomize_options: 1, balance_difficulty: 1, integrity_monitoring: 1, ai_review_written: 1 };
  const dlg = openModal({ wide: true, title: exam ? 'Exam settings' : 'New exam', body: `<form id="ef" novalidate>
    <div class="field"><label for="et">Title</label><input id="et" type="text" maxlength="200" value="${esc(x.title)}"></div>
    <div class="field"><label for="ei">Instructions for candidates</label><textarea id="ei" maxlength="5000">${esc(x.instructions)}</textarea></div>
    <div class="row3">
      <div class="field"><label for="es">Opens</label><input id="es" type="datetime-local" value="${toLocalInput(start.toISOString())}"></div>
      <div class="field"><label for="ee">Closes</label><input id="ee" type="datetime-local" value="${toLocalInput(end.toISOString())}"></div>
      <div class="field"><label for="ed">Duration (minutes)</label><input id="ed" type="number" min="1" max="600" value="${x.duration_minutes}"></div>
    </div>
    <div class="row">
      <div class="field"><label for="ep">Questions per paper</label><input id="ep" type="number" min="1" placeholder="All questions in the pool" value="${x.paper_size ?? ''}">
        <span class="hint">Leave empty to give everyone the whole pool. Set a number to give each candidate a different paper drawn from the pool.</span></div>
      <div class="field" id="tmw"><label for="etm">Target marks per paper</label><input id="etm" type="number" min="1" step="0.5" value="${x.total_marks || ''}">
        <span class="hint">Papers are built to total this, with similar difficulty.</span></div>
    </div>
    <label class="check"><input type="checkbox" id="erq" ${x.randomize_questions ? 'checked' : ''}><span>Shuffle question order<small>Each candidate sees questions in a different order.</small></span></label>
    <label class="check"><input type="checkbox" id="ero" ${x.randomize_options ? 'checked' : ''}><span>Shuffle answer options<small>Applies to single-answer and multiple-select questions.</small></span></label>
    <label class="check"><input type="checkbox" id="ebd" ${x.balance_difficulty ? 'checked' : ''}><span>Balance paper difficulty<small>Only used when each candidate gets a subset of the pool.</small></span></label>
    <label class="check"><input type="checkbox" id="eim" ${x.integrity_monitoring ? 'checked' : ''}><span>Record integrity indicators<small>Tab switches, pasting and similar events. Shown to examiners as indicators for review, never as proof.</small></span></label>
    <label class="check"><input type="checkbox" id="eai" ${x.ai_review_written ? 'checked' : ''}><span>AI review of written answers<small>Flags answers that may need a closer look. The examiner always decides.</small></span></label>
  </form>`, footer: `<button class="btn" data-close>Cancel</button><button class="btn primary" id="esave">${exam ? 'Save settings' : 'Create exam'}</button>` });
  const sync = () => {
    const has = !!$('#ep', dlg).value;
    $('#tmw', dlg).classList.toggle('hidden', !has);
    $('#ebd', dlg).disabled = !has;
  };
  $('#ep', dlg).oninput = sync; sync();
  $('#esave', dlg).onclick = e => busy(e.target, async () => {
    if ($('#et').value.trim().length < 3) return toast('Give the exam a title (at least 3 characters).', true);
    if (!$('#es').value || !$('#ee').value) return toast('Set when the exam opens and closes.', true);
    const ps = $('#ep').value ? parseInt($('#ep').value, 10) : null;
    const dur = parseInt($('#ed').value, 10);
    if (!(dur >= 1)) return toast('Enter the duration in minutes.', true);
    if (ps && !(parseFloat($('#etm').value) > 0)) return toast('Enter the target marks per paper.', true);
    const body = { title: $('#et').value, instructions: $('#ei').value, start_time: fromLocalInput($('#es').value), end_time: fromLocalInput($('#ee').value),
      duration_minutes: dur, paper_size: ps, total_marks: ps ? parseFloat($('#etm').value) : 0,
      randomize_questions: $('#erq').checked, randomize_options: $('#ero').checked, balance_difficulty: $('#ebd').checked,
      integrity_monitoring: $('#eim').checked, ai_review_written: $('#eai').checked };
    const res = await api(exam ? '/api/exams/' + exam.id : '/api/exams', { method: exam ? 'PUT' : 'POST', body });
    closeModal(); toast(exam ? 'Settings saved.' : 'Exam created. Add questions next.');
    onSaved(exam ? exam.id : res.id);
  });
}

/* ---------- detail ---------- */
async function examDetail(id) {
  let tab = 'overview';
  const TABS = [['overview', 'Overview'], ['questions', 'Questions'], ['candidates', 'Candidates'], ['review', 'Review & publish'], ['monitor', 'Live monitor'], ['fairness', 'Paper fairness']];
  let ex;

  async function reload() { ex = await api('/api/exams/' + id); draw(); }
  function draw() {
    clearInterval(App.monTimer);
    const canPublish = ex.status === 'draft';
    const canRevert = ex.eff_status === 'published' && !ex.locked;
    setView(`<p class="small"><a href="#/exams">&larr; All exams</a></p>` +
      pageHead(ex.title, `${statusBadge(ex.eff_status)} <span class="muted">${fmtDT(ex.start_time)} to ${fmtDT(ex.end_time)}</span>`,
        `${canPublish ? '<button class="btn primary" id="pub">Publish exam</button><button class="btn danger" id="del">Delete</button>' : ''}${canRevert ? '<button class="btn" id="unpub">Return to draft</button>' : ''}${ex.questions.length ? '<button class="btn" id="sandbox" title="Take this exam as a candidate. Nothing is recorded.">Preview as candidate</button>' : ''}`) +
      (ex.locked ? '<div class="banner warn">This exam has started, so its settings, questions and enrollment can no longer change.</div>' : '') +
      `<div class="tabs" role="tablist">${TABS.map(([k, l]) => `<button role="tab" aria-selected="${tab === k}" data-tab="${k}">${l}</button>`).join('')}</div><div id="tabbody"></div>`);
    $$('[data-tab]').forEach(b => b.onclick = () => { tab = b.dataset.tab; draw(); });
    if ($('#pub')) $('#pub').onclick = e => busy(e.target, async () => { await api(`/api/exams/${id}/publish`, { method: 'POST' }); toast('Published.'); await reload(); });
    if ($('#unpub')) $('#unpub').onclick = e => busy(e.target, async () => { await api(`/api/exams/${id}/unpublish`, { method: 'POST' }); toast('Returned to draft.'); await reload(); });
    if ($('#del')) $('#del').onclick = async e => {
      if (!await confirmBox('Delete this draft exam and its question pool and enrollments?', 'Delete exam', true)) return;
      busy(e.target, async () => { await api('/api/exams/' + id, { method: 'DELETE' }); toast('Exam deleted.'); location.hash = '#/exams'; });
    };
    if ($('#sandbox')) $('#sandbox').onclick = e => busy(e.target, () => App.startExam(id, true));
    const tabs = { overview: tabOverview, questions: tabQuestions, candidates: tabCandidates, review: tabReview,
      monitor: () => App.monitorTab(id, ex), fairness: () => App.fairnessTab(id, ex) };
    Promise.resolve().then(() => tabs[tab]()).catch(fail);
  }

  function tabOverview() {
    const flags = [[ex.randomize_questions, 'Question order shuffled'], [ex.randomize_options, 'Answer options shuffled'],
      [ex.paper_size && ex.balance_difficulty, 'Paper difficulty balanced'], [ex.integrity_monitoring, 'Integrity indicators recorded'], [ex.ai_review_written, 'AI review of written answers']]
      .filter(f => f[0]).map(f => f[1]);
    $('#tabbody').innerHTML = `<div class="panel panel-pad"><div class="actions" style="justify-content:space-between;margin-bottom:14px"><h2>Settings</h2>
      ${ex.locked ? '' : '<button class="btn" id="editset">Edit settings</button>'}</div>
      <dl class="kv"><dt>Instructions</dt><dd style="font-family:var(--serif);white-space:pre-wrap;font-weight:400">${esc(ex.instructions) || '<span class="muted">None</span>'}</dd>
      <dt>Availability</dt><dd>${fmtDT(ex.start_time)} to ${fmtDT(ex.end_time)}</dd>
      <dt>Time per candidate</dt><dd>${ex.duration_minutes} minutes</dd>
      <dt>Paper</dt><dd>${ex.paper_size ? `Each candidate gets ${ex.paper_size} questions from a pool of ${ex.questions.length}, targeting ${num(ex.total_marks)} marks` : `Everyone gets all ${ex.questions.length} questions (${num(ex.total_marks)} marks)`}</dd>
      <dt>Options</dt><dd>${flags.length ? flags.map(esc).join(', ') : 'None'}</dd></dl></div>`;
    if ($('#editset')) $('#editset').onclick = () => examForm(ex, reload);
  }

  async function tabQuestions() {
    const qs = ex.questions, by = d => qs.filter(q => q.difficulty === d).length;
    $('#tabbody').innerHTML = `<div class="actions" style="justify-content:space-between;margin-bottom:12px">
      <p class="muted">${qs.length} question${qs.length === 1 ? '' : 's'} in the pool: ${by('easy')} easy, ${by('medium')} medium, ${by('hard')} hard.</p>
      ${ex.locked ? '' : '<button class="btn primary" id="addq">Add from question bank</button>'}</div>
      <div class="panel tablewrap">${!qs.length ? empty('The pool is empty', 'Add questions from your question bank to build this exam.') :
        `<table><thead><tr><th>Question</th><th>Type</th><th>Level</th><th>Marks</th><th></th></tr></thead><tbody>
        ${qs.map(q => `<tr><td><div class="clamp">${esc(q.body)}</div><span class="muted small">${esc(q.category || 'No category')}</span></td>
          <td>${badge('type', TYPE_LABEL[q.question_type])}</td><td>${diffBadge(q.difficulty)}</td>
          <td>${ex.locked ? num(q.marks) : `<input class="marks-input" type="number" min="0.5" max="100" step="0.5" value="${q.marks}" data-marks="${q.question_id}" aria-label="Marks">`}</td>
          <td class="right">${ex.locked ? '' : `<button class="btn sm danger" data-rm="${q.question_id}">Remove</button>`}</td></tr>`).join('')}</tbody></table>`}</div>`;
    $$('[data-marks]').forEach(i => i.onchange = () => {
      const v = parseFloat(i.value); if (!(v > 0)) { toast('Marks must be above zero.', true); return reload(); }
      api(`/api/exams/${id}/questions/${i.dataset.marks}`, { method: 'PUT', body: { marks: v } }).then(reload).catch(e => { fail(e); reload(); });
    });
    $$('[data-rm]').forEach(b => b.onclick = () => busy(b, async () => { await api(`/api/exams/${id}/questions/${b.dataset.rm}`, { method: 'DELETE' }); await reload(); }));
    if ($('#addq')) $('#addq').onclick = pickQuestions;
  }

  async function pickQuestions() {
    const [bank, cats] = await Promise.all([api('/api/questions'), api('/api/categories')]);
    const inPool = new Set(ex.questions.map(q => q.question_id));
    const avail = bank.filter(q => !inPool.has(q.id));
    const dlg = openModal({ wide: true, title: 'Add from question bank', body: `
      <div class="toolbar"><input class="grow" id="pq" type="search" placeholder="Search" aria-label="Search">
        <select id="pc" aria-label="Category"><option value="">All categories</option>${cats.map(c => `<option value="${c.id}">${esc(c.name)}</option>`).join('')}</select>
        <select id="pd" aria-label="Difficulty"><option value="">Any level</option><option value="easy">Easy</option><option value="medium">Medium</option><option value="hard">Hard</option></select></div>
      <div id="plist"></div>`, footer: '<span class="muted small" id="pcount" style="margin-right:auto"></span><button class="btn" data-close>Cancel</button><button class="btn primary" id="padd">Add selected</button>' });
    const chosen = new Set();
    const draw = () => {
      const t = $('#pq', dlg).value.toLowerCase(), c = $('#pc', dlg).value, d = $('#pd', dlg).value;
      const rows = avail.filter(q => (!t || q.body.toLowerCase().includes(t)) && (!c || String(q.category_id) === c) && (!d || q.difficulty === d));
      $('#plist', dlg).innerHTML = !rows.length ? empty('Nothing to add', 'Every matching question is already in the pool, or none match the filters.') :
        rows.map(q => `<label class="pickrow"><input type="checkbox" data-q="${q.id}" ${chosen.has(q.id) ? 'checked' : ''}>
          <span><span class="clamp">${esc(q.body)}</span><span class="small muted">${TYPE_LABEL[q.question_type]} · ${num(q.marks)} marks · ${esc(q.category || 'No category')}</span></span>
          <span style="margin-left:auto">${diffBadge(q.difficulty)}</span></label>`).join('');
      $$('[data-q]', dlg).forEach(i => i.onchange = () => { i.checked ? chosen.add(+i.dataset.q) : chosen.delete(+i.dataset.q); count(); });
      count();
    };
    const count = () => { $('#pcount', dlg).textContent = chosen.size ? `${chosen.size} selected` : ''; };
    ['pq', 'pc', 'pd'].forEach(k => $('#' + k, dlg).oninput = draw); draw();
    $('#padd', dlg).onclick = e => busy(e.target, async () => {
      if (!chosen.size) return toast('Select at least one question.', true);
      const r = await api(`/api/exams/${id}/questions`, { method: 'POST', body: { question_ids: [...chosen] } });
      closeModal(); toast(`${r.added} question${r.added === 1 ? '' : 's'} added.`); await reload();
    });
  }

  async function tabCandidates() {
    const en = await api(`/api/exams/${id}/enrollments`);
    $('#tabbody').innerHTML = `<div class="actions" style="justify-content:space-between;margin-bottom:12px">
      <p class="muted">${en.length} candidate${en.length === 1 ? '' : 's'} enrolled. Only enrolled candidates can enter during the exam window.</p>
      ${ex.eff_status === 'completed' ? '' : '<button class="btn primary" id="enr">Enroll candidates</button>'}</div>
      <div class="panel tablewrap">${!en.length ? empty('No candidates enrolled', 'Enroll candidates so they can see this exam once it is published.') :
        `<table><thead><tr><th>Name</th><th>Email</th><th>Roll no.</th><th>Attempt</th><th></th></tr></thead><tbody>
        ${en.map(c => `<tr><td><strong>${esc(c.full_name)}</strong></td><td>${esc(c.email)}</td><td>${esc(c.roll_no || '–')}</td>
          <td>${c.attempt_status ? esc({ in_progress: 'In progress', submitted: 'Submitted', expired: 'Time expired' }[c.attempt_status]) : '<span class="muted">Not started</span>'}</td>
          <td class="right">${c.attempt_status ? '' : `<button class="btn sm danger" data-un="${c.id}">Remove</button>`}</td></tr>`).join('')}</tbody></table>`}</div>`;
    $$('[data-un]').forEach(b => b.onclick = () => busy(b, async () => { await api(`/api/exams/${id}/enrollments/${b.dataset.un}`, { method: 'DELETE' }); toast('Candidate removed.'); await tabCandidates(); await refreshReviewOnly(); }));
    if ($('#enr')) $('#enr').onclick = () => enrollModal(en);
  }
  async function refreshReviewOnly() { ex = await api('/api/exams/' + id); }

  async function enrollModal(current) {
    const all = await api('/api/users/candidates');
    const have = new Set(current.map(c => c.id));
    const avail = all.filter(c => !have.has(c.id));
    const dlg = openModal({ wide: true, title: 'Enroll candidates', body: `<div class="toolbar"><input class="grow" id="cq" type="search" placeholder="Search name, email or roll number" aria-label="Search candidates">
      <button class="btn sm" type="button" id="csel">Select all shown</button></div><div id="clist"></div>`,
      footer: '<span class="muted small" id="ccount" style="margin-right:auto"></span><button class="btn" data-close>Cancel</button><button class="btn primary" id="cadd">Enroll selected</button>' });
    const chosen = new Set(); let shown = [];
    const draw = () => {
      const t = $('#cq', dlg).value.toLowerCase();
      shown = avail.filter(c => !t || `${c.full_name} ${c.email} ${c.roll_no || ''}`.toLowerCase().includes(t));
      $('#clist', dlg).innerHTML = !shown.length ? empty('No candidates to enroll', avail.length ? 'No one matches your search.' : 'Everyone is already enrolled. Add more candidates under Users, or by import.') :
        shown.map(c => `<label class="pickrow"><input type="checkbox" data-c="${c.id}" ${chosen.has(c.id) ? 'checked' : ''}><span><strong>${esc(c.full_name)}</strong><br><span class="small muted">${esc(c.email)}${c.roll_no ? ' · ' + esc(c.roll_no) : ''}</span></span></label>`).join('');
      $$('[data-c]', dlg).forEach(i => i.onchange = () => { i.checked ? chosen.add(+i.dataset.c) : chosen.delete(+i.dataset.c); cnt(); });
      cnt();
    };
    const cnt = () => { $('#ccount', dlg).textContent = chosen.size ? `${chosen.size} selected` : ''; };
    $('#cq', dlg).oninput = draw;
    $('#csel', dlg).onclick = () => { shown.forEach(c => chosen.add(c.id)); draw(); };
    draw();
    $('#cadd', dlg).onclick = e => busy(e.target, async () => {
      if (!chosen.size) return toast('Select at least one candidate.', true);
      const r = await api(`/api/exams/${id}/enrollments`, { method: 'POST', body: { candidate_ids: [...chosen] } });
      closeModal(); toast(`${r.added} candidate${r.added === 1 ? '' : 's'} enrolled.`); await refreshReviewOnly(); await tabCandidates();
    });
  }

  async function tabReview() {
    const r = ex.review;
    const item = (cls, mark, text) => `<li><span class="dot ${cls}" aria-hidden="true">${mark}</span><span>${esc(text)}</span></li>`;
    const ok = [];
    if (!r.issues.length) ok.push('Setup is complete and ready to publish.');
    $('#tabbody').innerHTML = `<div class="panel panel-pad">
      <h2 style="margin-bottom:14px">${ex.status === 'draft' ? 'Before you publish' : 'Review'}</h2>
      <ul class="list-check">${r.issues.map(t => item('bad', '!', t)).join('')}${r.warnings.map(t => item('warn', '!', t)).join('')}${ok.map(t => item('ok', '✓', t)).join('')}</ul>
      <p class="muted small" style="margin-top:16px">${r.pool_size} questions in the pool · ${r.enrolled} candidate${r.enrolled === 1 ? '' : 's'} enrolled.
        Candidates cannot open the exam before it starts, even after you publish.</p>
      ${ex.status === 'draft' ? `<div style="margin-top:16px"><button class="btn primary" id="pub2" ${r.issues.length ? 'disabled' : ''}>Publish exam</button></div>` : `<p style="margin-top:16px">${statusBadge(ex.eff_status)} This exam is published.</p>`}</div>`;
    if ($('#pub2')) $('#pub2').onclick = e => busy(e.target, async () => { await api(`/api/exams/${id}/publish`, { method: 'POST' }); toast('Published.'); await reload(); });
  }

  await reload();
}
