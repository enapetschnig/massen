"""WÄCHTER: Wiesen und Spielplätze sind keine Räume.

Am WM-Plan standen 11 Geländeflächen mit zusammen 2153 m² in der Raumliste —
gegenüber 810 m² echter Räume. Sie überzogen den halben Plan mit Umriss-Lappen
("die Erkennung macht so einen Bogen"), und ein Polier, der
"Kinderspielfläche 313,96 m²" zwischen seinen Wohnungen findet, glaubt der
ganzen Liste nicht mehr.

WICHTIG und hier mitgeprüft: auf die MENGEN wirkte das nie. Jedes Innen-Gewerk
filtert auf kategorie_of() == 'Innenraum_warm'; end-zu-Ende gemessen ändern
sich 0 Positionen, wenn man die Freiflächen entfernt. Der Wächter hält beides
fest — die Trennung UND die Unversehrtheit der Mengen.

Die Regel ist sprachunabhängig und kommt aus dem Stempel:
ein Raumstempel führt Fläche UND Umfang (beides wird für den Innenausbau
gebraucht), eine Geländefläche nur eine Fläche.

    INNEN-Stempel   107 · 83 mit U-Angabe (78%)
    AUSSEN-Stempel   15 ·  0 mit U-Angabe ( 0%)

Weil 22% echter Räume ebenfalls kein U tragen, entscheidet erst die
Kombination: kein U + keine bekannte Raum-Kategorie + mindestens 100 m².
Am Korpus: 12 erkannt, 0 Fehlalarm, 3 verpasst (Radabstellplätze mit 22,70 m²,
die bleiben absichtlich Raum — einen echten Raum zu verlieren wäre teurer).
"""
import glob
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))
import massen_logic as ml   # noqa: E402

# (Name, F, U, soll_freiflaeche)
FAELLE = [
    ("Kinderspielfläche", 313.96, None, True),
    ("halbverband", 321.51, None, True),
    ("?", 233.83, None, True),
    # echte Räume dürfen NIE erwischt werden
    ("Tiefgarage", 555.90, None, False),          # bekannte Kategorie
    ("Wohnküche", 36.74, 26.82, False),           # trägt U
    ("Zimmer", 11.92, None, False),               # zu klein
    ("Halle", 180.00, 62.00, False),              # trägt U -> Raum
    ("Radabstell", 22.70, None, False),           # unter der Schwelle: Raum
]


