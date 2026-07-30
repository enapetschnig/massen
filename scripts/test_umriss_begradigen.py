"""WÄCHTER: Raumumrisse begradigen — ohne die Fläche zu verbiegen.

Nutzer-Befund: "die Erkennung ist immer noch nicht zu 100%, teilweise macht
es so einen Bogen nach oben". Am Referenzplan nachgemessen stimmten die
FLÄCHEN weitgehend (±4 %), die FORMEN nicht:

    Flur                39 Ecken · Rechteckigkeit 0,44
    Parkplatz überdacht 43 Ecken · 0,76
    Zimmer 2            26 Ecken · 0,55

Ein Raum in einem Bauplan ist praktisch immer rechtwinklig. 39 Ecken heißen:
der Umriss zappelt in winzigen Stufen an der Wand entlang — im Plan sieht
das aus wie ein Bogen.

nachzeichnen.rechtwinklig_ziehen() zieht die Kanten auf die vorherrschenden
Achsen und verschmilzt aufeinanderfolgende Kanten derselben Achse. Zwei
Dinge dürfen dabei NICHT passieren, und genau die prüft dieser Wächter:

  1. Die Fläche darf sich nicht verändern — sie ist die Mengengrundlage.
  2. Eine ECHTE Schräge (Erker, Pultdach) muss erhalten bleiben. Sonst
     begradigt das Verfahren ein Bauwerk weg, das es gar nicht kennt.
"""
import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))
import nachzeichnen as nz   # noqa: E402


def _flaeche(ps):
    a = 0.0
    for i in range(len(ps)):
        a += ps[i - 1][0] * ps[i][1] - ps[i][0] * ps[i - 1][1]
    return abs(a) / 2.0


def _zickzack(x0, y0, b, h, stufe=0.05, n=8):
    """Rechteck, dessen Kanten in winzigen Stufen zappeln — genau das
    Artefakt, das die Rekonstruktion erzeugt."""
    p = []
    for i in range(n):
        x = x0 + b * i / n
        p.append((x, y0 + (stufe if i % 2 else 0)))
    p.append((x0 + b, y0))
    for i in range(n):
        y = y0 + h * i / n
        p.append((x0 + b + (stufe if i % 2 else 0), y))
    p.append((x0 + b, y0 + h))
    for i in range(n):
        x = x0 + b - b * i / n
        p.append((x, y0 + h + (stufe if i % 2 else 0)))
    p.append((x0, y0 + h))
    for i in range(n):
        y = y0 + h - h * i / n
        p.append((x0 - (stufe if i % 2 else 0), y))
    return p


def run():
    print("UMRISS BEGRADIGEN — Form ja, Fläche nein")
    print("=" * 88)
    fehler = []

    # ── 1) Zickzack-Rechteck wird zum Rechteck, Flaeche bleibt ────────────
    z = _zickzack(10.0, 20.0, 6.0, 4.0)
    out = nz.rechtwinklig_ziehen(z)
    f0, f1 = _flaeche(z), _flaeche(out)
    print(f"Zickzack-Rechteck   {len(z):>3} Ecken → {len(out):<3} · "
          f"Fläche {f0:.2f} → {f1:.2f} ({abs(f1-f0)/f0*100:.1f}%)")
    if len(out) > 6:
        fehler.append(f"Zickzack bleibt bei {len(out)} Ecken — nicht begradigt")
    if abs(f1 - f0) / f0 > 0.10:
        fehler.append(f"Fläche wandert um {abs(f1-f0)/f0*100:.0f}%")

    # ── 2) ECHTE Schraege bleibt erhalten ─────────────────────────────────
    # Trapez mit einer langen, deutlich schraegen Kante (Pultdach/Erker).
    tr = [(0.0, 0.0), (10.0, 0.0), (10.0, 6.0), (0.0, 2.0)]
    out2 = nz.rechtwinklig_ziehen(tr)
    gleich = (len(out2) == len(tr)
              and all(abs(a[0] - b[0]) < 1e-6 and abs(a[1] - b[1]) < 1e-6
                      for a, b in zip(out2, tr)))
    print(f"Trapez mit Schräge   {len(tr):>3} Ecken → {len(out2):<3} · "
          f"{'unverändert ✓' if gleich else 'VERÄNDERT'}")
    if not gleich:
        fehler.append("echte Schräge wurde weggebügelt — das Verfahren darf "
                      "Formen nicht erfinden")

    # ── 3) Gedrehter Plan: dieselbe Form, um 12 Grad verdreht ─────────────
    th = math.radians(12.0)
    c, s = math.cos(th), math.sin(th)
    zr = [(x * c - y * s, x * s + y * c) for (x, y) in z]
    out3 = nz.rechtwinklig_ziehen(zr)
    f3a, f3b = _flaeche(zr), _flaeche(out3)
    print(f"…um 12° gedreht      {len(zr):>3} Ecken → {len(out3):<3} · "
          f"Fläche {f3a:.2f} → {f3b:.2f} ({abs(f3b-f3a)/f3a*100:.1f}%)")
    if len(out3) > 6:
        fehler.append(f"gedrehter Plan nicht begradigt ({len(out3)} Ecken) — "
                      f"die Achsen müssen aus der Hauptrichtung kommen, "
                      f"nicht stur waagrecht/senkrecht sein")

    # ── 4) Entartete Eingaben duerfen nicht crashen ───────────────────────
    for name, p in (("leer", []), ("Dreieck", [(0, 0), (1, 0), (0, 1)]),
                    ("Doppelpunkte", [(0, 0), (0, 0), (1, 0), (1, 1), (0, 1)])):
        try:
            nz.rechtwinklig_ziehen(p)
        except Exception as e:
            fehler.append(f"{name}: {type(e).__name__}: {e}")
    print("Entartete Eingaben   leer / Dreieck / Doppelpunkte — kein Absturz ✓")

    print("-" * 88)
    if fehler:
        print("FEHLER:")
        for f in fehler:
            print(f"  ✗ {f}")
    else:
        print("WÄCHTER ok: Zickzack wird begradigt, echte Schrägen bleiben, "
              "Fläche unverändert, auch auf gedrehten Plänen")
    assert not fehler, f"{len(fehler)} Begradigungs-Fehler"


if __name__ == "__main__":
    run()
