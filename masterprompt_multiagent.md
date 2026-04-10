# MASTERPROMPT – KI-Massenermittlung mit Multi-Agent-System
**Für Claude Code (Terminal) | Web-App | Multi-User SaaS | 5 spezialisierte Agenten**

---

## ÜBERGEORDNETES ZIEL

Baue eine vollständige, produktionsreife Web-Applikation zur **KI-gestützten automatischen Massenermittlung aus österreichischen Bauplänen (PDF)**. Das System soll so präzise sein, dass ein Baubetrieb das Ergebnis direkt für die Kalkulation verwenden kann – ohne stundenlange manuelle Nacharbeit.

Das Herzstück ist ein **Multi-Agent-System mit 5 spezialisierten KI-Agenten**, koordiniert von einem Orchestrator. Die Agenten arbeiten unabhängig voneinander, kommunizieren über strukturierte JSON-Nachrichten und kontrollieren sich gegenseitig.

---

## TECH-STACK

- **Backend:** Python 3.11+ mit FastAPI
- **Frontend:** HTML + CSS + Vanilla JavaScript
- **Datenbank:** Supabase (PostgreSQL)
- **PDF-Verarbeitung:** pdfplumber (primär) + PyMuPDF (fitz) als zweite Schicht
- **KI:** Anthropic Claude API – Modell `claude-opus-4-5` für alle Agenten
- **Excel-Export:** openpyxl
- **Auth:** Supabase Auth
- **Task-Queue:** Python asyncio (für parallele Agent-Aufrufe wo möglich)
- **Deployment:** Docker + docker-compose

---

## DAS MULTI-AGENT-SYSTEM

### Architektur-Überblick

```
                        ┌─────────────────────┐
                        │    ORCHESTRATOR      │
                        │  (Koordination &     │
                        │   Entscheidung)      │
                        └──────────┬──────────┘
                                   │
          ┌────────────┬───────────┼───────────┬────────────┐
          ▼            ▼           ▼           ▼            ▼
    ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐
    │  AGENT 1 │ │  AGENT 2 │ │  AGENT 3 │ │  AGENT 4 │ │  AGENT 5 │
    │  Parser  │ │Geometrie │ │  Kalkul- │ │  Kritik- │ │  Lern-   │
    │  Agent   │ │  Agent   │ │  ator    │ │  Agent   │ │  Agent   │
    └──────────┘ └──────────┘ └──────────┘ └──────────┘ └──────────┘
```

Der Orchestrator ruft die Agenten in der Reihenfolge auf die er für richtig hält, kann Agenten mehrfach aufrufen, kann bei niedrigem Konfidenz-Score automatisch nachbessern lassen und entscheidet wann das Ergebnis gut genug ist.

---

## AGENT 1 – DER PARSER-AGENT

### Aufgabe
Rohe Textextraktion aus dem PDF. Dieser Agent kennt nur PDFs und Koordinaten – keine Baukenntnis.

### System-Prompt
```
Du bist ein hochspezialisierter PDF-Analyse-Agent für österreichische Baupläne.

DEINE EINZIGE AUFGABE: Extrahiere ALLE Textelemente aus dem PDF vollständig und strukturiert.

REGELN:
1. Extrahiere jeden einzelnen Text mit seinen genauen Koordinaten (x, y), Schriftgröße und Transformationsmatrix
2. Erkenne rotierten Text anhand der Matrix (matrix[1] != 0 oder matrix[2] != 0) und markiere ihn gesondert
3. Gruppiere räumlich nahe Textelemente (Abstand < 50pt) zu Text-Clustern
4. Gib für jeden Text-Cluster einen Konfidenz-Score (0-100%) an wie sicher du dir bist dass die Elemente zusammengehören
5. Trenne NIEMALS Fenster-Notationen auf – "FE_31 / RPH -24 / FPH 0 / AL120 / AL231 / RB130 / RB288" ist ein einziges Element
6. Markiere alle Zahlen die auf Maße hindeuten (gefolgt von m², m, cm, mm oder allein stehend im Kontext von Abmessungen)
7. Erkenne Maßstabsangaben (z.B. 1:100, 1:50) und gib sie zurück

AUSGABE: Immer als strukturiertes JSON, niemals als Fließtext.

AUSGABEFORMAT:
{
  "massstab": "1:100",
  "seite": 1,
  "text_cluster": [
    {
      "id": "cluster_001",
      "texte": ["Wohnküche", "Parkett", "26,37 m²", "U: 20,66 m", "H: 2,42 m"],
      "koordinaten": {"x_min": 245.3, "y_min": 412.1, "x_max": 312.7, "y_max": 489.5},
      "rotiert": false,
      "rotationswinkel": 0,
      "konfidenz": 94,
      "typ_hinweis": "raum"
    }
  ],
  "warnungen": ["Seite 3 enthält unleserliche Bereiche bei x:200-300"],
  "gesamt_konfidenz": 87
}
```

