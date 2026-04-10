/**
 * KI-Massenermittlung - Ergebnistabellen (Results Tables)
 * Reads data from /api/plaene/{id}/ergebnis which returns:
 *   raeume/fenster: elemente rows with typ, bezeichnung, daten (JSONB), konfidenz
 *   massen: rows with pos_nr, beschreibung, gewerk, raum_referenz, berechnung, endsumme, einheit, konfidenz
 */

(function () {
  'use strict';

  var API_BASE = window.location.origin;
  var token = localStorage.getItem('token');

  function authHeaders() {
    return {
      'Content-Type': 'application/json',
      'Authorization': 'Bearer ' + token
    };
  }

  // --- Elements ---
  var resultsSection = document.getElementById('results-section');
  var summaryRooms = document.getElementById('summary-rooms');
  var summaryWindows = document.getElementById('summary-windows');
  var summaryConfidence = document.getElementById('summary-confidence');
  var tabButtons = document.querySelectorAll('#result-tabs .tab-btn');
  var tabPanels = {
    raeume: document.getElementById('tab-raeume'),
    fenster: document.getElementById('tab-fenster'),
    massen: document.getElementById('tab-massen')
  };
  var tables = {
    raeume: document.getElementById('table-raeume'),
    fenster: document.getElementById('table-fenster'),
    massen: document.getElementById('table-massen')
  };
  var exportBtn = document.getElementById('export-btn');

  var currentPlanId = null;

  // --- Tab Switching ---
  if (tabButtons) {
    tabButtons.forEach(function (btn) {
      btn.addEventListener('click', function () {
        var tab = this.getAttribute('data-tab');
        tabButtons.forEach(function (b) { b.classList.remove('active'); });
        this.classList.add('active');
        Object.keys(tabPanels).forEach(function (key) {
          if (tabPanels[key]) tabPanels[key].classList.remove('active');
        });
        if (tabPanels[tab]) tabPanels[tab].classList.add('active');
      });
    });
  }

  // --- Confidence HTML ---
  function confidenceHtml(value) {
    if (value === undefined || value === null) return '';
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

  function lowConfClass(value) {
    return (value !== undefined && value < 60) ? ' low-confidence' : '';
  }

  function escapeHtml(str) {
    var div = document.createElement('div');
    div.textContent = str || '';
    return div.innerHTML;
  }

  // --- Make Cell Editable ---
  function makeEditable(td, masseId, field) {
    td.classList.add('editable');
    td.addEventListener('click', function () {
      if (td.querySelector('.cell-input')) return;
      var originalValue = td.textContent.trim();
      var input = document.createElement('input');
      input.type = 'text';
      input.className = 'cell-input';
      input.value = originalValue;
      td.textContent = '';
      td.appendChild(input);
      input.focus();
      input.select();

      function saveEdit() {
        var newValue = input.value.trim();
        td.textContent = newValue;
        if (newValue !== originalValue) {
          td.classList.add('changed');
          saveChange(masseId, field, newValue);
        }
      }

      input.addEventListener('blur', saveEdit);
      input.addEventListener('keydown', function (e) {
        if (e.key === 'Enter') { e.preventDefault(); input.blur(); }
        if (e.key === 'Escape') { td.textContent = originalValue; }
      });
    });
  }

  // --- Save Change to API ---
  function saveChange(masseId, field, value) {
    var body = {};
    if (field === 'endsumme') {
      body.endsumme = parseFloat(value.replace(',', '.')) || 0;
    } else if (field === 'beschreibung') {
      body.beschreibung = value;
    } else if (field === 'einheit') {
      body.einheit = value;
    }

    fetch(API_BASE + '/api/massen/' + masseId, {
      method: 'PUT',
      headers: authHeaders(),
      body: JSON.stringify(body)
    })
      .then(function (res) {
        if (!res.ok) console.error('Fehler beim Speichern der Änderung');
      })
      .catch(function (err) {
        console.error('Fehler beim Speichern:', err);
      });
  }

  // --- Render Räume Table ---
  function renderRaeume(rooms) {
    if (!tables.raeume) return;
    var tbody = tables.raeume.querySelector('tbody');
    tbody.innerHTML = '';

    if (!rooms || rooms.length === 0) {
      tbody.innerHTML = '<tr><td colspan="7" style="padding:2rem;text-align:center;color:#8899aa">Keine Raumdaten vorhanden</td></tr>';
      return;
    }

    rooms.forEach(function (r, i) {
      var daten = r.daten || {};
      var tr = document.createElement('tr');

      addCell(tr, (i + 1));
      addCell(tr, r.bezeichnung || daten.name || '');
      addCell(tr, daten.bodenbelag || '-');
      addCell(tr, formatNum(daten.flaeche_m2));
      addCell(tr, formatNum(daten.umfang_m));
      addCell(tr, formatNum(daten.hoehe_m));

      var tdConf = document.createElement('td');
      tdConf.innerHTML = confidenceHtml(r.konfidenz);
      tr.appendChild(tdConf);

      tbody.appendChild(tr);
    });
  }

  // --- Render Fenster Table ---
  function renderFenster(windows) {
    if (!tables.fenster) return;
    var tbody = tables.fenster.querySelector('tbody');
    tbody.innerHTML = '';

    if (!windows || windows.length === 0) {
      tbody.innerHTML = '<tr><td colspan="7" style="padding:2rem;text-align:center;color:#8899aa">Keine Fensterdaten vorhanden</td></tr>';
      return;
    }

    windows.forEach(function (w, i) {
      var daten = w.daten || {};
      var tr = document.createElement('tr');

      addCell(tr, (i + 1));
      addCell(tr, w.bezeichnung || daten.bezeichnung || '');
      addCell(tr, formatNum(daten.al_breite_mm));
      addCell(tr, formatNum(daten.al_hoehe_mm));
      addCell(tr, formatNum(daten.rb_breite_mm));
      addCell(tr, formatNum(daten.rb_hoehe_mm));

      var tdConf = document.createElement('td');
      tdConf.innerHTML = confidenceHtml(w.konfidenz);
      tr.appendChild(tdConf);

      tbody.appendChild(tr);
    });
  }

  // --- Render Massen Table ---
  function renderMassen(masses) {
    if (!tables.massen) return;
    var tbody = tables.massen.querySelector('tbody');
    tbody.innerHTML = '';

    if (!masses || masses.length === 0) {
      tbody.innerHTML = '<tr><td colspan="8" style="padding:2rem;text-align:center;color:#8899aa">Keine Massendaten vorhanden</td></tr>';
      return;
    }

    masses.forEach(function (m) {
      var tr = document.createElement('tr');

      addCell(tr, m.pos_nr || '');

      var tdBeschr = addCell(tr, m.beschreibung || '');
      makeEditable(tdBeschr, m.id, 'beschreibung');

      addCell(tr, m.gewerk || '');
      addCell(tr, m.raum_referenz || '');

      var tdEndsumme = addCell(tr, formatNum(m.endsumme));
      tdEndsumme.className += lowConfClass(m.konfidenz);
      makeEditable(tdEndsumme, m.id, 'endsumme');

      var tdEinheit = addCell(tr, m.einheit || '');
      makeEditable(tdEinheit, m.id, 'einheit');

      var tdConf = document.createElement('td');
      tdConf.innerHTML = confidenceHtml(m.konfidenz);
      tr.appendChild(tdConf);

      if (m.manuell_korrigiert) {
        tr.classList.add('changed-row');
      }

      tbody.appendChild(tr);
    });
  }

  function addCell(tr, text) {
    var td = document.createElement('td');
    td.textContent = (text !== undefined && text !== null) ? String(text) : '-';
    tr.appendChild(td);
    return td;
  }

  // --- Load Results ---
  function loadResults(planId) {
    currentPlanId = planId;

    fetch(API_BASE + '/api/plaene/' + planId + '/ergebnis', {
      headers: authHeaders()
    })
      .then(function (res) {
        if (!res.ok) throw new Error('Ergebnisse nicht verfügbar');
        return res.json();
      })
      .then(function (data) {
        if (resultsSection) resultsSection.classList.remove('hidden');

        var rooms = data.raeume || [];
        var windows = data.fenster || [];
        var doors = data.tueren || [];
        var masses = data.massen || [];

        // Summary
        if (summaryRooms) summaryRooms.textContent = rooms.length;
        if (summaryWindows) summaryWindows.textContent = windows.length;

        var summaryDoors = document.getElementById('summary-doors');
        if (summaryDoors) summaryDoors.textContent = doors.length;

        // Confidence with colored circle
        var plan = data.plan || {};
        var konfidenz = plan.gesamt_konfidenz || 0;
        var confValueEl = document.getElementById('confidence-value');
        var confCircleEl = document.getElementById('confidence-circle');
        if (confValueEl) {
          confValueEl.textContent = konfidenz > 0 ? Math.round(konfidenz) + '%' : '-';
        }
        if (confCircleEl && konfidenz > 0) {
          confCircleEl.className = 'confidence-circle';
          if (konfidenz >= 80) confCircleEl.classList.add('confidence-green');
          else if (konfidenz >= 60) confCircleEl.classList.add('confidence-yellow');
          else confCircleEl.classList.add('confidence-red');
        }

        renderRaeume(rooms);
        renderFenster(windows);
        renderMassen(masses);

        if (resultsSection) {
          resultsSection.scrollIntoView({ behavior: 'smooth', block: 'start' });
        }
      })
      .catch(function (err) {
        console.error('Fehler beim Laden der Ergebnisse:', err);
      });
  }

  // --- Export ---
  if (exportBtn) {
    exportBtn.addEventListener('click', function () {
      if (!currentPlanId) return;
      exportBtn.disabled = true;
      exportBtn.textContent = 'Wird exportiert...';

      fetch(API_BASE + '/api/plaene/' + currentPlanId + '/export', {
        headers: { 'Authorization': 'Bearer ' + token }
      })
        .then(function (res) {
          if (!res.ok) throw new Error('Export fehlgeschlagen');
          var filename = 'massenermittlung.xlsx';
          var disposition = res.headers.get('Content-Disposition');
          if (disposition) {
            var match = disposition.match(/filename[^;=\n]*=((['"]).*?\2|[^;\n]*)/);
            if (match && match[1]) filename = match[1].replace(/['"]/g, '');
          }
          return res.blob().then(function (blob) {
            return { blob: blob, filename: filename };
          });
        })
        .then(function (result) {
          var url = window.URL.createObjectURL(result.blob);
          var a = document.createElement('a');
          a.href = url;
          a.download = result.filename;
          document.body.appendChild(a);
          a.click();
          document.body.removeChild(a);
          window.URL.revokeObjectURL(url);
        })
        .catch(function (err) {
          alert('Export fehlgeschlagen: ' + err.message);
        })
        .finally(function () {
          exportBtn.disabled = false;
          exportBtn.textContent = 'Excel Export';
        });
    });
  }

  // --- Helpers ---
  function formatNum(val) {
    if (val === undefined || val === null || val === '') return '-';
    var num = parseFloat(val);
    if (isNaN(num)) return String(val);
    return num.toLocaleString('de-AT', { minimumFractionDigits: 0, maximumFractionDigits: 2 });
  }

  // Expose globally
  window.loadResults = loadResults;
})();
