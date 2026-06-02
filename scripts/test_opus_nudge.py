#!/usr/bin/env python3
"""Nagelt die Schutzregeln des Opus-Korrektur-Loops (S1) fest.

Kernzusage: byte-exakte/Legende-gebundene Positionen (hohe Konfidenz) werden
NIEMALS verändert; nur ehrlich geschätzte Positionen (niedrige Konfidenz) sind
korrigierbar, und auch nur belegt + innerhalb ±25%. Alles andere wird abgelehnt
oder nur geflaggt — nie still angewandt.

Lauf:  python3 scripts/test_opus_nudge.py   (Exit 0 = alle Zusagen gehalten)
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "api"))

from opus_nudge import opus_mengen_nudge, NUDGE_KONF_NACH


def _liste():
    """Frische Bauteil-Struktur wie aus build_materialliste."""
    return {
        "Bodenplatte": [
            {"material": "EKV-5 Bitumendichtbahn", "menge": 125.0, "konfidenz": 0.95, "formel": "ΣF"},
        ],
        "Decke über EG": [
            {"material": "Schaltafel 200/50", "menge": 248.1, "konfidenz": 0.87, "formel": "Footprint×Auskragung"},
        ],
        "Öffnungen": [
            {"material": "Rolladenkasten (Lavatherm) 124cm", "menge": 4, "konfidenz": 0.62, "formel": "4 Fenster"},
            {"material": "Ziegelüberlage 12cm 125cm", "menge": 6, "konfidenz": 0.62, "formel": "6 Türen"},
        ],
        "Säulen": [
            {"material": "Stahlbeton-Stütze 25/25", "menge": 4, "konfidenz": 0.57, "formel": "geschätzt"},
        ],
    }


def run():
    fails = []

    def check(name, cond):
        print(f"  {'✓' if cond else '✗'} {name}")
        if not cond:
            fails.append(name)

    # 1) Byte-exakt (Konfidenz ≥ 0.80) wird NIE angetastet — auch mit Beleg + kleiner Abweichung
    bt, log = opus_mengen_nudge(_liste(), [
        {"bauteil": "Bodenplatte", "material": "EKV", "soll_menge": 130, "beleg": "Plan zeigt 130"},
        {"bauteil": "Decke über EG", "material": "Schaltafel", "soll_menge": 255, "beleg": "Plan"},
    ])
    check("Bodenplatte (0.95) unverändert", bt["Bodenplatte"][0]["menge"] == 125.0)
    check("gemessene Decke (0.87) unverändert", bt["Decke über EG"][0]["menge"] == 248.1)
    check("beide als abgelehnt geloggt (byte-exakt = tabu)",
          all(e["status"] == "abgelehnt" for e in log))

    # 2) Geschätzte Position (0.62) innerhalb ±25% → angewandt, Konfidenz gedeckelt, Vermerk
    bt, log = opus_mengen_nudge(_liste(), [
        {"bauteil": "Öffnungen", "material": "Rolladenkasten", "soll_menge": 5, "beleg": "5 Fenster-Symbole im Plan"},
    ])
    roll = bt["Öffnungen"][0]
    check("Rolladen 4→5 angewandt", roll["menge"] == 5)
    check("Konfidenz nach Korrektur gedeckelt", roll["konfidenz"] <= NUDGE_KONF_NACH)
    check("Beleg-Vermerk in Formel sichtbar", "Opus-korrigiert" in roll["formel"] and "Beleg:" in roll["formel"])
    check("opus_korrigiert-Flag gesetzt", roll.get("opus_korrigiert") is True)
    check("Log = angewandt", log[0]["status"] == "angewandt" and log[0]["alt"] == 4 and log[0]["neu"] == 5)

    # 3) Zu große Abweichung (>25%) → NICHT angewandt, nur geflaggt
    bt, log = opus_mengen_nudge(_liste(), [
        {"bauteil": "Säulen", "material": "Stütze", "soll_menge": 8, "beleg": "8 im Plan"},  # 4→8 = +100%
    ])
    check("Säulen 4 unverändert (>25% nicht angewandt)", bt["Säulen"][0]["menge"] == 4)
    check("aber als 'geflaggt' protokolliert", log[0]["status"] == "geflaggt")

    # 4) Ohne Beleg → abgelehnt
    bt, log = opus_mengen_nudge(_liste(), [
        {"bauteil": "Öffnungen", "material": "Rolladenkasten", "soll_menge": 5, "beleg": ""},
    ])
    check("ohne Beleg abgelehnt", bt["Öffnungen"][0]["menge"] == 4 and log[0]["status"] == "abgelehnt")

    # 5) Unbekanntes Bauteil → abgelehnt, nichts kaputt
    bt, log = opus_mengen_nudge(_liste(), [
        {"bauteil": "Fundament-XY", "soll_menge": 10, "beleg": "x"},
    ])
    check("unbekanntes Bauteil abgelehnt", log[0]["status"] == "abgelehnt")

    # 6) Mehrdeutiges Material (kein Stichwort, 2 geschätzte Positionen) → abgelehnt
    bt, log = opus_mengen_nudge(_liste(), [
        {"bauteil": "Öffnungen", "soll_menge": 5, "beleg": "x"},  # 2 eligible → nicht eindeutig
    ])
    check("mehrdeutige Zielposition abgelehnt",
          bt["Öffnungen"][0]["menge"] == 4 and bt["Öffnungen"][1]["menge"] == 6
          and log[0]["status"] == "abgelehnt")

    # 7) Leere Korrektur-Liste → No-op, kein Crash
    bt, log = opus_mengen_nudge(_liste(), [])
    check("leere Liste → No-op", log == [] and bt["Bodenplatte"][0]["menge"] == 125.0)

    # 8) Soll = Ist (0% Abweichung, Untergrenze) → angewandt aber wertgleich, keine Schein-Änderung
    bt, log = opus_mengen_nudge(_liste(), [
        {"bauteil": "Öffnungen", "material": "Ziegelüberlage", "soll_menge": 6, "beleg": "bestätigt 6"},
    ])
    check("Soll=Ist bleibt 6, sauber geloggt", bt["Öffnungen"][1]["menge"] == 6 and log[0]["status"] == "angewandt")

    print("-" * 60)
    if fails:
        print(f"FEHLER: {len(fails)} Zusage(n) verletzt: {fails}")
        return 1
    print("OK — Opus-Korrektur-Loop: byte-exakt tabu, geschätzt belegt+gedeckelt, Rest geflaggt/abgelehnt.")
    return 0


if __name__ == "__main__":
    sys.exit(run())
