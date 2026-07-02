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


def _wandbox(page, ptm):
    """Fallback-Box aus der Bounding-Box der dunklen Wand-Linien (für Grundriss-Pläne
    ohne Raumnamen). Nur wenn die Größe plausibel ist (4-45 m/Seite) → Schnitte/Lagepläne
    fallen raus. Perzentil-Box (2-98%) trimmt Streu-Linien am Blattrand."""
    segs, _f, _n = vektor._drawings(page)
    dark = [s for s in segs if (s[5] is None or s[5] < 0.45) and vektor._laenge(s) / ptm > 1.0]
    if len(dark) < 50:
        return None
    xs = sorted((s[0] + s[2]) / 2.0 for s in dark)
    ys = sorted((s[1] + s[3]) / 2.0 for s in dark)

    def pct(a, p):
        return a[min(len(a) - 1, max(0, int(p * (len(a) - 1))))]

    bx0, bx1 = pct(xs, 0.02), pct(xs, 0.98)
    by0, by1 = pct(ys, 0.02), pct(ys, 0.98)
    bm, hm = (bx1 - bx0) / ptm, (by1 - by0) / ptm
    # 4-30 m je Seite: EFH/MFH-Grundrisse liegen darunter; ein Schnitt-/Ansichts-Blatt
    # streut seine Linien über das ganze Blatt (Velden-Schnitt: 45×38 m → ehrlich ✗
    # statt ein falsches "Grundriss"-Bild zu zeigen).
    if 4.0 <= bm <= 30.0 and 4.0 <= hm <= 30.0:
        marge = 1.0 * ptm   # 1 m Rand
        return (bx0 - marge, bx1 + marge, by0 - marge, by1 + marge)
    return None


