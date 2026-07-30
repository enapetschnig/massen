"""WÄCHTER: der Raumname kommt aus dem STEMPEL, nicht von der Beschriftung daneben.

Ein Raumstempel ist eine Textsäule — Name, Belag, Fläche, Umfang stehen
untereinander und sind bündig. Eine Zeichnungsbeschriftung ("Lift D",
"Entwässerung", ein Bauteil-Code) steht DANEBEN.

Am WM-Plan gemessen, bevor die Bündigkeits-Regel da war:

    Stempel 19,83 m² · U 24,52 m · Feinsteinzeug
        Stiegenhaus   dy -23,8  dx +12,5   (bündig darüber)
        Lift D        dy  +0,6  dx +37,2   -> GEWANN
                                              d = |dy| + 0,3·|dx| = 11,8

Zwei Räume hießen darum "Lift D"/"Lift E" statt "Stiegenhaus". Der Name
entscheidet über die Gewerkezuordnung: ein Aufzugsschacht bekommt keinen
Estrich und keinen Bodenbelag, ein Stiegenhaus schon. Die Fläche war richtig,
die Zuordnung falsch — der teuerste Fehlertyp, weil er plausibel aussieht.

Geprüft werden hier die REGELN an gebauten Stempeln (schnell, ohne PDF) und
zusätzlich, dass der echte WM-Plan das Stiegenhaus findet, falls er daliegt.
"""
import glob
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))
import raumnetz as rn   # noqa: E402


class _FakeSpan(dict):
    pass


def _seite(spans):
    """Minimal-Seite, die raum_stempel() lesen kann.

    spans: [(text, x0, y0, x1, y1), ...]
    """
    class P:
        def get_text(self, _modus):
            return {"blocks": [{"type": 0, "lines": [
                {"spans": [{"text": t, "bbox": (x0, y0, x1, y1)}]}
            ]} for (t, x0, y0, x1, y1) in spans]}
    return P()


def _stempel(spans):
    return rn.raum_stempel(_seite(spans), (-1e6, 1e6, -1e6, 1e6))


# Höhe ~10pt, Zeilenabstand ~12pt — die WM-Geometrie nachgebaut
FAELLE = [
    ("Beschriftung auf derselben Zeile darf nicht gewinnen", [
        ("Stiegenhaus", 100, 76, 160, 86),
        ("Feinsteinzeug", 100, 88, 165, 98),
        ("19,83 m", 100, 100, 140, 110),
        ("²", 141, 99, 146, 106),
        ("U: 24,52 m", 100, 112, 155, 122),
        ("Lift D", 175, 100, 205, 110),      # 75pt rechts, gleiche Zeile
    ], "Stiegenhaus"),
    ("Name mittig über dem Wert", [
        ("Wohnküche", 92, 76, 152, 86),
        ("24,10 m", 100, 100, 140, 110),
        ("²", 141, 99, 146, 106),
    ], "Wohnküche"),
    ("Zusatz-Wort rechts wird nicht angehängt", [
        ("Loggia", 100, 88, 135, 98),
        ("9,45 m", 100, 100, 138, 110),
        ("²", 139, 99, 144, 106),
        ("Entwässerung", 168, 88, 240, 98),
    ], "Loggia"),
    ("Höhenkote klebt an der Ziffer — kein Raumname", [
        ("OK0,71", 100, 88, 138, 98),
        ("3,40 m", 100, 100, 138, 110),
        ("²", 139, 99, 144, 106),
    ], "?"),
    ("nacktes 'm' aus einer getrennten Längenangabe", [
        ("m", 100, 88, 108, 98),
        ("21,21 m", 100, 100, 142, 110),
        ("²", 143, 99, 148, 106),
    ], "?"),
    ("Bodenbelag ist kein Raumname", [
        ("Bad", 100, 76, 122, 86),
        ("Fliesen", 100, 88, 138, 98),
        ("5,98 m", 100, 100, 138, 110),
        ("²", 139, 99, 144, 106),
    ], "Bad"),
]


def run():
    print("RAUMNAME AUS DEM STEMPEL — nicht von der Beschriftung daneben")
    print("=" * 92)
    print(f"{'Fall':56}{'gelesen':>18}{'erwartet':>12}   ")
    print("-" * 92)
    fehler = []
    for name, spans, soll in FAELLE:
        got = _stempel(spans)
        ist = got[0]["name"] if got else "(kein Stempel)"
        if ist != soll:
            fehler.append(f"{name}: '{ist}' statt '{soll}'")
        print(f"{name[:55]:56}{str(ist)[:17]:>18}{soll:>12}"
              f"{'' if ist == soll else '   <- FALSCH'}")
    print("-" * 92)

    # ── am ECHTEN Plan, wenn er dabei ist ────────────────────────────────
    g = sorted(glob.glob(os.path.expanduser(
        "~/Downloads/*AU_WM_01 Erdgeschoss*.pdf")))
    if g:
        import fitz
        doc = fitz.open(g[0])
        pg = doc[0]
        r = pg.rect
        sp = rn.raum_stempel(pg, (r.x0, r.x1, r.y0, r.y1))
        doc.close()
        n1983 = [x for x in sp if x.get("f_m2") and abs(x["f_m2"] - 19.83) < 0.01]
        namen = sorted({str(x.get("name")) for x in n1983})
        print(f"\nechter WM-Plan: {len(n1983)} Stempel mit 19,83 m² -> {namen}")
        if any("lift" in n.lower() for n in namen):
            fehler.append("WM-Plan: 19,83-m²-Stempel heißt wieder 'Lift' — das "
                          "ist die Aufzugs-Beschriftung, nicht der Raumname")
        elif not any("stiegen" in n.lower() for n in namen):
            fehler.append(f"WM-Plan: 19,83-m²-Stempel heißt {namen}, erwartet "
                          f"'Stiegenhaus'")
        else:
            print("   Stiegenhaus richtig erkannt ✓")
        loggia = [x for x in sp if x.get("f_m2")
                  and abs(x["f_m2"] - 9.45) < 0.01]
        if loggia:
            ln = sorted({str(x.get("name")) for x in loggia})
            print(f"   9,45-m²-Stempel ({len(loggia)}x) -> {ln}")
            if any("entwässerung" in n.lower() for n in ln):
                fehler.append("WM-Plan: 'Entwässerung' klebt wieder am Raumnamen")
    else:
        print("\n(WM-Plan liegt nicht in ~/Downloads — nur die Regeln geprüft)")

    print()
    if fehler:
        print("FEHLER:")
        for f in fehler:
            print(f"  ✗ {f}")
    else:
        print(f"WÄCHTER ok: {len(FAELLE)} Stempel-Formen richtig gelesen, "
              f"Beschriftung daneben schlägt den Namen nicht mehr")
    assert not fehler, f"{len(fehler)} Namens-Fehler"


if __name__ == "__main__":
    run()
