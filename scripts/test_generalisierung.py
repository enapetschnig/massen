#!/usr/bin/env python3
"""Generalisierungs-Test: belegt dass die Pipeline NICHT auf den Angerer-Plan
überangepasst ist, sondern über verschiedene Architekten-Konventionen +
Gebäudetypen robust bleibt. Synthetische Szenarien statt 100 echter Pläne.

Lauf:  python3 scripts/test_generalisierung.py   (Exit 0 = alle bestanden)
"""
import sys, os, asyncio

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "api"))

import api.extract as ex
from legende import parse_legende
ex._MASSEN_OK = ex._MATERIAL_OK = ex._KONSISTENZ_OK = ex._LEGENDE_OK = True

# ── Supabase-Stub ───────────────────────────────────────────────────
class _R:
    def __init__(self, d): self.data = d
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
                    if o == "eq" and c == "id":
                        return _R({"projekt_id": "P"})
                return _R(plaene)
            if s._t == "elemente":
                for o, c, v in s._c:
                    if o == "eq" and c == "typ":
                        return _R(raum_rows if v == "raum" else [])
                return _R([])
            return _R([])
    class SB:
        def table(s, n): return Q(n)
    return SB()

def _run(raum_dicts, plaene_agent_logs):
    """raum_dicts: [(plan_id, raum)]. plaene_agent_logs: {plan_id: agent_log}."""
    rows = [{"plan_id": pid, "bezeichnung": r["name"], "daten": r, "typ": "raum"} for pid, r in raum_dicts]
    plaene = [{"id": pid, "dateiname": pid, "agent_log": log} for pid, log in plaene_agent_logs.items()]
    ex.sb = _mkSB(rows, plaene)
    first = plaene[0]["id"]
    return asyncio.run(ex.projekt_massen(ex.ProjektMassenRequest(plan_id=first)))

fails = []
def check(name, cond, detail=""):
    print(f"  {'✓' if cond else '✗'} {name}" + (f"  — {detail}" if detail and not cond else ""))
    if not cond:
        fails.append(name)

EG_LOG = {"geo": {"geschoss": "EG"}, "aussenkontur_vision": {"umfang_m": 40, "flaeche_m2": 95, "konfidenz": 0.8, "seiten_m": {"N": 12, "W": 8}}}

print("SZENARIO 1: EFH, ungewöhnliche Raumnamen (anderer Architekt)")
rooms = [("E", {"name": n, "flaeche_m2": f, "umfang_m": u, "hoehe_m": 2.6, "bodenbelag": "Parkett"})
         for n, f, u in [("Aufenthaltsraum", 28.0, 22.0), ("Kochnische", 9.0, 12.0),
                          ("Reduit", 4.0, 8.0), ("Ankleide", 6.0, 10.0), ("Galerie", 15.0, 16.0)]]
res = _run(rooms, {"E": EG_LOG})
check("alle 5 ungewöhnlichen Räume behalten", res["raeume_count"] == 5, f"got {res['raeume_count']}")

print("\nSZENARIO 2: MFH — 3 TOPs mit gleichem Raumnamen (dürfen NICHT gemergt/gefiltert werden)")
rooms = []
for top in ("TOP 1", "TOP 2", "TOP 3"):
    for n, f, u in [("Wohnküche", 26.0, 21.0), ("Bad", 6.0, 10.0), ("Zimmer", 14.0, 15.0)]:
        rooms.append(("E", {"name": n, "flaeche_m2": f, "umfang_m": u, "hoehe_m": 2.5, "bodenbelag": "Fliesen", "wohnung": top}))
res = _run(rooms, {"E": EG_LOG})
check("MFH: alle 9 Räume (3 TOPs × 3) behalten", res["raeume_count"] == 9, f"got {res['raeume_count']}")
check("MFH: keine fälschliche Einheit-Ausschließung", not res.get("ausgeschlossene_einheiten"),
      f"ausgeschlossen: {res.get('ausgeschlossene_einheiten')}")

