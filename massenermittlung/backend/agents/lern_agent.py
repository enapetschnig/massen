"""
Lern Agent - Intelligente Verwaltung von Lernregeln aus manuellen Korrekturen.

ARCHITEKTUR (3-Stufen-Pipeline):
  Stufe 1: Supabase-Abfrage - Bestehende Regeln und Korrekturen laden
  Stufe 2: Lokale Musteranalyse - Korrekturen gruppieren, Schwellenwerte pruefen
           - Nach Planbuero gruppieren (Schwelle: >2 gleiche -> buero-spezifisch)
           - Global gruppieren (Schwelle: >5 gleiche -> globale Regel)
           - Fehlertyp-Klassifizierung
  Stufe 3: Claude-KI-Analyse fuer komplexe Mustererkennung
           - Semantische Aehnlichkeit von Korrekturen
           - Kontext-spezifische Empfehlungen
           - Regelformulierung in natuerlicher Sprache

Regeltypen: FENSTER_NOTATION, RAUM_ZUORDNUNG, MASSSTAB_KORREKTUR,
            ABZUGS_REGEL, TEXT_KORREKTUR, WANDSTAERKE
"""

import json
import logging
import os
import re
from collections import Counter, defaultdict

import anthropic

logger = logging.getLogger(__name__)

MODEL = "claude-sonnet-4-20250514"

# ---------------------------------------------------------------------------
# Schwellenwerte fuer automatische Regelerstellung
# ---------------------------------------------------------------------------

BUERO_SCHWELLE = 2    # Gleicher Fehler >2x vom selben Buero -> buero-spezifische Regel
GLOBAL_SCHWELLE = 5   # Gleicher Fehler >5x global -> globale Regel

# Fehlertyp-Klassifizierung basierend auf korrigiertem Feld
FEHLERTYP_MAPPING = {
    "bezeichnung": "FENSTER_NOTATION",
    "fenster_bezeichnung": "FENSTER_NOTATION",
    "fenster_typ": "FENSTER_NOTATION",
    "raum_name": "RAUM_ZUORDNUNG",
    "raum_bezeichnung": "RAUM_ZUORDNUNG",
    "raum_referenz": "RAUM_ZUORDNUNG",
    "raum_zuordnung": "RAUM_ZUORDNUNG",
    "massstab": "MASSSTAB_KORREKTUR",
    "skalierung": "MASSSTAB_KORREKTUR",
    "abzug": "ABZUGS_REGEL",
    "abzugsregel": "ABZUGS_REGEL",
    "abzug_faktor": "ABZUGS_REGEL",
    "wandstaerke": "WANDSTAERKE",
    "wand_staerke": "WANDSTAERKE",
    "text": "TEXT_KORREKTUR",
    "ocr": "TEXT_KORREKTUR",
    "extraktion": "TEXT_KORREKTUR",
}


# ---------------------------------------------------------------------------
# Supabase-Abfrage (Stufe 1)
# ---------------------------------------------------------------------------

def _query_supabase_rules(firma_id: str, planbuero: str) -> tuple[list[dict], list[dict]]:
    """Laedt bestehende Regeln und Korrekturen aus Supabase.

    Versucht den Import des Supabase-Clients. Wenn nicht verfuegbar
    (z.B. in Tests oder wenn Umgebungsvariablen fehlen), gibt leere Listen zurueck.

    Returns:
        Tuple von (regeln, korrekturen).
    """
    regeln = []
    korrekturen = []

    try:
        from db.supabase_client import get_lernregeln, get_korrekturen

        logger.info("Supabase-Abfrage: Lade Regeln fuer firma_id=%s, planbuero=%s", firma_id, planbuero)

        # Buero-spezifische Regeln
        if planbuero:
            try:
                buero_regeln = get_lernregeln(firma_id, planbuero=planbuero)
                regeln.extend(buero_regeln)
                logger.info("  -> %d buero-spezifische Regeln geladen", len(buero_regeln))
            except Exception as e:
                logger.warning("Fehler beim Laden buero-spezifischer Regeln: %s", e)

        # Globale Regeln (ohne planbuero-Filter)
        try:
            alle_regeln = get_lernregeln(firma_id)
            # Nur Regeln hinzufuegen die nicht schon drin sind
            existing_ids = {r.get("id") for r in regeln}
            for regel in alle_regeln:
                if regel.get("id") not in existing_ids:
                    regeln.append(regel)
            logger.info("  -> %d Regeln insgesamt nach globalem Laden", len(regeln))
        except Exception as e:
            logger.warning("Fehler beim Laden globaler Regeln: %s", e)

        # Korrekturen laden
        try:
            korrekturen = get_korrekturen(firma_id=firma_id)
            logger.info("  -> %d Korrekturen geladen", len(korrekturen))
        except Exception as e:
            logger.warning("Fehler beim Laden der Korrekturen: %s", e)

    except ImportError:
        logger.info("Supabase-Client nicht verfuegbar, ueberspringe DB-Abfrage")
    except Exception as e:
        logger.warning("Supabase-Verbindung fehlgeschlagen: %s", e)

    return regeln, korrekturen


