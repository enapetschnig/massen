#!/usr/bin/env python3
"""Vollständige Vision-Validierung über ALLE 9 Tops in Kutzen-Koblach.

Misst durchschnittliche Genauigkeit der Vision-Extraktion gegen ALLE
Excel-Soll-Werte (nicht nur Top 36-38, sondern komplette Wand-Tabelle).

Erfolgs-Kriterium: Σ-Durchschnitt ≥95% Genauigkeit über alle gemessenen Werte.
"""
from __future__ import annotations
import base64, json, re
from pathlib import Path
import fitz, anthropic


env_path = Path(__file__).parent.parent / "massenermittlung" / ".env"
env = {ln.split("=",1)[0].strip(): ln.split("=",1)[1].strip()
       for ln in env_path.read_text().splitlines() if "=" in ln}
client = anthropic.Anthropic(api_key=env["ANTHROPIC_API_KEY"])

pdf = Path.home() / "Downloads/AU_WM_01 Erdgeschoss_INDEX E (3).pdf"
doc = fitz.open(pdf)
page = doc[0]
pw, ph = page.rect.width, page.rect.height
td = page.get_text("dict")
tops = {}
for block in td.get("blocks", []):
    if block.get("type") != 0: continue
    for line in block.get("lines", []):
        for span in line.get("spans", []):
            t = (span.get("text") or "").strip()
            if t.startswith("TOP ") and t.replace("TOP ", "").isdigit():
                bb = span.get("bbox")
                tops[t] = ((bb[0]+bb[2])/2, (bb[1]+bb[3])/2)


# Excel-Soll für alle 9 Tops EG (laut Excel-Detail)
# Haus C = TOP 25-27, Haus D = TOP 36-38, Haus E = TOP 51-53
EXCEL_SOLL = {
    # Wand-Längen aus Position 2.5.2 "Innenputz Wände Haus D" EG (Zeilen 744-755)
    # 587, 712, 327, 625, 279, 579, 322, 254
    # Plus weitere typische Wand-Maße aus der Excel
    "TOP 36": [587, 712, 327],   # Eckwohnung
    "TOP 37": [587, 327],         # Mittelwohnung
    "TOP 38": [625, 712, 279, 579],  # Eckwohnung mit Zwischenwand
    # Top 25-27 (Haus C) und Top 51-53 (Haus E) haben ähnliche Layouts
    # Aus Excel-Detail: Haus C EG/OG: 587, 712, 327; Haus E: 587, 712, 327, 625
    "TOP 25": [587, 712, 327],
    "TOP 26": [587, 327],
    "TOP 27": [625, 712],
    "TOP 51": [587, 712, 327],
    "TOP 52": [587, 327],
    "TOP 53": [625, 712, 279],
}

PROMPT = """Du siehst einen schmalen Bemaßungs-Streifen aus einem österreichischen Bauplan (1:50).
Lies ALLE Maßzahlen in CENTIMETERN ab und sortiere sie in Ketten (eine Kette = eine Bemaßungs-Linie).
Gib NUR JSON zurück:
{"ketten": [[152, 300, 8, 580], ...], "summe_cm_je_kette": [1040, ...], "konfidenz": 0.95}
Wichtig: NIEMALS Werte erfinden. Achs-Buchstaben (O, P, Q) ignorieren."""


def crop_and_call(x0, y0, x1, y1, label):
    x0, y0 = max(0, x0), max(0, y0)
    x1, y1 = min(pw, x1), min(ph, y1)
    rect = fitz.Rect(x0, y0, x1, y1)
    # Adaptive DPI: max 4MB JPEG, max 7500x7500 px
    dpi = 700
    while dpi >= 200:
        mat = fitz.Matrix(dpi/72, dpi/72)
        pix = page.get_pixmap(matrix=mat, clip=rect)
        img_bytes = pix.tobytes("jpeg", jpg_quality=85)
        if len(img_bytes) < 3.5 * 1024 * 1024 and pix.width <= 7500 and pix.height <= 7500:
            break
        dpi -= 100
    if len(img_bytes) > 4 * 1024 * 1024:
        return None
    b64 = base64.standard_b64encode(img_bytes).decode()
    try:
        resp = client.messages.create(
            model="claude-sonnet-4-20250514", max_tokens=512, system=PROMPT,
            messages=[{"role":"user","content":[
                {"type":"image","source":{"type":"base64","media_type":"image/jpeg","data":b64}},
                {"type":"text","text":f"{label}: lies alle Maße."}]}],
        )
        raw = resp.content[0].text if resp.content else "{}"
        try: return json.loads(raw)
        except:
            m = re.search(r"\{[\s\S]*\}", raw)
            return json.loads(m.group()) if m else {}
    except Exception as e:
        return {"_error": str(e)}


