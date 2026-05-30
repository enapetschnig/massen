#!/usr/bin/env python3
"""Belegt die erweiterte Öffnungs-Code-Erkennung im Text-Layer:
- FBH (Fenster-Brüstungs-Höhe) wird wie FPH als Parapet behandelt
- lockere Trenner: 'FPH 0,90', 'FPH:0.90', 'FPH0,90'
- versetzte STUK-Beschriftung (>35pt, <70pt) wird per Fallback geclustert

Lauf: python3 scripts/test_oeffnungen_codes.py   (Exit 0 = bestanden)
"""
import sys, os
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "api"))
from oeffnungen import extract_oeffnungen_from_text, FPH_RX, STUK_RX

fails = []
def check(name, cond, detail=""):
    print(f"  {'✓' if cond else '✗'} {name}" + (f"  — {detail}" if detail and not cond else ""))
    if not cond: fails.append(name)

print("Regex-Varianten:")
for txt in ["FPH 0,90", "FPH:0.90", "FPH0,90", "FBH 0,90", "FBH:0.90"]:
    m = FPH_RX.match(txt)
    check(f"FPH/FBH matcht '{txt}'", bool(m), f"kein Match")
check("STUK matcht 'STUK 2,15'", bool(STUK_RX.match("STUK 2,15")))

def _sp(t, x, y): return {"text": t, "cx": x, "cy": y, "bbox": [x, y, x+10, y+5], "size": 7}
ROOMS = [{"name": "Bad", "cx": 100, "cy": 100}]

print("\nSZENARIO: FBH-Code (statt FPH) + STUK → Fenster mit Höhe = STUK − FBH")
spans = [_sp("FBH 0,90", 100, 100), _sp("STUK 2,10", 110, 108), _sp("80", 105, 116)]
oeff = extract_oeffnungen_from_text(spans, ROOMS)
check("1 Öffnung aus FBH+STUK erkannt", len(oeff) == 1, f"got {len(oeff)}")
if oeff:
    h = oeff[0].get("hoehe_m")
    check("Höhe = 2.10 − 0.90 = 1.20m", abs((h or 0) - 1.20) < 0.02, f"got {h}")

print("\nSZENARIO: versetzte STUK-Beschriftung (50pt entfernt) → per Fallback geclustert")
spans = [_sp("FPH 0,90", 100, 100), _sp("STUK 2,10", 145, 122), _sp("100", 108, 118)]
oeff = extract_oeffnungen_from_text(spans, ROOMS)
check("Öffnung trotz 50pt-Versatz erkannt", len(oeff) == 1, f"got {len(oeff)}")

print("\nSZENARIO: STUK direkt daneben bleibt bevorzugt (kein Fehlcluster)")
spans = [_sp("FPH 0,90", 100, 100), _sp("STUK 2,10", 108, 105),
         _sp("STUK 2,80", 150, 130), _sp("90", 104, 114)]
oeff = extract_oeffnungen_from_text(spans, ROOMS)
check("nimmt die nahe STUK (Höhe ~1.20, nicht ~1.90)", oeff and abs(oeff[0]["hoehe_m"] - 1.20) < 0.05,
      f"got {oeff[0]['hoehe_m'] if oeff else None}")

print()
if fails:
    print(f"FEHLER: {len(fails)} Test(s) gescheitert: {fails}")
    sys.exit(1)
print("OK — Öffnungs-Code-Erkennung erweitert.")
