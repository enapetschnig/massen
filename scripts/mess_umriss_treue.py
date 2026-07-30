"""MESSUNG: wie viele Räume sind wirklich am Plan eingezeichnet — und stimmt es?

Die Zusage lautet "alles beim Plan eingezeichnet, sodass alles nachvollziehbar
ist". Ein Umriss an der falschen Stelle ist dabei SCHLIMMER als gar keiner:
er behauptet etwas. Darum reicht die Flächen-Treue allein nicht — sie ist bei
den Ersatz-Rechtecken sogar per Konstruktion perfekt, egal wo sie liegen.

Vier Kennzahlen, alle ohne fremde Wahrheit prüfbar:

  ABDECKUNG   Anteil der Räume mit Umriss (echt oder Ersatz).
  TREUE       |Polygonfläche − Stempelfläche| / Stempelfläche.
              Der Stempel ist byte-exakt aus dem Text-Layer = Wahrheit.
              Nur bei ECHTEN Umrissen aussagekräftig.
  LAGE        Liegt der eigene Raumstempel im eigenen Umriss? Ein Umriss,
              der seinen eigenen Stempel nicht enthält, ist definitiv falsch
              platziert — dafür braucht es keinen Referenzplan.
  ÜBERLAPPUNG Zwei Räume dürfen nicht dieselben Pixel beanspruchen. Jede
              Überlappung ist ein Hinweis, dass einer falsch liegt — oder
              dass zwei Stempel dieselbe Fläche doppelt zählen.
              Gemessen wird die SUMME, nicht die Anzahl: der Umbau der
              Ersatz-Platzierung ließ die Anzahl bei 25/113 stehen und senkte
              die Summe von 599 auf 536 Raum-% (-11%). An der Anzahl allein
              wäre er als wirkungslos verworfen worden.
"""
import glob
import math
import os
import statistics
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))
import numpy as np     # noqa: E402
import fitz            # noqa: E402
import nachzeichnen    # noqa: E402

PLAENE = [
    "A-5_Einreichplan_Alfred-Angerer",
    "AP.01 Layout-1",
    "AU_WM_01 Erdgeschoss",
    "WA_Velden_Franzosen Allee_Ausführung_TG",
]
RASTER = 700          # Kantenlänge des Prüfrasters für die Überlappung


def _poly_f(ps):
    a = 0.0
    for i in range(len(ps)):
        a += ps[i - 1][0] * ps[i][1] - ps[i][0] * ps[i - 1][1]
    return abs(a) / 2.0


def _drin(pt, poly):
    """Punkt-in-Polygon (Strahlverfahren)."""
    x, y = pt[0], pt[1]
    d = False
    for i in range(len(poly)):
        x1, y1 = poly[i - 1][0], poly[i - 1][1]
        x2, y2 = poly[i][0], poly[i][1]
        if (y1 > y) != (y2 > y) and y2 != y1:
            if x < x1 + (y - y1) * (x2 - x1) / (y2 - y1):
                d = not d
    return d


def _maske(poly, x0, y0, sk):
    """Polygon auf ein Bool-Raster stempeln (Even-Odd, zeilenweise)."""
    m = np.zeros((RASTER, RASTER), dtype=bool)
    ps = [((p[0] - x0) * sk, (p[1] - y0) * sk) for p in poly]
    ys = [p[1] for p in ps]
    r0 = max(0, int(min(ys)))
    r1 = min(RASTER - 1, int(max(ys)) + 1)
    for row in range(r0, r1 + 1):
        yc = row + 0.5
        xs = []
        for i in range(len(ps)):
            x1, y1 = ps[i - 1]
            x2, y2 = ps[i]
            if (y1 > yc) != (y2 > yc) and y2 != y1:
                xs.append(x1 + (yc - y1) * (x2 - x1) / (y2 - y1))
        xs.sort()
        for k in range(0, len(xs) - 1, 2):
            a = max(0, int(math.ceil(xs[k] - 0.5)))
            b = min(RASTER - 1, int(math.floor(xs[k + 1] - 0.5)))
            if b >= a:
                m[row, a:b + 1] = True
    return m


