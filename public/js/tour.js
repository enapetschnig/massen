/* INTERAKTIVE ANLEITUNG (Coach-Marks) — die App erklärt sich selbst.
 *
 * Warum so und nicht als Text-Kasten: der "So misst du"-Ersthinweis wurde
 * live nicht als Anleitung erkannt (Befund 2026-08-20). Eine Tour zeigt
 * stattdessen AUF das echte Element, in der echten Reihenfolge, und lässt
 * den Nutzer die Kern-Geste sofort selbst ausführen ("Probier es jetzt":
 * der Schritt wartet auf den Klick aufs Ziel statt auf "Weiter").
 *
 * Robustheit: fehlt ein Ziel-Element (z. B. noch kein Plan geladen), wird
 * der Schritt übersprungen. Jede Tour startet automatisch genau EINMAL je
 * Browser (localStorage) und ist jederzeit über den ❓-Knopf in der
 * Workflow-Leiste neu startbar.
 */
(function () {
  'use strict';
  var TOURS = {};        // name -> [{el, titel, text, warten}]
  var akt = null;        // laufende Tour: {name, steps, i, ov, ring, pop, cleanup}

  function lsGet(k) { try { return localStorage.getItem(k); } catch (e) { return '1'; } }
  function lsSet(k) { try { localStorage.setItem(k, '1'); } catch (e) { /* egal */ } }

  function findEl(step) {
    var sel = step.el;
    if (typeof sel === 'function') { try { return sel(); } catch (e) { return null; } }
    var el = document.querySelector(sel);
    // unsichtbare Ziele überspringen (display:none / aus dem Layout genommen)
    if (el && (!el.offsetParent && getComputedStyle(el).position !== 'fixed')) return null;
    return el;
  }

  function baueUi() {
    var ring = document.createElement('div');
    ring.className = 'tour-ring';
    var pop = document.createElement('div');
    pop.className = 'tour-pop';
    document.body.appendChild(ring);
    document.body.appendChild(pop);
    return { ring: ring, pop: pop };
  }

  function positioniere(step, el) {
    var r = el.getBoundingClientRect();
    var pad = 6;
    var ring = akt.ring, pop = akt.pop;
    ring.style.top = (r.top - pad) + 'px';
    ring.style.left = (r.left - pad) + 'px';
    ring.style.width = (r.width + pad * 2) + 'px';
    ring.style.height = (r.height + pad * 2) + 'px';
    // Popover: bevorzugt unter dem Ziel, sonst darüber, immer im Viewport.
    pop.style.visibility = 'hidden'; pop.style.display = 'block';
    var pw = Math.min(340, window.innerWidth - 24);
    pop.style.width = pw + 'px';
    var ph = pop.offsetHeight || 160;
    var top = r.bottom + pad + 10;
    if (top + ph > window.innerHeight - 12) top = Math.max(12, r.top - pad - ph - 10);
    var left = Math.max(12, Math.min(r.left, window.innerWidth - pw - 12));
    pop.style.top = top + 'px';
    pop.style.left = left + 'px';
    pop.style.visibility = 'visible';
  }

  function zeige(i) {
    if (!akt) return;
    var steps = akt.steps;
    // fehlende Ziele überspringen (vorwärts)
    while (i < steps.length && !findEl(steps[i])) i++;
    if (i >= steps.length) { fertig(true); return; }
    akt.i = i;
    var step = steps[i];
    var el = findEl(step);
    el.scrollIntoView({ behavior: 'smooth', block: 'center' });
    var sichtbar = steps.filter(function (s) { return findEl(s); }).length;
    var pos = steps.slice(0, i + 1).filter(function (s) { return findEl(s); }).length;
    akt.pop.innerHTML =
      '<div class="tour-kopf"><span class="tour-nr">' + pos + ' / ' + sichtbar + '</span>' +
      '<button type="button" class="tour-x" data-tour="zu" title="Anleitung schließen">✕</button></div>' +
      '<div class="tour-titel">' + step.titel + '</div>' +
      '<div class="tour-text">' + step.text + '</div>' +
      '<div class="tour-fuss">' +
      (i > 0 ? '<button type="button" class="tour-btn" data-tour="zurueck">‹ Zurück</button>' : '') +
      (step.warten === 'klick'
        ? '<span class="tour-probier">👆 Probier es jetzt — klicke das markierte Element</span>' +
          '<button type="button" class="tour-btn" data-tour="weiter">Überspringen ›</button>'
        : '<button type="button" class="tour-btn tour-btn-haupt" data-tour="weiter">' +
          (i >= steps.length - 1 ? 'Fertig ✓' : 'Weiter ›') + '</button>') +
      '</div>';
    positioniere(step, el);
    akt.pop.querySelectorAll('[data-tour]').forEach(function (b) {
      b.addEventListener('click', function (ev) {
        ev.stopPropagation();
        var w = b.getAttribute('data-tour');
        if (w === 'zu') fertig(false);
        else if (w === 'zurueck') zeige(rueckwaerts(i));
        else zeige(i + 1);
      });
    });
    // "Probier es"-Schritt: der echte Klick aufs Ziel führt weiter.
    if (akt.klickHandler) { document.removeEventListener('click', akt.klickHandler, true); akt.klickHandler = null; }
    if (step.warten === 'klick') {
      akt.klickHandler = function (ev) {
        var ziel = findEl(step);
        if (ziel && (ev.target === ziel || ziel.contains(ev.target))) {
          document.removeEventListener('click', akt.klickHandler, true);
          akt.klickHandler = null;
          // erst NACH dem Klick weiterschalten, damit die App reagieren kann
          setTimeout(function () { zeige(i + 1); }, 250);
        }
      };
      document.addEventListener('click', akt.klickHandler, true);
    }
    // Der Ring darf Klicks aufs Ziel nicht schlucken.
    akt.ring.style.pointerEvents = 'none';
  }

  function rueckwaerts(i) {
    var j = i - 1;
    while (j > 0 && !findEl(akt.steps[j])) j--;
    return Math.max(0, j);
  }

  function fertig(geschafft) {
    if (!akt) return;
    lsSet('tour_' + akt.name);
    if (akt.klickHandler) document.removeEventListener('click', akt.klickHandler, true);
    window.removeEventListener('resize', akt.repos);
    window.removeEventListener('scroll', akt.repos, true);
    akt.ring.remove(); akt.pop.remove();
    akt = null;
  }

  function start(name) {
    if (!TOURS[name]) return;
    if (akt) fertig(false);      // laufende Tour sauber beenden
    var ui = baueUi();
    akt = { name: name, steps: TOURS[name], i: 0, ring: ui.ring, pop: ui.pop };
    akt.repos = function () {
      if (!akt) return;
      var s = akt.steps[akt.i], el = s && findEl(s);
      if (el) positioniere(s, el);
    };
    window.addEventListener('resize', akt.repos);
    window.addEventListener('scroll', akt.repos, true);
    zeige(0);
  }

  function auto(name) {
    if (akt || lsGet('tour_' + name)) return;
    // kurz warten, bis die Ansicht steht (Repaints nach wfShow)
    setTimeout(function () { if (!akt && !lsGet('tour_' + name)) start(name); }, 600);
  }

  window.Tour = { define: function (n, s) { TOURS[n] = s; }, start: start, auto: auto,
                  laeuft: function () { return !!akt; },
                  // stopp(): bei einem Ansichtswechsel (Workflow-Schritt) die
                  // laufende Tour sauber beenden — ihre Ziele sind sonst weg.
                  stopp: function () { if (akt) fertig(false); } };

  /* ── TOUR-INHALTE ──────────────────────────────────────────────────── */

  Tour.define('plan', [
    { el: '#workflow-steps',
      titel: 'In 3 Schritten zum fertigen Aufmaß',
      text: '<b>1 · Plan</b> hochladen → <b>2 · Aufmaß</b> am Plan messen → ' +
            '<b>3 · Abrechnung</b> exportieren. Die KI arbeitet dazwischen ' +
            'automatisch. Über <b>❓ Anleitung</b> startest du diese Hilfe jederzeit neu.' },
    { el: '#upload-zone',
      titel: 'Schritt 1: Plan hochladen',
      text: 'PDF-Pläne hierher ziehen — gern <b>alle Blätter eines Bauvorhabens ' +
            'gleichzeitig</b> (Grundriss, Schnitt, Ansicht). Die Analyse startet ' +
            'von selbst; danach geht es automatisch weiter zum Aufmaß.' },
    { el: '#plan-list',
      titel: 'Deine Pläne',
      text: 'Hier steht je Plan der Analyse-Status. Sobald alles fertig ist, ' +
            'liegen die erkannten Räume als Vorschläge am Plan — Schritt 2.' }
  ]);

  Tour.define('aufmass', [
    { el: '.nz-wrap',
      titel: 'Der Plan ist deine Arbeitsfläche',
      text: '<b>Mausrad</b> = zoomen (auf den Cursor) · <b>Ziehen</b> = verschieben · ' +
            'Raum <b>anklicken</b> = Werte sehen. Am Touch-Gerät: Finger ziehen, ' +
            'zwei Finger zoomen.' },
    { el: '.nz-rail',
      titel: 'Werkzeuge — wie in einer Zeichensoftware',
      text: 'Links wählst du das Werkzeug: <b>Fläche</b>, <b>Rechteck</b>, ' +
            '<b>Länge</b>, Stück, Abzug … Auch per Taste: <b>F</b> Fläche · ' +
            '<b>R</b> Rechteck · <b>L</b> Länge.' },
    { el: '[data-mw="flaeche"]', warten: 'klick',
      titel: 'Miss deine erste Fläche',
      text: 'Klicke das Werkzeug <b>Fläche</b> an. Danach: Ecken am Plan ' +
            'antippen — <b>Klick auf den Startpunkt schließt</b> die Fläche. ' +
            '<b>Shift</b> = rechtwinklig · <b>Backspace</b> = Punkt zurück · ' +
            '<b>Esc</b> = abbrechen.' },
    { el: '[data-mw="snap"]',
      titel: '🧲 Fangen: du triffst, ohne zu zielen',
      text: 'Die App kennt die erkannten Wände. Mit <b>Fangen</b> rastet jeder ' +
            'Klick auf die nächste Wandlinie oder Ecke — auch beim Ziehen von ' +
            'Raum-Ecken und beim Verschieben ganzer Flächen. Taste <b>G</b> schaltet um.' },
    { el: function () { return document.querySelector('polygon[data-rpoly]'); },
      titel: 'Erkannte Räume: prüfen & anpassen',
      text: 'Farbige Flächen sind erkannte Räume. <b>Anklicken</b> zeigt Fläche ' +
            'und Umfang. <b>Ecken ziehen</b> passt den Umriss an — mit dem ' +
            '<b>✥-Griff in der Mitte</b> (oder Ziehen in der Fläche) verschiebst du den ' +
            '<b>ganzen Raum</b>. Fläche &amp; Umfang rechnen live mit.' },
    { el: '.nz-side',
      titel: 'Rechts: Messungen & Eigenschaften',
      text: 'Jede Messung steht hier mit <b>Wert und Formel</b> — der Grund, warum ' +
            'ein Polier der Zahl glaubt. KI-Vorschläge (gestrichelt am Plan) ' +
            'bestätigst du mit einem Klick. <b>Strg+Z</b> nimmt die letzte Messung zurück.' },
    { el: '[data-z="calib"]',
      titel: '📐 Maßstab — die Grundlage jeder Zahl',
      text: 'Bei Vektorplänen liest die App den Maßstab byte-exakt selbst. Bei ' +
            '<b>Scans</b>: hier klicken, dann <b>2 Punkte einer bekannten Länge</b> ' +
            'antippen und die Meter eingeben — ab dann ist alles metrisch.' }
  ]);

  Tour.define('abrechnung', [
    { el: '#positionen-section',
      titel: 'Schritt 3: Positionen (dein LV)',
      text: 'Leistungspositionen anlegen, importieren oder direkt <b>aus der ' +
            'KI-Mengenermittlung übernehmen</b> — jede Position mit Einheit und Aufmaßregel.' },
    { el: '#zuordnung-section',
      titel: 'Zuordnung — jede Zahl rückverfolgbar',
      text: 'Hier hängt jede Messung an ihrer Position. Jede Menge lässt sich ' +
            'bis zum einzelnen Raum, zur Wand und zur Öffnung zurückverfolgen — ' +
            'mit der Regel, die angewendet wurde.' },
    { el: '.export-group',
      titel: 'Export: Aufmaß, Materialliste, ÖNORM',
      text: 'Materialliste für den Einkauf, prüffähiges <b>Aufmaß als Excel</b>, ' +
            'Aufmaßblatt-PDF und <b>ÖNORM A 2063 (.onlv)</b> für die Kalkulations-Software.' }
  ]);

  Tour.define('uebersicht', [
    { el: '.result-hero',
      titel: 'Übersicht: alles auf einen Blick',
      text: 'Status der Auswertung und die wichtigsten Exporte. Die Arbeits-Schritte ' +
            'bleiben oben in der Leiste — die Übersicht ist zum Prüfen und Vorzeigen.' },
    { el: '#mengen-board',
      titel: 'Prüfbare Mengen',
      text: 'Mengen nach Leistungsgruppe/Position mit Aufmaß-Herleitung — ' +
            'auf <b>Bestellung</b> umschalten zeigt die Materialliste für den Einkauf.' },
    { el: '#pruefliste',
      titel: 'Wo du prüfen solltest',
      text: 'Die App sagt ehrlich, welche Werte sicher sind und wo ein Blick ' +
            'auf den Plan lohnt — grün ist bewiesen, gelb ist zu prüfen.' }
  ]);
})();