print("\nSZENARIO 3: Plan OHNE Legende (degradiert sauber, niedrigere Konfidenz)")
rooms = [("E", {"name": n, "flaeche_m2": f, "umfang_m": u, "hoehe_m": 2.7})
         for n, f, u in [("Wohnzimmer", 30, 24), ("Bad", 8, 11), ("Zimmer", 14, 15)]]
res = _run(rooms, {"E": {"geo": {"geschoss": "EG"}}})  # keine legende, keine geometrie
ml = res.get("materialliste", {})
check("ohne Legende: Materialliste trotzdem erzeugt", bool(ml.get("bauteile")))
hlz = [p for p in ml.get("bauteile", {}).get("Mauerwerk EG", []) if "HLZ" in p["material"]]
check("ohne Legende: HLZ-Konfidenz ehrlich < 80%", all(p["konfidenz"] < 0.8 for p in hlz) if hlz else True,
      f"konfs {[p['konfidenz'] for p in hlz]}")

print("\nSZENARIO 4: Legende mit anderem Hersteller (Porotherm) + Code AW-1")
spans = []
def _sp(t, x, y): spans.append({"text": t, "cx": x, "cy": y, "size": 8})
_sp("AW-1", 100, 100); _sp("Porotherm", 130, 100); _sp("38,0 cm", 200, 100)
_sp("IW-1", 100, 130); _sp("Porotherm", 130, 130); _sp("25,0 cm", 200, 130)
_sp("D-1", 100, 160); _sp("Stahlbeton", 130, 160); _sp("22,0 cm", 200, 160)
leg = parse_legende(spans)
check("Porotherm AW-1=38cm erkannt", leg["wand_typen"].get("AW1", {}).get("dicke_cm") == 38.0,
      f"got {leg['wand_typen']}")
check("Decke 22cm aus D-1", leg["decke_cm"] == 22.0, f"got {leg['decke_cm']}")

print("\nSZENARIO 5: zweite Einheit W02 (anderes Geschoss) WIRD ausgeschlossen")
rooms = [("E", {"name": n, "flaeche_m2": f, "umfang_m": u, "hoehe_m": 2.95, "wohnung": "Haus"})
         for n, f, u in [("Zimmer 1", 12, 14), ("Bad", 8, 11), ("Wohnen", 30, 24), ("Flur", 10, 13), ("WC", 2, 6)]]
rooms += [("A", {"name": n, "flaeche_m2": f, "umfang_m": u, "hoehe_m": 2.55, "wohnung": "W02"})
          for n, f, u in [("Zimmer 5", 11, 14), ("Zimmer 6", 12, 15)]]
res = _run(rooms, {"E": EG_LOG, "A": {"geo": {"geschoss": "EG"}}})
check("W02 (eigener Code + 1 Plan + andere Höhe) ausgeschlossen", len(res.get("ausgeschlossene_einheiten") or []) == 1,
      f"got {res.get('ausgeschlossene_einheiten')}")
check("W02-Räume trotzdem in Anzeige sichtbar", res["raeume_count"] == 7, f"got {res['raeume_count']}")

print("\nSZENARIO 6: echte zweite EG-Einheit (gleiche Höhe, in BEIDEN Plänen) NICHT ausschließen")
base = [("Zimmer 1", 12, 14), ("Bad", 8, 11), ("Wohnen", 30, 24), ("Flur", 10, 13)]
rooms = [("E", {"name": n, "flaeche_m2": f, "umfang_m": u, "hoehe_m": 2.7, "wohnung": "Haus"}) for n, f, u in base]
rooms += [("A", {"name": n, "flaeche_m2": f, "umfang_m": u, "hoehe_m": 2.7, "wohnung": "Haus"}) for n, f, u in base]
# Einliegerwohnung: gleiche Höhe 2.7, in BEIDEN Plänen (cross-validiert)
ein = [("Gästezimmer", 14, 15), ("Dusche", 4, 8)]
rooms += [("E", {"name": n, "flaeche_m2": f, "umfang_m": u, "hoehe_m": 2.7, "wohnung": "Einlieger"}) for n, f, u in ein]
rooms += [("A", {"name": n, "flaeche_m2": f, "umfang_m": u, "hoehe_m": 2.7, "wohnung": "Einlieger"}) for n, f, u in ein]
res = _run(rooms, {"E": EG_LOG, "A": {"geo": {"geschoss": "EG"}}})
check("Einliegerwohnung (gleiche Höhe, 2 Pläne) NICHT ausgeschlossen", not (res.get("ausgeschlossene_einheiten") or []),
      f"got {res.get('ausgeschlossene_einheiten')}")

