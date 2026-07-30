"""DIE ENTSCHEIDENDE MESSUNG: der Anker auf dem Pfad, auf dem er laeuft.

Bisher wurde der Textfleck-Anker an Vektor-Plaenen gemessen — dort laeuft er
in der Produktion aber nie (extract.py::_vision_raum_regionen steigt aus,
sobald ein Raum ein rekonstruiertes Polygon hat). Jetzt liegen echte Scans
vor (scan_bauen.py: Vektorplan gerastert, verrauscht, JPEG-komprimiert, als
reines Bild-PDF), deren Wahrheit aus dem Original byte-exakt bekannt ist.

Gemessen wird ueber die PRODUKTIONS-KETTE, nicht ueber eine bequemere:
  analysiere_doc -> basis_png (RGB-Pixmap -> PNG)
  -> fitz.Pixmap(csGRAY, fitz.Pixmap(png))      <- genau wie extract.py
  -> nachzeichnen.textflecken(arr)
Der direkte csGRAY-Weg liefert bis zu 38 % weniger Maskenpixel und damit
andere Zahlen — auf groben Plaenen also genau dort, wo es drauf ankommt.

DREI FRAGEN, in dieser Reihenfolge:
  1. DECKE: wie nah kommt der beste Fleck ueberhaupt an den Stempel? Das ist
     eine Eigenschaft der Flecken allein, ohne jede Simulation — und die
     Obergrenze fuer alles, was Einrasten je erreichen kann.
  2. ZELLGROESSE: schlaegt zell=2 die alte 4 auch hier?
  3. LOHNT EINRASTEN? Der Vergleich muss gegen "gar nicht einrasten" gehen,
     nicht nur gegen die alte Einstellung. Gemessen wird der MITTLERE
     LAGEFEHLER je Raum — eine Einrastung, die die Lage verschlechtert, sieht
     in einer Ja/Nein-Zaehlung sonst wie ein Erfolg aus.
"""
import math
import os
import random
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))
import numpy as np      # noqa: E402
import fitz             # noqa: E402
import nachzeichnen     # noqa: E402

SP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_scan_korpus_daten")
os.makedirs(SP, exist_ok=True)
KURZ = ["angerer", "ap01", "au_wm", "velden"]
HAERTEN = ["sauber", "rau"]


def laden(kurz, haerte):
    """-> (graubild wie die Produktion, wahrheit_px, flaechen, ppm) oder None."""
    npz = os.path.join(SP, f"scan_{kurz}_{haerte}.npz")
    pdf = os.path.join(SP, f"scan_{kurz}_{haerte}.pdf")
    if not (os.path.exists(npz) and os.path.exists(pdf)):
        return None
    d = np.load(npz, allow_pickle=True)
    doc = fitz.open(pdf)
    r = nachzeichnen.analysiere_doc(doc, max_px=1800)
    doc.close()
    png = r.get("basis_png")
    if not png:
        return None
    # EXAKT die Kette aus api/extract.py — RGB -> PNG -> csGRAY
    pm = fitz.Pixmap(fitz.csGRAY, fitz.Pixmap(png))
    arr = np.frombuffer(pm.samples, dtype=np.uint8).reshape(pm.height, pm.width)
    # Wahrheit umrechnen: npz-Punkte liegen im Render von scan_bauen (sc_mein),
    # das Produktionsbild in seiner eigenen Skala.
    sc_mein = float(d["sc"])
    doc2 = fitz.open(pdf)
    _pw = doc2[0].rect.width
    doc2.close()
    sc_prod = pm.width / _pw
    k = sc_prod / sc_mein
    pkt = np.array(d["pkt"], dtype=np.float64) * k
    return (arr, pkt, np.array(d["flaeche"]), float(d["ppm"]) * k,
            r.get("typ"), len(r.get("raeume") or []))


