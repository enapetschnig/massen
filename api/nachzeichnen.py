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
import math
import os
import re

import vektor

LEG = [50, 38, 25, 20, 12]
# AUCH AUSSENRAUM-WOERTER: die Grundriss-Box endet 4 m unter dem untersten
# TREFFER dieser Liste. Ohne "Terrasse" endete sie am Angerer-Plan mitten im
# Gebaeude — die ueberdachte Terrasse und die ganze Suedseite wurden vor dem
# Rendern abgeschnitten (Nutzer-Befund "der untere Teil ist abgeschnitten";
# gemessen: 69 % der dunklen Wandlinien lagen unterhalb der Box, das
# Terrassen-Label bei y=35 % der Seite war unsichtbar fuer die Liste).
# "Loggia" fehlt hier BEWUSST: am WM-Plan (Haeuser C+D auf einem Blatt)
# verkettet es die Label-Cluster ueber die Gebaeude hinweg und verdoppelt
# die Box (31,6 -> 57,7 m Breite, je Wort einzeln gemessen). Die Loggien
# sind dort ueber ihre F/U-Stempel abgedeckt — die Stempel-Box (Stufe 2)
# braucht das Wort nicht.
INNEN_WORTE = ["Wohnraum", "Waschen", "Bad", "WC", "Flur", "Zimmer", "Küche",
               "Geräte", "Schlafen", "Wohnen", "Diele", "Abstell", "Gang", "Kind",
               "Eltern", "Büro"]
RAUM_WORTE = INNEN_WORTE + ["Terrasse", "Balkon", "Vorraum", "Carport"]


def _massstab(page):
    m = re.search(r"1\s*:\s*(\d{2,4})", page.get_text())
    return f"1:{m.group(1)}" if m else None


def _eg_box(page, ptm, worte=None, liste=None):
    W, H = page.rect.width, page.rect.height
    _lst = liste if liste is not None else RAUM_WORTE
    pos = [(w[0], w[1]) for w in (worte if worte is not None else page.get_text("words"))
           if any(r.lower() in w[4].lower() for r in _lst)
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


def _rdp(punkte, eps):
    """Douglas-Peucker-Vereinfachung eines Polygonzugs (Ecken-Reduktion). eps in
    denselben Einheiten wie die Punkte. Entfernt Raster-Zacken, die den Umfang
    künstlich aufblähen, ohne echte Ecken zu verlieren."""
    if len(punkte) < 3:
        return list(punkte)
    x0, y0 = punkte[0]
    x1, y1 = punkte[-1]
    dx, dy = x1 - x0, y1 - y0
    seg = (dx * dx + dy * dy) ** 0.5
    dmax, idx = 0.0, 0
    for i in range(1, len(punkte) - 1):
        px, py = punkte[i]
        if seg < 1e-9:
            d = ((px - x0) ** 2 + (py - y0) ** 2) ** 0.5
        else:
            d = abs(dy * px - dx * py + x1 * y0 - y1 * x0) / seg
        if d > dmax:
            dmax, idx = d, i
    if dmax > eps:
        links = _rdp(punkte[:idx + 1], eps)
        rechts = _rdp(punkte[idx:], eps)
        return links[:-1] + rechts
    return [punkte[0], punkte[-1]]


def geometrie_umfang(reg_pt, f_m2, ptm, poly_exakt=False):
    """DETERMINISTISCHER Raum-Umfang aus dem rekonstruierten Polygon.

    Der Umfang ist der Hebel für Pläne, die Fläche+Höhe, aber KEINEN Umfang
    stempeln (Polierpläne wie Angerer AP.01): dort kam U bisher aus schwankender
    Vision. Das Polygon (raum_regionen, bereits flächen-treu ±20% gegated) liefert
    die FORM, die byte-exakte Stempel-Fläche pinnt die SKALA — U wird also aus der
    Geometrie abgeleitet UND per F kalibriert (korrigiert kleine Raster-/Erosions-
    Bias, die die Roh-Polygonfläche ~5-10% unter F drücken). Rein deterministisch.

    ZWEI robuste Schätzer werden GEMITTELT (geometrisches Mittel), weil ihre
    Fehler entgegengesetzt sind: (1) die F-kalibrierte Polygon-UMFANGLÄNGE (folgt
    echten Ecken, ÜBERschätzt aber verwinkelte/zackige Räume — Flur bis +32%);
    (2) die BBOX-Seitenverhältnis-Isoperimetrie (glatt, UNTERschätzt konkave/
    L-Räume). Das Mittel klammert die Wahrheit — am Angerer byte-exakt validiert:
    Flur +32%→−2%, Wohnraum Küche +20%→+2%, alle 5 Räume ±7%.

    reg_pt: [(x,y),…] Polygon in Seiten-pt; f_m2: byte-exakte Fläche (oder None);
    ptm: pt pro Meter. Rückgabe: {u_m, u_poly_m, u_bbox_m, a_poly_m2} oder None."""
    if not reg_pt or len(reg_pt) < 3 or not ptm or ptm <= 0:
        return None
    # Fläche aus dem ROH-Polygon (Zacken verfälschen die Fläche kaum).
    A = 0.0
    n = len(reg_pt)
    xs = []
    ys = []
    for i in range(n):
        x1, y1 = reg_pt[i]
        x2, y2 = reg_pt[(i + 1) % n]
        A += x1 * y2 - x2 * y1
        xs.append(x1)
        ys.append(y1)
    a_m2 = abs(A) / 2.0 / (ptm * ptm)
    if a_m2 <= 0:
        return None
    # (1) Umfang aus dem VEREINFACHTEN Polygon (Douglas-Peucker, ~12cm gegen
    # Raster-Zacken), an der byte-exakten Fläche kalibriert (U ~ √F).
    poly = _rdp(list(reg_pt), 0.12 * ptm)
    if len(poly) < 3:
        poly = list(reg_pt)
    U = 0.0
    m = len(poly)
    for i in range(m):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % m]
        U += ((x2 - x1) ** 2 + (y2 - y1) ** 2) ** 0.5
    u_poly = U / ptm
    if u_poly <= 0:
        return None
    flaeche = f_m2 if (f_m2 and f_m2 > 0) else a_m2
    if f_m2 and f_m2 > 0:
        k = (f_m2 / a_m2) ** 0.5
        if 0.8 <= k <= 1.25:
            u_poly = u_poly * k
    # (2) BBOX-Seitenverhältnis → isoperimetrischer Umfang (glatt, konkav-blind).
    bw = (max(xs) - min(xs)) / ptm
    bh = (max(ys) - min(ys)) / ptm
    if bw <= 0 or bh <= 0:
        return None
    asp = max(bw, bh) / min(bw, bh)
    u_bbox = 2.0 * ((flaeche * asp) ** 0.5 + (flaeche / asp) ** 0.5)
    # geometrisches Mittel der beiden Schätzer — ABER NUR, WO DAS
    # BBOX-MODELL GILT. Es unterstellt einen kompakten (konvex-artigen)
    # Raum; ein verzweigter Raum (L/T-Form) fuellt seine Bounding-Box nur
    # teilweise, und dann raet das Modell STRUKTURELL zu kurz.
    # Am Angerer-Flur nachgerechnet (2026-08-08): Region-U 22,67 m bei
    # Stempel 22,57 (+0,4 % — die Erkennung stimmt!), Fuellgrad 57 %,
    # u_bbox 16,0 → Mittel 18,25 = −19 % → Badge "Form widerlegt" auf einem
    # RICHTIGEN Umriss. Das Mittel stammt aus der Zeit ZACKIGER Polygone
    # (Docstring oben: "Flur +32 %"), die der Vektor-Snap seither begradigt
    # hat — die Praemisse "u_poly ueberschaetzt" gilt dort nicht mehr.
    # Darum: bei Fuellgrad < 0,72 traegt das Polygon allein (F-kalibriert);
    # kompakte Raeume behalten das bewaehrte Mittel.
    # ZWEITE BEDINGUNG, am Korpus gelernt (2026-08-08): das Polygon traegt
    # allein nur, wenn es VEKTOR-EXAKT auf Wandlinien gesnappt wurde
    # (poly_exakt). Ein zackiges Raster-Polygon UEBERschaetzt den Umfang —
    # ohne diese Bedingung klagte das Fuellgrad-Tor auf WM 4 und auf Velden
    # 2 RICHTIGE Umrisse neu als "Form widerlegt" an (2->6 bzw. 1->3),
    # waehrend es auf Angerer (vektor-gesnappt) den Flur korrekt heilte.
    fuell = a_m2 / max(1e-9, bw * bh)
    if fuell < 0.72 and poly_exakt:
        u_m = u_poly
    else:
        u_m = (u_poly * u_bbox) ** 0.5
    return {"u_m": round(u_m, 2), "u_poly_m": round(u_poly, 2),
            "u_bbox_m": round(u_bbox, 2), "a_poly_m2": round(a_m2, 2)}


def _tb_wort(wort):
    """Benennt dieses Wort eine TROCKENBAU-WAND (LG 39)?

    Zwei Verwechslungen sind hier belegt und werden ausgeschlossen:

    1. Eine PLATTE ist keine WAND. Das frühere Muster „gipskarton" traf auch
       „Gipskartonplatte" — ein Material-Eintrag der Schichtaufbau-Legende.
       Auf AP.01 und am Angerer war das der EINZIGE Treffer, und der Hinweis
       riet dort, 74 bzw. 63 m Wandlänge von LG 08 nach LG 39 zu buchen.
    2. HOLZständerwand ist Zimmerer (LG 36), nicht Trockenbau. Die
       Teilzeichenketten-Prüfung „ständerwand" trifft sie mit.
    """
    w = (wort or "").lower()
    if not w:
        return False
    if "holzständer" in w or "holzstaender" in w or "holzriegel" in w:
        return False
    return ("trockenbauw" in w or "gipskartonwand" in w
            or "gipskartonwände" in w or "vorsatzschale" in w
            or "ständerwand" in w or "staenderwand" in w
            or "metallständer" in w)


