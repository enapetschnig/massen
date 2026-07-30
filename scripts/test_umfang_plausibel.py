"""WÄCHTER: der Außenumfang muss die Grundfläche überhaupt umschließen können.

Es gibt eine harte geometrische Untergrenze, die kein Bauwerk unterbietet:
der kleinste Umfang, der eine Fläche F umschließt, ist der eines Kreises
(2·√(π·F)); für rechtwinklige Bauten der eines Quadrats (4·√F). Ein
gemeldeter Außenumfang unterhalb dieser Schranke ist nicht "ungenau",
sondern unmöglich — und er geht direkt in Mauerwerk, Fassade, WDVS und
Gerüst.

Warum dieser Wächter existiert: die Planansicht verglich die Summe der als
AUSSEN ERKANNTEN Overlay-Wände gegen den Außenumfang der Mengen und meldete
bei mehr als 8 % Abweichung ein rotes "prüfen!". Am Referenzplan schlug das
gegen die richtige Zahl an:

    Overlay        32,40 m   isoperimetrischer Quotient 0,65  -> unmöglich
    Mengen         45,31 m   isoperimetrischer Quotient 1,27  -> Quadrat
    Grundfläche   128,32 m²  Minimum 4·√128,32 = 45,31 m

Die Overlay-Summe ist eine UNTERGRENZE (sie zählt nur erkannte Wandstücke),
keine zweite Messung. Ein Vergleich, der die Richtung nicht beachtet,
verdächtigt die einzige byte-exakt belegte Zahl — und das kostet mehr
Vertrauen als es schützt.

Dieser Wächter prüft die Regel, die wirklich gilt.
"""
import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))
import massen_logic as ml   # noqa: E402


def _iso_min(f_m2):
    """Kleinster Umfang, der f_m2 umschließen kann (Quadrat-Schranke)."""
    return 4.0 * math.sqrt(f_m2) if f_m2 and f_m2 > 0 else 0.0


# Fälle aus der Wirklichkeit: (Name, Grundfläche, gemeldeter Umfang, soll_ok)
FAELLE = [
    ("Angerer-Referenzplan (Mengen)", 128.32, 45.31, True),
    ("Angerer-Referenzplan (Overlay-Summe)", 128.32, 32.40, False),
    ("langgestreckter Riegel 8×40 m", 320.0, 96.0, True),
    ("Quadrat 20×20 m", 400.0, 80.0, True),
    ("unmöglich: Umfang unter Kreis-Schranke", 100.0, 30.0, False),
    ("knapp darüber (Quadrat + 1 %)", 100.0, 40.4, True),
]


def run():
    print("AUSSENUMFANG — geometrisch möglich?")
    print("=" * 92)
    print(f"{'Fall':42}{'F (m²)':>9}{'U (m)':>9}{'Minimum':>10}"
          f"{'iso':>7}   Urteil")
    print("-" * 92)
    fehler = []
    for name, f, u, soll in FAELLE:
        mn = _iso_min(f)
        iso = (u * u) / (4 * math.pi * f) if f > 0 else 0.0
        ok = u >= mn * 0.98
        urteil = "möglich" if ok else "UNMÖGLICH"
        marke = " " if ok == soll else "  <- WÄCHTER FALSCH"
        if ok != soll:
            fehler.append(f"{name}: erwartet {'möglich' if soll else 'unmöglich'}, "
                          f"bewertet als {urteil}")
        print(f"{name[:41]:42}{f:9.2f}{u:9.2f}{mn:10.2f}{iso:7.2f}   {urteil}{marke}")
    print("-" * 92)

    # Die Pipeline selbst darf keinen unmöglichen Umfang liefern: die
    # isoperimetrische Schätzung ist genau dafür da.
    print("\nSchätzt die Pipeline selbst plausibel?")
    print(f"{'Fläche':>10}{'geschätzter U':>16}{'Minimum':>10}   Urteil")
    print("-" * 92)
    for f in (2.0, 8.75, 25.0, 128.32, 400.0, 3000.0):
        u = ml.isoperimetrischer_umfang(f) if hasattr(
            ml, "isoperimetrischer_umfang") else None
        if u is None:
            import nachzeichnen as nz
            u = nz.isoperimetrischer_umfang(f)
        mn = _iso_min(f)
        ok = u is not None and u >= mn * 0.98
        if not ok:
            fehler.append(f"isoperimetrische Schätzung für {f} m²: {u} m "
                          f"< Minimum {mn:.2f} m")
        print(f"{f:10.2f}{(u if u is not None else 0):16.2f}{mn:10.2f}   "
              f"{'ok' if ok else 'UNTER DEM MINIMUM'}")
    print("-" * 92)

    if fehler:
        print("\nFEHLER:")
        for x in fehler:
            print(f"  ✗ {x}")
    else:
        print(f"\nWÄCHTER ok: {len(FAELLE)} Fälle richtig bewertet, "
              f"6 geschätzte Umfänge über der geometrischen Untergrenze")
    assert not fehler, f"{len(fehler)} Umfangs-Fehler"


if __name__ == "__main__":
    run()
