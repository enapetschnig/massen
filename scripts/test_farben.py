#!/usr/bin/env python3
"""Test des byte-exakten Farb-Legende-Lesers gegen echte Pläne.

Lauf: massenermittlung/venv/bin/python3 scripts/test_farben.py
(braucht venv mit PyMuPDF + die Pläne in ~/Downloads)
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "api"))

import fitz
import farben

DL = os.path.expanduser("~/Downloads")

# (Datei-Teilstring, erwartet_bestand, erwartet_abbruch, erwartete Neubau-Klasse | None)
FAELLE = [
    ("A-5_Einreichplan_Alfred-Angerer", True, True, "rot"),
    ("AP.01 Layout-1", True, True, "rot"),
    ("WA_Velden_Franzosen Allee_Ausführung_ Schnitt", True, True, None),
    ("05_AU.3.1.1 HAUS A", False, False, None),          # reiner Neubau → No-Op
    ("1762788650811_EG-Wand-Grundriss", False, False, None),
]


def _find(teil):
    import glob
    g = sorted(glob.glob(os.path.join(DL, f"*{teil}*.pdf")))
    return g[0] if g else None


def run():
    ok = True
    for teil, e_best, e_abb, e_neu in FAELLE:
        pf = _find(teil)
        if not pf:
            print(f"  ⚠ übersprungen (nicht gefunden): {teil}")
            continue
        d = fitz.open(pf)
        r = farben.analysiere_dokument(d)
        m = r["mapping"]
        neu = (m.get("neubau") or {}).get("klasse")
        zeile = (f"{os.path.basename(pf)[:42]:<44} "
                 f"Bestand={r['hat_bestand']!s:<5} Abbruch={r['hat_abbruch']!s:<5} "
                 f"Neubau={neu or '–'}")
        fehler = []
        if r["hat_bestand"] != e_best:
            fehler.append(f"Bestand {r['hat_bestand']}≠{e_best}")
        if r["hat_abbruch"] != e_abb:
            fehler.append(f"Abbruch {r['hat_abbruch']}≠{e_abb}")
        if e_neu and neu != e_neu:
            fehler.append(f"Neubau-Klasse {neu}≠{e_neu}")
        if fehler:
            ok = False
            print(f"  ✗ {zeile}   FEHLER: {', '.join(fehler)}")
        else:
            print(f"  ✓ {zeile}")
        if r["hinweis"]:
            print(f"      → {r['hinweis']}")
        if m:
            print(f"      Mapping: " + " · ".join(
                f"{b}={ (dd.get('rgb') or dd.get('klasse')) }" for b, dd in m.items()))
    print("-" * 70)
    print("OK — Legende byte-exakt gelesen, reiner Neubau = No-Op." if ok
          else "FEHLER — siehe oben.")
    return ok


if __name__ == "__main__":
    sys.exit(0 if run() else 1)
