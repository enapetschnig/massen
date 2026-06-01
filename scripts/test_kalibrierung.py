#!/usr/bin/env python3
"""Belegt die Selbst-Kalibrierung (Moat): aus hochgeladenen Polier-Soll-Listen
lernt das System firmenspezifische Faktoren — mit HARTEN Überanpassungs-Guards
(nie aus 1 Liste, IQR-Filter, Klemmung) und sauberer Auflösungs-Reihenfolge
(User-Override > Firma > Global > Default). Byte-exakte Werte bleiben unangetastet.

Lauf: python3 scripts/test_kalibrierung.py   (Exit 0 = bestanden)
"""
import sys, os
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "api"))
import kalibrierung as kal
from materialliste import build_materialliste, f, DEFAULTS

fails = []
def check(name, cond, detail=""):
    print(f"  {'✓' if cond else '✗'} {name}" + (f"  — {detail}" if detail and not cond else ""))
    if not cond: fails.append(name)

print("1) Soll-Liste parsen (CSV + Freitext + deutsche Kommazahlen):")
csv = """# Materialliste Polier
Bodenplatte Beton C25/30;48,5;m³
Frostschürze XPS-SF;62,0;lfm
Außenwand HLZ 50;145,8;m²"""
p = kal.parse_soll_liste(csv)
check("3 CSV-Positionen geparst", len(p) == 3, f"got {len(p)}")
check("deutsche Kommazahl 48,5 → 48.5", any(abs(x["menge"] - 48.5) < 0.01 for x in p), f"got {p}")
frei = "Decke Beton ........... 1.234,56 m³\nKamin   2 Stk"
pf = kal.parse_soll_liste(frei)
check("Freitext Tausender-Punkt 1.234,56 → 1234.56", any(abs(x["menge"] - 1234.56) < 0.01 for x in pf), f"got {pf}")

# ALTERNIERENDES PDF-Layout (Bezeichnung-Zeile → Mengen-Zeile getrennt) — das reale
# Format, in dem ein Polier-PDF extrahiert wird. War vorher unlesbar (Moat-Bug).
pdf_alt = """Mauerwek EG:
HLZ 50cm H.I. Plan
48 Paletten
HLZ 38cm H.I. Plan
4 Paletten
HLZ 25cm Plan
7 Paletten
Noppenfolie 1m
75 lfm.
KV-Eco 25
10 Paletten"""
pa = kal.parse_soll_liste(pdf_alt)
pam = {p["bezeichnung"]: (p["menge"], p["einheit"]) for p in pa}
check("alternierend: HLZ 50cm → 48 Paletten", pam.get("HLZ 50cm H.I. Plan", (0,))[0] == 48, f"got {pam}")
check("alternierend: HLZ 38cm erkannt (war komplett verloren)", "HLZ 38cm H.I. Plan" in pam, f"got {list(pam)}")
check("alternierend: 'Noppenfolie 1m' NICHT als Menge 1 fehlgelesen → 75 lfm",
      pam.get("Noppenfolie 1m", (0,))[0] == 75, f"got {pam.get('Noppenfolie 1m')}")
check("alternierend: 'KV-Eco 25' (Name endet auf Zahl) → 10 Paletten, nicht 25",
      pam.get("KV-Eco 25", (0,))[0] == 10, f"got {pam.get('KV-Eco 25')}")
check("alternierend: HLZ-Verteilung lernt 38cm-Bucket",
      (kal.hlz_verteilung_aus_soll(pa) or {}).get("wand_anteil_38cm", 0) > 0,
      f"got {kal.hlz_verteilung_aus_soll(pa)}")

print("\n2) Belege aus Ist↔Soll-Vergleich (ratio = soll/ist):")
ist = {"Bodenplatte": [{"material": "Beton C25/30", "menge": 40.0}],
       "Frostschürze": [{"material": "XPS-SF G30", "menge": 50.0}],
       "Mauerwerk EG": [{"material": "HLZ 50 Außenwand", "menge": 120.0}]}
soll = [{"bezeichnung": "Bodenplatte Beton", "menge": 44.0},   # 44/40 = 1.10
        {"bezeichnung": "Frostschürze XPS", "menge": 60.0},     # 60/50 = 1.20
        {"bezeichnung": "Außenwand HLZ 50", "menge": 132.0}]     # 132/120 = 1.10
belege = kal.belege_aus_vergleich(ist, soll)
bm = {b["faktor"]: b["ratio"] for b in belege}
check("Bodenplatte ratio 1.10", abs(bm.get("bodenplatte_aufschlag", 0) - 1.10) < 0.01, f"got {bm}")
check("Frostschürze ratio 1.20", abs(bm.get("frostgraben_aufschlag", 0) - 1.20) < 0.01, f"got {bm}")
check("Außenumfang ratio 1.10", abs(bm.get("aussenumfang_aufschlag", 0) - 1.10) < 0.01, f"got {bm}")

