"""WÄCHTER Eigene Positionen: Betriebs-Position + Pflicht-Aufmaßregel.

Im Ziel-Workflow hinterlegt der Betrieb SEINE Leistungspositionen und
verknüpft jede mit einer Aufmaßregel — ohne Regel ist die Position gesperrt.
Dieser Guard prüft, dass die Mechanik trägt: gültige Regel → Menge mit
vollem Rechenweg und Plan-Ankern; ungültige Regel → gar nichts.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))
import massen_logic as ml   # noqa: E402

ROOMS = [
    {"name": "Wohnraum", "flaeche_m2": 31.12, "umfang_m": 25.95, "hoehe_m": 2.5},
    {"name": "Bad", "flaeche_m2": 8.75, "umfang_m": 11.9, "hoehe_m": 2.5},
    {"name": "Zimmer 1", "flaeche_m2": 10.53, "umfang_m": 13.2, "hoehe_m": 2.5},
]
FENSTER = [{"code": "F1", "raum": "Wohnraum", "breite_m": 2.4, "hoehe_m": 2.2,
            "fph_m": 0.0}]
TUEREN = [{"code": "T1", "raum": "Bad", "breite_m": 0.8, "hoehe_m": 2.0,
           "_art": "tuer"}]
BAUDATEN = {"geschosshoehe_m": 2.5, "wandstaerke_cm": 25}


def run():
    # 1) OHNE gültige Regel gibt es KEINE Menge („Regel fehlt" = gesperrt)
    assert ml.eigene_position(None, "1.1", "Test", ROOMS) is None
    assert ml.eigene_position("phantasie", "1.1", "Test", ROOMS) is None

    # 2) Katalog ist vollständig beschrieben — jede Regel nennt Einheit,
    #    Regelwerk und Rechenweg (sonst ist sie nicht nachvollziehbar)
    assert ml.AUFMASS_REGELN, "Regel-Katalog leer"
    for k, r in ml.AUFMASS_REGELN.items():
        for feld in ("name", "einheit", "norm", "formel"):
            assert (r.get(feld) or "").strip(), f"Regel {k}: {feld} fehlt"
        assert "ÖNORM" in r["norm"], f"Regel {k}: kein ÖNORM-Bezug"

    # 3) Bodenfläche = Σ F, und JEDE Zeile ist am Plan verankert
    p = ml.eigene_position("boden", "01.01", "Estrich EPS", ROOMS,
                           baudaten=BAUDATEN)
    assert p is not None and p.einheit == "m²"
    assert abs(p.endsumme - (31.12 + 8.75 + 10.53)) < 0.01, p.endsumme
    assert all(z.get("anker", {}).get("raum") for z in p.zeilen), \
        "Zeile ohne Plan-Anker — nicht nachvollziehbar"
    assert p.regel and p.regel["art"] == "norm", "Regel nicht maschinenlesbar"

    # 4) RAUM-FILTER: nur die gewählten Räume zählen (= Zuordnungs-Schritt)
    p2 = ml.eigene_position("boden", "01.02", "Nur Bad", ROOMS,
                            raum_filter=["Bad"], baudaten=BAUDATEN)
    assert abs(p2.endsumme - 8.75) < 0.01, p2.endsumme

    # 5) wand_netto zieht Öffnungen ab, wand_brutto nicht — und der
    #    Unterschied ist GENAU der Abzug (keine stille Doppelrechnung)
    br = ml.eigene_position("wand_brutto", "02.01", "Wand brutto", ROOMS,
                            FENSTER, TUEREN, BAUDATEN)
    ne = ml.eigene_position("wand_netto", "02.02", "Wand netto", ROOMS,
                            FENSTER, TUEREN, BAUDATEN)
    assert br and ne
    assert ne.endsumme < br.endsumme, "netto muss unter brutto liegen"
    abzug = sum(-z["wert"] for z in ne.zeilen if z["wert"] < 0)
    assert abs((br.endsumme - ne.endsumme) - abzug) < 0.02, \
        "Differenz brutto/netto ist nicht exakt der ausgewiesene Abzug"

    # 6) SOCKEL zieht die Türbreiten ab — raumscharf
    so = ml.eigene_position("sockel", "03.01", "Sockelleiste", ROOMS,
                            FENSTER, TUEREN, BAUDATEN)
    u_ges = 25.95 + 11.9 + 13.2
    assert abs(so.endsumme - (u_ges - 0.8)) < 0.02, so.endsumme

    # 7) VERSCHNITT ist eine EIGENE, sichtbare Zeile — nie still eingerechnet
    v = ml.eigene_position("boden", "01.03", "Fliesen +5%", ROOMS,
                           baudaten=BAUDATEN, verschnitt_pct=5)
    vz = [z for z in v.zeilen if "Verschnitt" in (z.get("text") or "")]
    assert len(vz) == 1, "Verschnitt muss als eigene Zeile erscheinen"
    basis = 31.12 + 8.75 + 10.53
    assert abs(v.endsumme - basis * 1.05) < 0.02, v.endsumme

    print(f"OK — Eigene Positionen: {len(ml.AUFMASS_REGELN)} Aufmaßregeln "
          f"({', '.join(sorted(ml.AUFMASS_REGELN))}), alle mit ÖNORM-Bezug · "
          f"ohne Regel keine Menge · Raum-Filter greift · brutto−netto = "
          f"ausgewiesener Abzug · Verschnitt sichtbar · jede Zeile plan-verankert")


if __name__ == "__main__":
    run()
