/* Candidate results: the API returns only the signed-in candidate's published results. */
App.views.results = async function (args = []) {
  if (args[0]) return showMyResult(+args[0]);
  const rows = await api('/api/results/mine');
  setView(pageHead('My results', 'Official results published by your examiners.') +
    (!rows.length ? `<div class="panel">${empty('No published results', 'Your results will appear here after your examiner has reviewed and published them.')}</div>` :
      `<div class="panel tablewrap"><table><thead><tr><th>Examination</th><th>Submitted</th><th>Score</th><th>Percentage</th><th></th></tr></thead><tbody>
      ${rows.map(r => `<tr><td><strong>${esc(r.title)}</strong></td><td>${fmtDT(r.submitted_at)}</td>
        <td>${num(r.total_score)} / ${num(r.max_score)}</td><td>${num(r.percentage)}%</td>
        <td class="right"><a class="btn sm" href="#/results/${r.attempt_id}">View result</a></td></tr>`).join('')}</tbody></table></div>`));
};

async function showMyResult(attemptId) {
  const r = await api(`/api/results/${attemptId}`);
  setView(`<p class="small"><a href="#/results">&larr; All results</a></p>` +
    pageHead(r.title, `Official result · Submitted ${fmtDT(r.submitted_at)}`) +
    `<div class="panel panel-pad" style="margin-bottom:14px"><div class="row3">
      <div><span class="small muted">Your score</span><h2>${num(r.total_score)} / ${num(r.max_score)}</h2></div>
      <div><span class="small muted">Percentage</span><h2>${num(r.percentage)}%</h2></div>
      <div><span class="small muted">Status</span><h2>Published</h2></div></div></div>
    <div class="panel tablewrap"><table><thead><tr><th>Question</th><th>Type</th><th>Marks awarded</th><th>Examiner feedback</th></tr></thead><tbody>
      ${r.questions.map(q => `<tr><td><strong>Q${q.position}.</strong> ${esc(q.body)}</td><td>${esc(TYPE_LABEL[q.type])}</td>
        <td>${q.is_graded ? `${num(q.marks_awarded)} / ${num(q.marks)}` : '–'}</td>
        <td>${esc(q.grader_comment || '–')}</td></tr>`).join('')}</tbody></table></div>`);
}
