"""RAEUME AUS DEM SCANBILD — der Hebel, der nach dem Anker uebrig bleibt.

Acht Verfahren, die Raumlage ueber die BESCHRIFTUNG zu bestimmen, sind
gemessen und widerlegt (siehe mess_scan_anker.py und
mess_scan_verschiebung.py). Was bleibt, ist der andere Weg: die WAENDE aus
dem Bild lesen und die Raeume als das nehmen, was zwischen ihnen liegt.
Genau das tut die App auf Vektor-Plaenen schon; auf Scans fehlt es.

Warum das jetzt messbar ist: der hergestellte Scan-Korpus (_scan_korpus.py)
kennt nicht nur die Stempelpositionen, sondern auch die WAHREN UMRISSE —
sie stammen aus der Vektor-Rekonstruktion des Originals. Damit laesst sich
eine Bild-Rekonstruktion mit IoU gegen echte Polygone messen statt gegen
eine Vermutung.

DAS BEKANNTE HINDERNIS (Prototyp 2026-07-27, 2 von 11 Raeumen am A0-Scan):
Tueren sind blosse Wandluecken. Eine Flutung laeuft durch sie hindurch und
ueberschwemmt das halbe Blatt. Wandverdickung schliesst die Luecke, laesst
aber kleine Raeume kollabieren. Der Ausweg ist nicht "mehr Verdickung",
sondern ein ANNAHME-KRITERIUM: die byte-exakte Stempelflaeche sagt, wie
gross der Raum sein MUSS. Ein Fuellergebnis wird nur angenommen, wenn seine
Flaeche dazu passt — und die Verdickung wird je Raum so lange erhoeht, bis
das der Fall ist.

Gemessen wird:
  ANGENOMMEN   wie viele Raeume liefern ueberhaupt einen Umriss
  IoU          Ueberdeckung mit dem wahren Umriss (>=0,5 brauchbar,
               >=0,7 gut)
  FLAECHE      Abweichung zur byte-exakten Stempelflaeche
"""
import os
import sys
from collections import deque

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np      # noqa: E402
import nachzeichnen     # noqa: E402
from mess_scan_anker import laden, KURZ, HAERTEN, _korpus_sicherstellen  # noqa: E402

SP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_scan_korpus_daten")


def _wand_maske(arr, schwelle=170):
    """Dunkle Pixel = Wand/Linie. Scans sind nie sauber weiss."""
    return arr < schwelle


def _verdicken(maske, r):
    """Separables MAXIMUM ueber ein (2r+1)-Fenster — schliesst Tuerluecken.

    Zwei O(N)-Durchlaeufe statt O(N*r^2): fuer grosse Bilder der Unterschied
    zwischen Sekunden und Minuten.
    """
    if r <= 0:
        return maske
    m = maske
    for achse in (0, 1):
        n = m.shape[achse]
        aus = m.copy()
        for d in range(1, r + 1):
            if achse == 0:
                aus[d:] |= m[:n - d]
                aus[:n - d] |= m[d:]
            else:
                aus[:, d:] |= m[:, :n - d]
                aus[:, :n - d] |= m[:, d:]
        m = aus
    return m


def _fluten(frei, sx, sy, max_zellen):
    """4er-Flutung ab (sx,sy) im freien Raum. -> Menge der Zellen oder None,
    wenn sie ueber max_zellen hinauslaeuft (Tuerluecke offen geblieben)."""
    h, w = frei.shape
    if not (0 <= sy < h and 0 <= sx < w) or not frei[sy, sx]:
        return None
    gesehen = np.zeros_like(frei, dtype=bool)
    q = deque([(sy, sx)])
    gesehen[sy, sx] = True
    zellen = []
    while q:
        y, x = q.popleft()
        zellen.append((y, x))
        if len(zellen) > max_zellen:
            return None
        for dy, dx in ((0, 1), (0, -1), (1, 0), (-1, 0)):
            ny, nx = y + dy, x + dx
            if 0 <= ny < h and 0 <= nx < w and frei[ny, nx] and not gesehen[ny, nx]:
                gesehen[ny, nx] = True
                q.append((ny, nx))
    return zellen


def _bbox(zellen):
    ys = [z[0] for z in zellen]
    xs = [z[1] for z in zellen]
    return (min(xs), min(ys), max(xs) + 1, max(ys) + 1)


