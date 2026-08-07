"""MESSUNG: dichten die Türen — oder läuft die Raumfarbe durch?

Nutzer-Befund: "die Räume hören nicht bei den Türen auf". Die Wandmaske
versiegelt Türen bereits über zwei Wege (Türbogen byte-genau aus der
Geometrie, Text-Verschluss mit Beide-Enden-Test) — die Frage ist nicht OB es
ein System gibt, sondern WIE OFT es versagt.

Gemessen wird am Label-Gitter des ECHTEN Pipeline-Laufs (verifiziere_seite
wird abgehört, nicht nachgebaut): für jede erkannte Tür wird quer zur
Türachse beidseitig sondiert. Gehören beide Seiten demselben Raum-Label,
ist die Tür NICHT dicht — die Farbe läuft durch die Öffnung in den
Nachbarraum. Verschiedene Labels (oder eine Seite unbelegt) = dicht.

Das ist die ehrliche Kennzahl hinter dem Nutzer-Eindruck.
"""
import glob
import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))

PLAENE = [
    "A-5_Einreichplan_Alfred-Angerer",
    "AP.01 Layout-1 (1).pdf",
    "AU_WM_01 Erdgeschoss_INDEX E.pdf",
    "WA_Velden_Franzosen Allee_Ausführung_TG",
]


def _lauf_mit_abhoeren(pfad):
    """analysiere_doc normal laufen lassen, verifiziere_seite abhören.
    -> (label, rst, oeffnungen_pt) des Roh-Passes oder None."""
    import fitz
    import nachzeichnen
    import raumnetz
    mit = {}
    orig = raumnetz.verifiziere_seite

    def spion(page, ptm, box, dark, hatch, oeff, **kw):
        dbg = kw.get("debug")
        if dbg is None:
            dbg = {}
            kw["debug"] = dbg
        out = orig(page, ptm, box, dark, hatch, oeff, **kw)
        mit["dbg"] = dbg
        mit["oeff"] = oeff
        return out

    raumnetz.verifiziere_seite = spion
    try:
        doc = fitz.open(pfad)
        nachzeichnen.analysiere_doc(doc, max_px=1400)
        doc.close()
    finally:
        raumnetz.verifiziere_seite = orig
    dbg = mit.get("dbg") or {}
    if dbg.get("label") is None or dbg.get("rst") is None:
        return None
    return (dbg["label"], dbg["rst"], (mit.get("oeff") or []),
            dbg.get("grid"))


def _luecke_finden(grid, rst, cx, cy, b_m):
    """Die ECHTE Türlücke im Raster: Wand · Lücke · Wand um den Anker.

    Der Tür-Textanker liegt NICHT an der Tür — am Korpus gemessen im Median
    0,44–0,63 m daneben, im Extremfall 1,13 m. Genau so weit sondierte die
    alte Messung um den Anker herum: beide Sonden landeten leicht im selben
    Raum, und eine dichte Tür wurde als Leck gemeldet.

    Darum zuerst die Lücke lokalisieren (Wand links/rechts bzw. oben/unten
    innerhalb 1,8 m, Spaltbreite 0,45–2,6 m, am nächsten an der Nennbreite),
    dann QUER ÜBER DIESE LÜCKE sondieren statt um den Anker.
    -> (achse, fest, lo, hi) in Zellen | None
    """
    W, H = rst.W, rst.H
    b_z = max(3, int(round((b_m or 0.9) * rst.ptm / rst.cell)))
    cap = max(4, int(round(1.8 * rst.ptm / rst.cell)))
    fen = max(2, int(round(1.0 * rst.ptm / rst.cell)))
    sp_min = max(3, int(round(0.45 * rst.ptm / rst.cell)))
    sp_max = int(round(2.6 * rst.ptm / rst.cell))
    ci, cj = rst.ij(cx, cy)
    best = None
    for achse in ("h", "v"):
        for off in range(-fen, fen + 1):
            if achse == "h":
                jj = cj + off
                if not (0 <= jj < H):
                    continue
                li = re2 = None
                for d in range(cap + 1):
                    if li is None and 0 <= ci - d < W and grid[jj * W + ci - d]:
                        li = ci - d
                    if re2 is None and 0 <= ci + d < W and grid[jj * W + ci + d]:
                        re2 = ci + d
                    if li is not None and re2 is not None:
                        break
                if li is None or re2 is None:
                    continue
                sp, fest, lo, hi = re2 - li - 1, jj, li, re2
            else:
                ii = ci + off
                if not (0 <= ii < W):
                    continue
                ob = un = None
                for d in range(cap + 1):
                    if ob is None and 0 <= cj - d < H and grid[(cj - d) * W + ii]:
                        ob = cj - d
                    if un is None and 0 <= cj + d < H and grid[(cj + d) * W + ii]:
                        un = cj + d
                    if ob is not None and un is not None:
                        break
                if ob is None or un is None:
                    continue
                sp, fest, lo, hi = un - ob - 1, ii, ob, un
            if not (sp_min <= sp <= sp_max):
                continue
            sc = (abs(sp - b_z), abs(off))
            if best is None or sc < best[0]:
                best = (sc, achse, fest, lo, hi)
    return (best[1], best[2], best[3], best[4]) if best else None


