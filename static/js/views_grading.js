/* Examiner grading workspace: submission review, written grading and result publication. */
App.views.grading = async function (args = []) {
  if (args[0] === 'attempt' && args[1]) return gradingAttempt(+args[1]);
  if (args[0]) return gradingExam(+args[0]);
  return gradingHome();
};

async function gradingHome() {
  const exams = await api('/api/grading/exams');
  setView(pageHead('Grading', 'Review submitted attempts, grade written answers and publish final results.') +
    (!exams.length ? `<div class="panel">${empty('No examinations yet', 'Examinations with submissions will appear here.')}</div>` :
      `<div class="panel tablewrap"><table><thead><tr><th>Examination</th><th>Window</th><th>Submissions</th><th>Graded</th><th>Awaiting</th><th>Results</th><th></th></tr></thead><tbody>
      ${exams.map(e => `<tr>
        <td><strong>${esc(e.title)}</strong><div class="small muted">${badge('type', e.eff_status)}</div></td>
        <td class="small">${fmtDT(e.start_time)}<br>${fmtDT(e.end_time)}</td>
        <td>${e.submissions}</td><td>${e.graded}</td><td>${e.awaiting}</td>
        <td>${e.results_published ? badge('ok','Published') : badge('warn','Unpublished')}</td>
        <td class="right"><a class="btn sm" href="#/grading/${e.id}">Review</a></td>
      </tr>`).join('')}</tbody></table></div>`));
}

async function gradingExam(examId) {
  const [data, summary] = await Promise.all([
    api(`/api/grading/exams/${examId}/attempts`),
    api(`/api/grading/exams/${examId}/summary`)
  ]);
  const c = data.counts;
  const ready = data.exam.eff_status === 'completed' && !c.in_progress && c.submissions > 0 && c.awaiting === 0;
  const metrics = [
    ['Submissions', c.submissions], ['Fully graded', c.graded], ['Awaiting grading', c.awaiting],
    ['Average', summary.average_percentage == null ? '–' : `${summary.average_percentage}%`],
    ['Highest', summary.highest_percentage == null ? '–' : `${summary.highest_percentage}%`],
    ['Lowest', summary.lowest_percentage == null ? '–' : `${summary.lowest_percentage}%`]
  ];
  setView(`<p class="small"><a href="#/grading">&larr; All grading</a></p>` +
    pageHead(data.exam.title, 'Examiner review · actual submitted attempts only',
      `${data.exam.results_published ? badge('ok','Results published') : ready ? '<button class="btn primary" id="publish-results">Publish results</button>' : badge('warn','Not ready to publish')}`) +
    `<div class="row3" style="margin-bottom:16px">${metrics.map(([k,v]) => `<div class="panel panel-pad"><div class="muted small">${esc(k)}</div><h2 style="margin-top:5px">${esc(v)}</h2></div>`).join('')}</div>
    ${c.in_progress ? `<div class="banner warn">${c.in_progress} attempt(s) are still in progress. Publication is blocked until all attempts are finalized.</div>` : ''}
    ${c.awaiting ? `<div class="banner warn">${c.awaiting} submitted attempt(s) still need written-response grading.</div>` : ''}
    <div class="panel tablewrap">${!data.attempts.length ? empty('No submissions yet', 'Candidate submissions will appear here after they finish the examination.') :
      `<table><thead><tr><th>Candidate</th><th>Roll no.</th><th>Submitted</th><th>Score</th><th>Grading</th><th></th></tr></thead><tbody>
      ${data.attempts.map(a => `<tr><td><strong>${esc(a.full_name)}</strong><div class="small muted">${esc(a.email)}</div></td>
        <td>${esc(a.roll_no || '–')}</td><td class="small">${fmtDT(a.submitted_at)}</td>
        <td>${num(a.total_score)} / ${num(a.max_score)} <span class="small muted">(${num(a.percentage)}%)</span></td>
        <td>${a.grading_status === 'graded' ? badge('ok','Fully graded') : badge('warn','Needs grading')}</td>
        <td class="right"><a class="btn sm" href="#/grading/attempt/${a.attempt_id}">Review attempt</a></td></tr>`).join('')}</tbody></table>`}</div>
    ${data.exam.results_published ? '<p class="muted small" style="margin-top:12px">Published results are locked against further grading changes.</p>' : ''}`);
  const publish = $('#publish-results');
  if (publish) publish.onclick = e => busy(e.target, async () => {
    if (!await confirmBox('Publish the final results? Candidates will be able to view only their own results.', 'Publish results')) return;
    await api(`/api/grading/exams/${examId}/publish-results`, { method: 'POST' });
    toast('Results published.'); await gradingExam(examId);
  });
}