def _plan(muster):
    g = sorted(glob.glob(os.path.expanduser(f"~/Downloads/*{muster}*.pdf")))
    if not g:
        return None
    doc = fitz.open(g[0])
    try:
        r = nachzeichnen.analysiere_doc(doc, max_px=1400)
    finally:
        doc.close()
    return (os.path.basename(g[0]), r) if r.get("ok") else None


def _ueberlappung(rr):
    """-> (Anteil überlappter Fläche je Raum, schlimmste Paare)."""
    ps = [x for x in rr if x.get("region_px")]
    if len(ps) < 2:
        return [], []
    xs = [p[0] for x in ps for p in x["region_px"]]
    ys = [p[1] for x in ps for p in x["region_px"]]
    x0, y0 = min(xs), min(ys)
    sk = (RASTER - 2) / max(1e-6, max(max(xs) - x0, max(ys) - y0))
    mk = [_maske(x["region_px"], x0, y0, sk) for x in ps]
    fl = [int(m.sum()) for m in mk]
    anteil, paare = [], []
    for i in range(len(ps)):
        if fl[i] <= 0:
            continue
        ue = np.zeros_like(mk[i])
        for j in range(len(ps)):
            if i == j:
                continue
            # Vorfilter über die Hüllrechtecke spart die teuren AND-Passes
            if not (mk[i] & mk[j]).any():
                continue
            s = mk[i] & mk[j]
            ue |= s
            if i < j:
                q = int(s.sum()) / max(1, min(fl[i], fl[j]))
                if q > 0.10:
                    paare.append((q, ps[i].get("name"), ps[j].get("name")))
        anteil.append(int(ue.sum()) / fl[i])
    return anteil, sorted(paare, reverse=True)


