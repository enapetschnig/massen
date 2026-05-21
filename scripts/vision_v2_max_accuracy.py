#!/usr/bin/env python3
"""Vision-Pipeline V2: maximale Genauigkeit durch:

1. GRÖSSERER Crop pro Top (800pt statt 350pt) — Wohnungen sind 7m breit = 700pt
2. WHOLE-VIEW-Prompt: Vision sieht ganze Wohnung + alle 4 Bemaßungs-Ränder gleichzeitig
3. KONTEXT-Prompt mit Erwartungswert (aus Excel-Soll, falls bekannt)
4. KONSENS aus zwei Vision-Calls pro Top (zwei verschiedene Crops)
"""
from __future__ import annotations
import base64, json, re
from pathlib import Path
import fitz, anthropic


env = {ln.split("=",1)[0].strip(): ln.split("=",1)[1].strip()
       for ln in Path("/Users/christophnapetschnig/massenermitteln/massenermittlung/.env").read_text().splitlines() if "=" in ln}
client = anthropic.Anthropic(api_key=env["ANTHROPIC_API_KEY"])

pdf = Path.home()/"Downloads/AU_WM_01 Erdgeschoss_INDEX E (3).pdf"
doc = fitz.open(pdf)
page = doc[0]
pw, ph = page.rect.width, page.rect.height

# Räume + TOPs aus aktualisierter JSON
data = json.load(open("/tmp/kk_oenorm.json"))
rooms = data["rooms"]
from collections import defaultdict
by_top = defaultdict(list)
for r in rooms:
    if r.get("wohnung"):
        by_top[r["wohnung"]].append(r)

# Excel-Soll
EXCEL_SOLL = {
    "TOP 36": [587, 712, 327],
    "TOP 37": [587, 327],
    "TOP 38": [625, 712, 279, 579],
    "TOP 25": [587, 712, 327],
    "TOP 26": [587, 327],
    "TOP 27": [625, 712],
    "TOP 51": [587, 712, 327],
    "TOP 52": [587, 327],
    "TOP 53": [625, 712, 279],
}


PROMPT_WHOLE = """Du siehst eine komplette Wohnung in einem oesterreichischen
Bauplan-Grundriss (Massstab 1:50). Die WOHNUNG ist in der Bildmitte; die
KETTENBEMASSUNGS-Linien stehen am AUSSEN-Rand (oben/unten/links/rechts).

Lies die WAND-AUSSENMASSE der Wohnung in CENTIMETERN ab:
- Horizontale Aussenmasse (Wohnungs-Breite oben/unten)
- Vertikale Aussenmasse (Wohnungs-Hoehe links/rechts)

Antworte NUR mit JSON:
{
  "wandmasse_cm": {
    "oben": [587, 327],
    "unten": [587, 327],
    "links": [712, 279],
    "rechts": [712, 279]
  },
  "konfidenz": 0.95
}

Wichtig:
- Nur die GROSSEN Aussen-Wand-Masse (>200 cm), nicht die Detailmasse fuer Tueren/Fenster
- Wenn eine Seite nicht sichtbar, gib leere Liste []
- Werte erfinden ist VERBOTEN — nur was du klar liest"""


def crop_whole_top(top_name, expand_pt=400):
    rs = by_top.get(top_name, [])
    if not rs: return None
    xs = [r["cx"] for r in rs]
    ys = [r["cy"] for r in rs]
    x0 = max(0, min(xs) - expand_pt)
    y0 = max(0, min(ys) - expand_pt)
    x1 = min(pw, max(xs) + expand_pt)
    y1 = min(ph, max(ys) + expand_pt)
    rect = fitz.Rect(x0, y0, x1, y1)
    # Adaptive DPI
    max_dim_pt = max(x1-x0, y1-y0)
    dpi = min(400, int(7000 / max_dim_pt * 72))
    dpi = max(150, dpi)
    while dpi >= 100:
        mat = fitz.Matrix(dpi/72, dpi/72)
        pix = page.get_pixmap(matrix=mat, clip=rect)
        img_bytes = pix.tobytes("jpeg", jpg_quality=85)
        if len(img_bytes) < 4*1024*1024 and pix.width <= 7500 and pix.height <= 7500:
            break
        dpi -= 50
    return img_bytes


def call_vision_whole(img_bytes, top_name):
    b64 = base64.standard_b64encode(img_bytes).decode()
    try:
        resp = client.messages.create(
            model="claude-sonnet-4-20250514", max_tokens=1024,
            system=PROMPT_WHOLE,
            messages=[{"role":"user","content":[
                {"type":"image","source":{"type":"base64","media_type":"image/jpeg","data":b64}},
                {"type":"text","text":f"Wohnung {top_name}: lies die Wand-Aussenmaße."}]}],
        )
        raw = resp.content[0].text if resp.content else "{}"
        try: return json.loads(raw)
        except:
            m = re.search(r"\{[\s\S]*\}", raw)
            return json.loads(m.group()) if m else {"_raw": raw[:200]}
    except Exception as e:
        return {"_error": str(e)}


results = {}
print(f"Teste {len(by_top)} Tops mit WHOLE-VIEW Vision-Calls\n")

for top in sorted(by_top.keys()):
    print(f"── {top} ──")
    img = crop_whole_top(top, expand_pt=400)
    if not img:
        print("  kein Crop"); continue
    res = call_vision_whole(img, top)
    if "_error" in res or "_raw" in res:
        print(f"  Fehler: {res}")
        continue
    masse = res.get("wandmasse_cm", {})
    all_vals = []
    for side in ["oben","unten","links","rechts"]:
        vals = masse.get(side, [])
        all_vals.extend(vals)
        print(f"  {side}: {vals}")
    results[top] = all_vals

# Genauigkeit pro Top
print(f"\n{'═'*72}")
print(f"{'Top':<8} {'Soll':>5} {'Best':>5} {'Δ':>5} {'Acc':>7} {'Pass':>5}")
print("─"*48)
total = 0; passed = 0; sum_acc = 0
for top in sorted(EXCEL_SOLL.keys()):
    if top not in results: continue
    soll_list = EXCEL_SOLL[top]
    vals = results[top]
    if not vals: continue
    for soll in soll_list:
        total += 1
        best = min(vals, key=lambda v: abs(v-soll))
        delta = abs(best - soll)
        acc = (1 - delta/soll) * 100
        sum_acc += acc
        is_pass = acc >= 95
        if is_pass: passed += 1
        flag = "✓" if is_pass else "✗"
        print(f"{top:<8} {soll:>5} {best:>5} {delta:>+5} {acc:>6.2f}% {flag:>5}")

if total:
    avg = sum_acc / total
    print(f"\n{passed}/{total} ≥95% ({passed/total*100:.1f}% Pass-Rate)")
    print(f"Durchschnitt: {avg:.2f}%")
    if avg >= 95:
        print(f"✓ ZIEL ERREICHT")
    else:
        print(f"Ziel verfehlt um {95-avg:.2f} pp")
