/**
 * KI-Massenermittlung - Upload & Plan Management
 */

(function () {
  'use strict';

  var API_BASE = window.location.origin;

  // --- Auth Check ---
  var token = localStorage.getItem('token');
  if (!token) {
    window.location.href = 'index.html';
    return;
  }

  function authHeaders(contentType) {
    var h = { 'Authorization': 'Bearer ' + token };
    if (contentType) h['Content-Type'] = contentType;
    return h;
  }

  // --- Get Project ID from URL ---
  var params = new URLSearchParams(window.location.search);
  var projectId = params.get('id');

  if (!projectId) {
    window.location.href = 'dashboard.html';
    return;
  }

  // --- Elements ---
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

  // --- Company Name & Logout ---
  var firma = null;
  try { firma = JSON.parse(localStorage.getItem('firma') || '{}'); } catch(e) {}
  if (firma && firma.name && companyNameEl) {
    companyNameEl.textContent = firma.name;
  }

  if (logoutBtn) {
    logoutBtn.addEventListener('click', function () {
      localStorage.removeItem('token');
      localStorage.removeItem('company');
      localStorage.removeItem('user');
      window.location.href = 'index.html';
    });
  }

  // --- Load Project Info ---
  function loadProject() {
    fetch(API_BASE + '/api/projekte/' + projectId, {
      headers: authHeaders('application/json')
    })
      .then(function (res) {
        if (res.status === 401) {
          localStorage.removeItem('token');
          window.location.href = 'index.html';
          return;
        }
        if (!res.ok) throw new Error('Projekt nicht gefunden');
        return res.json();
      })
      .then(function (p) {
        if (!p) return;
        projectNameEl.textContent = p.name || p.projektname || '';
        projectAddressEl.textContent = p.address || p.adresse || '';
        var statusText = p.status || 'Neu';
        projectStatusEl.textContent = statusText.charAt(0).toUpperCase() + statusText.slice(1);
        document.title = 'KI-Massenermittlung – ' + (p.name || p.projektname || 'Projekt');
      })
      .catch(function (err) {
        console.error('Fehler beim Laden des Projekts:', err);
        projectNameEl.textContent = 'Fehler beim Laden';
      });
  }

  // --- Loading Spinner ---
  var plansLoading = document.getElementById('plans-loading');

  function showPlansLoading() {
    if (plansLoading) plansLoading.style.display = 'flex';
    plansEmpty.classList.add('hidden');
  }

  function hidePlansLoading() {
    if (plansLoading) plansLoading.style.display = 'none';
  }

  // --- Load Plans (from project detail endpoint) ---
  function loadPlans() {
    showPlansLoading();
    fetch(API_BASE + '/api/projekte/' + projectId, {
      headers: authHeaders('application/json')
    })
      .then(function (res) {
        if (!res.ok) return { plaene: [] };
        return res.json();
      })
      .then(function (data) {
        hidePlansLoading();
        var list = data.plaene || [];
        renderPlans(list);
      })
      .catch(function () {
        hidePlansLoading();
        renderPlans([]);
      });
  }

  function renderPlans(plans) {
    planList.innerHTML = '';

    if (plans.length === 0) {
      plansEmpty.classList.remove('hidden');
      return;
    }

    plansEmpty.classList.add('hidden');

    plans.forEach(function (plan) {
      var card = document.createElement('div');
      card.className = 'card plan-card';

      var isVerarbeitet = plan.verarbeitet === true;
      var statusClass = 'badge-neu';
      var statusLabel = isVerarbeitet ? 'Abgeschlossen' : 'Hochgeladen';
      if (isVerarbeitet) statusClass = 'badge-fertig';

      var confidenceHtml = '';
      if (plan.gesamt_konfidenz !== undefined && plan.gesamt_konfidenz !== null && plan.gesamt_konfidenz > 0) {
        confidenceHtml = buildConfidenceHtml(plan.gesamt_konfidenz);
      }

      card.innerHTML =
        '<div class="plan-info">' +
          '<div class="plan-icon">&#128196;</div>' +
          '<div>' +
            '<div class="plan-name">' + escapeHtml(plan.dateiname || '') + '</div>' +
            '<div class="plan-status">' +
              '<span class="badge ' + statusClass + '">' + escapeHtml(statusLabel) + '</span> ' +
              confidenceHtml +
            '</div>' +
          '</div>' +
        '</div>' +
        '<div class="plan-actions">' +
          '<button class="btn btn-accent btn-sm analyse-btn" data-plan-id="' + plan.id + '">Analyse starten</button>' +
          '<button class="btn-delete-plan" data-plan-id="' + plan.id + '" title="Plan löschen">&times;</button>' +
        '</div>';

      // If already finished, show "Ergebnisse anzeigen" instead
      if (isVerarbeitet) {
        var btn = card.querySelector('.analyse-btn');
        btn.textContent = 'Ergebnisse anzeigen';
        btn.classList.remove('btn-accent');
        btn.classList.add('btn-primary');
      }

      planList.appendChild(card);
    });

    // Attach analyse button handlers
    planList.querySelectorAll('.analyse-btn').forEach(function (btn) {
      btn.addEventListener('click', function () {
        var planId = this.getAttribute('data-plan-id');
        var label = this.textContent;

        if (label === 'Ergebnisse anzeigen') {
          // Load results directly
          if (typeof window.loadResults === 'function') {
            window.loadResults(planId);
          }
          return;
        }

        startAnalysis(planId, this);
      });
    });

    // Attach delete button handlers
    planList.querySelectorAll('.btn-delete-plan').forEach(function (btn) {
      btn.addEventListener('click', function (e) {
        e.stopPropagation();
        e.preventDefault();
        var planId = this.getAttribute('data-plan-id');
        if (!confirm('Möchten Sie diesen Plan wirklich löschen?')) return;
        deletePlan(planId);
      });
    });
  }

  function buildConfidenceHtml(value) {
    var cls = 'confidence-green';
    if (value < 60) cls = 'confidence-red';
    else if (value < 80) cls = 'confidence-yellow';

    return '<span class="confidence ' + cls + '">' +
      '<span class="confidence-dot dot-red"></span>' +
      '<span class="confidence-dot dot-yellow"></span>' +
      '<span class="confidence-dot dot-green"></span>' +
      '<span class="confidence-value">' + Math.round(value) + '%</span>' +
    '</span>';
  }

  // --- Delete Plan ---
  function deletePlan(planId) {
    fetch(API_BASE + '/api/plaene/' + planId, {
      method: 'DELETE',
      headers: authHeaders('application/json')
    })
      .then(function (res) {
        if (!res.ok) throw new Error('Plan konnte nicht gelöscht werden');
        loadPlans();
      })
      .catch(function (err) {
        alert(err.message);
      });
  }

  // --- Start Analysis ---
  function startAnalysis(planId, btnEl) {
    if (btnEl) {
      btnEl.disabled = true;
      btnEl.textContent = 'Analyse läuft...';
    }

    fetch(API_BASE + '/api/plaene/' + planId + '/analyse', {
      method: 'POST',
      headers: authHeaders('application/json')
    })
      .then(function (res) {
        if (!res.ok) throw new Error('Analyse konnte nicht gestartet werden');
        return res.json();
      })
      .then(function () {
        // Start progress tracking via WebSocket
        if (typeof window.startProgress === 'function') {
          window.startProgress(planId);
        }
      })
      .catch(function (err) {
        alert(err.message);
        if (btnEl) {
          btnEl.disabled = false;
          btnEl.textContent = 'Analyse starten';
        }
      });
  }

  // --- Drag & Drop ---
  uploadZone.addEventListener('click', function () {
    fileInput.click();
  });

  uploadZone.addEventListener('dragover', function (e) {
    e.preventDefault();
    e.stopPropagation();
    this.classList.add('dragover');
  });

  uploadZone.addEventListener('dragleave', function (e) {
    e.preventDefault();
    e.stopPropagation();
    this.classList.remove('dragover');
  });

  uploadZone.addEventListener('drop', function (e) {
    e.preventDefault();
    e.stopPropagation();
    this.classList.remove('dragover');

    var files = e.dataTransfer.files;
    if (files.length > 0) {
      handleFiles(files);
    }
  });

  fileInput.addEventListener('change', function () {
    if (this.files.length > 0) {
      handleFiles(this.files);
    }
  });

  // --- Upload Files ---
  function handleFiles(files) {
    var pdfFiles = [];
    for (var i = 0; i < files.length; i++) {
      if (files[i].type === 'application/pdf') {
        pdfFiles.push(files[i]);
      }
    }

    if (pdfFiles.length === 0) {
      alert('Bitte nur PDF-Dateien hochladen.');
      return;
    }

    // Upload sequentially
    uploadProgress.classList.remove('hidden');
    uploadSequential(pdfFiles, 0);
  }

  function uploadSequential(files, index) {
    if (index >= files.length) {
      uploadProgress.classList.add('hidden');
      uploadBar.style.width = '0%';
      uploadBar.textContent = '0%';
      fileInput.value = '';
      loadPlans();
      return;
    }

    var file = files[index];
    var formData = new FormData();
    formData.append('file', file);

    var xhr = new XMLHttpRequest();
    xhr.open('POST', API_BASE + '/api/projekte/' + projectId + '/upload');
    xhr.setRequestHeader('Authorization', 'Bearer ' + token);

    xhr.upload.addEventListener('progress', function (e) {
      if (e.lengthComputable) {
        var pct = Math.round((e.loaded / e.total) * 100);
        uploadBar.style.width = pct + '%';
        uploadBar.textContent = pct + '%';
      }
    });

    xhr.addEventListener('load', function () {
      if (xhr.status >= 200 && xhr.status < 300) {
        uploadSequential(files, index + 1);
      } else {
        alert('Fehler beim Hochladen von ' + file.name);
        uploadProgress.classList.add('hidden');
        fileInput.value = '';
        loadPlans();
      }
    });

    xhr.addEventListener('error', function () {
      alert('Netzwerkfehler beim Hochladen von ' + file.name);
      uploadProgress.classList.add('hidden');
      fileInput.value = '';
    });

    xhr.send(formData);
  }

  // --- Helpers ---
  function escapeHtml(str) {
    var div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
  }

  // Expose for other scripts
  window.loadPlans = loadPlans;
  window.projectId = projectId;

  // --- Init ---
  loadProject();
  loadPlans();
})();