print("\n3) GUARD: nie aus EINER Liste lernen (min_belege=2):")
eine = {"frostgraben_aufschlag": [1.20]}
check("1 Beleg → kein gelernter Faktor", kal.lerne_faktoren(eine) == {}, f"got {kal.lerne_faktoren(eine)}")
zwei = {"frostgraben_aufschlag": [1.20, 1.18]}
gelernt = kal.lerne_faktoren(zwei)
check("2 Belege → Faktor gelernt", "frostgraben_aufschlag" in gelernt, f"got {gelernt}")
# default 1.15 × median(1.19) ≈ 1.3685
check("gelernter Wert = default × median(ratio)",
      abs(gelernt["frostgraben_aufschlag"]["wert"] - round(1.15 * 1.19, 4)) < 0.001, f"got {gelernt}")
check("n_belege protokolliert", gelernt["frostgraben_aufschlag"]["n_belege"] == 2)

print("\n4) GUARD: Ausreißer-Liste verschiebt den Faktor NICHT (IQR + Median):")
mit_ausreisser = {"aussenumfang_aufschlag": [1.10, 1.12, 1.11, 1.10, 1.60]}  # 1.60 = Ausreißer
g2 = kal.lerne_faktoren(mit_ausreisser)
# Median der gefilterten ~1.11 → 1.55×1.11 ≈ 1.72; der 1.60-Ausreißer zieht NICHT
check("Median statt Mittel → Ausreißer ohne Wirkung",
      abs(g2["aussenumfang_aufschlag"]["ratio_median"] - 1.11) < 0.02, f"got {g2}")

print("\n5) GUARD: Klemmung — eine absurde Liste kann nicht entgleisen:")
# ratio wird schon beim Beleg auf [0.6,1.6] geklemmt
ist2 = {"Bodenplatte": [{"material": "Beton", "menge": 10.0}]}
soll2 = [{"bezeichnung": "Bodenplatte Beton", "menge": 1000.0}]  # ratio 100 → geklemmt 1.6
b2 = kal.belege_aus_vergleich(ist2, soll2)
check("absurde ratio auf 1.6 geklemmt", b2 and b2[0]["ratio"] == 1.6, f"got {b2}")
g3 = kal.lerne_faktoren({"bodenplatte_aufschlag": [1.6, 1.6]})
check("gelernter Faktor im Sanity-Band [0.5,2.5]", 0.5 <= g3["bodenplatte_aufschlag"]["wert"] <= 2.5)

print("\n6) Auflösung: Firma schlägt Global, beides flach:")
glob = {"frostgraben_aufschlag": {"wert": 1.25}, "decke_aufschlag": {"wert": 1.05}}
firma = {"frostgraben_aufschlag": {"wert": 1.40}}
res = kal.resolve_kalibrierung(firma, glob)
check("Firma-Wert schlägt Global", res["frostgraben_aufschlag"] == 1.40, f"got {res}")
check("Global-Wert bleibt, wo Firma nichts hat", res["decke_aufschlag"] == 1.05, f"got {res}")

print("\n7) Einweben in build_materialliste — Reihenfolge Override > Kalibrierung > Default:")
ROOMS = [{"name": "Wohnen", "flaeche_m2": 40.0, "umfang_m": 26.0, "hoehe_m": 2.7, "bodenbelag": "Fliesen"}]
BAUD = {"aussenwand_cm": 50, "innenwand_tragend_cm": 25, "innenwand_nichttragend_cm": 12,
        "decke_cm": 20, "bodenplatte_cm": 25, "geschosshoehe_m": 2.7}
ml_base = build_materialliste(ROOMS, [], BAUD)
ml_kal = build_materialliste(ROOMS, [], BAUD, kalibrierung={"bodenplatte_aufschlag": 1.30})
a_base = ml_base["annahmen"]["bodenplatte_aufschlag"]
a_kal = ml_kal["annahmen"]["bodenplatte_aufschlag"]
check("Kalibrierung ändert den Faktor (1.15→1.30)", abs(a_base - 1.15) < 0.01 and abs(a_kal - 1.30) < 0.01, f"base={a_base} kal={a_kal}")
ml_ov = build_materialliste(ROOMS, [], BAUD, override={"bodenplatte_aufschlag": 1.50},
                            kalibrierung={"bodenplatte_aufschlag": 1.30})
check("User-Override schlägt Kalibrierung (1.50 gewinnt)",
      abs(ml_ov["annahmen"]["bodenplatte_aufschlag"] - 1.50) < 0.01, f"got {ml_ov['annahmen']['bodenplatte_aufschlag']}")

