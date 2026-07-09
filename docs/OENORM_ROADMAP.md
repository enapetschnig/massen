# ÖNORM-Roadmap — Umbau zur besten Massenermittlungs-App (Stand 2026-07-08)

Erstellt aus ÖNORM-Recherche (B 2110/2204/2230/2232/A 2063/LB-HB, Wettbewerb:
Bluebeam/Togal/Kreo/ABK) + Code-Audit über 5 Säulen. Reifegrade = ehrliche Ist-Bewertung.

## Kernbefund

Die App hat einen echten, verteidigbaren Kern — byte-exakter Text-Layer, 12/12 Guards, 13/13 Polier-Positionen auf dem Referenzplan, 9 Gewerke, Kalibrierungs-Moat — aber sie ist heute die beste App für EINE Plan-Klasse (native Wohnbau-Polierpläne mit HLZ-Mauerwerk), nicht für "alle Pläne": Scans liefern null belastbare Mengen, mehrschichtige Aufbauten (Holzbau/WDVS) werden nachweislich falsch gepaart (6,95 m statt ~42 m), und "label"-kalibrierte Pläne sperren den Export. Beim Kernversprechen "Massen laut ÖNORM" gibt es drei belegte Norm-Fehler im Code: globale 4,0-m²-Öffnungsschwelle auch für Mauerwerk (B 2204 verlangt 0,5 m²), Maler-Schwelle 2,5 m² ist deutsche DIN-18363-Kontamination statt B 2230-1, und der 3,2-m-Höhensplit (Putz/Fliesen/Trockenbau) fehlt komplett — dazu kein A-2063-taugliches Format, also kein Anschluss an ABK/Nevaris. Traceability ist ein Parallel-Universum: nur HLZ-Zeilen sind plan-klickbar, ganze Mengen-Familien (Bodenplatte, Decke, WDVS-Fassade, Gerüst) sind auf keinem Blatt eingezeichnet, und ein Seiten-Key-Bug lässt OG-Korrekturen auf EG-Wänden landen. Im Workflow ist Vorhandenes abgerissen verdrahtet: Stepper ist toter Code, die Gewerk-Wahl tut nichts, die Kalibrierungsseite ist von nirgends verlinkt. Ehrlich gesagt: gegen Togal/Kreo gewinnt die App durch ÖNORM-Logik nur, wenn diese Logik gewerksrichtig, am Plan belegt und im A-2063-Format prüffähig ist — alle drei Stücke fehlen noch teilweise.

## Säulen-Reifegrade

### zuverlaessigkeit — 70%
**Ist:** Nativ-Pläne stark: byte-exakter Kern (Stempel, Öffnungen, Maßketten, Legende), Kalibrierung R²≥0.98 mit Kreuzcheck, ehrliche Degradation statt Crash, Angerer 9/9 green, 12/12 Guards. Aber: Wand-Paarung matcht bei mehrschichtigen Aufbauten Beplankungslinien statt Gesamtspanne (api/vektor.py:469-521, gemessen falsch), Schraffur-Gate erst ab 8 Hatches, PASS-4-Crops mit festen Offsets, 899k-Pfad-Pläne 364s = Vercel-Timeout-Risiko, Rohbau-vs-Fertig-Differenz drückt TG auf 64% green.
**Soll:** Jeder Plan validiert sich selbst (IoU-Raumbeweis + Maßketten-Snap als Standard-Gate), Zuverlässigkeit pro Plan GARANTIERT statt statistisch; Layer-Assembly-Paarung öffnet Holzbau/WDVS/STB; Zeit-Budget verhindert Prod-Timeouts.

### alle-plaene — 45%
**Ist:** Korpus 7/7 mit funktionierender Planansicht, Schnitt-Blätter ehrlich als Schnitt, Plantyp-Degradation vorhanden. Aber: Scans/Bild-PDFs liefern KEINE Mengen (härteste Grenze, api/nachzeichnen.py:74-77), gemischte cm/Meter-Notation nur pro Blatt → WM/Holzbau/05_AU nur 'label'-kalibriert = Export gesperrt, Grundriss-Heuristik deutsch/wohnbau-fixiert, Hallen >30m ohne Stempel fallen raus, Bestand/Abbruch-Farbsemantik nur Warnung statt Mengen-Eingriff — Umbaupläne bekommen falsche Neubau-Mengen.
**Soll:** Scans über OCR-Ersatz-Text-Layer in dieselbe byte-exakte Pipeline; pro-Kette-Notationsentscheidung schaltet die label-Pläne frei; Rot/Gelb/Grau hart in den Mengen; Plantyp-Klassifikation steuert Erwartung explizit.

