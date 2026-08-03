"""WÄCHTER: das GEWERK steht im Wandaufbau, nicht in der Wanddicke.

Die naheliegende Regel „dünne Wand = Trockenbau" ist am Korpus widerlegt:
  · Angerer: 12 cm = Hochlochziegel — also MAUERWERK (LG 08).
  · WM:      12,5 cm = Ständerwand, 15 cm = Ständerwand,
             20 und 38,5 cm = Stahlbeton mit GK-Beplankung (LG 07 Beton!).
Die Dicke ist damit nachweislich kein Material-Signal. Was das Gewerk trägt,
ist der WANDAUFBAU je Code — und der steht byte-exakt in der Legende.

`legende.materialklasse()` ordnet ihn zu: mauerwerk / beton / trockenbau /
holz. Zwei Vorrang-Regeln sind dabei entscheidend und werden hier gepinnt:
  1. „Stahlbeton mit GK-Beplankung" ist BETON (LG 07), keine Trockenbauwand.
     Sonst wandert eine tragende Wand ins Ausbau-Gewerk.
  2. „Holzständerwand" ist ZIMMERER (LG 36), nicht Trockenbau (LG 39).
     Die Teilzeichenkette „ständerwand" trifft sie sonst mit.

Dazu die zwei Lesefehler, die den WM-Plan seine ganze Legende gekostet
haben (Konfidenz 0,0, null Wandtypen, obwohl sie vollständig dasteht):
  · `(\\d+)\\b` scheitert an „IW01a"/„IW10a" — zwischen Ziffer und Buchstabe
    steht keine Wortgrenze.
  · Am Zeilenanfang verankert findet man „C/D/E - IW03" nicht.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "api"))

# (Aufbau-Text, erwartete Klasse, warum)
KLASSEN = [
    ("Hochlochziegel 25 cm", "mauerwerk", "Ziegel = LG 08"),
    ("HLZ 12", "mauerwerk", "auch dünn bleibt Ziegel Mauerwerk"),
    ("Stahlbeton 20 cm", "beton", "STB = LG 07"),
    ("Mantelbeton", "beton", "Beton bleibt Beton"),
    ("Vorsatzschale, 5 cm", "trockenbau", "Vorsatzschale = LG 39"),
    ("Gipskartonwand einlagig", "trockenbau", "GK-Wand = LG 39"),
    ("Metallständerwand CW 75", "trockenbau", "Metallständer = LG 39"),
    # DIE ZWEI VORRANG-FÄLLE
    ("Stahlbeton 20 cm mit GK-Beplankung", "beton",
     "tragende Wand bleibt LG 07, auch wenn Gipskarton draufsitzt"),
    ("Holzständerwand 12/16 mit Zellulose", "holz",
     "Zimmerer LG 36, NICHT Trockenbau LG 39"),
    ("Fenster", None, "kein Wandaufbau"),
    ("", None, "leer"),
]

# (Text, erwarteter Code oder None) — die Schreibweisen des Korpus
CODES = [
    ("AW1", "AW1"), ("AW 1", "AW1"), ("IW 2", "IW2"),
    ("IW01a", "IW01a"), ("IW10a", "IW10a"),        # Buchstaben-Suffix
    ("C/D/E - IW03", "IW03"), ("C/D/E-IW10a", "IW10a"),  # Code mitten im Text
    ("(IW02)", "IW02"),
    ("Fenster", None),
]


def run():
    import legende as LEG
    print("MATERIALKLASSE — das Gewerk steht im Aufbau, nicht in der Dicke")
    print("=" * 92)
    fehler = []

    print("Wandaufbau → Gewerk:")
    for text, soll, warum in KLASSEN:
        ist = LEG.materialklasse(text)
        ok = (ist or None) == soll
        if not ok:
            fehler.append(f"materialklasse({text!r}) = {ist!r}, erwartet "
                          f"{soll!r} — {warum}")
        print(f"   {'✓' if ok else 'FALSCH':<7}{str(text)[:38]:<40}"
              f"→ {str(ist):<12}{warum}")

    print("\nWand-Code lesen (Schreibweisen des Korpus):")
    for text, soll in CODES:
        m = LEG.WAND_CODE_RX.search(text)
        ist = (m.group(1).upper() + m.group(2)) if m else None
        ok = ist == soll
        if not ok:
            fehler.append(f"Code aus {text!r} = {ist!r}, erwartet {soll!r}")
        print(f"   {'✓' if ok else 'FALSCH':<7}{text:<20}→ {ist}")

    # REALPROBE: der Angerer muss seine vier Wandtypen MIT Klasse liefern.
    import glob

    import fitz
    g = sorted(glob.glob(os.path.expanduser(
        "~/Downloads/*A-5_Einreichplan_Alfred-Angerer*")))
    if not g:
        print("\n   (Angerer nicht in ~/Downloads — Realprobe übersprungen)")
    else:
        doc = fitz.open(g[0])
        sp = []
        for b in doc[0].get_text("dict").get("blocks", []):
            if b.get("type") != 0:
                continue
            for l in b.get("lines", []):
                for s in l.get("spans", []):
                    t = (s.get("text") or "").strip()
                    if not t:
                        continue
                    bb = s["bbox"]
                    sp.append({"text": t, "bbox": bb, "size": s.get("size", 0),
                               "cx": (bb[0] + bb[2]) / 2,
                               "cy": (bb[1] + bb[3]) / 2})
        doc.close()
        wt = (LEG.parse_legende(sp).get("wand_typen") or {})
        print(f"\nRealprobe Angerer: {len(wt)} Wandtypen")
        if len(wt) < 4:
            fehler.append(f"Angerer liefert nur {len(wt)} Wandtypen statt 4 — "
                          f"die Code-Erweiterung hat bestehende Lesungen "
                          f"kaputtgemacht")
        for code, d in sorted(wt.items()):
            k = d.get("materialklasse")
            print(f"   {code:<8}{d.get('dicke_cm')!s:>7} cm  "
                  f"{str(d.get('material'))[:22]:<24}{str(k)}")
            if k != "mauerwerk":
                fehler.append(f"Angerer {code}: Klasse {k!r} statt "
                              f"'mauerwerk' (Aufbau ist Hochlochziegel)")

    # AUFBAUTENTABELLE: manche Polierpläne führen die Wandaufbauten als eigene
    # Tabelle, weit weg von den Code-Markern, mit dem Wert VOR dem Material und
    # in MILLIMETERN. Der WM-Plan tut das; die Wandstärke ist dort die SUMME
    # der Schichten. Genau daran las die App auf WM null Wandtypen.
    print("\nAufbautentabelle:")
    ERWARTET = {
        # code: (dicke_cm, materialklasse, warum)
        "IW01a": (36.0, "beton",
                  "200 mm Stahlbeton-Kern → LG 07, trotz GK-Beplankung"),
        "IW02": (27.5, "beton", "200 mm Stahlbeton-Kern → LG 07"),
        "IW10a": (10.0, "trockenbau", "Vorsatzschale ohne tragende Schicht"),
    }
    g2 = sorted(glob.glob(os.path.expanduser(
        "~/Downloads/*AU_WM_01 Erdgeschoss*INDEX E.pdf")))
    if not g2:
        print("   (WM nicht in ~/Downloads — Tabellen-Probe übersprungen)")
    else:
        doc = fitz.open(g2[0])
        sp2 = []
        for b in doc[0].get_text("dict").get("blocks", []):
            if b.get("type") != 0:
                continue
            for l in b.get("lines", []):
                for s in l.get("spans", []):
                    t = (s.get("text") or "").strip()
                    if not t:
                        continue
                    bb = s["bbox"]
                    sp2.append({"text": t, "bbox": bb, "size": s.get("size", 0),
                                "cx": (bb[0] + bb[2]) / 2,
                                "cy": (bb[1] + bb[3]) / 2})
        doc.close()
        tab = LEG.aufbau_tabelle(sp2)
        for code, (d_soll, k_soll, warum) in ERWARTET.items():
            d = tab.get(code) or {}
            d_ist, k_ist = d.get("dicke_cm"), d.get("materialklasse")
            ok = (d_ist == d_soll and k_ist == k_soll)
            if not ok:
                fehler.append(f"WM {code}: {d_ist} cm / {k_ist!r}, erwartet "
                              f"{d_soll} cm / {k_soll!r} — {warum}")
            print(f"   {'✓' if ok else 'FALSCH':<7}{code:<8}{str(d_ist):>7} cm  "
                  f"{str(k_ist):<12}{warum}")
        # KEIN FEHLALARM: Pläne ohne solche Tabelle dürfen nichts liefern.
        for muster, lbl in (("A-5_Einreichplan_Alfred-Angerer", "Angerer"),
                            ("AP.01 Layout-1 (1).pdf", "AP.01")):
            gg = sorted(glob.glob(os.path.expanduser(f"~/Downloads/*{muster}*")))
            if not gg:
                continue
            doc = fitz.open(gg[0])
            sp3 = []
            for b in doc[0].get_text("dict").get("blocks", []):
                if b.get("type") != 0:
                    continue
                for l in b.get("lines", []):
                    for s in l.get("spans", []):
                        t = (s.get("text") or "").strip()
                        if not t:
                            continue
                        bb = s["bbox"]
                        sp3.append({"text": t, "bbox": bb,
                                    "size": s.get("size", 0),
                                    "cx": (bb[0] + bb[2]) / 2,
                                    "cy": (bb[1] + bb[3]) / 2})
            doc.close()
            n = len(LEG.aufbau_tabelle(sp3))
            print(f"   {'✓' if n == 0 else 'FALSCH':<7}{lbl:<8}{n:>7} Aufbauten "
                  f"(hat keine Tabelle — muss 0 sein)")
            if n:
                fehler.append(f"{lbl} hat keine Aufbautentabelle, liefert aber "
                              f"{n} — Fehlalarm")

    print("-" * 92)
    if fehler:
        print("FEHLER:")
        for f in fehler:
            print(f"  ✗ {f}")
    else:
        print("WÄCHTER ok: Aufbau → Gewerk korrekt zugeordnet (Beton schlägt "
              "GK-Beplankung,\n           Holzständer ist Zimmerer), und die "
              "Code-Schreibweisen des Korpus werden gelesen")
    assert not fehler, f"{len(fehler)} Materialklasse-Fehler"


if __name__ == "__main__":
    run()
