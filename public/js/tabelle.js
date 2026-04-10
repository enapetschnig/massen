/**
 * KI-Massenermittlung - Ergebnistabellen
 * Liest Daten direkt aus Supabase (elemente + massen Tabellen).
 */
(function () {
  'use strict';

  // --- DOM-Elemente ---
  var resultsSection = document.getElementById('results-section');
  var summaryRooms = document.getElementById('summary-rooms');
  var summaryWindows = document.getElementById('summary-windows');
  var summaryDoors = document.getElementById('summary-doors');
  var summaryMasses = document.getElementById('summary-masses');
  var confidenceValue = document.getElementById('confidence-value');
  var confidenceCircle = document.getElementById('confidence-circle');

  var tabButtons = document.querySelectorAll('#result-tabs .tab-btn');
  var tabPanels = {
    raeume: document.getElementById('tab-raeume'),
    fenster: document.getElementById('tab-fenster'),
    tueren: document.getElementById('tab-tueren'),
    massen: document.getElementById('tab-massen'),
    zusammenfassung: document.getElementById('tab-zusammenfassung')
  };
  var tables = {
    raeume: document.getElementById('table-raeume'),
    fenster: document.getElementById('table-fenster'),
    tueren: document.getElementById('table-tueren'),
    massen: document.getElementById('table-massen'),
    zusammenfassung: document.getElementById('table-zusammenfassung')
  };
  var exportBtn = document.getElementById('export-btn');

  var currentPlanId = null;
  var cachedData = { rooms: [], windows: [], doors: [], masses: [] };

  // --- Tab-Umschaltung ---
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

  // --- Konfidenz-Ampel HTML ---
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
    return (value !== undefined && value !== null && value < 60) ? ' low-confidence' : '';
  }

  // --- Zelle editierbar machen ---
  function makeEditable(td, masseId) {
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
          var numVal = parseFloat(newValue.replace(',', '.'));
          if (isNaN(numVal)) numVal = 0;
          _sb.from('massen')
            .update({ endsumme: numVal, manuell_korrigiert: true })
            .eq('id', masseId)
            .then(function (res) {
              if (res.error) console.error('Fehler beim Speichern:', res.error.message);
            });
        }
      }

      input.addEventListener('blur', saveEdit);
      input.addEventListener('keydown', function (e) {
        if (e.key === 'Enter') { e.preventDefault(); input.blur(); }
        if (e.key === 'Escape') { td.textContent = originalValue; }
      });
    });
  }

  // --- Zelle hinzufuegen ---
  function addCell(tr, text) {
    var td = document.createElement('td');
    td.textContent = (text !== undefined && text !== null) ? String(text) : '-';
    tr.appendChild(td);
    return td;
  }

  // --- Raeume rendern ---
  function renderRaeume(rooms) {
    if (!tables.raeume) return;
    var tbody = tables.raeume.querySelector('tbody');
    tbody.innerHTML = '';
    if (!rooms || rooms.length === 0) {
      tbody.innerHTML = '<tr><td colspan="8" style="padding:2rem;text-align:center;color:#8899aa">Keine Raumdaten vorhanden</td></tr>';
      return;
    }
    rooms.forEach(function (r, i) {
      var d = r.daten || {};
      var tr = document.createElement('tr');
      addCell(tr, i + 1);
      addCell(tr, d.name || r.bezeichnung || '');
      addCell(tr, d.bodenbelag || '-');
      addCell(tr, formatNum(d.flaeche_m2));
      addCell(tr, formatNum(d.umfang_m));
      addCell(tr, formatNum(d.hoehe_m));
      addCell(tr, formatNum(d.wandflaeche_m2));
      var tdConf = document.createElement('td');
      tdConf.innerHTML = confidenceHtml(r.konfidenz);
      tr.appendChild(tdConf);
      tbody.appendChild(tr);
    });
  }

  // --- Fenster rendern ---
  function renderFenster(windows) {
    if (!tables.fenster) return;
    var tbody = tables.fenster.querySelector('tbody');
    tbody.innerHTML = '';
    if (!windows || windows.length === 0) {
      tbody.innerHTML = '<tr><td colspan="11" style="padding:2rem;text-align:center;color:#8899aa">Keine Fensterdaten vorhanden</td></tr>';
      return;
    }
    windows.forEach(function (w, i) {
      var d = w.daten || {};
      var tr = document.createElement('tr');
      addCell(tr, i + 1);
      addCell(tr, d.bezeichnung || w.bezeichnung || '');
      addCell(tr, d.raum || '');
      addCell(tr, formatNum(d.al_breite_mm));
      addCell(tr, formatNum(d.al_hoehe_mm));
      addCell(tr, formatNum(d.rb_breite_mm));
      addCell(tr, formatNum(d.rb_hoehe_mm));
      addCell(tr, formatNum(d.rph_mm));
      addCell(tr, formatNum(d.fph_mm));
      addCell(tr, formatNum(d.flaeche_m2));
      var tdConf = document.createElement('td');
      tdConf.innerHTML = confidenceHtml(w.konfidenz);
      tr.appendChild(tdConf);
      tbody.appendChild(tr);
    });
  }

  // --- Tueren rendern ---
  function renderTueren(doors) {
    if (!tables.tueren) return;
    var tbody = tables.tueren.querySelector('tbody');
    tbody.innerHTML = '';
    if (!doors || doors.length === 0) {
      tbody.innerHTML = '<tr><td colspan="7" style="padding:2rem;text-align:center;color:#8899aa">Keine Tuerendaten vorhanden</td></tr>';
      return;
    }
    doors.forEach(function (t, i) {
      var d = t.daten || {};
      var tr = document.createElement('tr');
      addCell(tr, i + 1);
      addCell(tr, d.bezeichnung || t.bezeichnung || '');
      addCell(tr, d.raum || '');
      addCell(tr, formatNum(d.breite_mm));
      addCell(tr, formatNum(d.hoehe_mm));
      addCell(tr, d.typ || '-');
      var tdConf = document.createElement('td');
      tdConf.innerHTML = confidenceHtml(t.konfidenz);
      tr.appendChild(tdConf);
      tbody.appendChild(tr);
    });
  }

  // --- Massen rendern ---
  function renderMassen(masses) {
    if (!tables.massen) return;
    var tbody = tables.massen.querySelector('tbody');
    tbody.innerHTML = '';
    if (!masses || masses.length === 0) {
      tbody.innerHTML = '<tr><td colspan="7" style="padding:2rem;text-align:center;color:#8899aa">Keine Massendaten vorhanden</td></tr>';
      return;
    }
    masses.forEach(function (m) {
      var tr = document.createElement('tr');
      addCell(tr, m.pos_nr || '');
      addCell(tr, m.beschreibung || '');
      addCell(tr, m.gewerk || '');
      addCell(tr, m.raum_referenz || '');

      var tdEndsumme = addCell(tr, formatNum(m.endsumme));
      tdEndsumme.className += lowConfClass(m.konfidenz);
      makeEditable(tdEndsumme, m.id);

      addCell(tr, m.einheit || '');

      var tdConf = document.createElement('td');
      tdConf.innerHTML = confidenceHtml(m.konfidenz);
      tr.appendChild(tdConf);

      if (m.manuell_korrigiert) {
        tr.classList.add('changed-row');
      }
      tbody.appendChild(tr);
    });
  }

  // --- Zusammenfassung rendern (gruppiert nach Gewerk) ---
  function renderZusammenfassung(masses) {
    if (!tables.zusammenfassung) return;
    var tbody = tables.zusammenfassung.querySelector('tbody');
    tbody.innerHTML = '';
    if (!masses || masses.length === 0) {
      tbody.innerHTML = '<tr><td colspan="3" style="padding:2rem;text-align:center;color:#8899aa">Keine Daten vorhanden</td></tr>';
      return;
    }

    // Gruppieren nach Gewerk + Einheit
    var groups = {};
    masses.forEach(function (m) {
      var key = (m.gewerk || 'Sonstige') + '||' + (m.einheit || '');
      if (!groups[key]) {
        groups[key] = { gewerk: m.gewerk || 'Sonstige', einheit: m.einheit || '', total: 0 };
      }
      groups[key].total += (parseFloat(m.endsumme) || 0);
    });

    var keys = Object.keys(groups).sort();
    keys.forEach(function (key) {
      var g = groups[key];
      var tr = document.createElement('tr');
      tr.style.fontWeight = '600';
      addCell(tr, g.gewerk);
      addCell(tr, formatNum(g.total));
      addCell(tr, g.einheit);
      tbody.appendChild(tr);
    });
  }

  // --- Ergebnisse laden ---
  function loadResults(planId) {
    currentPlanId = planId;

    // Parallel: elemente und massen laden
    Promise.all([
      _sb.from('elemente').select('*').eq('plan_id', planId),
      _sb.from('massen').select('*').eq('plan_id', planId).order('pos_nr', { ascending: true })
    ]).then(function (results) {
      var elementeRes = results[0];
      var massenRes = results[1];

      if (elementeRes.error) { console.error('Fehler Elemente:', elementeRes.error.message); return; }
      if (massenRes.error) { console.error('Fehler Massen:', massenRes.error.message); return; }

      var elemente = elementeRes.data || [];
      var masses = massenRes.data || [];

      // Nach Typ filtern
      var rooms = elemente.filter(function (e) { return e.typ === 'raum'; });
      var windows = elemente.filter(function (e) { return e.typ === 'fenster'; });
      var doors = elemente.filter(function (e) { return e.typ === 'tuer'; });

      // Cache fuer Export
      cachedData = { rooms: rooms, windows: windows, doors: doors, masses: masses };

      // Zusammenfassung
      if (summaryRooms) summaryRooms.textContent = rooms.length;
      if (summaryWindows) summaryWindows.textContent = windows.length;
      if (summaryDoors) summaryDoors.textContent = doors.length;
      if (summaryMasses) summaryMasses.textContent = masses.length;

      // Gesamt-Konfidenz berechnen (Durchschnitt aller Elemente + Massen)
      var allConf = [];
      elemente.forEach(function (e) { if (e.konfidenz != null) allConf.push(e.konfidenz); });
      masses.forEach(function (m) { if (m.konfidenz != null) allConf.push(m.konfidenz); });
      var avgConf = allConf.length > 0 ? allConf.reduce(function (a, b) { return a + b; }, 0) / allConf.length : 0;

      if (confidenceValue) {
        confidenceValue.textContent = avgConf > 0 ? Math.round(avgConf) + '%' : '-';
      }
      if (confidenceCircle && avgConf > 0) {
        confidenceCircle.className = 'confidence-circle';
        if (avgConf >= 80) confidenceCircle.classList.add('confidence-green');
        else if (avgConf >= 60) confidenceCircle.classList.add('confidence-yellow');
        else confidenceCircle.classList.add('confidence-red');
      }

      // Tabellen befuellen
      renderRaeume(rooms);
      renderFenster(windows);
      renderTueren(doors);
      renderMassen(masses);
      renderZusammenfassung(masses);

      // Sektion anzeigen
      if (resultsSection) {
        resultsSection.classList.remove('hidden');
        resultsSection.scrollIntoView({ behavior: 'smooth', block: 'start' });
      }
    }).catch(function (err) {
      console.error('Fehler beim Laden der Ergebnisse:', err);
    });
  }

  // --- Excel Export (CSV-Download) ---
  if (exportBtn) {
    exportBtn.addEventListener('click', function () {
      if (!currentPlanId) return;
      exportBtn.disabled = true;
      exportBtn.textContent = 'Wird exportiert...';

      try {
        var csv = '';
        var BOM = '\uFEFF'; // UTF-8 BOM fuer Excel

        // Raeume
        csv += 'RAEUME\n';
        csv += 'Nr;Name;Bodenbelag;Flaeche m2;Umfang m;Hoehe m;Wandflaeche m2;Konfidenz\n';
        cachedData.rooms.forEach(function (r, i) {
          var d = r.daten || {};
          csv += csvRow([
            i + 1,
            d.name || r.bezeichnung || '',
            d.bodenbelag || '',
            csvNum(d.flaeche_m2),
            csvNum(d.umfang_m),
            csvNum(d.hoehe_m),
            csvNum(d.wandflaeche_m2),
            r.konfidenz != null ? Math.round(r.konfidenz) + '%' : ''
          ]);
        });

        csv += '\n';

        // Fenster
        csv += 'FENSTER\n';
        csv += 'Nr;Bezeichnung;Raum;AL Breite mm;AL Hoehe mm;RB Breite mm;RB Hoehe mm;RPH mm;FPH mm;Flaeche m2;Konfidenz\n';
        cachedData.windows.forEach(function (w, i) {
          var d = w.daten || {};
          csv += csvRow([
            i + 1,
            d.bezeichnung || w.bezeichnung || '',
            d.raum || '',
            csvNum(d.al_breite_mm),
            csvNum(d.al_hoehe_mm),
            csvNum(d.rb_breite_mm),
            csvNum(d.rb_hoehe_mm),
            csvNum(d.rph_mm),
            csvNum(d.fph_mm),
            csvNum(d.flaeche_m2),
            w.konfidenz != null ? Math.round(w.konfidenz) + '%' : ''
          ]);
        });

        csv += '\n';

        // Tueren
        csv += 'TUEREN\n';
        csv += 'Nr;Bezeichnung;Raum;Breite mm;Hoehe mm;Typ;Konfidenz\n';
        cachedData.doors.forEach(function (t, i) {
          var d = t.daten || {};
          csv += csvRow([
            i + 1,
            d.bezeichnung || t.bezeichnung || '',
            d.raum || '',
            csvNum(d.breite_mm),
            csvNum(d.hoehe_mm),
            d.typ || '',
            t.konfidenz != null ? Math.round(t.konfidenz) + '%' : ''
          ]);
        });

        csv += '\n';

        // Massen
        csv += 'MASSEN\n';
        csv += 'Pos;Beschreibung;Gewerk;Raum;Endsumme;Einheit;Konfidenz\n';
        cachedData.masses.forEach(function (m) {
          csv += csvRow([
            m.pos_nr || '',
            m.beschreibung || '',
            m.gewerk || '',
            m.raum_referenz || '',
            csvNum(m.endsumme),
            m.einheit || '',
            m.konfidenz != null ? Math.round(m.konfidenz) + '%' : ''
          ]);
        });

        // Download
        var blob = new Blob([BOM + csv], { type: 'text/csv;charset=utf-8;' });
        var url = window.URL.createObjectURL(blob);
        var a = document.createElement('a');
        a.href = url;
        a.download = 'massenermittlung_' + currentPlanId + '.csv';
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        window.URL.revokeObjectURL(url);
      } catch (err) {
        console.error('Export-Fehler:', err);
      } finally {
        exportBtn.disabled = false;
        exportBtn.textContent = '\uD83D\uDCE5 Excel Export';
      }
    });
  }

  // --- CSV-Hilfsfunktionen ---
  function csvRow(cells) {
    return cells.map(function (c) {
      var s = String(c == null ? '' : c);
      if (s.indexOf(';') !== -1 || s.indexOf('"') !== -1 || s.indexOf('\n') !== -1) {
        s = '"' + s.replace(/"/g, '""') + '"';
      }
      return s;
    }).join(';') + '\n';
  }

  function csvNum(val) {
    if (val === undefined || val === null || val === '') return '';
    var num = parseFloat(val);
    if (isNaN(num)) return String(val);
    return num.toLocaleString('de-AT', { minimumFractionDigits: 0, maximumFractionDigits: 2 });
  }

  // --- Formatierung: deutsches Zahlenformat ---
  function formatNum(val) {
    if (val === undefined || val === null || val === '') return '-';
    var num = parseFloat(val);
    if (isNaN(num)) return String(val);
    return num.toLocaleString('de-AT', { minimumFractionDigits: 0, maximumFractionDigits: 2 });
  }

  // Global verfuegbar machen
  window.loadResults = loadResults;
  window.formatNum = formatNum;
})();
