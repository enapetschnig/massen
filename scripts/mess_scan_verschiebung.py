"""Gemeinsame VERSCHIEBUNG statt Einrastung je Raum — traegt das?

Die Einrastung je Raum ist widerlegt (mess_scan_anker.py): jeder Raum sucht
unabhaengig seinen naechsten Fleck, und die Decke dieses Verfahrens liegt bei
0,77 m im Mittel. Damit verschlechtert es jede Vision-Lage, die besser ist.

Dieser Ansatz ist ein anderer. Vision kennt die RELATIVE Lage der Raeume
zueinander viel besser als die absolute — wenn der ganze Satz um denselben
Vektor daneben liegt, ist das mit vielen Raeumen gemeinsam schaetzbar, auch
wenn jede einzelne Paarung verrauscht ist. Die Decke je Raum bindet eine
gemeinsame Schaetzung NICHT: Rauschen mittelt sich heraus, ein systematischer
Versatz nicht.

Gemessen werden drei Fehler-Regime, weil davon alles abhaengt:
  UNABHAENGIG   jeder Raum zufaellig daneben (so hat die bisherige Simulation
                gerechnet) -> eine gemeinsame Verschiebung kann kaum helfen
  SYSTEMATISCH  alle Raeume um DENSELBEN Vektor daneben -> sie muesste fast
                alles zurueckholen
  GEMISCHT      beides zur Haelfte -> der realistische Fall

Und drei Schaetzer:
  MEDIAN   Median der Versatzvektoren aller Raeume (robust, billig)
  RANSAC   zufaellige Paare, groesste Uebereinstimmung gewinnt
  GETRIMMT Median nur ueber die Paare mit kleinstem Abstand (die sichersten)

Bewertet wird wie immer am MITTLEREN LAGEFEHLER je Raum gegen "gar nichts
tun" — nicht gegen die vorige Variante.
"""
import math
import os
import random
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np      # noqa: E402
import nachzeichnen     # noqa: E402
from mess_scan_anker import laden, KURZ, HAERTEN, _korpus_sicherstellen  # noqa: E402


def _vision_lagen(pkt, ppm, regime, staerke_m, rnd):
    """Simulierte Vision-Lagen nach einem der drei Fehler-Regime."""
    n = len(pkt)
    if regime == "systematisch":
        w = rnd.uniform(0, 2 * math.pi)
        gx, gy = (staerke_m * ppm * math.cos(w), staerke_m * ppm * math.sin(w))
        return [(x + gx, y + gy) for (x, y) in pkt]
    if regime == "unabhaengig":
        out = []
        for (x, y) in pkt:
            w = rnd.uniform(0, 2 * math.pi)
            r = abs(rnd.gauss(staerke_m, staerke_m * 0.4)) * ppm
            out.append((x + r * math.cos(w), y + r * math.sin(w)))
        return out
    # gemischt: halb systematisch, halb unabhaengig
    w = rnd.uniform(0, 2 * math.pi)
    s = staerke_m / math.sqrt(2)
    gx, gy = (s * ppm * math.cos(w), s * ppm * math.sin(w))
    out = []
    for (x, y) in pkt:
        w2 = rnd.uniform(0, 2 * math.pi)
        r = abs(rnd.gauss(s, s * 0.4)) * ppm
        out.append((x + gx + r * math.cos(w2), y + gy + r * math.sin(w2)))
    return out


def _paare(lagen, fl, max_px):
    """Je Vision-Lage der naechste Fleck -> Versatzvektoren."""
    out = []
    for (vx, vy) in lagen:
        best, bd = None, 1e18
        for p in fl:
            d = (p[0] - vx) ** 2 + (p[1] - vy) ** 2
            if d < bd:
                bd, best = d, p
        if best is not None and bd ** 0.5 <= max_px:
            out.append((best[0] - vx, best[1] - vy, bd ** 0.5))
    return out


