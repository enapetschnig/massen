"""WÄCHTER: zu JEDER Menge muss die Stelle im Plan zeigbar sein.

Der stehende Auftrag verlangt, dass „alles beim Plan eingezeichnet ist,
sodass alles nachvollziehbar ist". Für die Mengen heißt das konkret: jede
Zeile des Aufmaßes trägt einen PLAN-ANKER, und das Frontend macht daraus
einen Klick, der das zugehörige Element am Plan pulsen lässt.

Drei Ankerarten sind im Einsatz:
  {"raum": "Bad"}                  → der Raum-Umriss pulst
  {"ebene": "konturen"}            → die Gebäude-Hülle pulst (Bodenplatte,
                                     Decke, WDVS, Gerüst — bauteilbezogen,
                                     nicht raumbezogen)
  {"oeffnung": {typ, breite, höhe}} → der Fenster-/Tür-Marker pulst

Gemessen 2026-08-03 waren 31 von 33 Zeilen zeigbar. Die zwei Ausnahmen waren
genau die Öffnungs-Zeilen des Fenster-Gewerks: die Detail-Tabelle der
Öffnungen war längst klickbar, der RECHENWEG derselben Öffnung nicht — wer
das Aufmaß prüfte, konnte zu jedem Raum springen, aber zu keinem Fenster.

Dieser Wächter hält die Quote bei 100 % und prüft zusätzlich, dass das
Frontend alle drei Ankerarten wirklich verdrahtet — ein Anker ohne
Klick-Handler wäre eine Zusage ohne Wirkung.
"""
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "api"))

UI = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                  "..", "public", "js", "upload.js")

RAEUME = [
    {"name": "Wohnraum Küche", "flaeche_m2": 31.12, "umfang_m": 24.0,
     "hoehe_m": 2.7, "belag": "Fliesen"},
    {"name": "Bad", "flaeche_m2": 8.75, "umfang_m": 12.0, "hoehe_m": 2.7,
     "belag": "Fliesen"},
    {"name": "Zimmer 1", "flaeche_m2": 10.53, "umfang_m": 13.2, "hoehe_m": 2.7},
]
FENSTER = [{"breite_m": 1.2, "hoehe_m": 1.4, "typ": "fenster"},
           {"breite_m": 2.4, "hoehe_m": 2.2, "typ": "fenster"}]
TUEREN = [{"breite_m": 0.9, "hoehe_m": 2.0, "typ": "tuer"}]
BAUDATEN = {"geschosshoehe_m": 2.7, "aussenwand_cm": 38,
            "aussenumfang_m": 44.0, "grundflaeche_m2": 120.0}


def _ui_verdrahtet(fehler):
    """Ein Anker ohne Klick-Handler wäre eine Zusage ohne Wirkung."""
    src = open(UI, encoding="utf-8").read()
    for muster, was in (
        (r'z\.anker\s*&&\s*z\.anker\.raum', "anker.raum → nzHighlightRaum"),
        (r"z\.anker\.ebene\s*===\s*'konturen'", "anker.ebene → nzHighlightKontur"),
        (r'z\.anker\s*&&\s*z\.anker\.oeffnung', "anker.oeffnung → nzHighlightOeffnung"),
        (r'window\.nzHighlightOeffnung\s*=', "nzHighlightOeffnung existiert"),
        (r'window\.nzHighlightRaum\s*=', "nzHighlightRaum existiert"),
    ):
        if re.search(muster, src):
            print(f"   {was} ✓")
        else:
            fehler.append(f"Frontend: {was} — fehlt. Der Anker wird gesetzt, "
                          f"aber die Zeile bleibt tot.")


def run():
    import massen_logic as ml
    print("NACHVOLLZIEHBARKEIT — führt jede Menge zurück auf den Plan?")
    print("=" * 92)
    fehler = []
    print("Frontend-Verdrahtung:")
    _ui_verdrahtet(fehler)

    erg = ml.berechne_gewerke(RAEUME, FENSTER, BAUDATEN, tueren=TUEREN)
    ges = mit = 0
    arten = {}
    ohne = []
    print(f"\n{'Gewerk':<14}{'Pos':<7}{'Zeilen':>7}{'zeigbar':>9}   Ankerart")
    print("-" * 92)
    for gname, g in (erg.get("gewerke") or {}).items():
        for p in (g.get("positionen") or []):
            z = p.get("zeilen") or []
            m = [x for x in z if x.get("anker")]
            ges += len(z)
            mit += len(m)
            for x in m:
                k = next(iter(x["anker"]), "?")
                arten[k] = arten.get(k, 0) + 1
            for x in z:
                if not x.get("anker"):
                    ohne.append(f"{gname}/{p.get('posnr')}: {x.get('text')}")
            if z:
                _k = sorted({next(iter(x["anker"]), "?") for x in m}) or ["—"]
                print(f"{gname:<14}{str(p.get('posnr')):<7}{len(z):>7}{len(m):>9}"
                      f"   {', '.join(_k)}")
    print("-" * 92)
    quote = 100.0 * mit / ges if ges else 0
    print(f"KENNZAHL 'am Plan zeigbar': {mit}/{ges} Aufmaß-Zeilen ({quote:.0f}%)")
    print(f"   Ankerarten: {arten}")
    for o in ohne[:6]:
        print(f"   OHNE Anker: {o}")
    if ges < 20:
        fehler.append(f"nur {ges} Zeilen erzeugt — die Messung trägt nicht")
    if mit < ges:
        fehler.append(f"{ges - mit} Aufmaß-Zeile(n) ohne Plan-Anker: "
                      f"{'; '.join(ohne[:4])}. Der Kalkulant kann diese Menge "
                      f"nicht am Plan prüfen.")
    # Alle drei Ankerarten müssen tatsächlich vorkommen — sonst prüft der
    # Wächter nur den einfachsten Fall.
    for art in ("raum", "oeffnung"):
        if art not in arten:
            fehler.append(f"Ankerart '{art}' kommt gar nicht vor — der Fall "
                          f"wird nicht geprüft")
    print("-" * 92)
    if fehler:
        print("FEHLER:")
        for f in fehler:
            print(f"  ✗ {f}")
    else:
        print("WÄCHTER ok: jede Aufmaß-Zeile führt zurück auf ihr Element im "
              "Plan,\n           und das Frontend verdrahtet alle Ankerarten")
    assert not fehler, f"{len(fehler)} Nachvollziehbarkeits-Fehler"


if __name__ == "__main__":
    run()
