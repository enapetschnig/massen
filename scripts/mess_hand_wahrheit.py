"""MESS-HARNESS: die Erkennung gegen HANDGEZOGENE Raum-Umrisse.

Warum das die wichtigste Metrik ist, die uns bisher fehlte:
Alle bisherigen Kennzahlen prüfen ZAHLEN (Fläche/Umfang aus den byte-exakten
Stempeln) oder SCHWACHE Stellvertreter ("liegt der Umriss auf irgendeiner
Wand?" — 93 % und trotzdem falsche Form, siehe project_umriss_auf_wand).
Keine davon kann sagen, ob der Umriss AN DER RICHTIGEN STELLE liegt.

Ein vom Nutzer von Hand nachgezogener Raum kann das. Er ist die einzige
Wahrheit über FORM UND LAGE, die wir haben. Diese Umrisse liegen im Plan
unter agent_log['nachzeichnen_korrekturen']['raum_regionen'] — die App
speichert sie, seit der Nutzer sie am 23.08.2026 zog und sie beim Reload
verlor.

Gemessen wird je Raum:
  IoU            Schnitt/Vereinigung — die eine ehrliche Formzahl
  Flaeche        erkannt vs Hand (%)
  Versatz        Schwerpunkt-Abstand in cm (systematischer Lage-Fehler?)
  Randabstand    mittlerer Abstand der Hand-Kanten zum erkannten Umriss

Lauf: massenermittlung/venv/bin/python3 scripts/mess_hand_wahrheit.py
      [--projekt <id>] [--json]
Ohne Argument nimmt es das Angerer-Beispielprojekt.
"""
from __future__ import annotations

import json
import math
import os
import sys
import urllib.request

WURZEL = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROJEKT_DEFAULT = "82278c64-6a98-4b24-815b-52feaed59184"


# ── Supabase (nur lesend) ────────────────────────────────────────────────
def _env():
    pfad = os.path.join(WURZEL, "massenermittlung", ".env")
    werte = {}
    if os.path.exists(pfad):
        for zeile in open(pfad, encoding="utf-8"):
            if "=" in zeile and not zeile.strip().startswith("#"):
                k, _, v = zeile.strip().partition("=")
                werte[k] = v.strip().strip('"').strip("'")
    url = os.environ.get("SUPABASE_URL") or werte.get("SUPABASE_URL")
    key = (os.environ.get("SUPABASE_SERVICE_KEY") or werte.get("SUPABASE_SERVICE_KEY"))
    if not url or not key:
        print("FEHLER: SUPABASE_URL/SUPABASE_SERVICE_KEY fehlen "
              "(massenermittlung/.env)")
        sys.exit(2)
    return url, key


def _hole(pfad):
    url, key = _env()
    req = urllib.request.Request(url + pfad, headers={
        "apikey": key, "Authorization": "Bearer " + key})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


# ── Polygon-Werkzeuge (rein, ohne numpy) ─────────────────────────────────
def flaeche(poly):
    s = 0.0
    for i in range(len(poly)):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % len(poly)]
        s += x1 * y2 - x2 * y1
    return abs(s) / 2.0


def schwerpunkt(poly):
    a = 0.0
    cx = cy = 0.0
    for i in range(len(poly)):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % len(poly)]
        f = x1 * y2 - x2 * y1
        a += f
        cx += (x1 + x2) * f
        cy += (y1 + y2) * f
    if abs(a) < 1e-9:
        xs = [p[0] for p in poly]
        ys = [p[1] for p in poly]
        return sum(xs) / len(xs), sum(ys) / len(ys)
    a *= 0.5
    return cx / (6 * a), cy / (6 * a)


def _drin(pt, poly):
    """Strahlensatz — Punkt in Polygon."""
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


