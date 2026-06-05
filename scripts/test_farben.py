#!/usr/bin/env python3
"""Test des byte-exakten Farb-Legende-Lesers + Präzisions-Gate gegen echte Pläne.

Lauf: massenermittlung/venv/bin/python3 scripts/test_farben.py
(braucht venv mit PyMuPDF + die Pläne in ~/Downloads)
"""
import glob
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "api"))

import fitz
import farben

DL = os.path.expanduser("~/Downloads")

# (Datei-Teilstring, erw_bestand, erw_abbruch, erw Neubau-Klasse | None)
# Präzisions-Gate: NUR echte Bestand/Abbruch-Elemente → True. Boilerplate-Legende → False.
FAELLE = [
    ("A-5_Einreichplan_Alfred-Angerer", True, True, "rot"),    # echt: Bestandshütte + 13,5% Abbruch-Gelb
    ("AP.01 Layout-1", False, False, "rot"),                   # Boilerplate (gleiche Legende, 0,1% Inhalt)
    ("WA_Velden_Franzosen Allee_Ausführung_ Schnitt", False, False, None),  # Boilerplate-Schnittblatt
    ("05_AU.3.1.1 HAUS A", False, False, None),                # reiner Neubau → No-Op
    ("1762788650811_EG-Wand-Grundriss", False, False, None),   # reiner Neubau
]


def _find(teil):
    g = sorted(glob.glob(os.path.join(DL, f"*{teil}*.pdf")))
    return g[0] if g else None


def _unit_tests():
    """Edge-Cases ohne PDF: Farb-Normalisierung + Mehr-Token-Join + Robustheit."""
    ok = True
    # _norm_rgb: DeviceGray (float), RGB, CMYK, Müll
    cases = [
        (0.5, (0.5, 0.5, 0.5)),
        ((1.0, 0.0, 0.0), (1.0, 0.0, 0.0)),
        ((0.0, 0.0, 0.0, 0.0), (1.0, 1.0, 1.0)),   # CMYK weiß
        ((0.0, 0.0, 0.0, 1.0), (0.0, 0.0, 0.0)),   # CMYK schwarz
        (None, None),
        ("quatsch", None),
        ((1, 2), None),
    ]
    for inp, exp in cases:
        got = farben._norm_rgb(inp)
        if got != exp and not (exp and got and all(abs(a - b) < 1e-6 for a, b in zip(got, exp))):
            print(f"  ✗ _norm_rgb({inp!r}) = {got} ≠ {exp}")
            ok = False
    # _klasse: gelb UND gold beide → 'gelb' (kein harter Cliff)
    for col, exp in [((1, 1, 0), "gelb"), ((1, 0.84, 0), "gelb"), ((1, 0, 0), "rot"),
                     ((0.62, 0.62, 0.62), "grau")]:
        if farben._klasse(col) != exp:
            print(f"  ✗ _klasse({col}) = {farben._klasse(col)} ≠ {exp}")
            ok = False
    # Mehr-Token-Join 'Neu'+'bau' → neubau
    words = [(100, 50, 130, 62, "Neu"), (132, 50, 160, 62, "bau")]
    tr = farben._legende_treffer(words)
    if not any(b == "neubau" for (b, *_r) in tr):
        print(f"  ✗ Mehr-Token-Join 'Neu bau' nicht erkannt: {tr}")
        ok = False
    # 'Bestandshütte' darf NICHT als 'bestand' zählen
    if farben._wort_bedeutung("Bestandshütte") is not None:
        print("  ✗ 'Bestandshütte' fälschlich als Legende-Wort")
        ok = False
    print("  ✓ Unit-Tests (Farb-Norm, CMYK, gelb/gold, Token-Join, Bestandshütte-Gate)"
          if ok else "  ✗ Unit-Tests FEHLER")
    return ok


def run():
    ok = _unit_tests()
    for teil, e_best, e_abb, e_neu in FAELLE:
        pf = _find(teil)
        if not pf:
            print(f"  ⚠ übersprungen (nicht gefunden): {teil}")
            continue
        d = fitz.open(pf)
        r = farben.analysiere_dokument(d)
        m = r["mapping"]
        neu = (m.get("neubau") or {}).get("klasse")
        dbg = r.get("_debug", {})
        zeile = (f"{os.path.basename(pf)[:40]:<42} "
                 f"Bestand={r['hat_bestand']!s:<5} Abbruch={r['hat_abbruch']!s:<5} "
                 f"Neubau={neu or '–':<5} "
                 f"[Bw×{dbg.get('n_bestand_wort','?')} Aw×{dbg.get('n_abbruch_wort','?')} "
                 f"Agelb={dbg.get('abbruch_inhalt_pct','?')}%]")
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
    print("-" * 70)
    print("OK — Legende byte-exakt + Präzisions-Gate trennt echt von Boilerplate." if ok
          else "FEHLER — siehe oben.")
    return ok


if __name__ == "__main__":
    sys.exit(0 if run() else 1)