### design-workflow — 55%
**Ist:** Design-System 'Technisches Reißbrett' ist eigenständig und zielgruppenrichtig; Auto-Analyse-Queue, prüfbares Mengen-Board, Korrektur mit Live-Neuberechnung funktionieren. Aber: Workflow-Stepper ist toter Code (Element fehlt in projekt.html), Gewerk-/Geschoss-Wahl wirkungslos (still 3 Geschosse angenommen), Kalibrierung (der Moat!) von keiner Seite verlinkt, 6 Export-Buttons ohne Führung, zwei parallele Ergebnis-Systeme, Alles-oder-nichts-Gating, kein Onboarding/Demo-Projekt.
**Soll:** Geführte Kette: Sektor wählen → Plan rein → prüfbares Aufmaß mit Plan-Beleg → EIN sektorrichtiger Export (.xlsx/A2063) → Kalibrierung sichtbar im Loop; Wow-Moment beim ersten Login statt nach 5 Min Wartezeit.

### traceability — 50%
**Ist:** Wände (Länge/Stärke/mass_exakt), Räume (F+U-Beweis), Öffnungen (byte-exakte Marker), Hüllen-Kontur, Aufmaßblatt-PDF mit Formeln — gut. Aber: Overlay und Mengenwelt sind zwei getrennte Systeme mit nur 3 dünnen Brücken; Estrich/Maler/Fliesen/Putz-Positionen haben keinen Plan-Anker (klickbar ist NUR HLZ); Bodenplatte/Decke/Attika/WDVS-Fassade/Gerüst nirgends eingezeichnet; Öffnungsabzug am Plan unsichtbar; kein Auto-Abgleich Overlay-Σ vs. Mengen-Σ; Nachzeichnen-Fehlschlag blockiert Export nicht; Bug: Korrekturen ohne Seiten-Key → OG-Edits landen auf EG-Wänden.
**Soll:** Bluebeam-Prinzip: JEDE Aufmaß-Zeile klickbar auf ihr Plan-Element; Abzüge und Maßzahl-Anker am Plan eingezeichnet; Overlay-vs-Mengen-Abgleich als Prüf-Gate mit Δ%-Banner; Mengen ohne Plan-Beleg tragen sichtbare Warnung.

### multi-sektor — 55%
**Ist:** 9 Gewerke werden berechnet (Rohbau, Putz/Fassade, Estrich, Maler, Beton, Fliesen, Fenster, WDVS, Gerüst) — mehr als jeder KI-Wettbewerber. Aber: Öffnungsschwellen gewerklich teils normwidrig (Mauerwerk-Default 4,0 statt 0,5 m²; Maler 2,5 m² = DE-DIN-Import; kein 3,2-m-Höhensplit); keine A-2063/LB-HB-Positionsnummern → kein Anschluss an ABK/Nevaris/ORCA; im UI verstecken sich die Verkaufssektoren hinter 'Kalkulant (alle)' und einem zugeklappten Drawer; Dashboard-Dropdown widerspricht den Pipeline-Gewerken; Erdarbeiten (B 2205, m³) fehlen ganz.
**Soll:** Gewerksrichtige Schwellen-Matrix aus der Norm-Recherche im Code verankert und pro Firma kalibrierbar; Sektor-Sichten first-class im UI; Export als prüffähiges Aufmaß mit LB-HB-Position und A-2063-Formelkatalog — das Differenzierungs-Moat gegen Togal UND gegen ABK.

## Priorisierte Schritte (wirkungsstärkste zuerst)

### 1. ÖNORM-Schwellen-Matrix gewerksrichtig machen (Kernversprechen reparieren)
*Säule multi-sektor · Aufwand M · Risiko mittel · Demo-Risiko: ja*
*Norm-Bezug: B 2204:2021 4.2.4/5.5.1.3, B 2232:2016 5.5.2, B 2230-1 (AT statt DIN 18363), LB-HB LG 08/10/11*

