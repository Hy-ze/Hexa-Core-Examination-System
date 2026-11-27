/* Bulk import screens: CSV/JSON preview, validation and explicit commit. */
const IMPORT_TEMPLATES = {
  questions: {
    label: 'Questions', endpoint: '/api/imports/questions',
    description: 'Add questions to the question bank. Existing or duplicate question text is rejected.',
    headers: 'type,difficulty,category,question,option_a,option_b,option_c,option_d,correct,marks,negative_marks,multi_scheme,explanation',
    sample: 'mcq,medium,Biology,Which organelle produces ATP?,Nucleus,Mitochondrion,Ribosome,Golgi,B,1,0,partial,The mitochondrion is the main site of ATP production.'
  },
  candidates: {
    label: 'Candidates', endpoint: '/api/imports/candidates',
    description: 'Create candidate accounts. Available to administrators only. Leave password blank to generate one.',
    headers: 'full_name,email,roll_no,password',
    sample: 'Ayesha Khan,ayesha@example.com,BSCS-001,\nAli Raza,ali@example.com,BSCS-002,'
  },
  enrollments: {
    label: 'Exam enrollments', endpoint: null,
    description: 'Enroll existing candidate accounts in an exam using email or roll number.',
    headers: 'email,roll_no', sample: 'ayesha@example.com,BSCS-001\nali@example.com,BSCS-002'
  }
};

App.views.imports = async function (args) {
  const exams = await api('/api/exams');
  const isAdmin = App.user.role === 'admin';
  const types = isAdmin ? ['questions','candidates','enrollments'] : ['questions','enrollments'];
  let selected = types.includes(args[0]) ? args[0] : 'questions';
  let report = null, rawContent = '', chosenName = '';
  const examOptions = exams.map(e => `<option value="${e.id}">${esc(e.title)}</option>`).join('');
  const render = () => {
    const t = IMPORT_TEMPLATES[selected];
    const tabs = types.map(k => `<button class="tab-btn ${selected===k?'active':''}" type="button" data-kind="${k}">${IMPORT_TEMPLATES[k].label}</button>`).join('');
    setView(pageHead('Bulk imports', 'Upload structured files, review validation, then explicitly confirm the import.') +
      `<div class="tabs import-tabs">${tabs}</div>
       <section class="panel panel-pad import-panel">
        <div class="import-intro"><div><h2>${t.label}</h2><p class="muted">${t.description}</p></div><span class="badge b-type">CSV or JSON</span></div>
        ${selected==='enrollments' ? `<div class="field"><label for="import-exam">Target examination</label><select id="import-exam">${examOptions || '<option value="">No exams available</option>'}</select></div>` : ''}
        <div class="field"><label for="import-file">Choose file</label><input id="import-file" type="file" accept=".csv,.json,text/csv,application/json"><span class="hint">Maximum file size: approximately 1.5 MB. The file is read in your browser and sent for validation.</span></div>
        <div class="file-picked" id="file-picked">${chosenName ? `Selected: ${esc(chosenName)}` : 'No file selected'}</div>
        <div class="import-actions"><button class="btn" id="template-btn" type="button">Download CSV template</button><button class="btn primary" id="preview-import" type="button" ${rawContent?'':'disabled'}>Validate & preview</button></div>
        <div id="import-result">${report ? importReportHtml(report) : '<div class="empty"><h3>Ready when you are</h3><p>Select a CSV or JSON file to validate its rows before importing.</p></div>'}</div>
       </section>`);
    $$('[data-kind]').forEach(b => b.onclick = () => { selected=b.dataset.kind; report=null; rawContent=''; chosenName=''; render(); });
    $('#import-file').onchange = async e => {
      const file=e.target.files?.[0]; report=null; rawContent=''; chosenName=file?.name || '';
      if (!file) { $('#file-picked').textContent='No file selected'; $('#preview-import').disabled=true; return; }
      if (file.size > 1_500_000) { toast('This file is too large. Choose a file under 1.5 MB.',true); e.target.value=''; return; }
      try { rawContent=await file.text(); $('#file-picked').textContent=`${file.name} · ${(file.size/1024).toFixed(1)} KB`; $('#preview-import').disabled=!rawContent.trim(); }
      catch(err) { toast('Could not read this file.',true); }
    };
    $('#template-btn').onclick=()=>downloadText(`${selected}_template.csv`, `${t.headers}\n${t.sample}\n`);
    $('#preview-import').onclick=async e=>{
      if(!rawContent.trim()) return;
      const btn=e.currentTarget; btn.disabled=true; btn.textContent='Validating…';
      try {
        const fmt=chosenName.toLowerCase().endsWith('.json')?'json':'csv';
        const path=selected==='enrollments' ? `/api/imports/exams/${encodeURIComponent($('#import-exam').value)}/candidates` : t.endpoint;
        const result=await api(path,{method:'POST',body:{format:fmt,content:rawContent,commit:false}});
        report=result; $('#import-result').innerHTML=importReportHtml(result); bindCommit();
      } catch(err) { $('#import-result').innerHTML=`<div class="banner bad">${esc(err.message)}</div>`; }
      finally { btn.disabled=false; btn.textContent='Validate & preview'; }
    };
    bindCommit();
  };
  function bindCommit(){
    const b=$('#commit-import'); if(!b) return;
    b.onclick=async()=>{
      if(!report || !report.valid) return;
      if(!await confirmBox(`Import ${report.valid} valid ${report.kind} row(s)? This action will write to the database.`, 'Import now')) return;
      b.disabled=true; b.textContent='Importing…';
      try {
        const fmt=chosenName.toLowerCase().endsWith('.json')?'json':'csv';
        const t=IMPORT_TEMPLATES[selected];
        const path=selected==='enrollments' ? `/api/imports/exams/${encodeURIComponent($('#import-exam').value)}/candidates` : t.endpoint;
        report=await api(path,{method:'POST',body:{format:fmt,content:rawContent,commit:true}});
        $('#import-result').innerHTML=importReportHtml(report); bindCommit();
        toast(`Import complete: ${report.created ?? 0} record(s) created.`);
      } catch(err) { toast(err.message,true); b.disabled=false; b.textContent='Confirm import'; }
    };
  }
  render();
};

