"""
Kalkulations Agent - Produktionsreife Massenberechnung nach OENORM-Regeln.

ARCHITEKTUR (3-Stufen-Pipeline):
  Stufe 1: Lokale Vorberechnung aller Gewerke mit Python-Funktionen
           (Wandflaechen, Abzuege, Leibungen, Bodenbelag, Estrich, Fensterbank)
  Stufe 2: Claude-KI-Analyse fuer kontextuelle Entscheidungen
           (Raumzuordnung, Sonderfaelle, Plausibilitaetsbewertung)
  Stufe 3: Kreuzverifikation - Python prueft Claude's Ergebnisse,
           bei >5% Abweichung werden Werte korrigiert und Warnungen ergaenzt

Alle 7 Gewerke:
  1. Mauerwerk m3  2. Putz innen m2  3. Putz aussen m2  4. Maler m2
  5. Bodenbelag m2  6. Estrich m2  7. Fensterbaenke m
"""

import json
import logging
import math
import os
import re
import anthropic
from agents import get_anthropic_api_key as _get_api_key

logger = logging.getLogger(__name__)

MODEL = "claude-sonnet-4-20250514"

# ---------------------------------------------------------------------------
# OENORM Abzugsregeln - Schwellenwerte
# ---------------------------------------------------------------------------

OENORM_REGELN = {
    "mauerwerk": {
        "einheit": "m3",
        "beschreibung": "Mauerwerk (Volumen)",
        "schwellen": [
            {"bis": 0.5, "abzug": 0.0, "label": "kein Abzug (< 0,5 m2)"},
            {"bis": 3.0, "abzug": 0.5, "label": "halber Abzug (0,5-3,0 m2)"},
            {"bis": float("inf"), "abzug": 1.0, "label": "voller Abzug (> 3,0 m2)"},
        ],
    },
    "putz_innen": {
        "einheit": "m2",
        "beschreibung": "Putz Innen (Flaeche)",
        "schwellen": [
            {"bis": 2.5, "abzug": 0.0, "label": "kein Abzug (< 2,5 m2)"},
            {"bis": 10.0, "abzug": 0.5, "label": "halber Abzug (2,5-10,0 m2)"},
            {"bis": float("inf"), "abzug": 1.0, "label": "voller Abzug (> 10,0 m2)"},
        ],
    },
    "putz_aussen": {
        "einheit": "m2",
        "beschreibung": "Putz Aussen (Flaeche)",
        "schwellen": [
            {"bis": 2.5, "abzug": 0.0, "label": "kein Abzug (< 2,5 m2)"},
            {"bis": 10.0, "abzug": 0.5, "label": "halber Abzug (2,5-10,0 m2)"},
            {"bis": float("inf"), "abzug": 1.0, "label": "voller Abzug (> 10,0 m2)"},
        ],
    },
    "maler": {
        "einheit": "m2",
        "beschreibung": "Malerarbeiten / Anstrich (Flaeche)",
        "schwellen": [
            {"bis": 2.5, "abzug": 0.0, "label": "kein Abzug (< 2,5 m2)"},
            {"bis": 10.0, "abzug": 0.5, "label": "halber Abzug (2,5-10,0 m2)"},
            {"bis": float("inf"), "abzug": 1.0, "label": "voller Abzug (> 10,0 m2)"},
        ],
    },
    "fliesen": {
        "einheit": "m2",
        "beschreibung": "Fliesen / Plattenleger (Flaeche)",
        "schwellen": [
            {"bis": 0.1, "abzug": 0.0, "label": "kein Abzug (< 0,1 m2)"},
            {"bis": float("inf"), "abzug": 1.0, "label": "voller Abzug (>= 0,1 m2)"},
        ],
    },
    "bodenbelag": {
        "einheit": "m2",
        "beschreibung": "Bodenbelag (Raumflaeche)",
        "schwellen": [],  # keine Oeffnungsabzuege
    },
    "estrich": {
        "einheit": "m2",
        "beschreibung": "Estrich (Raumflaeche)",
        "schwellen": [],  # keine Oeffnungsabzuege
    },
    "fensterbank": {
        "einheit": "m",
        "beschreibung": "Fensterbank (Laufmeter)",
        "schwellen": [],
    },
}

# ---------------------------------------------------------------------------
# Lokale Berechnungsfunktionen
# ---------------------------------------------------------------------------


def _calculate_wandflaeche(umfang: float, hoehe: float) -> float:
    """Berechnet die Brutto-Wandflaeche eines Raumes.

    Args:
        umfang: Raumperimeter in Metern.
        hoehe: Raumhoehe in Metern.

    Returns:
        Wandflaeche in m2.
    """
    if umfang <= 0 or hoehe <= 0:
        return 0.0
    return round(umfang * hoehe, 4)


