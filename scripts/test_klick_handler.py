"""WÄCHTER: Klick-Handler im HTML-Attribut müssen gültig sein.

Ein stiller Fehler, der im Browser gefunden wurde und drei Stellen betraf —
zwei davon monatelang:

    onclick="nzHighlightRaum(" + JSON.stringify(name) + ")"

JSON.stringify liefert DOPPELTE Anführungszeichen. Das Attribut selbst steht
aber in doppelten. Der Browser liest also

    onclick="nzHighlightRaum("     ← Attribut endet hier
    Zimmer                          ← wird ein eigenes Attribut
    1")"                            ← Müll

Ergebnis: ein Syntaxfehler, der Klick bleibt wirkungslos. Kein Test schlug
an, keine Fehlermeldung erschien, die Zelle sah klickbar aus — nur passierte
nichts. Genau diese Sorte Fehler kostet Vertrauen: "Im Plan zeigen" ist die
Nachvollziehbarkeits-Zusage der App.

Der Wächter sucht im ausgelieferten JavaScript nach Inline-Handlern, die in
einem doppelt gequoteten Attribut mit JSON.stringify (oder einem anderen
doppelten Anführungszeichen) gebaut werden.
"""
import os
import re
import sys

WURZEL = os.path.join(os.path.dirname(__file__), "..")
DATEIEN = ["public/js/upload.js"]


def _praesentation_ehrlich(fehler):
    """Der Präsentations-Modus darf BERUHIGEN, nicht BESCHÖNIGEN.

    Er blendet aus, was der Prüfer braucht und der Zuschauer nicht:
    Wand-Beschriftung, Öffnungs-Marker, Prüf-Notiz am Raum. Was er NIEMALS
    ausblenden darf, ist der Zustand eines Raums — der rote Punkt „Form vom
    Plan widerlegt" und die Legenden-Zählung. Sonst sähe eine Vorführung
    besser aus als das Produkt, und genau das wäre ein Verkaufsversprechen,
    das die App nicht hält.
    """
    src = open(os.path.join(WURZEL, "public", "js", "upload.js"),
               encoding="utf-8").read()
    for muster, was in (
        (r"var _nzPraes = false", "Zustand _nzPraes existiert"),
        (r"data-z=\"praes\"", "Knopf in der Werkzeugleiste"),
        (r"z === 'praes'", "Knopf ist verdrahtet"),
    ):
        if re.search(muster, src):
            print(f"   {was} ✓")
        else:
            fehler.append(f"Präsentations-Modus: {was} — fehlt")
    # Die Zustands-Anzeige darf NICHT am Modus hängen.
    for muster, was in (
        (r"_nzPraes[^\n]*nRaumWl", "Legenden-Zählung 'Form widerlegt'"),
        (r"_nzPraes[^\n]*raumBadges \+= '<g", "Raum-Badge (Punkt am Plan)"),
        (r"_nzPraes[^\n]*nz-leg-item", "Legende insgesamt"),
    ):
        if re.search(muster, src):
            fehler.append(f"Der Präsentations-Modus unterdrückt {was}. Damit "
                          f"sähe eine Vorführung besser aus als das Produkt.")
    print("   Raum-Zustand und Legende bleiben im Modus sichtbar ✓")


