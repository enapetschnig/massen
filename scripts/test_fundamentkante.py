#!/usr/bin/env python3
"""Belegt die geschärfte Vision-Außenkontur: die Frostschürze/Randabschluss
folgen der FUNDAMENTPLATTEN-Außenkante (Linie B, inkl. angebauter überdachter
Bereiche), das MAUERWERK folgt der gemauerten Hülle (Linie A).

Lauf: python3 scripts/test_fundamentkante.py   (Exit 0 = bestanden)
"""
import sys, os
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "api"))
from materialliste import build_materialliste

ROOMS = [
    {"name": "Wohnen", "flaeche_m2": 30.0, "umfang_m": 24.0, "hoehe_m": 2.7, "bodenbelag": "Fliesen"},
    {"name": "Bad", "flaeche_m2": 8.0, "umfang_m": 11.0, "hoehe_m": 2.7, "bodenbelag": "Fliesen"},
    {"name": "Zimmer", "flaeche_m2": 14.0, "umfang_m": 15.0, "hoehe_m": 2.7, "bodenbelag": "Fliesen"},
]
BAUDATEN = {"aussenwand_cm": 50, "innenwand_tragend_cm": 25, "innenwand_nichttragend_cm": 12,
            "decke_cm": 20, "bodenplatte_cm": 25, "geschosshoehe_m": 2.7,
            "sauberkeitsschicht_cm": 10}

def _menge(ml, bauteil, needle):
    for p in ml["bauteile"].get(bauteil, []):
        if needle.lower() in p["material"].lower():
            return p["menge"]
    return None

# Variante A: keine Fundamentkante → fundament = aussenumfang (Verhalten wie bisher)
G_BASE = {"aussenumfang_m": 50.0, "bodenplatte_flaeche_m2": 125.0, "konfidenz": 0.9, "quelle": "test"}
ml_a = build_materialliste(ROOMS, [], BAUDATEN, gemessen=G_BASE)

# Variante B: Fundamentkante 60m (überdachte Terrasse angebaut), Hülle weiter 50m
G_FUND = dict(G_BASE, fundament_umfang_m=60.0)
ml_b = build_materialliste(ROOMS, [], BAUDATEN, gemessen=G_FUND)

fails = []
def check(name, cond, detail=""):
    print(f"  {'✓' if cond else '✗'} {name}" + (f"  — {detail}" if detail and not cond else ""))
    if not cond:
        fails.append(name)

print("Fundamentkante 60m vs gemauerte Hülle 50m:")

# 1) Frostschürze skaliert mit der Fundamentkante (60/50 = 1.2× mehr)
fs_a = _menge(ml_a, "Frostschürze", "XPS-SF G30")
fs_b = _menge(ml_b, "Frostschürze", "XPS-SF G30")
check("Frostschürze XPS folgt Fundamentkante (×1.2)",
      fs_a and fs_b and abs(fs_b / fs_a - 1.2) < 0.02, f"a={fs_a} b={fs_b}")

# 2) Randabschlusskorb Bodenplatte = Fundamentkante (60), nicht Hülle (50)
ra_b = _menge(ml_b, "Bodenplatte", "Randabschlusskorb")
check("Randabschlusskorb = Fundamentkante 60m", ra_b == 60.0, f"got {ra_b}")
ra_a = _menge(ml_a, "Bodenplatte", "Randabschlusskorb")
check("Randabschlusskorb ohne Linie B = Hülle 50m", ra_a == 50.0, f"got {ra_a}")

# 3) MAUERWERK bleibt auf der gemauerten Hülle — Außenwand-HLZ unverändert
hlz_a = _menge(ml_a, "Mauerwerk EG", "HLZ 50")
hlz_b = _menge(ml_b, "Mauerwerk EG", "HLZ 50")
check("Mauerwerk HLZ50 folgt NICHT der Fundamentkante (unverändert)",
      hlz_a is not None and hlz_a == hlz_b, f"a={hlz_a} b={hlz_b}")

# 4) Mauersperrbahn (unter den Wänden) bleibt auf der Hülle
msb_a = _menge(ml_a, "Mauerwerk EG", "Mauersperrbahn")
msb_b = _menge(ml_b, "Mauerwerk EG", "Mauersperrbahn")
check("Mauersperrbahn unverändert (folgt Wänden, nicht Platte)",
      msb_a is not None and msb_a == msb_b, f"a={msb_a} b={msb_b}")

# 5) Bodenplatten-FLÄCHE-Material (XPS unter Platte) unverändert — nur Kante wächst
xps_a = _menge(ml_a, "Bodenplatte", "XPS-SF G30 120")
xps_b = _menge(ml_b, "Bodenplatte", "XPS-SF G30 120")
check("Bodenplatten-Fläche (XPS 120) unverändert", xps_a == xps_b, f"a={xps_a} b={xps_b}")

print()
if fails:
    print(f"FEHLER: {len(fails)} Test(s) gescheitert: {fails}")
    sys.exit(1)
print("OK — Fundamentkante korrekt geroutet.")
