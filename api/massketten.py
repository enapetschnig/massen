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

_NUM = re.compile(r"^\d{1,4}(?:,\d)?$")             # klassisch: cm-Ganzzahl
_NUM_M = re.compile(r"^\d{1,2}(?:[.,]\d{1,2})$")    # Meter-Notation ("1.80", "2,45")


def _val(t, rx=_NUM):
    t = (t or "").strip()
    if rx.match(t):
        try:
            return float(t.replace(",", "."))
        except ValueError:
            return None
    return None


def numeric_spans(words, meter_notation=False):
    """fitz get_text('words') → [(x, y, value_cm)] der plausiblen Maß-Zahlen.

    Zwei Notationen (beide real im Korpus): cm als Ganzzahl ("55", "300" —
    Angerer/ArchiCAD, Default) und METER mit Dezimaltrenner ("1.80" — z.B.
    1762788650811_EG-Wand: ohne diese Deutung 0 Ketten → Kalibrierung tot).
    meter_notation NIE gemischt mit cm anwenden: die Meter-Deutung erzeugt aus
    Höhen-Labels ("2,00") Fake-Ketten, die den Kalibrier-Cluster kippen
    (gemessen am Angerer: ptm 27,17 → 146). Deshalb strikt als Zweitpass."""
    out = []
    for w in words:
        try:
            x, y, txt = w[0], w[1], w[4]
        except (IndexError, TypeError):
            continue
        if meter_notation:
            v = _val(txt, _NUM_M)
            v = v * 100.0 if v is not None and 0.30 <= v <= 15.0 else None
        else:
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


# ── Byte-exakte WANDFLUCHTEN aus Ketten-Snap (Produkt-Feature, Juli 2026) ─────
def sub_ketten(chains, ptm, rms_max_cm=30.0):
    """Positions-Ketten [(pos_pt, wert_cm)] → validierte Subketten
    [(b0_label_pt, [kumulative Grenz-cm], [werte_cm])].

    Die Achs-Gruppen mischen fremde Maßblöcke; Labels sind nur GROB segment-
    mittig (RMS 12-23cm bei echten Zügen). Deshalb: Split am Label-Abstand
    (≈ (v_i+v_j)/2 ± 30%+20cm), B0 nur als grobe Lage — die byte-exakte
    Struktur wird anschließend auf die Wand-Maske gesnappt."""
    import math
    k = ptm / 100.0
    out = []
    for seg in chains:
        sub, cur = [], [seg[0]]
        for (p0, v0), (p1, v1) in zip(seg, seg[1:]):
            erwartet = (v0 + v1) / 2.0 * k
            if abs((p1 - p0) - erwartet) > 0.30 * erwartet + 20 * k:
                sub.append(cur)
                cur = []
            cur.append((p1, v1))
        sub.append(cur)
        for teil in sub:
            if len(teil) < 2:
                continue
            cum, offsets = 0.0, []
            for p, v in teil:
                offsets.append(p - (cum + v / 2.0) * k)
                cum += v
            b0 = sum(offsets) / len(offsets)
            rms = math.sqrt(sum((o - b0) ** 2 for o in offsets) / len(offsets))
            if rms > rms_max_cm * k:
                continue
            grenzen_cm = [0.0]
            cum = 0.0
            for _p, v in teil:
                cum += v
                grenzen_cm.append(cum)
            out.append((b0, grenzen_cm, [v for _p, v in teil]))
    return out


