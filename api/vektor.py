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
    def _slopes(meter_notation):
        try:
            from massketten import numeric_spans
            spans = numeric_spans(words, meter_notation=meter_notation)
        except Exception:
            return []
        chains = _chains_mit_pos(spans, "h") + _chains_mit_pos(spans, "v")
        out = []    # pt/m je Kette (nur R² ≥ 0.98 = wirklich lineare Kette)
        for ch in chains:
            s, r2 = _regress_ptcm(ch)
            if s and r2 >= 0.98 and s > 0.01:
                out.append(s * 100.0)
        return out

    slopes = _slopes(False)
    if not slopes:
        # ZWEITPASS Meter-Notation ("1.80" statt "180") — strikt nur wenn der
        # cm-Pass NICHTS liefert: gemischt kippen Höhen-Labels ("2,00") den
        # Cluster (gemessen: Angerer 27,17 → 146). 1762788650811_EG-Wand
        # kalibriert damit exakt auf 1:50 (56,69 ≈ 2835/50).
        slopes = _slopes(True)
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
    # LABEL-FALLBACK: zu wenige verwertbare Ketten (0-1), aber klarer Maßstab-Label
    # ("1:50" → 2835/50 pt/m) → das Label-ptm nutzen. Ehrlich UNBESTÄTIGT (tragfaehig
    # bleibt False) — erlaubt die Planansicht (Wände sichtbar), sperrt aber den
    # Mengen-Export. Erweitert die Abdeckung von "nur saubere CAD-Ketten" auf jeden
    # Plan mit lesbarem Maßstab.
    quelle = "ketten" if ptm else None
    if label_ptm and support < 2:
        ptm = label_ptm
        quelle = "label"
    return {"ptm_konsens": round(ptm, 2) if ptm else None,
            "streuung_pct": streuung, "n_ketten_tragfaehig": support,
            "n_ketten_gesamt": len(slopes), "label_ptm": label_ptm,
            "label_match": label_match, "tragfaehig": tragfaehig, "quelle": quelle}


# ── Wand-Paare aus parallelen Linien (Phase 1/2) ─────────────────────────────
def _faces(segmente, achse, pos_tol=1.0):
    """Kollineare achsparallele Segmente → Wand-Flächen. achse='v': vertikale Linien,
    Face=[pos_x, lo_y, hi_y]. Bucket nach gerundeter pos, dann Intervalle mergen."""
    buckets = defaultdict(list)
    for s in segmente:
        if _achse(s) != achse:
            continue
        if achse == "v":
            pos = (s[0] + s[2]) / 2.0
            lo, hi = sorted((s[1], s[3]))
        else:
            pos = (s[1] + s[3]) / 2.0
            lo, hi = sorted((s[0], s[2]))
        buckets[round(pos / pos_tol) * pos_tol].append((pos, lo, hi))
    faces = []
    for items in buckets.values():
        items.sort(key=lambda t: t[1])
        cur = None
        for pos, lo, hi in items:
            if cur and lo <= cur[2] + pos_tol:
                cur[2] = max(cur[2], hi)
                cur[0] = (cur[0] + pos) / 2.0
            else:
                if cur:
                    faces.append(cur)
                cur = [pos, lo, hi]
        if cur:
            faces.append(cur)
    return faces


def hatch_segmente(segmente):
    """Diagonale (weder h noch v) Segmente = Poché-Schraffur-Kandidaten. Echte Maurer-
    Wände sind innen schraffiert; Bemaßungs-/Terrassen-/Grundstücks-Kanten NICHT."""
    return [s for s in segmente
            if abs(s[0] - s[2]) > 0.5 and abs(s[1] - s[3]) > 0.5]


def _bezier_punkte(p1, p2, p3, p4, n=8):
    """Kubische Bezier-Kurve an n+1 Parametern abtasten."""
    pts = []
    for k in range(n + 1):
        t = k / n
        mt = 1 - t
        x = mt**3 * p1.x + 3 * mt**2 * t * p2.x + 3 * mt * t**2 * p3.x + t**3 * p4.x
        y = mt**3 * p1.y + 3 * mt**2 * t * p2.y + 3 * mt * t**2 * p3.y + t**3 * p4.y
        pts.append((x, y))
    return pts


