#!/usr/bin/env python3
"""Belegt den Text-Layer-Maßketten-Reader: byte-exakte Gebäude-Hülle aus den
Kettenbemaßungs-Zahlen, an der Grundfläche verankert (Gebäude vs. Lageplan).

Lauf: python3 scripts/test_massketten.py   (Exit 0 = bestanden)
"""
import sys, os, json
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "api"))
from massketten import reconstruct_bbox

fails = []
def check(name, cond, detail=""):
    print(f"  {'✓' if cond else '✗'} {name}" + (f"  — {detail}" if detail and not cond else ""))
    if not cond: fails.append(name)

def _chain(y, segs, x0=100, step=40):
    return [[x0 + i * step, y, v] for i, v in enumerate(segs)]

print("Sauberes Rechteck (Breite 12,0 / Tiefe 8,0 → Umfang 40):")
spans = []
# horizontale Ketten (gleiches y) summieren zu 1200cm; vertikale zu 800cm
spans += _chain(50, [300, 300, 300, 300])      # Σ 1200
spans += _chain(560, [600, 600])               # Σ 1200 (zweite Facade)
spans += [[60, 100 + i * 40, v] for i, v in enumerate([400, 400])]   # vertikal Σ 800
spans += [[700, 100 + i * 40, v] for i, v in enumerate([200, 200, 200, 200])]  # vertikal Σ 800
r = reconstruct_bbox(spans, footprint_m2=92.0)   # 12×8=96 ≈ 92×1.04
check("Rechteck 12×8 → Umfang 40", r and r["umfang_m"] == 40.0, f"got {r}")

print("\nLageplan-Distraktor (große Grundstücks-Ketten) → Gebäude wird gewählt:")
spans2 = list(spans)
spans2 += _chain(900, [900, 900, 900])   # Σ 2700 cm = 27m (Grundstück, viel größer)
spans2 += [[1500, 100 + i * 40, v] for i, v in enumerate([1000, 1000])]  # 2000cm vertikal
r = reconstruct_bbox(spans2, footprint_m2=92.0)
check("trotz Lageplan-Ketten: Gebäude 12×8 (Footprint-Anker)", r and r["umfang_m"] == 40.0, f"got {r}")

print("\nECHTE Angerer-Maße (Fixture aus dem Einreichplan):")
fx = os.path.join(ROOT, "scripts", "fixtures", "angerer_dimspans.json")
if os.path.exists(fx):
    spans3 = json.load(open(fx))
    r = reconstruct_bbox(spans3, footprint_m2=108.75)
    check("Angerer-Breite = 12,48 m", r and r["breite_m"] == 12.48, f"got {r}")
    check("Angerer-Tiefe = 10,75 m", r and r["tiefe_m"] == 10.75, f"got {r}")
    check("Angerer-Hülle-Umfang = 46,46 m (stabil, byte-exakt)", r and r["umfang_m"] == 46.46, f"got {r}")
    check("wiederholte Fassaden-Totals erkannt (h_rep≥3)", r and r["h_rep"] >= 3, f"got h_rep={r.get('h_rep') if r else None}")
else:
    print("  (Fixture fehlt — übersprungen)")

print("\nKein Match (leere/unpassende Spans) → None (Fallback, kein Crash):")
check("leere Spans → None", reconstruct_bbox([], 100) is None)
check("Spans ohne passende Fläche → None", reconstruct_bbox(_chain(50, [100, 100]), 999.0) is None)

print()
if fails:
    print(f"FEHLER: {len(fails)} Test(s) gescheitert: {fails}")
    sys.exit(1)
print("OK — Maßketten-Reader byte-exakt + Footprint-verankert.")