def _calculate_abzug(oeffnung_flaeche: float, gewerk: str) -> float:
    """Ermittelt den OENORM-Abzugsmultiplikator fuer eine Oeffnung.

    Args:
        oeffnung_flaeche: Flaeche der Oeffnung in m2.
        gewerk: Schluessel aus OENORM_REGELN (z.B. 'mauerwerk', 'putz_innen').

    Returns:
        Multiplikator: 0.0 (kein Abzug), 0.5 (halber Abzug) oder 1.0 (voller Abzug).
    """
    regel = OENORM_REGELN.get(gewerk)
    if not regel or not regel.get("schwellen"):
        return 0.0

    for schwelle in regel["schwellen"]:
        if oeffnung_flaeche < schwelle["bis"]:
            return schwelle["abzug"]
        # Spezialfall: exakt auf der oberen Grenze
        if oeffnung_flaeche == schwelle["bis"] and schwelle["abzug"] < 1.0:
            # Bei Gleichheit gilt die naechsthoehere Stufe bei Fliesen
            if gewerk == "fliesen":
                continue
            return schwelle["abzug"]

    return 1.0


def _get_abzug_label(oeffnung_flaeche: float, gewerk: str) -> str:
    """Gibt die textuelle Beschreibung der angewandten Abzugsregel zurueck."""
    regel = OENORM_REGELN.get(gewerk)
    if not regel or not regel.get("schwellen"):
        return "kein Abzug (Gewerk ohne Oeffnungsabzuege)"

    for schwelle in regel["schwellen"]:
        if oeffnung_flaeche < schwelle["bis"]:
            return schwelle["label"]

    return "voller Abzug"


def _calculate_laibung(wandstaerke: float, breite: float, hoehe: float) -> dict:
    """Berechnet Leibungsflaechen einer Oeffnung.

    Args:
        wandstaerke: Wandstaerke in Metern.
        breite: Oeffnungsbreite in Metern.
        hoehe: Oeffnungshoehe in Metern.

    Returns:
        Dict mit Einzelflaechen und Summe.
    """
    seitenleibung = 2.0 * wandstaerke * hoehe
    sturzleibung = wandstaerke * breite
    sohlbank_leibung = wandstaerke * breite

    gesamt = seitenleibung + sturzleibung + sohlbank_leibung

    return {
        "seitenleibung": round(seitenleibung, 4),
        "sturzleibung": round(sturzleibung, 4),
        "sohlbank_leibung": round(sohlbank_leibung, 4),
        "gesamt": round(gesamt, 4),
        "schritte": [
            f"Seitenleibungen: 2 x {wandstaerke:.2f} x {hoehe:.2f} = {seitenleibung:.4f} m2",
            f"Sturzleibung: {wandstaerke:.2f} x {breite:.2f} = {sturzleibung:.4f} m2",
            f"Sohlbank-/Fensterbankanschluss: {wandstaerke:.2f} x {breite:.2f} = {sohlbank_leibung:.4f} m2",
            f"Leibung gesamt: {gesamt:.4f} m2",
        ],
    }


def _extract_oeffnungen(geometrie: dict, raum_id: str) -> list[dict]:
    """Sammelt alle Oeffnungen (Fenster + Tueren) eines Raumes."""
    oeffnungen = []

    for fenster in geometrie.get("fenster", []):
        zuordnung = fenster.get("raum_referenz", fenster.get("raum_id", ""))
        if zuordnung == raum_id:
            breite_mm = fenster.get("breite_mm", fenster.get("breite", 0))
            hoehe_mm = fenster.get("hoehe_mm", fenster.get("hoehe", 0))
            # Konvertiere mm zu m falls noetig
            breite = breite_mm / 1000.0 if breite_mm > 10 else breite_mm
            hoehe = hoehe_mm / 1000.0 if hoehe_mm > 10 else hoehe_mm
            flaeche = breite * hoehe
            oeffnungen.append({
                "typ": "fenster",
                "bezeichnung": fenster.get("bezeichnung", "FE_?"),
                "breite_m": round(breite, 3),
                "hoehe_m": round(hoehe, 3),
                "flaeche_m2": round(flaeche, 4),
            })

    for tuer in geometrie.get("tueren", []):
        zuordnung = tuer.get("raum_referenz", tuer.get("raum_id", ""))
        if zuordnung == raum_id:
            breite_mm = tuer.get("breite_mm", tuer.get("breite", 0))
            hoehe_mm = tuer.get("hoehe_mm", tuer.get("hoehe", 0))
            breite = breite_mm / 1000.0 if breite_mm > 10 else breite_mm
            hoehe = hoehe_mm / 1000.0 if hoehe_mm > 10 else hoehe_mm
            if hoehe <= 0:
                hoehe = 2.10  # Standard-Tuerhoehe
            flaeche = breite * hoehe
            oeffnungen.append({
                "typ": "tuer",
                "bezeichnung": tuer.get("bezeichnung", "T_?"),
                "breite_m": round(breite, 3),
                "hoehe_m": round(hoehe, 3),
                "flaeche_m2": round(flaeche, 4),
            })

    return oeffnungen


