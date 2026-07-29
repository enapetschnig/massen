"""WÄCHTER Textfleck-Anker: der deterministische Positions-Anker für Scans.

Warum das die Kern-Zusage für Scans ist: Vision weiss WELCHE Räume es gibt
(Name, Fläche byte-exakt), trifft ihre LAGE aber nur grob und schwankt dabei
lauf-zu-lauf. Gemessen wurde am Angerer-Plan gegen die byte-exakten
Stempelpositionen:

  Vision-Bounding-Box        3–7 m       (IoU 0,00, unbrauchbar)
  Vision-Beschriftungspunkt  0,39 m      (schwankt 20–24 px je Lauf)
  TEXTFLECK IM BILD          0,04 m      DETERMINISTISCH

Dieser Guard prüft die Fleck-Erkennung selbst — rein rechnend auf einem
gerenderten Vektorplan, dessen Text-Layer die Wahrheit liefert. Kein
API-Guthaben nötig, damit die Zusage jederzeit nachprüfbar bleibt.
"""
import glob
import os
import sys
from collections import deque

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))
import numpy as np      # noqa: E402
import fitz             # noqa: E402
import nachzeichnen     # noqa: E402


def textflecken(arr, zell=4, px_pro_m=None):
    """Dieselbe Logik wie in der Pipeline (extract.py, Scan-Pfad).

    px_pro_m: Pixel je BAUWERKS-Meter. Damit wird der Groessenfilter
    massstabsunabhaengig — Planschrift ist auf dem Papier etwa 2,5-3,5 mm
    hoch, also je nach Massstab 0,1-0,4 m des Bauwerks. Ohne diese Umrechnung
    passt ein in Pixeln fester Filter nur zu EINEM Plan (am Korpus gemessen:
    Angerer 0,04 m, AU_WM_01 1,72 m — derselbe Filter, anderer Massstab)."""
    h, w = arr.shape
    H, W = h // zell, w // zell
    if H < 3 or W < 3:
        return []
    blk = arr[:H * zell, :W * zell].reshape(H, zell, W, zell)
    ant = (blk < 160).mean(axis=(1, 3))
    mk = (ant > 0.08) & (ant < 0.75)
    m2 = mk.copy()
    for d in (1, 2):
        m2[:, d:] |= mk[:, :-d]
        m2[:, :-d] |= mk[:, d:]
    ges = np.zeros_like(m2, dtype=bool)
    out = []
    for j in range(H):
        for i in range(W):
            if not m2[j, i] or ges[j, i]:
                continue
            q = deque([(j, i)]); ges[j, i] = True
            zl = []
            while q:
                y, x = q.popleft(); zl.append((y, x))
                if len(zl) > 400:
                    break
                for dy, dx in ((0, 1), (0, -1), (1, 0), (-1, 0)):
                    ny, nx = y + dy, x + dx
                    if 0 <= ny < H and 0 <= nx < W and m2[ny, nx] and not ges[ny, nx]:
                        ges[ny, nx] = True; q.append((ny, nx))
            if not (3 <= len(zl) <= 400):
                continue
            ys = [t[0] for t in zl]; xs = [t[1] for t in zl]
            bw = max(xs) - min(xs) + 1
            bh = max(ys) - min(ys) + 1
            if bh > bw:                       # Text liegt waagrecht
                continue
            if px_pro_m:
                _hm = bh * zell / px_pro_m    # Hoehe in Bauwerks-Metern
                _bm = bw * zell / px_pro_m
                if not (0.06 <= _hm <= 0.60) or not (0.10 <= _bm <= 4.0):
                    continue
            elif not (3 <= bw <= 60) or bh > 12:
                continue
            out.append(((min(xs) + max(xs) + 1) / 2 * zell,
                        (min(ys) + max(ys) + 1) / 2 * zell))
    return out


KORPUS = [
    "A-5_Einreichplan_Alfred-Angerer",
    "AP.01 Layout-1",
    "AU_WM_01 Erdgeschoss",
    "WA_Velden_Franzosen Allee_Ausführung_TG",
    "1762788650811_EG-Wand-Grundriss",
]


