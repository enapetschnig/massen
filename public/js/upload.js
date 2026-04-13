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
      renderPlans(res.data || []);
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

      card.innerHTML =
        '<div class="plan-info"><div class="plan-icon">&#128196;</div><div>' +
          '<div class="plan-name">' + esc(plan.dateiname || '') + '</div>' +
          '<div class="plan-status"><span class="badge ' + (done ? 'badge-fertig' : 'badge-neu') + '">' + (done ? 'Fertig' : 'Hochgeladen') + '</span>' + konfBadge + '</div>' +
        '</div></div>' +
        '<div class="plan-actions">' +
          '<span style="font-size:0.75rem;color:#666">Geschosse:</span>' +
          '<input type="number" class="form-control geschoss-input" data-id="' + plan.id + '" value="3" min="1" max="10" style="width:60px" title="Anzahl Geschosse">' +
          '<span style="font-size:0.75rem;color:#666">Whg/OG:</span>' +
          '<input type="number" class="form-control whg-og-input" data-id="' + plan.id + '" value="4" min="1" max="10" style="width:60px" title="Wohnungen pro OG">' +
          '<select class="form-control gewerk-select" data-id="' + plan.id + '">' +
            '<option value="allgemein">Allgemein (alle Gewerke)</option>' +
            '<option value="verputzer">Verputzer / Spachtelarbeiten (VP/SR)</option>' +
            '<option value="mauerwerk">Mauerwerk / Rohbau</option>' +
            '<option value="maler">Maler / Anstrich</option>' +
            '<option value="fliesen">Fliesen / Bel\u00e4ge</option>' +
            '<option value="estrich">Estrich</option>' +
            '<option value="trockenbau">Trockenbau</option>' +
            '<option value="zimmerer">Zimmerer / Dach</option>' +
          '</select>' +
          (done
            ? '<button class="btn btn-primary btn-sm res-btn" data-id="' + plan.id + '">Ergebnisse</button>' +
              '<button class="btn btn-outline btn-sm reana-btn" data-id="' + plan.id + '">Neu analysieren</button>'
            : '<button class="btn btn-accent btn-sm ana-btn" data-id="' + plan.id + '">Analyse starten</button>') +
          '<button class="btn-delete-plan" data-id="' + plan.id + '">&times;</button>' +
        '</div>';
      planList.appendChild(card);
    });

    // Ergebnisse-Button
    planList.querySelectorAll('.res-btn').forEach(function (b) {
      b.addEventListener('click', function () {
        if (window.loadResults) window.loadResults(this.getAttribute('data-id'));
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
  function startAnalysis(planId, btn) {
    btn.disabled = true;
    btn.textContent = 'KI analysiert...';

    var gewerk = document.querySelector('.gewerk-select[data-id="'+planId+'"]').value;
    var geschosse = parseInt(document.querySelector('.geschoss-input[data-id="'+planId+'"]').value) || 3;
    var whg_pro_og = parseInt(document.querySelector('.whg-og-input[data-id="'+planId+'"]').value) || 4;

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

    // Extract text from PDF first (server-side pdfplumber for accuracy)
    if (progressStatus) progressStatus.textContent = 'PDF-Texte extrahieren (pdfplumber)...';
    if (analysisBar) { analysisBar.style.width = '5%'; analysisBar.textContent = '5%'; }

    fetch('/api/extract', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ plan_id: planId })
    })
      .then(function(res) {
        return res.json().then(function(data) {
          if (data.error) console.warn('Extraktion:', data.error);
          console.log('Extraktion:', data.rooms_grouped || 0, 'Räume,', data.dimensions || 0, 'Maße');
          return data;
        });
      })
      .then(function() {
        // Server hat die Daten bereits in agent_log gespeichert
        // Step 1: Parser + Geometrie
        setStepActive(0);
        if (progressStatus) progressStatus.textContent = 'Schritt 1/3: PDF wird analysiert...';
        if (analysisBar) { analysisBar.style.width = '10%'; analysisBar.textContent = '10%'; }
        return callStep(1);
      })
      .then(function (r1) {
        setStepDone(0); setStepActive(1);
        if (progressStatus) progressStatus.textContent = 'Schritt 2/3: Massen werden berechnet... (' + r1.raeume + ' Räume, ' + r1.fenster + ' Fenster)';
        if (analysisBar) { analysisBar.style.width = '40%'; analysisBar.textContent = '40%'; }
        return callStep(2);
      })
      .then(function (r2) {
        setStepDone(1); setStepActive(2);
        if (progressStatus) progressStatus.textContent = 'Schritt 3/3: Qualitätsprüfung... (' + r2.massen + ' Positionen)';
        if (analysisBar) { analysisBar.style.width = '70%'; analysisBar.textContent = '70%'; }
        return callStep(3);
      })
      .then(function (r3) {
        setStepDone(2); setStepDone(3);
        if (analysisBar) { analysisBar.style.width = '100%'; analysisBar.textContent = '100%'; }
        if (progressStatus) progressStatus.textContent = 'Analyse abgeschlossen! Konfidenz: ' + r3.konfidenz + '%';
        setTimeout(function () {
          hideProgress();
          if (window.loadResults) window.loadResults(planId);
          loadPlans();
        }, 1200);
      })
      .catch(function (err) {
        hideProgress();
        btn.disabled = false;
        btn.textContent = 'Analyse starten';
        if (analysisError) { analysisError.textContent = 'Fehler: ' + err.message; analysisError.classList.remove('hidden'); }
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

  function doUpload(files, idx) {
    if (idx >= files.length) {
      uploadProgress.classList.add('hidden');
      uploadBar.style.width = '0%';
      fileInput.value = '';
      loadPlans();
      return;
    }
    var file = files[idx];
    var path = firma.id + '/' + projectId + '/' + Date.now() + '_' + file.name;
    uploadBar.style.width = '50%';
    uploadBar.textContent = 'Hochladen...';

    _sb.storage.from('plaene').upload(path, file, { contentType: 'application/pdf' })
      .then(function (r) {
        if (r.error) throw new Error(r.error.message);
        return _sb.from('plaene').insert({ projekt_id: projectId, dateiname: file.name, storage_path: path });
      })
      .then(function () {
        uploadBar.style.width = '100%';
        uploadBar.textContent = '100%';
        setTimeout(function () { doUpload(files, idx + 1); }, 300);
      })
      .catch(function (err) {
        if (analysisError) {
          analysisError.textContent = 'Upload-Fehler: ' + err.message;
          analysisError.classList.remove('hidden');
        }
        uploadProgress.classList.add('hidden');
        loadPlans();
      });
  }

  window.loadPlans = loadPlans;
  window.projectId = projectId;
  loadPlans();
})();
