"""Einen ECHTEN Scan-Korpus herstellen — mit byte-exakt bekannter Wahrheit.

Das Problem: der Textfleck-Anker laeuft in der Produktion NUR auf Plaenen
ohne Vektor-Geometrie (extract.py::_vision_raum_regionen steigt aus, sobald
ein Raum ein rekonstruiertes Polygon hat). Alle vier Referenzplaene sind
Vektor-Plaene — dort laeuft er nie. Gemessen wurde also bisher ein toter
Pfad, und lokal liegt kein echter Plan-Scan.

Die Loesung: einen Scan HERSTELLEN. Ein Vektorplan wird bei typischer
Scanner-Aufloesung gerastert, realistisch verschlechtert (Rauschen,
JPEG-Artefakte, leichte Verdrehung) und als reines BILD-PDF neu geschrieben —
ohne Textebene, ohne Vektoren. Genau das, was ein Buerokopierer liefert.

Der entscheidende Vorteil gegenueber einem fremden Scan: die WAHRHEIT ist
bekannt. Die Stempelpositionen stammen aus dem Text-Layer des Originals und
werden mit derselben Transformation in das Scan-Bild abgebildet. Damit ist
zum ersten Mal messbar, was der Anker auf dem Pfad leistet, auf dem er
wirklich laeuft.

Erzeugt je Plan zwei Haerten:
  sauber   150 dpi, wenig Rauschen, keine Verdrehung  (Bueroscan, Bestfall)
  rau      120 dpi, mehr Rauschen, 0,4 Grad verdreht, JPEG 60  (Realfall)
"""
import glob
import io
import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))
import numpy as np      # noqa: E402
import fitz             # noqa: E402
from PIL import Image   # noqa: E402
import nachzeichnen     # noqa: E402

SP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_scan_korpus_daten")
os.makedirs(SP, exist_ok=True)
PLAENE = [
    ("angerer", "*A-5_Einreichplan_Alfred-Angerer*"),
    ("ap01", "*AP.01 Layout-1*"),
    ("au_wm", "*AU_WM_01 Erdgeschoss*"),
    ("velden", "*WA_Velden_Franzosen Allee_Ausführung_TG*"),
]
HAERTEN = [
    # name,    dpi,  rausch, winkel_grad, jpeg_q
    ("sauber", 150, 3.0, 0.0, 92),
    ("rau", 120, 9.0, 0.4, 60),
]


def _drehen(arr, grad, fuell=255):
    """Bild drehen — und dieselbe Drehung auf die Wahrheit anwendbar machen."""
    if abs(grad) < 1e-6:
        return arr, (1.0, 0.0, 0.0, 0.0, 1.0, 0.0)
    im = Image.fromarray(arr)
    h0, w0 = arr.shape
    im2 = im.rotate(grad, resample=Image.BICUBIC, expand=True, fillcolor=fuell)
    w1, h1 = im2.size
    # PIL dreht um den Bildmittelpunkt, gegen den Uhrzeigersinn, und
    # verschiebt danach so, dass alles ins neue Bild passt.
    th = math.radians(grad)
    cos, sin = math.cos(th), math.sin(th)
    cx0, cy0 = w0 / 2.0, h0 / 2.0
    cx1, cy1 = w1 / 2.0, h1 / 2.0
    # (x,y) -> (cos*(x-cx0) + sin*(y-cy0) + cx1, -sin*(x-cx0) + cos*(y-cy0) + cy1)
    return np.array(im2), (cos, sin, cx1 - cos * cx0 - sin * cy0,
                           -sin, cos, cy1 + sin * cx0 - cos * cy0)


