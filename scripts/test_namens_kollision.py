"""WÄCHTER: gleichnamige Räume dürfen sich nichts teilen.

Wohnbauten haben in JEDER Wohnung ein "Bad", einen "Vorraum", eine
"Wohnküche". Wer eine Zuordnung nach dem Raumnamen schlüsselt, wirft sie
zusammen. Am eingefrorenen Korpus teilen sich 66 von 113 Stempeln ihren
normierten Namen mit einem anderen — bei AU_WM_01 sind es 56 von 70 (80 %),
"Zimmer" allein kommt 16-mal vor, mit Flächen von 3,40 bis 13,12 m².

Genau dieser Fehler war in der Produktion und hat MENGEN verfälscht:
api/extract.py::_plan_geo_umfaenge baute {normierter_name: umfang} und gab
damit jedem gleichnamigen Raum den Umfang des ERSTEN. Am Velden-Plan
gemessen bekamen 2 von 8 betroffenen Räumen einen fremden Umfang,
Median-Abweichung 2,00 m = 14 % — und U geht direkt in Putz und Maler
(U × H).

Die bestehenden Wächter konnten das grundsätzlich nicht sehen: sie rechnen
alle mit Einfamilienhaus-Sätzen, in denen jeder Name genau einmal vorkommt.
Dieser hier prüft deshalb den Mehrfamilien-Fall — drei gleiche Bäder mit
verschiedenen Maßen — und verlangt, dass jeder Raum seine eigenen Zahlen
behält.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))
import massen_logic as ml   # noqa: E402

# Drei Wohnungen, überall dieselben Raumnamen, aber andere Maße.
# So sieht jeder reale Wohnbau aus.
MFH = [
    {"name": "Bad", "wohnung": "TOP 01", "flaeche_m2": 5.20, "umfang_m": 9.60,
     "hoehe_m": 2.5},
    {"name": "Bad", "wohnung": "TOP 02", "flaeche_m2": 5.80, "umfang_m": 10.10,
     "hoehe_m": 2.5},
    {"name": "Bad", "wohnung": "TOP 03", "flaeche_m2": 6.40, "umfang_m": 10.40,
     "hoehe_m": 2.5},
    {"name": "Wohnküche", "wohnung": "TOP 01", "flaeche_m2": 24.10,
     "umfang_m": 20.40, "hoehe_m": 2.5},
    {"name": "Wohnküche", "wohnung": "TOP 02", "flaeche_m2": 26.30,
     "umfang_m": 21.30, "hoehe_m": 2.5},
    {"name": "Wohnküche", "wohnung": "TOP 03", "flaeche_m2": 28.00,
     "umfang_m": 22.00, "hoehe_m": 2.5},
]
FENSTER = [
    {"code": "F1", "raum": "Wohnküche", "breite_m": 1.80, "hoehe_m": 1.60,
     "fph_m": 0.9},
    {"code": "F2", "raum": "Wohnküche", "breite_m": 1.80, "hoehe_m": 1.60,
     "fph_m": 0.9},
    {"code": "F3", "raum": "Wohnküche", "breite_m": 1.80, "hoehe_m": 1.60,
     "fph_m": 0.9},
]
BAUDATEN = {"geschosshoehe_m": 2.8, "aussenwand_cm": 38.0,
            "innenwand_tragend_cm": 25.0, "innenwand_nichttragend_cm": 10.0,
            "decke_cm": 22.0, "wandmaterial": "Hochlochziegel"}


def _fehler(liste, text):
    liste.append(text)
    print(f"  ✗ {text}")


def run():
    print("WÄCHTER: gleichnamige Räume (Mehrfamilienhaus-Fall)")
    print("=" * 88)
    print(f"{len(MFH)} Räume, davon 3x 'Bad' und 3x 'Wohnküche' — "
          f"jeweils mit VERSCHIEDENEN Maßen")
    fehler = []

    g = ml.berechne_gewerke([dict(r) for r in MFH], [dict(f) for f in FENSTER],
                            dict(BAUDATEN), geschoss="EG")

    # ── 1) Die Kreuztabelle darf keinen Raum verschlucken ──────────────────
    m = ml.aufmass_matrix(g["gewerke"], [dict(r) for r in MFH])
    zeilen = m.get("raeume") or []
    print(f"\nKreuztabelle: {len(zeilen)} Zeilen für {len(MFH)} Räume")
    for z in zeilen:
        print(f"  {str(z.get('raum'))[:22]:24} F={z.get('f_m2')}")
    if len(zeilen) < len(MFH):
        _fehler(fehler, f"nur {len(zeilen)} Zeilen für {len(MFH)} Räume — "
                        f"{len(MFH) - len(zeilen)} sind verschwunden "
                        f"(Zuordnung nach Raumname statt nach Raum)")

    # ── 2) Jede Fläche muss genau einmal vorkommen ─────────────────────────
    soll_f = sorted(round(r["flaeche_m2"], 2) for r in MFH)
    ist_f = sorted(round(z["f_m2"], 2) for z in zeilen if z.get("f_m2"))
    if ist_f and ist_f != soll_f:
        _fehler(fehler, f"Flächen in der Tabelle {ist_f} statt {soll_f} — "
                        f"Räume wurden zusammengeworfen")

    # ── 3) Fenster dürfen nicht alle im ERSTEN gleichnamigen Raum landen ───
    # Signatur ist fenster_pro_raum(rooms, windows) und der Rückgabeschlüssel
    # ist id(raum) — die Räume also als Liste halten, sonst zeigt der Wächter
    # nur Objekt-IDs und prüft nichts.
    rooms = [dict(r) for r in MFH]
    fpr = ml.fenster_pro_raum(rooms, [dict(f) for f in FENSTER])
    verteilung = {}
    for r in rooms:
        n = f"{r['name']} {r.get('wohnung', '')}".strip()
        verteilung[n] = len(fpr.get(id(r)) or [])
    wk = {k: v for k, v in verteilung.items() if k.startswith("Wohnküche")}
    print(f"\nFenster je Wohnküche: {wk}")
    if wk and max(wk.values()) >= len(FENSTER) and len(FENSTER) > 1:
        _fehler(fehler, f"alle {len(FENSTER)} Fenster in EINEM Raum ({wk}) — "
                        f"die anderen gleichnamigen Räume bekommen keines")
    if wk and sum(wk.values()) != len(FENSTER):
        _fehler(fehler, f"{sum(wk.values())} von {len(FENSTER)} Fenstern "
                        f"zugeordnet ({wk}) — Fenster gehen verloren")

    # ── 4) Die Mengen müssen die SUMME aller Räume tragen ─────────────────
    # Wenn Räume verschluckt werden, fehlt ihre Fläche in den Gewerken.
    soll_boden = sum(r["flaeche_m2"] for r in MFH)
    est = (g["gewerke"].get("estrich") or {}).get("positionen") or []
    ist_boden = sum(p.get("endsumme") or 0 for p in est
                    if (p.get("einheit") == "m²"))
    print(f"\nEstrich-Fläche: {ist_boden:.2f} m² (Summe der Räume "
          f"{soll_boden:.2f} m²)")
    if ist_boden and abs(ist_boden - soll_boden) > 0.5:
        _fehler(fehler, f"Estrich {ist_boden:.2f} m² statt {soll_boden:.2f} m² "
                        f"— es fehlen Räume in der Mengenrechnung")

    print("\n" + "=" * 88)
    if fehler:
        print(f"{len(fehler)} FEHLER — gleichnamige Räume werden zusammengeworfen.")
        print("Ein Wohnbau hat in jeder Wohnung ein 'Bad'. Wer nach dem Namen")
        print("schlüsselt, rechnet für alle dasselbe. Schlüssel muss den RAUM")
        print("identifizieren (Fläche, Position oder Wohnung), nicht seine")
        print("Beschriftung.")
    else:
        print(f"WÄCHTER ok: {len(MFH)} gleichnamige Räume behalten je eigene "
              f"Zahlen (Kreuztabelle, Fenster, Mengen)")
    assert not fehler, f"{len(fehler)} Namens-Kollisionen"


if __name__ == "__main__":
    run()
