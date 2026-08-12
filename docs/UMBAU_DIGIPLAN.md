# Umbau zum Aufmaß-Werkzeug (Vorbild digiplan)

**Stand 2026-08-10. Verbindliche Richtung nach Nutzer-Ansage:** „die Erkennung
ist immer noch nicht so gut — legen wir den Fokus darauf, das Ganze so wie
geplant zu machen, so wie digiplan."

---

## 1. Was digiplan ist (Recherche)

digiplan (Bausoft, AT) ist der Marktführer für Aufmaß im deutschsprachigen
Raum. Recherchiert auf digi-plan.at und bausoft.at:

- **Vier Modi:** Papierplan (digipen), **PDF-Plan (Maus am PC)**, Foto
  (Fassaden), App (vor Ort).
- **22 spezialisierte Werkzeuge**, modular gekauft: Flächen (m²), Längen
  (lfm), Stück, Treppe (rechnet Stiegenuntersicht + Volumen), Fundament/
  Beton-Volumen, Dach (Grat, Kehle, Ortgang, Traufe), unregelmäßige Formen,
  **Abzüge**, **Bauteile**, Geschossfläche.
- **Ausgabe immer dreiteilig:** Aufmaß-Protokoll **mit Formeln**, visueller
  **Aufmaß-Plan** (die gemessenen Flächen eingezeichnet), digitale
  Abrechnungspläne. Als Excel oder PDF, der Rechnung beilegbar.
- **Schnittstellen:** GAEB (DE), **ÖNORM (AT)** in die Angebots-/
  Abrechnungssoftware.
- Werbeversprechen: „80 % schneller, 100 % fehlerfrei", 14 Tage früherer
  Zahlungseingang durch bessere Dokumentation.

### Die entscheidende Erkenntnis

**digiplan erkennt nichts.** Der Mensch klickt die Punkte, die Software
rechnet exakt und dokumentiert lückenlos. „100 % fehlerfrei" heißt: kein
Rechenfehler, kein Übertragungsfehler — nicht „die KI hat es erkannt".

Damit ist die Erkennungsqualität **kein Produkt-Blocker**. Sie ist ein
Beschleuniger. Unser Vorteil gegenüber digiplan bleibt bestehen und wird
sogar größer, wenn wir das Werkzeug drumherum haben:

| | digiplan | wir (Ziel) |
|---|---|---|
| Messen | Mensch klickt alles | Mensch klickt — **KI hat vorbelegt** |
| Maßstab | Mensch setzt | byte-exakt aus Maßketten gelesen |
| Fluchten/Ecken | freies Klicken | **Snapping auf erkannte Wandlinien** |
| Räume | Mensch umfährt jeden | 121 Räume vorgeschlagen, Mensch prüft |
| Protokoll | Formeln | Formeln **+ Klick springt zum Bauteil** |
| Norm | Regel je Position | ÖNORM-Regelwerk eingebaut (LG 07–46) |

---

## 2. Was wir heute haben (Inventar 2026-08-10)

### Stark
- **Byte-exaktes Lesen:** Maßstab, Raumstempel (F/U/H), Öffnungen (STUK/FPH/
  RPH), Legende, Höhenkoten, Farb-Legende, Maßketten.
- **Geometrie:** Wanderkennung (Poché-verankert), Raum-Rekonstruktion mit
  Beweisstufen, 121 Räume auf 4 Plänen, Angerer-Flächenfehler 3,0 %.
- **ÖNORM-Mengenlogik:** `massen_logic.py` mit `LVPosition`, 6 Gewerken,
  Übermessungsregeln, Abzügen, Leibungen, `AUFMASS_REGELN`-Katalog,
  `aufmass_matrix` (Kreuztabelle Räume × Positionen).
- **Exporte:** CSV, XLSX (Blatt je Gewerk), **ONLV (ÖNORM A 2063, XSD-
  validiert)**, Aufmaßblatt-PDF, Raumliste PDF/XLSX. **ONLV-Import existiert
  serverseitig** (`/api/lv-import`), wird vom Frontend nicht genutzt.
- **Planansicht als Zeichentool** (seit 2026-08-08): Werkzeugleiste,
  Eigenschaften-Panel, Wand-Klick, Mehrfachauswahl, Dicke-Eingabe,
  Rechteck-Werkzeug, Messen, Maßstab-Kalibrierung, Raum-Polygon-Editor.
- **78 Wächter** in der Suite, Kalibrierungs-Moat, Firmen-Accounts.