def bauen(kurz, muster):
    g = sorted(glob.glob(os.path.expanduser("~/Downloads/" + muster)))
    if not g:
        print(f"{kurz:10} Datei fehlt")
        return
    doc = fitz.open(g[0])
    r = nachzeichnen.analysiere_doc(doc, max_px=1800)
    if not r.get("ok"):
        print(f"{kurz:10} analysiere_doc nicht ok")
        doc.close()
        return
    meta = r["meta"]
    box, ptm, sc0 = meta["box_pt"], meta["ptm"], meta["scale"]
    # WAHRHEIT: "px" gibt es auf jedem Stempel ("cx" nur auf manchen).
    # px ist relativ zur Clip-Box gerechnet -> zurueck in Seiten-pt.
    wahr_pt = [(x["px"][0] / sc0 + box[0], x["px"][1] / sc0 + box[1])
               for x in r["raeume"] if x.get("px")]
    flaechen = [float(x.get("f_m2") or 0.0) for x in r["raeume"] if x.get("px")]
    if len(wahr_pt) < 2:
        print(f"{kurz:10} zu wenige Stempel")
        doc.close()
        return
    page = doc[meta.get("seite") or 0]

    for hname, dpi, rausch, winkel, jq in HAERTEN:
        sc = dpi / 72.0
        pix = page.get_pixmap(matrix=fitz.Matrix(sc, sc),
                              clip=fitz.Rect(*box), colorspace=fitz.csGRAY)
        arr = np.frombuffer(pix.samples, dtype=np.uint8).reshape(
            pix.height, pix.width).copy()
        # Wahrheit in Bildpixel dieses Renders
        pkt = np.array([[(x - box[0]) * sc, (y - box[1]) * sc]
                        for (x, y) in wahr_pt], dtype=np.float64)
        # 1) Verdrehen (Vorlage liegt nie exakt gerade auf dem Glas)
        arr, M = _drehen(arr, winkel)
        a, b, c, d, e, f = M
        pkt = np.stack([a * pkt[:, 0] + b * pkt[:, 1] + c,
                        d * pkt[:, 0] + e * pkt[:, 1] + f], axis=1)
        # 2) Sensorrauschen
        if rausch > 0:
            rng = np.random.default_rng(hash(kurz) % 2**32)
            arr = np.clip(arr.astype(np.int16)
                          + rng.normal(0, rausch, arr.shape).astype(np.int16),
                          0, 255).astype(np.uint8)
        # 3) JPEG-Artefakte (jeder Bueroscanner komprimiert)
        buf = io.BytesIO()
        Image.fromarray(arr).save(buf, format="JPEG", quality=jq)
        buf.seek(0)
        arr = np.array(Image.open(buf).convert("L"))

        # 4) als reines BILD-PDF schreiben — keine Textebene, keine Vektoren
        png = io.BytesIO()
        Image.fromarray(arr).save(png, format="PNG")
        neu = fitz.open()
        # Seitengroesse wie das Original-Blatt, damit der Massstab passt
        pw, ph = arr.shape[1] / sc, arr.shape[0] / sc
        seite = neu.new_page(width=pw, height=ph)
        seite.insert_image(fitz.Rect(0, 0, pw, ph), stream=png.getvalue())
        ziel = os.path.join(SP, f"scan_{kurz}_{hname}.pdf")
        neu.save(ziel, deflate=True)
        neu.close()

        np.savez_compressed(
            os.path.join(SP, f"scan_{kurz}_{hname}.npz"),
            pkt=pkt, flaeche=np.array(flaechen), ppm=sc * ptm,
            sc=sc, ptm=ptm, pdf=ziel)
        print(f"{kurz:10} {hname:7} {arr.shape[1]}x{arr.shape[0]}px · "
              f"{sc * ptm:.0f} px/m · {len(pkt)} Stempel · "
              f"{os.path.getsize(ziel) / 1e6:.1f} MB")
    doc.close()


def pruefen():
    """Sind die erzeugten PDFs wirklich Scans — und laeuft der Anker-Pfad?"""
    print(f"\n{'Scan':26}{'Spans':>7}{'Bilder':>8}{'Räume':>7}{'mit Polygon':>13}"
          f"   Anker-Pfad")
    print("-" * 74)
    for kurz, _ in PLAENE:
        for hname, *_ in HAERTEN:
            p = os.path.join(SP, f"scan_{kurz}_{hname}.pdf")
            if not os.path.exists(p):
                continue
            d = fitz.open(p)
            pg = d[0]
            ns = sum(len(l.get("spans", []))
                     for bl in pg.get_text("dict").get("blocks", [])
                     if bl.get("type") == 0 for l in bl.get("lines", []))
            nb = len(pg.get_images(full=True))
            rr = nachzeichnen.analysiere_doc(d, max_px=1800)
            d.close()
            rs = rr.get("raeume") or []
            mit = sum(1 for x in rs
                      if (x.get("region_px") or []) and len(x["region_px"]) >= 3)
            laeuft = "JA" if mit == 0 else f"nein ({mit} Polygone)"
            print(f"{kurz + '/' + hname:26}{ns:>7}{nb:>8}{len(rs):>7}{mit:>13}"
                  f"   {laeuft}")


if __name__ == "__main__":
    for k, m in PLAENE:
        try:
            bauen(k, m)
        except Exception as e:
            print(f"{k:10} FEHLER {type(e).__name__}: {e}")
    pruefen()