# ---------------------------------------------------------------------------
# Lokale Musteranalyse (Stufe 2)
# ---------------------------------------------------------------------------

def _classify_correction(korrektur: dict) -> str:
    """Klassifiziert eine Korrektur nach Fehlertyp.

    Args:
        korrektur: Dict mit mindestens 'feld' oder 'grund'.

    Returns:
        Fehlertyp-String (z.B. 'FENSTER_NOTATION').
    """
    feld = korrektur.get("feld", "").lower()
    grund = korrektur.get("grund", "").lower()

    # Direkter Mapping-Match
    for key, typ in FEHLERTYP_MAPPING.items():
        if key in feld:
            return typ

    # Keyword-basierte Erkennung aus dem Grund
    if any(kw in grund for kw in ["fenster", "fe_", "fe ", "fensterbez"]):
        return "FENSTER_NOTATION"
    if any(kw in grund for kw in ["raum", "zimmer", "bezeichnung"]):
        return "RAUM_ZUORDNUNG"
    if any(kw in grund for kw in ["massstab", "skalierung", "faktor"]):
        return "MASSSTAB_KORREKTUR"
    if any(kw in grund for kw in ["abzug", "oeffnung", "oenorm"]):
        return "ABZUGS_REGEL"
    if any(kw in grund for kw in ["wand", "staerke", "dicke"]):
        return "WANDSTAERKE"
    if any(kw in grund for kw in ["text", "ocr", "erkennung", "lesen"]):
        return "TEXT_KORREKTUR"

    return "TEXT_KORREKTUR"  # Standard-Fallback


def _create_correction_signature(korrektur: dict) -> str:
    """Erzeugt eine Signatur fuer die Korrektur zur Gruppierung aehnlicher Fehler.

    Zwei Korrekturen mit gleicher Signatur gelten als 'gleicher Fehler'.
    """
    feld = korrektur.get("feld", "unbekannt")
    original = str(korrektur.get("original_wert", korrektur.get("alter_wert", "")))
    korr = str(korrektur.get("korrektur_wert", korrektur.get("neuer_wert", "")))

    # Normalisiere Zahlen (1.20 und 1.2 sind gleich)
    try:
        original = str(float(original))
    except (ValueError, TypeError):
        pass
    try:
        korr = str(float(korr))
    except (ValueError, TypeError):
        pass

    return f"{feld}::{original}->{korr}"


