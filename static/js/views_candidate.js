/* Candidate: my exams. Start/resume opens the exam room (views_exam_room.js). */
App.views['my-exams'] = async function () {
  const list = await api('/api/exams/mine');
  const done = e => e.attempt_status === 'submitted' || e.attempt_status === 'expired';
  const groups = [
    ['Available now', list.filter(e => e.access_status === 'open' && !done(e))],
    ['Upcoming', list.filter(e => e.access_status === 'upcoming')],
    ['Completed or closed', list.filter(e => done(e) || e.access_status === 'closed')],
  ];
  const card = e => {
    const open = e.access_status === 'open' && !done(e);
    const note = e.attempt_status === 'in_progress' ? 'You have an attempt in progress.'
      : done(e) ? (e.results_published ? 'Results are published.' : 'Submitted. Results are not published yet.')
      : e.access_status === 'upcoming' ? `Opens ${fmtDT(e.start_time)}.`
      : e.access_status === 'closed' ? 'The exam window has closed.' : '';
    return `<div class="exam-card"><div><h3>${esc(e.title)}</h3>
      <div class="exam-meta"><span>Opens ${fmtDT(e.start_time)}</span><span>Closes ${fmtDT(e.end_time)}</span><span>${e.duration_minutes} minutes</span></div>
      ${note ? `<p class="small" style="margin-top:8px">${esc(note)}</p>` : ''}
      ${e.instructions ? `<details class="instr"><summary>Instructions</summary><p>${esc(e.instructions)}</p></details>` : ''}</div>
      <div>${open ? `<button class="btn primary" data-start="${e.id}">${e.attempt_status === 'in_progress' ? 'Resume exam' : 'Start exam'}</button>` : badge(e.access_status, { open: 'Open', upcoming: 'Not open yet', closed: 'Closed' }[e.access_status])}</div></div>`;
  };
  setView(pageHead('My exams', 'Exams you are enrolled in.') + (!list.length ?
    `<div class="panel">${empty('No exams assigned yet', 'When an examiner enrolls you in a published exam, it will appear here.')}</div>` :
    groups.filter(g => g[1].length).map(([t, items]) => `<h2 class="section-title">${t}</h2><div class="panel">${items.map(card).join('')}</div>`).join('')));
  $$('[data-start]').forEach(b => b.onclick = () => busy(b, () => App.startExam(+b.dataset.start)));
};
