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


def textflecken(arr, zell=4):
    """Dieselbe Logik wie in der Pipeline (extract.py, Scan-Pfad)."""
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
            if not (3 <= bw <= 60) or bh > 12 or bh > bw:
                continue
            out.append(((min(xs) + max(xs) + 1) / 2 * zell,
                        (min(ys) + max(ys) + 1) / 2 * zell))
    return out


def run():
    g = sorted(glob.glob(os.path.expanduser(
        "~/Downloads/*A-5_Einreichplan_Alfred-Angerer*.pdf")))
    if not g:
        print("OK — übersprungen (Referenzplan nicht vorhanden)")
        return
    doc = fitz.open(g[0])
    r = nachzeichnen.analysiere_doc(doc, max_px=1800)
    assert r.get("ok"), r.get("grund")
    meta = r["meta"]; sc = meta["scale"]; ptm = meta["ptm"]
    # WAHRHEIT: Stempelpositionen aus dem Text-Layer (byte-exakt)
    wahr = {x["name"]: tuple(x["px"]) for x in r["raeume"]
            if x.get("px") and x.get("name")}
    assert len(wahr) >= 5, f"zu wenige Referenz-Stempel ({len(wahr)})"

    page = doc[meta.get("seite") or 0]
    pix = page.get_pixmap(matrix=fitz.Matrix(sc, sc),
                          clip=fitz.Rect(*meta["box_pt"]), colorspace=fitz.csGRAY)
    arr = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width)

    fl = textflecken(arr)
    assert fl, "keine Textflecken erkannt — Erkennung kaputt"

    # 1) DETERMINISMUS: zweiter Lauf auf demselben Bild muss identisch sein
    fl2 = textflecken(arr)
    assert fl == fl2, "Fleck-Erkennung nicht deterministisch"

    # 2) GENAUIGKEIT: zu jedem echten Stempel gibt es einen Fleck ganz nah
    d = sorted(min(((f[0] - t[0]) ** 2 + (f[1] - t[1]) ** 2) ** 0.5
                   for f in fl) / sc / ptm for t in wahr.values())
    median = d[len(d) // 2]
    nah = sum(1 for x in d if x < 0.5)
    assert median <= 0.30, f"Anker-Median {median:.2f} m — zu ungenau (Ziel ≤0,30)"
    assert nah >= 0.7 * len(d), \
        f"nur {nah}/{len(d)} Stempel mit Fleck unter 0,5 m"

    print(f"OK — Textfleck-Anker: {len(fl)} Flecken · Median {median:.2f} m "
          f"zum byte-exakten Stempel · {nah}/{len(d)} unter 0,5 m · "
          f"deterministisch (zwei Läufe identisch)")
    doc.close()


if __name__ == "__main__":
    run()
