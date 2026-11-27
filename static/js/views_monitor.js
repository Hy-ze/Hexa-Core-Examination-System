/* Examiner: live monitoring (3.6), integrity indicators for human review (5.1), paper fairness (5.2). */
const SIGNAL_LABEL = {
  tab_switching: 'Page switching', paste_activity: 'Pasting', focus_loss: 'Window focus lost',
  ai_style_text: 'Written-answer style (AI review)', text_style_heuristic: 'Written-answer style (offline check)',
};
const mmss = s => { s = Math.max(0, Math.round(s)); return Math.floor(s / 60) + ':' + String(s % 60).padStart(2, '0'); };

function connState(a) {
  if (a.status !== 'in_progress') return null;
  if (a.hb_age == null) return ['unknown', 'No signal yet'];
  if (a.hb_age <= 25) return ['online', 'Connected'];
  if (a.hb_age <= 90) return ['unstable', 'Unstable'];
  return ['offline', 'No signal ' + mmss(a.hb_age)];
}

function describeEvent(e) {
  const d = e.detail || '', get = k => (d.match(new RegExp(k + '=(\\d+)')) || [])[1];
  switch (e.event_type) {
    case 'tab_hidden': return 'Left the exam page (tab hidden or minimised)';
    case 'tab_visible': return `Returned to the exam page${get('away') ? ` after ${get('away')}s` : ''}`;
    case 'window_blur': return `Exam window lost focus${get('away') ? ` for ${get('away')}s` : ''}`;
    case 'paste': return `Pasted ${get('len') || '?'} characters${get('q') ? ` (question ${get('q')}${/in=pad/.test(d) ? ', scratchpad' : ''})` : ''}`;
    case 'copy': return `Copied ${get('len') || '?'} characters from question ${get('q') || '?'}`;
    case 'offline': return 'Connection lost (technical incident)';
    case 'online': return `Connection restored${get('down') ? ` after ${get('down')}s` : ''}`;
    default: return e.event_type;
  }
}

/* ------------------------------------------------------------------ live monitor */
App.monitorTab = async function (id, ex) {
  clearInterval(App.monTimer);
  if (ex.status === 'draft') { $('#tabbody').innerHTML = `<div class="panel">${empty('Nothing to monitor yet', 'Publish the exam and enrol candidates. Live attempts, connection status and announcements appear here during the exam.')}</div>`; return; }
  $('#tabbody').innerHTML = `<div class="banner plain">Indicators below are observations to review, not evidence of misconduct. A hidden tab or a dropped connection has many innocent causes.</div>
    <div id="mon-root"><p class="muted">Loading…</p></div>
    <h2 class="section-title">Announce to candidates</h2>
    <div class="panel panel-pad"><form id="annf" class="ann-form"><label class="sr" for="annmsg">Message</label>
      <textarea id="annmsg" maxlength="1000" placeholder="For example: 10 minutes remain. Question 7 has been clarified." rows="2"></textarea>
      <button class="btn primary" type="submit">Send to all</button></form><div id="annlist"></div></div>`;
  const load = async () => {
    if (!$('#mon-root')) { clearInterval(App.monTimer); return; }
    const m = await api(`/api/exams/${id}/monitor`);
    if (!$('#mon-root')) return;
    drawMonitor(m, id);
  };
  const loadAnn = async () => {
    const list = await api(`/api/exams/${id}/announcements`);
    const el = $('#annlist'); if (!el) return;
    el.innerHTML = list.length ? `<ul class="ann-list">${list.map(a => `<li><span class="small muted">${fmtDT(a.created_at)}</span> ${esc(a.message)}</li>`).join('')}</ul>` : '<p class="muted small" style="margin-top:10px">No announcements sent yet.</p>';
  };
  $('#annf').onsubmit = async e => {
    e.preventDefault();
    const msg = $('#annmsg').value.trim(), btn = e.target.querySelector('button');
    if (msg.length < 2) return toast('Write a message first.', true);
    await busy(btn, async () => { await api(`/api/exams/${id}/announcements`, { method: 'POST', body: { message: msg } }); $('#annmsg').value = ''; toast('Sent. Candidates see it within a few seconds.'); await loadAnn(); });
  };
  await Promise.all([load(), loadAnn()]);
  App.monTimer = setInterval(() => load().catch(() => { }), 5000);
};

