#!/usr/bin/env python3
"""Guard fürs Aufmaßblatt-PDF: erzeugt es aus dem Angerer-Plan und prüft Grundform.

Lauf: massenermittlung/venv/bin/python3 scripts/test_aufmassblatt.py
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "api"))

import fitz
import nachzeichnen
import aufmassblatt

PLAN = os.path.expanduser("~/Downloads/A-5_Einreichplan_Alfred-Angerer_36_25_Index 0 (1).pdf")


def run():
    r = nachzeichnen.analysiere_doc(fitz.open(PLAN), max_px=1200)
    assert r.get("ok"), f"nachzeichnen nicht ok: {r.get('grund')}"
    pdf = aufmassblatt.erzeuge(r, projekt_name="Test")
    assert pdf[:5] == b"%PDF-", "kein PDF"
    assert len(pdf) > 50_000, f"PDF verdächtig klein ({len(pdf)} B)"
    d = fitz.open(stream=pdf, filetype="pdf")
    assert d.page_count >= 1
    txt = d[0].get_text()
    for muss in ("AUFMASSBLATT", "Wandlängen", "Räume"):
        assert muss in txt, f"'{muss}' fehlt im PDF-Text"
    print(f"  ✓ Aufmaßblatt: {len(pdf)//1024} KB · {d.page_count} Seite(n) · Kopf/Legende/Summen im Text")
    # graceful-fail: kaputtes Ergebnis → ValueError, kein Crash-PDF
    try:
        aufmassblatt.erzeuge({"ok": False})
        print("  ✗ erwartete ValueError blieb aus")
        return 1
    except ValueError:
        print("  ✓ graceful: unbrauchbares Ergebnis → ValueError")
    print("OK — Aufmaßblatt-Guard grün.")
    return 0


if __name__ == "__main__":
    sys.exit(run())
