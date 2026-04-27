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
        '<span class="legend-item"><span class="trust-dot text"></span> Byte-exakt aus PDF-Text</span>' +
        '<span class="legend-item"><span class="trust-dot matched"></span> KI + Text bestätigt</span>' +
        '<span class="legend-item"><span class="trust-dot inferred"></span> Nur KI · prüfen</span>' +
        '<span class="legend-item" style="margin-left:auto"><span class="legend-color" style="background:rgba(34,197,94,0.25);border:2px solid #22c55e"></span> Fenster</span>' +
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

    // Draw room cluster outlines — clusters come from pdf.js text layer
    // so they're inherently "text-tier" (byte-exact positions). Color =
    // teal #0f766e to match sidebar dots.
    if (showRooms) {
      roomClusters.forEach(function (cluster) {
        var sx = cluster.x * scale - 8;
        var sy = cluster.y * scale - 8;
        var sw = cluster.w * scale + 16;
        var sh = cluster.h * scale + 16;
        var isActive = cluster === activeCluster;

        overlayCtx.fillStyle = isActive ? 'rgba(15,118,110,0.16)' : 'rgba(15,118,110,0.06)';
        overlayCtx.fillRect(sx, sy, sw, sh);
        overlayCtx.strokeStyle = isActive ? '#0f766e' : 'rgba(15,118,110,0.55)';
        overlayCtx.lineWidth = isActive ? 2.5 : 1.5;
        overlayCtx.setLineDash([]);
        overlayCtx.strokeRect(sx, sy, sw, sh);

        if (isActive && cluster.name) {
          overlayCtx.font = 'bold 12px sans-serif';
          var labelText = cluster.name + (cluster.area ? ' · ' + cluster.area : '');
          var tw = overlayCtx.measureText(labelText).width;
          overlayCtx.fillStyle = '#fff';
          overlayCtx.fillRect(sx, sy - 20, tw + 12, 20);
          overlayCtx.strokeStyle = '#0f766e';
          overlayCtx.lineWidth = 1;
          overlayCtx.strokeRect(sx, sy - 20, tw + 12, 20);
          overlayCtx.fillStyle = '#0f766e';
          overlayCtx.fillText(labelText, sx + 6, sy - 6);
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

  function getTier(d) {
    // Room-level tier: text | matched | inferred | manual
    if (!d) return 'inferred';
    if (d._source === 'manual' || d.manuell_korrigiert) return 'manual';
    if (d._source === 'text') return 'text';
    var v = d._verified || {};
    if (v.F && v.U && v.H) return 'matched';
    if (d._source === 'vision' && d.name) return 'matched';
    return 'inferred';
  }
  function getFieldTier(d, fld) {
    // Per-value tier - finer grain for F/U/H individually
    if (!d) return 'inferred';
    if (d._source === 'manual') return 'manual';
    if (d._source === 'text') return 'text';
    // vision-sourced: each field gets matched if text-verified, else inferred
    var v = d._verified || {};
    var verified = v[fld];
    if (verified) return 'matched';
    return 'inferred';
  }
  function tierLabel(t) {
    return t === 'text' ? 'Aus PDF-Text · 100% byte-genau'
      : t === 'matched' ? 'KI + Text bestätigt · ~95%'
      : t === 'manual' ? 'Manuell korrigiert'
      : 'Nur KI-Erkennung · bitte prüfen';
  }
  // ─── URL-hash filter persistence ───
  function readFilterState() {
    var h = window.location.hash || '';
    var m = h.match(/pv:([^\&]+)/);
    if (!m) return { tier: 'all', wohnung: 'all', bodenbelag: 'all', sort: 'name' };
    var parts = m[1].split('|');
    return {
      tier: parts[0] || 'all',
      wohnung: decodeURIComponent(parts[1] || 'all'),
      bodenbelag: decodeURIComponent(parts[2] || 'all'),
      sort: parts[3] || 'name',
    };
  }
  function writeFilterState(s) {
    var enc = [s.tier, encodeURIComponent(s.wohnung), encodeURIComponent(s.bodenbelag), s.sort].join('|');
    var h = (window.location.hash || '').replace(/pv:[^&]*/, '');
    h = h.replace(/^#&?/, '');
    window.location.hash = (h ? h + '&' : '') + 'pv:' + enc;
  }
  // ─── Excel export ───
  function exportToExcel(raeume) {
    var rows = [['Wohnung', 'Raum', 'Quelle', 'Fläche m²', 'Umfang m', 'Höhe m', 'Bodenbelag']];
    raeume.forEach(function(r){
      var d = r.daten || {};
      var t = getTier(d);
      var src = t === 'text' ? 'PDF-Text (byte-exakt)'
        : t === 'matched' ? 'KI + Text verifiziert'
        : t === 'manual' ? 'Manuell korrigiert'
        : 'Nur KI - geprüft?';
      rows.push([
        d.wohnung || '',
        r.bezeichnung || d.name || '',
        src,
        d.flaeche_m2 != null ? d.flaeche_m2 : '',
        d.umfang_m != null ? d.umfang_m : '',
        d.hoehe_m != null ? d.hoehe_m : '',
        d.bodenbelag || '',
      ]);
    });
    // Build CSV (Excel opens .csv natively with UTF-8 BOM)
    var csv = '﻿' + rows.map(function(r){
      return r.map(function(c){
        var s = String(c == null ? '' : c);
        if (/[;"\n,]/.test(s)) s = '"' + s.replace(/"/g, '""') + '"';
        return s;
      }).join(';');
    }).join('\r\n');
    var blob = new Blob([csv], { type: 'text/csv;charset=utf-8' });
    var a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = 'massenermittlung_' + new Date().toISOString().slice(0,10) + '.csv';
    document.body.appendChild(a); a.click(); document.body.removeChild(a);
    URL.revokeObjectURL(a.href);
  }

  // Cached state for re-rendering on filter/sort change
  var _stateRaeume = [], _stateMassen = [], _stateFilter = null;

  function renderSidebar(elemente, massen) {
    _stateRaeume = elemente.filter(function (e) { return e.typ === 'raum'; });
    _stateMassen = massen || [];
    _stateFilter = readFilterState();
    drawSidebar();
  }

  function drawSidebar() {
    var sb = document.getElementById('pv-sidebar');
    if (!sb) return;
    var raeume = _stateRaeume;
    var massen = _stateMassen;
    var f = _stateFilter;

    // Tier counts
    var tiers = { text: 0, matched: 0, inferred: 0, manual: 0 };
    raeume.forEach(function(r){ tiers[getTier(r.daten || {})]++; });
    var totalRooms = raeume.length;

    // ── Empty state ──
    if (totalRooms === 0) {
      sb.innerHTML = '<div class="trust-bar flag-warn"><span class="trust-headline">Analyse ohne Treffer</span></div>' +
        '<div class="pv-empty-state">' +
          '<div class="pv-empty-state-icon">🚪</div>' +
          '<h4>Keine Räume erkannt</h4>' +
          '<p>Der Plan war vermutlich kein Wohnungsgrundriss oder hat keine Beschriftungen für Räume.</p>' +
        '</div>';
      return;
    }

    // ── Trust bar ──
    var trustClass = 'trust-bar';
    var headlineHtml = '';
    if (tiers.inferred === 0 && tiers.text > 0) {
      trustClass += ' flag-clean';
      headlineHtml = '<span class="trust-headline">' + totalRooms + ' Räume · alle byte-exakt aus PDF-Text</span>';
    } else if (tiers.text === 0 && tiers.matched === 0) {
      trustClass += ' flag-warn';
      headlineHtml = '<span class="trust-headline">⚠ ' + totalRooms + ' Räume · nur KI-Erkennung · alle bitte prüfen</span>';
    } else {
      headlineHtml = '<span class="trust-headline">' + totalRooms + ' Räume erkannt</span>';
    }

    var html = '<div class="' + trustClass + '">';
    html += headlineHtml;
    if (tiers.text) html += '<span class="trust-counter" data-filter="text" title="Byte-genau aus PDF-Text-Layer"><span class="trust-dot text"></span>' + tiers.text + ' byte-exakt</span>';
    if (tiers.matched) html += '<span class="trust-counter" data-filter="matched" title="KI-erkannt und gegen PDF-Text validiert"><span class="trust-dot matched"></span>' + tiers.matched + ' verifiziert</span>';
    if (tiers.inferred) html += '<span class="trust-counter flag-pulse" data-filter="inferred" title="Nur KI-Erkennung — manuell prüfen"><span class="trust-dot inferred"></span>' + tiers.inferred + ' zu prüfen</span>';
    if (tiers.manual) html += '<span class="trust-counter" data-filter="manual" title="Manuell vom Nutzer angepasst"><span class="trust-dot manual"></span>' + tiers.manual + ' korrigiert</span>';
    // Action buttons
    html += '<span class="trust-bar-actions">';
    if (tiers.inferred > 0) {
      html += '<button class="btn btn-outline btn-sm" id="pv-bulk-approve" title="Alle ' + tiers.inferred + ' KI-erkannten als geprüft markieren">Alle freigeben</button>';
    }
    html += '<button class="btn btn-accent btn-sm" id="pv-export-csv" title="Als Excel-CSV exportieren">⬇ Excel</button>';
    html += '</span>';
    html += '</div>';

    // ── Filter pills ──
    html += '<div class="pv-filter-strip">';
    html += '<span class="pv-filter-pill' + (f.tier==='all'?' active':'') + '" data-pill="all">Alle <span class="filter-count">' + totalRooms + '</span></span>';
    html += '<span class="pv-filter-pill' + (f.tier==='text'?' active':'') + '" data-pill="text"><span class="trust-dot text"></span><span class="filter-count">' + tiers.text + '</span></span>';
    html += '<span class="pv-filter-pill' + (f.tier==='matched'?' active':'') + '" data-pill="matched"><span class="trust-dot matched"></span><span class="filter-count">' + tiers.matched + '</span></span>';
    html += '<span class="pv-filter-pill' + (f.tier==='inferred'?' active':'') + '" data-pill="inferred"><span class="trust-dot inferred"></span><span class="filter-count">' + tiers.inferred + '</span></span>';
    html += '</div>';

    // ── Wohnung + Bodenbelag dropdowns + Sort ──
    var wohnungSet = {}; var bodenSet = {};
    raeume.forEach(function(r){
      var d = r.daten || {};
      if (d.wohnung) wohnungSet[d.wohnung] = true;
      if (d.bodenbelag) bodenSet[d.bodenbelag] = true;
    });
    var wohnungOpts = Object.keys(wohnungSet).sort();
    var bodenOpts = Object.keys(bodenSet).sort();

    html += '<div class="pv-filter-controls">';
    html += '<select id="pv-filter-wohnung"><option value="all">Alle Wohnungen</option>';
    wohnungOpts.forEach(function(w){ html += '<option value="' + esc(w) + '"' + (f.wohnung===w?' selected':'') + '>' + esc(w) + '</option>'; });
    html += '</select>';
    html += '<select id="pv-filter-bodenbelag"><option value="all">Alle Beläge</option>';
    bodenOpts.forEach(function(b){ html += '<option value="' + esc(b) + '"' + (f.bodenbelag===b?' selected':'') + '>' + esc(b) + '</option>'; });
    html += '</select>';
    html += '<select id="pv-sort">';
    html += '<option value="name"' + (f.sort==='name'?' selected':'') + '>↕ Name</option>';
    html += '<option value="flaeche-desc"' + (f.sort==='flaeche-desc'?' selected':'') + '>↓ Fläche</option>';
    html += '<option value="flaeche-asc"' + (f.sort==='flaeche-asc'?' selected':'') + '>↑ Fläche</option>';
    html += '<option value="tier"' + (f.sort==='tier'?' selected':'') + '>↑ Konfidenz</option>';
    html += '</select>';
    html += '</div>';

    // ── Apply filters + sort to room list ──
    var visible = raeume.filter(function(r){
      var d = r.daten || {};
      var t = getTier(d);
      if (f.tier !== 'all' && t !== f.tier) return false;
      if (f.wohnung !== 'all' && (d.wohnung || 'Sonstige') !== f.wohnung) return false;
      if (f.bodenbelag !== 'all' && (d.bodenbelag || '') !== f.bodenbelag) return false;
      return true;
    });
    var tierOrder = { inferred: 0, matched: 1, manual: 2, text: 3 };
    if (f.sort === 'flaeche-desc') visible.sort(function(a,b){ return ((b.daten||{}).flaeche_m2 || 0) - ((a.daten||{}).flaeche_m2 || 0); });
    else if (f.sort === 'flaeche-asc') visible.sort(function(a,b){ return ((a.daten||{}).flaeche_m2 || 0) - ((b.daten||{}).flaeche_m2 || 0); });
    else if (f.sort === 'tier') visible.sort(function(a,b){ return (tierOrder[getTier(a.daten||{})] || 0) - (tierOrder[getTier(b.daten||{})] || 0); });
    else visible.sort(function(a,b){ return (a.bezeichnung||'').localeCompare(b.bezeichnung||''); });

    // Group by Wohnung if not already filtered
    var whg = {};
    visible.forEach(function (r) {
      var w = (r.daten || {}).wohnung || 'Sonstige';
      if (!whg[w]) whg[w] = [];
      whg[w].push(r);
    });

    if (visible.length === 0) {
      html += '<div class="pv-empty-state" style="padding:2rem 1rem"><p>Keine Räume mit den aktuellen Filtern.</p></div>';
    }

    Object.keys(whg).sort().forEach(function (wName) {
      var rooms = whg[wName];
      html += '<div class="pv-whg">';
      html += '<div class="pv-whg-head" onclick="this.parentElement.classList.toggle(\'collapsed\')">' + esc(wName) + ' <span style="color:#94a3b8;font-weight:400">· ' + rooms.length + '</span><span style="float:right">▾</span></div>';
      rooms.forEach(function (r) {
        var d = r.daten || {};
        var tier = getTier(d);
        var name = r.bezeichnung || d.name || '?';
        html += '<div class="pv-room-v2" data-tier="' + tier + '" data-room="' + esc(r.id || '') + '" title="' + esc(tierLabel(tier)) + '">';
        html += '<div class="pv-room-v2-head">';
        html += '<span class="trust-dot ' + tier + '"></span>';
        html += '<span class="pv-room-v2-name">' + esc(name) + '</span>';
        html += '</div>';

        // Per-value KPI chips with individual source dots
        html += '<div class="pv-room-v2-kpis">';
        ['F','U','H'].forEach(function(fld){
          var attr = fld === 'F' ? 'flaeche_m2' : (fld === 'U' ? 'umfang_m' : 'hoehe_m');
          var unit = fld === 'F' ? ' m²' : ' m';
          var val = d[attr];
          if (val) {
            var fldTier = getFieldTier(d, fld);
            html += '<span class="kpi-chip" title="' + tierLabel(fldTier) + '"><span class="kpi-src ' + fldTier + '"></span><span class="kpi-label">' + fld + '</span><span class="kpi-val">' + fnum(val) + unit + '</span></span>';
          } else {
            html += '<span class="kpi-chip empty">' + fld + ' —</span>';
          }
        });
        html += '</div>';

        if (d.bodenbelag) {
          html += '<div class="pv-room-v2-bod">▦ ' + esc(d.bodenbelag) + '</div>';
        }

        html += '</div>';
      });
      html += '</div>';
    });

    if (massen.length > 0) {
      html += '<div style="padding:0.6rem 0.75rem;background:#fff7ed;font-weight:600;font-size:0.82rem;color:#9a3412;border-top:1px solid #fdba74">Massen (' + massen.length + ')</div>';
      massen.sort(function(a,b){return (a.pos_nr||'').localeCompare(b.pos_nr||'');});
      massen.forEach(function(m){
        html += '<div class="pv-room-v2" style="border-color:#fdba74"><div class="pv-room-v2-head"><span class="pv-room-v2-name" style="color:#9a3412;font-size:0.82rem"><strong>' + esc(m.pos_nr||'') + '</strong> ' + esc(m.beschreibung||'') + '</span></div><div style="font-variant-numeric:tabular-nums;font-size:0.85rem;font-weight:600;color:#1a3a5c">= ' + fnum(m.endsumme) + ' ' + esc(m.einheit||'') + '</div></div>';
      });
    }

    sb.innerHTML = html;

    // ── Wire up: filter pills ──
    sb.querySelectorAll('.pv-filter-pill').forEach(function(p){
      p.addEventListener('click', function(){
        _stateFilter.tier = p.getAttribute('data-pill');
        writeFilterState(_stateFilter);
        drawSidebar();
      });
    });
    // Trust counter click
    sb.querySelectorAll('.trust-counter').forEach(function(c){
      c.addEventListener('click', function(){
        _stateFilter.tier = c.getAttribute('data-filter');
        writeFilterState(_stateFilter);
        drawSidebar();
      });
    });
    // Wohnung / Bodenbelag / Sort dropdowns
    var selW = document.getElementById('pv-filter-wohnung');
    if (selW) selW.onchange = function(){ _stateFilter.wohnung = selW.value; writeFilterState(_stateFilter); drawSidebar(); };
    var selB = document.getElementById('pv-filter-bodenbelag');
    if (selB) selB.onchange = function(){ _stateFilter.bodenbelag = selB.value; writeFilterState(_stateFilter); drawSidebar(); };
    var selS = document.getElementById('pv-sort');
    if (selS) selS.onchange = function(){ _stateFilter.sort = selS.value; writeFilterState(_stateFilter); drawSidebar(); };
    // Bulk approve
    var bulk = document.getElementById('pv-bulk-approve');
    if (bulk) bulk.onclick = function(){
      var n = tiers.inferred;
      if (!confirm(n + ' KI-erkannte Räume als "geprüft" markieren? Sie können einzelne Räume später noch korrigieren.')) return;
      var promises = _stateRaeume.filter(function(r){ return getTier(r.daten || {}) === 'inferred'; }).map(function(r){
        var d = r.daten || {};
        d._source = 'manual';
        d.manuell_korrigiert = true;
        return _sb.from('elemente').update({ daten: d, konfidenz: 95 }).eq('id', r.id);
      });
      Promise.all(promises).then(function(){
        _stateRaeume.forEach(function(r){
          if (r.daten && r.daten._source === 'manual') { r.konfidenz = 95; }
        });
        drawSidebar();
      });
    };
    // Excel export
    var exp = document.getElementById('pv-export-csv');
    if (exp) exp.onclick = function(){ exportToExcel(_stateRaeume); };
    // Click room card → zoom + drawer
    sb.querySelectorAll('.pv-room-v2[data-room]').forEach(function(card){
      card.addEventListener('click', function(e){
        if (e.target.closest('.pv-whg-head')) return;
        var rid = card.getAttribute('data-room');
        var room = _stateRaeume.find(function(r){ return String(r.id) === String(rid); });
        if (!room) return;
        sb.querySelectorAll('.pv-room-v2').forEach(function(c){ c.classList.remove('active'); });
        card.classList.add('active');
        zoomToRoom(room);
        openDrawer(room);
      });
    });
  }

  // ─── Click-to-Zoom: pan & zoom canvas to a room's cluster ───
  function zoomToRoom(room) {
    var d = room.daten || {};
    var name = (room.bezeichnung || d.name || '').toLowerCase().trim();
    if (!name || !roomClusters || !roomClusters.length) return;
    // Find best matching cluster by name
    var match = null;
    var bestScore = 0;
    roomClusters.forEach(function(c){
      var cn = (c.name || '').toLowerCase();
      if (cn.indexOf(name) >= 0 || name.indexOf(cn) >= 0) {
        var score = Math.min(cn.length, name.length);
        if (score > bestScore) { bestScore = score; match = c; }
      }
    });
    if (!match) return;
    activeCluster = match;
    // Fit cluster in 60% of viewport
    var cw = canvasContainer.clientWidth;
    var ch = canvasContainer.clientHeight;
    var targetScale = Math.min(cw / (match.w * 1.6), ch / (match.h * 1.6), 4);
    if (targetScale < 0.5) targetScale = 0.5;
    scale = targetScale;
    renderPage();
    // Center scroll on cluster
    setTimeout(function(){
      var cx = (match.x + match.w/2) * scale;
      var cy = (match.y + match.h/2) * scale;
      canvasContainer.scrollTo({
        left: cx - cw/2,
        top: cy - ch/2,
        behavior: 'smooth'
      });
    }, 50);
  }

  // ─── Detail drawer ───
  function openDrawer(room) {
    closeDrawer();
    var d = room.daten || {};
    var tier = getTier(d);
    var name = room.bezeichnung || d.name || '?';

    var backdrop = document.createElement('div');
    backdrop.className = 'pv-drawer-backdrop';
    backdrop.onclick = closeDrawer;

    var dr = document.createElement('div');
    dr.className = 'pv-drawer';
    dr.id = 'pv-drawer';
    dr.innerHTML =
      '<div class="pv-drawer-header">' +
        '<span class="trust-dot ' + tier + '"></span>' +
        '<span class="pv-drawer-title">' + esc(name) + '</span>' +
        '<button class="pv-drawer-close" type="button">×</button>' +
      '</div>' +
      '<div class="pv-drawer-body">' +
        '<div class="pv-drawer-source-row"><span class="trust-dot ' + tier + '"></span> ' + esc(tierLabel(tier)) + (d.wohnung ? ' · ' + esc(d.wohnung) : '') + '</div>' +
        '<div class="pv-drawer-field">' +
          '<div class="pv-drawer-field-label"><span class="kpi-src ' + getFieldTier(d,'F') + '"></span> Fläche (m²)</div>' +
          '<input type="text" data-field="flaeche_m2" value="' + (d.flaeche_m2 != null ? d.flaeche_m2 : '') + '">' +
        '</div>' +
        '<div class="pv-drawer-field">' +
          '<div class="pv-drawer-field-label"><span class="kpi-src ' + getFieldTier(d,'U') + '"></span> Umfang (m)</div>' +
          '<input type="text" data-field="umfang_m" value="' + (d.umfang_m != null ? d.umfang_m : '') + '">' +
        '</div>' +
        '<div class="pv-drawer-field">' +
          '<div class="pv-drawer-field-label"><span class="kpi-src ' + getFieldTier(d,'H') + '"></span> Höhe (m)</div>' +
          '<input type="text" data-field="hoehe_m" value="' + (d.hoehe_m != null ? d.hoehe_m : '') + '">' +
        '</div>' +
        '<div class="pv-drawer-field">' +
          '<div class="pv-drawer-field-label">Bodenbelag</div>' +
          '<input type="text" data-field="bodenbelag" value="' + esc(d.bodenbelag || '') + '" placeholder="z.B. Parkett, Fliesen, Estrich">' +
        '</div>' +
      '</div>' +
      '<div class="pv-drawer-actions">' +
        '<button class="btn btn-primary btn-sm" id="pv-drawer-save">Speichern</button>' +
        '<button class="btn btn-outline btn-sm" id="pv-drawer-cancel">Abbrechen</button>' +
        '<button class="btn btn-danger btn-sm" id="pv-drawer-delete">Löschen</button>' +
      '</div>';

    document.body.appendChild(backdrop);
    document.body.appendChild(dr);
    requestAnimationFrame(function(){ dr.classList.add('open'); });

    dr.querySelector('.pv-drawer-close').onclick = closeDrawer;
    dr.querySelector('#pv-drawer-cancel').onclick = closeDrawer;

    // Mark inputs as changed on edit
    dr.querySelectorAll('input').forEach(function(inp){
      var orig = inp.value;
      inp.addEventListener('input', function(){
        if (inp.value !== orig) inp.classList.add('changed');
        else inp.classList.remove('changed');
      });
    });

    dr.querySelector('#pv-drawer-save').onclick = function(){
      var newD = Object.assign({}, d);
      var changed = false;
      dr.querySelectorAll('input[data-field]').forEach(function(inp){
        var k = inp.getAttribute('data-field');
        var v = inp.value.trim();
        var num = (k === 'bodenbelag') ? v : parseFloat(v.replace(',', '.'));
        var prev = d[k];
        if (k !== 'bodenbelag' && isNaN(num)) num = null;
        if (k === 'bodenbelag' ? prev !== v : prev !== num) {
          newD[k] = num != null ? num : (k === 'bodenbelag' ? v : null);
          changed = true;
        }
      });
      if (changed) {
        newD._source = 'manual';
        newD.manuell_korrigiert = true;
        _sb.from('elemente')
          .update({ daten: newD, konfidenz: 100 })
          .eq('id', room.id)
          .then(function(res){
            if (res.error) { alert('Fehler beim Speichern: ' + res.error.message); return; }
            room.daten = newD;
            room.konfidenz = 100;
            closeDrawer();
            drawSidebar();
          });
      } else closeDrawer();
    };

    dr.querySelector('#pv-drawer-delete').onclick = function(){
      if (!confirm('Raum "' + name + '" wirklich aus der Auswertung entfernen?')) return;
      _sb.from('elemente').delete().eq('id', room.id).then(function(res){
        if (res.error) { alert('Fehler: ' + res.error.message); return; }
        var idx = _stateRaeume.findIndex(function(r){ return r.id === room.id; });
        if (idx >= 0) _stateRaeume.splice(idx, 1);
        closeDrawer();
        drawSidebar();
      });
    };
  }
  function closeDrawer() {
    var d = document.getElementById('pv-drawer');
    if (d) {
      d.classList.remove('open');
      setTimeout(function(){ d.remove(); }, 280);
    }
    var b = document.querySelector('.pv-drawer-backdrop');
    if (b) b.remove();
  }

  function loadPdfJs() {
    if (window.pdfjsLib) return Promise.resolve();
    return new Promise(function (r) { var s = document.createElement('script'); s.src = PDFJS_CDN; s.onload = function () { pdfjsLib.GlobalWorkerOptions.workerSrc = PDFJS_WORKER; r(); }; document.head.appendChild(s); });
  }
  function esc(s) { var d = document.createElement('div'); d.textContent = s||''; return d.innerHTML; }
  function fnum(v) { return v != null ? parseFloat(v).toLocaleString('de-AT', {maximumFractionDigits:2}) : '-'; }
})();