### Technische Implementierung
```python
# backend/agents/parser_agent.py

import pdfplumber
import fitz  # PyMuPDF als zweite Schicht
import json
import math
from anthropic import Anthropic

client = Anthropic()

def extract_with_pdfplumber(pdf_path: str) -> dict:
    """Schicht 1: pdfplumber für präzise Koordinaten"""
    results = []
    with pdfplumber.open(pdf_path) as pdf:
        for page_num, page in enumerate(pdf.pages):
            chars = page.chars
            words = page.extract_words(
                x_tolerance=3,
                y_tolerance=3,
                keep_blank_chars=False,
                use_text_flow=False,
                extra_attrs=["matrix", "size", "fontname"]
            )
            # Rotierten Text separat behandeln
            rotated = []
            normal = []
            for char in chars:
                matrix = char.get('matrix', (1,0,0,1,0,0))
                if abs(matrix[1]) > 0.1 or abs(matrix[2]) > 0.1:
                    rotated.append(char)
                else:
                    normal.append(char)
            results.append({
                "seite": page_num + 1,
                "normal_text": words,
                "rotierter_text": cluster_rotated_chars(rotated),
                "seitenbreite": page.width,
                "seitenhoehe": page.height
            })
    return results

def cluster_rotated_chars(chars: list) -> list:
    """Rotierten Text zu zusammenhängenden Strings zusammenführen"""
    if not chars:
        return []
    # Nach Position clustern (Abstand < 30pt = zusammengehörig)
    clusters = []
    current = [chars[0]]
    for char in chars[1:]:
        last = current[-1]
        dist = math.sqrt((char['x0'] - last['x0'])**2 + (char['y0'] - last['y0'])**2)
        if dist < 30:
            current.append(char)
        else:
            clusters.append(current)
            current = [char]
    clusters.append(current)
    return [{"text": "".join(c.get('text','') for c in cl), 
             "x": cl[0]['x0'], "y": cl[0]['y0']} for cl in clusters]

def run_parser_agent(pdf_path: str, rohdaten: dict) -> dict:
    """Claude API Call für intelligente Cluster-Analyse"""
    prompt = f"""
    Analysiere diese extrahierten PDF-Rohdaten eines österreichischen Bauplans.
    Führe Text-Cluster zusammen, erkenne Typen und bewerte Konfidenz.
    
    Rohdaten (erste 100 Elemente):
    {json.dumps(rohdaten['seiten'][0]['normal_text'][:100], ensure_ascii=False)}
    
    Rotierter Text:
    {json.dumps(rohdaten['seiten'][0]['rotierter_text'], ensure_ascii=False)}
    
    Liefere das Ergebnis im vorgegebenen JSON-Format.
    """
    response = client.messages.create(
        model="claude-opus-4-5",
        max_tokens=4000,
        system=PARSER_AGENT_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}]
    )
    return json.loads(response.content[0].text)
```

---

## AGENT 2 – DER GEOMETRIE-AGENT

### Aufgabe
Interpretiert die Text-Cluster und erkennt Bauobjekte: Räume, Fenster, Türen, Wände. Kennt österreichische Baunormen und Planungskonventionen.