function drawMonitor(m, id) {
  const s = m.summary, root = $('#mon-root');
  const tile = (n, l) => `<div class="tile"><strong>${n}</strong><span>${l}</span></div>`;
  const rows = m.attempts.map(a => {
    const c = connState(a), pct = a.total_q ? Math.round(100 * a.answered_q / a.total_q) : 0;
    const chips = [[a.n_tab, 'tab switches'], [a.n_paste, 'pastes'], [a.n_blur, 'focus losses']].filter(x => x[0] > 0).map(([n, l]) => `<span class="mini">${n} ${l}</span>`).join('')
      + (a.n_offline > 0 ? `<span class="mini net">${a.n_offline} disconnects</span>` : '');
    return `<tr><td><strong>${esc(a.full_name)}</strong><br><span class="small muted">${esc(a.roll_no || '')}</span></td>
      <td>${a.status === 'in_progress' ? badge('ongoing', 'In progress') : a.status === 'expired' ? badge('closed', 'Time expired') : badge('open', 'Submitted')}</td>
      <td><div class="pbar" role="img" aria-label="${a.answered_q} of ${a.total_q} answered"><span style="width:${pct}%"></span></div><span class="small muted">${a.answered_q}/${a.total_q} answered${a.marked_q > 0 ? `, ${a.marked_q} marked` : ''}</span></td>
      <td>${a.status === 'in_progress' ? `<span class="tnum">${mmss(a.remaining)}</span>` : '<span class="muted">–</span>'}</td>
      <td>${c ? `<span class="conn ${c[0]}"><i aria-hidden="true"></i>${c[1]}</span>` : '<span class="muted">–</span>'}</td>
      <td>${chips || '<span class="muted small">None</span>'}${a.open_flags > 0 ? ` <span class="badge b-hard">${a.open_flags} to review</span>` : ''}</td>
      <td><button class="btn sm" data-review="${a.attempt_id}">Details</button></td></tr>`;
  }).join('');
  root.innerHTML = `<div class="tiles">${tile(s.enrolled, 'Enrolled')}${tile(s.not_started, 'Not started')}${tile(s.in_progress, 'In progress')}${tile(s.submitted, 'Submitted')}${tile(s.expired, 'Time expired')}${tile(s.open_flags, 'Indicators to review')}</div>
    <div class="panel tablewrap">${!m.attempts.length ? empty('No attempts yet', 'Candidates appear here as soon as they start. This view refreshes every few seconds.') :
      `<table><thead><tr><th>Candidate</th><th>Status</th><th>Progress</th><th>Time left</th><th>Connection</th><th>Indicators</th><th></th></tr></thead><tbody>${rows}</tbody></table>`}</div>
    ${m.not_started.length ? `<details class="instr" style="margin-top:12px"><summary>${m.not_started.length} enrolled candidate${m.not_started.length > 1 ? 's' : ''} not started</summary><p>${m.not_started.map(n => esc(n.full_name)).join(', ')}</p></details>` : ''}`;
  $$('[data-review]', root).forEach(b => b.onclick = () => attemptReview(+b.dataset.review));
}

