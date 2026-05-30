#!/usr/bin/env python3
"""Belegt die Schnitt-/Ansichts-Lesung: Säulen, Geschoss-Höhe, Dachtyp aus den
Schnitten/Ansichten des Einreichplans fließen in Baudaten + Materialliste.
(Der Vision-Call selbst läuft nur in Prod; hier wird die Konsum-Logik in
projekt_massen geprüft, indem agent_log.schnitt_vision vorgegeben wird.)

Lauf: python3 scripts/test_schnitt.py   (Exit 0 = bestanden)
"""
import sys, os, asyncio
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "api")); sys.path.insert(0, ROOT)
import api.extract as ex
ex._MASSEN_OK = ex._MATERIAL_OK = ex._KONSISTENZ_OK = ex._LEGENDE_OK = True

class _R:
    def __init__(s, d): s.data = d
def _mkSB(raum_rows, plaene):
    class Q:
        def __init__(s, t, c=None): s._t = t; s._c = c or []
        def select(s, *a, **k): return s
        def eq(s, c, v): return Q(s._t, s._c + [("eq", c, v)])
        def in_(s, c, v): return Q(s._t, s._c + [("in", c, v)])
        def single(s): return s
        def execute(s):
            if s._t == "plaene":
                for o, c, v in s._c:
                    if o == "eq" and c == "id": return _R({"projekt_id": "P"})
                return _R(plaene)
            if s._t == "elemente":
                for o, c, v in s._c:
                    if o == "eq" and c == "typ": return _R(raum_rows if v == "raum" else [])
                return _R([])
            return _R([])
    class SB:
        def table(s, n): return Q(n)
    return SB()

def _run(raum_dicts, logs):
    rows = [{"plan_id": pid, "bezeichnung": r["name"], "daten": r, "typ": "raum"} for pid, r in raum_dicts]
    plaene = [{"id": pid, "dateiname": pid, "agent_log": log} for pid, log in logs.items()]
    ex.sb = _mkSB(rows, plaene)
    return asyncio.run(ex.projekt_massen(ex.ProjektMassenRequest(plan_id=plaene[0]["id"])))

fails = []
def check(name, cond, detail=""):
    print(f"  {'✓' if cond else '✗'} {name}" + (f"  — {detail}" if detail and not cond else ""))
    if not cond: fails.append(name)

ROOMS = [("E", {"name": n, "flaeche_m2": f, "umfang_m": u, "hoehe_m": 2.70, "bodenbelag": "Fliesen", "_source": "text"})
         for n, f, u in [("Wohnen", 30, 24), ("Bad", 8, 11), ("Zimmer", 14, 15), ("Flur", 10, 13), ("WC", 2, 6)]]

SCHNITT = {"geschosshoehe_rohbau_m": 2.95, "dachtyp": "flach", "attika_hoehe_m": 0.4,
           "saeulen_anzahl": 2, "konfidenz": 0.75, "quelle": "Schnitt A-A"}
LOG = {"geo": {"geschoss": "EG"}, "schnitt_vision": SCHNITT,
       "aussenkontur_vision": {"umfang_m": 40, "flaeche_m2": 95, "konfidenz": 0.8, "seiten_m": {"N": 12, "W": 8}}}

print("SZENARIO: Schnitt liefert Geschoss-Höhe 2,95, Flachdach, 2 Säulen")
res = _run(ROOMS, {"E": LOG})
check("Säulen aus Schnitt erkannt (=2)", res.get("saeulen_erkannt") == 2, f"got {res.get('saeulen_erkannt')}")
bd = res.get("baudaten") or {}
check("Geschoss-Höhe aus Schnitt (2,95)", abs((bd.get("geschosshoehe_m") or 0) - 2.95) < 0.01, f"got {bd.get('geschosshoehe_m')}")
check("Geschoss-Höhe-Quelle = schnitt", (bd.get("_quellen") or {}).get("geschosshoehe_m") == "schnitt",
      f"got {(bd.get('_quellen') or {}).get('geschosshoehe_m')}")
ml = res.get("materialliste") or {}
saeulen = ml.get("bauteile", {}).get("Säulen", [])
check("Materialliste enthält Säulen-Block", len(saeulen) > 0, f"got {len(saeulen)} Positionen")
attika = ml.get("bauteile", {}).get("Attika", [])
check("Flachdach aus Schnitt → Attika aktiv", len(attika) > 0, f"got {len(attika)} Positionen")

print("\nSZENARIO: kein Schnitt auf dem Blatt → keine Säulen erfunden")
res2 = _run(ROOMS, {"E": {"geo": {"geschoss": "EG"}, "schnitt_vision": {"kein_schnitt": True},
                          "aussenkontur_vision": LOG["aussenkontur_vision"]}})
check("ohne Schnitt: saeulen_erkannt None", not res2.get("saeulen_erkannt"), f"got {res2.get('saeulen_erkannt')}")

print("\nSZENARIO: DOPPELCHECK — Legende & Schnitt stimmen überein (Decke 20cm) → bestätigt")
LEG = {"wand_typen": {"AW1": {"dicke_cm": 50, "art": "aussen"}, "IW1": {"dicke_cm": 25, "art": "innen"}},
       "decke_cm": 20.0, "bodenplatte_cm": 25.0, "estrich_cm": 7.0, "konfidenz": 0.9, "dach_typ": "flach"}
SCH = {"geschosshoehe_rohbau_m": 2.95, "dachtyp": "flach",
       "schichten_cm": {"decke": 20, "bodenplatte": 25, "estrich": 7}, "konfidenz": 0.75}
res3 = _run(ROOMS, {"E": dict(LOG, legende=LEG, schnitt_vision=SCH)})
dc = res3.get("doppelcheck") or []
best = [d for d in dc if d["status"] == "bestätigt"]
check("Decke doppelt bestätigt (Legende 20 = Schnitt 20)",
      any(d["key"] == "decke_cm" and d["status"] == "bestätigt" for d in dc), f"got {dc}")
check("Dachtyp flach doppelt bestätigt",
      any(d["key"] == "dach_typ" and d["status"] == "bestätigt" for d in dc), f"got {[d['key'] for d in best]}")

print("\nSZENARIO: DOPPELCHECK — Widerspruch (Legende Decke 20 vs Schnitt 25) → Warnung")
SCH_W = dict(SCH, schichten_cm={"decke": 25, "bodenplatte": 25})
res4 = _run(ROOMS, {"E": dict(LOG, legende=LEG, schnitt_vision=SCH_W)})
dc4 = res4.get("doppelcheck") or []
check("Decke-Widerspruch erkannt (20 vs 25)",
      any(d["key"] == "decke_cm" and d["status"] == "widerspruch" for d in dc4), f"got {dc4}")

print()
if fails:
    print(f"FEHLER: {len(fails)} Test(s) gescheitert: {fails}")
    sys.exit(1)
print("OK — Schnitt-/Ansichts-Lesung korrekt verarbeitet.")