def _analyze_patterns(
    korrekturen: list[dict],
    korrektur_historie: list[dict],
    _planbuero: str,
    bisherige_regeln: list[dict],
) -> dict:
    """Analysiert Korrekturmuster und schlaegt neue Regeln vor.

    Gruppiert Korrekturen nach:
      1. Planbuero + Signatur (buero-spezifisch)
      2. Nur Signatur (global)

    Returns:
        Dict mit 'neue_regeln', 'muster_statistik', 'empfehlungen'.
    """
    alle_korrekturen = list(korrekturen) + list(korrektur_historie)

    if not alle_korrekturen:
        return {"neue_regeln": [], "muster_statistik": {}, "empfehlungen": []}

    # Gruppiere nach Buero
    buero_gruppen: dict[str, dict[str, list[dict]]] = defaultdict(lambda: defaultdict(list))
    global_gruppen: dict[str, list[dict]] = defaultdict(list)
    fehlertyp_counter: Counter = Counter()

    for korr in alle_korrekturen:
        sig = _create_correction_signature(korr)
        korr_buero = korr.get("planbuero", "")
        fehlertyp = _classify_correction(korr)
        fehlertyp_counter[fehlertyp] += 1

        # Buero-spezifische Gruppierung
        if korr_buero:
            buero_gruppen[korr_buero][sig].append(korr)

        # Globale Gruppierung
        global_gruppen[sig].append(korr)

    # Bestehende Regeln als Set fuer Duplikat-Erkennung
    bestehende_beschreibungen = {
        r.get("beschreibung", "").lower() for r in bisherige_regeln
    }

    neue_regeln = []
    empfehlungen = []
    regel_counter = len(bisherige_regeln)

    # --- Buero-spezifische Regeln (Schwelle: >2) ---
    for buero, signaturen in buero_gruppen.items():
        for sig, korr_list in signaturen.items():
            if len(korr_list) > BUERO_SCHWELLE:
                fehlertyp = _classify_correction(korr_list[0])
                beschreibung = _format_rule_description(korr_list[0], fehlertyp, len(korr_list))

                if beschreibung.lower() not in bestehende_beschreibungen:
                    regel_counter += 1
                    konfidenz = min(0.95, 0.5 + (len(korr_list) * 0.1))
                    neue_regeln.append({
                        "id": f"LR_{regel_counter:03d}",
                        "typ": fehlertyp,
                        "planbuero": buero,
                        "beschreibung": beschreibung,
                        "anweisung": _format_rule_instruction(korr_list[0], fehlertyp),
                        "konfidenz": round(konfidenz, 2),
                        "anwendungen": len(korr_list),
                        "global": False,
                        "signatur": sig,
                        "basiert_auf_korrekturen": len(korr_list),
                    })
                    empfehlungen.append(
                        f"Buero '{buero}': {beschreibung} "
                        f"(basierend auf {len(korr_list)} Korrekturen)"
                    )

    # --- Globale Regeln (Schwelle: >5) ---
    for sig, korr_list in global_gruppen.items():
        if len(korr_list) > GLOBAL_SCHWELLE:
            fehlertyp = _classify_correction(korr_list[0])
            beschreibung = _format_rule_description(korr_list[0], fehlertyp, len(korr_list))

            if beschreibung.lower() not in bestehende_beschreibungen:
                # Pruefen ob nicht schon als buero-spezifische Regel erstellt
                already_buero = any(
                    r.get("signatur") == sig for r in neue_regeln
                )
                if not already_buero:
                    regel_counter += 1
                    konfidenz = min(0.98, 0.6 + (len(korr_list) * 0.05))
                    neue_regeln.append({
                        "id": f"LR_{regel_counter:03d}",
                        "typ": fehlertyp,
                        "planbuero": "",
                        "beschreibung": beschreibung,
                        "anweisung": _format_rule_instruction(korr_list[0], fehlertyp),
                        "konfidenz": round(konfidenz, 2),
                        "anwendungen": len(korr_list),
                        "global": True,
                        "signatur": sig,
                        "basiert_auf_korrekturen": len(korr_list),
                    })
                    empfehlungen.append(
                        f"GLOBAL: {beschreibung} "
                        f"(basierend auf {len(korr_list)} Korrekturen)"
                    )

    muster_statistik = {
        "total_korrekturen_analysiert": len(alle_korrekturen),
        "einzigartige_signaturen": len(global_gruppen),
        "bueros_mit_korrekturen": len(buero_gruppen),
        "fehlertyp_verteilung": dict(fehlertyp_counter),
        "neue_regeln_vorgeschlagen": len(neue_regeln),
    }

    logger.info(
        "Musteranalyse: %d Korrekturen -> %d einzigartige Muster -> %d neue Regeln",
        len(alle_korrekturen),
        len(global_gruppen),
        len(neue_regeln),
    )

    return {
        "neue_regeln": neue_regeln,
        "muster_statistik": muster_statistik,
        "empfehlungen": empfehlungen,
    }


