"""
Geometrie Agent - Interpretation von Bauobjekten aus Parser-Daten.

Interpretiert Textcluster als Räume, Fenster und Türen nach
österreichischen ÖNORM-Standards (A 6240, B 1600).
"""

import json
import logging
import os
from typing import Any

import anthropic

logger = logging.getLogger(__name__)

MODEL = "claude-sonnet-4-20250514"

SYSTEM_PROMPT = """Du bist ein spezialisierter KI-Agent für die geometrische Interpretation von österreichischen Bauplänen nach ÖNORM-Standards.

Du erhältst analysierte Textcluster aus einem Bauplan und musst daraus strukturierte Bauobjekte (Räume, Fenster, Türen) extrahieren.

ÖSTERREICHISCHE NORMEN:
- ÖNORM A 6240: Technisches Zeichnen im Bauwesen
- ÖNORM B 1600: Barrierefreies Bauen

FENSTERNOTATION (österreichisch):
FE_[Nr] / RPH [Wert] / FPH [Wert] / AL[Breite] / AL[Höhe] / RB[Breite] / RB[Höhe]
- FE_[Nr]: Fensterbezeichnung/Nummer
- RPH: Rohbauparapethöhe in mm (Unterkante Fenster ab Rohfußboden)
- FPH: Fertigparapethöhe in mm (ab Fertigfußboden, kann 0 oder negativ sein)
- AL: Architekturlichte (Breite × Höhe) in mm
- RB: Rohbauöffnung (Breite × Höhe) in mm

RAUMNOTATION:
[Raumname] / [Bodenbelag] / [Fläche in m²] / U: [Umfang in m] / H: [Höhe in m]
Beispiel: "Wohnzimmer / Parkett / 23.50 m² / U: 20.40 m / H: 2.60 m"

TÜRNOTATION:
T[Nr] / [Breite]×[Höhe] / [Typ] (z.B. "T1 / 90×210 / Drehflügel")

AUSGABEFORMAT (JSON):
{
  "raeume": [
    {
      "id": "R1",
      "name": "Wohnzimmer",
      "bodenbelag": "Parkett",
      "flaeche_m2": 23.50,
      "umfang_m": 20.40,
      "hoehe_m": 2.60,
      "wandflaeche_m2": 53.04,
      "konfidenz": 0.95
    }
  ],
  "fenster": [
    {
      "id": "FE_31",
      "bezeichnung": "FE_31",
      "raum_id": "R1",
      "rph_mm": -24,
      "fph_mm": 0,
      "al_breite_mm": 1200,
      "al_hoehe_mm": 1500,
      "rb_breite_mm": 1200,
      "rb_hoehe_mm": 1500,
      "flaeche_m2": 1.80,
      "konfidenz": 0.90
    }
  ],
  "tueren": [
    {
      "id": "T1",
      "bezeichnung": "T1",
      "raum_id": "R1",
      "breite_mm": 900,
      "hoehe_mm": 2100,
      "typ": "Drehflügel",
      "flaeche_m2": 1.89,
      "konfidenz": 0.85
    }
  ],
  "warnungen": [],
  "gesamt_konfidenz": 0.88
}

BERECHNUNGSREGELN:
- Wandfläche = Umfang × Höhe (brutto, vor Abzügen)
- Fensterfläche (AL) = AL_Breite × AL_Höhe / 1.000.000 (mm² → m²)
- Fensterfläche (RB) = RB_Breite × RB_Höhe / 1.000.000 (mm² → m²)

Antworte NUR mit validem JSON, ohne Markdown-Codeblöcke.
"""


def _parse_json_response(text: str) -> dict:
    """Robustes JSON-Parsing mit Fallbacks."""
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    import re
    match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass

    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(text[start:end + 1])
        except json.JSONDecodeError:
            pass

    logger.error("Konnte JSON nicht parsen: %s", text[:200])
    return {
        "raeume": [],
        "fenster": [],
        "tueren": [],
        "warnungen": ["JSON-Parsing fehlgeschlagen"],
        "gesamt_konfidenz": 0.0,
    }


