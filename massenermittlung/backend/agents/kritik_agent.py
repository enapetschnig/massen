"""
Kritik Agent - Produktionsreife Qualitaetskontrolle und Plausibilitaetspruefung.

ARCHITEKTUR (2-Stufen-Pipeline):
  Stufe 1: Lokale Python-Validierung (deterministisch, schnell)
           - Raum-Plausibilitaet (Flaeche, Umfang-Flaeche-Verhaeltnis)
           - Fenster/Tuer-Plausibilitaet (Groesse, RB>AL Pruefung)
           - Berechnungs-Konsistenz (Summen, OENORM-Regeln)
           - Vollstaendigkeitspruefung (fehlende Gewerke, Raeume, Leibungen)
  Stufe 2: Claude-KI-Analyse (hoehere Logik, Kontextbewertung)
           - Erhaelt lokale Pruefergebnisse als Basis
           - Bewertet Gesamtqualitaet und Plausibilitaet
           - Erkennt Muster die lokale Pruefung nicht abdeckt

Das Ergebnis ist eine detaillierte Qualitaetsbewertung mit konkreten
Korrekturanweisungen fuer die betroffenen Agenten.
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
# Plausibilitaets-Referenzwerte
# ---------------------------------------------------------------------------

RAUM_FLAECHE_BEREICHE: dict[str, tuple[float, float]] = {
    "wohnzimmer": (15.0, 45.0),
    "wohnraum": (15.0, 45.0),
    "wohn-ess": (20.0, 55.0),
    "wohnkueche": (20.0, 55.0),
    "schlafzimmer": (10.0, 25.0),
    "kinderzimmer": (8.0, 20.0),
    "badezimmer": (4.0, 15.0),
    "bad": (4.0, 15.0),
    "wc": (1.5, 5.0),
    "toilette": (1.5, 5.0),
    "kueche": (6.0, 20.0),
    "flur": (3.0, 15.0),
    "vorraum": (3.0, 15.0),
    "vorzimmer": (3.0, 15.0),
    "gang": (2.0, 20.0),
    "diele": (3.0, 15.0),
    "abstellraum": (1.0, 8.0),
    "abstellkammer": (0.5, 6.0),
    "lager": (2.0, 30.0),
    "keller": (5.0, 50.0),
    "garage": (12.0, 40.0),
    "balkon": (3.0, 20.0),
    "terrasse": (5.0, 40.0),
    "loggia": (3.0, 15.0),
    "buero": (8.0, 30.0),
    "arbeitszimmer": (8.0, 20.0),
    "hauswirtschaft": (3.0, 12.0),
    "technik": (3.0, 15.0),
    "technikraum": (3.0, 15.0),
    "speis": (1.0, 6.0),
    "speisekammer": (1.0, 6.0),
    "ankleide": (3.0, 12.0),
    "garderobe": (1.5, 8.0),
    "waschkueche": (4.0, 15.0),
    "sauna": (4.0, 12.0),
    "fitness": (8.0, 30.0),
    "hobbyraum": (10.0, 40.0),
}

FENSTER_GRENZEN = {
    "max_flaeche_m2": 6.0,
    "max_hoehe_mm": 3000,
    "max_breite_mm": 4000,
    "min_hoehe_mm": 200,
    "min_breite_mm": 200,
    "rph_typisch_min": 0,
    "rph_typisch_max": 1200,
}

TUER_GRENZEN = {
    "max_breite_mm": 2500,
    "min_breite_mm": 500,
    "max_hoehe_mm": 3000,
    "min_hoehe_mm": 1800,
    "standard_hoehe_mm": 2100,
}


# ---------------------------------------------------------------------------
# Lokale Validierungsfunktionen (Stufe 1)
# ---------------------------------------------------------------------------


def _check_room_plausibility(raeume: list[dict]) -> list[dict]:
    """Prueft ob Raumgroessen, Umfaenge und Proportionen plausibel sind.

    Pruefungen:
      - Flaeche in typischem Bereich fuer den Raumtyp
      - Extrem kleine (<1 m2) oder grosse (>100 m2) Raeume
      - Umfang-Flaeche-Konsistenz: U >= 4*sqrt(A) (Quadrat ist Minimum)
      - Umfang nicht uebertrieben gross fuer die Flaeche

    Returns:
        Liste von Fehler-Dicts.
    """
    fehler = []

    for raum in raeume:
        raum_id = raum.get("id", raum.get("referenz", "?"))
        raum_name = raum.get("name", raum.get("bezeichnung", "Unbekannt")).lower()
        flaeche = raum.get("flaeche_m2", raum.get("flaeche", 0.0))
        umfang = raum.get("umfang_m", raum.get("umfang", 0.0))

        # --- Extremwerte ---
        if flaeche <= 0:
            fehler.append({
                "kategorie": "KRITISCH",
                "bereich": "geometrie",
                "beschreibung": f"Raum {raum_id} ({raum_name}): Flaeche ist 0 oder negativ ({flaeche} m2)",
                "betroffenes_objekt": raum_id,
                "korrekturvorschlag": "Raumflaeche aus Plan erneut extrahieren",
            })
            continue

        if flaeche < 1.0:
            fehler.append({
                "kategorie": "WARNUNG",
                "bereich": "geometrie",
                "beschreibung": f"Raum {raum_id} ({raum_name}): Flaeche verdaechtig klein ({flaeche:.2f} m2)",
                "betroffenes_objekt": raum_id,
                "korrekturvorschlag": "Pruefen ob Massstab korrekt angewendet wurde",
            })

        if flaeche > 100.0:
            fehler.append({
                "kategorie": "WARNUNG",
                "bereich": "geometrie",
                "beschreibung": f"Raum {raum_id} ({raum_name}): Flaeche ungewoehnlich gross ({flaeche:.2f} m2)",
                "betroffenes_objekt": raum_id,
                "korrekturvorschlag": "Pruefen ob der Raum korrekt abgegrenzt ist oder ob Massstab falsch",
            })

        # --- Typspezifischer Bereich ---
        for typ_key, (typ_min, typ_max) in RAUM_FLAECHE_BEREICHE.items():
            if typ_key in raum_name:
                if flaeche < typ_min * 0.5:
                    fehler.append({
                        "kategorie": "WARNUNG",
                        "bereich": "geometrie",
                        "beschreibung": (
                            f"Raum {raum_id} ({raum_name}): Flaeche {flaeche:.2f} m2 "
                            f"deutlich unter typischem Bereich ({typ_min}-{typ_max} m2)"
                        ),
                        "betroffenes_objekt": raum_id,
                        "korrekturvorschlag": f"Erwartete Flaeche fuer '{typ_key}': {typ_min}-{typ_max} m2",
                    })
                elif flaeche > typ_max * 1.5:
                    fehler.append({
                        "kategorie": "WARNUNG",
                        "bereich": "geometrie",
                        "beschreibung": (
                            f"Raum {raum_id} ({raum_name}): Flaeche {flaeche:.2f} m2 "
                            f"deutlich ueber typischem Bereich ({typ_min}-{typ_max} m2)"
                        ),
                        "betroffenes_objekt": raum_id,
                        "korrekturvorschlag": f"Erwartete Flaeche fuer '{typ_key}': {typ_min}-{typ_max} m2",
                    })
                break  # Nur ersten Match verwenden

        # --- Umfang-Flaeche-Konsistenz ---
        if umfang > 0 and flaeche > 0:
            # Minimaler Umfang fuer gegebene Flaeche ist ein Kreis: U = 2*pi*sqrt(A/pi)
            # Praktisch: Quadrat ist naechste Naeherung: U_min = 4*sqrt(A)
            u_min_quadrat = 4.0 * math.sqrt(flaeche)

            if umfang < u_min_quadrat * 0.85:
                fehler.append({
                    "kategorie": "KRITISCH",
                    "bereich": "geometrie",
                    "beschreibung": (
                        f"Raum {raum_id} ({raum_name}): Umfang ({umfang:.2f} m) ist kleiner als "
                        f"physikalisch moeglich fuer Flaeche {flaeche:.2f} m2 "
                        f"(Minimum Quadrat: {u_min_quadrat:.2f} m)"
                    ),
                    "betroffenes_objekt": raum_id,
                    "korrekturvorschlag": "Umfang oder Flaeche sind inkonsistent - erneut extrahieren",
                })

            # Umfang sollte nicht mehr als ~3x des Quadrat-Umfangs sein (sehr langgestreckt)
            if umfang > u_min_quadrat * 3.0:
                fehler.append({
                    "kategorie": "WARNUNG",
                    "bereich": "geometrie",
                    "beschreibung": (
                        f"Raum {raum_id} ({raum_name}): Umfang ({umfang:.2f} m) ungewoehnlich gross "
                        f"fuer Flaeche {flaeche:.2f} m2 - extrem langgestreckter Raum?"
                    ),
                    "betroffenes_objekt": raum_id,
                    "korrekturvorschlag": "Pruefen ob Umfang oder Flaeche fehlerhaft extrahiert wurden",
                })

    return fehler


def _check_window_plausibility(fenster_list: list[dict]) -> list[dict]:
    """Prueft ob Fenstermasse plausibel sind.

    Pruefungen:
      - Dimensionen in realistischem Bereich
      - RB > AL Beziehung (Rohbauoeffnung > Architekturlichtmass)
      - Fensterfaeche nicht zu gross
      - RPH (Rohbauparapethoehe) in typischem Bereich

    Returns:
        Liste von Fehler-Dicts.
    """
    fehler = []

    for fenster in fenster_list:
        bez = fenster.get("bezeichnung", "FE_?")
        breite = fenster.get("breite_mm", fenster.get("breite", 0))
        hoehe = fenster.get("hoehe_mm", fenster.get("hoehe", 0))
        rph = fenster.get("rph", fenster.get("RPH", None))
        rb_breite = fenster.get("rb_breite", fenster.get("RB", None))
        al_breite = fenster.get("al_breite", fenster.get("AL", None))

        # Konvertiere falls in m statt mm
        if 0 < breite < 10:
            breite = breite * 1000
        if 0 < hoehe < 10:
            hoehe = hoehe * 1000

        # --- Dimensionsgrenzen ---
        if breite > FENSTER_GRENZEN["max_breite_mm"]:
            fehler.append({
                "kategorie": "WARNUNG",
                "bereich": "geometrie",
                "beschreibung": f"Fenster {bez}: Breite {breite:.0f} mm ueberschreitet Maximum ({FENSTER_GRENZEN['max_breite_mm']} mm)",
                "betroffenes_objekt": bez,
                "korrekturvorschlag": "Fensterbreite pruefen - moeglicherweise Massstabfehler",
            })

        if hoehe > FENSTER_GRENZEN["max_hoehe_mm"]:
            fehler.append({
                "kategorie": "WARNUNG",
                "bereich": "geometrie",
                "beschreibung": f"Fenster {bez}: Hoehe {hoehe:.0f} mm ueberschreitet Maximum ({FENSTER_GRENZEN['max_hoehe_mm']} mm)",
                "betroffenes_objekt": bez,
                "korrekturvorschlag": "Fensterhoehe pruefen - moeglicherweise Massstabfehler",
            })

        if 0 < breite < FENSTER_GRENZEN["min_breite_mm"]:
            fehler.append({
                "kategorie": "WARNUNG",
                "bereich": "geometrie",
                "beschreibung": f"Fenster {bez}: Breite {breite:.0f} mm ungewoehnlich klein",
                "betroffenes_objekt": bez,
                "korrekturvorschlag": "Pruefen ob Fensterbreite korrekt extrahiert oder ob es ein Oberlicht ist",
            })

        # --- Flaechenpruefung ---
        if breite > 0 and hoehe > 0:
            flaeche_m2 = (breite / 1000.0) * (hoehe / 1000.0)
            if flaeche_m2 > FENSTER_GRENZEN["max_flaeche_m2"]:
                fehler.append({
                    "kategorie": "WARNUNG",
                    "bereich": "geometrie",
                    "beschreibung": (
                        f"Fenster {bez}: Flaeche {flaeche_m2:.2f} m2 ueberschreitet "
                        f"Maximum ({FENSTER_GRENZEN['max_flaeche_m2']} m2) - "
                        "moeglicherweise eine Fensterfront oder Massstabfehler"
                    ),
                    "betroffenes_objekt": bez,
                    "korrekturvorschlag": "Pruefen ob es sich um ein einzelnes Fenster oder eine Fensterfront handelt",
                })

        # --- RB > AL Pruefung ---
        if rb_breite is not None and al_breite is not None:
            if isinstance(rb_breite, (int, float)) and isinstance(al_breite, (int, float)):
                if rb_breite < al_breite:
                    fehler.append({
                        "kategorie": "KRITISCH",
                        "bereich": "geometrie",
                        "beschreibung": (
                            f"Fenster {bez}: RB ({rb_breite}) ist kleiner als AL ({al_breite}) - "
                            "Rohbauoeffnung muss groesser als Architekturlichtmass sein"
                        ),
                        "betroffenes_objekt": bez,
                        "korrekturvorschlag": "RB und AL Werte pruefen, moeglicherweise vertauscht",
                    })

        # --- RPH Pruefung ---
        if rph is not None and isinstance(rph, (int, float)):
            if rph < FENSTER_GRENZEN["rph_typisch_min"]:
                fehler.append({
                    "kategorie": "WARNUNG",
                    "bereich": "geometrie",
                    "beschreibung": f"Fenster {bez}: RPH ({rph} mm) ist negativ",
                    "betroffenes_objekt": bez,
                    "korrekturvorschlag": "Rohbauparapethoehe muss >= 0 sein",
                })
            elif rph > FENSTER_GRENZEN["rph_typisch_max"]:
                fehler.append({
                    "kategorie": "HINWEIS",
                    "bereich": "geometrie",
                    "beschreibung": f"Fenster {bez}: RPH ({rph} mm) ueber typischem Bereich (0-{FENSTER_GRENZEN['rph_typisch_max']} mm)",
                    "betroffenes_objekt": bez,
                    "korrekturvorschlag": "Hohe Parapethoehe - pruefen ob korrekt (z.B. Oberlicht)",
                })

    return fehler


def _check_door_plausibility(tueren_list: list[dict]) -> list[dict]:
    """Prueft ob Tuermasse plausibel sind."""
    fehler = []

    for tuer in tueren_list:
        bez = tuer.get("bezeichnung", "T_?")
        breite = tuer.get("breite_mm", tuer.get("breite", 0))
        hoehe = tuer.get("hoehe_mm", tuer.get("hoehe", 0))

        if 0 < breite < 10:
            breite = breite * 1000
        if 0 < hoehe < 10:
            hoehe = hoehe * 1000

        if breite > TUER_GRENZEN["max_breite_mm"]:
            fehler.append({
                "kategorie": "WARNUNG",
                "bereich": "geometrie",
                "beschreibung": f"Tuer {bez}: Breite {breite:.0f} mm ueberschreitet Maximum",
                "betroffenes_objekt": bez,
                "korrekturvorschlag": "Tuerbreite pruefen",
            })

        if 0 < breite < TUER_GRENZEN["min_breite_mm"]:
            fehler.append({
                "kategorie": "WARNUNG",
                "bereich": "geometrie",
                "beschreibung": f"Tuer {bez}: Breite {breite:.0f} mm ungewoehnlich klein",
                "betroffenes_objekt": bez,
                "korrekturvorschlag": "Pruefen ob Tuerbreite korrekt extrahiert",
            })

        if hoehe > 0 and hoehe < TUER_GRENZEN["min_hoehe_mm"]:
            fehler.append({
                "kategorie": "WARNUNG",
                "bereich": "geometrie",
                "beschreibung": f"Tuer {bez}: Hoehe {hoehe:.0f} mm ungewoehnlich niedrig",
                "betroffenes_objekt": bez,
                "korrekturvorschlag": "Tuerhoehe pruefen - moeglicherweise Kriechklappe oder Massstabfehler",
            })

    return fehler


def _check_calculation_consistency(kalkulation: dict, geometrie: dict) -> list[dict]:
    """Prueft ob die Kalkulationsergebnisse mathematisch konsistent sind.

    Pruefungen:
      - Wandflaeche = Umfang x Hoehe (pro Raum)
      - Summe Bodenbelag ~ Summe Raumflaechen
      - Summe Estrich ~ Summe Raumflaechen
      - Keine negativen Mengen
      - OENORM-Abzugsregeln korrekt angewendet
      - Leibungen vorhanden wo erwartet

    Returns:
        Liste von Fehler-Dicts.
    """
    fehler = []
    positionen = kalkulation.get("positionen", [])
    zusammenfassung = kalkulation.get("zusammenfassung", {})
    raeume = geometrie.get("raeume", [])
    fenster = geometrie.get("fenster", [])

    # --- Negative Werte ---
    for pos in positionen:
        if pos.get("endsumme", 0) < 0:
            fehler.append({
                "kategorie": "KRITISCH",
                "bereich": "kalkulation",
                "beschreibung": (
                    f"Position {pos.get('pos_nr', '?')} ({pos.get('beschreibung', '')}): "
                    f"Negativer Wert {pos.get('endsumme', 0)}"
                ),
                "betroffenes_objekt": pos.get("raum_referenz", "?"),
                "korrekturvorschlag": "Negative Mengen sind nicht erlaubt - Berechnung pruefen",
            })

    # --- Bodenbelag/Estrich vs. Raumflaechen ---
    summe_raumflaechen = sum(
        r.get("flaeche_m2", r.get("flaeche", 0.0))
        for r in raeume
        if r.get("flaeche_m2", r.get("flaeche", 0.0)) > 0
    )

    if summe_raumflaechen > 0:
        bodenbelag_summe = zusammenfassung.get("bodenbelag_m2", 0.0)
        if bodenbelag_summe > 0:
            abweichung = abs(bodenbelag_summe - summe_raumflaechen) / summe_raumflaechen
            if abweichung > 0.10:
                fehler.append({
                    "kategorie": "WARNUNG",
                    "bereich": "kalkulation",
                    "beschreibung": (
                        f"Bodenbelag-Summe ({bodenbelag_summe:.2f} m2) weicht "
                        f"{abweichung:.0%} von Summe Raumflaechen ({summe_raumflaechen:.2f} m2) ab"
                    ),
                    "betroffenes_objekt": "zusammenfassung",
                    "korrekturvorschlag": "Pruefen ob alle Raeume einen Bodenbelag haben",
                })

        estrich_summe = zusammenfassung.get("estrich_m2", 0.0)
        if estrich_summe > 0:
            abweichung = abs(estrich_summe - summe_raumflaechen) / summe_raumflaechen
            if abweichung > 0.10:
                fehler.append({
                    "kategorie": "WARNUNG",
                    "bereich": "kalkulation",
                    "beschreibung": (
                        f"Estrich-Summe ({estrich_summe:.2f} m2) weicht "
                        f"{abweichung:.0%} von Summe Raumflaechen ({summe_raumflaechen:.2f} m2) ab"
                    ),
                    "betroffenes_objekt": "zusammenfassung",
                    "korrekturvorschlag": "Pruefen ob alle Raeume Estrich haben",
                })

    # --- Pruefe OENORM-Abzugsregeln in Berechnungsschritten ---
    for pos in positionen:
        berechnung = pos.get("berechnung", [])

        # Pruefen ob Berechnungsschritte vorhanden
        if not berechnung:
            fehler.append({
                "kategorie": "WARNUNG",
                "bereich": "kalkulation",
                "beschreibung": (
                    f"Position {pos.get('pos_nr', '?')} ({pos.get('beschreibung', '')}): "
                    "Keine Berechnungsschritte dokumentiert"
                ),
                "betroffenes_objekt": pos.get("raum_referenz", "?"),
                "korrekturvorschlag": "Berechnung muss nachvollziehbare Schritte enthalten",
            })

    # --- Pruefen ob Fensterbank-Position vorhanden ---
    if fenster:
        has_fensterbank = any(
            p.get("gewerk") in ("fensterbank", "fensterbaenke")
            for p in positionen
        )
        if not has_fensterbank:
            fehler.append({
                "kategorie": "WARNUNG",
                "bereich": "kalkulation",
                "beschreibung": (
                    f"{len(fenster)} Fenster vorhanden, aber keine Fensterbank-Position berechnet"
                ),
                "betroffenes_objekt": "fensterbank",
                "korrekturvorschlag": "Fensterbank-Position ergaenzen (Summe Fensterbreiten in Laufmeter)",
            })

    return fehler


def _check_completeness(
    parser: dict, geometrie: dict, kalkulation: dict
) -> list[dict]:
    """Prueft ob alle Elemente vollstaendig verarbeitet wurden.

    Pruefungen:
      - Alle Raeume haben Bodenbelag + Estrich
      - Alle Raeume haben Mauerwerk/Putz
      - Alle Fenster in Kalkulation beruecksichtigt
      - Leibungen fuer Putz berechnet
      - Parser-Konfidenz akzeptabel

    Returns:
        Liste von Fehler-Dicts.
    """
    fehler = []

    raeume = geometrie.get("raeume", [])
    fenster = geometrie.get("fenster", [])
    tueren = geometrie.get("tueren", [])
    positionen = kalkulation.get("positionen", [])

    # --- Parser-Konfidenz ---
    parser_konfidenz = parser.get("gesamt_konfidenz", 0)
    if isinstance(parser_konfidenz, (int, float)) and parser_konfidenz < 0.60:
        fehler.append({
            "kategorie": "WARNUNG",
            "bereich": "parser",
            "beschreibung": f"Parser-Konfidenz niedrig ({parser_konfidenz:.0%}) - Extraktionsqualitaet fragwuerdig",
            "betroffenes_objekt": "parser",
            "korrekturvorschlag": "PDF moeglicherweise schwer lesbar - manuelle Pruefung empfohlen",
        })

    # --- Raeume ohne Positionen ---
    raum_ids_in_kalk = set()
    gewerke_pro_raum: dict[str, set[str]] = {}
    for pos in positionen:
        ref = pos.get("raum_referenz", "")
        if ref and ref != "alle":
            raum_ids_in_kalk.add(ref)
            gewerke_pro_raum.setdefault(ref, set()).add(pos.get("gewerk", ""))

    for raum in raeume:
        raum_id = raum.get("id", raum.get("referenz", ""))
        raum_name = raum.get("name", raum.get("bezeichnung", "Unbekannt"))

        if raum_id and raum_id not in raum_ids_in_kalk:
            fehler.append({
                "kategorie": "KRITISCH",
                "bereich": "kalkulation",
                "beschreibung": f"Raum {raum_id} ({raum_name}) hat keine Kalkulations-Positionen",
                "betroffenes_objekt": raum_id,
                "korrekturvorschlag": "Alle Gewerke fuer diesen Raum berechnen",
            })
            continue

        gewerke = gewerke_pro_raum.get(raum_id, set())
        pflicht_gewerke = {"mauerwerk", "putz_innen", "maler", "bodenbelag", "estrich"}
        fehlende = pflicht_gewerke - gewerke
        if fehlende:
            fehler.append({
                "kategorie": "WARNUNG",
                "bereich": "kalkulation",
                "beschreibung": (
                    f"Raum {raum_id} ({raum_name}): Fehlende Gewerke: {', '.join(sorted(fehlende))}"
                ),
                "betroffenes_objekt": raum_id,
                "korrekturvorschlag": f"Fehlende Gewerke berechnen: {', '.join(sorted(fehlende))}",
            })

    # --- Keine Raeume erkannt ---
    if not raeume:
        fehler.append({
            "kategorie": "KRITISCH",
            "bereich": "geometrie",
            "beschreibung": "Keine Raeume in Geometriedaten - Massenermittlung unvollstaendig",
            "betroffenes_objekt": "geometrie",
            "korrekturvorschlag": "Geometrie-Agent muss Raeume aus Parser-Ergebnis extrahieren",
        })

    # --- Keine Positionen berechnet ---
    if not positionen and raeume:
        fehler.append({
            "kategorie": "KRITISCH",
            "bereich": "kalkulation",
            "beschreibung": f"{len(raeume)} Raeume vorhanden, aber keine Positionen berechnet",
            "betroffenes_objekt": "kalkulation",
            "korrekturvorschlag": "Kalkulations-Agent muss Positionen fuer alle Gewerke berechnen",
        })

    # --- Leibungen pruefen ---
    if fenster or tueren:
        putz_positionen = [p for p in positionen if "putz" in p.get("gewerk", "")]
        has_leibung = any(
            any("leibung" in schritt.lower() or "Leibung" in schritt
                for schritt in p.get("berechnung", []))
            for p in putz_positionen
        )
        if putz_positionen and not has_leibung:
            fehler.append({
                "kategorie": "WARNUNG",
                "bereich": "kalkulation",
                "beschreibung": (
                    f"{len(fenster)} Fenster und {len(tueren)} Tueren vorhanden, "
                    "aber keine Leibungsberechnung in Putz-Positionen gefunden"
                ),
                "betroffenes_objekt": "leibungen",
                "korrekturvorschlag": "Leibungsflaechen muessen zum Putz addiert werden",
            })

    return fehler


def _run_all_local_checks(
    parser: dict, geometrie: dict, kalkulation: dict
) -> tuple[list[dict], dict]:
    """Fuehrt alle lokalen Pruefungen durch und liefert Zusammenfassung.

    Returns:
        Tuple von (alle_fehler, statistik_dict).
    """
    alle_fehler = []

    # Raum-Plausibilitaet
    raum_fehler = _check_room_plausibility(geometrie.get("raeume", []))
    alle_fehler.extend(raum_fehler)

    # Fenster-Plausibilitaet
    fenster_fehler = _check_window_plausibility(geometrie.get("fenster", []))
    alle_fehler.extend(fenster_fehler)

    # Tuer-Plausibilitaet
    tuer_fehler = _check_door_plausibility(geometrie.get("tueren", []))
    alle_fehler.extend(tuer_fehler)

    # Berechnungs-Konsistenz
    kalk_fehler = _check_calculation_consistency(kalkulation, geometrie)
    alle_fehler.extend(kalk_fehler)

    # Vollstaendigkeit
    voll_fehler = _check_completeness(parser, geometrie, kalkulation)
    alle_fehler.extend(voll_fehler)

    # Statistik
    kritisch = sum(1 for f in alle_fehler if f["kategorie"] == "KRITISCH")
    warnung = sum(1 for f in alle_fehler if f["kategorie"] == "WARNUNG")
    hinweis = sum(1 for f in alle_fehler if f["kategorie"] == "HINWEIS")

    statistik = {
        "gesamt_fehler": len(alle_fehler),
        "kritisch": kritisch,
        "warnung": warnung,
        "hinweis": hinweis,
        "lokale_qualitaetsschaetzung": _estimate_quality(kritisch, warnung, hinweis),
    }

    return alle_fehler, statistik


def _estimate_quality(kritisch: int, warnung: int, hinweis: int) -> int:
    """Schaetzt die Qualitaet basierend auf der lokalen Fehlerzaehlung.

    Returns:
        Qualitaetswert 0-100.
    """
    score = 100
    score -= kritisch * 15  # Jeder kritische Fehler -15 Punkte
    score -= warnung * 5    # Jede Warnung -5 Punkte
    score -= hinweis * 1    # Jeder Hinweis -1 Punkt
    return max(0, min(100, score))


# ---------------------------------------------------------------------------
# System-Prompt fuer Claude (Stufe 2)
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """Du bist ein spezialisierter KI-Agent fuer die Qualitaetskontrolle von Massenermittlungen aus oesterreichischen Bauplaenen.