def _format_rule_description(korrektur: dict, fehlertyp: str, count: int) -> str:
    """Formatiert eine menschenlesbare Regelbeschreibung."""
    feld = korrektur.get("feld", "unbekannt")
    original = korrektur.get("original_wert", korrektur.get("alter_wert", "?"))
    korr_wert = korrektur.get("korrektur_wert", korrektur.get("neuer_wert", "?"))

    if fehlertyp == "FENSTER_NOTATION":
        return f"Fensterbezeichnung '{original}' wird zu '{korr_wert}' korrigiert ({count}x)"
    elif fehlertyp == "RAUM_ZUORDNUNG":
        return f"Raumbezeichnung '{original}' wird zu '{korr_wert}' korrigiert ({count}x)"
    elif fehlertyp == "MASSSTAB_KORREKTUR":
        return f"Massstab-Korrektur: {original} -> {korr_wert} ({count}x)"
    elif fehlertyp == "WANDSTAERKE":
        return f"Wandstaerke-Korrektur: {original} -> {korr_wert} ({count}x)"
    elif fehlertyp == "ABZUGS_REGEL":
        return f"Abzugsregel-Korrektur fuer '{feld}': {original} -> {korr_wert} ({count}x)"
    else:
        return f"Korrektur in Feld '{feld}': '{original}' -> '{korr_wert}' ({count}x)"


def _format_rule_instruction(korrektur: dict, fehlertyp: str) -> str:
    """Formatiert eine Anweisung fuer die anderen Agenten."""
    original = korrektur.get("original_wert", korrektur.get("alter_wert", "?"))
    korr_wert = korrektur.get("korrektur_wert", korrektur.get("neuer_wert", "?"))

    if fehlertyp == "FENSTER_NOTATION":
        return f"Interpretiere '{original}' als '{korr_wert}' bei Fensterbezeichnungen"
    elif fehlertyp == "RAUM_ZUORDNUNG":
        return f"Ordne '{original}' als '{korr_wert}' zu"
    elif fehlertyp == "MASSSTAB_KORREKTUR":
        return f"Verwende Massstab-Korrekturfaktor: {original} -> {korr_wert}"
    elif fehlertyp == "WANDSTAERKE":
        return f"Verwende Wandstaerke {korr_wert} statt Standard {original}"
    elif fehlertyp == "ABZUGS_REGEL":
        return f"Abzugsregel anpassen: {original} -> {korr_wert}"
    else:
        return f"Korrigiere '{original}' zu '{korr_wert}'"


def _build_context_recommendations(
    regeln: list[dict], planbuero: str
) -> list[str]:
    """Erstellt kontext-spezifische Empfehlungen aus aktiven Regeln.

    Returns:
        Liste von Empfehlungs-Strings fuer die anderen Agenten.
    """
    empfehlungen = []

    # Sortiere nach Konfidenz (hoechste zuerst)
    sorted_regeln = sorted(regeln, key=lambda r: r.get("konfidenz", 0), reverse=True)

    for regel in sorted_regeln:
        anweisung = regel.get("anweisung", "")
        if not anweisung:
            anweisung = regel.get("beschreibung", "")
        if not anweisung:
            continue

        # Buero-spezifische Regeln priorisieren
        ist_buero = regel.get("planbuero", "") == planbuero and planbuero
        konfidenz = regel.get("konfidenz", 0)

        if ist_buero:
            empfehlungen.append(f"[Buero-Regel, Konfidenz {konfidenz:.0%}] {anweisung}")
        elif regel.get("global", False):
            empfehlungen.append(f"[Globale Regel, Konfidenz {konfidenz:.0%}] {anweisung}")
        else:
            empfehlungen.append(anweisung)

    return empfehlungen


