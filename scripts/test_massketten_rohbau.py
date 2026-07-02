"""MASSKETTEN-ROHBAU-METRIK (LOG-only) — Wandflächen gegen byte-exakte Ketten.

ERKENNTNIS (Juli 2026, Geräte-/WC-/Waschen-Sezierung): Raum-Stempel messen den
FERTIG-Raum (inkl. Vorwände/Futterkästen/Putz, Zeichnungsform variiert), unsere
Geometrie den ROHBAU. Für die Materialliste (HLZ!) ist ROHBAU das Produktmaß —
und die byte-exakten Rohbau-Sollwerte stehen in den MASSKETTEN.

METRIK: Jedes Ketten-Einzelmaß impliziert zwei WANDFLÄCHEN-Ebenen (Label sitzt
mittig über seinem Segment → Grenzen = pos ± wert/2). Eine Grenze gilt als
BESTÄTIGT, wenn die Wand-Maske dort eine Flächen-Kante (frei↔Wand-Übergang über
≥0,4m Lauflänge) innerhalb ±3,5cm zeigt.

Ausgabe: bestätigte/geprüfte Grenzen je Achse + Fehlliste (= Arbeitsliste).
"""
import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))
import fitz            # noqa: E402
import vektor          # noqa: E402
import nachzeichnen    # noqa: E402
import raumnetz        # noqa: E402
import massketten      # noqa: E402

PLAN = os.path.expanduser("~/Downloads/A-5_Einreichplan_Alfred-Angerer_36_25_Index 0 (1).pdf")


from massketten import sub_ketten   # eine Quelle — Produkt & Metrik identisch


def flaechen_kanten(grid, rst, achse):
    """Wandflächen-Ebenen der Maske: x-Positionen (achse='v') bzw. y-Positionen
    ('h') mit vielen frei↔Wand-Übergängen. → dict {zell_index: anzahl_transitionen}"""
    W, H = rst.W, rst.H
    kanten = {}
    if achse == "v":
        for i in range(1, W):
            n = sum(1 for j in range(H)
                    if grid[j * W + i] != grid[j * W + i - 1])
            if n:
                kanten[i] = n
    else:
        for j in range(1, H):
            n = sum(1 for i in range(W)
                    if grid[j * W + i] != grid[(j - 1) * W + i])
            if n:
                kanten[j] = n
    return kanten