### Die Lücke — und sie ist strukturell
**Es gibt keine MESSUNG als Objekt.** Heute existieren nur:
- `elemente` (Räume/Fenster/Türen, von der KI erzeugt) und
- `LVPosition` (im Speicher berechnet, nirgends gespeichert).

Was fehlt, ist die Schicht dazwischen, die digiplan ausmacht:

| Fehlt | Folge heute |
|---|---|
| **Messung als Entität** (Geometrie + Typ + Formel + Wert) | Der Nutzer kann nichts messen, was die KI nicht erkannt hat |
| **Werkzeugkasten** (Fläche/Länge/Stück/Abzug/Bauteil/Treppe/Dach) | Nur „Messen" als flüchtige Hilfslinie, ohne Speichern |
| **Positionen als Entität** (CRUD, Vorlagen, Import) | Positionen sind im Code fest verdrahtet |
| **Zuordnung Messung → Position** | Kreuztabelle ist Anzeige, nicht bedienbar |
| **Aufmaßprotokoll aus Messungen** | Protokoll kommt aus KI-Mengen, nicht aus Messungen |
| **Persistenz von all dem** | Alles hängt an `agent_log`-JSON eines Plans |

---

## 3. Zielarchitektur

### 3.1 Datenmodell (neu)

```
projekte
└── plaene (PDF, Seiten)
    ├── elemente        [KI-Lesung: Räume/Fenster/Türen]   — bleibt
    └── messungen       [NEU: jede einzelne Messung]
positionen             [NEU: LV-Positionen je Projekt/Firma]
positionsvorlagen      [NEU: Positionssätze je Gewerk/Firma]
```

**`messungen`** — das Herzstück:
```
id, plan_id, seite, projekt_id
typ            flaeche | laenge | stueck | volumen | abzug | bauteil
geometrie      jsonb  {punkte:[[x,y]…], form:polygon|polyline|punkt|rechteck}
bezeichnung    "Wohnraum Küche Boden"
formel         "5,84 × 4,77 − 1,20 × 0,90"   (menschenlesbar, prüfbar)
wert, einheit  31,12 | m²
position_id    → positionen.id   (nullable = noch nicht zugeordnet)
quelle         ki | mensch | ki_bestaetigt
raum_ref       optionaler Raum-Anker (für die Kreuztabelle)
erstellt_am, geaendert_am
```

**`positionen`**:
```
id, projekt_id | firma_id (Vorlage), nr, bezeichnung, langtext,
einheit, regel_id (→ AUFMASS_REGELN), verschnitt_pct,
quelle: eigen | onlv_import | katalog | ki, lg (Leistungsgruppe), sort
```

### 3.2 Der Ablauf (5 Schritte, wie geplant)

1. **Pläne** — Upload, Maßstab prüfen (byte-exakt vorbelegt), Seiten wählen.
2. **Plan & Messen** — das Zeichentool. KI-Vorschläge liegen als Messungen
   vor (grau/gestrichelt = Vorschlag), der Nutzer bestätigt per Klick oder
   misst selbst mit dem Werkzeugkasten. **Jede Messung ist ein Objekt.**
3. **Positionen** — LV anlegen/importieren (ONLV/GAEB), Vorlagen je Gewerk,
   je Position eine Pflicht-Aufmaßregel, Verschnitt-Default.
