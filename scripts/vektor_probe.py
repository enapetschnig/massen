#!/usr/bin/env python3
"""Beweis-Harness für die Vektor-"Nachzeichnen"-Pipeline (Phase 0).

Läuft api/vektor.py über mehrere ECHTE Pläne verschiedener Büros und loggt, ob die
pt→m-Kalibrierung STABIL ist (kleine Streuung, genug konsistente Maßketten). Das ist
die Gate-Entscheidung: trägt die Vektor-Lesung über die Plan-Vielfalt, oder nur für
saubere CAD-Exporte? Ehrlicher Mess-Schritt, BEVOR die volle Pipeline gebaut wird.

Lauf (venv mit PyMuPDF):
  massenermittlung/venv/bin/python3 scripts/vektor_probe.py [plan1.pdf plan2.pdf ...]
Ohne Argumente: nimmt die bekannten Pläne aus ~/Downloads.
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "api"))

import fitz
import vektor

DL = os.path.expanduser("~/Downloads")
DEFAULT_PLAENE = [
    "A-5_Einreichplan_Alfred-Angerer_36_25_Index 0 (1).pdf",
    "AP.01 Layout-1 (1).pdf",
    "05_AU.3.1.1 HAUS A SCH 01, SCH 02_INDEX C.pdf",
    "1762788650811_EG-Wand-Grundriss 01.pdf",
    "WA_Velden_Franzosen Allee_Ausführung_TG Plan22.04.2026.pdf",
    "WA_Velden_Franzosen Allee_Ausführung_ Schnitt_21.04.2026Vorabzug.pdf",
]


def _massstab(page):
    import re
    t = page.get_text()
    m = re.search(r"1\s*:\s*(\d{2,4})", t)
    return f"1:{m.group(1)}" if m else None


def run(pfade):
    print(f"{'Plan':<42}{'Quelle':>7}{'Pfade':>8}{'pt/m':>9}{'Streu%':>8}{'Ketten':>8}{'Maßst':>7}  Trag?")
    print("-" * 100)
    ergebnisse = []
    for pf in pfade:
        name = os.path.basename(pf)
        try:
            d = fitz.open(pf)
        except Exception as e:
            print(f"{name[:40]:<42}  Fehler: {e}")
            continue
        # größte Seite (meist der Grundriss-Plan)
        page = max(d, key=lambda p: p.rect.width * p.rect.height)
        mst = _massstab(page)
        r = vektor.analysiere_seite(page, mst)
        kal = r.get("kalibrierung") or {}
        ergebnisse.append((name, r))
        print(f"{name[:40]:<42}{r.get('quelle','?'):>7}{r.get('n_pfade',0):>8}"
              f"{str(kal.get('ptm_konsens') or '–'):>9}{str(kal.get('streuung_pct') or '–'):>8}"
              f"{kal.get('n_ketten_tragfaehig',0):>8}{str(mst or '–'):>7}  "
              f"{'✓' if r.get('tragfaehig') else '✗'}")
    # ── Querschnitt-Urteil ──
    print("-" * 100)
    vek = [r for _, r in ergebnisse if r.get("quelle") == "vektor"]
    trag = [r for r in vek if r.get("tragfaehig")]
    ptms = [r["kalibrierung"]["ptm_konsens"] for r in trag if r["kalibrierung"].get("ptm_konsens")]
    print(f"{len(vek)} Vektor-Pläne · {len(trag)} mit tragfähiger Kalibrierung "
          f"(genug konsistente Maßketten, Streuung ≤8%).")
    if ptms:
        sp = (max(ptms) - min(ptms)) / (sum(ptms) / len(ptms)) * 100
        print(f"pt/m über die tragfähigen Pläne: {[round(p,1) for p in ptms]}  → "
              f"Plan-übergreifende Spanne {sp:.0f}% (erwartbar groß: verschiedene Maßstäbe; "
              f"entscheidend ist die Streuung INNERHALB eines Plans).")
    print()
    if len(trag) >= max(2, len(vek) // 2):
        print("URTEIL: Kalibrierung trägt auf der Mehrheit → Phase 1/2 (Wand-Länge) lohnt.")
    else:
        print("URTEIL: Kalibrierung instabil auf der Plan-Vielfalt → Vektor-Pipeline nur für "
              "saubere CAD-Exporte tragfähig, NICHT als Generalprodukt. Ehrlich so dokumentieren.")
    return ergebnisse


if __name__ == "__main__":
    args = sys.argv[1:]
    pfade = args if args else [os.path.join(DL, n) for n in DEFAULT_PLAENE if os.path.exists(os.path.join(DL, n))]
    if not pfade:
        print("Keine Plan-PDFs gefunden. Pfade als Argumente übergeben.")
        sys.exit(1)
    run(pfade)
