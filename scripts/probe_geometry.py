#!/usr/bin/env python3
"""Probe: Wandlängen pro Top-Wohnung aus PDF-Vector-Drawings ableiten.

Hintergrund (aus Session 2026-05-18):
- Die Excel-Massenermittlung Kutzen-Koblach rechnet Innenputz pro Top mit
  spezifischen Wandlängen (z.B. Top 36 EG: 5.87×2.66 + 7.12×2.66 …).
- Diese Wandlängen stehen NICHT im Text-Layer des PDFs (das wurde getestet:
  Werte wie 5.87/7.12/3.27/6.25 sind als Spans nicht vorhanden — die
  Außen-Bemaßung ist in ArchiCAD-Plänen als Vektor-Grafik gerendert).
- Mögliche Ableitung: aus den 878k Vector-Drawings die langen
  horizontalen/vertikalen Linien filtern und pro Top zuordnen.

Diese Probe macht:
  1. Alle PDF-Drawings einlesen (`page.get_drawings()`)
  2. Lange Linien (>100pt, horizontal/vertikal) extrahieren
  3. Pro Top (aus oenorm_extract.py-Ergebnis) die naheliegenden Linien sammeln
  4. Bounding-Polygon abschätzen → Wandlängen-Schätzung
  5. Vergleich gegen Excel-Soll-Werte

Status: experimentell — liefert keine 95%-Genauigkeit. Sinn ist, den
Lösungsweg zu skizzieren und Fortschritts-Hebel zu zeigen.

Aufruf: python3 scripts/probe_geometry.py [<plan.pdf>]
"""
from __future__ import annotations
import json
import sys
from collections import defaultdict
from pathlib import Path

import fitz


# ════════════════════════════════════════════════════════════════════════
# 1. Vector-Linien extrahieren
# ════════════════════════════════════════════════════════════════════════
def extract_long_lines(page, min_length_pt: float = 100.0) -> list[dict]:
    """Sammle alle langen horizontalen/vertikalen Linien."""
    drawings = page.get_drawings()
    out = []
    for d in drawings:
        if d.get("type") != "s":
            continue
        color = d.get("color") or (0, 0, 0)
        width = d.get("width") or 0
        is_black = max(color) < 0.20
        if not is_black:
            continue
        for itm in d.get("items", []):
            if itm[0] != "l":
                continue
            p1, p2 = itm[1], itm[2]
            dx = abs(p1.x - p2.x)
            dy = abs(p1.y - p2.y)
            length = (dx * dx + dy * dy) ** 0.5
            if length < min_length_pt:
                continue
            is_h = dy < 0.5
            is_v = dx < 0.5
            if not (is_h or is_v):
                continue
            out.append({
                "p1": (p1.x, p1.y),
                "p2": (p2.x, p2.y),
                "length_pt": length,
                "width": width,
                "is_horizontal": is_h,
            })
    return out


# ════════════════════════════════════════════════════════════════════════
# 2. Linien pro Top zuordnen (auf Raum-Bounding-Box + Margen)
# ════════════════════════════════════════════════════════════════════════
def lines_per_top(rooms: list[dict], lines: list[dict],
                  margin_pt: float = 200.0) -> dict[str, list[dict]]:
    by_top: dict[str, list[dict]] = defaultdict(list)
    # Raumzentren pro Top sammeln → Boundingbox
    top_bbox: dict[str, tuple[float, float, float, float]] = {}
    by_room_top = defaultdict(list)
    for r in rooms:
        if r.get("wohnung"):
            by_room_top[r["wohnung"]].append(r)
    for top, rs in by_room_top.items():
        xs = [r["cx"] for r in rs]
        ys = [r["cy"] for r in rs]
        top_bbox[top] = (min(xs) - margin_pt, min(ys) - margin_pt,
                         max(xs) + margin_pt, max(ys) + margin_pt)

    for line in lines:
        for top, (x0, y0, x1, y1) in top_bbox.items():
            # Linie liegt im Top-Bereich, wenn beide Endpunkte drin sind
            (lx1, ly1) = line["p1"]
            (lx2, ly2) = line["p2"]
            mx = (lx1 + lx2) / 2.0
            my = (ly1 + ly2) / 2.0
            if x0 <= mx <= x1 and y0 <= my <= y1:
                by_top[top].append(line)
    return dict(by_top), top_bbox


