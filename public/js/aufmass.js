/* AUFMASS-WERKZEUG — Positionen (E4), Zuordnung (E5), Protokoll (E6).
 *
 * Eigenes Modul, bewusst NICHT in upload.js: der Monolith hat 4700 Zeilen,
 * und alles ab hier (LV, Zuordnung, Protokoll) hängt nur an der Projekt-ID
 * und den neuen /api/messungen-Endpunkten — nicht am Plan-Zeichenzustand.
 *
 * Grundsatz wie überall im Umbau: gerechnet wird auf dem Server, hier wird
 * nur angezeigt und zugewiesen. Die Formel neben jeder Zahl ist der Grund,
 * warum ein Polier dem Protokoll glaubt.
 */
(function () {
  'use strict';
  function esc(t) {
    return String(t == null ? '' : t).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }
  function fmt(x) {
    if (x == null || isNaN(x)) return '—';
    return Number(x).toLocaleString('de-AT', { maximumFractionDigits: 2 });
  }
  function einh(e) { return e === 'm2' ? 'm²' : (e === 'm3' ? 'm³' : (e || '')); }
  function pid() { return window.projectId; }
  function api(u, body) {
    return fetch(u, body ? { method: 'POST', headers: { 'Content-Type': 'application/json' },
                             body: JSON.stringify(body) } : undefined)
      .then(function (r) { return r.json(); });
  }

  var _positionen = [];
  var _messungen = [];

  /* ── E4: LV-POSITIONEN ─────────────────────────────────────────────── */
  function renderPositionen() {
    var el = document.getElementById('positionen-section');
    if (!el || !pid()) return;
    api('/api/positionen?projekt_id=' + encodeURIComponent(pid())).then(function (d) {
      _positionen = (d && d.positionen) || [];
      var rows = _positionen.map(function (p) {
        return '<tr data-pid="' + p.id + '">' +
          '<td class="pos-nr">' + esc(p.nr) + '</td>' +
          '<td>' + esc(p.bezeichnung) +
          (p.lg ? ' <span class="badge">LG ' + esc(p.lg) + '</span>' : '') + '</td>' +
          '<td>' + einh(p.einheit) + '</td>' +
          '<td>' + (p.verschnitt_pct ? fmt(p.verschnitt_pct) + ' %' : '—') + '</td>' +
          '<td>' + esc(p.quelle === 'onlv_import' ? 'ONLV' :
                       p.quelle === 'ki' ? 'aus Mengenermittlung' : 'eigene') + '</td>' +
          '<td><button type="button" class="btn btn-sm" data-pdel="' + p.id + '" ' +
          'title="Position löschen — zugeordnete Messungen bleiben, verlieren aber die Zuordnung">✕</button></td></tr>';
      }).join('');
      el.innerHTML =
        '<div class="section"><h3 class="section-title">Leistungsverzeichnis — Positionen</h3>' +
        '<p class="zuordnung-sub">Die Positionen, auf die gemessen wird. Anlegen, aus dem ' +
        'ÖNORM-LV des Auftraggebers importieren (.onlv) oder die berechneten Positionen der ' +
        'Mengenermittlung übernehmen.</p>' +
        '<div class="pos-toolbar">' +
        '<button type="button" class="btn btn-sm" id="pos-uebernehmen">⚡ Aus Mengenermittlung übernehmen</button>' +
        '<label class="btn btn-sm" for="pos-onlv" style="cursor:pointer">📄 ONLV importieren' +
        '<input type="file" id="pos-onlv" accept=".onlv,.xml" style="display:none"></label>' +
        '</div>' +
        (rows ? '<div class="tbl-scroll"><table class="data-table"><thead><tr>' +
          '<th>Nr.</th><th>Bezeichnung</th><th>Einheit</th><th>Verschnitt</th><th>Herkunft</th><th></th>' +
          '</tr></thead><tbody>' + rows + '</tbody></table></div>'
          : '<p class="mw-meta">Noch keine Positionen.</p>') +
        '<div class="pos-neu">' +
        '<input id="pn-nr" placeholder="Nr. (z.B. 1.2)" maxlength="12">' +
        '<input id="pn-bez" placeholder="Bezeichnung (z.B. Zementestrich 5 cm)">' +
        '<select id="pn-einheit"><option value="m2">m²</option><option value="m">m</option>' +
        '<option value="m3">m³</option><option value="stk">Stk</option><option value="psch">psch</option></select>' +
        '<input id="pn-ver" type="number" min="0" max="50" step="0.5" placeholder="Verschnitt %" style="width:7.5rem">' +
        '<button type="button" class="btn btn-sm btn-primary" id="pn-add">+ Position</button>' +
        '</div></div>';

      var add = document.getElementById('pn-add');
      if (add) add.addEventListener('click', function () {
        var nr = (document.getElementById('pn-nr').value || '').trim();
        var bez = (document.getElementById('pn-bez').value || '').trim();
        if (!nr || !bez) return;
        api('/api/position', {
          projekt_id: pid(), nr: nr, bezeichnung: bez,
          einheit: document.getElementById('pn-einheit').value,
          verschnitt_pct: +(document.getElementById('pn-ver').value || 0)
        }).then(function () { renderPositionen(); renderMessungZuordnung(); });
      });
      el.querySelectorAll('[data-pdel]').forEach(function (b) {
        b.addEventListener('click', function () {
          api('/api/position-loeschen', { id: b.getAttribute('data-pdel') })
            .then(function () { renderPositionen(); renderMessungZuordnung(); });
        });
      });
      var ueb = document.getElementById('pos-uebernehmen');
      if (ueb) ueb.addEventListener('click', uebernehmenAusMassen);
      var onlv = document.getElementById('pos-onlv');
      if (onlv) onlv.addEventListener('change', onlvImport);
    });
  }

  // Die berechneten LV-Positionen der KI-Mengenermittlung werden echte,
  // editierbare Positionen — einmalig, ohne Duplikate (Abgleich über Nr.).
  function uebernehmenAusMassen() {
    var data = window.projektMassenData;
    var gewerke = (data && data.gewerke) || [];
    if (!gewerke.length) { alert('Noch keine Mengenermittlung vorhanden — zuerst einen Plan analysieren.'); return; }
    var da = {}; _positionen.forEach(function (p) { da[p.nr] = true; });
    var neu = [];
    gewerke.forEach(function (g) {
      (g.positionen || []).forEach(function (po) {
        if (!po.posnr || da[po.posnr]) return;
        da[po.posnr] = true;
        neu.push({ projekt_id: pid(), nr: String(po.posnr),
                   bezeichnung: po.beschreibung || '', einheit: po.einheit || 'm2',
                   lg: String(po.lg || g.lg || ''), quelle: 'ki' });
      });
    });
    if (!neu.length) { alert('Alle Positionen sind schon übernommen.'); return; }
    var kette = Promise.resolve();
    neu.forEach(function (p) { kette = kette.then(function () { return api('/api/position', p); }); });
    kette.then(function () { renderPositionen(); renderMessungZuordnung(); });
  }

  function onlvImport(ev) {
    var f = ev.target.files && ev.target.files[0];
    if (!f) return;
    var fd = new FormData(); fd.append('datei', f);
    fetch('/api/lv-import', { method: 'POST', body: fd })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        if (!d || !d.ok) { alert('ONLV konnte nicht gelesen werden: ' + ((d && d.grund) || '')); return; }
        var da = {}; _positionen.forEach(function (p) { da[p.nr] = true; });
        var kette = Promise.resolve(), n = 0;
        (d.positionen || []).forEach(function (po) {
          if (!po.nr || da[po.nr]) return;
          da[po.nr] = true; n++;
          kette = kette.then(function () {
            return api('/api/position', {
              projekt_id: pid(), nr: String(po.nr), bezeichnung: po.stichwort || '',
              langtext: po.langtext || '', einheit: po.einheit || 'm2', quelle: 'onlv_import'
            });
          });
        });
        kette.then(function () {
          alert(n + ' Positionen aus dem ONLV übernommen.');
          renderPositionen(); renderMessungZuordnung();
        });
      });
  }

  /* ── E5: ZUORDNUNG Messung → Position ──────────────────────────────── */
  function renderMessungZuordnung() {
    var el = document.getElementById('messung-zuordnung');
    if (!el || !pid()) return;
    Promise.all([
      api('/api/messungen?projekt_id=' + encodeURIComponent(pid())),
      _positionen.length ? Promise.resolve({ positionen: _positionen })
        : api('/api/positionen?projekt_id=' + encodeURIComponent(pid()))
    ]).then(function (rr) {
      _messungen = (rr[0] && rr[0].messungen) || [];
      _positionen = (rr[1] && rr[1].positionen) || [];
      if (!_messungen.length) { el.innerHTML = ''; return; }
      var opts = '<option value="">— keine Position —</option>' + _positionen.map(function (p) {
        return '<option value="' + p.id + '">' + esc(p.nr + '  ' + p.bezeichnung) + '</option>';
      }).join('');
      var offen = 0;
      var rows = _messungen.map(function (m) {
        if (m.status === 'verworfen') return '';
        if (!m.position_id) offen++;
        return '<tr' + (m.status === 'vorschlag' ? ' class="mz-vorschlag"' : '') + '>' +
          '<td class="pos-nr">M' + (m.nummer || '?') + '</td>' +
          '<td>' + esc(m.bezeichnung || '') +
          (m.quelle === 'ki' ? ' <span class="badge">KI-Vorschlag</span>' :
           m.quelle === 'ki_bestaetigt' ? ' <span class="badge badge-ok">KI ✓</span>' : '') + '</td>' +
          '<td class="mz-formel">' + esc(m.formel || '') + '</td>' +
          '<td style="text-align:right;font-family:var(--font-mono);font-weight:700">' +
          fmt(m.wert) + ' ' + einh(m.einheit) + '</td>' +
          '<td><select class="mz-sel" data-mid="' + m.id + '">' +
          opts.replace('value="' + (m.position_id || '') + '"',
                       'value="' + (m.position_id || '') + '" selected') +
          '</select></td></tr>';
      }).join('');
      el.innerHTML =
        '<div class="section"><h3 class="section-title">Messungen den Positionen zuordnen</h3>' +
        '<p class="zuordnung-sub">Jede Messung (M-Nummer wie am Plan) bekommt ihre LV-Position. ' +
        (offen ? '<strong>' + offen + ' Messung(en) sind noch keiner Position zugeordnet</strong> — sie ' +
          'erscheinen im Protokoll unter „ohne Position", nicht in einer Summe.' : 'Alle zugeordnet.') + '</p>' +
        '<div class="tbl-scroll"><table class="data-table"><thead><tr>' +
        '<th>Nr.</th><th>Messung</th><th>Formel</th><th style="text-align:right">Wert</th><th>Position</th>' +
        '</tr></thead><tbody>' + rows + '</tbody></table></div></div>';
      el.querySelectorAll('.mz-sel').forEach(function (sel) {
        sel.addEventListener('change', function () {
          api('/api/messung', { projekt_id: pid(), id: sel.getAttribute('data-mid'),
                                position_id: sel.value || null })
            .then(function () { renderProtokoll(); });
        });
      });
    });
  }

  /* ── E6: AUFMASSPROTOKOLL ──────────────────────────────────────────── */
  function renderProtokoll() {
    var el = document.getElementById('protokoll-section');
    if (!el || !pid()) return;
    api('/api/aufmass-protokoll?projekt_id=' + encodeURIComponent(pid())).then(function (d) {
      if (!d || !d.ok) { el.innerHTML = ''; return; }
      var bloecke = (d.positionen || []).filter(function (p) { return p.n_messungen > 0; });
      if (!bloecke.length && !d.n_ohne_position) { el.innerHTML = ''; return; }
      var html = bloecke.map(function (p) {
        return '<div class="prot-pos"><div class="prot-kopf"><span class="pos-nr">' + esc(p.nr) +
          '</span> ' + esc(p.bezeichnung) + '<span class="prot-summe">' + fmt(p.endsumme) + ' ' +
          einh(p.einheit) + '</span></div>' +
          '<table class="data-table"><tbody>' +
          p.zeilen.map(function (z) {
            return '<tr><td class="pos-nr">M' + (z.nummer || '?') + '</td>' +
              '<td>' + esc(z.bezeichnung || '') + (z.typ === 'abzug' ? ' <span class="badge">Abzug</span>' : '') + '</td>' +
              '<td class="mz-formel">' + esc(z.formel || '') + '</td>' +
              '<td style="text-align:right;font-family:var(--font-mono)">' +
              (z.typ === 'abzug' ? '−' : '') + fmt(z.wert) + '</td></tr>';
          }).join('') +
          '<tr class="prot-sum-z"><td colspan="3">Summe' +
          (p.verschnitt_pct ? ' + ' + fmt(p.verschnitt_pct) + ' % Verschnitt' : '') + '</td>' +
          '<td style="text-align:right;font-family:var(--font-mono);font-weight:700">' +
          fmt(p.endsumme) + ' ' + einh(p.einheit) + '</td></tr>' +
          '</tbody></table></div>';
      }).join('');
      if (d.n_ohne_position) {
        html += '<div class="prot-pos prot-warn"><div class="prot-kopf">Ohne Position (' +
          d.n_ohne_position + ') — nicht in den Summen</div><table class="data-table"><tbody>' +
          (d.ohne_position || []).map(function (z) {
            return '<tr><td class="pos-nr">M' + (z.nummer || '?') + '</td><td>' +
              esc(z.bezeichnung || '') + '</td><td style="text-align:right;font-family:var(--font-mono)">' +
              fmt(z.wert) + ' ' + einh(z.einheit) + '</td></tr>';
          }).join('') + '</tbody></table></div>';
      }
      el.innerHTML =
        '<div class="section" id="prot-print"><h3 class="section-title">Aufmaßprotokoll ' +
        '<button type="button" class="btn btn-sm" id="prot-drucken">🖨 Drucken / PDF</button> ' +
        '<a class="btn btn-sm" id="prot-plan" href="/api/aufmassplan?projekt_id=' +
        encodeURIComponent(pid()) + '" download>🗺 Aufmaßplan (PDF)</a></h3>' +
        '<p class="zuordnung-sub">Jede Zeile ist eine Messung am Plan (M-Nummer), mit der Formel, ' +
        'aus der ihr Wert entstanden ist. Dieses Protokoll liegt der Rechnung bei.</p>' +
        html + '</div>';
      var dr = document.getElementById('prot-drucken');
      if (dr) dr.addEventListener('click', function () { window.print(); });
    });
  }

  window.renderAufmassBereiche = function () {
    renderPositionen();
    renderMessungZuordnung();
    renderProtokoll();
  };
})();