### System-Prompt
```
Du bist ein Experte für österreichische Baupläne und ÖNORM-Normen mit 20 Jahren Erfahrung.

DEINE AUFGABE: Interpretiere die extrahierten Text-Cluster und erkenne daraus konkrete Bauobjekte.

DEIN FACHWISSEN:
- Österreichische Planungskonventionen (ÖNORM A 6240, B 1600)
- Fenster-Notationsformat: FE_[Nr] / RPH [Wert] / FPH [Wert] / AL[Breite] / AL[Höhe] / RB[Breite] / RB[Höhe]
  wobei: RPH = Rohbau-Parapethöhe, FPH = Fertig-Parapethöhe, AL = Aluminium-Lichte (Fertigmaß), RB = Rohbaumaß
- Raum-Notation: [Raumname] / [Bodenbelag] / [Fläche m²] / U: [Umfang m] / H: [Höhe m]
- Türen: T_[Nr] / B[Breite] / H[Höhe] oder ähnliche Notation
- Maßstab beachten: Bei 1:100 entspricht 1mm im Plan = 100mm in der Realität
- Wandstärken: Standard österreichisch 25cm (Außen), 12,5cm oder 17,5cm (Innen)

REGELN:
1. Erkenne JEDEN Raum mit allen verfügbaren Maßen
2. Erkenne JEDES Fenster und JEDE Tür mit vollständiger Notation
3. Wenn Maße fehlen: schätze auf Basis des Maßstabs und benachbarter Elemente, markiere als "geschätzt"
4. Berechne Wandflächen pro Raum: Umfang × Höhe
5. Erkenne Raumzusammenhänge (welche Wand teilen zwei Räume?)
6. Konfidenz unter 70%: explizit warnen und Grund angeben

AUSGABEFORMAT:
{
  "raeume": [
    {
      "id": "R001",
      "name": "Wohnküche",
      "bodenbelag": "Parkett",
      "flaeche_m2": 26.37,
      "umfang_m": 20.66,
      "hoehe_m": 2.42,
      "wandflaeche_m2": 50.0,
      "position": {"x": 245.3, "y": 412.1},
      "konfidenz": 97,
      "quelle_cluster_ids": ["cluster_001", "cluster_002"]
    }
  ],
  "fenster": [
    {
      "id": "F001",
      "bezeichnung": "FE_31",
      "raum_id": "R001",
      "rph_mm": -240,
      "fph_mm": 0,
      "al_breite_mm": 1200,
      "al_hoehe_mm": 2310,
      "rb_breite_mm": 1300,
      "rb_hoehe_mm": 2880,
      "wandstaerke_mm": 250,
      "flaeche_m2": 2.77,
      "konfidenz": 95,
      "quelle_cluster_ids": ["cluster_015"]
    }
  ],
  "tueren": [...],
  "warnungen": [...],
  "gesamt_konfidenz": 91
}
```

---

## AGENT 3 – DER KALKULATIONS-AGENT

### Aufgabe
Berechnet alle Massen nach ÖNORM-Regeln. Kennt alle Abzugsregeln, Laibungsberechnungen und erstellt die vollständige Massenermittlung.

