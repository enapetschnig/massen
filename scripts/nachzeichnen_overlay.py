#!/usr/bin/env python3
"""NACHZEICHNEN-OVERLAY — visuelle, prüfbare Wand-Rekonstruktion aus den PDF-Vektoren.

Zeichnet die erkannten Wände farbcodiert nach Stärke (rot=50, orange=38, blau=25,
grün=20, lila=12cm) mit Länge beschriftet auf den echten Plan. Das ist die
"Nachzeichnen"-Ansicht zum NACHVOLLZIEHEN (sieht der Nutzer, was die KI als Wand
gelesen hat) und als Grundlage zum KORRIGIEREN (welche Linie ist keine Wand etc).

Nutzt das Schraffur-Gate (echte Maurer-Wände sind innen poché-schraffiert, Bemaßungs-/
Terrassen-/Grundstücks-Kanten nicht) → weniger Geister im Bild.

Lauf: massenermittlung/venv/bin/python3 scripts/nachzeichnen_overlay.py [plan.pdf] [out.png]
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "api"))

import fitz
import vektor
from PIL import Image, ImageDraw, ImageFont

LEG = [50, 38, 25, 20, 12]
FARBE = {50: (220, 30, 30), 38: (240, 140, 0), 25: (30, 80, 220),
         20: (20, 160, 60), 12: (150, 40, 200)}
RAUM_WORTE = ["Wohnraum", "Waschen", "Bad", "WC", "Flur", "Zimmer", "Küche", "Geräte",
              "Schlafen", "Wohnen", "Diele", "Abstell", "Gang", "Kind", "Eltern"]


def _massstab(page):
    m = re.search(r"1\s*:\s*(\d{2,4})", page.get_text())
    return f"1:{m.group(1)}" if m else None


def _eg_box(page, ptm):
    W, H = page.rect.width, page.rect.height
    pos = [(w[0], w[1]) for w in page.get_text("words")
           if any(r.lower() in w[4].lower() for r in RAUM_WORTE)
           and 0.02 * W <= w[0] <= 0.55 * W and 0.04 * H <= w[1] <= 0.6 * H]
    return vektor._view_bbox(pos, ptm, marge_m=4.0, radius_m=13.0)


def render(pdf, out):
    d = fitz.open(pdf)
    page = max(d, key=lambda p: p.rect.width * p.rect.height)
    ptm = vektor.kalibriere(page.get_text("words"), _massstab(page)).get("ptm_konsens")
    if not ptm:
        print("Keine Kalibrierung — Abbruch.")
        return
    box = _eg_box(page, ptm)
    if not box:
        print("Keine EG-Grundriss-Box gefunden (zu wenig Raum-Labels).")
        return
    bx0, bx1, by0, by1 = box
    segs, _f, _n = vektor._drawings(page)
    inb = lambda s: bx0 <= (s[0] + s[2]) / 2 <= bx1 and by0 <= (s[1] + s[3]) / 2 <= by1
    arch = [s for s in segs if (s[5] is None or s[5] < 0.45)
            and vektor._laenge(s) / ptm > 0.5 and inb(s)]
    hatch = [s for s in vektor.hatch_segmente(segs) if inb(s)]
    waende = vektor.wand_paare(arch, ptm, min_len_m=0.6, legende_dicken=LEG,
                               hatch=hatch, min_hatch_dichte=1.0, mit_geometrie=True)

    SC = 3.0
    pix = page.get_pixmap(matrix=fitz.Matrix(SC, SC), clip=fitz.Rect(bx0, by0, bx1, by1))
    img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples).convert("RGBA")
    img = Image.alpha_composite(img, Image.new("RGBA", img.size, (255, 255, 255, 90)))
    dr = ImageDraw.Draw(img, "RGBA")
    try:
        font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 13)
    except Exception:
        font = ImageFont.load_default()
    px = lambda x, y: ((x - bx0) * SC, (y - by0) * SC)

    ges = {}
    for w in waende:
        sn = vektor._snap_legende(w["dicke_cm"], LEG, 2.0)
        if not sn:
            continue
        ges[sn] = ges.get(sn, 0) + w["laenge_m"]
        col = FARBE.get(sn, (120, 120, 120))
        x0, y0 = px(w["x0"], w["y0"])
        x1, y1 = px(w["x1"], w["y1"])
        dr.line([x0, y0, x1, y1], fill=col + (230,), width=max(3, int(sn / 100 * ptm * SC)))
        dr.text(((x0 + x1) / 2 + 4, (y0 + y1) / 2 - 7), f"{sn}·{w['laenge_m']:.1f}m",
                fill=(0, 0, 0, 255), font=font)

    dr.rectangle([8, 8, 252, 8 + len([t for t in LEG if t in ges]) * 22 + 30],
                 fill=(255, 255, 255, 235), outline=(0, 0, 0, 255))
    dr.text((16, 12), "Nachgezeichnete Wände (Vektor)", fill=(0, 0, 0, 255), font=font)
    ly = 34
    for t in LEG:
        if t not in ges:
            continue
        dr.rectangle([16, ly + 2, 34, ly + 14], fill=FARBE[t] + (255,))
        dr.text((42, ly), f"HLZ {t}cm: Σ {ges[t]:.1f} m", fill=(0, 0, 0, 255), font=font)
        ly += 22
    img.convert("RGB").save(out, quality=92)
    print(f"{len(waende)} Wände · Σ je Stärke {dict((k, round(v, 1)) for k, v in ges.items())}")
    print(f"→ {out}")


if __name__ == "__main__":
    pdf = sys.argv[1] if len(sys.argv) > 1 else os.path.expanduser(
        "~/Downloads/A-5_Einreichplan_Alfred-Angerer_36_25_Index 0 (1).pdf")
    out = sys.argv[2] if len(sys.argv) > 2 else "/tmp/nachzeichnen.png"
    render(pdf, out)
