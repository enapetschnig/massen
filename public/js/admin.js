/* e-power Super-Admin — Kunden-Accounts + globale Basis-Kalibrierung.
   Auth: Admin-Token gegen /api/admin/* (app_config['ADMIN_TOKEN']). */
(function () {
  'use strict';
  var TOKEN = sessionStorage.getItem('admin_token') || '';
  var SESSION = null;   // eingeloggte Firma (localStorage) → token-freier Super-Admin-Zugang
  try { SESSION = JSON.parse(localStorage.getItem('firma') || 'null'); } catch (e) { SESSION = null; }

  function esc(s) { return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) {
    return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]; }); }
  function msg(t, kind) {
    var el = document.getElementById('admin-msg');
    if (el) { el.innerHTML = '<div class="status-' + (kind || 'info') + '">' + esc(t) + '</div>';
      el.scrollIntoView({ block: 'nearest' }); }
  }
  // Robuster API-Call: fängt Netzwerk- UND Nicht-JSON-Fehler ab (nie still scheitern).
  function api(path, body) {
    return fetch(path, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(Object.assign({ admin_token: TOKEN, auth_firma_id: SESSION && SESSION.id }, body || {}))
    }).then(function (r) {
      return r.text().then(function (txt) {
        var j = null; try { j = txt ? JSON.parse(txt) : null; } catch (e) { j = { detail: txt || ('HTTP ' + r.status) }; }
        return { ok: r.ok, status: r.status, j: j };
      });
    }).catch(function (e) { return { ok: false, status: 0, j: { detail: 'Netzwerkfehler: ' + e.message } }; });
  }

  function loadFirmen() {
    msg('Lade Accounts …', 'info');
    api('/api/admin/firmen').then(function (o) {
      if (!o.ok) {
        var tc = document.getElementById('admin-token-card'); if (tc) tc.style.display = '';
        msg('Kein automatischer Admin-Zugriff (' + o.status + ') — bitte Token eingeben.', 'warn'); return;
      }
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
            .then(function (o2) { if (o2.ok) loadFirmen(); else msg((o2.j && o2.j.detail) || 'Fehler', 'warn'); });
        });
      });
    });
  }

  document.getElementById('admin-login').addEventListener('click', function () {
    TOKEN = (document.getElementById('admin-token').value || '').trim();
    if (!TOKEN) { msg('Bitte Admin-Token eingeben.', 'warn'); return; }
    sessionStorage.setItem('admin_token', TOKEN);
    loadFirmen();
  });

  document.getElementById('nf-create').addEventListener('click', function () {
    var btn = this;
    var name = document.getElementById('nf-name').value.trim();
    var email = document.getElementById('nf-email').value.trim();
    var pass = document.getElementById('nf-pass').value;
    if (!TOKEN) { msg('Erst oben den Admin-Token laden.', 'warn'); return; }
    if (!name || !email || pass.length < 8) { msg('Name, E-Mail und Passwort (mind. 8 Zeichen) ausfüllen.', 'warn'); return; }
    btn.disabled = true; btn.textContent = 'Lege an …'; msg('Account wird angelegt …', 'info');
    api('/api/admin/firma-anlegen', { name: name, email: email, passwort: pass }).then(function (o) {
      if (o.ok) {
        msg('✓ Account angelegt: ' + name + ' (' + email + ') — kann sich jetzt einloggen.', 'ok');
        document.getElementById('nf-name').value = document.getElementById('nf-email').value = document.getElementById('nf-pass').value = '';
        loadFirmen();
      } else {
        msg('Anlegen fehlgeschlagen (' + o.status + '): ' + ((o.j && o.j.detail) || 'unbekannt'), 'warn');
      }
    }).finally(function () { btn.disabled = false; btn.textContent = 'Account anlegen'; });
  });

  document.getElementById('gf-save').addEventListener('click', function () {
    var faktoren = {};
    document.querySelectorAll('#global-faktoren input[data-gf]').forEach(function (i) {
      if (i.value !== '') faktoren[i.getAttribute('data-gf')] = parseFloat(i.value);
    });
    api('/api/admin/global-kalibrierung', { faktoren: faktoren }).then(function (o) {
      msg(o.ok ? 'Globale Basis gespeichert.' : ('Fehler (' + o.status + '): ' + ((o.j && o.j.detail) || '')), o.ok ? 'ok' : 'warn');
    });
  });

  // Auto-Login: als eingeloggter Super-Admin token-frei laden; sonst Token-Karte zeigen.
  if (SESSION && SESSION.id) { loadFirmen(); }
  else if (TOKEN) { document.getElementById('admin-token').value = TOKEN; loadFirmen(); }
  else { var tc0 = document.getElementById('admin-token-card'); if (tc0) tc0.style.display = ''; }
})();