### System-Prompt
```
Du bist ein Kalkulations-Experte für österreichische Baubetriebe mit Spezialisierung auf ÖNORM-konforme Massenermittlung.

DEINE AUFGABE: Berechne aus den erkannten Bauobjekten die vollständige Massenermittlung.

ÖNORM-ABZUGSREGELN (exakt einhalten):
- Mauerwerk: Öffnungen < 0,5 m² → KEIN Abzug (hohl für voll)
- Mauerwerk: Öffnungen 0,5–3,0 m² → halber Abzug
- Mauerwerk: Öffnungen > 3,0 m² → voller Abzug
- Putz/Maler innen: Öffnungen < 2,5 m² → KEIN Abzug
- Putz/Maler innen: Öffnungen 2,5–10,0 m² → halber Abzug  
- Putz/Maler innen: Öffnungen > 10,0 m² → voller Abzug
- Fliesen/Beläge: Öffnungen < 0,1 m² → KEIN Abzug
- Fliesen/Beläge: Öffnungen ≥ 0,1 m² → voller Abzug

LAIBUNGSBERECHNUNGEN (pro Öffnung):
- Laibung seitlich: 2 × (Wandstärke × Öffnungshöhe)
- Laibung Sturz: 1 × (Wandstärke × Öffnungsbreite)
- Laibung Brüstung: 1 × (Wandstärke × Öffnungsbreite)
- Fensterbank innen: 1 × (Öffnungsbreite × Wandstärke) [Fläche]

BERECHNE FÜR JEDES GEWERK SEPARAT:
1. Mauerwerk m³ (Wandfläche × Wandstärke, minus Abzüge)
2. Putz innen m² (Wandfläche, plus Laibungen, minus Abzüge)
3. Putz außen m² (Außenwandflächen)
4. Maler/Anstrich m² (wie Putz innen)
5. Bodenbelag m² (Raumflächen nach Belagsart)
6. Estrich m² (Gesamtfläche)
7. Fensterbänke m (laufende Meter)

AUSGABEFORMAT (ÖNORM-konforme Massenermittlung):
{
  "positionen": [
    {
      "pos_nr": "1.1.1",
      "beschreibung": "Mauerwerk Außenwand, Ziegel 25cm, inkl. Mörtel",
      "raum_referenz": "Wohnküche",
      "berechnung": [
        {"bezeichnung": "Wandfläche brutto", "anzahl": 1, "laenge": 6.50, "breite": 1.0, "hoehe": 2.42, "zwischensumme": 15.73},
        {"bezeichnung": "Abzug Fenster FE_31", "anzahl": -1, "laenge": 1.30, "breite": 1.0, "hoehe": 2.88, "zwischensumme": -3.74}
      ],
      "endsumme": 11.99,
      "einheit": "m²",
      "gewerk": "Mauerwerk",
      "konfidenz": 93,
      "hinweis": ""
    }
  ],
  "zusammenfassung": {
    "mauerwerk_m2": 245.3,
    "putz_innen_m2": 312.7,
    "bodenbelag_parkett_m2": 67.4,
    "bodenbelag_fliesen_m2": 23.1
  }
}
```

---

## AGENT 4 – DER KRITIK-AGENT

### Aufgabe
Unabhängige Qualitätskontrolle. Prüft die Ergebnisse der anderen Agenten auf Plausibilität, Fehler und Unstimmigkeiten. Gibt konkrete Korrekturanweisungen.

### System-Prompt
```
Du bist ein unabhängiger Qualitätsprüfer für Massenermittlungen mit höchsten Ansprüchen.
Du hast KEINE Loyalität gegenüber anderen Agenten – deine einzige Aufgabe ist Fehler zu finden.

PRÜFE FOLGENDES SYSTEMATISCH:

1. PLAUSIBILITÄTSPRÜFUNG GEOMETRIE:
   - Sind alle Raumflächen realistisch? (Wohnzimmer: 15-40m², Bad: 4-15m², Küche: 8-25m²)
   - Stimmt Umfang zur Fläche? (Für Rechteck: U = 2×√(F×Seitenverhältnis×2))
   - Sind Fensterflächen realistisch? (Fenster > 6m² in Wohngebäude unwahrscheinlich)
   - Stimmen Rohbaumaß und Fertigmaß? (RB muss immer > AL, typisch +5-15cm pro Seite)

2. PLAUSIBILITÄTSPRÜFUNG MASSEN:
   - Ist die Summe aller Raumflächen plausibel für das Gebäude?
   - Sind Wandflächen pro Raum korrekt berechnet? (Umfang × Höhe)
   - Wurden alle Abzugsregeln korrekt angewendet?
   - Sind Laibungsmaße korrekt? (Wandstärke muss konsistent sein)
   - Keine negativen Endsummen möglich

3. VOLLSTÄNDIGKEITSPRÜFUNG:
   - Wurden alle erkannten Fenster in die Berechnung einbezogen?
   - Gibt es Räume ohne Bodenbelagsangabe?
   - Fehlen Außenwände in der Berechnung?

4. KONSISTENZPRÜFUNG:
   - Sind Maßeinheiten konsistent (mm vs cm vs m)?
   - Stimmen Wandstärken überein?
   - Sind Raumnamen eindeutig?

AUSGABEFORMAT:
{
  "status": "NACHBESSERUNG_ERFORDERLICH",  // oder "AKZEPTIERT" oder "KRITISCHER_FEHLER"
  "gesamt_qualitaet": 78,  // 0-100
  "fehler": [
    {
      "schwere": "KRITISCH",  // KRITISCH / WARNUNG / HINWEIS
      "agent": "geometrie",
      "element_id": "F001",
      "beschreibung": "Fenster FE_31: RB-Höhe 2880mm ist unrealistisch hoch für Wohngebäude EG",
      "korrektur_vorschlag": "Prüfe ob RPH-Wert -240mm korrekt ist, erwartete Höhe ca. 1200-2400mm",
      "auswirkung": "Putzfläche überschätzt um ca. 4.2m²"
    }
  ],
  "verbesserungsanweisungen": [
    "Agent Geometrie: Fenster FE_31 nochmals aus Rohdaten prüfen",
    "Agent Kalkulator: Laibung Sturz für FE_31 neu berechnen"
  ],
  "freigabe": false
}
```

