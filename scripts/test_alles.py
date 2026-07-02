#!/usr/bin/env python3
"""SCOREBOARD — alle Kern-Metriken der App in einem Lauf (Doktrin: Messwert statt
Behauptung). Vor/nach JEDER Änderung laufen lassen; keine Zahl darf fallen.

Lauf: massenermittlung/venv/bin/python3 scripts/test_alles.py [--schnell]
  --schnell: nur die Guards (ohne Korpus/Raumverifikation, ~10s statt ~2min)
"""
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = os.path.join(ROOT, "massenermittlung", "venv", "bin", "python3")

GUARDS = [
    ("Polier-Liste (rote Linie)", "test_materialliste_angerer.py", "13/13 Positionen"),
    ("ÖNORM-Öffnungslogik", "test_massen_logic.py", "B 2204 §5.5.1.3"),
    ("Öffnungs-Codes", "test_oeffnungen_codes.py", "STUK/FPH/STUK-only"),
    ("Verschnitt", "test_verschnitt.py", "nur HLZ, nur aufwärts"),
    ("Farb-Legende", "test_farben.py", "Neubau/Bestand/Abbruch + Boilerplate-Gate"),
    ("Nachzeichnen-Backend", "test_nachzeichnen.py", "Bild+Wände+graceful-fail"),
    ("Korrektur-Override", "test_nachzeichnen_override.py", "bounded, kein Kollateral"),
    ("Aufmaßblatt", "test_aufmassblatt.py", "PDF mit Plan+Einzeichnungen"),
    ("Kalibrier-Mechanik", "test_kalibrierung.py", "dormant, aber intakt"),
]
LANGSAM = [
    ("Plan-Korpus-Abdeckung", "test_korpus.py", "ABDECKUNG:"),
    ("Raum-Verifikation", "test_raumverifikation.py", "ERGEBNIS:"),
    ("Rohbau-Raumcheck", "test_rohbau_raumcheck.py", "ROHBAU-verifiziert"),
]


def lauf(skript):
    r = subprocess.run([PY, os.path.join(ROOT, "scripts", skript)],
                       capture_output=True, text=True, timeout=600)
    return r.returncode == 0, r.stdout


def run():
    schnell = "--schnell" in sys.argv
    print("=" * 72)
    print("SCOREBOARD — Kern-Metriken (Messwert statt Behauptung)")
    print("=" * 72)
    alle_ok = True
    for name, skript, was in GUARDS:
        try:
            ok, _ = lauf(skript)
        except Exception:
            ok = False
        alle_ok &= ok
        print(f"  {'✓' if ok else '✗'} {name:<28} {was}")
    if not schnell:
        print("-" * 72)
        for name, skript, marker in LANGSAM:
            try:
                ok, out = lauf(skript)
                zeile = next((l for l in out.splitlines() if marker in l), "?")
            except Exception:
                ok, zeile = False, "CRASH"
            alle_ok &= ok
            print(f"  {'✓' if ok else '✗'} {name:<28} {zeile.strip()[:70]}")
    print("=" * 72)
    print("ALLE METRIKEN GRÜN — keine Regression." if alle_ok
          else "MINDESTENS EINE METRIK ROT — NICHT mergen/pushen.")
    return 0 if alle_ok else 1


if __name__ == "__main__":
    sys.exit(run())
