#!/usr/bin/env python3
"""Hybrid-Beweis: Vision VERSTEHT den Plan (segmentiert die Ansichten), Vektoren MESSEN
byte-exakt darin. Schließt die View-Isolation-Lücke der reinen Vektor-Pipeline.

Vision liefert die Bounding-Box des EG-Grundrisses (das, was rein-geometrisch so schwer
zu finden war) → die Vektor-Wand-Messung läuft NUR in dieser Box → saubere Wände.

Lauf: massenermittlung/venv/bin/python3 scripts/vektor_hybrid_probe.py [plan.pdf]
Key:  /tmp/.ak (in dieser Session gesetzt)
"""
import base64
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "api"))

import fitz
import anthropic
import vektor

KEY = open("/tmp/.ak").read().strip()
DL = os.path.expanduser("~/Downloads")

PROMPT = """Du siehst ein Architektur-Planblatt (oft MEHRERE Ansichten auf einem Blatt:
Grundrisse, Schnitte, Ansichten, Lageplan, Legende). Segmentiere das Blatt.

Antworte NUR mit JSON:
{"ansichten":[
  {"typ":"grundriss_eg|grundriss_og|grundriss_kg|schnitt|ansicht|lageplan|legende|sonstiges",
   "bbox":[x0,y0,x1,y1],   // normiert 0..1 (0,0 = oben-links), umschließt NUR diese Ansicht
   "massstab":"1:100",     // falls erkennbar
   "titel":"kurzer Titel/Beschriftung der Ansicht"}
]}
Wichtig: das ERDGESCHOSS-Grundriss ("grundriss_eg") so eng wie möglich umschließen
(nur die Zeichnung, ohne Beschriftung/Maßketten am Rand). Nichts raten — nur was du siehst."""


def vision_segmentiere(page):
    dpi = 120
    pix = page.get_pixmap(matrix=fitz.Matrix(dpi / 72, dpi / 72))
    img = pix.tobytes("jpeg", jpg_quality=80)
    # falls zu groß, runter
    while len(img) > 4_500_000 and dpi > 60:
        dpi = int(dpi * 0.8)
        pix = page.get_pixmap(matrix=fitz.Matrix(dpi / 72, dpi / 72))
        img = pix.tobytes("jpeg", jpg_quality=80)
    cl = anthropic.Anthropic(api_key=KEY, timeout=120, max_retries=2)
    resp = cl.messages.create(
        model="claude-sonnet-4-20250514", max_tokens=1500, temperature=0,
        messages=[{"role": "user", "content": [
            {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                          "data": base64.standard_b64encode(img).decode()}},
            {"type": "text", "text": PROMPT}]}])
    raw = resp.content[0].text
    m = re.search(r"\{[\s\S]*\}", raw)
    return json.loads(m.group()) if m else {}


def wand_in_bbox(page, bbox_norm, ptm, legende_dicken):
    """Wand-Messung NUR in der (normierten) Vision-Bbox."""
    W, H = page.rect.width, page.rect.height
    bx0, by0, bx1, by1 = bbox_norm[0] * W, bbox_norm[1] * H, bbox_norm[2] * W, bbox_norm[3] * H
    segs, _f, _n = vektor._drawings(page)
    inb = lambda s: bx0 <= (s[0] + s[2]) / 2 <= bx1 and by0 <= (s[1] + s[3]) / 2 <= by1
    arch = [s for s in segs if (s[5] is None or s[5] < 0.45)
            and vektor._laenge(s) / ptm > 0.8 and inb(s)]
    paare = vektor.wand_paare(arch, ptm, min_len_m=0.8)
    je = {}
    for L, dk, _ac in paare:
        sn = vektor._snap_legende(dk, legende_dicken, 2.5)
        if sn:
            e = je.setdefault(sn, {"laenge_m": 0.0, "n": 0})
            e["laenge_m"] += L
            e["n"] += 1
    return {"bbox_m": [round((bx1 - bx0) / ptm, 1), round((by1 - by0) / ptm, 1)],
            "n_arch": len(arch), "n_paare": len(paare),
            "je_staerke": {k: {"laenge_m": round(v["laenge_m"], 1), "n": v["n"]} for k, v in je.items()}}


def run(pdf):
    d = fitz.open(pdf)
    page = max(d, key=lambda p: p.rect.width * p.rect.height)
    mst = (re.search(r"1\s*:\s*(\d{2,4})", page.get_text()) or [None, None])
    mst = f"1:{mst[1]}" if mst[1] else None
    ptm = vektor.kalibriere(page.get_text("words"), mst).get("ptm_konsens")
    print(f"Plan: {os.path.basename(pdf)[:50]} · pt/m={ptm} · Maßstab={mst}")
    print("→ Vision segmentiert die Ansichten …")
    seg = vision_segmentiere(page)
    views = seg.get("ansichten", [])
    for v in views:
        print(f"   [{v.get('typ'):<14}] {v.get('titel','')[:40]:<40} bbox={[round(x,2) for x in v.get('bbox',[])]}")
    eg = next((v for v in views if v.get("typ") == "grundriss_eg"), None)
    if not eg or not ptm:
        print("Kein EG-Grundriss erkannt ODER keine Kalibrierung → Abbruch.")
        return
    print(f"\n→ Vektor-Wand-Messung NUR in der EG-Grundriss-Box {eg['bbox']}:")
    r = wand_in_bbox(page, eg["bbox"], ptm, [50, 25, 12])
    print(f"   Box {r['bbox_m']} m · {r['n_arch']} arch-Segmente · {r['n_paare']} Paare")
    for t in [50, 25, 12]:
        e = r["je_staerke"].get(t, {})
        print(f"   HLZ {t}cm: {e.get('n', 0)} Wände, Σ {e.get('laenge_m', 0)} m")
    print("   Referenz Angerer: 50cm ≈ Außenumfang 45-50m · 12cm dominant ~29m")


if __name__ == "__main__":
    pdf = sys.argv[1] if len(sys.argv) > 1 else os.path.join(DL, "A-5_Einreichplan_Alfred-Angerer_36_25_Index 0 (1).pdf")
    run(pdf)
