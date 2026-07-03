#!/usr/bin/env python3
"""Regressionsnetz für api/massen_logic.py (ÖNORM-LV-Gewerke) — Phase 0.

Nagelt das HEUTIGE ÖNORM-Öffnungsverhalten fest, BEVOR die Logik erweitert wird
(Schwelle parametrisieren, Mauerwerk-Abzug, Laibung wandbezogen). Erster Test
dieses Moduls überhaupt.

Kern-Zusagen:
  • Putz zieht NUR Öffnungen > 5 m² ab (+ Laibung), kleinere werden übermessen.
  • Maler zieht > 5 m² ab, OHNE Laibung.
  • Estrich ignoriert Öffnungen komplett.
  • Default-Schwelle ist 4,0 m² (Wächter gegen stille Änderung; ÖNORM B 2204 §5.5.1.3).

Lauf:  python3 scripts/test_massen_logic.py   (Exit 0 = Verhalten festgenagelt)
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "api"))

import massen_logic as ML
from massen_logic import (gewerk_putz, gewerk_maler, gewerk_estrich,
                          gewerk_rohbau, gewerk_beton, berechne_gewerke)

BAUDATEN = {"aussenwand_cm": 50.0, "geschosshoehe_m": 2.70, "decke_cm": 20.0,
            "bodenplatte_cm": 25.0}

# Ein warmer Innenraum mit zwei Fenstern: eines GROSS (>4 m²), eines KLEIN (<4 m²)
ROOMS = [{"name": "Zimmer 1", "flaeche_m2": 30.0, "umfang_m": 22.0, "hoehe_m": 2.70}]
WINDOWS = [
    {"raum": "Zimmer 1", "breite_m": 3.0, "hoehe_m": 2.0, "code": "GROSS"},   # 6,0 m² → Abzug
    {"raum": "Zimmer 1", "breite_m": 1.0, "hoehe_m": 1.0, "code": "KLEIN"},   # 1,0 m² → übermessen
]


def _negative_zeilen(pos):
    return [z for z in pos.zeilen if (z["wert"] or 0) < 0]


def _zeilen_mit(pos, stich):
    return [z for z in pos.zeilen if stich.lower() in (z["text"] or "").lower()]


def run():
    fails = []

    def check(name, cond):
        print(f"  {'✓' if cond else '✗'} {name}")
        if not cond:
            fails.append(name)

    # ── Default-Schwelle festnageln (ÖNORM B 2204 §5.5.1.3: 4,0 m²) ──
    check("Default-Öffnungsschwelle = 4,0 m²", ML.OEFFNUNG_ABZUG_SCHWELLE_M2 == 4.0)
    check("oeffnung_abzug: 6,0 m² wird abgezogen (>4)", ML.oeffnung_abzug(3.0, 2.0) is True)
    check("oeffnung_abzug: 4,4 m² wird abgezogen (>4)", ML.oeffnung_abzug(2.2, 2.0) is True)
    check("oeffnung_abzug: 3,0 m² wird übermessen (<4)", ML.oeffnung_abzug(1.5, 2.0) is False)
    check("oeffnung_abzug: 1,0 m² wird übermessen (<4)", ML.oeffnung_abzug(1.0, 1.0) is False)

    # ── PUTZ (ÖNORM B 2210): nur > 5 m² abziehen + Laibung ──
    putz = gewerk_putz(ROOMS, WINDOWS, BAUDATEN)
    wand = next(p for p in putz if p.posnr == "1.1")
    neg = _negative_zeilen(wand)
    check("Putz: genau EIN Abzug (nur das große Fenster)", len(neg) == 1)
    check("Putz: Abzug = -6,0 m² (3,0×2,0)", neg and abs(neg[0]["wert"] + 6.0) < 0.01)
    # ÖNORM-Audit P3: Leibung ist EIGENE Position 1.1a (B 2204 §5.5.1.3
    # zweigleisig — mit Leibungs-Position wird abgezogen UND separat verrechnet)
    laib = next((p for p in putz if p.posnr == "1.1a"), None)
    check("Putz: Leibungs-Position 1.1a vorhanden (großes Fenster)",
          laib is not None and len(laib.zeilen) == 1 and laib.endsumme > 0)
    check("Putz: kleines Fenster erzeugt KEINEN Abzug (übermessen)",
          not any("klein" in (z["text"] or "").lower() for z in neg))
    # Brutto-Wand 22×2,70=59,4 − 6,0 = 53,4 (Laibung separat in 1.1a)
    check("Putz: Wand-Endsumme = Brutto − Abzug (Leibung separat)",
          abs(wand.endsumme - 53.4) < 0.1)

    # ── MALER: > 4 m² abziehen, MIT Laibung (ÖNORM-konsistent zum Putz, Phase 1) ──
    maler = gewerk_maler(ROOMS, WINDOWS, BAUDATEN)
    mwand = next(p for p in maler if p.posnr == "1.1")
    check("Maler: genau EIN Abzug (großes Fenster)", len(_negative_zeilen(mwand)) == 1)
    check("Maler: Laibung-Zeile vorhanden (konsistent mit Putz)", len(_zeilen_mit(mwand, "laibung")) == 1)

    # ── ESTRICH (ÖNORM B 2232): Öffnungen irrelevant ──
    estrich = gewerk_estrich(ROOMS, WINDOWS, BAUDATEN)
    eflaeche = next(p for p in estrich if p.posnr == "1.1")
    check("Estrich: Fläche = Raumfläche 30,0 (kein Öffnungseinfluss)",
          abs(eflaeche.endsumme - 30.0) < 0.01)
    check("Estrich: keine negativen Zeilen", len(_negative_zeilen(eflaeche)) == 0)

    # ── PHASE 1: zentraler Helfer oeffnung_netto (ÖNORM B 2204) ──
    n_klein = ML.oeffnung_netto(1.5, 2.0, wand_cm=50, schwelle=4.0)   # 3,0 m²
    check("netto: 3,0 m² übermessen → kein Abzug", n_klein["uebermessen"] and n_klein["abzug"] == 0)
    check("netto: übermessen → keine Laibung", n_klein["laibung"] == 0)
    n_aw = ML.oeffnung_netto(3.0, 2.0, wand_cm=50, schwelle=4.0)      # 6,0 m², Außenwand
    n_iw = ML.oeffnung_netto(3.0, 2.0, wand_cm=12, schwelle=4.0)      # gleiche Öffnung, dünne Innenwand
    check("netto: >Schwelle → Abzug = Fläche", abs(n_aw["abzug"] - 6.0) < 0.01)
    check("netto: dickere Wand → tiefere Laibung", n_aw["laibung"] > n_iw["laibung"] > 0)
    n_ohne = ML.oeffnung_netto(3.0, 2.0, wand_cm=50, fph_m=0.0, schwelle=4.0)
    n_mit = ML.oeffnung_netto(3.0, 2.0, wand_cm=50, fph_m=0.90, schwelle=4.0)
    check("netto: fph>0,15 → Sohlbank + größere Laibung",
          n_mit["sohlbank"] and n_mit["laibung"] > n_ohne["laibung"])

    # ── Wandstärke je Öffnung: wand_typ schlägt Art-Fallback ──
    check("_wand_cm: Fenster (Fallback) → Außenwand 50",
          ML._wand_cm_of({"_art": "fenster"}, BAUDATEN) == 50.0)
    check("_wand_cm: Tür (Fallback) → Innenwand 25",
          ML._wand_cm_of({"_art": "tuer"}, BAUDATEN) == 25.0)
    check("_wand_cm: wand_typ='IW' schlägt Art",
          ML._wand_cm_of({"_art": "fenster", "wand_typ": "IW"}, BAUDATEN) == 25.0)

    # ── Türen werden jetzt durchgereicht + nach ÖNORM behandelt ──
    putz_gt = gewerk_putz(ROOMS, [], BAUDATEN,
                          tueren=[{"raum": "Zimmer 1", "breite_m": 2.5, "hoehe_m": 2.0, "code": "T-GROSS"}])  # 5,0 m²
    check("Türen: große Tür (5 m²) wird abgezogen",
          len(_negative_zeilen(next(p for p in putz_gt if p.posnr == "1.1"))) == 1)
    putz_kt = gewerk_putz(ROOMS, [], BAUDATEN,
                          tueren=[{"raum": "Zimmer 1", "breite_m": 0.9, "hoehe_m": 2.1, "code": "T-KLEIN"}])  # 1,89 m²
    check("Türen: normale Tür (1,9 m²) wird übermessen",
          len(_negative_zeilen(next(p for p in putz_kt if p.posnr == "1.1"))) == 0)

    # ── Schwelle je Gewerk überschreibbar (z.B. strenges Mauerwerks-Ausmaß 0,5) ──
    check("Schwelle: Default 4,0", ML._schwelle_fuer(BAUDATEN) == 4.0)
    check("Schwelle: global überschrieben", ML._schwelle_fuer({"oeffnung_schwelle": 0.5}) == 0.5)
    check("Schwelle: je Gewerk überschrieben",
          ML._schwelle_fuer({"oeffnung_schwelle_putz": 2.5}, "putz") == 2.5)

    # ── PHASE 2: Mauerwerk-Netto + gemeinsame Basis (Decke/Bodenplatte) ──
    basis = dict(BAUDATEN, _basis_aussenwand_flaeche_m2=180.0,
                 _basis_decke_m2=240.0, _basis_bodenplatte_m2=125.0)
    roh = gewerk_rohbau(ROOMS, WINDOWS, basis)   # WINDOWS: 6,0 m² (Abzug) + 1,0 m² (übermessen)
    mw = next((p for p in roh if p.posnr == "1.0"), None)
    check("Rohbau: Mauerwerk-Netto-Position (1.0) bei vorhandener Basis", mw is not None)
    check("Rohbau: Außenwand netto = 180 − 6 (große Öffnung) = 174",
          mw and abs(mw.endsumme - 174.0) < 0.1)
    decke = next(p for p in roh if p.posnr == "1.2")
    check("Rohbau: Decke = gemeinsame Basis 240 × 0,20",
          abs(decke.endsumme - 240.0 * basis["decke_cm"] / 100.0) < 0.01)
    bopl = next(p for p in roh if p.posnr == "1.3")
    check("Rohbau: Bodenplatte = gemeinsame Basis 125 × 0,25",
          abs(bopl.endsumme - 125.0 * basis["bodenplatte_cm"] / 100.0) < 0.01)
    roh0 = gewerk_rohbau(ROOMS, WINDOWS, BAUDATEN)
    check("Rohbau: ohne Basis KEINE Mauerwerk-Netto-Position (keine Wand-Geometrie)",
          not any(p.posnr == "1.0" for p in roh0))

    # ── PHASE 2: Beton-Gewerk (Stützen mit Faktor wie Bestell-Liste + Kamin) ──
    beton = gewerk_beton(ROOMS, WINDOWS, dict(BAUDATEN, anzahl_saeulen=4, anzahl_kamine=1))
    saeule = next(p for p in beton if "Stützen" in p.beschreibung)
    check("Beton: 4 Stützen × 0,5 = 2,0 m³ (Faktor wie Bestell-Liste)",
          abs(saeule.endsumme - 2.0) < 0.01)
    check("Beton: Kamin als Stk-Position", any("Kamin" in p.beschreibung for p in beton))
    check("Beton: leer wenn nichts erkannt", gewerk_beton(ROOMS, WINDOWS, BAUDATEN) == [])

    # ── berechne_gewerke: Durchreich-Keys + leeres Beton ausgelassen ──
    res = berechne_gewerke(ROOMS, WINDOWS, basis)
    check("berechne_gewerke: _basis_* erreichen das Rohbau-Gewerk (Pos 1.0 da)",
          any(p["posnr"] == "1.0" for p in res["gewerke"]["rohbau"]["positionen"]))
    check("berechne_gewerke: leeres Beton-Gewerk wird ausgelassen",
          "beton" not in res["gewerke"])
    res2 = berechne_gewerke(ROOMS, WINDOWS, dict(BAUDATEN, anzahl_saeulen=3))
    check("berechne_gewerke: Beton-Gewerk erscheint mit Säulen",
          "beton" in res2["gewerke"] and res2["gewerke"]["beton"]["positionen"])

    print("-" * 62)
    if fails:
        print(f"FEHLER: {len(fails)} Zusage(n) verletzt: {fails}")
        return 1
    print("OK — ÖNORM-Öffnungslogik (B 2204): >4m²→Abzug+Laibung wandbezogen, ≤4m²→übermessen, "
          "Türen durchgereicht, Schwelle je Gewerk.")
    return 0


if __name__ == "__main__":
    sys.exit(run())