def _werkzeugkasten(fehler):
    """Der Werkzeugkasten muss VOLLSTAENDIG verdrahtet sein (Umbau E2).

    Ein Werkzeug-Knopf, der nichts speichert, ist schlimmer als keiner: der
    Nutzer misst, sieht eine Zahl, und beim naechsten Laden ist sie weg. Die
    Kette Knopf -> Klick -> Server -> Liste -> SVG wird darum als GANZES
    geprueft, nicht Stueck fuer Stueck.
    """
    src = open(os.path.join(WURZEL, "public", "js", "upload.js"),
               encoding="utf-8").read()
    for muster, was in (
        # Die Knoepfe werden dynamisch gebaut (_mwBtn) — das Attribut
        # steht nie literal im Quelltext. Geprueft wird der AUFRUF.
        (r"_mwBtn\('flaeche'", "Werkzeug Fläche in der Leiste"),
        (r"_mwBtn\('rechteck'", "Werkzeug Rechteck"),
        (r"_mwBtn\('laenge'", "Werkzeug Länge"),
        (r"_mwBtn\('stueck'", "Werkzeug Stück"),
        (r"_mwBtn\('abzug'", "Werkzeug Abzug"),
        (r"_mwBtn\('volumen'", "Werkzeug Volumen (E8)"),
        (r"_mwBtn\('treppe'", "Werkzeug Treppe (E8)"),
        (r"_mwBtn\('dach'", "Werkzeug Dach (E8)"),
        (r"_mwBtn\('wandflaeche'", "Werkzeug Wandfläche (E8)"),
        (r"_mwAutoDone", "Auto-Vorschläge beim Plan-Laden"),
        (r"hoehe_m", "Höhe wird erfragt und mitgeschickt"),
        (r"querySelectorAll\('\[data-mw\]'\)", "Werkzeug-Knöpfe verdrahtet"),
        (r"function _mwKlick", "Klick setzt Punkte"),
        (r"function _mwAbschliessen", "Doppelklick/Enter beendet"),
        (r"fetch\('/api/messung'", "Messung wird GESPEICHERT"),
        (r"fetch\('/api/messungen\?", "Messungen werden GELADEN"),
        (r"function _mwSvg", "Messungen werden gezeichnet"),
        (r"function _mwSnapPunkt", "Snapping auf Wandlinien"),
        (r"_mwLaden\(\)", "Laden ist verdrahtet"),
        (r"id=\"nz-mw\"", "SVG-Ebene im Plan"),
    ):
        if re.search(muster, src):
            print(f"   {was} ✓")
        else:
            fehler.append(f"Werkzeugkasten: {was} — fehlt. Eine Messung, die "
                          f"nicht gespeichert/geladen/gezeichnet wird, ist "
                          f"eine Zahl, die beim Neuladen verschwindet.")

    # DIE GEOMETRIE WIRD IN PLAN-PUNKTEN GESPEICHERT, nicht in Bild-Pixeln.
    # Bild-px haengen an der Render-Aufloesung; wird das Vorschaubild einmal
    # groesser gerendert, laegen alle Messungen falsch.
    if re.search(r"punkte:\s*ptsPx\.map\(_mwPxZuPt\)", src):
        print("   Geometrie wird in PLAN-pt gespeichert (nicht Bild-px)  ✓")
    else:
        fehler.append("Messungs-Geometrie wird nicht nach Plan-pt gewandelt — "
                      "bei anderer Render-Auflösung läge jede Messung falsch.")

    # E3–E6: die Kette von der Erkennung bis zum Protokoll. Jedes Glied,
    # das fehlt, laesst Mengen stumm verschwinden: ohne Vorschlags-Knopf
    # bleibt die Erkennung folgenlos, ohne Zuordnungs-Select landet jede
    # Messung unter "ohne Position", ohne Protokoll gibt es nichts, das der
    # Rechnung beiliegt.
    auf = open(os.path.join(WURZEL, "public", "js", "aufmass.js"),
               encoding="utf-8").read()
    html = open(os.path.join(WURZEL, "public", "projekt.html"),
                encoding="utf-8").read()
    for muster, wo, was in (
        (r"messungen-vorschlagen", src, "KI-Räume -> Vorschläge (Frontend)"),
        (r"data-mokall", src, "Alle Vorschläge bestätigen"),
        (r"function renderPositionen", auf, "Positionen-Verwaltung"),
        (r"/api/lv-import", auf, "ONLV-Import angeschlossen"),
        (r"/api/aufmassplan", auf, "Aufmaßplan-PDF verlinkt"),
        (r"/api/protokoll-xlsx", auf, "Protokoll-Excel verlinkt"),
        # MANUELL-MODUS + EDITOR-GESTEN (docs/MANUELL_MODUS.md):
        (r"_projModus === 'manuell'", src, "Manuell-Modus-Weiche"),
        (r"reqBody\.leicht = true", src, "Leicht-Pass wird angefordert"),
        (r"data-mki", src, "KI-Analyse nachholen"),
        (r"e\.key === 'Backspace'", src, "Backspace nimmt Punkt zurück"),
        (r"e\.key === 'Delete'", src, "Entf löscht gewählte Messung"),
        (r"_mwUndo", src, "Ctrl+Z-Sitzungsstack"),
        (r"e\.shiftKey && _mwPts\.length", src, "Shift-Ortho"),
        (r"nzZeigeMessung", src, "Plan-Sprung existiert"),
        (r"mw_hint_gesehen", src, "So-misst-du-Ersthinweis (einmalig)"),
        (r"data-sprung", auf, "M-Nummern springen zum Plan"),
        (r"data-mv", src, "Vertex-Handles der Messung"),
        (r"_mwVDrag", src, "Vertex-Drag-Zustand"),
        (r"geometrie: _dM\.geometrie", src, "Drop PATCHt die Geometrie (Server rechnet)"),
        (r"< 12\) \{\n        _mwAbschliessen", src, "Klick auf Start schließt"),
        (r"uebernehmenAusMassen", auf, "KI-LV -> echte Positionen"),
        (r"function renderMessungZuordnung", auf, "Zuordnung Messung->Position"),
        (r"function renderProtokoll", auf, "Aufmaßprotokoll"),
        (r"ohne Position", auf, "Unzugeordnetes wird ausgewiesen"),
        (r"js/aufmass\.js", html, "Modul ist eingebunden"),
        (r"renderAufmassBereiche", src, "Schritt-Wechsel lädt die Bereiche"),
    ):
        if re.search(muster, wo):
            print(f"   {was} ✓")
        else:
            fehler.append(f"Aufmaß-Kette: {was} — fehlt")
    api_src = open(os.path.join(WURZEL, "api", "extract.py"),
                   encoding="utf-8").read()
    if "/api/messungen-vorschlagen" not in api_src:
        fehler.append("Endpunkt /api/messungen-vorschlagen fehlt im Backend")
    else:
        print("   Endpunkt messungen-vorschlagen im Backend ✓")

    # AUSGEMISTET (2026-08-19): das alte "Messen"-Hilfslinien-Werkzeug ist
    # raus — vollstaendig vom Laengen-Werkzeug (L) abgeloest. Kommt es
    # zurueck, ist das eine bewusste Produktentscheidung, kein Versehen.
    if re.search(r"_railBtn\('mess',", src):
        fehler.append("altes Mess-Werkzeug ist zurueck in der Leiste — es war "
                      "bewusst ausgemistet (L ist der eine Messweg)")
    else:
        print("   altes Mess-Werkzeug bleibt draussen                    ✓")

    # DER WERT KOMMT VOM SERVER. Rechnet der Browser die gespeicherte Zahl,
    # gibt es zwei Wahrheiten (Anzeige vs. Protokoll/Export).
    if re.search(r"_mwListe\.push\(d\.messung\)", src):
        print("   gespeicherter Wert kommt vom Server                    ✓")
    else:
        fehler.append("Der gespeicherte Wert stammt nicht aus der Server-"
                      "Antwort — zwei Rechenwege sind zwei Wahrheiten.")