def _tuer_dicht(label, rst, o, grid=None):
    """-> 'dicht' | 'undicht' | 'offen' für eine Tür.

    Mit grid: über der LOKALISIERTEN Lücke sondieren (genau, s.
    _luecke_finden). Ohne grid: alter Anker-Kreis (nur Rückfallebene).
    """
    W, H = rst.W, rst.H
    cx, cy = o["cx"], o["cy"]
    b = (o.get("breite_m") or 0.9)
    if grid is not None:
        _lk = _luecke_finden(grid, rst, cx, cy, b)
        if _lk is None:
            return "offen"          # keine Lücke lokalisierbar → nicht bewertbar
        achse, fest, lo, hi = _lk
        mid = (lo + hi) // 2
        # NACH AUSSEN LAUFEN, BIS EIN RAUM KOMMT: eine feste Sondentiefe
        # landet bei dicken Wänden IM Mauerwerk (Label <0) — dann galten
        # 41 von 74 Türen als "nicht bewertbar", die Messung hätte über die
        # halbe Menge nichts gesagt. Die Sonde läuft darum von der Wandlinie
        # nach außen, bis sie eine Raum-Zelle trifft (max. 1,2 m).
        _max_s = max(3, int(round(1.2 * rst.ptm / rst.cell)))

        def _erste_raumzelle(vz):
            for d in range(1, _max_s + 1):
                if achse == "h":
                    jj = fest + vz * d
                    if not (0 <= jj < H):
                        return None
                    idx = jj * W + mid
                else:
                    ii = fest + vz * d
                    if not (0 <= ii < W):
                        return None
                    idx = mid * W + ii
                if label[idx] >= 0:
                    return label[idx]
            return None

        l1, l2 = _erste_raumzelle(-1), _erste_raumzelle(+1)
        if l1 is None or l2 is None:
            return "offen"
        return "undicht" if l1 == l2 else "dicht"
    leck = None
    getrennt = False
    for wdeg in range(0, 180, 15):
        wx = math.cos(math.radians(wdeg))
        wy = math.sin(math.radians(wdeg))
        d = max(0.45, 0.7 * b) * rst.ptm
        i1, j1 = rst.ij(cx + wx * d, cy + wy * d)
        i2, j2 = rst.ij(cx - wx * d, cy - wy * d)
        if not (0 <= i1 < W and 0 <= j1 < H and 0 <= i2 < W and 0 <= j2 < H):
            continue
        l1, l2 = label[j1 * W + i1], label[j2 * W + i2]
        if l1 >= 0 and l2 >= 0:
            if l1 == l2:
                leck = l1
            else:
                getrennt = True
    if leck is not None:
        return "undicht"
    return "dicht" if getrennt else "offen"


