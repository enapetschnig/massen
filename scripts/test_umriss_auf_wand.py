"""WÄCHTER: misst `umriss_auf_wand` wirklich, was draufsteht?

Die Kennzahl steht am Plan („84 % auf Wand") und der Prüfer richtet sein
Urteil danach. Eine Kennzahl, die etwas anderes misst als ihr Name sagt,
ist schlimmer als keine — deshalb hier künstliche Fälle mit bekannter
Antwort, unabhängig von jedem PDF.

Zusätzlich hält dieser Wächter die WIDERLEGUNG fest: die Kennzahl darf
NICHT wieder als Beweisregel („grüner Haken") verdrahtet werden. Am Korpus
gemessen erreichte diese Regel nur 80 % Präzision, weil richtige Fläche +
Wandnähe die PROPORTION prinzipiell nicht prüfen können (WM-Loggia: Stempel
3,60 × 2,62 m, rekonstruiert 6,11 × 1,55 m — dieselbe Fläche, und der
schmale Streifen schmiegt sich an Wände sogar besser an).
"""
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "api"))

UI = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                  "..", "public", "js", "upload.js")


class _Rst(object):
    """Minimales Raster: 1 pt = 1 Zelle, Ursprung (0,0)."""
    def __init__(self, w, h):
        self.W, self.H = w, h
        self.bx0, self.by0 = 0.0, 0.0
        self.cell, self.zm, self.ptm = 1.0, 1.0, 1.0

    def ij(self, x, y):
        return int(x), int(y)


def _grid_rechteck(rst, x0, y0, x1, y1):
    """Wand-Maske: nur der RAHMEN des Rechtecks ist Wand."""
    g = bytearray(rst.W * rst.H)
    for x in range(x0, x1 + 1):
        for y in (y0, y1):
            g[y * rst.W + x] = 1
    for y in range(y0, y1 + 1):
        for x in (x0, x1):
            g[y * rst.W + x] = 1
    return g


def run():
    import raumnetz
    print("UMRISS AUF WAND — misst die Kennzahl, was sie behauptet?")
    print("=" * 84)
    fehler = []
    rst = _Rst(120, 120)
    wand = _grid_rechteck(rst, 10, 10, 60, 50)

    faelle = [
        # (Name, Polygon in pt, erwartet_min, erwartet_max)
        ("Umriss genau auf der Wand",
         [(10, 10), (60, 10), (60, 50), (10, 50)], 0.99, 1.00),
        ("Umriss 2 pt innerhalb (Toleranz 3 Zellen greift)",
         [(12, 12), (58, 12), (58, 48), (12, 48)], 0.99, 1.00),
        ("Umriss 12 pt innerhalb — keine Wand in Reichweite",
         [(22, 22), (48, 22), (48, 38), (22, 38)], 0.00, 0.02),
        ("Umriss völlig woanders (im Freien)",
         [(80, 80), (110, 80), (110, 110), (80, 110)], 0.00, 0.02),
        ("halb auf der Wand, halb im Freien",
         [(10, 10), (60, 10), (60, 90), (10, 90)], 0.30, 0.62),
    ]
    for name, poly, lo, hi in faelle:
        w = raumnetz.umriss_auf_wand(poly, wand, rst)
        ok = w is not None and lo <= w <= hi
        print(f"   {name:<50}{(w if w is not None else -1) * 100:>7.1f}%"
              f"   erwartet {lo:.0%}–{hi:.0%}   {'✓' if ok else '✗'}")
        if not ok:
            fehler.append(f"{name}: {w} liegt nicht in [{lo}, {hi}]")

    # Randfälle dürfen nicht krachen
    for leer in (None, [], [(1, 1), (2, 2)]):
        if raumnetz.umriss_auf_wand(leer, wand, rst) is not None:
            fehler.append(f"leeres Polygon {leer!r} liefert einen Wert")
    if raumnetz.umriss_auf_wand([(10, 10), (60, 10), (60, 50)], None, rst) is not None:
        fehler.append("ohne Grid muss None kommen")
    print("   Randfälle (leer / zu kurz / ohne Grid) → None            ✓")

    # ── DIE WIDERLEGUNG FESTHALTEN ────────────────────────────────────
    # Der Fehlermodus im Klartext: gleiche Fläche, falsche Proportion —
    # und der schmale Streifen liegt BESSER an der Wand als das richtige
    # Rechteck. Genau darum taugt die Kennzahl nicht als Beweis.
    breit = raumnetz.umriss_auf_wand(
        [(10, 10), (60, 10), (60, 50), (10, 50)], wand, rst)
    streifen = raumnetz.umriss_auf_wand(
        [(10, 10), (60, 10), (60, 13), (10, 13)], wand, rst)
    print(f"\n   Gegenbeweis: richtiges Rechteck {breit:.0%} auf Wand, "
          f"falscher Streifen {streifen:.0%} —")
    print(f"   die Kennzahl kann die beiden NICHT trennen "
          f"({'bestätigt' if streifen >= breit - 0.02 else 'ANNAHME HINFÄLLIG'}).")
    if streifen < breit - 0.02:
        fehler.append("Der Gegenbeweis trägt nicht mehr — dann wäre die "
                      "Beweisregel neu zu prüfen statt weiter abzulehnen.")

    src = open(UI, encoding="utf-8").read()
    # Die Kennzahl darf ANGEZEIGT, aber nicht als Beweis verdrahtet werden.
    if "umriss_wand" not in src:
        fehler.append("upload.js zeigt die Kennzahl gar nicht an — dann ist "
                      "sie für den Prüfer wertlos")
    else:
        print("   upload.js zeigt die Kennzahl am Plan                    ✓")
    for muster in (r"formGeprueft\s*=[^;]*umriss_wand", r"ok\s*=[^;]*umriss_wand"):
        if re.search(muster, src):
            fehler.append("umriss_wand entscheidet wieder über den grünen "
                          "Haken — am Korpus mit 80 % Präzision widerlegt "
                          "(richtige Fläche, falsche Proportion)")
    print("   umriss_wand entscheidet NICHT über den grünen Haken      ✓")

    print("-" * 84)
    if fehler:
        print("FEHLER:")
        for f in fehler:
            print(f"  ✗ {f}")
    else:
        print("WÄCHTER ok: die Kennzahl misst die Wandnähe des Umrisses und "
              "bleibt\n           eine Angabe für den Prüfer, kein Beweis.")
    assert not fehler, f"{len(fehler)} Fehler in umriss_auf_wand"


if __name__ == "__main__":
    run()