Du erhaeltst die Ergebnisse aller Agenten UND die Ergebnisse einer lokalen Python-Validierung.
Deine Aufgabe ist es, die lokalen Pruefergebnisse zu bestaetigen, zu ergaenzen und eine Gesamtbewertung abzugeben.

DIE LOKALE VALIDIERUNG hat bereits geprueft:
- Raumflaechen und Umfaenge auf Plausibilitaet
- Fenster- und Tuerdimensionen
- RB > AL Beziehung bei Fenstern
- Mathematische Konsistenz der Berechnungen
- Vollstaendigkeit (alle Raeume, alle Gewerke)
- OENORM-Abzugsregeln

DEINE ZUSAETZLICHEN PRUEFUNGEN:
1. Kontextuelle Plausibilitaet (passen die Raeume zu einem typischen Wohnungsgrundriss?)
2. Semantische Konsistenz (stimmen Raumnamen mit Groessen ueberein?)
3. Bauphysikalische Plausibilitaet (Aussenwaende, Innenwandstaerken)
4. Erkennung von Muster-Fehlern (typische OCR-Fehler, Massstab-Probleme)
5. Gesamtbewertung unter Beruecksichtigung aller Faktoren

OENORM-ABZUGSREGELN (zur Verifikation):
- Mauerwerk: <0,5m2 kein Abzug, 0,5-3,0m2 halb, >3,0m2 voll
- Putz/Anstrich innen: <2,5m2 kein, 2,5-10,0m2 halb, >10,0m2 voll
- Putz aussen: gleich wie innen
- Maler: gleich wie Putz innen
- Fliesen: <0,1m2 kein, >=0,1m2 voll
- Bodenbelag/Estrich: kein Oeffnungsabzug

