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

WAS DIESER WÄCHTER NICHT ZEIGT — bitte vor jeder Zusage lesen:

Der Korpus besteht aus VEKTOR-Plänen, und auf denen läuft der Anker in der
Produktion überhaupt nicht. Der einzige Aufrufer ist
api/extract.py::_vision_raum_regionen, und der steigt aus, sobald auch nur
ein Raum ein rekonstruiertes Polygon hat — bei allen Referenzplänen ist das
für jeden Raum der Fall (9/9 · 9/9 · 70/70 · 25/25). Der Anker greift nur
bei echten Scans ohne Vektor-Geometrie.

Dieser Wächter belegt also: die Fleck-Erkennung findet Raumbeschriftungen in
einem gerasterten Plan, deterministisch und messbar besser als vorher. Er
belegt NICHT, dass die Einrastung beim Nutzer die Lage verbessert. Dafür
fehlen zwei Dinge:
  1. ein Korpus aus echten Plan-Scans (lokal liegt keiner),
  2. die gemessene LAGE-Genauigkeit der Vision-Anker. Solange die unbekannt
     ist, ist unentschieden, ob Einrasten überhaupt hilft: ein Orakel, das
     immer den stempelnächsten Fleck wählt, landet im Mittel 0,80 m daneben
     — jede Vision-Lage, die besser ist als diese Decke, wird durchs
     Einrasten schlechter.
