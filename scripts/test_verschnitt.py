#!/usr/bin/env python3
"""Schützt die Invarianten des HLZ-Verschnitt-Aufschlags (materialliste.py).

Aus der adversarialen Gegenprüfung des Fixes (1.05): der Verschnitt darf
AUSSCHLIESSLICH die Ziegel-Paletten-Menge erhöhen — niemals Mauermörtel,
Voranstrich, EKV oder die Kennzahlen. Und er rundet nur nach OBEN (sichere
Richtung für den Polier), auch auf kleinen Positionen höchstens +1 Palette.

Lauf:  python3 scripts/test_verschnitt.py   (Exit 0 = Invarianten gehalten)
"""
import math
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "api"))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

from materialliste import build_materialliste
from test_materialliste_angerer import (ROOMS, BAUDATEN, WAND_VERTEILUNG,
                                         GEMESSEN, WINDOWS, TUEREN)


def _menge(ml, bauteil, stich):
    for p in (ml.get("bauteile") or {}).get(bauteil, []):
        if stich.lower() in p["material"].lower():
            return p["menge"]
    return None


def _build(versch):
    return build_materialliste(ROOMS, WINDOWS, BAUDATEN,
                               override={"hlz_verschnitt": versch}, geschoss="EG",
                               tueren=TUEREN, gemessen=GEMESSEN,
                               wand_verteilung=WAND_VERTEILUNG)


def run():
    fails = []

    def check(name, cond):
        print(f"  {'✓' if cond else '✗'} {name}")
        if not cond:
            fails.append(name)

    ml_100 = _build(1.0)    # ohne Verschnitt
    ml_105 = _build(1.05)   # Standard
    ml_115 = _build(1.15)   # höherer Firmen-Verschnitt (Kalibrierung)

    # ── 1) PFAD-TRENNUNG: alles AUSSER HLZ-Paletten muss byte-identisch bleiben ──
    for bauteil, stich in [("Mauerwerk EG", "Mauermörtel"),
                           ("Mauerwerk EG", "Voranstrich"),
                           ("Mauerwerk EG", "EKV-5 (Außenwand)")]:
        a, b = _menge(ml_100, bauteil, stich), _menge(ml_105, bauteil, stich)
        check(f"{stich} unverändert (roh m², kein Verschnitt)", a is not None and a == b)

    # Kennzahlen (Höhe/Wandfläche) hängen am rohen m² → unberührt
    k100 = ml_100.get("kennzahlen") or {}
    k105 = ml_105.get("kennzahlen") or {}
    check("Kennzahl aussenwand_flaeche_m2 unverändert",
          k100.get("aussenwand_flaeche_m2") == k105.get("aussenwand_flaeche_m2"))
    check("Kennzahl innenwand_flaeche_m2 unverändert",
          k100.get("innenwand_flaeche_m2") == k105.get("innenwand_flaeche_m2"))

    # ── 2) NUR HLZ-PALETTEN steigen, und nur nach OBEN (nie runter) ──
    hlz_100 = {p["material"]: p["menge"] for p in (ml_100["bauteile"].get("Mauerwerk EG") or [])
               if "hlz" in p["material"].lower()}
    hlz_105 = {p["material"]: p["menge"] for p in (ml_105["bauteile"].get("Mauerwerk EG") or [])
               if "hlz" in p["material"].lower()}
    check("HLZ-Sorten in beiden Läufen deckungsgleich", set(hlz_100) == set(hlz_105))
    nie_kleiner = all(hlz_105[m] >= hlz_100[m] for m in hlz_100)
    check("kein HLZ sinkt durch Verschnitt (sichere Richtung)", nie_kleiner)
    irgendwo_groesser = any(hlz_105[m] > hlz_100[m] for m in hlz_100)
    check("mind. eine HLZ-Position steigt (Verschnitt wirkt)", irgendwo_groesser)

    # ── 3) Höherer Firmen-Verschnitt (1.15) ≥ Standard (1.05) ──
    hlz_115 = {p["material"]: p["menge"] for p in (ml_115["bauteile"].get("Mauerwerk EG") or [])
               if "hlz" in p["material"].lower()}
    check("Firmen-Verschnitt 1.15 ≥ Standard 1.05 (Kalibrierung greift)",
          all(hlz_115[m] >= hlz_105[m] for m in hlz_100))

    # ── 4) KLEINE Position: +5% kippt höchstens +1 Palette (Generalisierungs-Sorge) ──
    # Winziges Gebäude (Fallback-Pfad, kleiner geschätzter Umfang) → kleine HLZ-m².
    klein_rooms = [{"name": "Lager", "flaeche_m2": 6.0, "umfang_m": 10.0, "hoehe_m": 2.70}]
    ml_k100 = build_materialliste(klein_rooms, [], {"aussenwand_cm": 50, "geschosshoehe_m": 2.70},
                                  override={"hlz_verschnitt": 1.0}, geschoss="EG")
    ml_k105 = build_materialliste(klein_rooms, [], {"aussenwand_cm": 50, "geschosshoehe_m": 2.70},
                                  override={"hlz_verschnitt": 1.05}, geschoss="EG")
    k0 = {p["material"]: p["menge"] for p in (ml_k100["bauteile"].get("Mauerwerk EG") or [])
          if "hlz" in p["material"].lower()}
    k5 = {p["material"]: p["menge"] for p in (ml_k105["bauteile"].get("Mauerwerk EG") or [])
          if "hlz" in p["material"].lower()}
    deltas = [k5[m] - k0[m] for m in k0]
    check("kleine Positionen: Verschnitt-Delta je Sorte ∈ {0,1} (kein Mehrfach-Sprung)",
          all(d in (0, 1) for d in deltas))
    check("kleine Positionen: nie negativ", all(d >= 0 for d in deltas))

    print("-" * 62)
    if fails:
        print(f"FEHLER: {len(fails)} Invariante(n) verletzt: {fails}")
        return 1
    print("OK — Verschnitt wirkt NUR auf HLZ-Paletten, nur aufwärts, ≤+1/Sorte klein.")
    return 0


if __name__ == "__main__":
    sys.exit(run())