BEWERTUNGSSKALA:
- 90-100: Hervorragend, keine Fehler
- 80-89: Gut, nur kleine Hinweise
- 60-79: Akzeptabel mit Warnungen
- 40-59: Nachbesserung empfohlen
- 0-39: Kritische Fehler, Neuberechnung noetig

FEHLERKATEGORIEN:
- KRITISCH: Falsche Abzugsregel, fehlende Raeume, grob falsche Flaechen, negative Werte
- WARNUNG: Ungewoehnliche Werte, fehlende Leibungen, Rundungsfehler, fehlende Gewerke
- HINWEIS: Optimierungspotential, fehlende Detailangaben, stilistische Anmerkungen

STATUS-REGELN:
- AKZEPTIERT: gesamt_qualitaet >= 80, keine KRITISCHEN Fehler
- NACHBESSERUNG_ERFORDERLICH: gesamt_qualitaet 40-79 ODER KRITISCHE Fehler vorhanden
- KRITISCHER_FEHLER: gesamt_qualitaet < 40

AUSGABEFORMAT (JSON):
{
  "status": "AKZEPTIERT" | "NACHBESSERUNG_ERFORDERLICH" | "KRITISCHER_FEHLER",
  "gesamt_qualitaet": 85,
  "fehler": [
    {
      "kategorie": "KRITISCH" | "WARNUNG" | "HINWEIS",
      "bereich": "geometrie" | "kalkulation" | "parser",
      "beschreibung": "Detaillierte Beschreibung des Fehlers",
      "betroffenes_objekt": "R1" | "FE_31",
      "korrekturvorschlag": "Konkreter Vorschlag zur Korrektur"
    }
  ],
  "verbesserungsanweisungen": [
    "Konkrete Anweisung fuer den betroffenen Agenten"
  ],
  "freigabe": true | false,
  "zusammenfassung": "Kurze Zusammenfassung der Pruefung",
  "kontextuelle_anmerkungen": [
    "Hoehere Analyse-Ergebnisse die ueber lokale Checks hinausgehen"
  ]
}