def wand_fluchten(words, box, ptm, grid, W, H, cell_pt,
                  tol_m=0.035, min_lauf_m=0.4, zm=0.02):
    """Byte-exakte Wandfluchten: Maßketten-Züge auf die Wand-Maske snappen.

    → Liste {achse: 'v'|'h' (Linien-RICHTUNG), pos: pt, ok: bool} — 'v' ist
    eine vertikale Flucht (x=pos, aus h-Ketten), 'h' horizontal (y=pos).
    ok=True: die Maske hat dort eine Flächen-Kante (±tol_m, Lauf ≥min_lauf_m).
    Nur WAND-Züge (≥50% Grenzen treffen) werden geliefert — Außenanlagen-/
    Öffnungs-Züge der Polierpläne messen keine Wände (AP.01 gemessen)."""
    import vektor   # lazy (vektor importiert massketten lazy → kein Zyklus)
    bx0, bx1, by0, by1 = box
    # UNION beider Notationen (Token-Klassen disjunkt: "300" nur cm, "1.80" nur
    # Meter) — Pläne mischen sie im selben Blatt (1762788650811). Die KALIBRIERUNG
    # bleibt strikt zweipassig (Höhen-Labels kippten dort den Cluster, gemessen);
    # hier gaten Subketten-Split + Snap + Wand-Zug-Regel die Fehldeutungen.
    spans = numeric_spans(words) + numeric_spans(words, meter_notation=True)
    m3 = 3.0 * ptm
    spans = [(x, y, v) for (x, y, v) in spans
             if bx0 - m3 <= x <= bx1 + m3 and by0 - m3 <= y <= by1 + m3]
    k = ptm / 100.0
    min_lauf = int(min_lauf_m / zm)
    tol_z = max(1, int(tol_m / zm))
    out = []
    for achse in ("h", "v"):      # Ketten-Achse; Fluchten stehen QUER dazu
        # Flächen-Kanten der Maske quer zur Kette
        kanten = {}
        if achse == "h":          # h-Kette → vertikale Fluchten (x=const)
            for i in range(1, W):
                n = sum(1 for j in range(H) if grid[j * W + i] != grid[j * W + i - 1])
                if n:
                    kanten[i] = n
            base, lo, hi = bx0, bx0, bx1
        else:
            for j in range(1, H):
                n = sum(1 for i in range(W) if grid[j * W + i] != grid[(j - 1) * W + i])
                if n:
                    kanten[j] = n
            base, lo, hi = by0, by0, by1

        def kante_n(pos_pt):
            iz = int((pos_pt - base) / cell_pt)
            return max((kanten.get(iz + o, 0)
                        for o in range(-tol_z, tol_z + 1)), default=0)

        def kante_ok(pos_pt):
            return kante_n(pos_pt) >= min_lauf

        for b0_lab, grenzen_cm, _w in sub_ketten(
                vektor._chains_mit_pos(spans, achse), ptm):
            best_b0, best_hits = b0_lab, -1
            # ±60cm: Label-Offsets bis 48cm real gemessen (Angerer West-AW-Zug
            # sass ausserhalb des alten ±35cm-Fensters → Zufalls-Snap +6cm)
            for off_cm in range(-60, 61):
                b0 = b0_lab + off_cm * k
                hits = sum(1 for g in grenzen_cm if kante_ok(b0 + g * k))
                if hits > best_hits:
                    best_hits, best_b0 = hits, b0
            im_bild = [g for g in grenzen_cm
                       if lo - 0.1 * ptm <= best_b0 + g * k <= hi + 0.1 * ptm]
            if len(im_bild) < 2:
                continue
            oks = [kante_ok(best_b0 + g * k) for g in im_bild]
            if sum(oks) < 0.5 * len(im_bild):
                continue    # kein Wand-Zug
            for g, ok in zip(im_bild, oks):
                out.append({"achse": "v" if achse == "h" else "h",
                            "pos": round(best_b0 + g * k, 2), "ok": bool(ok),
                            "lauf": int(kante_n(best_b0 + g * k))})
    # DEDUPE: dieselbe Kette steht oft beidseitig des Plans (Angerer: 8 Doppel) —
    # Fluchten <2cm beisammen verschmelzen, ok=True gewinnt.
    out.sort(key=lambda f: (f["achse"], f["pos"], not f["ok"]))
    ded = []
    for f in out:
        if ded and ded[-1]["achse"] == f["achse"]                 and abs(ded[-1]["pos"] - f["pos"]) < 0.02 * ptm:
            ded[-1]["ok"] = ded[-1]["ok"] or f["ok"]
            ded[-1]["lauf"] = max(ded[-1].get("lauf", 0), f.get("lauf", 0))
            continue
        ded.append(f)
    return ded