/* ------------------------------------------------------------------ per-attempt review */
async function attemptReview(attemptId) {
  const d = await api('/api/integrity/attempts/' + attemptId);
  const open = d.flags.filter(f => f.review_status === 'open').length;
  const flagHtml = f => `<div class="flag ${f.review_status}" data-flag="${f.id}">
    <div class="flag-top"><strong>${esc(SIGNAL_LABEL[f.signal] || f.signal)}${f.question_no ? ` (question ${f.question_no})` : ''}</strong>
      <span class="badge b-type">${f.source === 'ai' ? 'AI review' : 'Rule-based'}</span>
      <span class="small muted">strength ${Math.round(f.score * 100)}%</span>
      <span class="badge ${f.review_status === 'open' ? 'b-hard' : 'b-closed'}">${{ open: 'Needs review', dismissed: 'Dismissed', noted: 'Noted' }[f.review_status]}</span></div>
    <p>${esc(f.reason)}</p>
    ${f.review_status === 'open' ? `<div class="flag-act"><label class="sr" for="fn${f.id}">Note</label><input type="text" id="fn${f.id}" maxlength="500" placeholder="Your note (required)">
      <button class="btn sm" data-act="dismissed">Dismiss</button><button class="btn sm" data-act="noted">Keep as note</button></div>`
      : `<p class="small muted">${esc(f.reviewer || 'Examiner')}: ${esc(f.review_note || '')}</p>`}</div>`;
  const dlg = openModal({
    wide: true, title: `${d.candidate.full_name}: integrity review`,
    body: `<p class="banner plain">${esc(d.notice)}</p>
      ${!d.monitoring_enabled ? '<p class="banner warn">Integrity monitoring was switched off for this exam. Only connection events are recorded.</p>' : ''}
      <h3 style="margin:6px 0 10px">Indicators ${open ? `<span class="badge b-hard">${open} to review</span>` : ''}</h3>
      ${d.flags.length ? d.flags.map(flagHtml).join('') : '<p class="muted">No indicators were raised for this attempt.</p>'}
      <h3 style="margin:22px 0 4px">Timeline</h3>
      <p class="small muted" style="margin-bottom:8px">Time since the candidate started. Connection events are shown so that a drop in the candidate's network is not mistaken for something else.</p>
      ${d.events.length ? `<ol class="tl">${d.events.map(e => `<li class="${e.event_type === 'offline' || e.event_type === 'online' ? 'net' : ''}"><span class="tnum">${mmss(e.offset_s)}</span>${esc(describeEvent(e))}</li>`).join('')}</ol>` : '<p class="muted">No events recorded.</p>'}`,
    footer: `<span class="small muted" style="margin-right:auto">Written-answer review: ${esc(d.ai_provider)}</span>
      ${d.status !== 'in_progress' ? '<button class="btn" id="rescan">Re-run checks</button>' : ''}<button class="btn primary" data-close>Close</button>`
  });
  dlg.addEventListener('click', e => {
    const b = e.target.closest('[data-act]'); if (!b) return;
    const box = b.closest('[data-flag]'), note = $('input', box).value.trim();
    if (!note) { toast('Add a short note explaining your decision.', true); return $('input', box).focus(); }
    busy(b, async () => { await api('/api/integrity/flags/' + box.dataset.flag, { method: 'PUT', body: { review_status: b.dataset.act, note } }); toast('Review saved.'); closeModal(); attemptReview(attemptId); });
  });
  const rs = $('#rescan', dlg);
  if (rs) rs.onclick = () => busy(rs, async () => { const r = await api(`/api/integrity/attempts/${attemptId}/rescan`, { method: 'POST' }); toast(`Checks finished with ${r.provider}. ${r.flags_created} indicator(s) raised.`); closeModal(); attemptReview(attemptId); });
}