# ════════════════════════════════════════════════════════════════════════
# 3. Maßstab-Heuristik: pt/m aus Plan-Größe
# ════════════════════════════════════════════════════════════════════════
def pt_per_meter(massstab: str | None, page_w_pt: float) -> float:
    """Bei A0 print + Maßstab 1:50 sind real ca. 60m × 42m → pt/m ≈ page/real."""
    # Annahme: Plan-Aufmessungs-Breite real ≈ ⅔ der Plan-pt-Breite (Rest = Schriftfeld, Bemaßung)
    if massstab == "1:50":
        return 200.0 / 1.81  # gemessener Faktor aus Kutzen-Koblach (Top 36 BBox 376pt ≈ 2m × 1.81 = 3.4m)
    if massstab == "1:100":
        return 100.0 / 1.81
    return 110.0  # Fallback


# ════════════════════════════════════════════════════════════════════════
# 4. Wandlängen-Schätzung pro Top
# ════════════════════════════════════════════════════════════════════════
def estimate_wall_lengths(by_top: dict, top_bbox: dict, ppm: float) -> dict:
    """Pro Top: H/V-Linien sammeln, längste Außen-Linien pro Achse summieren.
    Heuristik: pro Top sind die LÄNGSTEN HORIZONTALEN + LÄNGSTEN VERTIKALEN
    Linien die Außenkanten der Wohnung."""
    out = {}
    for top, lines in by_top.items():
        h_lines = sorted([l for l in lines if l["is_horizontal"]],
                         key=lambda l: -l["length_pt"])[:8]
        v_lines = sorted([l for l in lines if not l["is_horizontal"]],
                         key=lambda l: -l["length_pt"])[:8]
        # Länge in Meter
        h_m = [l["length_pt"] / ppm for l in h_lines]
        v_m = [l["length_pt"] / ppm for l in v_lines]
        out[top] = {
            "n_h": len(h_lines),
            "n_v": len(v_lines),
            "h_lengths_m": [round(x, 2) for x in h_m],
            "v_lengths_m": [round(x, 2) for x in v_m],
        }
    return out


# ════════════════════════════════════════════════════════════════════════
# Main
# ════════════════════════════════════════════════════════════════════════
def main():
    pdf_path = Path(sys.argv[1]).expanduser() if len(sys.argv) > 1 else \
        Path.home() / "Downloads/AU_WM_01 Erdgeschoss_INDEX E (3).pdf"

    # Lade Räume aus oenorm_extract.py-Output
    rooms_json = Path("/tmp/kk_oenorm.json")
    if not rooms_json.exists():
        print(f"Fehlt: {rooms_json}. Erst scripts/oenorm_extract.py laufen lassen.")
        sys.exit(1)
    data = json.loads(rooms_json.read_text())
    rooms = data["rooms"]
    massstab = data.get("massstab")
    pw = data["page_size_pt"][0]

    # PDF öffnen
    doc = fitz.open(pdf_path)
    page = doc[0]

    print(f"PDF: {pdf_path.name}  ({pw:.0f}pt breit, Maßstab {massstab})")

    lines = extract_long_lines(page, min_length_pt=80)
    print(f"Lange H/V-Linien (>80pt, schwarz): {len(lines)}")

    by_top, top_bbox = lines_per_top(rooms, lines, margin_pt=250)

    ppm = pt_per_meter(massstab, pw)
    print(f"Maßstab-Schätzung: {ppm:.1f} pt/m")

    estim = estimate_wall_lengths(by_top, top_bbox, ppm)

    print(f"\n{'═'*72}\nWandlängen-Schätzung pro Top (experimentell)\n{'═'*72}")
    EXCEL_REFERENCE = {  # nur EG-Teil von Haus D laut Excel-Detail
        "TOP 36": {"L": 5.87, "B": 7.12},
        "TOP 37": {"L": 5.87, "B": 3.27},
        "TOP 38": {"L": 6.25, "B": 7.12},  # plus Zwischenwand 5.79
    }
    for top in sorted(estim.keys()):
        e = estim[top]
        ref = EXCEL_REFERENCE.get(top)
        print(f"\n{top}:")
        print(f"  Längste H-Linien (m): {e['h_lengths_m'][:5]}")
        print(f"  Längste V-Linien (m): {e['v_lengths_m'][:5]}")
        if ref:
            print(f"  Excel-Referenz:        L={ref['L']}  B={ref['B']}")

    print(f"\n{'─'*72}")
    print("Hinweis: Diese Probe ist HEURISTISCH. Für Excel-1:1-Match (≥95%) müssen")
    print("  (a) Wandlinien pro Wohnung sauber polygonisiert werden,")
    print("  (b) Doppellinien (Wand-Außenkante + Wand-Innenkante) zu EINER Wand")
    print("      zusammengefasst werden, und")
    print("  (c) Tür-/Fensteröffnungen in den Wandsegmenten erkannt werden.")
    print("Das ist eine eigene Pipeline-Iteration (1-2 Tage Arbeit).")


if __name__ == "__main__":
    main()