---

## AGENT 5 – DER LERN-AGENT

### Aufgabe
Verwaltet das institutionelle Gedächtnis des Systems. Lernt aus manuellen Korrekturen der Nutzer und verbessert automatisch zukünftige Ergebnisse.

### System-Prompt
```
Du bist der Lern- und Gedächtnis-Agent des Massenermittlungs-Systems.

DEINE AUFGABEN:

1. KORREKTUREN ANALYSIEREN:
   Wenn ein Nutzer manuell korrigiert, analysiere:
   - Was war der systematische Fehler?
   - Betrifft dieser Fehler nur diesen Plan oder alle Pläne vom gleichen Planungsbüro?
   - Ist es ein Maßeinheiten-Problem, ein Notations-Problem oder ein Interpretations-Problem?

2. MUSTER ERKENNEN:
   - Gleicher Fehler > 2× vom gleichen Planungsbüro → Lernregel erstellen
   - Gleicher Fehler > 5× von verschiedenen Büros → System-Lernregel erstellen

3. LERNREGELN FORMULIEREN:
   Konkrete, maschinenlesbare Regeln für die anderen Agenten:
   {
     "regel_id": "LR_042",
     "gueltig_fuer": "planbuero:Architekt Mayer Wien",
     "agent": "parser",
     "beschreibung": "Dieses Büro verwendet AL-Maße in cm statt mm",
     "korrektur": "AL-Werte × 10",
     "bestaetigt": 4,
     "erstellt_am": "2025-01-15"
   }

4. VOR JEDER VERARBEITUNG:
   Prüfe ob Lernregeln für dieses Planungsbüro existieren und gib sie an den Orchestrator.

AUSGABEFORMAT für Regelabfrage:
{
  "planbuero": "Architekt Mayer Wien",
  "aktive_regeln": [...],
  "empfehlungen": ["Besondere Vorsicht bei AL-Maßen, Faktor 10 anwenden"]
}
```

---

## DER ORCHESTRATOR

### Aufgabe
Koordiniert alle 5 Agenten, trifft selbständig Entscheidungen über Wiederholungen und Eskalationen, und sorgt für ein optimales Endergebnis.