# ---------------------------------------------------------------------------
# System-Prompt fuer Claude (Stufe 3)
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """Du bist ein spezialisierter KI-Agent fuer maschinelles Lernen aus manuellen Korrekturen bei der Massenermittlung aus oesterreichischen Bauplaenen.

Du erhaeltst:
1. Bestehende Lernregeln aus der Datenbank
2. Ergebnisse einer lokalen Musteranalyse (Python-basiert)
3. Neue und historische Korrekturen zur Analyse

Deine Aufgabe:
1. Lokale Musteranalyse bestaetigen oder verfeinern
2. Semantische Muster erkennen die die lokale Analyse nicht findet
   (z.B. "FE31" und "FE_31" und "FE-31" sind dasselbe Muster)
3. Kontext-spezifische Empfehlungen fuer die anderen Agenten formulieren
4. Neue Regelvorschlaege pruefen und gegebenenfalls zusammenfuehren

REGELTYPEN:
- FENSTER_NOTATION: Spezielle Fensterbezeichnungen eines Planungsbueros
- RAUM_ZUORDNUNG: Besondere Raumbezeichnungen oder -zuordnungen
- MASSSTAB_KORREKTUR: Planungsbuero-spezifischer Massstab
- ABZUGS_REGEL: Abweichende Abzugsregeln fuer bestimmte Bauteile
- TEXT_KORREKTUR: Wiederkehrende OCR/Extraktionsfehler
- WANDSTAERKE: Buero-spezifische Standard-Wandstaerken

SCHWELLENWERTE:
- Gleicher Fehler >2 Mal vom SELBEN Planungsbuero -> buero-spezifische Regel
- Gleicher Fehler >5 Mal GLOBAL -> globale Regel
- Regeln haben eine Konfidenz (0.0-1.0) basierend auf Haeufigkeit

AUSGABEFORMAT (JSON):
{
  "aktive_regeln": [
    {
      "id": "LR_001",
      "typ": "FENSTER_NOTATION",
      "planbuero": "Architekt Mustermann",
      "beschreibung": "Verwendet FE statt F fuer Fensterbezeichnungen",
      "anweisung": "Interpretiere 'FE' als Fensterbezeichnung",
      "konfidenz": 0.95,
      "anwendungen": 12,
      "global": false
    }
  ],
  "empfehlungen": [
    "Achte auf die spezielle Fensternotation dieses Bueros: FE statt F",
    "Standardwandstaerke fuer dieses Buero: 0.25 m statt 0.30 m"
  ],
  "neue_regeln": [],
  "zusammengefuehrte_muster": [
    "FE31, FE_31 und FE-31 als gleiches Muster erkannt"
  ],
  "warnungen": []
}

Antworte NUR mit validem JSON, ohne Markdown-Codebloecke."""


# ---------------------------------------------------------------------------
# JSON Parsing
# ---------------------------------------------------------------------------

def _parse_json_response(text: str) -> dict:
    """Robustes JSON-Parsing mit mehreren Fallback-Strategien."""
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

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

    if start != -1 and end != -1:
        candidate = text[start:end + 1]
        candidate = re.sub(r"//.*?\n", "\n", candidate)
        candidate = re.sub(r",\s*([}\]])", r"\1", candidate)
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            pass

    logger.error("JSON-Parsing fehlgeschlagen fuer Lern-Agent: %s", text[:300])
    return {
        "aktive_regeln": [],
        "empfehlungen": [],
        "neue_regeln": [],
        "warnungen": ["JSON-Parsing fehlgeschlagen"],
    }


# ---------------------------------------------------------------------------
# Hauptfunktion
# ---------------------------------------------------------------------------

