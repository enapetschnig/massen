"""WÄCHTER/METRIK: liegt jede Raum-Region an ihrem eigenen Stempel?

DIE LÜCKE, die dieser Test schliesst (Befund 23.08.2026, am handgezogenen
Korpus belegt): auf dem AP.01-Polierplan lagen ALLE fünf Regionen um 73 cm
nach unten verschoben — bei nahezu exakter Fläche (+2,5 bis +4,5 %). Keine
bestehende Kennzahl hat das gesehen:
  · Flächen-Vergleich gegen den Stempel  -> stimmt (die Fläche ist ja richtig)
  · "Umriss liegt auf einer Wand"        -> stimmt sogar besser als die
                                            Handarbeit (die Region folgt den
                                            FALSCH erkannten Wandlinien)
Beide messen die Erkennung gegen sich selbst. Es fehlte ein LAGE-Anker aus
einer unabhängigen Quelle.

Der Raum-STEMPEL ist dieser Anker: seine Position kommt byte-exakt aus dem
PDF-Textlayer, unabhängig von Wandmaske, Watershed und Snap. Ein Planer
setzt den Raumnamen ins Rauminnere — liegt unsere Region richtig, enthält
sie ihren eigenen Stempel, und zwar nicht am äussersten Rand.

Gemessen je Raum:
  drin?        liegt der Stempelpunkt im Polygon (harte Ja/Nein-Prüfung)
  rand_anteil  Abstand Stempel->Polygonrand, relativ zur Raumgrösse
               (0 = auf der Kante, 1 = so weit innen wie möglich)
Und je Plan der SYSTEMATIK-Test: zeigen die Stempel-zu-Schwerpunkt-Vektoren
aller Räume in dieselbe Richtung, ist es EIN gemeinsamer Lage-Fehler.

Lauf: massenermittlung/venv/bin/python3 scripts/mess_stempel_lage.py
      [--projekt <id>] [--plan <id>]
"""
from __future__ import annotations

import json
import math
import os
import sys
import urllib.request

WURZEL = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROJEKT_DEFAULT = "82278c64-6a98-4b24-815b-52feaed59184"


def _env():
    pfad = os.path.join(WURZEL, "massenermittlung", ".env")
    werte = {}
    if os.path.exists(pfad):
        for zeile in open(pfad, encoding="utf-8"):
            if "=" in zeile and not zeile.strip().startswith("#"):
                k, _, v = zeile.strip().partition("=")
                werte[k] = v.strip().strip('"').strip("'")
    return (os.environ.get("SUPABASE_URL") or werte.get("SUPABASE_URL"),
            os.environ.get("SUPABASE_SERVICE_KEY") or werte.get("SUPABASE_SERVICE_KEY"))


def _hole(pfad):
    url, key = _env()
    req = urllib.request.Request(url + pfad, headers={
        "apikey": key, "Authorization": "Bearer " + key})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


def _drin(pt, poly):
    x, y = pt
    drin = False
    j = len(poly) - 1
    for i in range(len(poly)):
        xi, yi = poly[i]
        xj, yj = poly[j]
        if (yi > y) != (yj > y):
            if x < (xj - xi) * (y - yi) / ((yj - yi) or 1e-9) + xi:
                drin = not drin
        j = i
    return drin


def _dist_kante(p, a, b):
    px, py = p
    ax, ay = a
    bx, by = b
    dx, dy = bx - ax, by - ay
    L2 = dx * dx + dy * dy
    if L2 < 1e-9:
        return math.hypot(px - ax, py - ay)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / L2))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def _schwerpunkt(poly):
    a = cx = cy = 0.0
    for i in range(len(poly)):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % len(poly)]
        f = x1 * y2 - x2 * y1
        a += f
        cx += (x1 + x2) * f
        cy += (y1 + y2) * f
    if abs(a) < 1e-9:
        return (sum(p[0] for p in poly) / len(poly),
                sum(p[1] for p in poly) / len(poly))
    a *= 0.5
    return cx / (6 * a), cy / (6 * a)


def _flaeche(poly):
    s = 0.0
    for i in range(len(poly)):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % len(poly)]
        s += x1 * y2 - x2 * y1
    return abs(s) / 2.0