def _iou_maske(zellen, poly, gitter, form):
    """IoU der gefluteten Zellen gegen das wahre Polygon (gerastert)."""
    if poly is None or len(poly) < 3:
        return None
    h, w = form
    # Polygon rastern (even-odd, zeilenweise) — ohne PIL-Abhaengigkeit
    wahr = np.zeros((h, w), dtype=bool)
    p = poly / gitter
    n = len(p)
    ymin = max(0, int(np.floor(p[:, 1].min())))
    ymax = min(h - 1, int(np.ceil(p[:, 1].max())))
    for y in range(ymin, ymax + 1):
        xs = []
        for i in range(n):
            x1, y1 = p[i]
            x2, y2 = p[(i + 1) % n]
            if (y1 <= y < y2) or (y2 <= y < y1):
                xs.append(x1 + (y - y1) * (x2 - x1) / (y2 - y1))
        xs.sort()
        for i in range(0, len(xs) - 1, 2):
            a = max(0, int(np.ceil(xs[i])))
            b = min(w - 1, int(np.floor(xs[i + 1])))
            if b >= a:
                wahr[y, a:b + 1] = True
    ist = np.zeros((h, w), dtype=bool)
    for (y, x) in zellen:
        ist[y, x] = True
    schnitt = int((wahr & ist).sum())
    vereinigung = int((wahr | ist).sum())
    return schnitt / vereinigung if vereinigung else None


def rekonstruieren(arr, pkt, flaechen, ppm, gitter=4, tol=0.30,
                   radien=(1, 2, 3, 4, 5, 6, 8, 10, 12, 15)):
    """Raeume aus dem Bild. -> je Raum (zellen, radius, f_ist) oder None.

    Kern ist das ANNAHME-KRITERIUM: die Flutung wird nur uebernommen, wenn
    ihre Flaeche zur byte-exakten Stempelflaeche passt. Die Wandverdickung
    waechst so lange, bis das eintritt — je Raum einzeln, denn ein grosser
    Raum vertraegt viel Verdickung, ein WC nicht.
    """
    h, w = arr.shape
    H, W = h // gitter, w // gitter
    if H < 8 or W < 8:
        return [None] * len(pkt)
    # auf das Grobgitter bringen: eine Zelle gilt als Wand, wenn sie
    # ueberwiegend dunkel ist (Rauschen faellt so heraus)
    blk = _wand_maske(arr)[:H * gitter, :W * gitter].reshape(
        H, gitter, W, gitter)
    wand0 = blk.mean(axis=(1, 3)) > 0.35
    zelle_m = gitter / ppm                     # Kantenlaenge einer Zelle
    ergebnis = []
    cache = {0: ~wand0}
    for i, (px, py) in enumerate(pkt):
        f_soll = float(flaechen[i]) if i < len(flaechen) else 0.0
        sx, sy = int(px / gitter), int(py / gitter)
        if f_soll <= 0:
            ergebnis.append(None)
            continue
        max_zellen = int(f_soll * 3.0 / (zelle_m ** 2)) + 200
        treffer = None
        bester = None          # (abstand_zur_sollflaeche, zellen, r, f_ist)
        for r in radien:
            if r not in cache:
                cache[r] = ~_verdicken(wand0, r)
            frei = cache[r]
            # Saatpunkt: der Stempel steht MITTEN im Raum, aber auf Schrift.
            # Darum die naechste freie Zelle in einer kleinen Spirale suchen.
            saat = None
            for dr in range(0, 12):
                for dy in range(-dr, dr + 1):
                    for dx in (-dr, dr) if dr else (0,):
                        yy, xx = sy + dy, sx + dx
                        if 0 <= yy < H and 0 <= xx < W and frei[yy, xx]:
                            saat = (xx, yy)
                            break
                    if saat:
                        break
                if saat:
                    break
            if not saat:
                continue
            zellen = _fluten(frei, saat[0], saat[1], max_zellen)
            if not zellen:
                continue
            # RAND ZURUECKGEBEN: die Verdickung ist ein Mittel, um Tueren zu
            # schliessen — sie soll den Raum nicht verkleinern. Also das
            # Flutergebnis um r Zellen zurueckwachsen lassen, begrenzt auf den
            # UNVERDICKTEN freien Raum. Ohne diesen Schritt ist die Flaeche
            # systematisch zu klein (am Korpus 13-26 % zu wenig).
            zellen = _zurueckgeben(zellen, cache[0], r, wand0.shape)
            f_ist = len(zellen) * (zelle_m ** 2)
            ab = abs(f_ist - f_soll) / f_soll
            if bester is None or ab < bester[0]:
                bester = (ab, zellen, r, f_ist)
            if f_ist < (1 - tol) * f_soll:
                break     # ab hier wird es nur noch kleiner
        # NICHT den ersten passenden Radius nehmen, sondern den BESTEN. Die
        # Flaeche faellt mit wachsendem r monoton; der Treffer liegt dazwischen
        # und wird von einer groben Radien-Leiter sonst uebersprungen.
        if bester and bester[0] <= tol:
            treffer = (bester[1], bester[2], bester[3])
        ergebnis.append(treffer)
    return ergebnis