Die Simulation unten vergleicht deshalb NUR alte gegen neue Einstellung.
Sie beantwortet nicht die Frage, ob eingerastet werden soll.
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
    # WAHRHEIT: Stempelpositionen aus dem Text-Layer (byte-exakt).
    #
    # ALS LISTE, nicht als Dict nach Namen. Frueher stand hier
    #     {x["name"]: tuple(x["px"]) for x in r["raeume"] ...}
    # und das hat still den groessten Teil des Korpus verschluckt: AU_WM_01
    # hat 70 Stempel, aber nur 14 verschiedene Namen (viele heissen "?",
    # weil der Name im Stempel nicht sauber lesbar ist). 56 Stempel fielen
    # weg, und WELCHER je Name uebrig blieb, entschied die Einfuegereihenfolge.
    # Der Korpus war dadurch scheinbar 47 Stempel gross statt 113 — und die
    # gemeldete Zahl haing an einer willkuerlichen Auswahl.
    wahr = [tuple(x["px"]) for x in r["raeume"] if x.get("px")]
    # Flaeche je Stempel — die Pipeline leitet daraus die Boxgroesse und
    # damit die Einrast-Toleranz ab. Fuer die Ende-zu-Ende-Pruefung noetig.
    flaechen = [float(x.get("f_m2") or 0.0) for x in r["raeume"] if x.get("px")]
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
                   for f in fl) / sc / ptm for t in wahr)
    # Flecken der ALTEN Einstellung fuer den Vorher-Nachher-Vergleich.
    fl_alt = nachzeichnen.textflecken(arr, zell=4)
    doc.close()
    return (len(fl), d[len(d) // 2], sum(1 for x in d if x < 0.5), len(d),
            {"fl": fl, "fl_alt": fl_alt, "wahr": wahr, "flaechen": flaechen,
             "ppm": sc * ptm, "abstaende": d})


def _tol_faktor_aus_produktion():
    """Den Einrast-Faktor aus api/extract.py lesen, nicht hier nachschreiben.

    Zellgroesse und Toleranz wirken nur ZUSAMMEN: die feinere Zelle findet
    dreimal so viele Flecken, und mit der alten weiten Toleranz rastet die
    Regel dann fast immer auf irgendetwas ein. Wer eine der beiden Zahlen
    allein zurueckdreht, macht die Einrastung schlechter als vorher. Darum
    liest dieser Waechter beide aus dem echten Code.
    """
    import re
    p = os.path.join(os.path.dirname(__file__), "..", "api", "extract.py")
    m = re.search(r"_tol = max\(12\.0,\s*([0-9.]+)\s*\* max\(_bw3, _bh3\)\)",
                  open(p, encoding="utf-8").read())
    assert m, "Einrast-Toleranz in api/extract.py nicht gefunden (umbenannt?)"
    return float(m.group(1))


def _einrasten(daten, zell_neu, tol_faktor, rausch_m, startwert):
    """Die ECHTE Pipeline-Regel auf simulierter Vision-Lage.

    -> (richtig, falsch, offen). "falsch" heisst: eingerastet, aber weiter
    als 0,5 m vom echten Stempel — der teure Fehler, weil er sicher aussieht.
    """
    import math
    import random
    rnd = random.Random(startwert)
    richtig = falsch = offen = 0
    for d in daten:
        fl = d["fl"] if zell_neu else d["fl_alt"]
        ppm = d["ppm"]
        if not fl:
            offen += len(d["wahr"])
            continue
        for i, (tx, ty) in enumerate(d["wahr"]):
            w = rnd.uniform(0, 2 * math.pi)
            r = rnd.gauss(rausch_m, rausch_m * 0.4)
            vx, vy = tx + r * ppm * math.cos(w), ty + r * ppm * math.sin(w)
            f = d["flaechen"][i] if i < len(d["flaechen"]) else 0.0
            seite = (max(f, 1.0) ** 0.5) * ppm
            tol = max(12.0, tol_faktor * seite)
            best = min(fl, key=lambda p: (p[0] - vx) ** 2 + (p[1] - vy) ** 2)
            if ((best[0] - vx) ** 2 + (best[1] - vy) ** 2) ** 0.5 > tol:
                offen += 1
                continue
            if ((best[0] - tx) ** 2 + (best[1] - ty) ** 2) ** 0.5 / ppm < 0.5:
                richtig += 1
            else:
                falsch += 1
    return richtig, falsch, offen


def _einrasten_pruefen(daten):
    """Bringt die heutige Einstellung dem NUTZER mehr als die alte?

    "Abstand zum naechsten Fleck" ist nur ein Stellvertreter. Entscheidend
    ist, was die Pipeline-Regel daraus macht — und dort kann eine bessere
    Erkennung sogar schaden, wenn die Regel zu grosszuegig ist.
    """
    tf = _tol_faktor_aus_produktion()
    print(f"\nEinrasten (Pipeline-Regel, Toleranzfaktor {tf} aus extract.py)")
    print(f"  {'Vision-Versatz':>15}{'alt r/f':>14}{'heute r/f':>14}{'Differenz':>16}")
    print("  " + "-" * 60)
    sR = sF = 0
    schlimmster = None
    for rm in (0.2, 0.3, 0.4, 0.6, 0.8):
        aR = aF = nR = nF = 0
        for sw in (1, 7, 23):
            x, y, _ = _einrasten(daten, False, 0.25, rm, sw)
            aR += x; aF += y
            x, y, _ = _einrasten(daten, True, tf, rm, sw)
            nR += x; nF += y
        sR += nR - aR; sF += nF - aF
        if schlimmster is None or (nR - aR) - (nF - aF) < schlimmster[0]:
            schlimmster = ((nR - aR) - (nF - aF), rm, nR - aR, nF - aF)
        print(f"  {rm:14.1f}m{aR:>8}/{aF:<5}{nR:>8}/{nF:<5}"
              f"{nR - aR:>+9}/{nF - aF:<5}")
    print("  " + "-" * 60)
    print(f"  gesamt: richtig {sR:+d} · falsch {sF:+d}")
    # (e) die heutige Einstellung muss dem Nutzer MEHR richtige Einrastungen
    #     bringen als die alte — und nicht mehr falsche. Beides zusammen,
    #     sonst ist es kein Fortschritt, sondern eine Verschiebung.
    assert sR > 0, \
        f"keine zusaetzlichen richtigen Einrastungen ({sR:+d}) — die feinere " \
        f"Zelle bringt dem Nutzer nichts"
    assert sF <= 0, \
        f"{sF:+d} FALSCHE Einrastungen mehr — eine falsche Lage sieht sicher " \
        f"aus und ist schlimmer als gar keine. Toleranzfaktor pruefen " \
        f"(gemessen: 0,25 kostet +155 falsche, 0,10 spart 464)"
    # (f) auch der schlechteste Vision-Versatz darf nicht ins Minus kippen
    assert schlimmster[3] <= 2, \
        f"bei Vision-Versatz {schlimmster[1]} m: {schlimmster[3]:+d} falsche " \
        f"Einrastungen — die Regel ist dort zu grosszuegig"
    print(f"  schlechtester Vision-Versatz {schlimmster[1]} m: "
          f"richtig {schlimmster[2]:+d} · falsch {schlimmster[3]:+d} ✓")


def run():
    _umgebung_pruefen()
    print(f"{'Plan':<40}{'Flecken':>8}{'Median':>9}{'<0,5 m':>10}")
    print("-" * 70)
    alle_med, ges_nah, ges_n, geprueft = [], 0, 0, 0
    # Plaene mit genug Stempeln, um eine Aussage zu tragen. Ein Blatt mit
    # zwei Stempeln hat als "Median" einen von zwei Werten — daran darf keine
    # Zusage haengen, weder im Guten noch im Schlechten.
    tragfaehig = []
    sim_daten = []      # Rohdaten je Plan fuer die Ende-zu-Ende-Pruefung
    for teil in KORPUS:
        g = sorted(glob.glob(os.path.expanduser(f"~/Downloads/*{teil}*.pdf")))
        if not g:
            print(f"{teil[:38]:<40}{'(Datei fehlt)':>27}")
            continue
        erg = _messe(g[0])
        if not erg:
            print(f"{os.path.basename(g[0])[:38]:<40}{'(kein Grundriss)':>27}")
            continue
        n_fl, med, nah, n, roh = erg
        sim_daten.append(roh)
        geprueft += 1
        alle_med.append(med); ges_nah += nah; ges_n += n
        if n >= 5:
            tragfaehig.append((os.path.basename(g[0]), med, n))
        print(f"{os.path.basename(g[0])[:38]:<40}{n_fl:>8}{med:>8.2f}m{nah:>6}/{n:<4}"
              f"{'' if n >= 5 else '  (zu wenige Stempel für eine Aussage)'}")
    print("-" * 70)
    if not geprueft:
        print("OK — übersprungen (keine Referenzpläne vorhanden)")
        return
    alle_med.sort()
    # ECHTER Korpus-Median: über alle Stempel, nicht über die Plan-Mediane.
    # Hier stand früher alle_med[len//2] und war als "Median über alle"
    # beschriftet — das ist der mittlere der Plan-Mediane und etwas ganz
    # anderes: bei zell=4 ergab er 0,90 m, der echte Korpus-Median 1,12 m.
    # AU_WM_01 stellt allein 70 der 113 Stempel; ein Plan-Mittel wiegt ihn
    # genauso wie einen Plan mit 9.
    _alle_abst = sorted(x for s in sim_daten for x in (s.get("abstaende") or []))
    gesamt_med = (_alle_abst[len(_alle_abst) // 2] if _alle_abst
                  else alle_med[len(alle_med) // 2])
    print(f"{geprueft} Pläne · {len(_alle_abst)} Stempel · "
          f"Korpus-Median {gesamt_med:.2f} m · Median der Plan-Mediane "
          f"{alle_med[len(alle_med) // 2]:.2f} m · "
          f"{ges_nah}/{ges_n} Stempel mit Fleck unter 0,5 m")
    # EHRLICHE ZUSAGEN — am Korpus gemessen, nicht am Bestfall.
    #
    # Stand 2026-07-29, nach der Umstellung auf Zellgroesse 2 (vorher 4):
    #   Angerer   0,04 m   wenige, klar stehende Raumbeschriftungen
    #   AP.01     0,45 m   Polierplan voller Kanal-/Masstext — der naechste
    #                      Fleck ist dann oft die falsche Schrift
    #   Velden    0,55 m   Tiefgarage, grob aufgeloest (28 px/m)
    #   AU_WM_01  0,68 m   grosse Tafel, grob aufgeloest (28 px/m)
    #
    # Vorher lagen dieselben Plaene bei 0,04 / 0,52 / 0,90 / 1,50 m. Die
    # URSACHE der Schwaeche war nicht die Textdichte, wie hier lange stand,
    # sondern die Rasterung: bei 28 px/m verwischt die Stempelschrift zu
    # hellgrau (dunkelster Grauwert 149-153 statt 0) und faellt aus der
    # Maske. Eine feinere Zelle faengt sie — siehe nachzeichnen.textflecken.
    # Textdichte bleibt ein Faktor (AP.01), ist aber nicht der Haupteffekt.
    assert geprueft >= 3, f"nur {geprueft} Pläne geprüft — Aussage nicht belastbar"
    # (a) das Verfahren FUNKTIONIERT nachweislich — mindestens ein Plan unter
    #     0,10 m; faellt das weg, ist die Erkennung selbst kaputt
    assert min(alle_med) <= 0.10, \
        f"bester Plan nur {min(alle_med):.2f} m — Fleck-Erkennung defekt"
    # (b) keine Verschlechterung ueber den Korpus. Die Schwelle wird mit dem
    #     Fortschritt nachgezogen, sonst bewacht sie nichts mehr: gemessen
    #     0,56 m (Korpus-Median ueber alle Stempel), festgeschrieben 0,62 m.
    assert gesamt_med <= 0.62, \
        f"Anker-Median {gesamt_med:.2f} m über den Korpus — geregressiert"
    # (c) der Anker muss auch auf den GROB aufgeloesten Plaenen tragen —
    #     genau dort war er unbrauchbar. Kein tragfaehiger Plan (>=5 Stempel)
    #     darf schlechter als 0,80 m sein; vorher lagen zwei bei 0,90 und
    #     1,50 m.
    if tragfaehig:
        schlecht = max(tragfaehig, key=lambda t: t[1])
        print(f"schlechtester tragfähiger Plan: {schlecht[0][:34]} "
              f"{schlecht[1]:.2f} m ({schlecht[2]} Stempel)")
        assert schlecht[1] <= 0.80, \
            f"{schlecht[0]} bei {schlecht[1]:.2f} m — grob aufgeloeste Plaene " \
            f"tragen wieder nicht (Rasterung pruefen, siehe textflecken-Docstring)"
    # (d) die Einrastung muss auf der MEHRHEIT der Stempel greifen, nicht nur
    #     im Median. Gemessen 51/113 = 45 %; vorher 24/113 = 21 %.
    assert ges_n and ges_nah / ges_n >= 0.38, \
        f"nur {ges_nah}/{ges_n} Stempel unter 0,5 m — Einrastquote gefallen"
    # (e/f) und das Entscheidende: bringt es dem NUTZER etwas?
    if sim_daten:
        _einrasten_pruefen(sim_daten)
    print(f"bester Plan {min(alle_med):.2f} m · deterministisch "
          f"(je Plan zwei identische Läufe) ✓")
    print("HINWEIS: der begrenzende Faktor ist die RASTERUNG, nicht die "
          "Textdichte — bei 28 px/m verwischt die Stempelschrift zu hellgrau "
          "und faellt aus der Maske. Eine feinere Zelle faengt sie (Zellgroesse "
          "2 statt 4). Textdichte bleibt ein Nebeneffekt: AP.01 hat trotz "
          "96 px/m 0,45 m, weil dort viel Fremdschrift steht. In der Pipeline "
          "rastet der Anker nur ein, wenn ein Fleck NAH genug liegt; sonst "
          "bleibt der Vision-Anker stehen.")


if __name__ == "__main__":
    run()
