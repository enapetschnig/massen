/**
 * Plan-Viewer mit PIXELGENAUEN Overlays aus PDF-Textpositionen.
 * Nutzt pdf.js getTextContent() für exakte Koordinaten - NICHT Claude-Schätzungen.
 */
(function () {
  'use strict';

  var PDFJS_CDN = 'https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.min.js';
  var PDFJS_WORKER = 'https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.worker.min.js';
  var pdfDoc = null, currentPage = null, scale = 1.0;
  var pdfCanvas, overlayCanvas, pdfCtx, overlayCtx, canvasContainer;
  var textItems = [];    // Raw text items with EXACT positions from pdf.js
  var roomClusters = []; // Grouped room texts
  var activeCluster = null;

  var ROOM_KEYWORDS = ['wohnküche', 'wohnk', 'zimmer', 'schlafzimmer', 'kinderzimmer', 'bad', 'wc', 'dusche',
    'vorraum', 'flur', 'gang', 'diele', 'küche', 'loggia', 'balkon', 'terrasse', 'stiegenhaus',
    'abstellraum', 'garderobe', 'speis', 'technik', 'keller', 'waschk'];

  window.showPlanView = function (planId) {
    var old = document.getElementById('plan-viewer');
    if (old) old.remove();

    var div = document.createElement('div');
    div.id = 'plan-viewer';
    div.className = 'plan-viewer';
    div.innerHTML =
      '<div class="plan-viewer-header">' +
        '<h3>Planansicht</h3>' +
        '<div class="plan-viewer-controls">' +
          '<button class="btn btn-sm" id="pv-zoom-in">+</button>' +
          '<button class="btn btn-sm" id="pv-zoom-out">&minus;</button>' +
          '<button class="btn btn-sm" id="pv-zoom-fit">Anpassen</button>' +
          '<label style="font-size:0.8rem;margin-left:1rem"><input type="checkbox" id="pv-show-dims" checked> Ma&szlig;e</label>' +
          '<label style="font-size:0.8rem;margin-left:0.5rem"><input type="checkbox" id="pv-show-rooms" checked> R&auml;ume</label>' +
          '<label style="font-size:0.8rem;margin-left:0.5rem"><input type="checkbox" id="pv-show-fenster" checked> Fenster</label>' +
        '</div>' +
        '<button class="btn btn-sm" id="pv-close">&times;</button>' +
      '</div>' +
      '<div class="plan-viewer-legend">' +
        '<span class="legend-item"><span class="legend-color" style="background:rgba(26,58,92,0.25);border:2px solid #1a3a5c"></span> R&auml;ume/Fl&auml;chen</span>' +
        '<span class="legend-item"><span class="legend-color" style="background:rgba(34,197,94,0.25);border:2px solid #22c55e"></span> Fenster</span>' +
        '<span class="legend-item"><span class="legend-color" style="background:rgba(243,147,1,0.25);border:2px solid #f39301"></span> Ma&szlig;e</span>' +
      '</div>' +
      '<div class="plan-viewer-body">' +
        '<div class="plan-canvas-container" id="pv-canvas-container">' +
          '<canvas id="pv-pdf-canvas"></canvas>' +
          '<canvas id="pv-overlay-canvas" style="position:absolute;top:0;left:0;pointer-events:auto;cursor:crosshair"></canvas>' +
        '</div>' +
        '<div class="plan-sidebar" id="pv-sidebar"><div class="loading"><div class="spinner"></div> Lade Plan...</div></div>' +
      '</div>';

    var target = document.getElementById('results-section');
    if (target) target.parentNode.insertBefore(div, target);
    else document.querySelector('.page-container').appendChild(div);
    div.scrollIntoView({ behavior: 'smooth' });

    pdfCanvas = document.getElementById('pv-pdf-canvas');
    overlayCanvas = document.getElementById('pv-overlay-canvas');
    pdfCtx = pdfCanvas.getContext('2d');
    overlayCtx = overlayCanvas.getContext('2d');
    canvasContainer = document.getElementById('pv-canvas-container');

    document.getElementById('pv-zoom-in').onclick = function () { scale = Math.min(5, scale * 1.3); renderPage(); };
    document.getElementById('pv-zoom-out').onclick = function () { scale = Math.max(0.2, scale * 0.7); renderPage(); };
    document.getElementById('pv-zoom-fit').onclick = zoomFit;
    document.getElementById('pv-close').onclick = function () { div.remove(); };
    document.getElementById('pv-show-dims').onchange = drawOverlays;
    document.getElementById('pv-show-rooms').onchange = drawOverlays;
    document.getElementById('pv-show-fenster').onchange = drawOverlays;

    // Click on overlay
    overlayCanvas.onclick = function (e) {
      var rect = overlayCanvas.getBoundingClientRect();
      var cx = (e.clientX - rect.left) * (overlayCanvas.width / rect.width);
      var cy = (e.clientY - rect.top) * (overlayCanvas.height / rect.height);
      handleClick(cx, cy);
    };

    // Drag to pan
    var drag = false, sx = 0, sy = 0, sl = 0, st = 0;
    canvasContainer.onmousedown = function (e) { if (e.target === overlayCanvas && e.button === 0) { drag = true; sx = e.clientX; sy = e.clientY; sl = canvasContainer.scrollLeft; st = canvasContainer.scrollTop; e.preventDefault(); } };
    document.onmousemove = function (e) { if (!drag) return; canvasContainer.scrollLeft = sl - (e.clientX - sx); canvasContainer.scrollTop = st - (e.clientY - sy); };
    document.onmouseup = function () { drag = false; };

    // Load PDF and extract text
    _sb.from('plaene').select('storage_path').eq('id', planId).single().then(function (res) {
      return _sb.storage.from('plaene').createSignedUrl(res.data.storage_path, 3600);
    }).then(function (urlRes) {
      loadPdfJs().then(function () {
        pdfjsLib.getDocument(urlRes.data.signedUrl).promise.then(function (pdf) {
          pdfDoc = pdf;
          pdf.getPage(1).then(function (page) {
            currentPage = page;
            // Extract text with EXACT positions
            page.getTextContent().then(function (tc) {
              var vp = page.getViewport({ scale: 1.0 });
              processTextContent(tc, vp.width, vp.height);
              zoomFit();
            });
          });
        });
      });
    });

    // Load DB elements for sidebar
    Promise.all([
      _sb.from('elemente').select('*').eq('plan_id', planId),
      _sb.from('massen').select('*').eq('plan_id', planId),
    ]).then(function (res) {
      renderSidebar(res[0].data || [], res[1].data || []);
    });
  };

  // Process pdf.js text content into classified items
  function processTextContent(tc, pageW, pageH) {
    textItems = [];
    roomClusters = [];

    tc.items.forEach(function (item) {
      if (!item.str || !item.str.trim()) return;
      var tx = item.transform;
      // PDF coordinates: tx[4]=x, tx[5]=y (bottom-up)
      // We need top-down for canvas
      var x = tx[4];
      var y = pageH - tx[5];
      var w = item.width || 50;
      var h = Math.abs(tx[3]) || 10;

      var text = item.str.trim();
      var type = classifyText(text);

      textItems.push({ text: text, x: x, y: y - h, w: w, h: h, type: type, pageW: pageW, pageH: pageH });
    });

    // Cluster room-related texts that are close together
    var roomTexts = textItems.filter(function (t) { return t.type === 'room' || t.type === 'area' || t.type === 'umfang' || t.type === 'hoehe'; });
    clusterTexts(roomTexts);
  }

  function classifyText(text) {
    var lower = text.toLowerCase();
    // Room name
    for (var i = 0; i < ROOM_KEYWORDS.length; i++) {
      if (lower.includes(ROOM_KEYWORDS[i])) return 'room';
    }
    if (/top\s*\d/i.test(text)) return 'room';
    // Area (m²)
    if (/m[²2]/.test(text) || /\d+[.,]\d+\s*m/.test(text)) return 'area';
    // Umfang
    if (/^U\s*[:=]/i.test(text)) return 'umfang';
    // Height
    if (/^[RH]?H\s*[:=]/i.test(text)) return 'hoehe';
    // Fenster code
    if (/FE[_\s-]?\d/i.test(text)) return 'fenster';
    // Dimension (3-4 digit number)
    if (/^\d{3,4}$/.test(text)) {
      var v = parseInt(text) / 100;
      if (v > 0.5 && v < 25) return 'dimension';
    }
    return 'other';
  }

  function clusterTexts(items) {
    var used = new Array(items.length).fill(false);
    for (var i = 0; i < items.length; i++) {
      if (used[i]) continue;
      var cluster = [items[i]];
      used[i] = true;
      // Find nearby items (within 80 PDF points)
      for (var j = i + 1; j < items.length; j++) {
        if (used[j]) continue;
        var dx = Math.abs(items[j].x - items[i].x);
        var dy = Math.abs(items[j].y - items[i].y);
        if (dx < 150 && dy < 80) {
          cluster.push(items[j]);
          used[j] = true;
        }
      }
      if (cluster.length > 0) {
        var minX = Math.min.apply(null, cluster.map(function (c) { return c.x; }));
        var minY = Math.min.apply(null, cluster.map(function (c) { return c.y; }));
        var maxX = Math.max.apply(null, cluster.map(function (c) { return c.x + c.w; }));
        var maxY = Math.max.apply(null, cluster.map(function (c) { return c.y + c.h; }));
        var name = cluster.filter(function (c) { return c.type === 'room'; }).map(function (c) { return c.text; }).join(' ');
        var area = cluster.filter(function (c) { return c.type === 'area'; }).map(function (c) { return c.text; }).join(' ');
        roomClusters.push({ items: cluster, x: minX, y: minY, w: maxX - minX, h: maxY - minY, name: name, area: area });
      }
    }
  }

  // Draw overlays using EXACT PDF text positions
  function drawOverlays() {
    if (!overlayCtx || !currentPage) return;
    overlayCtx.clearRect(0, 0, overlayCanvas.width, overlayCanvas.height);

    var showDims = document.getElementById('pv-show-dims')?.checked;
    var showRooms = document.getElementById('pv-show-rooms')?.checked;
    var showFenster = document.getElementById('pv-show-fenster')?.checked;

    textItems.forEach(function (item) {
      var sx = item.x * scale;
      var sy = item.y * scale;
      var sw = Math.max(item.w * scale, 10);
      var sh = Math.max(item.h * scale, 8);

      if (item.type === 'room' && showRooms) {
        // Room name highlight
        overlayCtx.fillStyle = 'rgba(26,58,92,0.2)';
        overlayCtx.fillRect(sx - 3, sy - 2, sw + 6, sh + 4);
        overlayCtx.strokeStyle = '#1a3a5c';
        overlayCtx.lineWidth = 1.5;
        overlayCtx.strokeRect(sx - 3, sy - 2, sw + 6, sh + 4);
      }

      if (item.type === 'area' && showRooms) {
        // Area value highlight
        overlayCtx.fillStyle = 'rgba(26,58,92,0.12)';
        overlayCtx.fillRect(sx - 2, sy - 1, sw + 4, sh + 2);
        overlayCtx.strokeStyle = '#1a3a5c88';
        overlayCtx.lineWidth = 1;
        overlayCtx.strokeRect(sx - 2, sy - 1, sw + 4, sh + 2);
      }

      if (item.type === 'fenster' && showFenster) {
        overlayCtx.fillStyle = 'rgba(34,197,94,0.25)';
        overlayCtx.fillRect(sx - 3, sy - 2, sw + 6, sh + 4);
        overlayCtx.strokeStyle = '#22c55e';
        overlayCtx.lineWidth = 2;
        overlayCtx.strokeRect(sx - 3, sy - 2, sw + 6, sh + 4);
      }

      if (item.type === 'dimension' && showDims) {
        overlayCtx.fillStyle = 'rgba(243,147,1,0.15)';
        overlayCtx.fillRect(sx - 2, sy - 1, sw + 4, sh + 2);
        overlayCtx.strokeStyle = '#f3930188';
        overlayCtx.lineWidth = 1;
        overlayCtx.strokeRect(sx - 2, sy - 1, sw + 4, sh + 2);
      }
    });

    // Draw room cluster outlines
    if (showRooms) {
      roomClusters.forEach(function (cluster) {
        var sx = cluster.x * scale - 8;
        var sy = cluster.y * scale - 8;
        var sw = cluster.w * scale + 16;
        var sh = cluster.h * scale + 16;
        var isActive = cluster === activeCluster;

        overlayCtx.strokeStyle = isActive ? '#1a3a5c' : 'rgba(26,58,92,0.4)';
        overlayCtx.lineWidth = isActive ? 3 : 1;
        overlayCtx.setLineDash(isActive ? [] : [4, 4]);
        overlayCtx.strokeRect(sx, sy, sw, sh);
        overlayCtx.setLineDash([]);

        if (isActive && cluster.name) {
          overlayCtx.font = 'bold 12px sans-serif';
          overlayCtx.fillStyle = 'rgba(255,255,255,0.9)';
          var tw = overlayCtx.measureText(cluster.name + ' ' + cluster.area).width;
          overlayCtx.fillRect(sx, sy - 18, tw + 8, 18);
          overlayCtx.fillStyle = '#1a3a5c';
          overlayCtx.fillText(cluster.name + ' ' + cluster.area, sx + 4, sy - 5);
        }
      });
    }
  }

  function handleClick(cx, cy) {
    activeCluster = null;
    for (var i = 0; i < roomClusters.length; i++) {
      var c = roomClusters[i];
      var sx = c.x * scale - 8, sy = c.y * scale - 8;
      var sw = c.w * scale + 16, sh = c.h * scale + 16;
      if (cx >= sx && cx <= sx + sw && cy >= sy && cy <= sy + sh) {
        activeCluster = c;
        break;
      }
    }
    drawOverlays();
  }

  function renderPage() {
    if (!currentPage) return;
    var vp = currentPage.getViewport({ scale: scale });
    pdfCanvas.width = vp.width;
    pdfCanvas.height = vp.height;
    overlayCanvas.width = vp.width;
    overlayCanvas.height = vp.height;
    overlayCanvas.style.width = vp.width + 'px';
    overlayCanvas.style.height = vp.height + 'px';
    canvasContainer.style.minWidth = (vp.width + 20) + 'px';
    canvasContainer.style.minHeight = (vp.height + 20) + 'px';
    // Position overlay exactly on top of pdf
    overlayCanvas.style.position = 'absolute';
    overlayCanvas.style.left = pdfCanvas.offsetLeft + 'px';
    overlayCanvas.style.top = pdfCanvas.offsetTop + 'px';
    currentPage.render({ canvasContext: pdfCtx, viewport: vp }).promise.then(drawOverlays);
  }

  function zoomFit() {
    if (!currentPage) return;
    var cw = (canvasContainer.parentElement || canvasContainer).clientWidth - 360;
    var ch = Math.max(500, window.innerHeight - 200);
    var vp = currentPage.getViewport({ scale: 1.0 });
    scale = Math.min(cw / vp.width, ch / vp.height, 2.0);
    renderPage();
  }

  function renderSidebar(elemente, massen) {
    var sb = document.getElementById('pv-sidebar');
    var raeume = elemente.filter(function (e) { return e.typ === 'raum'; });
    var fenster = elemente.filter(function (e) { return e.typ === 'fenster'; });

    var html = '<div style="padding:0.75rem;background:#1a3a5c;color:white;font-size:0.85rem">';
    html += '<strong>' + raeume.length + ' R&auml;ume</strong> &middot; ' + fenster.length + ' Fenster &middot; ' + massen.length + ' Massen';
    html += '<br><span style="opacity:0.8">' + textItems.filter(function(t){return t.type==="dimension";}).length + ' Ma&szlig;ketten pixelgenau markiert</span>';
    html += '</div>';

    var whg = {};
    raeume.forEach(function (r) { var w = (r.daten||{}).wohnung||'Sonstige'; if(!whg[w])whg[w]=[]; whg[w].push(r); });

    Object.keys(whg).sort().forEach(function (wName) {
      var rooms = whg[wName];
      html += '<div class="pv-whg"><div class="pv-whg-head" onclick="this.parentElement.classList.toggle(\'collapsed\')">' + esc(wName) + ' (' + rooms.length + ') <span style="float:right">&#9660;</span></div>';
      rooms.forEach(function (r) {
        var d = r.daten || {};
        html += '<div class="pv-room"><div class="pv-room-name">' + esc(r.bezeichnung||d.name||'?') + '</div>';
        html += '<div class="pv-room-data">';
        if(d.flaeche_m2) html += '<span>' + d.flaeche_m2 + 'm&sup2;</span>';
        if(d.umfang_m) html += '<span>U:' + d.umfang_m + 'm</span>';
        if(d.hoehe_m) html += '<span>H:' + d.hoehe_m + 'm</span>';
        html += '</div></div>';
      });
      html += '</div>';
    });

    if (massen.length > 0) {
      html += '<div style="padding:0.5rem 0.75rem;background:#fce4ec;font-weight:600;font-size:0.85rem">Massen (' + massen.length + ')</div>';
      massen.sort(function(a,b){return (a.pos_nr||'').localeCompare(b.pos_nr||'');});
      massen.forEach(function(m){
        html += '<div class="pv-room" style="border-left-color:#f39301"><div class="pv-room-name" style="color:#f39301;font-size:0.8rem"><strong>' + esc(m.pos_nr||'') + '</strong> ' + esc(m.beschreibung||'') + ' = <strong>' + fnum(m.endsumme) + ' ' + esc(m.einheit||'') + '</strong></div></div>';
      });
    }

    sb.innerHTML = html;
  }

  function loadPdfJs() {
    if (window.pdfjsLib) return Promise.resolve();
    return new Promise(function (r) { var s = document.createElement('script'); s.src = PDFJS_CDN; s.onload = function () { pdfjsLib.GlobalWorkerOptions.workerSrc = PDFJS_WORKER; r(); }; document.head.appendChild(s); });
  }
  function esc(s) { var d = document.createElement('div'); d.textContent = s||''; return d.innerHTML; }
  function fnum(v) { return v != null ? parseFloat(v).toLocaleString('de-AT', {maximumFractionDigits:2}) : '-'; }
})();
