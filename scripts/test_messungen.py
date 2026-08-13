"""WÄCHTER: der Rechenkern des Aufmaß-Werkzeugs (Umbau E1).

Warum dieser Wächter der wichtigste des Umbaus ist: ab hier ist die MESSUNG
die Quelle jeder Menge. Rechnet sie falsch, ist alles falsch — Anzeige,
Protokoll, Export, Rechnung. Und anders als bei der Erkennung gibt es hier
keine Unschärfe: 5,84 × 4,77 ist 27,86 m², punkt.

Zweite Zusage, die hier festgenagelt wird: die FORMEL muss zur ZAHL passen.
Ein Protokoll, das „5,84 × 4,77" schreibt und 30,0 rechnet, ist schlimmer
als gar keins — der Polier prüft die Formel und vertraut danach der Zahl.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "api"))
PTM = 28.35   # 1:100 → 1 m = 28,35 pt


def _rect(b_m, h_m):
    return {"form": "rechteck",
            "punkte": [[0, 0], [b_m * PTM, 0], [b_m * PTM, h_m * PTM],
                       [0, h_m * PTM]]}


def run():
    import messungen as M
    print("AUFMASS-RECHENKERN — stimmt die Zahl, und passt die Formel dazu?")
    print("=" * 84)
    fehler = []

    # 1) Flächen: Zahl UND Formel.
    faelle = [
        (5.84, 4.77, 27.86, "5,84 × 4,77"),
        (1.20, 0.90, 1.08, "1,20 × 0,90"),
        (10.0, 10.0, 100.0, "10,00 × 10,00"),
    ]
    for b, h, soll, formel in faelle:
        w, e, f = M.rechne("flaeche", _rect(b, h), PTM)
        ok = abs(w - soll) < 0.01 and e == "m2" and f == formel
        print(f"   {b} × {h} m → {w} {e}  „{f}\"{'':<4}{'✓' if ok else '✗'}")
        if not ok:
            fehler.append(f"Fläche {b}×{h}: {w} {e} „{f}\" statt {soll} m² „{formel}\"")

    # 2) Der Abzug muss in Zahl UND Formel auftauchen.
    w, e, f = M.rechne("flaeche", _rect(5.84, 4.77), PTM,
                       abzuege=[{"wert": 1.08}])
    ok = abs(w - 26.78) < 0.01 and "−" in f and "1,08" in f
    print(f"   mit Abzug 1,08 → {w} m²  „{f}\"   {'✓' if ok else '✗'}")
    if not ok:
        fehler.append(f"Abzug fehlt in Zahl oder Formel: {w} „{f}\"")

    # 3) Volumen = Fläche × Höhe, und die Formel zeigt beides.
    w, e, f = M.rechne("volumen", _rect(5.0, 4.0), PTM, hoehe_m=0.2)
    ok = abs(w - 4.0) < 0.01 and e == "m3" and "0,20" in f
    print(f"   Volumen 5×4×0,20 → {w} {e}  „{f}\"   {'✓' if ok else '✗'}")
    if not ok:
        fehler.append(f"Volumen falsch: {w} {e} „{f}\"")

    # 4) Länge: Summe der Teilstrecken, Teilstrecken in der Formel.
    L = {"punkte": [[0, 0], [3 * PTM, 0], [3 * PTM, 4 * PTM]]}
    w, e, f = M.rechne("laenge", L, PTM)
    ok = abs(w - 7.0) < 0.01 and e == "m" and "3,00" in f and "4,00" in f
    print(f"   Länge 3 + 4 → {w} {e}  „{f}\"   {'✓' if ok else '✗'}")
    if not ok:
        fehler.append(f"Länge falsch: {w} {e} „{f}\"")

    # 5) Stück.
    w, e, f = M.rechne("stueck", {"anzahl": 7}, PTM)
    if not (w == 7 and e == "stk"):
        fehler.append(f"Stück falsch: {w} {e}")
    else:
        print(f"   Stück 7 → {w} {e}  „{f}\"   ✓")

    # 6) OHNE MASSSTAB darf NICHTS gerechnet werden. Eine Zahl ohne Maßstab
    #    wäre frei erfunden — lieber keine Menge als eine falsche.
    w, e, f = M.rechne("flaeche", _rect(5, 4), 0)
    if w is not None:
        fehler.append(f"ohne Maßstab wurde gerechnet: {w} — das wäre erfunden")
    else:
        print("   ohne Maßstab: keine Zahl (statt einer erfundenen)   ✓")

    # 7) Gedrehtes Rechteck: die Formel muss trotzdem zwei Seiten zeigen.
    import math
    a = math.radians(30)
    b_m, h_m = 4.0, 3.0
    P = [[0, 0],
         [b_m * PTM * math.cos(a), b_m * PTM * math.sin(a)],
         [b_m * PTM * math.cos(a) - h_m * PTM * math.sin(a),
          b_m * PTM * math.sin(a) + h_m * PTM * math.cos(a)],
         [-h_m * PTM * math.sin(a), h_m * PTM * math.cos(a)]]
    w, e, f = M.rechne("flaeche", {"punkte": P}, PTM)
    ok = abs(w - 12.0) < 0.02 and "×" in f
    print(f"   gedrehtes Rechteck 4×3 → {w} m²  „{f}\"   {'✓' if ok else '✗'}")
    if not ok:
        fehler.append(f"gedrehtes Rechteck: {w} „{f}\" statt 12,0 „4,00 × 3,00\"")

    # 8) KI-Vorschlag: der byte-exakte STEMPEL schlägt die Geometrie, und die
    #    Formel sagt das auch. Sonst stünde im Protokoll eine Polygon-Fläche,
    #    wo der Plan eine exakte Zahl nennt.
    r = M.aus_raum({"name": "Bad", "f_m2": 8.75,
                    "region_pt": [[0, 0], [100, 0], [100, 80], [0, 80]]}, PTM)
    ok = r and r["wert"] == 8.75 and "Raumstempel" in r["formel"] \
        and r["status"] == "vorschlag" and r["quelle"] == "ki"
    print(f"   KI-Raum mit Stempel → {r and r['wert']} „{r and r['formel']}\" "
          f"({r and r['status']})   {'✓' if ok else '✗'}")
    if not ok:
        fehler.append(f"KI-Vorschlag: {r}")
    # Ohne Stempel muss die Geometrie tragen.
    r2 = M.aus_raum({"name": "X", "region_pt": [[0, 0], [PTM, 0],
                                                [PTM, PTM], [0, PTM]]}, PTM)
    if not (r2 and abs(r2["wert"] - 1.0) < 0.01):
        fehler.append(f"KI-Raum ohne Stempel rechnet nicht aus der Geometrie: {r2}")
    else:
        print(f"   KI-Raum ohne Stempel → {r2['wert']} m² aus der Geometrie   ✓")

    # 8b) TREPPE (E8): Untersicht = Grundfläche × Schrägfaktor; das Volumen
    #     steht in der Formel. Ein Treppen-Werkzeug, das nur die Grundfläche
    #     liefert, wäre kein Werkzeug — die Untersicht ist die Fläche, die
    #     der Maler/Trockenbauer wirklich abrechnet.
    P_tr = [[0, 0], [3.0 * PTM, 0], [3.0 * PTM, 1.2 * PTM], [0, 1.2 * PTM]]
    w, e, f = M.rechne("treppe", {"punkte": P_tr}, PTM, hoehe_m=2.75)
    soll_u = 3.6 * math.sqrt(1 + (2.75 / 3.0) ** 2)
    ok = w and abs(w - soll_u) < 0.01 and e == "m2" and "V≈" in (f or "")
    print(f"   Treppe 3,0x1,2 H2,75 -> {w} m2 Untersicht   {'OK' if ok else 'FEHLER'}")
    if not ok:
        fehler.append(f"Treppe: {w} {e} ({f}) statt {round(soll_u,3)} m2 mit V in der Formel")
    # Treppe ohne Höhe: Default 2,75 (Geschosshöhe), nie None-Crash.
    w2, _, _ = M.rechne("treppe", {"punkte": P_tr}, PTM)
    if not w2 or w2 <= 3.6:
        fehler.append(f"Treppe ohne Höhe: {w2} — Untersicht muss > Grundfläche sein")
    else:
        print(f"   Treppe ohne Höhe → Default Geschosshöhe ({w2} m²)   ✓")

    # 8c) DACH (E8): wahre Flaeche = Grundriss x 1/cos(Neigung); absurde
    #     Neigung liefert KEINE Zahl (89 Grad waere Faktor 57 — erfunden).
    P_d = [[0, 0], [8 * PTM, 0], [8 * PTM, 5 * PTM], [0, 5 * PTM]]
    w, e, f = M.rechne("dach", {"punkte": P_d, "neigung_grad": 25}, PTM)
    soll_d = 40.0 / math.cos(math.radians(25))
    if not (w and abs(w - soll_d) < 0.01 and "25" in (f or "")):
        fehler.append(f"Dach 25 Grad: {w} ({f}) statt {round(soll_d,3)}")
    else:
        print(f"   Dach 40 m2 bei 25 Grad -> {w} m2, Neigung in der Formel   OK")
    w, e, f = M.rechne("dach", {"punkte": P_d, "neigung_grad": 85}, PTM)
    if w is not None:
        fehler.append(f"Dach 85 Grad lieferte {w} — Faktor 11 waere erfunden")
    else:
        print("   Dach 85 Grad: keine Zahl (Faktor waere absurd)   OK")

    # 8d) WANDFLAECHE (E8): Laenge x Hoehe; ohne Hoehe keine Zahl.
    L_w = {"form": "polylinie", "punkte": [[0, 0], [12.4 * PTM, 0]]}
    w, e, f = M.rechne("wandflaeche", L_w, PTM, hoehe_m=2.75)
    if not (w and abs(w - 34.1) < 0.01 and e == "m2"):
        fehler.append(f"Wandflaeche: {w} {e} statt 34,1 m2")
    else:
        print(f"   Wandflaeche 12,4 x 2,75 -> {w} m2   OK")
    w, _, _ = M.rechne("wandflaeche", L_w, PTM)
    if w is not None:
        fehler.append(f"Wandflaeche ohne Hoehe lieferte {w} — erfunden")
    else:
        print("   Wandflaeche ohne Hoehe: keine Zahl   OK")

    # 9) Protokoll: Summe, Abzug, Verschnitt — und nichts fällt unter den Tisch.
    ms = [
        {"id": "a", "position_id": "p1", "nummer": 1, "wert": 31.12,
         "typ": "flaeche", "formel": "5,84 × 4,77"},
        {"id": "b", "position_id": "p1", "nummer": 2, "wert": 1.08,
         "typ": "abzug", "formel": "1,20 × 0,90"},
        {"id": "c", "position_id": None, "nummer": 3, "wert": 5.0,
         "typ": "flaeche"},
        {"id": "d", "position_id": "p1", "nummer": 4, "wert": 99.0,
         "typ": "flaeche", "status": "verworfen"},
    ]
    pr = M.protokoll(ms, [{"id": "p1", "nr": "1.2", "bezeichnung": "Estrich",
                           "einheit": "m2", "verschnitt_pct": 5}])
    p1 = pr["positionen"][0]
    if abs(p1["summe"] - 30.04) > 0.01:
        fehler.append(f"Protokoll-Summe {p1['summe']} statt 30,04 "
                      f"(31,12 − 1,08; verworfene Messung darf nicht zählen)")
    else:
        print(f"   Protokoll: Summe {p1['summe']} (Abzug ab, verworfen raus)   ✓")
    if abs(p1["endsumme"] - 31.54) > 0.02:
        fehler.append(f"Verschnitt 5 % nicht gerechnet: {p1['endsumme']}")
    else:
        print(f"   Protokoll: +5 % Verschnitt → {p1['endsumme']}   ✓")
    if pr["n_ohne_position"] != 1:
        fehler.append("Messung ohne Position wird verschwiegen — sie muss "
                      "ausgewiesen werden, sonst fehlt sie stillschweigend "
                      "in der Abrechnung")
    else:
        print("   Messung ohne Position wird ausgewiesen, nicht verschluckt   ✓")

    print("-" * 84)
    if fehler:
        print("FEHLER:")
        for f in fehler:
            print(f"  ✗ {f}")
    else:
        print("WÄCHTER ok: jede Menge kommt aus der Geometrie, jede Formel "
              "passt zur Zahl,\n           und ohne Maßstab wird nichts "
              "erfunden.")
    assert not fehler, f"{len(fehler)} Fehler im Aufmaß-Rechenkern"


if __name__ == "__main__":
    run()