def _local_pre_calculate(geometrie: dict, wandstaerke: float) -> dict:
    """Stufe 1: Vollstaendige lokale Vorberechnung aller Gewerke.

    Berechnet alle Positionen rein mathematisch, damit Claude's Ergebnisse
    spaeter gegengeprüft werden koennen.

    Returns:
        Dict mit allen vorberechneten Positionen und Zusammenfassung.
    """
    positionen = []
    zusammenfassung = {
        "mauerwerk_m3": 0.0,
        "putz_innen_m2": 0.0,
        "putz_aussen_m2": 0.0,
        "maler_m2": 0.0,
        "bodenbelag_m2": 0.0,
        "estrich_m2": 0.0,
        "fensterbank_m": 0.0,
    }
    warnungen = []
    pos_counter = 0

    raeume = geometrie.get("raeume", [])
    if not raeume:
        warnungen.append("Keine Raeume in den Geometriedaten gefunden")
        return {"positionen": positionen, "zusammenfassung": zusammenfassung, "warnungen": warnungen}

    for raum in raeume:
        raum_id = raum.get("id", raum.get("referenz", f"R{raeume.index(raum) + 1}"))
        raum_name = raum.get("name", raum.get("bezeichnung", "Unbekannt"))
        flaeche = raum.get("flaeche_m2", raum.get("flaeche", 0.0))
        umfang = raum.get("umfang_m", raum.get("umfang", 0.0))
        hoehe = raum.get("hoehe_m", raum.get("raumhoehe", raum.get("hoehe", 2.60)))
        ist_aussen = raum.get("aussenwand", raum.get("ist_aussen", False))

        # Hoehe-Konvertierung falls in mm
        if hoehe > 10:
            hoehe = hoehe / 1000.0

        # Umfang-Plausibilitaet: falls 0, aus Flaeche schaetzen (Quadrat-Annahme)
        if umfang <= 0 and flaeche > 0:
            umfang = 4.0 * math.sqrt(flaeche)
            warnungen.append(
                f"Raum {raum_id} ({raum_name}): Umfang fehlend, "
                f"geschaetzt als Quadrat: {umfang:.2f} m"
            )

        oeffnungen = _extract_oeffnungen(geometrie, raum_id)

        # --- Wandflaeche brutto ---
        wandflaeche_brutto = _calculate_wandflaeche(umfang, hoehe)

        # ===========================================================
        # GEWERK 1: Mauerwerk (m3)
        # ===========================================================
        schritte_mw = [f"Wandflaeche brutto: {umfang:.2f} m x {hoehe:.2f} m = {wandflaeche_brutto:.2f} m2"]
        abzug_summe_mw = 0.0

        for oeff in oeffnungen:
            mult = _calculate_abzug(oeff["flaeche_m2"], "mauerwerk")
            label = _get_abzug_label(oeff["flaeche_m2"], "mauerwerk")
            eff_abzug = oeff["flaeche_m2"] * mult
            abzug_summe_mw += eff_abzug

            schritte_mw.append(
                f"Oeffnung {oeff['bezeichnung']}: {oeff['breite_m']:.2f} x {oeff['hoehe_m']:.2f} = "
                f"{oeff['flaeche_m2']:.2f} m2 -> {label}, Abzug: {eff_abzug:.2f} m2"
            )

        wandflaeche_netto_mw = max(0.0, wandflaeche_brutto - abzug_summe_mw)
        volumen = wandflaeche_netto_mw * wandstaerke
        schritte_mw.append(f"Wandflaeche netto: {wandflaeche_brutto:.2f} - {abzug_summe_mw:.2f} = {wandflaeche_netto_mw:.2f} m2")
        schritte_mw.append(f"Volumen: {wandflaeche_netto_mw:.2f} x {wandstaerke:.2f} = {volumen:.2f} m3")

        pos_counter += 1
        positionen.append({
            "pos_nr": f"{pos_counter:02d}.01",
            "beschreibung": f"Mauerwerk {raum_name}",
            "raum_referenz": raum_id,
            "gewerk": "mauerwerk",
            "einheit": "m3",
            "berechnung": schritte_mw,
            "endsumme": round(volumen, 2),
            "konfidenz": 0.90,
        })
        zusammenfassung["mauerwerk_m3"] += round(volumen, 2)

        # ===========================================================
        # GEWERK 2 & 3: Putz innen / aussen (m2)
        # ===========================================================
        for putz_typ, putz_key, summ_key in [
            ("Putz innen", "putz_innen", "putz_innen_m2"),
            ("Putz aussen", "putz_aussen", "putz_aussen_m2"),
        ]:
            # Putz aussen nur fuer Aussenwand-Raeume
            if putz_key == "putz_aussen" and not ist_aussen:
                continue

            schritte_putz = [f"Wandflaeche brutto: {umfang:.2f} x {hoehe:.2f} = {wandflaeche_brutto:.2f} m2"]
            abzug_summe_putz = 0.0
            leibung_total = 0.0

            for oeff in oeffnungen:
                mult = _calculate_abzug(oeff["flaeche_m2"], putz_key)
                label = _get_abzug_label(oeff["flaeche_m2"], putz_key)
                eff_abzug = oeff["flaeche_m2"] * mult
                abzug_summe_putz += eff_abzug

                schritte_putz.append(
                    f"Oeffnung {oeff['bezeichnung']}: {oeff['flaeche_m2']:.2f} m2 -> {label}, Abzug: {eff_abzug:.2f} m2"
                )

                # Leibung berechnen
                leib = _calculate_laibung(wandstaerke, oeff["breite_m"], oeff["hoehe_m"])
                leibung_total += leib["gesamt"]
                schritte_putz.extend([f"  Leibung {oeff['bezeichnung']}: {s}" for s in leib["schritte"]])

            wandflaeche_netto = max(0.0, wandflaeche_brutto - abzug_summe_putz + leibung_total)
            schritte_putz.append(
                f"Netto: {wandflaeche_brutto:.2f} - {abzug_summe_putz:.2f} + {leibung_total:.2f} (Leibungen) = "
                f"{wandflaeche_netto:.2f} m2"
            )

            pos_counter += 1
            positionen.append({
                "pos_nr": f"{pos_counter:02d}.01",
                "beschreibung": f"{putz_typ} {raum_name}",
                "raum_referenz": raum_id,
                "gewerk": putz_key,
                "einheit": "m2",
                "berechnung": schritte_putz,
                "endsumme": round(wandflaeche_netto, 2),
                "konfidenz": 0.88,
            })
            zusammenfassung[summ_key] += round(wandflaeche_netto, 2)

        # ===========================================================
        # GEWERK 4: Maler / Anstrich (m2) - gleiche Regeln wie Putz innen
        # ===========================================================
        schritte_maler = [f"Wandflaeche brutto: {umfang:.2f} x {hoehe:.2f} = {wandflaeche_brutto:.2f} m2"]
        abzug_summe_maler = 0.0
        leibung_total_maler = 0.0

        for oeff in oeffnungen:
            mult = _calculate_abzug(oeff["flaeche_m2"], "maler")
            label = _get_abzug_label(oeff["flaeche_m2"], "maler")
            eff_abzug = oeff["flaeche_m2"] * mult
            abzug_summe_maler += eff_abzug

            schritte_maler.append(
                f"Oeffnung {oeff['bezeichnung']}: {oeff['flaeche_m2']:.2f} m2 -> {label}, Abzug: {eff_abzug:.2f} m2"
            )

            leib = _calculate_laibung(wandstaerke, oeff["breite_m"], oeff["hoehe_m"])
            leibung_total_maler += leib["gesamt"]
            schritte_maler.extend([f"  Leibung {oeff['bezeichnung']}: {s}" for s in leib["schritte"]])

        wandflaeche_maler = max(0.0, wandflaeche_brutto - abzug_summe_maler + leibung_total_maler)
        schritte_maler.append(
            f"Netto: {wandflaeche_brutto:.2f} - {abzug_summe_maler:.2f} + {leibung_total_maler:.2f} = "
            f"{wandflaeche_maler:.2f} m2"
        )

        pos_counter += 1
        positionen.append({
            "pos_nr": f"{pos_counter:02d}.01",
            "beschreibung": f"Maler / Anstrich {raum_name}",
            "raum_referenz": raum_id,
            "gewerk": "maler",
            "einheit": "m2",
            "berechnung": schritte_maler,
            "endsumme": round(wandflaeche_maler, 2),
            "konfidenz": 0.88,
        })
        zusammenfassung["maler_m2"] += round(wandflaeche_maler, 2)

        # ===========================================================
        # GEWERK 5: Bodenbelag (m2) - direkt Raumflaeche, kein Abzug
        # ===========================================================
        if flaeche > 0:
            pos_counter += 1
            positionen.append({
                "pos_nr": f"{pos_counter:02d}.01",
                "beschreibung": f"Bodenbelag {raum_name}",
                "raum_referenz": raum_id,
                "gewerk": "bodenbelag",
                "einheit": "m2",
                "berechnung": [f"Raumflaeche: {flaeche:.2f} m2 (kein Oeffnungsabzug)"],
                "endsumme": round(flaeche, 2),
                "konfidenz": 0.95,
            })
            zusammenfassung["bodenbelag_m2"] += round(flaeche, 2)

        # ===========================================================
        # GEWERK 6: Estrich (m2) - direkt Raumflaeche, kein Abzug
        # ===========================================================
        if flaeche > 0:
            pos_counter += 1
            positionen.append({
                "pos_nr": f"{pos_counter:02d}.01",
                "beschreibung": f"Estrich {raum_name}",
                "raum_referenz": raum_id,
                "gewerk": "estrich",
                "einheit": "m2",
                "berechnung": [f"Raumflaeche: {flaeche:.2f} m2 (kein Oeffnungsabzug)"],
                "endsumme": round(flaeche, 2),
                "konfidenz": 0.95,
            })
            zusammenfassung["estrich_m2"] += round(flaeche, 2)

    # ===========================================================
    # GEWERK 7: Fensterbank (m) - Summe aller Fensterbreiten
    # ===========================================================
    fensterbank_total = 0.0
    fb_schritte = []
    for fenster in geometrie.get("fenster", []):
        breite_mm = fenster.get("breite_mm", fenster.get("breite", 0))
        breite = breite_mm / 1000.0 if breite_mm > 10 else breite_mm
        if breite > 0:
            bezeichnung = fenster.get("bezeichnung", "FE_?")
            fensterbank_total += breite
            fb_schritte.append(f"{bezeichnung}: {breite:.2f} m")

    if fensterbank_total > 0:
        fb_schritte.append(f"Summe Fensterbank: {fensterbank_total:.2f} m")
        pos_counter += 1
        positionen.append({
            "pos_nr": f"{pos_counter:02d}.01",
            "beschreibung": "Fensterbaenke gesamt",
            "raum_referenz": "alle",
            "gewerk": "fensterbank",
            "einheit": "m",
            "berechnung": fb_schritte,
            "endsumme": round(fensterbank_total, 2),
            "konfidenz": 0.92,
        })
        zusammenfassung["fensterbank_m"] = round(fensterbank_total, 2)

    # Runde Zusammenfassung
    for key in zusammenfassung:
        zusammenfassung[key] = round(zusammenfassung[key], 2)

    return {
        "positionen": positionen,
        "zusammenfassung": zusammenfassung,
        "warnungen": warnungen,
    }


