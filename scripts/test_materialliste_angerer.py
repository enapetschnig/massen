#!/usr/bin/env python3
"""Regressions-Test: Rohbau-Materialliste gegen die manuelle Polier-Liste
(Bauvorhaben Angerer EFH). Nagelt die erreichte Genauigkeit fest, damit
künftige Änderungen sie nicht still verschlechtern.

Lauf:  python3 scripts/test_materialliste_angerer.py
Exit 0 = alle Toleranzen gehalten, Exit 1 = Regression.

Speist die gemergten Räume + die echte Plan-Legende + gemessene Geometrie
in build_materialliste() und vergleicht Schlüssel-Positionen gegen das
Soll aus der manuellen Materialliste.
"""
import sys
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "api"))

from materialliste import build_materialliste

# ── Eingangsdaten: gemergte Räume (Einreich + Polier), Stand wie in Prod ──
ROOMS = [
    {"name": "Zimmer 1", "flaeche_m2": 10.53, "umfang_m": 13.20, "hoehe_m": 2.95, "bodenbelag": "Fliesen"},
    {"name": "Bad", "flaeche_m2": 8.75, "umfang_m": 11.90, "hoehe_m": 2.70, "bodenbelag": "Fliesen"},
    {"name": "Zimmer 2", "flaeche_m2": 19.66, "umfang_m": 19.55, "hoehe_m": 2.95, "bodenbelag": "Fliesen"},
    {"name": "Flur", "flaeche_m2": 15.84, "umfang_m": 22.57, "hoehe_m": 2.70, "bodenbelag": "Fliesen"},
    {"name": "WC", "flaeche_m2": 1.83, "umfang_m": 5.68, "hoehe_m": 2.95, "bodenbelag": "Fliesen"},
    {"name": "Waschen", "flaeche_m2": 6.20, "umfang_m": 10.98, "hoehe_m": 2.95, "bodenbelag": "Fliesen"},
    {"name": "Wohnraum Küche", "flaeche_m2": 31.12, "umfang_m": 25.95, "hoehe_m": 2.95, "bodenbelag": "Fliesen"},
    {"name": "Terrasse überdacht", "flaeche_m2": 60.74, "umfang_m": 37.46, "hoehe_m": 2.95, "bodenbelag": "Fliesen"},
    {"name": "Parkplatz überdacht", "flaeche_m2": 36.00, "umfang_m": 24.00, "hoehe_m": 2.95, "bodenbelag": "Fliesen"},
    {"name": "Geräte-Abstellraum", "flaeche_m2": 14.82, "umfang_m": 16.67, "hoehe_m": 2.95, "bodenbelag": "Fliesen"},
]

# Echte Plan-Legende (wie legende.parse_legende sie aus dem Angerer-Plan liest)
BAUDATEN = {
    "aussenwand_cm": 50.0, "innenwand_tragend_cm": 25.0, "innenwand_nichttragend_cm": 12.0,
    "decke_cm": 20.0, "bodenplatte_cm": 25.0, "geschosshoehe_m": 2.95,
    "sauberkeitsschicht_cm": 10.0, "konfidenz": 0.95,
}
WAND_VERTEILUNG = {"aussen": {50.0: 73.3, 20.0: 26.7}, "innen": {25.0: 28.6, 12.0: 71.4}}
GEMESSEN = {"aussenumfang_m": 62.0, "bodenplatte_flaeche_m2": 125.0,
            "quelle": "polygon-build+vision-konsistent", "konfidenz": 0.95}
# Fenster (dedupliziert) + Türen
WINDOWS = [
    {"raum": "Zimmer 1", "breite_m": 1.30, "hoehe_m": 1.28},
    {"raum": "Zimmer 2", "breite_m": 1.30, "hoehe_m": 1.28},
    {"raum": "Wohnraum Küche", "breite_m": 1.30, "hoehe_m": 1.28},
    {"raum": "Wohnraum Küche", "breite_m": 0.90, "hoehe_m": 0.88},
    {"raum": "Wohnraum Küche", "breite_m": 0.60, "hoehe_m": 0.60},
    {"raum": "Bad", "breite_m": 0.60, "hoehe_m": 0.58},
    {"raum": "Geräte-Abstellraum", "breite_m": 0.60, "hoehe_m": 0.60},
]
TUEREN = [
    {"raum": "Bad", "breite_m": 0.80, "hoehe_m": 2.05},
    {"raum": "WC", "breite_m": 0.80, "hoehe_m": 2.05},
    {"raum": "WC", "breite_m": 0.80, "hoehe_m": 2.20},
    {"raum": "Zimmer 2", "breite_m": 0.80, "hoehe_m": 2.30},
    {"raum": "Wohnraum Küche", "breite_m": 0.80, "hoehe_m": 2.05},
    {"raum": "Flur", "breite_m": 2.20, "hoehe_m": 2.00},
]

