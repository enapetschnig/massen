/**
 * KI-Massenermittlung - Dashboard (direkt via Supabase)
 */
(function () {
  'use strict';

  var firma = requireAuth();
  if (!firma) return;

  var companyNameEl = document.getElementById('company-name');
  var logoutBtn = document.getElementById('logout-btn');
  var newProjectBtn = document.getElementById('new-project-btn');
  var projectGrid = document.getElementById('project-grid');
  var emptyState = document.getElementById('empty-state');
  var modalOverlay = document.getElementById('project-modal');
  var modalClose = document.getElementById('modal-close');
  var modalCancel = document.getElementById('modal-cancel');
  var projectForm = document.getElementById('project-form');
  var projectsLoading = document.getElementById('projects-loading');

  if (firma.name && companyNameEl) companyNameEl.textContent = firma.name;

  logoutBtn.addEventListener('click', function () {
    clearSession();
    window.location.href = 'index.html';
  });

  // Modal
  function openModal() { modalOverlay.classList.add('visible'); }
  function closeModal() { modalOverlay.classList.remove('visible'); projectForm.reset(); }
  newProjectBtn.addEventListener('click', openModal);
  modalClose.addEventListener('click', closeModal);
  modalCancel.addEventListener('click', closeModal);
  modalOverlay.addEventListener('click', function (e) { if (e.target === modalOverlay) closeModal(); });

  function formatDate(d) {
    if (!d) return '';
    return new Date(d).toLocaleDateString('de-AT', { day: '2-digit', month: '2-digit', year: 'numeric' });
  }

  function escapeHtml(s) { var d = document.createElement('div'); d.textContent = s; return d.innerHTML; }

  function statusBadge(s) {
    switch ((s || '').toLowerCase()) {
      case 'neu': return 'badge-neu';
      case 'fertig': case 'abgeschlossen': return 'badge-fertig';
      default: return 'badge-neu';
    }
  }

  // Load projects directly from Supabase
  function loadProjects() {
    if (projectsLoading) projectsLoading.style.display = 'flex';
    emptyState.classList.add('hidden');

    _sb.from('projekte').select('*').eq('firma_id', firma.id).order('erstellt_am', { ascending: false })
      .then(function (res) {
        if (projectsLoading) projectsLoading.style.display = 'none';
        var list = res.data || [];
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

          card.innerHTML =
            '<button class="btn-delete-project" title="Löschen">&times;</button>' +
            '<h3>' + escapeHtml(p.name || '') + '</h3>' +
            '<p class="project-address">' + escapeHtml(p.adresse || '') + '</p>' +
            '<div class="project-meta">' +
              '<span class="badge ' + statusBadge(p.status) + '">' + escapeHtml(p.status || 'Neu') + '</span>' +
              '<span>' + formatDate(p.erstellt_am) + '</span>' +
            '</div>';

          card.querySelector('.btn-delete-project').addEventListener('click', function (e) {
            e.stopPropagation();
            if (!confirm('Projekt "' + p.name + '" wirklich löschen?')) return;
            _sb.from('projekte').delete().eq('id', p.id).then(function () { loadProjects(); });
          });

          card.addEventListener('click', function () {
            window.location.href = 'projekt.html?id=' + p.id;
          });

          projectGrid.appendChild(card);
        });
      });
  }

  // Create project
  projectForm.addEventListener('submit', function (e) {
    e.preventDefault();
    var name = document.getElementById('proj-name').value.trim();
    var address = document.getElementById('proj-address').value.trim();
    var gewerk = document.getElementById('proj-gewerk').value;
    if (!name) return;

    var btn = projectForm.querySelector('button[type="submit"]');
    btn.disabled = true;

    _sb.from('projekte').insert({ firma_id: firma.id, name: name, adresse: address, gewerk: gewerk })
      .then(function () {
        closeModal();
        loadProjects();
      })
      .catch(function (err) { alert(err.message); })
      .finally(function () { btn.disabled = false; });
  });

  loadProjects();
})();
