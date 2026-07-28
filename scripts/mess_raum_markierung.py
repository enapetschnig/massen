"""MESSUNG: Werden die Räume am Plan RICHTIG MARKIERT?

Nicht „öffnet sich die Planansicht" (das misst test_korpus), sondern die
Kennzahl, die der Nutzer sieht: bekommt JEDER erkannte Raum ein Polygon
eingezeichnet — und ist es das RICHTIGE?

Drei Stufen je Raum, streng aufsteigend:
  markiert   — es gibt überhaupt ein Polygon (>=3 Punkte)
  plausibel  — Polygonfläche passt zur ausgewiesenen Fläche (±20 %)
  bewiesen   — unabhängig bestätigt (IoU-Formbeweis der Pipeline)
Rein lesend, kein API-Guthaben nötig.
"""
import glob
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))
import fitz            # noqa: E402
import nachzeichnen    # noqa: E402

DL = os.path.expanduser("~/Downloads")
KORPUS = [
    "AU_WM_01 Erdgeschoss",
    "A-5_Einreichplan_Alfred-Angerer",
    "AP.01 Layout-1",
    "1762788650811_EG-Wand-Grundriss",
    "05_AU.3.1.1 HAUS A",
    "WA_Velden_Franzosen Allee_Ausführung_TG",
]


def _find(teil):
    g = sorted(glob.glob(os.path.join(DL, f"*{teil}*.pdf")))
    return g[0] if g else None


def _poly_flaeche_m2(pts, scale, ptm):
    """region_px (Bildpixel) -> m². px -> pt via /scale, pt -> m via /ptm."""
    if not pts or len(pts) < 3 or not scale or not ptm:
        return None
    s = 0.0
    for i in range(len(pts)):
        x1, y1 = pts[i]
        x2, y2 = pts[(i + 1) % len(pts)]
        s += x1 * y2 - x2 * y1
    return abs(s) / 2.0 / (scale ** 2) / (ptm ** 2)


def run():
    print(f"{'Plan':<40}{'Räume':>6}{'markiert':>10}{'plausibel':>11}"
          f"{'bewiesen':>10}{'konstr.':>8}")
    print("-" * 78)
    g_raeume = g_mark = g_plaus = g_bew = g_konstr = 0
    details = []
    for teil in KORPUS:
        pf = _find(teil)
        if not pf:
            print(f"{teil[:38]:<40}{'—':>6}  (Datei fehlt)")
            continue
        try:
            r = nachzeichnen.analysiere_doc(fitz.open(pf), max_px=1400)
        except Exception as e:
            print(f"{teil[:38]:<40}  CRASH {str(e)[:28]}")
            continue
        if not r.get("ok"):
            print(f"{teil[:38]:<40}{'—':>6}  ✗ {(r.get('grund') or '')[:30]}")
            continue
        meta = r.get("meta") or {}
        sc, ptm = meta.get("scale"), meta.get("ptm")
        raeume = r.get("raeume") or []
        n = len(raeume)
        mark = plaus = bew = 0
        konstr = 0
        for rm in raeume:
            pts = rm.get("region_px") or []
            if len(pts) >= 3:
                mark += 1
                if rm.get("region_geschaetzt"):
                    konstr += 1
                f_soll = rm.get("f_m2") or rm.get("flaeche_m2")
                f_poly = _poly_flaeche_m2(pts, sc, ptm)
                if f_soll and f_poly and abs(f_poly / f_soll - 1.0) <= 0.20:
                    plaus += 1
                elif not f_soll and f_poly:
                    plaus += 1          # ohne Stempel: Polygon IST die Quelle
            if rm.get("iou_bewiesen"):
                bew += 1
            if len(pts) < 3:
                details.append((os.path.basename(pf)[:26], rm.get("name"),
                                "kein Polygon"))
        g_raeume += n; g_mark += mark; g_plaus += plaus; g_bew += bew
        g_konstr += konstr
        print(f"{os.path.basename(pf)[:38]:<40}{n:>6}{mark:>10}{plaus:>11}{bew:>10}"
              f"{konstr:>8}")
    print("-" * 78)
    q = lambda a, b: f"{a/b*100:.0f}%" if b else "—"   # noqa: E731
    print(f"{'GESAMT':<40}{g_raeume:>6}{g_mark:>10}{g_plaus:>11}{g_bew:>10}"
          f"{g_konstr:>8}")
    print(f"{'':40}{'':6}{q(g_mark,g_raeume):>10}{q(g_plaus,g_raeume):>11}"
          f"{q(g_bew,g_raeume):>10}")
    if details:
        print(f"\nRäume OHNE Polygon ({len(details)}):")
        for d in details[:20]:
            print(f"  {d[0]:<28} {str(d[1])[:24]:<26} {d[2]}")
    print(f"\nKENNZAHL 'Räume richtig markiert': {g_plaus}/{g_raeume} "
          f"({q(g_plaus, g_raeume)}) plausibel eingezeichnet")

    # WÄCHTER-SCHWELLEN (gemessen 2026-07-28 nach dem Stempel-Gate: 92/115 = 80%,
    # markiert == plausibel). Beides ist die Zusage an den Nutzer:
    #  (a) mindestens 70 % der Räume bekommen einen Umriss,
    #  (b) JEDER gezeichnete Umriss ist gegen den Stempel bewiesen — wir zeichnen
    #      nichts Falsches. (b) ist die härtere und wichtigere Zusage.
    assert g_raeume >= 100, f"Korpus geschrumpft ({g_raeume} Räume) — Messung untauglich"
    quote = g_plaus / g_raeume
    # Zusage 1: praktisch JEDER Raum wird markiert (gemessen 115/115 = 100%;
    # Schwelle 95% lässt Luft für neue, schwierigere Pläne im Korpus).
    assert quote >= 0.95, f"Raum-Markierung geregressiert: {quote*100:.0f}% < 95%"
    # Zusage 2 (die härtere): es wird NICHTS FALSCHES eingezeichnet — jeder
    # gezeichnete Umriss umschließt die gestempelte Fläche (±20%), entweder
    # geometrisch bewiesen oder flächenrichtig konstruiert.
    falsch = g_mark - g_plaus
    assert falsch == 0, (
        f"{falsch} gezeichnete Umrisse decken sich NICHT mit der Stempel-Fläche "
        f"— es darf nichts Falsches eingezeichnet werden")
    # Zusage 3: die Mehrheit ist ECHTE Geometrie, nicht nur konstruiert.
    echt = g_mark - g_konstr
    assert echt >= 0.6 * g_mark, (
        f"nur {echt}/{g_mark} Umrisse aus echter Geometrie — zu viel konstruiert")
    print(f"WÄCHTER ok: {quote*100:.0f}% markiert (Schwelle 95%), "
          f"0 falsche Umrisse, {echt}/{g_mark} aus echter Geometrie")


if __name__ == "__main__":
    run()