def run():
    print("FREIFLÄCHE ODER RAUM?")
    print("=" * 88)
    print(f"{'Stempel':<26}{'F m²':>10}{'U m':>8}{'erkannt':>12}{'erwartet':>11}")
    print("-" * 88)
    fehler = []
    for name, f, u, soll in FAELLE:
        ist = ml.ist_aussenanlage(name, f, u)
        if ist != soll:
            fehler.append(f"{name} ({f} m²): {'Freifläche' if ist else 'Raum'}, "
                          f"erwartet {'Freifläche' if soll else 'Raum'}")
        print(f"{name[:25]:<26}{f:>10.2f}{(u if u else 0):>8.2f}"
              f"{'Freifläche' if ist else 'Raum':>12}"
              f"{'Freifläche' if soll else 'Raum':>11}"
              f"{'' if ist == soll else '   <- FALSCH'}")
    print("-" * 88)

    # Robustheit: kaputte Eingaben dürfen nicht crashen
    for bad in ((None, None, None), ("x", "abc", None), ("y", float("nan"), None),
                ("z", -5, None), (None, 1e9, None)):
        try:
            ml.ist_aussenanlage(*bad)
        except Exception as e:
            fehler.append(f"crash bei {bad}: {type(e).__name__}: {e}")
    print("Kaputte Eingaben (None/Text/NaN/negativ) — kein Absturz ✓")

    # ── DIE MENGEN DÜRFEN SICH NICHT ÄNDERN ──────────────────────────────
    ROOMS = [
        {"name": "Wohnküche", "flaeche_m2": 36.74, "umfang_m": 26.82, "hoehe_m": 2.5},
        {"name": "Bad", "flaeche_m2": 5.80, "umfang_m": 10.45, "hoehe_m": 2.5},
        {"name": "Zimmer", "flaeche_m2": 11.92, "umfang_m": 14.10, "hoehe_m": 2.5},
    ]
    FREI = [
        {"name": "Kinderspielfläche", "flaeche_m2": 313.96, "umfang_m": None},
        {"name": "halbverband", "flaeche_m2": 321.51, "umfang_m": None},
        {"name": "?", "flaeche_m2": 233.83, "umfang_m": None},
    ]
    bd = {"geschosshoehe_m": 3.0, "aussenwand_cm": 50.0,
          "innenwand_tragend_cm": 25.0, "innenwand_nichttragend_cm": 12.0,
          "decke_cm": 25.0, "bodenplatte_cm": 25.0, "hat_keller": False,
          "wandmaterial": "Hochlochziegel"}

    def mengen(rooms):
        g = ml.berechne_gewerke(rooms, [], dict(bd), geschoss="EG",
                                tueren=[])["gewerke"]
        o = {}
        for k, v in (g or {}).items():
            for p in ((v or {}).get("positionen") or []):
                if p.get("endsumme"):
                    o[f"{k}|{p.get('beschreibung')}"] = round(p["endsumme"], 2)
        return o

    a, b = mengen(ROOMS + FREI), mengen(ROOMS)
    abw = [k for k in set(a) | set(b) if a.get(k) != b.get(k)]
    print(f"\nMengen MIT Freiflächen vs OHNE: {len(a)} Positionen, "
          f"{len(abw)} Unterschiede")
    if abw:
        for k in abw[:8]:
            fehler.append(f"Freifläche wirkt auf '{k}': {b.get(k)} -> {a.get(k)}")
    else:
        print("   keine Position ändert sich — die Kategorie-Sperre hält ✓")

    # ── am ECHTEN Plan ───────────────────────────────────────────────────
    g = sorted(glob.glob(os.path.expanduser(
        "~/Downloads/*AU_WM_01 Erdgeschoss*.pdf")))
    if g:
        import fitz
        import nachzeichnen
        doc = fitz.open(g[0])
        r = nachzeichnen.analysiere_doc(doc, max_px=1400)
        doc.close()
        rr = [x for x in (r.get("raeume") or []) if x.get("f_m2")]
        fr = [x for x in rr if x.get("aussenanlage")]
        print(f"\nechter WM-Plan: {len(rr)} Stempel · {len(fr)} Freiflächen "
              f"({sum(x['f_m2'] for x in fr):.0f} m²) · "
              f"{len(rr)-len(fr)} Räume "
              f"({sum(x['f_m2'] for x in rr if not x.get('aussenanlage')):.0f} m²)")
        if len(fr) < 8:
            fehler.append(f"nur {len(fr)} Freiflächen erkannt — am WM-Plan sind "
                          f"es 11; die Geländelappen stehen wieder in der Raumliste")
        # kein echter Raum darf erwischt werden
        fp = [x for x in fr
              if ml.kategorie_of(x.get("name")) == "Innenraum_warm"]
        if fp:
            fehler.append(f"{len(fp)} ECHTE Räume als Freifläche markiert: "
                          f"{[x.get('name') for x in fp][:5]}")
        else:
            print("   kein echter Raum fälschlich als Freifläche markiert ✓")
    else:
        print("\n(WM-Plan liegt nicht in ~/Downloads — nur die Regeln geprüft)")

    print()
    if fehler:
        print("FEHLER:")
        for f in fehler:
            print(f"  ✗ {f}")
    else:
        print(f"WÄCHTER ok: {len(FAELLE)} Stempel richtig eingeordnet, "
              f"Mengen unverändert")
    assert not fehler, f"{len(fehler)} Freiflächen-Fehler"


if __name__ == "__main__":
    run()
