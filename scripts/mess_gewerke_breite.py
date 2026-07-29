"""MESSUNG Gewerke-Breite: für WELCHE Bereiche der Baubranche rechnet die App?

„Für mehrere Bereiche der Baubranche" ist eine Zusage, die man zeigen muss —
mit Leistungsgruppe, Einheit und einer echten Menge je Gewerk. Ein Betrieb
sieht daran, ob SEIN Gewerk dabei ist.

Gerechnet an einem realistischen Wohnhaus-Satz (beheizte Räume, Nassraum,
Fenster, Tür, Keller), damit möglichst viele Gewerke tatsächlich anspringen.
Leere Gewerke werden bewusst ausgelassen — die App erfindet keine Position,
für die im Plan die Grundlage fehlt.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))
import massen_logic as ml   # noqa: E402

ROOMS = [
    {"name": "Wohnraum", "flaeche_m2": 31.12, "umfang_m": 25.95, "hoehe_m": 2.5},
    {"name": "Zimmer 1", "flaeche_m2": 14.20, "umfang_m": 15.40, "hoehe_m": 2.5},
    {"name": "Zimmer 2", "flaeche_m2": 12.80, "umfang_m": 14.60, "hoehe_m": 2.5},
    {"name": "Bad", "flaeche_m2": 8.75, "umfang_m": 11.90, "hoehe_m": 2.5},
    {"name": "WC", "flaeche_m2": 2.10, "umfang_m": 6.20, "hoehe_m": 2.5},
    {"name": "Flur", "flaeche_m2": 9.60, "umfang_m": 14.80, "hoehe_m": 2.5},
    # unbeheizte Bauteile: loesen Fassade/Geruest aus, zaehlen aber nicht
    # in die beheizten Innenflaechen (Kategorie-Trennung)
    {"name": "Terrasse überdacht", "flaeche_m2": 18.40, "umfang_m": 17.20},
    {"name": "Geräte-Abstellraum", "flaeche_m2": 14.82, "umfang_m": 16.67,
     "hoehe_m": 2.5},
]
FENSTER = [
    {"code": "F1", "raum": "Wohnraum", "breite_m": 2.40, "hoehe_m": 2.20, "fph_m": 0.0},
    {"code": "F2", "raum": "Zimmer 1", "breite_m": 1.20, "hoehe_m": 1.40, "fph_m": 0.9},
    {"code": "F3", "raum": "Bad", "breite_m": 0.60, "hoehe_m": 0.60, "fph_m": 1.4},
]
TUEREN = [
    {"code": "T1", "raum": "Bad", "breite_m": 0.80, "hoehe_m": 2.00, "_art": "tuer"},
    {"code": "T2", "raum": "WC", "breite_m": 0.70, "hoehe_m": 2.00, "_art": "tuer"},
]
# Baudaten wie sie die Pipeline aus einem echten Plan liest (Werte aus dem
# Angerer-Showcase uebernommen) — inkl. Saeulen/Kaminen, die den Betonbau
# und die Fassaden-Gewerke ueberhaupt erst ausloesen.
BAUDATEN = {
    "geschosshoehe_m": 3.0, "aussenwand_cm": 50.0,
    "innenwand_tragend_cm": 25.0, "innenwand_nichttragend_cm": 12.0,
    "decke_cm": 25.0, "bodenplatte_cm": 25.0, "hat_keller": True,
    "anzahl_saeulen": 2, "anzahl_kamine": 1, "anzahl_tueren_innen": 8,
    "tuer_breite_m": 0.9, "tuer_hoehe_m": 2.1,
    "wandmaterial": "Hochlochziegel",
}

# Gewerk -> in welchem Bereich der Baubranche es gebraucht wird
BEREICH = {
    "rohbau": "Baumeister / Maurer",
    "beton": "Baumeister / Stahlbetonbau",
    "erdarbeiten": "Erdbau / Baumeister",
    "putz": "Verputzer",
    "estrich": "Estrichleger / Bodenleger",
    "maler": "Maler / Anstreicher",
    "fliesen": "Fliesenleger",
    "fenster": "Fensterbau / Bauelemente",
    "daemmung": "Fassadenbau / WDVS",
    "geruest": "Gerüstbau",
}


def run():
    g = ml.berechne_gewerke(ROOMS, FENSTER, BAUDATEN, geschoss="EG",
                            tueren=TUEREN)["gewerke"]
    print(f"{'Bereich der Baubranche':<30}{'LG':<5}{'Pos.':>5}{'Einheiten':<14}  Beispiel-Position")
    print("-" * 104)
    aktiv = []
    for key in sorted(g, key=lambda k: str((g[k] or {}).get("lg") or "")):
        gv = g[key] or {}
        pos = [p for p in (gv.get("positionen") or []) if p.get("endsumme")]
        if not pos:
            continue
        aktiv.append(key)
        einh = sorted({p.get("einheit") or "?" for p in pos})
        gross = max(pos, key=lambda p: abs(p.get("endsumme") or 0))
        print(f"{BEREICH.get(key, key):<30}{str(gv.get('lg') or '?'):<5}{len(pos):>5}"
              f"  {','.join(einh):<12}  {str(gross.get('beschreibung'))[:34]} = "
              f"{gross['endsumme']:.2f} {gross.get('einheit')}")
    print("-" * 104)
    print(f"{len(aktiv)} Gewerke liefern Mengen — je mit ÖNORM-Leistungsgruppe")

    leer = [k for k in g if k not in aktiv]
    if leer:
        print(f"ausgelassen (keine Grundlage im Plan): {', '.join(sorted(leer))}")
    print("\nDas ist die Breite: ein Baumeister, ein Verputzer, ein Estrichleger")
    print("und ein Fliesenleger bekommen aus DEMSELBEN Plan jeweils ihr eigenes")
    print("Aufmaß — statt einer Rohbau-Schablone für alle.")

    # ZUSAGEN
    assert len(aktiv) >= 8, f"nur {len(aktiv)} Gewerke aktiv — Breite verloren"
    # jedes aktive Gewerk nennt seine Leistungsgruppe (LV-Anschluss)
    ohne_lg = [k for k in aktiv if not (g[k] or {}).get("lg")]
    assert not ohne_lg, f"Gewerke ohne Leistungsgruppe: {ohne_lg}"
    # mindestens drei verschiedene Einheiten (Flaeche, Laenge, Volumen/Stueck)
    alle_einh = {p.get("einheit") for k in aktiv
                 for p in (g[k].get("positionen") or []) if p.get("endsumme")}
    assert len(alle_einh) >= 3, f"nur Einheiten {alle_einh} — zu schmal"
    print(f"\nWÄCHTER ok: {len(aktiv)} Gewerke, alle mit LG, "
          f"{len(alle_einh)} Einheiten ({', '.join(sorted(x for x in alle_einh if x))})")


if __name__ == "__main__":
    run()
