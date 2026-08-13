# Arbeitsplan nach Suite-Lauf (2026-08-13)

## A. Erkennung — Korpus-Befund (alle 9 hochgeladenen Pläne gemessen)

| Plan | Räume | Umrisse | verifiziert | Ø-Fehler |
|---|---|---|---|---|
| Garage-Einreichplan | 4 | 4/4 | 3 | 1,6 % |
| 03 EG | 10 | 10/10 | 6 | 1,8 % |
| Angerer | 10 | 10/10 | 6 | 2,9 % |
| AP.01 (Polierplan) | 9 | 9/9 | 8 | 4,3 % |
| Sadiku Lageplan | 4 | 4/4 | 4 | 1,6 % |
| **Sadiku Grundriss** | **25** | 25/25 | 9 | **5,0 % (max 15,5)** |
| 2510_einreichung | **0 (Scan!)** | — | — | Vision-Route: 21 Räume ✓ |

Priorisierte Fixes (alle Zell-Stufe, Mechanismus per Grid-Dump belegt):
1. **Sadiku Speis +19 % Zellen**: leckt in die Treppenzone — Stufen-
   Schraffur ist keine Wand. Ansatz: Treppen-Schraffur (Zickzack-Muster)
   als Sperrzone rastern, wie Poché. Messbar am Korpus (Speis, Bad WC).
2. **Bad WC +16,7 %, Eltern Zimmer +13,9 %**: gleiche Klasse (kleine
   Räume, un-bewandete Grenzen zu Nische/Nachbar).
3. **WK-Glasfront-Band** (Angerer): Innere-Glaslinie-Snap in
   raum_kontur_exakt — Deckel erlaubt −10 cm, greift dort nicht.
4. **Scan-Vorschläge**: Vision-Räume (21 Stück am 2510) haben keine
   Geometrie → keine Mess-Vorschläge. Ehrlich lösen: Vorschlag ohne
   Geometrie = Wert + Name, am Plan nicht einzeichenbar, im Protokoll
   mit Quelle "Vision (Scan)" — oder Erker: Vision-BBox als Rechteck.

## B. UI-Komplettumbau (Nutzer: "kannst das komplett verändern")

Designsprache bleibt „Technisches Reißbrett" (eigenständig, nicht
digiplan) — aber die Seitenstruktur wird App-artig:

1. **Projekt-Seite = 5 echte Screens** statt einer langen Scroll-Seite:
   der Stepper schaltet Vollbild-Ansichten (heute: Ausblenden per
   wf-hidden, Rest scrollt). Schritt 2 (Plan) füllt den Viewport.
2. **Höhen-Abfragen** (Volumen/Treppe/Dach/Wand) raus aus window.prompt,
   rein ins Eigenschaften-Panel (Eingabefeld + Übernehmen).
3. **Dashboard**: Karten mit Plan-Thumbnail (basis_png klein), Status-
   Chips (analysiert / N Messungen / Protokoll fertig), klarer CTA.
4. **Leerzustände** als Anleitungen (was ist der nächste Schritt).
5. **Zuordnung**: Drag oder Klick-Klick statt nur Selects; Kreuztabelle
   bleibt Anzeige.

Reihenfolge: B2 (klein) → A1/A2 (Messlauf) → B1 (groß) → B3–B5 → A3/A4.
