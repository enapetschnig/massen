"""WÄCHTER Mengen-Engine-Robustheit: 'sehr sehr zuverlässig' heißt — die
Materiallisten-/Gewerke-Berechnung darf auf KEINER Eingabe crashen oder
unsinnige (negative/NaN/inf) Mengen liefern. Vision/Text/Merge können
None, Zahl-Strings, negative/absurde Werte liefern — das Kernprodukt fängt
das ab (defensive Eingangs-Normalisierung + Mengen-Clamp)."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))
from materialliste import materialliste_bauteile   # noqa: E402
from massen_logic import berechne_gewerke           # noqa: E402

RAUM_FAELLE = [
    ("leer", []),
    ("ohne Fläche", [{"name": "X"}]),
    ("F=0", [{"name": "X", "flaeche_m2": 0, "umfang_m": 0, "hoehe_m": 0}]),
    ("F negativ", [{"name": "X", "flaeche_m2": -5, "umfang_m": -3, "hoehe_m": -2}]),
    ("riesig", [{"name": "X", "flaeche_m2": 1e9, "umfang_m": 1e6, "hoehe_m": 1e4}]),
    ("None-Werte", [{"name": None, "flaeche_m2": None, "umfang_m": None, "hoehe_m": None}]),
    ("Zahl-Strings", [{"name": "X", "flaeche_m2": "20", "umfang_m": "18"}]),
    ("U ohne F", [{"name": "X", "umfang_m": 18}]),
    ("H=0", [{"name": "Zi", "flaeche_m2": 20, "umfang_m": 18, "hoehe_m": 0}]),
    ("Garage riesig", [{"name": "Tiefgarage", "flaeche_m2": 9999, "umfang_m": 0}]),
]
BD_FAELLE = [
    ("leer", {}), ("None", None),
    ("nullen", {"aussenwand_cm": 0, "geschosshoehe_m": 0, "decke_cm": 0}),
    ("negativ", {"aussenwand_cm": -50, "geschosshoehe_m": -2}),
    ("dach o. Höhe", {"aussenwand_cm": 50, "dach_typ": "sattel"}),
    ("Zahl-Strings", {"aussenwand_cm": "50", "geschosshoehe_m": "2.6"}),
]


def _endlich_nichtneg(v):
    return v == v and v not in (float("inf"), float("-inf")) and v >= -0.001


def run():
    n, verletzt = 0, 0
    for _rn, rooms in RAUM_FAELLE:
        for _bn, bd in BD_FAELLE:
            n += 2
            for p in materialliste_bauteile(rooms, [], bd,
                                             gemessen={"aussenumfang_m": 30, "konfidenz": 0.9}):
                assert _endlich_nichtneg(p.menge), f"{_rn}/{_bn}: {p.material}={p.menge}"
                verletzt += 0 if p.menge >= 0 else 1
            r = berechne_gewerke(rooms, [], bd)
            for g, info in r.get("gewerke", {}).items():
                for p in info.get("positionen", []):
                    assert _endlich_nichtneg(p.get("endsumme") or 0), f"{_rn}/{_bn}/{g}"
    assert verletzt == 0
    print(f"OK — Mengen-Engine: {n} Fuzz-Kombinationen (None/Strings/negativ/"
          f"riesig/0) ohne Crash, keine negative/NaN/inf-Menge.")


if __name__ == "__main__":
    run()
