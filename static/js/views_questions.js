/* Examiner: question bank. */
const diffBadge = d => badge(d, d[0].toUpperCase() + d.slice(1));

App.views.questions = async function () {
  let cats = await api('/api/categories');
  setView(pageHead('Question bank', 'Reusable questions you can add to any exam.',
    '<button class="btn" id="newcat">New category</button><button class="btn primary" id="newq">New question</button>') +
    `<div class="toolbar"><input class="grow" id="qq" type="search" placeholder="Search question text" aria-label="Search questions">
      <select id="qc" aria-label="Category"></select>
      <select id="qd" aria-label="Difficulty"><option value="">Any difficulty</option><option value="easy">Easy</option><option value="medium">Medium</option><option value="hard">Hard</option></select>
      <select id="qt" aria-label="Question type"><option value="">Any type</option><option value="mcq">Single answer</option><option value="multi">Multiple select</option><option value="written">Written</option></select></div>
    <div class="panel tablewrap" id="qtable"></div>`);

  const fillCats = () => { $('#qc').innerHTML = '<option value="">All categories</option>' + cats.map(c => `<option value="${c.id}">${esc(c.name)} (${c.question_count})</option>`).join(''); };
  fillCats();
  let timer;
  async function load() {
    const p = new URLSearchParams();
    [['q', 'qq'], ['category_id', 'qc'], ['difficulty', 'qd'], ['question_type', 'qt']].forEach(([k, id]) => { const v = $('#' + id).value.trim(); if (v) p.set(k, v); });
    const list = await api('/api/questions?' + p);
    const me = App.user;
    $('#qtable').innerHTML = !list.length ? empty('No questions found', 'Change the filters, or create a question to get started.') :
      `<table><thead><tr><th>Question</th><th>Type</th><th>Level</th><th>Category</th><th>Marks</th><th>Used</th><th>Correct rate</th><th></th></tr></thead><tbody>
      ${list.map(q => `<tr><td><div class="clamp">${esc(q.body)}</div><span class="muted small">by ${esc(q.author)}</span></td>
        <td>${badge('type', TYPE_LABEL[q.question_type])}</td><td>${diffBadge(q.difficulty)}</td><td>${esc(q.category || '–')}</td>
        <td>${num(q.marks)}</td><td>${q.exam_count} exam${q.exam_count === 1 ? '' : 's'}</td>
        <td>${q.question_type !== 'written' && q.times_presented ? Math.round(100 * q.times_correct / q.times_presented) + '%' : '–'}</td>
        <td class="right" style="white-space:nowrap">${(me.role === 'admin' || q.created_by === me.id) ?
          `<button class="btn sm" data-edit="${q.id}">Edit</button> <button class="btn sm danger" data-del="${q.id}">Delete</button>` : ''}</td></tr>`).join('')}</tbody></table>`;
    $$('[data-edit]').forEach(b => b.onclick = () => editor(+b.dataset.edit).catch(fail));
    $$('[data-del]').forEach(b => b.onclick = async () => {
      if (!await confirmBox('Delete this question? This cannot be undone.', 'Delete question', true)) return;
      busy(b, async () => { await api('/api/questions/' + b.dataset.del, { method: 'DELETE' }); toast('Question deleted.'); await refreshAll(); });
    });
  }
  async function refreshAll() { cats = await api('/api/categories'); const keep = $('#qc').value; fillCats(); $('#qc').value = keep; await load(); }
  ['qc', 'qd', 'qt'].forEach(id => $('#' + id).onchange = () => load().catch(fail));
  $('#qq').oninput = () => { clearTimeout(timer); timer = setTimeout(() => load().catch(fail), 250); };
  $('#newq').onclick = () => editor(null).catch(fail);
  $('#newcat').onclick = () => {
    const dlg = openModal({ title: 'New category', body: `<div class="field"><label for="cn">Category name</label><input id="cn" type="text" maxlength="100"></div>`,
      footer: '<button class="btn" data-close>Cancel</button><button class="btn primary" id="csave">Add category</button>' });
    $('#csave', dlg).onclick = e => busy(e.target, async () => {
      if ($('#cn').value.trim().length < 2) return toast('Enter a category name.', true);
      await api('/api/categories', { method: 'POST', body: { name: $('#cn').value } });
      closeModal(); toast('Category added.'); await refreshAll();
    });
  };

  async function editor(id) {
    const q = id ? await api('/api/questions/' + id) : { question_type: 'mcq', difficulty: 'medium', marks: 1, negative_marks: 0, multi_scheme: 'partial', body: '',
      options: [{ text: '', is_correct: true }, { text: '', is_correct: false }, { text: '', is_correct: false }, { text: '', is_correct: false }] };
    const dlg = openModal({ wide: true, title: id ? 'Edit question' : 'New question', body: `
      ${q.locked ? '<div class="banner warn">This question has been attempted. You can fix wording, level and category, but its type, options and marking scheme are locked to keep past results valid.</div>' : ''}
      <form id="qf" novalidate>
        <div class="field"><label for="qb">Question</label><textarea id="qb" maxlength="5000">${esc(q.body)}</textarea></div>
        <div class="row3">
          <div class="field"><label for="qty">Type</label><select id="qty" ${q.locked ? 'disabled' : ''}>${Object.entries(TYPE_LABEL).map(([k, v]) => `<option value="${k}" ${q.question_type === k ? 'selected' : ''}>${v}</option>`).join('')}</select></div>
          <div class="field"><label for="qdf">Difficulty</label><select id="qdf">${['easy', 'medium', 'hard'].map(d => `<option value="${d}" ${q.difficulty === d ? 'selected' : ''}>${d[0].toUpperCase() + d.slice(1)}</option>`).join('')}</select></div>
          <div class="field"><label for="qct">Category</label><select id="qct"><option value="">None</option>${cats.map(c => `<option value="${c.id}" ${q.category_id === c.id ? 'selected' : ''}>${esc(c.name)}</option>`).join('')}</select></div>
        </div>
        <div class="row3">
          <div class="field"><label for="qm">Marks</label><input id="qm" type="number" min="0.5" max="100" step="0.5" value="${q.marks}"></div>
          <div class="field" id="negw"><label for="qn">Negative marks</label><input id="qn" type="number" min="0" max="100" step="0.25" value="${q.negative_marks}"><span class="hint">Deducted for a wrong answer.</span></div>
          <div class="field" id="schw"><label for="qs">Multiple-select marking</label><select id="qs" ${q.locked ? 'disabled' : ''}>
            <option value="partial" ${q.multi_scheme === 'partial' ? 'selected' : ''}>Partial credit</option><option value="all_or_nothing" ${q.multi_scheme === 'all_or_nothing' ? 'selected' : ''}>All or nothing</option></select></div>
        </div>
        <div id="optw"><div class="label" style="margin-bottom:8px">Answer options <span class="muted small" id="opthint"></span></div><div id="opts"></div>
          <button class="btn sm" type="button" id="addopt" ${q.locked ? 'disabled' : ''}>Add option</button></div>
        <div id="maw" class="field"><label for="qma">Model answer (for the grader)</label><textarea id="qma" maxlength="5000">${esc(q.model_answer)}</textarea></div>
        <div class="field" style="margin-top:14px"><label for="qex">Explanation (optional)</label><textarea id="qex" style="min-height:60px" maxlength="2000">${esc(q.explanation)}</textarea></div>
      </form>`,
      footer: '<button class="btn" data-close>Cancel</button><button class="btn primary" id="qsave">Save question</button>' });

    let opts = (q.options || []).map(o => ({ text: o.text, is_correct: !!o.is_correct }));
    const type = () => $('#qty', dlg).value;
    function drawOpts() {
      const single = type() === 'mcq';
      $('#opts', dlg).innerHTML = opts.map((o, i) => `<div class="optrow">
        <input type="${single ? 'radio' : 'checkbox'}" name="correct" ${o.is_correct ? 'checked' : ''} data-c="${i}" aria-label="Option ${i + 1} is correct" ${q.locked ? 'disabled' : ''}>
        <input type="text" value="${esc(o.text)}" maxlength="500" data-t="${i}" placeholder="Option ${i + 1}" aria-label="Option ${i + 1} text" ${q.locked ? 'disabled' : ''}>
        <button class="btn sm" type="button" data-r="${i}" ${q.locked || opts.length <= 2 ? 'disabled' : ''} aria-label="Remove option ${i + 1}">Remove</button></div>`).join('');
      $$('[data-t]', dlg).forEach(el => el.oninput = () => { opts[+el.dataset.t].text = el.value; });
      $$('[data-c]', dlg).forEach(el => el.onchange = () => {
        const i = +el.dataset.c;
        if (single) opts.forEach((o, j) => o.is_correct = j === i); else opts[i].is_correct = el.checked;
      });
      $$('[data-r]', dlg).forEach(el => el.onclick = () => { opts.splice(+el.dataset.r, 1); drawOpts(); });
    }
    function applyType() {
      const t = type(), written = t === 'written';
      $('#optw', dlg).classList.toggle('hidden', written);
      $('#maw', dlg).classList.toggle('hidden', !written);
      $('#schw', dlg).classList.toggle('hidden', t !== 'multi');
      $('#negw', dlg).classList.toggle('hidden', written);
      $('#opthint', dlg).textContent = t === 'mcq' ? '(choose the one correct answer)' : '(tick every correct answer)';
      if (t === 'mcq') { let seen = false; opts.forEach(o => { if (o.is_correct && seen) o.is_correct = false; if (o.is_correct) seen = true; }); if (!seen && opts.length) opts[0].is_correct = true; }
      drawOpts();
    }
    $('#qty', dlg).onchange = applyType;
    $('#addopt', dlg).onclick = () => { if (opts.length >= 8) return toast('Use at most eight options.', true); opts.push({ text: '', is_correct: false }); drawOpts(); };
    applyType();

    $('#qsave', dlg).onclick = e => busy(e.target, async () => {
      const t = type();
      const body = { category_id: $('#qct').value ? +$('#qct').value : null, question_type: t, difficulty: $('#qdf').value,
        body: $('#qb').value, marks: parseFloat($('#qm').value), negative_marks: t === 'written' ? 0 : (parseFloat($('#qn').value) || 0),
        multi_scheme: $('#qs').value, model_answer: t === 'written' ? ($('#qma').value || null) : null, explanation: $('#qex').value || null,
        options: t === 'written' ? [] : opts.map(o => ({ text: o.text, is_correct: o.is_correct })) };
      if (body.body.trim().length < 5) return toast('Write the question (at least 5 characters).', true);
      if (!(body.marks > 0)) return toast('Marks must be above zero.', true);
      if (t !== 'written' && opts.some(o => !o.text.trim())) return toast('Fill in every option or remove the empty ones.', true);
      await api(id ? '/api/questions/' + id : '/api/questions', { method: id ? 'PUT' : 'POST', body });
      closeModal(); toast(id ? 'Question updated.' : 'Question created.'); await refreshAll();
    });
  }
  await load();
};