async function gradingAttempt(attemptId) {
  const d = await api(`/api/grading/attempts/${attemptId}`);
  const locked = !!d.results_published;
  const cards = d.questions.map(q => {
    const answer = q.type === 'written'
      ? `<div class="answer-box"><div class="small muted" style="margin-bottom:6px">Candidate response</div><div style="white-space:pre-wrap">${esc(q.written_answer || 'No answer submitted.')}</div></div>
         ${q.model_answer ? `<details style="margin-top:10px"><summary>Model answer / grading guide</summary><p style="white-space:pre-wrap">${esc(q.model_answer)}</p></details>` : ''}`
      : `<div class="answer-box"><div class="small muted" style="margin-bottom:8px">Options · selected answer(s) highlighted</div>
         ${q.options.map(o => `<div style="padding:5px 8px;border-radius:6px;margin:3px 0;background:${o.selected ? 'var(--tint, #eef5f5)' : 'transparent'}">
           ${o.selected ? '<strong>Selected</strong> · ' : ''}${esc(o.text)}
           <span class="small">${o.is_correct ? ' · Correct option' : ''}</span></div>`).join('')}
         <p class="small muted" style="margin-top:8px">Scheme: ${esc(q.type === 'mcq' ? 'Single answer' : q.multi_scheme === 'partial' ? 'Partial credit' : 'All or nothing')} · Penalty: ${num(q.negative_marks)}</p></div>`;
    const grade = q.type === 'written'
      ? `<div class="row" style="align-items:end;margin-top:12px">
           <div class="field" style="max-width:180px"><label for="mark-${q.aq_id}">Marks awarded (out of ${num(q.marks)})</label>
             <input id="mark-${q.aq_id}" type="number" min="0" max="${q.marks}" step="0.01" value="${q.is_graded ? q.marks_awarded : ''}" ${locked ? 'disabled' : ''}></div>
           <div class="field" style="flex:1"><label for="comment-${q.aq_id}">Examiner comment (optional)</label>
             <input id="comment-${q.aq_id}" maxlength="3000" value="${esc(q.grader_comment)}" ${locked ? 'disabled' : ''}></div>
           ${locked ? '' : `<button class="btn primary" data-save-grade="${q.aq_id}">Save grade</button>`}
         </div>
         <div class="small muted">${q.is_graded ? (q.graded_by ? 'Manually graded' : 'Automatically set to zero because the response was blank') : 'Awaiting examiner grading'}</div>`
      : `<div class="small" style="margin-top:12px">Automatic grade: <strong>${num(q.marks_awarded)} / ${num(q.marks)}</strong> ${q.is_graded ? badge('ok','Auto-graded') : badge('warn','Pending')}</div>`;
    return `<section class="panel panel-pad" style="margin-bottom:12px">
      <div class="actions" style="justify-content:space-between"><h3>Question ${q.position}</h3><span class="small muted">${esc(TYPE_LABEL[q.type])} · ${num(q.marks)} marks</span></div>
      <p style="white-space:pre-wrap;margin:12px 0">${esc(q.body)}</p>${answer}${grade}</section>`;
  }).join('');
  setView(`<p class="small"><a href="#/grading/${d.exam_id}">&larr; Back to ${esc(d.exam_title)}</a></p>` +
    pageHead(esc(d.candidate_name), `${esc(d.exam_title)} · ${esc(d.candidate_email)} · ${esc(d.candidate_roll_no || 'No roll number')}`) +
    `<div class="panel panel-pad" style="margin-bottom:14px"><div class="row" style="justify-content:space-between;align-items:center">
      <div><span class="muted small">Current total</span><h2>${num(d.total_score)} / ${num(d.max_score)}</h2></div>
      <div>${d.grading_status === 'graded' ? badge('ok','Fully graded') : badge('warn','Awaiting grading')}</div>
      <div class="small muted">Submitted ${fmtDT(d.submitted_at)} · ${esc(d.status)}</div></div></div>
    ${locked ? '<div class="banner warn">Results are published. This attempt is read-only.</div>' : ''}
    ${cards || '<div class="panel">No questions found for this attempt.</div>'}`);
  $$('[data-save-grade]').forEach(btn => btn.onclick = () => busy(btn, async () => {
    const id = btn.dataset.saveGrade, field = $('#mark-' + id);
    const value = field.value === '' ? NaN : Number(field.value);
    const max = Number(field.max);
    if (!Number.isFinite(value) || value < 0 || value > max) return toast(`Enter a grade between 0 and ${max}.`, true);
    await api(`/api/grading/attempts/${attemptId}/questions/${id}`, {
      method: 'PUT', body: { marks_awarded: value, grader_comment: $('#comment-' + id).value }
    });
    toast('Grade saved.'); await gradingAttempt(attemptId);
  }));
}
