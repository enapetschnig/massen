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

  // Druck: Aufmaß-Details (LV-Buchform) vor dem Drucken aufklappen, danach zurück —
  // damit die gedruckte Massenermittlung alle Σ-Zeilen prüfbar zeigt.
  var _printOpened = [];
  window.addEventListener('beforeprint', function () {
    _printOpened = [];
    document.querySelectorAll('.lv-aufmass:not([open])').forEach(function (d) {
      d.setAttribute('open', ''); _printOpened.push(d);
    });
  });
  window.addEventListener('afterprint', function () {
    _printOpened.forEach(function (d) { d.removeAttribute('open'); });
    _printOpened = [];
  });

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
      // Ergebnis ERST zeigen, wenn ALLE Pläne fertig analysiert sind — sonst
      // verwirren Teil-Ergebnisse (Räume/Mengen ändern sich noch). Solange noch
      // Pläne laufen: Ergebnis ausblenden + klaren Warte-Hinweis zeigen.
      var sec = document.getElementById('ergebnis-section');
      var warteEl = document.getElementById('ergebnis-warte');
      if (plans.length > 0 && fertigCount === plans.length) {
        if (warteEl) warteEl.classList.add('hidden');
        loadProjektMassen(fertigCount, plans.length);
      } else {
        if (sec) sec.classList.add('hidden');
        if (warteEl) {
          if (plans.length === 0) { warteEl.classList.add('hidden'); }
          else {
            warteEl.classList.remove('hidden');
            warteEl.innerHTML = '<div class="spinner"></div> <strong>' + fertigCount + ' von ' +
              plans.length + ' Plänen analysiert</strong> — das Ergebnis erscheint, sobald alle fertig sind ' +
              '(sonst ändern sich Räume und Mengen noch).';
          }
        }
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
    // Planansicht-Tabs mit demselben Manifest versorgen (gleicher IIFE-Scope, hoisted)
    if (plaeneManifest && plaeneManifest.length) _nzPlaene = plaeneManifest;
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
  var _lastML = null, _lastGemessen = null;  // für Rechenweg-Toggle-Rerender
  function refreshProjektMassen() {
    if (_lastFertig > 0) loadProjektMassen(_lastFertig, _lastTotal);
  }

  // --- Projekt-weite Massenermittlung (gemerged über alle Pläne) ---
  function loadProjektMassen(fertigCount, totalCount) {
    var sec = document.getElementById('ergebnis-section');
    if (!sec) return;
    var badge = document.getElementById('projekt-massen-badge');
    var grid = document.getElementById('projekt-massen-grid');
    var detail = document.getElementById('projekt-massen-detail');
    var detailWrap = document.getElementById('projekt-massen-detail-wrap');
    var board = document.getElementById('ml-board');

    sec.classList.remove('hidden');
    _lastFertig = fertigCount; _lastTotal = totalCount;
    bindFilterControls();
    bindErgebnisTabs();
    bindProjektExport();
    if (badge) badge.textContent = 'Pläne werden zusammengeführt …';
    if (board) board.innerHTML = '<div class="loading" style="padding:1.5rem"><div class="spinner"></div> Räume aller Pläne werden zusammengeführt und Mengen berechnet …</div>';
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
          if (board) board.innerHTML = '<div class="ml-empty">Projekt-Massen konnten nicht berechnet werden — bitte Detail-Ansicht im Plan öffnen.</div>';
          return;
        }
        renderProjektMassen(data, fertigCount, totalCount);
        renderNachzeichnen();   // Planansicht automatisch nachzeichnen (einmal, danach via Guard)
      })
      .catch(function () {
        if (badge) badge.textContent = '';
        if (board) board.innerHTML = '<div class="ml-empty">Netzwerk-Fehler bei der Mengenberechnung.</div>';
      });
  }

  // Bauteil → Symbol für die Material-Gruppen (scanbar wie eine Bestell-Liste)
  var BAUTEIL_ICONS = {
    'Frostschürze': '🧊', 'Bodenplatte': '🟫', 'Mauerwerk EG': '🧱',
    'Mauerwerk': '🧱', 'Öffnungen': '🪟', 'Decke über EG': '▦', 'Decke': '▦',
    'Attika': '🔲', 'Kamin': '🔥', 'Infrastruktur': '🚰', 'Bodenaufbau': '🪵'
  };
  function bauteilIcon(name) {
    if (BAUTEIL_ICONS[name]) return BAUTEIL_ICONS[name];
    var hit = Object.keys(BAUTEIL_ICONS).filter(function (k) { return name.indexOf(k) === 0; })[0];
    return hit ? BAUTEIL_ICONS[hit] : '📦';
  }
  // Konfidenz (0..1) → ehrliche Vertrauens-Stufe
  function konfTier(konf) {
    if (konf >= 0.7) return { cls: 'hoch', title: 'Direkt aus dem Plan gelesen — verlässlich' };
    if (konf >= 0.5) return { cls: 'mittel', title: 'Aus Plan-Maßen + üblicher Annahme' };
    return { cls: 'niedrig', title: 'Schätzung — am Bau gegenprüfen' };
  }

  // FACT-STRIP: zeigt knapp, was die App byte-exakt aus dem Plan gelesen hat
  function renderFactStrip(data) {
    var el = document.getElementById('fact-strip');
    if (!el) return;
    var bd = data.baudaten || {}, bq = bd._quellen || {}, g = data.gemessen || {};
    var facts = [];
    // SEKTOR-INDIKATOR (mehrere Bereiche der Baubranche sichtbar machen): die
    // App erkennt den Plan-Typ und rechnet im passenden Modus — der Nutzer sieht
    // sofort, WAS erkannt wurde, statt still umgeschaltet zu werden.
    var sektor = null;
    var _kz = (data.materialliste && data.materialliste.kennzahlen) || {};
    if ((data.dach_positionen || []).length)
      sektor = { ico: '🏠', txt: 'Dachplan · Zimmerer/Dachdecker', col: '#b45309' };
    else if (_kz.sektor === 'STB/Tiefgarage')
      sektor = { ico: '🅿️', txt: 'Tiefgarage · Stahlbeton-Modus', col: '#475569' };
    else
      sektor = { ico: '🏗️', txt: 'Rohbau · Hochbau (EFH/Wohnbau)', col: '#166534' };
    facts.push('<div class="fact fact-sektor" style="border-color:' + sektor.col +
      '"><span class="fact-ico">' + sektor.ico + '</span><span class="fact-k">Sektor</span>' +
      '<span class="fact-v" style="color:' + sektor.col + ';font-weight:700">' + sektor.txt +
      '</span><span class="fact-src" title="automatisch aus dem Plan-Typ erkannt — passt Mengenlogik + Materialliste an">erkannt</span></div>');
    function srcTag(key) {
      var q = (bq[key] || '') + '';
      var dc = q.indexOf('doppelcheck') >= 0 ? '<span class="fact-confirm" title="von zwei unabhängigen Quellen bestätigt — sehr hohe Konfidenz">✓✓</span>' : '';
      var base;
      if (q.indexOf('legende') >= 0) base = '<span class="fact-src read" title="byte-exakt aus Bauteil-Legende gelesen">gelesen</span>';
      else if (q.indexOf('schnitt') >= 0) base = '<span class="fact-src measured" title="aus dem Schnitt/der Ansicht gelesen">aus Schnitt</span>';
      else if (/vision|raumhoehen|gemessen|bbox|polygon|kette/i.test(q)) base = '<span class="fact-src measured" title="aus dem Plan gemessen">gemessen</span>';
      else if (!q) base = '';
      else base = '<span class="fact-src assumed" title="Standard-Annahme — kein Plan-Beleg">Standard</span>';
      return base + dc;
    }
    function bdFact(icon, label, key, unit) {
      if (bd[key] == null) return;
      facts.push('<div class="fact"><span class="fact-ico">' + icon + '</span><span class="fact-k">' + label +
        '</span><span class="fact-v">' + bd[key] + unit + '</span>' + srcTag(key) + '</div>');
    }
    // Nur die WANDSTÄRKEN + Öffnungen hier — die Geometrie (Umfang/Fläche/Höhe)
    // steht schon im Geometrie-Kasten darüber, damit es nicht doppelt + überladen wirkt.
    bdFact('🧱', 'Außenwand', 'aussenwand_cm', ' cm');
    bdFact('▦', 'Decke', 'decke_cm', ' cm');
    bdFact('🟫', 'Bodenplatte', 'bodenplatte_cm', ' cm');
    var fen = data.fenster_count || 0, tur = data.tueren_count || 0;
    if (fen || tur) facts.push('<div class="fact"><span class="fact-ico">🪟</span><span class="fact-k">Öffnungen</span><span class="fact-v">' +
      fen + ' F · ' + tur + ' T</span><span class="fact-src read">aus Text</span></div>');
    // Schnitt-/Ansichts-Lesung: Säulen + Dachtyp
    var sv = data.schnitt || {};
    if (data.saeulen_erkannt) {
      var _saeQ = data.saeulen_geschaetzt
        ? '<span class="fact-src assumed" title="aus der überdachten Fläche geschätzt — am Plan/in der Statik prüfen">geschätzt</span>'
        : '<span class="fact-src measured" title="aus Schnitt/Ansicht erkannt">aus Schnitt</span>';
      facts.push('<div class="fact" title="in der Materialliste berücksichtigt"><span class="fact-ico">🏛️</span><span class="fact-k">Säulen</span><span class="fact-v">' +
        data.saeulen_erkannt + '</span>' + _saeQ + '</div>');
    }
    if (sv.dachtyp) facts.push('<div class="fact"><span class="fact-ico">🏠</span><span class="fact-k">Dach</span><span class="fact-v">' +
      esc(sv.dachtyp) + (sv.attika_hoehe_m ? ' · Attika ' + fmtNum(sv.attika_hoehe_m) + 'm' : '') + '</span><span class="fact-src measured">aus Schnitt</span></div>');
    el.innerHTML = facts.join('');
  }

  // GEOMETRIE-KASTEN: die kritischen Maße für die Mengen, jede mit Sicherungs-Flag
  function renderGeoBox(data) {
    var el = document.getElementById('geo-box');
    if (!el) return;
    var g = data.gemessen || {};
    var gq = g.geometrie_qualitaet || {};
    var bd = data.baudaten || {};
    var dc = data.doppelcheck || [];
    var ghOk = dc.some(function (d) { return d.key === 'geschosshoehe_m' && d.status === 'bestätigt'; });
    function tile(icon, label, value, cls, mark, note) {
      return '<div class="geo-tile ' + cls + '">' +
        '<div class="geo-tile-head"><span class="geo-ico">' + icon + '</span><span class="geo-label">' + label +
          '</span><span class="geo-flag">' + mark + '</span></div>' +
        '<div class="geo-val">' + value + '</div>' +
        '<div class="geo-note">' + note + '</div></div>';
    }
    var t = [];
    var opusGarage = (gq.opus_garage || []).filter(Boolean);
    if (g.aussenumfang_m) {
      var cls, mark, note;
      if (gq.umfang_validiert) { cls = 'ok2'; mark = '✓✓'; note = 'aus den Maßen im Plan bestätigt'; }
      else if (gq.umfang_verdacht_niedrig) { cls = 'warn'; mark = '⚠'; note = 'wirkt zu klein für die Fläche — am Plan prüfen oder unten eintragen'; }
      else if (gq.cross_check_warnung) { cls = 'warn'; mark = '⚠'; note = 'unsicher — am Plan prüfen'; }
      else { cls = 'ok'; mark = '✓'; note = 'Umfang der Außenwände'; }
      if (opusGarage.length && gq.opus_mauerwerk_zusatz_m) {
        note += ' · inkl. ' + esc(opusGarage.join(', ')) + ' (im Schnitt gemauert, +' +
          fmtNum(gq.opus_mauerwerk_zusatz_m) + ' m)';
      }
      t.push(tile('📐', 'Außenwand-Umfang', fmtNum(g.aussenumfang_m) + ' m', cls, mark, note));
    }
    if (g.bodenplatte_flaeche_m2) t.push(tile('⬛', 'Grundfläche', fmtNum(g.bodenplatte_flaeche_m2) + ' m²',
      'ok2', '✓✓', 'aus den Raumflächen im Plan'));
    if (g.fundament_umfang_m) {
      if (gq.fundament_unsicher) {
        t.push(tile('🔲', 'Bodenplatten-Kante', fmtNum(g.fundament_umfang_m) + ' m', 'warn', '⚠',
          'überdachte Bereiche am Haus (Terrasse/Carport) — die Platte läuft evtl. weiter. Am Polierplan prüfen oder Umfang eintragen.'));
      } else if (gq.opus_slab_aktiv) {
        t.push(tile('🔲', 'Bodenplatten-Kante', fmtNum(g.fundament_umfang_m) + ' m', 'ok', '✓',
          'läuft unter den Anbau weiter (im Schnitt erkannt)'));
      } else if (gq.linie_b_erkannt) {
        t.push(tile('🔲', 'Bodenplatten-Kante', fmtNum(g.fundament_umfang_m) + ' m', 'ok', '✓', 'inkl. angebautem überdachten Bereich'));
      } else {
        t.push(tile('🔲', 'Bodenplatten-Kante', fmtNum(g.fundament_umfang_m) + ' m', 'grey', '=', 'gleich Außenkante (kein Überstand)'));
      }
    }
    if (bd.geschosshoehe_m) {
      var ghEntry = dc.filter(function (d) { return d.key === 'geschosshoehe_m'; })[0];
      var ghSrc;
      if (ghEntry && ghEntry.status === 'bestätigt') {
        ghSrc = 'aus Plan + Schnitt bestätigt';
      } else if (ghEntry && ghEntry.status === 'verstaerkt') {
        ghSrc = 'aus dem Plan gelesen';
      } else {
        ghSrc = 'aus den Raumhöhen im Plan';
      }
      t.push(tile('📏', 'Geschoss-Höhe', fmtNum(bd.geschosshoehe_m) + ' m',
        ghOk ? 'ok2' : 'ok', ghOk ? '✓✓' : '✓', ghSrc));
    }
    el.innerHTML = t.join('');
  }

  // KENNZAHLEN: immer sichtbar am Ende der Auswertung — Höhe + Wandflächen.
  // Werte kommen EXAKT aus der Materialliste (kennzahlen), damit Anzeige und
  // berechnete Mengen garantiert übereinstimmen (Konstanz).
  function renderKennzahlen(data) {
    var el = document.getElementById('auswertung-kennzahlen');
    if (!el) return;
    var k = (data.materialliste && data.materialliste.kennzahlen) || {};
    // Fallback (falls Backend-Kennzahlen fehlen): Höhe aus baudaten, Wandfläche = Umfang×Höhe
    var h = k.geschosshoehe_m || (data.baudaten && data.baudaten.geschosshoehe_m);
    var awf = k.aussenwand_flaeche_m2;
    if (awf == null && data.gemessen && data.gemessen.aussenumfang_m && h) {
      awf = Math.round(data.gemessen.aussenumfang_m * h * 100) / 100;
    }
    if (h == null && awf == null) { el.innerHTML = ''; return; }
    function kz(icon, label, value, sub) {
      return '<div class="kz-tile"><div class="kz-head"><span class="kz-ico">' + icon + '</span>' +
        '<span class="kz-label">' + label + '</span></div>' +
        '<div class="kz-val">' + value + '</div>' +
        (sub ? '<div class="kz-sub">' + sub + '</div>' : '') + '</div>';
    }
    var tiles = [];
    if (h != null) tiles.push(kz('📏', 'Geschoss-Höhe', fmtNum(h) + ' m', 'wie oben — treibt die Wandfläche'));
    if (awf != null) tiles.push(kz('🧱', 'Außenwand-Fläche', fmtNum(awf) + ' m²', 'Umfang × Höhe (brutto)'));
    if (k.innenwand_flaeche_m2 != null && k.innenwand_flaeche_m2 > 0)
      tiles.push(kz('🧱', 'Innenwand-Fläche', fmtNum(k.innenwand_flaeche_m2) + ' m²', 'tragend + nichttragend (brutto)'));
    if (k.decke_flaeche_m2 != null)
      tiles.push(kz('▦', 'Deckenfläche', fmtNum(k.decke_flaeche_m2) + ' m²', 'EG-Decke inkl. Auskragung'));
    el.innerHTML = '<div class="kz-title">Kennzahlen auf einen Blick</div><div class="kz-grid">' + tiles.join('') + '</div>';
    renderDachPositionen(data, el);
  }

  // DACH-POSITIONEN (Dachdecker/Zimmerer-Sektor): byte-exakt vom Plan gelesene
  // Flächen/Hölzer/Fenster — eigener Block unter den Kennzahlen, nur wenn der
  // Plan-Satz Dach-Positionen trägt (Sanierungs-/Angebotspläne).
  function renderDachPositionen(data, anchorEl) {
    var alle = data.dach_positionen || [];
    var old = document.getElementById('dach-positionen-karte');
    if (old) old.remove();
    if (!alle.length || !anchorEl) return;
    var html = '<div class="kz-title" style="margin-top:1rem">🏠 Dach-Positionen (byte-exakt vom Plan)</div>';
    alle.forEach(function (dp) {
      var z = [];
      (dp.flaechen || []).forEach(function (f2) {
        z.push('Dachfläche ' + esc(f2.name) + ': <strong>' + f2.m2 + ' m²</strong>' +
          (f2.rechnung ? ' <span style="color:#6b7280">(= ' + esc(f2.rechnung) + ')</span>' : ''));
      });
      if (dp.gesamt_m2 != null && dp.gesamt_bestaetigt)
        z.push('<span style="color:#166534">✓ Σ Teilflächen = Gesamt (' + dp.gesamt_m2 +
               ' m²) — der Plan bestätigt sich selbst</span>');
      (dp.hoelzer || []).forEach(function (h2) {
        z.push(h2.anzahl + '× ' + esc(h2.bauteil) + ' B/H ' + h2.b_cm + '/' + h2.h_cm + ' cm');
      });
      (dp.fenster || []).forEach(function (fe) {
        z.push(fe.anzahl + '× ' + esc(fe.marke) + (fe.typ ? ' ' + esc(fe.typ) : '') +
               ' ' + fe.breite_cm + '/' + fe.hoehe_cm + ' cm');
      });
      (dp.positionen || []).forEach(function (po) {
        z.push('Pos. ' + po.pos + ') ' + esc(po.text) + (po.m2 ? ' — ca. ' + po.m2 + ' m²' : ''));
      });
      // Abgeleitete Material-Mengen (bestellbar) — mit Rechenweg & Konfidenz
      (dp.materialliste || []).forEach(function (mp) {
        var kf = mp.konfidenz != null ? Math.round(mp.konfidenz * 100) + '%' : '';
        z.push('<strong>' + esc(mp.material) + ': ' + mp.menge + ' ' + esc(mp.einheit) +
          '</strong> <span style="color:#6b7280">[' + kf + ']' +
          (mp.formel ? ' = ' + esc(mp.formel) : '') + '</span>');
      });
      if (z.length) {
        html += '<div class="kz-sub" style="margin:.2rem 0 .5rem">' +
          (dp.plan ? esc(dp.plan) + ': ' : '') + '</div><ul style="margin:.1rem 0 .6rem 1.1rem;font-size:.86rem;line-height:1.5">' +
          z.map(function (t) { return '<li>' + t + '</li>'; }).join('') + '</ul>';
      }
    });
    var div = document.createElement('div');
    div.id = 'dach-positionen-karte';
    div.innerHTML = html;
    anchorEl.appendChild(div);
  }

  // PRÜF-LISTE: klare „hier nachschauen"-Punkte für den Polier (deterministisch
  // vom Backend nach Priorität sortiert). Nichts erfinden — nur was die Engine
  // selbst als unsicher/widersprüchlich markiert hat.
  function renderPruefliste(data) {
    var el = document.getElementById('pruefliste');
    if (!el) return;
    var items = (data && data.pruefliste) || [];
    if (!items.length) { el.innerHTML = ''; return; }
    var ICON = { hoch: '🔴', mittel: '🟡', niedrig: '⚪' };
    function li(it) {
      return '<li class="pl-row pl-' + esc(it.prio) + '">' +
        '<span class="pl-ico">' + (ICON[it.prio] || '•') + '</span>' +
        '<span class="pl-body"><strong>' + esc(it.thema || '') + '</strong> — ' + esc(it.hinweis || '') + '</span></li>';
    }
    var TOP = 7;
    var head = items.slice(0, TOP).map(li).join('');
    var rest = items.slice(TOP).map(li).join('');
    el.innerHTML = '<div class="pl-title">🔎 Vor der Bestellung prüfen <span class="pl-count">' + items.length + '</span></div>' +
      '<ul class="pl-list">' + head + '</ul>' +
      (rest ? '<details class="pl-rest"><summary>Alle ' + items.length + ' Punkte zeigen</summary><ul class="pl-list">' + rest + '</ul></details>' : '');
  }

  // HERKUNFTS-LEDGER: jede Schlüssel-Zahl mit Quelle + Verlässlichkeit (Transparenz).
  function renderHerkunft(data) {
    var el = document.getElementById('herkunft-ledger');
    if (!el) return;
    var items = (data && data.herkunft) || [];
    if (!items.length) { el.innerHTML = ''; return; }
    function konfTxt(it) {
      if (it.status === 'bestätigt') return '<span class="hk-k hk-ok">doppelt bestätigt</span>';
      if (it.konfidenz == null) return '';
      var k = Math.round(it.konfidenz * 100);
      var c = k >= 90 ? 'hk-ok' : (k >= 70 ? 'hk-mid' : 'hk-low');
      return '<span class="hk-k ' + c + '">' + k + '%</span>';
    }
    el.innerHTML = '<table class="hk-table"><tbody>' + items.map(function (it) {
      return '<tr><td class="hk-g">' + esc(it.groesse) + '</td>' +
        '<td class="hk-v">' + esc(it.wert) + ' ' + esc(it.einheit || '') + '</td>' +
        '<td class="hk-q">' + esc(it.quelle || '') + '</td>' +
        '<td class="hk-kc">' + konfTxt(it) + '</td></tr>';
    }).join('') + '</tbody></table>';
  }

  // STATUS-BANNER: nur Hinweise, bei denen der Nutzer etwas tun kann/sollte
  function renderStatusBanner(data) {
    var statusEl = document.getElementById('ergebnis-status-banner');
    if (!statusEl) return;
    var hints = [];
    // FARB-LEGENDE: enthält der Plan Bestand/Abbruch-Bauteile? Dann beziehen sich die
    // Massen auf den Neubau und Bestand/Abbruch sind NICHT herausgerechnet — wichtigste
    // Warnung zuerst (sonst zählt der Polier bei einem Umbau-Plan Bestandswände mit).
    if (data.farben && (data.farben.hat_bestand || data.farben.hat_abbruch)) {
      var baTeile = [];
      if (data.farben.hat_bestand) baTeile.push('Bestand');
      if (data.farben.hat_abbruch) baTeile.push('Abbruch');
      hints.push('<div class="status-warn">🎨 <strong>' + baTeile.join(' + ') +
        ' im Plan erkannt</strong> — ' + esc(data.farben.hinweis ||
        ('laut Legende. Die Massen beziehen sich auf den NEUBAU; ' + baTeile.join('/') +
         ' ist nicht automatisch herausgerechnet, bitte separat prüfen.')) + '</div>');
    }
    // Nur INNENRÄUME ohne Höhe sind ein Problem — überdachte Außenflächen
    // (Terrasse/Parkplatz/Loggia) haben korrekt keine Raumhöhe.
    var innenOhneH = (data.raeume || []).filter(function (r) {
      return r && r.flaeche_m2 && !r.hoehe_m && !r._h_not_applicable;
    });
    if (innenOhneH.length > 0 && data.plaene_count === 1) {
      hints.push('<div class="status-warn">⚠ <strong>' + innenOhneH.length +
        ' Innenräume ohne Höhe</strong> — der Einreichplan hat nur Fläche + Umfang. ' +
        '<strong>Lade auch den Polierplan hoch</strong>, sonst rechnen alle Wand-/Putz-/Maler-Mengen mit Default-Höhe.</div>');
    } else if (data.h_inferred_count > 0) {
      hints.push('<div class="status-info">ℹ ' + data.h_inferred_count +
        ' Innenräume ohne Höhe im Plan → <strong>' + fmtNum(data.h_inferred_value) + ' m</strong> Geschoss-Höhe übernommen.</div>');
    }
    if (data.aussen_ohne_h_count > 0) {
      hints.push('<div class="status-ok">✓ ' + data.aussen_ohne_h_count +
        ' überdachte Außenfläche(n) ohne Raumhöhe — korrekt, fließen nur über die Fläche in Decke/Bodenaufbau.</div>');
    }
    // DOPPELCHECK: nur QUALITATIV unterschiedliche Methoden (Text-Layer vs Vision)
    // gelten als echte Bestätigung ("bestätigt"). Zwei Bild-Lesungen desselben Plans
    // (Schnitt + Opus) sind nur Redundanz ("verstaerkt") — ehrlich getrennt anzeigen.
    var dc = data.doppelcheck || [];
    var bestaetigt = dc.filter(function (d) { return d.status === 'bestätigt'; });
    var verstaerkt = dc.filter(function (d) { return d.status === 'verstaerkt'; });
    var widerspruch = dc.filter(function (d) { return d.status === 'widerspruch'; });
    if (bestaetigt.length) {
      hints.push('<div class="status-ok">✓✓ <strong>' + bestaetigt.length +
        ' Wert(e) doppelt bestätigt</strong> (' + bestaetigt.map(function (d) { return esc(d.groesse); }).join(', ') +
        ') — aus dem Plan-Text und dem Plan-Bild übereinstimmend gelesen. Sehr verlässlich.</div>');
    }
    // (verstaerkt-Hinweis bewusst weggelassen — technische Feinheit, die der
    //  Baubetrieb nicht braucht; hält die Auswertung fokussiert.)
    widerspruch.forEach(function (d) {
      var vals = (d.quellen || []).map(function (q) { return esc(q.quelle) + ' ' + q.wert + (d.einheit || ''); }).join(' vs ');
      hints.push('<div class="status-warn">⚠ <strong>' + esc(d.groesse) + ' unklar</strong>: ' + vals +
        ' — Quellen widersprechen sich, bitte am Plan prüfen.</div>');
    });
    // Öffnungs-Cap: Symbol-Zählung hat Über-Erkennung korrigiert
    dc.filter(function (d) { return d.status === 'gekappt'; }).forEach(function (d) {
      hints.push('<div class="status-info">✂ <strong>' + esc(d.groesse) + '</strong> von ' + d.vorher + ' auf ' +
        d.wert + ' korrigiert — Symbol-Zählung am Plan ergab ' + d.symbol + ' (Doppelzählung entfernt).</div>');
    });
    // Geometrie: Außenumfang verdächtig/unsicher → am Plan prüfen
    var gq = (data.gemessen || {}).geometrie_qualitaet || {};
    var g0 = data.gemessen || {};
    if (gq.umfang_verdacht_niedrig && g0.aussenumfang_m) {
      hints.push('<div class="status-warn">⚠ <strong>Außenumfang wirkt zu niedrig</strong> (' +
        fmtNum(g0.aussenumfang_m) + ' m bei ' + fmtNum(g0.bodenplatte_flaeche_m2) + ' m² Grundfläche). ' +
        'Vermutlich ein L-/U-Bau, den die KI zu kompakt liest. <strong>Frostschürze, Randabschluss und Außenwand-Ziegel sind dadurch zu niedrig</strong> — ' +
        'bitte am Plan prüfen und unten im Erweitert-Drawer den echten Umfang setzen.</div>');
    } else if (gq.cross_check_warnung && g0.aussenumfang_m) {
      hints.push('<div class="status-warn">⚠ <strong>Außenumfang unsicher</strong> — die Mess-Quellen sind sich uneinig' +
        (gq.poly_vs_bbox_diff_pct ? ' (' + gq.poly_vs_bbox_diff_pct + '% Abweichung)' : '') +
        '. Frostschürze/Randabschluss/Mauerwerk am Plan gegenprüfen oder im Erweitert-Drawer den Umfang setzen.</div>');
    }
    if (gq.fundament_unsicher) {
      hints.push('<div class="status-warn">⚠ <strong>Fundamentkante prüfen</strong> — ' + (gq.ueberdachte_flaechen || '') +
        ' überdachte Fläche(n) (Terrasse/Carport) am Haus. Die Bodenplatte läuft mglw. darunter weiter — <strong>wie weit, steht nur im Polierplan</strong>. ' +
        'Frostschürze/Randabschluss daher mit Vorsicht; bei Bedarf den echten Umfang im Erweitert-Drawer setzen.</div>');
    }
    // OPUS-BAUINGENIEUR: im Schnitt als gemauert erkannte „überdachte" Bereiche
    // (z.B. ein als Parkplatz beschrifteter, real gemauerter Garagen-Anbau)
    var opusGar = (gq.opus_garage || []).filter(Boolean);
    if (opusGar.length && gq.opus_mauerwerk_zusatz_m) {
      hints.push('<div class="status-ok">🏗 <strong>' + esc(opusGar.join(', ')) +
        ' ist gemauert</strong> — im Grundriss nur „überdacht", aber im Schnitt rundum gemauert. ' +
        '+' + fmtNum(gq.opus_mauerwerk_zusatz_m) + ' m Außenwand kommen dazu.</div>');
    }
    if (gq.opus_slab_aktiv) {
      hints.push('<div class="status-ok">✓ <strong>Bodenplatte läuft unter den Anbau weiter</strong> — ' +
        'im Schnitt erkannt; die Bodenplatten-Kante ist entsprechend gesetzt.</div>');
    }
    if (data.opus_status === 'fehler') {
      hints.push('<div class="status-info">ℹ <strong>Schnitt-Auswertung diesmal nicht verfügbar</strong> — ' +
        'die Garage-/Höhen-/Dach-Erkennung aus dem Schnitt ist ausgefallen. Die übrigen Werte sind davon nicht betroffen.' +
        (data.opus_fehler_grund ? ' <span style="opacity:.7">(Grund: ' + esc(String(data.opus_fehler_grund)) + ')</span>' : '') +
        '</div>');
    }
    // OPUS-SCHLUSSPRÜFUNG: nur EINE Zusammenfassungszeile — die einzelnen Befunde
    // stehen gebündelt unten in der Prüf-Liste (keine doppelte Text-Wand mehr).
    var pruef = data.opus_pruefung;
    if (pruef && (pruef.befunde || []).length) {
      hints.push('<div class="status-info">🔍 <strong>Schlussprüfung: ' + pruef.befunde.length +
        ' Punkt(e) zu prüfen</strong> — gebündelt unten unter „Vor der Bestellung prüfen".</div>');
    } else if (pruef && pruef.gesamturteil === 'plausibel') {
      hints.push('<div class="status-ok">🔍 <strong>Schlussprüfung bestanden</strong> — der Bauingenieur-Pass ' +
        'hat die Liste gegen den Plan geprüft und nichts Auffälliges gefunden.</div>');
    }
    var fen = data.fenster_count || 0, tur = data.tueren_count || 0;
    if (fen === 0 && tur === 0) {
      hints.push('<div class="status-warn">⚠ <strong>0 Öffnungen erkannt</strong> — Laibungen, Rolladenkästen und Überlagen werden pauschal geschätzt.</div>');
    }
    if (data.halluzinationen && data.halluzinationen.length) {
      hints.push('<div class="status-info">🧹 ' + data.halluzinationen.length + ' Vision-Halluzination(en) automatisch gefiltert: ' +
        data.halluzinationen.map(function (h) { return esc(h.name); }).join(', ') + '</div>');
    }
    (data.legende_warnungen || []).forEach(function (w) {
      hints.push('<div class="status-warn">⚠ <strong>Wandstärke prüfen</strong> — ' + esc(w) +
        '. Diese Wand ist in der Legende nicht definiert; ihre Menge wird konservativ behandelt.</div>');
    });
    var konsistenz = data.konsistenz;
    if (konsistenz && konsistenz.findings && konsistenz.findings.length) {
      var sw = (konsistenz.summary || {}).schweren || {};
      var fehler = sw.fehler || 0, warnungen = sw.warnung || 0, infos = sw.info || 0;
      // nur zeigen, wenn es echte Fehler/Warnungen gibt — reine Infos nicht aufdrängen
      if (fehler > 0 || warnungen > 0) {
        var cssClass = fehler > 0 ? 'status-warn' : 'status-info';
        var icon = fehler > 0 ? '⛔' : '⚠';
        var parts = [];
        if (fehler) parts.push(fehler + ' Fehler');
        if (warnungen) parts.push(warnungen + ' Warnungen');
        if (infos) parts.push(infos + ' Hinweise');
        hints.push('<div class="' + cssClass + '">' + icon + ' Konsistenz-Check: ' + parts.join(', ') +
          ' <details style="display:inline-block;margin-left:0.4rem"><summary style="cursor:pointer">Details</summary>' +
          '<ul style="margin:0.3rem 0 0 0;padding-left:1.2rem">' +
          konsistenz.findings.map(function (f) { return '<li><strong>' + esc(f.schwere) + '</strong> · ' + esc(f.msg) + '</li>'; }).join('') +
          '</ul></details></div>');
      }
    }
    // ENTSCHLACKEN: nur handlungsrelevante Warnungen direkt zeigen; OK-/Info-Zeilen
    // (Bestätigungen, Hinweise) einklappen — der Polier sieht die ~3 wichtigen sofort.
    var krit = hints.filter(function (h) { return h.indexOf('status-warn') >= 0; });
    var rest = hints.filter(function (h) { return h.indexOf('status-warn') < 0; });
    statusEl.innerHTML = krit.join('') +
      (rest.length ? '<details class="status-rest"><summary>' + rest.length +
        ' weitere Hinweise</summary>' + rest.join('') + '</details>' : '');
  }

  function renderProjektMassen(data, fertigCount, totalCount) {
    // Single Source of Truth: die gemergte+deduplizierte Projekt-Antwort
    // global ablegen, damit ALLE Ansichten (auch die Legacy-Detail-Tabellen
    // in tabelle.js) dieselben Zahlen zeigen statt Roh-Pro-Plan-Daten.
    window.projektMassenData = data;
    var badge = document.getElementById('projekt-massen-badge');
    var grid = document.getElementById('projekt-massen-grid');
    var detail = document.getElementById('projekt-massen-detail');
    var detailWrap = document.getElementById('projekt-massen-detail-wrap');

    // Hero-Untertitel: kompakte Projekt-Fakten
    if (badge) {
      var bt = data.plaene_count + ' Plan' + (data.plaene_count === 1 ? '' : 'e') +
        ' · ' + data.raeume_count + ' Räume gelesen';
      if (data.merge_enrichments > 0) bt += ' · ' + data.merge_enrichments + ' Lücken durch Merge gefüllt';
      if (totalCount > fertigCount) bt += ' · ⏳ ' + (totalCount - fertigCount) + ' Plan(e) noch in Analyse';
      badge.textContent = bt;
    }

    if (data.plaene) renderPlanFilter(data.plaene);
    renderFactStrip(data);
    renderGeoBox(data);
    renderKennzahlen(data);
    renderPruefliste(data);
    renderHerkunft(data);
    renderStatusBanner(data);
    renderKalibrierungStatus(data.kalibrierung);
    renderOeffnungsAufmass(data.oeffnungs_aufmass);
    renderRaumAufmass(data.raeume, data.baudaten);

    // ÖNORM-Gewerke-Kacheln (im Erweitert-Drawer)
    var gw = data.gewerke || {};
    var cards = [];
    Object.keys(gw).forEach(function (gk) {
      var g = gw[gk];
      var label = (g.label || gk).replace(/\s*\(.*\)/, '');
      (g.positionen || []).forEach(function (p) {
        if ((p.endsumme || 0) !== 0) {   // alle ermittelten Positionen (inkl. 1.0 Mauerwerk + Beton)
          var konf = Math.round((p.konfidenz || 0) * 100);
          cards.push({ gewerk: label, text: p.beschreibung || '', wert: p.endsumme || 0, einheit: p.einheit || '', konf: konf, warn: konf < 65 });
        }
      });
    });
    if (grid) {
      grid.innerHTML = cards.length ? cards.map(function (c) {
        return '<div class="projekt-massen-card">' +
          '<div class="projekt-massen-card-label">' + esc(c.gewerk) + '</div>' +
          '<div style="font-size:0.78rem;color:#6c757d;margin-bottom:0.3rem">' + esc(c.text) + '</div>' +
          '<div class="projekt-massen-card-value">' + fmtNum(c.wert) +
            '<span class="projekt-massen-card-unit">' + esc(c.einheit) + '</span></div>' +
          '<div class="projekt-massen-card-konf' + (c.warn ? ' warn' : '') + '">Konfidenz ' + c.konf + '%</div>' +
          '</div>';
      }).join('') : '<p style="color:#92400e">Keine ÖNORM-Massen ermittelt.</p>';
    }
    if (detail && detailWrap) {
      detailWrap.style.display = '';
      // Prüfbare LV-Buchform: je Gewerk → Positionen mit Pos-Nr, Beschreibung,
      // Endsumme, Konfidenz, ÖNORM-Quelle + ausklappbarem Aufmaß (Σ-Zeilen je Raum).
      var html = '';
      Object.keys(gw).forEach(function (gk) {
        var g = gw[gk];
        var poss = (g.positionen || []);
        if (!poss.length) return;
        html += '<div class="lv-gewerk"><div class="lv-gewerk-titel">' + esc(g.label || gk) + '</div>';
        poss.forEach(function (p) {
          var konf = Math.round((p.konfidenz || 0) * 100);
          var tier = konf >= 80 ? 'sicher' : (konf >= 60 ? 'mittel' : 'unsicher');
          var zeilen = p.zeilen || [];
          html += '<div class="lv-pos">' +
            '<div class="lv-pos-kopf">' +
              '<span class="lv-pos-nr">' + esc(p.posnr || '') + '</span>' +
              '<span class="lv-pos-text">' + esc(p.beschreibung || '') + '</span>' +
              '<span class="lv-pos-summe">' + fmtNum(p.endsumme) + ' <em>' + esc(p.einheit || '') + '</em></span>' +
              '<span class="lv-pos-konf ' + tier + '" title="Konfidenz">' + konf + '%</span>' +
            '</div>' +
            (p.quelle ? '<div class="lv-pos-quelle">' + esc(p.quelle) + '</div>' : '');
          if (zeilen.length) {
            html += '<details class="lv-aufmass"><summary>Aufmaß · ' + zeilen.length + ' Zeile' + (zeilen.length === 1 ? '' : 'n') + '</summary><table class="lv-aufmass-tab"><tbody>';
            zeilen.forEach(function (z) {
              var masse = [];
              if (z.anzahl) masse.push(z.anzahl + '×');
              if (z.laenge) masse.push(fmtNum(z.laenge));
              if (z.breite) masse.push('×' + fmtNum(z.breite));
              if (z.hoehe) masse.push('×' + fmtNum(z.hoehe));
              html += '<tr><td>' + esc(z.text || '') + '</td><td class="num">' + esc(masse.join(' ')) + '</td>' +
                '<td class="num">' + fmtNum(z.wert) + '</td><td class="lv-z-quelle">' + esc(z.quelle || '') + '</td></tr>';
            });
            html += '</tbody></table></details>';
          }
          html += '</div>';
        });
        html += '</div>';
      });
      detail.innerHTML = html || '<p style="color:#92400e">Keine ÖNORM-Massen ermittelt.</p>';
    }

    renderReadData(data);
    renderMaterialliste(data.materialliste, data.gemessen);
  }

  // EINE Datenquelle für alle gelesenen Elemente: Räume + Fenster + Türen aus
  // der gemergten Projekt-Antwort (gleiche Zahlen wie der Fact-Strip-Kopf).
  function renderReadData(data) {
    var target = document.getElementById('projekt-massen-rooms');
    if (!target) return;
    var raeume = data.raeume || [], fenster = data.fenster || [], tueren = data.tueren || [];
    var TH = 'text-align:left;padding:0.3rem 0.5rem;background:#f8fafc';
    var THn = 'text-align:right;padding:0.3rem 0.5rem;background:#f8fafc';
    var TD = 'padding:0.3rem 0.5rem;border-bottom:1px solid #f1f3f5';
    var TDn = 'text-align:right;padding:0.3rem 0.5rem;border-bottom:1px solid #f1f3f5';
    function dash(v) { return v ? fmtNum(v) : '<span style="color:#dc2626">–</span>'; }

    // ── Räume ──
    var html = '<div class="read-sub">Räume (' + raeume.length + ')</div>';
    html += '<table style="width:100%;border-collapse:collapse;font-size:0.82rem">';
    html += '<thead><tr><th style="' + TH + '">Raum</th><th style="' + THn + '">F (m²)</th>' +
            '<th style="' + THn + '">U (m)</th><th style="' + THn + '">H (m)</th>' +
            '<th style="' + TH + '">Boden</th><th style="text-align:center;padding:0.3rem 0.5rem;background:#f8fafc">Quellen</th></tr></thead><tbody>';
    raeume.forEach(function (r) {
      var quellen = (r._quellen_plaene || []).length;
      var merged = (r._merged_from || []).join(',');
      // Höhe: abgeleitet markieren, Außenflächen klar als n.a.
      var hCell;
      if (r._h_not_applicable) hCell = '<span title="überdachte Außenfläche — keine Raumhöhe" style="color:#94a3b8">n.a.</span>';
      else if (r.hoehe_m) hCell = fmtNum(r.hoehe_m) + (r._h_inferred ? '<sup title="Geschoss-Höhe übernommen" style="color:#f39301">≈</sup>' : '');
      else hCell = '<span style="color:#dc2626">–</span>';
      html += '<tr><td style="' + TD + '">' + esc(r.name || '?') + '</td>' +
        '<td style="' + TDn + '">' + dash(r.flaeche_m2) + '</td>' +
        '<td style="' + TDn + '">' + dash(r.umfang_m) + '</td>' +
        '<td style="' + TDn + '">' + hCell + '</td>' +
        '<td style="' + TD + '">' + esc(r.bodenbelag || '') + '</td>' +
        '<td style="text-align:center;' + TD + '" title="' + esc(merged) + '">' + quellen + (merged ? ' <small style="color:#16a34a">✓merged</small>' : '') + '</td></tr>';
    });
    html += '</tbody></table>';

    // ── Öffnungen (Fenster + Türen) — gleiche deduplizierte Liste wie der Kopf ──
    function oeffTable(titel, arr) {
      if (!arr.length) return '<div class="read-sub">' + titel + ' (0)</div>';
      var h = '<div class="read-sub">' + titel + ' (' + arr.length + ')</div>';
      h += '<table style="width:100%;border-collapse:collapse;font-size:0.82rem">';
      h += '<thead><tr><th style="' + TH + '">Bez.</th><th style="' + TH + '">Raum</th>' +
           '<th style="' + THn + '">B (m)</th><th style="' + THn + '">H (m)</th>' +
           '<th style="' + THn + '">FPH</th><th style="' + THn + '">STUK</th><th style="' + TH + '">Quelle</th></tr></thead><tbody>';
      arr.forEach(function (o) {
        var q = (o.quelle || '').indexOf('stuk') >= 0 ? '<span style="color:#0f766e">Text/STUK</span>' :
                ((o.quelle || '').indexOf('vision') >= 0 ? '<span style="color:#1e40af">Vision</span>' : esc(o.quelle || ''));
        h += '<tr><td style="' + TD + '">' + esc(o.bezeichnung || '') + '</td>' +
          '<td style="' + TD + '">' + esc(o.raum || '') + '</td>' +
          '<td style="' + TDn + '">' + dash(o.breite_m) + '</td>' +
          '<td style="' + TDn + '">' + dash(o.hoehe_m) + '</td>' +
          '<td style="' + TDn + '">' + (o.fph_m ? fmtNum(o.fph_m) : '') + '</td>' +
          '<td style="' + TDn + '">' + (o.stuk_m ? fmtNum(o.stuk_m) : '') + '</td>' +
          '<td style="' + TD + '">' + q + '</td></tr>';
      });
      return h + '</tbody></table>';
    }
    html += oeffTable('Fenster', fenster);
    html += oeffTable('Türen', tueren);
    target.innerHTML = html;
  }

  function renderMaterialliste(ml, gemessen) {
    _lastML = ml; _lastGemessen = gemessen;
    var board = document.getElementById('ml-board');
    var ring = document.getElementById('trust-ring');
    var ringNum = document.getElementById('trust-ring-num');
    if (!board) return;

    // Rechenweg-Toggle + „nur Sichere"-Filter einmalig binden → neu rendern
    var tog = document.getElementById('ml-formel-toggle');
    if (tog && !tog.dataset.bound) {
      tog.dataset.bound = '1';
      tog.addEventListener('change', function () { renderMaterialliste(_lastML, _lastGemessen); });
    }
    var onlySure = document.getElementById('ml-only-sure');
    if (onlySure && !onlySure.dataset.bound) {
      onlySure.dataset.bound = '1';
      onlySure.addEventListener('change', function () { renderMaterialliste(_lastML, _lastGemessen); });
    }

    if (!ml || ml.error || !ml.bauteile) {
      board.innerHTML = '<div class="ml-empty">Noch keine Materialliste — die Pläne enthalten noch keine vollständigen Raumdaten.</div>';
      if (ringNum) ringNum.textContent = '–';
      return;
    }

    var showFormel = !!(tog && tog.checked);
    var nurSicher = !!(onlySure && onlySure.checked);
    var totalPos = 0, sicherPos = 0, sumKonf = 0;
    // Gruppen nach Konfidenz sortieren: sofort-bestellbar (grün) zuerst,
    // dann prüfen (gelb), dann am-Bau-klären (grau) — ein Polier sieht oben,
    // was sicher ist.
    var groups = Object.keys(ml.bauteile).map(function (bauteil) {
      var rows = (ml.bauteile[bauteil] || []).filter(Boolean);
      var avg = rows.length ? rows.reduce(function (a, p) { return a + (p.konfidenz || 0); }, 0) / rows.length : 0;
      return { bauteil: bauteil, rows: rows, avg: avg };
    }).filter(function (g) { return g.rows.length; });
    groups.sort(function (a, b) { return b.avg - a.avg; });

    var html = '<div class="ml-legende"><span class="ml-dot hoch"></span> sehr sicher · ' +
      '<span class="ml-dot mittel"></span> Standard-Annahme · ' +
      '<span class="ml-dot niedrig"></span> am Bau klären</div>';
    groups.forEach(function (grp, gi) {
      var gtier = grp.avg >= 0.7 ? 'hoch' : (grp.avg >= 0.5 ? 'mittel' : 'niedrig');
      // Abdeckung der Gruppe: wie viele Positionen sicher / Annahme / am-Bau-klären
      var nH = 0, nM = 0, nL = 0;
      grp.rows.forEach(function (p) {
        var k = p.konfidenz || 0;
        if (k >= 0.7) nH++; else if (k >= 0.5) nM++; else nL++;
        totalPos++; sumKonf += k; if (k >= 0.7) sicherPos++;   // Trust-Ring zählt ALLE
      });
      var tot = grp.rows.length || 1;
      var coverLbl = nH + ' von ' + grp.rows.length + ' sicher' + (nL ? ' · ' + nL + ' am Bau klären' : '');
      var bar = '<span class="ml-cover" title="' + esc(coverLbl) + '">' +
        '<span class="ml-cover-seg hoch" style="width:' + (nH / tot * 100) + '%"></span>' +
        '<span class="ml-cover-seg mittel" style="width:' + (nM / tot * 100) + '%"></span>' +
        '<span class="ml-cover-seg niedrig" style="width:' + (nL / tot * 100) + '%"></span></span>';
      var rows = nurSicher ? grp.rows.filter(function (p) { return (p.konfidenz || 0) >= 0.7; }) : grp.rows;

      html += '<section class="ml-group tier-' + gtier + '">';
      html += '<header class="ml-group-head"><span class="ml-group-ico">' + bauteilIcon(grp.bauteil) + '</span>' +
        '<span class="ml-group-name">' + esc(grp.bauteil) + '</span>' + bar +
        '<span class="ml-group-meta">' + esc(coverLbl) + '</span>' +
        '<button class="ml-copy" data-g="' + gi + '" title="Diese Gruppe in die Zwischenablage (für Excel)">⧉</button></header>';
      html += '<div class="ml-rows">';
      rows.forEach(function (p) {
        var konf = p.konfidenz || 0;
        var tier = konfTier(konf);
        var hlz = (p.material || '').match(/HLZ\s*(\d+)/i);   // Kopplung Plan ↔ Liste
        var pref = p.plan_ref || (hlz ? { layer: 'waende', snap_cm: parseInt(hlz[1], 10) } : null);
        var clickAttr = ' class="ml-row"';
        if (pref && pref.layer === 'waende' && pref.snap_cm) {
          clickAttr = ' class="ml-row ml-row-hlz" data-hlz="' + pref.snap_cm + '" title="Am Plan zeigen — die ' + pref.snap_cm + 'cm-Wände hervorheben"';
        } else if (pref && pref.layer === 'konturen') {
          clickAttr = ' class="ml-row ml-row-kontur" title="Am Plan zeigen — die Hüllen-Kontur (blau) hervorheben"';
        } else if (pref && pref.layer === 'oeffnungen') {
          clickAttr = ' class="ml-row ml-row-oeff" title="Am Plan zeigen — die Öffnungs-Marker hervorheben"';
        }
        html += '<div' + clickAttr + '>' +
          '<span class="ml-dot ' + tier.cls + '" title="' + tier.title + ' (' + Math.round(konf * 100) + '%)"></span>' +
          '<span class="ml-mat">' + esc(p.material || '') +
            (hlz ? '<span class="ml-plan-hint">📐 am Plan</span>' : '') +
            (showFormel && p.formel ? '<span class="ml-formel">' + esc(p.formel) + '</span>' : '') +
          '</span>' +
          '<span class="ml-qty">' + fmtNum(p.menge) + ' <em>' + esc(p.einheit || '') + '</em></span>' +
          '</div>';
      });
      if (nurSicher && !rows.length) html += '<div class="ml-row ml-row-empty">— alle Positionen hier sind Annahmen —</div>';
      html += '</div></section>';
    });
    board.innerHTML = html;
    // Kopier-Knöpfe je Bauteil-Gruppe (Tab-getrennt → direkt in Excel einfügbar)
    Array.prototype.forEach.call(board.querySelectorAll('.ml-copy'), function (b) {
      b.addEventListener('click', function (e) {
        e.stopPropagation();
        var g = groups[parseInt(b.getAttribute('data-g'), 10)];
        if (!g) return;
        var txt = g.rows.map(function (p) { return (p.material || '') + '\t' + fmtNum(p.menge) + '\t' + (p.einheit || ''); }).join('\n');
        if (navigator.clipboard) navigator.clipboard.writeText(txt).then(function () {
          b.textContent = '✓'; setTimeout(function () { b.textContent = '⧉'; }, 1200);
        });
      });
    });
    // Kopplung Plan ↔ Liste: HLZ-Position anklicken → zugehörige Wände am Plan hervorheben
    Array.prototype.forEach.call(board.querySelectorAll('.ml-row-hlz'), function (r) {
      r.addEventListener('click', function () { nzHighlight(parseInt(r.getAttribute('data-hlz'), 10)); });
    });
    // plan_ref-Kopplung: Konturen-/Öffnungs-Positionen pulsieren ihre Plan-Ebene
    function _pulse(selector) {
      var sec = document.getElementById('nachzeichnen-section');
      if (sec) sec.scrollIntoView({ behavior: 'smooth', block: 'start' });
      var cont = document.getElementById('nachzeichnen-container');
      if (!cont) return;
      var sel = cont.querySelectorAll(selector);
      Array.prototype.forEach.call(sel, function (el) { el.classList.add('nz-hi'); });
      setTimeout(function () {
        Array.prototype.forEach.call(sel, function (el) { el.classList.remove('nz-hi'); });
      }, 3200);
    }
    Array.prototype.forEach.call(board.querySelectorAll('.ml-row-kontur'), function (r) {
      r.addEventListener('click', function () { _pulse('polyline'); });
    });
    Array.prototype.forEach.call(board.querySelectorAll('.ml-row-oeff'), function (r) {
      r.addEventListener('click', function () { _pulse('circle'); });
    });

    // Trust-Ring: EHRLICH + dynamisch — Mischung aus Anteil sicherer Positionen
    // UND echter Durchschnitts-Konfidenz, minus Abzug für geflaggte Geometrie-
    // Unsicherheit (Slab-Kante/Umfang). So steht da nicht immer dieselbe Zahl,
    // sondern sie spiegelt die tatsächliche Datenlage des Projekts.
    var gq2 = (gemessen || {}).geometrie_qualitaet || {};
    var base = totalPos ? (sicherPos / totalPos) : 0;
    var meanK = totalPos ? (sumKonf / totalPos) : 0;
    var penalty = (gq2.umfang_verdacht_niedrig ? 0.08 : 0) + (gq2.fundament_unsicher ? 0.05 : 0) +
      (gq2.cross_check_warnung ? 0.04 : 0);
    var pct = Math.max(0, Math.min(100, Math.round((base * 0.5 + meanK * 0.5 - penalty) * 100)));
    if (ringNum) ringNum.textContent = pct + '%';
    if (ring) {
      ring.style.setProperty('--ring-pct', pct);
      ring.classList.remove('low', 'mid', 'high');
      ring.classList.add(pct >= 75 ? 'high' : (pct >= 50 ? 'mid' : 'low'));
      ring.title = sicherPos + ' von ' + totalPos + ' Positionen byte-exakt (≥70%); Ø-Konfidenz ' +
        Math.round(meanK * 100) + '%' + (penalty ? '; −' + Math.round(penalty * 100) + ' wg. unsicherer Geometrie' : '');
    }

    // HERO-Status: 3-stufiges Bau-Signal statt nacktem Prozent
    var statusEl = document.getElementById('result-hero-status');
    if (statusEl) {
      statusEl.classList.remove('st-green', 'st-yellow', 'st-red');
      // EHRLICH: das ist eine Mengenermittlung (Schätzung aus dem Plan), KEINE
      // Bestellgarantie — der Polier prüft/gegenrechnet immer. Darum nicht
      // "bereit zum Bestellen", sondern Mengenermittlungs-Sprache.
      if (pct >= 75) { statusEl.textContent = '✓ Mengenermittlung abgeschlossen'; statusEl.classList.add('st-green'); }
      else if (pct >= 50) { statusEl.textContent = '⚠ Mengen ermittelt — Geometrie noch prüfen'; statusEl.classList.add('st-yellow'); }
      else { statusEl.textContent = '⛔ Mengen unsicher — am Plan nachprüfen'; statusEl.classList.add('st-red'); }
    }
  }

  function fmtNum(n) {
    if (n == null || isNaN(n)) return '–';
    return Number(n).toLocaleString('de-AT', { maximumFractionDigits: 2 });
  }

  // ─── Projekt-Export-Button (CSV mit allen Daten + Materialliste) ───
  function doExport(format, btn) {
    var orig = btn.innerHTML;
    btn.disabled = true; btn.textContent = 'Wird exportiert...';
    var payload = { projekt_id: projectId };
    if (format) payload.export_format = format;
    if (_filterState.gewerke) payload.gewerke_filter = _filterState.gewerke;
    if (_filterState.plan_ids) payload.plan_ids = _filterState.plan_ids;
    if (_filterState.baudaten_override) payload.baudaten_override = _filterState.baudaten_override;
    if (_filterState.materialliste_override) payload.materialliste_override = _filterState.materialliste_override;
    fetch('/api/projekt-export', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload)
    })
      .then(function (r) { if (!r.ok) throw new Error('Export-Status ' + r.status); return r.blob(); })
      .then(function (blob) {
        var url = window.URL.createObjectURL(blob);
        var a = document.createElement('a'); a.href = url;
        a.download = (format === 'rohbau' ? 'materialliste-' :
                      format === 'oenorm' ? 'oenorm-massenermittlung-' :
                      'projekt-massenermittlung-') +
          (projectId || 'export').slice(0, 8) + '.csv';
        document.body.appendChild(a); a.click(); document.body.removeChild(a);
        window.URL.revokeObjectURL(url);
      })
      .catch(function (e) { alert('Export-Fehler: ' + e.message); })
      .finally(function () { btn.disabled = false; btn.innerHTML = orig; });
  }
  function bindProjektExport() {
    var btn = document.getElementById('projekt-export-btn');       // saubere Materialliste (Polier)
    if (btn && !btn.dataset.bound) { btn.dataset.bound = '1';
      btn.addEventListener('click', function () { doExport('rohbau', btn); }); }
    var btnOe = document.getElementById('projekt-export-oenorm-btn'); // nur ÖNORM-Massenermittlung
    if (btnOe && !btnOe.dataset.bound) { btnOe.dataset.bound = '1';
      btnOe.addEventListener('click', function () { doExport('oenorm', btnOe); }); }
    var btnFull = document.getElementById('projekt-export-voll-btn'); // voller Dump
    if (btnFull && !btnFull.dataset.bound) { btnFull.dataset.bound = '1';
      btnFull.addEventListener('click', function () { doExport(null, btnFull); }); }
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

    // Planansicht/Ergebnis ERST wenn ALLE Pläne fertig analysiert sind — sonst
    // ändern sich Räume/Mengen noch. Einzelne fertige Pläne werden noch nicht geöffnet.
    var alleFertig = plans.every(function (p) { return p.verarbeitet === true; });
    plans.forEach(function (plan) {
      var card = document.createElement('div');
      card.className = 'card plan-card';
      var done = plan.verarbeitet === true;       // dieser Plan ist analysiert
      var darfOeffnen = done && alleFertig;        // Öffnen erst wenn ALLE fertig
      var konfBadge = '';
      if (done && plan.gesamt_konfidenz != null) {
        var kVal = Math.round(plan.gesamt_konfidenz);
        var kClass = kVal >= 80 ? 'confidence-green' : (kVal >= 60 ? 'confidence-yellow' : 'confidence-red');
        konfBadge = ' <span class="confidence ' + kClass + '"><span class="confidence-dot dot-red"></span><span class="confidence-dot dot-yellow"></span><span class="confidence-dot dot-green"></span><span class="confidence-value">' + kVal + '%</span></span>';
      }

      // Karten erst klickbar (→ Planansicht/Ergebnis), wenn ALLE Pläne fertig sind
      if (darfOeffnen) {
        card.classList.add('plan-card-clickable');
        card.setAttribute('data-plan-id', plan.id);
        card.title = 'Klicken um Ergebnisse und Korrektur-Ansicht zu öffnen';
      }
      var statusTxt = done ? (darfOeffnen ? ' · klicken zum Öffnen'
          : ' · analysiert — Ergebnis erscheint, sobald alle Pläne fertig sind') : '';
      card.innerHTML =
        '<div class="plan-info"><div class="plan-icon">&#128196;</div><div>' +
          '<div class="plan-name">' + esc(plan.dateiname || '') + '</div>' +
          '<div class="plan-status"><span class="badge ' + (done ? 'badge-fertig' : 'badge-neu') + '">' + (done ? 'Analysiert' : 'Hochgeladen') + '</span>' + konfBadge + '<span style="font-size:0.75rem;color:#6c757d">' + statusTxt + '</span></div>' +
        '</div></div>' +
        '<div class="plan-actions">' +
          (done
            ? (darfOeffnen ? '<button class="btn btn-primary btn-sm res-btn" data-id="' + plan.id + '">&Ouml;ffnen</button>' : '') +
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

    // Neu-auslesen-Button: erzwingt eine frische Analyse (umgeht den Konstanz-Freeze)
    planList.querySelectorAll('.reana-btn').forEach(function (b) {
      b.addEventListener('click', function () {
        var btn = this;
        var planId = btn.getAttribute('data-id');
        if (!confirm('Plan neu auslesen? Das verwirft das gespeicherte Ergebnis und analysiert frisch.')) return;
        startAnalysis(planId, btn, null, true);
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
  function startAnalysis(planId, btn, onDone, force) {
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
      body: JSON.stringify({ plan_id: planId, force: !!force })
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

  // ── RAUM-AUFMASS: jeder Raum einzeln — Boden byte-exakt · Decke · Abwicklung · Sockel ──
  function renderRaumAufmass(raeume, baudaten) {
    var el = document.getElementById('raum-aufmass');
    if (!el) return;
    var innen = (raeume || []).filter(function (r) { return r && r.flaeche_m2; });
    if (!innen.length) { el.innerHTML = ''; return; }
    var hDef = (baudaten || {}).geschosshoehe_m || 2.7;
    var sF = 0, sW = 0, sU = 0;
    var html = '<h4 class="advanced-h" style="margin-top:1.1rem">Raum-Aufmaß — jeder Raum einzeln ' +
      '(F/U byte-exakt aus den Raum-Stempeln des Plans)</h4>' +
      '<table class="oa-tab"><thead><tr><th>Raum</th><th>Boden (=F)</th><th>Decke</th><th>Umfang U</th>' +
      '<th>Höhe</th><th>Wandabwicklung U×H</th><th>Sockel</th></tr></thead><tbody>';
    innen.forEach(function (r) {
      var aussen = !!r._h_not_applicable;
      var h = r.hoehe_m || (aussen ? null : hDef);
      var u = r.umfang_m || null;
      var wf = (u && h) ? Math.round(u * h * 100) / 100 : null;
      if (!aussen) { sF += r.flaeche_m2 || 0; if (wf) sW += wf; if (u) sU += u; }
      html += '<tr' + (aussen ? ' style="opacity:.6"' : '') + '><td>' + esc(r.name || '?') +
        (aussen ? ' <span title="überdachte Außenfläche">☂</span>' : '') + '</td>' +
        '<td>' + fmtNum(r.flaeche_m2) + ' m² ✓</td>' +
        '<td>' + (aussen ? '–' : fmtNum(r.flaeche_m2) + ' m²') + '</td>' +
        '<td>' + (u ? fmtNum(u) + ' m ✓' : '–') + '</td>' +
        '<td>' + (h ? fmtNum(h) + ' m' + (r.hoehe_m ? ' ✓' : ' ≈') : '–') + '</td>' +
        '<td>' + (wf ? fmtNum(wf) + ' m²' : '–') + '</td>' +
        '<td>' + (u && !aussen ? fmtNum(u) + ' lfm' : '–') + '</td></tr>';
    });
    html += '</tbody></table><div class="oa-summe">Σ Innenräume: Boden <strong>' +
      fmtNum(Math.round(sF * 100) / 100) + ' m²</strong> · Wandabwicklung <strong>' +
      fmtNum(Math.round(sW * 100) / 100) + ' m²</strong> · Sockel <strong>' +
      fmtNum(Math.round(sU * 100) / 100) + ' lfm</strong> — ✓ = byte-exakt aus dem Plan-Text, ' +
      '≈ = Geschoss-Höhe übernommen. Öffnungs-Abzüge: siehe Öffnungs-Aufmaß.</div>';
    el.innerHTML = html;
  }

  // ── WAND-AUFMASS: jede Wand einzeln, aus der Planansicht — LIVE mit Korrekturen ──
  function renderWandAufmass() {
    var el = document.getElementById('wand-aufmass');
    if (!el) return;
    if (!_nzData || !_nzData.waende || !_nzData.waende.length) { el.innerHTML = ''; return; }
    var bd = (window.projektMassenData || {}).baudaten || {};
    var h = bd.geschosshoehe_m || 2.7;
    // WAND↔ÖFFNUNG-ZUORDNUNG: jede Öffnung zur nächstliegenden Wand (Punkt-Segment-
    // Distanz in Bild-Pixeln) → je Wand brutto − Öffnungen = NETTO (ÖNORM: nur >4m² Abzug)
    function distSeg(px, py, p) {
      var dx = p[2] - p[0], dy = p[3] - p[1];
      var t = dx || dy ? Math.max(0, Math.min(1, ((px - p[0]) * dx + (py - p[1]) * dy) / (dx * dx + dy * dy))) : 0;
      var qx = p[0] + t * dx - px, qy = p[1] + t * dy - py;
      return Math.sqrt(qx * qx + qy * qy);
    }
    var wandOeff = {};   // wand-id → [{typ, b, hh, fl, abzug}]
    (_nzData.oeffnungen || []).forEach(function (o) {
      if (_nzEdit.oeffRemoved && _nzEdit.oeffRemoved[o.id]) return;
      var best = null;
      (_nzData.waende || []).forEach(function (w) {
        if (_nzEdit.removed && _nzEdit.removed[w.id]) return;
        if (!_nzCm(w)) return;
        var d = distSeg(o.px[0], o.px[1], w.px);
        if (best === null || d < best.d) best = { d: d, id: w.id, sw: w.staerke_px || 6 };
      });
      if (!best || best.d > best.sw * 2.5 + 25) return;   // zu weit weg von jeder Wand
      var fl = (o.breite_m && o.hoehe_m) ? Math.round(o.breite_m * o.hoehe_m * 100) / 100 : null;
      (wandOeff[best.id] = wandOeff[best.id] || []).push({
        typ: o.typ, fl: fl, abzug: (fl && fl > 4.0) ? fl : 0
      });
    });
    var rows = [], sums = {};
    (_nzData.waende || []).forEach(function (w) {
      if (_nzEdit.removed && _nzEdit.removed[w.id]) return;
      var cm = _nzCm(w);
      if (!cm) return;
      var brutto = Math.round(w.laenge_m * h * 100) / 100;
      var oe = wandOeff[w.id] || [];
      var abzug = Math.round(oe.reduce(function (a, x) { return a + x.abzug; }, 0) * 100) / 100;
      var netto = Math.round((brutto - abzug) * 100) / 100;
      rows.push({ id: w.id, cm: cm, l: w.laenge_m, exakt: !!w.mass_exakt,
        manuell: !!w.manuell, achse: w.achse, brutto: brutto,
        nOeff: oe.length, abzug: abzug, netto: netto });
      sums[cm] = sums[cm] || { n: 0, l: 0, m2: 0 };
      sums[cm].n++; sums[cm].l += w.laenge_m; sums[cm].m2 += netto;
    });
    if (!rows.length) { el.innerHTML = ''; return; }
    rows.sort(function (a, b) { return b.cm - a.cm || b.l - a.l; });
    var html = '<h4 class="advanced-h" style="margin-top:1.1rem">Wand-Aufmaß — jede Wand einzeln ' +
      '(aus der Planansicht · Höhe ' + fmtNum(h) + ' m · aktualisiert sich mit deinen Korrekturen)</h4>' +
      '<div class="oa-summe">' + Object.keys(sums).sort(function (a, b) { return b - a; }).map(function (t) {
        return 'HLZ ' + t + ': ' + sums[t].n + ' Wände · Σ ' + fmtNum(Math.round(sums[t].l * 100) / 100) +
          ' m · <strong>' + fmtNum(Math.round(sums[t].m2 * 100) / 100) + ' m²</strong> netto';
      }).join(' &nbsp;|&nbsp; ') + '</div>' +
      '<table class="oa-tab"><thead><tr><th>Wand</th><th>Stärke</th><th>Länge</th><th>Höhe</th>' +
      '<th>brutto</th><th>Öffnungen</th><th>Abzug >4m²</th><th>netto</th><th>Quelle</th></tr></thead><tbody>';
    rows.forEach(function (r) {
      html += '<tr><td>W' + r.id + ' (' + (r.achse === 'v' ? 'vert.' : 'horiz.') + ')</td>' +
        '<td>HLZ ' + r.cm + '</td>' +
        '<td>' + fmtNum(r.l) + ' m' + (r.exakt ? ' <span title="Länge = byte-exakte Plan-Maßzahl">✓</span>' : '') + '</td>' +
        '<td>' + fmtNum(h) + ' m</td>' +
        '<td>' + fmtNum(r.brutto) + ' m²</td>' +
        '<td>' + (r.nOeff || '–') + '</td>' +
        '<td>' + (r.abzug ? '−' + fmtNum(r.abzug) + ' m²' : '–') + '</td>' +
        '<td><strong>' + fmtNum(r.netto) + ' m²</strong></td>' +
        '<td>' + (r.manuell ? 'manuell ergänzt' : (r.exakt ? 'Plan-Maßzahl (byte-exakt)' : 'Vektor-Messung')) + '</td></tr>';
    });
    el.innerHTML = html + '</tbody></table>' +
      '<div class="oa-summe">Öffnungen der nächstliegenden Wand zugeordnet; Abzug nur >4,0 m² ' +
      '(ÖNORM B 2204 — kleinere übermessen, Laibungen siehe Öffnungs-Aufmaß).</div>';
  }

  // ── ÖFFNUNGS-AUFMASS: jede Öffnung einzeln, mit ÖNORM-Regel + Laibungs-Formel ──
  function renderOeffnungsAufmass(oa) {
    var el = document.getElementById('oeffnungs-aufmass');
    if (!el) return;
    if (!oa || !oa.zeilen || !oa.zeilen.length) { el.innerHTML = ''; return; }
    var s = oa.summen || {};
    var html = '<h4 class="advanced-h" style="margin-top:1.1rem">Öffnungs-Aufmaß — jede Öffnung einzeln (' +
      esc(oa.norm || '') + ')</h4>' +
      '<div class="oa-summe">' + s.n + ' Öffnungen · ' + s.n_uebermessen + ' übermessen (≤4,0 m²) · ' +
      s.n_abzug + ' mit Abzug — Σ Abzug <strong>' + fmtNum(s.abzug_m2) + ' m²</strong>, Σ Laibungen <strong>' +
      fmtNum(s.laibung_m2) + ' m²</strong></div>' +
      '<table class="oa-tab"><thead><tr><th>Raum</th><th>Typ</th><th>Wand</th><th>B×H</th><th>Fläche</th>' +
      '<th>Regel</th><th>Abzug</th><th>Laibung</th><th>Rechenweg</th></tr></thead><tbody>';
    oa.zeilen.forEach(function (z) {
      html += '<tr' + (z.abzug_m2 > 0 ? ' class="oa-abzug"' : '') + '>' +
        '<td>' + esc(z.raum || '–') + '</td>' +
        '<td>' + (z.typ === 'tuer' ? 'Tür' : 'Fenster') + '</td>' +
        '<td>' + esc(z.wand) + '</td>' +
        '<td>' + fmtNum(z.breite_m) + '×' + fmtNum(z.hoehe_m) + '</td>' +
        '<td>' + fmtNum(z.flaeche_m2) + ' m²</td>' +
        '<td>' + esc(z.regel) + '</td>' +
        '<td>' + (z.abzug_m2 ? '−' + fmtNum(z.abzug_m2) + ' m²' : '–') + '</td>' +
        '<td>' + (z.laibung_m2 ? '+' + fmtNum(z.laibung_m2) + ' m²' + (z.sohlbank ? ' (inkl. Sohlbank)' : '') : '–') + '</td>' +
        '<td class="oa-formel">' + esc(z.formel) + '</td></tr>';
    });
    el.innerHTML = html + '</tbody></table>';
  }

  // Firmen-Selbst-Kalibrierung ENTFERNT — Korrektur passiert jetzt direkt am Plan
  // (Nachzeichnen) statt über gelernte Firmen-Faktoren (jeder Plan ist ein anderes Gebäude).
  function renderKalibrierungStatus() { /* no-op: Feature entfernt */ }

  // ── PROJEKT-CHATBOT: Fragen zur fertigen Auswertung (read-only, gegroundet) ──
  function buildChatContext(d) {
    if (!d) return {};
    var ml = d.materialliste || {};
    return {
      bau_kenndaten: d.baudaten,
      kennzahlen: ml.kennzahlen,
      herkunft_der_zahlen: d.herkunft,
      materialliste_je_bauteil: (ml && ml.bauteile) || {},
      raeume: (d.raeume || []).map(function (r) {
        return { name: r.name, flaeche_m2: r.flaeche_m2, umfang_m: r.umfang_m, hoehe_m: r.hoehe_m, bodenbelag: r.bodenbelag };
      }),
      fenster_anzahl: d.fenster_count, tueren_anzahl: d.tueren_count,
      doppelcheck: d.doppelcheck,
      pruefliste: d.pruefliste,
      plausibilitaets_hinweise: (d.konsistenz && d.konsistenz.findings) || [],
      schlusspruefung: d.opus_pruefung,
      kalibrierung_aktiv: d.kalibrierung,
      bauteil_legende: d.legende
    };
  }
  function wireChat() {
    var sendBtn = document.getElementById('chat-send');
    var input = document.getElementById('chat-input');
    var log = document.getElementById('chat-log');
    var suggest = document.getElementById('chat-suggest');
    if (!sendBtn || !input || !log) return;
    var verlauf = [];
    var SUGGEST = ['Wie viel Beton für die Decke — und warum?', 'Welche Positionen soll ich am Plan prüfen?',
      'Wie verlässlich ist die Außenwand-Menge?', 'Was steckt hinter den HLZ-Paletten?'];
    function renderSuggest() {
      if (!suggest) return;
      suggest.innerHTML = SUGGEST.map(function (s) { return '<button class="chat-chip" type="button">' + esc(s) + '</button>'; }).join('');
      Array.prototype.forEach.call(suggest.querySelectorAll('.chat-chip'), function (b) {
        b.addEventListener('click', function () { input.value = b.textContent; send(); });
      });
    }
    function addMsg(role, text) {
      var div = document.createElement('div');
      div.className = 'chat-msg chat-' + role;
      div.innerHTML = esc(text).replace(/\n/g, '<br>');
      log.appendChild(div); log.scrollTop = log.scrollHeight;
      return div;
    }
    function send() {
      var q = (input.value || '').trim();
      if (!q) return;
      if (!window.projektMassenData) { addMsg('assistant', 'Die Auswertung ist noch nicht geladen.'); return; }
      addMsg('user', q); input.value = ''; if (suggest) suggest.innerHTML = '';
      sendBtn.disabled = true;
      var pending = addMsg('assistant', '…'); pending.classList.add('chat-pending');
      fetch('/api/projekt-chat', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ frage: q, kontext: buildChatContext(window.projektMassenData), verlauf: verlauf.slice(-8) })
      })
        .then(function (r) { return r.json().then(function (j) { return { ok: r.ok, j: j }; }); })
        .then(function (o) {
          var ans = o.ok ? (o.j.antwort || '') : ('Fehler: ' + ((o.j && o.j.detail) || 'Chat nicht verfügbar'));
          pending.classList.remove('chat-pending'); pending.innerHTML = esc(ans).replace(/\n/g, '<br>');
          log.scrollTop = log.scrollHeight;
          verlauf.push({ role: 'user', text: q }); verlauf.push({ role: 'assistant', text: ans });
        })
        .catch(function (e) { pending.classList.remove('chat-pending'); pending.textContent = 'Fehler: ' + e.message; })
        .finally(function () { sendBtn.disabled = false; });
    }
    sendBtn.addEventListener('click', send);
    input.addEventListener('keydown', function (e) { if (e.key === 'Enter') { e.preventDefault(); send(); } });
    renderSuggest();
  }
  wireChat();

  // ── NACHZEICHNEN-OVERLAY: Plan + erkannte Wände — anklickbar korrigieren ──
  var NZ_FARBE = { 50: '#dc1e1e', 38: '#f08c00', 25: '#1e50dc', 20: '#14a03c', 12: '#9628c8' };
  var _nzGeladen = false, _nzLaeuft = false;
  var _nzData = null;
  var _nzEdit = { removed: {}, thick: {}, aussen: {} };  // id → bool / cm / bool
  var _nzSel = null;
  var _nzZoom = { s: 1, x: 0, y: 0 }, _nzMoved = false;   // Zoom/Pan-Zustand + Drag-Erkennung
  var _nzWrap = null, _nzPan = null, _nzZoomWinBound = false;
  var _nzAddMode = false, _nzDraw = null;   // "Wand hinzufügen"-Modus + laufende Zeichnung

  function _nzCm(w) { return _nzEdit.thick[w.id] != null ? _nzEdit.thick[w.id] : w.snap_cm; }
  function _nzAussenDefault(cm) { return cm === 50 || cm === 38; }  // 20/12 immer innen, 25 default innen
  function _nzIstAussen(w, cm) {
    if (cm === 20 || cm === 12) return false;
    if (cm === 50 || cm === 38) return true;
    return _nzEdit.aussen[w.id] != null ? _nzEdit.aussen[w.id] : false;  // 25cm: default innen
  }

  function _nzSplit() {
    // Summen je Stärke + außen/innen-Split aus dem KORRIGIERTEN Zustand.
    var o = { 50: 0, 38: 0, 25: 0 }, i = { 25: 0, 20: 0, 12: 0 }, ges = {};
    (_nzData.waende || []).forEach(function (w) {
      if (_nzEdit.removed[w.id]) return;
      var cm = _nzCm(w);
      if ([50, 38, 25, 20, 12].indexOf(cm) < 0) return;
      ges[cm] = (ges[cm] || 0) + w.laenge_m;
      if (_nzIstAussen(w, cm)) o[cm] = (o[cm] || 0) + w.laenge_m;
      else i[cm] = (i[cm] || 0) + w.laenge_m;
    });
    var ot = o[50] + o[38] + o[25], it = i[25] + i[20] + i[12];
    var anteile = null;
    if (ot > 0 && it > 0) {
      var pct = function (x, t) { return Math.round(x / t * 1000) / 10; };
      anteile = {
        wand_anteil_50cm: pct(o[50], ot), wand_anteil_38cm: pct(o[38], ot),
        wand_anteil_25cm_aussen: pct(o[25], ot), wand_anteil_25cm_innen: pct(i[25], it),
        wand_anteil_20cm: pct(i[20], it), wand_anteil_12cm: pct(i[12], it)
      };
    }
    return { ges: ges, o: o, i: i, ot: ot, it: it, anteile: anteile };
  }

  function _nzPaint() {
    if (!_nzData) return;
    var W = _nzData.bild_w, H = _nzData.bild_h, meta = _nzData.meta || {};
    var fs = Math.max(13, Math.round(W / 78));   // Label-Schriftgröße relativ zur Bildbreite
    var lines = '', labels = '';
    // BYTE-EXAKTE WANDFLUCHTEN (Maßketten-Snap): jede Linie ist eine Wandflucht
    // laut Plan-Bemaßung — grün = von der Wand-Erkennung bestätigt, rot = dort
    // fehlt eine Wand in der Erkennung (oder die Kette misst etwas anderes).
    // HÖHENKOTEN (Schnitt-Blätter): byte-exakt gelesene ±-Koten als Marker —
    // auch Schnitt-/Ansichts-Blätter sind damit nachvollziehbar erschlossen.
    (_nzData.koten || []).forEach(function (k) {
      lines += '<circle cx="' + k.px[0] + '" cy="' + k.px[1] + '" r="5" fill="#7c3aed"' +
        ' fill-opacity="0.55" stroke="#fff" stroke-width="1"><title>Höhenkote ' +
        esc(k.wert) + ' m (byte-exakt)</title></circle>';
    });
    // DACH-/ZIMMERER-MARKER (byte-exakt am Dachplan eingezeichnet): Velux-Fenster
    // am Fensterort, Dachflächen-Summe als Callout — der Dachdecker sieht, WO
    // die Mengen herkommen (Nachvollziehbarkeit für den neuen Sektor).
    (_nzData.dach_marker || []).forEach(function (m2) {
      var col = m2.art === 'fenster' ? '#ea580c' : '#166534';
      lines += '<circle cx="' + m2.px[0] + '" cy="' + m2.px[1] + '" r="7" fill="' + col +
        '" fill-opacity="0.5" stroke="#fff" stroke-width="1.5"><title>' + esc(m2.label) +
        ' (byte-exakt vom Plan)</title></circle>';
      labels += '<text x="' + (m2.px[0] + 10) + '" y="' + (m2.px[1] + 4) + '" font-size="' +
        Math.round(fs * 0.9) + '" fill="' + col + '" stroke="#fff" stroke-width="0.6"' +
        ' paint-order="stroke">' + esc(m2.label) + '</text>';
    });
    // GEMAUERTE HÜLLE (Kontur der Wand-Maske): der Außenumfang treibt die
    // halbe Materialliste — hier ist er am Plan sichtbar und gegen die
    // gerechnete Zahl prüfbar (ÖNORM-B-2110-Prinzip: prüfbare Mengen).
    (_nzData.konturen || []).forEach(function (k, ki) {
      if (!k.px || k.px.length < 3) return;
      var pts = k.px.map(function (p) { return p[0] + ',' + p[1]; }).join(' ');
      lines += '<polyline points="' + pts + '" fill="none" stroke="#1d4ed8"' +
        ' stroke-width="2.2" stroke-opacity="0.55" stroke-dasharray="10 5"' +
        ' pointer-events="stroke"><title>Gemauerte Hülle (erkannt): Umfang ≈ ' +
        k.umfang_m + ' m' + (ki === 0 ? ' — vergleiche mit dem Außenumfang im Geo-Kasten' : '') +
        '</title></polyline>';
    });
    var nFlOk = 0, nFl = 0;
    (_nzData.fluchten || []).forEach(function (f) {
      nFl++; if (f.ok) nFlOk++;
      var fcol = f.ok ? '#16a34a' : (f.kurz ? '#f59e0b' : '#dc2626');
      var x1 = f.achse === 'v' ? f.px : 0, y1 = f.achse === 'v' ? 0 : f.px;
      var x2 = f.achse === 'v' ? f.px : W, y2 = f.achse === 'v' ? H : f.px;
      lines += '<line x1="' + x1 + '" y1="' + y1 + '" x2="' + x2 + '" y2="' + y2 +
        '" stroke="' + fcol + '" stroke-width="1.2" stroke-opacity="' + (f.ok ? 0.32 : 0.42) +
        '" stroke-dasharray="3 6" pointer-events="stroke"><title>Wandflucht lt. Maßkette (byte-exakt)' +
        (f.ok ? ' — ✓ von der Wand-Erkennung bestätigt'
              : (f.kurz ? ' — kurze Kante (Öffnungs-Laibung/Pfeiler) — plausibel'
                        : ' — ✗ hier fehlt eine Wand in der Erkennung → prüfen')) +
        '</title></line>';
    });
    (_nzData.waende || []).forEach(function (w) {
      var cm = _nzCm(w), rm = !!_nzEdit.removed[w.id], sel = (_nzSel === w.id);
      var col = rm ? '#b8c0cc' : (NZ_FARBE[cm] || '#888');
      var unsicher = !cm || (w.hatch_dichte != null && w.hatch_dichte < 1.5);
      var p = w.px;
      lines += '<line data-wid="' + w.id + '" data-cm="' + (cm || '') + '" x1="' + p[0] + '" y1="' + p[1] + '" x2="' + p[2] + '" y2="' + p[3] +
        '" stroke="' + col + '" stroke-width="' + Math.max(2, w.staerke_px) + '" stroke-linecap="round"' +
        ' stroke-opacity="' + (rm ? 0.3 : 0.82) + '"' + (sel ? ' style="filter:drop-shadow(0 0 4px #000)"' : '') +
        ((unsicher || rm) ? ' stroke-dasharray="6 5"' : '') + ' cursor="pointer"><title>' +
        (cm ? 'HLZ ' + cm + 'cm' : '~' + w.dicke_cm + 'cm') + ' · ' + w.laenge_m + ' m' +
        (w.mass_exakt ? ' (= Maßzahl lt. Plan)' : '') + ' — klicken zum Korrigieren</title></line>';
      // Sichtbares Längen-/Stärke-Label auf der Wand (1:1 zum Plan vergleichbar)
      if (!rm && cm && w.laenge_m >= 1.2) {
        var mx = (p[0] + p[2]) / 2, my = (p[1] + p[3]) / 2;
        var txt = 'HLZ' + cm + ' · ' + fmtNum(w.laenge_m) + 'm';
        labels += '<text x="' + mx + '" y="' + my + '" font-size="' + fs + '" text-anchor="middle" dy="' +
          (w.achse === 'h' ? -fs * 0.5 : fs * 0.35) + '" paint-order="stroke" stroke="#fff" stroke-width="' +
          Math.round(fs / 3.5) + '" fill="' + col + '" style="font-weight:600;pointer-events:none">' + txt + '</text>';
      }
    });
    // Öffnungs-Marker (Fenster/Türen aus dem Text-Layer, byte-exakt) — anklicken = keine Öffnung
    var marker = '', nF = 0, nT = 0;
    _nzEdit.oeffRemoved = _nzEdit.oeffRemoved || {};
    (_nzData.oeffnungen || []).forEach(function (o) {
      var rm = !!_nzEdit.oeffRemoved[o.id], istF = o.typ === 'fenster';
      if (!rm) { if (istF) nF++; else nT++; }
      var mcol = istF ? '#0284c7' : '#b45309', rad = Math.max(9, fs * 0.72);
      marker += '<g data-oid="' + o.id + '" cursor="pointer" opacity="' + (rm ? 0.28 : 0.95) + '">' +
        '<circle cx="' + o.px[0] + '" cy="' + o.px[1] + '" r="' + rad + '" fill="' + mcol + '" stroke="#fff" stroke-width="2"/>' +
        '<text x="' + o.px[0] + '" y="' + o.px[1] + '" font-size="' + Math.round(rad * 1.1) + '" text-anchor="middle" dy="' +
        Math.round(rad * 0.38) + '" fill="#fff" style="font-weight:700;pointer-events:none">' + (istF ? 'F' : 'T') + '</text>' +
        '<title>' + (istF ? 'Fenster' : 'Tür') + (o.breite_m ? ' ' + fmtNum(o.breite_m) + '×' + fmtNum(o.hoehe_m) + 'm' : '') +
        ' — klicken = keine Öffnung</title></g>';
    });
    // RAUM-VERIFIKATION: grün = Geometrie gegen die Plan-Stempel (F+U) BEWIESEN,
    // gelb = prüfen. Der Plan validiert sich selbst.
    var nRaumOk = 0, nRaumF = 0, raumBadges = '';
    (_nzData.raeume || []).forEach(function (r) {
      // 3 Stufen: voll verifiziert (F+U) · Fläche bestätigt (F exakt, U prüfen) · prüfen
      var ok = r.status === 'verifiziert' || r.rohbau_ok || r.iou_bewiesen;
      var fOk = !ok && r.status === 'u_daneben';
      if (ok) nRaumOk++; else if (fOk) nRaumF++;
      var col = ok ? '#16a34a' : (fOk ? '#0d9488' : '#d97706');
      var tip = (r.name || '?') + ' — F ' + fmtNum(r.f_m2) + ' m² lt. Plan' +
        (r.f_ist != null ? ' (rekonstruiert ' + fmtNum(r.f_ist) + ')' : '');
      if (r.u_m) {
        tip += ' · U ' + fmtNum(r.u_m) + ' m' + (r.u_ist != null ? ' (rek. ' + fmtNum(r.u_ist) + ')' : '');
        // Soll-Rechteck aus F+U (byte-exakt eindeutig): a+b=U/2, a·b=F
        var p2 = r.u_m / 2, disc = p2 * p2 / 4 - r.f_m2;
        if (disc >= 0) {
          var wu = Math.sqrt(disc);
          tip += ' · Soll-Form (falls rechteckig) ≈ ' + fmtNum(Math.round((p2 / 2 + wu) * 100) / 100) + '×' +
            fmtNum(Math.round((p2 / 2 - wu) * 100) / 100) + ' m';
        }
      }
      if (r.iou_bewiesen) {
        tip += ' — ✓✓ RÄUMLICH BEWIESEN: ' + r.iou_form + ' deckt die Raumfläche zu ' +
          Math.round(r.iou_wert * 100) + '% (byte-exakte Fluchten; höchste Beweisstufe)';
      } else if (r.rohbau_ok && r.status !== 'verifiziert') {
        tip += ' — ✓ ROHBAU-' + (r.rohbau_form === 'l' ? 'L-Polygon' : 'Rechteck') +
          ' aus Maßketten bestätigt (' + fmtNum(r.f_rohbau) + ' m²; Stempel misst Fertigmaß)';
      } else
      tip += ok ? ' — ✓ Fläche+Umfang bestätigt'
        : (fOk ? ' — ✓ Fläche exakt; Umfang weicht ab → Form prüfen (mögliche Phantom-Wand/offene Stelle)'
               : ' — bitte prüfen');
      raumBadges += '<g><circle cx="' + r.px[0] + '" cy="' + (r.px[1] - fs * 1.6) + '" r="' + (fs * 0.62) + '"' +
        ' fill="' + col + '" stroke="#fff" stroke-width="2"/>' +
        '<text x="' + r.px[0] + '" y="' + (r.px[1] - fs * 1.6) + '" font-size="' + Math.round(fs * 0.75) + '"' +
        ' text-anchor="middle" dy="' + Math.round(fs * 0.26) + '" fill="#fff" style="font-weight:700;pointer-events:none">' +
        (ok || fOk ? '✓' : '?') + '</text><title>' + tip + '</title></g>';
      // PRÜF-RÄUME sichtbar am Plan beschriften (nicht nur im Tooltip): erkannte
      // Fläche + Abweichung, damit die zu prüfenden Stellen ohne Hover auffallen.
      if (!ok && r.f_ist != null && r.f_m2) {
        var dpct = Math.round((r.f_ist - r.f_m2) / r.f_m2 * 100);
        var note = fOk ? 'Umfang prüfen' : ('erkannt ' + fmtNum(r.f_ist) + ' (' + (dpct >= 0 ? '+' : '') + dpct + '%)');
        raumBadges += '<text x="' + (r.px[0] + fs * 0.9) + '" y="' + (r.px[1] - fs * 1.6) + '"' +
          ' font-size="' + Math.round(fs * 0.62) + '" dy="' + Math.round(fs * 0.22) + '" fill="' + col +
          '" stroke="#fff" stroke-width="0.7" paint-order="stroke" style="pointer-events:none">' +
          note + '</text>';
      }
    });
    var s = _nzSplit(), ges = s.ges;
    var legend = '';
    if (_nzData.raeume && _nzData.raeume.length) {
      legend += '<span class="nz-leg-item"><span class="nz-sw" style="background:#16a34a;border-radius:50%"></span>' +
        '<strong>' + nRaumOk + '</strong>&nbsp;voll bestätigt</span>' +
        '<span class="nz-leg-item"><span class="nz-sw" style="background:#0d9488;border-radius:50%"></span>' +
        '<strong>' + nRaumF + '</strong>&nbsp;Fläche exakt (Umfang prüfen)</span>' +
        '<span class="nz-leg-item">von <strong>' + _nzData.raeume.length + '</strong> Räumen</span>';
    }
    [50, 38, 25, 20, 12].forEach(function (t) {
      if (!ges[t]) return;
      legend += '<span class="nz-leg-item"><span class="nz-sw" style="background:' + NZ_FARBE[t] + '"></span>' +
        'HLZ ' + t + 'cm: <strong>' + fmtNum(ges[t]) + ' m</strong></span>';
    });
    if (_nzData.oeffnungen && _nzData.oeffnungen.length) {
      legend += '<span class="nz-leg-item"><span class="nz-sw" style="background:#0284c7;border-radius:50%"></span>' +
        '<strong>' + nF + '</strong> Fenster</span>' +
        '<span class="nz-leg-item"><span class="nz-sw" style="background:#b45309;border-radius:50%"></span>' +
        '<strong>' + nT + '</strong> Türen</span>';
    }
    if (nFl) {
      legend += '<span class="nz-leg-item" title="Wandfluchten aus den byte-exakten Maßketten des Plans, auf die Wand-Erkennung gesnappt">' +
        '<span class="nz-sw" style="background:repeating-linear-gradient(90deg,#16a34a 0 3px,transparent 3px 6px)"></span>' +
        'Maßketten-Fluchten: <strong>' + nFlOk + '/' + nFl + '</strong> bestätigt</span>';
    }
    // Auswahl-Toolbar
    var tb = '';
    if (_nzSel != null) {
      var w = _nzData.waende[_nzSel], cm = _nzCm(w), rm = !!_nzEdit.removed[w.id];
      var btn = function (lab, act, on) {
        return '<button type="button" class="nz-btn' + (on ? ' nz-btn-on' : '') + '" data-act="' + act + '">' + lab + '</button>';
      };
      tb = '<div class="nz-toolbar"><span class="nz-tb-info">Wand: ' + (cm ? 'HLZ ' + cm : '~' + w.dicke_cm) + 'cm · ' +
        fmtNum(w.laenge_m) + ' m</span>' +
        btn(rm ? '↩ wiederherstellen' : '✕ keine Wand', 'rm', rm) +
        '<span class="nz-tb-sep">Stärke:</span>' +
        [50, 38, 25, 20, 12].map(function (t) { return btn(String(t), 'cm' + t, cm === t); }).join('') +
        (cm === 25 ? '<span class="nz-tb-sep"></span>' + btn(_nzIstAussen(w, 25) ? 'außen' : 'innen', 'ai', false) : '') +
        '</div>';
    }
    // Übernehmen-Bereich
    var apply = '';
    var exportierbar = meta.tragfaehig && s.anteile;
    if (s.anteile) {
      apply = '<div class="nz-apply"><div class="nz-apply-pct">Abgeleitete Verteilung — Außen: ' +
        '50cm ' + s.anteile.wand_anteil_50cm + '% · 38cm ' + s.anteile.wand_anteil_38cm + '% · 25cm ' + s.anteile.wand_anteil_25cm_aussen + '%' +
        ' | Innen: 25cm ' + s.anteile.wand_anteil_25cm_innen + '% · 20cm ' + s.anteile.wand_anteil_20cm + '% · 12cm ' + s.anteile.wand_anteil_12cm + '%</div>' +
        (exportierbar
          ? '<button type="button" class="btn btn-sm btn-primary" id="nz-apply">Verteilung in Materialliste übernehmen</button>'
          : '<span class="nachzeichnen-hint" style="color:#92400e">⚠ Maßstab unsicher — Verteilung nur als Sichthilfe, nicht übernehmbar.</span>') +
        ' <button type="button" class="btn btn-sm btn-outline" id="nz-reset">Korrektur zurücksetzen</button></div>';
    }
    var cont = document.getElementById('nachzeichnen-container');
    cont.querySelector('.nz-dynamic').innerHTML =
      '<div class="nz-legend">' + legend + '</div>' + tb + apply +
      '<div class="nz-zoomctl"><button type="button" class="nz-btn" data-z="in">＋</button>' +
      '<button type="button" class="nz-btn" data-z="out">－</button>' +
      '<button type="button" class="nz-btn" data-z="reset">Ansicht zurücksetzen</button>' +
      '<button type="button" class="nz-btn' + (_nzAddMode ? ' nz-btn-on' : '') + '" data-z="add">➕ Wand hinzufügen</button>' +
      '<span class="nachzeichnen-hint" style="margin:0 0 0 .3rem">' +
      (_nzAddMode ? '<strong style="color:#1d4ed8">Linie über die Wand ziehen</strong>' : 'Mausrad = zoomen · ziehen = verschieben') + '</span></div>' +
      '<div class="nz-wrap" style="position:relative;max-width:100%;overflow:hidden;border:1px solid #e2e8f0;border-radius:8px;cursor:' + (_nzAddMode ? 'crosshair' : 'grab') + ';touch-action:none">' +
      '<div class="nz-zoom" style="transform-origin:0 0;position:relative;width:100%">' +
      '<img src="' + _nzData.basis_png_b64 + '" style="display:block;width:100%;height:auto" alt="Plan" draggable="false">' +
      '<svg viewBox="0 0 ' + W + ' ' + H + '" preserveAspectRatio="none" ' +
      'style="position:absolute;top:0;left:0;width:100%;height:100%;pointer-events:none">' +
      '<g style="pointer-events:auto">' + lines + '</g><g>' + labels + '</g>' +
      '<g style="pointer-events:auto">' + marker + '</g>' +
      '<g style="pointer-events:auto">' + raumBadges + '</g></svg></div></div>';
    _nzWireZoom(cont);
    // Events neu binden
    cont.querySelectorAll('line[data-wid]').forEach(function (ln) {
      ln.addEventListener('click', function () {
        if (_nzMoved) return;   // war ein Pan, kein Klick
        _nzSel = parseInt(ln.getAttribute('data-wid'), 10); _nzPaint();
      });
    });
    // Öffnungs-Marker anklicken = keine Öffnung (Fehl-Erkennung entfernen)
    cont.querySelectorAll('g[data-oid]').forEach(function (mk) {
      mk.addEventListener('click', function () {
        if (_nzMoved) return;
        var oid = parseInt(mk.getAttribute('data-oid'), 10);
        _nzEdit.oeffRemoved[oid] = !_nzEdit.oeffRemoved[oid];
        _nzPaint(); _nzSave(_nzSplit().anteile);
      });
    });
    cont.querySelectorAll('.nz-btn').forEach(function (b) {
      b.addEventListener('click', function () {
        var act = b.getAttribute('data-act'), id = _nzSel;
        if (act === 'rm') _nzEdit.removed[id] = !_nzEdit.removed[id];
        else if (act === 'ai') _nzEdit.aussen[id] = !_nzIstAussen(_nzData.waende[id], 25);
        else if (act.indexOf('cm') === 0) _nzEdit.thick[id] = parseInt(act.slice(2), 10);
        _nzPaint();
      });
    });
    var ap = document.getElementById('nz-apply');
    if (ap) ap.addEventListener('click', function () { _nzUebernehmen(s.anteile); });
    var rs = document.getElementById('nz-reset');
    if (rs) rs.addEventListener('click', function () {
      // auch manuell hinzugefügte Wände wieder entfernen
      _nzData.waende = (_nzData.waende || []).filter(function (w) { return !w.manuell; });
      _nzEdit = { removed: {}, thick: {}, aussen: {}, added: [] }; _nzSel = null;
      _filterState.materialliste_override = _nzStripAnteile(_filterState.materialliste_override);
      _nzPaint(); refreshProjektMassen(); _nzSave(null);
    });
    renderWandAufmass();   // Wand-Aufmaß live mitziehen (jede Korrektur sofort sichtbar)
  }

  function _nzApplyZoom() {
    if (!_nzWrap || !_nzData) return;
    var zoom = _nzWrap.querySelector('.nz-zoom'); if (!zoom) return;
    var Wv = _nzWrap.clientWidth, Hv = _nzWrap.clientHeight || (Wv * _nzData.bild_h / _nzData.bild_w), s = _nzZoom.s;
    _nzZoom.x = Math.min(0, Math.max(Wv * (1 - s), _nzZoom.x));
    _nzZoom.y = Math.min(0, Math.max(Hv * (1 - s), _nzZoom.y));
    zoom.style.transform = 'translate(' + _nzZoom.x + 'px,' + _nzZoom.y + 'px) scale(' + s + ')';
  }

  function _nzZoomAt(cx, cy, faktor) {
    var s0 = _nzZoom.s, s1 = Math.min(8, Math.max(1, s0 * faktor));
    _nzZoom.x = cx - (cx - _nzZoom.x) * (s1 / s0);
    _nzZoom.y = cy - (cy - _nzZoom.y) * (s1 / s0);
    _nzZoom.s = s1; _nzApplyZoom();
  }

  function _nzWireZoom(cont) {
    _nzWrap = cont.querySelector('.nz-wrap'); if (!_nzWrap) return;
    _nzApplyZoom();
    _nzWrap.addEventListener('wheel', function (e) {
      e.preventDefault();
      var rect = _nzWrap.getBoundingClientRect();
      _nzZoomAt(e.clientX - rect.left, e.clientY - rect.top, e.deltaY < 0 ? 1.15 : 1 / 1.15);
    }, { passive: false });
    _nzWrap.addEventListener('mousedown', function (e) {
      if (_nzAddMode) { _nzDraw = { p0: _nzScreenToImg(e), p1: null }; e.preventDefault(); return; }
      _nzPan = { sx: e.clientX, sy: e.clientY, ox: _nzZoom.x, oy: _nzZoom.y };
      _nzMoved = false; _nzWrap.style.cursor = 'grabbing';
    });
    cont.querySelectorAll('.nz-zoomctl [data-z]').forEach(function (b) {
      b.addEventListener('click', function () {
        var z = b.getAttribute('data-z');
        if (z === 'add') { _nzAddMode = !_nzAddMode; _nzSel = null; _nzPaint(); }
        else if (z === 'reset') { _nzZoom = { s: 1, x: 0, y: 0 }; _nzApplyZoom(); }
        else _nzZoomAt(_nzWrap.clientWidth / 2, _nzWrap.clientHeight / 2, z === 'in' ? 1.3 : 1 / 1.3);
      });
    });
    if (!_nzZoomWinBound) {   // Window-Listener nur EINMAL binden (sonst Leak je Repaint)
      _nzZoomWinBound = true;
      window.addEventListener('mousemove', function (e) {
        if (_nzDraw && _nzWrap) { _nzDraw.p1 = _nzScreenToImg(e); _nzDrawPreview(); return; }
        if (!_nzPan || !_nzWrap) return;
        var dx = e.clientX - _nzPan.sx, dy = e.clientY - _nzPan.sy;
        if (Math.abs(dx) > 4 || Math.abs(dy) > 4) _nzMoved = true;
        _nzZoom.x = _nzPan.ox + dx; _nzZoom.y = _nzPan.oy + dy; _nzApplyZoom();
      });
      window.addEventListener('mouseup', function () {
        if (_nzDraw) { if (_nzDraw.p1) _nzAddWall(_nzDraw.p0, _nzDraw.p1); _nzDraw = null; return; }
        if (_nzPan) { _nzPan = null; if (_nzWrap) _nzWrap.style.cursor = 'grab'; }
      });
    }
  }

  // Bildschirm-Punkt → Bild-Pixel (berücksichtigt Zoom-Transform + img-Skalierung)
  function _nzScreenToImg(e) {
    var rect = _nzWrap.getBoundingClientRect();
    var cx = e.clientX - rect.left, cy = e.clientY - rect.top;
    var contentX = (cx - _nzZoom.x) / _nzZoom.s, contentY = (cy - _nzZoom.y) / _nzZoom.s;
    var f = _nzData.bild_w / _nzWrap.clientWidth;   // content-px → Bild-px
    return [contentX * f, contentY * f];
  }

  function _nzDrawPreview() {
    if (!_nzDraw || !_nzDraw.p1) return;
    var svg = _nzWrap.querySelector('svg'); if (!svg) return;
    var g = svg.firstChild;
    var pv = svg.querySelector('#nz-prev');
    if (!pv) {
      pv = document.createElementNS('http://www.w3.org/2000/svg', 'line');
      pv.setAttribute('id', 'nz-prev'); pv.setAttribute('stroke', '#1d4ed8');
      pv.setAttribute('stroke-width', '6'); pv.setAttribute('stroke-dasharray', '8 6');
      pv.setAttribute('stroke-linecap', 'round'); g.appendChild(pv);
    }
    var a = _nzDraw.p0, b = _nzDraw.p1;
    pv.setAttribute('x1', a[0]); pv.setAttribute('y1', a[1]);
    pv.setAttribute('x2', b[0]); pv.setAttribute('y2', b[1]);
  }

  function _nzNextId() { var m = 0; (_nzData.waende || []).forEach(function (w) { if (w.id > m) m = w.id; }); return m + 1; }

  function _nzAddWall(p0, p1) {
    var dx = Math.abs(p1[0] - p0[0]), dy = Math.abs(p1[1] - p0[1]);
    if (Math.max(dx, dy) < 8) { _nzPaint(); return; }   // zu kurz → verwerfen
    var m = _nzData.meta || {}, scale = m.scale || 1, ptm = m.ptm || 1;
    var px, achse, lenpx;
    if (dx >= dy) { var ym = (p0[1] + p1[1]) / 2; px = [Math.min(p0[0], p1[0]), ym, Math.max(p0[0], p1[0]), ym]; achse = 'h'; lenpx = dx; }
    else { var xm = (p0[0] + p1[0]) / 2; px = [xm, Math.min(p0[1], p1[1]), xm, Math.max(p0[1], p1[1])]; achse = 'v'; lenpx = dy; }
    var laenge_m = Math.round(lenpx / (scale * ptm) * 100) / 100;
    if (laenge_m < 0.3) { _nzPaint(); return; }
    var cm = 12;   // Default 12cm — Nutzer korrigiert die Stärke gleich in der Auswahl-Leiste
    var w = { id: _nzNextId(), achse: achse, px: px, dicke_cm: cm, snap_cm: cm, laenge_m: laenge_m,
      staerke_px: Math.round(cm / 100 * ptm * scale * 10) / 10, hatch_dichte: null, manuell: true };
    _nzData.waende.push(w);
    _nzEdit.added = _nzEdit.added || []; _nzEdit.added.push(w);
    _nzSel = w.id; _nzAddMode = false;
    _nzPaint();
  }

  function _nzStripAnteile(ov) {
    if (!ov) return null;
    var keys = ['wand_anteil_50cm', 'wand_anteil_38cm', 'wand_anteil_25cm_aussen',
      'wand_anteil_25cm_innen', 'wand_anteil_20cm', 'wand_anteil_12cm'];
    var out = {}; Object.keys(ov).forEach(function (k) { if (keys.indexOf(k) < 0) out[k] = ov[k]; });
    return Object.keys(out).length ? out : null;
  }

  function _nzUebernehmen(anteile) {
    if (!anteile) return;
    var ov = _filterState.materialliste_override || {};
    Object.keys(anteile).forEach(function (k) { ov[k] = anteile[k]; });
    _filterState.materialliste_override = ov;
    refreshProjektMassen();
    _nzSave(anteile);   // Korrektur dauerhaft am Plan speichern (überlebt Reload)
    var ap = document.getElementById('nz-apply');
    if (ap) { ap.textContent = '✓ übernommen & gespeichert — Materialliste neu gerechnet'; ap.disabled = true; }
  }

  // Speichert den Korrektur-Zustand (Edits + angewandte Verteilung) am Plan.
  function _nzSave(anteile) {
    if (!_nzData || !_nzData.plan_id) return;
    var leer = !Object.keys(_nzEdit.removed).length && !Object.keys(_nzEdit.thick).length &&
      !Object.keys(_nzEdit.aussen).length && !(_nzEdit.added && _nzEdit.added.length) &&
      !(_nzEdit.oeffRemoved && Object.keys(_nzEdit.oeffRemoved).length) && !anteile;
    fetch('/api/nachzeichnen-korrektur', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ plan_id: _nzData.plan_id,
        korrekturen: leer ? null : { edit: _nzEdit, anteile: anteile || null } })
    }).catch(function () { /* Speichern ist best-effort */ });
  }

  // Kopplung Liste → Plan: die Wände einer HLZ-Stärke am Plan pulsieren lassen.
  function nzHighlight(cm) {
    var sec = document.getElementById('nachzeichnen-section');
    if (sec) sec.scrollIntoView({ behavior: 'smooth', block: 'start' });
    var cont = document.getElementById('nachzeichnen-container');
    if (!cont) return;
    if (_nzWrap) { _nzZoom = { s: 1, x: 0, y: 0 }; _nzApplyZoom(); }   // Vollansicht, damit alle sichtbar
    Array.prototype.forEach.call(cont.querySelectorAll('line.nz-hi'), function (l) { l.classList.remove('nz-hi'); });
    var sel = cont.querySelectorAll('line[data-cm="' + cm + '"]');
    if (!sel.length) return;
    Array.prototype.forEach.call(sel, function (l) { l.classList.add('nz-hi'); });
    setTimeout(function () {
      Array.prototype.forEach.call(sel, function (l) { l.classList.remove('nz-hi'); });
    }, 3200);
  }

  // Multi-Geschoss/Multi-Plan: Tabs über der Planansicht — jeder Plan des Projekts
  // ist durchschaltbar (EG-Blatt, OG-Blatt, Polierplan …). Lazy je Tab geladen.
  var _nzPlaene = [];      // Manifest [{id, dateiname}] — von renderPlanFilter gesetzt
  var _nzAktivPlan = null;
  // Multi-Geschoss: das Backend meldet weitere analysierbare Blätter (EG/OG/KG
  // im selben PDF); die UI bietet sie als Umschalter an, Analyse on-demand.
  var _nzWeitereSeiten = [], _nzHauptSeite = null, _nzAktivSeite = null;

  function _nzSeitenHtml() {
    if (!_nzWeitereSeiten.length) return '';
    var alle = [_nzHauptSeite].concat(_nzWeitereSeiten);
    return ' · Blätter: ' + alle.map(function (s) {
      var aktiv = (s === _nzAktivSeite);
      return aktiv ? '<strong>Blatt ' + (s + 1) + '</strong>'
        : '<a href="#" data-nz-seite="' + s + '">Blatt ' + (s + 1) + '</a>';
    }).join(' ');
  }

  function _nzWireSeiten(cont) {
    cont.querySelectorAll('[data-nz-seite]').forEach(function (a) {
      a.addEventListener('click', function (ev) {
        ev.preventDefault();
        var s = parseInt(a.getAttribute('data-nz-seite'), 10);
        _nzGeladen = false;
        renderNachzeichnen(_nzAktivPlan, s === _nzHauptSeite ? null : s);
      });
    });
  }

  function _nzTabsHtml() {
    if (!_nzPlaene || _nzPlaene.length < 2) return '';
    return '<div class="nz-tabs">' + _nzPlaene.map(function (p) {
      var on = p.id === _nzAktivPlan;
      return '<button type="button" class="nz-btn' + (on ? ' nz-btn-on' : '') + '" data-nzplan="' +
        esc(p.id) + '">' + esc((p.dateiname || 'Plan').slice(0, 34)) + '</button>';
    }).join('') + '</div>';
  }

  function _nzWireTabs(cont) {
    cont.querySelectorAll('[data-nzplan]').forEach(function (b) {
      b.addEventListener('click', function () {
        var pid = b.getAttribute('data-nzplan');
        if (pid === _nzAktivPlan) return;
        _nzGeladen = false;
        renderNachzeichnen(pid);
      });
    });
  }

  function renderNachzeichnen(planId, seite) {
    var cont = document.getElementById('nachzeichnen-container');
    if (!cont || (_nzGeladen && !planId && seite == null) || _nzLaeuft) return;
    _nzLaeuft = true;
    cont.innerHTML = _nzTabsHtml() +
      '<p class="nachzeichnen-hint">Plan wird nachgezeichnet &hellip; (die Wände werden aus den Vektoren gelesen)</p>';
    _nzWireTabs(cont);
    var reqBody = planId ? { plan_id: planId } : { projekt_id: projectId };
    if (seite != null) reqBody.seite = seite;
    fetch('/api/plan-nachzeichnen', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(reqBody)
    }).then(function (r) { return r.json(); }).then(function (d) {
      _nzGeladen = true; _nzLaeuft = false;
      if (!d || !d.ok) {
        if (planId) _nzAktivPlan = planId;   // Tab bleibt wählbar markiert
        cont.innerHTML = _nzTabsHtml() +
          '<p class="nachzeichnen-hint">Nachzeichnen für diesen Plan nicht verfügbar' +
          (d && d.grund ? ' — ' + esc(d.grund) : '') + '. (Funktioniert bei klar bemaßten Grundriss-Blättern.)</p>';
        _nzWireTabs(cont);
        return;
      }
      _nzAktivPlan = d.plan_id || planId || null;
      _nzAktivSeite = (d.meta || {}).seite != null ? d.meta.seite : null;
      if (seite == null) {   // Hauptblatt-Lauf liefert die Blatt-Liste
        _nzHauptSeite = _nzAktivSeite;
        _nzWeitereSeiten = d.weitere_seiten || [];
      }
      _nzData = d; _nzEdit = { removed: {}, thick: {}, aussen: {} }; _nzSel = null;
      // Gespeicherte Korrekturen wiederherstellen (überleben den Reload)
      var k = d.korrekturen;
      if (k && k.edit) {
        _nzEdit = { removed: k.edit.removed || {}, thick: k.edit.thick || {}, aussen: k.edit.aussen || {},
          added: k.edit.added || [], oeffRemoved: k.edit.oeffRemoved || {} };
        // manuell hinzugefügte Wände wieder in die Geometrie einspielen
        (_nzEdit.added || []).forEach(function (w) { _nzData.waende.push(w); });
        if (k.anteile) {   // angewandte Verteilung zurück in den Override → Mengen stimmen wieder
          var ov = _filterState.materialliste_override || {}, changed = false;
          Object.keys(k.anteile).forEach(function (kk) { if (ov[kk] !== k.anteile[kk]) { ov[kk] = k.anteile[kk]; changed = true; } });
          if (changed) { _filterState.materialliste_override = ov; refreshProjektMassen(); }
        }
      }
      var meta = d.meta || {};
      var hatK = k && k.edit && (Object.keys(k.edit.removed || {}).length || Object.keys(k.edit.thick || {}).length);
      var schnittHint = d.typ === 'schnitt'
        ? '<p class="nachzeichnen-hint">📐 <strong>Schnitt-/Ansichts-Blatt</strong> — ' +
          (d.koten || []).length + ' Höhenkoten byte-exakt gelesen (violette Marker, Tooltip zeigt den Wert). ' +
          'Kein Grundriss auf diesem Blatt — Mengen kommen von den Grundriss-Blättern. ' +
          'Maßstab ' + esc((d.meta || {}).massstab || '?') + '</p>'
        : null;
      if (schnittHint) {
        cont.innerHTML = _nzTabsHtml() + schnittHint + '<div class="nz-dynamic"></div>';
        _nzWireTabs(cont);
        _nzWireSeiten(cont);
        _nzPaint();
        return;
      }
      cont.innerHTML = _nzTabsHtml() +
        '<p class="nachzeichnen-hint">Erkannte Wände, farbcodiert nach Stärke (gestrichelt = unsicher). ' +
        '<strong>Klicke eine Wand</strong>, um sie zu entfernen (keine Wand), die Stärke zu korrigieren oder 25cm außen/innen zu setzen. ' +
        (hatK ? '<strong style="color:#166534">✓ deine gespeicherten Korrekturen sind angewandt.</strong> ' : '') +
        'Maßstab ' + esc(meta.massstab || '?') + ' · Bereich ' + (meta.box_m ? meta.box_m[0] + '×' + meta.box_m[1] + ' m' : '?') +
        ' · ' + (d.dateiname ? esc(d.dateiname) : '') + _nzSeitenHtml() + '</p>' +
        '<div class="nz-dynamic"></div>';
      _nzWireTabs(cont);
      _nzWireSeiten(cont);
      _nzPaint();
    }).catch(function (e) {
      _nzGeladen = false; _nzLaeuft = false;
      cont.innerHTML = '<p class="nachzeichnen-hint">Nachzeichnen fehlgeschlagen: ' + esc(e.message) + '</p>';
    });
  }

  // Die Planansicht lädt automatisch nach der ersten Auswertung (renderNachzeichnen()
  // wird im Lade-Flow aufgerufen, der _nzGeladen-Guard hält es bei einem Fetch).
  window._nzReset = function () { _nzGeladen = false; _nzData = null; renderNachzeichnen(_nzAktivPlan); };

  // ── AUFMASSBLATT: abheftbares Prüf-PDF (Plan + eingezeichnete Bauteile) ──
  (function wireAufmass() {
    var b = document.getElementById('projekt-aufmass-btn');
    if (!b) return;
    b.addEventListener('click', function () {
      b.disabled = true; var t0 = b.textContent; b.textContent = 'Erzeuge Aufmaßblatt …';
      fetch('/api/plan-aufmassblatt', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(Object.assign(
          _nzAktivPlan ? { plan_id: _nzAktivPlan } : { projekt_id: projectId },
          // Seite 2 des Aufmaßblatts: Mengen mit Formel (B-2110-Prüfbeleg)
          _lastML && _lastML.bauteile
            ? { massen: { bauteile: _lastML.bauteile, kennzahlen: _lastML.kennzahlen } } : {}))
      }).then(function (r) {
        var ct = r.headers.get('content-type') || '';
        if (ct.indexOf('pdf') < 0) return r.json().then(function (j) { throw new Error((j && j.grund) || 'nicht verfügbar'); });
        return r.blob();
      }).then(function (blob) {
        var a = document.createElement('a');
        a.href = URL.createObjectURL(blob);
        a.download = 'aufmassblatt.pdf';
        document.body.appendChild(a); a.click(); a.remove();
        setTimeout(function () { URL.revokeObjectURL(a.href); }, 4000);
      }).catch(function (e) {
        alert('Aufmaßblatt: ' + e.message);
      }).finally(function () { b.disabled = false; b.textContent = t0; });
    });
  })();

  // ── AUFMASS-CSV: die drei Aufmaß-Tabellen (Räume · Wände · Öffnungen) für Excel ──
  (function wireAufmassCsv() {
    var b = document.getElementById('projekt-aufmass-csv-btn');
    if (!b) return;
    function z(v) { return v == null ? '' : String(v).replace(/;/g, ','); }
    b.addEventListener('click', function () {
      var d = window.projektMassenData || {};
      var teile = [];
      // Räume
      var innen = (d.raeume || []).filter(function (r) { return r && r.flaeche_m2; });
      if (innen.length) {
        teile.push('RAUM-AUFMASS (F/U byte-exakt aus den Raum-Stempeln)');
        teile.push('Raum;Boden m2;Decke m2;Umfang m;Hoehe m;Wandabwicklung m2;Sockel lfm');
        var hDef = (d.baudaten || {}).geschosshoehe_m || 2.7;
        innen.forEach(function (r) {
          var aussen = !!r._h_not_applicable;
          var h = r.hoehe_m || (aussen ? null : hDef);
          var wf = (r.umfang_m && h) ? Math.round(r.umfang_m * h * 100) / 100 : '';
          teile.push([z(r.name), r.flaeche_m2, aussen ? '' : r.flaeche_m2, r.umfang_m || '',
            h || '', wf, (r.umfang_m && !aussen) ? r.umfang_m : ''].join(';'));
        });
        teile.push('');
      }
      // Wände (aus der Planansicht, inkl. Korrekturen)
      if (_nzData && _nzData.waende) {
        teile.push('WAND-AUFMASS (aus der Planansicht; * = Laenge byte-exakt aus Plan-Masszahl)');
        teile.push('Wand;Staerke cm;Laenge m;Quelle');
        (_nzData.waende || []).forEach(function (w) {
          if (_nzEdit.removed && _nzEdit.removed[w.id]) return;
          var cm = _nzCm(w);
          if (!cm) return;
          teile.push(['W' + w.id, cm, w.laenge_m + (w.mass_exakt ? '*' : ''),
            w.manuell ? 'manuell' : (w.mass_exakt ? 'Plan-Masszahl' : 'Vektor')].join(';'));
        });
        teile.push('');
      }
      // Öffnungen
      var oa = d.oeffnungs_aufmass;
      if (oa && oa.zeilen && oa.zeilen.length) {
        teile.push('OEFFNUNGS-AUFMASS (' + z(oa.norm) + ')');
        teile.push('Raum;Typ;Wand;Breite m;Hoehe m;Flaeche m2;Regel;Abzug m2;Laibung m2;Rechenweg');
        oa.zeilen.forEach(function (x) {
          teile.push([z(x.raum), x.typ, x.wand, x.breite_m, x.hoehe_m, x.flaeche_m2,
            z(x.regel), x.abzug_m2 || '', x.laibung_m2 || '', z(x.formel)].join(';'));
        });
      }
      if (!teile.length) { alert('Noch keine Aufmaß-Daten — bitte erst die Auswertung laden.'); return; }
      var blob = new Blob(['﻿' + teile.join('\n')], { type: 'text/csv;charset=utf-8' });
      var a = document.createElement('a');
      a.href = URL.createObjectURL(blob);
      a.download = 'aufmass.csv';
      document.body.appendChild(a); a.click(); a.remove();
      setTimeout(function () { URL.revokeObjectURL(a.href); }, 4000);
    });
  })();

  // ── WORKFLOW-STEPPER: Pläne → Plan prüfen → Massen & Material → Export & Fragen ──
  // Führt den Nutzer in 4 Schritten durch die Ermittlung, statt alles auf einmal zu
  // zeigen. Schritt 2 (Plan prüfen) ist der Default nach der Analyse: ERST die
  // Planansicht verifizieren/korrigieren, DANN die Massen ansehen.
  var WF_GRUPPEN = {
    2: ['#ergebnis-status-banner', '#pruefliste', '#nachzeichnen-section'],
    3: ['#zielgruppen-presets', '#geo-box', '#fact-strip', '.ml-board-toolbar', '#ml-board', '#auswertung-kennzahlen', '.advanced-drawer'],
    4: ['#projekt-chat']
  };
  function wfShow(step) {
    Object.keys(WF_GRUPPEN).forEach(function (s) {
      var an = String(step) === s;
      WF_GRUPPEN[s].forEach(function (sel) {
        document.querySelectorAll(sel).forEach(function (el) { el.classList.toggle('wf-hidden', !an); });
      });
    });
    document.querySelectorAll('#workflow-steps .wf-step').forEach(function (b) {
      b.classList.toggle('wf-on', b.getAttribute('data-wf') === String(step));
    });
    if (step === 1) {
      var up = document.getElementById('upload-section');
      if (up) up.scrollIntoView({ behavior: 'smooth', block: 'start' });
    } else if (step === 2 && typeof _nzApplyZoom === 'function') {
      _nzApplyZoom();   // Zoom-Transform neu anwenden (Element war ggf. unsichtbar)
    }
  }
  (function wireWorkflow() {
    var bar = document.getElementById('workflow-steps');
    if (!bar) return;
    bar.querySelectorAll('.wf-step').forEach(function (b) {
      b.addEventListener('click', function () { wfShow(parseInt(b.getAttribute('data-wf'), 10)); });
    });
    wfShow(2);   // initial: Plan prüfen (Bereiche der anderen Schritte ausblenden)
  })();

  // ── ZIELGRUPPEN-PRESETS: gleiche Daten, passende Sicht je Branche-Bereich ──
  var ZG_GEWERKE = {
    rohbau: ['rohbau', 'beton'],            // Baumeister: Mauerwerk/Beton + Materialliste
    ausbau: ['putz', 'estrich', 'maler'],   // Ausbau-Subunternehmer
    kalkulant: null                          // alle Gewerke, LV-Form offen
  };
  (function wirePresets() {
    var box = document.getElementById('zielgruppen-presets');
    if (!box) return;
    function apply(preset, initial) {
      _filterState.gewerke = ZG_GEWERKE[preset] || null;
      box.querySelectorAll('.zg-btn').forEach(function (b) {
        b.classList.toggle('zg-on', b.getAttribute('data-preset') === preset);
      });
      try { localStorage.setItem('zg_preset', preset); } catch (e) { /* egal */ }
      if (preset === 'kalkulant') {
        var dr = document.querySelector('.advanced-drawer');
        if (dr) dr.open = true;   // ÖNORM-Buchform sofort sichtbar
      }
      if (!initial) refreshProjektMassen();
    }
    box.querySelectorAll('.zg-btn').forEach(function (b) {
      b.addEventListener('click', function () { apply(b.getAttribute('data-preset'), false); });
    });
    var saved = null;
    try { saved = localStorage.getItem('zg_preset'); } catch (e) { /* egal */ }
    if (saved && ZG_GEWERKE.hasOwnProperty(saved)) apply(saved, true);
  })();

  window.loadPlans = loadPlans;
  window.projectId = projectId;
  loadPlans();
})();
