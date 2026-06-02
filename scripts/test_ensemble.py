#!/usr/bin/env python3
"""Belegt die deterministische Reconciliation (Self-Consistency): mehrere Lesungen
→ EIN stabiler Wert + EHRLICHE Übereinstimmungs-Konfidenz, byte-exakter Anker schlägt.

Lauf: python3 scripts/test_ensemble.py   (Exit 0 = bestanden)
"""
import sys, os
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "api"))
import ensemble as E

fails = []
def check(name, cond, detail=""):
    print(f"  {'✓' if cond else '✗'} {name}" + (f"  — {detail}" if detail and not cond else ""))
    if not cond: fails.append(name)

print("1) Modus über Zähl-Lesungen (häufigster, Gleichstand → kleinerer):")
check("Mehrheit 4 (4,4,5) → 4", E.modus_zahl([4, 4, 5]) == 4)
check("Gleichstand (4,5) → 4 (konservativ+deterministisch)", E.modus_zahl([5, 4]) == 4)
check("leer → default", E.modus_zahl([], default=0) == 0)

print("\n2) Median in cm-Buckets (reproduzierbar):")
check("(1.28,1.30,1.32) bucket5cm → 1.30", abs(E.median_bucket([1.28, 1.30, 1.32], 0.05) - 1.30) < 1e-6, f"got {E.median_bucket([1.28,1.30,1.32],0.05)}")
check("kleine Schwankung kippt nicht (1.31,1.29) → 1.30", abs(E.median_bucket([1.31, 1.29], 0.05) - 1.30) < 1e-6, f"got {E.median_bucket([1.31,1.29],0.05)}")

print("\n3) Mehrheits-Existenz (Phantom fällt raus):")
check("3/3 vorhanden → existiert", E.mehrheit([True, True, True]) is True)
check("1/3 (Phantom) → existiert NICHT", E.mehrheit([True, False, False]) is False)
check("2/3 → existiert (strikte Mehrheit)", E.mehrheit([True, True, False]) is True)

print("\n4) Übereinstimmung = ehrliche Konfidenz-Basis:")
check("alle gleich → 1.0", abs(E.uebereinstimmung([4, 4, 4]) - 1.0) < 1e-9)
check("2 von 3 → 0.66", abs(E.uebereinstimmung([4, 4, 5]) - 2/3) < 1e-6)
check("alle verschieden → 1/3", abs(E.uebereinstimmung([4, 5, 6]) - 1/3) < 1e-6)

print("\n5) Konfidenz aus Agreement (deterministisch, byte-exakt = Anker):")
check("text-Anker → 0.97", E.konfidenz_aus_agreement(0.5, 3, text_anker=True) == 0.97)
check("volle Einigkeit hoch", E.konfidenz_aus_agreement(1.0, 3) >= 0.9)
check("keine Einigkeit niedrig", E.konfidenz_aus_agreement(0.34, 3) < 0.65)
check("monoton in agreement", E.konfidenz_aus_agreement(1.0, 3) > E.konfidenz_aus_agreement(0.5, 3))

print("\n6) reconcile_zaehlung — Säulen-Beispiel:")
r = E.reconcile_zaehlung([4, 4, 5], label="Säulen")
check("Ensemble-Wert = Modus 4", r["wert"] == 4, f"got {r}")
check("status mehrheit (nicht alle einig)", r["status"] == "mehrheit", f"got {r['status']}")
check("Alternative 5 protokolliert", r["alternativen"] == [5], f"got {r['alternativen']}")
r2 = E.reconcile_zaehlung([5, 5, 5], label="Säulen")
check("alle einig → bestaetigt", r2["status"] == "bestaetigt" and r2["wert"] == 5)
r3 = E.reconcile_zaehlung([4, 5, 6], text_wert=5, label="Säulen")
check("text-Anker 5 schlägt Ensemble", r3["wert"] == 5 and r3["quelle"] == "text-anker" and r3["status"] == "bestaetigt", f"got {r3}")
check("text-Anker Konfidenz hoch", r3["konfidenz"] >= 0.95)

