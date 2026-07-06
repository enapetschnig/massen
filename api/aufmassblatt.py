"""AUFMASSBLATT — das abheftbare Prüf-Dokument (Säule C: alles nachvollziehbar).

Erzeugt ein PDF: der echte Plan-Ausschnitt mit allen EINGEZEICHNETEN Erkenntnissen —
Wände farbcodiert nach Stärke mit Längen-Labels (z.T. byte-exakt aus den Plan-
Maßketten), Fenster/Tür-Marker, Raum-Verifikations-Status (✓ bewiesen / ? prüfen),
Σ je Wandstärke, Maßstab + Datum. Das Dokument, das der Polier/AG abheftet und
gegen den Plan prüfen kann.

Input ist das nachzeichnen-Ergebnis (analysiere_seite/_doc mit basis_png-bytes).
"""
from datetime import date

FARBE = {50: (0.86, 0.12, 0.12), 38: (0.94, 0.55, 0.0), 25: (0.12, 0.31, 0.86),
         20: (0.08, 0.63, 0.24), 12: (0.59, 0.16, 0.78)}
GRAU = (0.45, 0.45, 0.45)
GRUEN = (0.09, 0.64, 0.29)
AMBER = (0.85, 0.47, 0.02)
BLAU = (0.01, 0.52, 0.78)
BRAUN = (0.71, 0.33, 0.04)