def _kasa_fit(pts):
    """Algebraischer Kreisfit (Kasa), 2×2-System ohne numpy. → (cx, cy, r) | None."""
    import math as _m
    n = len(pts)
    sx = sum(p[0] for p in pts) / n
    sy = sum(p[1] for p in pts) / n
    u = [(p[0] - sx) for p in pts]
    v = [(p[1] - sy) for p in pts]
    suu = sum(a * a for a in u)
    svv = sum(a * a for a in v)
    suv = sum(a * b for a, b in zip(u, v))
    suuu = sum(a * a * a for a in u)
    svvv = sum(a * a * a for a in v)
    suvv = sum(a * b * b for a, b in zip(u, v))
    svuu = sum(b * a * a for a, b in zip(u, v))
    det = suu * svv - suv * suv
    if abs(det) < 1e-9:
        return None
    uc = (0.5 * (suuu + suvv) * svv - 0.5 * (svvv + svuu) * suv) / det
    vc = (0.5 * (svvv + svuu) * suu - 0.5 * (suuu + suvv) * suv) / det
    r = _m.sqrt(uc * uc + vc * vc + (suu + svv) / n)
    return (uc + sx, vc + sy, r)


def tuer_boegen(page, box, ptm, r_min_m=0.50, r_max_m=1.40,
                winkel_min=55.0, winkel_max=125.0, fit_tol=0.15):
    """TÜR-AUFSCHLAG-BÖGEN aus den 'c'-Bezier-Items der Drawings (die Tür zeichnet
    sich selbst: Viertelkreis = Angelpunkt + Radius (=Türbreite byte-genau) +
    Radius-Endpunkte, einer davon = 'Tür zu' = Öffnungslinie IN der Wand).
    Empirisch am Angerer: 9 Bögen, alle exakt 90,0°, r = 0,83/0,87/1,07m.

    Rückgabe: [{hinge, r_m, a, b, winkel_grad}] — a/b = Radius-Endpunkte."""
    import math as _m
    bx0, bx1, by0, by1 = box
    out = []
    for p in page.get_drawings():
        kette = []

        def _flush():
            if not kette:
                return
            pts = []
            for (p1, p2, p3, p4) in kette:
                seg = _bezier_punkte(p1, p2, p3, p4)
                pts.extend(seg if not pts else seg[1:])
            kette.clear()
            if len(pts) < 5:
                return
            mx = sum(q[0] for q in pts) / len(pts)
            my = sum(q[1] for q in pts) / len(pts)
            if not (bx0 <= mx <= bx1 and by0 <= my <= by1):
                return
            fit = _kasa_fit(pts)
            if not fit:
                return
            cx, cy, r = fit
            r_m = r / ptm
            if not (r_min_m <= r_m <= r_max_m):
                return
            fehler = max(abs(_m.hypot(q[0] - cx, q[1] - cy) - r) for q in pts)
            if fehler > fit_tol * r:
                return
            a, b = pts[0], pts[-1]
            wa = _m.atan2(a[1] - cy, a[0] - cx)
            wb = _m.atan2(b[1] - cy, b[0] - cx)
            dw = _m.degrees(abs(_m.atan2(_m.sin(wb - wa), _m.cos(wb - wa))))
            if not (winkel_min <= dw <= winkel_max):
                return
            out.append({"hinge": (cx, cy), "r_m": round(r_m, 3),
                        "a": a, "b": b, "winkel_grad": round(dw, 1)})

        for it in p.get("items", []):
            if it[0] == "c":
                if kette:
                    pe = kette[-1][3]
                    if _m.hypot(it[1].x - pe.x, it[1].y - pe.y) > 0.5:
                        _flush()
                kette.append((it[1], it[2], it[3], it[4]))
            else:
                _flush()
        _flush()
    return out


def wand_poche(page, box=None, min_anteil=0.08, min_absolut=100):
    """Wand-Poché-Diagonalen mit FARB-Filter: auf farbigen Plänen ist die Maurer-
    Schraffur ROT/ORANGE (= Neubau-Farbe; empirisch am Angerer verifiziert — Außenwand
    + Innenwände rot/orange, Terrain-/Muster-Diagonalen grau/grün). Sind ≥min_anteil
    der Diagonalen rot/orange → NUR diese (filtert ~2700 Rausch-Diagonalen); sonst
    (monochromer Plan) alle Diagonalen (Fallback = bisheriges Verhalten).
    Liefert [(x0,y0,x1,y1,width,grau)] wie _drawings-Segmente."""
    farbig, alle = [], []
    for p in page.get_drawings():
        col = p.get("color")
        rgb = None
        if col is not None:
            try:
                seq = [float(c) for c in col] if not isinstance(col, (int, float)) else [float(col)] * 3
                if len(seq) == 1:
                    rgb = (seq[0], seq[0], seq[0])
                elif len(seq) >= 3:
                    rgb = (seq[0], seq[1], seq[2])
            except (TypeError, ValueError):
                rgb = None
        ist_rot = bool(rgb and rgb[0] > 0.6 and rgb[0] > rgb[1] + 0.2 and rgb[2] < 0.35)
        w = p.get("width") or 0.0
        grau = round(sum(rgb) / 3.0, 3) if rgb else None
        for it in p["items"]:
            if it[0] != "l":
                continue
            a, b = it[1], it[2]
            if abs(a.x - b.x) <= 0.5 or abs(a.y - b.y) <= 0.5:
                continue
            if box:
                mx, my = (a.x + b.x) / 2.0, (a.y + b.y) / 2.0
                if not (box[0] <= mx <= box[1] and box[2] <= my <= box[3]):
                    continue
            seg = (a.x, a.y, b.x, b.y, round(w, 3), grau)
            alle.append(seg)
            if ist_rot:
                farbig.append(seg)
    if alle and len(farbig) >= min_absolut and len(farbig) / len(alle) >= min_anteil:
        return farbig
    return alle