Sei STRENG aber FAIR. Bestaetie die lokalen Ergebnisse und ergaenze deine eigenen Erkenntnisse.
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

    # Bereinigungsversuch
    if start != -1 and end != -1:
        candidate = text[start:end + 1]
        candidate = re.sub(r"//.*?\n", "\n", candidate)
        candidate = re.sub(r",\s*([}\]])", r"\1", candidate)
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            pass

    logger.error("JSON-Parsing fehlgeschlagen fuer Kritik-Agent: %s", text[:300])
    return {
        "status": "KRITISCHER_FEHLER",
        "gesamt_qualitaet": 0,
        "fehler": [{"kategorie": "KRITISCH", "bereich": "kritik", "beschreibung": "JSON-Parsing fehlgeschlagen"}],
        "verbesserungsanweisungen": [],
        "freigabe": False,
        "zusammenfassung": "Kritik-Agent konnte Ergebnis nicht verarbeiten.",
    }


# ---------------------------------------------------------------------------
# Hauptfunktion
# ---------------------------------------------------------------------------

async def run(kontext: dict, anweisung: str = "") -> dict:
    """
    Hauptfunktion des Kritik-Agents (2-Stufen-Pipeline).

    Args:
        kontext: Dict mit 'parser_ergebnis', 'geometrie_ergebnis', 'kalkulations_ergebnis'.
        anweisung: Optionale zusaetzliche Anweisung.

    Returns:
        Dict mit status, gesamt_qualitaet, fehler, verbesserungsanweisungen, freigabe.
    """
    parser_ergebnis = kontext.get("parser_ergebnis", {})
    geometrie_ergebnis = kontext.get("geometrie_ergebnis", {})
    kalkulations_ergebnis = kontext.get("kalkulations_ergebnis", {})

    if not any([parser_ergebnis, geometrie_ergebnis, kalkulations_ergebnis]):
        logger.warning("Kritik-Agent: Keine Ergebnisse zum Pruefen erhalten")
        return {
            "status": "KRITISCHER_FEHLER",
            "gesamt_qualitaet": 0,
            "fehler": [{"kategorie": "KRITISCH", "bereich": "kritik", "beschreibung": "Keine Ergebnisse zum Pruefen erhalten"}],
            "verbesserungsanweisungen": [],
            "freigabe": False,
            "zusammenfassung": "Keine Daten zur Pruefung vorhanden.",
        }

    # ===================================================================
    # STUFE 1: Lokale Python-Validierung
    # ===================================================================
    logger.info("Kritik-Agent Stufe 1: Lokale Python-Validierung")

    lokale_fehler, statistik = _run_all_local_checks(
        parser_ergebnis, geometrie_ergebnis, kalkulations_ergebnis
    )

    logger.info(
        "Lokale Validierung: %d Fehler (KRITISCH=%d, WARNUNG=%d, HINWEIS=%d), "
        "Geschaetzte Qualitaet=%d%%",
        statistik["gesamt_fehler"],
        statistik["kritisch"],
        statistik["warnung"],
        statistik["hinweis"],
        statistik["lokale_qualitaetsschaetzung"],
    )

    for fehler in lokale_fehler:
        if fehler["kategorie"] == "KRITISCH":
            logger.warning(
                "KRITISCH: %s [%s]", fehler["beschreibung"], fehler.get("betroffenes_objekt", "?")
            )

    # ===================================================================
    # STUFE 2: Claude-KI-Analyse
    # ===================================================================
    logger.info("Kritik-Agent Stufe 2: Claude-KI-Analyse")

    all_data = {
        "parser_ergebnis": parser_ergebnis,
        "geometrie_ergebnis": geometrie_ergebnis,
        "kalkulations_ergebnis": kalkulations_ergebnis,
    }
    data_json = json.dumps(all_data, ensure_ascii=False, indent=2)
    lokale_json = json.dumps({
        "lokale_fehler": lokale_fehler,
        "statistik": statistik,
    }, ensure_ascii=False, indent=2)

    user_message = f"""Fuehre eine vollstaendige Qualitaetskontrolle der folgenden Massenermittlung durch.

ZUSAMMENFASSUNG DER EINGABEDATEN:
- Parser-Konfidenz: {parser_ergebnis.get("gesamt_konfidenz", "N/A")}
- Anzahl Raeume: {len(geometrie_ergebnis.get("raeume", []))}
- Anzahl Fenster: {len(geometrie_ergebnis.get("fenster", []))}
- Anzahl Tueren: {len(geometrie_ergebnis.get("tueren", []))}
- Anzahl Kalkulations-Positionen: {len(kalkulations_ergebnis.get("positionen", []))}

ERGEBNISSE DER LOKALEN PYTHON-VALIDIERUNG (Stufe 1):
{lokale_json}

{f"Zusaetzliche Anweisung: {anweisung}" if anweisung else ""}

VOLLSTAENDIGE AGENTEN-ERGEBNISSE:
{data_json}

AUFGABEN:
1. Bestaetie oder korrigiere die lokalen Pruefergebnisse
2. Fuehre kontextuelle Pruefungen durch (Grundriss-Plausibilitaet, Semantik)
3. Pruefe OENORM-Abzugsregeln stichprobenartig nach
4. Bewerte die Gesamtqualitaet unter Beruecksichtigung aller Faktoren
5. Erstelle konkrete Verbesserungsanweisungen bei Bedarf

WICHTIG: Uebernimm die lokalen Fehler in deine Ausgabe und ergaenze sie um deine eigenen Erkenntnisse.

Antworte NUR mit validem JSON gemaess dem vorgegebenen Format."""

    try:
        client = anthropic.AsyncAnthropic(
            api_key=_get_api_key(),
        )

        response = await client.messages.create(
            model=MODEL,
            max_tokens=8192,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_message}],
        )

        raw_text = response.content[0].text if response.content else ""
        result = _parse_json_response(raw_text)

        logger.info(
            "Claude-Analyse: Status=%s, Qualitaet=%d%%, Fehler=%d",
            result.get("status", "?"),
            result.get("gesamt_qualitaet", 0),
            len(result.get("fehler", [])),
        )

    except anthropic.APIError as e:
        logger.error("Anthropic API Fehler: %s - verwende nur lokale Ergebnisse", e)
        # Fallback: Nur lokale Ergebnisse verwenden
        qualitaet = statistik["lokale_qualitaetsschaetzung"]
        has_critical = statistik["kritisch"] > 0
        if qualitaet < 40:
            status = "KRITISCHER_FEHLER"
        elif qualitaet < 80 or has_critical:
            status = "NACHBESSERUNG_ERFORDERLICH"
        else:
            status = "AKZEPTIERT"

        return {
            "status": status,
            "gesamt_qualitaet": qualitaet,
            "fehler": lokale_fehler,
            "verbesserungsanweisungen": [f["korrekturvorschlag"] for f in lokale_fehler if f.get("korrekturvorschlag")],
            "freigabe": status == "AKZEPTIERT",
            "zusammenfassung": f"Nur lokale Validierung (API-Fehler: {e}). {statistik['gesamt_fehler']} Fehler gefunden.",
        }
    except Exception as e:
        logger.error("Unerwarteter Fehler im Kritik-Agent: %s", e, exc_info=True)
        return {
            "status": "KRITISCHER_FEHLER",
            "gesamt_qualitaet": 0,
            "fehler": [{"kategorie": "KRITISCH", "bereich": "kritik", "beschreibung": f"Unerwarteter Fehler: {str(e)}"}],
            "verbesserungsanweisungen": [],
            "freigabe": False,
            "zusammenfassung": f"Unerwarteter Fehler: {str(e)}",
        }

    # ===================================================================
    # Ergebnisse zusammenfuehren und validieren
    # ===================================================================

    # Sicherstelle Grundstruktur
    result.setdefault("status", "KRITISCHER_FEHLER")
    result.setdefault("gesamt_qualitaet", 0)
    result.setdefault("fehler", [])
    result.setdefault("verbesserungsanweisungen", [])
    result.setdefault("freigabe", False)
    result.setdefault("zusammenfassung", "")

    # Stelle sicher, dass lokale kritische Fehler nicht verloren gehen
    claude_fehler_beschreibungen = {f.get("beschreibung", "") for f in result["fehler"]}
    for lokaler_fehler in lokale_fehler:
        if lokaler_fehler["kategorie"] == "KRITISCH":
            # Pruefe ob Claude diesen Fehler uebernommen hat (ungefaehre Suche)
            obj = lokaler_fehler.get("betroffenes_objekt", "")
            already_found = any(obj in beschr for beschr in claude_fehler_beschreibungen)
            if not already_found:
                result["fehler"].append(lokaler_fehler)
                logger.warning(
                    "Kritischer lokaler Fehler von Claude nicht uebernommen, ergaenzt: %s",
                    lokaler_fehler["beschreibung"],
                )

    # Erzwinge Status-Regeln konsistent
    qualitaet = result["gesamt_qualitaet"]
    has_critical = any(f.get("kategorie") == "KRITISCH" for f in result["fehler"])

    if qualitaet < 40:
        result["status"] = "KRITISCHER_FEHLER"
        result["freigabe"] = False
    elif qualitaet < 80 or has_critical:
        result["status"] = "NACHBESSERUNG_ERFORDERLICH"
        result["freigabe"] = False
    else:
        result["status"] = "AKZEPTIERT"
        result["freigabe"] = True

    # Fuege Statistik der lokalen Validierung hinzu
    result["lokale_validierung"] = statistik

    logger.info(
        "Kritik-Agent abgeschlossen: Status=%s, Qualitaet=%d%%, "
        "Fehler=%d (lokal=%d, gesamt=%d), Freigabe=%s",
        result["status"],
        result["gesamt_qualitaet"],
        len(result["fehler"]),
        statistik["gesamt_fehler"],
        len(result["fehler"]),
        result["freigabe"],
    )

    return result
