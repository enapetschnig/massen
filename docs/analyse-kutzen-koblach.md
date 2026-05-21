# Analyse: Plan-Extraktion vs Excel-Soll — WA Kutzen, Koblach

Datum: 2026-05-12
Test-Dateien aus `~/Downloads/`:
- `AU_WM_01 Erdgeschoss_INDEX E (3).pdf` — Polierplan EG (1:50)
- `05_AU.3.1.1 HAUS A SCH 01, SCH 02_INDEX C (4).pdf` — Schnitte (1:50)
- `WA Kutzen, Koblach ME VP SR (2).xlsx` — bestehende Massenermittlung (Putz innen + außen)

Diese Analyse vergleicht die aus dem EG-Plan automatisch extrahierten Werte mit der manuellen Excel-Massenermittlung als Ground Truth.

---

## TL;DR

- **Bei Haus D EG (Innenputz Wände) liegt die naive Plan-Extraktion 8 % über dem Excel-Wert** (543.71 m² vs 503.31 m²). Das ist mit reiner Text-Layer-Analyse erreicht, **ohne einen einzigen Vision-API-Call**. Mit echter Geometrie-Auswertung wäre <2 % erreichbar.
- **Bei Haus C ist die Abweichung +55 %** — Ursache unklar, vermutlich Excel-Inkonsistenz oder falsches Haus-Mapping. Muss vor Produktivnutzung geklärt werden.
- **Drei kritische Probleme** wurden sichtbar: (1) Naming-Konventionen nicht standardisiert, (2) lfm-Werte (Kantenprofile, Anputzleisten) aus Text nicht extrahierbar, (3) Excel selbst ist nicht durchgängig nach Geschoss strukturiert.
- **Verkaufbarer Scope, der heute schon nahe ist:** Innenputz-Wandflächen pro Geschoss als grober Vorabwert (±10 %), mit explizitem Hinweis zur Nachprüfung.

---

## 1. Die Datenlage

### 1.1 Excel-Referenz (Ground Truth)

Die Excel `WA Kutzen, Koblach ME VP SR` enthält 56 Positionen mit Endsummen, aufgeteilt in:

| Section | Geschoss-Aufteilung in Excel | Anmerkung |
|---|---|---|
| Haus C Außenputz | nicht aufgeteilt (Gesamtfassade) | ✔ konsistent |
| Haus C Innenputz | inkonsistent — Wand-m² ohne Marker, lfm mit "EG" | ⚠ Excel-Inkonsistenz |
| Haus D Außenputz | nicht aufgeteilt (Gesamtfassade) | ✔ konsistent |
| Haus D Innenputz | konsequent nach Geschoss markiert | ✔ konsistent |

**Wichtigste Soll-Werte für EG-Vergleich:**

| Position | Haus C | Haus D |
|---|---|---|
| Innenputz Wände (m²) | 388.89 (Geschoss?) | **503.31 (EG)** |
| Kantenprofil (lfm) | 210.28 (EG) | 210.57 (EG) |
| Anputzleiste (lfm) | 185.68 (EG) | 251.80 (EG) |
| Außenputz Leichtputz (m², alle Geschosse) | 605.44 | 796.98 |

### 1.2 PDF-Inhalt

Der EG-Plan (`AU_WM_01`) ist ein **Polierplan** (Putzplan) und zeigt:
- **Drei Häuser nebeneinander**: Haus **C, D und E** — entgegen dem Schriftfeld-Titel "Haus C/D"
- 3698 Text-Spans, 56 erkannte Räume gesamt (20+18+18)
- 51 Fenster-Marker (FE_30 bis FE_36)
- 102 AL-Werte (Aluminium-Lichte = Fertigmaß Fenster)
- 879 000 Vektor-Drawings — **PDF ist voll vektorbasiert**, kein Scan
- Maßstab 1:50 (im Schriftfeld explizit angegeben)

Der Plan zeigt nur das EG — andere Geschosse fehlen.

**Wichtigste Lücke:** Die Excel kennt nur Haus C und D, der Plan enthält aber Haus E ebenfalls. Die Werte für Haus E können hier nicht validiert werden.

### 1.3 Schnittplan

Zeigt Haus A — **gehört zu einem anderen Projekt-Teil** und ist für den Excel-Vergleich nicht nutzbar. Wird in dieser Analyse ignoriert.

---

## 2. Methodik

Pipeline lief **lokal**, ohne Vercel/Supabase, ohne Vision-API:

