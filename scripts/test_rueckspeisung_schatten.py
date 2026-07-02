"""RÜCKSPEISUNGS-SCHATTEN (LOG-only) — Wand-Längen aus Flucht-zu-Flucht-Spannen.

DOKTRIN: Die Live-Mengen (13/13-Polier-Linie) bleiben unangetastet, bis der
Schatten sie schlägt. Dieses Skript misst NUR:

  Für jede erkannte Wand (nachzeichnen.waende): liegen ihre ENDPUNKTE auf
  bestätigten QUER-Fluchten (±25cm)? Wenn ja: länge_schatten = Abstand der
  beiden Fluchten (byte-exakt aus den Maßketten) vs länge_m (Vektor-Messung
  bzw. mass_exakt-Snap).

Ausgabe: Abdeckung (Wände mit beidseitiger Flucht), Δ-Verteilung, Σ je HLZ-
Klasse Schatten vs Live — die Entscheidungsgrundlage fürs Umschalten.
"""
import glob
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))
import fitz            # noqa: E402
import nachzeichnen    # noqa: E402

DL = os.path.expanduser("~/Downloads")


def schatten(plan_teil):
    g = sorted(glob.glob(os.path.join(DL, f"*{plan_teil}*")))
    if not g:
        print(f"{plan_teil}: FEHLT")
        return
    nz = nachzeichnen.analysiere_doc(fitz.open(g[0]))
    if not nz.get("ok"):
        print(f"{plan_teil}: {nz.get('grund')}")
        return
    meta = nz["meta"]
    scale, ptm = meta["scale"], meta["ptm"]
    fluchten = [f for f in (nz.get("fluchten") or []) if f["ok"]]
    fl_v = sorted(f["px"] for f in fluchten if f["achse"] == "v")   # x=const
    fl_h = sorted(f["px"] for f in fluchten if f["achse"] == "h")   # y=const
    tol_px = 0.25 * ptm * scale

    def naechste(fl, p):
        best = None
        for q in fl:
            if best is None or abs(q - p) < abs(best - p):
                best = q
        return best if best is not None and abs(best - p) <= tol_px else None

    n_beidseitig = 0
    deltas = []
    sum_live, sum_schatten = {}, {}
    for w in (nz.get("waende") or []):
        p = w["px"]
        cm = w.get("snap_cm")
        # Endpunkte entlang der Wand-Achse → Quer-Fluchten
        if w["achse"] == "h":
            a, b = naechste(fl_v, p[0]), naechste(fl_v, p[2])
        else:
            a, b = naechste(fl_h, p[1]), naechste(fl_h, p[3])
        if cm:
            sum_live[cm] = sum_live.get(cm, 0.0) + w["laenge_m"]
        if a is None or b is None or a == b:
            if cm:
                sum_schatten[cm] = sum_schatten.get(cm, 0.0) + w["laenge_m"]
            continue
        n_beidseitig += 1
        l_schatten = abs(b - a) / scale / ptm
        deltas.append((round(l_schatten - w["laenge_m"], 3), w["laenge_m"],
                       round(l_schatten, 2), cm, bool(w.get("mass_exakt"))))
        if cm:
            sum_schatten[cm] = sum_schatten.get(cm, 0.0) + l_schatten
    n = len(nz.get("waende") or [])
    print(f"\n=== {plan_teil} ===")
    print(f"{n_beidseitig}/{n} Wände mit beidseitig bestätigter Quer-Flucht")
    gross = [d for d in deltas if abs(d[0]) > 0.03]
    print(f"Δ>3cm bei {len(gross)}/{len(deltas)}:")
    for dl, lm, ls, cm, ex in sorted(gross, key=lambda t: -abs(t[0]))[:8]:
        print(f"  Δ{dl:+.2f}m  gemessen {lm}m → Flucht {ls}m  (HLZ{cm}"
              f"{', mass_exakt' if ex else ''})")
    print("Σ je Klasse (live → schatten):")
    for cm in sorted(set(sum_live) | set(sum_schatten), reverse=True):
        lv, sc = sum_live.get(cm, 0.0), sum_schatten.get(cm, 0.0)
        print(f"  HLZ{cm}: {lv:7.2f} m → {sc:7.2f} m  (Δ{sc - lv:+.2f})")


if __name__ == "__main__":
    for teil in ["A-5_Einreichplan_Alfred-Angerer", "AU_WM_01 Erdgeschoss"]:
        schatten(teil)
