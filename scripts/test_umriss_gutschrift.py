"""WÄCHTER: das Umriss-Gate muss dieselbe Fläche prüfen wie die Menge.

Der Tür-Balken versiegelt Zellen, die laut Plan-F zum Raum gehören. Für die
MENGE ist das seit Langem gutgeschrieben (`_messen_und_status`, Balken-F-
Gutschrift). Das UMRISS-GATE in `raum_regionen` sah diese Gutschrift NICHT —
es prüfte die nackte Polygonfläche. Dadurch verlor ein Raum seinen Umriss
allein deshalb, weil eine Tür dicht gemacht wurde, während seine Menge
unverändert weiterlief. Zwei Stellen, zwei Zahlen für dieselbe Fläche.

Am Korpus gemessen (2026-08-08, 4 echte Pläne):
    Form am Plan bewiesen   42 → 51
    Form ungeprüft          56 → 46
    echte Umrisse           70 → 75
    Laufzeit               433 → 414 s
    Türen                  unverändert (28 undicht von 57)

VIER ANDERE WEGE dorthin sind gemessen und VERWORFEN — sie alle versuchten,
den Konflikt zu GEWICHTEN (Veto, Score, Balken-Term, Diagonal-Begradigung)
statt seine Ursache zu beheben. Nachzulesen im Docstring von
`raumnetz._tuer_lecks`. Wer die Gutschrift wieder ausbaut, holt sich diese
Sackgasse zurück.

Zwei Eigenschaften sind zu halten, und die zweite ist die unbequeme:
  1. Ein DEFIZIT wird ausgeglichen (Balken hat Fläche weggenommen).
  2. Es wird NIE AUFGEBLÄHT: mehr als das Defizit zum Stempel kann die
     Gutschrift nicht sein. Ohne Kappe verschöbe sie Räume, deren Polygon
     ohnehin zu groß ist, erst recht aus der Toleranz.
"""
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "api"))
WURZEL = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")


def run():
    print("UMRISS-GUTSCHRIFT — prüft das Gate dieselbe Fläche wie die Menge?")
    print("=" * 84)
    fehler = []
    quelle = open(os.path.join(WURZEL, "api", "raumnetz.py"),
                  encoding="utf-8").read()

    # 1) Der Parameter existiert und wird im Gate benutzt.
    for muster, was in (
        (r"def raum_regionen\([^)]*ist_f=None", "raum_regionen nimmt ist_f"),
        (r"_kred\s*=\s*max\(0\.0,\s*float\(ist_f\[ridx\]\)\s*-\s*region_flaeche\)",
         "Gutschrift = kreditierte Fläche − Regionfläche"),
        (r"_kred\s*=\s*min\(_kred,\s*max\(0\.0,\s*_sf\s*-\s*poly_flaeche\)\)",
         "KAPPE auf das Defizit zum Stempel"),
        (r"_sr\s*=\s*abs\(poly_flaeche\s*\+\s*_kred\s*-\s*_sf\)\s*/\s*_sf",
         "Gate rechnet mit der Gutschrift"),
    ):
        if re.search(muster, quelle):
            print(f"   {was} ✓")
        else:
            fehler.append(f"{was} — fehlt oder wurde umgebaut. Ohne sie "
                          f"verliert ein Raum seinen Umriss, sobald eine Tür "
                          f"dicht gemacht wird.")

    # 2) Die Aufrufstelle reicht die Fläche wirklich durch — ein Parameter,
    #    den niemand füllt, ist eine Zusage ohne Wirkung.
    nz = open(os.path.join(WURZEL, "api", "nachzeichnen.py"),
              encoding="utf-8").read()
    if re.search(r"ist_f=\[", nz):
        print("   nachzeichnen reicht f_ist an das Gate durch          ✓")
    else:
        fehler.append("nachzeichnen ruft raum_regionen ohne ist_f — der "
                      "Parameter bleibt leer und die Gutschrift wirkungslos.")

    # 3) RECHNET es auch richtig? Die Formel an bekannten Zahlen prüfen.
    #    Genau hier lag der Fehler der ersten Fassung: sie ADDIERTE die
    #    Gutschrift ohne Kappe.
    print("\n   Formel an bekannten Zahlen (Stempel · Polygon · kreditiert):")
    faelle = [
        # (stempel, polygon, region, ist_f, erwartete Abweichung, was)
        (10.0, 8.5, 8.5, 10.0, 0.00, "Balken nahm 1,5 m² — voll ausgeglichen"),
        (10.0, 8.5, 8.5, 9.0, 0.10, "Teil-Ausgleich: 0,5 m² gutgeschrieben, 1,0 offen"),
        (10.0, 12.0, 12.0, 13.0, 0.20, "Polygon ZU GROSS — Kappe verhindert "
                                       "weiteres Aufblähen"),
        (10.0, 9.9, 9.9, None, 0.01, "ohne ist_f: unverändert wie bisher"),
    ]
    for _sf, poly, region, istf, erw, was in faelle:
        kred = 0.0
        if istf:
            kred = max(0.0, float(istf) - region)
        kred = min(kred, max(0.0, _sf - poly))
        sr = abs(poly + kred - _sf) / _sf
        ok = abs(sr - erw) < 0.005
        print(f"      {was:<52}{sr:>6.2f}  {'✓' if ok else '✗ erwartet ' + str(erw)}")
        if not ok:
            fehler.append(f"{was}: Abweichung {sr:.3f} statt {erw:.3f}")

    print("-" * 84)
    if fehler:
        print("FEHLER:")
        for f in fehler:
            print(f"  ✗ {f}")
    else:
        print("WÄCHTER ok: das Umriss-Gate rechnet mit derselben Fläche wie "
              "die Menge,\n           und die Gutschrift gleicht aus, ohne "
              "je aufzublähen.")
    assert not fehler, f"{len(fehler)} Fehler in der Umriss-Gutschrift"


if __name__ == "__main__":
    run()