def _messe(pfad):
    """-> (n_flecken, median_m, anteil_unter_05, n_stempel) oder None."""
    doc = fitz.open(pfad)
    r = nachzeichnen.analysiere_doc(doc, max_px=1800)
    if not r.get("ok"):
        doc.close(); return None
    meta = r["meta"]; sc = meta["scale"]; ptm = meta["ptm"]
    # WAHRHEIT: Stempelpositionen aus dem Text-Layer (byte-exakt)
    wahr = {x["name"]: tuple(x["px"]) for x in r["raeume"]
            if x.get("px") and x.get("name")}
    if len(wahr) < 2:
        doc.close(); return None

    page = doc[meta.get("seite") or 0]
    pix = page.get_pixmap(matrix=fitz.Matrix(sc, sc),
                          clip=fitz.Rect(*meta["box_pt"]), colorspace=fitz.csGRAY)
    arr = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width)

    fl = textflecken(arr, px_pro_m=sc * ptm)
    if not fl:
        doc.close(); return None
    # DETERMINISMUS: zweiter Lauf auf demselben Bild muss identisch sein
    assert fl == textflecken(arr, px_pro_m=sc * ptm), \
        "Fleck-Erkennung nicht deterministisch"
    d = sorted(min(((f[0] - t[0]) ** 2 + (f[1] - t[1]) ** 2) ** 0.5
                   for f in fl) / sc / ptm for t in wahr.values())
    doc.close()
    return (len(fl), d[len(d) // 2],
            sum(1 for x in d if x < 0.5), len(d))


def run():
    print(f"{'Plan':<40}{'Flecken':>8}{'Median':>9}{'<0,5 m':>10}")
    print("-" * 70)
    alle_med, ges_nah, ges_n, geprueft = [], 0, 0, 0
    for teil in KORPUS:
        g = sorted(glob.glob(os.path.expanduser(f"~/Downloads/*{teil}*.pdf")))
        if not g:
            print(f"{teil[:38]:<40}{'(Datei fehlt)':>27}")
            continue
        erg = _messe(g[0])
        if not erg:
            print(f"{os.path.basename(g[0])[:38]:<40}{'(kein Grundriss)':>27}")
            continue
        n_fl, med, nah, n = erg
        geprueft += 1
        alle_med.append(med); ges_nah += nah; ges_n += n
        print(f"{os.path.basename(g[0])[:38]:<40}{n_fl:>8}{med:>8.2f}m{nah:>6}/{n:<4}")
    print("-" * 70)
    if not geprueft:
        print("OK — übersprungen (keine Referenzpläne vorhanden)")
        return
    alle_med.sort()
    gesamt_med = alle_med[len(alle_med) // 2]
    print(f"{geprueft} Pläne · Median über alle {gesamt_med:.2f} m · "
          f"{ges_nah}/{ges_n} Stempel mit Fleck unter 0,5 m")
    # EHRLICHE ZUSAGEN — am Korpus gemessen, nicht am Bestfall.
    #
    # Der Textfleck-Anker traegt NICHT ueberall gleich gut:
    #   Angerer   0,04 m   wenige, klar stehende Raumbeschriftungen
    #   AP.01     0,74 m   Polierplan voller Kanal-/Masstext — der naechste
    #                      Fleck ist dann oft die falsche Schrift
    #   AU_WM_01  1,80 m   grosse Tafel, grob aufgeloest (28 px/m)
    # Die Genauigkeit haengt also an TEXTDICHTE und AUFLOESUNG, nicht nur am
    # Verfahren. Darum wird hier NICHT der Bestfall festgeschrieben, sondern:
    assert geprueft >= 3, f"nur {geprueft} Pläne geprüft — Aussage nicht belastbar"
    # (a) das Verfahren FUNKTIONIERT nachweislich — mindestens ein Plan unter
    #     0,10 m; faellt das weg, ist die Erkennung selbst kaputt
    assert min(alle_med) <= 0.10, \
        f"bester Plan nur {min(alle_med):.2f} m — Fleck-Erkennung defekt"
    # (b) keine Verschlechterung ueber den Korpus (gemessen 2026-07-29: 1,07 m)
    assert gesamt_med <= 1.30, \
        f"Anker-Median {gesamt_med:.2f} m über den Korpus — geregressiert"
    print(f"bester Plan {min(alle_med):.2f} m · deterministisch "
          f"(je Plan zwei identische Läufe) ✓")
    print("HINWEIS: die Anker-Güte haengt an Textdichte und Aufloesung — auf "
          "beschriftungsarmen Plaenen zentimetergenau, auf dichten Polier-"
          "plaenen deutlich schwaecher. In der Pipeline rastet der Anker nur "
          "ein, wenn ein Fleck NAH genug liegt; sonst bleibt der Vision-Anker.")


if __name__ == "__main__":
    run()
