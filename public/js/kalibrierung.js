/**
 * KI-Massenermittlung — dedizierter Kalibrierungs-Bereich.
 * Lädt Polier-Pläne + Material-Ermittlung als Referenz-Paare hoch (außerhalb der
 * Kundenprojekte) und zeigt, was die KI daraus für den Betrieb gelernt hat.
 */
(function () {
  'use strict';

  var firma = requireAuth();
  if (!firma) return;

  var KALIB_NAME = '__Kalibrierung__';

  var companyNameEl = document.getElementById('company-name');
  if (firma.name && companyNameEl) companyNameEl.textContent = firma.name;
  document.getElementById('logout-btn').addEventListener('click', function () {
    clearSession(); window.location.href = 'index.html';
  });

  var standEl = document.getElementById('kalib-stand');
  var refEl = document.getElementById('kalib-referenzen');
  var progressEl = document.getElementById('kalib-progress');
  var resultEl = document.getElementById('kalib-result');
  var lernenBtn = document.getElementById('kalib-lernen-btn');
  var resetBtn = document.getElementById('kalib-reset-btn');

  function esc(s) { var d = document.createElement('div'); d.textContent = (s == null ? '' : s); return d.innerHTML; }
  function fmtDate(d) { try { return new Date(d).toLocaleDateString('de-AT'); } catch (e) { return ''; } }
  function setProgress(msg) { progressEl.classList.remove('hidden'); progressEl.innerHTML = '<div class="spinner"></div> ' + esc(msg); }
  function clearProgress() { progressEl.classList.add('hidden'); progressEl.innerHTML = ''; }

  // ── Versteckter Kalibrierungs-Projektkontext (für die Analyse-Pipeline) ──
  function getOrCreateKalibProjekt() {
    return _sb.from('projekte').select('id').eq('firma_id', firma.id).eq('name', KALIB_NAME).limit(1)
      .then(function (res) {
        if (res.data && res.data.length) return res.data[0].id;
        return _sb.from('projekte').insert({ firma_id: firma.id, name: KALIB_NAME, adresse: '', gewerk: 'rohbau' })
          .select('id').single().then(function (r) {
            if (r.error) throw new Error(r.error.message);
            return r.data.id;
          });
      });
  }

  // ── Aktueller Lernstand ──
  var FAKTOR_LABEL = {
    bodenplatte_aufschlag: 'Bodenplatte-Aufschlag',
    decke_aufschlag: 'Decke-Aufschlag',
    frostgraben_aufschlag: 'Frostschürze-Aufschlag',
    aussenumfang_aufschlag: 'Außenwand-Aufschlag'
  };
  function renderStand(data) {
    var aufg = data.aufgeloest || {};
    var wandKeys = ['wand_anteil_50cm', 'wand_anteil_38cm', 'wand_anteil_25cm_innen', 'wand_anteil_20cm', 'wand_anteil_12cm'];
    var hasWand = wandKeys.some(function (k) { return aufg[k] != null; });
    var faktorKeys = Object.keys(FAKTOR_LABEL).filter(function (k) { return aufg[k] != null; });

    var html = '';
    if (!hasWand && !faktorKeys.length) {
      html = '<p class="kalib-empty">Noch nichts gelernt. Lade unten deine erste Referenz hoch — schon eine '
           + 'Polier-Liste mit HLZ-Paletten bringt die Wandstärken-Aufteilung.</p>';
    } else {
      if (hasWand) {
        html += '<div class="kalib-stand-block"><div class="kalib-stand-titel">Wandstärken-Aufteilung (deine Bauweise)</div>'
              + '<div class="kalib-chips">';
        var aussen = [['50 cm', aufg.wand_anteil_50cm], ['38 cm', aufg.wand_anteil_38cm]];
        var innen = [['25 cm', aufg.wand_anteil_25cm_innen], ['20 cm', aufg.wand_anteil_20cm], ['12 cm', aufg.wand_anteil_12cm]];
        html += '<span class="kalib-chip-label">Außen:</span>';
        aussen.forEach(function (x) { if (x[1] != null) html += '<span class="kalib-chip">' + x[0] + ' · ' + Math.round(x[1]) + '%</span>'; });
        html += '<span class="kalib-chip-label">Innen:</span>';
        innen.forEach(function (x) { if (x[1] != null) html += '<span class="kalib-chip">' + x[0] + ' · ' + Math.round(x[1]) + '%</span>'; });
        html += '</div></div>';
      }
      if (faktorKeys.length) {
        html += '<div class="kalib-stand-block"><div class="kalib-stand-titel">Korrektur-Faktoren</div><div class="kalib-chips">';
        faktorKeys.forEach(function (k) {
          html += '<span class="kalib-chip">' + esc(FAKTOR_LABEL[k]) + ' · ×' + Number(aufg[k]).toFixed(2) + '</span>';
        });
        html += '</div></div>';
      }
    }
    html += '<div class="kalib-foot">' + (data.anzahl_soll_listen || 0) + ' Referenz(en) gespeichert · '
          + 'Faktoren werden ab 2 Listen aktiv (Schutz vor Überanpassung), die Wandaufteilung schon ab der 1.</div>';
    standEl.innerHTML = html;
  }
  function loadStand() {
    return fetch('/api/kalibrierung?firma_id=' + encodeURIComponent(firma.id))
      .then(function (r) { return r.json(); }).then(renderStand)
      .catch(function (e) { standEl.innerHTML = '<p class="kalib-empty">Lernstand nicht ladbar: ' + esc(e.message) + '</p>'; });
  }

  // ── Referenzliste ──
  function renderReferenzen(data) {
    var refs = data.referenzen || [];
    if (!refs.length) {
      refEl.innerHTML = '<p class="kalib-empty">Noch keine Referenzen hochgeladen.</p>';
      return;
    }
    refEl.innerHTML = refs.map(function (r) {
      var wv = r.wand_verteilung || {};
      var wvTxt = (wv.wand_anteil_50cm != null)
        ? ('Wand 50/38 · ' + Math.round(wv.wand_anteil_50cm) + '/' + Math.round(wv.wand_anteil_38cm || 0) + '%')
        : 'keine HLZ-Verteilung';
      return '<div class="kalib-ref-row">'
        + '<div class="kalib-ref-main"><div class="kalib-ref-titel">' + esc(r.titel) + '</div>'
        + '<div class="kalib-ref-meta">' + r.positionen + ' Positionen · ' + r.belege_anzahl + ' Belege · '
        + esc(wvTxt) + ' · ' + fmtDate(r.erstellt_am) + '</div></div>'
        + '<button class="btn-delete-project kalib-ref-del" data-id="' + esc(r.id) + '" title="Löschen">&times;</button>'
        + '</div>';
    }).join('');
    Array.prototype.forEach.call(refEl.querySelectorAll('.kalib-ref-del'), function (b) {
      b.addEventListener('click', function () {
        if (!confirm('Diese Referenz löschen? Die KI lernt danach neu.')) return;
        fetch('/api/kalibrierung-referenz-loeschen', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ firma_id: firma.id, soll_liste_id: b.getAttribute('data-id') })
        }).then(function (r) { return r.json(); }).then(function () { loadStand(); loadReferenzen(); });
      });
    });
  }
  function loadReferenzen() {
    return fetch('/api/kalibrierung-referenzen?firma_id=' + encodeURIComponent(firma.id))
      .then(function (r) { return r.json(); }).then(renderReferenzen)
      .catch(function (e) { refEl.innerHTML = '<p class="kalib-empty">Referenzen nicht ladbar: ' + esc(e.message) + '</p>'; });
  }

  // ── Upload eines PDFs in den Storage → storage_path ──
  function uploadPdf(file, prefix) {
    var path = firma.id + '/' + prefix + '/' + Date.now() + '_' + file.name.replace(/[^\w.\-]+/g, '_');
    return _sb.storage.from('plaene').upload(path, file, { contentType: 'application/pdf' })
      .then(function (r) { if (r.error) throw new Error(r.error.message); return path; });
  }

  // ── Haupt-Flow: Plan (optional) analysieren + Soll vergleichen + lernen ──
  async function lernen() {
    var planFile = document.getElementById('kalib-plan').files[0] || null;
    var sollFile = document.getElementById('kalib-soll-pdf').files[0] || null;
    var sollText = (document.getElementById('kalib-soll-text').value || '').trim();
    var titel = (document.getElementById('kalib-titel').value || '').trim();

    if (!sollFile && !sollText) {
      resultEl.classList.remove('hidden');
      resultEl.className = 'kalib-result kalib-result-err';
      resultEl.textContent = 'Bitte eine Polier-Material-Ermittlung als PDF hochladen oder den Text einfügen.';
      return;
    }

    lernenBtn.disabled = true;
    resultEl.classList.add('hidden');
    try {
      var body = { titel: titel };

      if (planFile) {
        setProgress('Plan wird hochgeladen…');
        var projId = await getOrCreateKalibProjekt();
        var planPath = await uploadPdf(planFile, projId);
        var ins = await _sb.from('plaene').insert({
          projekt_id: projId, dateiname: planFile.name, storage_path: planPath
        }).select('id').single();
        if (ins.error) throw new Error(ins.error.message);
        var planId = ins.data.id;

        setProgress('KI analysiert den Plan … das dauert ca. 30–60 Sekunden.');
        var az = await fetch('/api/analyse-zoom', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ plan_id: planId })
        });
        var azData = await az.json().catch(function () { return {}; });
        if (!az.ok) throw new Error('Plan-Analyse fehlgeschlagen: ' + (azData.detail || azData.error || az.status));

        body.projekt_id = projId;
        body.plan_ids = [planId];
      } else {
        body.firma_id = firma.id;
      }

      // Soll-Liste: PDF (server-seitig lesen) ODER eingefügter Text
      if (sollFile) {
        setProgress('Polier-Liste wird hochgeladen & gelesen…');
        body.soll_storage_path = await uploadPdf(sollFile, 'kalib-soll');
      } else {
        body.soll_text = sollText;
      }

      setProgress('Vergleich & Lernen…');
      var up = await fetch('/api/kalibrierung-upload', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body)
      });
      var upData = await up.json().catch(function () { return {}; });
      if (!up.ok) throw new Error(upData.detail || upData.error || ('Status ' + up.status));

      clearProgress();
      resultEl.classList.remove('hidden');
      resultEl.className = 'kalib-result kalib-result-ok';
      var parts = ['<strong>✓ Gelernt.</strong> ' + esc(upData.soll_positionen) + ' Positionen aus deiner Liste gelesen.'];
      if (upData.gelernte_wandverteilung) {
        var w = upData.gelernte_wandverteilung;
        parts.push('Wandstärken-Aufteilung übernommen: außen ' + Math.round(w.wand_anteil_50cm || 0) + '% / '
          + Math.round(w.wand_anteil_38cm || 0) + '% · innen ' + Math.round(w.wand_anteil_25cm_innen || 0) + '/'
          + Math.round(w.wand_anteil_20cm || 0) + '/' + Math.round(w.wand_anteil_12cm || 0) + '%.');
      }
      if (upData.hinweis) parts.push(esc(upData.hinweis));
      resultEl.innerHTML = parts.join('<br>');

      // Form leeren + neu laden
      document.getElementById('kalib-plan').value = '';
      document.getElementById('kalib-soll-pdf').value = '';
      document.getElementById('kalib-soll-text').value = '';
      document.getElementById('kalib-titel').value = '';
      loadStand(); loadReferenzen();
    } catch (e) {
      clearProgress();
      resultEl.classList.remove('hidden');
      resultEl.className = 'kalib-result kalib-result-err';
      resultEl.textContent = 'Fehler: ' + e.message;
    } finally {
      lernenBtn.disabled = false;
    }
  }

  lernenBtn.addEventListener('click', lernen);
  resetBtn.addEventListener('click', function () {
    if (!confirm('Alle Referenzen + gelernten Werte deiner Firma zurücksetzen? (Globale Basis bleibt.)')) return;
    fetch('/api/kalibrierung-reset', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ firma_id: firma.id })
    }).then(function (r) { return r.json(); }).then(function () { loadStand(); loadReferenzen(); });
  });

  loadStand();
  loadReferenzen();
})();