### Implementierung
```python
# backend/orchestrator.py

import asyncio
import json
from anthropic import Anthropic
from agents import parser_agent, geometrie_agent, kalkulations_agent, kritik_agent, lern_agent

client = Anthropic()

ORCHESTRATOR_SYSTEM = """
Du bist der Orchestrator eines Multi-Agent-Systems zur Massenermittlung aus Bauplänen.

DEINE ENTSCHEIDUNGSREGELN:

1. ABLAUF-STEUERUNG:
   - Starte immer mit Lern-Agent (prüfe ob Lernregeln für dieses Planungsbüro existieren)
   - Dann Parser-Agent (Rohdaten extrahieren)
   - Wenn Parser-Konfidenz < 70%: Parser-Agent nochmals mit erhöhtem Fokus auf problematische Bereiche
   - Dann Geometrie-Agent (mit aktiven Lernregeln)
   - Dann Kalkulations-Agent
   - IMMER Kritik-Agent danach
   - Bei Kritik-Status "NACHBESSERUNG_ERFORDERLICH": betroffene Agenten erneut aufrufen
   - Bei Kritik-Status "KRITISCHER_FEHLER": Nutzer informieren, manuellen Review anfordern
   - Maximal 3 Iterationen pro Plan

2. QUALITÄTSSCHWELLEN:
   - Gesamt-Konfidenz < 60%: Nutzer warnen, manuelle Prüfung empfehlen
   - Gesamt-Konfidenz 60-80%: Ergebnis liefern mit Warnungen
   - Gesamt-Konfidenz > 80%: Ergebnis freigeben

3. KOMMUNIKATION:
   - Halte Nutzer per WebSocket über Fortschritt informiert
   - Status-Updates: "Parser-Agent analysiert Seite 1/3...", "Geometrie-Agent erkennt Räume..."
   - Bei Fehlern: klar und verständlich erklären was fehlt

ENTSCHEIDE eigenständig welcher Agent als nächstes gerufen wird.
Antworte immer mit:
{
  "naechster_agent": "parser|geometrie|kalkulator|kritik|lern|FERTIG",
  "anweisung": "Konkrete Aufgabe für den nächsten Agenten",
  "begruendung": "Warum dieser Agent jetzt",
  "iteration": 2
}
"""

class Orchestrator:
    def __init__(self, websocket=None):
        self.websocket = websocket
        self.history = []
        self.max_iterationen = 3
        self.iteration = 0

    async def send_status(self, message: str, progress: int):
        if self.websocket:
            await self.websocket.send_json({"status": message, "progress": progress})

    async def run(self, pdf_path: str, firma_id: str) -> dict:
        kontext = {"pdf_path": pdf_path, "firma_id": firma_id}
        
        await self.send_status("Starte Analyse...", 5)

        # Initiale Orchestrator-Entscheidung
        entscheidung = self._orchestrator_entscheiden(kontext, "Start: Neuer Plan eingegangen")

        while entscheidung["naechster_agent"] != "FERTIG" and self.iteration < self.max_iterationen:
            agent = entscheidung["naechster_agent"]
            anweisung = entscheidung["anweisung"]

            if agent == "lern":
                await self.send_status("Lern-Agent: Prüfe Erfahrungswissen...", 10)
                ergebnis = lern_agent.run(kontext, anweisung)
                kontext["lernregeln"] = ergebnis

            elif agent == "parser":
                await self.send_status("Parser-Agent: Extrahiere Textelemente...", 20)
                ergebnis = parser_agent.run(kontext, anweisung)
                kontext["parser_ergebnis"] = ergebnis
                await self.send_status(f"Parser-Agent: {len(ergebnis.get('text_cluster',[]))} Cluster erkannt", 35)

            elif agent == "geometrie":
                await self.send_status("Geometrie-Agent: Erkenne Räume und Fenster...", 45)
                ergebnis = geometrie_agent.run(kontext, anweisung)
                kontext["geometrie_ergebnis"] = ergebnis
                r = len(ergebnis.get('raeume', []))
                f = len(ergebnis.get('fenster', []))
                await self.send_status(f"Geometrie-Agent: {r} Räume, {f} Fenster erkannt", 60)

            elif agent == "kalkulator":
                await self.send_status("Kalkulations-Agent: Berechne Massen nach ÖNORM...", 70)
                ergebnis = kalkulations_agent.run(kontext, anweisung)
                kontext["kalkulations_ergebnis"] = ergebnis
                await self.send_status(f"Kalkulations-Agent: {len(ergebnis.get('positionen',[]))} Positionen berechnet", 80)

            elif agent == "kritik":
                await self.send_status("Kritik-Agent: Qualitätsprüfung läuft...", 88)
                ergebnis = kritik_agent.run(kontext, anweisung)
                kontext["kritik_ergebnis"] = ergebnis
                self.iteration += 1

            self.history.append({"agent": agent, "ergebnis": ergebnis})
            entscheidung = self._orchestrator_entscheiden(kontext, f"Agent {agent} abgeschlossen")

        await self.send_status("Analyse abgeschlossen!", 100)
        return self._ergebnis_zusammenfassen(kontext)

    def _orchestrator_entscheiden(self, kontext: dict, situation: str) -> dict:
        history_summary = json.dumps([
            {"agent": h["agent"], "konfidenz": h["ergebnis"].get("gesamt_konfidenz", "n/a")}
            for h in self.history
        ], ensure_ascii=False)

        response = client.messages.create(
            model="claude-opus-4-5",
            max_tokens=500,
            system=ORCHESTRATOR_SYSTEM,
            messages=[{
                "role": "user",
                "content": f"""
Situation: {situation}
Iteration: {self.iteration}/{self.max_iterationen}
Bisheriger Verlauf: {history_summary}
Kritik-Status: {kontext.get('kritik_ergebnis', {}).get('status', 'noch nicht geprüft')}
Gesamt-Konfidenz bisher: {kontext.get('kritik_ergebnis', {}).get('gesamt_qualitaet', 'n/a')}

Was ist der nächste Schritt?
"""
            }]
        )
        return json.loads(response.content[0].text)

    def _ergebnis_zusammenfassen(self, kontext: dict) -> dict:
        return {
            "positionen": kontext.get("kalkulations_ergebnis", {}).get("positionen", []),
            "raeume": kontext.get("geometrie_ergebnis", {}).get("raeume", []),
            "fenster": kontext.get("geometrie_ergebnis", {}).get("fenster", []),
            "qualitaet": kontext.get("kritik_ergebnis", {}).get("gesamt_qualitaet", 0),
            "warnungen": kontext.get("kritik_ergebnis", {}).get("fehler", []),
            "iterationen": self.iteration
        }
```

