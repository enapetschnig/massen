"""Byte-exakte FARB-LEGENDE aus dem PDF-Text-Layer + Vektor-Swatches.

Viele AT-Bau-Pläne führen eine Legende-Box "Neubau / Bestand / Abbruch", jeweils mit
einem farbigen Swatch (Wort + kleines gefülltes Rechteck). Diese Legende steht
BYTE-EXAKT im PDF (Wort im Text-Layer, Swatch als Vektor-Fill) — KEIN Vision nötig,
um zu wissen WELCHE Farbe was bedeutet.

Empirisch an echten Plänen verifiziert (venv mit PyMuPDF, scripts/test_farben.py):
  • Angerer / AP.01 (Büro Hohenwarter): Neubau=rot(1,0,0), Abbruch=gelb(1,1,0),
    Bestand=grau. Angerer hat ECHTEN Bestand/Abbruch (Bestandshütte ×5 Labels,
    Abbruch-Gelb 13,5% gezeichneter Inhalt). AP.01 trägt DIESELBE Legende als
    Plankopf-BOILERPLATE, aber 0,1% Inhalt → KEIN echter Abbruch.
  • WA_Velden: BESTAND/ABBRUCH-Legende (Abbruch=gold 1,0.84,0), aber Boilerplate.
  • HAUS A / EG-Wand-Grundriss: KEINE Neubau/Bestand/Abbruch-Legende → reiner Neubau.

PRÄZISIONS-GATE (gegen Plankopf-Boilerplate-Fehlalarm, der sonst je Büro-Template bei
JEDEM reinen Neubau-Plan feuern würde): hat_bestand/hat_abbruch werden NUR True, wenn
die Bedeutung in der Legende steht UND tatsächlich gezeichnet ist — über die Wort-
Häufigkeit (Objekt-Labels jenseits der einen Legende-Zeile) bzw. die EXAKTE Swatch-
Farbe als Zeichnungs-Inhalt jenseits des Swatches. Empirisch trennt das Angerer (echt)
sauber von AP.01/WA_Velden (Boilerplate).

EHRLICHER SCOPE: Das Legende-MAPPING ist byte-exakt. Die Wand-für-Wand-Region-Zuordnung
ist es NICHT (Schraffur nutzt gemischte Material-Farben gelb/orange/grau, die nicht
sauber auf die Legende mappen) → bleibt ein Vision-Job (Architektur: Vision = Semantik,
Vektoren = Maß). Daher v1: WARNEN statt still filtern (sicher, kein Mengen-Eingriff).

Read-only, best-effort: läuft im Live-Upload-Pfad und darf NIE einen Upload brechen —
jede Ausnahme degradiert auf das neutrale (reiner-Neubau-)Ergebnis.
"""
import math
from collections import defaultdict

# Wort → Bedeutung. Nur exakte Legende-Begriffe; Objekt-Labels wie "Bestandshütte"
# werden über exakte Wort-Gleichheit ausgeschlossen (==, nicht "in").
_BEDEUTUNG_WORTE = {
    "neubau": "neubau",
    "bestand": "bestand",
    "abbruch": "abbruch",
    "abzubrechen": "abbruch",
    "rückbau": "abbruch",
    "ruckbau": "abbruch",
    "abtrag": "abbruch",
}
_KERN = ("neubau", "bestand", "abbruch")

# Swatch-Geometrie (großzügig für verschiedene Büros/Skalen, s. Review)
_SW_MIN_W, _SW_MAX_W = 4.0, 120.0
_SW_MIN_H, _SW_MAX_H = 3.0, 40.0
# Präzisions-Schwellen (empirisch: Angerer 13,5% vs AP.01 0,1%; Bestand-Wort ×6 vs ×1)
_ABBRUCH_INHALT_MIN = 0.01      # ≥1% exakte Abbruch-Farbe gezeichnet → echt
_WORT_MIN_ECHT = 2              # Legende-Wort + ≥1 Objekt-Label → echt
_RGB_TOL = 0.06                 # exakte-Farb-Match-Toleranz pro Kanal


def _norm_rgb(col):
    """PyMuPDF-Farbe → (r,g,b) 0..1 oder None. Robust gegen DeviceGray (single float),
    CMYK (4-Tupel) und Müll — sonst würde `r,g,b = col` den Upload sprengen."""
    if col is None:
        return None
    if isinstance(col, (int, float)):
        g = float(col)
        return (g, g, g)
    try:
        seq = [float(x) for x in col]
    except (TypeError, ValueError):
        return None
    n = len(seq)
    if n == 1:
        return (seq[0], seq[0], seq[0])
    if n == 3:
        return (seq[0], seq[1], seq[2])
    if n == 4:                      # CMYK → RGB
        c, m, y, k = seq
        return ((1 - c) * (1 - k), (1 - m) * (1 - k), (1 - y) * (1 - k))
    return None


