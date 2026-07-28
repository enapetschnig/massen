"""WÄCHTER Aufmaß-Kreuztabelle (Räume × Positionen) — die Kontrollansicht.

Prüft die Invarianten der Matrix, mit der ein Polier auf einen Blick sieht,
welcher Raum welche Position in welcher Menge trägt (Vorbild: Übersicht-Tab
im Aufmaß-Workflow). Gebaut aus den Plan-Ankern der Rechenzeilen — kein
zusätzliches Erkennen, darum hart testbar.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))
import massen_logic as ml   # noqa: E402


def _gewerke():
    """Echte Berechnung auf einem kleinen, vollständigen Raum-Satz."""
    rooms = [
        {"name": "Zimmer 1", "flaeche_m2": 10.53, "umfang_m": 13.2, "hoehe_m": 2.5},
        {"name": "Bad", "flaeche_m2": 8.75, "umfang_m": 11.9, "hoehe_m": 2.5},
        {"name": "Wohnraum", "flaeche_m2": 31.12, "umfang_m": 25.95, "hoehe_m": 2.5},
    ]
    windows = [
        {"code": "F1", "raum": "Zimmer 1", "breite_m": 1.2, "hoehe_m": 1.4,
         "fph_m": 0.9},
        {"code": "F2", "raum": "Wohnraum", "breite_m": 2.4, "hoehe_m": 2.2,
         "fph_m": 0.0},
    ]
    baudaten = {"geschosshoehe_m": 2.5, "wandstaerke_cm": 25}
    # berechne_gewerke liefert {baudaten, gewerke} — die Matrix will die
    # innere Gewerke-Ebene (identisch mit dem, was die API ausliefert).
    return ml.berechne_gewerke(rooms, windows, baudaten, geschoss="EG")["gewerke"]


def run():
    gewerke = _gewerke()
    rooms = [
        {"name": "Zimmer 1", "flaeche_m2": 10.53, "umfang_m": 13.2},
        {"name": "Bad", "flaeche_m2": 8.75, "umfang_m": 11.9},
        {"name": "Wohnraum", "flaeche_m2": 31.12, "umfang_m": 25.95},
    ]
    m = ml.aufmass_matrix(gewerke, rooms)

    # 1) Struktur steht
    assert m["positionen"], "keine Positions-Spalten"
    assert m["raeume"], "keine Raum-Zeilen"

    # 2) Jede Spalte trägt ihre AUFMASSREGEL im Klartext (Nachvollziehbarkeit:
    #    keine Menge ohne benannte Regel — das ist der Kern des Beweis-Gedankens)
    ohne_regel = [p for p in m["positionen"] if not (p.get("regel") or "").strip()]
    assert not ohne_regel, f"Positionen ohne Aufmaßregel: {ohne_regel[:3]}"

    # 3) Spalten-Schlüssel sind eindeutig (posnr '1.1' existiert in MEHREREN
    #    Gewerken — ohne Gewerk-Präfix würden Mengen kollidieren)
    keys = [p["key"] for p in m["positionen"]]
    assert len(keys) == len(set(keys)), "Spalten-Schlüssel nicht eindeutig"

    # 4) Die drei Räume tauchen als Zeilen auf und tragen Mengen
    namen = {r["raum"] for r in m["raeume"]}
    for n in ("Zimmer 1", "Bad", "Wohnraum"):
        assert n in namen, f"Raum {n} fehlt in der Matrix"
    assert sum(r["n_positionen"] for r in m["raeume"]) > 0, "keine Zelle gefüllt"

    # 5) ABZÜGE sind raumscharf: der Öffnungs-Abzug mindert GENAU den Raum,
    #    in dem die Öffnung liegt — nicht die Nachbarn. Wichtig: die
    #    Putz-Schwelle ist 4,0 m² (ÖNORM B 2204) — kleinere Öffnungen werden
    #    ÜBERMESSEN und dürfen NICHT abgezogen werden. Darum prüft der Test
    #    beide Seiten: das 1,68-m²-Fenster (Zimmer 1) bleibt übermessen,
    #    das 5,28-m²-Fenster (Wohnraum) wird abgezogen.
    putz11 = next((p["key"] for p in m["positionen"]
                   if p["gewerk"] == "putz" and p["posnr"] == "1.1"), None)
    assert putz11, "Putz-Position 1.1 fehlt"
    z1 = next(r for r in m["raeume"] if r["raum"] == "Zimmer 1")
    bad = next(r for r in m["raeume"] if r["raum"] == "Bad")
    wohn = next(r for r in m["raeume"] if r["raum"] == "Wohnraum")
    assert abs(bad["mengen"][putz11] - 11.9 * 2.5) < 0.05, \
        f"Bad ohne Öffnung muss U×H sein, ist {bad['mengen'][putz11]}"
    assert abs(z1["mengen"][putz11] - 13.2 * 2.5) < 0.05, \
        "1,68-m²-Fenster liegt unter der 4-m²-Schwelle → muss ÜBERMESSEN bleiben"
    assert wohn["mengen"][putz11] < 25.95 * 2.5 - 1.0, \
        "5,28-m²-Fenster muss den Wohnraum mindern (Abzug raumscharf)"

    # 6) Deckungsgrad ist ehrlich: Anteil der Menge mit Raum-Beleg, 0..100
    assert 0.0 <= m["deckung_pct"] <= 100.0
    assert m["deckung_pct"] > 40.0, \
        f"zu wenig raumscharf belegt: {m['deckung_pct']}%"

    # 7) Nicht verankerte Mengen werden AUSGEWIESEN statt verschwiegen
    for o in m["ohne_anker"]:
        assert "wert" in o and "beschreibung" in o

    print(f"OK — Aufmaß-Matrix: {len(m['raeume'])} Räume × "
          f"{len(m['positionen'])} Positionen, "
          f"{m['deckung_pct']}% raumscharf belegt, "
          f"{len(m['ohne_anker'])} Zeilen gebäudeweit (ausgewiesen), "
          f"Abzüge raumscharf ✓, jede Position mit Aufmaßregel ✓")


if __name__ == "__main__":
    run()
