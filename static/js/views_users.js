/* Admin: user management. */
App.views.users = async function () {
  let timer;
  setView(pageHead('Users', 'Create accounts and control who can do what.', '<button class="btn primary" id="newuser">Add user</button>') +
    `<div class="toolbar"><input class="grow" id="uq" type="search" placeholder="Search name, email or roll number" aria-label="Search users">
      <select id="ur" aria-label="Filter by role"><option value="">All roles</option><option value="admin">Administrators</option><option value="examiner">Examiners</option><option value="candidate">Candidates</option></select></div>
    <div class="panel tablewrap" id="utable"></div>`);

  async function load() {
    const p = new URLSearchParams();
    if ($('#uq').value.trim()) p.set('q', $('#uq').value.trim());
    if ($('#ur').value) p.set('role', $('#ur').value);
    const users = await api('/api/users?' + p);
    $('#utable').innerHTML = !users.length ? empty('No users match', 'Try a different search or add a new user.') :
      `<table><thead><tr><th>Name</th><th>Email</th><th>Role</th><th>Roll no.</th><th>Status</th><th></th></tr></thead><tbody>
      ${users.map(u => `<tr><td><strong>${esc(u.full_name)}</strong></td><td>${esc(u.email)}</td><td>${esc(u.role)}</td>
        <td>${esc(u.roll_no || '–')}</td><td>${u.is_active ? badge('open', 'Active') : badge('off', 'Deactivated')}</td>
        <td class="right"><button class="btn sm" data-edit="${u.id}">Edit</button></td></tr>`).join('')}</tbody></table>`;
    $$('[data-edit]').forEach(b => b.onclick = () => userForm(users.find(u => u.id === +b.dataset.edit)));
  }
  $('#uq').oninput = () => { clearTimeout(timer); timer = setTimeout(() => load().catch(fail), 250); };
  $('#ur').onchange = () => load().catch(fail);
  $('#newuser').onclick = () => userForm(null);

  function userForm(u) {
    const editing = !!u;
    const dlg = openModal({
      title: editing ? 'Edit user' : 'Add user',
      body: `<form id="uf" novalidate>
        <div class="field"><label for="fn">Full name</label><input id="fn" type="text" required maxlength="120" value="${esc(u?.full_name)}"></div>
        <div class="field"><label for="fe">Email</label><input id="fe" type="email" required value="${esc(u?.email)}"></div>
        <div class="row"><div class="field"><label for="fr">Role</label><select id="fr">
          ${['candidate', 'examiner', 'admin'].map(r => `<option value="${r}" ${u?.role === r ? 'selected' : ''}>${r[0].toUpperCase() + r.slice(1)}</option>`).join('')}</select></div>
        <div class="field"><label for="fl">Roll number</label><input id="fl" type="text" maxlength="40" value="${esc(u?.roll_no)}"><span class="hint">Optional, for candidates.</span></div></div>
        <div class="field"><label for="fp">${editing ? 'New password' : 'Password'}</label><input id="fp" type="password" minlength="8" autocomplete="new-password" ${editing ? '' : 'required'}>
          <span class="hint">${editing ? 'Leave blank to keep the current password. ' : ''}At least 8 characters.</span></div>
        ${editing ? `<label class="check"><input type="checkbox" id="fa" ${u.is_active ? 'checked' : ''}><span>Account is active<small>Deactivated users cannot sign in.</small></span></label>` : ''}
      </form>`,
      footer: `<button class="btn" data-close>Cancel</button><button class="btn primary" id="usave">${editing ? 'Save changes' : 'Create user'}</button>`
    });
    $('#usave', dlg).onclick = e => busy(e.target, async () => {
      if (!$('#fn').value.trim() || !$('#fe').value.trim()) return toast('Name and email are required.', true);
      if (!editing && $('#fp').value.length < 8) return toast('Password must be at least 8 characters.', true);
      if ($('#fp').value && $('#fp').value.length < 8) return toast('Password must be at least 8 characters.', true);
      const body = { full_name: $('#fn').value, email: $('#fe').value, role: $('#fr').value, roll_no: $('#fl').value || null,
        password: $('#fp').value || null, is_active: editing ? $('#fa').checked : true };
      await api(editing ? `/api/users/${u.id}` : '/api/users', { method: editing ? 'PUT' : 'POST', body });
      closeModal(); toast(editing ? 'User updated.' : 'User created.'); await load();
    });
  }
  await load();
};