def analysiere_seite(page, max_px=1800, min_len_m=0.6, min_hatch_dichte=1.0):
    """Eine Grundriss-Seite → {ok, basis_png(bytes), waende[], summe_m, meta}."""
    kal = vektor.kalibriere(page.get_text("words"), _massstab(page))
    ptm = kal.get("ptm_konsens")
    if not ptm:
        return {"ok": False, "grund": "Maßstab/Kalibrierung nicht lesbar"}
    box = _eg_box(page, ptm)
    if not box:
        # FALLBACK für Grundriss-Pläne OHNE Raumnamen (z.B. reine Wand-Grundrisse):
        # die Bounding-Box der dunklen Wand-Linien nehmen — aber nur, wenn sie eine
        # PLAUSIBLE Gebäude-Größe hat (4-45 m/Seite). Schließt Schnitte/Lagepläne aus.
        box = _wandbox(page, ptm)
    if not box:
        return {"ok": False, "grund": "Kein Grundriss-Bereich gefunden (weder Raum-Labels noch plausible Wand-Kontur)"}
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
    # farb-gefilterte Wand-Poché (Neubau rot/orange auf farbigen Plänen; Fallback alle)
    hatch = vektor.wand_poche(page, (bx0, bx1, by0, by1))
    roh = vektor.wand_paare(arch, ptm, min_len_m=min_len_m, legende_dicken=LEG,
                            hatch=hatch, min_hatch_dichte=min_hatch_dichte, mit_geometrie=True)

    def to_px(x, y):
        return [round((x - bx0) * scale, 1), round((y - by0) * scale, 1)]

    clampx = lambda v: min(max(v, bx0), bx1)
    clampy = lambda v: min(max(v, by0), by1)

    # MASSKETTEN-SNAP (Stufe 3, "1:1 mit den Längen"): steht neben einer Wand eine
    # byte-exakte Maß-Zahl, deren Wert der gemessenen Länge entspricht (±8cm/4%),
    # gewinnt die PLAN-ZAHL über die Messung. Killt das cm-Rauschen der Vektor-Messung.
    try:
        from massketten import numeric_spans
        masse = [(x, y, v) for (x, y, v) in numeric_spans(page.get_text("words"))
                 if bx0 <= x <= bx1 and by0 <= y <= by1]
    except Exception:
        masse = []

    def mass_snap(achse, pos, lo, hi, laenge_m):
        best = None
        quer = 2.5 * ptm     # Maßketten liegen oft 1-3m neben der Wand (Außenketten);
                             # die enge WERT-Toleranz (8cm/4%) verhindert Fehl-Matches
        for (mx, my, v) in masse:
            vm = v / 100.0
            if abs(vm - laenge_m) > max(0.08, 0.04 * laenge_m):
                continue
            if achse == "v":
                if abs(mx - pos) > quer or not (lo - 0.5 * ptm <= my <= hi + 0.5 * ptm):
                    continue
            else:
                if abs(my - pos) > quer or not (lo - 0.5 * ptm <= mx <= hi + 0.5 * ptm):
                    continue
            d = abs(vm - laenge_m)
            if best is None or d < best[0]:
                best = (d, vm)
        return best[1] if best else None

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
            exakt = mass_snap("v", x0c, min(y0c, y1c), max(y0c, y1c), laenge_m)
        else:
            laenge_m = round(abs(x1c - x0c) / ptm, 2)
            exakt = mass_snap("h", y0c, min(x0c, x1c), max(x0c, x1c), laenge_m)
        if exakt is not None:
            laenge_m = round(exakt, 2)
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
            "mass_exakt": exakt is not None,     # Länge = byte-exakte Plan-Maßzahl
            "staerke_px": round((sn or w["dicke_cm"]) / 100.0 * ptm * scale, 1),
            "hatch_dichte": w.get("hatch_dichte"),
        })
        idx += 1
        if sn:
            summe[sn] = round(summe.get(sn, 0) + laenge_m, 2)

    # Öffnungen (Fenster/Türen) aus dem Text-Layer (STUK/FPH-Codes stehen an der Öffnung,
    # byte-exakt) → klickbare Marker. Best-effort, bricht nie.
    oeffnungen = []
    try:
        import oeffnungen as _oeff
        # Spans wie die Haupt-Pipeline aus get_text("dict") (Text-Runs halten "FPH 0,00"
        # zusammen — "words" würde "FPH" und "0,00" trennen → keine Öffnung erkannt).
        spans = []
        for block in page.get_text("dict").get("blocks", []):
            if block.get("type") != 0:
                continue
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    txt = (span.get("text") or "").strip()
                    if not txt:
                        continue
                    bb = tuple(span.get("bbox") or (0, 0, 0, 0))
                    spans.append({"text": txt, "bbox": bb, "size": span.get("size", 0),
                                  "cx": (bb[0] + bb[2]) / 2.0, "cy": (bb[1] + bb[3]) / 2.0})
        oeff_pt = []
        for o in _oeff.extract_oeffnungen_from_text(spans, []):
            cx, cy = o.get("cx"), o.get("cy")
            if cx is None or not (bx0 <= cx <= bx1 and by0 <= cy <= by1):
                continue
            oeff_pt.append(o)
            oeffnungen.append({
                "id": len(oeffnungen), "typ": o.get("typ"),
                "breite_m": o.get("breite_m"), "hoehe_m": o.get("hoehe_m"),
                "px": to_px(cx, cy),
            })
    except Exception as e:  # pragma: no cover
        oeff_pt = []
        print(f"[nachzeichnen] Öffnungen fehlgeschlagen: {e}")

    # RAUM-VERIFIKATION (Stufe 4): der Plan validiert sich selbst — rekonstruierte
    # Raum-Gebiete gegen die byte-exakten F/U-Stempel prüfen → grüne (bewiesene) vs
    # gelbe (prüfen!) Räume in der Planansicht. Best-effort, gröberes Raster (3cm)
    # für die Latenz des Live-Endpoints.
    raeume = []
    try:
        import raumnetz
        dark = [s for s in segs if (s[5] is None or s[5] < 0.45)
                and vektor._laenge(s) / ptm > 0.10 and inb(s)]
        rres, _st = raumnetz.verifiziere_seite(page, ptm, (bx0, bx1, by0, by1),
                                               dark, hatch, oeff_pt, zelle_m=0.03)
        for r in rres:
            raeume.append({
                "name": r.get("name"), "f_m2": r.get("f_m2"), "u_m": r.get("u_m"),
                "f_ist": r.get("f_ist"), "u_ist": r.get("u_ist"),
                "status": r.get("status"),
                "px": to_px(r["cx"], r["cy"]),
            })
    except Exception as e:  # pragma: no cover
        print(f"[nachzeichnen] Raum-Verifikation fehlgeschlagen: {e}")

    # BYTE-EXAKTE WANDFLUCHTEN (Maßketten-Snap): jede bestätigte Ketten-Grenze
    # IST eine Wandflucht laut Plan-Bemaßung — eingezeichnet in Planansicht +
    # Aufmaßblatt macht sie die Maße NACHVOLLZIEHBAR ("Längen 1:1 aus dem Plan").
    # Korpus: WM 89% / AP.01 61% / Angerer 56% der Grenzen bestätigt.
    fluchten = []
    try:
        import raumnetz
        import massketten
        dark_f = [s for s in segs if (s[5] is None or s[5] < 0.45)
                  and vektor._laenge(s) / ptm > 0.10 and inb(s)]
        rst_f = raumnetz._Raster((bx0, bx1, by0, by1), ptm, 0.02)
        fills_f = vektor.wand_fill_rects(page, (bx0, bx1, by0, by1),
                                         min_seite_m=0.3, ptm=ptm)
        grid_f = raumnetz.wand_maske(rst_f, dark_f, hatch, [], fill_rects=fills_f)
        for fl in massketten.wand_fluchten(page.get_text("words"),
                                           (bx0, bx1, by0, by1), ptm,
                                           grid_f, rst_f.W, rst_f.H, rst_f.cell):
            px = to_px(fl["pos"], by0)[0] if fl["achse"] == "v" \
                else to_px(bx0, fl["pos"])[1]
            # 3 Stufen: Wandfläche (ok) · kurze Kante ≥12cm (Öffnungs-Laibung/
            # Pfeiler — Fenster-Ketten des 1762788650811 seziert) · fehlt
            fluchten.append({"achse": fl["achse"], "px": px, "ok": fl["ok"],
                             "kurz": bool(not fl["ok"] and fl.get("lauf", 0) >= 6)})
    except Exception as e:  # pragma: no cover
        print(f"[nachzeichnen] Wandfluchten fehlgeschlagen: {e}")

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
        "oeffnungen": oeffnungen,
        "raeume": raeume,
        "fluchten": fluchten,
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