print("\nSZENARIO 7: Vision-erfundene Räume (kein Text-Beleg) werden verworfen")
# 6 echte Text-Räume + 2 Vision-Halluzinationen ohne Text-Beleg (wie Zimmer3/4)
rooms = [("E", {"name": n, "flaeche_m2": f, "umfang_m": u, "hoehe_m": 2.7, "bodenbelag": "Fliesen", "_source": "text", "wohnung": "Haus"})
         for n, f, u in [("Wohnen", 30, 24), ("Bad", 8, 11), ("Zimmer", 14, 15), ("Flur", 10, 13), ("WC", 2, 6), ("Speis", 4, 8)]]
rooms += [("A", {"name": n, "flaeche_m2": f, "umfang_m": u, "hoehe_m": 2.55, "_source": "vision", "wohnung": "W05"})
          for n, f, u in [("Zimmer 7", 11, 14), ("Zimmer 8", 12, 15)]]
res = _run(rooms, {"E": EG_LOG, "A": {"geo": {"geschoss": "EG"}}})
hallu_namen = [h["name"] for h in res.get("halluzinationen") or []]
check("Vision-Räume ohne Text-Beleg verworfen", "Zimmer 7" in hallu_namen and "Zimmer 8" in hallu_namen,
      f"hallu: {hallu_namen}")
check("nur die 6 echten Text-Räume in Berechnung", res["raeume_count"] == 6, f"got {res['raeume_count']}")

print("\nSZENARIO 8: derselbe Raum unterschiedlich benannt über 2 Pläne → F/U/H zusammenführen")
# Einreichplan: 'Wohnraum Küche' mit F+U (keine H). Polierplan: 'Küche' mit H.
rooms = [("E", {"name": "Wohnraum Küche", "flaeche_m2": 31.12, "umfang_m": 25.95, "wohnung": "Haus", "_source": "text"})]
rooms += [("A", {"name": "Küche", "hoehe_m": 2.95, "wohnung": "Haus", "_source": "text"})]
# zwei klar verschiedene Zimmer dürfen NICHT verschmelzen
rooms += [("E", {"name": "Zimmer 1", "flaeche_m2": 12.0, "umfang_m": 14.0, "hoehe_m": 2.95, "wohnung": "Haus", "_source": "text"})]
rooms += [("E", {"name": "Zimmer 2", "flaeche_m2": 14.0, "umfang_m": 15.0, "hoehe_m": 2.95, "wohnung": "Haus", "_source": "text"})]
# gleiches Kopf-Nomen, anderer Qualifizierer (keine Teilmenge) → NICHT mergen
rooms += [("E", {"name": "Großes Bad", "flaeche_m2": 18.0, "umfang_m": 17.0, "hoehe_m": 2.95, "wohnung": "Haus", "_source": "text"})]
rooms += [("E", {"name": "Kleines Bad", "flaeche_m2": 9.0, "umfang_m": 12.0, "hoehe_m": 2.95, "wohnung": "Haus", "_source": "text"})]
res = _run(rooms, {"E": EG_LOG, "A": {"geo": {"geschoss": "EG"}}})
kueche = [r for r in res["raeume"] if "üche" in (r.get("name") or "")]
check("Wohnraum Küche + Küche → EIN Raum", len(kueche) == 1, f"got {[r.get('name') for r in kueche]}")
check("Küche-Raum hat F+U+H zusammengeführt",
      kueche and kueche[0].get("flaeche_m2") and kueche[0].get("umfang_m") and kueche[0].get("hoehe_m"),
      f"got {kueche[0] if kueche else None}")
