# ROADMAP — Die beste Massenermittlungs-App der Baubranche

**Nordstern:** Pläne **sehr zuverlässig** lesen, Massen **laut ÖNORM** ermitteln,
**alles am Plan eingezeichnet und nachvollziehbar**, funktioniert **für alle Pläne**,
für mehrere Bereiche der Baubranche (Baubetriebe/Rohbau, Ausbau-Gewerke, Kalkulanten).

---

## Genauigkeits-Doktrin (gilt für ALLES)

1. **Byte-exakt schlägt gemessen schlägt geschätzt.** Prioritätskette je Wert:
   Text-Layer (Maßketten, Raum-Stempel F/U/H, STUK/FPH, Legende) → Vektor-Geometrie
   (kalibriert, pt→m) → Vision (nur Semantik: Ansichten, Farben, Symbole) → Heuristik
   (immer als „Annahme" gekennzeichnet).
2. **Der Plan validiert sich selbst.** Jeder Raum-Stempel trägt F+U byte-exakt →
   rekonstruierte Geometrie wird DAGEGEN verifiziert (grün = bewiesen, gelb = prüfen).
   Kern-Metrik: **verifizierte Räume / alle Räume** (scripts/test_raumverifikation.py).
3. **Jede Zahl ist am Plan belegbar.** Materialposition ↔ Wände/Räume/Öffnungen am
   Plan gekoppelt (klicken → aufleuchten). Keine Zahl ohne Herkunft.
4. **Ehrliche Konfidenz.** Unsicheres wird gestrichelt/gelb/als Annahme gezeigt —
   niemals falsche Präzision. Maßstab unsicher → Ansicht ja, Mengen-Export gesperrt.
5. **Guard-Tests gegen echte Polier-Listen.** Angerer 13/13 Positionen
   (test_materialliste_angerer) ist die rote Linie — keine Änderung darf sie brechen.
   Jede Verbesserung braucht einen messbaren Harness VOR dem Einbau.
6. **Empirie schlägt Theorie.** Jede Idee wird am echten Plan gemessen (Bild rendern +
   Zahlen), Verschlechterungen werden verworfen und dokumentiert.

---

## Säule A — Lesen für ALLE Pläne (Zuverlässigkeit)

| Status | Item |
|---|---|
| ✅ | Maßstab-Kalibrierung: Ketten-Regression + Label-Fallback („1:50" → pt/m) |
| ✅ | Grundriss-Box: Raum-Label-Cluster + Wand-Kontur-Fallback (Pläne ohne Raumnamen) |
| ✅ | Wand-Poché farb-gefiltert (Neubau rot/orange; monochromer Fallback) — 85% Rauschen raus |
| ✅ | Möbel-Aussortierung (Schraffur-Verankerung) |
| ✅ | **Multi-Geschoss**: alle Pläne des Projekts als Tabs in der Planansicht (lazy je Tab, Korrekturen pro Plan) |
| 🔜 | Raum-Verifikation Runde 3: Gang-/Zonen-Zuordnung, Tür↔Raum-Topologie → Quote hoch |
| ✅ | **Plan-Korpus + Abdeckungs-Metrik** (`scripts/test_korpus.py`): 6 echte Pläne, je Plan Kalibrierung/Ansicht/Wände/Öffnungen/Räume✓. Stand: **alle 4 Grundriss-Pläne ✓** (die 2 ✗ sind Schnitt-Blätter — ehrlich ausgeschlossen statt falsches Bild). Korpus wächst mit jedem neuen Kunden-Plan. |
| ⬜ | **Raster-/Scan-Fallback** (Pläne ohne Vektoren): Vision-gestützt, ehrlich als „gescannt — reduzierte Genauigkeit" gekennzeichnet |
| ⬜ | Mehrseitige Pläne / mehrere Grundrisse pro Blatt sauber getrennt (EG/OG auf einem A0) |

## Säule B — ÖNORM-Konformität (zitierfähig)

| Status | Item |
|---|---|
| ✅ | Öffnungs-Regel B 2204:2019 §5.5.1.3 (≤4,0 m² übermessen, >4,0 Abzug + Laibung) |
| ✅ | Zitate konsolidiert auf **B 2204** (ersetzt seit 2019: B 2206 Mauerwerk, B 2210 Putz, B 2211 Beton, B 2212 Trockenbau, B 2259 WDVS); Estrich bleibt B 2232 |
| ✅ | „in Anlehnung an" (ehrlich, solange nicht 100% wortgleich) |
| 🔜 | Ausmaßregeln je Gewerk als in-App-Referenz (Tooltip an jeder Position: welche Regel, welcher Paragraph) |
| ⬜ | **ONLV-Export (ÖNORM A 2063)**: das Austauschformat der österreichischen AVA-Welt (ABK, Auer, Nevaris …). Massen → LV-Positionen (LB-Hochbau) → .onlv. DER Integrations-Hebel für Baubetriebe. |
| ⬜ | LB-Hochbau-Positionsnummern an den Gewerke-Positionen (Kalkulanten-Anschluss) |

## Säule C — Nachvollziehbarkeit am Plan (alles eingezeichnet)

| Status | Item |
|---|---|
| ✅ | Planansicht führt die Auswertung an (automatisch, 1:1-Plan als Basis) |
| ✅ | Wände farbcodiert + Längen-Labels (Maßketten-Snap: Plan-Zahl gewinnt) |
| ✅ | Fenster/Türen als Marker (byte-exakt aus STUK/FPH) |
| ✅ | Räume grün ✓ / gelb ? (Selbst-Verifikation gegen F/U-Stempel) |
| ✅ | Korrigierbar: Wand entfernen/Stärke/hinzufügen, Öffnung entfernen — persistiert |
| ✅ | Materialliste ↔ Plan gekoppelt (HLZ-Position → Wände leuchten) |
| 🔜 | Kopplung ausbauen: JEDE Position (Decke, Bodenplatte, Estrich je Raum, Frostschürze) zeigt ihre Fläche/Kante am Plan |
| ✅ | Prüfbares **Aufmaßblatt** (PDF): Plan mit eingezeichneten Wänden/Maßen/Öffnungen/Raum-Status + Legende + Summen (`api/aufmassblatt.py`, Button im Kopf, `test_aufmassblatt.py`) |

## Säule D — Workflow & Design (Umbau)

Ziel-Workflow (Stepper statt Scroll-Wüste):
**1. Pläne hochladen → 2. Plan prüfen (Planansicht: grün/gelb, korrigieren) → 3. Massen & Material (ÖNORM-Buchform + Bestell-Liste) → 4. Export (CSV/Excel/ONLV/Aufmaßblatt)**

| Status | Item |
|---|---|
| ✅ | Planansicht als Zentrum; Kalibrier-Komplexität entfernt; Stellschrauben |
| ✅ | Stepper-Navigation: 1 Pläne → 2 Plan prüfen (Default) → 3 Massen & Material → 4 Export & Fragen |
| ✅ | Zielgruppen-Presets in Schritt 3: Rohbau/Baumeister (Mauerwerk+Beton), Ausbau (Putz·Estrich·Maler), Kalkulant (alle Gewerke, LV-Form offen) — gemerkt via localStorage |
| ⬜ | Design-Überarbeitung auf die 4 Schritte (klare Hierarchie, weniger gleichzeitig sichtbar) |

## Säule E — Zielgruppen & Markt

- **Baubetriebe/Baumeister (Rohbau)**: Bestell-Materialliste + Mauerwerks-Massen — Kernprodukt, validiert.
- **Ausbau-Subunternehmer** (Verputzer, Estrichleger, Maler): je Gewerk eigene Massen-Ansicht + Export.
- **Kalkulanten/AVA**: ÖNORM-LV + ONLV-Export.
- Später: Abrechnung (Aufmaß gegen Ist), Bauträger-Mengenprüfung.

---

## Kern-Metriken (werden bei jeder Änderung gemessen)

1. `test_materialliste_angerer` — 13/13 Positionen gegen echte Polier-Liste (rote Linie)
2. `test_raumverifikation` — n/9 Räume selbst-verifiziert (aktuell 1–2/9, Ziel: alle Innenräume)
3. Plan-Korpus-Abdeckung — n/6 Pläne mit funktionierender Planansicht (aktuell 4/6)
4. Alle Einheiten-Tests (Öffnungen, Verschnitt, Farben, Nachzeichnen, Kalibrier-Mechanik)

---

## UMBAU-ENTSCHEIDUNG (User, 2026-07-02): „Massen zuerst" — einen Schritt zurück

**Das Fundament der App wird die VOLLSTÄNDIGE Massenermittlung, Position für Position —
das Material ist nur eine abgeleitete Sicht daraus.** Reihenfolge des Rechenwegs (und
des Workflows): Geometrie (Planansicht, verifiziert) → **komplettes Aufmaß** → Gewerke-
Massen → Material/Bestellung → Export.

Das komplette Aufmaß heißt EINZELN aufgelistet und prüfbar:
- **jede Wand** einzeln (Stärke · Länge · Höhe · brutto − Öffnungen = netto) — wie der Polier im Excel
- **jede Öffnung** einzeln mit ÖNORM-Regel: ≤4,0 m² übermessen (KEINE Laibung) · >4,0 m²
  Abzug **+ Laibungszeile** (2·H+B, mit Sohlbank bei Parapet) × Laibungstiefe — sichtbar,
  welche Laibungen drin sind und warum
- **jeder Raum** einzeln (Boden = F byte-exakt · Decke · Wandabwicklung U×H · Sockel)

| Status | Item |
|---|---|
| ✅ | Öffnungs-Aufmaß-Tabelle: je Öffnung Raum·Typ·B×H·Fläche·Regel·Laibung m² mit Rechenweg |
| ✅ | Wand-Aufmaß-Tabelle aus der Planansicht (je Wand einzeln, ✓ byte-exakt, LIVE mit Korrekturen) + Raum-Aufmaß (je Raum: Boden ✓/Decke/Abwicklung/Sockel) |
| ✅ | Workflow-Schritt 3 heißt „Aufmaß & Massen" (drei Einzel-Tabellen: Öffnungen·Wände·Räume); ⬜ Rest: Wand↔Öffnung-Zuordnung je Einzelwand, Raum-Stempel-Format WM-Büro |
