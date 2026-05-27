/**
 * KI-Massenermittlung - Upload & Plaene (direkt via Supabase)
 */
(function () {
  'use strict';

  var firma = requireAuth();
  if (!firma) return;

  var params = new URLSearchParams(window.location.search);
  var projectId = params.get('id');
  if (!projectId) { window.location.href = 'dashboard.html'; return; }

  var companyNameEl = document.getElementById('company-name');
  var logoutBtn = document.getElementById('logout-btn');
  var projectNameEl = document.getElementById('project-name');
  var projectAddressEl = document.getElementById('project-address');
  var projectStatusEl = document.getElementById('project-status');
  var uploadZone = document.getElementById('upload-zone');
  var fileInput = document.getElementById('file-input');
  var uploadProgress = document.getElementById('upload-progress');
  var uploadBar = document.getElementById('upload-bar');
  var planList = document.getElementById('plan-list');
  var plansEmpty = document.getElementById('plans-empty');
  var plansLoading = document.getElementById('plans-loading');
  var progressSection = document.getElementById('progress-section');
  var analysisBar = document.getElementById('analysis-bar');
  var progressStatus = document.getElementById('progress-status');
  var analysisError = document.getElementById('analysis-error');

  // Agent-Stepper Elemente
  var agentIds = ['agent-parser', 'agent-geometrie', 'agent-kalkulation', 'agent-kritik'];

  if (firma.name && companyNameEl) companyNameEl.textContent = firma.name;
  if (logoutBtn) logoutBtn.addEventListener('click', function () { clearSession(); window.location.href = 'index.html'; });

  // Projekt laden
  _sb.from('projekte').select('*').eq('id', projectId).single().then(function (res) {
    if (res.data) {
      projectNameEl.textContent = res.data.name || '';
      projectAddressEl.textContent = res.data.adresse || '';
      var status = res.data.status || 'Neu';
      projectStatusEl.textContent = status;
      projectStatusEl.className = 'badge badge-' + statusClass(status);
    }
  });

  function statusClass(status) {
    var s = (status || '').toLowerCase();
    if (s === 'fertig' || s === 'abgeschlossen') return 'fertig';
    if (s === 'analyse' || s === 'in bearbeitung') return 'analyse';
    if (s === 'fehler') return 'fehler';
    return 'neu';
  }

  // --- Plaene laden ---
  function loadPlans() {
    if (plansLoading) plansLoading.style.display = 'flex';
    plansEmpty.classList.add('hidden');
    _sb.from('plaene').select('*').eq('projekt_id', projectId).order('hochgeladen_am', { ascending: false }).then(function (res) {
      if (plansLoading) plansLoading.style.display = 'none';
      var plans = res.data || [];
      renderPlans(plans);
      // Plans-Count-Badge im Section-Titel
      var fertigCount = plans.filter(function (p) { return p.verarbeitet === true; }).length;
      var countEl = document.getElementById('plans-count');
      if (countEl) {
        if (plans.length === 0) {
          countEl.textContent = '';
        } else if (fertigCount === plans.length) {
          countEl.innerHTML = '<span class="plans-count-badge ok">' + plans.length + ' fertig analysiert</span>';
        } else {
          countEl.innerHTML = '<span class="plans-count-badge work">' + fertigCount + ' von ' + plans.length + ' analysiert</span>';
        }
      }
      // Ergebnis-Section nur, wenn mindestens ein Plan fertig analysiert ist.
      if (fertigCount >= 1) {
        loadProjektMassen(fertigCount, plans.length);
      } else {
        var sec = document.getElementById('ergebnis-section');
        if (sec) sec.classList.add('hidden');
      }
    });
  }

  // --- Filter-State für Projekt-Massen (in Memory, kein localStorage) ---
  var _filterState = {
    gewerke: null,           // null = alle, sonst array
    plan_ids: null,          // null = alle, sonst array
    baudaten_override: null, // {key:value} oder null
    materialliste_override: null, // {key:value} oder null
  };

  function bindFilterControls() {
    // Gewerk-Chips → State
    var gwBox = document.getElementById('filter-gewerke');
    if (gwBox && !gwBox.dataset.bound) {
      gwBox.dataset.bound = '1';
      gwBox.addEventListener('change', function (e) {
        var checks = gwBox.querySelectorAll('input[data-gw]');
        var sel = [];
        checks.forEach(function (c) { if (c.checked) sel.push(c.getAttribute('data-gw')); });
        _filterState.gewerke = (sel.length === checks.length || sel.length === 0) ? null : sel;
        refreshProjektMassen();
      });
    }
    // Plan-Chips (werden in renderPlanFilter befüllt)
    // Baudaten-Apply / Reset
    var apply = document.getElementById('filter-baudaten-apply');
    if (apply && !apply.dataset.bound) {
      apply.dataset.bound = '1';
      apply.addEventListener('click', function () {
        var inputs = document.querySelectorAll('#filter-baudaten input[data-bd]');
        var ov = {};
        inputs.forEach(function (i) {
          var v = i.value.trim();
          if (v !== '') {
            var n = parseFloat(v.replace(',', '.'));
            if (!isNaN(n) && n > 0) ov[i.getAttribute('data-bd')] = n;
          }
        });
        _filterState.baudaten_override = Object.keys(ov).length ? ov : null;
        refreshProjektMassen();
      });
    }
    var reset = document.getElementById('filter-baudaten-reset');
    if (reset && !reset.dataset.bound) {
      reset.dataset.bound = '1';
      reset.addEventListener('click', function () {
        document.querySelectorAll('#filter-baudaten input[data-bd]').forEach(function (i) { i.value = ''; });
        _filterState.baudaten_override = null;
        refreshProjektMassen();
      });
    }
    // Materialliste-Annahmen: Apply / Reset
    var mlApply = document.getElementById('materialliste-apply');
    if (mlApply && !mlApply.dataset.bound) {
      mlApply.dataset.bound = '1';
      mlApply.addEventListener('click', function () {
        var inputs = document.querySelectorAll('#materialliste-annahmen-grid input[data-ml]');
        var ov = {};
        inputs.forEach(function (i) {
          var v = i.value.trim();
          if (v !== '') {
            var n = parseFloat(v.replace(',', '.'));
            if (!isNaN(n)) ov[i.getAttribute('data-ml')] = n;
          }
        });
        _filterState.materialliste_override = Object.keys(ov).length ? ov : null;
        refreshProjektMassen();
      });
    }
    var mlReset = document.getElementById('materialliste-reset');
    if (mlReset && !mlReset.dataset.bound) {
      mlReset.dataset.bound = '1';
      mlReset.addEventListener('click', function () {
        document.querySelectorAll('#materialliste-annahmen-grid input[data-ml]').forEach(function (i) { i.value = ''; });
        _filterState.materialliste_override = null;
        refreshProjektMassen();
      });
    }
  }

  function renderPlanFilter(plaeneManifest) {
    var box = document.getElementById('filter-plaene');
    if (!box || !plaeneManifest) return;
    box.innerHTML = plaeneManifest.map(function (p) {
      var checked = p.selected ? ' checked' : '';
      return '<label class="projekt-chip"><input type="checkbox" data-plan="' + esc(p.id) + '"' + checked + '> ' +
        esc((p.dateiname || '').slice(0, 40)) + '</label>';
    }).join('');
    if (!box.dataset.bound) {
      box.dataset.bound = '1';
      box.addEventListener('change', function () {
        var checks = box.querySelectorAll('input[data-plan]');
        var sel = [];
        checks.forEach(function (c) { if (c.checked) sel.push(c.getAttribute('data-plan')); });
        _filterState.plan_ids = (sel.length === checks.length || sel.length === 0) ? null : sel;
        refreshProjektMassen();
      });
    }
  }

  // Letzte Werte für Refresh (ohne Plans-Liste neu zu laden)
  var _lastFertig = 0, _lastTotal = 0;
  function refreshProjektMassen() {
    if (_lastFertig > 0) loadProjektMassen(_lastFertig, _lastTotal);
  }

  // --- Projekt-weite Massenermittlung (gemerged über alle Pläne) ---
  function loadProjektMassen(fertigCount, totalCount) {
    var sec = document.getElementById('ergebnis-section');
    if (!sec) return;
    var badge = document.getElementById('projekt-massen-badge');
    var info = document.getElementById('projekt-massen-info');
    var grid = document.getElementById('projekt-massen-grid');
    var detail = document.getElementById('projekt-massen-detail');
    var detailWrap = document.getElementById('projekt-massen-detail-wrap');

    sec.classList.remove('hidden');
    _lastFertig = fertigCount; _lastTotal = totalCount;
    bindFilterControls();
    bindErgebnisTabs();
    bindProjektExport();
    if (badge) badge.textContent = 'lädt...';
    if (info) info.textContent = '';
    if (grid) grid.innerHTML = '<div class="loading" style="padding:1rem"><div class="spinner"></div> Räume aller Pläne werden zusammengeführt...</div>';
    if (detail) detail.innerHTML = '';
    if (detailWrap) detailWrap.style.display = 'none';

    var payload = { projekt_id: projectId };
    if (_filterState.gewerke) payload.gewerke_filter = _filterState.gewerke;
    if (_filterState.plan_ids) payload.plan_ids = _filterState.plan_ids;
    if (_filterState.baudaten_override) payload.baudaten_override = _filterState.baudaten_override;
    if (_filterState.materialliste_override) payload.materialliste_override = _filterState.materialliste_override;

    fetch('/api/projekt-massen', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (data) {
        if (!data || data.status !== 'ok') {
          if (badge) badge.textContent = '';
          if (grid) grid.innerHTML = '<p style="color:#92400e">Projekt-Massen konnten nicht berechnet werden — Detail-Ansicht im Plan öffnen.</p>';
          return;
        }
        renderProjektMassen(data, fertigCount, totalCount);
      })
      .catch(function () {
        if (badge) badge.textContent = '';
        if (grid) grid.innerHTML = '<p style="color:#92400e">Netzwerk-Fehler bei Projekt-Massen.</p>';
      });
  }

  function renderProjektMassen(data, fertigCount, totalCount) {
    var badge = document.getElementById('projekt-massen-badge');
    var info = document.getElementById('projekt-massen-info');
    var grid = document.getElementById('projekt-massen-grid');
    var detail = document.getElementById('projekt-massen-detail');
    var detailWrap = document.getElementById('projekt-massen-detail-wrap');

    if (badge) {
      var bt = data.plaene_count + ' Pl' + (data.plaene_count === 1 ? 'an' : 'äne') +
        ' · ' + data.raeume_count + ' Räume';
      if (data.merge_enrichments > 0) bt += ' · ' + data.merge_enrichments + ' Lücken gefüllt';
      badge.textContent = bt;
    }

    // Plan-Filter-Chips befüllen
    if (data.plaene) renderPlanFilter(data.plaene);

    // Status-Banner: was hat die App erkannt?
    var statusEl = document.getElementById('ergebnis-status-banner');
    if (statusEl) {
      var hints = [];
      // Räume ohne H prüfen — typisches Symptom für fehlenden Polierplan
      var raeumeOhneH = (data.raeume || []).filter(function(r){
        return r && r.flaeche_m2 && !r.hoehe_m;
      });
      if (raeumeOhneH.length > 0 && data.plaene_count === 1) {
        hints.push('<div class="status-warn">⚠ <strong>' + raeumeOhneH.length +
          ' Räume ohne Höhen-Wert</strong> — der Einreichplan hat nur F+U, ' +
          'die Raumhöhen stehen im Polierplan. ' +
          '<strong>Lade auch den Polierplan hoch</strong>, sonst werden alle ' +
          'Wand-, Putz-, Maler-Mengen mit Default-Geschosshöhe (2,70m) gerechnet.</div>');
      } else if (data.h_inferred_count > 0) {
        // Polierplan ist dabei aber nicht alle Räume haben H — wir haben
        // den Median-Wert verwendet
        hints.push('<div class="status-info">ℹ ' + data.h_inferred_count +
          ' Räume hatten keine H im Plan → Wert <strong>' +
          fmtNum(data.h_inferred_value) + ' m</strong> aus Median der anderen Räume ergänzt. ' +
          'Geschoss-Höhe für Putz/Maler/Estrich übernommen.</div>');
      } else if (raeumeOhneH.length > 0) {
        hints.push('<div class="status-info">ℹ ' + raeumeOhneH.length +
          ' Räume ohne H — Default-Geschosshöhe wird verwendet.</div>');
      }
      if (data.fenster_count === 0) {
        hints.push('<div class="status-warn">⚠ <strong>0 Fenster erkannt</strong> — Laibungen, Rolladenkästen und Ziegelüberlagen werden pauschal geschätzt. Vision hat im Grundriss keine Fenster gefunden.</div>');
      } else {
        hints.push('<div class="status-ok">✓ ' + data.fenster_count + ' Fenster aus Vision/Plan erkannt</div>');
      }
      if (data.halluzinationen && data.halluzinationen.length) {
        hints.push('<div class="status-info">🧹 ' + data.halluzinationen.length + ' Vision-Halluzination(en) gefiltert: ' +
          data.halluzinationen.map(function(h){ return esc(h.name); }).join(', ') + '</div>');
      }
      hints.push('<div class="status-room-count">📐 ' + data.raeume_count + ' Räume · ' + (data.plaene_count || '?') + ' Plan' + (data.plaene_count===1?'':'e') + '</div>');
      statusEl.innerHTML = hints.join('');
    }
    if (info) {
      var bd = data.baudaten || {};
      var bq = bd._quellen || {};
      function bdItem(label, key, unit) {
        if (bd[key] == null) return '';
        var src = bq[key] === 'vision' ? '👁' : '≈';
        return '<span style="margin-right:0.8rem">' + label + ' <strong>' + bd[key] + unit + '</strong> ' + src + '</span>';
      }
      info.innerHTML = 'Bau-Kenndaten: ' +
        bdItem('Außenwand', 'aussenwand_cm', 'cm') +
        bdItem('Decke', 'decke_cm', 'cm') +
        bdItem('Bodenplatte', 'bodenplatte_cm', 'cm') +
        bdItem('Geschoss-H', 'geschosshoehe_m', 'm') +
        '<span style="color:#6c757d;font-size:0.78rem;margin-left:0.5rem">👁 = aus Plan gemessen · ≈ = Standard-Annahme</span>';
    }

    // Kacheln pro Hauptposition jedes Gewerks (1.1)
    var gw = data.gewerke || {};
    var cards = [];
    Object.keys(gw).forEach(function (gk) {
      var g = gw[gk];
      var label = (g.label || gk).replace(/\s*\(.*\)/, '');
      (g.positionen || []).forEach(function (p) {
        if (p.posnr === '1.1' || p.posnr === '1.2' || p.posnr === '1.3') {
          var konf = Math.round((p.konfidenz || 0) * 100);
          var warn = konf < 65;
          cards.push({
            gewerk: label,
            text: p.beschreibung || '',
            wert: p.endsumme || 0,
            einheit: p.einheit || '',
            konf: konf,
            warn: warn
          });
        }
      });
    });

    if (grid) {
      if (!cards.length) {
        grid.innerHTML = '<p style="color:#92400e">Keine Massen ermittelt — Pläne enthalten noch keine vollständigen Raumdaten.</p>';
      } else {
        grid.innerHTML = cards.map(function (c) {
          return '<div class="projekt-massen-card">' +
            '<div class="projekt-massen-card-label">' + esc(c.gewerk) + '</div>' +
            '<div style="font-size:0.78rem;color:#6c757d;margin-bottom:0.3rem">' + esc(c.text) + '</div>' +
            '<div class="projekt-massen-card-value">' + fmtNum(c.wert) +
              '<span class="projekt-massen-card-unit">' + esc(c.einheit) + '</span></div>' +
            '<div class="projekt-massen-card-konf' + (c.warn ? ' warn' : '') + '">Konfidenz ' + c.konf + '%</div>' +
            '</div>';
        }).join('');
      }
    }

    if (detail && detailWrap) {
      detailWrap.style.display = '';
      var html = '<table><thead><tr><th>Gewerk</th><th>Pos</th><th>Beschreibung</th><th class="num">Wert</th><th>Einheit</th><th class="num">Konf</th></tr></thead><tbody>';
      Object.keys(gw).forEach(function (gk) {
        var g = gw[gk];
        var label = (g.label || gk).replace(/\s*\(.*\)/, '');
        (g.positionen || []).forEach(function (p) {
          html += '<tr><td>' + esc(label) + '</td><td>' + esc(p.posnr || '') + '</td><td>' + esc(p.beschreibung || '') +
            '</td><td class="num">' + fmtNum(p.endsumme) + '</td><td>' + esc(p.einheit || '') + '</td><td class="num">' +
            Math.round((p.konfidenz || 0) * 100) + '%</td></tr>';
        });
      });
      html += '</tbody></table>';
      detail.innerHTML = html;
    }

    // Hinweis bei noch nicht analysierten Plänen
    if (totalCount > fertigCount) {
      var hint = '<div style="color:#92400e;font-size:0.82rem;margin-top:0.4rem">⏳ ' +
        (totalCount - fertigCount) + ' Plan' + (totalCount - fertigCount === 1 ? '' : 'e') +
        ' noch nicht analysiert — Massen aktualisieren sich automatisch nach Abschluss.</div>';
      if (info) info.innerHTML += hint;
    }

    // Räume-Liste rendern (was die KI gefunden hat)
    renderRoomsList(data.raeume);

    // Materialliste rendern
    renderMaterialliste(data.materialliste);
  }

  function renderRoomsList(raeume) {
    var target = document.getElementById('projekt-massen-rooms');
    if (!target || !raeume) return;
    var html = '<table style="width:100%;border-collapse:collapse;font-size:0.82rem">';
    html += '<thead><tr><th style="text-align:left;padding:0.3rem 0.5rem;background:#f8fafc">Raum</th>' +
            '<th class="num" style="text-align:right;padding:0.3rem 0.5rem;background:#f8fafc">F (m²)</th>' +
            '<th class="num" style="text-align:right;padding:0.3rem 0.5rem;background:#f8fafc">U (m)</th>' +
            '<th class="num" style="text-align:right;padding:0.3rem 0.5rem;background:#f8fafc">H (m)</th>' +
            '<th style="text-align:left;padding:0.3rem 0.5rem;background:#f8fafc">Boden</th>' +
            '<th style="text-align:center;padding:0.3rem 0.5rem;background:#f8fafc">Quellen</th></tr></thead><tbody>';
    raeume.forEach(function(r){
      var quellen = (r._quellen_plaene || []).length;
      var merged = (r._merged_from || []).join(',');
      html += '<tr>' +
        '<td style="padding:0.3rem 0.5rem;border-bottom:1px solid #f1f3f5">' + esc(r.name || '?') + '</td>' +
        '<td class="num" style="text-align:right;padding:0.3rem 0.5rem;border-bottom:1px solid #f1f3f5">' + (r.flaeche_m2 ? fmtNum(r.flaeche_m2) : '<span style="color:#dc2626">–</span>') + '</td>' +
        '<td class="num" style="text-align:right;padding:0.3rem 0.5rem;border-bottom:1px solid #f1f3f5">' + (r.umfang_m ? fmtNum(r.umfang_m) : '<span style="color:#dc2626">–</span>') + '</td>' +
        '<td class="num" style="text-align:right;padding:0.3rem 0.5rem;border-bottom:1px solid #f1f3f5">' + (r.hoehe_m ? fmtNum(r.hoehe_m) : '<span style="color:#dc2626">–</span>') + '</td>' +
        '<td style="padding:0.3rem 0.5rem;border-bottom:1px solid #f1f3f5">' + esc(r.bodenbelag || '') + '</td>' +
        '<td style="text-align:center;padding:0.3rem 0.5rem;border-bottom:1px solid #f1f3f5" title="' + esc(merged) + '">' + quellen + ' Plan' + (quellen===1?'':'') + (merged ? ' <small style="color:#16a34a">✓merged</small>' : '') + '</td>' +
        '</tr>';
    });
    html += '</tbody></table>';
    target.innerHTML = html;
  }

  function renderMaterialliste(ml) {
    // Materialliste lebt jetzt als Tab innerhalb der ergebnis-section
    var panel = document.getElementById('ergebnis-panel-material');
    var tab = document.querySelector('.ergebnis-tab[data-ergtab="material"]');
    if (!panel || !tab) return;
    var tbody = document.querySelector('#materialliste-table tbody');
    if (!ml || ml.error || !ml.bauteile) {
      tab.style.display = 'none';
      if (tbody) tbody.innerHTML = '';
      return;
    }
    tab.style.display = '';
    if (!tbody) return;
    var html = '';
    Object.keys(ml.bauteile).forEach(function (bauteil) {
      html += '<tr class="bauteil-head"><td colspan="6">' + esc(bauteil) + '</td></tr>';
      ml.bauteile[bauteil].forEach(function (p) {
        var konf = Math.round((p.konfidenz || 0) * 100);
        var konfClass = konf >= 70 ? 'hoch' : (konf >= 50 ? 'mittel' : 'niedrig');
        html += '<tr>' +
          '<td></td>' +
          '<td>' + esc(p.material || '') + '</td>' +
          '<td class="num">' + fmtNum(p.menge) + '</td>' +
          '<td>' + esc(p.einheit || '') + '</td>' +
          '<td class="num"><span class="materialliste-konf-badge ' + konfClass + '">' + konf + '%</span></td>' +
          '<td class="formel">' + esc(p.formel || '') + '</td>' +
          '</tr>';
      });
    });
    tbody.innerHTML = html;
  }

  function fmtNum(n) {
    if (n == null || isNaN(n)) return '–';
    return Number(n).toLocaleString('de-AT', { maximumFractionDigits: 2 });
  }

  // ─── Projekt-Export-Button (CSV mit allen Daten + Materialliste) ───
  function bindProjektExport() {
    var btn = document.getElementById('projekt-export-btn');
    if (!btn || btn.dataset.bound) return;
    btn.dataset.bound = '1';
    btn.addEventListener('click', function () {
      btn.disabled = true;
      var orig = btn.innerHTML;
      btn.textContent = 'Wird exportiert...';
      var payload = { projekt_id: projectId };
      if (_filterState.gewerke) payload.gewerke_filter = _filterState.gewerke;
      if (_filterState.plan_ids) payload.plan_ids = _filterState.plan_ids;
      if (_filterState.baudaten_override) payload.baudaten_override = _filterState.baudaten_override;
      if (_filterState.materialliste_override) payload.materialliste_override = _filterState.materialliste_override;
      fetch('/api/projekt-export', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      })
        .then(function (r) { if (!r.ok) throw new Error('Export-Status ' + r.status); return r.blob(); })
        .then(function (blob) {
          var url = window.URL.createObjectURL(blob);
          var a = document.createElement('a');
          a.href = url;
          a.download = 'projekt-massenermittlung-' + (projectId || 'export').slice(0,8) + '.csv';
          document.body.appendChild(a); a.click(); document.body.removeChild(a);
          window.URL.revokeObjectURL(url);
        })
        .catch(function (e) { alert('Export-Fehler: ' + e.message); })
        .finally(function () { btn.disabled = false; btn.innerHTML = orig; });
    });
  }

  // ─── Tab-Wechsel innerhalb der Ergebnis-Section ───
  function bindErgebnisTabs() {
    var tabs = document.querySelectorAll('.ergebnis-tab');
    if (!tabs.length || tabs[0].dataset.bound) return;
    tabs.forEach(function (t) {
      t.dataset.bound = '1';
      t.addEventListener('click', function () {
        var which = t.getAttribute('data-ergtab');
        document.querySelectorAll('.ergebnis-tab').forEach(function (x) { x.classList.toggle('active', x === t); });
        document.querySelectorAll('.ergebnis-panel').forEach(function (p) {
          p.classList.toggle('active', p.id === 'ergebnis-panel-' + which);
        });
      });
    });
  }

  function renderPlans(plans) {
    planList.innerHTML = '';
    if (!plans.length) { plansEmpty.classList.remove('hidden'); return; }
    plansEmpty.classList.add('hidden');

    plans.forEach(function (plan) {
      var card = document.createElement('div');
      card.className = 'card plan-card';
      var done = plan.verarbeitet === true;
      var konfBadge = '';
      if (done && plan.gesamt_konfidenz != null) {
        var kVal = Math.round(plan.gesamt_konfidenz);
        var kClass = kVal >= 80 ? 'confidence-green' : (kVal >= 60 ? 'confidence-yellow' : 'confidence-red');
        konfBadge = ' <span class="confidence ' + kClass + '"><span class="confidence-dot dot-red"></span><span class="confidence-dot dot-yellow"></span><span class="confidence-dot dot-green"></span><span class="confidence-value">' + kVal + '%</span></span>';
      }

      // Done-Karten sind komplett klickbar - direkt zur Planansicht
      if (done) {
        card.classList.add('plan-card-clickable');
        card.setAttribute('data-plan-id', plan.id);
        card.title = 'Klicken um Ergebnisse und Korrektur-Ansicht zu öffnen';
      }
      card.innerHTML =
        '<div class="plan-info"><div class="plan-icon">&#128196;</div><div>' +
          '<div class="plan-name">' + esc(plan.dateiname || '') + '</div>' +
          '<div class="plan-status"><span class="badge ' + (done ? 'badge-fertig' : 'badge-neu') + '">' + (done ? 'Fertig' : 'Hochgeladen') + '</span>' + konfBadge + (done ? ' <span style="font-size:0.75rem;color:#6c757d">· klicken zum Öffnen</span>' : '') + '</div>' +
        '</div></div>' +
        '<div class="plan-actions">' +
          (done
            ? '<button class="btn btn-primary btn-sm res-btn" data-id="' + plan.id + '">&Ouml;ffnen</button>' +
              '<button class="btn btn-outline btn-sm reana-btn" data-id="' + plan.id + '" title="Erneut analysieren">&#8635;</button>'
            : '<button class="btn btn-accent btn-sm ana-btn" data-id="' + plan.id + '">Analyse starten</button>') +
          '<button class="btn-delete-plan" data-id="' + plan.id + '">&times;</button>' +
        '</div>';
      planList.appendChild(card);
    });

    // Ergebnisse-Button
    planList.querySelectorAll('.res-btn').forEach(function (b) {
      b.addEventListener('click', function (e) {
        e.stopPropagation();
        if (window.loadResults) window.loadResults(this.getAttribute('data-id'));
      });
    });

    // Karte direkt klickbar (wenn done)
    planList.querySelectorAll('.plan-card-clickable').forEach(function (c) {
      c.addEventListener('click', function (e) {
        // Klick auf Buttons / Inputs / Selects soll Karte-Click nicht triggern
        if (e.target.closest('button, input, select')) return;
        var pid = c.getAttribute('data-plan-id');
        if (pid && window.loadResults) window.loadResults(pid);
      });
    });

    // Analyse-Button
    planList.querySelectorAll('.ana-btn').forEach(function (b) {
      b.addEventListener('click', function () {
        var btn = this;
        var planId = btn.getAttribute('data-id');
        startAnalysis(planId, btn);
      });
    });

    // Neu-analysieren-Button
    planList.querySelectorAll('.reana-btn').forEach(function (b) {
      b.addEventListener('click', function () {
        var btn = this;
        var planId = btn.getAttribute('data-id');
        startAnalysis(planId, btn);
      });
    });

    // Loeschen-Button
    planList.querySelectorAll('.btn-delete-plan').forEach(function (b) {
      b.addEventListener('click', function (e) {
        e.stopPropagation();
        if (confirm('Plan wirklich loeschen?')) {
          _sb.from('plaene').delete().eq('id', this.getAttribute('data-id')).then(loadPlans);
        }
      });
    });
  }

  // --- Analyse starten (3 Schritte nacheinander) ---
  // btn ist optional: beim Auto-Flow (direkt nach Upload) gibt es keinen Button.
  // onDone ist optional: Callback nach Abschluss (für die Auto-Queue).
  function startAnalysis(planId, btn, onDone) {
    if (btn) {
      btn.disabled = true;
      btn.textContent = 'KI analysiert...';
    }

    // Parameter aus DOM-Inputs lesen, falls vorhanden — sonst Defaults.
    // Beim Auto-Flow existieren die Karten-Inputs noch nicht.
    var gewSel = document.querySelector('.gewerk-select[data-id="'+planId+'"]');
    var gesInp = document.querySelector('.geschoss-input[data-id="'+planId+'"]');
    var whgInp = document.querySelector('.whg-og-input[data-id="'+planId+'"]');
    var gewerk = gewSel ? gewSel.value : 'allgemein';
    var geschosse = gesInp ? (parseInt(gesInp.value) || 3) : 3;
    var whg_pro_og = whgInp ? (parseInt(whgInp.value) || 4) : 4;

    if (analysisError) { analysisError.classList.add('hidden'); analysisError.textContent = ''; }
    showProgress();

    function callStep(step) {
      return fetch(SUPABASE_URL + '/functions/v1/orchestrator', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + SUPABASE_ANON_KEY },
        body: JSON.stringify({ plan_id: planId, step: step, gewerk: gewerk, geschosse: geschosse, whg_pro_og: whg_pro_og })
      }).then(function (res) {
        return res.json().then(function (data) {
          if (!res.ok || data.error) throw new Error(data.error || 'Schritt ' + step + ' fehlgeschlagen');
          return data;
        });
      });
    }

    // Zoom-Section Analyse: rendert PDF in High-DPI Abschnitten und lässt Claude jeden lesen
    setStepActive(0);
    if (progressStatus) progressStatus.textContent = 'Schritt 1/2: PDF-Abschnitte werden in hoher Auflösung analysiert (Zoom)...';
    if (analysisBar) { analysisBar.style.width = '10%'; analysisBar.textContent = '10%'; }

    fetch('/api/analyse-zoom', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ plan_id: planId })
    })
      .then(function(res) {
        // Try to parse JSON, but if response is HTML (404/500 page) show raw text
        var ct = res.headers.get('content-type') || '';
        if (!ct.includes('json')) {
          return res.text().then(function(text) {
            throw new Error('Server-Fehler ' + res.status + ': ' + text.slice(0, 200));
          });
        }
        return res.json().then(function(data) {
          if (!res.ok || data.error) throw new Error('Status ' + res.status + ': ' + (data.error || data.detail || JSON.stringify(data).slice(0,200)));
          console.log('Zoom-Analyse:', data.sections_analyzed, 'Abschnitte,', data.raeume, 'Räume,', data.fenster, 'Fenster');
          setStepDone(0); setStepActive(1);
          if (progressStatus) progressStatus.textContent = 'Schritt 2/2: Massen werden berechnet... (' + (data.raeume || 0) + ' Räume, ' + (data.fenster || 0) + ' Fenster)';
          if (analysisBar) { analysisBar.style.width = '40%'; analysisBar.textContent = '40%'; }
          return data;
        });
      })
      .then(function () {
        // ── KRITISCHER TEIL FERTIG ──
        // analyse-zoom hat Räume + ÖNORM-LV in agent_log + elemente gespeichert.
        // Die Massen-Berechnung (Step 2) + Kritik (Step 3) sind ein BONUS:
        // sie befüllen die massen-Tabelle. Schlagen sie fehl, zeigen wir
        // trotzdem die Plan-Ergebnisse — kein harter Abbruch mehr.
        return callStep(2).then(function (r2) {
          setStepDone(1); setStepActive(2);
          if (progressStatus) progressStatus.textContent = 'Qualitätsprüfung... (' + (r2.massen || 0) + ' Positionen)';
          if (analysisBar) { analysisBar.style.width = '70%'; analysisBar.textContent = '70%'; }
          return callStep(3).catch(function (e) {
            console.warn('Step 3 (Kritik) übersprungen:', e.message);
            return null;
          });
        }).catch(function (e) {
          console.warn('Massen-Berechnung (Step 2/3) übersprungen:', e.message);
          return null;
        });
      })
      .then(function (r3) {
        setStepDone(1); setStepDone(2); setStepDone(3);
        if (analysisBar) { analysisBar.style.width = '100%'; analysisBar.textContent = '100%'; }
        var konfText = (r3 && r3.konfidenz != null) ? ' Konfidenz: ' + r3.konfidenz + '%' : '';
        if (progressStatus) progressStatus.textContent = 'Analyse abgeschlossen!' + konfText;
        setTimeout(function () {
          hideProgress();
          if (window.loadResults) window.loadResults(planId);
          loadPlans();
          if (typeof onDone === 'function') onDone(true);
        }, 1200);
      })
      .catch(function (err) {
        // Hierher kommt nur, wenn analyse-zoom selbst fehlschlägt
        // (kein PDF lesbar, Server-Fehler) — das ist der echte harte Fehler.
        hideProgress();
        if (btn) {
          btn.disabled = false;
          btn.textContent = 'Analyse starten';
        }
        if (analysisError) {
          analysisError.textContent = 'Analyse fehlgeschlagen: ' + err.message;
          analysisError.classList.remove('hidden');
        }
        if (typeof onDone === 'function') onDone(false);
      });
  }

  function setStepActive(idx) {
    if (agentIds[idx]) { var el = document.getElementById(agentIds[idx]); if (el) { el.classList.remove('done'); el.classList.add('active'); } }
  }
  function setStepDone(idx) {
    if (agentIds[idx]) { var el = document.getElementById(agentIds[idx]); if (el) { el.classList.remove('active'); el.classList.add('done'); } }
  }

  // --- Fortschrittsanzeige ---
  function showProgress() {
    if (progressSection) progressSection.classList.remove('hidden');
    if (analysisBar) { analysisBar.style.width = '0%'; analysisBar.textContent = '0%'; }
    if (progressStatus) progressStatus.textContent = 'Analyse wird vorbereitet...';

    // Alle Agenten zuruecksetzen
    agentIds.forEach(function (id) {
      var el = document.getElementById(id);
      if (el) { el.classList.remove('active', 'done', 'error'); }
    });

    // Simulierte Schritte
    simulateSteps();
  }

  function simulateSteps() {
    var steps = [
      { agent: 'agent-parser', pct: 25, text: 'PDF wird geparst...' },
      { agent: 'agent-geometrie', pct: 50, text: 'Geometrie wird analysiert...' },
      { agent: 'agent-kalkulation', pct: 75, text: 'Massen werden berechnet...' },
      { agent: 'agent-kritik', pct: 90, text: 'Ergebnisse werden geprueft...' }
    ];

    var prevAgent = null;
    steps.forEach(function (step, i) {
      setTimeout(function () {
        // Vorherigen Agenten als fertig markieren
        if (prevAgent) {
          var prevEl = document.getElementById(prevAgent);
          if (prevEl) { prevEl.classList.remove('active'); prevEl.classList.add('done'); }
        }
        // Aktuellen Agenten als aktiv markieren
        var el = document.getElementById(step.agent);
        if (el) el.classList.add('active');
        if (analysisBar) { analysisBar.style.width = step.pct + '%'; analysisBar.textContent = step.pct + '%'; }
        if (progressStatus) progressStatus.textContent = step.text;
        prevAgent = step.agent;
      }, (i + 1) * 2000);
    });
  }

  function completeProgress() {
    agentIds.forEach(function (id) {
      var el = document.getElementById(id);
      if (el) { el.classList.remove('active'); el.classList.add('done'); }
    });
    if (analysisBar) { analysisBar.style.width = '100%'; analysisBar.textContent = '100%'; }
    if (progressStatus) progressStatus.textContent = 'Analyse abgeschlossen!';
  }

  function hideProgress() {
    if (progressSection) progressSection.classList.add('hidden');
  }

  function esc(s) { var d = document.createElement('div'); d.textContent = s; return d.innerHTML; }

  // --- Drag & Drop ---
  uploadZone.addEventListener('click', function () { fileInput.click(); });
  uploadZone.addEventListener('dragover', function (e) { e.preventDefault(); this.classList.add('dragover'); });
  uploadZone.addEventListener('dragleave', function (e) { e.preventDefault(); this.classList.remove('dragover'); });
  uploadZone.addEventListener('drop', function (e) {
    e.preventDefault(); this.classList.remove('dragover');
    if (e.dataTransfer.files.length) handleFiles(e.dataTransfer.files);
  });
  fileInput.addEventListener('change', function () { if (this.files.length) handleFiles(this.files); });

  function handleFiles(files) {
    var pdfs = [];
    for (var i = 0; i < files.length; i++) {
      if (files[i].type === 'application/pdf') pdfs.push(files[i]);
    }
    if (!pdfs.length) {
      if (analysisError) {
        analysisError.textContent = 'Nur PDF-Dateien werden unterstuetzt.';
        analysisError.classList.remove('hidden');
      }
      return;
    }
    uploadProgress.classList.remove('hidden');
    doUpload(pdfs, 0);
  }

  // Sammelt die IDs frisch hochgeladener Pläne für die Auto-Analyse
  var _uploadedPlanIds = [];

  function doUpload(files, idx) {
    if (idx >= files.length) {
      uploadProgress.classList.add('hidden');
      uploadBar.style.width = '0%';
      fileInput.value = '';
      loadPlans();
      // ─── AUTO-FLOW: hochgeladene Pläne sofort analysieren ───
      // Der Nutzer muss nichts mehr klicken. Pläne werden sequentiell
      // verarbeitet (analyse-zoom ist API-intensiv).
      if (_uploadedPlanIds.length > 0) {
        var queue = _uploadedPlanIds.slice();
        _uploadedPlanIds = [];
        autoAnalyseQueue(queue, 0);
      }
      return;
    }
    var file = files[idx];
    var path = firma.id + '/' + projectId + '/' + Date.now() + '_' + file.name;
    uploadBar.style.width = '50%';
    uploadBar.textContent = 'Hochladen...';

    _sb.storage.from('plaene').upload(path, file, { contentType: 'application/pdf' })
      .then(function (r) {
        if (r.error) throw new Error(r.error.message);
        return _sb.from('plaene')
          .insert({ projekt_id: projectId, dateiname: file.name, storage_path: path })
          .select().single();
      })
      .then(function (insertRes) {
        uploadBar.style.width = '100%';
        uploadBar.textContent = '100%';
        if (insertRes && insertRes.data && insertRes.data.id) {
          _uploadedPlanIds.push(insertRes.data.id);
        }
        setTimeout(function () { doUpload(files, idx + 1); }, 300);
      })
      .catch(function (err) {
        // Fehler bei dieser Datei → Meldung zeigen, aber mit nächster
        // Datei weitermachen statt die ganze Kette abzubrechen.
        if (analysisError) {
          analysisError.textContent = 'Upload-Fehler bei "' + file.name + '": ' + err.message;
          analysisError.classList.remove('hidden');
        }
        setTimeout(function () { doUpload(files, idx + 1); }, 300);
      });
  }

  // Verarbeitet eine Warteschlange von Plan-IDs sequentiell mit Auto-Analyse.
  // Nutzt den onDone-Callback von startAnalysis — kein Polling, verlässlich.
  function autoAnalyseQueue(queue, i) {
    if (i >= queue.length) {
      loadPlans();
      return;
    }
    var planId = queue[i];
    startAnalysis(planId, null, function () {
      // Egal ob erfolgreich oder fehlgeschlagen — nächsten Plan starten
      autoAnalyseQueue(queue, i + 1);
    });
  }

  window.loadPlans = loadPlans;
  window.projectId = projectId;
  loadPlans();
})();