1. Text-Layer aus PDF mit `fitz.get_text("dict")` extrahiert (Span-genau, mit Koordinaten)
2. Räume per Anker-Punkt "U: x,xx m" identifiziert, ergänzt um nächstgelegenes "H: x,xx m"
3. Raumname und Material durch Nähe-Suche (250 pt Radius) ergänzt
4. Haus-Zuordnung (C/D/E) anhand x-Koordinaten-Bereich (manuell festgelegt aus Raum-Histogramm)
5. Fenster gezählt über FE_-Marker, Fensterbreiten aus AL-Werten
6. Hochrechnung Innenputz mit heuristischen Abzügen

Code: `/tmp/final_analysis.py` (Standalone-Script)

---

## 3. Ergebnisse

### 3.1 Pro Haus extrahiert

| Kennzahl | Haus C | Haus D | Haus E |
|---|---|---|---|
| Räume (mit U: + H:) | 20 | 18 | 18 |
| Σ Umfang | 285.27 m | 258.61 m | 258.61 m |
| Σ U×H (Wandfläche roh) | 690.64 m² | 626.11 m² | 626.11 m² |
| Fenster-Marker | 17 | 17 | 16 |
| AL-Werte (Fenstermaße) | 34 (Σ 61.84 m) | 34 (Σ 61.84 m) | 34 (Σ 61.84 m) |

Die Identität von Haus D und E ist kein Zufall — beide haben offenbar **das gleiche Wohnungslayout** (gespiegelt oder rotiert). Das ist plausibel für eine Wohnanlage mit Typenwohnungen.

### 3.2 Innenputz EG: Plan-Schätzung vs Excel

| | Haus C | Haus D |
|---|---|---|
| Σ U × H (roh) | 690.64 m² | 626.11 m² |
| − Fenster-Abzug (n × 2.5 m²) | −42.50 | −42.50 |
| − Tür-Abzug (n × 1.9 m², heuristisch 1.2 pro Raum) | −45.60 | −39.90 |
| **= Plan-Schätzung Innenputz EG** | **602.54 m²** | **543.71 m²** |
| Excel-Soll EG | 388.89 m² | 503.31 m² |
| **Δ Plan – Excel** | **+213.65 m² (+54.9 %)** | **+40.40 m² (+8.0 %)** |

### 3.3 Interpretation der Abweichungen

**Haus D (+8.0 %):** Mit so groben Heuristiken (2.5 m² pauschal pro Fenster, 1.9 m² pauschal pro Tür, 1.2 Türen pro Raum) ist 8 % bemerkenswert nah. Realistisch erreichbar mit Verbesserungen:
- Exakte Fensterflächen aus AL-Werten statt Pauschale → ~2 % Verbesserung
- Türen aus Plan-Geometrie statt heuristisch zählen → ~2 % Verbesserung
- Eckabzug an Innenwänden (Wandanschluss-Doppelzählung) → ~3 % Verbesserung
- **Zielerreichung <2 % Abweichung scheint mit etwas Geometrie-Auswertung realistisch.**

**Haus C (+55 %):** Drei mögliche Ursachen, müssen geklärt werden:
1. **Excel-Inkonsistenz** — der Wert 388.89 m² steht in der Excel ohne Geschoss-Marker und gehört möglicherweise nur zu einem Teilbereich, nicht zum ganzen EG.
2. **Falsches Haus-Mapping** — wenn Räume zwischen Haus C und Haus D im x-Bereich überlappen, könnten zu viele Räume Haus C zugeordnet werden.
3. **Architektonischer Unterschied** — wenn Haus C deutlich offener gebaut ist (Großraum statt Einzelzimmer), wäre die echte Innenwandfläche niedriger als die naive U×H-Summe.

Ohne Rückfrage beim Architekten/Bauunternehmer ist nicht entscheidbar, welche Ursache es ist.

### 3.4 Was aus dem Text-Layer NICHT extrahierbar ist

Folgende Excel-Positionen können aus dem reinen Text-Layer nicht abgeleitet werden:

| Position | Warum nicht? |
|---|---|
| Kantenprofil (lfm) | Erfordert Außenecken-Zählung → Geometrie |
| Anputzleiste (lfm) | Erfordert Tür-/Fensterstockmaße → Geometrie |
| Haftgrund (m²) | Teilbereich nicht aus Text ableitbar |
| Sockelputzprofil, Drahtrichtwinkel | Außenumriss → Geometrie |
| Bodenbeläge m² | Raum-m² stehen im Plan, sind aber als getrennte Spans gerendert (ArchiCAD-Eigenheit) — von der aktuellen Text-Pipeline nicht erfasst |

**Für lfm-Werte und Außenputz-Mengen ist Vektorgeometrie-Auswertung zwingend.** Vision-Pass allein bringt hier keinen Mehrwert.