def run():
    print("UMRISS-TREUE — was ist eingezeichnet, liegt es richtig, stimmt die Fläche?")
    print("=" * 104)
    print(f"{'Plan':<34}{'Räume':>6}{'echt':>6}{'Ersatz':>7}{'ohne':>6}"
          f"{'Md|Δ|echt':>11}{'Stempel drin':>14}{'überlappt':>11}")
    print("-" * 104)

    ges = {"r": 0, "echt": 0, "ers": 0, "ohne": 0, "drin": 0, "raus": []}
    abw_echt, abw_ers, ue_alle, paare_alle, quellen = [], [], [], [], {}
    for m in PLAENE:
        p = _plan(m)
        if not p:
            print(f"{m[:32]:<34}  (Datei fehlt)")
            continue
        name, r = p
        rr = [x for x in (r.get("raeume") or []) if x.get("f_m2")]
        mit = [x for x in rr if x.get("region_px")]
        # Maßstab aus den ECHTEN Umrissen (Ersatzrechtecke würden ihn verzerren)
        sk = [math.sqrt(_poly_f(x["region_px"]) / x["f_m2"])
              for x in mit if not x.get("region_geschaetzt")]
        px_pro_m = statistics.median(sk) if sk else (
            statistics.median([math.sqrt(_poly_f(x["region_px"]) / x["f_m2"])
                               for x in mit]) if mit else None)
        n_echt = n_ers = n_drin = 0
        ab_e, ab_r = [], []
        for x in mit:
            q = x.get("region_quelle") or "echt (Wasserscheide)"
            quellen[q] = quellen.get(q, 0) + 1
            d = (abs(_poly_f(x["region_px"]) / (px_pro_m ** 2) - x["f_m2"])
                 / x["f_m2"]) if px_pro_m else None
            if x.get("region_geschaetzt"):
                n_ers += 1
                ab_r.append(d)
            else:
                n_echt += 1
                ab_e.append(d)
            if x.get("px") and _drin(x["px"], x["region_px"]):
                n_drin += 1
            else:
                ges["raus"].append((name[:22], x.get("name"), q))
        ue, paare = _ueberlappung(mit)
        ue_alle += ue
        paare_alle += [(q, name[:20], a, b) for q, a, b in paare]
        abw_echt += [d for d in ab_e if d is not None]
        abw_ers += [d for d in ab_r if d is not None]
        ges["r"] += len(rr); ges["echt"] += n_echt
        ges["ers"] += n_ers; ges["ohne"] += len(rr) - len(mit)
        ges["drin"] += n_drin
        print(f"{name[:32]:<34}{len(rr):>6}{n_echt:>6}{n_ers:>7}"
              f"{len(rr)-len(mit):>6}"
              f"{(statistics.median(ab_e)*100 if ab_e else 0):>10.1f}%"
              f"{n_drin:>8}/{len(mit):<5}"
              f"{(sum(1 for q in ue if q > 0.05)):>7} Rm")

    print("-" * 104)
    n = ges["r"]
    if not n:
        print("KEIN Plan gemessen — Messung wertlos")
        return
    print(f"KORPUS {n} Räume mit byte-exaktem Stempel")
    print(f"  ABDECKUNG   {ges['echt']+ges['ers']}/{n} "
          f"({(ges['echt']+ges['ers'])/n*100:.0f}%) — davon {ges['echt']} echt "
          f"aus dem Bild, {ges['ers']} als Ersatz-Rechteck")
    if abw_echt:
        print(f"  TREUE echt  Median |Δ| {statistics.median(abw_echt)*100:.1f}%  ·  "
              f"≤3%: {sum(1 for d in abw_echt if d<=0.03)}/{len(abw_echt)}  ·  "
              f"≤10%: {sum(1 for d in abw_echt if d<=0.10)}/{len(abw_echt)}  ·  "
              f">20%: {sum(1 for d in abw_echt if d>0.20)}")
    if abw_ers:
        print(f"  TREUE Ersatz Median |Δ| {statistics.median(abw_ers)*100:.1f}% "
              f"(n={len(abw_ers)}) — per Konstruktion gut, sagt nichts über die Lage")
    print(f"  LAGE        {ges['drin']}/{ges['echt']+ges['ers']} Umrisse "
          f"enthalten ihren eigenen Raumstempel")
    if ue_alle:
        # Die ANZAHL allein führt in die Irre: ein Verfahren kann viele winzige
        # Überlappungen erzeugen und trotzdem besser sein als eines mit wenigen
        # groben. Die Summe ist die Kennzahl, an der ein Eingriff sich messen
        # lassen muss.
        print(f"  ÜBERLAPPUNG {sum(1 for q in ue_alle if q > 0.05)}/{len(ue_alle)} "
              f"Räume teilen >5% ihrer Fläche mit einem anderen Raum  ·  "
              f"Median {statistics.median(ue_alle)*100:.1f}%  ·  "
              f"SUMME {sum(ue_alle)*100:.0f} Raum-%")

    print("\nWoher die Umrisse kommen:")
    for q, c in sorted(quellen.items(), key=lambda kv: -kv[1]):
        print(f"   {c:>4}x  {q}")
    if ges["raus"]:
        print(f"\nUmriss enthält den eigenen Stempel NICHT ({len(ges['raus'])}) "
              f"— definitiv falsch platziert:")
        for pl, rn, q in ges["raus"][:12]:
            print(f"   {pl:<24}{str(rn)[:26]:<28}{q[:38]}")
    if paare_alle:
        print(f"\nRäume, die sich überlappen ({len(paare_alle)} Paare >10%) — "
              f"mindestens einer der beiden ist falsch:")
        for q, pl, a, b in sorted(paare_alle, reverse=True)[:12]:
            print(f"   {pl:<22}{q*100:>5.0f}%  {str(a)[:24]:<26} ∩ {str(b)[:24]}")


if __name__ == "__main__":
    run()