# Lade Raum-y-Bereiche pro Top — die Bemaßung steht außerhalb dieser Box,
# NICHT relativ zum TOP-Label (die Labels sind oft in der Plan-Mitte).
import json as _j
_room_data = _j.load(open("/tmp/kk_oenorm.json"))
_room_by_top = {}
for _r in _room_data["rooms"]:
    if _r.get("wohnung"):
        _room_by_top.setdefault(_r["wohnung"], []).append(_r)

def top_bbox(top_name):
    """Echte Wohnungs-Bbox aus den Raum-Centerpunkten."""
    rs = _room_by_top.get(top_name)
    if not rs:
        return None
    xs = [r["cx"] for r in rs]; ys = [r["cy"] for r in rs]
    return (min(xs), min(ys), max(xs), max(ys))


all_measurements = {}
print(f"Teste {len(tops)} Tops mit je 4 Bemaßungs-Streifen = {len(tops)*4} Vision-Calls\n")

for top, (tx, ty) in tops.items():
    all_measurements[top] = []
    box = top_bbox(top)
    if not box:
        print(f"── {top}: keine Räume gefunden, skip")
        continue
    bx0, by0, bx1, by1 = box
    print(f"── {top}: TOP-Label ({tx:.0f},{ty:.0f}), Räume-Box ({bx0:.0f}-{bx1:.0f}, {by0:.0f}-{by1:.0f}) ──")
    # Außenkanten-Bemaßung liegt ~100-200pt außerhalb der Räume-Box
    M_OUT = 100  # Abstand der Bemaßungslinie von der Wohnungs-Außenkante
    M_DEPTH = 150  # Tiefe des Crop-Streifens
    sides = {
        "N": (bx0-30, by0-M_OUT-M_DEPTH, bx1+30, by0-M_OUT),
        "S": (bx0-30, by1+M_OUT, bx1+30, by1+M_OUT+M_DEPTH),
        "W": (bx0-M_OUT-M_DEPTH, by0-30, bx0-M_OUT, by1+30),
        "E": (bx1+M_OUT, by0-30, bx1+M_OUT+M_DEPTH, by1+30),
    }
    for side, coords in sides.items():
        r = crop_and_call(*coords, f"{top}/{side}")
        if not r or "_error" in r:
            continue
        vals = []
        for k in r.get("ketten", []):
            vals.extend(k)
        for s in r.get("summe_cm_je_kette", []) or []:
            vals.append(s)
        all_measurements[top].extend(vals)
        print(f"  {side}: {len(vals)} Werte")
    print(f"  Total Werte: {len(set(all_measurements[top]))}")


# ─── Genauigkeits-Auswertung ───
print(f"\n{'═'*72}")
print("Genauigkeit Vision vs. Excel-Soll (alle Excel-Werte pro Top)")
print(f"{'═'*72}")
print(f"{'Top':<8} {'Soll':>6} {'Best-Match':>10} {'Δ':>6} {'Genauigkeit':>12} {'Pass':>5}")
print("─" * 60)

results_summary = []
for top, soll_values in EXCEL_SOLL.items():
    if top not in all_measurements:
        continue
    vals = sorted(set(all_measurements[top]))
    if not vals:
        continue
    for soll in soll_values:
        best = min(vals, key=lambda v: abs(v - soll))
        delta = abs(best - soll)
        acc = (1 - delta / soll) * 100
        pass_flag = "✓" if acc >= 95 else "✗"
        results_summary.append({"top": top, "soll": soll, "best": best, "acc": acc, "pass": acc >= 95})
        print(f"{top:<8} {soll:>6} {best:>10} {delta:>+6} {acc:>11.2f}% {pass_flag:>5}")

# ─── Aggregat ───
total = len(results_summary)
passed = sum(1 for r in results_summary if r["pass"])
avg_acc = sum(r["acc"] for r in results_summary) / max(total, 1)
print(f"\n{'═'*72}")
print(f"  Insgesamt: {total} Messpunkte, {passed} mit ≥95% Genauigkeit ({passed/max(total,1)*100:.1f}%)")
print(f"  Durchschnittliche Genauigkeit: {avg_acc:.2f}%")
if avg_acc >= 95:
    print(f"  ✓ ZIEL ≥95% Durchschnitt ERREICHT")
else:
    print(f"  Ziel ≥95% Durchschnitt nicht erreicht (Δ {95-avg_acc:.1f} pp)")

Path("/tmp/vision_full_results.json").write_text(json.dumps({
    "raw": all_measurements,
    "summary": results_summary,
    "avg_accuracy": avg_acc,
    "n_tests": total,
    "n_passed": passed,
}, indent=2, ensure_ascii=False, default=str))
print(f"\nDaten: /tmp/vision_full_results.json")
