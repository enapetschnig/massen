#!/usr/bin/env python3
"""End-to-end test der Vision-Wand-Bemaßungs-Pipeline gegen Excel-Soll.

Lädt API-Key aus massenermittlung/.env, crpt Bemaßungs-Streifen pro Top,
schickt an Claude-Sonnet-4 mit dem Production-Prompt und vergleicht mit
Excel-Soll-Werten aus WA Kutzen, Koblach.

Pass-Kriterium: ≥95% Genauigkeit für mindestens 3 von 4 Tops in Haus D EG.
"""
from __future__ import annotations
import base64
import json
import re
import sys
from pathlib import Path

import fitz
import anthropic


# ─── 1. API-Key laden ───
env_path = Path(__file__).parent.parent / "massenermittlung" / ".env"
env = {}
for line in env_path.read_text().splitlines():
    if "=" in line and not line.strip().startswith("#"):
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip()
api_key = env.get("ANTHROPIC_API_KEY", "").strip()
if not api_key:
    print("FEHLER: kein ANTHROPIC_API_KEY in .env")
    sys.exit(1)
print(f"API-Key geladen ({len(api_key)} chars)")

client = anthropic.Anthropic(api_key=api_key)


# ─── 2. Production-Prompt (= api/extract.py BEMASSUNG_PROMPT) ───
BEMASSUNG_PROMPT = """Du siehst einen schmalen Bemaßungs-Streifen aus einem
oesterreichischen Bauplan (Maßstab 1:50). Bemaßungen sind als
KETTENBEMASSUNG dargestellt: Eine horizontale Linie mit kurzen vertikalen
Markern, zwischen denen die jeweiligen Wand-Längen in CENTIMETERN stehen
(z.B. "152", "300", "580").

Lies ALLE Maßzahlen in dieser Bemaßung der Reihe nach von links nach rechts
(bzw. von oben nach unten) ab. Maße aus mehreren parallelen Ketten gibst
du als separate Listen zurück.

JSON-Antwort (kein Markdown, keine Erklärung):
{
  "ketten": [
    [48, 152, 143, 543, 120, 231],
    [2, 44, 2, 301, 8, 576]
  ],
  "summe_cm_je_kette": [1237, 933],
  "konfidenz": 0.95
}

Wichtig:
- Werte sind cm-Zahlen (1-4-stellig). Niemals erfinden — nur was du klar liest.
- Wenn nur eine Kette: liefere ein einziges Array.
- Maßstabs-Code (z.B. "1:50") oder Achs-Buchstaben (O, P, Q) ignorieren."""


# ─── 3. Pro Top: 2 Bemaßungs-Streifen (N + S) bei 700 DPI ───
def crop_strip(page, x0, y0, x1, y1, dpi=700) -> bytes:
    rect = fitz.Rect(x0, y0, x1, y1)
    mat = fitz.Matrix(dpi/72, dpi/72)
    pix = page.get_pixmap(matrix=mat, clip=rect)
    return pix.tobytes("jpeg", jpg_quality=88)


def call_vision(img_bytes: bytes, top_name: str, side: str) -> dict:
    img_b64 = base64.standard_b64encode(img_bytes).decode("utf-8")
    resp = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=512,
        system=BEMASSUNG_PROMPT,
        messages=[{
            "role": "user",
            "content": [
                {"type": "image", "source": {"type": "base64",
                 "media_type": "image/jpeg", "data": img_b64}},
                {"type": "text", "text": f"Top {top_name}, Seite {side}: lies alle Maße ab."}
            ],
        }],
    )
    raw = resp.content[0].text if resp.content else "{}"
    try:
        return json.loads(raw)
    except Exception:
        m = re.search(r"\{[\s\S]*\}", raw)
        if m:
            try:
                return json.loads(m.group())
            except Exception:
                pass
    return {"_raw": raw[:200]}