def iou_raster(a, b, zellen=260):
    """IoU über ein feines Raster — robust ohne Clipping-Bibliothek.

    Ein exakter Polygon-Schnitt wäre schöner, aber jede Eigenbau-Variante
    ist an entarteten Kanten fehleranfällig; ein 260er-Raster über der
    gemeinsamen BBox liegt bei diesen Raumgrößen unter 1 % Rasterfehler
    und ist nachvollziehbar.
    """
    xs = [p[0] for p in a] + [p[0] for p in b]
    ys = [p[1] for p in a] + [p[1] for p in b]
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    if x1 <= x0 or y1 <= y0:
        return 0.0, 0.0, 0.0
    schnitt = nur_a = nur_b = 0
    for i in range(zellen):
        x = x0 + (x1 - x0) * (i + 0.5) / zellen
        for j in range(zellen):
            y = y0 + (y1 - y0) * (j + 0.5) / zellen
            ia, ib = _drin((x, y), a), _drin((x, y), b)
            if ia and ib:
                schnitt += 1
            elif ia:
                nur_a += 1
            elif ib:
                nur_b += 1
    ver = schnitt + nur_a + nur_b
    zell_f = (x1 - x0) * (y1 - y0) / (zellen * zellen)
    return (schnitt / ver if ver else 0.0), nur_a * zell_f, nur_b * zell_f


def dist_punkt_kante(p, a, b):
    px, py = p
    ax, ay = a
    bx, by = b
    dx, dy = bx - ax, by - ay
    L2 = dx * dx + dy * dy
    if L2 < 1e-9:
        return math.hypot(px - ax, py - ay)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / L2))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def rand_abstand(soll, ist):
    """Mittlerer Abstand der SOLL-Ecken zum IST-Umriss (px)."""
    if not ist:
        return None
    werte = []
    for p in soll:
        werte.append(min(dist_punkt_kante(p, ist[i], ist[(i + 1) % len(ist)])
                         for i in range(len(ist))))
    return sum(werte) / len(werte)


