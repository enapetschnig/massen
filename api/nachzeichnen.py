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


def _eg_box(page, ptm, worte=None):
    W, H = page.rect.width, page.rect.height
    pos = [(w[0], w[1]) for w in (worte if worte is not None else page.get_text("words"))
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
    # TEXT-SHARING (WM-Profil: get_text('words') kostet ~5s bei 878k-Pfad-Plänen
    # und lief 4× je Analyse) — einmal ziehen, durchreichen.
    worte = page.get_text("words")
    m_label = _massstab(page)
    kal = vektor.kalibriere(worte, m_label)
    ptm = kal.get("ptm_konsens")
    if not ptm:
        # SCAN-ERKENNUNG (Edge-Case-Sweep): Bild-PDFs ohne Text-Layer bekommen
        # eine handlungsleitende Meldung statt der generischen.
        if len(worte) < 10:
            return {"ok": False, "grund": ("Scan/Bild-PDF ohne Text-Layer — für die "
                    "Massenermittlung wird das Vektor-Original benötigt "
                    "(aus dem CAD als PDF exportiert, nicht gescannt)")}
        return {"ok": False, "grund": "Maßstab/Kalibrierung nicht lesbar"}
    box = _eg_box(page, ptm, worte=worte)
    # STUFE 2 (TG-/Großbau-Pläne, Sektor-Audit: die Wohn-RAUM_WORTE trafen am
    # Velden-TG nur den Stiegenhaus-Kern via Zufallstreffer 'Gang'/'Eingang' —
    # Box deckte 8% des Bauwerks): Box aus den F/U-STEMPEL-Positionen, wenn
    # KEINE Box da ist ODER >50% der Stempel außerhalb liegen. raum_stempel
    # liest seit dem Rotated-Support auch ArchiCAD-Blöcke (555,9m²-Halle).
    try:
        import raumnetz as _rn
        _st = _rn.raum_stempel(page, (0, page.rect.width, 0, page.rect.height))
        if len(_st) >= 3:
            drin = sum(1 for x in _st
                       if box and box[0] <= x["cx"] <= box[1]
                       and box[2] <= x["cy"] <= box[3])
            if not box or drin < 0.5 * len(_st):
                pos = [(x["cx"], x["cy"]) for x in _st]
                # Marge skaliert mit dem größten Stempel: der 555,9m²-Hallen-
                # Stempel sitzt MITTIG, die Außenkante liegt ~√F/2 entfernt —
                # die 4m-Marge kappte die Halle auf 225m² (gemessen). EFH
                # (max F ≤ 40) bleibt bei 4m.
                _fmax = max((x.get("f_m2") or 0) for x in _st)
                _marge = max(4.0, 0.6 * (_fmax ** 0.5))
                box = vektor._view_bbox(pos, ptm, marge_m=_marge, radius_m=40.0)
    except Exception:
        pass
    if not box:
        # FALLBACK für Grundriss-Pläne OHNE Raumnamen (z.B. reine Wand-Grundrisse):
        # die Bounding-Box der dunklen Wand-Linien nehmen — aber nur, wenn sie eine
        # PLAUSIBLE Gebäude-Größe hat (4-45 m/Seite). Schließt Schnitte/Lagepläne aus.
        box = _wandbox(page, ptm)
    if not box:
        # SCHNITT-BLATT-MODUS ('für alle Pläne': jedes Blatt liefert, was es
        # trägt): Schnitt-/Ansichts-Blätter haben keinen Grundriss, aber
        # byte-exakte HÖHENKOTEN (Velden 40, 05_AU 83 gemessen) — Ansicht mit
        # Koten-Markern statt reinem ✗.
        koten = [(w[0], w[1], w[4]) for w in worte
                 if re.match(r"^[±+\-]\s?\d{1,2}[.,]\d{2}$", w[4].strip())]
        if len(koten) >= 8:
            bx0s, by0s = 0.0, 0.0
            bx1s, by1s = page.rect.width, page.rect.height
            scale_s = max(0.5, min(max_px / bx1s, max_px / by1s, 4.0))
            try:
                import fitz as _fz
                pix = page.get_pixmap(matrix=_fz.Matrix(scale_s, scale_s))
                return {
                    "ok": True, "typ": "schnitt",
                    "basis_png": pix.tobytes("png"),
                    "bild_w": pix.width, "bild_h": pix.height,
                    "waende": [], "oeffnungen": [], "raeume": [],
                    "konturen": [], "fluchten": [], "summe_m": {},
                    "koten": [{"px": [round(x * scale_s, 1), round(y * scale_s, 1)],
                               "wert": t.strip()} for (x, y, t) in koten[:200]],
                    "meta": {
                        "ptm": round(ptm, 2), "scale": round(scale_s, 4),
                        "box_pt": [0.0, 0.0, round(bx1s, 1), round(by1s, 1)],
                        "n_waende": 0,
                        "box_m": [round(bx1s / ptm, 1), round(by1s / ptm, 1)],
                        "tragfaehig": bool(kal.get("tragfaehig")),
                        "streuung_pct": kal.get("streuung_pct"),
                        "massstab": m_label, "typ": "schnitt",
                    },
                }
            except Exception:
                pass
        return {"ok": False, "grund": "Kein Grundriss-Bereich gefunden (weder Raum-Labels noch plausible Wand-Kontur)"}
    bx0, bx1, by0, by1 = box
    breite_pt, hoehe_pt = (bx1 - bx0), (by1 - by0)
    if breite_pt <= 0 or hoehe_pt <= 0:
        return {"ok": False, "grund": "Ungültige Grundriss-Box"}

    # Render-Skala so wählen, dass die größere Bildkante ≈ max_px (Payload begrenzen)
    scale = min(max_px / breite_pt, max_px / hoehe_pt, 4.0)
    scale = max(scale, 0.5)

    # ADAPTIVE RASTERWEITEN (WM-Lehre: mit korrektem ptm=56,7 wurde die Box
    # ~3,24× größer je Seite, das 0,03er-Raster explodierte ~10× → Pipeline
    # lief >40min). Ziel: Zellzahl gedeckelt; Angerer-Klasse (≤ ~360m²) behält
    # EXAKT die bewährten 0,03/0,02 (Untergrenzen).
    flaeche_m2 = (breite_pt / ptm) * (hoehe_pt / ptm)
    zelle_r = max(0.03, min(0.08, (flaeche_m2 / 360000.0) ** 0.5))
    zelle_f = max(0.02, min(0.06, (flaeche_m2 / 810000.0) ** 0.5))
    grossplan = flaeche_m2 > 600.0

    # PFAD-SHARING (WM-Lehre: page.get_drawings() kostet ~45s bei 878k Pfaden
    # und lief 5× je Analyse — _drawings, wand_poche, fill_rects, tuer_boegen,
    # Möbel-Scan → >40min statt Minuten). EINMAL ziehen, überall durchreichen.
    pfade = list(page.get_drawings())
    segs, _f, _n = vektor._drawings(page, pfade=pfade)
    inb = lambda s: bx0 <= (s[0] + s[2]) / 2 <= bx1 and by0 <= (s[1] + s[3]) / 2 <= by1
    arch = [s for s in segs if (s[5] is None or s[5] < 0.45)
            and vektor._laenge(s) / ptm > 0.5 and inb(s)]
    # farb-gefilterte Wand-Poché (Neubau rot/orange auf farbigen Plänen; Fallback alle)
    hatch = vektor.wand_poche(page, (bx0, bx1, by0, by1), pfade=pfade, ptm=ptm)
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
        masse = [(x, y, v) for (x, y, v) in numeric_spans(worte)
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

    # FALLBACK-SUMME für Grundriss-Pläne OHNE Mauerwerks-Legende (Breiten-Test Holzbau
    # 'EG-Wand-Grundriss' 1:50, Holzerleben): dessen Wände messen ~9cm (Ständer/Innen)
    # und ~34cm (gedämmte Außenwand) — keine davon schnappt auf LEG=[50,38,25,20,12],
    # also blieb die Wandlängen-Summe LEER, obwohl 13 echte Wände getrace't wurden.
    # Nur wenn summe SONST leer wäre → strikt monoton (jeder Plan mit ≥1 Legenden-Snap
    # bleibt unberührt, Angerer/TG/Dach unverändert). Nahe Mess-Cluster (8/9, 33.8/33.9)
    # werden längen-gewichtet zu einem Bucket zusammengeführt (Vektor-Rauschen ±1cm).
    if not summe and waende:
        paare = sorted(((round(w.get("dicke_cm") or 0), w["laenge_m"]) for w in waende
                        if (w.get("dicke_cm") or 0) >= 5.0), key=lambda t: t[0])

        def _flush(grp):
            if not grp:
                return
            L = sum(l for _, l in grp)
            rep = round(sum(d * l for d, l in grp) / L)
            summe[rep] = round(summe.get(rep, 0) + L, 2)

        grp = []
        for dc, lm in paare:
            if grp and dc - grp[-1][0] > 2:
                _flush(grp)
                grp = []
            grp.append((dc, lm))
        _flush(grp)

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
        dbg_r = {}
        rres, _st = raumnetz.verifiziere_seite(page, ptm, (bx0, bx1, by0, by1),
                                               dark, hatch, oeff_pt, zelle_m=zelle_r,
                                               debug=dbg_r, pfade=pfade)
        # REKONSTRUIERTE RAUM-REGIONEN als Umriss (Nachvollziehbarkeit: die
        # geometrische Lesart der App über dem Plan — grün deckt sich, Prüf-
        # Räume zeigen die Abweichung). Aus dem finalen Label-Grid des Roh-
        # Passes (dbg_r); best-effort, große Pläne nicht (Latenz/Rausch).
        regionen = {}
        try:
            # Läuft jetzt AUCH auf Großplänen (Nachvollziehbarkeit: WM/TG-Räume hatten
            # gar keine gezeichnete Kontur — die größten Pläne mit den meisten Räumen
            # waren blank). raum_regionen selbst filtert unzuverlässige/zackige Umrisse
            # (Flächen-Treue ±20%, ≤40 Ecken, ≥75% achsparallel) → nur saubere Räume
            # bekommen einen Umriss, komplexe bleiben ehrlich ohne. Sicherheits-Deckel
            # gegen Extrem-Pläne: >150 Räume überspringen (reine Latenz-Vorsicht).
            if dbg_r.get("label") is not None and len(rres) <= 150:
                regionen = raumnetz.raum_regionen(dbg_r["label"], dbg_r["rst"],
                                                  len(rres))
        except Exception as _er:
            regionen = {}
        for i, r in enumerate(rres):
            reg = regionen.get(i)
            raeume.append({
                "name": r.get("name"), "f_m2": r.get("f_m2"), "u_m": r.get("u_m"),
                "f_ist": r.get("f_ist"), "u_ist": r.get("u_ist"),
                "status": r.get("status"),
                "ebene": r.get("ebene"),   # 'roh'|'fertig' — welche Ebene bewies
                "px": to_px(r["cx"], r["cy"]),
                "region_px": [to_px(x, y) for (x, y) in reg] if reg else None,
                "cx": r["cx"], "cy": r["cy"],   # für den IoU-Beweis (pt)
            })
    except Exception as e:  # pragma: no cover
        print(f"[nachzeichnen] Raum-Verifikation fehlgeschlagen: {e}")

    # GEMAUERTE HÜLLE als Kontur-Layer (Nachvollziehbarkeits-Audit P1: der
    # Außenumfang treibt ~20 der 35 Material-Positionen und war nie am Plan
    # eingezeichnet — B-2110-Prinzip prüfbarer Mengenermittlung). Quelle ist
    # die AUSSEN-Grenze der Wand-Maske (Plan-Koordinaten, direkt vergleichbar
    # mit dem Materialliste-Umfang).
    konturen = []
    try:
        import raumnetz
        if dbg_r.get("grid") is not None and dbg_r.get("label") is not None:
            for k in raumnetz.huellen_kontur(dbg_r["grid"], dbg_r["label"],
                                             dbg_r["rst"], dbg_r["AUSSEN"]):
                konturen.append({
                    "px": [to_px(x, y) for (x, y) in k["punkte"]],
                    "umfang_m": k["umfang_m"],
                })
    except Exception as e:  # pragma: no cover
        print(f"[nachzeichnen] Hüllen-Kontur fehlgeschlagen: {e}")

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
        rst_f = raumnetz._Raster((bx0, bx1, by0, by1), ptm, zelle_f)
        fills_f = vektor.wand_fill_rects(page, (bx0, bx1, by0, by1),
                                         min_seite_m=0.3, ptm=ptm, pfade=pfade)
        grid_f = raumnetz.wand_maske(rst_f, dark_f, hatch, [], fill_rects=fills_f)
        fluchten_pt = massketten.wand_fluchten(worte,
                                               (bx0, bx1, by0, by1), ptm,
                                               grid_f, rst_f.W, rst_f.H, rst_f.cell)
        for fl in fluchten_pt:
            px = to_px(fl["pos"], by0)[0] if fl["achse"] == "v" \
                else to_px(bx0, fl["pos"])[1]
            # 3 Stufen: Wandfläche (ok) · kurze Kante ≥12cm (Öffnungs-Laibung/
            # Pfeiler — Fenster-Ketten des 1762788650811 seziert) · fehlt
            fluchten.append({"achse": fl["achse"], "px": px, "ok": fl["ok"],
                             "kurz": bool(not fl["ok"] and fl.get("lauf", 0) >= 6)})
        # ZWEI-EBENEN-VERIFIKATION: Räume zusätzlich gegen das byte-exakte ROHBAU-
        # Rechteck aus FLUCHT-PAAREN prüfen (Stempel misst FERTIG, Region ROHBAU —
        # Geräte/Bad/Zimmer 1 am Angerer nur so beweisbar; Paar-Suche = Kombination
        # mit Stempel innen + Fläche ≈ F_stempel×[0,98..1,15], reconstruct_bbox-Prinzip).
        nutzbar = [f for f in fluchten_pt if f["ok"] or f.get("lauf", 0) >= 6]
        fv = sorted(f["pos"] for f in nutzbar if f["achse"] == "v")
        fh = sorted(f["pos"] for f in nutzbar if f["achse"] == "h")
        # WM-PROFIL-LEHRE: die Paar-Kreuzprodukte skalieren mit Fluchten-Dichte⁴
        # (155 Mio. Kombis, >3min am WM). ÄQUIVALENTER Umbau: hp nach Höhe
        # sortieren, das F-Fenster [0,98..1,15]×F_ziel per bisect ziehen —
        # gleiche Kandidatenmenge, gleiche Best-Wahl, O(vp·log hp).
        import bisect as _bi
        for r in raeume:
            f_ziel, f_ist, u_ist = r.get("f_m2"), r.get("f_ist"), r.get("u_ist")
            if not (f_ziel and f_ist):
                continue
            rcx = r["px"][0] / scale + bx0
            rcy = r["px"][1] / scale + by0
            vp = [(a, b) for a in fv if a < rcx for b in fv if b > rcx
                  if 0.5 <= (b - a) / ptm <= 14.0]
            hp = [(a, b) for a in fh if a < rcy for b in fh if b > rcy
                  if 0.5 <= (b - a) / ptm <= 14.0]
            hh = sorted((b - a) / ptm for (a, b) in hp)
            best = None
            formen_r = []    # ALLE F+U-kompatiblen Formen → Eindeutigkeits-Gate
            for (l_, r_) in vp:
                w_ = (r_ - l_) / ptm
                for k in range(_bi.bisect_left(hh, 0.98 * f_ziel / w_),
                               _bi.bisect_right(hh, 1.15 * f_ziel / w_)):
                    h_ = hh[k]
                    f_k, u_k = w_ * h_, 2 * (w_ + h_)
                    if (abs(f_ist - f_k) / f_k <= 0.05 and u_ist
                            and abs(u_ist - u_k) / u_k <= 0.08):
                        formen_r.append((w_, h_))
                    sc = abs(f_k - 1.06 * f_ziel)
                    if best is None or sc < best[0]:
                        best = (sc, w_, h_)
            rect_ok = False
            if best:
                _sc, w_, h_ = best
                f_roh, u_roh = w_ * h_, 2 * (w_ + h_)
                # EINDEUTIGKEITS-GATE (WM-Lehre: 22/22 rohbau_ok bei dichten
                # Fluchten = Beliebigkeit — irgendein Rechteck passt immer;
                # exakt das ±10cm-Gate der bewährten Bogen-Stufe): ALLE
                # kompatiblen Formen müssen dieselbe sein, sonst kein Beweis.
                eindeutig = bool(formen_r) and all(
                    abs(a[0] - formen_r[0][0]) <= 0.1
                    and abs(a[1] - formen_r[0][1]) <= 0.1 for a in formen_r)
                if (eindeutig and abs(f_ist - f_roh) / f_roh <= 0.05
                        and u_ist and abs(u_ist - u_roh) / u_roh <= 0.08):
                    r["rohbau_ok"] = True
                    r["rohbau_form"] = "rechteck"
                    r["f_rohbau"] = round(f_roh, 2)
                    r["u_rohbau"] = round(u_roh, 2)
                    rect_ok = True
            if not rect_ok and u_ist:
                # L-FORM (Stufe 2): Bounding-Box per U-Kompatibilität (achsparalleles
                # L hat den Bounding-Umfang), Kerbe = Eck-Rechteck an inneren Fluchten.
                # PLAUSI: Stempel nicht in der Kerbe, Kerbe ≥ 0,5m² (gegen Overfitting).
                # WM-PROFIL-LEHRE: U-Fenster H∈[0,92·u/2−W .. 1,08·u/2−W] per bisect
                # statt Vierfach-Kreuzprodukt (äquivalent — dieselbe ±8%-Bedingung);
                # Kombi-BUDGET als Not-Deckel gegen Fluchten-Dichte⁶ auf Großplänen.
                lbest = None
                formen_l = []    # Eindeutigkeits-Gate wie im Rect-Zweig
                hps = sorted(hp, key=lambda p: p[1] - p[0])
                hph = [(b - a) / ptm for (a, b) in hps]
                budget = 3_000_000
                for (L_, R_) in vp:
                    W_ = (R_ - L_) / ptm
                    for k in range(_bi.bisect_left(hph, 0.92 * u_ist / 2 - W_),
                                   _bi.bisect_right(hph, 1.08 * u_ist / 2 - W_)):
                        O_, U_ = hps[k]
                        H_ = hph[k]
                        if abs(2 * (W_ + H_) - u_ist) / u_ist > 0.08:
                            continue
                        WH = W_ * H_
                        xs = fv[_bi.bisect_right(fv, L_):_bi.bisect_left(fv, R_)]
                        ys = fh[_bi.bisect_right(fh, O_):_bi.bisect_left(fh, U_)]
                        budget -= 4 * len(xs) * len(ys)
                        if budget < 0:
                            break
                        for xi in xs:
                            for yj in ys:
                                for wn_pt, ecke_x in ((xi - L_, (L_, xi)),
                                                      (R_ - xi, (xi, R_))):
                                    for hn_pt, ecke_y in ((yj - O_, (O_, yj)),
                                                          (U_ - yj, (yj, U_))):
                                        a_n = (wn_pt / ptm) * (hn_pt / ptm)
                                        if a_n < 0.5:
                                            continue
                                        if (ecke_x[0] <= rcx <= ecke_x[1]
                                                and ecke_y[0] <= rcy <= ecke_y[1]):
                                            continue    # Stempel in Kerbe
                                        err = abs(WH - a_n - f_ist)
                                        if err <= 0.05 * f_ziel:
                                            formen_l.append((W_, H_))
                                            if lbest is None or err < lbest[0]:
                                                lbest = (err, WH - a_n, 2 * (W_ + H_))
                    if budget < 0:
                        break
                if lbest and all(abs(a[0] - formen_l[0][0]) <= 0.1
                                 and abs(a[1] - formen_l[0][1]) <= 0.1
                                 for a in formen_l):
                    r["rohbau_ok"] = True
                    r["rohbau_form"] = "l"
                    r["f_rohbau"] = round(lbest[1], 2)
                    r["u_rohbau"] = round(lbest[2], 2)
        # RÄUMLICHER IoU-BEWEIS (Goldstandard, Cache-Miss-Muster: läuft nur beim
        # Erstlauf mit, danach aus dem Cache): Fluchten-Pool = Ketten ∪ geschlossene
        # Bogen-Türlinien ∪ Wand-Faces, Cluster-Mittel-Dedupe; Beweis annotiert
        # raeume[i] mit iou_bewiesen/iou_wert/iou_form (5/5 formtaugliche Angerer-
        # Räume, raster-robust).
        try:
            fv2 = [f["pos"] for f in nutzbar if f["achse"] == "v"]
            fh2 = [f["pos"] for f in nutzbar if f["achse"] == "h"]
            for bg in vektor.tuer_boegen(page, (bx0, bx1, by0, by1), ptm,
                                         pfade=pfade):
                hx, hy = bg["hinge"]

                def _po(pt):
                    r2 = (0.28 * ptm) ** 2
                    return sum(1 for hh in hatch
                               if ((hh[0] + hh[2]) / 2 - pt[0]) ** 2
                               + ((hh[1] + hh[3]) / 2 - pt[1]) ** 2 <= r2)

                na, nb = _po(bg["a"]), _po(bg["b"])
                if na == nb:
                    continue
                zu = bg["a"] if na > nb else bg["b"]
                ddx, ddy = abs(zu[0] - hx), abs(zu[1] - hy)
                if ddy < 0.2 * ddx:
                    fh2.append((hy + zu[1]) / 2.0)
                elif ddx < 0.2 * ddy:
                    fv2.append((hx + zu[0]) / 2.0)
            for w in roh:
                d2f = (w.get("dicke_cm") or 0) / 100.0 * ptm / 2.0
                if w["achse"] == "v":
                    fv2.extend([w["x0"] - d2f, w["x0"] + d2f])
                else:
                    fh2.extend([w["y0"] - d2f, w["y0"] + d2f])

            def _ddp(lst):
                out, cl = [], []
                for p in sorted(lst):
                    if cl and p - cl[-1] > 0.07 * ptm:
                        out.append(sum(cl) / len(cl))
                        cl = []
                    cl.append(p)
                if cl:
                    out.append(sum(cl) / len(cl))
                return out

            if dbg_r.get("label") is not None:
                # Der räumliche IoU-Beweis läuft jetzt AUCH auf Großplänen — dort
                # aber raum-lokal (nur_bbox): der teure Full-Pool-Fallback
                # (O(dichte⁴), einst die Grossplan-Sperre) bleibt aus, der
                # bbox-lokale Pass entfernt die Fluchten-Ambiguität, an der die
                # F+U-Beweise auf dichten Plänen scheitern. So gewinnt der
                # Goldstandard genau dort Räume, wo Roh-Status+rohbau_ok null
                # tragen (WM/TG). EFH bleibt beim vollen Beweis (nur_bbox=False).
                raumnetz.raum_iou_beweis(raeume, dbg_r["label"], dbg_r["rst"],
                                         _ddp(fv2), _ddp(fh2), ptm,
                                         nur_bbox=grossplan)
        except Exception as e:  # pragma: no cover
            print(f"[nachzeichnen] IoU-Beweis fehlgeschlagen: {e}")
        for r in raeume:
            r.pop("cx", None)
            r.pop("cy", None)
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
        "konturen": konturen,
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
            "massstab": m_label,
        },
    }