def _zurueckgeben(zellen, frei0, r, form):
    """Region um r Zellen wachsen lassen, begrenzt auf den freien Raum."""
    if r <= 0:
        return zellen
    H, W = form
    m = np.zeros((H, W), dtype=bool)
    for (y, x) in zellen:
        m[y, x] = True
    m = _verdicken(m, r) & frei0
    ys, xs = np.nonzero(m)
    return list(zip(ys.tolist(), xs.tolist()))


def run():
    _korpus_sicherstellen()
    print("RAEUME AUS DEM SCANBILD — gegen die WAHREN Umrisse gemessen")
    print("=" * 104)
    print(f"{'Scan':22}{'Räume':>7}{'angenommen':>12}{'IoU≥0,5':>9}"
          f"{'IoU≥0,7':>9}{'IoU median':>12}{'F-Abw. median':>15}")
    print("-" * 104)
    g_n = g_ang = g_50 = g_70 = 0
    alle_iou, alle_fa = [], []
    for k in KURZ:
        for hh in HAERTEN:
            g = laden(k, hh)
            if not g:
                continue
            arr, pkt, fla, ppm, _t, _n = g
            d = np.load(os.path.join(SP, f"scan_{k}_{hh}.npz"), allow_pickle=True)
            if "poly" not in d:
                print(f"{k + '/' + hh:22}  (Korpus ohne Umriss-Wahrheit — "
                      f"_scan_korpus.py neu laufen lassen)")
                continue
            polys = d["poly"]
            # Wahrheit liegt in den Pixeln von _scan_korpus; das Bild hier ist
            # das Produktionsbild. Verhaeltnis ueber ppm angleichen.
            k_um = ppm / float(d["ppm"])
            gitter = 4
            erg = rekonstruieren(arr, pkt, fla, ppm, gitter=gitter)
            n_ang = n50 = n70 = 0
            ious, fas = [], []
            for i, e in enumerate(erg):
                g_n += 1
                if not e:
                    continue
                n_ang += 1
                g_ang += 1
                zellen, r, f_ist = e
                pw = (np.array(polys[i], dtype=np.float64) * k_um
                      if len(polys[i]) >= 3 else None)
                iou = _iou_maske(zellen, pw, gitter,
                                 (arr.shape[0] // gitter, arr.shape[1] // gitter))
                if iou is not None:
                    ious.append(iou)
                    alle_iou.append(iou)
                    if iou >= 0.5:
                        n50 += 1
                        g_50 += 1
                    if iou >= 0.7:
                        n70 += 1
                        g_70 += 1
                if fla[i]:
                    fa = abs(f_ist - float(fla[i])) / float(fla[i])
                    fas.append(fa)
                    alle_fa.append(fa)
            med_i = float(np.median(ious)) if ious else 0.0
            med_f = float(np.median(fas)) * 100 if fas else 0.0
            print(f"{k + '/' + hh:22}{len(pkt):>7}{n_ang:>12}{n50:>9}{n70:>9}"
                  f"{med_i:12.2f}{med_f:14.0f}%")
    print("-" * 104)
    if g_n:
        print(f"KORPUS: {g_ang}/{g_n} Räume rekonstruiert "
              f"({g_ang / g_n * 100:.0f}%) · IoU≥0,5 bei {g_50} · "
              f"IoU≥0,7 bei {g_70} · IoU-Median "
              f"{float(np.median(alle_iou)) if alle_iou else 0:.2f}")
        print(f"Zum Vergleich: der Prototyp von 2026-07-27 kam am A0-Scan auf "
              f"2 von 11 Räumen.")


if __name__ == "__main__":
    run()
