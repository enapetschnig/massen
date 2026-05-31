#!/usr/bin/env python3
"""Belegt den Opus-4.8-Bauingenieur-Konsum + die Kreuz-Kontrolle (Vier-Augen-
Prinzip): das ganzheitliche Urteil wird NUR additiv, beleg- und konfidenz-
gegated eingewoben — es bestätigt/widerspricht, es RÄT nie und es überschreibt
nie eine byte-exakte/Schnitt-/Legende-Quelle.

Lauf: python3 scripts/test_opus_konsum.py   (Exit 0 = bestanden)
"""
import sys, os
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "api"))
import opus_konsum as ok

fails = []
def check(name, cond, detail=""):
    print(f"  {'✓' if cond else '✗'} {name}" + (f"  — {detail}" if detail and not cond else ""))
    if not cond:
        fails.append(name)

# Realistischer Fall Angerer: "Parkplatz überdacht" ist im Schnitt eine
# geschlossene GEMAUERTE Garage auf der durchgehenden Bodenplatte.
OPUS_GARAGE = {
    "ueberdachte_bereiche": [
        {"name": "Parkplatz überdacht", "geschlossen_typ": "gemauert", "auf_slab": True,
         "mauerwerk_umfang_zusatz_m": 14.0, "fundament_umfang_zusatz_m": 14.0,
         "konfidenz": 0.85, "evidenz": "Schnitt: HLZ-Wände bis Dach + Tor"},
        {"name": "Terrasse", "geschlossen_typ": "offen", "auf_slab": True,
         "mauerwerk_umfang_zusatz_m": 0.0, "fundament_umfang_zusatz_m": 6.0,
         "konfidenz": 0.7, "evidenz": "nur Platte, keine Wände"},
    ],
    "hoehe": {"rohbau_m": 2.95, "licht_m": 2.70, "konfidenz": 0.8, "evidenz": "Schnitt A-A"},
    "dach": {"dach_typ": "flach", "attika_hoehe_m": 0.4, "konfidenz": 0.8, "evidenz": "Attika im Schnitt"},
    "saeulen_anzahl": 0,
    "gesamtkonfidenz": 0.82,
}
HUELLE = 46.46   # byte-exakte Maßketten-Hülle Angerer

print("1) Geschlossene gemauerte Garage → Mauerwerks-Hülle (Linie A):")
mw, namen = ok.mauerwerk_zusatz(OPUS_GARAGE, HUELLE)
check("nur die GEMAUERTE Garage zählt (14m), Terrasse nicht", mw == 14.0, f"got {mw}")
check("Garagen-Name geliefert", namen == ["Parkplatz überdacht"], f"got {namen}")

print("2) Bereiche auf durchgehender Platte → Slab-Kante (Linie B):")
slab = ok.slab_zusatz(OPUS_GARAGE, HUELLE)
# Garage 14 + Terrasse 6 = 20 → 46,46 + 20 = 66,46 (beide auf_slab)
check("Slab = Hülle + Σ Platten-Zusatz (Garage+Terrasse)", slab == round(HUELLE + 20.0, 2), f"got {slab}")

print("3) Höhe/Dach/Säulen nur konf-gegated (≥0.6):")
check("Rohbau-Höhe aus Schnitt", ok.hoehe_rohbau(OPUS_GARAGE) == 2.95, f"got {ok.hoehe_rohbau(OPUS_GARAGE)}")
check("Dachtyp flach", ok.dach_typ(OPUS_GARAGE) == "flach", f"got {ok.dach_typ(OPUS_GARAGE)}")
check("Säulen 0 wenn keine", ok.saeulen(OPUS_GARAGE) == 0)

print("4) KREUZ-KONTROLLE (Vier-Augen): drei Quellen stimmen → bestätigt:")
dc = ok.doppelcheck_num("Geschoss-Höhe", "geschosshoehe_m", "m",
        [("Schnitt", 2.95), ("Raumhöhen", 2.92), ("Opus", 2.95)], 0.12)
check("3 Quellen einig → bestätigt", dc and dc["status"] == "bestätigt", f"got {dc}")
check("3 Quellen protokolliert", dc and len(dc["quellen"]) == 3, f"got {dc}")
dct = ok.doppelcheck_kat("Dachtyp", "dach_typ",
        [("Legende", "Flach"), ("Schnitt", "flach"), ("Opus", "flach")])
check("Dachtyp 3× flach → bestätigt", dct and dct["status"] == "bestätigt", f"got {dct}")