def _klasse(col):
    """RGB → grobe Farbklasse (nur für Lesbarkeit; Matching läuft über exakte RGB)."""
    rgb = _norm_rgb(col)
    if rgb is None:
        return None
    r, g, b = rgb
    mx, mn = max(r, g, b), min(r, g, b)
    if mx - mn < 0.12:
        if mx > 0.85:
            return "weiss"
        return "schwarz" if mx < 0.25 else "grau"
    # gelb/gold-Familie (deckt 1,1,0 und Gold 1,0.84,0; weite Bande gg. harte Kante)
    if r > 0.7 and 0.45 <= g <= 1.0 and b < 0.35:
        return "gelb"
    if r > g and r > b:
        return "rot" if g < 0.35 else "orange"
    if g > r and g > b:
        return "gruen"
    if b > r and b > g:
        return "blau"
    return "andere"


def _rgb_nah(a, b, tol=_RGB_TOL):
    return a is not None and b is not None and all(abs(x - y) <= tol for x, y in zip(a, b))


def _rect_ok(rc):
    if rc is None:
        return False
    try:
        if rc.is_infinite or rc.is_empty:
            return False
        w, h = rc.width, rc.height
    except Exception:
        return False
    return all(math.isfinite(v) for v in (w, h, rc.x0, rc.y0, rc.x1, rc.y1))


def _swatch_kandidaten(drawings):
    """Alle Swatch-tauglichen GEFÜLLTEN Rechtecke einer Seite → [(cx, cy, rgb)].
    Iteriert p['items'] je 're'-Element (nicht den Pfad-Bounding-Rect — gruppierte
    CAD-Legende-Blöcke sind EIN Pfad), verlangt eine Füllfarbe (kein Stroke-Fallback,
    sonst maskiert eine schwarze Outline den Swatch). Muster wie api/vektor.py:_drawings."""
    out = []
    for p in drawings:
        typ = p.get("type") or ""
        fill = p.get("fill")
        if "f" not in typ or fill is None:
            continue
        rgb = _norm_rgb(fill)
        if rgb is None:
            continue
        rects = []
        for it in (p.get("items") or []):
            if it and it[0] == "re":
                rects.append(it[1])
        if not rects:                      # gefüllter Pfad ohne 're' → Pfad-Rect als Fallback
            rc = p.get("rect")
            if rc is not None:
                rects.append(rc)
        for rc in rects:
            if not _rect_ok(rc):
                continue
            w, h = rc.width, rc.height
            if _SW_MIN_W <= w <= _SW_MAX_W and _SW_MIN_H <= h <= _SW_MAX_H:
                out.append(((rc.x0 + rc.x1) / 2.0, (rc.y0 + rc.y1) / 2.0,
                            tuple(round(c, 3) for c in rgb)))
    return out


def _swatch_near(kandidaten, x0, y0, x1, y1, max_dx=180.0, max_dy=14.0):
    """Nächster Swatch zu einem Legende-Wort (gleiche Höhe, links/rechts)."""
    cy = (y0 + y1) / 2.0
    wcx = (x0 + x1) / 2.0
    best = None
    for (mx, my, rgb) in kandidaten:
        if abs(my - cy) > max_dy:
            continue
        dx = abs(mx - wcx)
        if dx > max_dx:
            continue
        if best is None or dx < best[0]:
            best = (dx, rgb)
    if best is None:
        return None, None
    return best[1], _klasse(best[1])


def _wort_bedeutung(text):
    """Exaktes Legende-Wort → Bedeutung (sonst None). 'Bestandshütte' fällt raus (==)."""
    t = (text or "").strip().lower().strip(":·.-—")
    return _BEDEUTUNG_WORTE.get(t)


def _derotiert_words(page):
    """get_text('words') in der UNROTIERTEN Zeichnungs-Ebene (wie get_drawings).
    Auf /Rotate-90/270-Blättern (A1/A3 quer) leben Text und Vektoren sonst in
    verschiedenen Koordinaten → Swatch wird nie gefunden."""
    words = page.get_text("words")
    rot = getattr(page, "rotation", 0) or 0
    if not rot:
        return [(w[0], w[1], w[2], w[3], w[4]) for w in words]
    try:
        import fitz
        dm = page.derotation_matrix
        out = []
        for w in words:
            r = fitz.Rect(w[0], w[1], w[2], w[3]) * dm
            out.append((r.x0, r.y0, r.x1, r.y1, w[4]))
        return out
    except Exception:
        return [(w[0], w[1], w[2], w[3], w[4]) for w in words]