Gewerksspezifische Defaults statt globaler 4,0 m²: Mauerwerk/Beton-Fläche/Estrich-Aussparung/Abdichtung → 0,5 m² (B 2204 4.2.4.2 / B 2232 5.5.2.2b); Putz/WDVS/Trockenbau → 4,0 m² nur weil LB-HB keine Leibungspositionen kennt (B 2204 5.5.1.3, als Begründung im Aufmaß ausweisen); Beton-Raummaß → 0,10 m³; Maler: die 2,5-m²-DE-Regel (massen_logic.py:146-148, explizit 'analog DIN 18363') entfernen — B 2230-1 sieht Brutto+Zuschläge vor; solange die Norm nicht vorliegt, Schwelle als 'nicht AT-belegt, bitte je Firma setzen' kennzeichnen statt still DE-Recht anwenden. Zusätzlich: Unterbrechungen ≤0,5 m bei Längenmaß übermessen, Leibungen ≤0,25 m lfm vs. >0,25 m m², FT-Überlager +2×15 cm (LB-HB LG 08), Estrich-Sockel-Mindestmaß 0,25 m. Jede Schwelle bleibt pro Firma/Gewerk überschreibbar (Mechanismus _schwelle_fuer existiert).

**Verifikation:** Neuer Guard test_oenorm_schwellen: pro Gewerk eine Fixture-Öffnung 1,0×2,01 m (2,01 m²) — muss bei Mauerwerk abgezogen, bei Putz übermessen werden; Angerer-13/13 darf nicht regressieren (bewusste Deltas dokumentieren)

**Dateien:** api/massen_logic.py:20-200, api/materialliste.py, scripts/test_massen_logic.py, scripts/test_materialliste_angerer.py (Toleranzen neu justieren)

### 2. Positions-Anker generalisieren: jede Aufmaß-Zeile klickbar auf den Plan
*Säule traceability · Aufwand M · Risiko niedrig · Demo-Risiko: nein*
*Norm-Bezug: B 2110 Aufmaß-Nachvollziehbarkeit; Bluebeam-Prinzip Markup=Datensatz*

add_zeile um strukturierte Anker-Felder (raum, wand_id, oeffnung_id) erweitern; nzHighlight von 'nur HLZ-cm' auf Raum-Polygone, Wand-Segmente und Öffnungs-Marker verallgemeinern und an ALLE Gewerk-Zeilen (Estrich/Maler/Fliesen/Putz/Beton) binden. Beide Enden existieren schon — größter Traceability-Hebel pro Aufwand.

**Verifikation:** Guard: jede Zeile mit Raumnamen im Text muss einen Anker tragen (Coverage-Metrik nicht-fallend in test_alles.py); manueller Klick-Test auf Angerer+TG

**Dateien:** api/massen_logic.py:100 (add_zeile), public/js/upload.js:747, 873, 1042, 2376

### 3. Bugfix: Korrekturen je Seite speichern (OG-Edits verfälschen EG-Aufmaß)
*Säule zuverlaessigkeit · Aufwand S · Risiko niedrig · Demo-Risiko: nein*

Speicher-Key der Plan-Korrekturen um Seiten-Suffix (_s{seite}) erweitern und beim Restore je Seite filtern — heute landen per Wand-ID gespeicherte OG-Korrekturen auf EG-Wänden.

**Verifikation:** Guard: Korrektur auf Seite 2 setzen, Seite 1 laden → keine Anwendung; Migrationstest für bestehende Keys ohne Suffix

**Dateien:** public/js/upload.js:2363-2372, api/extract.py:5013, 5041, 5100

### 4. Kalibrierung in den Flow holen (der Moat ist unsichtbar)
*Säule design-workflow · Aufwand S · Risiko niedrig · Demo-Risiko: nein*

Navbar-Link auf allen Seiten, CTA im Konfidenz-Kopf ('Weicht die Liste ab? → Mit fertigem Projekt kalibrieren'), Kalibrierungs-Status als Dashboard-Stat ('KI kennt N deiner Projekte'). Rein additiv, kein Eingriff in Rechenwege.

**Verifikation:** Manuell: von jeder Seite in ≤1 Klick zur Kalibrierung; Demo-Durchlauf unverändert

**Dateien:** public/dashboard.html, public/projekt.html, public/index.html, public/js/upload.js, public/js/dashboard.js, public/kalibrierung.html

