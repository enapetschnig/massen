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
    return dbg["label"], dbg["rst"], (mit.get("oeff") or [])


def _tuer_dicht(label, rst, o):
    """-> 'dicht' | 'undicht' | 'offen' für eine Tür."""
    W, H = rst.W, rst.H
    cx, cy = o["cx"], o["cy"]
    b = (o.get("breite_m") or 0.9)
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
        label, rst, oeff = e
        tueren = [o for o in oeff if o.get("typ") == "tuer"
                  and o.get("cx") is not None]
        z = {"dicht": 0, "undicht": 0, "offen": 0}
        for o in tueren:
            z[_tuer_dicht(label, rst, o)] += 1
        ges_d += z["dicht"]; ges_u += z["undicht"]
        print(f"{os.path.basename(g[0])[:42]:<44}{len(tueren):>7}"
              f"{z['dicht']:>7}{z['undicht']:>9}{z['offen']:>8}")
    print("-" * 84)
    bew = ges_d + ges_u
    if bew:
        print(f"KORPUS: {bew} bewertbare Türen · {ges_d} dicht · "
              f"{ges_u} UNDICHT ({ges_u / bew * 100:.0f}%)")
    else:
        print("keine Türen bewertbar — Messung trägt nicht")


if __name__ == "__main__":
    run()