def _dach_ansicht(doc, max_px=1800):
    """DACH-/ZIMMERER-PLAN als beschriftete Ansicht (Nachvollziehbarkeit: der
    Dachdecker-Sektor lieferte Mengen, aber die Planansicht zeigte '0 Räume').
    Wählt die roof-PLAN-Seite (Sparrenlage/Draufsicht mit den meisten Velux-/
    Sparren-Labels), rendert sie und legt die byte-exakten Positionen als
    Marker darüber: Velux-Fenster am Fensterort, Dachflächen als Summen-Callout.
    → {ok, typ:'dach', basis_png, dach_marker[], dach_positionen, meta} oder None."""
    try:
        from dach_positionen import dach_positionen as _dp
    except Exception:
        return None
    dp = _dp(doc)
    if not dp:
        return None
    # Beste roof-PLAN-Seite: die mit den meisten Velux-/Sparren-Wort-Treffern
    # (Draufsicht > Ansicht/Schnitt). Fallback: erste Seite mit Dach-Text.
    best, best_score, best_words = None, -1, None
    for page in doc:
        try:
            worte = page.get_text("words")
        except Exception:
            continue
        txt = " ".join(w[4] for w in worte).lower()
        if "dach" not in txt and "sparren" not in txt and "velux" not in txt:
            continue
        score = (sum(1 for w in worte if w[4].lower() in ("velux", "roto", "fakro")) * 3
                 + sum(1 for w in worte if "sparren" in w[4].lower()))
        if score > best_score:
            best, best_score, best_words = page, score, worte
    if best is None:
        return None
    W, H = best.rect.width, best.rect.height
    scale = max(0.5, min(max_px / max(W, 1), max_px / max(H, 1), 4.0))
    try:
        import fitz as _fz
        pix = best.get_pixmap(matrix=_fz.Matrix(scale, scale))
        basis_png = pix.tobytes("png")
    except Exception:
        return None
    marker = []
    # Velux/Dachfenster am Fensterort (Wortposition 'Velux')
    n_fe = sum(fe.get("anzahl", 0) for fe in (dp.get("fenster") or []))
    fe_typ = (dp.get("fenster") or [{}])[0].get("typ") if dp.get("fenster") else None
    for w in (best_words or []):
        if w[4].lower() in ("velux", "roto", "fakro"):
            marker.append({"px": [round(w[0] * scale, 1), round(w[1] * scale, 1)],
                           "label": "Dachfenster" + (f" {fe_typ}" if fe_typ else ""),
                           "art": "fenster"})
    # Dachflächen-Summe als Callout (Wortposition der Gesamt-/Teilflächen)
    for w in (best_words or []):
        if w[4] in ("Sparrenlage", "Dachflächen", "Sparren") and not any(
                m["art"] == "flaeche" for m in marker):
            ges = dp.get("gesamt_m2")
            marker.append({"px": [round(w[0] * scale, 1), round(w[1] * scale, 1)],
                           "label": f"Σ Dachfläche {ges} m²" if ges else "Dachplan",
                           "art": "flaeche"})
    return {
        "ok": True, "typ": "dach",
        "basis_png": basis_png,
        "bild_w": pix.width, "bild_h": pix.height,
        "dach_marker": marker,
        "dach_positionen": dp,
        "raeume": [], "waende": [],
        "dateiname": None,
        "meta": {"seite": best.number, "sektor": "Dach/Zimmerer",
                 "massstab": _massstab(best)},
    }


