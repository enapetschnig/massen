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

        # PRÄZISIONS-GATE: eine PLATTE ist keine WAND.
        # Gemessen 2026-08-02: das alte Muster "gipskarton" traf auch
        # "Gipskartonplatte" — ein Material-Eintrag der Schichtaufbau-Legende.
        # Auf AP.01 und Angerer war das der EINZIGE Treffer, und der Hinweis
        # riet dort, 74 bzw. 63 m Wandlänge von LG 08 nach LG 39 umzubuchen.
        # Zwei von drei Auslösungen waren also Fehlalarm.
        for txt, soll, warum in (
            ("Gips (Gipskartonplatte) 12,5mm", False,
             "Platte in der Material-Legende — keine Wand-Deklaration"),
            ("IW10a Vorsatzschale, 5cm", True, "Vorsatzschale = Bauteil"),
            ("Gipskartonwand einlagig beplankt", True, "…wand = Bauteil"),
            ("Metallständerwand CW 75", True, "Ständerwand = Bauteil"),
            # HOLZständerwand ist ZIMMERER (LG 36), nicht Trockenbau (LG 39).
            # `"ständerwand" in wort` trifft sie als Teilzeichenkette mit —
            # ein Holzriegelbau würde ins falsche Gewerk gebucht.
            ("Holzständerwand 12/16", False, "Holzbau = LG 36 Zimmerer"),
            ("Holzriegelwand mit Zellulose", False, "Holzbau = LG 36"),
        ):
            doc = fitz.open(p)
            doc[0].insert_text((700, 80), txt, fontsize=8)
            pf = os.path.join(tmp, f"gate_{abs(hash(txt)) % 9999}.pdf")
            doc.save(pf)
            doc.close()
            doc = fitz.open(pf)
            r = nachzeichnen.analysiere_doc(doc, max_px=1400)
            doc.close()
            ist = bool((r.get("meta") or {}).get("trockenbau_hinweis"))
            ok = ist == soll
            print(f"   {txt[:34]:<36} hinweis={str(ist):<5} soll={soll}  "
                  f"{'✓' if ok else 'FALSCH'}  — {warum}")
            if not ok:
                fehler.append(f"Präzisions-Gate '{txt[:30]}': hinweis={ist}, "
                              f"erwartet {soll} ({warum})")

    # Realprobe: WM deklariert wörtlich, AP.01 und Angerer nennen NUR die
    # Platte — auf denen darf nichts stehen.
    for muster, soll, lbl in (
        ("AU_WM_01 Erdgeschoss*INDEX E.pdf", True, "WM (deklariert wörtlich)"),
        ("AP.01 Layout-1 (1).pdf", False, "AP.01 (nur Platte in Legende)"),
        ("A-5_Einreichplan_Alfred-Angerer*", False, "Angerer (nur Platte)"),
    ):
        g = sorted(glob.glob(os.path.expanduser(f"~/Downloads/*{muster}")))
        if not g:
            print(f"   ({lbl} nicht in ~/Downloads — übersprungen)")
            continue
        doc = fitz.open(g[0])
        r = nachzeichnen.analysiere_doc(doc, max_px=1400)
        doc.close()
        ist = bool((r.get("meta") or {}).get("trockenbau_hinweis"))
        ok = ist == soll
        print(f"   {lbl:<36} hinweis={str(ist):<5} soll={soll}  "
              f"{'✓' if ok else 'FALSCH'}")
        if not ok:
            fehler.append(f"{lbl}: hinweis={ist}, erwartet {soll}")

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