# Soll aus manueller Polier-Materialliste + Toleranz (rel. Abweichung)
# (bauteil, material-stichwort, soll_menge, toleranz_pct)
SOLL = [
    ("Bodenplatte", "EKV", 125, 0.12),
    ("Bodenplatte", "XPS-SF G30 120", 125, 0.12),
    ("Bodenplatte", "AQ 65", 25, 0.15),
    ("Bodenplatte", "PE-Folie", 3, 0.40),
    ("Bodenplatte", "C16/20", 13, 0.25),
    ("Frostschürze", "XPS-SF G30 140", 75, 0.20),
    ("Frostschürze", "Noppenfolie", 75, 0.20),
    ("Frostschürze", "Steckeisen", 125, 0.25),
    ("Mauerwerk EG", "HLZ 50", 48, 0.15),   # erreicht -2% (Verschnitt-Aufschlag) → enger nageln
    ("Mauerwerk EG", "HLZ 12", 7, 0.22),    # erreicht ±0%; 0.22 absorbiert ±1 Paletten-Rundung auf 7
    ("Decke über EG", "Schaltafel", 250, 0.15),
    ("Decke über EG", "EKV", 340, 0.15),
    ("Decke über EG", "ISO-Korb", 48, 0.20),
]


def run():
    ml = build_materialliste(ROOMS, WINDOWS, BAUDATEN, geschoss="EG",
                             tueren=TUEREN, gemessen=GEMESSEN,
                             wand_verteilung=WAND_VERTEILUNG)
    bauteile = ml.get("bauteile") or {}

    def menge(bauteil, stich):
        for p in bauteile.get(bauteil, []):
            if stich.lower() in p["material"].lower():
                return p["menge"]
        return None

    print(f"{'Position':<34}{'App':>9}{'Soll':>8}{'Δ%':>7}  Status")
    print("-" * 70)
    fails = []
    for bauteil, stich, soll, tol in SOLL:
        app = menge(bauteil, stich)
        if app is None:
            print(f"  {bauteil[:14]+'/'+stich[:14]:<32}{'FEHLT':>9}{soll:>8}        ✗ fehlt")
            fails.append((bauteil, stich, "fehlt"))
            continue
        d = (app - soll) / soll
        ok = abs(d) <= tol
        mark = "✓" if ok else "✗ ÜBER TOLERANZ"
        print(f"  {bauteil[:14]+'/'+stich[:16]:<32}{app:>9.1f}{soll:>8}{d*100:>+6.0f}%  {mark}")
        if not ok:
            fails.append((bauteil, stich, f"{d*100:+.0f}% > {tol*100:.0f}%"))

    # ── ABSOLUTE WANDLÄNGEN-PFAD (Genauigkeits-Hebel + manuelle Anpassung) ──
    # HLZ-Fläche = Wandlänge × Höhe, direkt aus dem byte-exakten Overlay bzw.
    # vom Polier manuell gesetzt — statt Hülle × Anteil%. Prüft, dass a) der
    # Pfad greift, b) MANUELLE Korrektur die HLZ50 näher an die Realität bringt.
    print()
    _wl_manuell = {"wand_laengen_m": {"aussen": {"50": 48.0, "25": 4.5},
                                      "innen": {"20": 15.0, "12": 25.5}},
                   "wand_laengen_manuell": True}
    ml_wl = build_materialliste(ROOMS, WINDOWS, BAUDATEN, geschoss="EG",
                                tueren=TUEREN, gemessen=GEMESSEN, override=_wl_manuell)
    bt_wl = ml_wl.get("bauteile") or {}

    def _m(stich):
        for p in bt_wl.get("Mauerwerk EG", []):
            if stich.lower() in p["material"].lower():
                return p
        return None
    wl_fails = []
    _h50 = _m("HLZ 50")
    if not _h50 or abs(_h50["menge"] - 48) / 48 > 0.10:
        wl_fails.append(f"HLZ50 manuell 48m → {_h50['menge'] if _h50 else 'FEHLT'} (Soll ~48)")
    else:
        print(f"  ✓ Wandlängen-Pfad: HLZ50 aus 48m manuell = {_h50['menge']} Pal (Soll 48, "
              f"{(_h50['menge']-48)/48*100:+.0f}%)")
    if not (_h50 and "MANUELL" in (_h50.get("formel") or "")):
        wl_fails.append("HLZ50 trägt kein 'MANUELL gesetzt'-Label")
    else:
        print("  ✓ Wandlängen-Pfad: Herleitung als 'MANUELL gesetzt' belegt")
    # Byte-exakt gemessener Pfad (nicht manuell) muss ebenfalls greifen + Label tragen
    ml_g = build_materialliste(ROOMS, WINDOWS, BAUDATEN, geschoss="EG", tueren=TUEREN,
                               gemessen=GEMESSEN,
                               override={"wand_laengen_m": {"aussen": {"50": 41.5}, "innen": {"12": 25.5}}})
    _g50 = next((p for p in (ml_g.get("bauteile") or {}).get("Mauerwerk EG", []) if "HLZ 50" in p["material"]), None)
    if not (_g50 and "gemessen" in (_g50.get("formel") or "")):
        wl_fails.append("gemessener Pfad trägt kein 'byte-exakt gemessen'-Label")
    else:
        print("  ✓ Wandlängen-Pfad: gemessener (nicht-manueller) Pfad als 'gemessen' belegt")

    print("-" * 70)
    if fails or wl_fails:
        print(f"REGRESSION: {len(fails)+len(wl_fails)} Problem(e):")
        for b, s, why in fails:
            print(f"   - {b}/{s}: {why}")
        for w in wl_fails:
            print(f"   - Wandlängen: {w}")
        return 1
    print(f"OK — alle {len(SOLL)} Positionen in Toleranz + Wandlängen-Pfad (auto/manuell) grün.")
    return 0


if __name__ == "__main__":
    sys.exit(run())
