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

# Realistischer Fall Angerer: eine echte GEMAUERTE Garage zählt zur Hülle, der
# OFFENE überdachte Parkplatz (Dach auf Stützen) NICHT — auch wenn Opus ihn
# fälschlich als "gemauert" liest (deterministischer Namens-Guard).
OPUS_GARAGE = {
    "ueberdachte_bereiche": [
        {"name": "Garage", "geschlossen_typ": "gemauert", "auf_slab": True,
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
check("Garagen-Name geliefert", namen == ["Garage"], f"got {namen}")
# DETERMINISTISCHER NAMENS-GUARD: ein "Parkplatz/Carport/Terrasse überdacht" ist
# inhärent OFFEN (Dach auf Stützen) → bekommt NIE Mauerwerk, selbst wenn Opus
# ihn als "gemauert" mit hoher Konfidenz liest. Das stoppt das Lauf-zu-Lauf-
# Springen + den Außenwand-Overcount (echtes Angerer-Problem).
_offener_pp = {"ueberdachte_bereiche": [{"name": "Parkplatz überdacht",
               "geschlossen_typ": "gemauert", "auf_slab": True,
               "mauerwerk_umfang_zusatz_m": 14.0, "konfidenz": 0.9}],
               "gesamtkonfidenz": 0.9}
check("'Parkplatz überdacht' gemauert (Konf 0.9) → TROTZDEM kein Mauerwerk (offen)",
      ok.mauerwerk_zusatz(_offener_pp, HUELLE) == (0.0, []), f"got {ok.mauerwerk_zusatz(_offener_pp, HUELLE)}")
# STABILITÄT: eine nur mittel-sichere Garage (0.65 < 0.75) erweitert die Hülle NICHT
# (offen-vs-gemauert schwankt; nur sehr sichere Urteile zählen).
_wackel = {"ueberdachte_bereiche": [{"name": "Garage", "geschlossen_typ": "gemauert",
           "auf_slab": True, "mauerwerk_umfang_zusatz_m": 14.0, "konfidenz": 0.65}],
           "gesamtkonfidenz": 0.7}
check("wackelige Garage (Konf 0.65) → KEIN Mauerwerk-Zusatz (stabil)",
      ok.mauerwerk_zusatz(_wackel, HUELLE) == (0.0, []), f"got {ok.mauerwerk_zusatz(_wackel, HUELLE)}")

print("2) Bereiche auf durchgehender Platte → Slab-Kante (Linie B):")
slab = ok.slab_zusatz(OPUS_GARAGE, HUELLE)
# Garage 14 + Terrasse 6 = 20 → 46,46 + 20 = 66,46 (beide auf_slab; Slab folgt
# auf_slab, NICHT dem Namens-Guard — die Platte läuft auch unter den Carport).
check("Slab = Hülle + Σ Platten-Zusatz (Garage+Terrasse)", slab == round(HUELLE + 20.0, 2), f"got {slab}")

print("3) Höhe/Dach/Säulen nur konf-gegated (≥0.6):")
check("Rohbau-Höhe aus Schnitt", ok.hoehe_rohbau(OPUS_GARAGE) == 2.95, f"got {ok.hoehe_rohbau(OPUS_GARAGE)}")
check("Dachtyp flach", ok.dach_typ(OPUS_GARAGE) == "flach", f"got {ok.dach_typ(OPUS_GARAGE)}")
check("Säulen 0 wenn keine", ok.saeulen(OPUS_GARAGE) == 0)

print("4) ECHTE UNABHÄNGIGKEIT — nur Text×Vision bestätigt, nicht Vision×Vision:")
# Raumhöhen = byte-exakter Text-Layer, Schnitt = Vision → ZWEI Methoden → bestätigt
dc = ok.doppelcheck_num("Geschoss-Höhe", "geschosshoehe_m", "m",
        [("Schnitt", 2.95, "vision"), ("Raumhöhen", 2.92, "text"), ("Opus", 2.95, "vision")], 0.12)
check("Text + Vision einig → bestätigt", dc and dc["status"] == "bestätigt", f"got {dc}")
check("als unabhängig markiert (2 Typen)", dc and dc["unabhaengig"] and dc["typen_n"] == 2, f"got {dc}")
check("3 Quellen protokolliert", dc and len(dc["quellen"]) == 3, f"got {dc}")
# KERN-EHRLICHKEIT: Schnitt + Opus lesen DASSELBE Bild → keine echte Bestätigung
dc_vv = ok.doppelcheck_num("Geschoss-Höhe", "geschosshoehe_m", "m",
        [("Schnitt", 2.95, "vision"), ("Opus", 2.95, "vision")], 0.12)
check("zwei Vision-Pässe einig → NUR verstaerkt (nicht bestätigt)",
      dc_vv and dc_vv["status"] == "verstaerkt" and not dc_vv["unabhaengig"], f"got {dc_vv}")
# Dachtyp: Legende (Text) + Schnitt (Vision) → bestätigt
dct = ok.doppelcheck_kat("Dachtyp", "dach_typ",
        [("Legende", "Flach", "text"), ("Schnitt", "flach", "vision"), ("Opus", "flach", "vision")])
check("Dachtyp Text+Vision flach → bestätigt", dct and dct["status"] == "bestätigt", f"got {dct}")
dct_vv = ok.doppelcheck_kat("Dachtyp", "dach_typ",
        [("Schnitt", "flach", "vision"), ("Opus", "flach", "vision")])
check("Dachtyp zwei Vision-Pässe → nur verstaerkt", dct_vv and dct_vv["status"] == "verstaerkt", f"got {dct_vv}")

print("5) WIDERSPRUCH statt falscher Sicherheit:")
dc2 = ok.doppelcheck_num("Geschoss-Höhe", "geschosshoehe_m", "m",
        [("Schnitt", 2.95, "vision"), ("Raumhöhen", 2.50, "text"), ("Opus", 2.95, "vision")], 0.12)
check("Eine Quelle weicht ab → widerspruch", dc2 and dc2["status"] == "widerspruch", f"got {dc2}")
dct2 = ok.doppelcheck_kat("Dachtyp", "dach_typ",
        [("Legende", "flach", "text"), ("Opus", "pult", "vision")])
check("Dachtyp uneinig → widerspruch", dct2 and dct2["status"] == "widerspruch", f"got {dct2}")
# Nur EINE Quelle → gar kein Eintrag (nichts behaupten)
check("eine einzige Quelle → kein Doppelcheck-Eintrag",
      ok.doppelcheck_num("X", "x", "m", [("Opus", 2.95, "vision")], 0.12) is None)

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

print("11) GENERALISIERUNG — offener Carport (ständer) ist KEIN Mauerwerk:")
# Echter offener Carport: nur Stützen, kein Mauerwerk, aber auf der Platte.
carport = {"ueberdachte_bereiche": [
    {"name": "Carport", "geschlossen_typ": "ständer", "auf_slab": True,
     "mauerwerk_umfang_zusatz_m": 0.0, "fundament_umfang_zusatz_m": 9.0, "konfidenz": 0.8}],
    "gesamtkonfidenz": 0.8}
check("ständer-Carport → KEIN Mauerwerk-Zusatz", ok.mauerwerk_zusatz(carport, HUELLE) == (0.0, []))
check("ständer-Carport auf Platte → Slab-Zusatz (Plattenrand zählt)",
      ok.slab_zusatz(carport, HUELLE) == round(HUELLE + 9.0, 2), f"got {ok.slab_zusatz(carport, HUELLE)}")
# Reiner offener Bereich (nur Dach/Platte) ohne auf_slab → gar nichts
offen = {"ueberdachte_bereiche": [
    {"name": "Vordach", "geschlossen_typ": "offen", "auf_slab": False,
     "mauerwerk_umfang_zusatz_m": 0.0, "fundament_umfang_zusatz_m": 0.0, "konfidenz": 0.8}],
    "gesamtkonfidenz": 0.8}
check("offenes Vordach → kein Mauerwerk, kein Slab", ok.mauerwerk_zusatz(offen, HUELLE) == (0.0, []) and ok.slab_zusatz(offen, HUELLE) is None)
# Leerer bereiche-Array (Plan ohne Anbau) → keine Phantom-Zusätze
leer = {"ueberdachte_bereiche": [], "hoehe": {"rohbau_m": 2.8, "konfidenz": 0.8}, "gesamtkonfidenz": 0.8}
check("Plan ohne Anbau → kein Mauerwerk-Phantom", ok.mauerwerk_zusatz(leer, HUELLE) == (0.0, []))
check("Plan ohne Anbau → kein Slab-Phantom", ok.slab_zusatz(leer, HUELLE) is None)
check("Plan ohne Anbau → Höhe trotzdem lesbar", ok.hoehe_rohbau(leer) == 2.8)

print("12) WAND-VERTEILUNG aus scharfen Grundriss-Kacheln (Vision, konf-gegated):")
mit_wv = {"wand_verteilung": {"aussen_pct": {"50": 85, "38": 8, "25": 7},
          "innen_pct": {"25": 30, "20": 39, "12": 31}, "konfidenz": 0.6},
          "gesamtkonfidenz": 0.7}
wv = ok.wand_verteilung_aus_opus(mit_wv)
check("Außen-Anteile konvertiert (50→85)", wv and wv["aussen"][50.0] == 85.0, f"got {wv}")
check("Innen-Anteile konvertiert (12→31)", wv and wv["innen"][12.0] == 31.0, f"got {wv}")
check("Quelle = opus-vision", wv and wv["quelle"] == "opus-vision")
schwach_wv = {"wand_verteilung": {"aussen_pct": {"50": 90}, "konfidenz": 0.3}, "gesamtkonfidenz": 0.6}
check("schwache Konfidenz (0.3) → None (nicht raten)", ok.wand_verteilung_aus_opus(schwach_wv) is None)
check("unsicheres Opus → None", ok.wand_verteilung_aus_opus(dict(mit_wv, unsicherheit_flag=True)) is None)
check("ohne wand_verteilung → None", ok.wand_verteilung_aus_opus({"gesamtkonfidenz": 0.8}) is None)

print()
if fails:
    print(f"FEHLER: {len(fails)} Test(s) gescheitert: {fails}")
    sys.exit(1)
print("OK — Opus-Konsum additiv, gegroundet, kreuz-kontrolliert, rät nie.")
