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

Er ruft dieselbe Funktion auf, die in der Pipeline läuft
(nachzeichnen.textflecken) — vorher gab es zwei Kopien, und die sind
auseinandergelaufen. Welcher Größenfilter darin steckt, ist am Korpus
A/B-gemessen; die verworfenen Varianten stehen im Docstring der Funktion.
"""
import glob
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))
import numpy as np      # noqa: E402
import fitz             # noqa: E402
import nachzeichnen     # noqa: E402


# EINE Implementierung — die der Pipeline. Frueher stand hier eine zweite
# Kopie; die beiden sind auseinandergelaufen (der massstabsfreie Filter war
# hier gemessen, aber nie in der Pipeline angekommen). Wird hier importiert,
# kann das nicht mehr passieren: der Waechter misst, was der Nutzer bekommt.
textflecken = nachzeichnen.textflecken


KORPUS = [
    "A-5_Einreichplan_Alfred-Angerer",
    "AP.01 Layout-1",
    "AU_WM_01 Erdgeschoss",
    "WA_Velden_Franzosen Allee_Ausführung_TG",
    "1762788650811_EG-Wand-Grundriss",
]


def _umgebung_pruefen():
    """Misst dieser Lauf ueberhaupt das, was in der Produktion laeuft?

    Der Anker liest PIXEL. Pixel entstehen im PDF-Rasterer — und der
    unterscheidet sich zwischen PyMuPDF-Versionen. Am selben Korpus gemessen:

        PyMuPDF 1.24.14 (Produktion)  Median 0,75 m   17/47 unter 0,5 m
        PyMuPDF 1.25.3                       1,07 m   15/47
        PyMuPDF 1.26.5                       0,90 m   14/47

    Dieselbe Funktion, dieselben Plaene, drei verschiedene Antworten. Eine
    Zahl aus der falschen Umgebung sagt nichts ueber das, was der Nutzer
    bekommt — darum bricht dieser Guard lieber ab, als eine huebsche, aber
    bedeutungslose Zahl zu melden.
    """
    import fitz as _f
    soll = None
    rq = os.path.join(os.path.dirname(__file__), "..", "requirements.txt")
    for zeile in open(rq, encoding="utf-8"):
        if zeile.strip().lower().startswith("pymupdf=="):
            soll = zeile.strip().split("==", 1)[1].strip()
    ist = getattr(_f, "VersionBind", "?")
    print(f"Umgebung: PyMuPDF {ist} (Produktion pinnt {soll})")
    assert soll and ist == soll, (
        f"PyMuPDF {ist} statt {soll} — der Rasterer entscheidet ueber die "
        f"Pixel und damit ueber die gemessene Anker-Guete. Angleichen mit: "
        f"massenermittlung/venv/bin/python3 -m pip install PyMuPDF=={soll}")


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

    fl = textflecken(arr)
    if not fl:
        doc.close(); return None
    # DETERMINISMUS: zweiter Lauf auf demselben Bild muss identisch sein
    assert fl == textflecken(arr), \
        "Fleck-Erkennung nicht deterministisch"
    d = sorted(min(((f[0] - t[0]) ** 2 + (f[1] - t[1]) ** 2) ** 0.5
                   for f in fl) / sc / ptm for t in wahr.values())
    doc.close()
    return (len(fl), d[len(d) // 2],
            sum(1 for x in d if x < 0.5), len(d))


def run():
    _umgebung_pruefen()
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
    #   AP.01     0,52 m   Polierplan voller Kanal-/Masstext — der naechste
    #                      Fleck ist dann oft die falsche Schrift
    #   Velden    0,75 m   Tiefgarage, grob aufgeloest (28 px/m)
    #   AU_WM_01  1,79 m   grosse Tafel, grob aufgeloest (28 px/m)
    # Die Genauigkeit haengt also an TEXTDICHTE und AUFLOESUNG, nicht nur am
    # Verfahren. Darum wird hier NICHT der Bestfall festgeschrieben, sondern:
    assert geprueft >= 3, f"nur {geprueft} Pläne geprüft — Aussage nicht belastbar"
    # (a) das Verfahren FUNKTIONIERT nachweislich — mindestens ein Plan unter
    #     0,10 m; faellt das weg, ist die Erkennung selbst kaputt
    assert min(alle_med) <= 0.10, \
        f"bester Plan nur {min(alle_med):.2f} m — Fleck-Erkennung defekt"
    # (b) keine Verschlechterung ueber den Korpus. Gemessen 2026-07-29 mit
    #     der Funktion UND dem Rasterer, die wirklich in der Produktion
    #     laufen: 0,75 m. Die frueher hier stehenden 1,07 m waren doppelt
    #     verfaelscht — eine Filter-Variante, die die Pipeline nie benutzt
    #     hat, gemessen mit einer PyMuPDF-Version, die sie nie benutzt hat.
    assert gesamt_med <= 0.90, \
        f"Anker-Median {gesamt_med:.2f} m über den Korpus — geregressiert"
    print(f"bester Plan {min(alle_med):.2f} m · deterministisch "
          f"(je Plan zwei identische Läufe) ✓")
    print("HINWEIS: die Anker-Güte haengt an Textdichte und Aufloesung — auf "
          "beschriftungsarmen Plaenen zentimetergenau, auf dichten Polier-"
          "plaenen deutlich schwaecher. In der Pipeline rastet der Anker nur "
          "ein, wenn ein Fleck NAH genug liegt; sonst bleibt der Vision-Anker.")


if __name__ == "__main__":
    run()