def _legende_treffer(words):
    """Legende-Wörter inkl. Mehr-Token-Joins ('Neu bau', 'Ab bruch').
    Liefert [(bedeutung, x0, y0, x1, y1)]."""
    out = []
    # nach Zeile (y-Band) gruppieren für saubere Nachbar-Joins
    zeilen = defaultdict(list)
    for (x0, y0, x1, y1, txt) in words:
        zeilen[round((y0 + y1) / 2.0 / 3.0)].append((x0, y0, x1, y1, txt))
    for _k, ws in zeilen.items():
        ws.sort(key=lambda w: w[0])
        for i, w in enumerate(ws):
            bd = _wort_bedeutung(w[4])
            if bd:
                out.append((bd, w[0], w[1], w[2], w[3]))
                continue
            # Nachbar-Join: 'Neu'+'bau' → 'neubau' (kleiner x-Gap, gleiche Zeile)
            if i + 1 < len(ws):
                nxt = ws[i + 1]
                if nxt[0] - w[2] < 18.0:
                    join = (w[4] + nxt[4]).replace("-", "")
                    bd2 = _wort_bedeutung(join)
                    if bd2:
                        out.append((bd2, w[0], w[1], nxt[2], nxt[3]))
    return out


def lies_farb_legende(page, words=None):
    """Eine Seite → {bedeutung: {rgb, klasse, wort_pos, n_vorkommen}}.
    `words` (derotiert) kann übergeben werden, um Doppelarbeit zu sparen."""
    if words is None:
        words = _derotiert_words(page)
    treffer = _legende_treffer(words)
    if not treffer:
        return {}
    kand = _swatch_kandidaten(page.get_drawings())
    gefunden = defaultdict(list)
    for (bd, x0, y0, x1, y1) in treffer:
        rgb, kl = _swatch_near(kand, x0, y0, x1, y1)
        gefunden[bd].append({"rgb": rgb, "klasse": kl, "wort_pos": (round(x0), round(y0))})
    out = {}
    for bd, lst in gefunden.items():
        mit = [t for t in lst if t["rgb"] is not None]
        out[bd] = dict(mit[0] if mit else lst[0])
        out[bd]["n_vorkommen"] = len(lst)
    return out


def _farb_inhalt_anteil(page, ziel_rgb, leg_positions):
    """Anteil der EXAKTEN Ziel-Farbe als gezeichneter Inhalt (Länge l + Umfang re),
    jenseits der Legende-Swatch-Region. Trennt echten Abbruch (13,5%) von Boilerplate
    (0,1%). Bewusst exakte RGB-Toleranz, NICHT _klasse (Wand-Schraffur ist selbst gelb)."""
    if ziel_rgb is None:
        return 0.0
    L_ziel = 0.0
    L_tot = 0.0
    for p in page.get_drawings():
        rgb = _norm_rgb(p.get("color") or p.get("fill"))
        for it in (p.get("items") or []):
            if not it:
                continue
            if it[0] == "l":
                a, b = it[1], it[2]
                ln = abs(a.x - b.x) + abs(a.y - b.y)
            elif it[0] == "re" and _rect_ok(it[1]):
                ln = 2 * (it[1].width + it[1].height)
            else:
                continue
            # Mittelpunkt grob
            if it[0] == "l":
                mx, my = (it[1].x + it[2].x) / 2.0, (it[1].y + it[2].y) / 2.0
            else:
                mx, my = (it[1].x0 + it[1].x1) / 2.0, (it[1].y0 + it[1].y1) / 2.0
            if any(abs(mx - lx) < 130 and abs(my - ly) < 95 for (lx, ly) in leg_positions):
                continue
            L_tot += ln
            if _rgb_nah(rgb, ziel_rgb):
                L_ziel += ln
    return (L_ziel / L_tot) if L_tot else 0.0


def _wort_anzahl(doc, praefixe):
    """Wie oft kommt eines der Präfixe als Wort-Anfang im ganzen Dokument vor."""
    n = 0
    for page in doc:
        try:
            for w in page.get_text("words"):
                wl = (w[4] or "").lower()
                if any(wl.startswith(p) for p in praefixe):
                    n += 1
        except Exception:
            continue
    return n


