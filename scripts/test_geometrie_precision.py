#!/usr/bin/env python3
"""Belegt die L-Form-Genauigkeit der Bounding-Box: Segmente derselben Fassade
werden SUMMIERT (nicht max), sonst wird der Umfang systematisch unterschätzt.

Lauf: python3 scripts/test_geometrie_precision.py   (Exit 0 = bestanden)
"""
import sys, os
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "api"))
from extract import _bbox_from_sides

fails = []
def check(name, cond, detail=""):
    print(f"  {'✓' if cond else '✗'} {name}" + (f"  — {detail}" if detail and not cond else ""))
    if not cond: fails.append(name)

print("Rechteck (eine Zahl je Seite) — unverändert:")
b = _bbox_from_sides({"N": 12.0, "S": 12.0, "W": 8.0, "E": 8.0})
check("Rechteck 12×8 → Umfang 40", b and b["umfang_m"] == 40.0, f"got {b}")

print("\nL-Form mit Fassaden-Segmenten — Segmente werden SUMMIERT:")
# Südfassade in zwei Segmenten 7,2 + 5,2 = 12,4 ; Ostfassade 4,5 + 3,5 = 8,0
b = _bbox_from_sides({"N": 12.4, "S": 7.2, "S_b": 5.2, "W": 8.0, "E": 4.5, "E_b": 3.5})
check("Süd 7,2+5,2 → 12,4 (Breite)", b and b["breite_m"] == 12.4, f"got {b}")
check("Ost 4,5+3,5 → 8,0 (Tiefe)", b and b["tiefe_m"] == 8.0, f"got {b}")
check("Umfang 2×(12,4+8,0) = 40,8 (nicht 2×(12,4+4,5)=33,8)", b and b["umfang_m"] == 40.8, f"got {b}")

print("\nNur Segmente einer Fassade (kein Voll-Maß) — Summe statt max:")
b = _bbox_from_sides({"N": 7.0, "N_b": 5.0, "S": 12.0, "W": 8.0, "E": 8.0})
check("Nord 7+5=12 (nicht max 7)", b and b["breite_m"] == 12.0, f"got {b}")

print("\nPlausi-Gate bleibt: unrealistische Seite wird verworfen:")
b = _bbox_from_sides({"N": 200.0, "S": 200.0, "W": 8.0, "E": 8.0})
check("200m-Seite → None (Plausi)", b is None, f"got {b}")

print("\nOst-Synonym 'O' wird wie 'E' behandelt:")
b = _bbox_from_sides({"N": 10.0, "S": 10.0, "W": 6.0, "O": 6.0})
check("O==E → Tiefe 6, Umfang 32", b and b["umfang_m"] == 32.0, f"got {b}")

print()
if fails:
    print(f"FEHLER: {len(fails)} Test(s) gescheitert: {fails}")
    sys.exit(1)
print("OK — Geometrie-BBox summiert Fassaden-Segmente korrekt.")