def pruefe(plan_pfad=PLAN, label="1:100", tol_m=0.035, min_lauf_m=0.4, verbose=True):
    d = fitz.open(plan_pfad)
    page = max(d, key=lambda p: p.rect.width * p.rect.height)
    words = page.get_text("words")
    ptm = vektor.kalibriere(words, label)["ptm_konsens"]
    box = nachzeichnen._eg_box(page, ptm) if ptm else None
    if ptm and not box:
        box = nachzeichnen._wandbox(page, ptm)   # Pläne ohne Raumnamen
    if not (ptm and box):
        print("Kalibrierung/Box fehlgeschlagen")
        return None
    bx0, bx1, by0, by1 = box

    segs, _f, _n = vektor._drawings(page)
    inb = lambda s: bx0 <= (s[0] + s[2]) / 2 <= bx1 and by0 <= (s[1] + s[3]) / 2 <= by1
    dark = [s for s in segs if (s[5] is None or s[5] < 0.45) and inb(s)
            and vektor._laenge(s) / ptm > 0.10]
    hatch = vektor.wand_poche(page, (bx0, bx1, by0, by1))
    rst = raumnetz._Raster(box, ptm, 0.02)
    grid = raumnetz.wand_maske(rst, dark, hatch, [])   # ohne Verschlüsse: reine Wände

    spans = massketten.numeric_spans(words) \
        + massketten.numeric_spans(words, meter_notation=True)   # Union (wie Produkt)
    # Nur Ketten DIESER Ansicht: das Blatt trägt auch OG/Schnitt-Maßketten
    # (gemessen: Züge @y=1067 weit außerhalb der EG-Box) — Spans müssen in
    # Box ± 3m liegen (Maßlinien sitzen knapp außerhalb des Gebäudes).
    m3, m1 = 3.0 * ptm, 1.0 * ptm
    spans = [(x, y, v) for (x, y, v) in spans
             if bx0 - m3 <= x <= bx1 + m3 and by0 - m3 <= y <= by1 + m3]
    k = ptm / 100.0
    min_lauf = int(min_lauf_m / rst.zm)
    tol_z = max(1, int(tol_m / rst.zm))
    ergebnisse = {}
    for achse in ("h", "v"):
        chains = vektor._chains_mit_pos(spans, achse)
        ketten = sub_ketten(chains, ptm)
        kanten = flaechen_kanten(grid, rst, "v" if achse == "h" else "h")
        base = rst.bx0 if achse == "h" else rst.by0

        def kante_ok(pos_pt):
            iz = int((pos_pt - base) / rst.cell)
            return max((kanten.get(iz + o, 0)
                        for o in range(-tol_z, tol_z + 1)), default=0) >= min_lauf

        lo, hi = (bx0, bx1) if achse == "h" else (by0, by1)
        treffer, geprueft = 0, 0
        details = []
        for b0_lab, grenzen_cm, werte in ketten:
            # SNAP: starre byte-exakte Struktur, 1 Freiheitsgrad (Translation) —
            # bestes B0 in ±35cm um die grobe Label-Lage (1cm-Schritte)
            best_b0, best_hits = b0_lab, -1
            for off_cm in range(-60, 61):   # wie massketten.wand_fluchten
                b0 = b0_lab + off_cm * k
                hits = sum(1 for g_cm in grenzen_cm if kante_ok(b0 + g_cm * k))
                if hits > best_hits:
                    best_hits, best_b0 = hits, b0
            im_bild = [g_cm for g_cm in grenzen_cm
                       if lo - 0.1 * ptm <= best_b0 + g_cm * k <= hi + 0.1 * ptm]
            if len(im_bild) < 2:
                continue    # Zug liegt (nach Snap) nicht in dieser Ansicht
            hits = sum(1 for g_cm in im_bild if kante_ok(best_b0 + g_cm * k))
            n = len(im_bild)
            treffer += hits
            geprueft += n
            details.append((hits, n, werte, best_b0))
        ergebnisse[achse] = (treffer, geprueft, details)
        if verbose:
            print(f"Achse {achse}: {treffer}/{geprueft} Grenzen nach Snap bestätigt "
                  f"(±{tol_m * 100:.1f}cm, Lauf ≥{min_lauf_m}m, {len(ketten)} Züge)")
            for hits, n, werte, b0 in sorted(details)[:6]:
                if hits < n:
                    print(f"    {hits}/{n}  Zug {werte[:8]} @ {b0:.0f}")
    t = sum(v[0] for v in ergebnisse.values())
    g = sum(v[1] for v in ergebnisse.values())
    # ZWEI ZAHLEN (AP.01-Sezierung: Polierpläne bemaßen ALLES — Außenanlagen-
    # und Öffnungs-Züge messen keine Wände und verwässern den Nenner):
    #   WAND-Züge = ≥50% der Grenzen treffen nach Snap → deren Abdeckung
    #   misst die MASKEN-Qualität; der Wand-Zug-Anteil die Plan-Interpretierbarkeit.
    alle_det = [dd for v in ergebnisse.values() for dd in v[2]]
    wand = [(h, n) for h, n, _w, _b in alle_det if n and h / n >= 0.5]
    wt = sum(h for h, _n in wand)
    wg = sum(n for _h, n in wand)
    if verbose:
        print(f"\nGESAMT: {t}/{g} = {100 * t / max(1, g):.0f}% aller Grenzen | "
              f"WAND-Züge: {len(wand)}/{len(alle_det)} Züge, davon "
              f"{wt}/{wg} = {100 * wt / max(1, wg):.0f}% Grenzen bestätigt")
    ergebnisse["wand"] = (wt, wg, len(wand), len(alle_det))
    return ergebnisse


def korpus():
    import glob
    DL = os.path.expanduser("~/Downloads")
    plaene = [
        ("A-5_Einreichplan_Alfred-Angerer", "1:100"),
        ("AU_WM_01 Erdgeschoss", None),
        ("AP.01 Layout-1", None),
        ("1762788650811_EG-Wand-Grundriss 01.pdf", None),
        ("05_AU.3.1.1 HAUS A", None),
    ]
    for teil, label in plaene:
        g = sorted(glob.glob(os.path.join(DL, f"*{teil}*")))
        print(f"\n=== {teil} ===")
        if not g:
            print("  FEHLT")
            continue
        try:
            pruefe(g[0], label, verbose=True)
        except Exception as e:
            print(f"  FEHLER {type(e).__name__}: {e}")


if __name__ == "__main__":
    if "--korpus" in sys.argv:
        korpus()
    else:
        pruefe()
