"""Kann man zur LAUFZEIT erkennen, wann Einrasten hilft?

Befund aus mess_scan_anker.py: ueber den ganzen Scan-Korpus schadet das
Einrasten bei jedem Vision-Versatz. Aber die Decke ist je Plan sehr
verschieden:

    angerer  0,10-0,12 m   9/9 Stempel unter 0,5 m   <- Einrasten waere Gold
    ap01     0,30-0,43 m   5-7/9
    velden   0,66-0,72 m   9-11/25
    au_wm    0,93-0,98 m   24-26/70                  <- Einrasten ist Muenzwurf

Bedingungsloses Einrasten mittelt das zusammen und verliert. Die Frage ist
darum nicht "enger oder weiter", sondern: gibt es ein Merkmal, das OHNE
Wahrheit erkennbar ist und die guten Faelle von den schlechten trennt?

Drei Kandidaten, alle zur Laufzeit berechenbar:
  TOR A  Im eigenen Raum-Kasten liegt GENAU EIN Textfleck. Dann ist er mit
         hoher Wahrscheinlichkeit die Beschriftung dieses Raums.
  TOR B  Der naechste Fleck liegt deutlich naeher als der zweitnaechste
         (Verhaeltnistest). Trennt "eine Beschriftung" von "Textgewimmel".
  TOR C  Fleckendichte im Raum-Kasten unter einer Schwelle.

Bewertet wird wie zuvor am MITTLEREN LAGEFEHLER je Raum gegen "gar nicht
einrasten" — und zusaetzlich, wie viele Raeume das Tor ueberhaupt passieren
(ein Tor, das nie oeffnet, ist keine Loesung).
"""
import math
import os
import random
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))
import numpy as np      # noqa: E402

