/**
 * KI-Massenermittlung - Plan-Viewer mit Berechnungsnachweis
 * Zeigt den Plan links und die erkannten Elemente + Berechnungen rechts.
 * Der User kann prüfen ob alles korrekt erfasst wurde.
 */
(function () {
  'use strict';

  var PDFJS_CDN = 'https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.min.js';
  var PDFJS_WORKER = 'https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.worker.min.js';

  var pdfDoc = null, currentPage = null, scale = 1.0;
  var pdfCanvas, overlayCanvas, pdfCtx, overlayCtx, canvasContainer;
  var elements = [], massen = [];
  var viewerEl = null;
  var activeElement = null;

  var COLORS = {
    raum: { fill: 'rgba(26,58,92,0.15)', stroke: '#1a3a5c', bg: '#e8eef4' },
    fenster: { fill: 'rgba(34,197,94,0.15)', stroke: '#22c55e', bg: '#e8f8ef' },
    tuer: { fill: 'rgba(243,147,1,0.15)', stroke: '#f39301', bg: '#fef3e2' },
  };

  function createViewer() {
    if (document.getElementById('plan-viewer')) {
      document.getElementById('plan-viewer').remove();
    }

    var div = document.createElement('div');
    div.id = 'plan-viewer';
    div.className = 'plan-viewer';
    div.innerHTML =
      '<div class="plan-viewer-header">' +
        '<h3>Planansicht & Berechnungsnachweis</h3>' +
        '<div class="plan-viewer-controls">' +
          '<button class="btn btn-sm" id="pv-zoom-in">+</button>' +
          '<button class="btn btn-sm" id="pv-zoom-out">&minus;</button>' +
          '<button class="btn btn-sm" id="pv-zoom-fit">Anpassen</button>' +
        '</div>' +
        '<button class="btn btn-sm" id="pv-close">&times;</button>' +
      '</div>' +
      '<div class="plan-viewer-legend">' +
        '<span class="legend-item"><span class="legend-color" style="background:rgba(26,58,92,0.3);border:2px solid #1a3a5c"></span> R&auml;ume</span>' +
        '<span class="legend-item"><span class="legend-color" style="background:rgba(34,197,94,0.3);border:2px solid #22c55e"></span> Fenster</span>' +
        '<span class="legend-item"><span class="legend-color" style="background:rgba(243,147,1,0.3);border:2px solid #f39301"></span> T&uuml;ren</span>' +
        '<span class="legend-item" style="margin-left:auto;font-weight:600;color:#1a3a5c">Klicke auf ein Element f&uuml;r Details</span>' +
      '</div>' +
      '<div class="plan-viewer-body">' +
        '<div class="plan-canvas-container" id="pv-canvas-container">' +
          '<canvas id="pv-pdf-canvas"></canvas>' +
          '<canvas id="pv-overlay-canvas"></canvas>' +
        '</div>' +
        '<div class="plan-sidebar" id="pv-sidebar">' +
          '<div class="loading"><div class="spinner"></div> Lade Plan...</div>' +
        '</div>' +
      '</div>';

    var resultsSection = document.getElementById('results-section');
    if (resultsSection) {
      resultsSection.parentNode.insertBefore(div, resultsSection);
    } else {
      document.querySelector('.page-container').appendChild(div);
    }
    return div;
  }

  window.showPlanView = function (planId) {
    viewerEl = createViewer();
    viewerEl.scrollIntoView({ behavior: 'smooth' });

    pdfCanvas = document.getElementById('pv-pdf-canvas');
    overlayCanvas = document.getElementById('pv-overlay-canvas');
    pdfCtx = pdfCanvas.getContext('2d');
    overlayCtx = overlayCanvas.getContext('2d');
    canvasContainer = document.getElementById('pv-canvas-container');

    // Controls
    document.getElementById('pv-zoom-in').onclick = function () { zoomBy(1.3); };
    document.getElementById('pv-zoom-out').onclick = function () { zoomBy(0.7); };
    document.getElementById('pv-zoom-fit').onclick = zoomFit;
    document.getElementById('pv-close').onclick = function () { viewerEl.remove(); };

    // Overlay click handler
    overlayCanvas.addEventListener('click', handleOverlayClick);

    // Load data
    Promise.all([
      _sb.from('plaene').select('storage_path, agent_log').eq('id', planId).single(),
      _sb.from('elemente').select('*').eq('plan_id', planId),
      _sb.from('massen').select('*').eq('plan_id', planId),
    ]).then(function (res) {
      var plan = res[0].data;
      elements = res[1].data || [];
      massen = res[2].data || [];

      renderSidebar();

      _sb.storage.from('plaene').createSignedUrl(plan.storage_path, 3600).then(function (urlRes) {
        if (urlRes.error) return;
        loadPdfJs().then(function () {
          var task = window.pdfjsLib.getDocument(urlRes.data.signedUrl);
          task.promise.then(function (pdf) {
            pdfDoc = pdf;
            pdf.getPage(1).then(function (page) {
              currentPage = page;
              zoomFit();
            });
          });
        });
      });
    });
  };

  // --- Sidebar mit Raumliste + Berechnungen ---
  function renderSidebar() {
    var sb = document.getElementById('pv-sidebar');
    var html = '';

    // Gruppiere nach Wohnung
    var wohnungen = {};
    elements.forEach(function (el) {
      var d = el.daten || {};
      var w = d.wohnung || el.typ || 'Sonstige';
      if (!wohnungen[w]) wohnungen[w] = [];
      wohnungen[w].push(el);
    });

    // Zusammenfassung
    var rCount = elements.filter(function (e) { return e.typ === 'raum'; }).length;
    var fCount = elements.filter(function (e) { return e.typ === 'fenster'; }).length;
    var tCount = elements.filter(function (e) { return e.typ === 'tuer'; }).length;

    html += '<div style="padding:0.75rem;background:#f0f4ff;border-bottom:1px solid #ddd;font-size:0.85rem">';
    html += '<strong>' + rCount + ' R&auml;ume</strong>, ' + fCount + ' Fenster, ' + tCount + ' T&uuml;ren<br>';
    html += '<span style="color:#6b7280">' + Object.keys(wohnungen).length + ' Wohnungen erkannt</span>';
    html += '</div>';

    // Pro Wohnung
    Object.keys(wohnungen).sort().forEach(function (wName) {
      var items = wohnungen[wName];
      var raeume = items.filter(function (e) { return e.typ === 'raum'; });
      var totalFlaeche = raeume.reduce(function (s, r) { return s + (r.daten?.flaeche_m2 || 0); }, 0);

      html += '<div class="sidebar-whg">';
      html += '<div class="sidebar-whg-header" onclick="this.parentElement.classList.toggle(\'collapsed\')">';
      html += '<strong>' + esc(wName) + '</strong> (' + raeume.length + ' R., ' + totalFlaeche.toFixed(1) + 'm&sup2;)';
      html += ' <span style="float:right">&#9660;</span>';
      html += '</div>';
      html += '<div class="sidebar-whg-body">';

      items.forEach(function (el) {
        var d = el.daten || {};
        var color = COLORS[el.typ] || COLORS.raum;
        var konfBadge = el.konfidenz >= 80 ? 'confidence-green' : el.konfidenz >= 60 ? 'confidence-yellow' : 'confidence-red';

        html += '<div class="sidebar-element ' + el.typ + '" data-id="' + el.id + '">';
        html += '<div class="sidebar-element-name">';
        html += '<span class="sidebar-type-dot" style="background:' + color.stroke + '"></span>';
        html += esc(el.bezeichnung || d.name || el.typ);
        html += ' <span class="confidence-badge ' + konfBadge + '">' + (el.konfidenz || '?') + '%</span>';
        html += '</div>';

        if (el.typ === 'raum') {
          html += '<div class="sidebar-element-detail">';
          if (d.flaeche_m2) html += d.flaeche_m2 + ' m&sup2;';
          if (d.umfang_m) html += ' &middot; U: ' + d.umfang_m + 'm';
          if (d.hoehe_m) html += ' &middot; H: ' + d.hoehe_m + 'm';
          if (d.bodenbelag) html += ' &middot; ' + esc(d.bodenbelag);

          // Berechnete Wandlängen anzeigen
          if (d.flaeche_m2 && d.umfang_m) {
            var halfU = d.umfang_m / 2;
            var disc = halfU * halfU - 4 * d.flaeche_m2;
            if (disc >= 0) {
              var a = (halfU + Math.sqrt(disc)) / 2;
              var b = (halfU - Math.sqrt(disc)) / 2;
              html += '<br><span style="color:#1a3a5c;font-weight:600">Seiten: ' + a.toFixed(2) + 'm &times; ' + b.toFixed(2) + 'm</span>';
            }
          }
          html += '</div>';
        }

        if (el.typ === 'fenster') {
          html += '<div class="sidebar-element-detail">';
          if (d.al_breite_mm) html += 'AL ' + d.al_breite_mm + '&times;' + (d.al_hoehe_mm || '?') + 'mm';
          if (d.rb_breite_mm) html += ' &middot; RB ' + d.rb_breite_mm + '&times;' + (d.rb_hoehe_mm || '?') + 'mm';
          if (d.raum) html += ' &middot; ' + esc(d.raum);
          html += '</div>';
        }

        if (el.typ === 'tuer') {
          html += '<div class="sidebar-element-detail">';
          if (d.breite_mm) html += d.breite_mm + '&times;' + (d.hoehe_mm || '?') + 'mm';
          if (d.typ) html += ' &middot; ' + esc(d.typ);
          if (d.raum) html += ' &middot; ' + esc(d.raum);
          html += '</div>';
        }

        html += '</div>';
      });

      html += '</div></div>';
    });

    // Massen-Zusammenfassung
    if (massen.length > 0) {
      html += '<div style="padding:0.75rem;background:#fef3e2;border-top:2px solid #f39301;margin-top:0.5rem">';
      html += '<strong>Massenberechnung (' + massen.length + ' Positionen)</strong>';
      html += '</div>';

      massen.sort(function (a, b) { return (a.pos_nr || '').localeCompare(b.pos_nr || ''); });
      massen.forEach(function (m) {
        html += '<div class="sidebar-element raum" style="border-left-color:#f39301">';
        html += '<div class="sidebar-element-name" style="font-size:0.8rem">';
        html += '<strong>' + esc(m.pos_nr || '') + '</strong> ' + esc(m.beschreibung || '');
        html += '</div>';
        html += '<div class="sidebar-element-detail">';
        html += '<strong>' + formatNum(m.endsumme) + ' ' + esc(m.einheit || '') + '</strong>';
        if (m.gewerk) html += ' &middot; ' + esc(m.gewerk);
        html += '</div>';

        // Berechnungsschritte
        var ber = m.berechnung;
        if (ber && Array.isArray(ber) && ber.length > 0) {
          html += '<div class="sidebar-berechnung">';
          ber.forEach(function (step) {
            html += '<div class="berechnung-step">' + esc(String(step)) + '</div>';
          });
          html += '</div>';
        }
        html += '</div>';
      });
    }

    sb.innerHTML = html;

    // Click handlers for sidebar elements
    sb.querySelectorAll('.sidebar-element[data-id]').forEach(function (el) {
      el.addEventListener('click', function () {
        var id = this.getAttribute('data-id');
        highlightElement(id);
      });
    });
  }

  // --- Highlight element on plan ---
  function highlightElement(elId) {
    activeElement = elId;
    drawOverlays();

    // Scroll sidebar element into view
    var sidebarEl = document.querySelector('.sidebar-element[data-id="' + elId + '"]');
    if (sidebarEl) {
      document.querySelectorAll('.sidebar-element.highlighted').forEach(function (e) { e.classList.remove('highlighted'); });
      sidebarEl.classList.add('highlighted');
      sidebarEl.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }
  }

  // --- Draw overlays ---
  function drawOverlays() {
    if (!overlayCtx) return;
    overlayCtx.clearRect(0, 0, overlayCanvas.width, overlayCanvas.height);

    elements.forEach(function (el) {
      var pos = el.daten && el.daten.position_pct;
      if (!pos || !Array.isArray(pos) || pos.length < 4) return;

      var color = COLORS[el.typ] || COLORS.raum;
      var isActive = el.id === activeElement;
      var x = (pos[0] / 100) * overlayCanvas.width;
      var y = (pos[1] / 100) * overlayCanvas.height;
      var w = Math.max((pos[2] / 100) * overlayCanvas.width, 20);
      var h = Math.max((pos[3] / 100) * overlayCanvas.height, 15);

      // Fill
      overlayCtx.fillStyle = isActive ? color.stroke + '44' : color.fill;
      overlayCtx.fillRect(x, y, w, h);

      // Border
      overlayCtx.strokeStyle = color.stroke;
      overlayCtx.lineWidth = isActive ? 3 : 1.5;
      overlayCtx.strokeRect(x, y, w, h);

      // Label (only for rooms and active elements)
      if (el.typ === 'raum' || isActive) {
        var label = el.bezeichnung || '';
        if (el.typ === 'raum' && el.daten?.flaeche_m2) {
          label += ' ' + el.daten.flaeche_m2 + 'm²';
        }
        overlayCtx.font = (isActive ? 'bold ' : '') + '10px sans-serif';
        overlayCtx.fillStyle = 'rgba(255,255,255,0.9)';
        var tw = overlayCtx.measureText(label).width;
        overlayCtx.fillRect(x + 2, y + 2, tw + 6, 14);
        overlayCtx.fillStyle = color.stroke;
        overlayCtx.fillText(label, x + 5, y + 13);
      }
    });
  }

  // --- Handle overlay click ---
  function handleOverlayClick(e) {
    var rect = overlayCanvas.getBoundingClientRect();
    var cx = (e.clientX - rect.left) / (rect.width / overlayCanvas.width);
    var cy = (e.clientY - rect.top) / (rect.height / overlayCanvas.height);

    var clicked = null;
    elements.forEach(function (el) {
      var pos = el.daten && el.daten.position_pct;
      if (!pos || pos.length < 4) return;
      var x = (pos[0] / 100) * overlayCanvas.width;
      var y = (pos[1] / 100) * overlayCanvas.height;
      var w = (pos[2] / 100) * overlayCanvas.width;
      var h = (pos[3] / 100) * overlayCanvas.height;
      if (cx >= x && cx <= x + w && cy >= y && cy <= y + h) {
        clicked = el;
      }
    });

    if (clicked) {
      highlightElement(clicked.id);
    } else {
      activeElement = null;
      drawOverlays();
    }
  }

  // --- Zoom ---
  function zoomBy(factor) {
    scale = Math.max(0.3, Math.min(4.0, scale * factor));
    renderPage();
  }

  function zoomFit() {
    if (!currentPage) return;
    var cw = canvasContainer.parentElement.clientWidth - 300; // sidebar width
    var ch = Math.max(canvasContainer.parentElement.clientHeight, 500);
    var vp = currentPage.getViewport({ scale: 1.0 });
    scale = Math.min(cw / vp.width, ch / vp.height, 2.0);
    renderPage();
  }

  function renderPage() {
    if (!currentPage) return;
    var vp = currentPage.getViewport({ scale: scale });
    pdfCanvas.width = vp.width;
    pdfCanvas.height = vp.height;
    overlayCanvas.width = vp.width;
    overlayCanvas.height = vp.height;
    canvasContainer.style.minWidth = (vp.width + 20) + 'px';
    canvasContainer.style.minHeight = (vp.height + 20) + 'px';
    currentPage.render({ canvasContext: pdfCtx, viewport: vp }).promise.then(drawOverlays);
  }

  // --- PDF.js laden ---
  function loadPdfJs() {
    if (window.pdfjsLib) return Promise.resolve();
    return new Promise(function (resolve) {
      var s = document.createElement('script');
      s.src = PDFJS_CDN;
      s.onload = function () {
        window.pdfjsLib.GlobalWorkerOptions.workerSrc = PDFJS_WORKER;
        resolve();
      };
      document.head.appendChild(s);
    });
  }

  function esc(s) { var d = document.createElement('div'); d.textContent = s || ''; return d.innerHTML; }
  function formatNum(v) {
    if (v == null) return '-';
    return parseFloat(v).toLocaleString('de-AT', { minimumFractionDigits: 0, maximumFractionDigits: 2 });
  }
})();
