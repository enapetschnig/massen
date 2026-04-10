/**
 * KI-Massenermittlung - Upload & Plans (direkt via Supabase)
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

  if (firma.name && companyNameEl) companyNameEl.textContent = firma.name;
  if (logoutBtn) logoutBtn.addEventListener('click', function () { clearSession(); window.location.href = 'index.html'; });

  _sb.from('projekte').select('*').eq('id', projectId).single().then(function (res) {
    if (res.data) {
      projectNameEl.textContent = res.data.name || '';
      projectAddressEl.textContent = res.data.adresse || '';
      projectStatusEl.textContent = res.data.status || 'Neu';
    }
  });

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

      card.innerHTML =
        '<div class="plan-info"><div class="plan-icon">&#128196;</div><div>' +
          '<div class="plan-name">' + esc(plan.dateiname || '') + '</div>' +
          '<div class="plan-status"><span class="badge ' + (done ? 'badge-fertig' : 'badge-neu') + '">' + (done ? 'Fertig' : 'Hochgeladen') + '</span></div>' +
        '</div></div>' +
        '<div class="plan-actions">' +
          (done ? '<button class="btn btn-primary btn-sm res-btn" data-id="' + plan.id + '">Ergebnisse</button>' :
                  '<button class="btn btn-accent btn-sm ana-btn" data-id="' + plan.id + '">Analyse starten</button>') +
          '<button class="btn-delete-plan" data-id="' + plan.id + '">&times;</button>' +
        '</div>';
      planList.appendChild(card);
    });

    planList.querySelectorAll('.res-btn').forEach(function (b) {
      b.addEventListener('click', function () { if (window.loadResults) window.loadResults(this.getAttribute('data-id')); });
    });
    planList.querySelectorAll('.ana-btn').forEach(function (b) {
      b.addEventListener('click', function () {
        var btn = this;
        var planId = btn.getAttribute('data-id');
        btn.disabled = true;
        btn.textContent = 'KI analysiert...';

        fetch('/api/analyse', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ plan_id: planId })
        })
          .then(function (res) {
            if (!res.ok) return res.json().then(function (d) { throw new Error(d.detail || 'Analyse fehlgeschlagen'); });
            return res.json();
          })
          .then(function (data) {
            btn.textContent = 'Fertig!';
            btn.classList.remove('btn-accent');
            btn.classList.add('btn-primary');
            alert('Analyse abgeschlossen!\n' + data.raeume + ' Räume, ' + data.fenster + ' Fenster, ' + data.tueren + ' Türen erkannt.\nKonfidenz: ' + data.konfidenz + '%');
            loadPlans();
          })
          .catch(function (err) {
            btn.disabled = false;
            btn.textContent = 'Analyse starten';
            alert('Fehler: ' + err.message);
          });
      });
    });
    planList.querySelectorAll('.btn-delete-plan').forEach(function (b) {
      b.addEventListener('click', function (e) {
        e.stopPropagation();
        if (confirm('Plan löschen?')) _sb.from('plaene').delete().eq('id', this.getAttribute('data-id')).then(loadPlans);
      });
    });
  }

  function esc(s) { var d = document.createElement('div'); d.textContent = s; return d.innerHTML; }

  // Drag & Drop
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
    for (var i = 0; i < files.length; i++) if (files[i].type === 'application/pdf') pdfs.push(files[i]);
    if (!pdfs.length) { alert('Nur PDF-Dateien.'); return; }
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
    uploadBar.style.width = '50%'; uploadBar.textContent = 'Hochladen...';

    _sb.storage.from('plaene').upload(path, file, { contentType: 'application/pdf' })
      .then(function (r) {
        if (r.error) throw new Error(r.error.message);
        return _sb.from('plaene').insert({ projekt_id: projectId, dateiname: file.name, storage_path: path });
      })
      .then(function () {
        uploadBar.style.width = '100%'; uploadBar.textContent = '100%';
        setTimeout(function () { doUpload(files, idx + 1); }, 300);
      })
      .catch(function (err) {
        alert('Upload-Fehler: ' + err.message);
        uploadProgress.classList.add('hidden');
        loadPlans();
      });
  }

  window.loadPlans = loadPlans;
  window.projectId = projectId;
  loadPlans();
})();
