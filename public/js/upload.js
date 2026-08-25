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
  var _projGewerk = '';   // Sektor des Projekts → fließt in die Analyse (statt still 'allgemein')
  _sb.from('projekte').select('*').eq('id', projectId).single().then(function (res) {
    if (res.data) {
      projectNameEl.textContent = res.data.name || '';
      projectAddressEl.textContent = res.data.adresse || '';
      _projGewerk = (res.data.gewerk || '').toLowerCase().trim();
      window._projModus = res.data.modus || 'ki';
      // MANUELL-MODUS (Live-Befund 2026-08-21: "funktioniert gar nicht"):
      // renderNachzeichnen hing am ERFOLGSPFAD der Massen-Berechnung —
      // ohne Analyse bricht die vorher ab, der Plan wurde NIE gezeichnet.
      // Im Manuell-Modus zeichnet der Leicht-Pass direkt.
      // WETTLAUF (Live-Befund 2026-08-24): loadPlans() startet PARALLEL zu
      // diesem Abruf. Ist es zuerst fertig, war _projModus noch undefined —
      // dann versteckt es die Ergebnis-Sektion (und mit ihr den Editor) und
      // zeigt "0 von 2 Plänen analysiert". Deshalb im Manuell-Modus die
      // Planliste neu bewerten, sobald der Modus wirklich bekannt ist.
      if (window._projModus === 'manuell') {
        loadPlans();
        setTimeout(function () { renderNachzeichnen(); }, 300);
      }
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
      } else if (window._projModus === 'manuell' && plans.length > 0) {
        // MANUELL-MODUS: hier wird BEWUSST nicht analysiert — der Nutzer misst
        // selbst. Die Ergebnis-Sektion trägt aber den Plan-Editor; sie hier zu
        // verstecken sperrte den Nutzer aus seinem einzigen Werkzeug aus und
        // hinterließ nur "0 von 2 Plänen analysiert" (Live-Befund 2026-08-24:
        // "ich komm nicht in den Editor"). Auf ein Analyse-Ergebnis zu warten,
        // das nie kommt, ist in diesem Modus sinnlos.
        if (sec) sec.classList.remove('hidden');
        if (warteEl) warteEl.classList.add('hidden');
        renderNachzeichnen();
        if (typeof window.wfAutoPlan === 'function') window.wfAutoPlan();
      } else {
        if (sec) sec.classList.add('hidden');
        if (warteEl) {
          if (plans.length === 0) { warteEl.classList.add('hidden'); }
          else {
            warteEl.classList.remove('hidden');
            warteEl.innerHTML = '<div class="spinner"></div> <strong>' + fertigCount + ' von ' +
              plans.length + ' Plänen analysiert</strong> — das Ergebnis erscheint, sobald alle fertig sind ' +
              '(sonst ändern sich Räume und Mengen noch).' +
              // AUSWEG statt Sackgasse: wer nicht warten will, misst selbst.
              ' <button type="button" class="btn btn-sm btn-outline" id="warte-manuell" ' +
              'style="margin-left:.6rem">✏️ Jetzt selbst messen</button>';
            var wm = document.getElementById('warte-manuell');
            if (wm) wm.addEventListener('click', function () {
              window._projModus = 'manuell';
              if (window.projectId) {
                _sb.from('projekte').update({ modus: 'manuell' }).eq('id', window.projectId).then(function () {});
              }
              loadPlans();
            });
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
        // Nicht-Formular-Overrides BEWAHREN — v.a. den am Plan GEMESSENEN
        // aussenumfang_m (aus _nzMessUmfangUebernehmen). Ohne das würde jeder
        // Feld-Apply die Overrides aus null neu bauen und das Nachmess-Ergebnis
        // still wegwerfen (HasenbeinPlan-Schleife: Messung → Berechnung bräche).
        var formKeys = {};
        Array.prototype.forEach.call(inputs, function (i) { formKeys[i.getAttribute('data-bd')] = 1; });
        var ov = {}, prev = _filterState.baudaten_override || {};
        Object.keys(prev).forEach(function (k) { if (!formKeys[k]) ov[k] = prev[k]; });
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
  var _lastMatrix = null;   // Aufmaß-Kreuztabelle, auch für die Raum-Werte am Plan
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
        if (window._projModus === 'manuell') renderNachzeichnen();
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
    // (Sektor-Indikator wandert in den Konfidenz-Kopf — hier nicht doppeln.)
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
      else if (gq.umfang_verdacht_niedrig) { cls = 'warn'; mark = '⚠'; note = 'wirkt zu klein für die Fläche (L-/U-Form?) — <button type="button" class="nz-btn" style="padding:.05rem .45rem;font-size:.76rem" onclick="_nzMessenStart()" title="Gebäude-Außenkante am Plan abklicken → byte-exakter Umfang in die Materialliste">📏 jetzt nachmessen</button>'; }
      else if (gq.cross_check_warnung) { cls = 'warn'; mark = '⚠'; note = 'unsicher — <button type="button" class="nz-btn" style="padding:.05rem .45rem;font-size:.76rem" onclick="_nzMessenStart()">📏 jetzt nachmessen</button>'; }
      else { cls = 'ok'; mark = '✓'; note = 'Umfang der Außenwände'; }
      if (opusGarage.length && gq.opus_mauerwerk_zusatz_m) {
        note += ' · inkl. ' + esc(opusGarage.join(', ')) + ' (im Schnitt gemauert, +' +
          fmtNum(gq.opus_mauerwerk_zusatz_m) + ' m)';
      }
      t.push(tile('📐', 'Außenwand-Umfang', fmtNum(g.aussenumfang_m) + ' m', cls, mark, note));
    }
    if (g.bodenplatte_flaeche_m2) t.push(tile('⬛', 'Grundfläche', fmtNum(g.bodenplatte_flaeche_m2) + ' m²',
      'ok2', '✓✓', data.footprint_hinweis || 'aus den Raumflächen im Plan'));
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
      // Abbruch/Rückbau ist eine bezahlte ÖNORM-Leistung, lässt sich aber aus der
      // (mehrdeutigen) Farb-Kodierung NICHT zuverlässig auto-quantifizieren
      // (gemessen: Abbruch-Gelb pervasiv/nicht wand-paarbar) → ehrlich: am Plan
      // nachmessen statt eine falsche Rückbau-Menge zu behaupten.
      var messCta = data.farben.hat_abbruch
        ? ' <button type="button" class="nz-btn" style="padding:.05rem .45rem;font-size:.76rem" onclick="_nzMessenStart()" title="Abbruch-/Rückbau-Kanten am Plan abklicken → Länge/Fläche">📏 Rückbau am Plan nachmessen</button>'
        : '';
      hints.push('<div class="status-warn">🎨 <strong>' + baTeile.join(' + ') +
        ' im Plan erkannt</strong> — ' + esc(data.farben.hinweis ||
        ('laut Legende. Die Massen beziehen sich auf den NEUBAU; ' + baTeile.join('/') +
         ' ist nicht automatisch herausgerechnet, bitte separat prüfen.')) + messCta + '</div>');
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
    renderAufmassMatrix(data.aufmass_matrix);
    renderEigenePosition(data);

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

    renderKonfidenzKopf(data);
    renderReadData(data);
    renderMengenermittlung(data);
    renderMaterialliste(data.materialliste, data.gemessen);
  }

  // KONFIDENZ-KOPF: beantwortet „kann ich das übernehmen?" in einem Blick —
  // Gesamt-Konfidenz + die tragenden Signale (Maßstab, gelesene Räume,
  // Geometrie-Flags). Zurückhaltend/seriös, nicht als Deko: der Wert leitet
  // den Nutzer, WO er prüfen muss.
  function renderKonfidenzKopf(data) {
    var el = document.getElementById('konf-kopf');
    if (!el) return;
    var g = data.gemessen || {}, gq = g.geometrie_qualitaet || {};
    var ml = data.materialliste || {}, kz = ml.kennzahlen || {};
    var raeume = data.raeume || [];
    // Gesamt-Konfidenz: Median der Positions-Konfidenzen (robust gg. Ausreißer)
    var konfs = [];
    Object.keys(ml.bauteile || {}).forEach(function (b) {
      (ml.bauteile[b] || []).forEach(function (p) { if (p && p.konfidenz != null) konfs.push(p.konfidenz); });
    });
    konfs.sort(function (a, b) { return a - b; });
    // ECHTER Median: bei GERADER Anzahl das Mittel der zwei zentralen Werte (vorher
    // wurde das obere mittlere Element genommen — als 'Median' gelabelt, aber leicht
    // verzerrt nach oben).
    var med;
    if (!konfs.length) med = (g.konfidenz || 0);
    else if (konfs.length % 2) med = konfs[(konfs.length - 1) / 2];
    else med = (konfs[konfs.length / 2 - 1] + konfs[konfs.length / 2]) / 2;
    var pct = Math.round(med * 100);
    var stufe = pct >= 80 ? 'ok' : (pct >= 65 ? 'warn' : 'idle');
    // Sektor
    var sektor = (data.dach_positionen || []).length ? { i: '🏠', t: 'Dachplan · Zimmerer/Dachdecker' }
      : (kz.sektor === 'STB/Tiefgarage' ? { i: '🅿️', t: 'Tiefgarage · Stahlbeton' }
        : { i: '🏗️', t: 'Rohbau · Hochbau' });
    var facts = [];
    facts.push('<span class="kf sector">' + sektor.i + ' ' + esc(sektor.t) + '</span>');
    // Bau-Status prominent (wichtigste Interpretations-Warnung): enthält der Plan
    // laut Farb-Legende ECHTEN Bestand/Abbruch, beziehen sich die Mengen auf den
    // NEUBAU — auf einem Umbauplan zählte der Polier sonst Bestandswände mit.
    if (data.farben && (data.farben.hat_bestand || data.farben.hat_abbruch)) {
      var _ba = [];
      if (data.farben.hat_bestand) _ba.push('Bestand');
      if (data.farben.hat_abbruch) _ba.push('Abbruch');
      facts.push('<span class="kf warn" title="Farb-Legende Neubau/Bestand/Abbruch — die Mengen umfassen den NEUBAU; Bestand/Abbruch sind NICHT herausgerechnet">'
        + '<i></i>Umbau/Sanierung: ' + _ba.join(' + ') + ' im Plan → Mengen = Neubau</span>');
    }
    if (raeume.length) facts.push('<span class="kf ok"><i></i>' + raeume.length + ' Räume byte-exakt gelesen</span>');
    if (gq.umfang_validiert) facts.push('<span class="kf ok"><i></i>Außenumfang aus Plan-Maßen bestätigt</span>');
    else if (gq.umfang_verdacht_niedrig) facts.push('<span class="kf warn"><i></i>Außenumfang unsicher → nachmessen</span>');
    if (g.bodenplatte_flaeche_m2) facts.push('<span class="kf ok"><i></i>Grundfläche aus Raumflächen exakt</span>');
    var satz = pct >= 80 ? 'Belastbar — bestellfertig, Prüfpunkte markiert.'
      : (pct >= 65 ? 'Weitgehend belastbar — die markierten Stellen kurz prüfen.'
        : 'Erste Auswertung — bitte die markierten Stellen prüfen/nachmessen.');
    el.innerHTML =
      '<div class="konf-score konf-' + stufe + '"><b>' + pct + '<small>%</small></b><span>Konfidenz</span></div>' +
      '<div class="konf-body"><div class="konf-eyebrow">Auswertung geprüft</div>' +
      '<div class="konf-satz">' + satz + '</div>' +
      '<div class="konf-facts">' + facts.join('') + '</div></div>';
  }

  // PRÜFBARE MENGENERMITTLUNG (ÖNORM A 2063 / LB-Hochbau): Gewerk (LG) →
  // Position → Menge · Einheit → AUFMASS-HERLEITUNG (der Rechenweg je Raum) +
  // Konfidenz. Das ist die ausschreibungs-/abrechnungsfähige Grundlage — die
  // Bestell-Materialliste ist die abgeleitete Beschaffungs-Sicht (Umschalter).
  var _lastGewerke = null;
  function renderMengenermittlung(data) {
    _lastGewerke = data && data.gewerke;
    var board = document.getElementById('mengen-board');
    if (!board) return;
    var gw = data && data.gewerke || {};
    var keys = Object.keys(gw).filter(function (k) {
      return (gw[k].positionen || []).some(function (p) { return (p.endsumme || 0) !== 0; });
    });
    if (!keys.length) {
      board.innerHTML = '<div class="ml-empty">Noch keine Mengen — die Pläne enthalten noch keine vollständigen Raumdaten.</div>';
      return;
    }
    var showAuf = !!(document.getElementById('ml-formel-toggle') || {}).checked;
    var onlySure = !!(document.getElementById('ml-only-sure') || {}).checked;
    var html = '';
    keys.forEach(function (gk) {
      var g = gw[gk];
      var lg = g.lg || '';
      var name = (g.label || gk).replace(/\s*\(.*\)/, '').replace(/^Maurer\s*\/\s*/, '').replace(/^Verputzer/, 'Putz');
      var pos = (g.positionen || []).filter(function (p) {
        return (p.endsumme || 0) !== 0 && (!onlySure || (p.konfidenz || 0) >= 0.65);
      });
      if (!pos.length) return;
      // Gewerk-Konfidenz (min) → Farb-Stripe
      var gkonf = Math.min.apply(null, pos.map(function (p) { return p.konfidenz || 0; }));
      var gc = gkonf >= 0.8 ? 'ok' : (gkonf >= 0.6 ? 'warn' : 'idle');
      html += '<section class="mgroup mg-' + gc + '">';
      html += '<div class="mgroup-h">' +
        (lg ? '<span class="lg-badge">LG ' + esc(lg) + '</span>' : '') +
        '<span class="mg-name">' + esc(name) + '</span>' +
        '<span class="mg-ct">' + pos.length + ' Position' + (pos.length > 1 ? 'en' : '') +
        (g.label && /B\s*2\d{3}/.test(g.label) ? ' · ÖNORM ' + (g.label.match(/B\s*2\d{3}/) || [''])[0] : '') +
        '</span></div>';
      pos.forEach(function (p) {
        var konf = Math.round((p.konfidenz || 0) * 100);
        var kc = konf >= 80 ? 'hi' : (konf >= 65 ? 'mid' : 'lo');
        html += '<div class="mrow2">' +
          '<div class="m-pos"><span class="m-nr">' + esc(p.posnr || '') + '</span> ' +
          esc(p.beschreibung || '') + '</div>' +
          '<div class="m-qty">' + fmtNum(p.endsumme) + '<span class="u">' + esc(p.einheit || '') + '</span></div>' +
          '<div class="m-conf ' + kc + '">' + konf + '%</div></div>';
        if (showAuf && (p.zeilen || []).length) {
          html += '<div class="m-auf">';
          (p.zeilen || []).forEach(function (z) {
            // Plan-Anker: anker.raum → Raum pulst; anker.ebene='konturen' →
            // Gebäude-Hülle (blaue Kontur) pulst (Bodenplatte/Decke/WDVS/Gerüst).
            var ank = z.anker && z.anker.raum;
            var ankK = !ank && z.anker && z.anker.ebene === 'konturen';
            // anker.oeffnung → der Fenster-/Tür-Marker am Plan pulst. Diese
            // Zeilen waren die EINZIGEN im ganzen Aufmaß ohne Sprung zum Plan
            // (gemessen 31 von 33 zeigbar): die Öffnungs-Detailtabelle war
            // längst klickbar, der Rechenweg derselben Öffnung nicht.
            var ankO = !ank && !ankK && z.anker && z.anker.oeffnung;
            html += '<div class="auf-z' + ((ank || ankK || ankO) ? ' auf-z-anker' : '') + '"' +
              (ank ? ' onclick="nzHighlightRaum(\'' + _jsStr(z.anker.raum) + '\', \''
                + _jsStr((z.text || '') + (z.quelle ? ' · ' + z.quelle : '')
                  + (z.wert != null ? ' = ' + fmtNum(z.wert) : '')) + '\')"' +
                ' title="Am Plan zeigen: ' + esc(z.anker.raum) + '"' : '') +
              (ankK ? ' onclick="nzHighlightKontur()"' +
                ' title="Am Plan zeigen: Gebäude-Hülle (blaue Kontur)"' : '') +
              (ankO ? ' onclick="nzHighlightOeffnung(\'' + _jsStr(ankO.typ || 'fenster')
                + '\',\'\',' + (Number(ankO.breite_m) || 0) + ','
                + (Number(ankO.hoehe_m) || 0) + ','
                + (ankO.ohne_mass ? 'true' : 'false') + ')"' +
                ' title="Am Plan zeigen: ' + esc(ankO.typ === 'tuer' ? 'Tür' : 'Fenster')
                + (ankO.ohne_mass ? ' ohne vollständiges Maß"'
                   : ' ' + fmtNum(ankO.breite_m) + '×' + fmtNum(ankO.hoehe_m) + ' m"') : '') +
              '><span class="az-t">' + ((ank || ankK || ankO) ? '📍 ' : '') + esc(z.text || '') + '</span>' +
              '<span class="az-q">' + esc(z.quelle || '') + '</span>' +
              '<span class="az-w">' + fmtNum(z.wert) + '</span></div>';
          });
          html += '</div>';
        }
      });
      html += '</section>';
    });
    board.innerHTML = html;
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
      var _typ = titel === 'Fenster' ? 'fenster' : 'tuer';
      arr.forEach(function (o) {
        var q = (o.quelle || '').indexOf('stuk') >= 0 ? '<span style="color:#0f766e">Text/STUK</span>' :
                ((o.quelle || '').indexOf('vision') >= 0 ? '<span style="color:#34363d">Vision</span>' : esc(o.quelle || ''));
        // Klick auf die Zeile → zugehörigen Marker am Plan pulsen (Traceability).
        var click = ' class="oeff-z-klick" onclick="nzHighlightOeffnung(\'' + _typ + '\',\'' +
          esc(o.raum || '').replace(/'/g, "\\'") + '\',' + (o.breite_m || 0) + ',' + (o.hoehe_m || 0) + ')"' +
          ' title="Am Plan zeigen"';
        h += '<tr' + click + '><td style="' + TD + '">📍 ' + esc(o.bezeichnung || '') + '</td>' +
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

    // Rechenweg/Aufmaß-Toggle + „nur Sichere"-Filter binden → BEIDE Ansichten neu
    var tog = document.getElementById('ml-formel-toggle');
    if (tog && !tog.dataset.bound) {
      tog.dataset.bound = '1';
      tog.addEventListener('change', function () {
        renderMaterialliste(_lastML, _lastGemessen);
        renderMengenermittlung({ gewerke: _lastGewerke });
      });
    }
    var onlySure = document.getElementById('ml-only-sure');
    if (onlySure && !onlySure.dataset.bound) {
      onlySure.dataset.bound = '1';
      onlySure.addEventListener('change', function () {
        renderMaterialliste(_lastML, _lastGemessen);
        renderMengenermittlung({ gewerke: _lastGewerke });
      });
    }
    // Ansichts-Umschalter Mengen ↔ Bestellung (einmalig binden)
    var vsw = document.getElementById('mengen-view-switch');
    if (vsw && !vsw.dataset.bound) {
      vsw.dataset.bound = '1';
      vsw.querySelectorAll('.vs').forEach(function (b) {
        b.addEventListener('click', function () {
          var v = b.getAttribute('data-view');
          vsw.querySelectorAll('.vs').forEach(function (x) {
            var on = x === b; x.classList.toggle('on', on); x.setAttribute('aria-selected', on ? 'true' : 'false');
          });
          var mb = document.getElementById('mengen-board'), lb = document.getElementById('ml-board');
          if (mb) mb.classList.toggle('hidden', v !== 'mengen');
          if (lb) lb.classList.toggle('hidden', v !== 'material');
        });
      });
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
      var sec = _wfZuPlan();
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

  // ─── Raumliste (PDF/Excel) — Zwischen-Export direkt nach der Raum-Erkennung ───
  function bindRaumliste(id, format, endung, mime) {
    var b = document.getElementById(id);
    if (!b || b.dataset.bound) return;
    b.dataset.bound = '1';
    b.addEventListener('click', function () {
      var d = window.projektMassenData || {};
      var rs = (d.raeume || []).filter(function (r) { return r && r.flaeche_m2; });
      if (!rs.length) { alert('Noch keine Räume mit Fläche gelesen.'); return; }
      var alt = b.textContent;
      b.textContent = '… erstellt'; b.disabled = true;
      fetch('/api/raumliste', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          projekt_name: ((document.getElementById('project-name') || {}).textContent || 'Projekt').trim(),
          raeume: rs, format: format
        })
      }).then(function (r) {
        var ct = r.headers.get('Content-Type') || '';
        if (ct.indexOf(mime) === -1) throw new Error('Export fehlgeschlagen');
        return r.blob();
      }).then(function (blob) {
        var u = URL.createObjectURL(blob), a = document.createElement('a');
        a.href = u; a.download = 'Raumliste.' + endung;
        document.body.appendChild(a); a.click(); a.remove();
        URL.revokeObjectURL(u);
      }).catch(function (e) {
        alert('Raumliste konnte nicht erstellt werden: ' + e.message);
      }).then(function () { b.textContent = alt; b.disabled = false; });
    });
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
    bindRaumliste('raumliste-pdf-btn', 'pdf', 'pdf', 'pdf');
    bindRaumliste('raumliste-xlsx-btn', 'xlsx', 'xlsx', 'spreadsheetml');
    // Prüffähiges Aufmaß als .xlsx — WYSIWYG: schickt exakt die geladenen
    // Daten (gewerke/materialliste/raeume) ans Backend, openpyxl formatiert.
    var btnX = document.getElementById('projekt-xlsx-btn');
    if (btnX && !btnX.dataset.bound) { btnX.dataset.bound = '1';
      btnX.addEventListener('click', function () {
        var d = window.projektMassenData || {};
        if (!d.gewerke) { alert('Noch keine Auswertung geladen.'); return; }
        var alt = btnX.textContent;
        btnX.textContent = '… erstellt';
        btnX.disabled = true;
        fetch('/api/aufmass-xlsx', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            projekt_name: ((document.getElementById('project-name') || {}).textContent || 'Projekt').trim(),
            gewerke: d.gewerke,
            // materialliste.bauteile ist ein Dict {Bauteil: [Zeilen]} → flache Liste
            materialliste: (function () {
              var bt = (d.materialliste && d.materialliste.bauteile) || {};
              var rows = [];
              Object.keys(bt).forEach(function (k) {
                (bt[k] || []).forEach(function (p) { rows.push(p); });
              });
              return rows;
            })(),
            raeume: d.raeume || []
          })
        }).then(function (r) {
          var ct = r.headers.get('Content-Type') || '';
          if (ct.indexOf('spreadsheetml') === -1) throw new Error('Export fehlgeschlagen');
          return r.blob();
        }).then(function (blob) {
          var a = document.createElement('a');
          a.href = URL.createObjectURL(blob);
          var pn = ((document.getElementById('project-name') || {}).textContent || 'Projekt');
          a.download = 'Aufmass_' + (pn.replace(/[^\wäöüß\- ]/gi, '').trim() || 'Projekt') + '.xlsx';
          a.click();
          setTimeout(function () { URL.revokeObjectURL(a.href); }, 4000);
        }).catch(function (e) {
          alert('Excel-Export fehlgeschlagen: ' + e.message);
        }).finally(function () {
          btnX.textContent = alt;
          btnX.disabled = false;
        });
      });
    }
    // LV als ÖNORM-A-2063-Datenträger (.onlv, XML) — WYSIWYG wie .xlsx:
    // schickt die geladenen Gewerke ans Backend, das die ONLV-XML baut.
    var btnLv = document.getElementById('projekt-onlv-btn');
    if (btnLv && !btnLv.dataset.bound) { btnLv.dataset.bound = '1';
      btnLv.addEventListener('click', function () {
        var d = window.projektMassenData || {};
        if (!d.gewerke) { alert('Noch keine Auswertung geladen.'); return; }
        var alt = btnLv.textContent;
        btnLv.textContent = '… erstellt';
        btnLv.disabled = true;
        fetch('/api/aufmass-onlv', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            projekt_name: ((document.getElementById('project-name') || {}).textContent || 'Projekt').trim(),
            gewerke: d.gewerke
          })
        }).then(function (r) {
          var ct = r.headers.get('Content-Type') || '';
          if (ct.indexOf('xml') === -1) return r.json().then(function (j) {
            throw new Error((j && j.grund) || 'Export fehlgeschlagen');
          });
          return r.blob();
        }).then(function (blob) {
          var a = document.createElement('a');
          a.href = URL.createObjectURL(blob);
          var pn = ((document.getElementById('project-name') || {}).textContent || 'Projekt');
          a.download = 'LV_' + (pn.replace(/[^\wäöüß\- ]/gi, '').trim() || 'Projekt') + '.onlv';
          a.click();
          setTimeout(function () { URL.revokeObjectURL(a.href); }, 4000);
        }).catch(function (e) {
          alert('ÖNORM-A-2063-Export fehlgeschlagen: ' + e.message);
        }).finally(function () {
          btnLv.textContent = alt;
          btnLv.disabled = false;
        });
      });
    }
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
          // ORIGINAL-PDF ZURÜCKHOLEN: hochgeladene Pläne müssen wieder
          // herunterladbar sein — auf der Baustelle hat man das Original oft
          // nicht mehr zur Hand, und ein Aufmaß ohne den zugehörigen Plan ist
          // für den Prüfer wertlos.
          '<button class="btn btn-outline btn-sm dl-btn" data-id="' + plan.id +
          '" data-sp="' + esc(plan.storage_path || '') +
          '" data-fn="' + esc(plan.dateiname || 'plan.pdf') +
          '" title="Original-PDF herunterladen">&#11015;</button>' +
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

    // DOWNLOAD des Original-PDFs. Signierte URL statt öffentlichem Link:
    // der Bucket ist privat, und das soll er bleiben — ein Bauplan ist
    // Kundeneigentum.
    planList.querySelectorAll('.dl-btn').forEach(function (b) {
      b.addEventListener('click', function (e) {
        e.stopPropagation();
        var btn = this, sp = btn.getAttribute('data-sp');
        var fn = btn.getAttribute('data-fn') || 'plan.pdf';
        if (!sp) { alert('Zu diesem Plan ist keine Datei hinterlegt.'); return; }
        var t0 = btn.innerHTML;
        btn.disabled = true; btn.textContent = '…';
        _sb.storage.from('plaene').createSignedUrl(sp, 120)
          .then(function (res) {
            if (res.error || !res.data || !res.data.signedUrl) {
              throw new Error((res.error && res.error.message) || 'kein Link');
            }
            // Über den Blob gehen, damit der Dateiname stimmt (ein direkter
            // Link auf den Storage lädt sonst unter dem Pfad-Namen).
            return fetch(res.data.signedUrl).then(function (r) { return r.blob(); });
          })
          .then(function (blob) {
            var a = document.createElement('a');
            a.href = URL.createObjectURL(blob);
            a.download = fn.match(/\.pdf$/i) ? fn : fn + '.pdf';
            document.body.appendChild(a); a.click(); a.remove();
            setTimeout(function () { URL.revokeObjectURL(a.href); }, 4000);
          })
          .catch(function (err) {
            alert('Download nicht möglich: ' + (err.message || err));
          })
          .finally(function () { btn.disabled = false; btn.innerHTML = t0; });
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
    // SEKTOR-VERDRAHTUNG: das bei der Projektanlage gewählte Gewerk fließt in
    // die Analyse (vorher lief ALLES still als 'allgemein'). Nur bekannte
    // Pipeline-Sektoren durchlassen; alles andere → 'allgemein' (Demo-Default).
    // Nur Sektoren, die die Pipeline WIRKLICH rechnet (+ 'dach' als eigener
    // Pfad und 'allgemein' als Default). 'trockenbau' stand hier, wurde aber
    // nie berechnet — der Nutzer waehlte ein Gewerk und bekam dafuer nichts.
    var _SEKTOREN = ['rohbau','putz','estrich','maler','beton','fliesen','fenster',
                     'daemmung','geruest','erdarbeiten','dach','allgemein'];
    var _pg = _SEKTOREN.indexOf(_projGewerk) >= 0 ? _projGewerk : 'allgemein';
    var gewSel = document.querySelector('.gewerk-select[data-id="'+planId+'"]');
    var gesInp = document.querySelector('.geschoss-input[data-id="'+planId+'"]');
    var whgInp = document.querySelector('.whg-og-input[data-id="'+planId+'"]');
    var gewerk = gewSel ? gewSel.value : _pg;
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
    if (progressStatus) progressStatus.textContent = 'Schritt 1/2: PDF-Abschnitte werden in hoher Auflösung analysiert — bei detailreichen/großen Plänen ein bis mehrere Minuten, bitte warten …';
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
    // KEINE fake simulateSteps mehr: sie raste in ~8s auf 90% und kollidierte mit
    // den ECHTEN Meilensteinen (10→40→70→100%) → die Bar sprang und stand dann bei
    // 90%, während die echte Analyse (bei Großplänen Minuten) noch lief = 'hängt'.
    // Der reale Analyse-Flow treibt Bar + Agent-Stepper jetzt allein und ehrlich.
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
        // MANUELL-MODUS (digiplan-Stil): keine Auto-Analyse — der Plan ist
        // nach dem Leicht-Pass sofort messbereit. "KI-Analyse nachholen"
        // steht im Aufmass-Schritt bereit.
        if (window._projModus === 'manuell') {
          _uploadedPlanIds = [];
          wfShow(2);
        } else {
          var queue = _uploadedPlanIds.slice();
          _uploadedPlanIds = [];
          autoAnalyseQueue(queue, 0);
        }
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
  // AUFMASS-KREUZTABELLE: welcher Raum trägt welche Position in welcher Menge.
  // Die Kontrollansicht des Aufmaßes — Vollständigkeit auf einen Blick prüfbar.
  // Zellen sind klickbar: markiert den Raum im Plan (Nachvollziehbarkeit).
  // EIGENE POSITION: der Betrieb hinterlegt SEINE Leistungsposition, waehlt
  // die Aufmassregel und die Raeume — die Menge faellt daraus ab, mit vollem
  // Rechenweg. Ohne Regel bleibt die Position gesperrt ("Regel fehlt").
  var _epRegeln = null;
  function renderEigenePosition(data) {
    var el = document.getElementById('eigene-position');
    if (!el) return;
    var rs = ((data && data.raeume) || []).filter(function (r) { return r && r.flaeche_m2; });
    if (!rs.length) { el.innerHTML = ''; return; }
    if (el.dataset.gebaut === '1') return;      // nicht bei jedem Refresh neu
    el.dataset.gebaut = '1';

    el.innerHTML = '<h4 class="advanced-h" style="margin-top:1.1rem">Eigene Position — ' +
      'nach Aufmaßregel rechnen</h4>' +
      '<p style="font-size:.8rem;color:#6c757d;margin:.2rem 0 .5rem">' +
      'Hinterlege deine Leistungsposition und wähle die Regel, nach der ' +
      'gemessen wird. Ohne Regel gibt es keine Menge — so steht hinter jeder ' +
      'Zahl eine benannte Vorschrift.</p>' +
      '<div class="ep-form" style="display:flex;flex-wrap:wrap;gap:.5rem;align-items:flex-end">' +
      '  <label style="font-size:.78rem;color:#6c757d">Pos.-Nr.<br>' +
      '    <input id="ep-nr" class="form-control" style="width:6.5rem" placeholder="01.01"></label>' +
      '  <label style="font-size:.78rem;color:#6c757d;flex:1;min-width:12rem">Bezeichnung<br>' +
      '    <input id="ep-bez" class="form-control" placeholder="z.B. Estrich 60 mm"></label>' +
      '  <label style="font-size:.78rem;color:#6c757d">Aufmaßregel <span style="color:#b45309">*</span><br>' +
      '    <select id="ep-regel" class="form-control" style="min-width:15rem"><option value="">— Regel wählen —</option></select></label>' +
      '  <label style="font-size:.78rem;color:#6c757d">Verschnitt %<br>' +
      '    <input id="ep-vs" class="form-control" style="width:5.5rem" type="number" min="0" max="50" step="0.5" value="0"></label>' +
      '  <button class="btn btn-accent btn-sm" id="ep-go">Menge ermitteln</button>' +
      '</div>' +
      '<details style="margin:.5rem 0"><summary style="cursor:pointer;font-size:.82rem;color:#6c757d">' +
      'Räume zuordnen (ohne Auswahl zählen alle ' + rs.length + ')</summary>' +
      '<div id="ep-raeume" style="display:flex;flex-wrap:wrap;gap:.4rem;margin-top:.4rem">' +
      rs.map(function (r, i) {
        return '<label style="font-size:.78rem;background:rgba(0,0,0,.04);padding:.15rem .45rem;border-radius:3px">' +
          '<input type="checkbox" class="ep-r" data-i="' + i + '"> ' + esc(r.name || 'Raum') +
          ' <span style="color:#6c757d">' + fmtNum(r.flaeche_m2) + ' m²</span></label>';
      }).join('') + '</div></details>' +
      '<div id="ep-out"></div>';

    var sel = document.getElementById('ep-regel');
    function fuelleRegeln(rg) {
      _epRegeln = rg;
      rg.forEach(function (r) {
        var o = document.createElement('option');
        o.value = r.id;
        o.textContent = r.name + '  [' + r.einheit + ' · ' + r.norm + ']';
        sel.appendChild(o);
      });
    }
    if (_epRegeln) fuelleRegeln(_epRegeln);
    else {
      fetch('/api/aufmassregeln').then(function (r) { return r.json(); })
        .then(function (d) { if (d && d.ok) fuelleRegeln(d.regeln || []); })
        .catch(function () { /* Maske bleibt nutzbar, Auswahl leer */ });
    }

    document.getElementById('ep-go').addEventListener('click', function () {
      var out = document.getElementById('ep-out');
      var regel = sel.value;
      if (!regel) {
        out.innerHTML = '<p style="color:#b45309;font-size:.84rem;margin:.4rem 0">' +
          '⚠ Regel fehlt — bitte eine Aufmaßregel wählen. Ohne Regel wird keine ' +
          'Menge ermittelt.</p>';
        return;
      }
      var gewaehlt = [];
      document.querySelectorAll('.ep-r:checked').forEach(function (c) {
        var r = rs[parseInt(c.dataset.i, 10)];
        if (r && r.name) gewaehlt.push(r.name);
      });
      var d = window.projektMassenData || {};
      out.innerHTML = '<p style="font-size:.84rem;color:#6c757d">… wird gerechnet</p>';
      fetch('/api/eigene-position', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          regel: regel,
          posnr: (document.getElementById('ep-nr').value || '').trim() || '01.01',
          bezeichnung: (document.getElementById('ep-bez').value || '').trim(),
          raeume: rs, fenster: d.fenster || [], tueren: d.tueren || [],
          baudaten: d.baudaten || {},
          raum_filter: gewaehlt.length ? gewaehlt : null,
          verschnitt_pct: parseFloat(document.getElementById('ep-vs').value) || 0
        })
      }).then(function (r) { return r.json(); }).then(function (res) {
        if (!res || !res.ok) {
          out.innerHTML = '<p style="color:#b45309;font-size:.84rem">' +
            esc((res && res.grund) || 'Fehlgeschlagen') + '</p>';
          return;
        }
        var p = res.position;
        var h = '<div style="margin-top:.5rem;padding:.5rem .7rem;border-left:3px solid var(--accent);background:rgba(0,0,0,.025)">' +
          '<strong>' + esc(p.posnr) + ' ' + esc(p.beschreibung) + '</strong> = ' +
          '<strong style="color:#166534">' + fmtNum(p.endsumme) + ' ' + esc(p.einheit) + '</strong>' +
          '<div style="font-size:.78rem;color:#6c757d;margin:.2rem 0 .4rem">Regel: ' + esc(p.quelle) + '</div>' +
          '<table class="oa-tab"><tbody>' +
          (p.zeilen || []).map(function (z) {
            var raum = (z.anker || {}).raum;
            return '<tr><td' + _raumKlick(raum, (z.text || '') +
              (z.quelle ? ' · ' + z.quelle : '') +
              (z.wert != null ? ' = ' + fmtNum(z.wert) : '')) + '>' +
              esc(z.text || '') + '</td><td style="text-align:right">' + fmtNum(z.wert) +
              '</td><td style="color:#6c757d;font-size:.76rem">' + esc(z.quelle || '') + '</td></tr>';
          }).join('') + '</tbody></table></div>';
        out.innerHTML = h;
      }).catch(function (e) {
        out.innerHTML = '<p style="color:#b45309;font-size:.84rem">Fehlgeschlagen: ' +
          esc(e.message) + '</p>';
      });
    });
  }

  // Klick-Attribut "Im Plan zeigen" — EINE Stelle statt drei.
  //
  // Hier stand dreimal JSON.stringify(name) INNERHALB eines doppelt
  // gequoteten Attributs. JSON.stringify liefert aber DOPPELTE
  // Anfuehrungszeichen, und damit endet das Attribut mitten im Aufruf:
  //     onclick="nzHighlightRaum("Zimmer 1")"
  // Der Browser liest daraus onclick="nzHighlightRaum(" — ein Syntaxfehler,
  // der Klick blieb wirkungslos. Im Browser nachgestellt und bestaetigt.
  // Innen gehoeren EINFACHE Anfuehrungszeichen hin, JS-escaped und danach
  // HTML-escaped.
  function _jsStr(x) {
    return esc(String(x || '').replace(/\\/g, '\\\\').replace(/'/g, "\\'"));
  }

  function _raumKlick(name, beleg) {
    var s = String(name || '');
    if (!s) return '';
    return ' style="cursor:pointer" onclick="nzHighlightRaum(\'' + _jsStr(s) +
      '\'' + (beleg ? ", '" + _jsStr(beleg) + "'" : '') +
      ')" title="Im Plan zeigen"';
  }

  function renderAufmassMatrix(m) {
    var el = document.getElementById('aufmass-matrix');
    // Auch fuer die Raum-Werte am Plan merken — dieselbe gerechnete Grundlage,
    // damit Plan und Kreuztabelle nie auseinanderlaufen.
    _lastMatrix = m || null;
    if (!el) return;
    if (!m || !(m.positionen || []).length || !(m.raeume || []).length) {
      el.innerHTML = ''; return;
    }
    // nur Positionen zeigen, die mindestens einem Raum zugeordnet sind
    var benutzt = {};
    (m.raeume || []).forEach(function (r) {
      Object.keys(r.mengen || {}).forEach(function (k) { benutzt[k] = 1; });
    });
    var spalten = (m.positionen || []).filter(function (p) { return benutzt[p.key]; });
    if (!spalten.length) { el.innerHTML = ''; return; }
    var zeilen = (m.raeume || []).filter(function (r) { return r.n_positionen > 0; });

    var h = '<h4 class="advanced-h" style="margin-top:1.1rem">Aufmaß-Kreuztabelle — ' +
      'welcher Raum trägt welche Position</h4>' +
      '<p style="font-size:.8rem;color:#6c757d;margin:.2rem 0 .5rem">' +
      esc(zeilen.length) + ' Räume × ' + esc(spalten.length) + ' Positionen · ' +
      '<strong>' + fmtNum(m.deckung_pct) + '%</strong> der Menge ist raumscharf belegt' +
      ((m.ohne_anker || []).length ? ' · ' + (m.ohne_anker || []).length +
        ' Zeilen gelten gebäudeweit (unten ausgewiesen)' : '') + '</p>' +
      '<div class="tbl-scroll"><table class="oa-tab"><thead><tr>' +
      '<th style="position:sticky;left:0;background:inherit">Raum</th>' +
      '<th>F (m²)</th>';
    spalten.forEach(function (p) {
      // Regel-Herkunft sichtbar: ÖNORM-gestützt / Stückzahl / Fachpraxis /
      // FREMDNORM. Eine Menge ohne österreichische Norm darf nicht so
      // aussehen, als haette sie eine.
      var rg = p.regel_obj || null;
      var art = rg && rg.art, kz = '', tip = (p.regel || '');
      if (art === 'norm') { kz = '<span style="color:#166534" title="nach ' +
        esc(rg.norm) + '">' + esc(rg.norm.replace('ÖNORM ', '')) + '</span>'; }
      else if (art === 'norm_offen') { kz = '<span style="color:#b45309" ' +
        'title="Regelwerk ' + esc(rg.norm) + ' — aber ein Parameter (Abzugs' +
        'schwelle) ist darin nicht belegt und je Firma zu setzen">' +
        esc(rg.norm.replace('ÖNORM ', '')) + ' *</span>'; }
      else if (art === 'fremdnorm') { kz = '<span style="color:#b45309" ' +
        'title="Fremdnorm — fachlich zu klären">⚠ ' + esc(rg.norm) + '</span>'; }
      else if (art === 'stueckzahl') { kz = '<span style="color:#6c757d">Stück</span>'; }
      else if (art === 'praxis') { kz = '<span style="color:#b45309" ' +
        'title="Fachpraxis/Annahme — kein Norm-Beleg">Praxis</span>'; }
      h += '<th title="' + esc((p.gewerk_label || '') + ' · ' + tip) + '">' +
        esc(p.posnr || '') + '<div style="font-weight:400;font-size:.7rem;color:#6c757d">' +
        esc((p.beschreibung || '').replace(/\s*—.*$/, '').slice(0, 26)) +
        '<br>' + esc(p.einheit || '') + (kz ? ' · ' + kz : '') + '</div></th>';
    });
    h += '</tr></thead><tbody>';
    // Welche Raumnamen kommen mehrfach vor? Nur dort hilft die Wohnung.
    var _mehrfach = {};
    zeilen.forEach(function (r) {
      _mehrfach[r.raum] = (_mehrfach[r.raum] || 0) + 1;
    });
    Object.keys(_mehrfach).forEach(function (k) {
      _mehrfach[k] = _mehrfach[k] > 1;
    });
    zeilen.forEach(function (r) {
      // Wohnung NUR anzeigen, wenn sie wirklich unterscheidet: in einem
      // Wohnbau heissen drei Zeilen "Bad" und brauchen sie, in einem
      // Einfamilienhaus stuende hinter jedem Raum "Haus" — reiner Lärm.
      h += '<tr><td style="position:sticky;left:0;background:inherit"><strong>' +
        esc(r.raum || '') + '</strong>' +
        ((r.wohnung && _mehrfach[r.raum]) ? ' <span style="color:#6c757d;font-size:.75rem">'
          + esc(r.wohnung) + '</span>' : '') +
        (r.geschoss ? ' <span style="color:#6c757d;font-size:.75rem">' + esc(r.geschoss) + '</span>' : '') +
        '</td><td>' + (r.f_m2 != null ? fmtNum(r.f_m2) : '—') + '</td>';
      spalten.forEach(function (p) {
        var v = (r.mengen || {})[p.key];
        h += '<td' + (v != null
          ? _raumKlick(r.raum, (p.posnr ? p.posnr + ' ' : '') +
              (p.beschreibung || '').replace(/\s*—.*$/, '') + ' · ' +
              (r.raum || '') + ' · ' + fmtNum(v) + ' ' + (p.einheit || '') +
              (p.regel ? ' · ' + p.regel : '')) + '>' + fmtNum(v)
          : ' style="color:#c8ccd0">—') + '</td>';
      });
      h += '</tr>';
    });
    h += '</tbody></table></div>';
    if ((m.ohne_anker || []).length) {
      var summe = 0;
      (m.ohne_anker || []).forEach(function (o) { summe += Math.abs(o.wert || 0); });
      h += '<details style="margin-top:.5rem"><summary style="cursor:pointer;font-size:.82rem;color:#6c757d">' +
        'Gebäudeweite Mengen ohne Raum-Zuordnung (' + (m.ohne_anker || []).length +
        ' Zeilen, Σ ' + fmtNum(Math.round(summe * 100) / 100) + ') — ehrlich ausgewiesen</summary>' +
        '<div class="tbl-scroll" style="margin-top:.3rem"><table class="oa-tab"><tbody>';
      (m.ohne_anker || []).slice(0, 40).forEach(function (o) {
        h += '<tr><td>' + esc(o.beschreibung || '') + '</td><td>' + esc(o.text || '') +
          '</td><td>' + fmtNum(o.wert) + '</td></tr>';
      });
      h += '</tbody></table></div></details>';
    }
    el.innerHTML = h;
  }

  function renderRaumAufmass(raeume, baudaten) {
    var el = document.getElementById('raum-aufmass');
    if (!el) return;
    var innen = (raeume || []).filter(function (r) { return r && r.flaeche_m2; });
    if (!innen.length) { el.innerHTML = ''; return; }
    var hDef = (baudaten || {}).geschosshoehe_m || 2.7;
    var sF = 0, sW = 0, sU = 0;
    var html = '<h4 class="advanced-h" style="margin-top:1.1rem">Raum-Aufmaß — jeder Raum einzeln ' +
      '(F/U byte-exakt aus den Raum-Stempeln des Plans)</h4>' +
      '<div class="tbl-scroll"><table class="oa-tab"><thead><tr><th>Raum</th><th>Boden (=F)</th><th>Decke</th><th>Umfang U</th>' +
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
        '<td>' + (u ? fmtNum(u) + ' m ' + (r.umfang_geschaetzt
          ? '<span title="aus Raum-Proportion geschätzt (kein U-Stempel im Plan) — bitte prüfen">≈</span>'
          : '✓') : '–') + '</td>' +
        '<td>' + (h ? fmtNum(h) + ' m' + (r.hoehe_m ? ' ✓' : ' ≈') : '–') + '</td>' +
        '<td>' + (wf ? fmtNum(wf) + ' m²' : '–') + '</td>' +
        '<td>' + (u && !aussen ? fmtNum(u) + ' lfm' : '–') + '</td></tr>';
    });
    html += '</tbody></table></div><div class="oa-summe">Σ Innenräume: Boden <strong>' +
      fmtNum(Math.round(sF * 100) / 100) + ' m²</strong> · Wandabwicklung <strong>' +
      fmtNum(Math.round(sW * 100) / 100) + ' m²</strong> · Sockel <strong>' +
      fmtNum(Math.round(sU * 100) / 100) + ' lfm</strong> — ✓ = byte-exakt aus dem Plan-Text, ' +
      '≈ = geschätzt (Geschoss-Höhe übernommen bzw. Umfang aus Raum-Proportion). ' +
      'Öffnungs-Abzüge: siehe Öffnungs-Aufmaß.</div>';
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
      // Abzug auf die eigene Brutto-Wandfläche deckeln → netto nie NEGATIV: eine
      // kurze Wand, der eine große (>4 m²) Öffnung zugeordnet wurde, zeigte sonst
      // eine negative Fläche (die Öffnung überlappt evtl. eine Nachbarwand).
      var abzug = Math.round(Math.min(brutto,
        oe.reduce(function (a, x) { return a + x.abzug; }, 0)) * 100) / 100;
      var netto = Math.round((brutto - abzug) * 100) / 100;
      rows.push({ id: w.id, cm: cm, l: w.laenge_m, exakt: !!w.mass_exakt,
        manuell: !!w.manuell, achse: w.achse, brutto: brutto,
        nOeff: oe.length, abzug: abzug, netto: netto,
        // GEWERK aus dem Wand-Code des Plans (nicht aus der Dicke).
        gewerk: w.gewerk || null, gewerkCode: w.gewerk_code || null });
      sums[cm] = sums[cm] || { n: 0, l: 0, m2: 0 };
      sums[cm].n++; sums[cm].l += w.laenge_m; sums[cm].m2 += netto;
    });
    if (!rows.length) { el.innerHTML = ''; return; }
    rows.sort(function (a, b) { return b.cm - a.cm || b.l - a.l; });
    var html = '<h4 class="advanced-h" style="margin-top:1.1rem">Wand-Aufmaß — jede Wand einzeln ' +
      '(aus der Planansicht · Höhe ' + fmtNum(h) + ' m · aktualisiert sich mit deinen Korrekturen)</h4>' +
      '<div class="oa-summe">' + Object.keys(sums).sort(function (a, b) { return b - a; }).map(function (t) {
        return _nzTLabel(t) + ': ' + sums[t].n + ' Wände · Σ ' + fmtNum(Math.round(sums[t].l * 100) / 100) +
          ' m · <strong>' + fmtNum(Math.round(sums[t].m2 * 100) / 100) + ' m²</strong> netto';
      }).join(' &nbsp;|&nbsp; ') + '</div>' +
      '<div class="tbl-scroll"><table class="oa-tab"><thead><tr><th>Wand</th><th>Stärke</th><th>Gewerk</th><th>Länge</th><th>Höhe</th>' +
      '<th>brutto</th><th>Öffnungen</th><th>Abzug >4m²</th><th>netto</th><th>Quelle</th></tr></thead><tbody>';
    rows.forEach(function (r) {
      html += '<tr><td>W' + r.id + ' (' + (r.achse === 'v' ? 'vert.' : 'horiz.') + ')</td>' +
        '<td>' + _nzTLabel(r.cm) + '</td>' +
        // Das Gewerk steht am Bauteil, nicht in einer Fussnote: wer die
        // Mengen prueft, sieht sofort, ob eine Wand LG 08 (Mauerwerk),
        // LG 07 (Beton), LG 39 (Trockenbau) oder LG 36 (Holzbau) ist.
        '<td>' + (r.gewerk
          ? '<span title="aus Wand-Code ' + esc(r.gewerkCode || '') +
            ' laut Plan-Legende">' +
            ({mauerwerk: 'Mauerwerk', beton: 'Beton',
              trockenbau: 'Trockenbau', holz: 'Holzbau'}[r.gewerk] || r.gewerk) +
            '</span>'
          : '<span style="color:#9aa0a6" title="Plan definiert für diese Wand keinen Aufbau">–</span>') + '</td>' +
        '<td>' + fmtNum(r.l) + ' m' + (r.exakt ? ' <span title="Länge = byte-exakte Plan-Maßzahl">✓</span>' : '') + '</td>' +
        '<td>' + fmtNum(h) + ' m</td>' +
        '<td>' + fmtNum(r.brutto) + ' m²</td>' +
        '<td>' + (r.nOeff || '–') + '</td>' +
        '<td>' + (r.abzug ? '−' + fmtNum(r.abzug) + ' m²' : '–') + '</td>' +
        '<td><strong>' + fmtNum(r.netto) + ' m²</strong></td>' +
        '<td>' + (r.manuell ? 'manuell ergänzt' : (r.exakt ? 'Plan-Maßzahl (byte-exakt)' : 'Vektor-Messung')) + '</td></tr>';
    });
    el.innerHTML = html + '</tbody></table></div>' +
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
      '<div class="tbl-scroll"><table class="oa-tab"><thead><tr><th>Raum</th><th>Typ</th><th>Wand</th><th>B×H</th><th>Fläche</th>' +
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
    el.innerHTML = html + '</tbody></table></div>';
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

  // ── GENERALISIERUNG für Pläne OHNE Mauerwerks-Legende (Breiten-Test Holzbau 1:50):
  // schnappt KEINE Wand auf die Legende, werden die gemessenen Stärken geclustert und
  // als neutrale "d X cm"-Wände (statt "HLZ", was Ziegel behauptet) dargestellt.
  // Nur dann aktiv → Mauerwerks-Pläne (Angerer) unverändert (strikt monoton, wie Backend).
  var _nzLegendlos = false;   // true = kein einziger Legenden-Snap auf diesem Plan
  var _nzMessMap = {};        // wand.id → repräsentative gemessene Stärke (cm)
  var _NZ_PAL = ['#0d9488', '#7c3aed', '#c2410c', '#0369a1', '#4d7c0f', '#a21caf'];
  function _nzFarbe(cm) {
    return NZ_FARBE[cm] != null ? NZ_FARBE[cm] : _NZ_PAL[Math.abs(Math.round(cm || 0)) % _NZ_PAL.length];
  }
  function _nzTLabel(cm) { return _nzLegendlos ? ('d ' + cm + ' cm') : ('HLZ ' + cm); }
  function _nzStaerkeOptionen() {
    if (!_nzLegendlos) return [50, 38, 25, 20, 12];
    var s = {};
    Object.keys(_nzMessMap).forEach(function (k) { s[_nzMessMap[k]] = 1; });
    var arr = Object.keys(s).map(Number).sort(function (a, b) { return b - a; });
    return arr.length ? arr : [50, 38, 25, 20, 12];
  }
  function _nzBaueMessCluster() {
    _nzLegendlos = false; _nzMessMap = {};
    var ws = (_nzData && _nzData.waende) || [];
    if (!ws.length || ws.some(function (w) { return w.snap_cm != null; })) return;
    _nzLegendlos = true;   // gemessene Stärken längen-gewichtet zu Buckets clustern (±2cm)
    var pts = ws.filter(function (w) { return (w.dicke_cm || 0) >= 5; })
      .map(function (w) { return { id: w.id, d: Math.round(w.dicke_cm), l: w.laenge_m || 0 }; })
      .sort(function (a, b) { return a.d - b.d; });
    var grp = [];
    function flush(g) {
      if (!g.length) return;
      var L = g.reduce(function (s, x) { return s + x.l; }, 0) || 1;
      var rep = Math.round(g.reduce(function (s, x) { return s + x.d * x.l; }, 0) / L);
      g.forEach(function (x) { _nzMessMap[x.id] = rep; });
    }
    pts.forEach(function (x) {
      if (grp.length && x.d - grp[grp.length - 1].d > 2) { flush(grp); grp = []; }
      grp.push(x);
    });
    flush(grp);
  }
  var _nzSel = null;
  // MEHRFACHAUSWAHL (Zeichentool): Shift-Klick sammelt Wände, das
  // Eigenschaften-Panel wirkt dann auf alle. _nzSel bleibt die primäre
  // Wand (bestehende Einzel-Aktionen unverändert).
  var _nzSelSet = [];
  var _nzRaumInfo = null;   // angeklickter Raum (Werte-Anzeige, ohne Editor)
  var _nzZoom = { s: 1, x: 0, y: 0 }, _nzMoved = false;   // Zoom/Pan-Zustand + Drag-Erkennung
  var _nzWrap = null, _nzPan = null, _nzZoomWinBound = false;
  var _nzAddMode = false, _nzDraw = null;   // "Wand hinzufügen"-Modus + laufende Zeichnung
  var _nzMeasMode = false, _nzMeasPts = [];   // MESSEN-Modus (Lineal/Fläche) + geklickte Punkte
  var _nzRaumFill = true;   // Räume kräftig bunt füllen (Raumansicht, Default an)
  var _nzUmfassung = true;  // Raumgrenze je Bauteil färben (Außen/Innenwand, Tür, offen)
  // PRÄSENTATION: alles ausblenden, was der Prüfer braucht und der Zuschauer
  // nicht — Wand-Beschriftung, Öffnungs-Marker, Prüf-Notizen. Übrig bleibt,
  // was die Leistung zeigt: der Raum-Umriss auf dem echten Plan, sein Name
  // und seine Fläche. Am Angerer-Plan liegen sonst über 40 Beschriftungen
  // gleichzeitig im Bild und überlappen einander.
  var _nzPraes = false;
  // ── AUFMASS-WERKZEUG (E2) ───────────────────────────────────────────
  // Der Unterschied zwischen Erkennungs-Demo und Werkzeug: hier entstehen
  // Mengen durch KLICKEN, nicht nur durch Erkennen. Jede Messung ist ein
  // gespeichertes Objekt (Tabelle `messungen`), das Ergebnis kommt vom
  // Server — ein zweiter Rechenweg im Browser waere eine zweite Wahrheit.
  var _mwTool = null;        // flaeche|rechteck|laenge|stueck|abzug|null
  var _mwPts = [];           // laufende Zeichnung (Bild-px)
  var _mwListe = [];         // gespeicherte Messungen dieser Seite
  var _mwSel = null;         // gewaehlte Messung (id)
  var _mwSnap = true;        // auf erkannte Wandlinien/Ecken einrasten
  var _mwBusy = false;
  var _mwAutoDone = {};   // Plan:Seite -> Auto-Vorschlag schon versucht
  var _mwPending = null;  // fertige Hoehen-Zeichnung, wartet auf Eingabe im Panel
  var _mwUndo = [];       // in DIESER Sitzung erzeugte Messungen (Ctrl+Z)
  var _mwVDrag = null;    // {mid, vi} — gezogener Eckpunkt einer Messung
  // EBENEN (Nutzer: "das, was mit KI draufgezeichnet wurde, auch entfernen
  // koennen"): jede KI-Ebene laesst sich einzeln ausblenden — der Plan
  // selbst bleibt immer sichtbar.
  var _nzLay = { waende: true, oeff: true, raeume: true, mess: true };
  var _MW_FARBE = { flaeche: '#0d9488', rechteck: '#0d9488', laenge: '#1d4ed8',
                    stueck: '#7c3aed', abzug: '#dc2626', volumen: '#b45309', treppe: '#9333ea', dach: '#0369a1', wandflaeche: '#a16207',
                    bauteil: '#0f766e' };
  var _MW_NAME = { flaeche: 'Fläche', rechteck: 'Rechteck', laenge: 'Länge', treppe: 'Treppe', dach: 'Dach', wandflaeche: 'Wandfläche',
                   stueck: 'Stück', abzug: 'Abzug', volumen: 'Volumen',
                   bauteil: 'Bauteil' };
  // Kräftige, gut unterscheidbare Raumfarben (Raumansicht) — je Raum stabil per Index.
  var _NZ_RAUMFARBEN = ['#22c55e', '#3b82f6', '#a855f7', '#ec4899', '#f97316',
    '#14b8a6', '#eab308', '#8b5cf6', '#06b6d4', '#ef4444', '#84cc16', '#f43f5e'];
  // RAUM-POLYGON-EDITOR: Eckpunkte ziehen/hinzufügen/löschen, Fläche live neu.
  var _nzRaumEditMode = false;   // „Raum bearbeiten"-Modus
  var _nzRaumSel = -1;           // Index des bearbeiteten Raums in _nzData.raeume
  var _nzRvDrag = null;          // {ri, vi} gerade gezogener Eckpunkt
  // GANZEN RAUM VERSCHIEBEN (digiplan-Parität "Flächen leicht verschieben"):
  // {ri, start, orig, ank} — ank = Index der Ecke, die beim Fangen einrastet
  // (die dem Griff-Punkt nächste Ecke; so snappt die ganze Fläche auf die Wand).
  var _nzRMove = null;
  var _mwMDrag = null;           // ganze MESSUNG verschieben: {mid, start, orig}
  var _nzFull = false;           // Plan im Vollbild

  // Fläche (m²) eines Polygons in Bild-Pixeln — Shoelace, am Plan-Maßstab.
  function _nzPolyFlaeche(pts) {
    if (!pts || pts.length < 3) return 0;
    var k = _nzPxProM(); if (!k) return 0;
    var A = 0, n = pts.length;
    for (var i = 0; i < n; i++) {
      var a = pts[i], b = pts[(i + 1) % n];
      A += a[0] * b[1] - b[0] * a[1];
    }
    return Math.abs(A) / 2 / (k * k);
  }
  // Umfang (m) eines geschlossenen Polygons in Bild-Pixeln.
  function _nzPolyUmfang(pts) {
    if (!pts || pts.length < 3) return 0;
    var k = _nzPxProM(); if (!k) return 0;
    var U = 0, n = pts.length;
    for (var i = 0; i < n; i++) {
      var a = pts[i], b = pts[(i + 1) % n];
      U += Math.sqrt((b[0] - a[0]) * (b[0] - a[0]) + (b[1] - a[1]) * (b[1] - a[1]));
    }
    return U / k;
  }
  // Polygon-Vereinfachung (Douglas-Peucker): entfernt Rausch-/Treppen-Punkte
  // der Watershed-Rekonstruktion, damit die Raum-Umrisse sauberer/glatter am
  // Plan liegen — ohne die Fläche zu verzerren (nur fast-kollineare Punkte weg).
  function _nzSimplify(pts, eps) {
    if (!pts || pts.length <= 4) return pts;
    function seg(p, a, b) {
      var dx = b[0] - a[0], dy = b[1] - a[1], L2 = dx * dx + dy * dy;
      if (!L2) return Math.hypot(p[0] - a[0], p[1] - a[1]);
      var t = ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / L2;
      t = Math.max(0, Math.min(1, t));
      return Math.hypot(p[0] - (a[0] + t * dx), p[1] - (a[1] + t * dy));
    }
    function dp(list) {
      if (list.length < 3) return list;
      var dmax = 0, idx = 0;
      for (var i = 1; i < list.length - 1; i++) {
        var d = seg(list[i], list[0], list[list.length - 1]);
        if (d > dmax) { dmax = d; idx = i; }
      }
      if (dmax > eps) {
        var l = dp(list.slice(0, idx + 1)), r = dp(list.slice(idx));
        return l.slice(0, -1).concat(r);
      }
      return [list[0], list[list.length - 1]];
    }
    // geschlossenes Polygon: am weitest entfernten Punktpaar aufbrechen
    var out = dp(pts.concat([pts[0]]));
    out.pop();
    return out.length >= 3 ? out : pts;
  }
  // Rekonstruierte Raum-Umrisse einmalig glätten (nur echte, nicht editierte).
  function _nzCleanRegionen() {
    if (!_nzData || !_nzData.raeume) return;
    var k = _nzPxProM(); var eps = k ? k * 0.12 : 4;   // ~12 cm Toleranz
    _nzData.raeume.forEach(function (r) {
      if (!r.region_px || r.region_px.length < 5 || r._cleaned || r._edited) return;
      r._cleaned = true;
      r.region_px = _nzSimplify(r.region_px, eps);
    });
  }
  // WAND-SNAPPING (Kern für „läuft von selbst genau"): jeden Raum-Eckpunkt auf
  // die nächste byte-exakte Wand-FLUCHT rasten (Maßketten-Linien aus dem Plan).
  // So kleben die rekonstruierten Räume automatisch sauber an den Wänden statt
  // watershed-ungefähr daneben. Nur innerhalb Toleranz (~30 cm) — weit entfernte
  // Ecken (freie Kanten) bleiben. Nur echte, nicht editierte/synthetische Polygone.
  function _nzSnapRegionen() {
    if (!_nzData || !_nzData.raeume || !_nzData.fluchten || !_nzData.fluchten.length) return;
    var k = _nzPxProM(); var tol = k ? k * 0.30 : 12;   // ~30 cm Fangradius
    var vx = [], hy = [];
    _nzData.fluchten.forEach(function (f) {
      if (f.px == null) return;
      if (f.achse === 'v') vx.push(f.px); else hy.push(f.px);
    });
    if (!vx.length && !hy.length) return;
    function snap(val, arr) {
      var best = val, bd = tol;
      for (var i = 0; i < arr.length; i++) {
        var d = Math.abs(arr[i] - val);
        if (d < bd) { bd = d; best = arr[i]; }
      }
      return best;
    }
    _nzData.raeume.forEach(function (r) {
      // auch synthetische Startformen ausrichten (aber nicht editierte);
      // fehlt in Reichweite eine Flucht, bleibt die Ecke → offener Carport
      // wird nicht verzerrt.
      if (!r.region_px || r.region_px.length < 3 || r._snapped || r._edited) return;
      r._snapped = true;
      var snapped = r.region_px.map(function (p) {
        return [Math.round(snap(p[0], vx)), Math.round(snap(p[1], hy))];
      });
      // nach dem Snap aufeinanderfallende Punkte zusammenfassen
      var out = [];
      snapped.forEach(function (p) {
        var last = out[out.length - 1];
        if (!last || Math.abs(last[0] - p[0]) > 1 || Math.abs(last[1] - p[1]) > 1) out.push(p);
      });
      if (out.length >= 3) r.region_px = out;
    });
  }
  // JEDER Raum als editierbares Polygon: Räume mit Fläche, aber OHNE rekonstru-
  // iertes Polygon (offene/verwinkelte Räume, die das Backend auslässt) bekommen
  // eine GESCHÄTZTE Rechteck-Startform aus F+U, mittig am Raum-Label. So sieht
  // der Nutzer jeden Raum farbig — und zieht die Form am Plan zurecht (Calcora-
  // Prinzip). Klar als geschätzt markiert (_synthetic). Einmal je Datensatz.
  function _nzSynthRegionen() {
    if (!_nzData || !_nzData.raeume) return;
    var k = _nzPxProM(); if (!k) return;
    _nzData.raeume.forEach(function (r) {
      if ((r.region_px && r.region_px.length >= 3) || r._synthTried) return;
      r._synthTried = true;
      var f = r.f_m2, u = r.u_m, px = r.px;
      if (!f || !px) return;
      var a, b;   // Seiten in Metern
      if (u && u > 0) {
        var p = u / 2, disc = p * p / 4 - f;
        if (disc >= 0) { var w = Math.sqrt(disc); a = p / 2 + w; b = p / 2 - w; }
      }
      if (!(a > 0 && b > 0)) { a = b = Math.sqrt(f); }   // Fallback: Quadrat
      var aw = a * k / 2, bh = b * k / 2, cx = px[0], cy = px[1];
      r.region_px = [[cx - aw, cy - bh], [cx + aw, cy - bh], [cx + aw, cy + bh], [cx - aw, cy + bh]];
      r._synthetic = true;   // geschätzte Startform — bitte am Plan anpassen
    });
  }
  // Ein Raum-Polygon wurde geändert → neue Fläche/Umfang merken (noch nicht in
  // die Massen — erst „Fläche übernehmen"). Readout aktualisieren.
  // ▭ RECHTECK-WERKZEUG (Nutzer-Richtung: "bei den Aussenflaechen wie der
  // Terrasse ist es meistens rechteckig"). Ersetzt das Polygon des gewaehlten
  // Raums durch ein achsparalleles Rechteck: Seitenverhaeltnis aus der
  // Bounding-Box des bisherigen Umrisses, FLAECHE = byte-exakter Stempel
  // (die Wahrheit bleibt die Wahrheit), Mittelpunkt = Polygon-Schwerpunkt.
  // Der Mensch bleibt im Spiel: Ecken sind danach normal ziehbar, und
  // "Original" stellt den erkannten Umriss wieder her.
  function _nzRaumRechteck(ri) {
    var r = _nzData.raeume[ri]; if (!r || !(r.region_px || []).length) return;
    var k = _nzPxProM(); if (!k) return;
    if (!r._region_orig) r._region_orig = r.region_px.map(function (p) { return [p[0], p[1]]; });
    var xs = r.region_px.map(function (p) { return p[0]; });
    var ys = r.region_px.map(function (p) { return p[1]; });
    var bw = Math.max.apply(null, xs) - Math.min.apply(null, xs);
    var bh = Math.max.apply(null, ys) - Math.min.apply(null, ys);
    if (bw <= 0 || bh <= 0) return;
    var cx = 0, cy = 0;
    r.region_px.forEach(function (p) { cx += p[0]; cy += p[1]; });
    cx /= r.region_px.length; cy /= r.region_px.length;
    var fpx = (r.f_m2 || _nzPolyFlaeche(r.region_px)) * k * k;   // Ziel in px²
    var w = Math.sqrt(fpx * (bw / bh)), h = fpx / w;
    r.region_px = [[cx - w / 2, cy - h / 2], [cx + w / 2, cy - h / 2],
                   [cx + w / 2, cy + h / 2], [cx - w / 2, cy + h / 2]]
      .map(function (p) { return [Math.round(p[0]), Math.round(p[1])]; });
    _nzRaumMarkEdited(ri); _nzPaint(); _nzRaumLiveReadout(ri);
  }
  function _nzRaumOriginal(ri) {
    var r = _nzData.raeume[ri]; if (!r || !r._region_orig) return;
    r.region_px = r._region_orig.map(function (p) { return [p[0], p[1]]; });
    r._region_orig = null; r._edited = false; r._f_edit = null; r._u_edit = null;
    _nzPaint(); _nzRaumLiveReadout(ri);
    _nzSave(null);   // Rückbau auch speichern — sonst kehrt die alte
                     // raum_regionen-Korrektur beim Reload zurück
  }
  // ── FLÜSSIGES ZIEHEN ─────────────────────────────────────────────────
  // Vorher rief JEDE Mausbewegung _nzPaint() — und das baut das komplette
  // Studio neu (Werkzeugleiste, alle Wand-/Raum-/Öffnungs-/Mess-SVGs, das
  // Eigenschaften-Panel) und bindet sämtliche Listener neu. Auf einem Plan
  // mit 27 Wänden und 10 Räumen sind das tausende DOM-Knoten pro Frame; das
  // Ziehen ruckelte entsprechend (Nutzer-Befund 2026-08-23).
  // Jetzt: während des Ziehens werden nur die Attribute der betroffenen
  // SVG-Elemente gesetzt, gedrosselt auf einen Frame. Das volle _nzPaint
  // läuft erst beim Loslassen — dort ist es unmerklich.
  var _nzRaf = null;
  function _nzFrame(fn) {
    if (_nzRaf) return;                       // in diesem Frame schon geplant
    _nzRaf = requestAnimationFrame(function () { _nzRaf = null; fn(); });
  }
  function _nzQ(sel) { return _nzWrap ? _nzWrap.querySelector(sel) : null; }
  // Raum ri direkt im SVG nachziehen (Polygon + Eck-, Einfüge- und ✥-Griffe).
  function _nzRaumSvgLive(ri) {
    if (!_nzData || !_nzData.raeume[ri]) return;
    var pts = _nzData.raeume[ri].region_px || [];
    if (pts.length < 3) return;
    var d = pts.map(function (p) { return p[0] + ',' + p[1]; }).join(' ');
    var poly = _nzQ('polygon[data-rpoly="' + ri + '"]');
    if (poly) poly.setAttribute('points', d);
    var cx = 0, cy = 0;
    pts.forEach(function (v, vi) {
      cx += v[0]; cy += v[1];
      var h = _nzQ('circle[data-rv="' + ri + ':' + vi + '"]');
      if (h) { h.setAttribute('cx', v[0]); h.setAttribute('cy', v[1]); }
      var vn = pts[(vi + 1) % pts.length];
      var a = _nzQ('circle[data-radd="' + ri + ':' + vi + '"]');
      if (a) { a.setAttribute('cx', (v[0] + vn[0]) / 2);
               a.setAttribute('cy', (v[1] + vn[1]) / 2); }
    });
    var mv = _nzQ('circle[data-rmove="' + ri + '"]');
    if (mv) { mv.setAttribute('cx', cx / pts.length);
              mv.setAttribute('cy', cy / pts.length); }
  }
  // Messung mid direkt im SVG nachziehen (Form + Vertex-Griffe).
  function _mwSvgLive(mid) {
    var m = (_mwListe || []).filter(function (x) { return x.id === mid; })[0];
    if (!m || !m.geometrie) return;
    var pts = (m.geometrie.punkte || []).map(_mwPtZuPx);
    if (!pts.length) return;
    var d = pts.map(function (p) { return p[0] + ',' + p[1]; }).join(' ');
    var el = _nzQ('[data-mid="' + mid + '"]');
    if (el && el.tagName !== 'g') el.setAttribute('points', d);
    pts.forEach(function (q, vi) {
      var h = _nzQ('circle[data-mv="' + mid + ':' + vi + '"]');
      if (h) { h.setAttribute('cx', q[0]); h.setAttribute('cy', q[1]); }
    });
    var cx = 0, cy = 0;
    pts.forEach(function (q) { cx += q[0]; cy += q[1]; });
    var mv = _nzQ('circle[data-mmove="' + mid + '"]');
    if (mv) { mv.setAttribute('cx', cx / pts.length);
              mv.setAttribute('cy', cy / pts.length); }
  }

  // ── PUNKT-BEARBEITUNG: Rechtsklick-Menü + Auswahl/Entf ───────────────
  // Nutzer-Wunsch 2026-08-23: „einzelne Punkte entfernen — auswählen und
  // entfernen, oder Rechtsklick und ein Menü geht auf". Beides, weil beide
  // Wege im Zeichenprogramm-Alltag vorkommen. Der Doppelklick auf einen
  // Raum-Eckpunkt bleibt zusätzlich erhalten.
  var _nzPktSel = null;   // {art:'raum'|'mess', ri|mid, vi} — gewählter Punkt

  function _nzMenuZu() {
    var m = document.getElementById('nz-ctx');
    if (m) m.remove();
  }
  // Öffnet das Kontextmenü an der Bildschirmposition (x,y) mit [{text, fn}].
  function _nzMenu(x, y, eintraege) {
    _nzMenuZu();
    if (!eintraege.length) return;
    var m = document.createElement('div');
    m.id = 'nz-ctx';
    m.className = 'nz-ctx';
    eintraege.forEach(function (e) {
      var b = document.createElement('button');
      b.type = 'button';
      b.className = 'nz-ctx-item' + (e.warn ? ' nz-ctx-warn' : '');
      b.textContent = e.text;
      b.addEventListener('click', function (ev) {
        ev.stopPropagation(); _nzMenuZu(); e.fn();
      });
      m.appendChild(b);
    });
    document.body.appendChild(m);
    // im Fenster halten
    var r = m.getBoundingClientRect();
    m.style.left = Math.min(x, window.innerWidth - r.width - 8) + 'px';
    m.style.top = Math.min(y, window.innerHeight - r.height - 8) + 'px';
    setTimeout(function () {
      window.addEventListener('click', _nzMenuZu, { once: true });
      window.addEventListener('contextmenu', _nzMenuZu, { once: true });
    }, 0);
  }

  // Punkt aus einem RAUM-Umriss entfernen (mind. 3 müssen bleiben).
  function _nzRaumPunktWeg(ri, vi) {
    var reg = _nzData && _nzData.raeume[ri] && _nzData.raeume[ri].region_px;
    if (!reg) return;
    if (reg.length <= 3) {
      _mwHinweis('Ein Raum braucht mindestens 3 Eckpunkte.', true);
      return;
    }
    reg.splice(vi, 1);
    _nzPktSel = null;
    _nzRaumMarkEdited(ri);   // speichert entprellt mit
    _nzPaint();
  }
  // Punkt aus einer MESSUNG entfernen — der Server rechnet Wert+Formel neu.
  function _nzMessPunktWeg(mid, vi) {
    var m = (_mwListe || []).filter(function (x) { return x.id === mid; })[0];
    if (!m || !m.geometrie) return;
    var pts = m.geometrie.punkte || [];
    var min = (m.geometrie.form === 'polylinie') ? 2 : 3;
    if (pts.length <= min) {
      _mwHinweis('Diese Messung braucht mindestens ' + min + ' Punkte — '
                 + 'zum Entfernen die ganze Messung löschen.', true);
      return;
    }
    pts.splice(vi, 1);
    _nzPktSel = null;
    fetch('/api/messung', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ projekt_id: window.projectId, id: m.id, typ: m.typ,
        geometrie: m.geometrie, ptm: +((_nzData.meta || {}).ptm) || 0 })
    }).then(function (r) { return r.json(); }).then(function (d) {
      if (d && d.ok && d.messung) {
        for (var i = 0; i < _mwListe.length; i++) {
          if (_mwListe[i].id === d.messung.id) _mwListe[i] = d.messung;
        }
      }
      _nzPaint();
    }).catch(function () { _nzPaint(); });
  }
  // Der gewählte Punkt (Entf-Taste) — egal ob Raum oder Messung.
  function _nzPunktSelWeg() {
    if (!_nzPktSel) return false;
    if (_nzPktSel.art === 'raum') _nzRaumPunktWeg(_nzPktSel.ri, _nzPktSel.vi);
    else _nzMessPunktWeg(_nzPktSel.mid, _nzPktSel.vi);
    return true;
  }

  var _nzRaumSaveT = null;
  function _nzRaumMarkEdited(ri) {
    var r = _nzData.raeume[ri]; if (!r) return;
    r._edited = true;
    r._f_edit = Math.round(_nzPolyFlaeche(r.region_px) * 100) / 100;
    r._u_edit = Math.round(_nzPolyUmfang(r.region_px) * 100) / 100;
    _nzRaumLiveReadout(ri);
    // JEDER abgeschlossene Zug speichert (entprellt) — die Handarbeit darf
    // keinen "Übernehmen"-Klick brauchen, um den Reload zu überleben.
    clearTimeout(_nzRaumSaveT);
    _nzRaumSaveT = setTimeout(function () { _nzSave(null); }, 800);
  }
  // Live-Anzeige (Name · Fläche · Umfang) des bearbeiteten Raums im Readout-Feld.
  function _nzRaumLiveReadout(ri) {
    var out = document.getElementById('nz-raum-out'); if (!out) return;
    var r = _nzData.raeume[ri]; if (!r) return;
    var f = _nzPolyFlaeche(r.region_px), u = _nzPolyUmfang(r.region_px);
    var f0 = r.f_m2;
    out.innerHTML = '<strong>' + esc(r.name || 'Raum') + '</strong> — Fläche <strong style="color:#0369a1">' +
      fmtNum(Math.round(f * 100) / 100) + ' m²</strong>' +
      (f0 ? ' <span style="color:#6b7280">(Plan: ' + fmtNum(f0) + ')</span>' : '') +
      ' · Umfang <strong>' + fmtNum(Math.round(u * 100) / 100) + ' m</strong>' +
      ' &nbsp;<button type="button" class="nz-btn" style="padding:.1rem .5rem" onclick="_nzRaumUebernehmen()">✓ Fläche &amp; Umfang übernehmen</button>' +
      (r.region_px.length > 3 ? ' <span style="color:#6b7280;font-size:.78rem">· Doppelklick auf einen Punkt = löschen · kleine Kreise auf den Kanten = Punkt einfügen</span>' : '');
  }
  // VERSCHIEBEN-START: Ausgangslage merken + die dem Griffpunkt nächste Ecke
  // als FANG-ANKER wählen. Beim Ziehen rastet diese Ecke auf die erkannten
  // Wandlinien/Ecken ein (sofern 🧲 Fangen an ist) — die ganze Fläche folgt.
  function _nzRMoveStart(ri, p0) {
    var reg = _nzData.raeume[ri].region_px;
    var ank = 0, bd = Infinity;
    reg.forEach(function (v, vi) {
      var d = (v[0] - p0[0]) * (v[0] - p0[0]) + (v[1] - p0[1]) * (v[1] - p0[1]);
      if (d < bd) { bd = d; ank = vi; }
    });
    _nzRMove = { ri: ri, start: p0, ank: ank,
                 orig: reg.map(function (v) { return [v[0], v[1]]; }) };
  }
  // Verschiebe-Delta mit Wand-Fang: die Anker-Ecke wird probehalber bewegt
  // und durch _mwSnapPunkt gerastet; die Korrektur gilt für alle Punkte.
  function _nzRMoveDelta(mv, p) {
    var dx = p[0] - mv.start[0], dy = p[1] - mv.start[1];
    var a = mv.orig[mv.ank];
    var roh = [a[0] + dx, a[1] + dy];
    var ras = _mwSnapPunkt(roh);   // respektiert den 🧲-Schalter selbst
    return [dx + (ras[0] - roh[0]), dy + (ras[1] - roh[1])];
  }
  // Übernahme: die editierte Fläche/Umfang des gewählten Raums als Override in die
  // Massenrechnung geben (per Raumname+Geschoss) + am Plan speichern.
  window._nzRaumUebernehmen = function () {
    if (_nzRaumSel < 0 || !_nzData) return;
    var r = _nzData.raeume[_nzRaumSel]; if (!r) return;
    var f = Math.round(_nzPolyFlaeche(r.region_px) * 100) / 100;
    var u = Math.round(_nzPolyUmfang(r.region_px) * 100) / 100;
    if (!f) { alert('Dieser Plan ist nicht kalibriert — die Fläche lässt sich nicht in m² umrechnen.'); return; }
    var ov = _filterState.materialliste_override || {};
    ov.raum_flaechen = ov.raum_flaechen || {};
    ov.raum_flaechen[_nrmRaum(r.name || '')] = { name: r.name, f_m2: f, umfang_m: u,
      geschoss: r.geschoss || null };
    _filterState.materialliste_override = ov;
    refreshProjektMassen();
    _nzSave(null);   // Override-Zustand (inkl. raum_flaechen) am Plan speichern
    var out = document.getElementById('nz-raum-out');
    if (out) out.innerHTML = '<strong style="color:#166534">✓ ' + esc(r.name || 'Raum') +
      ': Fläche ' + fmtNum(f) + ' m² / Umfang ' + fmtNum(u) + ' m übernommen — Mengen neu gerechnet.</strong>';
  };

  // Bild-px → Meter über die Plan-Kalibrierung (scale·ptm). Kern des Mess-
  // Werkzeugs: wo die Auto-Erkennung unsicher ist, misst der Polier selbst
  // byte-exakt am Maßstab (wie HasenbeinPlan — nur dass der Plan schon
  // kalibriert ist). laenge in px → m; Polygon-Fläche via Shoelace → m².
  function _nzPxProM() {
    var m = _nzData && _nzData.meta || {};
    // MANUELLE Maßstab-Kalibrierung (Scans ohne Maßketten): der Nutzer hat zwei
    // Punkte einer bekannten Länge geklickt → px/m direkt gesetzt. Höchste
    // Priorität, macht JEDEN Plan metrisch (Messen/Wandlängen/Raumflächen).
    if (m.px_pro_m_manuell > 0) return m.px_pro_m_manuell;
    var s = +m.scale, p = +m.ptm;
    // Beide müssen echte Kalibrierwerte (>0) sein. Fehlt einer — z.B. bei einem
    // nicht kalibrierten Dach-/Schnitt-Plan-Tab — ist die Strecke NICHT in Meter
    // umrechenbar. Dann 0 (falsy) zurückgeben statt still px==m (das alte "|| 1")
    // anzunehmen, was aus 500 px fälschlich "500 m" gemacht hätte.
    if (!(s > 0) || !(p > 0)) return 0;
    return s * p;   // px pro Meter
  }
  var _nzCalibMode = false;   // Maßstab-Kalibrierung: 2 Punkte einer bekannten Länge
  // Pixel-Distanz der ersten beiden Mess-Punkte (für die Kalibrierung).
  function _nzMessPxDist() {
    if (_nzMeasPts.length < 2) return 0;
    var a = _nzMeasPts[0], b = _nzMeasPts[1];
    return Math.sqrt((b[0] - a[0]) * (b[0] - a[0]) + (b[1] - a[1]) * (b[1] - a[1]));
  }
  // Kalibrier-Modus starten: Messwerkzeug in den 2-Punkt-Kalibriermodus schalten.
  window._nzKalibrierenStart = function () {
    var sec = _wfZuPlan();
    if (sec) sec.scrollIntoView({ behavior: 'smooth', block: 'start' });
    _nzCalibMode = true; _nzMeasMode = true; _nzAddMode = false; _nzRaumEditMode = false;
    _nzMeasPts = []; _nzSel = null; _nzPaint();
  };
  // Maßstab aus 2 Punkten + eingegebener Länge setzen → px/m; persistiert.
  window._nzKalibrierenSetzen = function () {
    var inp = document.getElementById('nz-calib-m');
    var meters = inp ? parseFloat(inp.value) : NaN;
    var pxd = _nzMessPxDist();
    if (!(meters > 0) || !(pxd > 0)) { alert('Bitte eine gültige Länge in Metern eingeben.'); return; }
    var ppm = pxd / meters;
    _nzData.meta = _nzData.meta || {};
    _nzData.meta.px_pro_m_manuell = ppm;
    // Raum-Flächen/Umfänge, Wandlängen, Snapping neu ableiten lassen
    _nzData.raeume && _nzData.raeume.forEach(function (r) {
      r._cleaned = r._snapped = r._synthTried = false;
      if (r._synthetic) { r.region_px = null; r._synthetic = false; }
    });
    _nzCleanRegionen(); _nzSynthRegionen(); _nzSnapRegionen();
    _nzCalibMode = false; _nzMeasMode = false; _nzMeasPts = [];
    _nzPaint();
    _nzSave(null);   // voller Korrektur-Zustand inkl. Maßstab (aus _nzData.meta)
    var out = document.getElementById('nz-mess-out');
    if (out) out.innerHTML = '<strong style="color:#166534">✓ Maßstab gesetzt: ' +
      fmtNum(Math.round(ppm)) + ' px/m — der Plan ist jetzt metrisch (Messen, Wandlängen, Raumflächen aktiv).</strong>';
  };
  function _nzKalibriert() { return _nzPxProM() > 0; }
  function _nzMessStrecke() {
    var k = _nzPxProM(), L = 0;
    for (var i = 1; i < _nzMeasPts.length; i++) {
      var a = _nzMeasPts[i - 1], b = _nzMeasPts[i];
      L += Math.sqrt((b[0] - a[0]) * (b[0] - a[0]) + (b[1] - a[1]) * (b[1] - a[1]));
    }
    return L / k;
  }
  function _nzMessFlaeche() {
    if (_nzMeasPts.length < 3) return 0;
    var k = _nzPxProM(), A = 0, n = _nzMeasPts.length;
    for (var i = 0; i < n; i++) {
      var a = _nzMeasPts[i], b = _nzMeasPts[(i + 1) % n];
      A += a[0] * b[1] - b[0] * a[1];
    }
    return Math.abs(A) / 2 / (k * k);
  }
  function _nzMessUmfang() {   // GESCHLOSSENER Umfang (inkl. Schluss-Kante) in m
    if (_nzMeasPts.length < 3) return 0;
    var k = _nzPxProM(), U = 0, n = _nzMeasPts.length;
    for (var i = 0; i < n; i++) {
      var a = _nzMeasPts[i], b = _nzMeasPts[(i + 1) % n];
      U += Math.sqrt((b[0] - a[0]) * (b[0] - a[0]) + (b[1] - a[1]) * (b[1] - a[1]));
    }
    return U / k;
  }
  // Gemessenen Gebäude-Umfang als Außenumfang übernehmen → fließt in die
  // Materialliste (Außenwand/Frostschürze/Randabschluss hängen daran). Der
  // Backend-Override markiert 'user-gemessen' (Konfidenz 0,98) und schlägt
  // die Vision-Schätzung. So schließt sich die HasenbeinPlan-Schleife:
  // Messung → Berechnung — für genau die unsicheren Fälle.
  // Proaktiver Weg von der Unsicherheit zur Lösung: wenn der Geo-Kasten den
  // Umfang als verdächtig flaggt, aktiviert dieser CTA direkt den Mess-Modus
  // und scrollt zum Plan — die App sagt WAS unsicher ist UND gibt den Klick-Weg.
  window._nzMessenStart = function () {
    var sec = _wfZuPlan();
    if (sec) sec.scrollIntoView({ behavior: 'smooth', block: 'start' });
    if (_nzWrap && _nzData) {
      _nzMeasMode = true; _nzAddMode = false; _nzMeasPts = []; _nzSel = null;
      _nzPaint();
    }
  };
  window._nzMessUmfangUebernehmen = function () {
    if (!_nzKalibriert()) { alert('Dieser Plan ist nicht auf einen Maßstab kalibriert — die Messung lässt sich nicht in Meter umrechnen. Bitte auf dem kalibrierten Grundriss-Tab messen.'); return; }
    var u = Math.round(_nzMessUmfang() * 100) / 100;
    if (!(u >= 10 && u <= 400)) { alert('Gemessener Umfang ' + u + ' m außerhalb 10–400 m — bitte Gebäude-Außenkante abklicken.'); return; }
    var ov = _filterState.baudaten_override || {};
    ov.aussenumfang_m = u;
    _filterState.baudaten_override = ov;
    // Messwert AUCH ins Baudaten-Formularfeld spiegeln (data-bd="aussenumfang_m").
    // Sonst wirft der nächste Baudaten-Apply — der die Overrides aus den Feldern
    // neu baut — den nur in _filterState gehaltenen Messwert wieder weg. Genau
    // das meint das Feld-Label „am Plan messen und hier eintragen".
    var fld = document.querySelector('#filter-baudaten input[data-bd="aussenumfang_m"]');
    if (fld) fld.value = String(u).replace('.', ',');
    refreshProjektMassen();
    var out = document.getElementById('nz-mess-out');
    if (out) out.innerHTML = '<strong style="color:#166534">✓ Außenumfang ' + fmtNum(u) + ' m übernommen — Materialliste neu gerechnet</strong>';
  };

  // Wand nach IDENTITÄT (w.id) finden — NICHT nach Array-Position. Backend-IDs
  // sind 1-basiert/beliebig und nach Löschen/Hinzufügen ≠ Index; ein direkter
  // waende[id]-Zugriff griff die falsche Wand (Auswahl-Panel + Außen/Innen-Toggle).
  function _nzWandById(id) {
    var a = _nzData && _nzData.waende || [];
    for (var i = 0; i < a.length; i++) if (a[i].id === id) return a[i];
    return null;
  }
  function _nzCm(w) {
    if (_nzEdit.thick[w.id] != null) return _nzEdit.thick[w.id];
    if (w.snap_cm != null) return w.snap_cm;
    return _nzLegendlos && _nzMessMap[w.id] != null ? _nzMessMap[w.id] : null;
  }
  function _nzAussenDefault(cm) { return cm === 50 || cm === 38; }  // 20/12 immer innen, 25 default innen
  function _nzIstAussen(w, cm) {
    if (cm === 20 || cm === 12) return false;
    if (cm === 50 || cm === 38) return true;
    if (!w) return false;   // Wand zwischenzeitlich entfernt → nie crashen (Default innen)
    return _nzEdit.aussen[w.id] != null ? _nzEdit.aussen[w.id] : false;  // 25cm: default innen
  }

  function _nzSplit() {
    // Summen je Stärke + außen/innen-Split aus dem KORRIGIERTEN Zustand.
    var o = { 50: 0, 38: 0, 25: 0 }, i = { 25: 0, 20: 0, 12: 0 }, ges = {};
    (_nzData.waende || []).forEach(function (w) {
      if (_nzEdit.removed[w.id]) return;
      var cm = _nzCm(w);
      if (!cm) return;
      if (!_nzLegendlos && [50, 38, 25, 20, 12].indexOf(cm) < 0) return;
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

  // Absolute BYTE-EXAKT gemessene Wandlängen je Stärke (Meter) — die Basis für
  // die genaue HLZ-Menge (Fläche = Länge × Höhe, statt Hülle × Anteil%). Diese
  // Werte belegen die editierbare Meter-Tabelle vor; der Polier korrigiert sie.
  function _nzLaengen() {
    var s = _nzSplit();
    var r1 = function (x) { return Math.round((x || 0) * 10) / 10; };
    return {
      aussen: { 50: r1(s.o[50]), 38: r1(s.o[38]), 25: r1(s.o[25]) },
      innen: { 25: r1(s.i[25]), 20: r1(s.i[20]), 12: r1(s.i[12]) }
    };
  }

  // BEWEIS-STATUS: „wie viele Räume sind am Plan belegt — und wie gut?"
  // Trennt ehrlich nach QUELLE des Umrisses, statt eine Gesamtzahl zu zeigen:
  // ein flächenrichtiges Rechteck an geschätzter Stelle ist NICHT dasselbe wie
  // ein Umriss, der echten Wandlinien folgt. Klick zeigt den Raum im Plan.
  function _nzBeweisStatus(d) {
    var rs = (d && d.raeume) || [];
    if (!rs.length) return '';
    var mitU = rs.filter(function (r) { return (r.region_px || []).length >= 3; });
    if (!mitU.length) return '';
    var geschaetzt = mitU.filter(function (r) {
      return (r.region_quelle || '').indexOf('geschätzt') >= 0 ||
             r.lage_unbestimmt === true;
    });
    var ohne = rs.length - mitU.length;
    var verlaesslich = mitU.length - geschaetzt.length;
    var alles = (verlaesslich === rs.length);
    var farbe = alles ? '#166534' : (verlaesslich >= 0.8 * rs.length ? '#0369a1' : '#b45309');
    var h = '<div class="nz-beweis" style="margin:.4rem 0 .2rem;padding:.45rem .7rem;' +
      'border-left:3px solid ' + farbe + ';background:rgba(0,0,0,.025);font-size:.84rem">' +
      '<strong style="color:' + farbe + '">' + verlaesslich + ' von ' + rs.length +
      ' Räumen am Plan belegt</strong>' +
      '<span style="color:#6c757d"> — Umriss folgt echten Wandlinien</span>';
    if (geschaetzt.length) {
      h += '<br><span style="color:#b45309">' + geschaetzt.length +
        ' mit UNBESTIMMTER Lage</span><span style="color:#6c757d"> — die Fläche ' +
        'stimmt (aus dem Raumstempel), die Position ist nur ein Anhaltspunkt ' +
        'und bitte mit ✏️ zurechtzuziehen: </span>' +
        geschaetzt.slice(0, 6).map(function (r) {
          var _js = esc(String(r.name || '').replace(/\\/g, '\\\\')
            .replace(/'/g, "\\'"));
          return '<a href="#" onclick="nzHighlightRaum(\'' + _js + '\');return false" ' +
            'style="color:#b45309;text-decoration:underline">' + esc(r.name || 'Raum') + '</a>';
        }).join(', ');
    }
    if (ohne) {
      h += '<br><span style="color:#6c757d">' + ohne +
        ' ohne Umriss (kein Flächen-Stempel im Plan)</span>';
    }
    return h + '</div>';
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
      var cm = _nzCm(w), rm = !!_nzEdit.removed[w.id],
        sel = (_nzSel === w.id || _nzSelSet.indexOf(w.id) >= 0);
      var col = rm ? '#b8c0cc' : (cm ? _nzFarbe(cm) : '#888');
      var unsicher = !cm || (w.hatch_dichte != null && w.hatch_dichte < 1.5);
      var p = w.px;
      // SCHARFE WAND-DARSTELLUNG (Sichtbefund 2026-08-18: "Wand-Erkennung
      // schaut nicht gut aus" — breite halbtransparente Linien wirkten
      // verschmiert): Wandkoerper als leichte Fuellung + duenne KANTEN in
      // Vollfarbe. Die Kanten zeichnen die Wand, nicht der Nebel.
      var _sw = Math.max(2, w.staerke_px);
      var _dx = p[2] - p[0], _dy = p[3] - p[1];
      var _L = Math.hypot(_dx, _dy) || 1;
      var _nx = -_dy / _L * _sw / 2, _ny = _dx / _L * _sw / 2;
      lines += '<polygon points="' +
        (p[0] + _nx) + ',' + (p[1] + _ny) + ' ' + (p[2] + _nx) + ',' + (p[3] + _ny) + ' ' +
        (p[2] - _nx) + ',' + (p[3] - _ny) + ' ' + (p[0] - _nx) + ',' + (p[1] - _ny) +
        '" fill="' + col + '" fill-opacity="' + (rm ? 0.08 : 0.16) +
        '" stroke="' + col + '" stroke-width="1.4"' +
        ' stroke-opacity="' + (rm ? 0.35 : 0.95) + '"' +
        ((unsicher || rm) ? ' stroke-dasharray="6 5"' : '') +
        ' pointer-events="none"/>';
      lines += '<line data-wid="' + w.id + '" data-cm="' + (cm || '') + '" x1="' + p[0] + '" y1="' + p[1] + '" x2="' + p[2] + '" y2="' + p[3] +
        '" stroke="' + col + '" stroke-width="1.2" stroke-linecap="round"' +
        ' stroke-opacity="' + (rm ? 0.3 : 0.55) + '"' + (sel ? ' style="filter:drop-shadow(0 0 4px #000)"' : '') +
        ' cursor="pointer"><title>' +
        (cm ? _nzTLabel(cm) : '~' + w.dicke_cm + ' cm') + ' · ' + w.laenge_m + ' m' +
        (w.mass_exakt ? ' (= Maßzahl lt. Plan)' : '') + ' — klicken zum Korrigieren</title></line>' +
        // FETTE KLICKZONE (unsichtbar, oben drauf): eine 2-px-Linie ist mit
        // der Maus kaum zu treffen — Zeichentool-Standard ist eine breite
        // unsichtbare Trefferfläche über der sichtbaren Linie.
        '<line data-wid="' + w.id + '" x1="' + p[0] + '" y1="' + p[1] + '" x2="' + p[2] + '" y2="' + p[3] +
        '" stroke="rgba(0,0,0,0)" stroke-width="' + Math.max(14, (w.staerke_px || 2) + 8) +
        '" stroke-linecap="round" cursor="pointer" style="pointer-events:stroke"><title>' +
        (cm ? _nzTLabel(cm) : '~' + w.dicke_cm + ' cm') + ' · ' + w.laenge_m + ' m — klicken: auswählen · Shift-Klick: mehrere</title></line>';
      // BEWEIS-RING: markiert die PLAN-MASSZAHL, aus der die Wandlänge byte-exakt
      // gelesen wurde ("diese Zahl im Plan wurde verwendet") — Traceability der
      // Lesung selbst. Dezent (dünner Teal-Ring); pulst mit, wenn die Wand
      // selektiert ist.
      if (w.mass_px && w.mass_exakt && !rm) {
        lines += '<circle data-wring="' + w.id + '" cx="' + w.mass_px[0] + '" cy="' + w.mass_px[1] +
          '" r="' + Math.max(10, (w.staerke_px || 6) * 1.4) + '" fill="none" stroke="#0f766e"' +
          ' stroke-width="' + (sel ? 3 : 1.4) + '" stroke-opacity="' + (sel ? 0.95 : 0.55) + '"' +
          ' pointer-events="none"><title>Verwendete Plan-Maßzahl für Wand ' + w.laenge_m + ' m</title></circle>';
      }
      // Sichtbares Längen-/Stärke-Label auf der Wand (1:1 zum Plan vergleichbar)
      if (!rm && cm && w.laenge_m >= 1.2 && !_nzPraes) {
        var mx = (p[0] + p[2]) / 2, my = (p[1] + p[3]) / 2;
        // GEWERK am Bauteil, wenn der Plan es hergibt. Es kommt aus dem
        // Wand-CODE (AW01/IW03/…) und dessen Aufbau in der Legende — nicht
        // aus der Dicke, die am Korpus kein Material-Signal ist (Angerer
        // 12 cm = Hochlochziegel, WM IW01a 36 cm = Stahlbeton). Wer die
        // Mengen prüft, sieht damit am Plan, welches Gewerk eine Wand trägt.
        var _gwTxt = {mauerwerk: 'Mauerwerk', beton: 'Beton',
                      trockenbau: 'Trockenbau', holz: 'Holzbau'}[w.gewerk] || '';
        var txt = _nzTLabel(cm) + ' · ' + fmtNum(w.laenge_m) + 'm'
          + (_gwTxt ? ' · ' + _gwTxt : '');
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
      // Gezählt wird weiter (die Legende bleibt ehrlich), nur gezeichnet nicht:
      // im Präsentations-Modus verdecken die Marker sonst genau die Umrisse,
      // die gezeigt werden sollen.
      if (_nzPraes) return;
      var mcol = istF ? '#0284c7' : '#b45309', rad = Math.max(9, fs * 0.72);
      // ÖNORM-ABZUG AM PLAN (Traceability): jede Öffnung zeigt direkt, ob sie
      // abgezogen (>4 m² → „−X m²") oder übermessen wird (≤4 m²). Dieselbe
      // Regel wie in den Gewerke-Positionen (B 2204 §5.5.1.3, Default 4,0).
      var abz = '', abzCol = '#63666c';
      // ÖFFNUNG OHNE MASS: bisher stand hier NICHTS — dadurch sah eine
      // ungemessene Öffnung genauso aus wie eine geprüfte, und der Hinweis
      // oben ("22 von 46 ohne Maß") war am Plan nicht auffindbar. Fehlt ein
      // Maß, ist die Abzugsfläche rechnerisch 0; die Menge steht da, nur eben
      // brutto. Das muss AM Bauteil stehen, nicht nur in einem Kasten.
      var unvoll = !(o.breite_m && o.hoehe_m);
      if (unvoll) {
        // Was bekannt ist, wird gezeigt — meist die Höhe. Daraus sieht der
        // Kalkulant sofort, ab welcher Breite die 4-m²-Schwelle überhaupt
        // fällt, und ob Nachmessen sich lohnt.
        abz = o.hoehe_m ? ('H ' + fmtNum(o.hoehe_m) + ' m · Breite fehlt')
          : (o.breite_m ? ('B ' + fmtNum(o.breite_m) + ' m · Höhe fehlt') : 'Maß fehlt');
        abzCol = '#2563eb';   // derselbe Ton wie der Hinweiskasten oben
      } else {
        var om2 = Math.round(o.breite_m * o.hoehe_m * 100) / 100;
        abz = om2 > 4.0 ? ('Abzug −' + fmtNum(om2) + ' m²') : ('übermessen (' + fmtNum(om2) + ' m² ≤ 4)');
        abzCol = om2 > 4.0 ? '#b42318' : '#63666c';
      }
      marker += '<g data-oid="' + o.id + '" cursor="pointer" opacity="' + (rm ? 0.28 : 0.95) + '">' +
        '<circle cx="' + o.px[0] + '" cy="' + o.px[1] + '" r="' + rad + '" fill="' + mcol + '" stroke="' +
        (unvoll ? '#2563eb' : '#fff') + '" stroke-width="' + (unvoll ? 3 : 2) + '"' +
        (unvoll ? ' stroke-dasharray="' + Math.round(rad * 0.5) + ' ' + Math.round(rad * 0.34) + '"' : '') + '/>' +
        '<text x="' + o.px[0] + '" y="' + o.px[1] + '" font-size="' + Math.round(rad * 1.1) + '" text-anchor="middle" dy="' +
        Math.round(rad * 0.38) + '" fill="#fff" style="font-weight:700;pointer-events:none">' + (istF ? 'F' : 'T') + '</text>' +
        (abz && !rm ? '<text x="' + (o.px[0] + rad * 1.35) + '" y="' + o.px[1] + '" font-size="' + Math.round(rad * 0.82) + '" dy="' +
          Math.round(rad * 0.3) + '" fill="' + abzCol + '"' +
          ' stroke="#fff" stroke-width="0.8" paint-order="stroke" style="pointer-events:none">' + abz + '</text>' : '') +
        '<title>' + (istF ? 'Fenster' : 'Tür') +
        (!unvoll ? ' ' + fmtNum(o.breite_m) + '×' + fmtNum(o.hoehe_m) + 'm · ' + abz + ' (ÖNORM B 2204)'
          : ' · ' + abz + ' — ohne vollständiges Maß ist kein ÖNORM-Abzug möglich; Putz, Maler und Mauerwerk rechnen hier mit der vollen Wandfläche') +
        (o.quelle === 'vision' ? ' · KI-Bildlesung (Position ungefähr)' : '') +
        ' — klicken = keine Öffnung</title></g>';
    });
    // RAUM-VERIFIKATION: grün = Geometrie gegen die Plan-Stempel (F+U) BEWIESEN,
    // gelb = prüfen. Der Plan validiert sich selbst.
    var nRaumOk = 0, nRaumF = 0, nRaumWl = 0, raumBadges = '';
    // REKONSTRUIERTE RAUM-REGIONEN als Umriss ÜBER dem Plan (nachvollziehbar:
    // die geometrische Lesart der App — grün deckt sich mit dem Raum, Prüf-Farbe
    // zeigt, wo die Rekonstruktion abweicht). Nur verlässliche, achsparallele
    // Umrisse (offene/zackige Räume werden vom Backend ausgelassen).
    // RAUMANSICHT (Calcora-Stil): jeder rekonstruierte Raum als kräftig gefülltes,
    // eigen-farbiges Polygon mit Name + Fläche — das „es hat den Plan verstanden"-
    // Signal. Umschaltbar (_nzRaumFill); aus = die technische Wand-/Prüf-Ansicht.
    var _rIdx = 0, _rvHandles = '';
    (_nzData.raeume || []).forEach(function (r, _ri) {
      if (!r.region_px || r.region_px.length < 3) return;
      var pts = r.region_px.map(function (p) { return p[0] + ',' + p[1]; }).join(' ');
      // Handles auch bei blosser AUSWAHL (Live-Befund: "Raeume leicht
      // aendern indem man die Ecken zieht") — der Griff-Anfasser aktiviert
      // den Editor beim ersten Zug automatisch.
      var _edit = (_nzRaumEditMode && _nzRaumSel === _ri) ||
                  (!_nzRaumEditMode && _nzRaumInfo === _ri);
      // Im Editier-Modus sind die Polygone anklickbar (Raum wählen).
      // Raeume sind IMMER anklickbar — ein Klick zeigt die Werte. Vorher ging
      // das nur im Bearbeiten-Modus, also musste man erst ein Werkzeug
      // einschalten, um zu sehen, was ein Raum traegt.
      var _pe = 'auto';
      if (_nzRaumFill) {
        var rc = _NZ_RAUMFARBEN[_rIdx % _NZ_RAUMFARBEN.length];
        var rok = r.status === 'verifiziert' || r.rohbau_ok || r.iou_bewiesen;
        var _synth = (r._synthetic || r.region_geschaetzt) && !r._edited;
        // FREIFLÄCHE (Wiese/Spielplatz/Pflaster): am WM-Plan sind das 2153 m²
        // gegenüber 810 m² echter Räume — als normale Raumfarben überzogen sie
        // den halben Plan und ließen die Raumliste unglaubwürdig aussehen.
        // Grau, ohne Füllung, nicht in der Farbrotation: sichtbar für die
        // Nachvollziehbarkeit, aber nicht als Raum ausgegeben.
        var _frei = !!r.aussenanlage;
        if (_frei) { rc = '#94a3b8'; } else { _rIdx++; }
        lines += '<polygon data-rpoly="' + _ri + '" points="' + pts + '" fill="' + rc + '" fill-opacity="' +
          (_frei ? (_nzRaumInfo === _ri ? 0.10 : 0.02)
                 : (_edit ? 0.16 : (_nzRaumInfo === _ri ? 0.22 : (_synth ? 0.10 : 0.09))))
          + '" stroke="' + rc + '" stroke-width="'
          + (_frei ? 1 : (_edit ? 3 : (_nzRaumInfo === _ri ? 2.4 : (_synth ? 1.6 : 1.3)))) + '"' +
          ' stroke-opacity="' + (_frei ? 0.55 : 1) + '"' +
          (_frei ? ' stroke-dasharray="7 5"' : '') +
          ((_frei || (_synth && !_edit)) ? ' stroke-dasharray="9 5"' : '') +
          ' cursor="pointer" pointer-events="' + _pe + '">' +
          '<title>' + esc(r.name || '') + (r.f_m2 ? ' · ' + fmtNum(r.f_m2) + ' m²' : '') +
          (_synth ? ' — geschätzte Startform, bitte am Plan anpassen (✏️ Raum bearbeiten)'
                  : (_nzRaumEditMode ? ' — klicken zum Bearbeiten' : (rok ? ' ✓ geometrisch bestätigt' : ' — prüfen'))) +
          '</title></polygon>';
        if (r.px) {
          var _rl = fs * 0.92;
          labels += '<text x="' + r.px[0] + '" y="' + r.px[1] + '" font-size="' + Math.round(_rl) +
            '" text-anchor="middle" paint-order="stroke" stroke="#fff" stroke-width="' +
            Math.round(_rl / 3) + '" fill="#1f2937" style="font-weight:700;pointer-events:none">' +
            esc((r.name || '').slice(0, 22)) + '</text>';
          var _fnow = _edit ? _nzPolyFlaeche(r.region_px) : r.f_m2;
          if (_fnow) labels += '<text x="' + r.px[0] + '" y="' + (r.px[1] + _rl * 1.15) +
            '" font-size="' + Math.round(_rl * 0.82) + '" text-anchor="middle" paint-order="stroke"' +
            ' stroke="#fff" stroke-width="' + Math.round(_rl / 3.5) + '" fill="' + (_edit ? '#0369a1' : '#374151') + '"' +
            ' style="font-weight:' + (_edit ? 700 : 400) + ';pointer-events:none">' + fmtNum(Math.round(_fnow * 100) / 100) + ' m²</text>';
        }
      } else {
        var rok2 = r.status === 'verifiziert' || r.rohbau_ok || r.iou_bewiesen;
        var rcol = rok2 ? '#16a34a' : (r.status === 'u_daneben' ? '#0d9488' : '#d97706');
        lines += '<polygon data-rpoly="' + _ri + '" points="' + pts + '" fill="' + rcol + '" fill-opacity="0.07"' +
          ' stroke="' + rcol + '" stroke-width="1.4" stroke-opacity="0.45"' +
          ' stroke-dasharray="7 4" cursor="pointer"' +
          ' pointer-events="' + _pe + '"/>';
      }
      // UMFASSUNGS-LAYER: die Raumgrenze farblich je Bauteil — Außenwand
      // rotbraun, Innenwand blau, Tür gelb, offen grau gestrichelt, unbekannt
      // amber gestrichelt. Macht sichtbar, wo der Raum aufhört und WOMIT.
      // Umfassungs-Segmente stammen aus der SERVER-Rekonstruktion — nach einer
      // Hand-Korrektur passen sie nicht mehr zum Umriss und liegen als schiefe
      // Fremdlinien am Plan (Nutzer-Screenshots 2026-08-23). Für editierte
      // Räume deshalb aus, bis der Server sie zur neuen Form neu klassifiziert.
      if (_nzUmfassung && r.umfassung && r.umfassung.segmente && !_edit && !r._edited) {
        var _UMFARB = { aussenwand: '#7c2d12', innenwand: '#2563eb', tuer: '#eab308',
                        offen: '#94a3b8', unbekannt: '#f59e0b' };
        var _UMNAME = { aussenwand: 'Außenwand', innenwand: 'Innenwand', tuer: 'Tür',
                        offen: 'offen / Durchgang', unbekannt: 'ungeprüft' };
        r.umfassung.segmente.forEach(function (s) {
          var _uc = _UMFARB[s.klasse] || '#f59e0b';
          var _ud = (s.klasse === 'offen' || s.klasse === 'unbekannt') ? ' stroke-dasharray="6 4"' : '';
          var _ut = (_UMNAME[s.klasse] || s.klasse) + ' · ' + fmtNum(s.laenge_m) + ' m'
            + (s.dicke_cm ? ' · ' + Math.round(s.dicke_cm) + ' cm' : '')
            + (s.nachbar ? ' → ' + s.nachbar : '');
          lines += '<line x1="' + s.p0[0] + '" y1="' + s.p0[1] + '" x2="' + s.p1[0] +
            '" y2="' + s.p1[1] + '" stroke="' + _uc + '" stroke-width="4.2" stroke-opacity="0.85"' +
            ' stroke-linecap="round"' + _ud + ' pointer-events="none"><title>' + esc(_ut) +
            '</title></line>';
        });
      }
      // GRIFFE des bearbeiteten Raums: Eckpunkte (ziehen) + Kanten-Mittelpunkte
      // (klicken = Punkt einfügen). Zuletzt gezeichnet → liegen ganz oben.
      if (_edit) {
        var rr = Math.max(5, fs * 0.5);
        r.region_px.forEach(function (v, vi) {
          var vn = r.region_px[(vi + 1) % r.region_px.length];
          _rvHandles += '<circle class="nz-radd" data-radd="' + _ri + ':' + vi + '" cx="' +
            ((v[0] + vn[0]) / 2) + '" cy="' + ((v[1] + vn[1]) / 2) + '" r="' + (rr * 0.62) +
            '" fill="#fff" stroke="#0369a1" stroke-width="1.5" cursor="copy" pointer-events="auto">' +
            '<title>Punkt einfügen</title></circle>';
        });
        r.region_px.forEach(function (v, vi) {
          _rvHandles += '<circle class="nz-rv" data-rv="' + _ri + ':' + vi + '" cx="' + v[0] + '" cy="' + v[1] +
            '" r="' + rr + '" fill="#0369a1" stroke="#fff" stroke-width="2" cursor="move" pointer-events="auto">' +
            '<title>Ziehen · Doppelklick = Punkt löschen</title></circle>';
        });
        // ✥-GRIFF: die GANZE Fläche verschieben (mit Wand-Fang an der
        // nächstliegenden Ecke). Zusätzlich zieht auch die Fläche selbst —
        // der Griff macht die Geste sichtbar/auffindbar.
        var _mcx = 0, _mcy = 0;
        r.region_px.forEach(function (v) { _mcx += v[0]; _mcy += v[1]; });
        _mcx /= r.region_px.length; _mcy /= r.region_px.length;
        _rvHandles += '<circle class="nz-rmove" data-rmove="' + _ri + '" cx="' + _mcx +
          '" cy="' + _mcy + '" r="' + (rr * 1.5) + '" fill="#0369a1" fill-opacity="0.92"' +
          ' stroke="#fff" stroke-width="2.5" cursor="move" pointer-events="auto">' +
          '<title>Ganzen Raum verschieben (Fangen: rastet auf Wände ein)</title></circle>' +
          '<text x="' + _mcx + '" y="' + (_mcy + rr * 0.55) + '" text-anchor="middle" font-size="' +
          Math.round(rr * 1.7) + '" fill="#fff" style="pointer-events:none;font-weight:700">✥</text>';
      }
    });
    (_nzData.raeume || []).forEach(function (r) {
      // 4 Stufen — die dritte war das Problem.
      //
      // "voll bestätigt" hiess bisher `status === 'verifiziert'`. Dieser
      // Status wird aber auch vergeben, wenn der Plan GAR KEINEN Umfang
      // stempelt: dann ist nur die FLÄCHE geprüft, die FORM überhaupt nicht.
      // Am AP.01-Polierplan tragen alle 9 Räume u_m = null, trotzdem standen
      // 8 als grün "voll bestätigt" da — während der Umriss des Carports
      // sichtbar über den Sickerschacht lief (Nutzer-Befund, am Bild belegt).
      // Die App weiss es sogar selbst: dieselben Räume tragen
      // region_geschaetzt = true und iou_max_form 0,79 (unter der
      // Beweisschwelle 0,85). Ein grüner Haken auf einer geschätzten Lage ist
      // eine Behauptung, keine Messung.
      //
      // Neu: grün nur, wenn die FORM tatsächlich gegen den Plan geprüft wurde
      // — durch IoU-Beweis, Rohbau-Fluchtrechteck oder einen gestempelten
      // Umfang, der zur Geometrie passt.
      // WELCHER SCHÄTZER? Am byte-exakten Stempel gemessen (48 Räume,
      // 4 echte Pläne, 2026-08-04) — Median des Betragsfehlers:
      //   u_geometrie        4,4 %   → 10 % weichen um >15 % ab
      //   u_geometrie_poly   6,4 %   → 27 %
      //   u_ist             12,8 %   → 46 %
      // Hier stand u_geometrie_poly zuerst. Das ist ausgerechnet der
      // Schätzer, der laut geometrie_umfang() verwinkelte Räume bis +32 %
      // ÜBERschätzt — er verweigerte damit reihenweise berechtigte Haken
      // und meldete Formen als widerlegt, die stimmen. u_geometrie mittelt
      // ihn mit der BBOX-Isoperimetrie und ist am Stempel validiert.
      // NUR ein Wert, der den GEZEICHNETEN Umriss beschreibt, darf ihn
      // anklagen. `u_ist` beschreibt die Watershed-Region — bei einem
      // ERSATZ-Umriss (aus Wandfluchten oder aus F+U konstruiert) ist das
      // eine ganz andere Form. Am Korpus gemessen beruhten 7 von 12 roten
      // Anklagen auf u_ist, und alle 7 standen auf Ersatz-Umrissen. Der
      // Gipfel: Velden „Tiefgarage" wird AUS F UND U konstruiert, sein
      // Umriss gibt den Stempel per Konstruktion wieder — und wurde
      // beschuldigt, ihm um +26 % zu widersprechen. Eine beweisbar falsche
      // Anklage ist schlimmer als gar keine.
      // Fehlt u_geometrie, ist die Form NICHT PRÜFBAR — dann wird nichts
      // behauptet, in keine Richtung.
      var _uSoll = r.u_m, _uIst = (r.u_geometrie != null ? r.u_geometrie
        : (r.u_geometrie_poly != null ? r.u_geometrie_poly : null));
      var formGeprueft = !!(r.iou_bewiesen || r.rohbau_ok ||
        (_uSoll && _uIst != null && Math.abs(_uIst / _uSoll - 1) <= 0.15));
      var geschaetzt = !!r.region_geschaetzt;
      var ok = (r.status === 'verifiziert' || r.rohbau_ok || r.iou_bewiesen) &&
        formGeprueft && !geschaetzt;
      var fOk = !ok && (r.status === 'u_daneben' || r.status === 'verifiziert');
      // WIDERLEGT getrennt zaehlen: der Plan stempelt einen Umfang UND er
      // widerspricht dem Umriss. Das ist keine offene Frage, sondern ein
      // Befund — und er gehoert in die Legende, nicht nur in den Tooltip.
      var _wl = fOk && _uSoll && _uIst != null &&
        Math.abs(_uIst / _uSoll - 1) > 0.15;
      if (ok) nRaumOk++; else if (_wl) { nRaumF++; nRaumWl++; }
      else if (fOk) nRaumF++;
      // Ein Haken auf einer vom Plan widerlegten Form ist die Art
      // Zusage, die der Nutzer am Bildschirm als Fehler erlebt.
      var col = ok ? '#16a34a' : (_wl ? '#dc2626' : (fOk ? '#0d9488' : '#d97706'));
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
      // BEWEIS-EBENE (nachvollziehbar: WIE wurde der Raum bestätigt?) — die
      // gestaffelten monotonen Ebenen der Erkennung, für den Prüfer sichtbar.
      var EBENE = {
        roh: 'Rohbau-Ebene (Wand-Poché + Watershed)',
        fertig: 'Fertig-Ebene (Vorwände/leichte Trennwände als Grenze)',
        schacht: 'Schacht-Glättung (Installations-Buchten geschlossen)',
        boden: 'Boden-Schraffur gefiltert (Fliesen-Textur ≠ Wand)',
        hybrid: 'Hybrid (Fläche aus Rohbau, Umfang aus Fertig-Pass)'
      };
      if (ok && r.ebene && EBENE[r.ebene]) tip += '  ·  Beweis: ' + EBENE[r.ebene];
      // UMRISS AUF WAND — Angabe, kein Urteil. Als Beweisregel ist sie am
      // Korpus widerlegt (80% Präzision: richtige Fläche, falsche Proportion
      // schmiegt sich an Wände sogar besonders gut an). Als Auskunft für den
      // Prüfer ist sie wertvoll: ein Zimmer bei 33% ist verdächtig, ein
      // Parkplatz bei 46% völlig normal — Freiflächen haben keine Wände.
      if (r.umriss_wand != null) {
        tip += '  ·  Umriss folgt zu ' + Math.round(r.umriss_wand * 100) +
          '% gezeichneten Wänden';
      }
      raumBadges += '<g data-raum="' + esc(_nrmRaum(r.name)) + '"><circle cx="' + r.px[0] + '" cy="' + (r.px[1] - fs * 1.6) + '" r="' + (fs * 0.62) + '"' +
        ' fill="' + col + '" stroke="#fff" stroke-width="2"/>' +
        '<text x="' + r.px[0] + '" y="' + (r.px[1] - fs * 1.6) + '" font-size="' + Math.round(fs * 0.75) + '"' +
        ' text-anchor="middle" dy="' + Math.round(fs * 0.26) + '" fill="#fff" style="font-weight:700;pointer-events:none">' +
        (_wl ? '!' : (ok || fOk ? '✓' : '?')) + '</text><title>' + tip + '</title></g>';
      // PRÜF-RÄUME sichtbar am Plan beschriften (nicht nur im Tooltip): erkannte
      // Fläche + Abweichung, damit die zu prüfenden Stellen ohne Hover auffallen.
      if (!ok && r.f_ist != null && r.f_m2) {
        var dpct = Math.round((r.f_ist - r.f_m2) / r.f_m2 * 100);
        // „Form ungeprüft" war zu freundlich, wo der Plan die Form
        // TATSÄCHLICH GEPRÜFT UND VERWORFEN hat: liegt ein U-Stempel vor und
        // widerspricht er dem Umriss, ist die Form nicht offen, sondern
        // widerlegt. Am Korpus betraf das 13 von 46 Umrissen mit U-Stempel
        // (28 %) — sie standen alle unter „ungeprüft". Der Prüfer muss den
        // Unterschied sehen: ungeprüft heißt nachsehen, widerlegt heißt
        // nicht verwenden.
        var uAb = (_uSoll && _uIst != null) ? (_uIst / _uSoll - 1) : null;
        var note = fOk
          ? ((uAb != null && Math.abs(uAb) > 0.15)
              ? ('Form widerlegt: U ' + fmtNum(Math.round(_uIst * 100) / 100)
                 + ' statt ' + fmtNum(_uSoll) + ' m')
              : (geschaetzt ? 'Umriss geschätzt'
                 : (_uIst == null ? 'Form nicht prüfbar' : 'Form ungeprüft')))
          : ('erkannt ' + fmtNum(r.f_ist) + ' (' + (dpct >= 0 ? '+' : '') + dpct + '%)');
        // Der Prüfer sieht sofort, WORAN er den Umriss messen kann: liegt er
        // auf gezeichneten Wänden, ist die Lage belegt (die Proportion nicht
        // — dafür ist die Kennzahl widerlegt). Liegt er im Freien, ist er
        // entweder eine Freifläche oder falsch.
        if (r.umriss_wand != null) {
          note += ' · ' + Math.round(r.umriss_wand * 100) + '% auf Wand';
        }
        if (_nzPraes) note = '';
        if (note) raumBadges += '<text x="' + (r.px[0] + fs * 0.9) + '" y="' + (r.px[1] - fs * 1.6) + '"' +
          ' font-size="' + Math.round(fs * 0.62) + '" dy="' + Math.round(fs * 0.22) + '" fill="' + col +
          '" stroke="#fff" stroke-width="0.7" paint-order="stroke" style="pointer-events:none">' +
          note + '</text>';
      }
    });
    var s = _nzSplit(), ges = s.ges;
    var legend = '';
    if (_nzData.raeume && _nzData.raeume.length) {
      // Die mittlere Stufe heisst jetzt, was sie ist: die FLÄCHE stimmt, die
      // FORM ist ungeprüft. Auf Plänen ohne gestempelten Umfang ist das der
      // Normalfall — und der Kalkulant muss es wissen, bevor er den Umriss
      // für bare Münze nimmt.
      var _nUngeprueft = _nzData.raeume.length - nRaumOk - nRaumF;
      legend += '<span class="nz-leg-item"><span class="nz-sw" style="background:#16a34a;border-radius:50%"></span>' +
        '<strong>' + nRaumOk + '</strong>&nbsp;Form am Plan bewiesen</span>' +
        '<span class="nz-leg-item"><span class="nz-sw" style="background:#0d9488;border-radius:50%"></span>' +
        '<strong>' + (nRaumF - nRaumWl) + '</strong>&nbsp;Fläche stimmt · Form ungeprüft</span>' +
        (nRaumWl > 0 ? '<span class="nz-leg-item" title="Der Plan stempelt einen Umfang, '
          + 'und er widerspricht dem gezeichneten Umriss um mehr als 15 %. Die Fläche ist '
          + 'byte-exakt richtig, die FORM nachweislich nicht — diesen Umriss nicht als Beweis verwenden.">'
          + '<span class="nz-sw" style="background:#dc2626;border-radius:50%"></span>'
          + '<strong>' + nRaumWl + '</strong>&nbsp;Form vom Plan widerlegt</span>' : '') +
        (_nUngeprueft > 0 ? '<span class="nz-leg-item"><span class="nz-sw" style="background:#d97706;border-radius:50%"></span>' +
          '<strong>' + _nUngeprueft + '</strong>&nbsp;prüfen</span>' : '') +
        '<span class="nz-leg-item">von <strong>' + _nzData.raeume.length + '</strong> Räumen</span>';
    }
    // Umfassungs-Legende: die Raumgrenze je Bauteil (nur wenn aktiv + Daten da)
    if (_nzUmfassung && (_nzData.raeume || []).some(function (r) { return r.umfassung; })) {
      legend += '<span class="nz-leg-item" title="Raumgrenze je Bauteil entlang der exakten Raumkontur — Segment-Tooltip zeigt Länge, Stärke, Nachbarraum">' +
        '<span class="nz-sw" style="background:#7c2d12"></span>Außenwand' +
        ' <span class="nz-sw" style="background:#2563eb"></span>Innenwand' +
        ' <span class="nz-sw" style="background:#eab308"></span>Tür' +
        ' <span class="nz-sw" style="background:#94a3b8"></span>offen' +
        ' <span class="nz-sw" style="background:#f59e0b"></span>ungeprüft</span>';
    }
    Object.keys(ges).map(Number).sort(function (a, b) { return b - a; }).forEach(function (t) {
      if (!ges[t]) return;
      legend += '<span class="nz-leg-item"><span class="nz-sw" style="background:' + _nzFarbe(t) + '"></span>' +
        _nzTLabel(t) + ': <strong>' + fmtNum(ges[t]) + ' m</strong></span>';
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
    // AUTO-ABGLEICH Overlay ↔ Mengen (Prüf-Gate): Σ der als AUSSEN erkannten
    // Overlay-Wände gegen den Außenumfang der Mengen-Welt. Δ ≤ 8% = die zwei
    // unabhängigen Wege bestätigen sich; darüber = rotes Prüfsignal.
    try {
      var _gemU = _lastGemessen && _lastGemessen.aussenumfang_m;
      if (_gemU) {
        var _ovU = 0;
        (_nzData.waende || []).forEach(function (w) {
          if (_nzEdit.removed[w.id]) return;
          var cm = _nzCm(w);
          if (cm != null && _nzIstAussen(w, cm)) _ovU += (w.laenge_m || 0);
        });
        if (_ovU > 3) {
          // RICHTUNG BEACHTEN. Die Overlay-Summe zählt nur die Wände, die als
          // AUSSEN ERKANNT wurden — sie ist eine UNTERGRENZE, keine zweite
          // Messung. Hier stand vorher |Δ| > 8 % → rotes "prüfen!", und das
          // schlug am Referenzplan gegen die einzige byte-exakt belegte Zahl an:
          //   Overlay 32,4 m · Mengen 45,31 m · Grundfläche 128,32 m²
          // Der kleinstmögliche Umfang für 128,32 m² ist der eines Quadrats,
          // 4·√128,32 = 45,31 m. Die Mengen-Zahl trifft dieses physikalische
          // Minimum exakt; die Overlay-Summe liegt mit einem isoperimetrischen
          // Quotienten von 0,65 UNTER dem Kreis — sie kann die Fläche gar nicht
          // umschließen. Die Warnung stand also an der richtigen Zahl.
          //
          // Jetzt wird geprüft, was wirklich ein Fehler wäre:
          var _bp = _lastGemessen && _lastGemessen.bodenplatte_flaeche_m2;
          var _isoMin = _bp > 0 ? 4 * Math.sqrt(_bp) : 0;
          var _zuKlein = _isoMin > 0 && _gemU < _isoMin * 0.98;
          var _ovMehr = _ovU > _gemU * 1.08;
          var _txt, _farbe, _tip;
          if (_zuKlein) {
            _farbe = '#b42318';
            _tip = 'Der Außenumfang der Mengen ist kleiner als der kleinste '
              + 'Umfang, der die Grundfläche überhaupt umschließen kann '
              + '(Quadrat = 4·√Fläche). Eine der beiden Zahlen ist falsch.';
            _txt = 'Außenumfang <strong>' + fmtNum(_gemU) + ' m</strong> zu klein für '
              + fmtNum(Math.round(_bp * 10) / 10) + ' m² Grundfläche (Minimum '
              + fmtNum(Math.round(_isoMin * 10) / 10) + ' m) — prüfen!';
          } else if (_ovMehr) {
            _farbe = '#b42318';
            _tip = 'Im Plan sind MEHR Außenwand-Meter eingezeichnet als die '
              + 'Mengenermittlung annimmt — dann fehlt in den Mengen ein Stück Hülle.';
            _txt = 'Außenwand: im Plan <strong>' + fmtNum(Math.round(_ovU * 10) / 10)
              + ' m</strong> erkannt, Mengen rechnen nur mit <strong>'
              + fmtNum(_gemU) + ' m</strong> — prüfen!';
          } else {
            var _abd = Math.round(_ovU / _gemU * 100);
            _farbe = '#0f766e';
            _tip = 'Die Overlay-Summe zählt nur die als AUSSEN ERKANNTEN '
              + 'Wandstücke und ist damit eine Untergrenze — nicht jede Außenwand '
              + 'ist als durchgehende Linie gezeichnet. Die Mengen-Zahl stammt '
              + 'aus den Maßketten und ist gegen die Grundfläche geprüft '
              + '(Minimum ' + fmtNum(Math.round(_isoMin * 10) / 10) + ' m).';
            _txt = 'Außenwand: <strong>' + fmtNum(Math.round(_ovU * 10) / 10)
              + ' m</strong> von <strong>' + fmtNum(_gemU) + ' m</strong> am Plan '
              + 'eingezeichnet (' + _abd + '%)'
              + (_isoMin > 0 ? ' · Umfang geometrisch plausibel ✓' : '');
          }
          legend += '<span class="nz-leg-item" title="' + _tip + '">' +
            '<span class="nz-sw" style="background:' + _farbe + ';border-radius:50%"></span>' +
            _txt + '</span>';
        }
      }
    } catch (e) { /* Abgleich ist Zusatzinfo — nie das Rendern brechen */ }
    // Auswahl-Toolbar
    var tb = '';
    var _mehrere = _nzSelSet.filter(function (id) { return _nzWandById(id); });
    if (_mehrere.length > 1) {
      // MEHRFACHAUSWAHL: eine Aktion wirkt auf alle gewählten Wände.
      var _summe = 0;
      _mehrere.forEach(function (id) { _summe += (_nzWandById(id).laenge_m || 0); });
      var _alleWeg = _mehrere.every(function (id) { return _nzEdit.removed[id]; });
      tb = '<div class="nz-toolbar">' +
        '<span class="nz-tb-info"><strong>' + _mehrere.length + ' Wände gewählt</strong> · Σ ' +
        fmtNum(Math.round(_summe * 100) / 100) + ' m</span>' +
        '<label class="nz-dick-row">Stärke <input type="number" id="nz-dick-in" min="5" max="60" step="1" ' +
        'inputmode="numeric" placeholder="cm"> cm ' +
        '<button type="button" class="nz-btn" data-act="dick-apply">übernehmen</button></label>' +
        '<span class="nz-tb-hint">rastet auf die nächste Legenden-Stärke (' + _nzStaerkeOptionen().join('/') + ') — ' +
        'die Mengen rechnen in diesen Klassen</span>' +
        '<button type="button" class="nz-btn" data-act="rm">' + (_alleWeg ? '↩ alle wiederherstellen' : '✕ keine Wand (alle)') + '</button>' +
        '<button type="button" class="nz-btn" data-act="sel-clear">Auswahl aufheben (Esc)</button>' +
        '</div>';
    } else if (_nzSel != null && _nzWandById(_nzSel)) {
      var w = _nzWandById(_nzSel), cm = _nzCm(w), rm = !!_nzEdit.removed[w.id];
      var btn = function (lab, act, on) {
        return '<button type="button" class="nz-btn' + (on ? ' nz-btn-on' : '') + '" data-act="' + act + '">' + lab + '</button>';
      };
      tb = '<div class="nz-toolbar"><span class="nz-tb-info">Wand: ' + (cm ? _nzTLabel(cm) : '~' + w.dicke_cm + ' cm') + ' · ' +
        fmtNum(w.laenge_m) + ' m</span>' +
        btn(rm ? '↩ wiederherstellen' : '✕ keine Wand', 'rm', rm) +
        '<span class="nz-tb-sep">Stärke:</span>' +
        _nzStaerkeOptionen().map(function (t) { return btn(String(t), 'cm' + t, cm === t); }).join('') +
        '<label class="nz-dick-row"><input type="number" id="nz-dick-in" min="5" max="60" step="1" ' +
        'inputmode="numeric" value="' + (cm || Math.round(w.dicke_cm)) + '"> cm ' +
        '<button type="button" class="nz-btn" data-act="dick-apply">übernehmen</button></label>' +
        (cm === 25 ? '<span class="nz-tb-sep"></span>' + btn(_nzIstAussen(w, 25) ? 'außen' : 'innen', 'ai', false) : '') +
        '</div>';
    }
    // Übernehmen-Bereich: EDITIERBARE Wandlängen-Tabelle (Meter je Stärke).
    // Vorbelegt mit der byte-exakt gemessenen Länge — der Polier korrigiert bei
    // Bedarf (Overlay verpasst z.B. dünne/verdeckte Wände) und rechnet die
    // Mauerwerks-Mengen direkt aus länge×Höhe neu. Das ist der Genauigkeits-
    // Hebel (Mauerwerk −35% → nahe Realität) UND die manuelle Anpassung.
    var apply = '';
    var wl = _nzLaengen();
    var mtot = wl.aussen[50] + wl.aussen[38] + wl.aussen[25] + wl.innen[25] + wl.innen[20] + wl.innen[12];
    var exportierbar = meta.tragfaehig;
    if (mtot > 0) {
      var inp = function (art, cm, v) {
        return '<label class="nz-wl-cell">' + cm + 'cm ' +
          '<input type="number" class="nz-wl" data-art="' + art + '" data-cm="' + cm +
          '" value="' + v + '" min="0" step="0.1" inputmode="decimal"> m</label>';
      };
      apply = '<div class="nz-apply">' +
        '<div class="nz-wl-title">🧱 Mauerwerk — Wandlänge je Stärke ' +
        '<span class="nz-wl-sub">(byte-exakt gemessen · zum Korrigieren einfach ändern)</span></div>' +
        '<div class="nz-wl-row"><span class="nz-wl-lab">Außen</span>' +
        inp('aussen', 50, wl.aussen[50]) + inp('aussen', 38, wl.aussen[38]) + inp('aussen', 25, wl.aussen[25]) + '</div>' +
        '<div class="nz-wl-row"><span class="nz-wl-lab">Innen</span>' +
        inp('innen', 25, wl.innen[25]) + inp('innen', 20, wl.innen[20]) + inp('innen', 12, wl.innen[12]) + '</div>' +
        (exportierbar
          ? '<button type="button" class="btn btn-sm btn-primary" id="nz-apply-len">Mauerwerk aus diesen Wandlängen rechnen</button>'
          : '<span class="nachzeichnen-hint" style="color:#92400e">⚠ Maßstab unsicher — Wandlängen nur als Sichthilfe, nicht übernehmbar.</span>') +
        ' <button type="button" class="btn btn-sm btn-outline" id="nz-reset">Korrektur zurücksetzen</button>' +
        (s.anteile ? '<div class="nz-apply-pct">Abgeleitete Verteilung — Außen: ' +
          '50cm ' + s.anteile.wand_anteil_50cm + '% · 38cm ' + s.anteile.wand_anteil_38cm + '% · 25cm ' + s.anteile.wand_anteil_25cm_aussen + '%' +
          ' | Innen: 25cm ' + s.anteile.wand_anteil_25cm_innen + '% · 20cm ' + s.anteile.wand_anteil_20cm + '% · 12cm ' + s.anteile.wand_anteil_12cm + '%</div>' : '') +
        '</div>';
    }
    // TROCKENBAU-HINWEIS (byte-exakt aus dem Plan-Text, kein Mengen-Eingriff):
    // der Plan kennzeichnet nichttragende Wände als Trockenbau — die App
    // rechnet sie derzeit als Mauerwerk. Das muss der Kalkulant WISSEN,
    // bevor er die LG-08-Mengen übernimmt (LG 39 ist ein anderes Gewerk
    // mit anderen Preisen). Erste Stufe eines echten LG-39-Aufmaßes.
    var tbHinweis = (meta.trockenbau_hinweis
      ? '<div class="nz-tb-hinweis">🧱→🪛 Der Plan kennzeichnet <strong>Trockenbauwände/' +
        'Vorsatzschalen</strong> (byte-exakt gelesen). Nichttragende Innenwände sind ' +
        'hier vermutlich <strong>LG 39 (Trockenbau)</strong>, nicht Mauerwerk — die ' +
        '12er-Wandlängen unten entsprechend zuordnen.</div>' : '');
    // ÖFFNUNGEN OHNE MASS: fehlt ein Maß, ist die Abzugsfläche rechnerisch 0 —
    // die Menge steht da, nur eben brutto. Ohne diesen Hinweis merkt das
    // niemand, weil nichts fehlt und nichts rot ist.
    var oeHinweis = (meta.oeffnungen_hinweis
      ? '<div class="nz-tb-hinweis nz-oe-hinweis">🪟 ' +
        String(meta.oeffnungen_hinweis)
          .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;') +
        // Wegweiser zum Plan: der Kasten nennt eine Anzahl, die Marker zeigen,
        // WELCHE. Ohne diesen Satz sucht der Kalkulant 46 Öffnungen ab.
        ' <strong>Am Plan gestrichelt umrandet</strong> — dort steht die ' +
        'bekannte Höhe, damit Sie die Breite gezielt nachtragen können.' +
        '</div>' : '');
    // SCHNITT-LESUNG: Blätter mit Schnitt/Ansicht lieferten bisher gar nichts.
    // Maßstab und Höhen-Niveaus stehen byte-exakt in den Höhenkoten — und der
    // abgeleitete Maßstab beweist sich selbst. Reine Anzeige, kein Mengen-Eingriff.
    var schHinweis = (meta.schnitt_hinweis
      ? '<div class="nz-tb-hinweis nz-sch-hinweis">📐 ' +
        String(meta.schnitt_hinweis)
          .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;') +
        '</div>' : '');
    var cont = document.getElementById('nachzeichnen-container');
    // ZEICHENTOOL-SHELL (Nutzer-Richtung: "wie eine moderne Zeichensoftware").
    // Drei Zonen: WERKZEUGE links (Modi + Zoom), CANVAS Mitte, EIGENSCHAFTEN
    // rechts (gewählte Wand / gewählter Raum / Ansicht + Korrekturen).
    // WICHTIG für die Wächter und die bestehende Verdrahtung: die Knöpfe
    // behalten ihre data-z/data-act-Attribute und liegen in Containern mit
    // Klasse nz-zoomctl — die Event-Delegation unten bindet unverändert.
    var _railBtn = function (z, on, icon, lab, title) {
      return '<button type="button" class="nz-btn nz-rail-btn' + (on ? ' nz-btn-on' : '') +
        '" data-z="' + z + '"' + (title ? ' title="' + title + '"' : '') + '>' +
        '<span class="nz-rb-ic">' + icon + '</span><span class="nz-rb-lab">' + lab + '</span></button>';
    };
    var _mwBtn = function (t, ic, lab, title) {
      return '<button type="button" class="nz-btn nz-rail-btn nz-mw-btn' +
        (_mwTool === t ? ' nz-btn-on' : '') + '" data-mw="' + t + '" title="' + title + '">' +
        '<span class="nz-rb-ic">' + ic + '</span><span class="nz-rb-lab">' + lab + '</span></button>';
    };
    var rail =
      '<div class="nz-rail-titel">Messen</div>' +
      _mwBtn('flaeche', '⬟', 'Fläche', 'Fläche als Polygon: Punkte klicken, Doppelklick/Enter beendet') +
      _mwBtn('rechteck', '▭', 'Rechteck', 'Rechteck: zwei gegenüberliegende Ecken klicken') +
      _mwBtn('laenge', '📏', 'Länge', 'Länge als Linienzug (lfm): Punkte klicken, Doppelklick beendet') +
      _mwBtn('stueck', '•', 'Stück', 'Stück zählen: je Klick ein Stück') +
      _mwBtn('abzug', '⊖', 'Abzug', 'Abzugsfläche (wird von der Menge abgezogen)') +
      _mwBtn('volumen', '◫', 'Volumen', 'Volumen: Fläche zeichnen, dann Höhe eingeben (m³)') +
      _mwBtn('treppe', '𝍖', 'Treppe', 'Treppe: Grundriss zeichnen, dann Geschosshöhe — rechnet Stiegenuntersicht + Betonvolumen') +
      _mwBtn('dach', '⛰', 'Dach', 'Dachfläche: Grundriss zeichnen, dann Neigung in Grad — rechnet die wahre (schräge) Fläche') +
      _mwBtn('wandflaeche', '▤', 'Wand', 'Wand-/Fassadenfläche: Linie an der Wand entlang, dann Höhe — Länge × Höhe in m²') +
      '<button type="button" class="nz-btn nz-rail-btn' + (_mwSnap ? ' nz-btn-on' : '') +
      '" data-mw="snap" title="Auf erkannte Wandlinien und Ecken einrasten — trifft die Ecke, ohne zu zielen">' +
      '<span class="nz-rb-ic">🧲</span><span class="nz-rb-lab">Fangen</span></button>' +
      '<span class="nz-rail-sep"></span>' +
      '<div class="nz-rail-titel">Ebenen</div>' +
      ['waende:▬:Wände', 'oeff:◧:Öffn.', 'raeume:⬚:Räume', 'mess:M:Maße']
        .map(function (d) {
          var t = d.split(':');
          return '<button type="button" class="nz-btn nz-rail-btn' +
            (_nzLay[t[0]] ? ' nz-btn-on' : '') + '" data-lay="' + t[0] +
            '" title="KI-Ebene „' + t[2] + '" ein-/ausblenden">' +
            '<span class="nz-rb-ic">' + t[1] + '</span>' +
            '<span class="nz-rb-lab">' + t[2] + '</span></button>';
        }).join('') +
      '<span class="nz-rail-sep"></span>' +
      '<div class="nz-rail-titel">Bearbeiten</div>' +
      _railBtn('raumedit', _nzRaumEditMode, '✏️', 'Raum', 'Raum-Eckpunkte ziehen/hinzufügen/löschen — Fläche &amp; Umfang rechnen live neu') +
      _railBtn('add', _nzAddMode, '➕', 'Wand', 'Wand zeichnen: Linie über die Wand ziehen') +
      _railBtn('calib', _nzCalibMode, '📐', 'Maßstab' + (_nzKalibriert() ? '' : ' ⚠'), 'Maßstab setzen: 2 Punkte einer bekannten Länge klicken, Meter eingeben') +
      '<span class="nz-rail-sep"></span>' +
      _railBtn('in', false, '＋', 'Zoom', '') +
      _railBtn('out', false, '－', 'Zoom', '') +
      _railBtn('reset', false, '🔄', 'Ansicht', 'Ansicht zurücksetzen') +
      _railBtn('full', _nzFull, '⛶', _nzFull ? 'schließen' : 'Vollbild', 'Plan im Vollbild (Esc = schließen)');
    var ansicht =
      '<button type="button" class="nz-btn' + (_nzRaumFill ? ' nz-btn-on' : '') + '" data-z="raumfill" title="Räume kräftig einfärben ↔ technische Prüfansicht">🎨 Räume</button>' +
      '<button type="button" class="nz-btn' + (_nzPraes ? ' nz-btn-on' : '') + '" data-z="praes" title="Ruhige Ansicht zum Vorzeigen: nur Raum-Umrisse, Namen und Flächen — ohne Wand-Beschriftung, Öffnungs-Marker und Prüf-Notizen">🎬 Präsentation</button>' +
      '<button type="button" class="nz-btn' + (_nzUmfassung ? ' nz-btn-on' : '') + '" data-z="umf" title="Raumgrenzen nach Bauteil färben: Außenwand rotbraun · Innenwand blau · Tür gelb · offen grau">🧱 Umfassung</button>';
    // MESSUNGS-PANEL: die gewaehlte Messung mit ihrer FORMEL. Die Formel ist
    // der Grund, warum ein Polier der Zahl glaubt — sie steht deshalb hier
    // und im Protokoll, nicht nur in der Datenbank.
    var mwPanel = '';
    if (_mwPending) {
      var _pdef = { dach: ['Dachneigung in Grad', '25'],
                    wandflaeche: ['Wandhöhe in m', '2,75'],
                    treppe: ['Geschosshöhe in m', '2,75'],
                    volumen: ['Höhe/Stärke in m', '0,20'] }[_mwPending.typ];
      mwPanel += '<div class="nz-side-sec nz-side-akt"><div class="nz-side-h">' +
        _MW_NAME[_mwPending.typ] + ' — noch eine Angabe</div>' +
        '<label class="mw-meta" for="mw-hoehe-in">' + _pdef[0] + '</label>' +
        '<div class="mw-hoehe-row"><input id="mw-hoehe-in" inputmode="decimal" value="' + _pdef[1] + '">' +
        '<button type="button" class="nz-btn nz-btn-ok" id="mw-hoehe-ok">✓ Übernehmen</button></div>' +
        '<button type="button" class="nz-btn" id="mw-hoehe-abbr">Abbrechen</button></div>';
    }
    var _mSel = (_mwListe || []).filter(function (x) { return x.id === _mwSel; })[0];
    if (_mSel) {
      mwPanel = '<div class="nz-side-sec nz-side-akt"><div class="nz-side-h">Messung M' +
        (_mSel.nummer || '?') + '</div>' +
        '<div class="mw-wert">' + (_mSel.wert != null ? fmtNum(_mSel.wert) : '—') +
        ' <span>' + _nzEinheit(_mSel.einheit) + '</span></div>' +
        (_mSel.formel ? '<div class="mw-formel">' + esc(_mSel.formel) + '</div>' : '') +
        '<div class="mw-meta">' + esc(_MW_NAME[_mSel.typ] || _mSel.typ) +
        (_mSel.quelle === 'ki' ? ' · KI-Vorschlag' :
         (_mSel.quelle === 'ki_bestaetigt' ? ' · KI, bestätigt' : ' · selbst gemessen')) +
        '</div>' +
        (_mSel.bezeichnung ? '<div class="mw-meta">' + esc(_mSel.bezeichnung) + '</div>' : '') +
        (_mSel.status === 'vorschlag'
          ? '<button type="button" class="nz-btn nz-btn-ok" data-mok="' + _mSel.id + '">✓ Vorschlag bestätigen</button>'
          : '') +
        '<button type="button" class="nz-btn" data-mdel="' + _mSel.id + '">✕ Messung löschen</button>' +
        '</div>';
    }
    var mwListe = '';
    if ((_mwListe || []).length) {
      var sum = {};
      _mwListe.forEach(function (m) {
        if (m.status === 'verworfen') return;
        var e = _nzEinheit(m.einheit) || 'm²';
        sum[e] = (sum[e] || 0) + (m.typ === 'abzug' ? -1 : 1) * (+m.wert || 0);
      });
      var _nVor = _mwListe.filter(function (m) { return m.status === 'vorschlag'; }).length;
      mwListe = '<div class="nz-side-sec"><div class="nz-side-h">Messungen (' +
        _mwListe.length + ')</div>' +
        (_nVor ? '<button type="button" class="nz-btn nz-btn-ok" data-mokall="1">✓ Alle ' +
                 _nVor + ' Vorschläge bestätigen</button>' +
                 '<button type="button" class="nz-btn" data-mwegall="1" ' +
                 'title="Alle unbestätigten KI-Vorschläge vom Plan entfernen — bestätigte und eigene Messungen bleiben">' +
                 '✕ Alle Vorschläge verwerfen</button>' : '') +
        '<div class="mw-summe">' +
        Object.keys(sum).map(function (e) {
          return '<span>' + fmtNum(Math.round(sum[e] * 100) / 100) + ' ' + e + '</span>';
        }).join('') + '</div>' +
        '<div class="mw-liste">' + _mwListe.slice(0, 12).map(function (m) {
          return '<button type="button" class="mw-item' + (_mwSel === m.id ? ' mw-on' : '') +
            '" data-mid2="' + m.id + '"><b>M' + (m.nummer || '?') + '</b> ' +
            esc((m.bezeichnung || _MW_NAME[m.typ] || '')) + '<span>' +
            (m.wert != null ? fmtNum(m.wert) + ' ' + _nzEinheit(m.einheit) : '') +
            '</span></button>';
        }).join('') + '</div></div>';
    }
    if (!mwListe && window._projModus === 'manuell') {
      mwListe = '<div class="nz-side-sec"><div class="nz-side-h">Manuell aufmessen</div>' +
        '<p class="mw-meta">Maßstab ' +
        ((_nzData.meta && _nzData.meta.massstab) ? esc(_nzData.meta.massstab) + ' — byte-exakt gelesen' : 'bitte kalibrieren (📐)') +
        '. Miss mit den Werkzeugen links (F Fläche · R Rechteck · L Länge · Shift = rechtwinklig).</p>' +
        '<button type="button" class="nz-btn" data-mki="1" title="Die KI liest den Plan und legt die Räume als Vorschläge auf — jederzeit nachholbar">⚡ KI-Analyse nachholen</button></div>';
    }
    if (!mwListe && (_nzData.raeume || []).length) {
      mwListe = '<div class="nz-side-sec"><div class="nz-side-h">Messungen</div>' +
        '<p class="mw-meta">Noch keine Messungen. Die Erkennung hat ' +
        (_nzData.raeume || []).length + ' Räume gefunden — als Vorschläge übernehmen und nur noch prüfen:</p>' +
        '<button type="button" class="nz-btn nz-btn-ok" data-mvor="1">⚡ Räume als Mess-Vorschläge übernehmen</button></div>';
    }
    // KORREKTUR-KREISLAUF sichtbar machen (Nutzer-Wunsch: "können wir es wieder
    // so machen, dass wir analysieren und ich es dann ausbessere?"). Deine
    // gezogenen Umrisse überleben den Reload und überschreiben dabei die
    // Erkennung — ohne diesen Kasten sieht man nicht, dass man die eigene
    // Handarbeit betrachtet statt eines frischen Ergebnisses.
    var _nKorr = (_nzData.raeume || []).filter(function (r) { return r._edited; }).length;
    var korrBox = '';
    if (_nKorr) {
      korrBox = '<div class="nz-side-sec nz-korr"><div class="nz-side-h">Deine Korrekturen</div>' +
        '<p class="mw-meta"><strong>' + _nKorr + ' von ' + (_nzData.raeume || []).length +
        ' Räumen</strong> hast du selbst gezogen. Sie sind gespeichert und ' +
        'gelten als Vorgabe gegenüber der Erkennung.</p>' +
        '<button type="button" class="nz-btn" data-z="korr-weg" ' +
        'title="Alle selbst gezogenen Umrisse verwerfen und die frische KI-Erkennung zeigen — für eine neue Prüfrunde">' +
        '↺ Alle verwerfen &amp; neu erkennen lassen</button></div>';
    }
    var seite =
      '<div class="nz-side">' + mwPanel + korrBox + mwListe +
      (tb ? '<div class="nz-side-sec nz-side-akt"><div class="nz-side-h">Auswahl</div>' + tb + '</div>' : '') +
      _nzRaumWerteHtml(_nzRaumInfo) +
      '<div class="nz-side-sec nz-zoomctl"><div class="nz-side-h">Ansicht</div><div class="nz-side-flex">' + ansicht + '</div></div>' +
      '<div class="nz-side-sec"><div class="nz-side-h">Status</div><div class="nz-legend">' + legend + '</div></div>' +
      tbHinweis + oeHinweis + schHinweis +
      (apply ? '<details class="nz-side-sec nz-side-details"><summary>🧱 Mauerwerk-Korrektur (Wandlängen)</summary>' + apply + '</details>' : '') +
      '</div>';
    cont.querySelector('.nz-dynamic').innerHTML =
      '<div class="nz-studio">' +
      '<div class="nz-rail nz-zoomctl">' + rail + '</div>' +
      '<div class="nz-main"><div class="nz-zoomctl nz-statusline">' +
      '<span class="nachzeichnen-hint" style="margin:0" id="nz-mess-out">' +
      (_nzAddMode ? '<strong style="color:#1d4ed8">Linie über die Wand ziehen</strong>'
        : (_nzMeasMode ? '<strong style="color:#7c3aed">Punkte klicken: Strecke · ab 3 Punkten auch Fläche</strong>'
          : 'Wand oder Raum anklicken = Eigenschaften rechts · Mausrad = scrollen · Strg+Rad = zoomen · ziehen = verschieben')) + '</span>' +
      // VOLLBILD prominent: der Knopf sass unten in der Werkzeugleiste und
      // wurde nicht gefunden (Nutzer: "den Editor irgendwo zum größer machen").
      '<button type="button" class="nz-btn nz-gross" data-z="full" title="Editor auf den ganzen Bildschirm (Esc schließt)">' +
      (_nzFull ? '⛶ Vollbild schließen' : '⛶ Größer') + '</button></div>' +
      (_nzRaumEditMode ? '<div class="nz-raum-editrow">' +
        '<div class="nz-raum-editbar" id="nz-raum-out">' +
        (_nzRaumSel >= 0 ? '' : '<strong style="color:#0369a1">Klicke einen Raum</strong>, um seine Eckpunkte zu ziehen — Fläche &amp; Umfang rechnen live neu.') +
        '</div>' +
        (_nzRaumSel >= 0 ? '<span class="nz-raum-tools">' +
          '<button type="button" class="nz-btn" data-rtool="rect" title="Umriss durch ein achsparalleles Rechteck ersetzen — Fläche bleibt der byte-exakte Stempel, Seitenverhältnis aus dem bisherigen Umriss. Ecken danach normal ziehbar.">▭ Rechteck</button>' +
          '<button type="button" class="nz-btn" data-rtool="orig" title="Den erkannten Original-Umriss wiederherstellen">↺ Original</button>' +
          '</span>' : '') +
        '</div>' : '') +
      _nzRaumLeiste() +
      '<div class="nz-wrap" style="position:relative;max-width:100%;overflow:hidden;border:1px solid #e2e8f0;border-radius:8px;cursor:' + (_nzAddMode || _nzMeasMode ? 'crosshair' : 'grab') + ';touch-action:none">' +
      '<div class="nz-zoom" style="transform-origin:0 0;position:relative;width:100%">' +
      '<img src="' + _nzData.basis_png_b64 + '" style="display:block;width:100%;height:auto" alt="Plan" draggable="false">' +
      '<svg viewBox="0 0 ' + W + ' ' + H + '" preserveAspectRatio="none" ' +
      'style="position:absolute;top:0;left:0;width:100%;height:100%;pointer-events:none">' +
      '<g style="pointer-events:auto" class="lay-waende">' + lines + '</g>' +
      '<g class="lay-waende">' + labels + '</g>' +
      '<g style="pointer-events:auto" class="lay-oeff">' + marker + '</g>' +
      '<g style="pointer-events:auto" class="lay-raeume">' + raumBadges + '</g>' +
      '<g style="pointer-events:auto" class="lay-raeume">' + _rvHandles + '</g>' +
      '<g style="pointer-events:auto" id="nz-mw" class="lay-mess">' + _mwSvg() + '</g></svg></div>' +
      _mwStatusbar() + '</div>' +
      '</div>' + seite + '</div>';
    _nzWireZoom(cont);
    // Events neu binden
    cont.querySelectorAll('line[data-wid]').forEach(function (ln) {
      ln.addEventListener('click', function (ev) {
        if (_mwTool) return;    // Mess-Werkzeug aktiv: Klick setzt Punkte
        if (_nzMoved) return;   // war ein Pan, kein Klick
        var id = parseInt(ln.getAttribute('data-wid'), 10);
        if (ev.shiftKey && _nzSel != null) {
          if (_nzSelSet.indexOf(_nzSel) < 0) _nzSelSet.push(_nzSel);
          var ix = _nzSelSet.indexOf(id);
          if (ix >= 0) _nzSelSet.splice(ix, 1); else _nzSelSet.push(id);
          _nzSel = _nzSelSet.length ? _nzSelSet[_nzSelSet.length - 1] : null;
        } else {
          _nzSelSet = [id]; _nzSel = id;
        }
        _nzPaint();
      });
    });
    // Esc = Auswahl aufheben (Zeichentool-Konvention) — einmal binden.
    if (!window._nzSelEscBound) {
      window._nzSelEscBound = true;
      window.addEventListener('keydown', function (e) {
        var _tg = e.target && e.target.tagName;
        if (_tg !== 'INPUT' && _tg !== 'TEXTAREA' && _tg !== 'SELECT' &&
            !e.metaKey && !e.ctrlKey && !e.altKey) {
          var _km = { f: 'flaeche', r: 'rechteck', l: 'laenge', s: 'stueck', a: 'abzug', v: 'volumen', t: 'treppe', d: 'dach', w: 'wandflaeche' };
          var _kt = _km[(e.key || '').toLowerCase()];
          if (_kt && _nzData) {
            _mwTool = (_mwTool === _kt) ? null : _kt; _mwPts = [];
            if (_mwTool) { _nzAddMode = false; _nzMeasMode = false; _nzRaumEditMode = false; _nzCalibMode = false; _nzSel = null; }
            _nzPaint(); e.preventDefault(); return;
          }
          if ((e.key || '').toLowerCase() === 'g' && _nzData) {
            _mwSnap = !_mwSnap; _nzPaint(); e.preventDefault(); return;
          }
        }
        // EDITOR-GESTEN (digiplan-Paritaet, docs/MANUELL_MODUS.md):
        if (_mwTool && e.key === 'Backspace' && _mwPts.length) {
          _mwPts.pop(); _nzPaint(); e.preventDefault(); return;
        }
        // ENTF: erst der gewählte PUNKT (feiner), dann die ganze Messung.
        if (!_mwTool && (e.key === 'Delete' || e.key === 'Backspace') && _nzPktSel) {
          if (_nzPunktSelWeg()) { e.preventDefault(); return; }
        }
        if (!_mwTool && e.key === 'Delete' && _mwSel) {
          _mwLoeschen(_mwSel); e.preventDefault(); return;
        }
        if ((e.metaKey || e.ctrlKey) && (e.key || '').toLowerCase() === 'z') {
          // Ctrl+Z: letzte in DIESER Sitzung erzeugte Messung zuruecknehmen
          var _uz = _mwUndo.pop();
          if (_uz) { _mwLoeschen(_uz); e.preventDefault(); }
          return;
        }
        if (_mwTool && (e.key === 'Enter' || e.key === 'Escape')) {
          if (e.key === 'Enter') _mwAbschliessen();
          else { _mwPts = []; _mwTool = null; _nzPaint(); }
          return;
        }
        if (e.key === 'Escape' && !_nzFull && (_nzSel != null || _nzSelSet.length)) {
          _nzSel = null; _nzSelSet = []; _nzPaint();
        }
      });
    }
    // RAUM ANKLICKEN = WERTE SEHEN. Direkt am Element gebunden, genau wie die
    // Waende darueber — der Weg ueber ein Fenster-weites mouseup mit
    // Pan-Zustand traegt nicht zuverlaessig (kein sauberes Ereignis-Paar bei
    // Stift/Touch), und dann passiert beim Antippen eines Zimmers gar nichts.
    var _rwZu = cont.querySelector('#raum-werte .rw-zu');
    if (_rwZu) _rwZu.addEventListener('click', function () {
      _nzRaumInfo = null; _nzPaint();
    });
    cont.querySelectorAll('.nz-rl[data-rl]').forEach(function (b) {
      b.addEventListener('click', function () {
        var ri = parseInt(b.getAttribute('data-rl'), 10);
        if (isNaN(ri)) return;
        _nzRaumInfo = (_nzRaumInfo === ri) ? null : ri;
        _nzPaint();
      });
    });
    cont.querySelectorAll('polygon[data-rpoly]').forEach(function (pg) {
      pg.addEventListener('click', function (ev) {
        // AKTIVES MESS-WERKZEUG: der Klick gehört dem Werkzeug (Punkt setzen),
        // nicht der Raum-Auswahl — durchlassen, NICHT stoppen. Live-Befund
        // 2026-08-23: über erkannten Räumen war Zeichnen sonst unmöglich.
        if (_mwTool) return;
        if (_nzMoved || _nzAddMode || _nzMeasMode) return;
        var ri = parseInt(pg.getAttribute('data-rpoly'), 10);
        if (isNaN(ri)) return;
        if (_nzRaumEditMode) { _nzRaumSel = ri; _nzPaint(); _nzRaumLiveReadout(ri); }
        else {
          _nzRaumInfo = (_nzRaumInfo === ri) ? null : ri;
          _nzPaint();
        }
        ev.stopPropagation();
      });
    });
    cont.querySelectorAll('[data-rtool]').forEach(function (b) {
      b.addEventListener('click', function () {
        if (_nzRaumSel < 0) return;
        if (b.getAttribute('data-rtool') === 'rect') _nzRaumRechteck(_nzRaumSel);
        else _nzRaumOriginal(_nzRaumSel);
      });
    });
    // Öffnungs-Marker anklicken = keine Öffnung (Fehl-Erkennung entfernen)
    cont.querySelectorAll('g[data-oid]').forEach(function (mk) {
      mk.addEventListener('click', function () {
        if (_mwTool || _nzMoved) return;
        var oid = parseInt(mk.getAttribute('data-oid'), 10);
        _nzEdit.oeffRemoved[oid] = !_nzEdit.oeffRemoved[oid];
        _nzPaint(); _nzSave(_nzSplit().anteile);
      });
    });
    cont.querySelectorAll('.nz-btn').forEach(function (b) {
      b.addEventListener('click', function () {
        var act = b.getAttribute('data-act'), id = _nzSel;
        if (!act) return;   // Ansicht-/Modus-Knöpfe (data-z) landen auch hier
        // Aktionen wirken auf die MEHRFACHAUSWAHL, sonst auf die eine Wand.
        var ziele = _nzSelSet.filter(function (x) { return _nzWandById(x); });
        if (!ziele.length && id != null) ziele = [id];
        if (act === 'sel-clear') { _nzSel = null; _nzSelSet = []; }
        else if (act === 'rm') {
          var _weg = !ziele.every(function (x) { return _nzEdit.removed[x]; });
          ziele.forEach(function (x) { _nzEdit.removed[x] = _weg; });
        }
        else if (act === 'ai') _nzEdit.aussen[id] = !_nzIstAussen(_nzWandById(id), 25);
        else if (act === 'dick-apply') {
          var _in = cont.querySelector('#nz-dick-in');
          var _v = _in ? parseFloat(_in.value) : NaN;
          if (!isNaN(_v) && _v > 0) {
            // Auf die nächste Legenden-Stärke einrasten: die Mengen rechnen
            // in diesen Klassen — ein stiller 17-cm-Eimer würde sonst aus
            // der Wandlängen-Tabelle fallen.
            var _opt = _nzStaerkeOptionen();
            var _best = _opt[0];
            _opt.forEach(function (t) { if (Math.abs(t - _v) < Math.abs(_best - _v)) _best = t; });
            ziele.forEach(function (x) { _nzEdit.thick[x] = _best; });
          }
        }
        else if (act.indexOf('cm') === 0) ziele.forEach(function (x) { _nzEdit.thick[x] = parseInt(act.slice(2), 10); });
        _nzPaint();
      });
    });
    var apl = document.getElementById('nz-apply-len');
    if (apl) apl.addEventListener('click', function () {
      // Wandlängen aus den (evtl. korrigierten) Eingabefeldern lesen
      var laengen = { aussen: {}, innen: {} }, manuell = false, gemessen = _nzLaengen();
      cont.querySelectorAll('input.nz-wl').forEach(function (el) {
        var art = el.getAttribute('data-art'), cm = el.getAttribute('data-cm');
        var v = parseFloat(el.value); if (isNaN(v) || v < 0) v = 0;
        laengen[art][cm] = v;
        if (Math.abs(v - (gemessen[art][cm] || 0)) > 0.05) manuell = true;
      });
      _nzUebernehmenLaengen(laengen, manuell);
    });
    var rs = document.getElementById('nz-reset');
    if (rs) rs.addEventListener('click', function () {
      // auch manuell hinzugefügte Wände wieder entfernen
      _nzData.waende = (_nzData.waende || []).filter(function (w) { return !w.manuell; });
      _nzEdit = { removed: {}, thick: {}, aussen: {}, added: [] }; _nzSel = null; _nzSelSet = [];
      _filterState.materialliste_override = _nzStripAnteile(_filterState.materialliste_override);
      _nzPaint(); refreshProjektMassen(); _nzSave(null);
    });
    renderWandAufmass();   // Wand-Aufmaß live mitziehen (jede Korrektur sofort sichtbar)
  }

  // VOLLBILD: die Planansicht füllt den ganzen Bildschirm — der Plan wird viel
  // größer, Zoom/Pan/Editor funktionieren unverändert. Esc oder Button schließt.
  function _nzToggleFull() {
    _nzFull = !_nzFull;
    var sec = document.getElementById('nachzeichnen-section');
    if (sec) sec.classList.toggle('nz-fullscreen', _nzFull);
    document.body.classList.toggle('nz-full-open', _nzFull);
    _nzPaint();
    setTimeout(function () { if (typeof _nzApplyZoom === 'function') _nzApplyZoom(); }, 30);
    if (_nzFull && !window._nzEscBound) {
      window._nzEscBound = true;
      window.addEventListener('keydown', function (e) {
        if (e.key === 'Escape' && _nzFull) _nzToggleFull();
      });
    }
  }

  function _nzApplyZoom() {
    if (!_nzWrap || !_nzData) return;
    var zoom = _nzWrap.querySelector('.nz-zoom'); if (!zoom) return;
    var Wv = _nzWrap.clientWidth, Hv = _nzWrap.clientHeight || (Wv * _nzData.bild_h / _nzData.bild_w), s = _nzZoom.s;
    // ECHTE Inhaltsgröße statt der Annahme "Inhalt = Fenster".
    //
    // Hier steckte ein handfester Fehler: die Schranken waren Wv*(1-s) und
    // Hv*(1-s) — bei s=1 also beide 0, das Verschieben war abgeschaltet.
    // Das Bild wird aber mit width:100% gezeichnet, ist bei einem quadra-
    // tischen Plan also ~1500px hoch, während das Fenster 76vh (~540px)
    // misst. Ergebnis: man sah das obere Drittel und kam nicht weiter —
    // am Angerer-Plan im Browser bestätigt.
    //
    // Richtig ist die Schranke gegen die WIRKLICHE Inhaltsgröße: passt der
    // Inhalt ins Fenster, bleibt es bei 0 (kein Zappeln); ist er größer,
    // darf genau um die Differenz geschoben werden — in jeder Zoomstufe.
    var cw = (zoom.offsetWidth || Wv) * s;
    var ch = (zoom.offsetHeight || Hv) * s;
    // Passt der Inhalt in seiner Achse ins Fenster, wird er ZENTRIERT statt an
    // den linken/oberen Rand geklemmt — seit der Terrassen-Erweiterung ist der
    // Plan höher als breit, und die alte Klammer (x ≤ 0) ließ rechts totes Feld.
    _nzZoom.x = cw < Wv ? (Wv - cw) / 2
                        : Math.min(0, Math.max(Wv - cw, _nzZoom.x));
    _nzZoom.y = ch < Hv ? (Hv - ch) / 2
                        : Math.min(0, Math.max(Hv - ch, _nzZoom.y));
    zoom.style.transform = 'translate(' + _nzZoom.x + 'px,' + _nzZoom.y + 'px) scale(' + s + ')';
    // Scrollbalken-Ersatz: ohne Rückmeldung weiß niemand, dass da noch mehr
    // ist. Ein dünner Streifen am Rand zeigt, welcher Ausschnitt gerade dran
    // ist — und verschwindet, sobald alles ins Fenster passt.
    _nzScrollHinweis(Wv, Hv, cw, ch);
  }

  function _nzScrollHinweis(Wv, Hv, cw, ch) {
    if (!_nzWrap) return;
    var bar = _nzWrap.querySelector('.nz-scrollbar');
    if (ch <= Hv + 1) { if (bar) bar.remove(); return; }
    if (!bar) {
      bar = document.createElement('div');
      bar.className = 'nz-scrollbar';
      _nzWrap.appendChild(bar);
    }
    var anteil = Math.max(0.06, Hv / ch);
    var pos = ch > Hv ? (-_nzZoom.y) / (ch - Hv) : 0;
    bar.style.height = (anteil * 100) + '%';
    bar.style.top = (pos * (1 - anteil) * 100) + '%';
  }

  // GANZEN PLAN INS FENSTER: Startansicht so wählen, dass der Plan komplett
  // sichtbar ist. Vorher startete er bei 100% Breite und war damit höher als
  // das Fenster — der Nutzer sah nur den oberen Teil und hielt das für den
  // ganzen Plan. Läuft NUR einmal je Plan, sonst würde es gegen jeden Zoom
  // des Nutzers arbeiten.
  function _nzFitGanz() {
    if (!_nzWrap) return;
    var zoom = _nzWrap.querySelector('.nz-zoom'); if (!zoom) return;
    var Hv = _nzWrap.clientHeight, ch = zoom.offsetHeight;
    if (!Hv || !ch || ch <= Hv) return;
    _nzZoom.s = Math.max(0.15, Hv / ch);
    // WAAGRECHT ZENTRIEREN: das Bild wird mit width:100% gezeichnet; ein hoher,
    // schmaler Plan (z.B. seit der Terrassen-Erweiterung) wird auf die Höhe
    // heruntergerechnet und stand dann links mit viel totem Rand rechts.
    var Wv = _nzWrap.clientWidth, cw = (zoom.offsetWidth || Wv) * _nzZoom.s;
    _nzZoom.x = cw < Wv ? (Wv - cw) / 2 : 0;
    _nzZoom.y = 0;
    _nzApplyZoom();
  }

  // SCAN-AUTO-ZOOM: bei einem Scan (dichte Multi-View-Tafel) auf die erkannten
  // Räume zoomen, damit sie groß & sauber liegen statt klein über das Blatt
  // verstreut. Bounding-Box aller Raum-Polygone → in den Viewport einpassen.
  function _nzFitToRooms() {
    if (!_nzWrap || !_nzData || !_nzData.raeume) return;
    var minx = 1e9, miny = 1e9, maxx = -1e9, maxy = -1e9, any = false;
    (_nzData.raeume || []).forEach(function (r) {
      (r.region_px || []).forEach(function (p) {
        any = true;
        if (p[0] < minx) minx = p[0]; if (p[0] > maxx) maxx = p[0];
        if (p[1] < miny) miny = p[1]; if (p[1] > maxy) maxy = p[1];
      });
    });
    if (!any || maxx <= minx || maxy <= miny) return;
    var Wv = _nzWrap.clientWidth, Hv = _nzWrap.clientHeight || (Wv * _nzData.bild_h / _nzData.bild_w);
    var f = Wv / _nzData.bild_w;                 // Bild-px → Anzeige-px
    var w = (maxx - minx) * f, h = (maxy - miny) * f;
    var cx = (minx + maxx) / 2 * f, cy = (miny + maxy) / 2 * f;
    var s = Math.min(6, Math.max(1, Math.min(Wv / (w * 1.12), Hv / (h * 1.12))));
    _nzZoom = { s: s, x: Wv / 2 - s * cx, y: Hv / 2 - s * cy };
    _nzApplyZoom();
  }

  function _nzZoomAt(cx, cy, faktor) {
    var s0 = _nzZoom.s, s1 = Math.min(8, Math.max(1, s0 * faktor));
    _nzZoom.x = cx - (cx - _nzZoom.x) * (s1 / s0);
    _nzZoom.y = cy - (cy - _nzZoom.y) * (s1 / s0);
    _nzZoom.s = s1; _nzApplyZoom();
  }

  // Welcher Raum liegt unter diesem Punkt? Rein rechnerisch (Strahlensatz),
  // damit der Treffer nicht davon abhaengt, was gerade oben gezeichnet ist.
  function _nzRaumUnterPunkt(pt) {
    if (!_nzData || !(_nzData.raeume || []).length) return null;
    var tref = null, klein = Infinity;
    (_nzData.raeume || []).forEach(function (r, ri) {
      var poly = r.region_px;
      if (!poly || poly.length < 3) return;
      var inside = false;
      for (var i = 0, j = poly.length - 1; i < poly.length; j = i++) {
        var xi = poly[i][0], yi = poly[i][1], xj = poly[j][0], yj = poly[j][1];
        if (((yi > pt[1]) !== (yj > pt[1])) &&
            (pt[0] < (xj - xi) * (pt[1] - yi) / ((yj - yi) || 1e-9) + xi)) {
          inside = !inside;
        }
      }
      if (!inside) return;
      var a = 0;
      for (var k = 0, l = poly.length - 1; k < poly.length; l = k++) {
        a += (poly[l][0] + poly[k][0]) * (poly[l][1] - poly[k][1]);
      }
      a = Math.abs(a / 2);
      if (a < klein) { klein = a; tref = ri; }   // verschachtelt -> kleinster
    });
    return tref;
  }

  // RAUMLEISTE ueber dem Plan: jeder Raum ein Knopf mit Name und Flaeche.
  // Der Klick im Plan ist der schoenere Weg, aber er ist nicht der einzige,
  // der funktionieren muss — auf einer A0-Tafel mit 70 Raeumen sucht man
  // sonst lange, und mit Stift oder am Touchgeraet trifft man daneben.
  function _nzRaumLeiste() {
    var rs = (_nzData && _nzData.raeume) || [];
    var alle = rs.map(function (r, i) { return { r: r, i: i }; })
      .filter(function (x) { return x.r && x.r.name; });
    // Freiflächen ans ENDE, hinter eine eigene Beschriftung. Sie gehören auf
    // den Plan (Nachvollziehbarkeit), aber nicht zwischen die Räume — sonst
    // sucht der Polier seine Wohnung zwischen Wiesen.
    var mit = alle.filter(function (x) { return !x.r.aussenanlage; });
    var frei = alle.filter(function (x) { return x.r.aussenanlage; });
    if (alle.length < 2) return '';
    var h = '<div class="nz-raumleiste" id="nz-raumleiste">' +
      '<span class="nz-rl-lab">Räume — anklicken zeigt die Werte:</span>';
    mit.forEach(function (x) {
      var ok = x.r.status === 'verifiziert' || x.r.rohbau_ok || x.r.iou_bewiesen;
      h += '<button type="button" class="nz-rl' + (_nzRaumInfo === x.i ? ' nz-rl-on' : '') +
        '" data-rl="' + x.i + '" title="' + esc(x.r.name || '') +
        (x.r.f_m2 ? ' · ' + fmtNum(x.r.f_m2) + ' m²' : '') + '">' +
        '<span class="nz-rl-pt" style="background:' + (ok ? '#16a34a' : '#d97706') + '"></span>' +
        esc(String(x.r.name || '').slice(0, 18)) +
        (x.r.f_m2 ? '<span class="nz-rl-f">' + fmtNum(x.r.f_m2) + ' m²</span>' : '') +
        '</button>';
    });
    if (frei.length) {
      h += '<span class="nz-rl-lab nz-rl-lab2">Freiflächen (keine Raumfläche, ' +
        'nicht in den Mengen):</span>';
      frei.forEach(function (x) {
        h += '<button type="button" class="nz-rl nz-rl-frei' +
          (_nzRaumInfo === x.i ? ' nz-rl-on' : '') +
          '" data-rl="' + x.i + '" title="' + esc(x.r.name || '') +
          (x.r.f_m2 ? ' · ' + fmtNum(x.r.f_m2) + ' m²' : '') +
          ' — Geländefläche ohne Umfangs-Stempel, geht in keine Position ein">' +
          '<span class="nz-rl-pt" style="background:#94a3b8"></span>' +
          esc(String(x.r.name || '').slice(0, 18)) +
          (x.r.f_m2 ? '<span class="nz-rl-f">' + fmtNum(x.r.f_m2) + ' m²</span>' : '') +
          '</button>';
      });
    }
    return h + '</div>';
  }

  function _nzWireZoom(cont) {
    _nzWrap = cont.querySelector('.nz-wrap'); if (!_nzWrap) return;
    _nzWrap.classList.toggle('nz-tool-aktiv', !!_mwTool);
    ['waende', 'oeff', 'raeume', 'mess'].forEach(function (k) {
      _nzWrap.classList.toggle('nz-lay-aus-' + k, !_nzLay[k]);
    });
    _nzApplyZoom();
    // MAUSRAD SCROLLT, STRG+RAD ZOOMT. Vorher lag das Rad komplett auf Zoom
    // (preventDefault + _nzZoomAt) — damit war Scrollen im Plan schlicht
    // nicht moeglich, egal wie gross der Plan war. Nutzer-Befund: "beim
    // unteren Teil des Plans kann ich nicht runterscrollen".
    // Konvention wie in jedem Karten-/Planbetrachter: Rad = verschieben,
    // Strg/Cmd + Rad = zoomen. Ist der Plan kleiner als sein Fenster, gibt
    // das Rad die Seite frei (kein preventDefault) — sonst klebt man fest.
    // RAD = ZOOM AUF DEN CURSOR (Karten-/CAD-Konvention; Nutzer-Befund
    // 2026-08-14: "beim Plan kann man immer noch nicht zoomen" — Zoom lag
    // nur auf Strg+Rad und den Knoepfen, das erwartet niemand). Der alte
    // Rad=Scroll-Kompromiss stammt aus der Zeit, als der Plan in einer
    // langen Seite steckte; seit dem Screen-Modus hat Schritt 2 den
    // Viewport. Trackpad-Pinch sendet ctrlKey+wheel und faellt in
    // denselben Pfad. Shift+Rad verschiebt horizontal, Drag verschiebt frei.
    _nzWrap.addEventListener('wheel', function (e) {
      var rect = _nzWrap.getBoundingClientRect();
      e.preventDefault();
      if (e.shiftKey) {
        _nzZoom.x -= (e.deltaY || e.deltaX);
        _nzApplyZoom();
        return;
      }
      _nzZoomAt(e.clientX - rect.left, e.clientY - rect.top,
                e.deltaY < 0 ? 1.15 : 1 / 1.15);
    }, { passive: false });
    // KLICK-EREIGNIS als zweiter, unabhaengiger Weg. Der Weg ueber
    // mousedown/mouseup + _nzPan traegt nicht ueberall: bei Stift- und
    // Touch-Eingabe und bei synthetischen Klicks kommt kein sauberes Paar an,
    // und dann passiert gar nichts. Ein Klick auf einen Raum muss aber
    // funktionieren.
    _nzWrap.addEventListener('click', function (e) {
      if (_mwTool || _nzAddMode || _nzMeasMode || _nzRaumEditMode || _nzMoved) return;
      if (e.target && e.target.getAttribute &&
          (e.target.getAttribute('data-wid') != null ||
           e.target.getAttribute('data-rv') != null)) return;   // Wand/Griff
      var ri = _nzRaumUnterPunkt(_nzScreenToImg(e));
      if (ri == null) return;
      _nzRaumInfo = (_nzRaumInfo === ri) ? null : ri;
      _nzPaint();
    });
    var _tch = null;
    _nzWrap.addEventListener('touchstart', function (e) {
      if (e.touches.length === 1) {
        _tch = { x: e.touches[0].clientX, y: e.touches[0].clientY,
                 ox: _nzZoom.x, oy: _nzZoom.y, d: 0 };
      } else if (e.touches.length === 2) {
        var dx = e.touches[0].clientX - e.touches[1].clientX;
        var dy = e.touches[0].clientY - e.touches[1].clientY;
        _tch = { pinch: Math.hypot(dx, dy), s0: _nzZoom.s };
      }
    }, { passive: true });
    _nzWrap.addEventListener('touchmove', function (e) {
      if (!_tch) return;
      if (e.touches.length === 1 && !_tch.pinch) {
        _nzZoom.x = _tch.ox + (e.touches[0].clientX - _tch.x);
        _nzZoom.y = _tch.oy + (e.touches[0].clientY - _tch.y);
        _nzApplyZoom(); e.preventDefault();
      } else if (e.touches.length === 2 && _tch.pinch) {
        var dx = e.touches[0].clientX - e.touches[1].clientX;
        var dy = e.touches[0].clientY - e.touches[1].clientY;
        var rect = _nzWrap.getBoundingClientRect();
        var cx = (e.touches[0].clientX + e.touches[1].clientX) / 2 - rect.left;
        var cy = (e.touches[0].clientY + e.touches[1].clientY) / 2 - rect.top;
        var f = Math.hypot(dx, dy) / _tch.pinch;
        _nzZoomAt(cx, cy, (_tch.s0 * f) / _nzZoom.s);
        e.preventDefault();
      }
    }, { passive: false });
    _nzWrap.addEventListener('touchend', function () { _tch = null; }, { passive: true });
    _nzWrap.addEventListener('dblclick', function (e) {
      if (_mwTool && _mwPts.length) { _mwAbschliessen(); e.preventDefault(); }
    });
    // RECHTSKLICK-MENÜ: auf einem Punkt „Punkt löschen", auf einer Messung
    // „Messung löschen", auf einem Raum die Umriss-Werkzeuge.
    _nzWrap.addEventListener('contextmenu', function (e) {
      if (!_nzData) return;
      var t = e.target, eintraege = [];
      var rv = t && t.getAttribute && t.getAttribute('data-rv');
      var mv = t && t.getAttribute && t.getAttribute('data-mv');
      var mid = t && t.getAttribute && t.getAttribute('data-mid');
      if (rv) {
        var pr = rv.split(':'), _ri = +pr[0], _vi = +pr[1];
        eintraege.push({ text: '✕ Punkt löschen', warn: true,
                         fn: function () { _nzRaumPunktWeg(_ri, _vi); } });
        eintraege.push({ text: '↺ Umriss auf Original zurücksetzen',
                         fn: function () { _nzRaumOriginal(_ri); } });
      } else if (mv) {
        var pm = mv.split(':'), _mid = pm[0], _mvi = +pm[1];
        eintraege.push({ text: '✕ Punkt löschen', warn: true,
                         fn: function () { _nzMessPunktWeg(_mid, _mvi); } });
        eintraege.push({ text: '✕ ganze Messung löschen', warn: true,
                         fn: function () { _mwLoeschen(_mid); } });
      } else if (mid) {
        eintraege.push({ text: '✕ Messung löschen', warn: true,
                         fn: function () { _mwLoeschen(mid); } });
      } else {
        var _rh = _nzRaumUnterPunkt(_nzScreenToImg(e));
        if (_rh != null) {
          eintraege.push({ text: '✏️ Umriss anpassen', fn: function () {
            _nzRaumEditMode = true; _nzRaumSel = _rh; _nzPaint();
          } });
          eintraege.push({ text: '▭ Umriss begradigen (Rechteck)', fn: function () {
            _nzRaumEditMode = true; _nzRaumSel = _rh; _nzRaumRechteck(_rh);
          } });
          eintraege.push({ text: '↺ Original wiederherstellen', fn: function () {
            _nzRaumOriginal(_rh);
          } });
        }
      }
      if (!eintraege.length) return;
      e.preventDefault();
      _nzMenu(e.clientX, e.clientY, eintraege);
    });
    // PUNKT AUSWÄHLEN (Klick auf einen Griff) — danach entfernt ihn Entf/Backspace.
    _nzWrap.addEventListener('click', function (e) {
      var t = e.target, rv = t && t.getAttribute && t.getAttribute('data-rv');
      var mv = t && t.getAttribute && t.getAttribute('data-mv');
      if (rv) { var p = rv.split(':'); _nzPktSel = { art: 'raum', ri: +p[0], vi: +p[1] }; }
      else if (mv) { var q = mv.split(':'); _nzPktSel = { art: 'mess', mid: q[0], vi: +q[1] }; }
      else if (!_mwTool) _nzPktSel = null;
      if (_nzPktSel) {
        _nzWrap.querySelectorAll('.nz-pkt-sel').forEach(function (el) {
          el.classList.remove('nz-pkt-sel');
        });
        t.classList.add('nz-pkt-sel');
        _mwHinweis('Punkt gewählt — Entf löscht ihn (oder Rechtsklick für das Menü).');
      }
    }, true);
    _nzWrap.addEventListener('click', function (e) {
      if (_mwTool && !_nzMoved) { if (_mwKlick(e)) { e.preventDefault(); e.stopPropagation(); } }
    });
    _nzWrap.addEventListener('mousedown', function (e) {
      var _mv = e.target && e.target.getAttribute && e.target.getAttribute('data-mv');
      if (_mv) {
        var _t = _mv.split(':');
        _mwVDrag = { mid: _t[0], vi: parseInt(_t[1], 10) };
        e.preventDefault(); e.stopPropagation(); return;
      }
      // GANZE MESSUNG verschieben (✥-Griff der gewählten Messung)
      var _mm = e.target && e.target.getAttribute && e.target.getAttribute('data-mmove');
      if (_mm) {
        var _mObj = (_mwListe || []).filter(function (x) { return x.id === _mm; })[0];
        if (_mObj) {
          _mwMDrag = { mid: _mm, start: _nzScreenToImg(e),
                       orig: _mObj.geometrie.punkte.map(function (p) { return [p[0], p[1]]; }) };
          e.preventDefault(); e.stopPropagation(); return;
        }
      }
      if (_mwTool) { e.preventDefault(); return; }   // Werkzeug: kein Pan
      if (_nzAddMode) { _nzDraw = { p0: _nzScreenToImg(e), p1: null }; e.preventDefault(); return; }
      // ERSTER ZUG AKTIVIERT DEN EDITOR: ein Griff an einem nur
      // AUSGEWAEHLTEN Raum schaltet den Raum-Editor an und zieht sofort.
      if (!_nzRaumEditMode) {
        var _tv = e.target;
        var _rv0 = _tv && _tv.getAttribute && _tv.getAttribute('data-rv');
        if (_rv0 != null) {
          var _pr0 = _rv0.split(':');
          _nzRaumEditMode = true;
          _nzRaumSel = +_pr0[0];
          _nzRvDrag = { ri: +_pr0[0], vi: +_pr0[1] };
          _nzPaint();
          e.preventDefault(); e.stopPropagation(); return;
        }
      }
      // GANZEN RAUM verschieben: ✥-Griff — funktioniert auch ohne aktiven
      // Editor (der Griff erscheint am ausgewählten Raum) und schaltet den
      // Editor beim ersten Zug automatisch an.
      var _rmv = e.target && e.target.getAttribute && e.target.getAttribute('data-rmove');
      if (_rmv != null && _nzData && _nzData.raeume[+_rmv]) {
        _nzRaumEditMode = true; _nzRaumSel = +_rmv;
        _nzRMoveStart(+_rmv, _nzScreenToImg(e));
        e.preventDefault(); e.stopPropagation(); return;
      }
      // RAUM-EDITOR: Eckpunkt ziehen oder (auf Kanten-Mitte) einfügen.
      if (_nzRaumEditMode) {
        var t = e.target;
        var rvv = t && t.getAttribute && t.getAttribute('data-rv');
        var add = t && t.getAttribute && t.getAttribute('data-radd');
        if (rvv) {
          var pr = rvv.split(':'); _nzRvDrag = { ri: +pr[0], vi: +pr[1] };
          e.preventDefault(); e.stopPropagation(); return;
        }
        // ZIEHEN IN DER FLÄCHE des gewählten Raums = ganzen Raum verschieben
        // (digiplan-Komfort "Flächen leicht verschieben"). Ein blosser Klick
        // ohne Bewegung bleibt Auswahl — entschieden wird in mousemove/mouseup.
        if (!rvv && !add && _nzRaumSel >= 0) {
          var _hitRi = _nzRaumUnterPunkt(_nzScreenToImg(e));
          if (_hitRi === _nzRaumSel) {
            _nzRMoveStart(_nzRaumSel, _nzScreenToImg(e));
            e.preventDefault(); e.stopPropagation(); return;
          }
        }
        if (add) {
          var pa = add.split(':'), ri = +pa[0], vi = +pa[1];
          var reg = _nzData.raeume[ri].region_px;
          var mid = [(reg[vi][0] + reg[(vi + 1) % reg.length][0]) / 2,
                     (reg[vi][1] + reg[(vi + 1) % reg.length][1]) / 2];
          reg.splice(vi + 1, 0, mid);           // neuen Punkt einfügen
          _nzRvDrag = { ri: ri, vi: vi + 1 };   // sofort ziehbar
          _nzRaumMarkEdited(ri); _nzPaint();
          e.preventDefault(); e.stopPropagation(); return;
        }
      }
      _nzPan = { sx: e.clientX, sy: e.clientY, ox: _nzZoom.x, oy: _nzZoom.y };
      _nzMoved = false; _nzWrap.style.cursor = 'grabbing';
    });
    cont.querySelectorAll('[data-lay]').forEach(function (b) {
      b.addEventListener('click', function () {
        var k = b.getAttribute('data-lay');
        _nzLay[k] = !_nzLay[k]; _nzPaint();
      });
    });
    cont.querySelectorAll('[data-mw]').forEach(function (b) {
      b.addEventListener('click', function () {
        var t = b.getAttribute('data-mw');
        if (t === 'snap') { _mwSnap = !_mwSnap; _nzPaint(); return; }
        _mwTool = (_mwTool === t) ? null : t;
        _mwPts = [];
        if (_mwTool) {   // Werkzeug-Modi schliessen sich gegenseitig aus
          _nzAddMode = false; _nzMeasMode = false; _nzRaumEditMode = false;
          _nzCalibMode = false; _nzSel = null;
        }
        _nzPaint();
        if (_mwTool) _mwHinweis(_MW_NAME[_mwTool] + ': Punkte im Plan klicken' +
          (_mwTool === 'stueck' ? '' : ' · Doppelklick beendet · Esc bricht ab'));
      });
    });
    // Gespeicherte Messung anklicken = auswählen (Eigenschaften rechts).
    var _hOk = cont.querySelector('#mw-hoehe-ok'),
        _hIn = cont.querySelector('#mw-hoehe-in'),
        _hAb = cont.querySelector('#mw-hoehe-abbr');
    function _hSubmit() {
      if (!_mwPending) return;
      var v = parseFloat((_hIn && _hIn.value || '').replace(',', '.'));
      var t = _mwPending.typ;
      if (!v || v <= 0 || (t === 'dach' && v >= 80)) { if (_hIn) _hIn.focus(); return; }
      _mwSpeichern(t, _mwPending.pts, { hoehe_m: v });
      _mwPending = null;
    }
    if (_hOk) _hOk.addEventListener('click', _hSubmit);
    if (_hIn) _hIn.addEventListener('keydown', function (e) {
      if (e.key === 'Enter') { _hSubmit(); e.preventDefault(); }
      if (e.key === 'Escape') { _mwPending = null; _nzPaint(); }
    });
    if (_hAb) _hAb.addEventListener('click', function () { _mwPending = null; _nzPaint(); });
    cont.querySelectorAll('[data-mki]').forEach(function (b) {
      b.addEventListener('click', function () {
        window._projModus = 'ki';
        if (window.projectId) {
          _sb.from('projekte').update({ modus: 'ki' }).eq('id', window.projectId).then(function () {});
        }
        _mwHinweis('KI-Analyse läuft — der Plan lädt gleich mit Vorschlägen neu …');
        var pid0 = _nzAktivPlan;
        fetch('/api/analyse-zoom', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ plan_id: pid0 })
        }).then(function () {
          _nzGeladen = false;
          renderNachzeichnen(pid0);
        });
      });
    });
    cont.querySelectorAll('[data-mvor]').forEach(function (b) {
      b.addEventListener('click', function () { _mwVorschlagen(); });
    });
    cont.querySelectorAll('[data-mok]').forEach(function (b) {
      b.addEventListener('click', function () { _mwBestaetigen([b.getAttribute('data-mok')]); });
    });
    cont.querySelectorAll('[data-mwegall]').forEach(function (b) {
      b.addEventListener('click', function () {
        var ids = _mwListe.filter(function (m) { return m.status === 'vorschlag'; })
          .map(function (m) { return m.id; });
        if (!ids.length) return;
        fetch('/api/messung-loeschen', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ ids: ids })
        }).then(function () { return _mwLaden(); }).then(function () { _nzPaint(); });
      });
    });
    cont.querySelectorAll('[data-mokall]').forEach(function (b) {
      b.addEventListener('click', function () {
        _mwBestaetigen(_mwListe.filter(function (m) { return m.status === 'vorschlag'; })
          .map(function (m) { return m.id; }));
      });
    });
    cont.querySelectorAll('[data-mdel]').forEach(function (b) {
      b.addEventListener('click', function () { _mwLoeschen(b.getAttribute('data-mdel')); });
    });
    cont.querySelectorAll('[data-mid2]').forEach(function (b) {
      b.addEventListener('click', function () {
        _mwSel = b.getAttribute('data-mid2'); _nzPaint();
      });
    });
    cont.querySelectorAll('[data-mid]').forEach(function (el) {
      el.addEventListener('click', function (ev) {
        if (_mwTool || _nzMoved) return;
        _mwSel = (_mwSel === el.getAttribute('data-mid')) ? null : el.getAttribute('data-mid');
        _nzPaint(); ev.stopPropagation();
      });
    });
    cont.querySelectorAll('.nz-zoomctl [data-z]').forEach(function (b) {
      b.addEventListener('click', function () {
        var z = b.getAttribute('data-z');
        if (z === 'raumfill') { _nzRaumFill = !_nzRaumFill; _nzPaint(); }
        if (z === 'umf') { _nzUmfassung = !_nzUmfassung; _nzPaint(); }
        if (z === 'praes') { _nzPraes = !_nzPraes; _nzPaint(); }
        else if (z === 'raumedit') {
          _nzRaumEditMode = !_nzRaumEditMode;
          if (_nzRaumEditMode) { _nzRaumFill = true; _nzAddMode = false; _nzMeasMode = false; _nzMeasPts = []; _nzSel = null; }
          else { _nzRaumSel = -1; _nzRvDrag = null; }
          _nzPaint();
        }
        else if (z === 'add') { _nzAddMode = !_nzAddMode; if (_nzAddMode) { _nzMeasMode = false; _nzMeasPts = []; _nzRaumEditMode = false; } _nzSel = null; _nzPaint(); }
        else if (z === 'mess') { _nzMeasMode = !_nzMeasMode; _nzCalibMode = false; if (_nzMeasMode) { _nzAddMode = false; } _nzMeasPts = []; _nzSel = null; _nzPaint(); }
        else if (z === 'calib') { if (_nzCalibMode) { _nzCalibMode = false; _nzMeasMode = false; _nzMeasPts = []; _nzPaint(); } else { _nzKalibrierenStart(); } }
        else if (z === 'mess-clear') { _nzMeasPts = []; _nzPaint(); }
        else if (z === 'korr-weg') {
          // Alle handgezogenen Umrisse verwerfen → frische Erkennung sehen.
          // Löscht auch den gespeicherten Stand, sonst kämen sie beim nächsten
          // Laden zurück.
          if (!window.confirm('Alle selbst gezogenen Raum-Umrisse verwerfen? '
              + 'Danach siehst du wieder die reine KI-Erkennung.')) return;
          (_nzData.raeume || []).forEach(function (r) {
            if (r._region_orig) r.region_px = r._region_orig.map(function (p) { return [p[0], p[1]]; });
            r._region_orig = null; r._edited = false; r._f_edit = null; r._u_edit = null;
          });
          var _ov = _filterState.materialliste_override || {};
          if (_ov.raum_flaechen) { delete _ov.raum_flaechen; _filterState.materialliste_override = _ov; }
          _nzSave(null);
          _nzGeladen = false;   // nächster Aufruf zeichnet frisch nach
          renderNachzeichnen(_nzAktivPlan, _nzAktivSeite === _nzHauptSeite ? null : _nzAktivSeite);
          refreshProjektMassen();
        }
        else if (z === 'reset') { _nzZoom = { s: 1, x: 0, y: 0 }; _nzApplyZoom(); }
        else if (z === 'full') { _nzToggleFull(); }
        else _nzZoomAt(_nzWrap.clientWidth / 2, _nzWrap.clientHeight / 2, z === 'in' ? 1.3 : 1 / 1.3);
      });
    });
    if (!_nzZoomWinBound) {   // Window-Listener nur EINMAL binden (sonst Leak je Repaint)
      _nzZoomWinBound = true;
      window.addEventListener('mousemove', function (e) {
        var _xy = document.getElementById('nz-sb-xy');
        if (_xy && _nzWrap && _nzData) {
          var k = _nzPxProM();
          if (k) {
            var q = _nzScreenToImg(e);
            var txt = (q[0] / k).toFixed(2) + ' / ' + (q[1] / k).toFixed(2) + ' m';
            if (_mwTool && _mwPts.length) {
              var lp = _mwPts[_mwPts.length - 1];
              txt = '↦ ' + (Math.hypot(q[0] - lp[0], q[1] - lp[1]) / k).toFixed(2) +
                ' m · ' + txt;
            }
            _xy.textContent = txt;
          }
        }
        if (_mwVDrag && _nzWrap) {
          var _mM = (_mwListe || []).filter(function (x) { return x.id === _mwVDrag.mid; })[0];
          if (_mM) {
            var _np2 = _mwSnapPunkt(_nzScreenToImg(e));
            _mM.geometrie.punkte[_mwVDrag.vi] = _mwPxZuPt(_np2);
            _nzFrame(function () { _mwSvgLive(_mwVDrag && _mwVDrag.mid); });
          }
          return;
        }
        if (_nzDraw && _nzWrap) { _nzDraw.p1 = _nzScreenToImg(e); _nzDrawPreview(); return; }
        // GANZE MESSUNG verschieben (Anker-Ecke rastet auf Wände, wie beim Raum).
        if (_mwMDrag && _nzWrap) {
          var _mMv = (_mwListe || []).filter(function (x) { return x.id === _mwMDrag.mid; })[0];
          if (_mMv) {
            var _pq = _nzScreenToImg(e);
            var _dxm = _pq[0] - _mwMDrag.start[0], _dym = _pq[1] - _mwMDrag.start[1];
            var _a0 = _mwPtZuPx(_mwMDrag.orig[0]);
            var _roh = [_a0[0] + _dxm, _a0[1] + _dym];
            var _ras = _mwSnapPunkt(_roh);
            _dxm += _ras[0] - _roh[0]; _dym += _ras[1] - _roh[1];
            _mMv.geometrie.punkte = _mwMDrag.orig.map(function (p0) {
              var px = _mwPtZuPx(p0);
              return _mwPxZuPt([px[0] + _dxm, px[1] + _dym]);
            });
            _nzFrame(function () { _mwSvgLive(_mwMDrag && _mwMDrag.mid); });
          }
          return;
        }
        // GANZEN RAUM live verschieben: Delta (mit Wand-Fang) auf alle Ecken.
        if (_nzRMove && _nzWrap) {
          var _dm = _nzRMoveDelta(_nzRMove, _nzScreenToImg(e));
          if (Math.abs(_dm[0]) > 2 || Math.abs(_dm[1]) > 2) _nzRMove.moved = true;
          var _regM = _nzData.raeume[_nzRMove.ri].region_px;
          _nzRMove.orig.forEach(function (v, vi) {
            _regM[vi] = [Math.round(v[0] + _dm[0]), Math.round(v[1] + _dm[1])];
          });
          var _riM = _nzRMove.ri;
          _nzFrame(function () { _nzRaumSvgLive(_riM); _nzRaumLiveReadout(_riM); });
          return;
        }
        // Raum-Eckpunkt live ziehen: Position updaten + neu zeichnen (Fläche folgt).
        // Der Punkt läuft durch den WAND-FANG (🧲): die Ecke rastet auf die
        // erkannte Wandlinie/Ecke — Taste G schaltet das Fangen um.
        if (_nzRvDrag && _nzWrap) {
          var p = _mwSnapPunkt(_nzScreenToImg(e));
          _nzData.raeume[_nzRvDrag.ri].region_px[_nzRvDrag.vi] = [Math.round(p[0]), Math.round(p[1])];
          var _riD = _nzRvDrag.ri;
          _nzFrame(function () { _nzRaumSvgLive(_riD); _nzRaumLiveReadout(_riD); });
          return;
        }
        if (!_nzPan || !_nzWrap) return;
        var dx = e.clientX - _nzPan.sx, dy = e.clientY - _nzPan.sy;
        if (Math.abs(dx) > 4 || Math.abs(dy) > 4) _nzMoved = true;
        _nzZoom.x = _nzPan.ox + dx; _nzZoom.y = _nzPan.oy + dy; _nzApplyZoom();
      });
      window.addEventListener('mouseup', function (e) {
        // GANZE MESSUNG losgelassen → Server rechnet Wert+Formel zur neuen Lage
        if (_mwMDrag) {
          var _dMv = (_mwListe || []).filter(function (x) { return x.id === _mwMDrag.mid; })[0];
          _mwMDrag = null;
          if (_dMv) {
            fetch('/api/messung', {
              method: 'POST', headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ projekt_id: window.projectId, id: _dMv.id,
                typ: _dMv.typ, geometrie: _dMv.geometrie,
                ptm: +((_nzData.meta || {}).ptm) || 0 })
            }).then(function (r) { return r.json(); }).then(function (d) {
              if (d && d.ok && d.messung) {
                for (var _k6 = 0; _k6 < _mwListe.length; _k6++) {
                  if (_mwListe[_k6].id === d.messung.id) _mwListe[_k6] = d.messung;
                }
              }
              _nzPaint();
            });
          }
          return;
        }
        // GANZEN RAUM losgelassen → Fläche/Umfang neu, als bearbeitet merken.
        // Ohne echte Bewegung war es ein Klick: Auswahl bleibt einfach stehen.
        if (_nzRMove) {
          if (_nzRMove.moved) _nzRaumMarkEdited(_nzRMove.ri);
          _nzRMove = null; _nzPaint(); return;
        }
        if (_mwVDrag) {
          var _dM = (_mwListe || []).filter(function (x) { return x.id === _mwVDrag.mid; })[0];
          _mwVDrag = null;
          if (_dM) {
            var _mB = { projekt_id: window.projectId, id: _dM.id, typ: _dM.typ,
                        geometrie: _dM.geometrie,
                        ptm: +((_nzData.meta || {}).ptm) || 0 };
            fetch('/api/messung', {
              method: 'POST', headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify(_mB)
            }).then(function (r) { return r.json(); }).then(function (d) {
              if (d && d.ok && d.messung) {
                for (var _k5 = 0; _k5 < _mwListe.length; _k5++) {
                  if (_mwListe[_k5].id === d.messung.id) _mwListe[_k5] = d.messung;
                }
              }
              _nzPaint();
            });
          }
          return;
        }

        if (_nzDraw) { if (_nzDraw.p1) _nzAddWall(_nzDraw.p0, _nzDraw.p1); _nzDraw = null; return; }
        if (_nzRvDrag) {   // Eckpunkt-Zug beendet → als bearbeitet markieren
          _nzRaumMarkEdited(_nzRvDrag.ri); _nzRvDrag = null; _nzPaint(); return;
        }
        // RAUM-EDITOR: Klick auf ein Polygon → diesen Raum bearbeiten.
        if (_nzPan && !_nzMoved && e.target) {
          var rp = e.target.getAttribute && e.target.getAttribute('data-rpoly');
          // ROBUST TREFFEN: der Treffer auf das SVG-Element allein reicht
          // nicht — ueber dem Raum liegen Wandlinien, Beschriftungen und
          // Marker, und je nachdem, was gerade oben liegt, geht der Klick ins
          // Leere. Darum zusaetzlich rechnerisch pruefen, in welchem
          // Raum-Polygon der Punkt liegt. Das haengt an keiner
          // Zeichenreihenfolge.
          if (rp == null && _nzWrap) {
            var _tref = _nzRaumUnterPunkt(_nzScreenToImg(e));
            if (_tref != null) rp = String(_tref);
          }
          if (rp != null) {
            if (_nzRaumEditMode) {
              _nzRaumSel = +rp; _nzPan = null; _nzPaint(); _nzRaumLiveReadout(_nzRaumSel);
            } else {
              // AUSSERHALB des Editors: Klick auf den Raum zeigt seine WERTE.
              _nzRaumInfo = (_nzRaumInfo === +rp) ? null : +rp;
              _nzPan = null; _nzPaint();
            }
            return;
          }
        }
        // MESSEN: ein sauberer Klick (kein Pan) setzt einen Mess-Punkt.
        if (_nzMeasMode && _nzPan && !_nzMoved && _nzWrap) {
          // Kalibrier-Modus: nur 2 Punkte; ein 3. Klick startet neu.
          if (_nzCalibMode && _nzMeasPts.length >= 2) _nzMeasPts = [];
          // Wand-Fang auch beim Lineal — NICHT beim Kalibrieren: dort klickt
          // man Maßketten-Enden, die gerade KEINE erkannte Wand sind.
          _nzMeasPts.push(_nzCalibMode ? _nzScreenToImg(e)
                                       : _mwSnapPunkt(_nzScreenToImg(e)));
          _nzPan = null; _nzMeasPaint(); return;
        }
        if (_nzPan) { _nzPan = null; if (_nzWrap) _nzWrap.style.cursor = 'grab'; }
      });
      // Doppelklick auf einen Eckpunkt → löschen (mind. 3 Punkte bleiben).
      window.addEventListener('dblclick', function (e) {
        if (!_nzRaumEditMode || !e.target || !e.target.getAttribute) return;
        var rv = e.target.getAttribute('data-rv');
        if (!rv) return;
        var pr = rv.split(':'), ri = +pr[0], vi = +pr[1];
        var reg = _nzData.raeume[ri].region_px;
        if (reg.length > 3) { reg.splice(vi, 1); _nzRaumMarkEdited(ri); _nzPaint(); }
        e.preventDefault();
      });
    }
    // Mess-Overlay nach einem Repaint wiederherstellen (Punkte überleben Zoom/Modus).
    if (_nzMeasMode && _nzMeasPts.length) _nzMeasPaint();
  }

  // MESS-OVERLAY: geklickte Punkte + Verbindungslinien + Live-Readout (m / m²).
  // Zeichnet in eine eigene SVG-Gruppe, ohne _nzPaint komplett neu zu bauen.
  function _nzMeasPaint() {
    var svg = _nzWrap && _nzWrap.querySelector('svg'); if (!svg) return;
    var old = svg.querySelector('#nz-mess'); if (old) old.remove();
    var g = document.createElementNS('http://www.w3.org/2000/svg', 'g');
    g.setAttribute('id', 'nz-mess');
    var pts = _nzMeasPts, n = pts.length;
    if (n >= 2) {
      var d = pts.map(function (p) { return p[0] + ',' + p[1]; }).join(' ');
      var poly = document.createElementNS('http://www.w3.org/2000/svg', n >= 3 ? 'polygon' : 'polyline');
      poly.setAttribute('points', d);
      poly.setAttribute('fill', n >= 3 ? '#7c3aed' : 'none');
      poly.setAttribute('fill-opacity', '0.12');
      poly.setAttribute('stroke', '#7c3aed'); poly.setAttribute('stroke-width', '2.5');
      g.appendChild(poly);
    }
    pts.forEach(function (p) {
      var c = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
      c.setAttribute('cx', p[0]); c.setAttribute('cy', p[1]); c.setAttribute('r', '5');
      c.setAttribute('fill', '#7c3aed'); c.setAttribute('stroke', '#fff'); c.setAttribute('stroke-width', '1.5');
      g.appendChild(c);
    });
    svg.appendChild(g);
    var out = document.getElementById('nz-mess-out');
    if (out) {
      // KALIBRIER-Modus: 2 Punkte einer bekannten Länge → Meter eingeben → px/m.
      if (_nzCalibMode) {
        if (n < 2) out.innerHTML = '<strong style="color:#0369a1">📐 Maßstab kalibrieren:</strong> klicke die 2 Endpunkte einer BEKANNTEN Länge am Plan (z.B. eine Maßkette oder Wand mit bekanntem Maß).';
        else {
          var _pxd = Math.round(_nzMessPxDist() * 10) / 10;
          out.innerHTML = '<strong style="color:#0369a1">' + _pxd + ' px gemessen.</strong> Reale Länge: ' +
            '<input type="number" id="nz-calib-m" step="0.01" min="0.01" inputmode="decimal" ' +
            'style="width:5rem;padding:.15rem .35rem;border:1px solid #0369a1;border-radius:6px" placeholder="Meter"> m ' +
            '<button type="button" class="nz-btn" style="padding:.1rem .5rem" onclick="_nzKalibrierenSetzen()">Maßstab setzen</button>';
          var _inp = document.getElementById('nz-calib-m'); if (_inp) _inp.focus();
        }
        return;
      }
      if (!_nzKalibriert()) out.innerHTML = '<strong style="color:#b45309">⚠ Dieser Plan ist nicht auf einen Maßstab kalibriert — Messung in Meter nicht möglich. </strong><button type="button" class="nz-btn" style="padding:.1rem .5rem" onclick="_nzKalibrierenStart()">📐 Maßstab jetzt setzen</button>';
      else if (n < 2) out.innerHTML = '<strong style="color:#7c3aed">Punkte klicken: Strecke · ab 3 Punkten auch Fläche</strong>';
      else {
        var s = 'Strecke <strong>' + fmtNum(Math.round(_nzMessStrecke() * 100) / 100) + ' m</strong>';
        if (n >= 3) s += ' · Umriss-Fläche <strong style="color:#7c3aed">' + fmtNum(Math.round(_nzMessFlaeche() * 100) / 100) + ' m²</strong>' +
          ' · Umfang <strong>' + fmtNum(Math.round(_nzMessUmfang() * 100) / 100) + ' m</strong>';
        out.innerHTML = s + ' <span style="color:#6b7280">(byte-exakt am Maßstab)</span>' +
          (n >= 3 ? ' <button type="button" class="nz-btn" style="padding:.1rem .5rem;font-size:.78rem" onclick="_nzMessUmfangUebernehmen()" title="Den geklickten Gebäude-Umriss als Außenumfang in die Materialliste übernehmen">→ als Außenumfang übernehmen</button>' : '');
      }
    }
  }

  // Bildschirm-Punkt → Bild-Pixel (berücksichtigt Zoom-Transform + img-Skalierung)
  // ═══ AUFMASS-WERKZEUG: Kern ════════════════════════════════════════
  // Koordinaten: gezeichnet wird in BILD-Pixeln, gespeichert wird in
  // PLAN-Punkten (pt). Grund: das Vorschaubild kann in anderer Aufloesung
  // neu gerendert werden — Plan-pt bleiben gueltig, Bild-px nicht.
  function _mwPxZuPt(p) {
    var sc = +(_nzData && _nzData.meta || {}).scale || 1;
    return [p[0] / sc, p[1] / sc];
  }
  function _mwPtZuPx(p) {
    var sc = +(_nzData && _nzData.meta || {}).scale || 1;
    return [p[0] * sc, p[1] * sc];
  }

  // SNAPPING — unser Vorsprung gegenueber reinen Klick-Werkzeugen: die App
  // kennt die gezeichneten Wandlinien und die byte-exakten Massketten-
  // Fluchten bereits. Der Nutzer trifft die Ecke, ohne zu zielen.
  function _mwSnapPunkt(p) {
    if (!_mwSnap || !_nzData) return p;
    var tol = 12;                      // Bild-px Fangradius
    var best = null, bd = tol * tol;
    // 1) Wand-Endpunkte (Ecken) haben Vorrang — dort trifft man sonst nie.
    (_nzData.waende || []).forEach(function (w) {
      [[w.px[0], w.px[1]], [w.px[2], w.px[3]]].forEach(function (q) {
        var d = (q[0] - p[0]) * (q[0] - p[0]) + (q[1] - p[1]) * (q[1] - p[1]);
        if (d < bd) { bd = d; best = [q[0], q[1]]; }
      });
    });
    if (best) return best;
    // 2) Sonst auf die naechste Wandlinie projizieren.
    var bl = null, bld = tol * tol;
    (_nzData.waende || []).forEach(function (w) {
      var x1 = w.px[0], y1 = w.px[1], x2 = w.px[2], y2 = w.px[3];
      var dx = x2 - x1, dy = y2 - y1, L2 = dx * dx + dy * dy;
      if (L2 < 1) return;
      var t = Math.max(0, Math.min(1, ((p[0] - x1) * dx + (p[1] - y1) * dy) / L2));
      var qx = x1 + t * dx, qy = y1 + t * dy;
      var d = (qx - p[0]) * (qx - p[0]) + (qy - p[1]) * (qy - p[1]);
      if (d < bld) { bld = d; bl = [qx, qy]; }
    });
    return bl || p;
  }

  function _mwSeite() { return (_nzAktivSeite || 0); }

  function _mwLaden() {
    if (!window.projectId || !_nzAktivPlan) { _mwListe = []; return Promise.resolve(); }
    return fetch('/api/messungen?projekt_id=' + encodeURIComponent(window.projectId) +
                 '&plan_id=' + encodeURIComponent(_nzAktivPlan) +
                 '&seite=' + _mwSeite())
      .then(function (r) { return r.json(); })
      .then(function (d) { _mwListe = (d && d.messungen) || []; })
      .catch(function () { _mwListe = []; });
  }

  function _mwSpeichern(typ, ptsPx, extra) {
    if (_mwBusy) return Promise.resolve();
    _mwBusy = true;
    var m = _nzData.meta || {};
    var body = Object.assign({
      projekt_id: window.projectId, plan_id: _nzAktivPlan, seite: _mwSeite(),
      typ: (typ === 'rechteck' ? 'flaeche' : typ),
      geometrie: {
        form: (typ === 'rechteck' ? 'rechteck'
               : (typ === 'laenge' || typ === 'wandflaeche') ? 'polylinie'
               : typ === 'stueck' ? 'punkt' : 'polygon'),
        punkte: ptsPx.map(_mwPxZuPt)
      },
      ptm: +m.ptm || 0, quelle: 'mensch', status: 'aktiv'
    }, extra || {});
    return fetch('/api/messung', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body)
    }).then(function (r) { return r.json(); })
      .then(function (d) {
        _mwBusy = false;
        if (d && d.ok && d.messung) {
          _mwListe.push(d.messung); _mwSel = d.messung.id;
          _mwUndo.push(d.messung.id);
        }
        else _mwHinweis('Konnte nicht gespeichert werden: ' + ((d && d.grund) || 'unbekannt'), true);
        _nzPaint();
      }).catch(function (e) { _mwBusy = false; _mwHinweis('Fehler: ' + e, true); });
  }

  function _mwLoeschen(id) {
    return fetch('/api/messung-loeschen', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ id: id })
    }).then(function () {
      _mwListe = _mwListe.filter(function (x) { return x.id !== id; });
      if (_mwSel === id) _mwSel = null;
      _nzPaint();
    });
  }

  function _mwVorschlagen() {
    if (_mwBusy || !window.projectId || !_nzAktivPlan) return;
    _mwBusy = true; _mwHinweis('KI-Vorschläge werden erzeugt …');
    fetch('/api/messungen-vorschlagen', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ projekt_id: window.projectId, plan_id: _nzAktivPlan,
                             seite: _mwSeite() })
    }).then(function (r) { return r.json(); })
      .then(function (d) {
        _mwBusy = false;
        if (d && d.ok) {
          _mwHinweis(d.vorschlaege + ' Vorschläge aus der Erkennung — gestrichelt am Plan, per Klick bestätigen');
          _mwLaden().then(function () {
        // KI-VORAUSWAHL (Nutzer-Auftrag): sind noch keine Messungen da,
        // liegen die erkannten Raeume sofort als Vorschlaege am Plan —
        // bestaetigen statt zeichnen. Einmal je Plan+Seite.
        var k = String(_nzAktivPlan) + ':' + _mwSeite();
        if (!_mwListe.length && (_nzData.raeume || []).length &&
            !_mwAutoDone[k]) {
          _mwAutoDone[k] = true;
          _mwVorschlagen();
        } else _nzPaint();
      });
        } else _mwHinweis((d && d.grund) || 'Keine Vorschläge möglich', true);
      }).catch(function () { _mwBusy = false; });
  }

  function _mwBestaetigen(ids) {
    return fetch('/api/messungen-bestaetigen', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(ids ? { ids: ids } : { projekt_id: window.projectId })
    }).then(function () { return _mwLaden(); }).then(function () { _nzPaint(); });
  }

  function _mwHinweis(txt, warn) {
    var el = document.getElementById('nz-mess-out');
    if (el) el.innerHTML = '<strong style="color:' + (warn ? '#b42318' : '#0d9488') +
      '">' + esc(txt) + '</strong>';
  }

  // Live-Wert waehrend des Zeichnens — dieselbe Formel wie der Server,
  // aber nur zur ANZEIGE; gespeichert wird immer das Server-Ergebnis.
  function _mwVorschau(typ, ptsPx) {
    var k = _nzPxProM(); if (!k || ptsPx.length < 1) return '';
    if (typ === 'stueck') return '1 Stk';
    if (typ === 'laenge') {
      var L = 0;
      for (var i = 1; i < ptsPx.length; i++)
        L += Math.hypot(ptsPx[i][0] - ptsPx[i - 1][0], ptsPx[i][1] - ptsPx[i - 1][1]);
      return fmtNum(Math.round(L / k * 100) / 100) + ' m';
    }
    if (ptsPx.length < 3) return ptsPx.length + ' Punkte';
    var A = 0;
    for (var j = 0; j < ptsPx.length; j++) {
      var a = ptsPx[j], b = ptsPx[(j + 1) % ptsPx.length];
      A += a[0] * b[1] - b[0] * a[1];
    }
    return fmtNum(Math.round(Math.abs(A) / 2 / (k * k) * 100) / 100) + ' m²';
  }

  // Klick im Werkzeug-Modus: Punkt setzen; Rechteck/Stück schliessen selbst ab.
  function _mwKlick(e) {
    if (!_mwTool) return false;
    var p = _mwSnapPunkt(_nzScreenToImg(e));
    // SHIFT = ORTHO (digiplan-Kernkomfort): Segment waagrecht/senkrecht
    // zum Vorpunkt zwingen — die groessere Achsdifferenz gewinnt.
    if (e.shiftKey && _mwPts.length) {
      var q = _mwPts[_mwPts.length - 1];
      if (Math.abs(p[0] - q[0]) >= Math.abs(p[1] - q[1])) p = [p[0], q[1]];
      else p = [q[0], p[1]];
    }
    if (_mwTool === 'stueck') { _mwSpeichern('stueck', [p], { }); return true; }
    // KLICK AUF DEN STARTPUNKT schliesst das Polygon (Toleranz 12 px).
    if (_mwPts.length >= 3) {
      var s0 = _mwPts[0];
      if (Math.hypot(p[0] - s0[0], p[1] - s0[1]) < 12) {
        _mwAbschliessen(); return true;
      }
    }
    _mwPts.push(p);
    if (_mwTool === 'rechteck' && _mwPts.length === 2) {
      var a = _mwPts[0], b = _mwPts[1];
      _mwSpeichern('rechteck', [[a[0], a[1]], [b[0], a[1]], [b[0], b[1]], [a[0], b[1]]]);
      _mwPts = []; return true;
    }
    _mwHinweis(_MW_NAME[_mwTool] + ': ' + _mwVorschau(_mwTool, _mwPts) +
               ' — Doppelklick oder Enter beendet, Esc bricht ab');
    _nzPaint();
    return true;
  }

  function _mwAbschliessen() {
    if (!_mwTool || _mwPts.length < 2) { _mwPts = []; _nzPaint(); return; }
    var typ = _mwTool === 'rechteck' ? 'flaeche' : _mwTool;
    if ((typ === 'flaeche' || typ === 'abzug' || typ === 'volumen' ||
         typ === 'treppe' || typ === 'dach') && _mwPts.length < 3) {
      _mwPts = []; _nzPaint(); return;
    }
    // HOEHEN-WERKZEUGE: die Zeichnung wird "wartend" — das Eigenschaften-
    // Panel fragt Hoehe/Neigung ab (kein window.prompt: der Dialog riss
    // aus dem Zeichenfluss und war nicht abbrechbar-transparent).
    if (typ === 'dach' || typ === 'wandflaeche' || typ === 'volumen' ||
        typ === 'treppe') {
      _mwPending = { typ: typ, pts: _mwPts.slice() };
      _mwPts = [];
      _nzPaint();
      var inp = document.getElementById('mw-hoehe-in');
      if (inp) { inp.focus(); inp.select(); }
      return;
    }
    _mwSpeichern(typ, _mwPts.slice(), {});
    _mwPts = [];
  }

  // SVG der gespeicherten Messungen + der laufenden Zeichnung.
  function _mwSvg() {
    if (!_nzData) return '';
    var out = '', fs = Math.max(11, Math.round((_nzData.bild_w || 1200) / 90));
    (_mwListe || []).forEach(function (m) {
      var g = m.geometrie || {}, pts = (g.punkte || []).map(_mwPtZuPx);
      if (!pts.length) return;
      var col = _MW_FARBE[m.typ] || '#0d9488';
      var vorschlag = (m.status === 'vorschlag');
      var sel = (_mwSel === m.id);
      var dash = vorschlag ? ' stroke-dasharray="7 5"' : '';
      if (g.form === 'punkt') {
        out += '<g data-mid="' + m.id + '" cursor="pointer"><circle cx="' + pts[0][0] +
          '" cy="' + pts[0][1] + '" r="' + (fs * 0.5) + '" fill="' + col +
          '" stroke="#fff" stroke-width="2"' + dash + '/></g>';
      } else if (g.form === 'polylinie') {
        out += '<polyline data-mid="' + m.id + '" points="' +
          pts.map(function (p) { return p[0] + ',' + p[1]; }).join(' ') +
          '" fill="none" stroke="' + col + '" stroke-width="' + (sel ? 5 : 3) +
          '" stroke-linecap="round"' + dash + ' cursor="pointer"/>';
      } else {
        out += '<polygon data-mid="' + m.id + '" points="' +
          pts.map(function (p) { return p[0] + ',' + p[1]; }).join(' ') +
          '" fill="' + col + (vorschlag ? '18' : '26') + '" stroke="' + col +
          '" stroke-width="' + (sel ? 5 : 3) + '"' + dash + ' cursor="pointer"/>';
      }
      // Nummer + Wert: die Referenz, unter der die Messung im Protokoll steht.
      var cx = 0, cy = 0;
      pts.forEach(function (p) { cx += p[0]; cy += p[1]; });
      cx /= pts.length; cy /= pts.length;
      var lab = 'M' + (m.nummer || '?') + '  ' +
        (m.wert != null ? fmtNum(m.wert) + ' ' + _nzEinheit(m.einheit) : '');
      out += '<text x="' + cx + '" y="' + cy + '" font-size="' + fs +
        '" text-anchor="middle" paint-order="stroke" stroke="#fff" stroke-width="' +
        Math.round(fs / 3) + '" fill="' + col +
        '" style="font-weight:700;pointer-events:none">' + esc(lab) + '</text>';
    });
    // VERTEX-HANDLES der gewaehlten Messung (digiplan-Paritaet,
    // Folgerunde aus docs/MANUELL_MODUS.md): Punkte ziehen, der Server
    // rechnet Wert+Formel neu — die Geometrie bleibt die Wahrheit.
    var _selM = (_mwListe || []).filter(function (x) { return x.id === _mwSel; })[0];
    if (_selM && _selM.geometrie && (_selM.geometrie.punkte || []).length &&
        _selM.geometrie.form !== 'punkt') {
      var _hp = _selM.geometrie.punkte.map(_mwPtZuPx);
      _hp.forEach(function (q, vi) {
        out += '<circle data-mv="' + _selM.id + ':' + vi + '" cx="' + q[0] +
          '" cy="' + q[1] + '" r="' + (fs * 0.45) +
          '" fill="#fff" stroke="' + (_MW_FARBE[_selM.typ] || '#0d9488') +
          '" stroke-width="2.5" cursor="grab"/>';
      });
      // ✥-GRIFF: die ganze Messung verschieben (Wert/Formel rechnet der
      // Server nach dem Loslassen neu — die Geometrie bleibt die Wahrheit).
      var _mmx = 0, _mmy = 0;
      _hp.forEach(function (q) { _mmx += q[0]; _mmy += q[1]; });
      _mmx /= _hp.length; _mmy /= _hp.length;
      var _mcol = _MW_FARBE[_selM.typ] || '#0d9488';
      out += '<circle data-mmove="' + _selM.id + '" cx="' + _mmx + '" cy="' + _mmy +
        '" r="' + (fs * 0.7) + '" fill="' + _mcol + '" fill-opacity="0.92"' +
        ' stroke="#fff" stroke-width="2.5" cursor="move"' +
        '><title>Ganze Messung verschieben</title></circle>' +
        '<text x="' + _mmx + '" y="' + (_mmy + fs * 0.28) + '" text-anchor="middle" font-size="' +
        Math.round(fs * 0.85) + '" fill="#fff" style="pointer-events:none;font-weight:700">✥</text>';
    }
    if (_mwPending && _mwPending.pts.length) {
      var cp = _MW_FARBE[_mwPending.typ] || '#0d9488';
      out += '<polygon points="' + _mwPending.pts.map(function (p) { return p[0] + ',' + p[1]; }).join(' ') +
        '" fill="' + cp + '22" stroke="' + cp + '" stroke-width="3" stroke-dasharray="8 5"/>';
    }
    // laufende Zeichnung
    if (_mwTool && _mwPts.length) {
      var c2 = _MW_FARBE[_mwTool] || '#0d9488';
      out += '<polyline points="' + _mwPts.map(function (p) { return p[0] + ',' + p[1]; }).join(' ') +
        '" fill="none" stroke="' + c2 + '" stroke-width="3" stroke-dasharray="5 4"/>';
      _mwPts.forEach(function (p) {
        out += '<circle cx="' + p[0] + '" cy="' + p[1] + '" r="' + (fs * 0.35) +
          '" fill="#fff" stroke="' + c2 + '" stroke-width="2"/>';
      });
    }
    return out;
  }
  // Statusleiste wie in einer Zeichensoftware: Werkzeug, Fangen, Massstab,
  // Cursor-Position in Metern. Der Massstab steht IMMER da — er ist die
  // Grundlage jeder Zahl, und wer ihn sieht, merkt, wenn er fehlt.
  function _mwStatusbar() {
    var m = (_nzData && _nzData.meta) || {};
    var mst = m.massstab ? '1:' + m.massstab : (m.ptm ? 'kalibriert' : '—');
    var nV = (_mwListe || []).filter(function (x) { return x.status === 'vorschlag'; }).length;
    return '<div class="nz-statusbar">' +
      '<span class="nz-sb-tool">' + (_mwTool ? _MW_NAME[_mwTool] :
        (_nzRaumEditMode ? 'Raum-Editor' : (_nzAddMode ? 'Wand zeichnen' : 'Auswahl'))) + '</span>' +
      '<span title="Fangen (Taste G)">🧲 ' + (_mwSnap ? 'an' : 'aus') + '</span>' +
      '<span title="Maßstab">📐 ' + mst + '</span>' +
      '<span>' + (_mwListe || []).length + ' Messungen' +
      (nV ? ' · <b>' + nV + ' offen</b>' : '') + '</span>' +
      '<span class="nz-sb-xy" id="nz-sb-xy"></span>' +
      '<span class="nz-sb-keys">F R L S A · V Volumen · T Treppe · D Dach · W Wand · G Fangen · Esc</span>' +
      '</div>';
  }

  function _nzEinheit(e) {
    return e === 'm2' ? 'm²' : (e === 'm3' ? 'm³' : (e || ''));
  }

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
    var pxProM = _nzPxProM();
    if (!pxProM) { alert('Dieser Plan ist nicht kalibriert — eine Wandlänge in Meter lässt sich nicht bestimmen. Bitte auf dem kalibrierten Grundriss-Tab zeichnen.'); _nzPaint(); return; }
    var m = _nzData.meta || {}, scale = +m.scale, ptm = +m.ptm;
    var px, achse, lenpx;
    if (dx >= dy) { var ym = (p0[1] + p1[1]) / 2; px = [Math.min(p0[0], p1[0]), ym, Math.max(p0[0], p1[0]), ym]; achse = 'h'; lenpx = dx; }
    else { var xm = (p0[0] + p1[0]) / 2; px = [xm, Math.min(p0[1], p1[1]), xm, Math.max(p0[1], p1[1])]; achse = 'v'; lenpx = dy; }
    var laenge_m = Math.round(lenpx / pxProM * 100) / 100;
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

  // ABSOLUTE Wandlängen (Meter je Stärke) in die Materialliste übernehmen —
  // HLZ-Fläche = Länge × Höhe (byte-exakt/manuell), statt Hülle × Anteil%.
  function _nzUebernehmenLaengen(laengen, manuell) {
    if (!laengen) return;
    var ov = _filterState.materialliste_override || {};
    // alte Prozent-Overrides entfernen (Länge hat Vorrang, kein Misch-Zustand)
    ['wand_anteil_50cm', 'wand_anteil_38cm', 'wand_anteil_25cm_aussen',
     'wand_anteil_25cm_innen', 'wand_anteil_20cm', 'wand_anteil_12cm'].forEach(function (k) { delete ov[k]; });
    ov.wand_laengen_m = laengen;
    ov.wand_laengen_manuell = !!manuell;
    _filterState.materialliste_override = ov;
    refreshProjektMassen();
    _nzSave(null, { wand_laengen_m: laengen, wand_laengen_manuell: !!manuell });
    var ap = document.getElementById('nz-apply-len');
    if (ap) {
      ap.textContent = manuell ? '✓ manuelle Wandlängen übernommen — Mengen neu gerechnet'
        : '✓ gemessene Wandlängen übernommen — Mengen neu gerechnet';
      ap.disabled = true;
    }
  }

  // Speichert den Korrektur-Zustand (Edits + Verteilung/Wandlängen/Raumflächen) am
  // Plan. Nimmt Wandlängen UND Raumflächen aus dem laufenden Override-Zustand mit,
  // damit ein Save nicht die jeweils andere Korrektur verwirft.
  function _nzSave(anteile, laengen) {
    if (!_nzData || !_nzData.plan_id) return;
    var ov = _filterState.materialliste_override || {};
    var wl = (laengen && laengen.wand_laengen_m) || ov.wand_laengen_m || null;
    var wlm = (laengen && laengen.wand_laengen_manuell) || ov.wand_laengen_manuell || false;
    var rf = ov.raum_flaechen && Object.keys(ov.raum_flaechen).length ? ov.raum_flaechen : null;
    var kalib = (_nzData.meta && _nzData.meta.px_pro_m_manuell > 0) ? _nzData.meta.px_pro_m_manuell : null;
    // HANDKORRIGIERTE RAUM-UMRISSE mitspeichern (Live-Befund 2026-08-23: der
    // Nutzer zog vier Räume sauber nach — beim Reload war ALLES weg, weil nur
    // F/U-Overrides, nie die Polygone gespeichert wurden). Key wie bei
    // raum_flaechen: normalisierter Name; Geschoss zur Absicherung im Wert.
    // ROBUST GEGEN PIPELINE-ÄNDERUNGEN: zusätzlich in PLAN-Koordinaten (pt)
    // sichern. Bild-Pixel gelten nur für eine bestimmte Box+Auflösung — ändert
    // sich der Bildausschnitt (z.B. weil ein Raum am Blattfuß dazukommt), wäre
    // die Handarbeit sonst wertlos. pt bleibt am Plan verankert.
    var _bp = (_nzData.meta || {}).box_pt, _sc = +(_nzData.meta || {}).scale;
    var _zuPt = (_bp && _sc > 0)
      ? function (p) { return [Math.round((p[0] / _sc + _bp[0]) * 100) / 100,
                               Math.round((p[1] / _sc + _bp[1]) * 100) / 100]; }
      : null;
    var rr = {};
    (_nzData.raeume || []).forEach(function (r) {
      if (r._edited && r.region_px && r.region_px.length >= 3 && r.name) {
        rr[_nrmRaum(r.name)] = { name: r.name, geschoss: r.geschoss || null,
          region_px: r.region_px.map(function (p) { return [p[0], p[1]]; }),
          region_pt: _zuPt ? r.region_px.map(_zuPt) : null };
      }
    });
    if (!Object.keys(rr).length) rr = null;
    var leer = !Object.keys(_nzEdit.removed).length && !Object.keys(_nzEdit.thick).length &&
      !Object.keys(_nzEdit.aussen).length && !(_nzEdit.added && _nzEdit.added.length) &&
      !(_nzEdit.oeffRemoved && Object.keys(_nzEdit.oeffRemoved).length) && !anteile && !wl && !rf && !kalib && !rr;
    fetch('/api/nachzeichnen-korrektur', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ plan_id: _nzData.plan_id,
        seite: (_nzAktivSeite != null && _nzAktivSeite !== _nzHauptSeite) ? _nzAktivSeite : null,
        korrekturen: leer ? null : { edit: _nzEdit, anteile: anteile || null,
          wand_laengen_m: wl, wand_laengen_manuell: wlm, raum_flaechen: rf,
          raum_regionen: rr, px_pro_m_manuell: kalib } })
    }).catch(function () { /* Speichern ist best-effort */ });
  }

  // Raumnamen-Normalisierung für den Plan-Anker-Abgleich (Aufmaß-Zeile ↔ Overlay).
  function _nrmRaum(s) {
    return (s || '').toLowerCase().replace(/ä/g, 'ae').replace(/ö/g, 'oe')
      .replace(/ü/g, 'ue').replace(/ß/g, 'ss').replace(/[^a-z0-9]/g, '');
  }
  // Kopplung Aufmaß-Zeile → Plan: den belegten RAUM am Plan pulsieren lassen.
  // (Traceability-Anker: jede Raum-Zeile der Gewerke trägt anker.raum.)
  // „Im Plan zeigen" muss auch dann funktionieren, wenn der Nutzer gerade in
  // einem Schritt steht, der die Planansicht ausblendet (Zuordnung, Positionen).
  // Sonst scrollt der Klick ins Leere und der Beleg ist nicht auffindbar.
  function _wfZuPlan() {
    var sec = document.getElementById('nachzeichnen-section');
    if (sec && sec.classList.contains('wf-hidden') && window.wfShow) window.wfShow(2);
    return sec;
  }
  // BELEG-LEISTE im Plan: was wird hier gerade geprueft?
  //
  // Der Sprung liess bisher nur den Raum aufleuchten. Was man angeklickt hat
  // und welche Zahl dahinter steht, musste man im Kopf behalten — auf einem
  // A0-Blatt mit 70 Raeumen ist das keine Nachvollziehbarkeit, sondern
  // Gedaechtnisarbeit. Jetzt steht die Position, der Raum und der Rechenweg
  // direkt ueber dem Plan, bis man sie wegklickt.
  function _planBeleg(text) {
    var sec = document.getElementById('nachzeichnen-section');
    if (!sec) return;
    var el = document.getElementById('plan-beleg');
    if (!el) {
      el = document.createElement('div');
      el.id = 'plan-beleg';
      el.className = 'plan-beleg';
      var cont = document.getElementById('nachzeichnen-container');
      if (cont && cont.parentNode) cont.parentNode.insertBefore(el, cont);
      else sec.appendChild(el);
    }
    if (!text) { el.style.display = 'none'; return; }
    el.innerHTML = '<span class="pb-marke">\uD83D\uDCCD im Plan geprüft</span>' +
      '<span class="pb-text">' + text + '</span>' +
      '<button type="button" class="pb-zu" title="Ausblenden">&times;</button>';
    el.style.display = '';
    var zu = el.querySelector('.pb-zu');
    if (zu) zu.onclick = function () {
      el.style.display = 'none';
      var c = document.getElementById('nachzeichnen-container');
      if (c) {
        var m = c.querySelectorAll('.nz-belegmarke');
        Array.prototype.forEach.call(m, function (x) {
          if (x.parentNode) x.parentNode.removeChild(x);
        });
      }
    };
  }
  window._planBeleg = _planBeleg;

  // Die MENGE AN DEN RAUM schreiben — nicht nur ueber den Plan.
  //
  // Eine Leiste ueber dem Blatt sagt WAS geprueft wird; auf dem Blatt selbst
  // stand die Zahl bisher nicht. Wer mit dem Ausdruck auf der Baustelle steht,
  // braucht sie aber dort, wo der Raum ist. Die Marke haengt am Raum-Badge und
  // verschwindet mit der Hervorhebung.
  function _kurzAusBeleg(b) {
    if (!b) return '';
    var t = String(b).replace(/&[a-z]+;/g, ' ');
    // Zwei Fallen, beide im Browser aufgefallen:
    // 1) KEIN \b hinter der Einheit. Nach "m²" folgt ein Leerzeichen, und
    //    weder "²" noch " " sind Wortzeichen — die Wortgrenze fehlt, die
    //    Alternative "m²" scheitert und der Ausdruck faellt auf "m" zurueck.
    //    Aus "38,94 m²" wurde so "38,94 m".
    // 2) Das LETZTE Gleichheitszeichen zaehlt. Eine Aufmass-Zeile lautet
    //    "U=13.2 × H=2.95 = 38,94" — das erste "=" liefert die Wandlaenge,
    //    nicht das Ergebnis.
    var EIN = /(-?[\d.,]+)\s*(m²|m³|lfm|Stk|m)?/;
    var letzte = null;
    var re = /=\s*(-?[\d.,]+)\s*(m²|m³|lfm|Stk|m)?/g;
    var tr;
    while ((tr = re.exec(t)) !== null) letzte = tr;
    if (!letzte) letzte = t.match(/·\s*(-?[\d.,]+)\s*(m²|m³|lfm|Stk|m)/);
    if (!letzte) letzte = t.match(EIN);
    return letzte ? (letzte[1] + (letzte[2] ? ' ' + letzte[2] : '')) : '';
  }

  function _markenWeg(cont) {
    if (!cont) return;
    var alt = cont.querySelectorAll('.nz-belegmarke');
    Array.prototype.forEach.call(alt, function (x) {
      if (x.parentNode) x.parentNode.removeChild(x);
    });
  }

  function _planMarke(g, kurz) {
    if (!kurz) return;
    var svg = g.ownerSVGElement;
    var c = g.querySelector('circle');
    if (!svg || !c) return;
    var cx = parseFloat(c.getAttribute('cx'));
    var cy = parseFloat(c.getAttribute('cy'));
    var rr = parseFloat(c.getAttribute('r')) || 8;
    if (!isFinite(cx) || !isFinite(cy)) return;
    var fs = Math.max(9, rr * 1.45);
    var br = kurz.length * fs * 0.58 + fs * 0.9;
    var NS = 'http://www.w3.org/2000/svg';
    var grp = document.createElementNS(NS, 'g');
    grp.setAttribute('class', 'nz-belegmarke');
    grp.setAttribute('pointer-events', 'none');
    var re = document.createElementNS(NS, 'rect');
    re.setAttribute('x', cx + rr + fs * 0.35);
    re.setAttribute('y', cy - fs * 0.85);
    re.setAttribute('width', br);
    re.setAttribute('height', fs * 1.7);
    re.setAttribute('rx', fs * 0.35);
    re.setAttribute('fill', '#1f2937');
    re.setAttribute('stroke', '#f39301');
    re.setAttribute('stroke-width', Math.max(1, fs * 0.11));
    var tx = document.createElementNS(NS, 'text');
    tx.setAttribute('x', cx + rr + fs * 0.8);
    tx.setAttribute('y', cy);
    tx.setAttribute('font-size', fs);
    tx.setAttribute('dy', fs * 0.33);
    tx.setAttribute('fill', '#fff');
    tx.setAttribute('style', 'font-weight:700');
    tx.textContent = kurz;
    grp.appendChild(re);
    grp.appendChild(tx);
    svg.appendChild(grp);
  }

  // RAUM-WERTE beim Klick — direkt am Plan, ohne Umweg ueber eine Tabelle.
  // Zeigt was der Raum ist (F/U/H byte-exakt oder geschaetzt) UND welche
  // Positionen er traegt. Genau das, was ein Polier wissen will, wenn er auf
  // ein Zimmer tippt.
  // Das Feld wird MIT dem Plan gezeichnet, nicht nachtraeglich in den DOM
  // gehaengt: sonst landet es weit oberhalb der Raumleiste, und wer einen
  // Raum antippt, sieht die Werte nicht — sie stehen ausserhalb des Blicks.
  function _nzRaumWerte(ri) { _nzPaint(); }

  function _nzRaumWerteHtml(ri) {
    if (ri == null || !_nzData || !(_nzData.raeume || [])[ri]) return '';
    var r = _nzData.raeume[ri];
    var nm = r.name || 'Raum';
    var f = r.f_m2, u = r.u_m, h = r.hoehe_m;
    var ex = function (v) { return v ? ' <span class="rw-ex">✓</span>' : ''; };
    var z = '<div class="rw-kopf"><strong>' + esc(nm) + '</strong>' +
      (r.status === 'verifiziert' || r.rohbau_ok || r.iou_bewiesen
        ? '<span class="rw-ok">geometrisch bestätigt</span>'
        : ((r._synthetic || r.region_geschaetzt)
          ? '<span class="rw-warn">Umriss geschätzt — bitte anpassen</span>' : '')) +
      '<button type="button" class="rw-zu" title="Schließen">&times;</button></div>';
    var _abwHtml = '';
    z += '<div class="rw-grid">';
    var zeile = function (lab, wert, einheit, exakt) {
      if (wert == null || wert === '') return '';
      return '<div class="rw-z"><span class="rw-l">' + lab + '</span>' +
        '<span class="rw-w">' + fmtNum(Math.round(wert * 100) / 100) + ' ' +
        einheit + ex(exakt) + '</span></div>';
    };
    z += zeile('Boden (=F)', f, 'm²', r.f_ist == null || r.status === 'verifiziert');
    // DER GEZEICHNETE UMRISS GEGEN DIE GERECHNETE ZAHL.
    //
    // Die Menge kommt aus dem byte-exakten Raumstempel; der Umriss am Plan
    // kommt aus der Rekonstruktion. Beim Flur des Referenzplans umschliesst
    // der gezeichnete Umriss 14,00 m², gestempelt sind 15,84 — 12 % weniger,
    // und nichts sagte das. Wer den Plan zum Pruefen benutzt, muss sehen,
    // wenn die Zeichnung und die Zahl nicht zusammenpassen: sonst prueft er
    // eine Flaeche, mit der gar nicht gerechnet wird.
    // Die Flaeche des GEZEICHNETEN Umrisses selbst rechnen, nicht r.f_ist
    // nehmen: das Feld enthaelt die Verifikations-Flaeche aus dem Raster,
    // nicht die des Polygons, das am Plan zu sehen ist. Am Referenzplan
    // weichen die beiden voneinander ab (Flur: f_ist 14,65 · Polygon 14,00 ·
    // Stempel 15,84) — der Hinweis haette an der falschen Zahl gehangen und
    // waere bei 7,5 % knapp unter der Schwelle stumm geblieben, obwohl der
    // sichtbare Umriss 11,6 % daneben liegt.
    var _fpoly = (r.region_px && r.region_px.length >= 3)
      ? _nzPolyFlaeche(r.region_px) : null;
    if (f && _fpoly && _fpoly > 0) {
      var _ab = Math.abs(_fpoly - f) / f * 100;
      if (_ab >= 8) {
        // NICHT ins Werte-Raster schreiben: dort wird der Kasten zu einer
        // Rasterzelle und quetscht Umfang/Höhe/Sockel zusammen. Erst
        // sammeln, dann UNTER dem Raster ausgeben.
        _abwHtml = '<div class="rw-abw">Der <strong>gezeichnete Umriss</strong> umschließt ' +
          fmtNum(Math.round(_fpoly * 100) / 100) + ' m² — ' +
          Math.round(_ab) + ' % ' + (_fpoly < f ? 'weniger' : 'mehr') +
          ' als der Raumstempel. <strong>Gerechnet wird mit ' + fmtNum(f) +
          ' m²</strong> (byte-exakt aus dem Plan-Text). Der Umriss ist hier ' +
          'nur der Zeigefinger — zum Nachmessen bitte ✏️ Raum bearbeiten.</div>';
      }
    }
    z += zeile('Umfang U', u, 'm', !r.umfang_geschaetzt);
    z += zeile('Höhe', h, 'm', true);
    if (f && u && h) z += zeile('Wandabwicklung U×H', u * h, 'm²', false);
    if (u) z += zeile('Sockel', u, 'lfm', false);
    z += '</div>' + _abwHtml;

    // Welche Positionen haengen an diesem Raum? Aus der Kreuztabelle, die
    // ohnehin schon gerechnet ist — kein zweiter Weg, keine zweite Wahrheit.
    var m = _lastMatrix;
    if (m && (m.raeume || []).length) {
      var _nk = function (x) { return _nrmRaum(x || ''); };
      var zeileR = (m.raeume || []).filter(function (x) {
        return _nk(x.raum) === _nk(nm);
      })[0];
      if (zeileR && zeileR.mengen) {
        var sp = {};
        (m.positionen || []).forEach(function (p) { sp[p.key] = p; });
        var items = Object.keys(zeileR.mengen).map(function (k) {
          var p = sp[k] || {};
          return { t: (p.posnr ? p.posnr + ' ' : '') +
            String(p.beschreibung || '').replace(/\s*—.*$/, ''),
            v: zeileR.mengen[k], e: p.einheit || '', g: p.gewerk_label || '' };
        }).sort(function (a, b) { return (b.v || 0) - (a.v || 0); });
        if (items.length) {
          z += '<div class="rw-pos-kopf">' + items.length +
            ' Positionen hängen an diesem Raum</div><div class="rw-pos">';
          items.forEach(function (it) {
            z += '<div class="rw-p"><span class="rw-pt">' + esc(it.t) + '</span>' +
              '<span class="rw-pg">' + esc(it.g) + '</span>' +
              '<span class="rw-pv">' + fmtNum(it.v) + ' ' + esc(it.e) + '</span></div>';
          });
          z += '</div>';
        }
      }
    }
    // BEARBEITEN AUFFINDBAR MACHEN: "Fläche verkleinern/verschieben, und die
    // Fläche rechnet mit" gibt es längst (✏️-Werkzeug: Eckpunkte ziehen,
    // F+U rechnen live, Übernahme in die Mengen) — aber als einer von sechs
    // Werkzeugknöpfen war es unsichtbar. Der Nutzer hat danach GEFRAGT,
    // während das Werkzeug auf der Seite stand. Darum steht der Einstieg
    // jetzt DORT, wo man mit dem Raum beschäftigt ist: im Werte-Feld.
    z += '<div class="rw-edit-hint"><button type="button" class="nz-btn" ' +
      'onclick="window._nzRaumEditStart&&window._nzRaumEditStart(' + ri + ')">' +
      '✏️ Umriss anpassen</button> <span>Eckpunkte ziehen — Fläche &amp; ' +
      'Umfang rechnen live, Übernahme geht in die Mengen.</span></div>';
    return '<div class="raum-werte" id="raum-werte">' + z + '</div>';
  }

  // Einstieg aus dem Werte-Feld: Editiermodus an + diesen Raum vorwählen.
  window._nzRaumEditStart = function (ri) {
    _nzRaumEditMode = true;
    _nzRaumSel = ri;
    _nzRaumInfo = null;
    _nzPaint();
    _nzRaumLiveReadout(ri);
    var w = document.querySelector('.nz-wrap');
    if (w) w.scrollIntoView({ behavior: 'smooth', block: 'center' });
  };
  window._nzRaumWerte = _nzRaumWerte;

  window.nzHighlightRaum = function (name, beleg) {
    var key = _nrmRaum(name);
    if (!key) return;
    _planBeleg(beleg || '');
    var sec = _wfZuPlan();
    if (sec) sec.scrollIntoView({ behavior: 'smooth', block: 'start' });
    var cont = document.getElementById('nachzeichnen-container');
    if (!cont) return;
    if (_nzWrap) {
      // FIT-CONTAIN statt Breiten-Fit (Live-Befund: "der untere Teil
      // fehlt schon wieder"): hohe Plaene wurden unten abgeschnitten.
      var _fitS = 1;
      try {
        var _iw = _nzWrap.querySelector('img, svg');
        var _dispH = (_nzData && _nzData.bild_h && _nzData.bild_w)
          ? _nzWrap.clientWidth * _nzData.bild_h / _nzData.bild_w : 0;
        if (_dispH > 0 && _nzWrap.clientHeight > 50 && _dispH > _nzWrap.clientHeight) {
          _fitS = Math.max(0.35, _nzWrap.clientHeight / _dispH);
        }
      } catch (e) {}
      _nzZoom = { s: _fitS, x: _fitS < 1 ? (_nzWrap.clientWidth * (1 - _fitS)) / 2 : 0, y: 0 };
      _nzApplyZoom();
    }
    var alle = cont.querySelectorAll('g[data-raum]');
    var sel = [];
    Array.prototype.forEach.call(alle, function (g) {
      g.classList.remove('nz-hi');
      var k = g.getAttribute('data-raum') || '';
      if (k === key || (k && (k.indexOf(key) === 0 || key.indexOf(k) === 0))) sel.push(g);
    });
    if (!sel.length) {
      // Ehrlich statt stumm: der Raum liegt auf einem anderen Blatt oder hat
      // keinen Marker. Vorher passierte hier gar nichts — der Nutzer sah nur
      // einen Sprung ins Nichts und wusste nicht, ob er sich verklickt hat.
      _markenWeg(cont);
      _planBeleg((beleg ? beleg + ' &middot; ' : '')
        + '<em>auf diesem Blatt nicht eingezeichnet — Blatt oben wechseln</em>');
      return;
    }
    _markenWeg(cont);
    var kurz = _kurzAusBeleg(beleg);
    sel.forEach(function (g) {
      g.classList.add('nz-hi');
      _planMarke(g, kurz);
    });
    // Das PULSEN hoert auf, die MARKE bleibt. Wer eine Menge prueft, schaut
    // erst auf die Zahl, dann auf den Plan, dann wieder auf die Zahl — eine
    // Beschriftung, die nach ein paar Sekunden verschwindet, zwingt zum
    // Nachklicken. Sie geht mit dem × der Beleg-Leiste oder mit der naechsten
    // geprueften Menge.
    setTimeout(function () {
      sel.forEach(function (g) { g.classList.remove('nz-hi'); });
    }, 3200);
  };
  // Kopplung Aufmaß-Zeile → Plan: die GEBÄUDE-HÜLLE (blaue Kontur) pulsieren
  // lassen — Beleg-Ort für flächige Mengen (Bodenplatte/Decke/WDVS/Gerüst).
  window.nzHighlightKontur = function () {
    var sec = _wfZuPlan();
    if (sec) sec.scrollIntoView({ behavior: 'smooth', block: 'start' });
    var cont = document.getElementById('nachzeichnen-container');
    if (!cont) return;
    var sel = cont.querySelectorAll('polyline');
    if (!sel.length) return;
    Array.prototype.forEach.call(sel, function (el) { el.classList.add('nz-hi'); });
    setTimeout(function () {
      Array.prototype.forEach.call(sel, function (el) { el.classList.remove('nz-hi'); });
    }, 3200);
  };
  // Kopplung Öffnungs-DATEN → Plan: eine Fenster-/Tür-Zeile anklicken →
  // der zugehörige Marker am Plan pulst (Traceability, beide Richtungen).
  // Match über Typ + nächstliegende Breite/Höhe (+ Raum, falls am Marker da).
  window.nzHighlightOeffnung = function (typ, raum, b, h, ohneMass) {
    var sec = _wfZuPlan();
    if (sec) sec.scrollIntoView({ behavior: 'smooth', block: 'start' });
    var cont = document.getElementById('nachzeichnen-container');
    if (!cont || !_nzData || !_nzData.oeffnungen) return;
    // ÖFFNUNGEN OHNE MASS lassen sich nicht über Breite×Höhe ansteuern —
    // sie haben ja keine. Sie sind aber genau die, bei denen kein
    // ÖNORM-Abzug möglich ist und die am Plan gestrichelt markiert sind.
    // Darum: ALLE masslosen Marker desselben Typs pulsen lassen.
    if (ohneMass) {
      if (_nzWrap) { _nzZoom = { s: 1, x: 0, y: 0 }; _nzApplyZoom(); }
      var n = 0;
      (_nzData.oeffnungen || []).forEach(function (o) {
        if (o.typ !== typ) return;
        if (o.breite_m && o.hoehe_m) return;          // hat ein Maß
        var gg = cont.querySelector('g[data-oid="' + o.id + '"]');
        if (!gg) return;
        n++;
        gg.classList.add('nz-hi-oeff');
        setTimeout(function () { gg.classList.remove('nz-hi-oeff'); }, 3400);
      });
      var o1 = document.getElementById('nz-mess-out');
      if (o1) {
        o1.innerHTML = n
          ? ('<strong>' + n + '</strong> ' + (typ === 'tuer' ? 'Türen' : 'Fenster')
             + ' ohne vollständiges Maß am Plan markiert — dort ist kein '
             + 'ÖNORM-Abzug möglich.')
          : '<strong style="color:#b45309">Keine masslose Öffnung auf diesem Blatt.</strong>';
      }
      return;
    }
    var key = _nrmRaum(raum || '');
    var best = null, bestd = 1e9;
    (_nzData.oeffnungen || []).forEach(function (o) {
      if (o.typ !== typ) return;
      var d = 0;
      if (b && o.breite_m) d += Math.abs(o.breite_m - b);
      if (h && o.hoehe_m) d += Math.abs(o.hoehe_m - h);
      // Marker mit passendem Raum bevorzugen (kleiner Bonus)
      if (key && o.raum && _nrmRaum(o.raum) === key) d -= 5;
      if (d < bestd) { bestd = d; best = o; }
    });
    if (!best) {
      var out = document.getElementById('nz-mess-out');
      if (out) out.innerHTML = '<strong style="color:#b45309">Diese Öffnung ist auf dem gezeigten Plan-Blatt nicht markiert — bitte das andere Plan-Blatt (Grundriss) wählen.</strong>';
      return;
    }
    if (_nzWrap) { _nzZoom = { s: 1, x: 0, y: 0 }; _nzApplyZoom(); }
    var g = cont.querySelector('g[data-oid="' + best.id + '"]');
    if (!g) return;
    g.classList.add('nz-hi-oeff');
    setTimeout(function () { g.classList.remove('nz-hi-oeff'); }, 3400);
  };
  // Kopplung Liste → Plan: die Wände einer HLZ-Stärke am Plan pulsieren lassen.
  function nzHighlight(cm) {
    var sec = _wfZuPlan();
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
    if (window._projModus === 'manuell' && reqBody) reqBody.leicht = true;
    fetch('/api/plan-nachzeichnen', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(reqBody)
    }).then(function (r) { return r.json(); }).then(function (d) {
      _nzGeladen = true;
      _mwLaden().then(function () { _nzPaint(); _mwErsthinweis(); }); _nzLaeuft = false;
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
      // Manueller Maßstab (Scan-Kalibrierung) VOR allem — macht den Plan metrisch,
      // bevor Regionen/Snapping abgeleitet werden.
      if (k && k.px_pro_m_manuell > 0) {
        _nzData.meta = _nzData.meta || {};
        _nzData.meta.px_pro_m_manuell = k.px_pro_m_manuell;
      }
      if (k && k.edit) {
        _nzEdit = { removed: k.edit.removed || {}, thick: k.edit.thick || {}, aussen: k.edit.aussen || {},
          added: k.edit.added || [], oeffRemoved: k.edit.oeffRemoved || {} };
        // manuell hinzugefügte Wände wieder in die Geometrie einspielen
        (_nzEdit.added || []).forEach(function (w) { _nzData.waende.push(w); });
        // Editierte Raumflächen (Polygon-Korrektur) zurück in den Override.
        var _ovr = _filterState.materialliste_override || {}, _rchg = false;
        if (k.raum_flaechen && Object.keys(k.raum_flaechen).length) {
          _ovr.raum_flaechen = k.raum_flaechen; _rchg = true;
        }
        // Wandlängen (byte-exakt/manuell) haben Vorrang; sonst die alte Prozent-Verteilung.
        if (k.wand_laengen_m) {   // absolute Wandlängen zurück in den Override
          _ovr.wand_laengen_m = k.wand_laengen_m;
          _ovr.wand_laengen_manuell = !!k.wand_laengen_manuell;
          _filterState.materialliste_override = _ovr;
          refreshProjektMassen();
        } else if (_rchg) {
          _filterState.materialliste_override = _ovr;
          refreshProjektMassen();
        } else if (k.anteile) {   // angewandte Verteilung zurück in den Override → Mengen stimmen wieder
          var ov = _filterState.materialliste_override || {}, changed = false;
          Object.keys(k.anteile).forEach(function (kk) { if (ov[kk] !== k.anteile[kk]) { ov[kk] = k.anteile[kk]; changed = true; } });
          if (changed) { _filterState.materialliste_override = ov; refreshProjektMassen(); }
        }
      }
      _nzBaueMessCluster();   // NACH dem Restore: legendenlose Pläne (Holzbau) → Stärke-Cluster
      _nzCleanRegionen();     // rekonstruierte Umrisse glätten (Treppen-Rauschen weg)
      _nzSynthRegionen();     // Räume ohne Polygon: editierbare Rechteck-Startform
      _nzSnapRegionen();      // ALLE (echt + geschätzt) auf die Wand-Fluchten rasten
      // HANDKORRIGIERTE UMRISSE zuletzt: sie sind die Wahrheit des Nutzers und
      // dürfen von Clean/Synth/Snap nicht angerührt werden — deshalb NACH allen
      // automatischen Schritten wiederherstellen.
      if (k && k.raum_regionen) {
        // PLAN-Koordinaten haben Vorrang: sie gelten auch, wenn sich der
        // Bildausschnitt seit dem Speichern geändert hat.
        var _bpN = (_nzData.meta || {}).box_pt, _scN = +(_nzData.meta || {}).scale;
        (_nzData.raeume || []).forEach(function (r) {
          var sav = k.raum_regionen[_nrmRaum(r.name || '')];
          if (sav && sav.region_pt && sav.region_pt.length >= 3 && _bpN && _scN > 0) {
            sav = { geschoss: sav.geschoss, region_px: sav.region_pt.map(function (p) {
              return [Math.round((p[0] - _bpN[0]) * _scN * 10) / 10,
                      Math.round((p[1] - _bpN[1]) * _scN * 10) / 10];
            }) };
          }
          if (sav && sav.region_px && sav.region_px.length >= 3 &&
              (sav.geschoss || null) === (r.geschoss || null)) {
            // Den erkannten Umriss als Original merken, BEVOR er ersetzt wird —
            // sonst hat "↺ Original" nach einem Reload nichts, worauf es
            // zurücksetzen könnte, und die Hand-Korrektur wäre unumkehrbar.
            r._region_orig = (r.region_px || []).map(function (p) { return [p[0], p[1]]; });
            r.region_px = sav.region_px.map(function (p) { return [p[0], p[1]]; });
            r._edited = true;
          }
        });
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
      var _hauptHint = d.typ === 'leicht'
        ? '✏️ <strong>Manuell-Modus</strong> — du misst selbst, die KI hat den Plan ' +
          'nicht analysiert. ' +
          ((d.meta || {}).ptm
            ? 'Maßstab <strong>' + esc((d.meta || {}).massstab || '?') +
              '</strong> byte-exakt gelesen — deine Messungen sind sofort in Metern.'
            : '<strong style="color:#0369a1">Setze zuerst den Maßstab</strong> (📐 — ' +
              'zwei Punkte einer bekannten Länge), dann rechnen alle Messungen in Meter.') +
          ((d.meta || {}).hinweis ? ' <span style="color:#6b7280">(' +
            esc(d.meta.hinweis) + ')</span>' : '') +
          ' · ' + (d.dateiname ? esc(d.dateiname) : '')
        : d.typ === 'scan'
        ? '🖼️ <strong>Scan / Bild-Plan</strong> (keine Vektoren). Die Räume sind aus dem Bild erkannt ' +
          '(<strong>gestrichelt = geschätzt</strong>, mit ✏️ Raum bearbeiten anpassen). ' +
          '<strong style="color:#0369a1">Setze zuerst den Maßstab</strong> (📐 — 2 Punkte einer bekannten Länge), ' +
          'dann sind Flächen/Längen in Metern. · ' + (d.dateiname ? esc(d.dateiname) : '')
        : 'Erkannte Wände, farbcodiert nach Stärke (gestrichelt = unsicher). ' +
          '<strong>Klicke eine Wand</strong>, um sie zu entfernen (keine Wand), die Stärke zu korrigieren oder 25cm außen/innen zu setzen. ' +
          (hatK ? '<strong style="color:#166534">✓ deine gespeicherten Korrekturen sind angewandt.</strong> ' : '') +
          'Maßstab ' + esc(meta.massstab || '?') + ' · Bereich ' + (meta.box_m ? meta.box_m[0] + '×' + meta.box_m[1] + ' m' : '?') +
          ' · ' + (d.dateiname ? esc(d.dateiname) : '');
      // PLATZ FÜR DEN PLAN: die lange Erklärzeile wandert in eine zuklappbare
      // Info-Zeile — der Editor ist das Werkzeug, nicht der Text darüber.
      // Beim Scan bleibt die eine entscheidende Ansage sichtbar: Maßstab setzen.
      cont.innerHTML = _nzTabsHtml() +
        '<details class="nz-planinfo"><summary>' +
        (d.typ === 'scan'
          ? '🖼️ Scan — <strong style="color:#0369a1">zuerst Maßstab 📐 setzen</strong> · Details'
          : d.typ === 'leicht'
            ? (meta.ptm
                ? '✏️ Manuell — Maßstab ' + esc(meta.massstab || '?') + ' gelesen · Details'
                : '✏️ Manuell — <strong style="color:#0369a1">zuerst Maßstab 📐 setzen</strong> · Details')
            : 'ℹ️ Plan-Infos · Maßstab ' + esc(meta.massstab || '?') + ' · Details') +
        '</summary><p class="nachzeichnen-hint">' + _hauptHint + '</p></details>' +
        (d.typ === 'scan' ? '' : '<div class="nz-seitenzeile">' + _nzSeitenHtml() + '</div>') +
        _nzBeweisStatus(d) +
        '<div class="nz-dynamic"></div>';
      _nzWireTabs(cont);
      _nzWireSeiten(cont);
      _nzPaint();
      // Scan (dichte Multi-View-Tafel): einmalig auf die erkannten Räume zoomen,
      // damit sie groß & sauber liegen. Nur beim ersten Laden dieses Blatts.
      if (d.typ === 'scan') setTimeout(function () { _nzFitToRooms(); }, 60);
      // Vektorplan: einmalig den GANZEN Plan ins Fenster holen. Zweimal
      // versetzt, weil das Bild beim ersten Lauf noch nicht geladen sein
      // muss — offsetHeight wäre dann 0 und die Einpassung liefe ins Leere.
      else {
        setTimeout(function () { _nzFitGanz(); }, 80);
        setTimeout(function () { _nzFitGanz(); }, 400);
      }
      // Analyse fertig + Plan überzeichnet → zuerst NUR die Planansicht zeigen
      // (statt der überladenen Gesamtansicht). Einmalig, respektiert Nutzer-Klick.
      if (typeof window.wfAutoPlan === 'function') window.wfAutoPlan();
    }).catch(function (e) {
      _nzGeladen = false; _nzLaeuft = false;
      cont.innerHTML = '<p class="nachzeichnen-hint">Nachzeichnen fehlgeschlagen: ' + esc(e.message) + '</p>';
    });
  }

  // Die Planansicht lädt automatisch nach der ersten Auswertung (renderNachzeichnen()
  // wird im Lade-Flow aufgerufen, der _nzGeladen-Guard hält es bei einem Fetch).
  // PLAN-SPRUNG (Runde 'Perfekt & ausgemistet'): jede M-Nummer in
  // Zuordnung/Protokoll fuehrt zum Plan — Schritt 2, Messung selektiert,
  // hingezoomt. Jede Zahl ist zwei Klicks vom Plan entfernt.
  // "SO MISST DU"-ERSTHINWEIS (Live-Befund 2026-08-20: der Werkzeug-
  // kasten wurde nicht als Hand-Editor erkannt). Einmal je Browser,
  // schliessbar; erklaert die drei Kerngesten in einer Zeile.
  function _mwErsthinweis() {
    // INTERAKTIVE TOUR statt Textkasten: sie zeigt AUF die echten Elemente
    // und lässt die Kern-Geste (Fläche messen) sofort selbst ausführen.
    // Startet automatisch einmal je Browser; ❓ Anleitung startet sie neu.
    if (window.Tour) { window.Tour.auto('aufmass'); return; }
    // Fallback ohne tour.js: der bewährte Einzeiler.
    try {
      if (localStorage.getItem('mw_hint_gesehen')) return;
    } catch (e) { return; }
    var el = document.createElement('div');
    el.id = 'mw-ersthinweis';
    el.innerHTML = '<strong>✏️ So misst du per Hand:</strong> ' +
      'Links <b>Fläche</b> wählen (oder Taste <b>F</b>) → Ecken am Plan ' +
      'anklicken → <b>Klick auf den Startpunkt schließt</b>. ' +
      '<b>Shift</b> = rechtwinklig · <b>Backspace</b> = Punkt zurück · ' +
      '<b>Strg+Z</b> = rückgängig · Messung anklicken = Ecken ziehen.' +
      '<button type="button" id="mw-hint-ok">Verstanden</button>';
    // _nzWrap ist das echte Canvas-Element (.nz-wrap) — die frei erfundene
    // id 'nz-canvas-wrap' existierte nicht: der Hinweis erschien NIE.
    var wrap = _nzWrap || document.querySelector('.nz-wrap');
    if (wrap && wrap.parentElement) {
      wrap.parentElement.insertBefore(el, wrap);
      document.getElementById('mw-hint-ok').addEventListener('click', function () {
        try { localStorage.setItem('mw_hint_gesehen', '1'); } catch (e) {}
        el.remove();
      });
    }
  }

  window.nzZeigeMessung = function (mid) {
    var m = (_mwListe || []).filter(function (x) { return x.id === mid; })[0];
    var fertig = function () {
      _mwSel = mid;
      var m2 = (_mwListe || []).filter(function (x) { return x.id === mid; })[0];
      _nzPaint();
      if (m2 && m2.geometrie && (m2.geometrie.punkte || []).length) {
        var pts = m2.geometrie.punkte.map(_mwPtZuPx);
        var xs = pts.map(function (q) { return q[0]; });
        var ys = pts.map(function (q) { return q[1]; });
        _nzZoomAufBereich((Math.min.apply(null, xs) + Math.max.apply(null, xs)) / 2,
                          (Math.min.apply(null, ys) + Math.max.apply(null, ys)) / 2);
      }
    };
    if (typeof wfShow === 'function') { _wfUserPicked = true; wfShow(2); }
    if (m || !mid) { fertig(); return; }
    // Messung eines anderen Plans: Plan wechseln, dann selektieren
    fetch('/api/messungen?projekt_id=' + encodeURIComponent(window.projectId))
      .then(function (r) { return r.json(); })
      .then(function (d) {
        var mm = ((d && d.messungen) || []).filter(function (x) { return x.id === mid; })[0];
        if (mm && mm.plan_id && mm.plan_id !== _nzAktivPlan) {
          _nzGeladen = false;
          renderNachzeichnen(mm.plan_id, mm.seite || undefined);
          setTimeout(fertig, 1500);
        } else fertig();
      });
  };
  function _nzZoomAufBereich(cx, cy) {
    if (!_nzWrap) return;
    var f = _nzWrap.clientWidth / (_nzData.bild_w || 1);
    var ziel = 1.6;
    _nzZoom.s = ziel;
    _nzZoom.x = _nzWrap.clientWidth / 2 - cx * f * ziel;
    _nzZoom.y = _nzWrap.clientHeight / 2 - cy * f * ziel;
    _nzApplyZoom();
  }
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

  // ── WORKFLOW-STEPPER: Pläne → Räume → Positionen → Zuordnung → Export ──
  // Die Reihenfolge, in der ein Aufmaß tatsächlich entsteht: erst der Plan,
  // dann die Räume verifizieren, daraus die Positionen, dann die Zuordnung
  // Position↔Raum (das ist der Prüf-Schritt) und zuletzt die Übergabe.
  // Schritt 2 ist der Default nach der Analyse — nichts wird gerechnet,
  // bevor die Räume stimmen.
  var WF_GRUPPEN = {
    1: ['#upload-section', '#plans-section'],
    // SCHRITT 2 IST DIE PLANANSICHT. Die Prüf-Kacheln standen hier daneben
    // und drängten den Plan nach unten; wer Räume prüfen will, braucht den
    // Plan gross, nicht eine Liste. Die Prüfpunkte bleiben in der Übersicht
    // und in Schritt 3 erreichbar.
    2: ['#nachzeichnen-section'],
    // SCHRITT 3 = ABRECHNUNG: Positionen + Zuordnung + Protokoll + Chat,
    // dazu die kompakte KI-Mengenermittlung (als Quelle fuer "Aus
    // Mengenermittlung uebernehmen"). Die uebrigen Analyse-Kacheln
    // (Pruefliste, Kennzahlen, Materialliste-Board, Drawer, Alt-Tabellen)
    // leben in Gruppe 9 — sie erscheinen NUR in der Uebersicht (Schritt 0
    // blendet nichts aus); in den Arbeitsschritten sind sie Laerm.
    3: ['#positionen-section', '#zuordnung-section', '#protokoll-section',
        '#mengen-board', '#projekt-chat'],
    9: ['#ergebnis-status-banner', '#zielgruppen-presets', '#geo-box',
        '#pruefliste', '#fact-strip', '.ml-board-toolbar', '#ml-board',
        '#konf-kopf', '#auswertung-kennzahlen', '.advanced-drawer',
        '#results-section']
  };
  function wfShow(step) {
    // Aufmass-Bereiche (Positionen/Zuordnung/Protokoll) beim Betreten frisch
    // laden — sie haengen an der DB, nicht am Analyse-Zustand.
    if (step >= 3 && window.renderAufmassBereiche) window.renderAufmassBereiche();
    // SCREEN-MODUS: jeder Schritt ist eine eigene Ansicht. Die Body-Klasse
    // steuert, was der Schritt NICHT zeigt (CSS .wf-s1 … .wf-s5) — z. B.
    // verdraengt der Ergebnis-Kopf in Schritt 1/2 sonst Upload bzw. Plan.
    for (var _ws = 0; _ws <= 5; _ws++) document.body.classList.remove('wf-s' + _ws);
    document.body.classList.add('wf-s' + step);

    // step 0 = ÜBERSICHT (Default): ALLES sichtbar — exakt die bisherige Seite.
    // Die Schritte 1-4 sind FOKUS-Ansichten (blenden fremde Gruppen aus) —
    // additiv: wer nichts klickt, verliert nichts.
    Object.keys(WF_GRUPPEN).forEach(function (s) {
      var an = step === 0 || String(step) === s;
      WF_GRUPPEN[s].forEach(function (sel) {
        document.querySelectorAll(sel).forEach(function (el) { el.classList.toggle('wf-hidden', !an); });
      });
    });
    document.querySelectorAll('#workflow-steps .wf-step').forEach(function (b) {
      b.classList.toggle('wf-on', b.getAttribute('data-wf') === String(step));
    });
    // Schritt 2 zeigt aus dem Ergebnis-Grid nur die Rail (Prüfliste) — Grid
    // einspaltig machen, sonst bleibt die ausgeblendete Hauptspalte als Loch stehen.
    var rg = document.querySelector('.result-grid');
    if (rg) rg.classList.remove('wf-rail-only');
    // Schritt 2: der Plan bekommt die volle Hoehe.
    var _ns = document.getElementById('nachzeichnen-section');
    if (_ns) _ns.classList.toggle('nz-plan-gross', step === 2);
    // LEERZUSTAND JE SCHRITT (Umbau 2026-08-18): statt leerer Flaeche ein
    // Satz, was fehlt, und ein Knopf dorthin. Signale aus dem Modul-Zustand
    // (_nzPlaene = analysierte Plaene, _mwListe = Messungen).
    var _hint = document.getElementById('wf-hint');
    if (_hint) {
      var _htxt = '';
      if (step === 2 && !(_nzPlaene && _nzPlaene.length) && !_nzLaeuft && !_nzData) {
        _htxt = 'Hier erscheint der Plan mit den KI-Vorschlägen, sobald einer ' +
          'analysiert ist. <button type="button" class="btn btn-sm btn-accent" ' +
          'data-wf-go="1">Plan hochladen</button>';
      } else if (step === 3 && !(_mwListe && _mwListe.length) &&
                 !(_nzPlaene && _nzPlaene.length)) {
        _htxt = 'Für die Abrechnung braucht es Messungen. ' +
          '<button type="button" class="btn btn-sm btn-accent" data-wf-go="1">' +
          'Plan hochladen</button> <button type="button" class="btn btn-sm" ' +
          'data-wf-go="2">Zum Aufmaß</button>';
      }
      _hint.innerHTML = _htxt;
      _hint.style.display = _htxt ? '' : 'none';
      _hint.querySelectorAll('[data-wf-go]').forEach(function (b) {
        b.addEventListener('click', function () {
          _wfUserPicked = true;
          wfShow(parseInt(b.getAttribute('data-wf-go'), 10));
        });
      });
    }
    if (step === 1) {
      var up = document.getElementById('upload-section');
      if (up) up.scrollIntoView({ behavior: 'smooth', block: 'start' });
    } else if (step === 2) {
      if (typeof _nzApplyZoom === 'function') _nzApplyZoom();
      var nz = document.getElementById('nachzeichnen-section');
      if (nz) nz.scrollIntoView({ behavior: 'smooth', block: 'start' });
    } else if (step === 3) {
      var po = document.getElementById('positionen-section');
      if (po) po.scrollIntoView({ behavior: 'smooth', block: 'start' });
    } else if (step === 4) {
      var zu = document.getElementById('zuordnung-section');
      if (zu) zu.scrollIntoView({ behavior: 'smooth', block: 'start' });
    } else if (step === 5) {
      // Die Export-Knöpfe stehen im Kopf und bleiben in jedem Schritt sichtbar
      // (eine Hauptaktion darf nicht verschwinden) — Schritt 5 führt hin.
      var ex = document.querySelector('.export-group');
      if (ex) ex.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }
    // Ansicht gewechselt → eine noch laufende Tour zeigt auf ausgeblendete
    // Elemente (live gesehen beim Auto-Sprung Plan→Aufmaß): sauber beenden.
    if (window.Tour && window._wfStep != null && window._wfStep !== step) window.Tour.stopp();
    window._wfStep = step;
    // INTERAKTIVE ANLEITUNG: je Schritt einmal automatisch starten
    // (❓ Anleitung startet sie jederzeit neu). Schritt 2 erst, wenn der
    // Plan wirklich da ist — sonst zeigte die Tour auf leere Fläche;
    // dieser Fall läuft über _mwErsthinweis nach dem ersten Paint.
    if (window.Tour) {
      var _tn = { 0: 'uebersicht', 1: 'plan', 3: 'abrechnung' }[step];
      if (step === 2 && _nzData) _tn = 'aufmass';
      if (_tn) window.Tour.auto(_tn);
    }
  }
  var _wfUserPicked = false;   // hat der Nutzer selbst einen Schritt gewählt?
  var _wfAutoDone = false;     // Auto-Sprung zur Planansicht schon passiert?
  window.wfShow = wfShow;
  // Nach abgeschlossener Analyse zuerst NUR den überzeichneten Plan zeigen
  // (nicht die überladene Gesamtansicht) — einmalig, und nur solange der
  // Nutzer nicht selbst einen Schritt gewählt hat.
  window.wfAutoPlan = function () {
    if (_wfUserPicked || _wfAutoDone) return;
    _wfAutoDone = true;
    wfShow(2);
  };
  (function wireWorkflow() {
    var bar = document.getElementById('workflow-steps');
    if (!bar) return;
    bar.querySelectorAll('.wf-step[data-wf]').forEach(function (b) {
      b.addEventListener('click', function () {
        _wfUserPicked = true;
        wfShow(parseInt(b.getAttribute('data-wf'), 10));
      });
    });
    // ❓ ANLEITUNG: startet die interaktive Tour des aktiven Schritts neu.
    var tb = document.getElementById('tour-btn');
    if (tb) tb.addEventListener('click', function () {
      if (!window.Tour) return;
      var s = window._wfStep || 0;
      window.Tour.start(s === 2 ? 'aufmass'
        : ({ 0: 'uebersicht', 1: 'plan', 3: 'abrechnung' }[s] || 'plan'));
    });
    // Start im ARBEITSABLAUF (digiplan-Vorbild), nicht in der Übersicht:
    // Schritt 1 (Plan). Sobald ein Plan analysiert & nachgezeichnet ist,
    // springt wfAutoPlan einmalig auf Schritt 2 (Aufmaß).
    wfShow(1);
  })();

  // ── ZIELGRUPPEN-PRESETS: gleiche Daten, passende Sicht je Branche-Bereich ──
  var ZG_GEWERKE = {
    rohbau: ['rohbau', 'beton', 'erdarbeiten'],   // Baumeister: Erdbau/Mauerwerk/Beton + Materialliste
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
      // SEKTORRICHTIGER PRIMÄR-EXPORT: Polier/Rohbau bestellt (Materialliste),
      // Ausbau/Kalkulant rechnet ab (Aufmaß .xlsx) — der Akzent wandert mit.
      var bMl = document.getElementById('projekt-export-btn');
      var bXl = document.getElementById('projekt-xlsx-btn');
      if (bMl && bXl) {
        var mlPrimaer = preset === 'rohbau';
        bMl.classList.toggle('btn-accent', mlPrimaer);
        bMl.classList.toggle('btn-outline', !mlPrimaer);
        bXl.classList.toggle('btn-accent', !mlPrimaer);
        bXl.classList.toggle('btn-outline', mlPrimaer);
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