### 5. Auto-Abgleich Overlay vs. Mengen + Export-Gate
*Säule traceability · Aufwand M · Risiko niedrig · Demo-Risiko: nein*
*Norm-Bezug: B 2110 8.3.1.2 (gemeinsame Feststellung/Prüfbarkeit)*

Abgleichszeile rendern: Hüllen-Kontur-Umfang vs. gemessen.aussenumfang_m und Overlay-Wand-Σ vs. Materialliste-Wandlängen, mit Δ% und rotem Banner + Nachmessen-CTA bei >5%; in Schritt 3/Export Warnhinweis 'Mengen ohne Plan-Beleg', wenn Nachzeichnen fehlschlug (heute wird trotzdem still voll exportiert). Macht das Overlay vom Nebenschauplatz zum Prüf-Gate.

**Verifikation:** Guard in test_korpus.py: Δ% je Plan berechnet und ≤ Schwelle auf grünen Plänen; UI-Banner-Sichtprüfung auf einem absichtlich verstellten Plan

**Dateien:** public/js/upload.js:355, 1963-1964, 2608-2611; api/nachzeichnen.py:361-370, 587

### 6. Pro-Kette-Notationsentscheidung: 'label'-Pläne für Mengen-Export freischalten
*Säule alle-plaene · Aufwand M · Risiko mittel · Demo-Risiko: ja*
*Norm-Bezug: A 6240-2 Bemaßungskonventionen (cm unter 1 m, m mit Hoch-cm)*

cm/Meter-Notation nicht mehr pro Blatt, sondern pro Maßkette entscheiden (strikte Zweitpass-Logik je Kette mit Konsistenz-Gate), damit WM-Großplan, Holzbau und 05_AU von 'Kalib label' (Export gesperrt) auf verifizierte Ketten-Kalibrierung kommen.

**Verifikation:** test_korpus.py: Kalib-Status der 3 label-Pläne wird ✓, R²/ptm der bisher grünen Pläne byte-identisch (Regressions-Assert auf exakte ptm-Werte)

**Dateien:** api/vektor.py:165-229 (bes. 183-188, 217-227), api/massketten.py:46-49, scripts/test_korpus.py

### 7. IoU-Selbstvalidierung als Standard-Gate + Konfidenz pro Position
*Säule zuverlaessigkeit · Aufwand L · Risiko mittel · Demo-Risiko: nein*

exp_rohbau_iou_v3 (Maßketten-Fluchten→Wand-Achsen-Snap + IoU-Raumbeweis) aus dem Experiment in die Pipeline heben und über den ganzen Korpus als Gate ausrollen; Ergebnis pro Position als sicher/prüfen/unsicher durchreichen (statt 4 verschiedener Konfidenz-Darstellungen). Der Plan prüft sich selbst — rote Grenzen werden die Arbeitsliste, Zuverlässigkeit pro Plan garantiert statt statistisch.

**Verifikation:** test_echter_greencount.py als nicht-fallende Metrik in test_alles.py verankern (Angerer 9/9 halten, TG >16/25 steigern)

**Dateien:** scripts/exp_rohbau_iou_v3.py → api/nachzeichnen.py / api/konsistenz.py, api/massen_logic.py (Konfidenz-Feld), public/js/upload.js (eine Konfidenz-Darstellung), scripts/test_echter_greencount.py

### 8. Layer-Assembly-Wandpaarung: Holzbau/WDVS/STB+Dämmung richtig messen
*Säule alle-plaene · Aufwand L · Risiko hoch · Demo-Risiko: ja*

Mehrschichtige Wandaufbauten als Gesamt-Spanne paaren statt global-greedy Nachbarlinien (heute: 34-cm-Außenwand wird 6,95 m statt ~42 m, alle Holzbau-Wände mass_exakt=False); Legende-Schichtsummen als Spann-Kandidaten nutzen; Zwei-Linien-Mauerwerk als abgesicherter Sonderfall. Öffnet die größten Plan-Klassen jenseits HLZ — Voraussetzung für die Sektoren Holzbau und WDVS.

**Verifikation:** Korpus-Guard monoton: Angerer/AP.01/TG-Wandzahlen und -Längen byte-identisch (Mauerwerk darf nicht regressieren); Holzbau-Plan: 34-cm-Wand-Σ im Toleranzband der Plan-Maßkette; hinter Feature-Flag entwickeln, erst nach Korpus-grün scharf schalten

