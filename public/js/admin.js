/* e-power Super-Admin — Kunden-Accounts + globale Basis-Kalibrierung.
   Auth: Admin-Token gegen /api/admin/* (app_config['ADMIN_TOKEN']). */
(function () {
  'use strict';
  var TOKEN = sessionStorage.getItem('admin_token') || '';

  function esc(s) { return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) {
    return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]; }); }
  function msg(t, kind) {
    document.getElementById('admin-msg').innerHTML = '<div class="status-' + (kind || 'info') + '">' + esc(t) + '</div>';
  }
  function api(path, body) {
    return fetch(path, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(Object.assign({ admin_token: TOKEN }, body || {}))
    }).then(function (r) { return r.json().then(function (j) { return { ok: r.ok, j: j }; }); });
  }

  function loadFirmen() {
    api('/api/admin/firmen').then(function (o) {
      if (!o.ok) { msg((o.j && o.j.detail) || 'Kein Zugriff', 'warn'); return; }
      document.getElementById('admin-firmen-card').style.display = '';
      document.getElementById('admin-global-card').style.display = '';
      msg('Angemeldet — ' + (o.j.anzahl || 0) + ' Account(s).', 'ok');
      var tb = document.querySelector('#firmen-tbl tbody');
      tb.innerHTML = (o.j.firmen || []).map(function (f) {
        return '<tr><td>' + esc(f.name) + '</td><td>' + esc(f.email) + '</td><td>' + (f.projekte || 0) +
          '</td><td>' + (f.soll_listen || 0) + '</td><td>' + (f.gesperrt ?
            '<span class="admin-locked">gesperrt</span>' : 'aktiv') + '</td>' +
          '<td><button class="btn btn-sm btn-outline" data-lock="' + esc(f.id) + '" data-to="' +
            (f.gesperrt ? '0' : '1') + '">' + (f.gesperrt ? 'Entsperren' : 'Sperren') + '</button></td></tr>';
      }).join('');
      tb.querySelectorAll('button[data-lock]').forEach(function (b) {
        b.addEventListener('click', function () {
          api('/api/admin/firma-sperren', { firma_id: b.getAttribute('data-lock'), gesperrt: b.getAttribute('data-to') === '1' })
            .then(function (o2) { if (o2.ok) loadFirmen(); });
        });
      });
    });
  }

  document.getElementById('admin-login').addEventListener('click', function () {
    TOKEN = (document.getElementById('admin-token').value || '').trim();
    sessionStorage.setItem('admin_token', TOKEN);
    loadFirmen();
  });

  document.getElementById('nf-create').addEventListener('click', function () {
    var name = document.getElementById('nf-name').value.trim();
    var email = document.getElementById('nf-email').value.trim();
    var pass = document.getElementById('nf-pass').value;
    if (!name || !email || pass.length < 8) { msg('Name, E-Mail und Passwort (≥8) nötig.', 'warn'); return; }
    api('/api/admin/firma-anlegen', { name: name, email: email, passwort: pass }).then(function (o) {
      if (o.ok) { msg('Account angelegt: ' + esc(name), 'ok');
        document.getElementById('nf-name').value = document.getElementById('nf-email').value = document.getElementById('nf-pass').value = '';
        loadFirmen();
      } else { msg((o.j && o.j.detail) || 'Anlegen fehlgeschlagen', 'warn'); }
    });
  });

  document.getElementById('gf-save').addEventListener('click', function () {
    var faktoren = {};
    document.querySelectorAll('#global-faktoren input[data-gf]').forEach(function (i) {
      if (i.value !== '') faktoren[i.getAttribute('data-gf')] = parseFloat(i.value);
    });
    api('/api/admin/global-kalibrierung', { faktoren: faktoren }).then(function (o) {
      msg(o.ok ? 'Globale Basis gespeichert.' : ((o.j && o.j.detail) || 'Fehler'), o.ok ? 'ok' : 'warn');
    });
  });

  if (TOKEN) { document.getElementById('admin-token').value = TOKEN; loadFirmen(); }
})();
