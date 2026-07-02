"""TÜR-BOGEN-FINDER (v3-Einstieg, LOG-only) — Türen aus GEOMETRIE statt Text-Ankern.

BEFUND der Snap-Großsezierung (Juli 2026): FPH/STUK-Text-Anker liegen bis 0,63m
neben der echten Tür; alle Text-Anker-Snap-Heuristiken waren über globale Schwellen
gekoppelt und instabil. DER PLAN ZEICHNET DIE TÜR ABER SELBST: Aufschlag-Viertelkreis
mit Angelpunkt (Drehband) + Radius (= Türbreite, byte-genau aus der Geometrie) +
Sehnen-Endpunkt (Tür zu = Öffnungslinie in der Wand).

Dieses Skript misst NUR (kein Pipeline-Eingriff):
  1. Wie viele Bezier-Bögen im EG-Bereich sind Viertelkreise mit Tür-Radius?
  2. Wie viele der bekannten FPH/STUK-Tür-Texte haben einen Bogen in ≤1,5m?
     (= Abdeckung: kann v3 die Text-Anker durch Bogen-Geometrie ersetzen?)

Kasa-Kreisfit (algebraisch, 2×2-Gleichungssystem, kein numpy — venv-kompatibel).
"""
import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))
import fitz            # noqa: E402
import vektor          # noqa: E402
import nachzeichnen    # noqa: E402
import oeffnungen as oeff_mod   # noqa: E402

PLAN = os.path.expanduser("~/Downloads/A-5_Einreichplan_Alfred-Angerer_36_25_Index 0 (1).pdf")


def _dict_spans(page):
    out = []
    for block in page.get_text("dict").get("blocks", []):
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                txt = (span.get("text") or "").strip()
                if not txt:
                    continue
                bb = tuple(span.get("bbox") or (0, 0, 0, 0))
                out.append({"text": txt, "bbox": bb, "size": span.get("size", 0),
                            "cx": (bb[0] + bb[2]) / 2.0, "cy": (bb[1] + bb[3]) / 2.0})
    return out


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
    """Algebraischer Kreisfit (Kasa): min Σ(x²+y²+Dx+Ey+F)². Rückgabe (cx, cy, r)."""
    n = len(pts)
    sx = sum(p[0] for p in pts) / n
    sy = sum(p[1] for p in pts) / n
    # zentrieren für Kondition
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
    r = math.sqrt(uc * uc + vc * vc + (suu + svv) / n)
    return (uc + sx, vc + sy, r)


def tuer_boegen(page, box, ptm, r_min_m=0.50, r_max_m=1.40,
                winkel_min=55.0, winkel_max=125.0, fit_tol=0.15):
    """Viertelkreis-Bögen mit Tür-Radius aus den 'c'-Items der Drawings.

    Rückgabe: Liste {hinge (x,y), r_m, a (Bogen-Anfang), b (Bogen-Ende), winkel_grad}.
    a/b sind die Radius-Endpunkte: einer davon = 'Tür zu' = Öffnungslinie in der Wand.
    """
    bx0, bx1, by0, by1 = box
    out = []
    for p in page.get_drawings():
        # Pro Pfad die 'c'-Ketten einsammeln (ein Viertelkreis = 1-2 Beziers)
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
            # Fit-Güte: max Abweichung vom Kreis relativ zum Radius
            fehler = max(abs(math.hypot(q[0] - cx, q[1] - cy) - r) for q in pts)
            if fehler > fit_tol * r:
                return
            a, b = pts[0], pts[-1]
            wa = math.atan2(a[1] - cy, a[0] - cx)
            wb = math.atan2(b[1] - cy, b[0] - cx)
            dw = math.degrees(abs(math.atan2(math.sin(wb - wa), math.cos(wb - wa))))
            if not (winkel_min <= dw <= winkel_max):
                return
            out.append({"hinge": (cx, cy), "r_m": round(r_m, 3),
                        "a": a, "b": b, "winkel_grad": round(dw, 1)})

        for it in p.get("items", []):
            if it[0] == "c":
                # zusammenhängend? (Ende der letzten = Anfang der neuen)
                if kette:
                    pe = kette[-1][3]
                    if math.hypot(it[1].x - pe.x, it[1].y - pe.y) > 0.5:
                        _flush()
                kette.append((it[1], it[2], it[3], it[4]))
            else:
                _flush()
        _flush()
    return out


def run():
    d = fitz.open(PLAN)
    page = max(d, key=lambda p: p.rect.width * p.rect.height)
    ptm = vektor.kalibriere(page.get_text("words"), "1:100")["ptm_konsens"]
    box = nachzeichnen._eg_box(page, ptm)
    assert ptm and box

    boegen = tuer_boegen(page, box, ptm)
    print(f"{len(boegen)} Tür-Bögen (Viertelkreis, r 0,50-1,40m) im EG-Bereich")
    for bg in boegen:
        print(f"  hinge=({bg['hinge'][0]:.0f},{bg['hinge'][1]:.0f}) "
              f"r={bg['r_m']:.2f}m winkel={bg['winkel_grad']}°")

    # Abdeckung: bekannte Tür-Texte ↔ nächster Bogen
    oeff = [o for o in oeff_mod.extract_oeffnungen_from_text(_dict_spans(page), [])
            if o.get("typ") == "tuer"]
    bx0, bx1, by0, by1 = box
    oeff = [o for o in oeff if bx0 <= o["cx"] <= bx1 and by0 <= o["cy"] <= by1]
    print(f"\n{len(oeff)} Tür-Texte (FPH/STUK) im EG-Bereich — Abdeckung:")
    treffer = 0
    for o in oeff:
        best, best_d = None, 1e9
        for bg in boegen:
            hx, hy = bg["hinge"]
            dd = math.hypot(hx - o["cx"], hy - o["cy"]) / ptm
            if dd < best_d:
                best_d, best = dd, bg
        ok = best is not None and best_d <= 1.5
        treffer += ok
        print(f"  Text ({o['cx']:.0f},{o['cy']:.0f}) → "
              + (f"Bogen r={best['r_m']:.2f}m in {best_d:.2f}m {'✓' if ok else '✗ (zu weit)'}"
                 if best else "kein Bogen ✗"))
    print(f"\nABDECKUNG: {treffer}/{len(oeff)} Tür-Texte mit Bogen ≤1,5m "
          f"→ v3 (Tür aus Geometrie) ist {'GO' if treffer >= 0.8 * len(oeff) else 'NICHT tragfähig'}")


if __name__ == "__main__":
    run()
