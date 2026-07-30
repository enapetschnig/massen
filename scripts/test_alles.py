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
    ("Dach-Sektor (byte-exakt)", "test_dach_positionen.py", "Σ=Gesamt + Sparren + Velux"),
    ("Edge-Case-Robustheit", "test_edgecases.py", "leer/Scan/rotiert — nie crashen"),
    ("Mengen-Engine-Fuzz", "test_materialliste_fuzz.py", "None/Strings/negativ — nie crashen/negativ"),
    ("Aufmaß-Kreuztabelle", "test_aufmass_matrix.py", "Räume × Positionen, Abzüge raumscharf"),
    ("Aufmaßregeln (ÖNORM-Deckung)", "test_aufmassregeln.py", "Positionen mit Menge"),
    ("Eigene Positionen (Regel-Pflicht)", "test_eigene_positionen.py", "Aufmaßregeln"),
    ("Vision-Antwort-Parser", "test_json_parser.py", "Vision-Parser"),
    ("LV-Import (A 2063)", "test_lv_import.py", "LV-Import"),
    ("ÖNORM-Nachweis (Rechenweg)", "mess_oenorm_nachweis.py", "Regeln nachgewiesen"),
    ("Gewerke-Breite (Sektoren)", "mess_gewerke_breite.py", "Gewerke liefern Mengen"),
    ("Textfleck-Anker (Scan-Lage)", "test_textanker.py", "Textfleck-Anker"),
    ("Workflow-Schritte", "test_workflow_schritte.py", "Pflicht-Bereiche"),
    ("Gleichnamige Räume (MFH)", "test_namens_kollision.py", "eigene Zahlen"),
    ("Klick-Handler (Im Plan zeigen)", "test_klick_handler.py", "Inline-Handler"),
    ("Außenumfang plausibel", "test_umfang_plausibel.py", "richtig bewertet"),
    ("Quellen-Konflikt (Text schlägt Vision)", "test_quellen_konflikt.py", "Konfliktfälle"),
    ("Umriss begradigen", "test_umriss_begradigen.py", "Zickzack wird begradigt"),
]
LANGSAM = [
    ("Plan-Korpus-Abdeckung", "test_korpus.py", "ABDECKUNG:"),
    ("Raum-Verifikation", "test_raumverifikation.py", "ERGEBNIS:"),
    ("Rohbau-Raumcheck", "test_rohbau_raumcheck.py", "ROHBAU-verifiziert"),
    ("Räumlicher Beweis (IoU)", "exp_rohbau_iou_v3.py", "RÄUMLICH bewiesen"),
    ("Räume richtig markiert", "mess_raum_markierung.py", "KENNZAHL"),
    ("Plan-Typ-Abdeckung", "mess_plantypen.py", "wie erwartet behandelt"),
]


def lauf(skript):
    r = subprocess.run([PY, os.path.join(ROOT, "scripts", skript)],
                       capture_output=True, text=True, timeout=1500)
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
