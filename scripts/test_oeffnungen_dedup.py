#!/usr/bin/env python3
"""Belegt die robuste Cross-Plan-Dedup von Fenstern/Türen (Toleranz-Clustering
statt fragiler 10cm-Hartbuckets). Zwei Pläne = DASSELBE Gebäude (Einreich +
Polier) → identische Öffnungen müssen GEMERGT, nicht addiert werden.

Lauf: python3 scripts/test_oeffnungen_dedup.py   (Exit 0 = bestanden)
"""
import sys, os, asyncio
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "api"))
import api.extract as ex
ex._MASSEN_OK = ex._MATERIAL_OK = ex._KONSISTENZ_OK = ex._LEGENDE_OK = True

class _R:
    def __init__(s, d): s.data = d

def _mkSB(raum_rows, fenster_rows, tuer_rows, plaene):
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
                        return _R({"raum": raum_rows, "fenster": fenster_rows,
                                   "tuer": tuer_rows}.get(v, []))
                return _R([])
            return _R([])
    class SB:
        def table(s, n): return Q(n)
    return SB()

def _row(plan, bez, raum, b, h, quelle, typ, konf=90):
    daten = {"raum": raum, "quelle": quelle, "konfidenz": konf}
    if b is not None: daten["breite_m"] = b
    if h is not None: daten["hoehe_m"] = h
    return {"plan_id": plan, "bezeichnung": bez, "daten": daten, "typ": typ}

def _run(raum_rows, fenster_rows, tuer_rows, plaene_ids, symbole=None):
    plaene = []
    for pid in plaene_ids:
        log = {"geo": {"geschoss": "EG"}}
        if symbole and pid in symbole:
            log["oeffnungs_symbole"] = symbole[pid]
        plaene.append({"id": pid, "dateiname": pid, "agent_log": log})
    ex.sb = _mkSB(raum_rows, fenster_rows, tuer_rows, plaene)
    return asyncio.run(ex.projekt_massen(ex.ProjektMassenRequest(plan_id=plaene_ids[0])))

fails = []
def check(name, cond, detail=""):
    print(f"  {'✓' if cond else '✗'} {name}" + (f"  — {detail}" if detail and not cond else ""))
    if not cond: fails.append(name)

# Minimal-Räume, damit projekt_massen nicht leer abbricht
RAEUME = [_row("E", "Wohnen", None, None, None, "text", "raum")]
RAEUME[0]["daten"] = {"name": "Wohnen", "flaeche_m2": 30.0, "umfang_m": 24.0, "hoehe_m": 2.7}
RAEUME.append({"plan_id": "E", "bezeichnung": "Bad",
               "daten": {"name": "Bad", "flaeche_m2": 8.0, "umfang_m": 11.0, "hoehe_m": 2.7}, "typ": "raum"})

print("SZENARIO A: dasselbe Fenster aus 2 Plänen (STUK 1.30×1.28 + Vision 1.26×1.30) + maßlos → 1 Fenster")
fenster = [
    _row("E", "F-130x128", "Wohnen", 1.30, 1.28, "text-layer-stuk-fph", "fenster", 95),
    _row("A", "FE_01", "Wohnen", 1.26, 1.30, "vision", "fenster", 75),     # Mess-Rauschen, selbe Öffnung
    _row("A", "FE_x", "Wohnen", None, None, "vision", "fenster", 60),        # maßlos, selbe Öffnung
    _row("E", "F-90x88", "Bad", 0.90, 0.88, "text-layer-stuk-fph", "fenster", 95),
]
res = _run(RAEUME, fenster, [], ["E", "A"])
check("3 roh-Fenster-Funde in Wohnen → 1 (dedupliziert)", res["fenster_count"] == 2,
      f"got {res['fenster_count']} (erwartet 2: Wohnen 1 + Bad 1)")

print("\nSZENARIO B: zwei ECHTE verschiedene Fenster im selben Raum (60cm + 70cm) → bleiben 2")
fenster = [
    _row("E", "F-60", "Wohnen", 0.60, 0.60, "text-layer-stuk-fph", "fenster", 95),
    _row("E", "F-70", "Wohnen", 0.70, 0.60, "text-layer-stuk-fph", "fenster", 95),
]
res = _run(RAEUME, fenster, [], ["E", "A"])
check("60cm + 70cm im selben Raum bleiben getrennt", res["fenster_count"] == 2, f"got {res['fenster_count']}")

