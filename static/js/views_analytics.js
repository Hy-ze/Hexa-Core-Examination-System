/* Per-exam question analytics dashboard. */
App.views.analytics = async function(args){
  const exams=await api('/api/exams');
  if(!exams.length){setView(pageHead('Analytics','Question-level performance from submitted attempts.')+empty('No examinations yet','Create an examination first, then analytics will appear here.'));return;}
  let examId=Number(args[0]) || exams[0].id;
  const render=async()=>{
    const exam=exams.find(x=>x.id===examId)||exams[0]; examId=exam.id;
    setView(pageHead('Exam analytics','Review question performance using completed, non-sandbox attempts.',`<a class="btn" href="#/exams/${exam.id}">Open exam</a>`) +
      `<div class="toolbar"><label for="analytics-exam" class="label">Examination</label><select id="analytics-exam">${exams.map(x=>`<option value="${x.id}" ${x.id===examId?'selected':''}>${esc(x.title)}</option>`).join('')}</select><button class="btn" id="refresh-analytics">Refresh</button></div><div id="analytics-body"><p class="muted">Loading analytics…</p></div>`);
    $('#analytics-exam').onchange=()=>{examId=Number($('#analytics-exam').value);location.hash=`#/analytics/${examId}`;};
    $('#refresh-analytics').onclick=load;
    await load();
  };
  async function load(){
    const root=$('#analytics-body'); if(!root)return; root.innerHTML='<p class="muted">Loading analytics…</p>';
    try{const d=await api(`/api/exams/${examId}/analytics/questions`); root.innerHTML=analyticsHtml(d);}
    catch(e){root.innerHTML=`<div class="banner bad">${esc(e.message)}</div>`;}
  }
  await render();
};
function pctText(v){return v==null?'—':`${Math.round(v*100)}%`;}
function metricCard(label,value,sub=''){return `<div class="metric"><span>${label}</span><strong>${value}</strong>${sub?`<small>${sub}</small>`:''}</div>`;}
function analyticsHtml(d){
  const s=d.summary||{};
  const cards=`<div class="metric-grid">${metricCard('Attempts counted',d.attempts_counted)}${metricCard('Questions',s.questions??0)}${metricCard('Questions with 5+ responses',s.with_data??0)}${metricCard('Average correct rate',pctText(s.avg_correct_rate))}${metricCard('Needs review',s.needs_review??0)}</div>`;
  const highlights=`<div class="analytics-highlights"><section class="panel panel-pad"><h3>Hardest questions</h3>${highlightList(s.hardest,'correct_rate')}</section><section class="panel panel-pad"><h3>Most skipped</h3>${highlightList(s.most_skipped,'skip_rate')}</section><section class="panel panel-pad"><h3>Easiest questions</h3>${highlightList(s.easiest,'correct_rate')}</section></div>`;
  const rows=(d.questions||[]).map(q=>`<tr><td><strong>#${q.question_id}</strong><div class="clamp">${esc(q.body)}</div><small class="muted">${esc(q.category||'Uncategorised')} · ${esc(q.type)} · ${esc(q.label)}</small></td><td>${q.shown}</td><td>${q.answered}</td><td>${q.skipped}</td><td>${pctText(q.skip_rate)}</td><td>${pctText(q.correct_rate)}</td><td>${pctText(q.avg_score_pct)}</td><td>${q.observed_level?badge(q.observed_level,q.observed_level):'—'}</td><td>${q.flags?.length||0}</td><td><button class="btn sm" data-qdetail="${q.question_id}">Details</button></td></tr>`).join('');
  const table=`<section class="panel tablewrap"><table><thead><tr><th>Question</th><th>Shown</th><th>Answered</th><th>Skipped</th><th>Skip rate</th><th>Fully correct</th><th>Avg. score</th><th>Observed</th><th>Flags</th><th></th></tr></thead><tbody>${rows||'<tr><td colspan="10">No question data available.</td></tr>'}</tbody></table></section>`;
  const notice=`<div class="banner warn analytics-notice">${esc(d.notice||'Figures are indicators, not verdicts. Interpret small samples cautiously.')}</div>`;
  setTimeout(()=>{ $$('[data-qdetail]').forEach(b=>b.onclick=()=>{const q=d.questions.find(x=>x.question_id===Number(b.dataset.qdetail));if(q)showQuestionAnalytics(q);});},0);
  return `${cards}${notice}${highlights}<h2 class="section-title">Question breakdown</h2>${table}<div class="report-note"><strong>PDF reports:</strong> The PDF builder is present in the backend, but a report API route is not yet registered. Downloads will be enabled once that endpoint is added.</div>`;
}
function highlightList(items,key){return items?.length?`<ul class="analytics-list">${items.map(x=>`<li><span>#${x.question_id} · ${esc(x.label)}</span><strong>${pctText(x[key])}</strong></li>`).join('')}</ul>`:'<p class="muted">Not enough submitted attempts yet.</p>';}
function showQuestionAnalytics(q){
  const options=q.options?.length?`<h3 class="section-title">Option selections</h3><div class="option-stats">${q.options.map(o=>`<div class="option-stat"><div><span>${esc(o.text)}</span>${o.is_correct?badge('easy','Correct'):''}</div><div class="bar-track"><span style="width:${Math.max(0,Math.min(100,(o.rate||0)*100))}%"></span></div><small>${o.picks} selections · ${pctText(o.rate)}</small></div>`).join('')}</div>`:'';
  const flags=q.flags?.length?`<h3 class="section-title">Review indicators</h3><ul class="list-check">${q.flags.map(f=>`<li><span class="dot ${f.severity==='review'?'bad':'warn'}">!</span><span><strong>${esc(f.code.replaceAll('_',' '))}</strong><br>${esc(f.text)}</span></li>`).join('')}</ul>`:'<p class="muted">No automatic indicators for this question.</p>';
  openModal({wide:true,title:`Question #${q.question_id} analytics`,body:`<p>${esc(q.body)}</p><div class="metric-grid compact-metrics">${metricCard('Shown',q.shown)}${metricCard('Answered',q.answered)}${metricCard('Skipped',q.skipped)}${metricCard('Correct rate',pctText(q.correct_rate))}${metricCard('Average score',pctText(q.avg_score_pct))}${metricCard('Discrimination',q.discrimination??'—')}</div>${options}${flags}`});
}