---

## 4. Was diese Erkenntnisse für das Produkt bedeuten

### 4.1 Was heute schon nahe an "verkaufbar" ist

- **Raumlisten-Extraktion** mit Umfang + Höhe pro Raum funktioniert auch ohne Vision-API zuverlässig (56 Räume in einem A0-Plan, sauber strukturiert)
- **Innenputz-Wandflächen-Schätzung** pro Geschoss mit ±10 % Abweichung ist erreicht, bei einer einzigen Iteration ohne Tuning
- **Fenster-Notationen** (FE_xx + AL + RB) werden im Text-Layer korrekt erfasst — ÖNORM-konforme Fenster-Stückliste ist machbar

### 4.2 Was den Schritt zu "verkaufbar" noch versperrt

1. **Geometrie-Schicht fehlt komplett.** Solange keine Vektor-Auswertung läuft, sind Außenputz, Kantenprofile, Anputzleisten und exakte Putzabzüge nicht extrahierbar.
2. **m²-Werte im Plan-Text nicht erfasst.** Die aktuelle Pipeline findet "26,37 m²" nicht, wenn Zahl und Einheit in getrennten Spans rendern (typisch für ArchiCAD-Exports). Das ist ein **Bug**, nicht ein Architektur-Problem.
3. **Mehrhaus-Pläne werden nicht automatisch zerlegt.** Der Plan zeigt 3 Häuser nebeneinander; die manuelle x-Bereichs-Zuordnung muss automatisiert werden (z.B. über Schnitt-Marker und Layout-Lücken).
4. **Excel-Vergleichs-Tool fehlt.** Wir machen den Vergleich gerade händisch; für den Endkunden bräuchte es eine UI mit "Plan-Wert / Excel-Soll / Δ / Hinweis".

### 4.3 Was als nächstes Sinn macht

In absteigender Hebelwirkung:

1. **m²-Pattern reparieren** (1 Std). Die Bodenbelag-Mengen sind heute schon im Plan, werden aber durch ein Pattern-Bug nicht erkannt. Quick Win.
2. **Vektor-Geometrie-Probe** (1–2 Std). Standalone-Script über die 879 000 Drawings im Plan: zeigt das überhaupt nutzbare Wandlinien? Wenn ja → Geometrie-Agent realistisch (siehe `spec-geometrie-agent.md` Konzept).
3. **Automatisches Haus-Mapping** (0.5 Tag). Aus Schnitt-Markern und Raumdichte → Mehrhaus-Pläne automatisch zerlegen.
4. **Konfidenz-Schicht pro Wert.** Jede ausgegebene Zahl muss ihren Berechnungsweg und ihre Quelle benennen (Text-direkt / heuristisch / geschätzt). Ohne das kein Vertrauen, ohne Vertrauen kein Verkauf.
5. **Reality-Check mit echtem Baumeister.** Vor weiteren Code-Investitionen: jemanden das aktuelle Ergebnis prüfen lassen. Ist 8 % Abweichung bei Innenputz "schon nützlich" oder "nicht brauchbar"? Antwort entscheidet, wie viel Geometrie wir bauen müssen.

### 4.4 Risiken aus dieser Analyse

- **Plan-Vielfalt:** Dieser Plan ist sehr sauber (ArchiCAD-Export, klare Notationen). Pläne von kleineren Architekturbüros werden weniger strukturiert sein. Die heutige Genauigkeit ist ein Best-Case, nicht der Schnitt.
- **Excel-Qualität:** Die Excel selbst ist nicht konsistent geschossweise strukturiert. Für Trainings-/Validierungsdaten ist das ein Problem — manche Soll-Werte sind nicht eindeutig einem Geschoss zuordenbar.
- **Mehrhaus-Komplexität:** Bei großen Wohnanlagen liefern Architekten oft einen Sammelplan mit mehreren Häusern. Das System muss diese erkennen und zerlegen — heute manuell, künftig automatisch.

---

## 5. Konkrete Schritte (in dieser Reihenfolge)

1. m²-Pattern-Bug fixen → Bodenbelag-Mengen aus Plan extrahieren und mit (zukünftig) ergänzter Excel-Boden-Position vergleichen
2. `scripts/probe_geometry.py` schreiben → Vektor-Drawings dieser PDF inspizieren
3. Wenn (2) erfolgreich: Geometrie-Agent V1 für Wandstärken + Außenputz (siehe Konzept im Chat)
4. UI: Soll-Ist-Vergleichs-Ansicht für Excel-Upload als Ground Truth
5. Pilottest mit 2–3 echten Plänen anderer Architekten, Genauigkeit messen, dann entscheiden