def _schaetzer(paare, art, rnd):
    """-> (dx, dy) gemeinsame Verschiebung, oder None."""
    if len(paare) < 3:
        return None
    if art == "median":
        return (float(np.median([p[0] for p in paare])),
                float(np.median([p[1] for p in paare])))
    if art == "getrimmt":
        s = sorted(paare, key=lambda p: p[2])[:max(3, len(paare) // 2)]
        return (float(np.median([p[0] for p in s])),
                float(np.median([p[1] for p in s])))
    # RANSAC: zufaelliger Vorschlag, meiste Zustimmung gewinnt
    best, best_n = None, -1
    tol = 0.25 * float(np.median([p[2] for p in paare]) or 1.0) + 4.0
    for _ in range(60):
        k = rnd.randrange(len(paare))
        cx, cy = paare[k][0], paare[k][1]
        n = sum(1 for p in paare
                if (p[0] - cx) ** 2 + (p[1] - cy) ** 2 <= tol * tol)
        if n > best_n:
            best_n, best = n, (cx, cy)
    if best is None:
        return None
    inl = [p for p in paare
           if (p[0] - best[0]) ** 2 + (p[1] - best[1]) ** 2 <= tol * tol]
    return (float(np.median([p[0] for p in inl])),
            float(np.median([p[1] for p in inl])))


def run():
    _korpus_sicherstellen()
    daten = []
    for k in KURZ:
        for h in HAERTEN:
            g = laden(k, h)
            if not g:
                continue
            arr, pkt, fla, ppm, _t, _n = g
            daten.append((pkt, ppm, nachzeichnen.textflecken(arr, zell=2)))
    if not daten:
        print("kein Scan-Korpus")
        return
    n_ges = sum(len(d[0]) for d in daten)
    print(f"GEMEINSAME VERSCHIEBUNG — {len(daten)} Scans · {n_ges} Stempel")
    print("=" * 104)
    print("Mittlerer Lagefehler je Raum in Metern. 'ohne' ist der Maßstab —")
    print("alles Groessere verschlechtert die Lage.\n")

    ARTEN = ["median", "getrimmt", "ransac"]
    ergebnis = {}
    for regime in ("unabhaengig", "gemischt", "systematisch"):
        print(f"{regime.upper():16}" + "".join(f"{f'{s} m':>12}" for s in
                                               (0.3, 0.6, 1.2, 2.5)))
        print("-" * 104)
        for art in ["ohne"] + ARTEN:
            zeile = []
            for staerke in (0.3, 0.6, 1.2, 2.5):
                summe, n = 0.0, 0
                for seed in (1, 7, 23, 99):
                    rnd = random.Random(seed)
                    for (pkt, ppm, fl) in daten:
                        lagen = _vision_lagen(pkt, ppm, regime, staerke, rnd)
                        if art == "ohne":
                            neu = lagen
                        else:
                            # Suchradius grosszuegig: die gemeinsame Schaetzung
                            # vertraegt Ausreisser, sie braucht viele Paare.
                            pr = _paare(lagen, fl, max_px=2.0 * staerke * ppm + 30)
                            v = _schaetzer(pr, art, rnd)
                            neu = ([(x + v[0], y + v[1]) for (x, y) in lagen]
                                   if v else lagen)
                        for (nx, ny), (tx, ty) in zip(neu, pkt):
                            summe += ((nx - tx) ** 2 + (ny - ty) ** 2) ** 0.5 / ppm
                            n += 1
                zeile.append(summe / n if n else 0.0)
            ergebnis[(regime, art)] = zeile
            mark = "  <- Maßstab" if art == "ohne" else ""
            print(f"  {art:14}" + "".join(f"{v:12.2f}" for v in zeile) + mark)
        print()

    print("=" * 104)
    print("BEFUND")
    besser_ueberall = []
    for art in ARTEN:
        gewinnt = 0
        gesamt = 0
        for regime in ("unabhaengig", "gemischt", "systematisch"):
            for i in range(4):
                gesamt += 1
                if ergebnis[(regime, art)][i] < ergebnis[(regime, "ohne")][i] - 0.005:
                    gewinnt += 1
        print(f"  {art:10} besser als 'ohne' in {gewinnt}/{gesamt} Faellen")
        if gewinnt == gesamt:
            besser_ueberall.append(art)
    if besser_ueberall:
        print(f"\n  -> {', '.join(besser_ueberall)} verbessert die Lage in JEDEM "
              f"Regime und bei jeder Fehlerstaerke.")
    else:
        print("\n  -> KEIN Schaetzer traegt durchgehend. Wo er im systematischen")
        print("     Regime gewinnt, verliert er im unabhaengigen — und welches")
        print("     Regime bei Vision vorliegt, ist ungemessen. Damit bleibt es")
        print("     bei der Vision-Lage mit ehrlichem Hinweis.")


if __name__ == "__main__":
    run()
