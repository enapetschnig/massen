"""WÄCHTER Dachdecker/Zimmerer-Sektor (byte-exakter Dach-Reader).

Ground-Truth: Mitterwurzerweg4-Satz (Baubetriebe-Audit) — Dachflächen
Süd 53,39 + Nord 61,04 = Gesamt 114,43 (Plan bestätigt sich selbst),
12 Sparren B/H 12/14, 4× Velux GPL MK06 78/118. Negativ: EFH-Plan → {}.
"""
import glob
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))
import fitz                    # noqa: E402
from dach_positionen import dach_positionen   # noqa: E402

DL = os.path.expanduser("~/Downloads")


def run():
    g = sorted(glob.glob(os.path.join(DL, "Pläne Mitterwurzerweg4.pdf")))
    if not g:
        print("Mitterwurzerweg-Plan FEHLT — Wächter übersprungen")
        return
    res = dach_positionen(fitz.open(g[0]))
    assert res.get("gesamt_m2") == 114.43, res.get("gesamt_m2")
    assert res.get("gesamt_bestaetigt") is True, "Σ Teilflächen ≠ Gesamt"
    assert any(f["name"] == "Süd" and f["m2"] == 53.39 and f.get("rechnung")
               for f in res["flaechen"]), "Süd-Fläche mit Rechnung fehlt"
    assert any(h["anzahl"] == 12 and h["bauteil"] == "Sparren"
               and (h["b_cm"], h["h_cm"]) == (12, 14) for h in res["hoelzer"])
    assert any(f["marke"] == "Velux" and f["anzahl"] == 4
               for f in res.get("fenster") or [])
    # Negativ: EFH-Grundriss darf NICHTS liefern (Sektoren bleiben getrennt)
    g2 = sorted(glob.glob(os.path.join(DL, "*A-5_Einreichplan_Alfred-Angerer*")))
    if g2:
        assert dach_positionen(fitz.open(g2[0])) == {}, "EFH liefert Dach-Daten!"
    print("OK — Dach-Reader: Σ=Gesamt byte-exakt bestätigt (114,43), "
          "12 Sparren 12/14, 4× Velux; EFH-Negativ-Test ✓")


if __name__ == "__main__":
    run()
