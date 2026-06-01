#!/usr/bin/env python3
"""Belegt: die Wandstärken-Verteilung meldet im Grundriss GEZÄHLTE Wand-Codes,
die in der Legende keinen Aufbau-Eintrag haben, als ehrlichen Prüf-Hinweis —
OHNE eine Stärke zu raten (keine Überanpassung) und OHNE die Verteilung der
dokumentierten Codes zu verändern (keine Regression).

Lauf: python3 scripts/test_legende_verteilung.py   (Exit 0 = bestanden)
"""
import sys, os
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "api"))
from legende import wand_verteilung_aus_counts

fails = []
def check(name, cond, detail=""):
    print(f"  {'✓' if cond else '✗'} {name}" + (f"  — {detail}" if detail and not cond else ""))
    if not cond: fails.append(name)

print("1) Alle gezählten Codes dokumentiert → KEINE Warnung, Verteilung wie bisher:")
leg_ok = {
    "wand_typen": {"AW1": {"dicke_cm": 50, "art": "aussen"}, "AW2": {"dicke_cm": 20, "art": "aussen"},
                   "IW1": {"dicke_cm": 25, "art": "innen"}, "IW2": {"dicke_cm": 12, "art": "innen"}},
    "wand_counts": {"AW1": 11, "AW2": 4, "IW1": 4, "IW2": 10},
}
v = wand_verteilung_aus_counts(leg_ok)
check("keine unbekannten Codes", "unbekannte_codes" not in v, f"got {v.get('unbekannte_codes')}")
check("Außen-Verteilung 50cm dominiert", round(v["aussen"][50]) == 73, f"got {v['aussen']}")
check("Innen-Verteilung vorhanden", 25 in v["innen"] and 12 in v["innen"], f"got {v['innen']}")

print("\n2) Ein gezählter Code OHNE Legende-Aufbau → ehrlicher Prüf-Hinweis:")
leg_gap = {
    "wand_typen": {"AW1": {"dicke_cm": 50, "art": "aussen"}, "IW1": {"dicke_cm": 25, "art": "innen"}},
    # BW1 (z.B. Brandwand 38cm) wird im Grundriss gezählt, steht aber NICHT in der Legende
    "wand_counts": {"AW1": 10, "IW1": 5, "BW1": 6},
}
v2 = wand_verteilung_aus_counts(leg_gap)
check("BW1 als unbekannter Code gemeldet", v2.get("unbekannte_codes") == ["BW1"], f"got {v2.get('unbekannte_codes')}")
check("dokumentierte Verteilung UNVERÄNDERT (keine geratene Stärke)",
      v2["aussen"] == {50: 100.0} and v2["innen"] == {25: 100.0}, f"got aussen={v2['aussen']} innen={v2['innen']}")

print("\n3) Mehrere unbekannte Codes → alle sortiert gemeldet:")
leg_multi = {"wand_typen": {"AW1": {"dicke_cm": 50, "art": "aussen"}},
             "wand_counts": {"AW1": 8, "TW2": 3, "BW1": 2}}
v3 = wand_verteilung_aus_counts(leg_multi)
check("beide unbekannten Codes (sortiert)", v3.get("unbekannte_codes") == ["BW1", "TW2"], f"got {v3.get('unbekannte_codes')}")

print("\n4) Leere Eingaben brechen nichts:")
check("keine Legende → {}", wand_verteilung_aus_counts({}) == {})
check("counts ohne typen → {}", wand_verteilung_aus_counts({"wand_counts": {"AW1": 5}}) == {})

print()
if fails:
    print(f"FEHLER: {len(fails)} Test(s) gescheitert: {fails}")
    sys.exit(1)
print("OK — unbekannte Wand-Codes ehrlich gemeldet, Verteilung unverändert, nichts geraten.")
