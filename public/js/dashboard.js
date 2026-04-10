/**
 * KI-Massenermittlung - Dashboard
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

  function authHeaders() {
    return {
      'Content-Type': 'application/json',
      'Authorization': 'Bearer ' + token
    };
  }

  // --- Elements ---
  var companyNameEl = document.getElementById('company-name');
  var logoutBtn = document.getElementById('logout-btn');
  var newProjectBtn = document.getElementById('new-project-btn');
  var projectGrid = document.getElementById('project-grid');
  var emptyState = document.getElementById('empty-state');
  var modalOverlay = document.getElementById('project-modal');
  var modalClose = document.getElementById('modal-close');
  var modalCancel = document.getElementById('modal-cancel');
  var projectForm = document.getElementById('project-form');

  // --- Company Name ---
  var firma = null;
  try { firma = JSON.parse(localStorage.getItem('firma') || '{}'); } catch(e) {}
  if (firma && firma.name && companyNameEl) {
    companyNameEl.textContent = firma.name;
  }

  // --- Logout ---
  logoutBtn.addEventListener('click', function () {
    localStorage.removeItem('token');
    localStorage.removeItem('firma');
    window.location.href = 'index.html';
  });

  // --- Modal ---
  function openModal() {
    modalOverlay.classList.add('visible');
  }

  function closeModal() {
    modalOverlay.classList.remove('visible');
    projectForm.reset();
  }

  newProjectBtn.addEventListener('click', openModal);
  modalClose.addEventListener('click', closeModal);
  modalCancel.addEventListener('click', closeModal);

  modalOverlay.addEventListener('click', function (e) {
    if (e.target === modalOverlay) {
      closeModal();
    }
  });

  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape') {
      closeModal();
    }
  });

  // --- Status Helpers ---
  function statusBadgeClass(status) {
    switch ((status || '').toLowerCase()) {
      case 'neu': return 'badge-neu';
      case 'analyse': case 'in_bearbeitung': return 'badge-analyse';
      case 'fertig': case 'abgeschlossen': return 'badge-fertig';
      case 'fehler': return 'badge-fehler';
      default: return 'badge-neu';
    }
  }

  function statusLabel(status) {
    switch ((status || '').toLowerCase()) {
      case 'neu': return 'Neu';
      case 'analyse': case 'in_bearbeitung': return 'In Analyse';
      case 'fertig': case 'abgeschlossen': return 'Fertig';
      case 'fehler': return 'Fehler';
      default: return status || 'Neu';
    }
  }

  function formatDate(dateStr) {
    if (!dateStr) return '';
    var d = new Date(dateStr);
    return d.toLocaleDateString('de-AT', { day: '2-digit', month: '2-digit', year: 'numeric' });
  }

  // --- Loading Spinner ---
  var projectsLoading = document.getElementById('projects-loading');

  function showLoading() {
    if (projectsLoading) projectsLoading.style.display = 'flex';
    emptyState.classList.add('hidden');
  }

  function hideLoading() {
    if (projectsLoading) projectsLoading.style.display = 'none';
  }

  // --- Load Projects ---
  function loadProjects() {
    showLoading();
    fetch(API_BASE + '/api/projekte', {
      headers: authHeaders()
    })
      .then(function (res) {
        if (res.status === 401) {
          localStorage.removeItem('token');
          window.location.href = 'index.html';
          return;
        }
        if (!res.ok) throw new Error('Projekte konnten nicht geladen werden');
        return res.json();
      })
      .then(function (projects) {
        hideLoading();
        if (!projects) return;
        renderProjects(projects);
      })
      .catch(function (err) {
        hideLoading();
        console.error('Fehler beim Laden der Projekte:', err);
        projectGrid.innerHTML = '';
        emptyState.classList.remove('hidden');
      });
  }

  function renderProjects(projects) {
    var list = Array.isArray(projects) ? projects : (projects.projekte || projects.data || []);

    if (list.length === 0) {
      projectGrid.innerHTML = '';
      emptyState.classList.remove('hidden');
      return;
    }

    emptyState.classList.add('hidden');
    projectGrid.innerHTML = '';

    list.forEach(function (p) {
      var card = document.createElement('div');
      card.className = 'card card-clickable project-card';
      card.setAttribute('data-id', p.id);

      var planCount = p.plan_count || p.plaene_count || p.anzahl_plaene || 0;

      card.innerHTML =
        '<button class="btn-delete-project" title="Projekt löschen">&times;</button>' +
        '<h3>' + escapeHtml(p.name || p.projektname || '') + '</h3>' +
        '<p class="project-address">' + escapeHtml(p.address || p.adresse || '') + '</p>' +
        '<div class="project-meta">' +
          '<span class="badge ' + statusBadgeClass(p.status) + '">' + statusLabel(p.status) + '</span>' +
          '<span>' + formatDate(p.created_at || p.erstellt_am) + '</span>' +
          '<span class="project-plans">' + planCount + ' Pläne</span>' +
        '</div>';

      // Delete button handler
      card.querySelector('.btn-delete-project').addEventListener('click', function (e) {
        e.stopPropagation();
        e.preventDefault();
        if (!confirm('Möchten Sie das Projekt "' + (p.name || p.projektname || '') + '" wirklich löschen?')) return;
        deleteProject(p.id);
      });

      card.addEventListener('click', function () {
        window.location.href = 'projekt.html?id=' + p.id;
      });

      projectGrid.appendChild(card);
    });
  }

  // --- Delete Project ---
  function deleteProject(id) {
    fetch(API_BASE + '/api/projekte/' + id, {
      method: 'DELETE',
      headers: authHeaders()
    })
      .then(function (res) {
        if (!res.ok) throw new Error('Projekt konnte nicht gelöscht werden');
        loadProjects();
      })
      .catch(function (err) {
        alert(err.message);
      });
  }

  // --- Create Project ---
  projectForm.addEventListener('submit', function (e) {
    e.preventDefault();

    var name = document.getElementById('proj-name').value.trim();
    var address = document.getElementById('proj-address').value.trim();
    var gewerk = document.getElementById('proj-gewerk').value;

    if (!name) return;

    var submitBtn = projectForm.querySelector('button[type="submit"]');
    submitBtn.disabled = true;

    fetch(API_BASE + '/api/projekte', {
      method: 'POST',
      headers: authHeaders(),
      body: JSON.stringify({
        name: name,
        adresse: address,
        gewerk: gewerk
      })
    })
      .then(function (res) {
        if (!res.ok) {
          return res.json().then(function (data) {
            throw new Error(data.detail || 'Projekt konnte nicht erstellt werden');
          });
        }
        return res.json();
      })
      .then(function () {
        closeModal();
        loadProjects();
      })
      .catch(function (err) {
        alert(err.message);
      })
      .finally(function () {
        submitBtn.disabled = false;
      });
  });

  // --- Helpers ---
  function escapeHtml(str) {
    var div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
  }

  // --- Init ---
  loadProjects();
})();