print("\nSZENARIO C: STUK füllt Maße in Vision-Lücke (Vision maßlos + STUK bemaßt) → 1 Fenster mit Maßen")
fenster = [
    _row("A", "FE_02", "Bad", None, None, "vision", "fenster", 70),
    _row("E", "F-60x57", "Bad", 0.60, 0.57, "text-layer-stuk-fph", "fenster", 95),
]
res = _run(RAEUME, fenster, [], ["E", "A"])
fe = [f for f in res["fenster"] if (f.get("raum") or "").lower() == "bad"]
check("Bad: 1 Fenster nach Merge", len(fe) == 1, f"got {len(fe)}")
check("Bad-Fenster trägt die STUK-Maße (0.60×0.57)", fe and fe[0].get("breite_m") == 0.60, f"got {fe[0] if fe else None}")

print("\nSZENARIO D: Raum-Varianten über Pläne (WC vs WC1) → dieselbe Tür mergt; Zimmer 1 ≠ Zimmer 2")
tueren = [
    _row("E", "T-80x204", "WC", 0.80, 2.04, "text-layer-stuk-fph", "tuer", 95),
    _row("A", "T_02", "WC1", 0.80, 2.04, "vision", "tuer", 70),       # selbe Tür, Polierplan nennt Raum WC1
    _row("E", "T-80x204", "Zimmer 1", 0.80, 2.04, "text-layer-stuk-fph", "tuer", 95),
    _row("E", "T-80x204", "Zimmer 2", 0.80, 2.04, "text-layer-stuk-fph", "tuer", 95),
]
res = _run(RAEUME, [], tueren, ["E", "A"])
wc = [t for t in res["tueren"] if (t.get("raum") or "").lower().startswith("wc")]
check("WC + WC1 → 1 Tür (Raum-Variante gemergt)", len(wc) == 1, f"got {len(wc)}: {[t.get('raum') for t in wc]}")
zi = [t for t in res["tueren"] if (t.get("raum") or "").lower().startswith("zimmer")]
check("Zimmer 1 + Zimmer 2 bleiben 2 Türen", len(zi) == 2, f"got {len(zi)}")
check("Türen gesamt = 3 (WC + Zimmer1 + Zimmer2)", res["tueren_count"] == 3, f"got {res['tueren_count']}")

print("\nSZENARIO E: Symbol-Zählung kappt Über-Erkennung (4 Türen in Varianten-Räumen → Symbol 2)")
tueren = [
    _row("E", "T-80x204", "Vorraum", 0.80, 2.04, "text-layer-stuk-fph", "tuer", 95),   # STUK — bleibt
    _row("A", "T_01", "Garderobe", 0.90, 2.01, "vision", "tuer", 70),
    _row("A", "T_02", "Diele", 0.90, 2.01, "vision", "tuer", 65),
    _row("A", "T_03", "Entree", 0.85, 2.01, "vision", "tuer", 60),
]
res = _run(RAEUME, [], tueren, ["E", "A"], symbole={"A": {"tueren_gesamt": 2, "konfidenz": 0.8}})
check("Türen auf Symbol-Zahl 2 gekappt", res["tueren_count"] == 2, f"got {res['tueren_count']}")
namen = [t.get("bezeichnung") for t in res["tueren"]]
check("STUK-Tür bleibt beim Kappen erhalten", "T-80x204" in namen, f"got {namen}")
cap = [d for d in (res.get("doppelcheck") or []) if d.get("status") == "gekappt"]
check("Cap im Doppelcheck vermerkt", any(d["key"] == "tueren" for d in cap), f"got {cap}")

print("\nSZENARIO F: niedrige Symbol-Konfidenz → KEIN Cap (No-Op)")
res = _run(RAEUME, [], tueren, ["E", "A"], symbole={"A": {"tueren_gesamt": 2, "konfidenz": 0.4}})
check("bei Konf 0.4 kein Cap (alle 4 bleiben)", res["tueren_count"] == 4, f"got {res['tueren_count']}")

print("\nSZENARIO G: Symbol-Zahl GRÖSSER als erkannt → NIE auffüllen")
res = _run(RAEUME, [], [_row("E", "T-80x204", "Bad", 0.80, 2.04, "text-layer-stuk-fph", "tuer", 95)],
           ["E", "A"], symbole={"A": {"tueren_gesamt": 9, "konfidenz": 0.9}})
check("Symbol 9 > erkannt 1 → bleibt 1 (kein Auffüllen)", res["tueren_count"] == 1, f"got {res['tueren_count']}")

print()
if fails:
    print(f"FEHLER: {len(fails)} Test(s) gescheitert: {fails}")
    sys.exit(1)
print("OK — Öffnungs-Dedup robust.")