def run():
    print("KLICK-HANDLER — Inline-Attribute auf gültige Anführungszeichen")
    print("=" * 84)
    fehler = []
    _praesentation_ehrlich(fehler)
    _werkzeugkasten(fehler)
    geprueft = 0
    for rel in DATEIEN:
        p = os.path.join(WURZEL, rel)
        if not os.path.exists(p):
            continue
        zeilen = open(p, encoding="utf-8").read().split("\n")
        # Ein Inline-Handler wird über mehrere Zeilen zusammengesetzt; darum
        # jede Zeile mit on…=" ansehen UND die beiden folgenden.
        for i, z in enumerate(zeilen):
            if not re.search(r'on(click|change|input|submit)="', z):
                continue
            geprueft += 1
            fenster = " ".join(zeilen[i:i + 3])
            # Der Aufruf endet erst mit ')"' — alles davor gehört zum Attribut.
            m = re.search(r'on\w+="[^"]*"\s*\+\s*(.+?)\+\s*\'\)"', fenster)
            teil = m.group(1) if m else fenster
            if "JSON.stringify" in teil and 'on\\w+="' not in teil:
                # JSON.stringify IN einem doppelt gequoteten Attribut
                if re.search(r'on\w+="[^"]*\'?\s*\+\s*JSON\.stringify', fenster):
                    fehler.append(
                        f"{rel}:{i + 1} — JSON.stringify in einem doppelt "
                        f"gequoteten Attribut: liefert doppelte "
                        f"Anführungszeichen und zerlegt das Attribut.\n"
                        f"      {z.strip()[:100]}")
    print(f"{geprueft} Inline-Handler geprüft in {len(DATEIEN)} Datei(en)")
    if fehler:
        print("\nFEHLER:")
        for f in fehler:
            print(f"  ✗ {f}")
        print("\nRichtig ist: innen EINFACHE Anführungszeichen, den Wert erst")
        print("JS-escapen (\\ und ') und dann HTML-escapen. In upload.js macht")
        print("das die Funktion _raumKlick(name) — sie ist die eine Stelle.")
    else:
        print("WÄCHTER ok: kein Inline-Handler baut sein Argument mit "
              "doppelten Anführungszeichen")
    assert not fehler, f"{len(fehler)} kaputte Klick-Handler"


if __name__ == "__main__":
    run()