def _wort_anzahl_max_seite(doc, praefixe):
    """Maximale Vorkommen auf EINER Seite (statt Dokument-Summe). Ein reiner Neubau-
    Plan mit der Boilerplate-Legende 'Neubau/Bestand/Abbruch' im Plankopf JEDER Seite
    hätte dokumentweit ≥2 'Bestand' (je 1 pro Blatt) und riebe das Boilerplate-Gate
    auf. Pro-Seite-Max bleibt für reine Boilerplate = 1; echter Bestand (Legende +
    ≥1 Objekt-Label auf DEMSELBEN Blatt) erreicht ≥2 auf einer Seite."""
    best = 0
    for page in doc:
        try:
            c = sum(1 for w in page.get_text("words")
                    if any((w[4] or "").lower().startswith(p) for p in praefixe))
            best = max(best, c)
        except Exception:
            continue
    return best


_NEUTRAL = {"hat_bestand": False, "hat_abbruch": False, "mapping": {},
            "seite": None, "hinweis": None}


def analysiere_dokument(doc):
    """Ganzes PDF → ehrliche Plan-Flagge mit Präzisions-Gate gegen Boilerplate.
    Reiner Neubau (keine echten Bestand/Abbruch-Elemente) → alle False, kein Hinweis
    (Massen unverändert) → der validierte Neubau-Fall bleibt ein exaktes No-Op.
    Best-effort: jede Ausnahme degradiert auf das neutrale Ergebnis (bricht nie Upload)."""
    try:
        best_seite, best_map, best_page = None, {}, None
        for idx, page in enumerate(doc):
            try:
                words = _derotiert_words(page)
            except Exception:
                continue
            # Performance-Prefilter: nur Seiten mit ≥2 Kern-Wörtern bekommen get_drawings()
            wset = {(_wort_bedeutung(w[4])) for w in words}
            kern_da = [b for b in _KERN if b in wset]
            if len(kern_da) < 2:
                continue
            try:
                m = lies_farb_legende(page, words=words)
            except Exception:
                continue
            kern = [b for b in _KERN if b in m]
            if len(kern) > len([b for b in _KERN if b in best_map]):
                best_seite, best_map, best_page = idx, m, page
                if len(kern) == 3:
                    break

        if not best_map:
            return dict(_NEUTRAL)

        # ── Präzisions-Gate: Legende-Wort UND tatsächlich gezeichnet ──
        # PER-SEITE-Max (nicht Dokument-Summe): sonst zählt die wiederholte Plankopf-
        # Boilerplate über mehrere Blätter fälschlich als Objekt-Labels (Mehrblatt-
        # Neubau-Set → falsche 'Umbau/Sanierung'-Warnung).
        n_best = _wort_anzahl_max_seite(doc, ("bestand",))
        n_abb = _wort_anzahl_max_seite(doc, ("abbruch", "abzubrech", "rückbau", "ruckbau"))
        hat_b = ("bestand" in best_map) and (n_best >= _WORT_MIN_ECHT)
        leg_pos = [d.get("wort_pos") or (0, 0) for d in best_map.values()]
        abb_rgb = (best_map.get("abbruch") or {}).get("rgb")
        abb_inhalt = 0.0
        if "abbruch" in best_map and best_page is not None:
            try:
                abb_inhalt = _farb_inhalt_anteil(best_page, abb_rgb, leg_pos)
            except Exception:
                abb_inhalt = 0.0
        hat_a = ("abbruch" in best_map) and (n_abb >= _WORT_MIN_ECHT
                                             or abb_inhalt >= _ABBRUCH_INHALT_MIN)

        hinweis = None
        if hat_b or hat_a:
            teile = []
            if hat_b:
                teile.append("Bestand")
            if hat_a:
                teile.append("Abbruch")
            t = "/".join(teile)
            hinweis = (f"Plan enthält {t}-Bauteile (laut Legende + im Plan gezeichnet). "
                       f"Die Massen beziehen sich auf den Neubau — {t} ist NICHT automatisch "
                       f"herausgerechnet, bitte separat prüfen.")

        return {
            "hat_bestand": hat_b,
            "hat_abbruch": hat_a,
            "mapping": {b: dict(d) for b, d in best_map.items()},
            "seite": best_seite,
            "hinweis": hinweis,
            "_debug": {"n_bestand_wort": n_best, "n_abbruch_wort": n_abb,
                       "abbruch_inhalt_pct": round(abb_inhalt * 100, 1)},
        }
    except Exception:
        return dict(_NEUTRAL)
