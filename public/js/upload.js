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
    if (konf >= 0.7) return { cls: 'hoch', title: 'Byte-exakt aus Plan + Bauteil-Legende oder gemessener Geometrie' };
    if (konf >= 0.5) return { cls: 'mittel', title: 'Gemessene Geometrie + bauphysikalische Standard-Annahme' };
    return { cls: 'niedrig', title: 'Faustformel / Pauschale — am Bau gegenprüfen' };
  }

  // FACT-STRIP: zeigt knapp, was die App byte-exakt aus dem Plan gelesen hat
  function renderFactStrip(data) {
    var el = document.getElementById('fact-strip');
    if (!el) return;
    var bd = data.baudaten || {}, bq = bd._quellen || {}, g = data.gemessen || {};
    var facts = [];
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
    bdFact('🧱', 'Außenwand', 'aussenwand_cm', ' cm');
    bdFact('▦', 'Decke', 'decke_cm', ' cm');
    bdFact('🟫', 'Bodenplatte', 'bodenplatte_cm', ' cm');
    bdFact('📏', 'Geschoss-H', 'geschosshoehe_m', ' m');
    if (g.aussenumfang_m) facts.push('<div class="fact" title="Gemauerte Hülle — Basis für das Mauerwerk"><span class="fact-ico">📐</span><span class="fact-k">Außenumfang</span><span class="fact-v">' +
      fmtNum(g.aussenumfang_m) + ' m</span><span class="fact-src measured">gemessen</span></div>');
    if (g.fundament_umfang_m && g.fundament_umfang_m > (g.aussenumfang_m || 0) + 0.05) {
      var eins = (g.fundament_einschluss || []).join(', ');
      facts.push('<div class="fact" title="Bodenplatten-Außenkante für Frostschürze/Randabschluss' +
        (eins ? ' — inkl. ' + esc(eins) : '') + '"><span class="fact-ico">🔲</span><span class="fact-k">Fundamentkante</span><span class="fact-v">' +
        fmtNum(g.fundament_umfang_m) + ' m</span><span class="fact-src measured">gemessen</span></div>');
    }
    if (g.bodenplatte_flaeche_m2) facts.push('<div class="fact"><span class="fact-ico">⬛</span><span class="fact-k">Grundfläche</span><span class="fact-v">' +
      fmtNum(g.bodenplatte_flaeche_m2) + ' m²</span><span class="fact-src measured">gemessen</span></div>');
    var fen = data.fenster_count || 0, tur = data.tueren_count || 0;
    if (fen || tur) facts.push('<div class="fact"><span class="fact-ico">🪟</span><span class="fact-k">Öffnungen</span><span class="fact-v">' +
      fen + ' F · ' + tur + ' T</span><span class="fact-src read">aus Text</span></div>');
    // Schnitt-/Ansichts-Lesung: Säulen + Dachtyp
    var sv = data.schnitt || {};
    if (data.saeulen_erkannt) facts.push('<div class="fact" title="aus Schnitt/Ansicht erkannt — in der Materialliste berücksichtigt"><span class="fact-ico">🏛️</span><span class="fact-k">Säulen</span><span class="fact-v">' +
      data.saeulen_erkannt + '</span><span class="fact-src measured">aus Schnitt</span></div>');
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
      if (gq.umfang_validiert) { cls = 'ok2'; mark = '✓✓'; note = 'gemauerte Hülle — Kettenbemaßung bestätigt (Σ = Gesamtmaß)'; }
      else if (gq.umfang_verdacht_niedrig) { cls = 'warn'; mark = '⚠'; note = 'wirkt zu niedrig für die Grundfläche — am Plan prüfen / Umfang setzen'; }
      else if (gq.cross_check_warnung) { cls = 'warn'; mark = '⚠'; note = 'Quellen uneinig — am Plan prüfen'; }
      else { cls = 'ok'; mark = '✓'; note = 'gemauerte Hülle (für Mauerwerk)'; }
      if (opusGarage.length && gq.opus_mauerwerk_zusatz_m) {
        note += ' · inkl. ' + esc(opusGarage.join(', ')) + ' als gemauert erkannt (+' +
          fmtNum(gq.opus_mauerwerk_zusatz_m) + ' m, Schnitt)';
      }
      t.push(tile('📐', 'Außenumfang', fmtNum(g.aussenumfang_m) + ' m', cls, mark, note));
    }
    if (g.bodenplatte_flaeche_m2) t.push(tile('⬛', 'Grundfläche', fmtNum(g.bodenplatte_flaeche_m2) + ' m²',
      'ok2', '✓✓', gq.flaeche_anker || 'byte-exakt aus Raumflächen'));
    if (g.fundament_umfang_m) {
      if (gq.fundament_unsicher) {
        t.push(tile('🔲', 'Fundamentkante', fmtNum(g.fundament_umfang_m) + ' m', 'warn', '⚠',
          (gq.ueberdachte_flaechen || '') + ' überdachte Fläche(n) — Platte läuft mglw. weiter, im Polierplan prüfen / Umfang setzen'));
      } else if (gq.opus_slab_aktiv) {
        t.push(tile('🔲', 'Fundamentkante', fmtNum(g.fundament_umfang_m) + ' m', 'ok', '✓',
          'Platte läuft unter Anbau weiter — vom Bauingenieur-Pass aus dem Schnitt belegt'));
      } else if (gq.linie_b_erkannt) {
        t.push(tile('🔲', 'Fundamentkante', fmtNum(g.fundament_umfang_m) + ' m', 'ok', '✓', 'inkl. angebauter überdachter Fläche'));
      } else {
        t.push(tile('🔲', 'Fundamentkante', fmtNum(g.fundament_umfang_m) + ' m', 'grey', '=', '= Außenkante (kein Überstand)'));
      }
    }
    if (bd.geschosshoehe_m) {
      var ghEntry = dc.filter(function (d) { return d.key === 'geschosshoehe_m'; })[0];
      var ghSrc;
      if (ghEntry && ghEntry.status === 'bestätigt') {
        ghSrc = (ghEntry.quellen || []).map(function (q) { return esc(q.quelle); }).join(' + ') + ' — unabhängig bestätigt';
      } else if (ghEntry && ghEntry.status === 'verstaerkt') {
        ghSrc = 'mehrfach gelesen (gleiche Methode) — nicht unabhängig bestätigt';
      } else {
        ghSrc = (bd._quellen || {}).geschosshoehe_m || 'aus Plan';
      }
      t.push(tile('📏', 'Geschoss-Höhe', fmtNum(bd.geschosshoehe_m) + ' m',
        ghOk ? 'ok2' : 'ok', ghOk ? '✓✓' : '✓', ghSrc));
    }
    el.innerHTML = t.join('');
  }

  // STATUS-BANNER: nur Hinweise, bei denen der Nutzer etwas tun kann/sollte
  function renderStatusBanner(data) {
    var statusEl = document.getElementById('ergebnis-status-banner');
    if (!statusEl) return;
    var hints = [];
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
      function methodLabel(t) { return t === 'text' ? 'Plan-Text (byte-exakt)' : 'Plan-Bild (Vision)'; }
      var typeSet = {};
      bestaetigt.forEach(function (d) { (d.quellen || []).forEach(function (q) { if (q.typ) typeSet[q.typ] = 1; }); });
      var methods = Object.keys(typeSet).map(methodLabel);
      var methodTxt = methods.length ? methods.join(' × ') : 'zwei Methoden';
      hints.push('<div class="status-ok">✓✓ <strong>' + bestaetigt.length +
        ' Wert(e) unabhängig bestätigt</strong> (' + bestaetigt.map(function (d) { return esc(d.groesse); }).join(', ') +
        ') — aus ' + esc(methodTxt) + ' gelesen (zwei unabhängige Methoden), sehr hohe Konfidenz.</div>');
    }
    if (verstaerkt.length) {
      hints.push('<div class="status-info">ℹ ' + verstaerkt.length +
        ' Wert(e) mehrfach gelesen (' + verstaerkt.map(function (d) { return esc(d.groesse); }).join(', ') +
        '), aber mit derselben Methode (zwei Bild-Lesungen) — das ist Redundanz, keine unabhängige Bestätigung. ' +
        'Für volle Sicherheit fehlt eine Text-/Plan-Quelle.</div>');
    }
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
        ' als Mauerwerk erkannt</strong> — im Grundriss „überdacht", im Schnitt aber rundum gemauert. ' +
        '+' + fmtNum(gq.opus_mauerwerk_zusatz_m) + ' m Außenwand in die Mauerwerks-Hülle übernommen ' +
        '(Bauingenieur-Pass, gegen die Maßketten geprüft).</div>');
    }
    if (gq.opus_slab_aktiv) {
      hints.push('<div class="status-ok">✓ <strong>Bodenplatte läuft unter den Anbau weiter</strong> — ' +
        'der Bauingenieur-Pass belegt die durchgehende Platte aus dem Schnitt; Fundamentkante entsprechend gesetzt.</div>');
    }
    if (data.opus_status === 'fehler') {
      hints.push('<div class="status-info">ℹ <strong>Bauingenieur-Pass nicht verfügbar</strong> — die ganzheitliche ' +
        'Schnitt-Lesung (Garage/Höhe/Dach) ist diesmal ausgefallen (API-Fehler). Die byte-exakten Werte und die ' +
        'übrigen Lesungen sind davon unberührt; nur die Garage-/Anbau-Erkennung fehlt ggf.</div>');
    }
    var fen = data.fenster_count || 0, tur = data.tueren_count || 0;
    if (fen === 0 && tur === 0) {
      hints.push('<div class="status-warn">⚠ <strong>0 Öffnungen erkannt</strong> — Laibungen, Rolladenkästen und Überlagen werden pauschal geschätzt.</div>');
    }
    if (data.halluzinationen && data.halluzinationen.length) {
      hints.push('<div class="status-info">🧹 ' + data.halluzinationen.length + ' Vision-Halluzination(en) automatisch gefiltert: ' +
        data.halluzinationen.map(function (h) { return esc(h.name); }).join(', ') + '</div>');
    }
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
    statusEl.innerHTML = hints.join('');
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
    renderStatusBanner(data);
    renderKalibrierungStatus(data.kalibrierung);

    // ÖNORM-Gewerke-Kacheln (im Erweitert-Drawer)
    var gw = data.gewerke || {};
    var cards = [];
    Object.keys(gw).forEach(function (gk) {
      var g = gw[gk];
      var label = (g.label || gk).replace(/\s*\(.*\)/, '');
      (g.positionen || []).forEach(function (p) {
        if (p.posnr === '1.1' || p.posnr === '1.2' || p.posnr === '1.3') {
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

    // Rechenweg-Toggle einmalig binden → bei Änderung neu rendern
    var tog = document.getElementById('ml-formel-toggle');
    if (tog && !tog.dataset.bound) {
      tog.dataset.bound = '1';
      tog.addEventListener('change', function () { renderMaterialliste(_lastML, _lastGemessen); });
    }

    if (!ml || ml.error || !ml.bauteile) {
      board.innerHTML = '<div class="ml-empty">Noch keine Materialliste — die Pläne enthalten noch keine vollständigen Raumdaten.</div>';
      if (ringNum) ringNum.textContent = '–';
      return;
    }

    var showFormel = !!(tog && tog.checked);
    var totalPos = 0, sicherPos = 0;
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
    groups.forEach(function (grp) {
      var gtier = grp.avg >= 0.7 ? 'hoch' : (grp.avg >= 0.5 ? 'mittel' : 'niedrig');
      html += '<section class="ml-group tier-' + gtier + '">';
      html += '<header class="ml-group-head"><span class="ml-group-ico">' + bauteilIcon(grp.bauteil) + '</span>' +
        '<span class="ml-group-name">' + esc(grp.bauteil) + '</span>' +
        '<span class="ml-group-meta">' + grp.rows.length + ' Position' + (grp.rows.length === 1 ? '' : 'en') + '</span></header>';
      html += '<div class="ml-rows">';
      grp.rows.forEach(function (p) {
        totalPos++;
        var konf = p.konfidenz || 0;
        if (konf >= 0.7) sicherPos++;
        var tier = konfTier(konf);
        html += '<div class="ml-row">' +
          '<span class="ml-dot ' + tier.cls + '" title="' + tier.title + ' (' + Math.round(konf * 100) + '%)"></span>' +
          '<span class="ml-mat">' + esc(p.material || '') +
            (showFormel && p.formel ? '<span class="ml-formel">' + esc(p.formel) + '</span>' : '') +
          '</span>' +
          '<span class="ml-qty">' + fmtNum(p.menge) + ' <em>' + esc(p.einheit || '') + '</em></span>' +
          '</div>';
      });
      html += '</div></section>';
    });
    board.innerHTML = html;

    // Trust-Ring: Anteil verlässlicher (byte-exakt/gemessener) Positionen
    var pct = totalPos ? Math.round(sicherPos / totalPos * 100) : 0;
    if (ringNum) ringNum.textContent = pct + '%';
    if (ring) {
      ring.style.setProperty('--ring-pct', pct);
      ring.classList.remove('low', 'mid', 'high');
      ring.classList.add(pct >= 75 ? 'high' : (pct >= 50 ? 'mid' : 'low'));
      ring.title = sicherPos + ' von ' + totalPos + ' Positionen byte-exakt aus Plan/Legende oder gemessener Geometrie (≥ 70% Konfidenz)';
    }

    // HERO-Status: 3-stufiges Bau-Signal statt nacktem Prozent
    var statusEl = document.getElementById('result-hero-status');
    if (statusEl) {
      statusEl.classList.remove('st-green', 'st-yellow', 'st-red');
      if (pct >= 75) { statusEl.textContent = '✓ Material bereit zum Bestellen'; statusEl.classList.add('st-green'); }
      else if (pct >= 50) { statusEl.textContent = '⚠ Vor Bestellung Geometrie prüfen'; statusEl.classList.add('st-yellow'); }
      else { statusEl.textContent = '⛔ Plan nachprüfen — Daten noch unsicher'; statusEl.classList.add('st-red'); }
    }
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

  // ── SELBST-KALIBRIERUNG (Moat) ──────────────────────────────────────────
  function renderKalibrierungStatus(kal) {
    var el = document.getElementById('kalibrierung-status');
    if (!el) return;
    var n = (kal && kal.anzahl) || 0;
    if (n > 0) {
      el.innerHTML = '<span class="kalib-badge kalib-on">&#10003; kalibriert &mdash; ' + n +
        ' firmenspezifische' + (n === 1 ? 'r Faktor' : ' Faktoren') + ' aktiv</span>';
    } else {
      el.innerHTML = '<span class="kalib-badge kalib-off">noch nicht kalibriert &mdash; Standard-Faktoren</span>';
    }
  }

  function kalibFaktorLabel(k) {
    var m = { bodenplatte_aufschlag: 'Bodenplatte-Aufschlag', decke_aufschlag: 'Decke-Aufschlag',
      frostgraben_aufschlag: 'Frostschürze-Aufschlag', aussenumfang_aufschlag: 'Außenumfang-Aufschlag',
      ekv_decke_aufschlag: 'Dachabdichtung-Aufschlag' };
    return m[k] || k;
  }

  function renderKalibrierungResult(r) {
    var el = document.getElementById('kalibrierung-result');
    if (!el) return;
    if (r.error) { el.innerHTML = '<div class="status-warn">⚠ ' + esc(r.error) + '</div>'; return; }
    var html = '<div class="status-ok">✓ ' + (r.soll_positionen || 0) + ' Soll-Positionen abgeglichen · ' +
      (r.anzahl_soll_listen || 0) + ' Liste(n) gesamt.</div>';
    var bel = r.belege || [];
    if (bel.length) {
      html += '<table class="kalib-table"><thead><tr><th>Faktor</th><th>Ist</th><th>Soll</th><th>Verhältnis</th></tr></thead><tbody>';
      bel.forEach(function (b) {
        var pct = Math.round((b.ratio - 1) * 100);
        var sign = pct > 0 ? '+' : '';
        html += '<tr><td>' + esc(kalibFaktorLabel(b.faktor)) + '</td><td>' + fmtNum(b.ist) +
          '</td><td>' + fmtNum(b.soll) + '</td><td>' + sign + pct + '%</td></tr>';
      });
      html += '</tbody></table>';
    }
    var gl = r.gelernte_faktoren || {};
    var keys = Object.keys(gl);
    if (keys.length) {
      html += '<div class="status-ok" style="margin-top:.4rem"><strong>Gelernte Faktoren (≥2 Listen):</strong> ' +
        keys.map(function (k) { return esc(kalibFaktorLabel(k)) + ' = ' + fmtNum(gl[k].wert) + ' (aus ' + gl[k].n_belege + ')'; }).join(' · ') + '</div>';
    } else if (r.hinweis) {
      html += '<div class="status-info" style="margin-top:.4rem">ℹ ' + esc(r.hinweis) + '</div>';
    }
    el.innerHTML = html;
  }

  function wireKalibrierung() {
    var up = document.getElementById('kalibrierung-upload');
    var rs = document.getElementById('kalibrierung-reset');
    if (up) up.addEventListener('click', function () {
      var txt = (document.getElementById('kalibrierung-soll') || {}).value || '';
      if (!txt.trim()) { renderKalibrierungResult({ error: 'Bitte eine Soll-Liste einfügen.' }); return; }
      up.disabled = true; up.textContent = 'Lerne…';
      fetch('/api/kalibrierung-upload', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ projekt_id: projectId, soll_text: txt })
      }).then(function (res) { return res.json().then(function (j) { return { ok: res.ok, j: j }; }); })
        .then(function (o) {
          renderKalibrierungResult(o.ok ? o.j : { error: (o.j && o.j.detail) || 'Upload fehlgeschlagen' });
          if (o.ok) refreshProjektMassen();  // Materialliste mit der neuen Kalibrierung neu laden
        })
        .catch(function (e) { renderKalibrierungResult({ error: String(e) }); })
        .finally(function () { up.disabled = false; up.textContent = 'Soll-Liste abgleichen & lernen'; });
    });
    if (rs) rs.addEventListener('click', function () {
      if (!confirm('Firmen-Kalibrierung wirklich zurücksetzen? (globale Basis bleibt)')) return;
      fetch('/api/kalibrierung-reset', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ projekt_id: projectId })
      }).then(function (res) { return res.json(); })
        .then(function () { renderKalibrierungStatus({ anzahl: 0 });
          document.getElementById('kalibrierung-result').innerHTML = '<div class="status-info">Kalibrierung zurückgesetzt.</div>';
          refreshProjektMassen(); });
    });
  }
  wireKalibrierung();

  window.loadPlans = loadPlans;
  window.projectId = projectId;
  loadPlans();
})();