SP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_scan_korpus_daten")
os.makedirs(SP, exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mess_scan_anker import laden, KURZ, HAERTEN   # noqa: E402
import nachzeichnen     # noqa: E402


def lauf(daten, tor, tol_faktor, rausch_m, seed):
    """-> (mittlerer Lagefehler, Anteil eingerastet, Anteil davon richtig)."""
    rnd = random.Random(seed)
    feh, n_ein, n_richtig, n = [], 0, 0, 0
    for (arr, pkt, fla, ppm, f2, f4) in daten:
        fl = f2
        for i, (tx, ty) in enumerate(pkt):
            n += 1
            w = rnd.uniform(0, 2 * math.pi)
            rr = rnd.gauss(rausch_m, rausch_m * 0.4)
            vx, vy = tx + rr * ppm * math.cos(w), ty + rr * ppm * math.sin(w)
            lage = (vx, vy)
            if fl and tor is not None:
                f = float(fla[i]) if i < len(fla) else 0.0
                seite = (max(f, 1.0) ** 0.5) * ppm
                halb = seite / 2.0
                # Flecken im eigenen Kasten (Kasten sitzt auf der Vision-Lage)
                drin = [p for p in fl
                        if abs(p[0] - vx) <= halb and abs(p[1] - vy) <= halb]
                d1 = d2 = 1e18
                best = None
                for p in fl:
                    dd = ((p[0] - vx) ** 2 + (p[1] - vy) ** 2) ** 0.5
                    if dd < d1:
                        d2, d1, best = d1, dd, p
                    elif dd < d2:
                        d2 = dd
                tol = max(12.0, tol_faktor * seite)
                offen = d1 <= tol
                if offen and tor == "A":
                    offen = len(drin) == 1
                elif offen and tor == "B":
                    offen = d2 > 1e17 or d1 <= 0.5 * d2
                elif offen and tor == "C":
                    offen = len(drin) <= 3
                elif offen and tor == "AB":
                    offen = (len(drin) == 1) and (d2 > 1e17 or d1 <= 0.5 * d2)
                if offen and best:
                    lage = best
                    n_ein += 1
                    if ((best[0] - tx) ** 2 + (best[1] - ty) ** 2) ** 0.5 / ppm < 0.5:
                        n_richtig += 1
            feh.append(((lage[0] - tx) ** 2 + (lage[1] - ty) ** 2) ** 0.5 / ppm)
    return (sum(feh) / len(feh) if feh else None,
            n_ein / n if n else 0.0,
            n_richtig / n_ein if n_ein else 0.0)


def run():
    daten = []
    for k in KURZ:
        for h in HAERTEN:
            g = laden(k, h)
            if not g:
                continue
            arr, pkt, fla, ppm, _typ, _nr = g
            daten.append((arr, pkt, fla, ppm,
                          nachzeichnen.textflecken(arr, zell=2),
                          nachzeichnen.textflecken(arr, zell=4)))
    if not daten:
        print("kein Scan-Korpus")
        return
    n_ges = sum(len(d[1]) for d in daten)
    print(f"TOR-MESSUNG auf {len(daten)} Scans · {n_ges} Stempel")
    print("=" * 104)
    VAR = [("ohne Anker", None, 0.0),
           ("kein Tor · 0,10", "-", 0.10),
           ("TOR A ein Fleck im Kasten", "A", 0.25),
           ("TOR B eindeutig (0,5)", "B", 0.25),
           ("TOR C hoechstens 3", "C", 0.25),
           ("TOR A+B", "AB", 0.25)]
    print(f"{'Variante':30}" + "".join(f"{f'{r}m':>13}" for r in (0.2, 0.4, 0.8, 1.5))
          + f"{'eingerastet':>13}{'davon richtig':>15}")
    print("-" * 104)
    for name, tor, tf in VAR:
        zeile, quote, treffer = [], [], []
        for rm in (0.2, 0.4, 0.8, 1.5):
            fs, qs, ts = [], [], []
            for seed in (1, 7, 23):
                f, q, t = lauf(daten, None if tor is None else
                               (None if tor == "-" else tor), tf, rm, seed)
                if tor == "-":
                    f, q, t = lauf_kein_tor(daten, tf, rm, seed)
                fs.append(f); qs.append(q); ts.append(t)
            zeile.append(sum(fs) / len(fs))
            quote.append(sum(qs) / len(qs))
            treffer.append(sum(ts) / len(ts))
        print(f"{name:30}" + "".join(f"{v:13.2f}" for v in zeile)
              + f"{sum(quote) / len(quote) * 100:12.0f}%"
              + f"{sum(treffer) / len(treffer) * 100:14.0f}%")
    print("-" * 104)
    print("Die erste Zeile ist der Massstab: alles, was darueber liegt, "
          "verschlechtert die Lage.")


def lauf_kein_tor(daten, tf, rm, seed):
    """Einrasten ohne Tor — dieselbe Regel wie in der Produktion."""
    rnd = random.Random(seed)
    feh, n_ein, n_richtig, n = [], 0, 0, 0
    for (arr, pkt, fla, ppm, f2, f4) in daten:
        for i, (tx, ty) in enumerate(pkt):
            n += 1
            w = rnd.uniform(0, 2 * math.pi)
            rr = rnd.gauss(rm, rm * 0.4)
            vx, vy = tx + rr * ppm * math.cos(w), ty + rr * ppm * math.sin(w)
            lage = (vx, vy)
            if f2:
                f = float(fla[i]) if i < len(fla) else 0.0
                seite = (max(f, 1.0) ** 0.5) * ppm
                tol = max(12.0, tf * seite)
                best = min(f2, key=lambda p: (p[0] - vx) ** 2 + (p[1] - vy) ** 2)
                if ((best[0] - vx) ** 2 + (best[1] - vy) ** 2) ** 0.5 <= tol:
                    lage = best
                    n_ein += 1
                    if ((best[0] - tx) ** 2 + (best[1] - ty) ** 2) ** 0.5 / ppm < 0.5:
                        n_richtig += 1
            feh.append(((lage[0] - tx) ** 2 + (lage[1] - ty) ** 2) ** 0.5 / ppm)
    return (sum(feh) / len(feh), n_ein / n if n else 0.0,
            n_richtig / n_ein if n_ein else 0.0)


if __name__ == "__main__":
    run()
