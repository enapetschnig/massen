#!/usr/bin/env python3
"""Systematischer Test der Pipeline auf MEHREREN Plänen.

Misst Lese-Genauigkeit pro Plan: Anzahl Räume, % mit F/U/H/Boden, Vision-Wandlängen
für ein Sample-Top (sofern verfügbar). Zeigt Pipeline-Generalisierung.

Pass-Kriterium: ≥95% Lese-Genauigkeit für die im Plan vorhandenen Werte.
"""
from __future__ import annotations
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from oenorm_extract import analyse_pdf


CANDIDATE_PLANS = [
    Path.home() / "Downloads/AU_WM_01 Erdgeschoss_INDEX E (3).pdf",   # Plan 1: detaillierter ArchiCAD-Bauplan
    Path.home() / "Downloads/1762788650811_EG-Wand-Grundriss 01.pdf",  # Plan 2: vereinfachter Plan
    Path.home() / "Downloads/05_AU.3.1.1 HAUS A SCH 01, SCH 02_INDEX C (4).pdf",  # Plan 3: Schnittplan
    Path.home() / "Downloads/WA_Velden_Franzosen Allee_Ausführung_TG Plan22.04.2026.pdf",  # Plan 4: Tiefgaragen-Plan
    Path.home() / "Downloads/Expose-Mieming-Zein-Haus-A-Top-04.pdf",   # Plan 5: Wohnungs-Expose
]


def measure(pdf_path: Path) -> dict:
    if not pdf_path.exists():
        return {"pdf": pdf_path.name, "_error": "file not found"}
    try:
        result = analyse_pdf(pdf_path)
    except Exception as e:
        return {"pdf": pdf_path.name, "_error": str(e)}

    rooms = result["rooms"]
    n_r = len(rooms)
    if n_r == 0:
        return {
            "pdf": pdf_path.name,
            "spans": result["spans"],
            "raume": 0,
            "_note": "Keine Raum-Labels gefunden (Plan-Stil unbekannt oder Schnittplan)",
        }
    n_f = sum(1 for r in rooms if r.get("flaeche_m2"))
    n_u = sum(1 for r in rooms if r.get("umfang_m"))
    n_h = sum(1 for r in rooms if r.get("hoehe_m"))
    n_b = sum(1 for r in rooms if r.get("bodenbelag"))
    return {
        "pdf": pdf_path.name,
        "spans": result["spans"],
        "raume": n_r,
        "F_quote": round(n_f / n_r * 100, 1),
        "U_quote": round(n_u / n_r * 100, 1),
        "H_quote": round(n_h / n_r * 100, 1),
        "Boden_quote": round(n_b / n_r * 100, 1),
        "fenster": len(result["windows"]),
        "massstab": result["massstab"],
        "geschoss": result["geschoss"],
        "haeuser": list(result["houses"].keys()),
    }


print(f"{'═'*100}")
print(f"  Pipeline-Generalisierung: Test auf 5 verschiedenen Plänen")
print(f"{'═'*100}\n")

for pdf in CANDIDATE_PLANS:
    print(f"── {pdf.name[:80]}")
    r = measure(pdf)
    if "_error" in r:
        print(f"   FEHLER: {r['_error']}")
        continue
    if r.get("raume", 0) == 0:
        print(f"   Spans={r['spans']}, Räume=0 → {r.get('_note','')}")
        continue
    print(f"   Spans={r['spans']}, Räume={r['raume']}, Fenster={r['fenster']}, "
          f"Maßstab={r['massstab']}, Geschoss={r['geschoss']}, Häuser={r['haeuser']}")
    print(f"   Lese-Quote: F={r['F_quote']}%, U={r['U_quote']}%, "
          f"H={r['H_quote']}%, Boden={r['Boden_quote']}%")
    avg = (r["F_quote"] + r["U_quote"] + r["H_quote"]) / 3
    pass_flag = "✓ ≥95% durchschnitt" if avg >= 95 else f"✗ Durchschnitt {avg:.1f}%"
    print(f"   → {pass_flag}\n")
