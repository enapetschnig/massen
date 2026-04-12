/**
 * Plan-Viewer - Zeigt den PDF-Plan neben einer Verifizierungsliste.
 * Keine geschätzten Overlays - nur der echte Plan + extrahierte Daten zum Prüfen.
 */
(function () {
  'use strict';

  var PDFJS_CDN = 'https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.min.js';
  var PDFJS_WORKER = 'https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.worker.min.js';
  var pdfDoc = null, currentPage = null, scale = 1.0;
  var pdfCanvas, pdfCtx, canvasContainer;

  window.showPlanView = function (planId) {
    // Remove old viewer
    var old = document.getElementById('plan-viewer');
    if (old) old.remove();

    var div = document.createElement('div');
    div.id = 'plan-viewer';
    div.className = 'plan-viewer';
    div.innerHTML =
      '<div class="plan-viewer-header">' +
        '<h3>Plan pr&uuml;fen</h3>' +
        '<div class="plan-viewer-controls">' +
          '<button class="btn btn-sm" id="pv-zoom-in">+</button>' +
          '<button class="btn btn-sm" id="pv-zoom-out">&minus;</button>' +
          '<button class="btn btn-sm" id="pv-zoom-fit">Anpassen</button>' +
        '</div>' +
        '<button class="btn btn-sm" id="pv-close">&times;</button>' +
      '</div>' +
      '<div class="plan-viewer-body">' +
        '<div class="plan-canvas-container" id="pv-canvas-container">' +
          '<canvas id="pv-pdf-canvas"></canvas>' +
        '</div>' +
        '<div class="plan-sidebar" id="pv-sidebar">' +
          '<div class="loading"><div class="spinner"></div> Lade...</div>' +
        '</div>' +
      '</div>';

    var target = document.getElementById('results-section');
    if (target) target.parentNode.insertBefore(div, target);
    else document.querySelector('.page-container').appendChild(div);

    div.scrollIntoView({ behavior: 'smooth' });

    pdfCanvas = document.getElementById('pv-pdf-canvas');
    pdfCtx = pdfCanvas.getContext('2d');
    canvasContainer = document.getElementById('pv-canvas-container');

    document.getElementById('pv-zoom-in').onclick = function () { scale = Math.min(4, scale * 1.3); renderPage(); };
    document.getElementById('pv-zoom-out').onclick = function () { scale = Math.max(0.3, scale * 0.7); renderPage(); };
    document.getElementById('pv-zoom-fit').onclick = zoomFit;
    document.getElementById('pv-close').onclick = function () { div.remove(); };

    // Drag to pan
    var drag = false, sx = 0, sy = 0, sleft = 0, stop = 0;
    canvasContainer.onmousedown = function (e) { drag = true; sx = e.clientX; sy = e.clientY; sleft = canvasContainer.scrollLeft; stop = canvasContainer.scrollTop; };
    document.onmousemove = function (e) { if (!drag) return; canvasContainer.scrollLeft = sleft - (e.clientX - sx); canvasContainer.scrollTop = stop - (e.clientY - sy); };
    document.onmouseup = function () { drag = false; };

    // Load data
    Promise.all([
      _sb.from('plaene').select('storage_path, agent_log').eq('id', planId).single(),
      _sb.from('elemente').select('*').eq('plan_id', planId),
      _sb.from('massen').select('*').eq('plan_id', planId),
    ]).then(function (res) {
      var plan = res[0].data;
      var elemente = res[1].data || [];
      var massen = res[2].data || [];
      var pdfText = (plan.agent_log || {}).pdf_text || {};

      renderSidebar(elemente, massen, pdfText);

      _sb.storage.from('plaene').createSignedUrl(plan.storage_path, 3600).then(function (urlRes) {
        if (urlRes.error) return;
        loadPdfJs().then(function () {
          pdfjsLib.getDocument(urlRes.data.signedUrl).promise.then(function (pdf) {
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

  function renderSidebar(elemente, massen, pdfText) {
    var sb = document.getElementById('pv-sidebar');
    var raeume = elemente.filter(function (e) { return e.typ === 'raum'; });
    var fenster = elemente.filter(function (e) { return e.typ === 'fenster'; });
    var tueren = elemente.filter(function (e) { return e.typ === 'tuer'; });
    var dims = (pdfText.dimensions || []);

    var html = '';

    // Header
    html += '<div style="padding:0.75rem;background:#1a3a5c;color:white;font-size:0.85rem">';
    html += '<strong>' + raeume.length + ' R&auml;ume</strong> &middot; ' + fenster.length + ' Fenster &middot; ' + tueren.length + ' T&uuml;ren &middot; ' + massen.length + ' Massen';
    if (dims.length > 0) html += '<br><span style="opacity:0.8">' + dims.length + ' Ma&szlig;ketten-Werte aus PDF extrahiert</span>';
    html += '</div>';

    // Verification checklist for rooms
    html += '<div style="padding:0.5rem 0.75rem;background:#e8f5e9;border-bottom:1px solid #c8e6c9;font-weight:600;font-size:0.85rem">R&auml;ume pr&uuml;fen</div>';

    // Group by apartment
    var whg = {};
    raeume.forEach(function (r) {
      var w = (r.daten || {}).wohnung || 'Sonstige';
      if (!whg[w]) whg[w] = [];
      whg[w].push(r);
    });

    Object.keys(whg).sort().forEach(function (wName) {
      var rooms = whg[wName];
      var totalF = rooms.reduce(function (s, r) { return s + ((r.daten || {}).flaeche_m2 || 0); }, 0);
      html += '<div class="pv-whg">';
      html += '<div class="pv-whg-head" onclick="this.parentElement.classList.toggle(\'collapsed\')">' + esc(wName) + ' <span style="color:#666">(' + rooms.length + ' R., ' + totalF.toFixed(1) + 'm&sup2;)</span> <span style="float:right">&#9660;</span></div>';

      rooms.forEach(function (r) {
        var d = r.daten || {};
        var hasF = d.flaeche_m2 > 0;
        var hasU = d.umfang_m > 0;
        var hasH = d.hoehe_m > 0;
        var icon = (hasF && hasU && hasH) ? '&#9989;' : '&#9888;&#65039;';

        html += '<div class="pv-room">';
        html += '<div class="pv-room-name">' + icon + ' ' + esc(r.bezeichnung || d.name || '?');
        html += ' <span class="pv-conf ' + (r.konfidenz >= 80 ? 'green' : r.konfidenz >= 60 ? 'yellow' : 'red') + '">' + (r.konfidenz || '?') + '%</span></div>';
        html += '<div class="pv-room-data">';
        html += hasF ? '<span>F: ' + d.flaeche_m2 + ' m&sup2;</span>' : '<span class="pv-missing">F: fehlt!</span>';
        html += hasU ? '<span>U: ' + d.umfang_m + ' m</span>' : '<span class="pv-missing">U: fehlt!</span>';
        html += hasH ? '<span>H: ' + d.hoehe_m + ' m</span>' : '<span class="pv-missing">H: fehlt!</span>';
        if (d.bodenbelag) html += '<span>' + esc(d.bodenbelag) + '</span>';
        html += '</div>';

        // Show calculated wall dimensions
        if (hasF && hasU) {
          var halfU = d.umfang_m / 2;
          var disc = halfU * halfU - 4 * d.flaeche_m2;
          if (disc >= 0) {
            var a = (halfU + Math.sqrt(disc)) / 2;
            var b = (halfU - Math.sqrt(disc)) / 2;
            html += '<div class="pv-calc">Wandl&auml;ngen: <strong>' + a.toFixed(2) + 'm &times; ' + b.toFixed(2) + 'm</strong> (berechnet aus F+U)</div>';
          }
        }
        html += '</div>';
      });
      html += '</div>';
    });

    // Fenster
    if (fenster.length > 0) {
      html += '<div style="padding:0.5rem 0.75rem;background:#e3f2fd;border-bottom:1px solid #bbdefb;font-weight:600;font-size:0.85rem">Fenster pr&uuml;fen</div>';
      fenster.forEach(function (f) {
        var d = f.daten || {};
        html += '<div class="pv-room" style="border-left-color:#22c55e">';
        html += '<div class="pv-room-name" style="color:#22c55e">' + esc(f.bezeichnung || d.bezeichnung || '?');
        html += ' <span class="pv-conf ' + (f.konfidenz >= 80 ? 'green' : 'yellow') + '">' + (f.konfidenz || '?') + '%</span></div>';
        html += '<div class="pv-room-data">';
        if (d.al_breite_mm) html += '<span>AL: ' + d.al_breite_mm + '&times;' + (d.al_hoehe_mm || '?') + '</span>';
        if (d.rb_breite_mm) html += '<span>RB: ' + d.rb_breite_mm + '&times;' + (d.rb_hoehe_mm || '?') + '</span>';
        if (d.raum) html += '<span>Raum: ' + esc(d.raum) + '</span>';
        html += '</div></div>';
      });
    }

    // Extracted dimensions from PDF
    if (dims.length > 0) {
      html += '<div style="padding:0.5rem 0.75rem;background:#fff3e0;border-bottom:1px solid #ffe0b2;font-weight:600;font-size:0.85rem">Ma&szlig;ketten aus PDF (' + dims.length + ')</div>';
      html += '<div style="padding:0.5rem;font-size:0.75rem;max-height:200px;overflow-y:auto">';
      dims.slice(0, 40).forEach(function (d) {
        html += '<span style="display:inline-block;background:#fff8e1;border:1px solid #ffe082;border-radius:4px;padding:1px 6px;margin:2px;font-family:monospace">' + d.value_m + 'm</span>';
      });
      if (dims.length > 40) html += '<span style="color:#999">... +' + (dims.length - 40) + ' weitere</span>';
      html += '</div>';
    }

    // Massen summary
    if (massen.length > 0) {
      html += '<div style="padding:0.5rem 0.75rem;background:#fce4ec;border-bottom:1px solid #f8bbd0;font-weight:600;font-size:0.85rem">Massen (' + massen.length + ' Positionen)</div>';
      massen.sort(function (a, b) { return (a.pos_nr || '').localeCompare(b.pos_nr || ''); });
      massen.forEach(function (m) {
        html += '<div class="pv-room" style="border-left-color:#f39301">';
        html += '<div class="pv-room-name" style="color:#f39301;font-size:0.8rem"><strong>' + esc(m.pos_nr || '') + '</strong> ' + esc(m.beschreibung || '') + '</div>';
        html += '<div class="pv-room-data"><strong>' + fnum(m.endsumme) + ' ' + esc(m.einheit || '') + '</strong>';
        if (m.gewerk) html += ' &middot; ' + esc(m.gewerk);
        html += '</div>';
        var ber = m.berechnung;
        if (ber && Array.isArray(ber) && ber.length > 0) {
          html += '<div class="pv-calc">';
          ber.slice(0, 5).forEach(function (s) { html += esc(String(s)) + '<br>'; });
          if (ber.length > 5) html += '<em>+' + (ber.length - 5) + ' weitere</em>';
          html += '</div>';
        }
        html += '</div>';
      });
    }

    sb.innerHTML = html;
  }

  function renderPage() {
    if (!currentPage) return;
    var vp = currentPage.getViewport({ scale: scale });
    pdfCanvas.width = vp.width;
    pdfCanvas.height = vp.height;
    canvasContainer.style.minWidth = (vp.width + 20) + 'px';
    canvasContainer.style.minHeight = (vp.height + 20) + 'px';
    currentPage.render({ canvasContext: pdfCtx, viewport: vp });
  }

  function zoomFit() {
    if (!currentPage) return;
    var cw = (canvasContainer.parentElement || canvasContainer).clientWidth - 360;
    var ch = Math.max(500, window.innerHeight - 200);
    var vp = currentPage.getViewport({ scale: 1.0 });
    scale = Math.min(cw / vp.width, ch / vp.height, 2.0);
    renderPage();
  }

  function loadPdfJs() {
    if (window.pdfjsLib) return Promise.resolve();
    return new Promise(function (res) {
      var s = document.createElement('script');
      s.src = PDFJS_CDN;
      s.onload = function () { pdfjsLib.GlobalWorkerOptions.workerSrc = PDFJS_WORKER; res(); };
      document.head.appendChild(s);
    });
  }

  function esc(s) { var d = document.createElement('div'); d.textContent = s || ''; return d.innerHTML; }
  function fnum(v) { return v != null ? parseFloat(v).toLocaleString('de-AT', { maximumFractionDigits: 2 }) : '-'; }
})();