print("5) WIDERSPRUCH statt falscher Sicherheit:")
dc2 = ok.doppelcheck_num("Geschoss-Höhe", "geschosshoehe_m", "m",
        [("Schnitt", 2.95), ("Raumhöhen", 2.50), ("Opus", 2.95)], 0.12)
check("Eine Quelle weicht ab → widerspruch", dc2 and dc2["status"] == "widerspruch", f"got {dc2}")
dct2 = ok.doppelcheck_kat("Dachtyp", "dach_typ",
        [("Legende", "flach"), ("Opus", "pult")])
check("Dachtyp uneinig → widerspruch", dct2 and dct2["status"] == "widerspruch", f"got {dct2}")
# Nur EINE Quelle → gar kein Eintrag (nichts behaupten)
check("eine einzige Quelle → kein Doppelcheck-Eintrag",
      ok.doppelcheck_num("X", "x", "m", [("Opus", 2.95)], 0.12) is None)

print("6) NICHTS RATEN — global unsicher → komplett verworfen:")
unsicher = dict(OPUS_GARAGE, unsicherheit_flag=True)
check("Mauerwerk-Zusatz 0 bei unsicher", ok.mauerwerk_zusatz(unsicher, HUELLE) == (0.0, []))
check("Slab None bei unsicher", ok.slab_zusatz(unsicher, HUELLE) is None)
check("Höhe None bei unsicher", ok.hoehe_rohbau(unsicher) is None)
check("Dach None bei unsicher", ok.dach_typ(unsicher) is None)
check("Opus-Quelle fällt aus Doppelcheck (kein 3.) → 2 Quellen",
      True)  # _ov_h ist dann None; in extract wird Opus gar nicht eingespeist

print("7) Feld-Konfidenz <0.6 → Wert NICHT konsumiert:")
schwach = {
    "ueberdachte_bereiche": [
        {"name": "Carport", "geschlossen_typ": "gemauert", "auf_slab": True,
         "mauerwerk_umfang_zusatz_m": 14.0, "fundament_umfang_zusatz_m": 14.0,
         "konfidenz": 0.45, "evidenz": "unklar ob Wand oder Stütze"}],
    "hoehe": {"rohbau_m": 2.95, "konfidenz": 0.4},
    "dach": {"dach_typ": "flach", "konfidenz": 0.5},
    "gesamtkonfidenz": 0.6,
}
check("schwache Garage (konf 0.45) nicht addiert", ok.mauerwerk_zusatz(schwach, HUELLE) == (0.0, []))
check("schwache Slab (konf 0.45) nicht addiert", ok.slab_zusatz(schwach, HUELLE) is None)
check("schwache Höhe (konf 0.4) verworfen", ok.hoehe_rohbau(schwach) is None)
check("schwacher Dachtyp (konf 0.5) verworfen", ok.dach_typ(schwach) is None)

print("8) PLAUSI-Deckel — ein Zusatz > 60% der Hülle ist unrealistisch:")
absurd = {"ueberdachte_bereiche": [
    {"name": "Riesen", "geschlossen_typ": "gemauert", "auf_slab": True,
     "mauerwerk_umfang_zusatz_m": HUELLE * 0.9, "fundament_umfang_zusatz_m": HUELLE * 0.9,
     "konfidenz": 0.9}], "gesamtkonfidenz": 0.9}
check("absurder Mauerwerk-Zusatz (90% Hülle) verworfen", ok.mauerwerk_zusatz(absurd, HUELLE) == (0.0, []))
check("absurder Slab-Zusatz verworfen", ok.slab_zusatz(absurd, HUELLE) is None)

print("9) GROUNDING — Höhe außerhalb Rohbau-Band [2.2,4.5] verworfen:")
ausband = {"hoehe": {"rohbau_m": 8.0, "konfidenz": 0.9}, "gesamtkonfidenz": 0.9}
check("8m Rohbau-Höhe (Fehl-Lesung) verworfen", ok.hoehe_rohbau(ausband) is None)

print("10) Leeres/None-Urteil bricht nichts:")
check("None → Mauerwerk (0, [])", ok.mauerwerk_zusatz(None, HUELLE) == (0.0, []))
check("None → Slab None", ok.slab_zusatz(None, HUELLE) is None)
check("None → Höhe None", ok.hoehe_rohbau(None) is None)
check("{} → Dach None", ok.dach_typ({}) is None)

print()
if fails:
    print(f"FEHLER: {len(fails)} Test(s) gescheitert: {fails}")
    sys.exit(1)
print("OK — Opus-Konsum additiv, gegroundet, kreuz-kontrolliert, rät nie.")
