/**
 * KI-Massenermittlung - Plan-Viewer mit PDF-Anzeige und Element-Overlay
 * Zeigt den hochgeladenen Bauplan als PDF mit farbigen Markierungen
 * fuer erkannte Raeume, Fenster und Tueren.
 */
(function () {
  'use strict';

  var PDFJS_CDN = 'https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.min.js';
  var PDFJS_WORKER = 'https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.worker.min.js';

  // Farben je Elementtyp
  var COLORS = {
    raum:    { fill: '#1a3a5c33', stroke: '#1a3a5c', label: 'Raum' },
    fenster: { fill: '#22c55e33', stroke: '#22c55e', label: 'Fenster' },
    tuer:    { fill: '#f3930133', stroke: '#f39301', label: 'Tuer' }
  };

  var pdfDoc = null;
  var currentPage = null;
  var scale = 1.0;
  var baseScale = 1.0;
  var elements = [];
  var viewerEl = null;
  var pdfCanvas, overlayCanvas, pdfCtx, overlayCtx;
  var canvasContainer;
  var isDragging = false;
  var dragStart = { x: 0, y: 0 };
  var scrollStart = { x: 0, y: 0 };

  // --- Viewer-HTML erzeugen ---
  function createViewerHtml() {
    if (document.getElementById('plan-viewer')) return;

    var div = document.createElement('div');
    div.id = 'plan-viewer';
    div.className = 'plan-viewer hidden';
    div.innerHTML =
      '<div class="plan-viewer-header">' +
        '<h3>Planansicht</h3>' +
        '<div class="plan-viewer-controls">' +
          '<button class="btn btn-sm" id="zoom-in">+</button>' +
          '<button class="btn btn-sm" id="zoom-out">&minus;</button>' +
          '<button class="btn btn-sm" id="zoom-fit">Anpassen</button>' +
        '</div>' +
        '<button class="btn btn-sm" id="close-viewer">&times;</button>' +
      '</div>' +
      '<div class="plan-viewer-legend">' +
        '<span class="legend-item"><span class="legend-color" style="background:#1a3a5c55;border-color:#1a3a5c"></span> R&auml;ume</span>' +
        '<span class="legend-item"><span class="legend-color" style="background:#22c55e55;border-color:#22c55e"></span> Fenster</span>' +
        '<span class="legend-item"><span class="legend-color" style="background:#f3930155;border-color:#f39301"></span> T&uuml;ren</span>' +
      '</div>' +
      '<div class="plan-viewer-body">' +
        '<div class="plan-canvas-container" id="canvas-container">' +
          '<canvas id="pdf-canvas"></canvas>' +
          '<canvas id="overlay-canvas"></canvas>' +
        '</div>' +
        '<div class="plan-sidebar" id="plan-sidebar"></div>' +
      '</div>' +
      '<div class="element-tooltip hidden" id="element-tooltip"></div>';

    // Vor der results-section einfuegen
    var resultsSection = document.getElementById('results-section');
    if (resultsSection) {
      resultsSection.parentNode.insertBefore(div, resultsSection);
    } else {
      document.querySelector('.page-container').appendChild(div);
    }

    viewerEl = div;

    // Event-Listener
    document.getElementById('close-viewer').addEventListener('click', closeViewer);
    document.getElementById('zoom-in').addEventListener('click', function () { zoomBy(1.25); });
    document.getElementById('zoom-out').addEventListener('click', function () { zoomBy(0.8); });
    document.getElementById('zoom-fit').addEventListener('click', function () { zoomFit(); });
  }

  // --- PDF.js laden ---
  function loadPdfJs() {
    return new Promise(function (resolve, reject) {
      if (window.pdfjsLib) { resolve(); return; }
      var s = document.createElement('script');
      s.src = PDFJS_CDN;
      s.onload = function () {
        window.pdfjsLib.GlobalWorkerOptions.workerSrc = PDFJS_WORKER;
        resolve();
      };
      s.onerror = reject;
      document.head.appendChild(s);
    });
  }

  // --- Hauptfunktion ---
  window.showPlanView = function (planId) {
    if (!planId) return;

    createViewerHtml();
    viewerEl.classList.remove('hidden');
    viewerEl.scrollIntoView({ behavior: 'smooth', block: 'start' });

    pdfCanvas = document.getElementById('pdf-canvas');
    overlayCanvas = document.getElementById('overlay-canvas');
    pdfCtx = pdfCanvas.getContext('2d');
    overlayCtx = overlayCanvas.getContext('2d');
    canvasContainer = document.getElementById('canvas-container');

    // Loading-Zustand
    var sidebar = document.getElementById('plan-sidebar');
    sidebar.innerHTML = '<div class="loading"><div class="spinner"></div> Lade Plan...</div>';

    // Pan-Events
    setupPanEvents();

    // Daten parallel laden
    Promise.all([
      _sb.from('plaene').select('storage_path, dateiname').eq('id', planId).single(),
      _sb.from('elemente').select('*').eq('plan_id', planId)
    ]).then(function (results) {
      var planRes = results[0];
      var elemRes = results[1];

      if (planRes.error) {
        sidebar.innerHTML = '<p style="color:#991b1b;padding:1rem">Fehler beim Laden des Plans.</p>';
        return;
      }

      var storagePath = planRes.data.storage_path;
      elements = (elemRes.data || []);

      // Sidebar befuellen
      renderSidebar(elements);

      // Signed URL erstellen und PDF laden
      _sb.storage.from('plaene').createSignedUrl(storagePath, 3600).then(function (urlRes) {
        if (urlRes.error) {
          sidebar.innerHTML = '<p style="color:#991b1b;padding:1rem">Fehler: URL konnte nicht erstellt werden.</p>';
          return;
        }

        loadPdfJs().then(function () {
          renderPdf(urlRes.data.signedUrl);
        });
      });
    });
  };

  // --- PDF rendern ---
  function renderPdf(url) {
    var loadingTask = window.pdfjsLib.getDocument(url);
    loadingTask.promise.then(function (pdf) {
      pdfDoc = pdf;
      return pdf.getPage(1);
    }).then(function (page) {
      currentPage = page;
      zoomFit();
    }).catch(function (err) {
      console.error('PDF Fehler:', err);
      var sidebar = document.getElementById('plan-sidebar');
      sidebar.innerHTML = '<p style="color:#991b1b;padding:1rem">PDF konnte nicht geladen werden.</p>';
    });
  }

  // --- Seite bei aktuellem Scale zeichnen ---
  function renderPage() {
    if (!currentPage) return;

    var viewport = currentPage.getViewport({ scale: scale });
    pdfCanvas.width = viewport.width;
    pdfCanvas.height = viewport.height;
    overlayCanvas.width = viewport.width;
    overlayCanvas.height = viewport.height;

    // Container-Mindestgroesse setzen
    var w = viewport.width + 32;
    var h = viewport.height + 32;
    canvasContainer.style.minWidth = w + 'px';
    canvasContainer.style.minHeight = h + 'px';

    currentPage.render({
      canvasContext: pdfCtx,
      viewport: viewport
    }).promise.then(function () {
      drawOverlays();
    });
  }

  // --- Overlays zeichnen ---
  function drawOverlays() {
    overlayCtx.clearRect(0, 0, overlayCanvas.width, overlayCanvas.height);

    elements.forEach(function (el) {
      var pos = el.daten && el.daten.position_pct;
      if (!pos || pos.length < 4) return;

      var color = COLORS[el.typ] || COLORS.raum;
      var x = (pos[0] / 100) * overlayCanvas.width;
      var y = (pos[1] / 100) * overlayCanvas.height;
      var w = (pos[2] / 100) * overlayCanvas.width;
      var h = (pos[3] / 100) * overlayCanvas.height;

      // Hintergrund
      overlayCtx.fillStyle = color.fill;
      overlayCtx.fillRect(x, y, w, h);

      // Rand
      overlayCtx.strokeStyle = color.stroke;
      overlayCtx.lineWidth = 2;
      overlayCtx.strokeRect(x, y, w, h);

      // Label
      var label = el.bezeichnung || el.typ;
      overlayCtx.font = '12px "Segoe UI", system-ui, sans-serif';
      overlayCtx.fillStyle = color.stroke;
      var textW = overlayCtx.measureText(label).width;

      // Label-Hintergrund
      overlayCtx.fillStyle = 'rgba(255,255,255,0.85)';
      overlayCtx.fillRect(x, y - 18, textW + 8, 18);

      overlayCtx.fillStyle = color.stroke;
      overlayCtx.fillText(label, x + 4, y - 5);
    });
  }

  // --- Zoom ---
  function zoomBy(factor) {
    scale *= factor;
    scale = Math.max(0.25, Math.min(5.0, scale));
    renderPage();
  }

  function zoomFit() {
    if (!currentPage) return;
    var containerW = canvasContainer.parentElement.clientWidth - 32;
    var containerH = canvasContainer.parentElement.clientHeight - 32;
    if (containerH < 200) containerH = 500;

    var viewport = currentPage.getViewport({ scale: 1.0 });
    var scaleW = containerW / viewport.width;
    var scaleH = containerH / viewport.height;
    baseScale = Math.min(scaleW, scaleH, 2.0);
    scale = baseScale;
    renderPage();
  }

  // --- Pan (Ziehen zum Scrollen) ---
  function setupPanEvents() {
    if (!canvasContainer) return;

    overlayCanvas.addEventListener('mousedown', function (e) {
      if (e.button !== 0) return;
      isDragging = true;
      dragStart.x = e.clientX;
      dragStart.y = e.clientY;
      scrollStart.x = canvasContainer.scrollLeft;
      scrollStart.y = canvasContainer.scrollTop;
      overlayCanvas.style.cursor = 'grabbing';
    });

    document.addEventListener('mousemove', function (e) {
      if (!isDragging) return;
      var dx = e.clientX - dragStart.x;
      var dy = e.clientY - dragStart.y;
      canvasContainer.scrollLeft = scrollStart.x - dx;
      canvasContainer.scrollTop = scrollStart.y - dy;
    });

    document.addEventListener('mouseup', function () {
      if (isDragging) {
        isDragging = false;
        if (overlayCanvas) overlayCanvas.style.cursor = 'crosshair';
      }
    });

    // Klick auf Overlay: Tooltip anzeigen
    overlayCanvas.addEventListener('click', function (e) {
      // Nur wenn nicht gedraggt wurde
      var dx = Math.abs(e.clientX - dragStart.x);
      var dy = Math.abs(e.clientY - dragStart.y);
      if (dx > 5 || dy > 5) return;

      var rect = overlayCanvas.getBoundingClientRect();
      var clickX = e.clientX - rect.left;
      var clickY = e.clientY - rect.top;

      // Welches Element wurde getroffen?
      var hit = null;
      elements.forEach(function (el) {
        var pos = el.daten && el.daten.position_pct;
        if (!pos || pos.length < 4) return;
        var x = (pos[0] / 100) * overlayCanvas.width;
        var y = (pos[1] / 100) * overlayCanvas.height;
        var w = (pos[2] / 100) * overlayCanvas.width;
        var h = (pos[3] / 100) * overlayCanvas.height;
        if (clickX >= x && clickX <= x + w && clickY >= y && clickY <= y + h) {
          hit = el;
        }
      });

      if (hit) {
        showTooltip(hit, e.clientX, e.clientY);
      } else {
        hideTooltip();
      }
    });

    // Mausrad-Zoom
    canvasContainer.addEventListener('wheel', function (e) {
      if (e.ctrlKey || e.metaKey) {
        e.preventDefault();
        var factor = e.deltaY < 0 ? 1.1 : 0.9;
        zoomBy(factor);
      }
    }, { passive: false });
  }

  // --- Tooltip ---
  function showTooltip(el, x, y) {
    var tooltip = document.getElementById('element-tooltip');
    if (!tooltip) return;

    var color = COLORS[el.typ] || COLORS.raum;
    var html = '<h4 style="color:' + color.stroke + '">' + (el.bezeichnung || el.typ) + '</h4>';
    html += '<div class="detail-row"><span class="detail-label">Typ</span><span class="detail-value">' + (color.label) + '</span></div>';

    if (el.konfidenz != null) {
      html += '<div class="detail-row"><span class="detail-label">Konfidenz</span><span class="detail-value">' + Math.round(el.konfidenz) + '%</span></div>';
    }

    // Daten anzeigen
    if (el.daten) {
      var skip = ['position_pct'];
      Object.keys(el.daten).forEach(function (key) {
        if (skip.indexOf(key) >= 0) return;
        var val = el.daten[key];
        if (val === null || val === undefined || val === '') return;
        var displayKey = key.replace(/_/g, ' ');
        displayKey = displayKey.charAt(0).toUpperCase() + displayKey.slice(1);
        html += '<div class="detail-row"><span class="detail-label">' + displayKey + '</span><span class="detail-value">' + val + '</span></div>';
      });
    }

    tooltip.innerHTML = html;
    tooltip.classList.remove('hidden');

    // Position berechnen (sicherstellen, dass Tooltip im Viewport bleibt)
    var tw = tooltip.offsetWidth;
    var th = tooltip.offsetHeight;
    var posX = x + 12;
    var posY = y + 12;
    if (posX + tw > window.innerWidth - 16) posX = x - tw - 12;
    if (posY + th > window.innerHeight - 16) posY = y - th - 12;
    tooltip.style.left = posX + 'px';
    tooltip.style.top = posY + 'px';
  }

  function hideTooltip() {
    var tooltip = document.getElementById('element-tooltip');
    if (tooltip) tooltip.classList.add('hidden');
  }

  // --- Sidebar ---
  function renderSidebar(elems) {
    var sidebar = document.getElementById('plan-sidebar');
    if (!sidebar) return;

    if (elems.length === 0) {
      sidebar.innerHTML = '<p style="color:#6b7280;padding:1rem;text-align:center">Keine Elemente gefunden.</p>';
      return;
    }

    // Nach Typ gruppieren
    var groups = { raum: [], fenster: [], tuer: [] };
    elems.forEach(function (el) {
      var t = el.typ || 'raum';
      if (!groups[t]) groups[t] = [];
      groups[t].push(el);
    });

    var html = '';
    var groupLabels = { raum: 'R\u00e4ume', fenster: 'Fenster', tuer: 'T\u00fcren' };

    Object.keys(groups).forEach(function (typ) {
      var items = groups[typ];
      if (items.length === 0) return;
      html += '<h4 style="font-size:0.85rem;color:#6b7280;margin:0.75rem 0 0.25rem;text-transform:uppercase;letter-spacing:0.05em">' + groupLabels[typ] + ' (' + items.length + ')</h4>';

      items.forEach(function (el) {
        var cssClass = typ === 'tuer' ? 'tuer' : typ;
        var detail = '';
        if (el.daten) {
          if (el.typ === 'raum' && el.daten.flaeche_m2) {
            detail = el.daten.flaeche_m2 + ' m\u00b2';
          } else if (el.typ === 'fenster' && el.daten.breite_mm && el.daten.hoehe_mm) {
            detail = el.daten.breite_mm + ' x ' + el.daten.hoehe_mm + ' mm';
          } else if (el.typ === 'tuer' && el.daten.breite_mm) {
            detail = el.daten.breite_mm + ' mm';
          }
        }

        html += '<div class="sidebar-element ' + cssClass + '" data-element-id="' + el.id + '">' +
          '<div class="sidebar-element-name">' + (el.bezeichnung || el.typ) + '</div>' +
          (detail ? '<div class="sidebar-element-detail">' + detail + '</div>' : '') +
          '</div>';
      });
    });

    sidebar.innerHTML = html;

    // Klick auf Sidebar-Element: Tooltip zeigen oder zum Element scrollen
    sidebar.querySelectorAll('.sidebar-element').forEach(function (item) {
      item.addEventListener('click', function () {
        var elId = this.getAttribute('data-element-id');
        var el = elements.find(function (e) { return e.id === elId; });
        if (!el) return;

        var pos = el.daten && el.daten.position_pct;
        if (pos && pos.length >= 4) {
          // Zum Element scrollen
          var x = (pos[0] / 100) * overlayCanvas.width;
          var y = (pos[1] / 100) * overlayCanvas.height;
          canvasContainer.scrollTo({
            left: x - canvasContainer.clientWidth / 2,
            top: y - canvasContainer.clientHeight / 2,
            behavior: 'smooth'
          });

          // Kurz aufleuchten
          highlightElement(el);
        }

        // Sidebar-Auswahl markieren
        sidebar.querySelectorAll('.sidebar-element').forEach(function (s) { s.style.background = ''; });
        this.style.background = '#f0f4ff';
      });
    });
  }

  // --- Element kurz hervorheben ---
  function highlightElement(el) {
    var pos = el.daten && el.daten.position_pct;
    if (!pos || pos.length < 4) return;

    var color = COLORS[el.typ] || COLORS.raum;
    var x = (pos[0] / 100) * overlayCanvas.width;
    var y = (pos[1] / 100) * overlayCanvas.height;
    var w = (pos[2] / 100) * overlayCanvas.width;
    var h = (pos[3] / 100) * overlayCanvas.height;

    // Highlight-Effekt
    overlayCtx.save();
    overlayCtx.strokeStyle = color.stroke;
    overlayCtx.lineWidth = 4;
    overlayCtx.shadowColor = color.stroke;
    overlayCtx.shadowBlur = 12;
    overlayCtx.strokeRect(x, y, w, h);
    overlayCtx.restore();

    // Nach kurzer Zeit zuruecksetzen
    setTimeout(function () {
      drawOverlays();
    }, 1500);
  }

  // --- Viewer schliessen ---
  function closeViewer() {
    if (viewerEl) {
      viewerEl.classList.add('hidden');
      hideTooltip();
    }
  }

  // Auch beim Druecken von Escape schliessen
  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape') closeViewer();
  });

  // Tooltip schliessen bei Klick ausserhalb
  document.addEventListener('click', function (e) {
    var tooltip = document.getElementById('element-tooltip');
    if (tooltip && !tooltip.contains(e.target) && e.target.id !== 'overlay-canvas') {
      hideTooltip();
    }
  });

})();
