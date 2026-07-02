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


def run(plan=PLAN, label="1:100", zelle_m=0.02):
    d = fitz.open(plan)
    page = max(d, key=lambda p: p.rect.width * p.rect.height)
    words = page.get_text("words")
    ptm = vektor.kalibriere(words, label)["ptm_konsens"]
    box = nachzeichnen._eg_box(page, ptm)
    bx0, bx1, by0, by1 = box
    segs, _f, _n = vektor._drawings(page)
    inb = lambda s: bx0 <= (s[0] + s[2]) / 2 <= bx1 and by0 <= (s[1] + s[3]) / 2 <= by1
    dark = [s for s in segs if (s[5] is None or s[5] < 0.45) and inb(s)
            and vektor._laenge(s) / ptm > 0.10]
    hatch = vektor.wand_poche(page, (bx0, bx1, by0, by1))
    oeff = oeff_mod.extract_oeffnungen_from_text(_dict_spans(page), [])
    res, _st = raumnetz.verifiziere_seite(page, ptm, box, dark, hatch, oeff,
                                          zelle_m=zelle_m)

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
        # FLUCHT-PAAR-SUCHE (v2, WM-Diagnose: bei dichten Fluchten liefert jede
        # Wand ZWEI Fluchten — "nächste" ergibt 2cm-Rechtecke). Wähle die
        # (links,rechts)×(oben,unten)-Kombination, die den Stempel enthält und
        # deren Fläche F_stempel×[0,98..1,15] am besten trifft (Fertig→Rohbau
        # wächst um Putz/Vorwände; byte-exakt eindeutig, reconstruct_bbox-Prinzip).
        f_ziel = r.get("f_m2") or 0
        if not f_ziel:
            continue
        vp = [(a, b) for a in fv if a < cx for b in fv if b > cx
              if 0.5 <= (b - a) / ptm <= 14.0]
        hp = [(a, b) for a in fh if a < cy for b in fh if b > cy
              if 0.5 <= (b - a) / ptm <= 14.0]
        best = None
        for (l_, r_) in vp:
            w_ = (r_ - l_) / ptm
            for (o_, u_) in hp:
                h_ = (u_ - o_) / ptm
                fl_a = w_ * h_
                if not (0.98 * f_ziel <= fl_a <= 1.15 * f_ziel):
                    continue
                score = abs(fl_a - 1.06 * f_ziel)
                if best is None or score < best[0]:
                    best = (score, l_, r_, o_, u_)
        rect_ok = False
        if best:
            _sc0, l0, r0, o0, u0 = best
            w0 = (r0 - l0) / ptm
            h0 = (u0 - o0) / ptm
            f_r0, u_r0 = w0 * h0, 2 * (w0 + h0)
            f_i0, u_i0 = r.get("f_ist"), r.get("u_ist")
            rect_ok = bool(f_i0 and abs(f_i0 - f_r0) / f_r0 <= 0.05
                           and u_i0 and abs(u_i0 - u_r0) / u_r0 <= 0.08)
        if not rect_ok:
            # STUFE 2 — L-FORM (Flur/Waschen/Wohnküche gemessen, Fehler 0,02-0,08m²):
            # achsparalleles L hat den UMFANG seiner Bounding-Box; F = W×H − Kerbe.
            # Bounding per U-Kompatibilität (±8%), Kerbe als Eck-Rechteck an
            # inneren Fluchten (byte-exakt), |WH−Kerbe−f_ist| ≤ 5%.
            u_ist0 = r.get("u_ist")
            if not u_ist0:
                continue
            lbest = None
            for L_ in (p for p in fv if p < cx):
                for R_ in (p for p in fv if p > cx):
                    W_ = (R_ - L_) / ptm
                    if not 0.5 <= W_ <= 14:
                        continue
                    for O_ in (p for p in fh if p < cy):
                        for U_ in (p for p in fh if p > cy):
                            H_ = (U_ - O_) / ptm
                            if not 0.5 <= H_ <= 14:
                                continue
                            if abs(2 * (W_ + H_) - u_ist0) / u_ist0 > 0.08:
                                continue
                            WH = W_ * H_
                            for xi in (p for p in fv if L_ < p < R_):
                                for yj in (p for p in fh if O_ < p < U_):
                                    for wn in ((xi - L_) / ptm, (R_ - xi) / ptm):
                                        for hn in ((yj - O_) / ptm, (U_ - yj) / ptm):
                                            err = abs(WH - wn * hn - (r.get("f_ist") or 0))
                                            if err <= 0.05 * f_ziel and (
                                                    lbest is None or err < lbest[0]):
                                                lbest = (err, W_, H_, wn, hn)
            if lbest:
                n_ok += 1
                print(f"  ✓✓L {r['name']}: F {r.get('f_ist')} ≈ "
                      f"{lbest[1]:.2f}×{lbest[2]:.2f} − {lbest[3]:.2f}×{lbest[4]:.2f} "
                      f"(Fehler {lbest[0]:.2f}m²) · U {r.get('u_ist')}")
            continue
        _sc, links, rechts, oben, unten = best
        w = (rechts - links) / ptm
        h = (unten - oben) / ptm   # (rect_ok: unten folgt die bestehende Ausgabe)
        f_roh, u_roh = w * h, 2 * (w + h)
        f_ist, u_ist = r.get("f_ist"), r.get("u_ist")
        ok = (f_ist and abs(f_ist - f_roh) / f_roh <= 0.05
              and u_ist and abs(u_ist - u_roh) / u_roh <= 0.08)
        if ok:
            n_ok += 1
            print(f"  ✓✓ {r['name']}: F {f_ist} vs Rohbau {f_roh:.2f} · "
                  f"U {u_ist} vs {u_roh:.2f}  ({w:.2f}×{h:.2f})")
    print(f"\n{n_ok} Räume ROHBAU-verifiziert (Flucht-Rechtecke, F±5%/U±8%)")
    return n_ok


if __name__ == "__main__":
    if "--wm" in sys.argv:
        import glob
        g = sorted(glob.glob(os.path.expanduser("~/Downloads/*AU_WM_01 Erdgeschoss*")))
        run(g[0], None, zelle_m=0.03)   # Großplan: gröberes Raster für Laufzeit
    else:
        n = run()
        assert n >= 5, "Regression: Z1+Bad+Geräte (Rect) + Flur/Waschen/Wohnküche (L) waren rohbau-verifiziert"