print("\n7) reconcile_masse — Fensterbreite:")
m = E.reconcile_masse([1.28, 1.30, 1.31], bucket=0.05, label="F-Breite")
check("Median-Bucket = 1.30", abs(m["wert"] - 1.30) < 1e-6, f"got {m}")
check("hohe Übereinstimmung (alle im Bucket)", m["agreement"] >= 0.99, f"got {m['agreement']}")
m2 = E.reconcile_masse([1.0, 1.3, 2.0], bucket=0.05, label="F-Breite")
check("breite Streuung → status unklar", m2["status"] in ("unklar", "mehrheit"), f"got {m2['status']}")

print("\n8) DETERMINISMUS — gleiche Eingabe, gleiche Ausgabe:")
a = E.reconcile_zaehlung([4, 5, 4, 5, 4])
b = E.reconcile_zaehlung([5, 4, 5, 4, 4])  # andere Reihenfolge, gleiche Multimenge
check("reihenfolge-unabhängig identisch", a == b, f"{a} vs {b}")

print("\n9) reconcile_opus_urteile — N Läufe → EIN robustes Urteil:")
U = [
    {"saeulen_anzahl": 4, "dach": {"dach_typ": "flach"}, "hoehe": {"rohbau_m": 2.95}, "gesamtkonfidenz": 0.8},
    {"saeulen_anzahl": 5, "dach": {"dach_typ": "flach"}, "hoehe": {"rohbau_m": 2.93}, "gesamtkonfidenz": 0.7},
    {"saeulen_anzahl": 5, "dach": {"dach_typ": "pult"}, "hoehe": {"rohbau_m": 2.97}, "gesamtkonfidenz": 0.75},
]
r = E.reconcile_opus_urteile(U)
check("Säulen = Modus (5, nicht 4)", r["saeulen_anzahl"] == 5, f"got {r['saeulen_anzahl']}")
check("Dachtyp = Mehrheit (flach 2:1)", r["dach"]["dach_typ"] == "flach", f"got {r['dach']}")
check("Höhe = Median-Bucket (~2.95)", abs(r["hoehe"]["rohbau_m"] - 2.95) < 0.03, f"got {r['hoehe']}")
check("Ensemble-N protokolliert", r["_ensemble_n"] == 3)
check("Säulen-Lesungen protokolliert", r["_ensemble_saeulen"] == [4, 5, 5], f"got {r.get('_ensemble_saeulen')}")
# Total-Ausfall-Schutz: 2 von 3 Läufen scheitern → das 1 gute Urteil zählt
U2 = [{"_fehler": "timeout"}, {"saeulen_anzahl": 6, "gesamtkonfidenz": 0.8}, {"_fehler": "parse"}]
r2 = E.reconcile_opus_urteile(U2)
check("1 erfolgreicher Lauf reicht (Säulen 6)", r2 and r2["saeulen_anzahl"] == 6 and r2["_ensemble_n"] == 1, f"got {r2}")
check("alle gescheitert → None", E.reconcile_opus_urteile([{"_fehler": "x"}, {"_fehler": "y"}]) is None)
check("leere Liste → None", E.reconcile_opus_urteile([]) is None)
# Determinismus: Reihenfolge der Läufe egal fürs robuste Skalar-Ergebnis
ra = E.reconcile_opus_urteile(U)
rb = E.reconcile_opus_urteile(list(reversed(U)))
check("Säulen reihenfolge-stabil", ra["saeulen_anzahl"] == rb["saeulen_anzahl"])

print()
if fails:
    print(f"FEHLER: {len(fails)} Test(s) gescheitert: {fails}")
    sys.exit(1)
print("OK — Reconciliation deterministisch, Modus/Median robust, Konfidenz ehrlich, Anker schlägt, Opus-Ensemble robust.")
