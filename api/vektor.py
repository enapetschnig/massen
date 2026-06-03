"""Vektor-"Nachzeichnen"-Pipeline — Phase 0: Extraktion + Maßstab-Kalibrierung (BEWEIS).

LOG-ONLY. Greift NICHT in die Auswertung ein. Hinter VEKTOR_PASS (Default AUS) gedacht.
Zweck (aus dem Design-Workflow): BEVOR die volle Pipeline gebaut wird, empirisch
beweisen, ob aus den PDF-Vektoren ein STABILER pt→m-Faktor ableitbar ist und ob die
Wand-Signaturen (parallele Linienpaare) saubere Stärken-Cluster ergeben. Der Maßstab
ist der Single-Point-of-Failure: ist pt→m um X% falsch, ist ALLES um X% falsch.

Kein Anspruch auf Vollständigkeit — das ist der Mess-/Beweis-Schritt.
"""
import re
from collections import defaultdict

RASTER_MIN_PFADE = 500     # weniger Vektor-Pfade → Scan/Raster → Vektor-Pipeline n/a
ACHS_TOL_PT = 0.6          # |dx| oder |dy| darunter = achsparallel


# ── Vektor-Extraktion ────────────────────────────────────────────────────────
def _drawings(page):
    """Roh-Pfade als (segmente, fills). segmente: (x0,y0,x1,y1,width,grau). fills: (bbox,grau)."""
    segmente, fills = [], []
    n_pfade = 0
    for p in page.get_drawings():
        n_pfade += 1
        w = p.get("width") or 0.0
        col = p.get("color")            # stroke-Farbe (r,g,b) 0..1 oder None
        grau = round(sum(col) / 3.0, 3) if col else None   # None = „kein Strich"/füllt
        typ = p.get("type")             # 's' stroke, 'f' fill, 'fs' beides
        for it in p.get("items", []):
            k = it[0]
            if k == "l":
                a, b = it[1], it[2]
                segmente.append((a.x, a.y, b.x, b.y, round(w, 3), grau))
            elif k == "re":
                r = it[1]
                if typ and "f" in typ:
                    fcol = p.get("fill")
                    fgrau = round(sum(fcol) / 3.0, 3) if fcol else 0.0
                    fills.append((r.x0, r.y0, r.x1, r.y1, fgrau))
                segmente += [(r.x0, r.y0, r.x1, r.y0, round(w, 3), grau),
                             (r.x1, r.y0, r.x1, r.y1, round(w, 3), grau),
                             (r.x1, r.y1, r.x0, r.y1, round(w, 3), grau),
                             (r.x0, r.y1, r.x0, r.y0, round(w, 3), grau)]
            # 'c' (Bögen) bewusst ignoriert in Phase 0
    return segmente, fills, n_pfade


def _achse(s):
    dx, dy = abs(s[2] - s[0]), abs(s[3] - s[1])
    if dy <= ACHS_TOL_PT and dx > ACHS_TOL_PT:
        return "h"
    if dx <= ACHS_TOL_PT and dy > ACHS_TOL_PT:
        return "v"
    return None


def _laenge(s):
    return ((s[2] - s[0]) ** 2 + (s[3] - s[1]) ** 2) ** 0.5


def layer_profil(segmente):
    """Pro (grau,width)-Layer: Segment-Anzahl, achsparalleler Anteil, größte Span.
    Zeigt, ob ein Layer die ARCHITEKTUR ist (viele achsparallele, lange Linien) oder
    Schraffur/Bemaßung/Text (kurz, viele, oder schräg)."""
    prof = defaultdict(lambda: {"n": 0, "hv": 0, "max_len": 0.0, "sum_len": 0.0})
    for s in segmente:
        key = (s[5], s[4])   # (grau, width)
        p = prof[key]
        p["n"] += 1
        L = _laenge(s)
        p["sum_len"] += L
        if L > p["max_len"]:
            p["max_len"] = L
        if _achse(s):
            p["hv"] += 1
    out = []
    for (grau, width), p in prof.items():
        out.append({"grau": grau, "width": width, "n": p["n"],
                    "hv_anteil": round(p["hv"] / p["n"], 2) if p["n"] else 0,
                    "max_len_pt": round(p["max_len"], 1),
                    "sum_len_pt": round(p["sum_len"], 1)})
    out.sort(key=lambda d: -d["n"])
    return out