async def run(kontext: dict, anweisung: str = "") -> dict:
    """
    Hauptfunktion des Geometrie-Agents.

    Args:
        kontext: Dict mit 'parser_ergebnis' (Ausgabe des Parser-Agents).
        anweisung: Optionale zusätzliche Anweisung (z.B. Lernregeln).

    Returns:
        Dict mit raeume, fenster, tueren, warnungen, gesamt_konfidenz.
    """
    parser_ergebnis = kontext.get("parser_ergebnis", {})
    has_data = (parser_ergebnis.get("raeume") or parser_ergebnis.get("fenster")
                or parser_ergebnis.get("tueren") or parser_ergebnis.get("text_cluster"))
    if not parser_ergebnis or not has_data:
        return {
            "raeume": [],
            "fenster": [],
            "tueren": [],
            "warnungen": ["Keine Daten vom Parser erhalten"],
            "gesamt_konfidenz": 0.0,
        }

    # Der Vision-First-Parser liefert bereits strukturierte Daten.
    # Wir senden alles an Claude zur Verfeinerung und Plausibilitätsprüfung.
    parser_data = json.dumps(parser_ergebnis, ensure_ascii=False, indent=2)

    user_message = f"""Verfeinere und ergänze die folgenden Parser-Ergebnisse eines österreichischen Bauplans.
Der Parser hat bereits Räume, Fenster und Türen erkannt. Deine Aufgabe:

1. PLAUSIBILITÄTSPRÜFUNG: Sind alle Werte realistisch?
2. WANDFLÄCHEN berechnen: Umfang × Höhe für jeden Raum
3. FENSTER den richtigen RÄUMEN zuordnen (falls noch nicht geschehen)
4. FEHLENDE DATEN ergänzen (z.B. Wandstärken, Fensterflächen)
5. IDs vergeben: R001, R002... für Räume, F001... für Fenster

Maßstab: {parser_ergebnis.get("massstab", "unbekannt")}
Geschoss: {parser_ergebnis.get("geschoss", "unbekannt")}
Räume erkannt: {len(parser_ergebnis.get("raeume", []))}
Fenster erkannt: {len(parser_ergebnis.get("fenster", []))}
Türen erkannt: {len(parser_ergebnis.get("tueren", []))}
Wandstärken: {parser_ergebnis.get("wandstaerken_mm", "unbekannt")}

{f"Zusätzliche Anweisung: {anweisung}" if anweisung else ""}

Parser-Ergebnis:
{parser_data}

Antworte NUR mit validem JSON gemäß dem vorgegebenen Format."""

    try:
        client = anthropic.AsyncAnthropic(
            api_key=os.environ.get("ANTHROPIC_API_KEY", ""),
        )

        response = await client.messages.create(
            model=MODEL,
            max_tokens=4096,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_message}],
        )

        raw_text = response.content[0].text if response.content else ""
        result = _parse_json_response(raw_text)

        # Ensure required fields
        result.setdefault("raeume", [])
        result.setdefault("fenster", [])
        result.setdefault("tueren", [])
        result.setdefault("warnungen", [])
        result.setdefault("gesamt_konfidenz", 0.0)

        # Calculate wandflaeche if missing
        for raum in result["raeume"]:
            if "wandflaeche_m2" not in raum and "umfang_m" in raum and "hoehe_m" in raum:
                raum["wandflaeche_m2"] = round(raum["umfang_m"] * raum["hoehe_m"], 2)

        # Calculate fenster flaeche if missing
        for fenster in result["fenster"]:
            if "flaeche_m2" not in fenster and "al_breite_mm" in fenster and "al_hoehe_mm" in fenster:
                fenster["flaeche_m2"] = round(
                    fenster["al_breite_mm"] * fenster["al_hoehe_mm"] / 1_000_000, 2
                )

        logger.info(
            "Geometrie-Agent abgeschlossen: %d Räume, %d Fenster, %d Türen, Konfidenz: %.0f%%",
            len(result["raeume"]),
            len(result["fenster"]),
            len(result["tueren"]),
            result["gesamt_konfidenz"] * 100,
        )
        return result

    except anthropic.APIError as e:
        logger.error("Anthropic API Fehler: %s", e)
        return {
            "raeume": [],
            "fenster": [],
            "tueren": [],
            "warnungen": [f"API-Fehler: {str(e)}"],
            "gesamt_konfidenz": 0.0,
        }
    except Exception as e:
        logger.error("Unerwarteter Fehler im Geometrie-Agent: %s", e, exc_info=True)
        return {
            "raeume": [],
            "fenster": [],
            "tueren": [],
            "warnungen": [f"Unerwarteter Fehler: {str(e)}"],
            "gesamt_konfidenz": 0.0,
        }
