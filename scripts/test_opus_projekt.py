#!/usr/bin/env python3
"""Belegt den PROJEKT-WEITEN Opus-Pass: statt N× pro Plan läuft Opus GENAU 1×
in projekt_massen — auf dem Blatt mit dem besten Schnitt, gegroundet an den
gemergten Fakten. Der echte API-Call (_run_opus_pass) wird gemockt; geprüft wird
die Orchestrierung + der Konsum (Garage → Mauerwerks-Hülle, opus_status, Quelle).

Lauf: python3 scripts/test_opus_projekt.py   (Exit 0 = bestanden)
"""
import sys, os, asyncio
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "api")); sys.path.insert(0, ROOT)
import api.extract as ex
ex._MASSEN_OK = ex._MATERIAL_OK = ex._KONSISTENZ_OK = ex._LEGENDE_OK = True

class _R:
    def __init__(s, d): s.data = d

def _mkSB(raum_rows, plaene, api_key="test-key", pdf=b"%PDF-fake"):
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
            if s._t == "app_config":
                return _R([{"value": api_key}] if api_key else [])
            return _R([])
    class Storage:
        def from_(s, b): return s
        def download(s, path): return pdf
    class SB:
        storage = Storage()
        def table(s, n): return Q(n)
    return SB()

def _run(raum_dicts, logs):
    rows = [{"plan_id": pid, "bezeichnung": r["name"], "daten": r, "typ": "raum"} for pid, r in raum_dicts]
    plaene = [{"id": pid, "dateiname": pid, "agent_log": log,
               "storage_path": f"proj/{pid}.pdf"} for pid, log in logs.items()]
    ex.sb = _mkSB(rows, plaene)
    return asyncio.run(ex.projekt_massen(ex.ProjektMassenRequest(plan_id=plaene[0]["id"])))

fails = []
def check(name, cond, detail=""):
    print(f"  {'✓' if cond else '✗'} {name}" + (f"  — {detail}" if detail and not cond else ""))
    if not cond: fails.append(name)

ROOMS = [("E", {"name": n, "flaeche_m2": f, "umfang_m": u, "hoehe_m": 2.70, "bodenbelag": "Fliesen", "_source": "text"})
         for n, f, u in [("Wohnen", 30, 24), ("Bad", 8, 11), ("Zimmer", 14, 15), ("Flur", 10, 13), ("WC", 2, 6)]]
AUSSEN = {"umfang_m": 40, "flaeche_m2": 95, "konfidenz": 0.8, "seiten_m": {"N": 12, "W": 8}}

# Der gemockte Opus-Call zählt seine Aufrufe + liefert eine geschlossene Garage.
_calls = {"n": 0, "fakten": None}
def _fake_opus(pdf_bytes, fakten, api_key):
    _calls["n"] += 1
    _calls["fakten"] = fakten
    return {
        "ueberdachte_bereiche": [
            {"name": "Parkplatz überdacht", "geschlossen_typ": "gemauert", "auf_slab": True,
             "mauerwerk_umfang_zusatz_m": 12.0, "fundament_umfang_zusatz_m": 12.0,
             "konfidenz": 0.85, "evidenz": "Schnitt: HLZ-Wände + Tor"}],
        "hoehe": {"rohbau_m": 2.95, "konfidenz": 0.8}, "dach": {"dach_typ": "flach", "konfidenz": 0.8},
        "saeulen_anzahl": 0, "gesamtkonfidenz": 0.82,
    }
ex._run_opus_pass = _fake_opus

print("SZENARIO 1: Einreichplan (mit Schnitt) + Polierplan (ohne) → Opus läuft 1×")
_calls["n"] = 0
LOG_EIN = {"geo": {"geschoss": "EG"}, "aussenkontur_vision": AUSSEN,
           "schnitt_vision": {"geschosshoehe_rohbau_m": 2.95, "dachtyp": "flach", "konfidenz": 0.8},
           "massketten_bbox": {"umfang_m": 46.46, "flaeche_m2": 134, "breite_m": 12.48, "tiefe_m": 10.75}}