def _verify_calculations(claude_result: dict, local_result: dict) -> list[str]:
    """Stufe 3: Kreuzverifikation von Claude's Ergebnis gegen lokale Berechnung.

    Vergleicht Zusammenfassungswerte und Einzelpositionen.
    Bei >5% Abweichung wird eine Warnung erzeugt und der lokale Wert eingesetzt.

    Returns:
        Liste von Warnungen bei Abweichungen.
    """
    TOLERANCE = 0.05  # 5% Toleranz
    warnungen = []
    corrected = False

    claude_zusammenfassung = claude_result.get("zusammenfassung", {})
    local_zusammenfassung = local_result.get("zusammenfassung", {})

    for key in local_zusammenfassung:
        local_val = local_zusammenfassung.get(key, 0.0)
        claude_val = claude_zusammenfassung.get(key, 0.0)

        if local_val == 0 and claude_val == 0:
            continue

        reference = max(abs(local_val), abs(claude_val), 0.001)
        abweichung = abs(local_val - claude_val) / reference

        if abweichung > TOLERANCE:
            warnungen.append(
                f"VERIFIKATION: {key} - Claude: {claude_val:.2f}, "
                f"Lokal: {local_val:.2f}, Abweichung: {abweichung:.1%} "
                f"-> Korrigiert auf lokalen Wert"
            )
            claude_zusammenfassung[key] = local_val
            corrected = True

    # Pruefe Einzelpositionen
    claude_positionen = claude_result.get("positionen", [])
    local_positionen = local_result.get("positionen", [])

    # Erstelle Lookup nach raum_referenz + gewerk
    local_lookup = {}
    for pos in local_positionen:
        lookup_key = f"{pos.get('raum_referenz', '')}_{pos.get('gewerk', '')}"
        local_lookup[lookup_key] = pos

    for claude_pos in claude_positionen:
        lookup_key = f"{claude_pos.get('raum_referenz', '')}_{claude_pos.get('gewerk', '')}"
        local_pos = local_lookup.get(lookup_key)

        if local_pos is None:
            continue

        c_val = claude_pos.get("endsumme", 0.0)
        l_val = local_pos.get("endsumme", 0.0)

        if c_val == 0 and l_val == 0:
            continue

        reference = max(abs(c_val), abs(l_val), 0.001)
        abweichung = abs(c_val - l_val) / reference

        if abweichung > TOLERANCE:
            warnungen.append(
                f"VERIFIKATION Position {claude_pos.get('pos_nr', '?')} "
                f"({claude_pos.get('beschreibung', '')}): "
                f"Claude={c_val:.2f}, Lokal={l_val:.2f}, "
                f"Abweichung={abweichung:.1%} -> Korrigiert"
            )
            claude_pos["endsumme"] = l_val
            claude_pos["berechnung"] = local_pos.get("berechnung", claude_pos.get("berechnung", []))
            claude_pos.setdefault("verifikation", {})
            claude_pos["verifikation"] = {
                "claude_original": c_val,
                "lokal_berechnet": l_val,
                "abweichung_prozent": round(abweichung * 100, 1),
                "korrigiert": True,
            }
            corrected = True

    if corrected:
        warnungen.insert(0, "ACHTUNG: Claude-Ergebnisse wurden durch lokale Verifikation korrigiert (Abweichung >5%)")

    return warnungen


