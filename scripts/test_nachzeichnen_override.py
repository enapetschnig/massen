#!/usr/bin/env python3
"""Safety-Guard für den Nachzeichnen→Override→Materialliste-Pfad (Stage 2).

Die Nachzeichnen-Korrektur schreibt eine wand_anteil_*-Verteilung ins
materialliste_override. Dieser Test sichert ab, dass dieser Override-Pfad
NUR die Mauerwerks-Positionen (HLZ) verändert und die validierten Nicht-Wand-
Positionen (Bodenplatte, Decke, Frostschürze …) EXAKT unberührt lässt — d.h. eine
Nutzer-Korrektur am Wand-Overlay kann die gegen die echte Polier-Liste validierten
13 Positionen nicht versehentlich regressieren.

Lauf: massenermittlung/venv/bin/python3 scripts/test_nachzeichnen_override.py
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "api"))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

from materialliste import build_materialliste
import test_materialliste_angerer as A   # Fixtures wiederverwenden


def _positionen(ml):
    """flach: {(bauteil, material): menge}."""
    out = {}
    for bauteil, lst in (ml.get("bauteile") or {}).items():
        for p in lst:
            out[(bauteil, p["material"])] = p["menge"]
    return out


def run():
    ok = True
    base = build_materialliste(A.ROOMS, A.WINDOWS, A.BAUDATEN, geschoss="EG",
                               tueren=A.TUEREN, gemessen=A.GEMESSEN,
                               wand_verteilung=A.WAND_VERTEILUNG)
    # Eine plausible Nachzeichnen-Korrektur: mehr 50cr außen, weniger 38; innen 12-lastig.
    override = {
        "wand_anteil_50cm": 88.0, "wand_anteil_38cm": 7.0, "wand_anteil_25cm_aussen": 5.0,
        "wand_anteil_25cm_innen": 20.0, "wand_anteil_20cm": 25.0, "wand_anteil_12cm": 55.0,
    }
    corr = build_materialliste(A.ROOMS, A.WINDOWS, A.BAUDATEN, geschoss="EG",
                               tueren=A.TUEREN, gemessen=A.GEMESSEN,
                               wand_verteilung=A.WAND_VERTEILUNG, override=override)

    pb, pc = _positionen(base), _positionen(corr)

    # 1) NICHT-Mauerwerk-Positionen müssen IDENTISCH sein (Override darf sie nicht berühren)
    nicht_wand_geaendert = []
    for key in set(pb) | set(pc):
        bauteil = key[0]
        if "mauerwerk" in bauteil.lower():
            continue
        if abs((pb.get(key) or 0) - (pc.get(key) or 0)) > 1e-6:
            nicht_wand_geaendert.append((key, pb.get(key), pc.get(key)))
    if nicht_wand_geaendert:
        ok = False
        print(f"  ✗ {len(nicht_wand_geaendert)} NICHT-Wand-Position(en) durch Verteilungs-Override verändert:")
        for k, a, b in nicht_wand_geaendert[:8]:
            print(f"      {k[0]}/{k[1]}: {a} → {b}")
    else:
        print("  ✓ Verteilungs-Override lässt ALLE Nicht-Wand-Positionen exakt unberührt")

    # 2) Die Mauerwerks-Verteilung muss sich tatsächlich geändert haben (Override greift)
    mw_base = {k[1]: v for k, v in pb.items() if "mauerwerk" in k[0].lower() and "hlz" in k[1].lower()}
    mw_corr = {k[1]: v for k, v in pc.items() if "mauerwerk" in k[0].lower() and "hlz" in k[1].lower()}
    if mw_base == mw_corr:
        ok = False
        print(f"  ✗ Mauerwerk unverändert — Override hat NICHT gegriffen: {mw_corr}")
    else:
        print(f"  ✓ Mauerwerk-Verteilung reagiert auf den Override (HLZ-Positionen geändert)")

    # 3) Ohne Override bleibt Angerer in Toleranz (Baseline = die validierten 13 Positionen).
    #    A.run() nutzt Exit-Code-Semantik: 0 = alle in Toleranz, 1 = Regression.
    if A.run() != 0:
        ok = False
        print("  ✗ Baseline-Angerer (ohne Override) NICHT in Toleranz")
    else:
        print("  ✓ Baseline-Angerer (ohne Override) weiter in Toleranz")

    print("-" * 64)
    print("OK — Nachzeichnen-Verteilungs-Override ist bounded (nur Wand, kein Kollateral)."
          if ok else "FEHLER — siehe oben.")
    return ok


if __name__ == "__main__":
    sys.exit(0 if run() else 1)