def isoperimetrischer_umfang(f_m2, aspekt=1.35):
    """FALLBACK-Umfang für Räume OHNE Polygon UND ohne U-Stempel: aus der byte-
    exakten Fläche + angenommenem Seitenverhältnis (Default 1,35 ≈ typischer
    Wohnraum). Exakt für Rechtecke, Untergrenze für verwinkelte Räume. Klar als
    Schätzung zu flaggen (umfang_quelle='geschaetzt')."""
    if not f_m2 or f_m2 <= 0:
        return None
    r = max(1.0, float(aspekt))
    # F = a*b, r = a/b → b = √(F/r), a = √(F*r); U = 2(a+b)
    u = 2.0 * ((f_m2 * r) ** 0.5 + (f_m2 / r) ** 0.5)
    return round(u, 2)


def textflecken(arr, zell=2, max_zellen=400):
    """Textartige Flecken in einem Graustufenbild finden -> [(cx, cy)] in Pixeln.

    DER Positions-Anker fuer Scans. Vision weiss WELCHE Raeume es gibt (Name
    und Flaeche byte-exakt aus dem Stempel), trifft die LAGE aber nur grob und
    schwankt lauf-zu-lauf um ~20 px. Eine Raumbeschriftung ist dagegen ein
    Textfleck im Bild und liegt bei gleichem Bild immer gleich — der Anker
    wird dadurch deterministisch.

    EINZIGE Kopie. Sie hat frueher doppelt existiert (Pipeline + Waechter)
    und ist auseinandergelaufen; seitdem misst der Waechter genau das, was
    der Nutzer bekommt.

    ZUM GROESSENFILTER — was gemessen und VERWORFEN wurde:
    Naheliegend waere, die Groessen in Bauwerks-Metern statt in Rasterzellen
    zu pruefen (Planschrift ist ~2,5-3,5 mm auf dem Papier, je nach Massstab
    also 0,1-0,4 m des Bauwerks). Am Korpus A/B-getestet — derselbe Plan,
    dasselbe Bild, nur der Filter wechselt (28-100 px/m Spanne):

        Zellen 3..60 / h<=12   Median 0,95 m   12/113 unter 0,25 m   <- beste
        Meter 0,06-0,60 m             0,99 m   11/113
        Meter 0,04-1,00 m             0,99 m   12/113
        Meter 0,04-1,50 m             0,97 m   12/113
        Meter bis 1,0 + breit         0,99 m   11/113
        nur waagrecht bw>=2bh         1,05 m   10/113

    Der Zellen-Filter gewinnt auf BEIDEN Massen. Grund: bw/bh zaehlen Zellen,
    nicht Pixel — bei 28 px/m deckelt der Meter-Filter die Texthoehe auf rund
    4 Zellen statt 12 und wirft zweizeilige Raumstempel weg. Nicht nochmal
    als "massstabsunabhaengige Verbesserung" einbauen: es ist keine.

    ZUR ZELLGROESSE 2 (frueher 4) — die URSACHE, gemessen 2026-07-29:
    Der Anker war auf grob aufgeloesten Plaenen unbrauchbar (AU_WM_01 1,50 m,
    Velden 0,90 m) und auf fein aufgeloesten sehr gut (Angerer 0,04 m). Der
    Grund ist nicht Textdichte, wie lange vermutet, sondern die RASTERUNG:

        dunkelster Grauwert an der Raumbeschriftung (Median je Plan)
        Angerer  100 px/m ->   0    AU_WM_01  28 px/m -> 153
        AP.01     96 px/m ->   0    Velden    28 px/m -> 149

    Bei 28 px/m ist die Stempelschrift so klein, dass sie zu hellgrau
    verwischt; sie reisst die Schwelle 160 kaum und fuellt eine 4-px-Zelle
    nicht zu den geforderten 8 %. Die Schrift kommt also gar nicht erst in
    die Maske — an 88 von 98 verfehlten Stempeln lag nicht einmal eine
    VERWORFENE Komponente in der Naehe. Kein Filter- und kein
    Zuordnungsproblem.

    Zwei Gegenmittel gemessen, dasselbe Ziel: feiner RENDERN (140 px/m kaeme
    auf 0,26 m, braucht aber 62 MPixel fuer AU_WM_01 — serverless nicht
    tragbar) oder feinere ZELLE bei unveraendertem Bild. Zweiteres gewaehlt.

    Am Bild, das die Pipeline wirklich benutzt (je Plan seine eigene Skala),
    ueber alle 113 Stempel der vier Referenzplaene:

        zell   Median   unter 0,5 m   unter 0,25 m   Zeit (schlimmster Plan)
          2    0,56 m     51/113        25/113            0,42 s   <- jetzt
          3    0,71 m     41/113        17/113            0,33 s
          4    1,12 m     24/113        14/113            0,17 s   <- vorher
          5    1,19 m     18/113        10/113            0,11 s

    Monoton und auf JEDEM der vier Plaene besser (Angerer 0,04->0,04 m,
    AP.01 0,52->0,45, AU_WM_01 1,48->0,66, Velden 0,90->0,55).

    ACHTUNG bei diesen Zahlen — zwei Einschraenkungen, beide gemessen:

    (1) "Median" ist hier der Median ueber ALLE 113 Stempel. Eine frueher
        hier stehende Tabelle nannte 0,90 statt 1,12 m fuer zell=4: das war
        der Median der vier PLAN-Mediane, also der drittkleinste von vier
        Werten, nicht der Korpus-Median. Der Unterschied ist erheblich, weil
        AU_WM_01 allein 70 der 113 Stempel stellt.

    (2) WICHTIGER: diese vier Plaene sind VEKTOR-Plaene, und auf ihnen laeuft
        diese Funktion in der Produktion gar nicht. Der einzige Aufrufer ist
        api/extract.py::_vision_raum_regionen, und der steigt sofort aus,
        sobald auch nur EIN Raum ein rekonstruiertes Polygon hat — bei allen
        vier ist das fuer JEDEN Raum der Fall (9/9, 9/9, 70/70, 25/25). Der
        Anker greift nur bei echten Scans ohne Vektor-Geometrie. Die Zahlen
        oben sind also ein STELLVERTRETER: sie belegen, dass der Detektor
        Raumbeschriftungen in einem gerasterten Plan besser findet, nicht,
        dass die Einrastung beim Nutzer besser wird. Fuer den Beweis fehlt
        ein Korpus aus echten Plan-Scans; lokal liegt keiner.

    Den Groessenfilter mitzuskalieren (bw<=120, bh<=24, damit er dieselbe
    physische Groesse meint) bringt 51 -> 53 von 113: im Rauschen. Bewusst
    NICHT gemacht — eine Aenderung mit klarem Beleg ist besser als zwei, von
    denen eine geraten ist.
    """
    import numpy as _np
    from collections import deque as _dq
    h, w = arr.shape
    H, W = h // zell, w // zell
    if H < 3 or W < 3:
        return []
    blk = arr[:H * zell, :W * zell].reshape(H, zell, W, zell)
    ant = (blk < 160).mean(axis=(1, 3))
    # beschriftet = etwas dunkel, aber nicht Wand-massiv
    mk = (ant > 0.08) & (ant < 0.75)
    m2 = mk.copy()
    for d in (1, 2):            # waagrecht schliessen: Buchstabenluecken
        m2[:, d:] |= mk[:, :-d]
        m2[:, :-d] |= mk[:, d:]
    ges = _np.zeros_like(m2, dtype=bool)
    out = []
    for j in range(H):
        for i in range(W):
            if not m2[j, i] or ges[j, i]:
                continue
            q = _dq([(j, i)]); ges[j, i] = True
            zl = []
            while q:
                y, x = q.popleft(); zl.append((y, x))
                if len(zl) > max_zellen:
                    break
                for dy, dx in ((0, 1), (0, -1), (1, 0), (-1, 0)):
                    ny, nx = y + dy, x + dx
                    if 0 <= ny < H and 0 <= nx < W and m2[ny, nx] and not ges[ny, nx]:
                        ges[ny, nx] = True; q.append((ny, nx))
            if not (3 <= len(zl) <= max_zellen):
                continue
            ys = [t[0] for t in zl]; xs = [t[1] for t in zl]
            bw = max(xs) - min(xs) + 1
            bh = max(ys) - min(ys) + 1
            if bh > bw:                       # Text liegt waagrecht
                continue
            if not (3 <= bw <= 60) or bh > 12:
                continue
            out.append(((min(xs) + max(xs) + 1) / 2 * zell,
                        (min(ys) + max(ys) + 1) / 2 * zell))
    return out