def analysiere_doc(doc, seite=None, **kw):
    """Ganzes PDF → Seiten nach Größe probieren, die erste ANALYSIERBARE gewinnt.
    (Breiten-Sweep-Fall Mitterwurzerweg4: Dachplan-Satz mit 3 gleich großen
    Seiten — die erste ist 'Dachflächen' ohne Grundriss-Kontur, die SPARREN-
    LAGE auf Seite 2 ist analysierbar. Nur-größte-Seite gab dort auf.)
    Streng additiv: war die größte Seite ok, ist das Ergebnis identisch;
    Fehlschläge scheitern früh (Kalibrierung/Box) und kosten Sekunden.
    seite: explizite Seiten-Nr. (Multi-Geschoss: UI fordert ein anderes
    Geschoss on-demand an). meta.seite trägt immer die analysierte Seite —
    der PNG-Renderer MUSS dieselbe Seite nehmen (nicht 'die größte')."""
    if seite is not None:
        try:
            res = analysiere_seite(doc[int(seite)], **kw)
        except Exception as e:
            return {"ok": False, "grund": f"Seite {seite} nicht analysierbar: {e}"}
        if res.get("ok"):
            res["meta"]["seite"] = int(seite)
        return res
    seiten = sorted(doc, key=lambda p: -(p.rect.width * p.rect.height))
    erster = None
    for page in seiten[:8]:
        res = analysiere_seite(page, **kw)
        if res.get("ok"):
            # DACH-/ZIMMERER-PLAN: findet die Grundriss-Analyse KEINE Räume
            # (Dachplan hat keine Raumstempel), aber der Satz trägt Dach-
            # Positionen → beschriftete Dach-Ansicht statt leerer Grundriss.
            if not (res.get("raeume") or []):
                da = _dach_ansicht(doc)
                if da and da.get("dach_marker"):
                    return da
            res["meta"]["seite"] = page.number
            # WEITERE GESCHOSSE (billige Probe, nur Raumwort-Box): Einreich-
            # Sätze tragen EG/OG/KG auf eigenen Seiten — die UI bietet sie
            # als Umschalter an und fordert die Analyse on-demand an.
            weitere = []
            for p2 in seiten[:8]:
                if p2.number == page.number:
                    continue
                try:
                    worte2 = p2.get_text("words")
                    kal2 = vektor.kalibriere(worte2, _massstab(p2))
                    ptm2 = kal2.get("ptm_konsens")
                    if ptm2 and _eg_box(p2, ptm2, worte=worte2):
                        weitere.append(p2.number)
                except Exception:
                    pass
            if weitere:
                res["weitere_seiten"] = weitere
            return res
        if erster is None:
            erster = res
    return erster or {"ok": False, "grund": "Leeres Dokument"}