def _nrm(s):
    s = (s or "").lower()
    for a, b in (("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("ß", "ss")):
        s = s.replace(a, b)
    return "".join(c for c in s if c.isalnum())


# ── Hauptlauf ────────────────────────────────────────────────────────────
def main():
    projekt = PROJEKT_DEFAULT
    als_json = "--json" in sys.argv
    if "--projekt" in sys.argv:
        projekt = sys.argv[sys.argv.index("--projekt") + 1]

    plaene = _hole(f"/rest/v1/plaene?projekt_id=eq.{projekt}"
                   f"&select=id,dateiname,agent_log")
    hand = {}          # plan_id -> {name: {region_px, ...}}
    for p in plaene:
        log = p.get("agent_log") or {}
        for key, k in log.items():
            if "korrektur" not in key or not isinstance(k, dict):
                continue
            rr = k.get("raum_regionen") or {}
            if rr:
                hand.setdefault(p["id"], {}).update(rr)
    if not hand:
        print("Keine handgezogenen Umrisse in diesem Projekt gefunden.")
        print("(Räume im Editor nachziehen — sie werden automatisch gespeichert.)")
        sys.exit(1)

    sys.path.insert(0, os.path.join(WURZEL, "api"))
    import extract  # noqa: E402  (braucht die Env aus _env)
    url, key = _env()
    os.environ.setdefault("SUPABASE_URL", url)
    os.environ.setdefault("SUPABASE_SERVICE_KEY", key)

    zeilen = []
    for plan_id, raeume_hand in hand.items():
        name_plan = next((p["dateiname"] for p in plaene if p["id"] == plan_id), plan_id)
        print(f"\n══ {name_plan[:60]}  ({len(raeume_hand)} handgezogene Räume)")

        class B:  # minimaler Request-Stub
            pass
        b = B()
        b.plan_id = plan_id
        b.projekt_id = None
        b.seite = None
        b.leicht = False
        try:
            erg = extract._nachzeichnen_roh(b)
        except AttributeError:
            print("   (interne Lauf-Funktion nicht gefunden — Name geändert?)")
            sys.exit(3)
        if not erg or not erg.get("ok"):
            print("   Nachzeichnen fehlgeschlagen:", (erg or {}).get("grund"))
            continue

        meta = erg.get("meta") or {}
        sc = float(meta.get("scale") or 0) or 1.0
        ptm = float(meta.get("ptm") or 0) or 0.0
        px_pro_m = sc * ptm if ptm else 0.0

        ist_map = {}
        for r in erg.get("raeume") or []:
            if r.get("region_px") and len(r["region_px"]) >= 3:
                ist_map[_nrm(r.get("name"))] = r

        for schluessel, v in sorted(raeume_hand.items()):
            # PLAN-Koordinaten haben Vorrang (überleben Box-/Auflösungs-
            # Änderungen); region_px gilt nur für den Bildausschnitt von damals.
            if v.get("region_pt") and sc:
                _b = meta.get("box_pt") or [0, 0]
                soll = [(float(p[0] - _b[0]) * sc, float(p[1] - _b[1]) * sc)
                        for p in v["region_pt"]]
            else:
                soll = [(float(p[0]), float(p[1])) for p in v["region_px"]]
            r_ist = ist_map.get(schluessel)
            if not r_ist:
                print(f"   {v.get('name', schluessel):22s} — von der Erkennung "
                      f"GAR NICHT als Polygon geliefert")
                zeilen.append({"raum": v.get("name", schluessel), "iou": 0.0,
                               "fehlt": True})
                continue
            ist = [(float(p[0]), float(p[1])) for p in r_ist["region_px"]]
            iou, zuviel, zuwenig = iou_raster(ist, soll)
            f_ist, f_soll = flaeche(ist), flaeche(soll)
            c_ist, c_soll = schwerpunkt(ist), schwerpunkt(soll)
            versatz_px = math.hypot(c_ist[0] - c_soll[0], c_ist[1] - c_soll[1])
            rand_px = rand_abstand(soll, ist)
            zu_m = (lambda px: px / px_pro_m) if px_pro_m else (lambda px: None)

            f_pct = (f_ist / f_soll - 1) * 100 if f_soll else 0
            zeile = {
                "raum": v.get("name", schluessel),
                "iou": round(iou, 3),
                "flaeche_abw_pct": round(f_pct, 1),
                # RICHTUNG des Versatzes, nicht nur der Betrag: zeigen alle
                # Räume in dieselbe Richtung, ist es EIN globaler Offset
                # (ein Fix für alle) statt vieler Einzelfehler.
                "dx_cm": round(zu_m(c_ist[0] - c_soll[0]) * 100, 1) if px_pro_m else None,
                "dy_cm": round(zu_m(c_ist[1] - c_soll[1]) * 100, 1) if px_pro_m else None,
                "versatz_cm": round(zu_m(versatz_px) * 100, 1) if px_pro_m else None,
                "randabstand_cm": round(zu_m(rand_px) * 100, 1) if px_pro_m else None,
                "zuviel_m2": round(zuviel / (px_pro_m ** 2), 2) if px_pro_m else None,
                "zuwenig_m2": round(zuwenig / (px_pro_m ** 2), 2) if px_pro_m else None,
                "ecken_ist": len(ist), "ecken_hand": len(soll),
                "stempel_f": r_ist.get("f_m2"),
            }
            zeilen.append(zeile)
            print(f"   {zeile['raum']:22s} IoU {iou:5.2f} · Fläche {f_pct:+6.1f} % · "
                  f"Δ({zeile['dx_cm']:+6.1f},{zeile['dy_cm']:+6.1f}) cm · "
                  f"Versatz {zeile['versatz_cm'] or 0:5.1f} cm · "
                  f"Rand {zeile['randabstand_cm'] or 0:5.1f} cm · "
                  f"zuviel {zeile['zuviel_m2']} m² / fehlt {zeile['zuwenig_m2']} m² · "
                  f"Ecken {len(ist)}→{len(soll)}")

        # GEGENPROBE gegen die unabhängige Vektor-Quelle (Wandlinien)
        gt = gegentest_waende(erg, raeume_hand, px_pro_m, ist_map)
        if gt:
            print("\n   Gegenprobe — Anteil des Umrisses auf einer erkannten Wand:")
            for name, a_hand, a_ist in gt:
                print(f"      {name:22s} Hand {a_hand*100:5.1f} %   "
                      f"Erkennung {a_ist*100:5.1f} %")
            mh = sum(x[1] for x in gt) / len(gt)
            mi = sum(x[2] for x in gt) / len(gt)
            print(f"      {'MITTEL':22s} Hand {mh*100:5.1f} %   "
                  f"Erkennung {mi*100:5.1f} %"
                  + ("   => die Handarbeit liegt auf den Wänden, "
                     "unsere Regionen nicht: der Fehler ist bei UNS."
                     if mh > mi + 0.15 else ""))

        gf, n_fl = gegentest_fluchten(erg, raeume_hand, px_pro_m, ist_map)
        if gf:
            print(f"\n   Gegenprobe — Anteil auf byte-exakter MASSKETTEN-FLUCHT "
                  f"({n_fl} bestaetigte Fluchten):")
            for name, a_hand, a_ist in gf:
                print(f"      {name:22s} Hand {a_hand*100:5.1f} %   "
                      f"Erkennung {a_ist*100:5.1f} %")
            mh2 = sum(x[1] for x in gf) / len(gf)
            mi2 = sum(x[2] for x in gf) / len(gf)
            print(f"      {'MITTEL':22s} Hand {mh2*100:5.1f} %   "
                  f"Erkennung {mi2*100:5.1f} %"
                  + ("   => die Handarbeit trifft die Plan-Bemassung, "
                     "unsere Regionen nicht." if mh2 > mi2 + 0.10 else ""))

    echte = [z for z in zeilen if not z.get("fehlt")]
    print("\n" + "─" * 78)
    if echte:
        n = len(echte)
        m_iou = sum(z["iou"] for z in echte) / n
        gut = sum(1 for z in echte if z["iou"] >= 0.85)
        print(f"KORPUS {len(zeilen)} handgezogene Räume · mittlere IoU {m_iou:.2f} · "
              f"{gut}/{n} erreichen IoU ≥ 0,85")
        vs = [z["versatz_cm"] for z in echte if z.get("versatz_cm") is not None]
        if vs:
            print(f"       Lage-Versatz: Median {sorted(vs)[len(vs)//2]:.1f} cm · "
                  f"max {max(vs):.1f} cm")
        # SYSTEMATIK-PRÜFUNG — die eigentliche Frage: ein globaler Offset
        # (dann reicht EIN Fix für alle künftigen Pläne) oder Einzelfehler?
        dxs = [z["dx_cm"] for z in echte if z.get("dx_cm") is not None]
        dys = [z["dy_cm"] for z in echte if z.get("dy_cm") is not None]
        if dxs:
            mx = sum(dxs) / len(dxs)
            my = sum(dys) / len(dys)
            sx = (sum((d - mx) ** 2 for d in dxs) / len(dxs)) ** 0.5
            sy = (sum((d - my) ** 2 for d in dys) / len(dys)) ** 0.5
            print(f"       Richtung: Δx {mx:+.1f} ± {sx:.1f} cm · "
                  f"Δy {my:+.1f} ± {sy:.1f} cm")
            betrag = (mx * mx + my * my) ** 0.5
            streu = (sx * sx + sy * sy) ** 0.5
            if betrag > 2 * streu and betrag > 10:
                print(f"       => SYSTEMATISCHER VERSATZ {betrag:.0f} cm "
                      f"(Streuung nur {streu:.0f} cm): ein gemeinsamer "
                      f"Lage-Fehler, kein Einzelraum-Problem.")
            else:
                print(f"       => KEIN gemeinsamer Offset (Streuung {streu:.0f} cm "
                      f"≥ Betrag {betrag:.0f} cm): die Räume liegen "
                      f"unabhängig voneinander daneben.")
        zv = [z["zuviel_m2"] for z in echte if z.get("zuviel_m2") is not None]
        zw = [z["zuwenig_m2"] for z in echte if z.get("zuwenig_m2") is not None]
        if zv:
            print(f"       Σ zu viel erkannt {sum(zv):.2f} m² · "
                  f"Σ fehlt {sum(zw):.2f} m²")
    if als_json:
        print(json.dumps(zeilen, ensure_ascii=False, indent=2))




def gegentest_waende(erg, raeume_hand, px_pro_m, ist_map, _nrm=_nrm):
    """GEGENPROBE: liegen die HAND-Umrisse auf den erkannten Wandlinien?

    Der Versatz-Befund allein könnte auch heissen, dass der Nutzer alles
    verschoben gezogen hat. Die Wandlinien stammen aber aus der VEKTOR-
    Geometrie (unabhaengige Quelle). Liegt die Handarbeit auf den Waenden
    und unsere Region daneben, ist der Fehler beweisbar bei uns.
    """
    waende = []
    for w in erg.get("waende") or []:
        px = w.get("px")
        if px and len(px) >= 4:
            waende.append(((float(px[0]), float(px[1])), (float(px[2]), float(px[3]))))
    if not waende:
        return None
    tol = 0.09 * px_pro_m if px_pro_m else 9.0   # 9 cm wie mess_umriss_auf_wand

    def anteil(poly):
        """Anteil der UMFANGS-Laenge, der naeher als tol an einer Wand liegt."""
        gesamt = treffer = 0.0
        for i in range(len(poly)):
            a, b = poly[i], poly[(i + 1) % len(poly)]
            L = math.hypot(b[0] - a[0], b[1] - a[1])
            if L < 1e-6:
                continue
            n = max(2, int(L / max(2.0, tol / 3)))
            for k in range(n):
                t = (k + 0.5) / n
                p = (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)
                d = min(dist_punkt_kante(p, w0, w1) for w0, w1 in waende)
                gesamt += L / n
                if d <= tol:
                    treffer += L / n
        return treffer / gesamt if gesamt else 0.0

    zeilen = []
    for schluessel, v in sorted(raeume_hand.items()):
        r_ist = ist_map.get(schluessel)
        if not r_ist:
            continue
        hand = [(float(p[0]), float(p[1])) for p in v["region_px"]]
        ist = [(float(p[0]), float(p[1])) for p in r_ist["region_px"]]
        zeilen.append((v.get("name", schluessel), anteil(hand), anteil(ist)))
    return zeilen



def gegentest_fluchten(erg, raeume_hand, px_pro_m, ist_map):
    """STARKER ANKER: die byte-exakten MASSKETTEN-FLUCHTEN.

    Der Wand-Gegentest misst die Erkennung gegen die Erkennung (Region gegen
    Wandmaske) — beide koennen gemeinsam falsch liegen, und genau das ist am
    AP.01 passiert. Die Fluchten dagegen kommen aus den BEMASSUNGS-ZAHLEN des
    Planers (massketten.wand_fluchten, byte-exakt gelesen): eine unabhaengige
    Quelle fuer die echten Wandachsen. Liegt die Handarbeit auf den Fluchten
    und unsere Region nicht, ist der Fehler bewiesen bei uns — und der Fix-Weg
    steht zugleich fest (Regionen auf Fluchten rasten).
    """
    fl = erg.get("fluchten") or []
    v_px = [f["px"] for f in fl if f.get("achse") == "v" and f.get("ok")]
    h_px = [f["px"] for f in fl if f.get("achse") == "h" and f.get("ok")]
    if not v_px and not h_px:
        return None, 0
    tol = 0.10 * px_pro_m if px_pro_m else 10.0

    def anteil(poly):
        """Anteil der Umfangslaenge auf einer bestaetigten Flucht."""
        gesamt = treffer = 0.0
        for i in range(len(poly)):
            a, b = poly[i], poly[(i + 1) % len(poly)]
            L = math.hypot(b[0] - a[0], b[1] - a[1])
            if L < 1e-6:
                continue
            senkrecht = abs(b[0] - a[0]) < abs(b[1] - a[1])
            achsen = v_px if senkrecht else h_px
            gesamt += L
            if achsen:
                lage = (a[0] + b[0]) / 2 if senkrecht else (a[1] + b[1]) / 2
                if min(abs(lage - x) for x in achsen) <= tol:
                    treffer += L
        return treffer / gesamt if gesamt else 0.0

    zeilen = []
    for schluessel, v in sorted(raeume_hand.items()):
        r_ist = ist_map.get(schluessel)
        if not r_ist:
            continue
        hand = [(float(p[0]), float(p[1])) for p in v["region_px"]]
        ist = [(float(p[0]), float(p[1])) for p in r_ist["region_px"]]
        zeilen.append((v.get("name", schluessel), anteil(hand), anteil(ist)))
    return zeilen, len(v_px) + len(h_px)

if __name__ == "__main__":
    main()