def pruefe_plan(erg, name=""):
    """Liefert (zeilen, systematik-dict) für einen Nachzeichnen-Lauf."""
    meta = erg.get("meta") or {}
    sc = float(meta.get("scale") or 0) or 1.0
    ptm = float(meta.get("ptm") or 0) or 0.0
    px_pro_m = sc * ptm

    zeilen = []
    for r in erg.get("raeume") or []:
        poly = r.get("region_px")
        stempel = r.get("px")
        if not poly or len(poly) < 3 or not stempel or len(stempel) < 2:
            continue
        poly = [(float(p[0]), float(p[1])) for p in poly]
        s = (float(stempel[0]), float(stempel[1]))
        drin = _drin(s, poly)
        rand = min(_dist_kante(s, poly[i], poly[(i + 1) % len(poly)])
                   for i in range(len(poly)))
        # Bezugsgröße: Radius eines flächengleichen Kreises — macht den
        # Randabstand über verschieden große Räume vergleichbar.
        radius = math.sqrt(max(_flaeche(poly), 1.0) / math.pi)
        c = _schwerpunkt(poly)
        zeilen.append({
            "raum": r.get("name") or "?",
            "drin": drin,
            "rand_anteil": round((rand / radius) if drin else -(rand / radius), 2),
            "rand_cm": round(rand / px_pro_m * 100, 1) if px_pro_m else None,
            "dx_cm": round((c[0] - s[0]) / px_pro_m * 100, 1) if px_pro_m else None,
            "dy_cm": round((c[1] - s[1]) / px_pro_m * 100, 1) if px_pro_m else None,
            "aussenanlage": bool(r.get("aussenanlage")),
        })

    innen = [z for z in zeilen if not z["aussenanlage"]]
    sys_info = {}
    if innen:
        dxs = [z["dx_cm"] for z in innen if z["dx_cm"] is not None]
        dys = [z["dy_cm"] for z in innen if z["dy_cm"] is not None]
        if dxs:
            mx, my = sum(dxs) / len(dxs), sum(dys) / len(dys)
            sx = (sum((d - mx) ** 2 for d in dxs) / len(dxs)) ** 0.5
            sy = (sum((d - my) ** 2 for d in dys) / len(dys)) ** 0.5
            sys_info = {"mx": mx, "my": my, "streu": math.hypot(sx, sy),
                        "betrag": math.hypot(mx, my)}
    return zeilen, sys_info


def main():
    projekt = PROJEKT_DEFAULT
    if "--projekt" in sys.argv:
        projekt = sys.argv[sys.argv.index("--projekt") + 1]
    nur_plan = None
    if "--plan" in sys.argv:
        nur_plan = sys.argv[sys.argv.index("--plan") + 1]

    url, key = _env()
    os.environ.setdefault("SUPABASE_URL", url)
    os.environ.setdefault("SUPABASE_SERVICE_KEY", key)
    sys.path.insert(0, os.path.join(WURZEL, "api"))
    import extract  # noqa: E402

    plaene = _hole(f"/rest/v1/plaene?projekt_id=eq.{projekt}&select=id,dateiname")
    fehler = []
    for p in plaene:
        if nur_plan and p["id"] != nur_plan:
            continue

        class B:
            pass
        b = B()
        b.plan_id = p["id"]
        b.projekt_id = None
        b.seite = None
        b.leicht = False
        erg = extract._nachzeichnen_roh(b)
        print(f"\n══ {p['dateiname'][:58]}")
        if not erg or not erg.get("ok"):
            print("   kein Grundriss / nicht auswertbar:", (erg or {}).get("grund"))
            continue
        zeilen, sysi = pruefe_plan(erg)
        if not zeilen:
            print("   keine Räume mit Polygon + Stempel")
            continue
        for z in zeilen:
            mark = "✓" if z["drin"] else "✗ STEMPEL LIEGT AUSSERHALB"
            print(f"   {z['raum'][:22]:22s} {mark:26s} "
                  f"Rand {z['rand_cm'] or 0:6.1f} cm · "
                  f"Δ({z['dx_cm']:+6.1f},{z['dy_cm']:+6.1f}) cm"
                  + ("  [Freifläche]" if z["aussenanlage"] else ""))
        innen = [z for z in zeilen if not z["aussenanlage"]]
        raus = [z for z in innen if not z["drin"]]
        print(f"   ── {len(innen) - len(raus)}/{len(innen)} Räume enthalten "
              f"ihren eigenen Stempel")
        if sysi:
            if sysi["betrag"] > 2 * sysi["streu"] and sysi["betrag"] > 15:
                print(f"   ── SYSTEMATISCHER VERSATZ {sysi['betrag']:.0f} cm "
                      f"(Δx {sysi['mx']:+.0f} / Δy {sysi['my']:+.0f}, Streuung "
                      f"{sysi['streu']:.0f} cm) — EIN gemeinsamer Lage-Fehler")
                fehler.append(f"{p['dateiname'][:30]}: {sysi['betrag']:.0f} cm Versatz")
            else:
                print(f"   ── kein gemeinsamer Versatz (Betrag {sysi['betrag']:.0f} cm, "
                      f"Streuung {sysi['streu']:.0f} cm)")
        if raus:
            fehler.append(f"{p['dateiname'][:30]}: {len(raus)} Räume ohne eigenen Stempel")

    print("\n" + "─" * 74)
    if fehler:
        print("BEFUNDE:")
        for f in fehler:
            print("  ·", f)
    else:
        print("OK — jede Region enthält ihren Stempel, kein systematischer Versatz.")
    return 1 if fehler else 0


if __name__ == "__main__":
    sys.exit(main())