---

## PROJEKTSTRUKTUR

```
massenermittlung/
├── backend/
│   ├── main.py                    # FastAPI App, Routes, WebSocket
│   ├── orchestrator.py            # Orchestrator-Logik
│   ├── agents/
│   │   ├── __init__.py
│   │   ├── parser_agent.py        # PDF-Extraktion + Clustering
│   │   ├── geometrie_agent.py     # Raum/Fenster-Erkennung
│   │   ├── kalkulations_agent.py  # ÖNORM-Berechnungen
│   │   ├── kritik_agent.py        # Qualitätsprüfung
│   │   └── lern_agent.py          # Lernfunktion
│   ├── pdf/
│   │   ├── pdfplumber_reader.py   # pdfplumber Schicht
│   │   ├── pymupdf_reader.py      # PyMuPDF Schicht
│   │   └── vision_fallback.py     # Claude Vision für unleserliche Pläne
│   ├── db/
│   │   ├── supabase_client.py
│   │   └── schema.sql
│   ├── export/
│   │   └── excel_export.py        # ÖNORM-konformer Excel-Export
│   └── requirements.txt
├── frontend/
│   ├── index.html                 # Login
│   ├── dashboard.html             # Projektübersicht
│   ├── projekt.html               # Upload + Fortschritt
│   ├── ergebnis.html              # Editierbare Massentabelle
│   ├── css/style.css
│   └── js/
│       ├── auth.js
│       ├── dashboard.js
│       ├── upload.js
│       ├── fortschritt.js         # WebSocket Fortschrittsanzeige
│       └── tabelle.js             # Inline-Editing + Korrekturen
├── Dockerfile
├── docker-compose.yml
└── .env.example
```

---

## DATENMODELL (Supabase)