def rechtwinklig_ziehen(poly, tol_grad=22.0, max_schraeg=0.25, tol_flaeche=0.10):
    """Raumumriss auf die vorherrschenden Achsen begradigen.

    WARUM: die rekonstruierten Umrisse hatten die richtige FLAECHE, aber nicht
    die richtige FORM — am Referenzplan Flur 39 Ecken bei einer
    Rechteckigkeit von 0,44, Zimmer 2 26 Ecken bei 0,55, Parkplatz 43 Ecken.
    Der Umriss zappelt dann in winzigen Stufen an der Wand entlang; im Plan
    sieht das aus wie ein Bogen. Gemessen: 21 der 39 Flur-Kanten liegen
    bereits innerhalb von 1 Grad an einer Achse — es fehlt nur das
    Zusammenfassen.

    WIE: die laengengewichtete Hauptrichtung gibt das Achsenkreuz (der Plan
    kann gedreht sein, darum nicht stur waagrecht/senkrecht). Jede Kante wird
    auf die naehere Achse gezogen; direkt aufeinanderfolgende Kanten
    DERSELBEN Achse werden zu einer verschmolzen (laengengewichtetes Mittel).
    Die Ecken sind danach die Schnittpunkte der wechselnden Achsen.

    GRENZEN, damit echte Formen erhalten bleiben:
      - Ist mehr als `max_schraeg` der Umfangslaenge wirklich schraeg
        (Erker, Pultdach, Schraege), bleibt der Umriss unangetastet.
      - Aendert die Begradigung die Flaeche um mehr als `tol_flaeche`,
        war die Annahme falsch -> Original zurueck.
    """
    import math as _m
    if not poly or len(poly) < 4:
        return poly
    pts = [(float(x), float(y)) for (x, y) in poly]
    n = len(pts)

    def _flaeche(ps):
        a = 0.0
        for i in range(len(ps)):
            a += ps[i - 1][0] * ps[i][1] - ps[i][0] * ps[i - 1][1]
        return abs(a) / 2.0

    f0 = _flaeche(pts)
    if f0 <= 0:
        return poly

    sx = sy = 0.0
    for i in range(n):
        dx = pts[(i + 1) % n][0] - pts[i][0]
        dy = pts[(i + 1) % n][1] - pts[i][1]
        L = _m.hypot(dx, dy)
        if L < 1e-9:
            continue
        w = _m.atan2(dy, dx) * 4.0
        sx += L * _m.cos(w)
        sy += L * _m.sin(w)
    if sx == 0 and sy == 0:
        return poly
    th = _m.atan2(sy, sx) / 4.0
    ca, sa = _m.cos(th), _m.sin(th)
    rot = [(x * ca + y * sa, -x * sa + y * ca) for (x, y) in pts]

    tol = _m.radians(tol_grad)
    tol_lang = _m.radians(6.0)     # strenger Massstab fuer lange Kanten
    _xs = [q[0] for q in rot]
    _ys = [q[1] for q in rot]
    _bw = max(_xs) - min(_xs)
    _bh = max(_ys) - min(_ys)
    # Massstab fuer "lange Schraege" ist die KURZE Seite, nicht die Diagonale:
    # ein Flur ist lang und schmal, seine Diagonale ist gross, und dann gilt
    # jede Zickzack-Kante als gewollte Schraege — genau der Fall, der die
    # Begradigung dort blockierte.
    # Beide Massstaebe helfen verschiedenen Raumformen: die Diagonale fasst
    # gedrungene Raeume besser, die kurze Seite lange schmale. Eine Kante gilt
    # erst dann als GEWOLLTE Schraege, wenn sie nach beiden Massstaeben lang
    # ist — sonst blockiert der jeweils strengere die Begradigung.
    lang = max(0.18 * _m.hypot(_bw, _bh), 0.35 * max(1e-6, min(_bw, _bh)))
    kanten, l_schraeg, l_ges = [], 0.0, 0.0
    for i in range(n):
        x1, y1 = rot[i]
        x2, y2 = rot[(i + 1) % n]
        dx, dy = x2 - x1, y2 - y1
        L = _m.hypot(dx, dy)
        l_ges += L
        if L < 1e-9:
            continue
        w = abs(_m.atan2(dy, dx))
        if w > _m.pi / 2:
            w = _m.pi - w
        # KURZE Schraegen sind das Zickzack, das begradigt werden soll;
        # LANGE Schraegen sind echte Formen (Erker, Pultdach) und bleiben.
        # Ohne diese Unterscheidung steigt das Verfahren bei jedem Raum aus:
        # der Flur hat 21 Kanten innerhalb von 1 Grad an einer Achse UND
        # vier kurze bei 23-30 Grad — die vier duerfen nicht alles blockieren.
        # LANGE Kanten muessen SEHR nah an der Achse liegen, um als
        # achsparallel zu gelten. Sonst passiert Folgendes (im Waechter
        # aufgefallen): eine lange gewollte Schraege zieht die Hauptrichtung
        # zu sich, liegt danach scheinbar innerhalb der 22-Grad-Toleranz und
        # wird flachgebuegelt — das Verfahren wuerde ein Trapez zum Rechteck
        # machen und damit eine Form erfinden, die im Plan nicht steht.
        if L >= lang and not (w <= tol_lang or w >= _m.pi / 2 - tol_lang):
            kanten.append(["s", 0.0, L])       # echte, lange Schraege
            l_schraeg += L
        elif w <= _m.pi / 4:
            kanten.append(["h", (y1 + y2) / 2.0, L])
        else:
            kanten.append(["v", (x1 + x2) / 2.0, L])
    if not kanten or (l_ges > 0 and l_schraeg / l_ges > max_schraeg):
        return poly                            # ueberwiegend schraeg -> unberuehrt
    if any(k[0] == "s" for k in kanten):
        return poly                            # echte Schraege dabei: nicht anfassen

    # Aufeinanderfolgende Kanten DERSELBEN Achse verschmelzen (ringfoermig)
    m = []
    for k in kanten:
        if m and m[-1][0] == k[0]:
            L1, L2 = m[-1][2], k[2]
            m[-1][1] = (m[-1][1] * L1 + k[1] * L2) / (L1 + L2)
            m[-1][2] = L1 + L2
        else:
            m.append(list(k))
    while len(m) > 2 and m[0][0] == m[-1][0]:
        L1, L2 = m[-1][2], m[0][2]
        m[0][1] = (m[0][1] * L2 + m[-1][1] * L1) / (L1 + L2)
        m[0][2] = L1 + L2
        m.pop()
    if len(m) < 4 or len(m) % 2 != 0:
        return poly                            # kein sauberer Wechsel h/v

    ecken = []
    for i in range(len(m)):
        a, b = m[i - 1], m[i]
        if a[0] == b[0]:
            return poly
        nx = a[1] if a[0] == "v" else b[1]
        ny = a[1] if a[0] == "h" else b[1]
        ecken.append((nx, ny))
    zurueck = [(x * ca - y * sa, x * sa + y * ca) for (x, y) in ecken]

    f1 = _flaeche(zurueck)
    if f1 <= 0 or abs(f1 - f0) / f0 > tol_flaeche:
        return poly
    return zurueck


