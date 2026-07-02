#!/usr/bin/env python3
"""Raum-Verifikations-Harness (Nachzeichnen 2.0) — der Plan validiert sich selbst.

Misst am echten Angerer-Plan: wie viele Räume lassen sich aus dem Linework (Schraffur-
verankerte Wand-Maske) + byte-exakten Öffnungen so rekonstruieren, dass Fläche F UND
Umfang U aus dem Raum-Stempel getroffen werden? DIE ehrliche Kern-Metrik der Erkennung.

Lauf: massenermittlung/venv/bin/python3 scripts/test_raumverifikation.py
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "api"))

import fitz
import vektor
import nachzeichnen
import raumnetz
import oeffnungen as oeff_mod

PLAN = os.path.expanduser("~/Downloads/A-5_Einreichplan_Alfred-Angerer_36_25_Index 0 (1).pdf")


def _dict_spans(page):
    out = []
    for block in page.get_text("dict").get("blocks", []):
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                txt = (span.get("text") or "").strip()
                if not txt:
                    continue
                bb = tuple(span.get("bbox") or (0, 0, 0, 0))
                out.append({"text": txt, "bbox": bb, "size": span.get("size", 0),
                            "cx": (bb[0] + bb[2]) / 2.0, "cy": (bb[1] + bb[3]) / 2.0})
    return out


def run():
    d = fitz.open(PLAN)
    page = max(d, key=lambda p: p.rect.width * p.rect.height)
    ptm = vektor.kalibriere(page.get_text("words"), "1:100")["ptm_konsens"]
    box = nachzeichnen._eg_box(page, ptm)
    assert ptm and box, "Kalibrierung/Box fehlgeschlagen"
    bx0, bx1, by0, by1 = box

    segs, _f, _n = vektor._drawings(page)
    inb = lambda s: bx0 <= (s[0] + s[2]) / 2 <= bx1 and by0 <= (s[1] + s[3]) / 2 <= by1
    dark = [s for s in segs if (s[5] is None or s[5] < 0.45) and inb(s)
            and vektor._laenge(s) / ptm > 0.10]
    hatch = [s for s in vektor.hatch_segmente(segs) if inb(s)]
    oeff = oeff_mod.extract_oeffnungen_from_text(_dict_spans(page), [])

    res, stempel = raumnetz.verifiziere_seite(page, ptm, box, dark, hatch, oeff)
    assert len(stempel) >= 6, f"zu wenige Stempel erkannt ({len(stempel)})"

    print(f"Box {(bx1-bx0)/ptm:.0f}×{(by1-by0)/ptm:.0f} m · {len(stempel)} Raum-Stempel · "
          f"{len(dark)} Kanten · {len(hatch)} Schraffur · ptm={ptm}")
    print(f"{'Raum':<24}{'F soll':>8}{'F ist':>8}{'U soll':>8}{'U ist':>8}  Status")
    n_ok = 0
    for r in sorted(res, key=lambda x: x["name"] or ""):
        fmt = lambda v: f"{v:>8.2f}" if v is not None else f"{'–':>8}"
        if r["status"] == "verifiziert":
            n_ok += 1
        print(f"{(r['name'] or '?')[:22]:<24}{fmt(r['f_m2'])}{fmt(r['f_ist'])}"
              f"{fmt(r.get('u_m'))}{fmt(r['u_ist'])}"
              f"  {'✓ VERIFIZIERT' if r['status'] == 'verifiziert' else r['status']}")
    print("-" * 70)
    print(f"ERGEBNIS: {n_ok}/{len(res)} Räume verifiziert — DIE Kern-Metrik der "
          f"Erkennung (Ziel: alle Innenräume).")
    return 0


if __name__ == "__main__":
    sys.exit(run())
