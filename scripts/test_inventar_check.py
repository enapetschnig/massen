#!/usr/bin/env python3
"""Nagelt den Bauteil-Inventar-Crosscheck (Phase 5) fest.

Kernzusagen: nur belegte + sicher genug erkannte Bauteile zählen; was die Liste
schon abbildet → gedeckt (keine Flagge); was im Plan gesehen aber NICHT abgebildet
ist → fehlend + Prüf-Flagge. Keine Geister-Flaggen ohne Beleg/Konfidenz.

Lauf:  python3 scripts/test_inventar_check.py   (Exit 0 = Zusagen gehalten)
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "api"))

from inventar_check import crosscheck_inventar, MIN_KONF

# Liste/LV: Säulen sind abgebildet (Beton-Gewerk), Treppe NICHT.
MATERIALLISTE = {"bauteile": {"Bodenplatte": [], "Mauerwerk EG": [], "Säulen": []}}
GEWERKE = {"gewerke": {
    "beton": {"positionen": [{"beschreibung": "Stahlbeton-Stützen — EG"}]},
    "rohbau": {"positionen": [{"beschreibung": "Stahlbeton-Decke über EG"}]},
}}


def run():
    fails = []

    def check(name, cond):
        print(f"  {'✓' if cond else '✗'} {name}")
        if not cond:
            fails.append(name)

    inv = [
        {"typ": "Säule", "anzahl": 5, "beleg": "5 Stützen im Grundriss", "konfidenz": 0.8},
        {"typ": "Treppe", "anzahl": 1, "beleg": "Treppe im Schnitt", "konfidenz": 0.75},
        {"typ": "Kamin", "anzahl": 1, "beleg": "Kaminzug Grundriss", "konfidenz": 0.7},
        {"typ": "Säule", "anzahl": 2, "beleg": "", "konfidenz": 0.9},          # kein Beleg → ignoriert
        {"typ": "Unterzug", "anzahl": 1, "beleg": "UZ im Schnitt", "konfidenz": 0.3},  # zu unsicher
        {"typ": "Gartenzaun", "anzahl": 1, "beleg": "x", "konfidenz": 0.9},    # unbekannter Typ → ignoriert
    ]
    r = crosscheck_inventar(inv, MATERIALLISTE, GEWERKE)

    typen_erkannt = {e["typ"] for e in r["erkannt"]}
    check("nur belegte + sichere + bekannte Typen erkannt (Säule/Treppe/Kamin)",
          typen_erkannt == {"saeule", "treppe", "kamin"})
    check("ohne Beleg ignoriert (kein 2. Säulen-Eintrag)",
          len([e for e in r["erkannt"] if e["typ"] == "saeule"]) == 1)
    check("zu unsicher (<MIN_KONF) ignoriert", "unterzug" not in typen_erkannt)
    check("unbekannter Typ ignoriert (keine Flagge für Gartenzaun)",
          not any("Gartenzaun" in f["hinweis"] for f in r["flaggen"]))

    gedeckt_typen = {e["typ"] for e in r["gedeckt"]}
    check("Säule gilt als GEDECKT (Beton-Gewerk bildet Stützen ab)", "saeule" in gedeckt_typen)
    check("Säule erzeugt KEINE Flagge", not any("Säulen" in f["thema"] for f in r["flaggen"]))

    fehlend_typen = {e["typ"] for e in r["fehlend"]}
    check("Treppe ist FEHLEND (nicht in Liste/LV)", "treppe" in fehlend_typen)
    check("Kamin ist FEHLEND", "kamin" in fehlend_typen)
    check("Treppe erzeugt eine 'Im Plan gesehen'-Flagge",
          any("Treppe" in f["thema"] and "Plan gesehen" in f["thema"] for f in r["flaggen"]))
    check("Flagge trägt den Beleg + 'prüfen/ergänzen'",
          any("Beleg:" in f["hinweis"] and "ergänzen" in f["hinweis"] for f in r["flaggen"]))
    check("Flaggen-Anzahl = fehlende Bauteile", len(r["flaggen"]) == len(r["fehlend"]))

    # Robustheit: leere/None-Eingaben brechen nichts
    leer = crosscheck_inventar([], MATERIALLISTE, GEWERKE)
    check("leeres Inventar → keine Flaggen, kein Crash", leer["flaggen"] == [])
    none_in = crosscheck_inventar(None, None, None)
    check("None-Eingaben → leer, kein Crash", none_in["erkannt"] == [] and none_in["flaggen"] == [])

    print("-" * 60)
    if fails:
        print(f"FEHLER: {len(fails)} Zusage(n) verletzt: {fails}")
        return 1
    print(f"OK — Crosscheck: belegt+sicher (≥{MIN_KONF}) zählt, gedeckt=keine Flagge, "
          "fehlend=Plan-gesehen-Flagge, keine Geister.")
    return 0


if __name__ == "__main__":
    sys.exit(run())