def run():
    print("TÜR-DICHTUNG — endet die Raumfarbe an der Tür?")
    print("=" * 84)
    print(f"{'Plan':<44}{'Türen':>7}{'dicht':>7}{'UNDICHT':>9}{'n.bew.':>8}")
    print("-" * 84)
    ges_d = ges_u = 0
    # PRO PLAN pinnen, nicht nur die Summe.
    # Am 2026-08-03 riss die Summen-Ratsche (29 → 32), obwohl KEIN Plan
    # schlechter geworden war: der Wandpaar-Rückfall machte den Velden-Plan
    # erstmals überhaupt messbar (0 → 6 bewertbare Türen, davon 3 undicht).
    # Eine Summen-Schranke kann „neue Abdeckung" nicht von „Regression"
    # unterscheiden — der A/B-Test musste es zeigen. Pro Plan kann sie das.
    MAX_UNDICHT = {
        "A-5_Einreichplan_Alfred-Angerer": 0,
        "AP.01 Layout-1 (1).pdf": 6,
        "AU_WM_01 Erdgeschoss_INDEX E.pdf": 19,
        "WA_Velden_Franzosen Allee_Ausführung_TG": 3,
    }
    pro_plan = {}
    for m in PLAENE:
        g = sorted(glob.glob(os.path.expanduser(f"~/Downloads/*{m}*")))
        if not g:
            continue
        try:
            e = _lauf_mit_abhoeren(g[0])
        except Exception as ex:
            print(f"{os.path.basename(g[0])[:42]:<44}  FEHLER "
                  f"{type(ex).__name__}: {str(ex)[:32]}")
            continue
        if not e:
            print(f"{os.path.basename(g[0])[:42]:<44}  (kein Label-Gitter)")
            continue
        label, rst, oeff, grid = e
        tueren = [o for o in oeff if o.get("typ") == "tuer"
                  and o.get("cx") is not None]
        z = {"dicht": 0, "undicht": 0, "offen": 0}
        for o in tueren:
            z[_tuer_dicht(label, rst, o, grid)] += 1
        ges_d += z["dicht"]; ges_u += z["undicht"]
        pro_plan[m] = z["undicht"]
        print(f"{os.path.basename(g[0])[:42]:<44}{len(tueren):>7}"
              f"{z['dicht']:>7}{z['undicht']:>9}{z['offen']:>8}")
    print("-" * 84)
    bew = ges_d + ges_u
    if bew:
        print(f"KORPUS: {bew} bewertbare Türen · {ges_d} dicht · "
              f"{ges_u} UNDICHT ({ges_u / bew * 100:.0f}%)")
    else:
        print("keine Türen bewertbar — Messung trägt nicht")

    # MESSGRUNDLAGE 2026-08-01: sondiert wird über der LOKALISIERTEN Türlücke
    # (Wand·Lücke·Wand im Raster), nicht mehr im Kreis um den Text-Anker.
    # Grund: der Anker liegt im Median 0,44–0,63 m neben der Tür (max 1,13 m)
    # — genau die Distanz, die die alte Sonde abtastete.
    #
    # ERWARTET hatte ich, dass die Quote dadurch FÄLLT (Artefakt-These aus
    # zwei Label-Crops). Sie fiel NICHT: 59% (Anker) -> 64% (Lücke) bei 66
    # statt 74 bewertbaren Türen. Ein Zwischenstand mit enger Sonde zeigte
    # 30%, war aber selbst verzerrt (zählte nur Türen mit dünner Wand, weil
    # die Sonde sonst im Mauerwerk landete). Die Lecks sind also ECHT — meine
    # Artefakt-These aus zwei Bildern war zu schnell verallgemeinert.
    #
    # Die neue Messung ist trotzdem die bessere: sie prüft dort, wo die Tür
    # wirklich ist, und macht jede künftige Reparatur sichtbar. Die Schwelle
    # bewacht, dass es nicht SCHLECHTER wird.
    # DIE ABSOLUTE ZAHL IST DER EHRLICHE MASSSTAB, NICHT DIE QUOTE.
    # Eine geschlossene Tür hat keine Wand·Lücke·Wand-Struktur mehr und gilt
    # damit als "nicht bewertbar" — sie verschwindet aus dem Nenner. Beim
    # Zweitdurchgang-Fix fiel die Basis 68 → 53, während die undichten Türen
    # 39 → 29 zurückgingen. Eine Quoten-Schranke hätte den Erfolg als
    # Regression gelesen (57 % → 51 % sieht klein aus, 39 → 24 nicht), und
    # eine `bew >= 40`-Schranke wäre beim nächsten Fortschritt gerissen.
    # Darum: die ANZAHL undichter Türen ist die Ratsche, und ein niedriger
    # Boden stellt nur sicher, dass überhaupt gemessen wurde.
    assert bew >= 25, f"nur {bew} Türen bewertbar — Messung untauglich"
    # PRO PLAN prüfen: nur ein Plan, der SCHLECHTER wird, ist eine Regression.
    _reg = [f"{m.split('_')[0][:16]}: {n} statt max {MAX_UNDICHT[m]}"
            for m, n in pro_plan.items()
            if m in MAX_UNDICHT and n > MAX_UNDICHT[m]]
    assert not _reg, ("Tür-Dichtung geregressiert — "
                      + " · ".join(_reg)
                      + f" (Korpus {ges_u} undicht von {bew}; "
                        f"Ausgangslinie 39 von 68)")
    print(f"   pro Plan gepinnt: "
          + " · ".join(f"{m.split('_')[0][:14]}≤{MAX_UNDICHT[m]}"
                       for m in MAX_UNDICHT))


if __name__ == "__main__":
    run()
