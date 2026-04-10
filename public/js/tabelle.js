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
          var alterWert = parseFloat(originalValue.replace(',', '.'));
          if (isNaN(alterWert)) alterWert = 0;

          _sb.from('massen')
            .update({ endsumme: numVal, manuell_korrigiert: true })
            .eq('id', masseId)
            .then(function (res) {
              if (res.error) console.error('Fehler beim Speichern:', res.error.message);
            });

          // Lern-Agent aufrufen
          fetch(SUPABASE_URL + '/functions/v1/lern-agent', {
            method: 'POST',
            headers: {
              'Content-Type': 'application/json',
              'Authorization': 'Bearer ' + SUPABASE_ANON_KEY
            },
            body: JSON.stringify({
              masse_id: masseId,
              feld: 'endsumme',
              alter_wert: alterWert,
              neuer_wert: numVal,
              firma_id: getSession().id
            })
          })
            .then(function (r) { return r.json(); })
            .then(function (data) {
              if (data.neue_regel) {
                showNotification('Lernregel erstellt');
              }
            })
            .catch(function (err) {
              console.error('Lern-Agent Fehler:', err);
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

      // Details-Button fuer Berechnungsschritte
      if (m.berechnung && Array.isArray(m.berechnung) && m.berechnung.length > 0) {
        var tdDetails = document.createElement('td');
        var detailBtn = document.createElement('button');
        detailBtn.className = 'btn btn-outline btn-sm';
        detailBtn.textContent = 'Details';
        detailBtn.addEventListener('click', (function (masse) {
          return function () { showBerechnungModal(masse); };
        })(m));
        tdDetails.appendChild(detailBtn);
        tr.appendChild(tdDetails);
      } else {
        addCell(tr, '');
      }

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

  // --- Excel Export (via Edge Function) ---
  if (exportBtn) {
    exportBtn.addEventListener('click', function () {
      if (!currentPlanId) return;
      exportBtn.disabled = true;
      exportBtn.textContent = 'Wird exportiert...';

      fetch(SUPABASE_URL + '/functions/v1/excel-export', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': 'Bearer ' + SUPABASE_ANON_KEY
        },
        body: JSON.stringify({ plan_id: currentPlanId })
      })
        .then(function (res) {
          if (!res.ok) {
            return res.json().then(function (d) {
              throw new Error(d.detail || d.error || 'Export fehlgeschlagen');
            });
          }
          return res.blob();
        })
        .then(function (blob) {
          var url = window.URL.createObjectURL(blob);
          var a = document.createElement('a');
          a.href = url;
          a.download = 'massenermittlung_' + currentPlanId + '.xlsx';
          document.body.appendChild(a);
          a.click();
          document.body.removeChild(a);
          window.URL.revokeObjectURL(url);
        })
        .catch(function (err) {
          console.error('Export-Fehler:', err);
          showNotification('Export-Fehler: ' + err.message);
        })
        .finally(function () {
          exportBtn.disabled = false;
          exportBtn.textContent = '\uD83D\uDCE5 Excel Export';
        });
    });
  }

  // --- Formatierung: deutsches Zahlenformat ---
  function formatNum(val) {
    if (val === undefined || val === null || val === '') return '-';
    var num = parseFloat(val);
    if (isNaN(num)) return String(val);
    return num.toLocaleString('de-AT', { minimumFractionDigits: 0, maximumFractionDigits: 2 });
  }

  // --- Berechnungsdetails Modal ---
  function showBerechnungModal(masse) {
    // Vorheriges Modal entfernen
    var existing = document.getElementById('berechnung-modal');
    if (existing) existing.remove();

    var overlay = document.createElement('div');
    overlay.id = 'berechnung-modal';
    overlay.style.cssText = 'position:fixed;top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,0.5);z-index:9999;display:flex;align-items:center;justify-content:center;';

    var box = document.createElement('div');
    box.style.cssText = 'background:#fff;border-radius:12px;padding:2rem;max-width:560px;width:90%;max-height:80vh;overflow-y:auto;box-shadow:0 8px 32px rgba(0,0,0,0.2);';

    var title = document.createElement('h3');
    title.style.cssText = 'margin:0 0 1rem 0;font-size:1.1rem;';
    title.textContent = 'Berechnungsdetails - ' + (masse.beschreibung || '');
    box.appendChild(title);

    var list = document.createElement('ol');
    list.style.cssText = 'margin:0 0 1.5rem 1.2rem;padding:0;line-height:1.8;';
    masse.berechnung.forEach(function (step) {
      var li = document.createElement('li');
      li.textContent = step;
      list.appendChild(li);
    });
    box.appendChild(list);

    var closeBtn = document.createElement('button');
    closeBtn.className = 'btn btn-primary btn-sm';
    closeBtn.textContent = 'Schliessen';
    closeBtn.addEventListener('click', function () { overlay.remove(); });
    box.appendChild(closeBtn);

    overlay.appendChild(box);
    overlay.addEventListener('click', function (e) { if (e.target === overlay) overlay.remove(); });
    document.body.appendChild(overlay);
  }

  // --- Benachrichtigung anzeigen ---
  function showNotification(text) {
    var note = document.createElement('div');
    note.textContent = text;
    note.style.cssText = 'position:fixed;bottom:2rem;right:2rem;background:#1a7f5a;color:#fff;padding:0.75rem 1.5rem;border-radius:8px;font-size:0.9rem;z-index:9999;box-shadow:0 4px 12px rgba(0,0,0,0.15);transition:opacity 0.3s;';
    document.body.appendChild(note);
    setTimeout(function () { note.style.opacity = '0'; setTimeout(function () { note.remove(); }, 300); }, 3000);
  }

  // Global verfuegbar machen
  window.loadResults = loadResults;
  window.formatNum = formatNum;
})();