def _hatch_dichte(hatch, achse, center, dist, lo, hi, laenge_m):
    """Schraffur-Linien pro Meter Wandlänge im Band der Wand (zwischen den 2 Flächen)."""
    if not hatch or laenge_m <= 0:
        return 0.0
    plo, phi = center - dist / 2.0, center + dist / 2.0
    n = 0
    for s in hatch:
        mx, my = (s[0] + s[2]) / 2.0, (s[1] + s[3]) / 2.0
        if achse == "v":
            if plo <= mx <= phi and lo <= my <= hi:
                n += 1
        else:
            if plo <= my <= phi and lo <= mx <= hi:
                n += 1
    return n / laenge_m


def wand_paare(segmente, pt_per_m, dicke_min_cm=8.0, dicke_max_cm=55.0, min_len_m=0.3,
               legende_dicken=None, snap_tol_cm=2.0, band_tol_cm=4.0,
               hatch=None, min_hatch_dichte=1.0, mit_geometrie=False):
    """Parallele Flächen-Paare = Wände. GLOBAL-greedy nach Überlappungs-LÄNGE: erst ALLE
    gültigen Kandidaten, dann nach Überlappung absteigend zuweisen (lange, sichere Wände —
    die Außenwand — zuerst; jede Fläche genau einmal). Empirisch (Angerer-Harness): bringt
    die Σ-Gesamtwandlänge auf -1% (die naive Positions-Reihenfolge gab -35%). Liefert
    [(laenge_m, dicke_cm, achse)].

    SCHRAFFUR-GATE (hatch übergeben): echte Maurer-Wände sind innen POCHÉ-schraffiert,
    Geister-Paare (Bemaßungslinien, Terrassen-/Grundstücks-Kanten, zufällige Parallelen)
    nicht. Paare mit Schraffur-Dichte < min_hatch_dichte/m fallen raus. Empirisch
    (Angerer): trennt echte Maurer-Hülle (~45m, Dichte 3-15/m) von ~9m Geister-50cm
    (Dichte 0-0.7/m) → die Außenwand nähert sich der echten Hülle statt des Footprints."""
    out = []
    for achse in ("v", "h"):
        faces = sorted(_faces(segmente, achse))
        dmin = dicke_min_cm / 100.0 * pt_per_m
        dmax = dicke_max_cm / 100.0 * pt_per_m
        kand = []   # (overlap_pt, i, j, dist_pt)
        for i, fa in enumerate(faces):
            for j in range(i + 1, len(faces)):
                fb = faces[j]
                d = abs(fb[0] - fa[0])
                if d > dmax:
                    break
                if d < dmin:
                    continue
                ov = min(fa[2], fb[2]) - max(fa[1], fb[1])
                if ov <= 0:
                    continue
                shorter = min(fa[2] - fa[1], fb[2] - fb[1])
                if shorter <= 0 or ov / shorter < 0.70:
                    continue
                kand.append((ov, i, j, d))
        kand.sort(reverse=True)               # längste Überlappung (sicherste Wand) zuerst
        used = set()
        roh = []   # (center_pos, lo, hi, ov_pt, dist_pt)
        for ov, i, j, d in kand:
            if i in used or j in used:
                continue
            used.add(i); used.add(j)
            fa, fb = faces[i], faces[j]
            center = (fa[0] + fb[0]) / 2.0
            lo, hi = max(fa[1], fb[1]), min(fa[2], fb[2])
            roh.append([center, lo, hi, ov, d])
        # Doppel-Zeichnung dedup: dieselbe Wand 2× gezeichnet (Ziegel- + Putzlinie, Doppel-
        # Layer) ergibt zwei Paare mit ~gleicher Mitte, gleicher Stärke, überlappendem
        # Extent. Stärke als Diskriminator ⇒ 20cm-Wand wird NIE mit 25cm-Wand verschmolzen
        # (anders als reine Positions-Toleranz, die dünne Klassen frisst). Längeres behalten.
        roh.sort(key=lambda r: -r[3])          # längstes zuerst (Anker)
        keep = []
        for r in roh:
            dup = False
            for k in keep:
                if abs(r[0] - k[0]) <= band_tol_cm / 100.0 * pt_per_m \
                        and abs(r[4] - k[4]) <= 3.0 / 100.0 * pt_per_m \
                        and min(r[2], k[2]) - max(r[1], k[1]) > 0.5 * (r[2] - r[1]):
                    dup = True
                    break
            if not dup:
                keep.append(r)
        for center, lo, hi, ov, d in keep:
            laenge_m = ov / pt_per_m
            if laenge_m < min_len_m:
                continue
            dichte = None
            if hatch is not None:
                dichte = _hatch_dichte(hatch, achse, center, d, lo, hi, laenge_m)
                if dichte < min_hatch_dichte:
                    continue   # Geister-Paar (keine Poché): Bemaßung/Terrasse/Grundstück
            if mit_geometrie:
                # Endpunkte in PDF-Koordinaten (für visuelles Overlay): achse 'v' →
                # vertikale Wand bei x=center, y von lo..hi; 'h' → horizontal bei y=center.
                if achse == "v":
                    x0 = x1 = center; y0, y1 = lo, hi
                else:
                    y0 = y1 = center; x0, x1 = lo, hi
                out.append({"achse": achse, "x0": x0, "y0": y0, "x1": x1, "y1": y1,
                            "dist_pt": d, "laenge_m": round(laenge_m, 2),
                            "dicke_cm": round(d / pt_per_m * 100, 1),
                            "hatch_dichte": round(dichte, 1) if dichte is not None else None})
            else:
                out.append((round(laenge_m, 2), round(d / pt_per_m * 100, 1), achse))
    return out