def erzeuge(nz, projekt_name="", firmen_name="", massen=None):
    """nachzeichnen-Ergebnis (ok, mit basis_png bytes) → PDF-Bytes (A3 quer).
    massen: optional {bauteile: {…: [Positionen]}, kennzahlen: {…}} → Seite 2
    'Mengen mit Formel' (B-2110-Prüfbeleg: Mengenermittlung nachvollziehbar)."""
    import fitz

    if not nz or not nz.get("ok") or not nz.get("basis_png"):
        raise ValueError("kein nachzeichenbares Ergebnis")

    W_PT, H_PT = 1190.55, 841.89          # A3 quer
    M = 28.0                              # Rand
    KOPF = 54.0
    FUSS = 96.0

    doc = fitz.open()
    page = doc.new_page(width=W_PT, height=H_PT)

    # ── Kopf ──
    heute = date.today().strftime("%d.%m.%Y")
    meta = nz.get("meta") or {}
    page.insert_text((M, M + 14), "AUFMASSBLATT — Planansicht mit erkannten Bauteilen",
                     fontsize=15, fontname="hebo")
    kopf2 = (f"Projekt: {projekt_name or '–'}   ·   Plan: {nz.get('dateiname') or '–'}   ·   "
             f"Maßstab {meta.get('massstab') or '?'}   ·   Bereich "
             f"{(meta.get('box_m') or ['?', '?'])[0]}×{(meta.get('box_m') or ['?', '?'])[1]} m   ·   {heute}")
    page.insert_text((M, M + 32), kopf2, fontsize=9, color=(0.25, 0.25, 0.25))
    if firmen_name:
        page.insert_text((W_PT - M - 200, M + 14), firmen_name, fontsize=9,
                         color=(0.25, 0.25, 0.25))

    # ── Plan-Bild einpassen ──
    bw, bh = nz["bild_w"], nz["bild_h"]
    avail_w = W_PT - 2 * M
    avail_h = H_PT - M - KOPF - FUSS
    f = min(avail_w / bw, avail_h / bh)
    iw, ih = bw * f, bh * f
    ix0 = M + (avail_w - iw) / 2.0
    iy0 = M + KOPF
    rect = fitz.Rect(ix0, iy0, ix0 + iw, iy0 + ih)
    page.insert_image(rect, stream=nz["basis_png"])
    page.draw_rect(rect, color=(0.6, 0.6, 0.6), width=0.7)

    def pt(px, py):
        return fitz.Point(ix0 + px * f, iy0 + py * f)

    # ── Gemauerte Hülle (Kontur der Wand-Maske) — der Außenumfang treibt die
    # halbe Materialliste; hier ist er am Plan prüfbar (B-2110-Prinzip) ──
    for _ki, _k in enumerate(nz.get("konturen") or []):
        _pts = _k.get("px") or []
        if len(_pts) < 3:
            continue
        for _n2 in range(1, len(_pts)):
            page.draw_line(pt(_pts[_n2 - 1][0], _pts[_n2 - 1][1]),
                           pt(_pts[_n2][0], _pts[_n2][1]),
                           color=(0.11, 0.31, 0.85), width=1.0,
                           stroke_opacity=0.55, dashes="[6 3] 0")

    # ── Byte-exakte Wandfluchten (Maßketten-Snap) — HINTER den Wänden ──
    # grün = von der Wand-Erkennung bestätigt, rot = Erkennungs-Lücke (prüfen!)
    n_fl_ok = 0
    fluchten = nz.get("fluchten") or []
    for fl in fluchten:
        ok = bool(fl.get("ok"))
        n_fl_ok += ok
        col = (0.09, 0.64, 0.29) if ok else \
            ((0.96, 0.62, 0.04) if fl.get("kurz") else (0.86, 0.15, 0.15))
        if fl.get("achse") == "v":
            a, b = pt(fl["px"], 0), pt(fl["px"], bh)
        else:
            a, b = pt(0, fl["px"]), pt(bw, fl["px"])
        page.draw_line(a, b, color=col, width=0.5, stroke_opacity=0.45,
                       dashes="[2 4] 0")

    # ── Wände einzeichnen ──
    for w in (nz.get("waende") or []):
        cm = w.get("snap_cm")
        col = FARBE.get(cm, GRAU)
        p = w["px"]
        breite = max(1.2, (w.get("staerke_px") or 4) * f)
        page.draw_line(pt(p[0], p[1]), pt(p[2], p[3]), color=col, width=breite,
                       stroke_opacity=0.75)
    for w in (nz.get("waende") or []):
        cm = w.get("snap_cm")
        if not cm or (w.get("laenge_m") or 0) < 1.2:
            continue
        p = w["px"]
        mx, my = (p[0] + p[2]) / 2.0, (p[1] + p[3]) / 2.0
        lab = f"HLZ{cm} · {w['laenge_m']:.2f}m" + ("*" if w.get("mass_exakt") else "")
        tp = pt(mx, my)
        page.insert_text(fitz.Point(tp.x - len(lab) * 1.9, tp.y - 2), lab,
                         fontsize=6.5, color=FARBE.get(cm, GRAU),
                         render_mode=0, fill_opacity=1)

    # ── Öffnungen ──
    for o in (nz.get("oeffnungen") or []):
        istF = o.get("typ") == "fenster"
        col = BLAU if istF else BRAUN
        c = pt(o["px"][0], o["px"][1])
        page.draw_circle(c, 6.5, color=(1, 1, 1), fill=col, width=1)
        page.insert_text(fitz.Point(c.x - 2.4, c.y + 2.6), "F" if istF else "T",
                         fontsize=7, color=(1, 1, 1), fontname="hebo")

    # ── Raum-Verifikation (3 Stufen: voll · Fläche exakt · prüfen) ──
    TEAL = (0.05, 0.58, 0.53)
    n_ok = 0
    n_f = 0
    raeume = nz.get("raeume") or []
    for r in raeume:
        ok = (r.get("status") == "verifiziert" or r.get("rohbau_ok")
              or r.get("iou_bewiesen"))
        f_ok = not ok and r.get("status") == "u_daneben"   # Fläche exakt, U prüfen
        if ok:
            n_ok += 1
        elif f_ok:
            n_f += 1
        col = GRUEN if ok else (TEAL if f_ok else AMBER)
        c = pt(r["px"][0], r["px"][1] - 14)
        page.draw_circle(c, 5.5, color=(1, 1, 1), fill=col, width=1)
        page.insert_text(fitz.Point(c.x - 2.2, c.y + 2.4), "✓" if (ok or f_ok) else "?",
                         fontsize=7, color=(1, 1, 1), fontname="hebo")
        # PRÜF-RÄUME am Plan beschriften (Nachvollziehbarkeit auf dem Ausdruck:
        # der Polier sieht OHNE Bildschirm, WO und WIE STARK unsere Lesung von
        # der Plan-Zahl abweicht). Nur bei nicht-voll-bestätigten Räumen, damit
        # der Plan nicht zuwuchert; byte-exakte Soll-Zahl steht schon im Stempel.
        if not ok and r.get("f_ist") and r.get("f_m2"):
            try:
                d_pct = (r["f_ist"] - r["f_m2"]) / r["f_m2"] * 100.0
                note = f"erkannt {r['f_ist']:.1f} m² ({d_pct:+.0f}%)"
                if f_ok:
                    note = f"F ok · Umfang prüfen ({r.get('u_ist', '?')} vs {r.get('u_m', '?')} m)"
                page.insert_text(fitz.Point(c.x + 8, c.y + 2.4), note,
                                 fontsize=6, color=col, fontname="helv")
            except (TypeError, ValueError):
                pass

    # ── Fuß: Legende + Summen + Ehrlichkeits-Hinweis ──
    y = H_PT - FUSS + 16
    x = M
    page.insert_text((x, y), "Legende:", fontsize=8.5, fontname="hebo")
    x += 52
    for cm, col in FARBE.items():
        page.draw_rect(fitz.Rect(x, y - 7, x + 14, y - 1), fill=col, color=col)
        page.insert_text((x + 17, y), f"HLZ {cm}", fontsize=8)
        x += 62
    page.draw_circle(fitz.Point(x + 5, y - 4), 4.5, fill=BLAU, color=BLAU)
    page.insert_text((x + 13, y), "Fenster", fontsize=8)
    x += 62
    page.draw_circle(fitz.Point(x + 5, y - 4), 4.5, fill=BRAUN, color=BRAUN)
    page.insert_text((x + 13, y), "Tür", fontsize=8)
    x += 48
    page.draw_circle(fitz.Point(x + 5, y - 4), 4.5, fill=GRUEN, color=GRUEN)
    page.insert_text((x + 13, y), "Raum geometrisch bestätigt (Fläche+Umfang = Plan-Stempel)",
                     fontsize=8)

    y += 16
    summe = nz.get("summe_m") or {}
    s_txt = "   ·   ".join(f"HLZ {k}: {v:.2f} m" for k, v in summe.items())
    page.insert_text((M, y), f"Σ Wandlängen je Stärke:  {s_txt}", fontsize=8.5)
    y += 14
    fl_txt = (f"   ·   Maßketten-Fluchten: {n_fl_ok}/{len(fluchten)} bestätigt "
              f"(grün gestrichelt; rot = Erkennungs-Lücke)") if fluchten else ""
    _kont = nz.get("konturen") or []
    if _kont:
        fl_txt += (f"   ·   Gemauerte Hülle (blau gestrichelt): "
                   f"Umfang ≈ {_kont[0].get('umfang_m')} m")
    page.insert_text((M, y),
                     f"Räume: {n_ok} voll bestätigt (Fläche+Umfang) · {n_f} Fläche exakt (Umfang prüfen) · von {len(raeume)}   ·   "
                     f"Öffnungen: {len(nz.get('oeffnungen') or [])} (byte-exakt aus STUK/FPH-Codes)   ·   "
                     f"* = Länge byte-exakt aus der Plan-Maßzahl übernommen" + fl_txt,
                     fontsize=8.5)
    y += 14
    kal = "Maßstab über Bemaßungsketten verifiziert" if meta.get("tragfaehig") \
        else "Maßstab aus Plan-Label (unbestätigt) — Längen als Sichthilfe"
    page.insert_text((M, y),
                     f"{kal}. Erzeugt aus den Plan-Vektoren (kein Schätzwert); gestrichelte/“?”-Elemente bitte am Plan prüfen.",
                     fontsize=8, color=(0.35, 0.35, 0.35))

    # ── Seite 2: MENGEN MIT FORMEL (Nachvollziehbarkeits-Audit P2) ──
    # Das abheftbare Dokument bewies bisher Wände/Räume/Öffnungen, aber keine
    # einzige ermittelte MENGE — als Prüfbeleg im Sinn ÖNORM B 2110 8.3.1.2
    # unvollständig. Jede Position mit Menge + Formel + Konfidenz.
    if massen and isinstance(massen, dict) and massen.get("bauteile"):
        p2 = doc.new_page(width=W_PT, height=H_PT)
        p2.insert_text((M, M + 14), "AUFMASSBLATT — Mengenermittlung mit Rechenweg",
                       fontsize=15, fontname="hebo")
        p2.insert_text((M, M + 32),
                       f"Projekt: {projekt_name or '–'}   ·   {heute}   ·   "
                       "Jede Menge mit Formel — händisch nachprüfbar (ÖNORM B 2110 Pkt. 8.3.1.2)",
                       fontsize=9, color=(0.25, 0.25, 0.25))
        y2 = M + 58
        SPALTE2 = W_PT / 2.0 + 10
        x2 = M
        col_w = W_PT / 2.0 - M - 20

        def _zeile(txt, fs=8.0, farbe=(0, 0, 0), bold=False):
            nonlocal y2, x2
            if y2 > H_PT - M - 14:
                y2 = M + 58
                x2 = SPALTE2 if x2 == M else M
                if x2 == M:      # beide Spalten voll → neue Seite
                    p3 = doc.new_page(width=W_PT, height=H_PT)
                    _seiten.append(p3)
            _seiten[-1].insert_text((x2, y2), txt[:150], fontsize=fs,
                                    fontname="hebo" if bold else "helv", color=farbe)
            y2 += fs + 4.5

        _seiten = [p2]
        for bauteil, rows in (massen.get("bauteile") or {}).items():
            if not rows:
                continue
            _zeile(str(bauteil), fs=9.5, bold=True)
            for r in rows:
                if not isinstance(r, dict):
                    continue
                kf = r.get("konfidenz")
                kf_txt = f"  [{int(round(float(kf) * 100))}%]" if kf is not None else ""
                _zeile(f"  {r.get('material')}: {r.get('menge')} {r.get('einheit')}{kf_txt}",
                       fs=8.5)
                if r.get("formel"):
                    _zeile(f"    = {r['formel']}", fs=7.5, farbe=(0.35, 0.35, 0.35))
            y2 += 4
        kz = massen.get("kennzahlen") or {}
        if kz:
            _zeile("Kennzahlen (Treiber der Mengen)", fs=9.5, bold=True)
            for k2, v2 in kz.items():
                _zeile(f"  {k2}: {v2}", fs=8.0)

    out = doc.tobytes(deflate=True)
    doc.close()
    return out
