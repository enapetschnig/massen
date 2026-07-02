"""VORWAND-DETEKTOR (LOG-only) — Rohbau-vs-Fertig-Hypothese messen.

BEFUND der Bogen-Sezierung (Juli 2026): Raum-Stempel messen den FERTIGEN Raum,
unsere Wand-Maske den ROHBAU. Differenzen dort, wo Installations-VORWÄNDE stehen:
WC +0,15m² (Spülkasten), Waschen +0,55 (WM/DR-Gerätewand), Bad +0,78, Geräte +0,97.

VORWAND-SIGNATUR im Linework (am WC empirisch): Spalte/Zeile kurzer Diagonal-TICKS
(L≈0,15-0,25m) in regelmäßigem Abstand, eingefasst von einer DOPPELLINIE parallel
zur Wand (Abstand 10-25cm = Vorwand-Tiefe).

Dieses Skript misst NUR:
  1. Tick-Cluster finden (kollineare Reihen kurzer Diagonalen).
  2. Pro Cluster: Länge, Tiefe, Lage — und welchem Raum-Stempel er am nächsten ist.
  3. Prognose: F_stempel ≈ F_rohbau − Σ(Vorwand-Streifen) — stimmen die Differenzen?
"""
import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))
import fitz            # noqa: E402
import vektor          # noqa: E402
import nachzeichnen    # noqa: E402
import raumnetz        # noqa: E402

PLAN = os.path.expanduser("~/Downloads/A-5_Einreichplan_Alfred-Angerer_36_25_Index 0 (1).pdf")


def tick_cluster(dark, ptm, l_min=0.10, l_max=0.30, abstand_max=0.25):
    """Reihen kurzer Diagonal-Ticks: kollinear (gleiche x- oder y-Mitte ±4cm),
    Nachbar-Abstand ≤ abstand_max, ≥3 Ticks."""
    ticks = []
    for s in dark:
        dx, dy = abs(s[2] - s[0]), abs(s[3] - s[1])
        L = math.hypot(dx, dy) / ptm
        if l_min <= L <= l_max and dx > 0.5 and dy > 0.5:   # echt diagonal
            ticks.append(((s[0] + s[2]) / 2, (s[1] + s[3]) / 2))
    cluster = []
    benutzt = [False] * len(ticks)
    for i, (x0, y0) in enumerate(ticks):
        if benutzt[i]:
            continue
        # vertikale Reihe (gleiches x)
        for achse in ("v", "h"):
            reihe = [i]
            for j, (x1, y1) in enumerate(ticks):
                if j == i or benutzt[j]:
                    continue
                if achse == "v" and abs(x1 - x0) < 0.06 * ptm:
                    reihe.append(j)
                elif achse == "h" and abs(y1 - y0) < 0.06 * ptm:
                    reihe.append(j)
            if len(reihe) < 3:
                continue
            # auf Lücken prüfen: sortiert entlang der Achse, max Nachbar-Abstand
            pos = sorted(ticks[j][1 if achse == "v" else 0] for j in reihe)
            gruppe, cur = [], [pos[0]]
            for p in pos[1:]:
                if p - cur[-1] <= abstand_max * ptm:
                    cur.append(p)
                else:
                    gruppe.append(cur)
                    cur = [p]
            gruppe.append(cur)
            beste = max(gruppe, key=len)
            if len(beste) < 3:
                continue
            laenge = (beste[-1] - beste[0]) / ptm
            if laenge < 0.4:
                continue
            # Mitglieder der besten Gruppe markieren
            n_mark = 0
            for j in reihe:
                pj = ticks[j][1 if achse == "v" else 0]
                if beste[0] - 1 <= pj <= beste[-1] + 1:
                    benutzt[j] = True
                    n_mark += 1
            cluster.append({"achse": achse, "fix": x0 if achse == "v" else y0,
                            "von": beste[0], "bis": beste[-1],
                            "laenge_m": round(laenge, 2), "n": n_mark})
            break
    return cluster


def run():
    d = fitz.open(PLAN)
    page = max(d, key=lambda p: p.rect.width * p.rect.height)
    ptm = vektor.kalibriere(page.get_text("words"), "1:100")["ptm_konsens"]
    box = nachzeichnen._eg_box(page, ptm)
    bx0, bx1, by0, by1 = box

    segs, _f, _n = vektor._drawings(page)
    inb = lambda s: bx0 <= (s[0] + s[2]) / 2 <= bx1 and by0 <= (s[1] + s[3]) / 2 <= by1
    dark = [s for s in segs if (s[5] is None or s[5] < 0.45) and inb(s)
            and vektor._laenge(s) / ptm > 0.10]
    st = raumnetz.raum_stempel(page, box)

    cl = tick_cluster(dark, ptm)
    print(f"{len(cl)} Tick-Reihen (Vorwand-Kandidaten) im EG:")
    for c in cl:
        # nächster Raum-Stempel
        mx = c["fix"] if c["achse"] == "v" else (c["von"] + c["bis"]) / 2
        my = (c["von"] + c["bis"]) / 2 if c["achse"] == "v" else c["fix"]
        best, bd = None, 1e9
        for s in st:
            dd = math.hypot(s["cx"] - mx, s["cy"] - my) / ptm
            if dd < bd:
                bd, best = dd, s
        print(f"  {c['achse']}-Reihe bei {c['fix']:.0f}, Länge {c['laenge_m']}m, "
              f"{c['n']} Ticks → nächster Raum: {best['name']} ({bd:.2f}m)")


if __name__ == "__main__":
    run()