# ---------------------------------------------------------------------------
# System-Prompt fuer Claude (Stufe 2)
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """Du bist ein spezialisierter KI-Agent fuer die Massenermittlung (Quantity Surveying) nach oesterreichischen OENORM-Standards.

Du erhaeltst Geometriedaten (Raeume, Fenster, Tueren) UND eine lokale Vorberechnung.
Deine Aufgabe ist es, die Vorberechnung zu verfeinern, kontextuelle Entscheidungen zu treffen
und Sonderfaelle zu beruecksichtigen, die rein mathematisch nicht erfasst werden.

OENORM ABZUGSREGELN FUER OEFFNUNGEN:

1. MAUERWERK (m3):
   - Oeffnung < 0,5 m2: KEIN Abzug (0%)
   - Oeffnung 0,5 - 3,0 m2: HALBER Abzug (50%)
   - Oeffnung > 3,0 m2: VOLLER Abzug (100%)
   Formel: Netto-Wandflaeche x Wandstaerke = Volumen

2. PUTZ INNEN (m2):
   - Oeffnung < 2,5 m2: KEIN Abzug (0%)
   - Oeffnung 2,5 - 10,0 m2: HALBER Abzug (50%)
   - Oeffnung > 10,0 m2: VOLLER Abzug (100%)
   PLUS Leibungsflaechen addieren!

3. PUTZ AUSSEN (m2):
   - Gleiche Abzugsregeln wie Putz innen
   - Nur fuer Aussenwand-Raeume berechnen
   PLUS Leibungsflaechen addieren!

4. MALER / ANSTRICH (m2):
   - Oeffnung < 2,5 m2: KEIN Abzug (0%)
   - Oeffnung 2,5 - 10,0 m2: HALBER Abzug (50%)
   - Oeffnung > 10,0 m2: VOLLER Abzug (100%)
   PLUS Leibungsflaechen addieren!

5. FLIESEN (m2):
   - Oeffnung < 0,1 m2: KEIN Abzug (0%)
   - Oeffnung >= 0,1 m2: VOLLER Abzug (100%)
   Typisch in Nassraeumen (Bad, WC, Kueche)

6. BODENBELAG (m2):
   - Direkte Raumflaeche, KEIN Oeffnungsabzug

7. ESTRICH (m2):
   - Direkte Raumflaeche, KEIN Oeffnungsabzug

8. FENSTERBANK (m):
   - Summe aller Fensterbreiten als Laufmeter

LEIBUNGSBERECHNUNG pro Oeffnung:
- Seitenleibungen: 2 x (Wandstaerke x Oeffnungshoehe)
- Sturzleibung: 1 x (Wandstaerke x Oeffnungsbreite)
- Sohlbank-/Fensterbankanschluss: 1 x (Wandstaerke x Oeffnungsbreite)
- Wandstaerke Standard: 0,30 m wenn nicht anders angegeben

KONTEXTUELLE ENTSCHEIDUNGEN die du treffen sollst:
- Welche Raeume bekommen Fliesen? (Bad, WC, Kueche typisch)
- Welche Waende sind Aussenwaende? (wenn nicht explizit markiert)
- Gibt es Sonderkonstruktionen (Dachschraegen, Nischen)?
- Sind alle Oeffnungen plausibel zugeordnet?

AUSGABEFORMAT (JSON):
{
  "positionen": [
    {
      "pos_nr": "01.01",
      "beschreibung": "Mauerwerk Wohnzimmer - Aussenwand",
      "raum_referenz": "R1",
      "berechnung": [
        "Wandflaeche brutto: 20.40 m x 2.60 m = 53.04 m2",
        "Oeffnung FE_31: 1.20 x 1.50 = 1.80 m2 -> halber Abzug: 0.90 m2",
        "Wandflaeche netto: 53.04 - 0.90 = 52.14 m2",
        "Volumen: 52.14 x 0.30 = 15.64 m3"
      ],
      "endsumme": 15.64,
      "einheit": "m3",
      "gewerk": "mauerwerk",
      "konfidenz": 0.90
    }
  ],
  "zusammenfassung": {
    "mauerwerk_m3": 15.64,
    "putz_innen_m2": 120.50,
    "putz_aussen_m2": 85.30,
    "maler_m2": 120.50,
    "bodenbelag_m2": 65.00,
    "estrich_m2": 65.00,
    "fensterbank_m": 8.40
  },
  "kontextuelle_entscheidungen": [
    "Bad und WC erhalten Fliesen-Positionen",
    "Nordwand als Aussenwand identifiziert"
  ],
  "warnungen": [],
  "gesamt_konfidenz": 0.88
}

WICHTIG:
- Jede Berechnung MUSS nachvollziehbare Schritte enthalten (berechnung-Array)
- Immer die richtige Abzugsregel anwenden und dokumentieren
- Bei fehlender Wandstaerke: Standard 0.30 m verwenden und warnen
- Leibungsflaechen zum Putz/Maler ADDIEREN (nicht subtrahieren!)
- Negative Werte sind NICHT erlaubt - mindestens 0.0
- Beruecksichtige die lokale Vorberechnung als Basis

Antworte NUR mit validem JSON, ohne Markdown-Codebloecke."""