/* ------------------------------------------------------------------ fairness (5.2) */
App.fairnessTab = async function (id, ex) {
  const f = await api(`/api/exams/${id}/fairness`);
  if (!f.randomized) {
    $('#tabbody').innerHTML = `<div class="panel">${empty('Everyone gets the same paper', 'Fairness balancing applies when each candidate receives a subset of the pool. In Settings, set "Questions per paper" to a number below the pool size to give every candidate a different, balanced paper.')}</div>`;
    return;
  }
  f.papers = f.papers.filter(p => p.paper_difficulty != null);
  const mean = f.papers.length ? f.papers.reduce((t, p) => t + p.paper_difficulty, 0) / f.papers.length : null;
  $('#tabbody').innerHTML = `<div class="panel panel-pad"><h2>How papers are built</h2>
    <ul class="plain-list"><li>Each candidate draws ${f.paper_size} of ${f.pool_size} questions, so neighbouring candidates see different papers.</li>
    <li>Every paper must total ${num(f.target_marks)} marks and have a similar average difficulty and mix of question types.</li>
    <li>Difficulty is the examiner's label blended with what candidates actually scored on each question. The balance improves every time the question is used.</li>
    <li>Balancing is ${f.balance_on ? 'switched on' : '<strong>switched off</strong>'} for this exam.</li></ul>
    <div class="actions" style="margin-top:14px"><button class="btn primary" id="sim">Compare with plain random papers</button><span class="small muted">Simulates 40 papers each way. Nothing is saved.</span></div>
    <div id="simout"></div></div>
    <h2 class="section-title">Papers issued so far</h2>
    <div class="panel tablewrap">${!f.papers.length ? empty('No real attempts yet', 'Papers are built when candidates start. Sandbox previews are not counted here.') :
      `<table><thead><tr><th>Candidate</th><th>Difficulty index</th><th>Total marks</th><th>Compared with average</th></tr></thead><tbody>${f.papers.map(p => {
        const dv = p.paper_difficulty - mean; return `<tr><td>${esc(p.full_name)}</td><td class="tnum">${p.paper_difficulty.toFixed(2)}</td><td class="tnum">${num(p.max_score)}</td>
        <td><span class="dev"><i style="left:${50 + Math.max(-45, Math.min(45, dv * 150))}%"></i></span> <span class="small muted">${dv >= 0 ? '+' : ''}${dv.toFixed(2)}</span></td></tr>`; }).join('')}</tbody></table>`}</div>
    <h2 class="section-title">Question difficulty: label versus observed</h2>
    <div class="panel tablewrap"><table><thead><tr><th>Question</th><th>Label</th><th>Seen by</th><th>Answered correctly</th><th>Effective difficulty</th></tr></thead><tbody>
    ${f.questions.map(q => `<tr><td><div class="clamp">${esc(q.body)}</div></td><td>${diffBadge(q.label)}</td><td>${q.presented}</td>
      <td>${q.correct_rate == null ? '<span class="muted">n/a</span>' : Math.round(q.correct_rate * 100) + '%'}</td>
      <td class="tnum">${q.effective.toFixed(2)} ${q.uses_observed ? '<span class="badge b-info">uses observed data</span>' : '<span class="small muted">label only</span>'}</td></tr>`).join('')}</tbody></table></div>`;
  $('#sim').onclick = e => busy(e.target, async () => {
    const r = await api(`/api/exams/${id}/fairness/simulate?count=40`);
    const all = [...r.balanced.papers, ...r.random.papers].map(p => p.index), lo = Math.min(...all) - 0.05, hi = Math.max(...all) + 0.05;
    const mk = [...r.balanced.papers, ...r.random.papers].map(p => p.marks), mlo = Math.min(...mk) - 1, mhi = Math.max(...mk) + 1;
    const strip = (papers, key, a, b) => `<div class="strip" aria-hidden="true">${papers.map(p => `<i style="left:${100 * (p[key] - a) / (b - a)}%"></i>`).join('')}</div>`;
    const col = (title, d, tag) => `<div class="simcol ${tag}"><h3>${title}</h3>
      <p class="small muted">Difficulty index of each paper (1 easy, 3 hard)</p>${strip(d.papers, 'index', lo, hi)}
      <p class="small muted">Total marks of each paper</p>${strip(d.papers, 'marks', mlo, mhi)}
      <dl class="kv sm"><dt>Difficulty range</dt><dd>${d.index.min.toFixed(2)} to ${d.index.max.toFixed(2)} (spread ${d.index.std.toFixed(3)})</dd>
      <dt>Marks range</dt><dd>${num(d.marks.min)} to ${num(d.marks.max)}</dd><dt>Different papers</dt><dd>${d.distinct} of ${r.count}</dd></dl></div>`;
    $('#simout').innerHTML = `<div class="simgrid">${col('Balanced (this system)', r.balanced, 'good')}${col('Plain random', r.random, 'bad')}</div>
      <p class="small muted">Each dot is one paper. Tighter dots mean candidates face a more equal exam, while the number of different papers shows that variation is kept.</p>`;
  });
};