**Dateien:** api/vektor.py:469-521 (wand_paare), api/vektor.py:489 (Schraffur-Gate), api/legende.py, scripts/test_korpus.py, scripts/test_generalisierung.py

### 9. Workflow-Stepper aktivieren + Ergebnis-Seite entrümpeln
*Säule design-workflow · Aufwand M · Risiko mittel · Demo-Risiko: ja*

#workflow-steps-Leiste in projekt.html einfügen (JS existiert komplett: WF_GRUPPEN, wfShow), Legacy results-section (Tabs, zweite Planview, sechster Export-Button) in den Advanced-Drawer verschieben oder löschen, Export auf EINEN Primär-Button (sektorabhängig) + Dropdown 'Weitere Formate' reduzieren, .xlsx statt CSV.

**Verifikation:** Manueller End-to-End-Durchlauf (Upload→Prüfen→Mengen→Export) auf Angerer; Screenshot-Vergleich der 4 Schritte; alte Deep-Links dürfen nicht brechen

**Dateien:** public/projekt.html (u.a. Zeile 463), public/js/upload.js:2603-2636, public/js/tabelle.js, public/js/planview.js, api (xlsx-Export)

### 10. Sektor-Wahl durchgängig verdrahten (Multi-Sektor sichtbar machen)
*Säule multi-sektor · Aufwand M · Risiko mittel · Demo-Risiko: nein*

EIN Sektor-Feld bei Projektanlage, abgestimmt auf die 9 Pipeline-Gewerke; reaktiviert den toten gewerk-Parameter in startAnalysis (heute läuft ALLES als 'allgemein' mit still angenommenen 3 Geschossen / 4 Whg — für ein EFH falsch); steuert Default-Preset, Reihenfolge im Mengen-Board, Export-Default; Geschoss-Annahmen sichtbar machen statt still setzen; Dashboard-Dropdown mit Pipeline-Gewerken synchronisieren (kein nicht-berechnetes 'Trockenbau' anbieten).

**Verifikation:** Default bleibt 'allgemein' (Demo unverändert); Guard: Analyse-Request trägt gewähltes Gewerk; manuell: EFH-Projekt mit 1 Geschoss liefert keine 3-Geschoss-Mengen

**Dateien:** public/js/upload.js:1290-1295, 2639; public/js/dashboard.js, public/dashboard.html, public/projekt.html, api/analyse.py

### 11. Beleg-Orte einzeichnen: Maßzahl-Anker, Öffnungsabzug, Wand-IDs, fehlende Bauteile
*Säule traceability · Aufwand L · Risiko niedrig · Demo-Risiko: nein*
*Norm-Bezug: B 2204 5.5.1.3 (Abzug/übermessen muss prüfbar sein), B 2110 Aufmaßblatt-Prüfbarkeit*

(a) mass_snap gibt (mx,my) des Maßzahl-Treffers zurück → Ring um die verwendete Plan-Maßzahl; (b) F/T-Marker zeigen Abzug ('−2,1 m²' bzw. 'übermessen') + Verbindungslinie zur zugeordneten Wand (wandOeff existiert); (c) 'W{id}' ins Wand-Label, Wand-Aufmaß-Zeilen klickbar → _nzSel; (d) Bodenplatten-/Decken-Polygon und Dach-Teilflächen einzeichnen (Kontur existiert, Fläche nicht); WDVS/Gerüst-Fassadenflächen mindestens als Abwicklungs-Schema am Grundriss.

**Verifikation:** Manuell auf Angerer: jede Aufmaßblatt-Zeile physisch am Plan auffindbar; Guard: mass_snap-Rückgabe enthält Koordinaten für alle mass_exakt-Wände

**Dateien:** api/nachzeichnen.py:196-231, 356-372, 643-658; public/js/upload.js:1592-1607, 1637-1679, 1993-2013

### 12. Rot/Gelb/Grau hart in die Mengen (Umbau-Pläne korrekt statt gewarnt)
*Säule alle-plaene · Aufwand L · Risiko hoch · Demo-Risiko: nein*
*Norm-Bezug: Bauordnungs-Farbcode (Wien u.a.); Abbruch nach B 2251:2020 (0,5 m²/0,10 m³)*