# ---------------------------------------------------------------------------
# JSON Parsing
# ---------------------------------------------------------------------------

def _parse_json_response(text: str) -> dict:
    """Robustes JSON-Parsing mit mehreren Fallback-Strategien."""
    # Versuch 1: Direktes Parsing
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Versuch 2: Markdown-Codeblock extrahieren
    match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass

    # Versuch 3: Erstes vollstaendiges JSON-Objekt finden
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(text[start:end + 1])
        except json.JSONDecodeError:
            pass

    # Versuch 4: Zeilenweise bereinigen (Kommentare, trailing commas)
    if start != -1 and end != -1:
        candidate = text[start:end + 1]
        # Entferne einzeilige Kommentare
        candidate = re.sub(r"//.*?\n", "\n", candidate)
        # Entferne trailing commas vor }]
        candidate = re.sub(r",\s*([}\]])", r"\1", candidate)
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            pass

    logger.error("JSON-Parsing fehlgeschlagen fuer Kalkulations-Agent: %s", text[:300])
    return {
        "positionen": [],
        "zusammenfassung": {},
        "warnungen": ["JSON-Parsing fehlgeschlagen - verwende lokale Berechnung"],
        "gesamt_konfidenz": 0.0,
    }


# ---------------------------------------------------------------------------
# Hauptfunktion
# ---------------------------------------------------------------------------

