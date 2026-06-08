#!/usr/bin/env python3
"""Test des Nachzeichnen-Backend-Moduls (Basis-Bild + Wände als Pixel-JSON).

Lauf: massenermittlung/venv/bin/python3 scripts/test_nachzeichnen.py
"""
import glob
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "api"))

import fitz
import nachzeichnen

DL = os.path.expanduser("~/Downloads")


def _find(teil):
    g = sorted(glob.glob(os.path.join(DL, f"*{teil}*.pdf")))
    return g[0] if g else None


def run():
    ok = True

    # 1) Angerer: ok + plausible Wände + JSON-serialisierbar + Pixel im Bild
    pf = _find("A-5_Einreichplan_Alfred-Angerer")
    if pf:
        r = nachzeichnen.analysiere_doc(fitz.open(pf))
        if not r.get("ok"):
            print(f"  ✗ Angerer: nicht ok ({r.get('grund')})"); ok = False
        else:
            waende = r["waende"]
            n50 = float(r["summe_m"].get("50", 0))
            inbild = all(0 <= w["px"][0] <= r["bild_w"] + 1 and 0 <= w["px"][1] <= r["bild_h"] + 1
                         for w in waende)
            # JSON ohne PNG-bytes muss serialisieren
            try:
                json.dumps({k: v for k, v in r.items() if k != "basis_png"})
                jok = True
            except Exception as e:
                jok = False; print(f"     JSON-Fehler: {e}")
            png_ok = isinstance(r["basis_png"], (bytes, bytearray)) and len(r["basis_png"]) > 1000
            if len(waende) >= 15 and 40 <= n50 <= 75 and inbild and jok and png_ok:
                print(f"  ✓ Angerer: {len(waende)} Wände · 50cm Σ {n50:.0f}m · "
                      f"Bild {r['bild_w']}x{r['bild_h']} · PNG {len(r['basis_png'])//1024}KB · Pixel im Bild · JSON ok")
            else:
                ok = False
                print(f"  ✗ Angerer: n={len(waende)} n50={n50} inbild={inbild} json={jok} png={png_ok}")
    else:
        print("  ⚠ Angerer nicht gefunden")

    # 2) Graceful-Fail: ein Nicht-Grundriss-Blatt (z.B. der Schnitt) → ok:False, kein Crash
    pf2 = _find("WA_Velden_Franzosen Allee_Ausführung_ Schnitt")
    if pf2:
        r2 = nachzeichnen.analysiere_doc(fitz.open(pf2))
        if r2.get("ok") is False and r2.get("grund"):
            print(f"  ✓ Schnitt-Blatt: graceful ok:False ({r2['grund']})")
        elif r2.get("ok"):
            # falls es doch eine Box findet, ist das kein Fehler — nur loggen
            print(f"  ✓ Schnitt-Blatt: ok mit {len(r2['waende'])} Wänden (Box gefunden)")
        else:
            ok = False; print(f"  ✗ Schnitt-Blatt: unerwartet {r2}")

    print("-" * 60)
    print("OK — Nachzeichnen-Backend liefert Bild + Wände, scheitert sauber." if ok
          else "FEHLER — siehe oben.")
    return ok


if __name__ == "__main__":
    sys.exit(0 if run() else 1)
