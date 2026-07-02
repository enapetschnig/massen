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


def doppellinie(c, dark, ptm, d_min=0.03, d_max=0.22):
    """Zur Tick-Reihe das flankierende Linien-Paar finden: achsparallele Kanten
    beidseits der Reihe (Abstand je 3-22cm), die ≥60% der Reihen-Länge decken.
    → (front1, front2) Koordinaten der beiden Fronten, sonst None."""
    fronten = []
    for seite in (-1, 1):
        best = None
        for s in dark:
            if c["achse"] == "v":
                if abs(s[0] - s[2]) > 0.5:      # nicht vertikal
                    continue
                pos = (s[0] + s[2]) / 2
                lo, hi = sorted((s[1], s[3]))
            else:
                if abs(s[1] - s[3]) > 0.5:
                    continue
                pos = (s[1] + s[3]) / 2
                lo, hi = sorted((s[0], s[2]))
            d = (pos - c["fix"]) * seite
            if not (d_min * ptm <= d <= d_max * ptm):
                continue
            ueberdeckung = min(hi, c["bis"]) - max(lo, c["von"])
            if ueberdeckung < 0.6 * (c["bis"] - c["von"]):
                continue
            if best is None or d < (best - c["fix"]) * seite:
                best = pos
        fronten.append(best)
    return (fronten[0], fronten[1]) if all(f is not None for f in fronten) else None


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
    hatch = vektor.wand_poche(page, (bx0, bx1, by0, by1))
    st = raumnetz.raum_stempel(page, box)

    cl = tick_cluster(dark, ptm)
    print(f"{len(cl)} Tick-Reihen (Vorwand-Kandidaten) im EG:")

    # Raum-Regionen der aktuellen Pipeline (für Streifen-Überlapp)
    import oeffnungen as oeff_mod
    spans = []
    for block in page.get_text("dict").get("blocks", []):
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                txt = (span.get("text") or "").strip()
                if txt:
                    bb = tuple(span.get("bbox") or (0, 0, 0, 0))
                    spans.append({"text": txt, "bbox": bb,
                                  "cx": (bb[0] + bb[2]) / 2, "cy": (bb[1] + bb[3]) / 2})
    oeff = oeff_mod.extract_oeffnungen_from_text(spans, [])
    dbg = {}
    res, stempel = raumnetz.verifiziere_seite(page, ptm, box, dark, hatch, oeff, debug=dbg)
    grid, label, rst = dbg["grid"], dbg["label"], dbg["rst"]
    namen = {i: s["name"] for i, s in enumerate(stempel)}
    ist = {r["name"]: r for r in res}

    abzug = {}
    for c in cl:
        mx = c["fix"] if c["achse"] == "v" else (c["von"] + c["bis"]) / 2
        my = (c["von"] + c["bis"]) / 2 if c["achse"] == "v" else c["fix"]
        best, bd = None, 1e9
        for s in st:
            dd = math.hypot(s["cx"] - mx, s["cy"] - my) / ptm
            if dd < bd:
                bd, best = dd, s
        dl = doppellinie(c, dark, ptm)
        info = f"  {c['achse']}-Reihe bei {c['fix']:.0f} L={c['laenge_m']}m → {best['name']} ({bd:.2f}m)"
        if not dl:
            print(info + "  [keine Doppellinie]")
            continue
        tiefe = abs(dl[1] - dl[0]) / ptm
        # Streifen-Zellen: welchem Raum-Label gehören sie aktuell?
        lo_f, hi_f = sorted(dl)
        von, bis = c["von"], c["bis"]
        zaehl = {}
        j0, j1 = (rst.ij(lo_f, von), rst.ij(hi_f, bis)) if c["achse"] == "v" else \
                 (rst.ij(von, lo_f), rst.ij(bis, hi_f))
        for gy in range(max(0, min(j0[1], j1[1])), min(rst.H, max(j0[1], j1[1]) + 1)):
            for gx in range(max(0, min(j0[0], j1[0])), min(rst.W, max(j0[0], j1[0]) + 1)):
                l = label[gy * rst.W + gx]
                if l in namen:
                    zaehl[namen[l]] = zaehl.get(namen[l], 0) + 1
        anteile = {k: round(v * rst.zm * rst.zm, 3) for k, v in zaehl.items()}
        print(info + f"  Tiefe {tiefe:.2f}m, im Raum gezählt: {anteile}")
        for k, v in anteile.items():
            abzug[k] = abzug.get(k, 0.0) + v

    print("\nF-PROGNOSE (F_ist − Vorwand-Überlapp ≈ F_soll?):")
    for name, a in sorted(abzug.items()):
        r = ist.get(name)
        if not r:
            continue
        f_ist, f_soll = r.get("f_ist"), r.get("f_m2")
        if not (f_ist and f_soll):
            continue
        neu = f_ist - a
        print(f"  {name:<22} ist {f_ist:6.2f} − Vorwand {a:5.2f} = {neu:6.2f} "
              f"(soll {f_soll:6.2f}, Fehler {100 * (neu - f_soll) / f_soll:+.1f}% "
              f"vorher {100 * (f_ist - f_soll) / f_soll:+.1f}%)")


if __name__ == "__main__":
    run()