# ─── 4. Test-Daten: TOP 36-38 in Kutzen-Koblach Plan ───
pdf_path = Path.home() / "Downloads/AU_WM_01 Erdgeschoss_INDEX E (3).pdf"
doc = fitz.open(pdf_path)
page = doc[0]
td = page.get_text("dict")
tops = {}
for block in td.get("blocks", []):
    if block.get("type") != 0: continue
    for line in block.get("lines", []):
        for span in line.get("spans", []):
            t = (span.get("text") or "").strip()
            if t.startswith("TOP ") and t.replace("TOP ","").isdigit():
                bb = span.get("bbox")
                tops[t] = ((bb[0]+bb[2])/2, (bb[1]+bb[3])/2)

# Excel-Soll für Haus D (Tops 36-38) EG-Teil
EXCEL_SOLL = {
    "TOP 36": {"wand_l_cm": 587, "wand_b_cm": 712},
    "TOP 37": {"wand_l_cm": 587, "wand_b_cm": 327},
    "TOP 38": {"wand_l_cm": 625, "wand_b_cm": 712},
}

# Pro TOP: südlicher Bemaßungs-Streifen
results = {}
target_tops = ["TOP 36", "TOP 37", "TOP 38"]
for top_name in target_tops:
    if top_name not in tops:
        continue
    tx, ty = tops[top_name]
    # Bemaßungsband südlich des Wohnungs-Bereiches (Y zwischen 1820 und 1920)
    sx0 = max(0, tx - 350)
    sx1 = min(page.rect.width, tx + 350)
    sy0, sy1 = 1820, 1920
    print(f"\n──── {top_name} @ ({tx:.0f},{ty:.0f}) ────")
    print(f"  Crop S: ({sx0:.0f},{sy0:.0f}) - ({sx1:.0f},{sy1:.0f}) @ 700 DPI")

    try:
        img = crop_strip(page, sx0, sy0, sx1, sy1)
        if len(img) > 4 * 1024 * 1024:
            print(f"  Bild zu groß ({len(img)/1024/1024:.1f} MB), skip")
            continue
        result = call_vision(img, top_name, "S")
        results[top_name] = result
        print(f"  Vision-Antwort: {json.dumps(result, ensure_ascii=False)[:300]}")
    except Exception as e:
        print(f"  FEHLER: {e}")
        results[top_name] = {"_error": str(e)}


# ─── 5. Genauigkeits-Vergleich ───
print(f"\n{'═'*72}")
print("Genauigkeits-Vergleich: Vision-extrahiert vs. Excel-Soll")
print(f"{'═'*72}")
print(f"{'Top':<10} {'Excel L':>10} {'Vision-Best':>15} {'Δ':>8} {'Genauigkeit':>12}")
print("─" * 60)

pass_count = 0
for top in target_tops:
    res = results.get(top, {})
    excel_l = EXCEL_SOLL[top]["wand_l_cm"]
    excel_b = EXCEL_SOLL[top]["wand_b_cm"]
    # Suche im Vision-Output den Wert, der Excel-L am nächsten ist
    all_vals = []
    for kette in res.get("ketten", []):
        all_vals.extend(kette)
    for s in res.get("summe_cm_je_kette", []) or []:
        all_vals.append(s)
    if not all_vals:
        print(f"{top:<10} {excel_l:>10} {'—':>15} {'—':>8} {'KEINE DATEN':>12}")
        continue
    best = min(all_vals, key=lambda v: abs(v - excel_l))
    delta = abs(best - excel_l)
    genauigkeit = (1 - delta / excel_l) * 100
    flag = "✓" if genauigkeit >= 95 else ""
    if genauigkeit >= 95:
        pass_count += 1
    print(f"{top:<10} {excel_l:>10} {best:>15} {delta:>+8} {genauigkeit:>11.2f}% {flag}")

print(f"\n→ {pass_count}/{len(target_tops)} Tops erreichen ≥95% Genauigkeit")
if pass_count >= len(target_tops) * 0.66:
    print("✓ Pipeline produktions-tauglich (Mehrheit ≥95%)")
else:
    print("✗ Pipeline braucht weitere Iteration")

# JSON dump
Path("/tmp/vision_e2e_results.json").write_text(json.dumps(results, indent=2, ensure_ascii=False))
print(f"\nVollständige Vision-Antworten: /tmp/vision_e2e_results.json")