# ── Maßstab-Kalibrierung (regressionsbasiert je Maßkette) ─────────────────────
def _median(xs):
    s = sorted(xs)
    n = len(s)
    return s[(n - 1) // 2] if n else None


def _chains_mit_pos(spans, axis, tol=6.0):
    """Wie massketten._chain_sums, aber behält Positionen: liefert je Kette eine
    nach Position sortierte Liste [(pos_pt, value_cm)]. axis='h' → Kette entlang x."""
    groups = defaultdict(list)
    for x, y, v in spans:
        key = round((y if axis == "h" else x) / tol) * tol
        pos = x if axis == "h" else y
        groups[key].append((pos, v))
    chains = []
    for seg in groups.values():
        if len(seg) >= 3:                  # min. 3 Maße → tragfähige Regression
            seg.sort()
            if 100 <= sum(v for _, v in seg) <= 8000:   # 1–80 m
                chains.append(seg)
    return chains


def _regress_ptcm(chain):
    """Lineare Regression Position(pt) gegen kumulierte Maße(cm) → Steigung = pt/cm.
    Robust gegen Zahl-Platzierung (Mitte/Ende verschiebt nur den Achsenabschnitt)."""
    cum, xs, ys = 0.0, [], []
    for pos, v in chain:
        cum += v
        xs.append(cum)        # cm (unabhängige Größe)
        ys.append(pos)        # pt (abhängige Größe)
    n = len(xs)
    mx = sum(xs) / n
    my = sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    sxy = sum((xs[i] - mx) * (ys[i] - my) for i in range(n))
    if sxx <= 1e-6:
        return None, 0.0
    slope = sxy / sxx                       # pt/cm
    # R² als Güte
    ss_tot = sum((y - my) ** 2 for y in ys)
    pred = [slope * (xs[i] - mx) + my for i in range(n)]
    ss_res = sum((ys[i] - pred[i]) ** 2 for i in range(n))
    r2 = 1 - ss_res / ss_tot if ss_tot > 1e-6 else 0.0
    return abs(slope), r2


def _label_ptm(massstab_label):
    """Theoretischer pt/m aus dem Maßstab-Label: 1:M → 1 m real = (100/M) cm Papier ×
    (72/2.54) pt/cm = 2835/M pt/m. Nur grober Anker (CAD-Export ist nicht papier-wahr)."""
    if not massstab_label:
        return None
    m = re.search(r"1\s*:\s*(\d+)", str(massstab_label))
    return round(2835.0 / int(m.group(1)), 2) if m else None


def _dominant_cluster(slopes_ptm, label_ptm=None, rel_tol=0.05):
    """RANSAC-artig: das pt/m, auf das die MEISTEN Maßketten ±rel_tol fallen (der echte
    Grundriss-Maßstab), statt der Median über alle (der mehrere Maßstäbe/Lagepläne mischt).
    Probiert jeden Slope + das Label als Zentrum, nimmt das mit der größten Gefolgschaft."""
    if not slopes_ptm:
        return None, []
    kandidaten = list(slopes_ptm) + ([label_ptm] if label_ptm else [])
    best_c, best_m = None, []
    for c in kandidaten:
        members = [s for s in slopes_ptm if abs(s - c) <= rel_tol * c]
        if len(members) > len(best_m):
            best_c, best_m = c, members
    return best_c, best_m


def kalibriere(words, massstab_label=None):
    """pt→m über den DOMINANTEN Maßketten-Cluster + Label-Kreuzcheck.
    Liefert {ptm_konsens, streuung_pct, n_ketten_tragfaehig, methoden, tragfaehig}."""
    try:
        from massketten import numeric_spans
        spans = numeric_spans(words)
    except Exception:
        spans = []
    chains = _chains_mit_pos(spans, "h") + _chains_mit_pos(spans, "v")
    slopes = []     # pt/m je Kette (nur R² ≥ 0.98 = wirklich lineare Kette)
    for ch in chains:
        s, r2 = _regress_ptcm(ch)
        if s and r2 >= 0.98 and s > 0.01:
            slopes.append(s * 100.0)
    label_ptm = _label_ptm(massstab_label)
    center, members = _dominant_cluster(slopes, label_ptm)
    ptm = _median(members) if members else None
    support = len(members)
    # Streuung INNERHALB des dominanten Clusters (nicht über alle Maßstäbe)
    streuung = None
    if support >= 3 and ptm:
        absdev = sorted(abs(s - ptm) for s in members)
        mad = absdev[(len(absdev) - 1) // 2]
        streuung = round((mad / ptm) * 100, 1)
    # Label-Übereinstimmung als Vertrauens-Booster
    label_match = bool(label_ptm and ptm and abs(ptm - label_ptm) / label_ptm <= 0.15)
    # Tragfähig: genug Maßketten einig ODER kleiner Cluster, der das Label bestätigt
    tragfaehig = bool(ptm and (support >= 5 or (support >= 2 and label_match)))
    return {"ptm_konsens": round(ptm, 2) if ptm else None,
            "streuung_pct": streuung, "n_ketten_tragfaehig": support,
            "n_ketten_gesamt": len(slopes), "label_ptm": label_ptm,
            "label_match": label_match, "tragfaehig": tragfaehig}


# ── Phase-0-Gesamtreport (ein Plan) ──────────────────────────────────────────
def analysiere_seite(page, massstab_label=None):
    segmente, fills, n_pfade = _drawings(page)
    if n_pfade < RASTER_MIN_PFADE:
        return {"quelle": "raster", "n_pfade": n_pfade, "tragfaehig": False}
    prof = layer_profil(segmente)
    words = page.get_text("words")
    kal = kalibriere(words, massstab_label)
    n_hv = sum(1 for s in segmente if _achse(s))
    return {
        "quelle": "vektor", "n_pfade": n_pfade, "n_segmente": len(segmente),
        "n_achsparallel": n_hv, "n_fills": len(fills),
        "top_layer": prof[:6],
        "kalibrierung": kal,
        "tragfaehig": kal["tragfaehig"],
    }