def decke(fl, pkt, ppm):
    """Bester erreichbarer Fehler: naechster Fleck je Stempel."""
    if not fl:
        return None, None, 0
    ds = sorted(min(((f[0] - x) ** 2 + (f[1] - y) ** 2) ** 0.5 for f in fl) / ppm
                for x, y in pkt)
    return (sum(ds) / len(ds), ds[len(ds) // 2],
            sum(1 for v in ds if v < 0.5))


def lagefehler(fl, pkt, flaechen, ppm, tol_faktor, rausch_m, seed,
               einrasten=True):
    """Mittlerer Lagefehler je Raum nach der Pipeline-Regel."""
    rnd = random.Random(seed)
    fehler = []
    for i, (tx, ty) in enumerate(pkt):
        w = rnd.uniform(0, 2 * math.pi)
        rr = rnd.gauss(rausch_m, rausch_m * 0.4)
        vx, vy = tx + rr * ppm * math.cos(w), ty + rr * ppm * math.sin(w)
        lage = (vx, vy)
        if einrasten and fl:
            f = float(flaechen[i]) if i < len(flaechen) else 0.0
            seite = (max(f, 1.0) ** 0.5) * ppm
            tol = max(12.0, tol_faktor * seite)
            best = min(fl, key=lambda p: (p[0] - vx) ** 2 + (p[1] - vy) ** 2)
            if ((best[0] - vx) ** 2 + (best[1] - vy) ** 2) ** 0.5 <= tol:
                lage = best
        fehler.append(((lage[0] - tx) ** 2 + (lage[1] - ty) ** 2) ** 0.5 / ppm)
    return sum(fehler) / len(fehler) if fehler else None


def _korpus_sicherstellen():
    """Fehlt der Scan-Korpus, wird er gebaut. Damit ist die Messung mit
    einem einzigen Aufruf reproduzierbar und haengt an keiner Handarbeit."""
    if any(f.startswith("scan_") and f.endswith(".npz") for f in os.listdir(SP)):
        return
    print("Scan-Korpus fehlt — wird gebaut (dauert einige Minuten) ...")
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import _scan_korpus
    for k, m in _scan_korpus.PLAENE:
        try:
            _scan_korpus.bauen(k, m)
        except Exception as e:
            print(f"  {k}: {type(e).__name__}: {e}")


def run():
    _korpus_sicherstellen()
    print("SCAN-ANKER — gemessen auf echten Scans über die Produktionskette")
    print("=" * 100)
    daten = {}
    print(f"{'Scan':22}{'Typ':>7}{'Bild':>13}{'px/m':>7}{'Stempel':>9}"
          f"{'Flecken z2':>12}{'z4':>7}")
    print("-" * 100)
    for k in KURZ:
        for h in HAERTEN:
            g = laden(k, h)
            if not g:
                print(f"{k + '/' + h:22}  (fehlt)")
                continue
            arr, pkt, fla, ppm, typ, nr = g
            f2 = nachzeichnen.textflecken(arr, zell=2)
            f4 = nachzeichnen.textflecken(arr, zell=4)
            daten[(k, h)] = (arr, pkt, fla, ppm, f2, f4)
            print(f"{k + '/' + h:22}{str(typ):>7}{arr.shape[1]}x{arr.shape[0]:>6}"
                  f"{ppm:7.0f}{len(pkt):>9}{len(f2):>12}{len(f4):>7}")
    if not daten:
        print("\nKein Scan-Korpus — scan_bauen.py zuerst laufen lassen.")
        return

    # ── 1) DECKE ───────────────────────────────────────────────────────────
    print(f"\n1) DECKE — bester erreichbarer Fehler (naechster Fleck am Stempel)")
    print(f"{'Scan':22}{'zell=4 Mittel/Median':>26}{'zell=2 Mittel/Median':>26}"
          f"{'<0,5m (z2)':>12}")
    print("-" * 100)
    ges2, ges4, n_ges, nah2 = [], [], 0, 0
    for (k, h), (arr, pkt, fla, ppm, f2, f4) in daten.items():
        m4, md4, _ = decke(f4, pkt, ppm)
        m2, md2, n2 = decke(f2, pkt, ppm)
        ges2 += [m2] * len(pkt)
        ges4 += [m4] * len(pkt)
        n_ges += len(pkt)
        nah2 += n2
        print(f"{k + '/' + h:22}{m4:14.2f} /{md4:8.2f} m{m2:14.2f} /{md2:8.2f} m"
              f"{n2:>7}/{len(pkt):<4}")
    print("-" * 100)
    d2 = sum(ges2) / len(ges2)
    d4 = sum(ges4) / len(ges4)
    print(f"KORPUS: Decke zell=4 {d4:.2f} m · zell=2 {d2:.2f} m · "
          f"{nah2}/{n_ges} Stempel unter 0,5 m (zell=2)")
    print(f"-> Jede Vision-Lage, die besser als {d2:.2f} m ist, wird durch "
          f"Einrasten SCHLECHTER. Das ist die harte Grenze.")

    # ── 2+3) LOHNT EINRASTEN, und mit welcher Einstellung? ─────────────────
    print(f"\n2+3) MITTLERER LAGEFEHLER je Raum — gegen 'gar nicht einrasten'")
    print(f"{'Vision-Versatz':>15}{'ohne Anker':>12}{'z4·0,25 (alt)':>15}"
          f"{'z2·0,25':>10}{'z2·0,10 (neu)':>15}{'  bester':>18}")
    print("-" * 100)
    VAR = [("ohne", None, False), ("z4_025", 0.25, "f4"),
           ("z2_025", 0.25, "f2"), ("z2_010", 0.10, "f2")]
    urteile = []
    for rm in (0.2, 0.4, 0.8, 1.5, 3.0):
        erg = {}
        for nm, tf, welche in VAR:
            summe, n = 0.0, 0
            for (k, h), (arr, pkt, fla, ppm, f2, f4) in daten.items():
                fl = f2 if welche == "f2" else (f4 if welche == "f4" else [])
                for seed in (1, 7, 23):
                    v = lagefehler(fl, pkt, fla, ppm, tf or 0.0, rm, seed,
                                   einrasten=bool(welche))
                    if v is not None:
                        summe += v * len(pkt)
                        n += len(pkt)
            erg[nm] = summe / n if n else None
        best = min((v, k) for k, v in erg.items() if v is not None)
        urteile.append((rm, erg, best[1]))
        print(f"{rm:14.1f}m{erg['ohne']:12.2f}{erg['z4_025']:15.2f}"
              f"{erg['z2_025']:10.2f}{erg['z2_010']:15.2f}{best[1]:>18}")
    print("-" * 100)
    gewinnt = [rm for rm, e, b in urteile if b != "ohne"]
    if gewinnt:
        print(f"Einrasten lohnt ab einem Vision-Versatz von rund "
              f"{min(gewinnt):.1f} m — darunter schadet es.")
    else:
        print("Einrasten lohnt bei KEINEM getesteten Vision-Versatz. "
              "Der Anker gehoert dann ausgeschaltet.")
    besser_neu = sum(1 for rm, e, b in urteile if e["z2_010"] < e["z4_025"])
    print(f"Die heutige Einstellung (z2·0,10) schlaegt die alte (z4·0,25) in "
          f"{besser_neu} von {len(urteile)} Versatz-Stufen.")


if __name__ == "__main__":
    run()
