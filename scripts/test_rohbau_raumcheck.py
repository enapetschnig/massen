"""ROHBAU-RAUMCHECK (LOG-only) — Raum-Regionen gegen FLUCHT-Rechtecke.

SYNTHESE der Session Juli 2026: Regionen sind ROHBAU, Stempel sind FERTIG
(Vorwände/Futterkästen, Zeichnungsform variiert) — aber die bestätigten
Maßketten-FLUCHTEN liefern pro Raum das byte-exakte ROHBAU-Rechteck
(nächste Flucht links/rechts/oben/unten vom Stempel). Rohbau gegen Rohbau.

ERSTBEFUND Angerer: Bad ✓✓ (U 12,72 vs 12,71 EXAKT — nie fertig-verifiziert!),
WC ✓F (+3,6%). Grenze: Fluchten-DICHTE (6 h-Fluchten) — Rechtecke spannen
sonst über mehrere Räume. Toleranzen: F ±5%, U ±8%.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))
import fitz            # noqa: E402
import vektor          # noqa: E402
import raumnetz        # noqa: E402
import nachzeichnen    # noqa: E402
import massketten      # noqa: E402
import oeffnungen as oeff_mod    # noqa: E402
from test_raumverifikation import PLAN, _dict_spans   # noqa: E402


def run():
    d = fitz.open(PLAN)
    page = max(d, key=lambda p: p.rect.width * p.rect.height)
    words = page.get_text("words")
    ptm = vektor.kalibriere(words, "1:100")["ptm_konsens"]
    box = nachzeichnen._eg_box(page, ptm)
    bx0, bx1, by0, by1 = box
    segs, _f, _n = vektor._drawings(page)
    inb = lambda s: bx0 <= (s[0] + s[2]) / 2 <= bx1 and by0 <= (s[1] + s[3]) / 2 <= by1
    dark = [s for s in segs if (s[5] is None or s[5] < 0.45) and inb(s)
            and vektor._laenge(s) / ptm > 0.10]
    hatch = vektor.wand_poche(page, (bx0, bx1, by0, by1))
    oeff = oeff_mod.extract_oeffnungen_from_text(_dict_spans(page), [])
    res, _st = raumnetz.verifiziere_seite(page, ptm, box, dark, hatch, oeff)

    rst = raumnetz._Raster(box, ptm, 0.02)
    fills = vektor.wand_fill_rects(page, box, min_seite_m=0.3, ptm=ptm)
    grid = raumnetz.wand_maske(rst, dark, hatch, [], fill_rects=fills)
    fl = [f for f in massketten.wand_fluchten(words, box, ptm, grid,
                                              rst.W, rst.H, rst.cell)
          if f["ok"] or f.get("lauf", 0) >= 6]
    fv = sorted(f["pos"] for f in fl if f["achse"] == "v")
    fh = sorted(f["pos"] for f in fl if f["achse"] == "h")

    n_ok = 0
    for r in res:
        cx, cy = r["cx"], r["cy"]
        links = max((p for p in fv if p < cx), default=None)
        rechts = min((p for p in fv if p > cx), default=None)
        oben = max((p for p in fh if p < cy), default=None)
        unten = min((p for p in fh if p > cy), default=None)
        if None in (links, rechts, oben, unten):
            continue
        w = (rechts - links) / ptm
        h = (unten - oben) / ptm
        f_roh, u_roh = w * h, 2 * (w + h)
        f_ist, u_ist = r.get("f_ist"), r.get("u_ist")
        ok = (f_ist and abs(f_ist - f_roh) / f_roh <= 0.05
              and u_ist and abs(u_ist - u_roh) / u_roh <= 0.08)
        if ok:
            n_ok += 1
            print(f"  ✓✓ {r['name']}: F {f_ist} vs Rohbau {f_roh:.2f} · "
                  f"U {u_ist} vs {u_roh:.2f}  ({w:.2f}×{h:.2f})")
    print(f"\n{n_ok} Räume ROHBAU-verifiziert (Flucht-Rechtecke, F±5%/U±8%)")
    assert n_ok >= 1, "Regression: Bad war rohbau-verifiziert"


if __name__ == "__main__":
    run()
