"""WÄCHTER: Trockenbau-Kennzeichnung wird erkannt — und schweigt ohne Anlass.

Erste Stufe eines LG-39-Gewerks (Trockenbau), OHNE Mengen-Eingriff — nach
demselben Muster wie die Bestand/Abbruch-Farb-Erkennung: der Plan sagt es,
die App gibt es weiter, der Kalkulant entscheidet.

Warum das zählt: der echte WM-Plan schreibt wörtlich "Alle Trockenbauwände
und Vorsatzschalen … !!!" — heute rechnet die App solche nichttragenden
Wände stumm als Mauerwerk (LG 08). Das ist ein anderes Gewerk mit anderen
Preisen. Ein volles LG-39-Aufmaß braucht die Material-Trennung je Wand
(sonst Doppelzählung mit LG 08); bis dahin muss die App ehrlich sagen,
DASS der Plan Trockenbau kennzeichnet.

Drei Zusagen:
  1. Plan MIT Kennzeichnung  -> meta.trockenbau_hinweis == True
  2. Plan OHNE Kennzeichnung -> False (kein Fehlalarm — ein falscher
     Hinweis lässt am richtigen Mauerwerks-Aufmaß zweifeln)
  3. der ECHTE WM-Plan wird erkannt (byte-exakte Realprobe)
"""
import glob
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "api"))
from _plan_generator import PlanBauer   # noqa: E402


def _wohnung(b):
    return (b.raum("Wohnküche", 1.0, 1.0, 5.2, 4.6, "Parkett")
             .raum("Bad", 6.7, 1.0, 2.4, 2.8, "Fliesen")
             .raum("Zimmer 1", 1.0, 5.9, 4.0, 3.6, "Parkett")
             .raum("Vorraum", 5.2, 5.9, 2.2, 3.6, "Fliesen"))


def run():
    import fitz
    import nachzeichnen
    print("TROCKENBAU-HINWEIS — Plan-Kennzeichnung byte-exakt erkannt?")
    print("=" * 76)
    fehler = []
    with tempfile.TemporaryDirectory() as tmp:
        p = _wohnung(PlanBauer(massstab=50)).schreibe(
            os.path.join(tmp, "ohne.pdf"))
        doc = fitz.open(p)
        doc[0].insert_text(
            (700, 80),
            "!!! Alle Trockenbauwände und Vorsatzschalen auf 5cm XPS stellen !!!",
            fontsize=8)
        p_mit = os.path.join(tmp, "mit.pdf")
        doc.save(p_mit)
        doc.close()
        for name, pfad, soll in (("gebaut MIT Kennzeichnung", p_mit, True),
                                 ("gebaut OHNE Kennzeichnung", p, False)):
            doc = fitz.open(pfad)
            r = nachzeichnen.analysiere_doc(doc, max_px=1400)
            doc.close()
            ist = (r.get("meta") or {}).get("trockenbau_hinweis")
            print(f"   {name:<28} ok={r.get('ok')}  hinweis={ist}  "
                  f"(soll {soll})")
            if not r.get("ok"):
                fehler.append(f"{name}: Plan nicht analysierbar "
                              f"({r.get('grund')})")
            elif bool(ist) != soll:
                fehler.append(f"{name}: hinweis={ist}, erwartet {soll}")

    g = sorted(glob.glob(os.path.expanduser(
        "~/Downloads/*AU_WM_01 Erdgeschoss*INDEX E.pdf")))
    if g:
        doc = fitz.open(g[0])
        r = nachzeichnen.analysiere_doc(doc, max_px=1400)
        doc.close()
        ist = (r.get("meta") or {}).get("trockenbau_hinweis")
        print(f"   {'echter WM-Plan':<28} hinweis={ist}  (soll True — der "
              f"Plan trägt den Text wörtlich)")
        if ist is not True:
            fehler.append("echter WM-Plan: Trockenbau-Text nicht erkannt")
    else:
        print("   (WM-Plan nicht in ~/Downloads — Realprobe übersprungen)")

    print("-" * 76)
    if fehler:
        print("FEHLER:")
        for f in fehler:
            print(f"  ✗ {f}")
    else:
        print("WÄCHTER ok: Trockenbau-Kennzeichnung erkannt, kein Fehlalarm, "
              "Realprobe bestanden")
    assert not fehler, f"{len(fehler)} Trockenbau-Hinweis-Fehler"


if __name__ == "__main__":
    run()
