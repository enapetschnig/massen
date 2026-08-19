# Manueller Modus + Editor-Parität (Design, 2026-08-19)

**Nutzer-Auftrag:** „Auch die Möglichkeit haben, dass man NICHT mit KI die
Räume erkennt und einfach sowas wie digiplan hat. Aber auch wichtig, dass
die KI-Planerkennung perfekt funktioniert und die Bedienung beim Editor
gleich gut wie bei digiplan ist."

## 1. Der Doppelmodus

Zwei Arbeitsweisen, EIN Werkzeug, EIN Datenmodell (messungen/positionen):

| | KI-Aufmaß (Standard) | Manuell (digiplan-Stil) |
|---|---|---|
| Upload | Auto-Analyse (Vision+Text, ~60 s) | nur Leicht-Pass (~3 s) |
| Planansicht | Vorschläge + Wände + Öffnungen | sauberer Plan, nur Werkzeuge |
| Maßstab | byte-exakt gelesen | byte-exakt gelesen (!) — sonst 2-Klick-Kalibrierung |
| Snapping | auf erkannte Wände/Ecken | Ortho-Snap (Shift) |
| Mengen | Vorschläge bestätigen + selbst messen | alles selbst messen |
| Abrechnung | identisch (Positionen → Zuordnung → Protokoll/Aufmaßplan/ÖNORM) | identisch |

Der Maßstab bleibt auch im manuellen Modus UNSER Vorsprung: digiplan lässt
den Nutzer kalibrieren, wir lesen ihn byte-exakt — die Kalibrierung ist nur
der Fallback (Scans).

### Umsetzung
- **DB**: `projekte.modus` text default 'ki' ('ki' | 'manuell'). Spalte live
  per Management-API angelegt (idempotent, additiv).
- **Backend**: `/api/plan-nachzeichnen` bekommt `leicht:true` → rendert nur
  basis_png + liest Maßstab/Box (überspringt Vektor-Wände, Watershed,
  Öffnungen — von ~40 s auf ~3 s). Kein eigener Endpoint: gleiche Route,
  gleicher Cache-Rahmen, ein Flag.
- **Upload-Fluss**: modus='manuell' → kein startAnalysis; Plan gilt sofort
  als „bereit". Wechsel jederzeit möglich: „KI-Analyse nachholen"-Knopf
  (ruft die normale Analyse, Vorschläge erscheinen) bzw. „Vorschläge
  entfernen" (existiert schon).
- **Dashboard-Modal**: Auswahl bei Projektanlage — zwei Karten:
  „⚡ KI-Aufmaß — die KI liest den Plan, du prüfst" /
  „✏️ Manuell — du misst selbst, wie gewohnt".
- **Frontend-Weiche**: leere waende/raeume/oeffnungen tragen bereits
  (Ebenen leer, Leerzustand zeigt im Manuell-Modus KEINEN
  Vorschlags-Hinweis, sondern „Miss mit F/R/L… — Maßstab steht").

## 2. Editor-Parität (die digiplan-Grundgesten)

Gemessen an dem, was ein Aufmaß-Editor können MUSS:

| Geste | Stand | Umsetzung |
|---|---|---|
| Rad-Zoom auf Cursor, Drag-Pan, Pinch | ✅ live | — |
| Esc bricht ab, Enter schließt | ✅ | — |
| **Backspace = letzter Punkt zurück** | ❌ | beim Zeichnen `_mwPts.pop()` |
| **Klick auf Startpunkt schließt Polygon** | ❌ | Toleranz ~12 px → abschließen |
| **Shift = Ortho** (waagrecht/senkrecht zwingen) | ❌ | Punkt auf Achse des Vorpunkts |
| **Entf löscht gewählte Messung** | ❌ | `_mwSel` → löschen |
| **Ctrl+Z macht letzte Messung rückgängig** | ❌ | Sitzungs-Stack: erstellen↔löschen |
| Eckpunkte gespeicherter Messungen ziehen | ❌ (nur Räume) | Folgerunde: Handles wie Raum-Editor, PATCH rechnet neu |
| Live-Wert beim Zeichnen | ✅ Hinweis | + Segmentlänge in Statusleiste |

Reihenfolge: die sechs ❌-Kurzgesten JETZT (eine Runde), Vertex-Drag als
Folgerunde (braucht die Handle-Mechanik der Messungen).

## 3. Nicht verhandelbar
- Beide Modi teilen Rechenkern & Protokoll — zwei Wege, EINE Wahrheit.
- Der Leicht-Pass erfindet nichts: ohne lesbaren Maßstab bleibt die
  Kalibrierungs-Pflicht sichtbar (Statusleiste „Maßstab: kalibrieren!").
- KI-Erkennung wird davon nicht berührt (Suite-Disziplin bleibt).