Die byte-exakt erkannte Farb-Legende (Neubau/Abbruch/Bestand) vom reinen Hinweis zum Mengen-Split machen: Wände nach Farbklasse klassifizieren, Abbruch als eigenes Gewerk (B 2251!), Bestand aus Neubau-Mengen raus; konservatives Gate: nur eingreifen, wenn Legende UND Flächen-Klassifikation konsistent, sonst heutige Warnung behalten. Heute bekommen Umbaupläne Neubau-Mengen inkl. Bestandsanteil — für Sanierung (halber AT-Markt) unbrauchbar.

**Verifikation:** Neubaupläne (ganzer Korpus) byte-identische Mengen (Gate greift nicht); ein Umbau-Fixture-Plan mit bekannter Rot/Gelb-Verteilung als neuer Guard

**Dateien:** api/farben.py:16-27, api/vektor.py (Farbklasse je Wand), api/materialliste.py, api/massen_logic.py, scripts/test_farben.py

### 13. Prüffähiges Aufmaß: LB-HB-Positionsnummern + ÖNORM A 2063 / .xlsx-Export
*Säule multi-sektor · Aufwand XL · Risiko niedrig · Demo-Risiko: nein*
*Norm-Bezug: ÖNORM A 2063 (B 2114 ist obsolet!), LB-HB Version 023, B 2110 Aufmaßblatt*

Jede Position bekommt ihre LB-HB-LG-Positionsnummer (LG 07/08/10/11/24/39/44/04/73), Rechengang im A-2063-Formelkatalog-Stil; Export als ONLV/A-2063-XML und .xlsx mit Firmen-Briefkopf. Das ist der Anschluss an ABK/Nevaris/ORCA statt Konkurrenz — kein US-Tool kann das, und die Aufmaß-Formeln existieren bereits in aufmassblatt.py.

**Verifikation:** Export-Datei in ABK/ORCA-Testversion einlesen (Roundtrip); Guard: jede Position trägt gültige LG-Nummer; Σ XML = Σ CSV

**Dateien:** api/massen_logic.py (LG-Nummern-Mapping), api/aufmassblatt.py:209ff, neuer api/a2063_export.py, public/js/upload.js (Export-Dropdown)

### 14. 3,2-m-Höhensplit für Putz/Fliesen/Trockenbau
*Säule multi-sektor · Aufwand M · Risiko niedrig · Demo-Risiko: nein*
*Norm-Bezug: LB-HB LG 10/24 (Höhensplit 3,2 m, ganze Höhe in die ü-3,2-Position), LG 39 (Aufzahlung ganze Wandhöhe 3,2–5 m)*

Positionen 'bis 3,2 m' vs. 'über 3,2 m' (Raumhöhen liegen als H-Stempel byte-exakt vor): Wand >3,2 m zählt zur GÄNZE in die teurere Position (lotrechte Abgrenzung), bei Trockenbau Aufzahlung auf die gesamte Wandhöhe. Fehlt heute komplett — bei Altbau/Gewerbe mit hohen Räumen ist jede Putz-/Fliesen-Masse in der falschen Position.

**Verifikation:** Guard: Fixture-Raum mit H=3,5 m → 100% der Wandfläche in ü-3,2-Position, 0% Split; Räume ≤3,2 m unverändert

**Dateien:** api/massen_logic.py (Putz-, Fliesen-, künftig Trockenbau-Blöcke), scripts/test_massen_logic.py

### 15. Scan-Pfad: OCR-Ersatz-Text-Layer für die byte-exakte Pipeline
*Säule alle-plaene · Aufwand XL · Risiko mittel · Demo-Risiko: nein*

High-DPI-Vision/OCR (mit Rotations-Hypothesen für vertikale Maßketten, Deskew, X/Y-Kalibrierung) erzeugt synthetische Text-Spans (Ketten-Zahlen, Stempel, Legende) in DEMSELBEN Format wie der PDF-Text-Layer und speist sie in die bestehende Pipeline — dadurch laufen Kalibrierung, Maßketten-Validierung und alle Gates auch auf Scans. Kontrollierte Degradation: Positionen nur mit bestandenem Selbst-Validierungs-Gate, nie geraten. Heute liefern Scans null Mengen — das ist die größte einzelne 'alle Pläne'-Lücke (Bestandspläne!).

**Verifikation:** 2-3 gescannte Fixture-Pläne mit bekannter Ground Truth in test_korpus.py; Metrik 'Scan-Positionen mit bestandenem Gate' nicht-fallend; native Pläne byte-identisch (Weiche greift nur bei Rastern)

