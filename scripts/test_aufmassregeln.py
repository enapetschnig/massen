"""WÄCHTER Aufmaßregeln: KEINE Menge ohne benannte Norm-Regel.

Das ist die Zusage „Massen laut ÖNORM ermittelt" in prüfbarer Form. Im
Ziel-Workflow ist eine Position ohne hinterlegte Aufmaßregel gesperrt und
mit „Regel fehlt" markiert — hier ist es ein harter Test: jede Position,
die eine Menge ausweist, MUSS eine maschinenlesbare Regel tragen
(Regelwerk + Rechenweg), sonst schlägt der Guard an.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))
import massen_logic as ml   # noqa: E402

# Regelwerke, die wir bewusst anwenden (ÖNORM-Familie der Werkvertragsnormen).
ERWARTETE_NORMEN = {
    "ÖNORM B 2204",   # Maurer-/Putzarbeiten (vormals B 2206/2210/2211)
    "ÖNORM B 2205",   # Erdarbeiten
    "ÖNORM B 2207",   # Fliesen-/Plattenarbeiten
    "ÖNORM B 2232",   # Estricharbeiten
    "ÖNORM B 2210",   # Putzarbeiten (Altbezeichnung, falls direkt zitiert)
    "ÖNORM B 2211",   # Maurerarbeiten (Altbezeichnung)
    "ÖNORM B 2206",   # Mauerarbeiten (Altbezeichnung)
    "ÖNORM B 2221",   # Zimmermeisterarbeiten
    "ÖNORM B 2215",   # Beton-/Stahlbetonarbeiten
    "ÖNORM B 2259",   # Wärmedämm-Verbundsysteme
    "ÖNORM B 2110",   # Werkvertragsnorm (Allgemeines)
}


def _alle_positionen():
    rooms = [
        {"name": "Wohnraum", "flaeche_m2": 31.12, "umfang_m": 25.95, "hoehe_m": 2.5},
        {"name": "Bad", "flaeche_m2": 8.75, "umfang_m": 11.9, "hoehe_m": 2.5},
        {"name": "Zimmer 1", "flaeche_m2": 10.53, "umfang_m": 13.2, "hoehe_m": 2.5},
    ]
    windows = [
        {"code": "F1", "raum": "Wohnraum", "breite_m": 2.4, "hoehe_m": 2.2, "fph_m": 0.0},
        {"code": "F2", "raum": "Bad", "breite_m": 0.6, "hoehe_m": 0.6, "fph_m": 1.4},
    ]
    tueren = [{"code": "T1", "raum": "Bad", "breite_m": 0.8, "hoehe_m": 2.0,
               "_art": "tuer"}]
    baudaten = {"geschosshoehe_m": 2.5, "wandstaerke_cm": 25}
    g = ml.berechne_gewerke(rooms, windows, baudaten, geschoss="EG",
                            tueren=tueren)["gewerke"]
    out = []
    for gk, gv in g.items():
        for p in (gv.get("positionen") or []):
            out.append((gk, p))
    return out


def run():
    positionen = _alle_positionen()
    assert positionen, "keine Positionen berechnet — Testaufbau kaputt"

    nach_art = {}
    ohne, fremde_norm, offen = [], [], []
    mit_stelle = 0
    normen = set()
    for gk, p in positionen:
        if not p.get("endsumme"):
            continue                      # leere Position: nichts zu belegen
        r = p.get("regel")
        if not r:
            ohne.append(f"{gk}/{p.get('posnr')} {p.get('beschreibung')}")
            continue
        art = r.get("art")
        nach_art[art] = nach_art.get(art, 0) + 1
        if art == "norm":
            normen.add(r["norm"])
            assert r["norm"] in ERWARTETE_NORMEN, \
                f"unerwartetes Regelwerk: {gk}/{p.get('posnr')} → {r['norm']}"
            if r.get("stelle"):
                mit_stelle += 1
        elif art == "fremdnorm":
            fremde_norm.append(f"{gk}/{p.get('posnr')} → {r['norm']}")
        elif art == "praxis":
            offen.append(f"{gk}/{p.get('posnr')} {p.get('beschreibung')}")
        # jede Regel nennt ihren Rechenweg
        assert (r.get("formel") or "").strip(), \
            f"Regel ohne Rechenweg: {gk}/{p.get('posnr')}"

    # 1) KEINE Menge ohne irgendeine ausgewiesene Herleitung
    assert not ohne, f"Positionen MIT Menge, aber OHNE jede Regel: {ohne[:5]}"

    # 2) Die MEHRHEIT der Mengen steht auf einer ÖNORM — das ist die Zusage
    n_mengen = sum(nach_art.values())
    assert nach_art.get("norm", 0) >= 0.5 * n_mengen, (
        f"nur {nach_art.get('norm', 0)}/{n_mengen} Positionen auf ÖNORM gestützt "
        f"— die Zusage 'Massen laut ÖNORM' traegt nicht")

    # 3) 'in Anlehnung an' wird als solches ausgewiesen (keine Behauptung
    #    woertlicher Norm-Uebernahme)
    angelehnt = [p for _g, p in positionen
                 if p.get("regel") and p["regel"].get("angelehnt")]
    assert angelehnt, "kein 'in Anlehnung an' erkannt — Parser vermutlich kaputt"

    # 4) FREMDNORMEN sind ein BEFUND: sie duerfen existieren, aber nur
    #    ausdruecklich als solche markiert (art='fremdnorm'), damit sie nicht
    #    als oesterreichische Regel durchgehen. Hier wird ihre Zahl fixiert —
    #    steigt sie, schlaegt der Guard an.
    assert len(fremde_norm) <= 1, (
        f"zu viele Fremdnorm-Bezuege in einer ÖNORM-Anwendung: {fremde_norm}")

    print(f"OK — Aufmaßregeln: {n_mengen} Positionen mit Menge, alle mit "
          f"ausgewiesener Herleitung")
    print(f"   ÖNORM-gestuetzt : {nach_art.get('norm', 0)} "
          f"({len(normen)} Regelwerke, {mit_stelle} mit Fundstelle §)")
    print(f"   Stueckzahl      : {nach_art.get('stueckzahl', 0)} (keine Aufmassregel noetig)")
    print(f"   Fachpraxis/offen: {nach_art.get('praxis', 0)}  {offen[:3]}")
    print(f"   FREMDNORM       : {nach_art.get('fremdnorm', 0)}  {fremde_norm}")
    if fremde_norm:
        print("   ^ BEFUND: deutsche/EU-Norm in einer ÖNORM-Anwendung — "
              "als solche markiert, aber fachlich zu klaeren.")


if __name__ == "__main__":
    run()