function downloadText(name, content){
  const blob=new Blob([content],{type:'text/csv;charset=utf-8'}); const url=URL.createObjectURL(blob);
  const a=document.createElement('a'); a.href=url; a.download=name; a.click(); URL.revokeObjectURL(url);
}
function importReportHtml(r){
  const cards=`<div class="metric-grid"><div class="metric"><span>Total rows</span><strong>${r.total}</strong></div><div class="metric"><span>Valid</span><strong class="metric-good">${r.valid}</strong></div><div class="metric"><span>Invalid</span><strong class="metric-bad">${r.invalid}</strong></div><div class="metric"><span>Created</span><strong>${r.created ?? (r.committed? r.valid:0)}</strong></div></div>`;
  const preview=r.preview?.length?`<h3 class="section-title">Valid row preview</h3><div class="tablewrap"><table><thead><tr>${Object.keys(r.preview[0]).map(k=>`<th>${esc(k.replaceAll('_',' '))}</th>`).join('')}</tr></thead><tbody>${r.preview.map(row=>`<tr>${Object.values(row).map(v=>`<td>${esc(v ?? '—')}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`:'<p class="muted">No valid rows to preview.</p>';
  const errors=r.errors?.length?`<h3 class="section-title">Validation issues</h3><div class="tablewrap"><table><thead><tr><th>Row</th><th>Issue</th></tr></thead><tbody>${r.errors.map(x=>`<tr><td>${x.row}</td><td>${esc(x.message)}</td></tr>`).join('')}</tbody></table></div>${r.errors_truncated?'<p class="hint">Only the first 200 errors are shown.</p>':''}`:'';
  const credentials=r.credentials?.length?`<div class="banner warn"><strong>Generated passwords</strong><p>Save these credentials securely now. They are shown only in this import response.</p><div class="tablewrap"><table><thead><tr><th>Name</th><th>Email</th><th>Roll no.</th><th>Temporary password</th></tr></thead><tbody>${r.credentials.map(x=>`<tr><td>${esc(x.full_name)}</td><td>${esc(x.email)}</td><td>${esc(x.roll_no)}</td><td><code>${esc(x.password)}</code></td></tr>`).join('')}</tbody></table></div><button class="btn sm" id="copy-credentials" type="button">Copy credentials</button></div>`:'';
  const action=!r.committed && r.valid?'<div class="commit-row"><p class="muted">Preview only — nothing has been saved yet.</p><button class="btn primary" id="commit-import" type="button">Confirm import</button></div>':r.committed?'<div class="banner good">Import committed successfully.</div>':'';
  const html=`${cards}${action}${preview}${errors}${credentials}`;
  setTimeout(()=>{const c=$('#copy-credentials');if(c)c.onclick=()=>GenCopyCredentials(r.credentials);},0);
  return html;
}
function GenCopyCredentials(rows){ const text=rows.map(x=>`${x.full_name}\t${x.email}\t${x.roll_no}\t${x.password}`).join('\n'); if(navigator.clipboard?.writeText) navigator.clipboard.writeText(text).then(()=>toast('Credentials copied.')).catch(()=>toast('Could not copy credentials.',true)); }
