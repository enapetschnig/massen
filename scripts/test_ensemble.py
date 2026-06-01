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

print()
if fails:
    print(f"FEHLER: {len(fails)} Test(s) gescheitert: {fails}")
    sys.exit(1)
print("OK — Reconciliation deterministisch, Modus/Median robust, Konfidenz ehrlich, Anker schlägt.")
