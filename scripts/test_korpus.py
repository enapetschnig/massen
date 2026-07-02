#!/usr/bin/env python3
"""PLAN-KORPUS-METRIK — macht „funktioniert für alle Pläne" MESSBAR.

Läuft die komplette Lese-Pipeline (Kalibrierung → Box → Wände → Öffnungen →
Raum-Verifikation) über alle bekannten echten Pläne verschiedener Büros und druckt
eine Abdeckungs-Tabelle. Jede Pipeline-Verbesserung muss diese Tabelle heben;
jede Regression fällt sofort auf.

Lauf: massenermittlung/venv/bin/python3 scripts/test_korpus.py
"""
import glob
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "api"))

import fitz
import vektor
import nachzeichnen

DL = os.path.expanduser("~/Downloads")
KORPUS = [
    "A-5_Einreichplan_Alfred-Angerer",
    "AP.01 Layout-1",
    "1762788650811_EG-Wand-Grundriss",
    "05_AU.3.1.1 HAUS A",
    "WA_Velden_Franzosen Allee_Ausführung_TG",
    "WA_Velden_Franzosen Allee_Ausführung_ Schnitt",
]


def _find(teil):
    g = sorted(glob.glob(os.path.join(DL, f"*{teil}*.pdf")))
    return g[0] if g else None


def run():
    print(f"{'Plan':<42}{'Kalib':>7}{'Ansicht':>9}{'Wände':>7}{'Öffn':>6}{'Räume✓':>8}  Anmerkung")
    print("-" * 92)
    n_ansicht = 0
    n_gesamt = 0
    for teil in KORPUS:
        pf = _find(teil)
        if not pf:
            print(f"{teil[:40]:<42} {'—':>6} (Datei fehlt)")
            continue
        n_gesamt += 1
        name = os.path.basename(pf)[:40]
        try:
            r = nachzeichnen.analysiere_doc(fitz.open(pf), max_px=1000)
        except Exception as e:
            print(f"{name:<42} {'✗':>6} CRASH: {str(e)[:40]}")
            continue
        if not r.get("ok"):
            grund = (r.get("grund") or "")[:44]
            # Kalibrierung separat prüfen (war es die Kalibrierung oder die Box?)
            try:
                d = fitz.open(pf)
                page = max(d, key=lambda p: p.rect.width * p.rect.height)
                kal = vektor.kalibriere(page.get_text("words"), nachzeichnen._massstab(page))
                k = "✓" if kal.get("ptm_konsens") else "✗"
            except Exception:
                k = "?"
            print(f"{name:<42}{k:>7}{'✗':>9}{'–':>7}{'–':>6}{'–':>8}  {grund}")
            continue
        n_ansicht += 1
        meta = r.get("meta") or {}
        raeume = r.get("raeume") or []
        n_ok = sum(1 for x in raeume if x.get("status") == "verifiziert")
        kal_txt = "✓" if meta.get("tragfaehig") else "label"
        print(f"{name:<42}{kal_txt:>7}{'✓':>9}{meta.get('n_waende', 0):>7}"
              f"{len(r.get('oeffnungen') or []):>6}{f'{n_ok}/{len(raeume)}' if raeume else '–':>8}"
              f"  Box {meta.get('box_m')}")
    print("-" * 92)
    print(f"ABDECKUNG: {n_ansicht}/{n_gesamt} Pläne mit funktionierender Planansicht.")
    print("(Schnitt-Blätter ohne Grundriss zählen ehrlich als ✗ — dort gibt es nichts nachzuzeichnen.)")
    return 0


if __name__ == "__main__":
    sys.exit(run())