def _snap_legende(dicke_cm, legende_dicken, tol_cm=3.0):
    """Gemessene Dicke auf nächsten Legende-Wert snappen (sonst None)."""
    if not legende_dicken:
        return None
    best = min(legende_dicken, key=lambda d: abs(d - dicke_cm))
    return best if abs(best - dicke_cm) <= tol_cm else None


def _view_bbox(label_pos, pt_per_m, marge_m=4.0, radius_m=12.0):
    """Grundriss-Ansicht (EIN Geschoss) aus Raum-Label-Positionen eingrenzen — robust
    gegen Mehr-Ansichten-Blatt: nimmt den DICHTESTEN Label-Cluster (das Label mit den
    meisten Nachbarn im Gebäude-Radius = Geschoss-Mitte), behält nur Labels darum.
    Trennt so EG von OG/Schnitt/Lageplan auf demselben A0-Blatt."""
    if len(label_pos) < 3:
        return None
    R = radius_m * pt_per_m
    best_c, best_n = None, -1
    for cx, cy in label_pos:
        n = sum(1 for x, y in label_pos if (x - cx) ** 2 + (y - cy) ** 2 <= R * R)
        if n > best_n:
            best_n, best_c = n, (cx, cy)
    cx, cy = best_c
    nah = [(x, y) for x, y in label_pos if (x - cx) ** 2 + (y - cy) ** 2 <= R * R]
    m = marge_m * pt_per_m
    return (min(x for x, _ in nah) - m, max(x for x, _ in nah) + m,
            min(y for _, y in nah) - m, max(y for _, y in nah) + m)


def messe_waende(page, label_pos, pt_per_m, legende_dicken, geschosshoehe_m=2.95):
    """Wand-Längen je Stärke aus den Vektoren, eingegrenzt auf die Grundriss-Ansicht
    (per Raum-Labels). Liefert {dicke_cm: {laenge_m, n}} + abgeleitete Flächen.
    LOG-Größe — Konsum nur nach Kreuzvalidierung (gegen Außenumfang/Legende)."""
    bbox = _view_bbox(label_pos, pt_per_m)
    if not bbox:
        return None
    bx0, bx1, by0, by1 = bbox
    segs, _f, _n = _drawings(page)
    arch = [s for s in segs
            if (s[5] is None or s[5] < 0.45)
            and _laenge(s) / pt_per_m > 0.8
            and bx0 <= (s[0] + s[2]) / 2 <= bx1 and by0 <= (s[1] + s[3]) / 2 <= by1]
    paare = wand_paare(arch, pt_per_m, min_len_m=0.8)
    je = {}
    for L, dk, _ac in paare:
        snap = _snap_legende(dk, legende_dicken, tol_cm=2.5)
        if snap is None:
            continue
        e = je.setdefault(snap, {"laenge_m": 0.0, "n": 0})
        e["laenge_m"] += L
        e["n"] += 1
    for dk, e in je.items():
        e["laenge_m"] = round(e["laenge_m"], 1)
        e["flaeche_m2"] = round(e["laenge_m"] * geschosshoehe_m, 1)
    return {"bbox_m": [round((bx1 - bx0) / pt_per_m, 1), round((by1 - by0) / pt_per_m, 1)],
            "je_staerke": je, "n_arch_segmente": len(arch), "n_paare": len(paare)}


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
