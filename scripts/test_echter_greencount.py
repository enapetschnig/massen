#!/usr/bin/env python3
"""ECHTER GREEN-COUNT — die user-seitige Verifikations-Rate, nicht der Roh-Status.

Die älteren Harnesse (test_raumverifikation: Angerer 7/9, --wm 55/70) messen NUR
den rohen verifiziere_seite-Status (F+U-Stempel). Der volle Prod-Pfad
(nachzeichnen.analysiere_seite) beweist zusätzlich über den ROHBAU-Flucht-Beweis
(rohbau_ok, Rect+L) und den IoU-Goldstandard (iou_bewiesen) — genau das, was das
UI grün zählt (upload.js: status==='verifiziert' || rohbau_ok || iou_bewiesen).

Dieser Harness misst DIESE Zahl — die ehrliche Zuverlässigkeit, die der Kunde sieht.

Lauf:  massenermittlung/venv/bin/python3 scripts/test_echter_greencount.py [--wm] [--tg]
"""
import os
import sys
import signal
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "api"))

import fitz            # noqa: E402
import nachzeichnen    # noqa: E402

PLANS = {
    "angerer": ("A-5_Einreichplan_Alfred-Angerer_36_25_Index 0 (1).pdf", 180),
    "wm": ("AU_WM_01 Erdgeschoss_INDEX E (3).pdf", 600),
    "tg": ("WA_Velden_Franzosen Allee_Ausführung_TG Plan22.04.2026.pdf", 400),
}


def messe(key):
    fn, budget = PLANS[key]
    P = os.path.expanduser(f"~/Downloads/{fn}")
    if not os.path.exists(P):
        # Glob-Fallback (INDEX-Varianten / Umbenennungen)
        import glob
        cand = sorted(glob.glob(os.path.expanduser(f"~/Downloads/*{fn.split('_')[0]}*")))
        if not cand:
            print(f"[{key}] Plan fehlt: {fn}")
            return
        P = cand[0]
    signal.signal(signal.SIGALRM, lambda *a: (_ for _ in ()).throw(TimeoutError()))
    signal.alarm(budget)
    t0 = time.time()
    try:
        page = max(fitz.open(P), key=lambda p: p.rect.width * p.rect.height)
        r = nachzeichnen.analysiere_seite(page)
    except Exception as e:
        signal.alarm(0)
        print(f"[{key}] Abbruch nach {time.time()-t0:.0f}s: {type(e).__name__}: {e}")
        return
    signal.alarm(0)
    raeume = r.get("raeume", [])
    if not raeume:
        print(f"[{key}] ok={r.get('ok')} typ={r.get('typ','?')} — keine Räume "
              f"({r.get('grund','')[:50]})")
        return
    n_status = sum(1 for x in raeume if x.get("status") == "verifiziert")
    n_roh = sum(1 for x in raeume if x.get("rohbau_ok") and x.get("status") != "verifiziert")
    n_iou = sum(1 for x in raeume if x.get("iou_bewiesen")
                and x.get("status") != "verifiziert" and not x.get("rohbau_ok"))
    n_green = sum(1 for x in raeume if x.get("status") == "verifiziert"
                  or x.get("rohbau_ok") or x.get("iou_bewiesen"))
    n = len(raeume)
    print(f"[{key}] {time.time()-t0:.0f}s · {n} Räume · "
          f"ECHTER GREEN-COUNT {n_green}/{n} ({100*n_green//n}%)")
    print(f"       davon: Roh-Status {n_status} + rohbau_ok {n_roh} + IoU {n_iou}")


if __name__ == "__main__":
    keys = ["angerer"]
    if "--wm" in sys.argv:
        keys.append("wm")
    if "--tg" in sys.argv:
        keys.append("tg")
    if "--alle" in sys.argv:
        keys = ["angerer", "tg", "wm"]
    for k in keys:
        messe(k)
