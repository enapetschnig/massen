"""Byte-exakte FARB-LEGENDE aus dem PDF-Text-Layer + Vektor-Swatches.

Viele AT-Bau-Pläne führen eine Legende-Box "Neubau / Bestand / Abbruch", jeweils mit
einem farbigen Swatch (Wort + kleines gefülltes Rechteck). Diese Legende steht
BYTE-EXAKT im PDF (Wort im Text-Layer, Swatch als Vektor-Fill) — KEIN Vision nötig,
um zu wissen WELCHE Farbe was bedeutet.

Empirisch an echten Plänen verifiziert (venv mit PyMuPDF):
  • Angerer / AP.01 (Büro Hohenwarter): Neubau=rot(1,0,0), Abbruch=gelb(1,1,0),
    Bestand=grau. Plan hat zusätzlich eine "Bestandshütte" (Bestand-Objekt).
  • WA_Velden: BESTAND/ABBRUCH-Legende vorhanden (Abbruch=gold 1,0.84,0).
  • HAUS A / EG-Wand-Grundriss: KEINE Neubau/Bestand/Abbruch-Legende → reiner Neubau.

WICHTIG (empirisch, der ehrliche Scope): Das Legende-MAPPING ist byte-exakt. Die
Zuordnung einzelner WÄNDE zu Neubau/Bestand/Abbruch ist es NICHT — die Wand-Schraffur
nutzt gemischte Material-Farben (orange/gelb), die nicht sauber auf die Legende mappen.
Welche REGION Neubau/Bestand/Abbruch ist, bleibt ein Vision-Job (Architektur:
Vision = Semantik, Vektoren = Maß). Dieses Modul liefert daher das ROBUSTE Fundament:
(1) das byte-exakte Farb→Bedeutung-Mapping, (2) die ehrliche Plan-Flagge "enthält
Bestand/Abbruch" → der Nutzer wird gewarnt, dass Massen sich auf Neubau beziehen und
Bestand/Abbruch separat zu prüfen sind. KEIN stilles Filtern (zu unsicher).
"""
from collections import defaultdict

# Wort → Bedeutung. Nur exakte Legende-Begriffe; Objekt-Labels wie "Bestandshütte"
# werden über exakte Wort-Gleichheit ausgeschlossen (nicht "in" sondern ==/startswith-Gate).
_BEDEUTUNG_WORTE = {
    "neubau": "neubau",
    "bestand": "bestand",
    "abbruch": "abbruch",
    "abzubrechen": "abbruch",
    "rückbau": "abbruch",
    "ruckbau": "abbruch",
    "abtrag": "abbruch",
}


def _klasse(col):
    """RGB 0..1 → grobe Farbklasse (für Lesbarkeit/Matching)."""
    if col is None:
        return None
    r, g, b = col
    mx, mn = max(r, g, b), min(r, g, b)
    if mx - mn < 0.12:
        if mx > 0.85:
            return "weiss"
        return "schwarz" if mx < 0.25 else "grau"
    if r > 0.5 and g > 0.5 and b < g - 0.15:
        return "gelb"
    if r > g and r > b:
        return "rot" if g < 0.35 else "orange"
    if g > r and g > b:
        return "gruen"
    if b > r and b > g:
        return "blau"
    return "andere"


def _legende_wort(text):
    """Exaktes Legende-Wort → Bedeutung (sonst None). Schließt 'Bestandshütte' etc. aus."""
    t = (text or "").strip().lower().strip(":·.-")
    return _BEDEUTUNG_WORTE.get(t)


def _swatch_near(drawings, x0, y0, x1, y1, max_dx=160.0, max_dy=12.0):
    """Nächstes Swatch-Rechteck (kleines gefülltes Rechteck) zu einem Legende-Wort.
    Swatch-Heuristik: rect-Breite 8..70pt, Höhe 4..28pt, Mitte ~ auf Wort-Höhe,
    in x links/rechts des Worts. Liefert (rgb, klasse) oder (None, None)."""
    cy = (y0 + y1) / 2.0
    wcx = (x0 + x1) / 2.0
    best = None
    for p in drawings:
        col = p.get("fill") or p.get("color")
        if not col:
            continue
        rc = p.get("rect")
        if rc is None:
            continue
        w, h = rc.width, rc.height
        if not (8.0 <= w <= 70.0 and 4.0 <= h <= 28.0):
            continue
        mx, my = (rc.x0 + rc.x1) / 2.0, (rc.y0 + rc.y1) / 2.0
        if abs(my - cy) > max_dy:
            continue
        dx = abs(mx - wcx)
        if dx > max_dx:
            continue
        if best is None or dx < best[0]:
            best = (dx, tuple(round(c, 3) for c in col))
    if best is None:
        return None, None
    return best[1], _klasse(best[1])


def lies_farb_legende(page):
    """Eine Seite → {bedeutung: {"rgb", "klasse", "wort_pos"}} aus der Legende-Box.
    Nur Bedeutungen mit gefundenem Swatch ODER (für 'bestand'/'abbruch'/'neubau')
    mit Wort-Treffer werden zurückgegeben. Mehrere Treffer je Bedeutung → der mit Swatch."""
    drawings = page.get_drawings()
    treffer = defaultdict(list)
    for w in page.get_text("words"):
        bd = _legende_wort(w[4])
        if not bd:
            continue
        rgb, kl = _swatch_near(drawings, w[0], w[1], w[2], w[3])
        treffer[bd].append({"rgb": rgb, "klasse": kl, "wort_pos": (round(w[0]), round(w[1]))})
    out = {}
    for bd, lst in treffer.items():
        mit_swatch = [t for t in lst if t["rgb"] is not None]
        out[bd] = (mit_swatch[0] if mit_swatch else lst[0])
        out[bd]["n_vorkommen"] = len(lst)
    return out


def analysiere_dokument(doc):
    """Ganzes PDF → ehrliche Plan-Flagge.
    Returns {
      "hat_bestand": bool, "hat_abbruch": bool,
      "mapping": {bedeutung: {rgb, klasse, ...}},   # byte-exaktes Farb→Bedeutung
      "seite": idx | None,                          # Seite mit der Legende
      "hinweis": str | None,                        # nutzer-lesbare Warnung
    }
    Reiner Neubau-Plan (keine Bestand/Abbruch-Legende) → alle False, kein Hinweis
    (Massen unverändert = Neubau). So bleibt der validierte Neubau-Fall ein No-Op."""
    best_seite, best_map = None, {}
    for idx, page in enumerate(doc):
        m = lies_farb_legende(page)
        # Eine echte Legende-Box hat mind. 2 der 3 Begriffe nah beieinander
        kern = [b for b in ("neubau", "bestand", "abbruch") if b in m]
        if len(kern) >= 2 and len(kern) > len([b for b in ("neubau", "bestand", "abbruch") if b in best_map]):
            best_seite, best_map = idx, m
    hat_b = "bestand" in best_map
    hat_a = "abbruch" in best_map
    hinweis = None
    if hat_b or hat_a:
        teile = []
        if hat_b:
            teile.append("Bestand")
        if hat_a:
            teile.append("Abbruch")
        hinweis = (f"Plan enthält {'/'.join(teile)}-Elemente (laut Legende). "
                   f"Die Massen beziehen sich auf den Neubau — {'/'.join(teile)} bitte "
                   f"separat prüfen (nicht automatisch herausgerechnet).")
    return {
        "hat_bestand": hat_b,
        "hat_abbruch": hat_a,
        "mapping": {b: {k: v for k, v in d.items()} for b, d in best_map.items()},
        "seite": best_seite,
        "hinweis": hinweis,
    }
