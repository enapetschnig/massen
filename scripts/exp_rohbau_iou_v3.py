"""ROHBAU-RAUMCHECK v3 (LOG-only) — RÄUMLICHER Beweis: Form muss die Region DECKEN.

ERKENNTNIS-KETTE (Juli 2026, alles gemessen):
  · Regionen sind ROHBAU, Stempel sind FERTIG → Fluchten-Rechtecke als Rohbau-Soll.
  · F+U UNTERBESTIMMEN Formen (613 passende Boundings am AP.01!) — Skalar-Match
    ist Koinzidenz: Zimmer-1-Rect passte F/U, deckte die Region aber nur zu 0,566.
  · Deshalb v3: Kandidaten (Rect + L) werden per exakter IoU gegen die Region
    GERANKT; Schwelle 0,85 (kalibriert: korrektes Bad = 0,93 — echte Einbauten
    wie Fensternische/Duschkabine drücken legitim unter 1,0).
  · Fluchten-DEDUPE <7cm vorab (5cm-Doppellinien erzeugen Quasi-Duplikat-Formen).
  · Bogen-Türlinien (nur GESCHLOSSENES Ende) als zusätzliche Flucht-Quelle —
    mit IoU als Wächter sicher (der v1-Overfit hatte keinen räumlichen Check).
  · EIN Pfad für alles — kein Sonder-Zweitpass (der ohne IoU absurde Formen baute).

Eindeutigkeit: alle Kandidaten nahe der Top-IoU (−0,03) müssen dieselbe physische
Form sein (alle 4 Bounding-Kanten ±12cm), sonst ambig → NICHT verifiziert.
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


def _dedupe(pos_liste, ptm, tol_m=0.07):
    """Fluchten <tol beisammen verschmelzen (Doppellinien) — erste gewinnt."""
    out = []
    for p in sorted(pos_liste):
        if not out or p - out[-1] > tol_m * ptm:
            out.append(p)
    return out


def run(plan=PLAN, label="1:100", zelle_m=0.02, iou_min=0.85, verbose=True):
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
    dbg = {}
    res, _st = raumnetz.verifiziere_seite(page, ptm, box, dark, hatch, oeff,
                                          zelle_m=zelle_m, debug=dbg)
    label_arr, rstd = dbg["label"], dbg["rst"]
    zm2 = rstd.zm * rstd.zm

    # Fluchten-Pool: Ketten (ok+kurz) + geschlossene Bogen-Türlinien, dedupliziert
    rst = raumnetz._Raster(box, ptm, 0.02)
    fills = vektor.wand_fill_rects(page, box, min_seite_m=0.3, ptm=ptm)
    grid = raumnetz.wand_maske(rst, dark, hatch, [], fill_rects=fills)
    fl = [f for f in massketten.wand_fluchten(words, box, ptm, grid,
                                              rst.W, rst.H, rst.cell)
          if f["ok"] or f.get("lauf", 0) >= 6]
    fv = [f["pos"] for f in fl if f["achse"] == "v"]
    fh = [f["pos"] for f in fl if f["achse"] == "h"]
    try:
        for bg in vektor.tuer_boegen(page, box, ptm):
            hx, hy = bg["hinge"]

            def _poche(pt):
                r2 = (0.28 * ptm) ** 2
                return sum(1 for hh in hatch
                           if ((hh[0] + hh[2]) / 2 - pt[0]) ** 2
                           + ((hh[1] + hh[3]) / 2 - pt[1]) ** 2 <= r2)

            na, nb = _poche(bg["a"]), _poche(bg["b"])
            if na == nb:
                continue
            zu = bg["a"] if na > nb else bg["b"]
            dx, dy = abs(zu[0] - hx), abs(zu[1] - hy)
            if dy < 0.2 * dx:
                fh.append((hy + zu[1]) / 2.0)
            elif dx < 0.2 * dy:
                fv.append((hx + zu[0]) / 2.0)
    except Exception:
        pass
    fv, fh = _dedupe(fv, ptm), _dedupe(fh, ptm)

    n_ok = 0
    for idx, r in enumerate(res):
        f_ziel = r.get("f_m2") or 0
        f_ist, u_ist = r.get("f_ist"), r.get("u_ist")
        if not (f_ziel and f_ist and u_ist):
            continue
        cx, cy = r["cx"], r["cy"]
        Wd = rstd.W
        pts = [(rstd.bx0 + (k % Wd + 0.5) * rstd.cell,
                rstd.by0 + (k // Wd + 0.5) * rstd.cell)
               for k in range(Wd * rstd.H) if label_arr[k] == idx]
        if not pts:
            continue

        def iou(L_, R_, O_, U_, kerbe=None):
            inter = 0
            for (px, py) in pts:
                if L_ <= px <= R_ and O_ <= py <= U_:
                    if not (kerbe and kerbe[0] <= px <= kerbe[1]
                            and kerbe[2] <= py <= kerbe[3]):
                        inter += 1
            f_area = (R_ - L_) * (U_ - O_) / ptm / ptm
            if kerbe:
                f_area -= ((kerbe[1] - kerbe[0]) * (kerbe[3] - kerbe[2])) / ptm / ptm
            union = f_area / zm2 + len(pts) - inter
            return inter / union if union else 0.0

        ober = max(1.15 * f_ziel, 1.10 * f_ziel + 0.25)
        kand = []    # (prefilter_score, L, R, O, U, kerbe, beschr)
        vp = [(a, b) for a in fv if a < cx for b in fv if b > cx
              if 0.5 <= (b - a) / ptm <= 14.0]
        hp = [(a, b) for a in fh if a < cy for b in fh if b > cy
              if 0.5 <= (b - a) / ptm <= 14.0]
        for (l_, r_) in vp:
            w_ = (r_ - l_) / ptm
            for (o_, u_) in hp:
                h_ = (u_ - o_) / ptm
                a_ = w_ * h_
                if 0.98 * f_ziel <= a_ <= ober:
                    kand.append((abs(a_ - f_ist), l_, r_, o_, u_, None,
                                 f"Rect {w_:.2f}×{h_:.2f}"))
                # L-Kandidaten: Bounding per U-Kompatibilität
                if abs(2 * (w_ + h_) - u_ist) / u_ist <= 0.08:
                    for xi in (p for p in fv if l_ < p < r_):
                        for yj in (p for p in fh if o_ < p < u_):
                            for kx in ((l_, xi), (xi, r_)):
                                for ky in ((o_, yj), (yj, u_)):
                                    ka = ((kx[1] - kx[0]) * (ky[1] - ky[0])
                                          / ptm / ptm)
                                    if ka < 0.5:
                                        continue
                                    err = abs(a_ - ka - f_ist)
                                    if err <= 0.05 * f_ziel:
                                        kand.append((err, l_, r_, o_, u_,
                                                     (kx[0], kx[1], ky[0], ky[1]),
                                                     f"L {w_:.2f}×{h_:.2f}−"
                                                     f"{ka:.1f}m²"))
        kand.sort(key=lambda t: t[0])
        gerankt = sorted(((iou(k[1], k[2], k[3], k[4], k[5]),) + k
                          for k in kand[:60]), key=lambda t: -t[0])
        if not gerankt:
            continue
        top = gerankt[0]
        # Eindeutigkeit: alle nahe der Top-IoU = dieselbe physische Form?
        nahe = [g for g in gerankt if g[0] >= top[0] - 0.03]
        gleich = all(abs(g[2] - top[2]) < 0.12 * ptm and abs(g[3] - top[3]) < 0.12 * ptm
                     and abs(g[4] - top[4]) < 0.12 * ptm
                     and abs(g[5] - top[5]) < 0.12 * ptm for g in nahe)
        if top[0] >= iou_min and gleich:
            n_ok += 1
            if verbose:
                print(f"  ✓✓ {r['name']}: {top[7]}  IoU={top[0]:.3f}  "
                      f"(F {f_ist}, U {u_ist})")
        elif verbose:
            grund = f"IoU {top[0]:.2f}<{iou_min}" if top[0] < iou_min \
                else f"{len(nahe)} nahe Formen uneindeutig"
            print(f"  ✗  {r['name']}: {grund}  (beste: {top[7]})")
    print(f"\n{n_ok} Räume RÄUMLICH bewiesen (IoU≥{iou_min}, eindeutig)")
    return n_ok


if __name__ == "__main__":
    if "--wm" in sys.argv:
        import glob
        g = sorted(glob.glob(os.path.expanduser("~/Downloads/*AU_WM_01 Erdgeschoss*")))
        run(g[0], None, zelle_m=0.03)
    else:
        run()   # EXPERIMENT — kein Guard; Befunde s. Memory (WC 0,85-Grenzfall,
        # err-Prefilter kappt räumlich richtige Formen, Dedupe-Strategie offen)