LOG_POLIER = {"geo": {"geschoss": "EG"}, "aussenkontur_vision": AUSSEN,
              "schnitt_vision": {"kein_schnitt": True}}
res = _run(ROOMS, {"E": LOG_EIN, "P": LOG_POLIER})
check("Opus genau 1× aufgerufen (nicht pro Plan)", _calls["n"] == 1, f"got {_calls['n']}")
check("opus_status = ok", res.get("opus_status") == "ok", f"got {res.get('opus_status')}")
check("opus_quelle_plan = Einreichplan (bester Schnitt)", res.get("opus_quelle_plan") == "E", f"got {res.get('opus_quelle_plan')}")
check("Opus-Urteil in Response", bool(res.get("opus_bauingenieur")), f"got {res.get('opus_bauingenieur')}")
gq = (res.get("gemessen") or {}).get("geometrie_qualitaet") or {}
check("Garage in die Mauerwerks-Hülle übernommen", "Parkplatz überdacht" in (gq.get("opus_garage") or []), f"got {gq.get('opus_garage')}")
check("Opus-Fakten gegroundet an Maßketten-Hülle",
      (_calls["fakten"] or {}).get("text_layer_massketten_huelle", {}).get("umfang_m") == 46.46,
      f"got {(_calls['fakten'] or {}).get('text_layer_massketten_huelle')}")

print("\nSZENARIO 2: kein Plan mit Schnitt → Opus läuft NICHT (kein Mehrwert)")
_calls["n"] = 0
res2 = _run(ROOMS, {"E": LOG_POLIER, "P": LOG_POLIER})
check("Opus NICHT aufgerufen", _calls["n"] == 0, f"got {_calls['n']}")
check("opus_status = aus", res2.get("opus_status") == "aus", f"got {res2.get('opus_status')}")

print("\nSZENARIO 3: Pro-Plan-Urteil schon da (OPUS_PER_PLAN) → kein zweiter Call")
_calls["n"] = 0
LOG_MIT_OPUS = dict(LOG_EIN, opus_bauingenieur={
    "ueberdachte_bereiche": [], "hoehe": {"rohbau_m": 2.8, "konfidenz": 0.8},
    "dach": {"dach_typ": "flach", "konfidenz": 0.8}, "saeulen_anzahl": 0, "gesamtkonfidenz": 0.8})
res3 = _run(ROOMS, {"E": LOG_MIT_OPUS})
check("Opus NICHT erneut aufgerufen (best_opus schon gesetzt)", _calls["n"] == 0, f"got {_calls['n']}")
check("opus_status = ok (aus Pro-Plan-Urteil)", res3.get("opus_status") == "ok", f"got {res3.get('opus_status')}")

print("\nSZENARIO 4: Opus-API-Fehler → fallback-sicher, Materialliste unberührt")
_calls["n"] = 0
def _fail_opus(pdf_bytes, fakten, api_key):
    _calls["n"] += 1
    return {"_fehler": "timeout", "_quelle": "fallback"}
ex._run_opus_pass = _fail_opus
res4 = _run(ROOMS, {"E": LOG_EIN, "P": LOG_POLIER})
check("Opus-Fehler → opus_status = fehler", res4.get("opus_status") == "fehler", f"got {res4.get('opus_status')}")
check("Materialliste trotzdem berechnet", bool(res4.get("materialliste")), "fehlt")
check("kein Garage-Zusatz bei Fehler", not ((res4.get("gemessen") or {}).get("geometrie_qualitaet") or {}).get("opus_garage"))

print()
if fails:
    print(f"FEHLER: {len(fails)} Test(s) gescheitert: {fails}")
    sys.exit(1)
print("OK — Opus läuft projekt-weit 1×, gegroundet, fallback-sicher.")