async def run(kontext: dict, anweisung: str = "") -> dict:
    """
    Hauptfunktion des Lern-Agents (3-Stufen-Pipeline).

    Args:
        kontext: Dict mit:
            - 'planbuero' (str): Name des Planungsbueros
            - 'firma_id' (str): ID der Firma
            - 'bisherige_regeln' (list, optional): Bereits geladene Regeln
            - 'korrekturen' (list, optional): Neue manuelle Korrekturen
            - 'korrektur_historie' (list, optional): Historische Korrekturen
        anweisung: Optionale zusaetzliche Anweisung.

    Returns:
        Dict mit aktive_regeln, empfehlungen, neue_regeln, warnungen.
    """
    planbuero = kontext.get("planbuero", "Unbekannt")
    firma_id = kontext.get("firma_id", "")
    bisherige_regeln = kontext.get("bisherige_regeln", [])
    korrekturen = kontext.get("korrekturen", [])
    korrektur_historie = kontext.get("korrektur_historie", [])

    logger.info(
        "Lern-Agent gestartet: Planbuero='%s', Firma='%s', "
        "bisherige_regeln=%d, korrekturen=%d, historie=%d",
        planbuero, firma_id,
        len(bisherige_regeln), len(korrekturen), len(korrektur_historie),
    )

    # ===================================================================
    # STUFE 1: Supabase-Abfrage
    # ===================================================================
    logger.info("Stufe 1: Supabase-Abfrage fuer bestehende Regeln und Korrekturen")

    db_regeln, db_korrekturen = _query_supabase_rules(firma_id, planbuero)

    # Zusammenfuehren mit uebergebenen Daten (DB hat Vorrang bei Duplikaten)
    alle_regeln = list(db_regeln)
    existing_regel_ids = {r.get("id") for r in alle_regeln}
    for regel in bisherige_regeln:
        if regel.get("id") not in existing_regel_ids:
            alle_regeln.append(regel)

    alle_korrekturen = list(korrekturen)
    alle_korrektur_historie = list(korrektur_historie)
    # DB-Korrekturen zur Historie hinzufuegen
    existing_korr_ids = {k.get("id") for k in alle_korrektur_historie}
    for korr in db_korrekturen:
        if korr.get("id") not in existing_korr_ids:
            alle_korrektur_historie.append(korr)

    logger.info(
        "Nach Supabase-Merge: %d Regeln, %d neue Korrekturen, %d Historie",
        len(alle_regeln), len(alle_korrekturen), len(alle_korrektur_historie),
    )

    # Schneller Pfad: Keine Korrekturen und keine Historie -> nur Regeln zurueckgeben
    if not alle_korrekturen and not alle_korrektur_historie:
        if not alle_regeln:
            logger.info("Lern-Agent: Keine Regeln, Korrekturen oder Historie vorhanden")
            return {
                "aktive_regeln": [],
                "empfehlungen": [],
                "neue_regeln": [],
                "warnungen": [],
            }

        empfehlungen = _build_context_recommendations(alle_regeln, planbuero)
        logger.info(
            "Lern-Agent: %d bestehende Regeln geladen, %d Empfehlungen generiert (kein API-Call noetig)",
            len(alle_regeln), len(empfehlungen),
        )
        return {
            "aktive_regeln": alle_regeln,
            "empfehlungen": empfehlungen,
            "neue_regeln": [],
            "warnungen": [],
        }

    # ===================================================================
    # STUFE 2: Lokale Musteranalyse
    # ===================================================================
    logger.info("Stufe 2: Lokale Musteranalyse")

    muster_ergebnis = _analyze_patterns(
        alle_korrekturen, alle_korrektur_historie, planbuero, alle_regeln
    )

    lokal_neue_regeln = muster_ergebnis["neue_regeln"]
    muster_statistik = muster_ergebnis["muster_statistik"]
    lokal_empfehlungen = muster_ergebnis["empfehlungen"]

    logger.info(
        "Lokale Musteranalyse: %d neue Regeln vorgeschlagen, %d Empfehlungen",
        len(lokal_neue_regeln), len(lokal_empfehlungen),
    )

    # Wenn nur wenige Korrekturen und keine neuen Muster, kein API-Call noetig
    if not lokal_neue_regeln and len(alle_korrekturen) + len(alle_korrektur_historie) < 3:
        empfehlungen = _build_context_recommendations(alle_regeln, planbuero)
        empfehlungen.extend(lokal_empfehlungen)
        logger.info("Lern-Agent: Zu wenig Daten fuer Claude-Analyse, verwende lokale Ergebnisse")
        return {
            "aktive_regeln": alle_regeln,
            "empfehlungen": empfehlungen,
            "neue_regeln": [],
            "muster_statistik": muster_statistik,
            "warnungen": [],
        }

    # ===================================================================
    # STUFE 3: Claude-KI-Analyse
    # ===================================================================
    logger.info("Stufe 3: Claude-KI-Analyse fuer komplexe Mustererkennung")

    context_data = json.dumps({
        "planbuero": planbuero,
        "firma_id": firma_id,
        "bisherige_regeln": alle_regeln,
        "korrekturen": alle_korrekturen,
        "korrektur_historie": alle_korrektur_historie[:50],  # Limitiere auf 50 fuer Kontext
        "lokale_musteranalyse": muster_ergebnis,
    }, ensure_ascii=False, indent=2)

    user_message = f"""Analysiere die folgenden Lernregeln und Korrekturen fuer das Planungsbuero "{planbuero}".

ZUSAMMENFASSUNG:
- Bestehende Regeln: {len(alle_regeln)}
- Neue Korrekturen: {len(alle_korrekturen)}
- Historische Korrekturen: {len(alle_korrektur_historie)}
- Lokal vorgeschlagene neue Regeln: {len(lokal_neue_regeln)}

LOKALE MUSTERANALYSE hat bereits folgende Muster erkannt:
- {muster_statistik.get('einzigartige_signaturen', 0)} einzigartige Fehler-Signaturen
- {muster_statistik.get('bueros_mit_korrekturen', 0)} Bueros mit Korrekturen
- Fehlertyp-Verteilung: {json.dumps(muster_statistik.get('fehlertyp_verteilung', {}), ensure_ascii=False)}

{f"Zusaetzliche Anweisung: {anweisung}" if anweisung else ""}

VOLLSTAENDIGE DATEN:
{context_data}

AUFGABEN:
1. Pruefe die lokal vorgeschlagenen Regeln auf Sinnhaftigkeit
2. Erkenne semantische Muster die die lokale Analyse verpasst hat
   (z.B. verschiedene Schreibweisen desselben Fehlers zusammenfuehren)
3. Formuliere konkrete Empfehlungen fuer Parser, Geometrie und Kalkulations-Agent
4. Bestaetie oder korrigiere die Konfidenz-Werte der vorgeschlagenen Regeln

Antworte NUR mit validem JSON gemaess dem vorgegebenen Format."""

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

        logger.info(
            "Claude-Analyse: %d aktive Regeln, %d Empfehlungen, %d neue Regeln",
            len(result.get("aktive_regeln", [])),
            len(result.get("empfehlungen", [])),
            len(result.get("neue_regeln", [])),
        )

    except anthropic.APIError as e:
        logger.error("Anthropic API Fehler: %s - verwende lokale Ergebnisse", e)
        empfehlungen = _build_context_recommendations(alle_regeln, planbuero)
        empfehlungen.extend(lokal_empfehlungen)
        return {
            "aktive_regeln": alle_regeln,
            "empfehlungen": empfehlungen,
            "neue_regeln": lokal_neue_regeln,
            "muster_statistik": muster_statistik,
            "warnungen": [f"Claude-API nicht erreichbar ({e}), verwende nur lokale Musteranalyse"],
        }
    except Exception as e:
        logger.error("Unerwarteter Fehler im Lern-Agent: %s", e, exc_info=True)
        empfehlungen = _build_context_recommendations(alle_regeln, planbuero)
        return {
            "aktive_regeln": alle_regeln,
            "empfehlungen": empfehlungen,
            "neue_regeln": lokal_neue_regeln,
            "muster_statistik": muster_statistik,
            "warnungen": [f"Unerwarteter Fehler ({e}), verwende nur lokale Ergebnisse"],
        }

    # ===================================================================
    # Ergebnisse zusammenfuehren
    # ===================================================================

    result.setdefault("aktive_regeln", [])
    result.setdefault("empfehlungen", [])
    result.setdefault("neue_regeln", [])
    result.setdefault("warnungen", [])

    # Sicherstellen, dass alle bestehenden Regeln enthalten sind
    claude_regel_ids = {r.get("id") for r in result["aktive_regeln"]}
    for regel in alle_regeln:
        if regel.get("id") not in claude_regel_ids:
            result["aktive_regeln"].append(regel)

    # Lokal vorgeschlagene Regeln hinzufuegen, wenn Claude sie nicht hat
    claude_neue_sigs = {r.get("signatur", "") for r in result["neue_regeln"]}
    for lokal_regel in lokal_neue_regeln:
        if lokal_regel.get("signatur", "") not in claude_neue_sigs:
            result["neue_regeln"].append(lokal_regel)

    # Muster-Statistik anhaengen
    result["muster_statistik"] = muster_statistik

    logger.info(
        "Lern-Agent abgeschlossen: %d aktive Regeln, %d Empfehlungen, "
        "%d neue Regeln, %d Warnungen",
        len(result["aktive_regeln"]),
        len(result["empfehlungen"]),
        len(result["neue_regeln"]),
        len(result["warnungen"]),
    )

    return result