def _koten_verteilt(koten, page, min_spalten=4, min_spanne=0.25):
    """HÖHENKOTEN oder GELDBETRÄGE? Beide sehen als Text gleich aus (+2.98 /
    -12,50) — die Schnitt-Erkennung hielt darum Booking-/Bank-Belege für
    Schnitt-Blätter ('ok, typ=schnitt' statt ehrlichem ✗; am Korpus gemessen).
    Unterschied ist die LAGE, nicht der Text: Beträge stehen rechtsbündig in
    1-2 Spalten (gemessen: 2 Spalten / 8,8% Blattbreite), echte Koten hängen
    am Bauwerk und streuen (echter Schnitt 35 Spalten / 89%, Grundriss 17/68%).
    -> Koten nur zählen, wenn sie über die Blattbreite verteilt sind."""
    if not koten or not page:
        return False
    try:
        br = float(page.rect.width) or 1.0
        xs = sorted(float(x) for x, _, _ in koten)
        if (xs[-1] - xs[0]) / br < min_spanne:
            return False
        spalten = 1
        for a, b in zip(xs, xs[1:]):
            if b - a > 12.0:            # neue Spalte (12pt Toleranz)
                spalten += 1
        return spalten >= min_spalten
    except Exception:
        return False


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
        # ECHTER Scan = Raster-Bild auf der Seite. Eine LEERE/inhaltslose Seite
        # (kein Text, kein Bild, keine Vektoren) ist KEIN Scan → ehrlich ok=False,
        # sonst zeigt das Overlay eine weiße Fläche als „Grundriss".
        _hat_bild = False
        try:
            _hat_bild = bool(page.get_images(full=True))
        except Exception:
            _hat_bild = False
        if len(worte) < 10 and _hat_bild:
            # SCAN-MODUS ('für alle Pläne'): Bild-PDF ohne Text-Layer → das Bild
            # RENDERN statt ablehnen; die Vision-Raum-Polygone werden per Decorator
            # eingezeichnet (region_pt), der Nutzer setzt den Maßstab manuell
            # (2 Punkte einer bekannten Länge). Uncalibriert (ptm=0).
            try:
                import fitz as _fz
                _bw, _bh = page.rect.width, page.rect.height
                _sc = max(0.5, min(max_px / _bw, max_px / _bh, 4.0))
                pix = page.get_pixmap(matrix=_fz.Matrix(_sc, _sc))
                return {
                    "ok": True, "typ": "scan",
                    "basis_png": pix.tobytes("png"),
                    "bild_w": pix.width, "bild_h": pix.height,
                    "waende": [], "oeffnungen": [], "raeume": [],
                    "konturen": [], "fluchten": [], "summe_m": {},
                    "meta": {
                        "ptm": 0, "scale": round(_sc, 4),
                        "box_pt": [0.0, 0.0, round(_bw, 1), round(_bh, 1)],
                        "n_waende": 0, "box_m": None,
                        "tragfaehig": False, "streuung_pct": None,
                        "massstab": m_label or "?", "typ": "scan",
                    },
                }
            except Exception as _e:
                return {"ok": False, "grund": f"Scan-Render fehlgeschlagen: {_e}"}
        if len(worte) < 10:
            # <10 Worte UND kein Bild → leere/inhaltslose Seite (Deckblatt, Brief).
            return {"ok": False,
                    "grund": "Leere oder inhaltslose Seite — kein Grundriss erkennbar"}
        return {"ok": False, "grund": "Maßstab/Kalibrierung nicht lesbar"}
    box = _eg_box(page, ptm, worte=worte)
    # ZWEI BOXEN, ein Grund (2026-08-08): die ERWEITERTE Box (mit Aussenraum-
    # Woertern) zeigt das ganze Gebaeude und liest den Terrassen-Stempel —
    # aber die MESS-Paesse leiden unter ihr, beide einzeln belegt:
    #   Wandliste: 50er-Wand 41,5 -> 32,9 m (27 -> 32 Waende), weil Pergola-
    #     und Suedmassketten-Linien in die Staerken-Zuordnung geraten — exakt
    #     der beim Stempel-Box-Versuch dokumentierte Fehlerkanal.
    #   IoU-Beweis: 5 -> 3 Raeume, weil die Suedketten MEHR byte-exakte
    #     Fluchten liefern und das Eindeutigkeits-Gate bei mehreren
    #     Kandidaten den Beweis zurueckzieht (Zimmer 1 / Geraete "uneindeutig").
    # Darum behalten Wandliste und Fluchten die ENGE Innenraum-Box, auf der
    # ihre Zahlen gemessen und gepinnt sind; Rendern/Stempel/Raster nutzen
    # die volle. Faellt die Wort-Box spaeter auf Stempel-/Wandbox zurueck,
    # gilt fuer alles dieselbe (dann gibt es keine verlaessliche Innen-Box).
    mess_box = _eg_box(page, ptm, worte=worte, liste=INNEN_WORTE) or box
    # STUFE 2 (TG-/Großbau-Pläne, Sektor-Audit: die Wohn-RAUM_WORTE trafen am
    # Velden-TG nur den Stiegenhaus-Kern via Zufallstreffer 'Gang'/'Eingang' —
    # Box deckte 8% des Bauwerks): Box aus den F/U-STEMPEL-Positionen, wenn
    # KEINE Box da ist ODER >50% der Stempel außerhalb liegen. raum_stempel
    # liest seit dem Rotated-Support auch ArchiCAD-Blöcke (555,9m²-Halle).
    try:
        import raumnetz as _rn
        _st = _rn.raum_stempel(page, (0, page.rect.width, 0, page.rect.height))
        if len(_st) >= 3:
            pos = [(x["cx"], x["cy"]) for x in _st]
            # Marge skaliert mit dem größten Stempel: der 555,9m²-Hallen-
            # Stempel sitzt MITTIG, die Außenkante liegt ~√F/2 entfernt —
            # die 4m-Marge kappte die Halle auf 225m² (gemessen). EFH
            # (max F ≤ 40) bleibt bei 4m.
            _fmax = max((x.get("f_m2") or 0) for x in _st)
            _marge = max(4.0, 0.6 * (_fmax ** 0.5))
            _box_st = vektor._view_bbox(pos, ptm, marge_m=_marge,
                                        radius_m=40.0)

            def _drin(b):
                return 0 if not b else sum(
                    1 for x in _st
                    if b[0] <= x["cx"] <= b[1] and b[2] <= x["cy"] <= b[3])

            # WELCHE BOX ENTHÄLT MEHR STEMPEL? Vorher stand hier "nimm die
            # Stempel-Box, wenn WENIGER ALS 50% der Stempel in der Wort-Box
            # liegen". An einem gebauten Schulgrundriss lagen exakt 4 von 8
            # drin — die Schwelle verfehlte um einen Raum, und vier
            # Klassenzimmer fielen aus dem Plan.
            #
            # Die Ursache ist grundsätzlicher: RAUM_WORTE ist eine Liste aus
            # 16 WOHNBAU-Begriffen. "Klasse", "Produktionshalle",
            # "Patientenzimmer", "Gästezimmer" stehen nicht darin. Trifft die
            # Liste NICHTS, fällt die Auswertung sauber auf die Stempel
            # zurück; trifft sie ZUFÄLLIG EIN PAAR Wörter (Schule: die WCs und
            # den Gang), entsteht eine falsche Box — ein Teiltreffer ist
            # schlimmer als kein Treffer.
            #
            # Die Stempel sind byte-exakt und sprachunabhängig: wo ein
            # F/U-Stempel steht, ist ein Raum. Also entscheidet die Anzahl
            # gefasster Stempel, nicht eine Prozentschwelle.
            #
            # ABER die Box ist nicht nur für Räume da — an ihr hängt auch die
            # WANDMESSUNG, und die will das Gegenteil: eine engere Box. Beide
            # Varianten wurden gemessen:
            #
            #   "Stempel-Box, sobald sie mehr Räume fasst"  -> Schule 8/8 ✓,
            #      aber Angerer 50-cm-Wand 41 m -> 33 m (32 statt 27 Wände:
            #      die größere Box zieht Fremdsegmente herein und verschiebt
            #      die Stärken-Zuordnung)
            #   dasselbe als VEREINIGUNG beider Boxen -> identisch schlecht,
            #      die Vergrößerung selbst ist die Ursache, nicht der Zuschnitt
            #
            # Also bleibt der Auslöser eng: die Stempel-Box greift erst, wenn
            # die Wort-Box HÖCHSTENS die Hälfte der Stempel fasst — dann ist
            # sie erwiesen unbrauchbar. Vorher stand hier "weniger als die
            # Hälfte"; der gebaute Schulgrundriss traf mit exakt 4 von 8 die
            # Grenze und verlor vier Klassenzimmer. Ein Gleichstand ist kein
            # Vertrauensbeweis für die Wortliste.
            if _box_st and _drin(box) <= 0.5 * len(_st):
                box = _box_st
                mess_box = _box_st
    except Exception:
        pass
    # SCHNITT-GATE vor _wandbox (Audit): ein kompaktes Schnitt-/Ansichts-Blatt (12×10 m
    # Gebäude) hat KEINE Raumnamen und KEINE Stempel, seine dunklen Linien ergeben aber
    # eine 4-30-m-Box → _wandbox akzeptierte es fälschlich als Grundriss. Trägt das Blatt
    # ≥8 byte-exakte HÖHENKOTEN (die Schnitt-Signatur), _wandbox überspringen → es fällt
    # sauber in den Schnitt-Modus unten.
    _koten_alle = [(w[0], w[1], w[4]) for w in worte
                   if re.match(r"^[±+\-]\s?\d{1,2}[.,]\d{2}$", w[4].strip())]
    _koten_n = len(_koten_alle) if _koten_verteilt(_koten_alle, page) else 0
    if not box and _koten_n < 8:
        # FALLBACK für Grundriss-Pläne OHNE Raumnamen (z.B. reine Wand-Grundrisse):
        # die Bounding-Box der dunklen Wand-Linien nehmen — aber nur, wenn sie eine
        # PLAUSIBLE Gebäude-Größe hat (4-45 m/Seite). Schließt Schnitte/Lagepläne aus.
        box = _wandbox(page, ptm)
        mess_box = box
    if not box:
        # SCHNITT-BLATT-MODUS ('für alle Pläne': jedes Blatt liefert, was es
        # trägt): Schnitt-/Ansichts-Blätter haben keinen Grundriss, aber
        # byte-exakte HÖHENKOTEN (Velden 40, 05_AU 83 gemessen) — Ansicht mit
        # Koten-Markern statt reinem ✗.
        koten = _koten_alle
        if len(koten) >= 8 and _koten_verteilt(koten, page):
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
    # PHASENGLEICHE ERWEITERUNG (2026-08-08): ist die Render-Box groesser als
    # die Mess-Box, wird ihr Ursprung so gelegt, dass er um GANZE Rasterzellen
    # (2 cm) unter dem Mess-Ursprung liegt. Die Zellzuordnung im gesamten
    # Mess-Bereich ist damit byte-identisch zur Zeit vor der Box-Erweiterung —
    # gemessen an beiden Alternativen: ohne Ausrichtung kippten zwei
    # IoU-Beweise ("uneindeutig", Zweitkandidat 0,94), mit Seiten-Gitter-Snap
    # kippten stattdessen fuenf Tuer-Dichtungen (28->33 undicht). Beides waren
    # reine Rundungs-Neuwuerfe an Schwellen, keine echten Aenderungen.
    if mess_box != box:
        _cell = 0.02 * ptm
        _mb0, _mb1, _mb2, _mb3 = mess_box
        bx0 = _mb0 - math.ceil(max(0.0, _mb0 - bx0) / _cell) * _cell
        by0 = _mb2 - math.ceil(max(0.0, _mb2 - by0) / _cell) * _cell
        box = (bx0, bx1, by0, by1)
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
    # MESS-Sicht (enge Innenraum-Box, s.o.): Wandliste + Fluchten arbeiten
    # auf ihr, damit Pergola-/Massketten-Linien der Box-ERWEITERUNG die
    # gepinnten Messungen nicht verschieben.
    mb0, mb1, mb2, mb3 = mess_box
    inm = lambda s: mb0 <= (s[0] + s[2]) / 2 <= mb1 and mb2 <= (s[1] + s[3]) / 2 <= mb3
    arch_mess = (arch if mess_box == box else [s for s in arch if inm(s)])
    hatch_mess = (hatch if mess_box == box else
                  vektor.wand_poche(page, (mb0, mb1, mb2, mb3),
                                    pfade=pfade, ptm=ptm))
    # span_chain (Roadmap #8) bleibt AUS: Hypothese "Hatch-Band als Ketten-
    # Diskriminator" am 3-Plan-Korpus falsifiziert (Angerer 50er 41,4→24,8 m,
    # Holzbau-34er weg) — nächster Kandidat: Fill-Rect-Spannen statt Hatch-Dichte.
    roh = vektor.wand_paare(arch_mess, ptm, min_len_m=min_len_m, legende_dicken=LEG,
                            hatch=hatch_mess, min_hatch_dichte=min_hatch_dichte, mit_geometrie=True)
    # FÜLLFLÄCHEN-WÄNDE (Roadmap #8, H3 bestätigt): mehrschichtige Aufbauten
    # (Holzbau/WDVS) als Gesamtspanne aus gestapelten Schicht-Rects.
    # GATE (Präzedenzfall Fallback-Summe unten): nur für Pläne, deren Linien-
    # Wände NICHT auf die Mauerwerks-Legende snappen — Angerer/AP.01/TG (HLZ/
    # STB) bleiben byte-identisch, Holzbau & Co. bekommen die fehlende Hülle.
    # Dedup per INTERVALL-SUBTRAKTION: nur der von Linien-Wänden UNBEDECKTE
    # Rest einer Fill-Wand wird ergänzt (kein Doppel, kein Alles-oder-Nichts).
    try:
        _leg_snap_da = any(vektor._snap_legende(w["dicke_cm"], LEG, 2.0) for w in roh)
        _add = 0
        if not _leg_snap_da:
            _fillw = vektor.wand_fill_waende(pfade, (bx0, by0, bx1, by1), ptm,
                                             min_len_m=max(min_len_m, 0.5))
            # VERDRÄNGUNG: die Linien-Paarung liest mehrschichtige Hüllen als
            # dünne Ständer-Wände (gemessen: Σ9cm ≈ 37 m = die 38er-Hülle!).
            # Liegt eine deutlich dünnere Linienwand (≥10 cm Differenz) mit
            # ≥60% ihrer Länge quer INNERHALB einer Fill-Spanne, ist sie die
            # falsche Lesart derselben Wand → raus, die Gesamtspanne gewinnt.
            _verdraengt = set()
            for fw in _fillw:
                _fax = fw["achse"]
                _flo, _fhi = (fw["y0"], fw["y1"]) if _fax == "v" else (fw["x0"], fw["x1"])
                _fc = fw["x0"] if _fax == "v" else fw["y0"]
                for wi, w in enumerate(roh):
                    if wi in _verdraengt or w["achse"] != _fax:
                        continue
                    if w["dist_pt"] > fw["dist_pt"] - 0.10 * ptm:
                        continue
                    _wc = w["x0"] if _fax == "v" else w["y0"]
                    if abs(_wc - _fc) > fw["dist_pt"] / 2.0:
                        continue
                    a, b = (w["y0"], w["y1"]) if _fax == "v" else (w["x0"], w["x1"])
                    _ov = min(b, _fhi) - max(a, _flo)
                    if b > a and _ov / (b - a) >= 0.60:
                        _verdraengt.add(wi)
            if _verdraengt:
                roh = [w for wi, w in enumerate(roh) if wi not in _verdraengt]
                print(f"[nachzeichnen] {len(_verdraengt)} Schicht-Fehllesungen durch "
                      f"Fill-Gesamtspannen verdrängt")
            for fw in _fillw:
                _ax = fw["achse"]
                _lo, _hi = (fw["y0"], fw["y1"]) if _ax == "v" else (fw["x0"], fw["x1"])
                # von Linien-Wänden bedeckte Längs-Intervalle einsammeln
                _cov = []
                for w in roh:
                    if w["achse"] != _ax or w.get("quelle") == "fill":
                        continue
                    _quer = abs((w["x0"] if _ax == "v" else w["y0"])
                                - (fw["x0"] if _ax == "v" else fw["y0"]))
                    if _quer > (w["dist_pt"] + fw["dist_pt"]) / 2.0:
                        continue
                    a, b = (w["y0"], w["y1"]) if _ax == "v" else (w["x0"], w["x1"])
                    a, b = max(a, _lo), min(b, _hi)
                    if b > a:
                        _cov.append((a, b))
                _cov.sort()
                # unbedeckte Reststücke ≥ 0,8 m als Wände übernehmen
                _pos = _lo
                _rest = []
                for a, b in _cov:
                    if a - _pos >= 0.8 * ptm:
                        _rest.append((_pos, a))
                    _pos = max(_pos, b)
                if _hi - _pos >= 0.8 * ptm:
                    _rest.append((_pos, _hi))
                for a, b in _rest:
                    st = dict(fw)
                    if _ax == "v":
                        st["y0"], st["y1"] = a, b
                    else:
                        st["x0"], st["x1"] = a, b
                    st["laenge_m"] = round((b - a) / ptm, 2)
                    roh.append(st)
                    _add += 1
        if _add:
            print(f"[nachzeichnen] {_add} Füllflächen-Wandstücke additiv ergänzt (Schicht-Aufbauten)")
    except Exception as _fe:  # pragma: no cover
        print(f"[nachzeichnen] Füllflächen-Wände übersprungen: {_fe!r}")

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
                best = (d, vm, mx, my)
        # (Wert, x, y) — die KOORDINATEN der verwendeten Maßzahl machen die
        # Lesung am Plan nachweisbar (Ring im Overlay: "diese Zahl wurde gelesen").
        return (best[1], best[2], best[3]) if best else None

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
        mass_px = None
        if exakt is not None:
            laenge_m = round(exakt[0], 2)
            _mp = to_px(exakt[1], exakt[2])
            mass_px = [_mp[0], _mp[1]]
        if laenge_m < min_len_m:
            continue
        # Fill-Gesamtspannen (Holzbau/WDVS) NICHT auf die Mauerwerks-Legende
        # snappen — sonst füllt ein 10er-Fill (→12) die summe und deaktiviert
        # die Fallback-Buckets, die 34/38er-Aufbauten gehören dorthin.
        sn = None if w.get("quelle") == "fill" \
            else vektor._snap_legende(w["dicke_cm"], LEG, 2.0)
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
            "mass_px": mass_px,                  # Ort der verwendeten Maßzahl (Beweis-Ring)
            "staerke_px": round((sn or w["dicke_cm"]) / 100.0 * ptm * scale, 1),
            "hatch_dichte": w.get("hatch_dichte"),
        })
        idx += 1
        if sn:
            summe[sn] = round(summe.get(sn, 0) + laenge_m, 2)

    # GEWERK JE WAND — die Trennung gehört in die GEOMETRIE, nicht in eine
    # Nachrechnung auf Summen.
    #
    # Der Plan sagt selbst, aus welchem Material eine Wand ist: er beschriftet
    # sie mit einem Code (AW01, IW03, „C/D/E - IW10a") und definiert diesen
    # Code in der Legende bzw. der Aufbautentabelle. Daraus fällt das GEWERK:
    # Mauerwerk (LG 08), Beton (LG 07), Trockenbau (LG 39), Holz (LG 36).
    #
    # Warum nicht über die Dicke: sie ist am Korpus nachweislich kein
    # Material-Signal. Angerer 12 cm = Hochlochziegel; WM IW01a ist 36 cm
    # dick und trotzdem BETON (200 mm Stahlbeton mit GK-Beplankung davor),
    # IW10a mit 10 cm ist Trockenbau. Eine Dicken-Regel hätte beide falsch
    # einsortiert.
    #
    # Read-only: das Feld beschreibt nur, was der Plan sagt. Eine Mengen-
    # Trennung darauf aufzusetzen ist der nächste Schritt — dann aber
    # konstruktiv doppelzählungsfrei, weil jede Wand genau EIN Gewerk trägt.
    try:
        import legende as _leg_m
        # SPANS, nicht Wörter. „C/D/E - IW01a Wohnungstrennwand," ist EIN Span;
        # als Wortliste zerfällt es in vier Teile, und dann findet weder der
        # Anker-Test (Code MIT Zusatztext) noch die Aufbautentabelle etwas —
        # gemessen: 0 Codes mit Materialklasse trotz 46 Code-Markern.
        _sp_leg = []
        for _b in page.get_text("dict").get("blocks", []):
            if _b.get("type") != 0:
                continue
            for _l in _b.get("lines", []):
                for _s in _l.get("spans", []):
                    _t = (_s.get("text") or "").strip()
                    if not _t:
                        continue
                    _bb = _s.get("bbox") or (0, 0, 0, 0)
                    _sp_leg.append({"text": _t, "bbox": _bb,
                                    "size": _s.get("size", 0),
                                    "cx": (_bb[0] + _bb[2]) / 2.0,
                                    "cy": (_bb[1] + _bb[3]) / 2.0})
        _klasse_von = {}
        for _c, _d in (_leg_m.parse_legende(_sp_leg).get("wand_typen") or {}).items():
            if _d.get("materialklasse"):
                _klasse_von[_c] = _d["materialklasse"]
        # Die Aufbautentabelle ist die stärkere Quelle (voller Schichtaufbau)
        # und darf die Kurz-Legende überschreiben.
        for _c, _d in (_leg_m.aufbau_tabelle(_sp_leg) or {}).items():
            if _d.get("materialklasse"):
                _klasse_von[_c] = _d["materialklasse"]
        # Code-MARKER am Grundriss (nicht die Legende) mit Position.
        _marker = []
        for _s in _sp_leg:
            _m = _leg_m.WAND_CODE_RX.search(_s["text"])
            if not _m:
                continue
            _code = f"{_m.group(1).upper()}{_m.group(2)}"
            if _code in _klasse_von:
                _marker.append((_s["cx"], _s["cy"], _klasse_von[_code], _code))
        if _marker:
            _rad = 1.6 * ptm      # ein Marker beschriftet die Wand daneben
            _n_gw = 0
            for _wd in waende:
                _pxs = _wd.get("px") or []
                if len(_pxs) < 4:
                    continue
                # Wand-Mitte zurück in PDF-Punkte (px sind skaliert)
                _mx = ((_pxs[0] + _pxs[2]) / 2.0) / scale + bx0
                _my = ((_pxs[1] + _pxs[3]) / 2.0) / scale + by0
                _best = None
                for _cx, _cy, _kl, _code in _marker:
                    _dd = ((_cx - _mx) ** 2 + (_cy - _my) ** 2) ** 0.5
                    if _dd <= _rad and (_best is None or _dd < _best[0]):
                        _best = (_dd, _kl, _code)
                if _best:
                    _wd["gewerk"] = _best[1]
                    _wd["gewerk_code"] = _best[2]
                    _n_gw += 1
            if _n_gw:
                print(f"[gewerk] {_n_gw} von {len(waende)} Wänden einem Gewerk "
                      f"zugeordnet ({len(_klasse_von)} Codes mit Materialklasse)")
    except Exception as _ge:      # pragma: no cover
        print(f"[gewerk] Zuordnung fehlgeschlagen: {_ge!r}")

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
            if o.get("typ") == "glasfront":
                # Siegel-Anker fuer raumnetz (oeff_pt), KEIN Bauteil: nicht
                # ans Frontend exportieren — dort wuerde er als Phantom-Tuer
                # gezaehlt und gezeichnet.
                continue
            oeffnungen.append({
                "id": len(oeffnungen), "typ": o.get("typ"),
                "breite_m": o.get("breite_m"), "hoehe_m": o.get("hoehe_m"),
                "px": to_px(cx, cy),
            })
        # MASSPAAR-ANKER (Sadiku-Klasse, 2026-08-14, hinter Schalter):
        # Plaene ohne FPH/STUK-Beschriftung stellen ans Fenster nur ein
        # GESTAPELTES Zahlenpaar (Breite ueber Hoehe/Parapet, z. B. 140
        # ueber 120; Legende: "RBL / fertige Parapethoehe"). Ein Zahlen-
        # paar, dessen Mitte AUF einer erkannten Wand liegt, ist ein
        # Fenster-Anker — Masskettenzahlen liegen auf Massketten-Linien,
        # nicht auf Waenden, und fallen durch den Abstands-Filter.
        # Nur Siegel-Anker (oeff_pt), kein Bauteil, kein Export.
        if os.environ.get("MASSPAAR_ANKER", "1") != "0" and waende:
            import re as _re

            def _cm(t):
                t = t.strip()
                m = _re.match(r"^([0-9]{2,3})$", t)
                if m:
                    v = int(m.group(1))
                    return v if 30 <= v <= 400 else None
                m = _re.match(r"^([0-9])[,.]([0-9]{1,2})$", t)
                if m:
                    v = float(m.group(1)) + float(m.group(2)) / (10 if len(m.group(2)) == 1 else 100)
                    v *= 100
                    return v if 30 <= v <= 400 else None
                return None

            _zs = []
            for sp in spans:
                v = _cm(sp.get("text") or "")
                if v is not None:
                    _zs.append((sp["cx"], sp["cy"], v))

            def _wanddist(x, y):
                best = 1e9
                for w0 in waende:
                    (px0, py0, px1, py1) = w0["px"]
                    ax, ay = px0 / scale + bx0, py0 / scale + by0
                    bx_, by_ = px1 / scale + bx0, py1 / scale + by0
                    dx, dy = bx_ - ax, by_ - ay
                    L2 = dx * dx + dy * dy
                    if L2 < 1:
                        continue
                    t0 = max(0.0, min(1.0, ((x - ax) * dx + (y - ay) * dy) / L2))
                    qx, qy = ax + t0 * dx, ay + t0 * dy
                    d = ((qx - x) ** 2 + (qy - y) ** 2) ** 0.5
                    if d < best:
                        best = d
                return best

            _n_mp = 0
            for i0 in range(len(_zs)):
                for j0 in range(i0 + 1, len(_zs)):
                    a, b = _zs[i0], _zs[j0]
                    # gestapelt (waagrechtes Label) ODER nebeneinander
                    # (gedrehtes Label an vertikaler Wand)
                    _stapel = abs(a[0] - b[0]) <= 12 and 2 < abs(a[1] - b[1]) < 14
                    _seitl = abs(a[1] - b[1]) <= 12 and 2 < abs(a[0] - b[0]) < 14
                    if not (_stapel or _seitl):
                        continue
                    mx, my = (a[0] + b[0]) / 2, (a[1] + b[1]) / 2
                    if not (bx0 <= mx <= bx1 and by0 <= my <= by1):
                        continue
                    if _wanddist(mx, my) > 0.22 * ptm:
                        continue
                    if _stapel:
                        ober = a if a[1] < b[1] else b   # obere Zahl = Breite
                    else:
                        ober = a if a[0] < b[0] else b   # links(gedreht oben)=Breite
                    oeff_pt.append({"typ": "fenster", "cx": mx, "cy": my,
                                    "breite_m": round(ober[2] / 100.0, 2),
                                    "hoehe_m": None, "quelle": "masspaar"})
                    _n_mp += 1
            if _n_mp and os.environ.get("GUARD_DEBUG"):
                print(f"[masspaar] {_n_mp} Fenster-Anker aus Zahlenpaaren")
    except Exception as e:  # pragma: no cover
        oeff_pt = []
        print(f"[nachzeichnen] Öffnungen fehlgeschlagen: {e}")

    # UNVOLLSTÄNDIGE ÖFFNUNGEN SICHTBAR MACHEN (Begründung und Schwellen-Logik
    # stehen bei oeffnungen.hinweis_unvollstaendig — eine Quelle für App und
    # Wächter). Kurz: fehlt ein Maß, ist die Abzugsfläche rechnerisch 0 und die
    # Mengenliste sieht trotzdem vollständig aus.
    oeffnungen_hinweis = ""
    try:
        import oeffnungen as _oeff_h
        oeffnungen_hinweis = _oeff_h.hinweis_unvollstaendig(oeffnungen)
    except Exception as e:  # pragma: no cover
        print(f"[nachzeichnen] Öffnungs-Hinweis fehlgeschlagen: {e}")

    # SCHNITT-LESUNG (Begründung in api/schnitt.py): Blätter mit Schnitt oder
    # Ansicht lieferten bisher NICHTS. Maßstab und Höhen-Niveaus kommen
    # byte-exakt aus den Höhenkoten; der abgeleitete Maßstab prüft sich
    # selbst. Best-effort, bricht nie — ein Grundriss liefert hier "".
    schnitt_hinweis = ""
    try:
        import schnitt as _schn
        schnitt_hinweis = _schn.hinweis(_schn.lies_schnitt(page))
    except Exception as e:  # pragma: no cover
        print(f"[nachzeichnen] Schnitt-Lesung fehlgeschlagen: {e}")

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
        # Freiflächen-Erkennung liegt in massen_logic (dort wohnt die
        # Raum-Kategorie). Import lokal, damit nachzeichnen ohne die
        # Mengen-Engine lauffähig bleibt.
        try:
            from massen_logic import ist_aussenanlage as _ist_aussen
        except Exception:      # pragma: no cover
            def _ist_aussen(_n, _f, _u):
                return False

        region_gates = {}   # je Raum: warum wurde der Umriss (nicht) gezeichnet
        try:
            # Läuft jetzt AUCH auf Großplänen (Nachvollziehbarkeit: WM/TG-Räume hatten
            # gar keine gezeichnete Kontur — die größten Pläne mit den meisten Räumen
            # waren blank). raum_regionen selbst filtert unzuverlässige/zackige Umrisse
            # (Flächen-Treue ±20%, ≤40 Ecken, ≥75% achsparallel) → nur saubere Räume
            # bekommen einen Umriss, komplexe bleiben ehrlich ohne. Sicherheits-Deckel
            # gegen Extrem-Pläne: >150 Räume überspringen (reine Latenz-Vorsicht).
            if dbg_r.get("label") is not None and os.environ.get("GRID_DUMP"):
                try:
                    import numpy as _np
                    _rst = dbg_r["rst"]
                    _np.savez(os.environ["GRID_DUMP"],
                              grid=_np.frombuffer(bytes(dbg_r["grid"]), dtype=_np.uint8),
                              label=_np.array(dbg_r["label"], dtype=_np.int32),
                              W=_rst.W, H=_rst.H, cell=_rst.cell,
                              namen=_np.array([(st.get("name") or "") for st in _st],
                                              dtype=object))
                    print(f"[griddump] {os.environ['GRID_DUMP']} W={_rst.W} H={_rst.H}")
                except Exception as _ge:
                    print(f"[griddump] fehlgeschlagen: {_ge}")
            if dbg_r.get("label") is not None and len(rres) <= 150:
                # byte-exakte Stempel-Flächen als WAHRHEIT ans Gate geben:
                # gezeichnet wird nur ein Umriss, der die richtige Fläche
                # umschließt (Form darf gedreht/verwinkelt sein).
                _sf = [(_r.get("f_m2") if isinstance(_r, dict) else None)
                       for _r in rres]
                regionen = raumnetz.raum_regionen(dbg_r["label"], dbg_r["rst"],
                                                  len(rres), debug=region_gates,
                                                  stempel_f=_sf,
                                                  ist_f=[(_r.get("f_ist")
                                                          if isinstance(_r, dict)
                                                          else None)
                                                         for _r in rres],
                                                  grid=dbg_r.get("grid"),
                                                  dark_segs=dark,
                                                  hatch_segs=hatch,
                                                  kredit_cells=dbg_r.get("kredit_cells"),
                                                  stuetzen=dbg_r.get("stuetzen"))
        except Exception as _er:
            regionen = {}
        for i, r in enumerate(rres):
            reg = regionen.get(i)
            # DETERMINISTISCHER Umfang aus dem Polygon (F-kalibriert) — der Hebel
            # für Räume ohne U-Stempel. Nur wenn ein sauberes Polygon da ist.
            # poly_exakt: wurde die Kontur vektor-exakt auf Wandlinien gesnappt
            # (raum_kontur_exakt, Snap-Quote ≥70 %)? Nur dann darf der
            # Umfangs-Schätzer dem Polygon allein glauben.
            _kx_ok = bool((region_gates.get(i) or {}).get("kontur_exakt"))
            u_geo = (geometrie_umfang(reg, r.get("f_m2"), ptm,
                                      poly_exakt=_kx_ok) if reg else None)
            # ZWEITER FORM-BEWEIS, unabhängig vom U-Stempel: liegt der Umriss
            # auf den gezeichneten Wänden? Auf Polierplänen ohne Umfangs-
            # angabe ist das der EINZIGE Weg, die Form ehrlich zu bestätigen.
            _uw = None
            if reg and dbg_r.get("grid") is not None:
                try:
                    _uw = raumnetz.umriss_auf_wand(reg, dbg_r["grid"],
                                                   dbg_r["rst"])
                except Exception:
                    _uw = None
            _g = region_gates.get(i) or {}
            # UMFASSUNGS-ZERLEGUNG: wo hört der Raum auf und WOMIT (Außen-/
            # Innenwand mit Nachbar, Tür, offen) — auf derselben exakten
            # Kontur, die gezeichnet wird. Farb-Layer in der Planansicht.
            _um = None
            if reg and dbg_r.get("grid") is not None \
                    and dbg_r.get("label") is not None:
                try:
                    _um = raumnetz.raum_umfassung(
                        reg, dbg_r["grid"], dbg_r["label"], dbg_r["rst"], i,
                        dbg_r["AUSSEN"], _st, oeffnungen=oeff_pt,
                        boegen=dbg_r.get("boegen"), dark_segs=dark,
                        draussen=dbg_r.get("draussen"))
                except Exception:
                    _um = None
            _um_seg = None
            if _um:
                _um_seg = [{**s, "p0": list(to_px(*s["p0"])),
                            "p1": list(to_px(*s["p1"]))}
                           for s in _um["segmente"]]
            raeume.append({
                # EHRLICHKEIT statt Blackbox: hat der Raum KEINEN Umriss, steht
                # hier warum (flaechen_treue / ecken / achs_parallel). Das
                # Frontend kann daraus einen verständlichen Hinweis machen und
                # gezielt die Ersatz-Markierung anbieten.
                "umriss_grund": (None if reg else (_g.get("grund") or "keine_region")),
                # Stufen-Diagnose (nur unter RG_DEBUG): Zellflaeche der Region
                # vs. DP-Polygonflaeche — lokalisiert, WO Flaeche entsteht.
                **({"_rg_dbg": {k: _g.get(k) for k in
                               ("region_m2", "poly_m2", "fr", "stempel_abw",
                                "ecken", "kredit_m2", "poly_pt")}}
                   if os.environ.get("RG_DEBUG") else {}),
                "umriss_fr": _g.get("fr"),
                "umriss_axis": _g.get("axis_frac"),
                # abgelehnter Umriss (nur Diagnose, NICHT gezeichnet)
                "_umriss_verworfen": ([to_px(x, y) for (x, y) in _g["poly_pt"]]
                                      if (not reg and _g.get("poly_pt")) else None),
                # FREIFLÄCHE statt Raum (Wiese/Spielplatz/Pflaster): wird in
                # der Liste und am Plan getrennt gezeigt, damit die Raumliste
                # nur Räume enthält. Mengen sind davon unberührt — die Innen-
                # Gewerke filtern ohnehin auf die Raum-Kategorie.
                "aussenanlage": _ist_aussen(r.get("name"), r.get("f_m2"),
                                            r.get("u_m")),
                "name": r.get("name"), "f_m2": r.get("f_m2"), "u_m": r.get("u_m"),
                "f_ist": r.get("f_ist"), "u_ist": r.get("u_ist"),
                "status": r.get("status"),
                "ebene": r.get("ebene"),   # 'roh'|'fertig' — welche Ebene bewies
                "px": to_px(r["cx"], r["cy"]),
                "region_px": ([to_px(x, y) for (x, y) in
                               rechtwinklig_ziehen(reg)] if reg else None),
                # Anteil des Umrisses, der auf einer Wand liegt (0..1).
                "umriss_wand": (round(_uw, 3) if _uw is not None else None),
                "umfassung": ({"segmente": _um_seg,
                               "klassen_m": _um["klassen_m"],
                               "anteil": _um["anteil_klassifiziert"]}
                              if _um_seg else None),
                "u_geometrie": (u_geo or {}).get("u_m"),
                "u_geometrie_poly": (u_geo or {}).get("u_poly_m"),
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
        # Fluchten auf der MESS-Box (s.o.): die Sued-Massketten der
        # Box-ERWEITERUNG lieferten zusaetzliche Kandidaten und liessen das
        # Eindeutigkeits-Gate zwei bewiesene Raeume zurueckziehen (IoU 5->3).
        dark_f = [s for s in segs if (s[5] is None or s[5] < 0.45)
                  and vektor._laenge(s) / ptm > 0.10 and inm(s)]
        rst_f = raumnetz._Raster((mb0, mb1, mb2, mb3), ptm, zelle_f)
        fills_f = vektor.wand_fill_rects(page, (mb0, mb1, mb2, mb3),
                                         min_seite_m=0.3, ptm=ptm, pfade=pfade)
        grid_f = raumnetz.wand_maske(rst_f, dark_f, hatch_mess, [],
                                     fill_rects=fills_f)
        fluchten_pt = massketten.wand_fluchten(worte,
                                               (mb0, mb1, mb2, mb3), ptm,
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
        # ERSATZ-MARKIERUNG für Räume ohne beweisbaren Umriss.
        # REIHENFOLGE (beste Quelle zuerst):
        #  1. FLUCHT-RECHTECK aus dem IoU-Beweis — stammt aus echten Wand-
        #     fluchten, enthält den Raumstempel und trifft die gestempelte
        #     Fläche. Das ist eine ECHTE Kontur, kein Ersatz.
        #  2. Rechteck aus Fläche+Umfang, an der Stempelstelle. Nur als letzte
        #     Rückfallebene — der Stempel-Textblock ist NICHT die Raummitte,
        #     das Rechteck sitzt darum oft sichtbar versetzt (am Live-Plan
        #     gesehen: Zimmer 1/Bad ragten über die Wände hinaus).
        _erg_flucht = _erg_fu = 0

        def _ersatz_setzen(_rm):
            """Einen Ersatz-Umriss setzen -> 'flucht' | 'fu' | None.

            Als Schleifenrumpf geschrieben, damit ein ZWEITER Durchgang
            möglich ist: im ersten Durchgang kennt ein früh gesetztes
            Rechteck die später gesetzten Nachbarn noch nicht und legt sich
            über sie (am WM-Plan: Lift E überdeckte den Vorraum zu 95%, beide
            waren Ersatz). Erst der zweite Durchgang sieht das ganze Bild.
            """
            _rc = _rm.get("iou_rect_pt")
            if _rc and len(_rc) == 4:
                _l, _r2, _o, _u2 = _rc
                _p1 = to_px(_l, _o); _p2 = to_px(_r2, _u2)
                _rm["region_px"] = [[_p1[0], _p1[1]], [_p2[0], _p1[1]],
                                    [_p2[0], _p2[1]], [_p1[0], _p2[1]]]
                _rm["region_geschaetzt"] = True
                _rm["region_quelle"] = "aus Wandfluchten · IoU-Beweis"
                return "flucht"
            _f = _rm.get("f_m2")
            if not _f or _f <= 0 or not ptm:
                return None
            # 1b) EIGENSTÄNDIGE Flucht-Suche (ohne Beweis-Anspruch): das
            # engste Wandflucht-Rechteck, das den Stempel enthält und die
            # gestempelte Fläche trifft. Fängt genau die Räume, die an der
            # strengen IoU-Schwelle scheitern (Zimmer 1 am Live-Plan).
            if _rm.get("cx") is not None and _rm.get("cy") is not None:
                try:
                    _fremd = [(o["cx"], o["cy"]) for o in raeume
                              if o is not _rm and o.get("cx") is not None
                              and o.get("cy") is not None]
                    # SCHON GEZEICHNETE UMRISSE als Hüllrechteck in Seiten-pt
                    # (region_px ist Bild-Pixel: px/scale + Rand = pt) plus
                    # ihre wahre Polygonfläche. Ohne das setzt jedes Ersatz-
                    # Rechteck blind über die Nachbarn.
                    _ff = []
                    for o in raeume:
                        _op = o.get("region_px") if o is not _rm else None
                        if not _op:
                            continue
                        _ox = [p[0] / scale + bx0 for p in _op]
                        _oy = [p[1] / scale + by0 for p in _op]
                        _fa = 0.0
                        for _k in range(len(_ox)):
                            _fa += (_ox[_k - 1] * _oy[_k]
                                    - _ox[_k] * _oy[_k - 1])
                        _ff.append((min(_ox), max(_ox), min(_oy), max(_oy),
                                    abs(_fa) / 2.0))
                    _fr = raumnetz.raum_rechteck_aus_fluchten(
                        _rm["cx"], _rm["cy"], _f, _ddp(fv2), _ddp(fh2), ptm,
                        fremde_stempel=_fremd, fremde_flaechen=_ff)
                except Exception:
                    _fr = None
                if _fr:
                    _l, _r2, _o, _u2 = _fr
                    _p1 = to_px(_l, _o); _p2 = to_px(_r2, _u2)
                    _rm["region_px"] = [[_p1[0], _p1[1]], [_p2[0], _p1[1]],
                                        [_p2[0], _p2[1]], [_p1[0], _p2[1]]]
                    _rm["region_geschaetzt"] = True
                    _rm["region_quelle"] = ("aus Wandfluchten · engste Fassung "
                                            "(nur eigener Stempel)")
                    return "flucht"
            _u = _rm.get("u_m")
            _a = _b = None
            if _u and _u > 0:
                _p = _u / 2.0
                _disc = _p * _p / 4.0 - _f
                if _disc >= 0:
                    _w = _disc ** 0.5
                    _a, _b = _p / 2.0 + _w, _p / 2.0 - _w
            if not (_a and _b and _a > 0 and _b > 0):
                _a = _b = _f ** 0.5
            _hw = _a * ptm * scale / 2.0
            _hh = _b * ptm * scale / 2.0
            _cx, _cy = _rm["px"][0], _rm["px"][1]
            _rm["region_px"] = [[_cx - _hw, _cy - _hh], [_cx + _hw, _cy - _hh],
                                [_cx + _hw, _cy + _hh], [_cx - _hw, _cy + _hh]]
            _rm["region_geschaetzt"] = True
            _rm["region_quelle"] = "aus Fläche+Umfang geschätzt (Lage ungenau)"
            return "fu"

        for _rm in raeume:
            if (_rm.get("region_px") or []) or not _rm.get("px"):
                continue
            _k = _ersatz_setzen(_rm)
            _erg_flucht += 1 if _k == "flucht" else 0
            _erg_fu += 1 if _k == "fu" else 0
        # ZWEITER DURCHGANG: jedes Ersatz-Rechteck noch einmal setzen, jetzt
        # mit ALLEN Nachbarn im Blick. Nur Ersatz-Umrisse werden angefasst —
        # ein echter Umriss aus dem Bild ist Beweis und wird nie überschrieben.
        # Bleibt der Raum ohne Rechteck, gilt wieder das alte (lieber grob
        # markiert als unsichtbar).
        for _rm in raeume:
            if not _rm.get("region_geschaetzt"):
                continue
            _alt = _rm.get("region_px")
            _rm["region_px"] = None
            if not _ersatz_setzen(_rm):
                _rm["region_px"] = _alt
        # ── SCHLUSSPRÜFUNG: nichts Falsches einzeichnen ──────────────────
        # Jeder Umriss — echt, begradigt oder Ersatz — muss am Ende die
        # gestempelte Fläche umschließen (±20%) UND seinen eigenen Stempel
        # enthalten. Die Einzelschritte prüfen jeder für sich (Watershed ±20%,
        # Ersatz-Rechteck ±18%, Begradigen ±10%), aber die Fehler ADDIEREN
        # sich, und die Ersatz-Rückfallebene darf notfalls verdrängen.
        # Am Korpus schlugen so drei Umrisse durch, die nicht zu ihrem Stempel
        # passen. Ein falscher Umriss ist schlechter als gar keiner: er
        # behauptet etwas. Wer hier durchfällt, verliert die Markierung und
        # bekommt einen Grund, den das Frontend anzeigen kann.
        def _pt_in_poly(pt, poly):
            x, y = pt[0], pt[1]
            d = False
            for _k in range(len(poly)):
                x1, y1 = poly[_k - 1][0], poly[_k - 1][1]
                x2, y2 = poly[_k][0], poly[_k][1]
                if (y1 > y) != (y2 > y) and y2 != y1:
                    if x < x1 + (y - y1) * (x2 - x1) / (y2 - y1):
                        d = not d
            return d

        _ppm = (ptm or 0.0) * (scale or 0.0)     # Bild-Pixel je Meter
        _verworfen = 0
        for _rm in raeume:
            _p = _rm.get("region_px")
            _f = _rm.get("f_m2")
            if not _p or len(_p) < 3 or not _f or _ppm <= 0:
                continue
            _a = 0.0
            for _k in range(len(_p)):
                _a += (_p[_k - 1][0] * _p[_k][1] - _p[_k][0] * _p[_k - 1][1])
            _fm = abs(_a) / 2.0 / (_ppm * _ppm)
            _lage = (_pt_in_poly(_rm["px"], _p) if _rm.get("px") else True)
            if abs(_fm / _f - 1.0) > 0.20 or not _lage:
                _rm["region_px"] = None
                _rm["region_geschaetzt"] = False
                _rm["region_quelle"] = None
                _rm["umriss_grund"] = ("flaeche_unplausibel" if _lage
                                       else "stempel_ausserhalb")
                _verworfen += 1
        if _verworfen:
            print(f"[nachzeichnen] Schlussprüfung: {_verworfen} Umrisse "
                  f"verworfen (Fläche oder Lage passt nicht zum Stempel)")

        if _erg_flucht or _erg_fu:
            print(f"[nachzeichnen] Ersatz-Umrisse: {_erg_flucht} aus Wandfluchten, "
                  f"{_erg_fu} aus Fläche+Umfang (Lage ungenau)")

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
            # TROCKENBAU-SIGNAL, byte-exakt aus dem Text-Layer (erste Stufe
            # eines LG-39-Gewerks — Hinweis OHNE Mengen-Eingriff, wie bei
            # Bestand/Abbruch): der WM-Plan schreibt wörtlich "Alle
            # Trockenbauwände und Vorsatzschalen …" — heute rechnen solche
            # nichttragenden Wände stumm als Mauerwerk. Ein volles LG-39-
            # Aufmaß braucht die Material-Trennung je Wand (sonst
            # Doppelzählung mit LG 08); bis dahin sagt die App ehrlich, DASS
            # der Plan Trockenbau kennzeichnet.
            # PRÄZISIONS-GATE (2026-08-02 gemessen): das Muster "gipskarton"
            # traf auch "Gipskartonplatte" — und das ist ein MATERIAL-Eintrag
            # in der Schichtaufbau-Legende, keine Wand-Deklaration. Auf zwei
            # der drei auslösenden Pläne (AP.01, Angerer) war der einzige
            # Treffer wörtlich "Gips (Gipskartonplatte)". Der Hinweis riet
            # dort, 74 bzw. 63 m Wandlänge ins falsche Gewerk zu buchen —
            # LG 39 statt LG 08 sind andere Preise. Der WM-Plan dagegen sagt
            # es wörtlich: "Alle Trockenbauwände und Vorsatz-",
            # "Gipskartonwand", "IW10a Vorsatzschale".
            # Es zählt also nur, was eine WAND benennt, nicht was eine PLATTE
            # benennt. Gleiche Logik wie das Boilerplate-Gate der Farb-Legende.
            # HOLZSTÄNDERWAND IST ZIMMERER (LG 36), NICHT TROCKENBAU (LG 39).
            # `"ständerwand" in wort` trifft als Teilzeichenkette auch
            # „Holzständerwand" — ein Holzriegelbau würde damit als Trockenbau
            # gemeldet und der Kalkulant ins falsche Gewerk geschickt. Auf dem
            # eigenen Korpus nicht auslösbar (die Holzbau-PDFs sind Verträge,
            # keine Pläne), die Verwechslung ist aber real und die Absicherung
            # kostet nichts.
            "trockenbau_hinweis": any(
                _tb_wort(w[4]) for w in (worte or [])),
            # Öffnungen ohne vollständiges Maß → stiller Nulldurchgang beim
            # ÖNORM-Abzug. Siehe Begründung bei der Berechnung oben.
            "oeffnungen_hinweis": oeffnungen_hinweis,
            # SCHNITT-LESUNG: Blätter mit Schnitt/Ansicht lieferten bisher
            # gar nichts (4 von 12 Korpus-Plänen). Maßstab und Höhen-Niveaus
            # kommen byte-exakt aus den Höhenkoten; der abgeleitete Maßstab
            # ist die Selbstprüfung. Reine Anzeige — die Mengen bleiben
            # unberührt, solange die Geschosshöhe nur auf EINER Quelle beruht.
            "schnitt_hinweis": schnitt_hinweis,
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
            # DACH-Substitution NUR, wenn die Seite KEIN echter Grundriss ist (kaum
            # Wände). Ein realer EG-Grundriss (viele Wände), dessen Raumstempel nur
            # nicht parsbar sind (kein 'Fl:'-Anker), blieb sonst nicht Grundriss,
            # sondern wurde fälschlich durch die Dach-Ansicht ersetzt (Audit).
            if not (res.get("raeume") or []) and (res.get("meta", {}).get("n_waende") or 0) < 5:
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