print("\n8) EHRLICHKEIT: ohne Kalibrierung bleibt der Baseline UNVERÄNDERT:")
ml_none = build_materialliste(ROOMS, [], BAUD, kalibrierung=None)
check("kalibrierung=None → exakt wie Baseline",
      ml_none["annahmen"]["bodenplatte_aufschlag"] == ml_base["annahmen"]["bodenplatte_aufschlag"])
check("leere Kalibrierung {} → unverändert",
      build_materialliste(ROOMS, [], BAUD, kalibrierung={})["annahmen"]["bodenplatte_aufschlag"] == a_base)

print("\n9) WANDVERTEILUNG (Schraffur-Größe) aus Soll-HLZ-Paletten lernen:")
soll_hlz = [{"bezeichnung": "HLZ 50cm H.I. Plan", "menge": 48, "einheit": "Paletten"},
            {"bezeichnung": "HLZ 38cm H.I. Plan", "menge": 4, "einheit": "Paletten"},
            {"bezeichnung": "HLZ 25cm Plan", "menge": 7, "einheit": "Paletten"},
            {"bezeichnung": "HLZ 20cm Plan", "menge": 9, "einheit": "Paletten"},
            {"bezeichnung": "HLZ 12cm Plan", "menge": 7, "einheit": "Paletten"}]
wv = kal.hlz_verteilung_aus_soll(soll_hlz)
check("Innenwand 25/20/12 aus echten Paletten (30/39/30)",
      wv and round(wv["wand_anteil_25cm_innen"]) == 30 and round(wv["wand_anteil_20cm"]) == 39
      and round(wv["wand_anteil_12cm"]) == 30, f"got {wv}")
check("Außenwand 50 dominiert (≈92%)", round(wv["wand_anteil_50cm"]) == 92, f"got {wv}")
check("keine HLZ in Liste → None", kal.hlz_verteilung_aus_soll([{"bezeichnung": "Beton", "menge": 5}]) is None)
agg = kal.aggregiere_verteilungen([{"wand_anteil_12cm": 30.0}, {"wand_anteil_12cm": 40.0}, {"wand_anteil_12cm": 50.0}])
check("Aggregation = Median über Listen", agg["wand_anteil_12cm"] == 40.0, f"got {agg}")

print("\n10) Verteilungs-PRÄZEDENZ: explizite Anteile schlagen Legende-Counts:")
WROOMS = [{"name": "Wohnen", "flaeche_m2": 40.0, "umfang_m": 26.0, "hoehe_m": 2.7, "bodenbelag": "Fliesen"},
          {"name": "Zimmer", "flaeche_m2": 16.0, "umfang_m": 16.0, "hoehe_m": 2.7, "bodenbelag": "Fliesen"}]
# explizite Geometrie, damit Innenwand-Länge positiv ist: (ΣU 42 − Außen 26)/2 = 8m
G_W = {"aussenumfang_m": 26.0, "bodenplatte_flaeche_m2": 56.0, "konfidenz": 0.9, "quelle": "test"}
def _hlz(ml, needle):
    for p in ml["bauteile"].get("Mauerwerk EG", []):
        if needle.lower() in p["material"].lower():
            return p["menge"]
    return None
# Legende sagt Innen 25:80/12:20; explizite Kalibrierung sagt 25:0/20:0/12:100
leg_vert = {"aussen": {50.0: 100.0}, "innen": {25.0: 80.0, 12.0: 20.0}}
ml_leg = build_materialliste(WROOMS, [], BAUD, wand_verteilung=leg_vert, gemessen=G_W)
ml_kal_wv = build_materialliste(WROOMS, [], BAUD, wand_verteilung=leg_vert, gemessen=G_W,
              kalibrierung={"wand_anteil_25cm_innen": 0, "wand_anteil_20cm": 0, "wand_anteil_12cm": 100,
                            "wand_anteil_50cm": 100, "wand_anteil_38cm": 0, "wand_anteil_25cm_aussen": 0})
check("ohne Kalibrierung: Legende-Verteilung greift (25cm-Wand vorhanden)",
      _hlz(ml_leg, "HLZ 25cm") and _hlz(ml_leg, "HLZ 25cm") > 0, f"got {_hlz(ml_leg,'HLZ 25cm')}")
check("mit Kalibrierung 12cm=100%: 12cm-Menge steigt, 20cm→0",
      _hlz(ml_kal_wv, "HLZ 12cm") and _hlz(ml_kal_wv, "HLZ 20cm") == 0, f"12er={_hlz(ml_kal_wv,'HLZ 12cm')} 20er={_hlz(ml_kal_wv,'HLZ 20cm')}")

print()
if fails:
    print(f"FEHLER: {len(fails)} Test(s) gescheitert: {fails}")
    sys.exit(1)
print("OK — Kalibrierung lernt Faktoren + Wandverteilung mit Guards, byte-exakt unangetastet, Präzedenz stimmt.")