**Dateien:** neuer api/ocr.py, api/extract.py:1380-1386, api/vektor.py:14 (RASTER_MIN_PFADE-Weiche), api/nachzeichnen.py:71-77, scripts/test_korpus.py (Scan-Fixtures)

### 16. Performance-Budget + Pfad-Dezimierung für Großpläne
*Säule zuverlaessigkeit · Aufwand M · Risiko mittel · Demo-Risiko: ja*

Gesamt-Zeitbudget in der Pipeline (heute nur API-Timeout-Guard) + Pfad-Dezimierung/Vorfilterung für >500k-Item-Pläne; 899k-Pfad-Plan brauchte 364s lokal gegen 300s Vercel-Limit — die größten (= lukrativsten) Pläne können in Prod still ins Timeout laufen.

**Verifikation:** test_korpus.py: Laufzeit je Plan als nicht-steigende Metrik, WM-Großplan <240s lokal; Mengen vor/nach Dezimierung byte-identisch auf dem ganzen Korpus

**Dateien:** api/extract.py:890-891, api/vektor.py (Dezimierung), scripts/test_korpus.py (Zeit-Metrik)

### 17. Teilergebnisse + Demo-Projekt (Verkaufs-Wow in 60 Sekunden)
*Säule design-workflow · Aufwand M · Risiko niedrig · Demo-Risiko: nein*

Ergebnis mit Banner 'vorläufig — 2/3 Pläne' schon vor Abschluss aller Pläne zeigen, fehlgeschlagene Pläne mit 'ohne diesen Plan fortfahren'; jedes neue Konto startet mit einem fertig analysierten Beispielprojekt (Angerer-artig) — der Käufer sieht prüfbares Aufmaß, Planansicht und Export VOR dem ersten eigenen Upload. Zusätzlich: Registrieren-Tab an das e-power-Account-Modell angleichen.

**Verifikation:** Neues Testkonto anlegen → Demo-Projekt sofort sichtbar; Upload von 3 Plänen, einen künstlich blockieren → Teilergebnis erscheint

**Dateien:** public/js/upload.js:95-109, 1195-1215; public/js/dashboard.js, public/index.html, Seed-Skript für Demo-Projekt

## Sofort sicher (kein Demo-Risiko)

- Bugfix Korrektur-Seiten-Key (upload.js:2363-2372 + api/extract.py:5013/5041/5100): OG-Edits landen heute auf EG-Wänden — kleiner Fix, echte Korrektheit, berührt keinen Demo-Pfad
- Kalibrierung in den Flow verlinken (Navbar + CTA im Konfidenz-Kopf + Dashboard-Stat): der Moat ist heute nur per URL-Eingabe erreichbar — rein additives UI, null Rechenweg-Risiko
- Positions-Anker generalisieren (api/massen_logic.py add_zeile + upload.js nzHighlight auf alle Gewerk-Zeilen): jede Estrich-/Maler-/Fliesen-Position wird per Klick am Plan sichtbar — größter Traceability-Hebel, beide Enden existieren bereits, rein additiv

*Erledigt seit Erstellung: Korrektur-Seiten-Key-Bugfix ✓ · Kalibrierung-Navbar-Links ✓ (Commit 1f31ae0) · #9 Workflow-Stepper aktiviert ✓ (b9608f9 + 5dc46d4, live verifiziert: Übersicht-Default unverändert, Schritt 2 = Prüfliste-Kartenraster + Planansicht mit Overlay, Übersicht stellt alles wieder her — Seitenhöhe 2553→5041px gemessen; Export-Konsolidierung auf 1 Primär-Button + .xlsx noch offen) · Fenster-Marker am Plan ✓ (e4a722e: Vision-Fenster mit pos_pt → Overlay+Aufmaßblatt, Sadiku 18/18 im Bild, visuell geprüft) · #15 Stufe 1 Scan-Geometrie ✓ (2510-Scan: 0/23 → 20/20 Raum-Umfänge aus Raum-Proportion U≈2(√(F·r)+√(F/r)), Vision-Bbox + Fuzzy-Name + Default 1,35 ohne Gänge; alle isoperimetrisch plausibel; ÖNORM-Zeilen live „U≈ (geschätzt)" vs. „U=" byte-exakt, Raum-Aufmaß ≈-Flag; echte Scan-Wandgeometrie/OCR bleibt Stufe 2)*