4. **Zuordnung** — Messungen den Positionen zuweisen; regelbasiert
   vorbelegt („alle Boden-Messungen → Pos. 1.2 Estrich"), manuell
   übersteuerbar. Kreuztabelle wird bedienbar.
5. **Export** — Aufmaßprotokoll (Formeln), Aufmaßplan (eingezeichnet),
   ONLV/GAEB, Excel.

---

## 4. Umbau in Etappen

Jede Etappe ist für sich lauffähig und wird gemessen + mit Wächter gesichert.

### E1 — Fundament: Messung als Objekt
- Tabelle `messungen` + `positionen` (SQL in `db/`)
- API: `GET/POST/PATCH/DELETE /api/messungen`, `/api/positionen`
- Frontend: Messungen laden/speichern statt flüchtiger `_nzMeasPts`
- **Erst danach hat alles Weitere einen Platz zum Hinschreiben.**

### E2 — Werkzeugkasten im Plan
- Werkzeuge: Fläche (Polygon), Rechteck, Länge (Polylinie), Stück (Punkt),
  Abzug (negativ, an Fläche gebunden)
- **Snapping** auf erkannte Wandlinien/Ecken/Maßketten-Fluchten (unser
  Alleinstellungsmerkmal — digiplan hat das nicht)
- Live-Zahl beim Zeichnen, Objekt anklickbar/editierbar/löschbar
- Nummerierung am Plan (M1, M2 …) → Referenz im Protokoll

### E3 — KI-Vorschläge als Messungen
- Die Erkennung erzeugt Messungen mit `quelle=ki`, Status Vorschlag
- „Alle bestätigen" / einzeln bestätigen / verwerfen
- **Damit ist die Erkennungsqualität entkoppelt:** schlechte Erkennung =
  mehr Handarbeit, nicht falsche Mengen.

### E4 — Positionen-Verwaltung (Schritt 3 neu)
- CRUD + Positionssätze als Vorlage (je Gewerk, je Firma)
- ONLV-Import ans Frontend anschließen (Backend existiert)
- Unsere ÖNORM-Positionen als mitgelieferter Katalog
- Pflicht-Aufmaßregel, Sperre + Badge „Regel fehlt"

### E5 — Zuordnung (Schritt 4 neu)
- Messung → Position per Klick/Drag, Mehrfachauswahl
- Regelbasierte Vorbelegung, Badge „automatisch"
- Kreuztabelle editierbar

### E6 — Aufmaßprotokoll + Aufmaßplan
- Protokoll je Position: jede Messung mit Formel und Plan-Nummer
- Aufmaßplan: Plan mit allen Messungen + Nummern, PDF-Export
- Beides aus `messungen` erzeugt, nicht aus KI-Mengen

### E7 — UI-Neubau der übrigen Bereiche
- Dashboard, Übersicht, Positionen, Zuordnung, Export im Zeichentool-Look
- `upload.js` (4674 Zeilen) in Module zerlegen

### E8 — Spezialwerkzeuge (digiplan-Parität)
- Treppe (Untersicht + Volumen), Dach (Grat/Kehle/Ortgang/Traufe),
  Fundament/Beton-Volumen, Geschossfläche, Fassade/Gerüst

---

## 5. Was NICHT passiert

- **Die Erkennung wird nicht abgeschaltet.** Sie bleibt der Vorsprung —
  aber sie ist ab E3 nicht mehr der einzige Weg zur Menge.
- **Keine Feinjustierung der Erkennung** in diesen Etappen (offene Fälle:
  WK-Glasfront, IK_SNAP, Front-Segmente — dokumentiert, geparkt).
- **Kein Wächter wird gelockert.** Die 78 grünen Prüfungen bleiben die
  Grundlinie; jede Etappe läuft gegen sie.

---

## 6. Das Produktversprechen (Nutzer-Formulierung 2026-08-10)

> „Eine Mischung: die KI erkennt die Räume, und dann hat man eine Software,
> die das Gleiche wie digiplan kann, um es besser zu machen — und sie soll
> natürlich nicht gleich ausschauen wie digiplan."

Daraus folgen drei Festlegungen:

**a) KI = Vorlage, Werkzeug = Wahrheit.** Die Erkennung liefert den
Vorsprung (Räume, Wände, Öffnungen, Maßstab, Fluchten). Das Werkzeug macht
daraus die abrechenbare Menge. Kein Anspruch mehr, dass die KI allein
ausreicht — und damit auch kein Blocker mehr, wenn sie einen Raum verfehlt.

**b) Funktionsparität, keine Kopie.** Was digiplan kann, muss die App
können: Flächen, Längen, Stück, Abzüge, Bauteile, Sonderwerkzeuge,
Aufmaßprotokoll mit Formeln, Aufmaßplan, ÖNORM/GAEB-Export. Das ist der
Prüfmaßstab.

**c) Eigene Gestaltung — ausdrücklich NICHT wie digiplan.** Wir bleiben bei
der bestehenden Designsprache („Technisches Reißbrett": Ocker-Akzent,
Sora/Inter/IBM Plex Mono, ruhige Flächen, Ampel-Semantik gemessen/geschätzt)
und beim Drei-Zonen-Zeichentool (Werkzeuge links, Plan Mitte, Eigenschaften
rechts). Unsere Unterscheidungsmerkmale in der Oberfläche:

| digiplan | wir |
|---|---|
| Werkzeug wählen, dann klicken | KI-Vorschläge liegen schon da — bestätigen statt zeichnen |
| freies Klicken | **Snapping** auf byte-exakte Wandlinien und Maßketten-Fluchten |
| Maßstab setzen | Maßstab byte-exakt aus dem Plan gelesen |
| Zahlen im Protokoll | jede Zahl **klickbar zurück aufs Bauteil im Plan** |
| Werkzeuge modular gekauft | alle Werkzeuge inklusive, Gewerke-Auswahl statt Lizenz |
| Desktop-Installation | Browser, nichts zu installieren |
