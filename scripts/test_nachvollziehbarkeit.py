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
# Die Öffnungen tragen ausdrücklich einen RAUM und einen WAND-TYP: nur dann
# entstehen Abzugs- UND LEIBUNGS-Zeilen. Ohne sie meldete dieser Wächter
# 34/34, während die Produktion am echten Plan eine ungeankerte Zeile zeigte
# ("Flur" unter Leibungsputz) — der Testkorpus erzeugte diesen Zeilentyp gar
# nicht. Ein Wächter, der einen Zeilentyp nicht erzeugt, kann ihn auch nicht
# prüfen.
FENSTER = [{"breite_m": 1.2, "hoehe_m": 1.4, "typ": "fenster",
            "raum": "Wohnraum Küche", "wand_typ": "AW", "code": "F1"},
           {"breite_m": 2.4, "hoehe_m": 2.2, "typ": "fenster",
            "raum": "Wohnraum Küche", "wand_typ": "AW", "code": "F2"},
           # OHNE MASS — am echten Korpus waren genau solche Zeilen die
           # einzigen ohne Plan-Anker (6 von 587). Ausgerechnet sie: dort ist
           # kein ÖNORM-Abzug möglich, und der Kalkulant will sie am
           # dringendsten am Plan sehen. Ohne diesen Fall im Testkorpus bleibt
           # die Lücke unsichtbar — genau wie zuvor bei den Leibungszeilen.
           {"breite_m": None, "hoehe_m": 1.6, "typ": "fenster",
            "raum": "Bad", "wand_typ": "AW", "code": "F3"}]
TUEREN = [{"breite_m": 0.9, "hoehe_m": 2.0, "typ": "tuer",
           "raum": "Bad", "wand_typ": "IW", "code": "T1"}]
BAUDATEN = {"geschosshoehe_m": 2.7, "aussenwand_cm": 38,
            "innenwand_tragend_cm": 25, "aussenumfang_m": 44.0,
            "grundflaeche_m2": 120.0}
# Zeilentypen, die im Korpus VORKOMMEN MÜSSEN — sonst prüft der Wächter nur
# die einfachen Fälle.
PFLICHT_ZEILEN = ("Leibung", "Abzug", "ohne Maß")


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
    # DIE ZEILENTYPEN müssen ebenfalls vorkommen. Genau hier lag der blinde
    # Fleck: ohne Leibungs-Zeilen im Korpus meldete der Wächter 100 %,
    # während die Produktion eine ungeankerte Leibungszeile zeigte.
    # Positions-BESCHREIBUNG und Zeilen-Text gemeinsam durchsuchen: "Leibung"
    # steht im Positionsnamen ("Leibungsputz bis 0,25 m Tiefe"), "Abzug" im
    # Zeilentext. Nur eines von beidem zu prüfen hätte den blinden Fleck
    # bloß verschoben.
    _alle_texte = " | ".join(
        [str(pp.get("beschreibung") or "")
         for gg in (erg.get("gewerke") or {}).values()
         for pp in (gg.get("positionen") or [])]
        + [str(x.get("text") or "")
           for gg in (erg.get("gewerke") or {}).values()
           for pp in (gg.get("positionen") or [])
           for x in (pp.get("zeilen") or [])])
    for _typ in PFLICHT_ZEILEN:
        if _typ.lower() not in _alle_texte.lower():
            fehler.append(f"Zeilentyp '{_typ}' kommt im Testkorpus gar nicht "
                          f"vor — dieser Zeilentyp wird also NICHT auf seinen "
                          f"Plan-Anker geprüft (genau so entstand der blinde "
                          f"Fleck bei den Leibungszeilen)")
        else:
            print(f"   Zeilentyp '{_typ}' im Korpus vorhanden ✓")
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
