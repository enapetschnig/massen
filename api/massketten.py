"""Maßketten-Reader (Text-Layer) — byte-exakte Gebäude-Geometrie ohne Vision.

Österreichische Einreichpläne tragen die Außenmaße als KETTENBEMASSUNG, und
diese Maßzahlen stehen (anders als oft angenommen) im PDF-TEXT-LAYER, nicht nur
als Vektor-Grafik. Wir lesen sie byte-exakt und rekonstruieren die Gebäude-
Bounding-Box (gemauerte Hülle):

  1. Numerische Maß-Spans (cm) sammeln.
  2. In Ketten clustern: gleiche y = horizontale Kette (Breite),
     gleiche x = vertikale Kette (Tiefe). Segment-Summe je Kette = Fassaden-Länge.
  3. Die (Breite, Tiefe) wählen, deren Rechteck-Fläche zur BYTE-EXAKTEN
     Grundfläche passt (Bounding ~1.05–1.15× Footprint) — so wird das GEBÄUDE
     vom Lageplan/Schnitt unterschieden, ohne Plan-spezifische Regionen.
  4. Wiederholte Fassaden-Totals (eine Kette erscheint mehrfach parallel) sind
     ein starkes Echtheits-Signal.

Ergebnis ist STABIL (kein Vision-Rauschen) und byte-exakt → ideale primäre
Umfang-Quelle für die gemauerte Hülle. GRENZE: misst die Hülle, nicht die
Bodenplatten-Kante unter angebauten überdachten Bereichen (die steht nur im
Fundament-/Polierplan).
"""
from __future__ import annotations
import re
from collections import defaultdict, Counter

_NUM = re.compile(r"^\d{1,4}(?:,\d)?$")


def _val(t):
    t = (t or "").strip()
    if _NUM.match(t):
        try:
            return float(t.replace(",", "."))
        except ValueError:
            return None
    return None


def numeric_spans(words):
    """fitz get_text('words') → [(x, y, value_cm)] der plausiblen Maß-Zahlen."""
    out = []
    for w in words:
        try:
            x, y, txt = w[0], w[1], w[4]
        except (IndexError, TypeError):
            continue
        v = _val(txt)
        if v is not None and 5 <= v <= 1500:   # cm-Maße einer Außenkette
            out.append((round(float(x), 1), round(float(y), 1), v))
    return out


def _chain_sums(spans, axis, tol=6.0):
    """Ketten entlang einer Achse clustern; je Kette die Segment-Summe (cm).
    axis='h' → gruppiere nach y (horizontale Kette = Breite)."""
    groups = defaultdict(list)
    for x, y, v in spans:
        key = round((y if axis == "h" else x) / tol) * tol
        groups[key].append((x if axis == "h" else y, v))
    sums = []
    for seg in groups.values():
        if len(seg) < 2:
            continue
        s = sum(v for _, v in seg)
        if 300 <= s <= 6000:   # 3–60 m Fassade
            sums.append(round(s, 1))
    return sums


def reconstruct_bbox(spans, footprint_m2, tol=6.0):
    """Byte-exakte Gebäude-Bounding-Box aus den Maßketten.

    spans: [(x_pt, y_pt, value_cm)] (siehe numeric_spans)
    footprint_m2: byte-exakte Grundfläche (Σ Innenraum-Fläche) als Anker.
    → {breite_m, tiefe_m, umfang_m, flaeche_m2, h_rep, v_rep} oder None.
    """
    if not spans or not footprint_m2 or footprint_m2 <= 0:
        return None
    H = _chain_sums(spans, "h", tol)
    V = _chain_sums(spans, "v", tol)
    if not H or not V:
        return None
    hc, vc = Counter(H), Counter(V)
    target = footprint_m2 * 1.07 * 10000.0   # Ziel-Fläche in cm² (Bounding ~1.07× Footprint)
    lo, hi = footprint_m2 * 0.95 * 10000.0, footprint_m2 * 1.70 * 10000.0
    best = None
    for hw, hn in hc.items():
        for vt, vn in vc.items():
            area = hw * vt
            if not (lo <= area <= hi):
                continue
            # näher an Ziel-Fläche + Bonus für wiederholte (echte) Fassaden-Totals
            score = abs(area - target) / target - 0.15 * (hn + vn)
            if best is None or score < best[0]:
                best = (score, hw, vt, hn, vn)
    if not best:
        return None
    _, hw, vt, hn, vn = best
    # Seiten-Plausi (EFH 4–60 m)
    if not (400 <= hw <= 6000 and 400 <= vt <= 6000):
        return None
    return {
        "breite_m": round(hw / 100.0, 2),
        "tiefe_m": round(vt / 100.0, 2),
        "umfang_m": round(2 * (hw + vt) / 100.0, 2),
        "flaeche_m2": round(hw * vt / 10000.0, 2),
        "h_rep": hn, "v_rep": vn,
    }
