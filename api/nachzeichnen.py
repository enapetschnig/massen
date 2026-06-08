"""NACHZEICHNEN fürs Produkt — Basis-Plan-Bild + erkannte Wände als JSON (Pixel-Koords).

Liefert dem Frontend (a) das gerenderte EG-Grundriss-Bild als PNG und (b) die erkannten
Wände in BILD-PIXEL-Koordinaten, damit das Frontend sie als SVG-Overlay exakt darüber
legen kann (anklick-/korrigierbar). Bewusst KEINE PIL-Abhängigkeit im Server — das
Basis-Bild kommt direkt aus fitz (pixmap → PNG), das Overlay zeichnet das Frontend.

Read-only/best-effort: scheitert die Kalibrierung oder fehlt die EG-Box (eines der
dokumentiert „harten" Blätter), kommt {"ok": False, "grund": ...} zurück — nie ein Fehler.

Baut auf api/vektor.py (Kalibrierung, Wand-Paarung, Schraffur-Gate). Das visuelle
Schwester-Skript scripts/nachzeichnen_overlay.py rendert dasselbe lokal mit PIL.
"""
import re

import vektor

LEG = [50, 38, 25, 20, 12]
RAUM_WORTE = ["Wohnraum", "Waschen", "Bad", "WC", "Flur", "Zimmer", "Küche", "Geräte",
              "Schlafen", "Wohnen", "Diele", "Abstell", "Gang", "Kind", "Eltern", "Büro"]


def _massstab(page):
    m = re.search(r"1\s*:\s*(\d{2,4})", page.get_text())
    return f"1:{m.group(1)}" if m else None


def _eg_box(page, ptm):
    W, H = page.rect.width, page.rect.height
    pos = [(w[0], w[1]) for w in page.get_text("words")
           if any(r.lower() in w[4].lower() for r in RAUM_WORTE)
           and 0.02 * W <= w[0] <= 0.55 * W and 0.04 * H <= w[1] <= 0.6 * H]
    return vektor._view_bbox(pos, ptm, marge_m=4.0, radius_m=13.0)


def analysiere_seite(page, max_px=1800, min_len_m=0.6, min_hatch_dichte=1.0):
    """Eine Grundriss-Seite → {ok, basis_png(bytes), waende[], summe_m, meta}."""
    kal = vektor.kalibriere(page.get_text("words"), _massstab(page))
    ptm = kal.get("ptm_konsens")
    if not ptm:
        return {"ok": False, "grund": "Maßstab/Kalibrierung nicht lesbar"}
    box = _eg_box(page, ptm)
    if not box:
        return {"ok": False, "grund": "Kein Grundriss-Bereich gefunden (zu wenig Raum-Labels)"}
    bx0, bx1, by0, by1 = box
    breite_pt, hoehe_pt = (bx1 - bx0), (by1 - by0)
    if breite_pt <= 0 or hoehe_pt <= 0:
        return {"ok": False, "grund": "Ungültige Grundriss-Box"}

    # Render-Skala so wählen, dass die größere Bildkante ≈ max_px (Payload begrenzen)
    scale = min(max_px / breite_pt, max_px / hoehe_pt, 4.0)
    scale = max(scale, 0.5)

    segs, _f, _n = vektor._drawings(page)
    inb = lambda s: bx0 <= (s[0] + s[2]) / 2 <= bx1 and by0 <= (s[1] + s[3]) / 2 <= by1
    arch = [s for s in segs if (s[5] is None or s[5] < 0.45)
            and vektor._laenge(s) / ptm > 0.5 and inb(s)]
    hatch = [s for s in vektor.hatch_segmente(segs) if inb(s)]
    roh = vektor.wand_paare(arch, ptm, min_len_m=min_len_m, legende_dicken=LEG,
                            hatch=hatch, min_hatch_dichte=min_hatch_dichte, mit_geometrie=True)

    def to_px(x, y):
        return [round((x - bx0) * scale, 1), round((y - by0) * scale, 1)]

    clampx = lambda v: min(max(v, bx0), bx1)
    clampy = lambda v: min(max(v, by0), by1)

    waende = []
    summe = {}
    idx = 0
    for w in roh:
        # Endpunkte auf die View-Box klemmen — über-lange Flächen (Merge/Kanten, die in
        # Carport/Terrasse weiterlaufen) zählen nur mit ihrem SICHTBAREN Anteil. Ehrlicher
        # fürs Bild UND fürs Maß (kein Über-Zählen jenseits des Grundrisses).
        x0c, x1c = clampx(w["x0"]), clampx(w["x1"])
        y0c, y1c = clampy(w["y0"]), clampy(w["y1"])
        if w["achse"] == "v":
            laenge_m = round(abs(y1c - y0c) / ptm, 2)
        else:
            laenge_m = round(abs(x1c - x0c) / ptm, 2)
        if laenge_m < min_len_m:
            continue
        sn = vektor._snap_legende(w["dicke_cm"], LEG, 2.0)
        p0 = to_px(x0c, y0c)
        p1 = to_px(x1c, y1c)
        waende.append({
            "id": idx,
            "achse": w["achse"],
            "px": [p0[0], p0[1], p1[0], p1[1]],
            "dicke_cm": w["dicke_cm"],
            "snap_cm": sn,
            "laenge_m": laenge_m,
            "staerke_px": round((sn or w["dicke_cm"]) / 100.0 * ptm * scale, 1),
            "hatch_dichte": w.get("hatch_dichte"),
        })
        idx += 1
        if sn:
            summe[sn] = round(summe.get(sn, 0) + laenge_m, 2)

    try:
        import fitz
        pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale),
                              clip=fitz.Rect(bx0, by0, bx1, by1))
        basis_png = pix.tobytes("png")
        bild_w, bild_h = pix.width, pix.height
    except Exception as e:  # pragma: no cover
        return {"ok": False, "grund": f"Render fehlgeschlagen: {e}"}

    return {
        "ok": True,
        "basis_png": basis_png,                 # bytes (Endpoint base64-kodiert)
        "bild_w": bild_w, "bild_h": bild_h,
        "waende": waende,
        "summe_m": {str(k): v for k, v in sorted(summe.items(), reverse=True)},
        "meta": {
            "ptm": round(ptm, 2),
            "box_pt": [round(bx0, 1), round(by0, 1), round(bx1, 1), round(by1, 1)],
            "scale": round(scale, 4),
            "n_waende": len(waende),
            "box_m": [round(breite_pt / ptm, 1), round(hoehe_pt / ptm, 1)],
            # Kalibrier-Güte: trägt das Maß? (Read-only-Ansicht zeigt es nur an; ein
            # späterer Mengen-Export muss tragfaehig==True + kleine Streuung verlangen.)
            "tragfaehig": bool(kal.get("tragfaehig")),
            "streuung_pct": kal.get("streuung_pct"),
            "massstab": _massstab(page),
        },
    }


def analysiere_doc(doc, **kw):
    """Ganzes PDF → größte Seite nachzeichnen."""
    page = max(doc, key=lambda p: p.rect.width * p.rect.height)
    return analysiere_seite(page, **kw)