async def run(kontext: dict, anweisung: str = "") -> dict:
    """
    Hauptfunktion des Kalkulations-Agents (3-Stufen-Pipeline).

    Args:
        kontext: Dict mit 'geometrie_ergebnis' (Ausgabe des Geometrie-Agents).
                 Optional: 'wandstaerke_m' (Standard: 0.30).
        anweisung: Optionale zusaetzliche Anweisung (z.B. Lernregeln).

    Returns:
        Dict mit positionen, zusammenfassung, warnungen, gesamt_konfidenz.
    """
    geometrie = kontext.get("geometrie_ergebnis", {})
    if not geometrie or (not geometrie.get("raeume") and not geometrie.get("fenster")):
        logger.warning("Kalkulations-Agent: Keine Geometriedaten erhalten")
        return {
            "positionen": [],
            "zusammenfassung": {},
            "warnungen": ["Keine Geometriedaten erhalten"],
            "gesamt_konfidenz": 0.0,
        }

    wandstaerke = kontext.get("wandstaerke_m", 0.30)
    logger.info(
        "Kalkulations-Agent gestartet: %d Raeume, %d Fenster, %d Tueren, Wandstaerke=%.2f m",
        len(geometrie.get("raeume", [])),
        len(geometrie.get("fenster", [])),
        len(geometrie.get("tueren", [])),
        wandstaerke,
    )

    # ===================================================================
    # STUFE 1: Lokale Vorberechnung
    # ===================================================================
    logger.info("Stufe 1: Lokale Vorberechnung aller 7 Gewerke")
    local_result = _local_pre_calculate(geometrie, wandstaerke)

    logger.info(
        "Lokale Vorberechnung: %d Positionen, MW=%.2f m3, PI=%.2f m2, BB=%.2f m2",
        len(local_result["positionen"]),
        local_result["zusammenfassung"].get("mauerwerk_m3", 0),
        local_result["zusammenfassung"].get("putz_innen_m2", 0),
        local_result["zusammenfassung"].get("bodenbelag_m2", 0),
    )

    if local_result.get("warnungen"):
        for w in local_result["warnungen"]:
            logger.warning("Lokale Vorberechnung: %s", w)

    # ===================================================================
    # STUFE 2: Claude-KI-Analyse fuer kontextuelle Verfeinerung
    # ===================================================================
    logger.info("Stufe 2: Claude-KI-Analyse fuer kontextuelle Verfeinerung")

    geometrie_data = json.dumps(geometrie, ensure_ascii=False, indent=2)
    local_data = json.dumps(local_result, ensure_ascii=False, indent=2)

    user_message = f"""Berechne die Baumengen (Massenermittlung) basierend auf den folgenden Geometriedaten.

Wandstaerke (Standard): {wandstaerke} m
Anzahl Raeume: {len(geometrie.get("raeume", []))}
Anzahl Fenster: {len(geometrie.get("fenster", []))}
Anzahl Tueren: {len(geometrie.get("tueren", []))}

{f"Zusaetzliche Anweisung: {anweisung}" if anweisung else ""}

LOKALE VORBERECHNUNG (als Basis - bitte pruefen und verfeinern):
{local_data}

GEOMETRIEDATEN:
{geometrie_data}

Aufgaben:
1. Pruefe die lokale Vorberechnung auf Vollstaendigkeit und Korrektheit
2. Ergaenze kontextuelle Entscheidungen (z.B. Fliesen nur in Nassraeumen)
3. Identifiziere Sonderfaelle die die lokale Berechnung nicht abdeckt
4. Berechne ALLE Positionen fuer ALLE 7 Gewerke
5. Dokumentiere jeden Berechnungsschritt nachvollziehbar im berechnung-Array

Antworte NUR mit validem JSON gemaess dem vorgegebenen Format."""

    try:
        client = anthropic.AsyncAnthropic(
            api_key=_get_api_key(),
        )

        response = await client.messages.create(
            model=MODEL,
            max_tokens=16384,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_message}],
        )

        raw_text = response.content[0].text if response.content else ""
        claude_result = _parse_json_response(raw_text)

        logger.info(
            "Claude-Ergebnis: %d Positionen, Konfidenz: %.0f%%",
            len(claude_result.get("positionen", [])),
            claude_result.get("gesamt_konfidenz", 0) * 100,
        )

    except anthropic.APIError as e:
        logger.error("Anthropic API Fehler in Stufe 2: %s - verwende lokale Berechnung", e)
        # Bei API-Fehler: lokale Berechnung als Ergebnis verwenden
        local_result["warnungen"].append(f"Claude-API nicht erreichbar ({e}), verwende rein lokale Berechnung")
        local_result["gesamt_konfidenz"] = 0.70
        return local_result
    except Exception as e:
        logger.error("Unerwarteter Fehler in Stufe 2: %s - verwende lokale Berechnung", e, exc_info=True)
        local_result["warnungen"].append(f"Fehler in Claude-Analyse ({e}), verwende rein lokale Berechnung")
        local_result["gesamt_konfidenz"] = 0.65
        return local_result

    # ===================================================================
    # STUFE 3: Kreuzverifikation
    # ===================================================================
    logger.info("Stufe 3: Kreuzverifikation Claude vs. Lokal")

    # Sicherstelle, dass Claude-Ergebnis Grundstruktur hat
    claude_result.setdefault("positionen", [])
    claude_result.setdefault("zusammenfassung", {})
    claude_result.setdefault("warnungen", [])
    claude_result.setdefault("gesamt_konfidenz", 0.0)

    # Falls Claude keine Positionen lieferte, verwende lokale
    if not claude_result["positionen"]:
        logger.warning("Claude lieferte keine Positionen, verwende lokale Berechnung")
        claude_result["positionen"] = local_result["positionen"]
        claude_result["zusammenfassung"] = local_result["zusammenfassung"]
        claude_result["warnungen"].append("Claude lieferte keine Positionen - lokale Berechnung verwendet")

    # Kreuzverifikation
    verifikations_warnungen = _verify_calculations(claude_result, local_result)
    if verifikations_warnungen:
        claude_result["warnungen"].extend(verifikations_warnungen)
        logger.warning(
            "Verifikation fand %d Abweichungen, Werte wurden korrigiert",
            len(verifikations_warnungen),
        )

    # Validiere: keine negativen Endsummen
    for pos in claude_result["positionen"]:
        if pos.get("endsumme", 0) < 0:
            pos["endsumme"] = 0.0
            claude_result["warnungen"].append(
                f"Position {pos.get('pos_nr', '?')}: Negativer Wert auf 0 korrigiert"
            )

    # Fuege lokale Vorberechnung als Referenz hinzu
    claude_result["lokale_vorberechnung"] = local_result["zusammenfassung"]

    logger.info(
        "Kalkulations-Agent abgeschlossen: %d Positionen, %d Warnungen, Konfidenz: %.0f%%",
        len(claude_result["positionen"]),
        len(claude_result["warnungen"]),
        claude_result["gesamt_konfidenz"] * 100,
    )

    return claude_result