zimmer1 = [r for r in res["raeume"] if (r.get("name") or "").lower() in ("zimmer 1", "zimmer 2")]
check("Zimmer 1 + Zimmer 2 bleiben getrennt (Ziffern-Gate)", len(zimmer1) == 2, f"got {[r.get('name') for r in zimmer1]}")
baeder = [r for r in res["raeume"] if (r.get("name") or "").lower().endswith("bad")]
check("Großes/Kleines Bad bleiben getrennt (kein Teilmengen-Match)", len(baeder) == 2, f"got {[r.get('name') for r in baeder]}")

print("\nSZENARIO 9: geometrisch unmöglicher Umfang (U < 4·√F, Stempel-Cross-Talk) → U verworfen")
rooms = [("E", {"name": "Flur", "flaeche_m2": 15.84, "umfang_m": 11.90, "hoehe_m": 2.7, "wohnung": "Haus", "_source": "text"}),
         ("E", {"name": "Wohnen", "flaeche_m2": 30.0, "umfang_m": 24.0, "hoehe_m": 2.7, "wohnung": "Haus", "_source": "text"}),
         ("E", {"name": "Bad", "flaeche_m2": 8.0, "umfang_m": 11.0, "hoehe_m": 2.7, "wohnung": "Haus", "_source": "text"}),
         ("E", {"name": "WC", "flaeche_m2": 2.0, "umfang_m": 6.0, "hoehe_m": 2.7, "wohnung": "Haus", "_source": "text"}),
         ("E", {"name": "Speis", "flaeche_m2": 4.0, "umfang_m": 8.0, "hoehe_m": 2.7, "wohnung": "Haus", "_source": "text"})]
res = _run(rooms, {"E": EG_LOG})
flur = [r for r in res["raeume"] if r.get("name") == "Flur"]
check("Flur mit unmöglichem U (11,9 < 15,9) → U verworfen", flur and not flur[0].get("umfang_m"),
      f"got umfang_m={flur[0].get('umfang_m') if flur else None}")
wohnen = [r for r in res["raeume"] if r.get("name") == "Wohnen"]
check("Wohnen mit plausiblem U (24 ≥ 21,9) → U behalten", wohnen and wohnen[0].get("umfang_m") == 24.0,
      f"got {wohnen[0].get('umfang_m') if wohnen else None}")

print("\nSZENARIO 10: angebaute überdachte Flächen → Slab-Kante aus Fläche geschätzt (>Hülle)")
rooms = [("E", {"name": n, "flaeche_m2": f, "umfang_m": u, "hoehe_m": 2.95, "wohnung": "Haus", "_source": "text"})
         for n, f, u in [("Wohnen", 31, 25), ("Zimmer 1", 10.5, 13), ("Bad", 8.7, 11), ("Flur", 15.8, 22), ("WC", 1.8, 5.6)]]
rooms += [("E", {"name": "Terrasse überdacht", "flaeche_m2": 60.0, "umfang_m": 37.0, "wohnung": "Haus", "_source": "text"}),
          ("E", {"name": "Parkplatz überdacht", "flaeche_m2": 36.0, "umfang_m": 24.0, "wohnung": "Haus", "_source": "text"})]
MK_LOG = {"geo": {"geschoss": "EG"},
          "massketten_bbox": {"breite_m": 12.48, "tiefe_m": 10.75, "umfang_m": 46.46, "flaeche_m2": 134.16, "h_rep": 6, "v_rep": 4}}
res = _run(rooms, {"E": MK_LOG})
gem = res.get("gemessen") or {}
gq = gem.get("geometrie_qualitaet") or {}
check("Hülle = byte-exakte Maßkette (46,46)", gem.get("aussenumfang_m") == 46.46, f"got {gem.get('aussenumfang_m')}")
check("Fundamentkante aus überdachten Flächen geschätzt (> Hülle)",
      gem.get("fundament_umfang_m") and gem["fundament_umfang_m"] > gem.get("aussenumfang_m", 0) + 5,
      f"got {gem.get('fundament_umfang_m')}")
check("Fundamentkante ehrlich als unsicher geflaggt", gq.get("fundament_unsicher") is True,
      f"got {gq.get('fundament_unsicher')}")

print()
if fails:
    print(f"FEHLER: {len(fails)} Generalisierungs-Test(s) gescheitert: {fails}")
    sys.exit(1)
print("OK — alle Generalisierungs-Szenarien bestanden.")