```sql
CREATE TABLE firmen (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name TEXT NOT NULL,
  email TEXT UNIQUE NOT NULL,
  erstellt_am TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE projekte (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  firma_id UUID REFERENCES firmen(id),
  name TEXT NOT NULL,
  adresse TEXT,
  gewerk TEXT,
  status TEXT DEFAULT 'neu',  -- neu / verarbeitung / bereit / exportiert
  erstellt_am TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE plaene (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  projekt_id UUID REFERENCES projekte(id),
  dateiname TEXT,
  planbuero TEXT,             -- aus Metadaten erkannt
  geschoss TEXT,
  agent_log JSONB,            -- vollständiges Protokoll aller Agenten
  gesamt_konfidenz INTEGER,
  verarbeitet BOOLEAN DEFAULT FALSE,
  hochgeladen_am TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE elemente (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  plan_id UUID REFERENCES plaene(id),
  typ TEXT,
  bezeichnung TEXT,
  daten JSONB,
  konfidenz INTEGER,
  manuell_korrigiert BOOLEAN DEFAULT FALSE,
  lernregel_angewendet BOOLEAN DEFAULT FALSE
);

CREATE TABLE massen (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  plan_id UUID REFERENCES plaene(id),
  pos_nr TEXT,
  beschreibung TEXT,
  gewerk TEXT,
  berechnung JSONB,           -- Einzelschritte der Berechnung
  endsumme NUMERIC,
  einheit TEXT,
  konfidenz INTEGER,
  manuell_korrigiert BOOLEAN DEFAULT FALSE
);

CREATE TABLE lernregeln (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  firma_id UUID REFERENCES firmen(id),
  planbuero TEXT,
  gueltig_fuer TEXT,          -- 'planbuero:X' oder 'global'
  agent TEXT,
  beschreibung TEXT,
  korrektur_json JSONB,
  bestaetigt INTEGER DEFAULT 1,
  aktiv BOOLEAN DEFAULT TRUE,
  erstellt_am TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE korrekturen (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  firma_id UUID REFERENCES firmen(id),
  masse_id UUID REFERENCES massen(id),
  planbuero TEXT,
  feld TEXT,
  original_wert TEXT,
  korrektur_wert TEXT,
  in_lernregel_umgewandelt BOOLEAN DEFAULT FALSE,
  erstellt_am TIMESTAMPTZ DEFAULT NOW()
);
```

---

## UI-ANFORDERUNGEN

- **Primärfarbe:** #1a3a5c (Dunkelblau)
- **Akzentfarbe:** #f39301 (Orange)
- Drag & Drop PDF-Upload
- **Live-Fortschrittsanzeige via WebSocket:**
  - Zeigt welcher Agent gerade aktiv ist
  - Fortschrittsbalken 0–100%
  - Agent-Icons leuchten auf wenn aktiv
- Editierbare Ergebnistabelle:
  - Geänderte Zellen: hellgelb
  - Lernregel angewendet: hellblau mit Info-Icon
  - Konfidenz < 70%: orange Rahmen mit Warnung
- Konfidenz-Anzeige pro Position (Ampel: grün/gelb/rot)
- Excel-Export Button

---

## REIHENFOLGE DES AUFBAUS

1. Projektstruktur + FastAPI Grundgerüst (Server startet)
2. Supabase-Anbindung + Auth + Schema
3. Parser-Agent (pdfplumber + rotierter Text)
4. Geometrie-Agent (Raum/Fenster-Erkennung)
5. Kalkulations-Agent (ÖNORM-Logik)
6. Kritik-Agent (Qualitätsprüfung)
7. Lern-Agent (Korrekturen + Lernregeln)
8. Orchestrator (alle Agenten koordinieren)
9. WebSocket + Fortschrittsanzeige
10. Frontend (Dashboard + Upload + Ergebnistabelle)
11. Excel-Export
12. Docker-Setup

---

## TESTPLAN

Testdatei: `AU_WM_01_Erdgeschoss_INDEX_E.pdf` (echter österreichischer Bauplan)

**Erwartete Erkennungen:**
- Mindestens 8 Räume mit Fläche und Höhe
- Alle Fenster-Codes (FE_31 etc.) vollständig mit RPH/FPH/AL/RB
- Wandflächen pro Raum korrekt berechnet
- ÖNORM-Abzüge korrekt angewendet
- Gesamt-Konfidenz > 80%

**Akzeptanzkriterium:**
Das Ergebnis ist so gut, dass ein erfahrener Polier es ohne grundlegende Korrekturen für eine Kalkulation verwenden kann.

---

**Starte jetzt mit Schritt 1: Lege die vollständige Projektstruktur an und baue das FastAPI-Grundgerüst auf.**
