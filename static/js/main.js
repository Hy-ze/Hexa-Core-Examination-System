/* Sign-in screen and app start. */
const DEMO = [
  ['Administrator', 'admin@exam.test', 'Admin@123'],
  ['Examiner', 'examiner@exam.test', 'Examiner@123'],
  ['Candidate', 'ayesha@exam.test', 'Candidate@123'],
];

function omrSheet() {
  const answers = [1, 3, 0, 2, 2, 1, 3, 0];
  return answers.map((a, i) => `<div class="omr-row"><b>${i + 1}</b>${['A', 'B', 'C', 'D'].map((l, j) =>
    `<span class="bubble ${j === a ? 'on' : ''}">${l}</span>`).join('')}</div>`).join('');
}

App.showLogin = function (message = '') {
  App.stopRoom?.();
  location.hash = '';
  $('#root').innerHTML = `<div class="login">
    <section class="login-art" aria-hidden="false">
      <div class="brand"><span class="brand-mark" style="border-color:#7BC4CA" aria-hidden="true"></span>ExamDesk</div>
      <div><h1>Run fair exams from first question to published result.</h1>
        <p>Timed on the server, saved as candidates type, graded and reviewed in one place.</p></div>
      <div class="omr" aria-hidden="true">${omrSheet()}</div>
    </section>
    <section class="login-form">
      <form id="loginf" novalidate>
        <h2>Sign in</h2>
        <p class="muted" style="margin-bottom:20px">Use the account your institution gave you.</p>
        <div id="lerr" class="banner bad ${message ? '' : 'hidden'}" role="alert">${esc(message)}</div>
        <div class="field"><label for="em">Email</label><input id="em" type="email" autocomplete="username" required></div>
        <div class="field"><label for="pw">Password</label><input id="pw" type="password" autocomplete="current-password" required></div>
        <button class="btn primary" style="width:100%;justify-content:center" id="lgo" type="submit">Sign in</button>
        <div class="demo"><span class="label small muted">Demo accounts (fill the form)</span>
          ${DEMO.map((d, i) => `<button type="button" data-demo="${i}"><span>${d[0]}</span><span class="muted small">${d[1]}</span></button>`).join('')}
        </div>
      </form></section></div>`;
  $$('[data-demo]').forEach(b => b.onclick = () => {
    const d = DEMO[+b.dataset.demo]; $('#em').value = d[1]; $('#pw').value = d[2]; $('#pw').focus();
  });
  $('#loginf').onsubmit = async e => {
    e.preventDefault();
    const btn = $('#lgo'), err = $('#lerr');
    err.classList.add('hidden');
    if (!$('#em').value.trim() || !$('#pw').value) { err.textContent = 'Enter your email and password.'; err.classList.remove('hidden'); return; }
    btn.disabled = true; btn.textContent = 'Signing in…';
    try {
      App.user = await api('/api/auth/login', { method: 'POST', body: { email: $('#em').value, password: $('#pw').value } });
      location.hash = HOME[App.user.role];
      showShell();
    } catch (ex) {
      err.textContent = ex.message; err.classList.remove('hidden');
      btn.disabled = false; btn.textContent = 'Sign in';
    }
  };
  $('#em').focus();
};

(async function start() {
  try { App.user = await api('/api/auth/me'); showShell(); }
  catch (e) { App.showLogin(); }
})();
