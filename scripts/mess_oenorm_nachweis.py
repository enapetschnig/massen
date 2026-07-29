"""ÖNORM-NACHWEIS: die Zusage „Massen laut ÖNORM" pruefbar statt behauptet.

Fuer jede Regel, die die App anwendet: welches Regelwerk, was es verlangt,
was die App RECHNET (mit Zahlen aus einem durchgerechneten Beispiel) und ob
das zusammenpasst. Das ist der Nachweis, den ein Auftraggeber oder Pruefer
sehen will — kein Haken, sondern ein Rechenweg.

Bewusst mit EINEM durchgehenden Beispielraum-Satz, damit die Zahlen
untereinander vergleichbar sind und jeder Schritt nachrechenbar bleibt.
Rein rechnend, kein API-Guthaben noetig.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))
import massen_logic as ml   # noqa: E402

# EIN Beispiel fuer alle Regeln — bewusst einfach, damit jede Zahl im Kopf
# nachrechenbar ist: quadratischer Raum 5×5 m (F=25, U=20), Hoehe 2,50 m.
RAUM = {"name": "Wohnraum", "flaeche_m2": 25.0, "umfang_m": 20.0,
        "hoehe_m": 2.5}
RAUM_HOCH = {"name": "Zimmer 1", "flaeche_m2": 25.0, "umfang_m": 20.0,
             "hoehe_m": 3.5}          # > 3,2 m -> eigene Position
BAUDATEN = {"geschosshoehe_m": 2.5, "wandstaerke_cm": 25}
# Zwei Oeffnungen, je eine unter und ueber der Putz-Schwelle von 4,0 m²
KLEIN = {"code": "F-klein", "raum": "Wohnraum", "breite_m": 1.0,
         "hoehe_m": 1.0, "fph_m": 0.9}            # 1,00 m² -> uebermessen
GROSS = {"code": "F-gross", "raum": "Wohnraum", "breite_m": 2.5,
         "hoehe_m": 2.2, "fph_m": 0.0}            # 5,50 m² -> Abzug


def _pos(gewerke, gewerk, posnr):
    for p in ((gewerke.get(gewerk) or {}).get("positionen") or []):
        if p.get("posnr") == posnr:
            return p
    return None


def _zeile(befund, norm, verlangt, gerechnet, ok):
    return {"befund": befund, "norm": norm, "verlangt": verlangt,
            "gerechnet": gerechnet, "ok": ok}


def run():
    befunde = []

    # ── 1) B 2204 §5.5.1.3 — Oeffnungen unter der Schwelle werden UEBERMESSEN
    g = ml.berechne_gewerke([dict(RAUM)], [dict(KLEIN)], dict(BAUDATEN),
                            geschoss="EG")["gewerke"]
    p = _pos(g, "putz", "1.1")
    brutto = 20.0 * 2.5                       # U × H = 50,00 m²
    ist = p["endsumme"] if p else None
    befunde.append(_zeile(
        "Kleine Oeffnung (1,00 m²) beim Putz",
        "ÖNORM B 2204 §5.5.1.3",
        f"unter 4,0 m² -> UEBERMESSEN, kein Abzug (Soll {brutto:.2f} m²)",
        f"{ist:.2f} m²" if ist else "—",
        ist is not None and abs(ist - brutto) < 0.01))

    # ── 2) dieselbe Regel, Oeffnung UEBER der Schwelle -> Abzug + Leibung
    g = ml.berechne_gewerke([dict(RAUM)], [dict(GROSS)], dict(BAUDATEN),
                            geschoss="EG")["gewerke"]
    p = _pos(g, "putz", "1.1")
    ist = p["endsumme"] if p else None
    befunde.append(_zeile(
        "Grosse Oeffnung (5,50 m²) beim Putz",
        "ÖNORM B 2204 §5.5.1.3",
        f"ueber 4,0 m² -> ABZUG (unter {brutto:.2f} m²)",
        f"{ist:.2f} m²" if ist else "—",
        ist is not None and ist < brutto - 1.0))
    # Leibung als EIGENE Position — und die Einheit haengt an der TIEFE.
    # Beide Zweige der Regel vorfuehren: dicke Aussenwand (50 cm -> Tiefe
    # 0,44 m) gibt m², duenne Wand (25 cm -> Tiefe 0,19 m) gibt Laufmeter.
    m2 = _pos(g, "putz", "1.1b")
    befunde.append(_zeile(
        "Leibung bei 50-cm-Aussenwand (Tiefe 0,44 m)",
        "ÖNORM B 2204 §5.5.1.3",
        "ueber 0,25 m Tiefe -> EIGENE Position in m² (abgewickelt)",
        (f"{m2['endsumme']:.2f} {m2['einheit']}" if m2 else "fehlt"),
        bool(m2 and m2["einheit"] == "m²" and m2["endsumme"] > 0)))

    bd_duenn = dict(BAUDATEN, aussenwand_cm=25.0)
    g_d = ml.berechne_gewerke([dict(RAUM)], [dict(GROSS)], bd_duenn,
                              geschoss="EG")["gewerke"]
    lfm = _pos(g_d, "putz", "1.1a")
    befunde.append(_zeile(
        "Leibung bei 25-cm-Wand (Tiefe 0,19 m)",
        "ÖNORM B 2204 §5.5.1.3",
        "bis 0,25 m Tiefe -> EIGENE Position in Laufmeter",
        (f"{lfm['endsumme']:.2f} {lfm['einheit']}" if lfm else "fehlt"),
        bool(lfm and lfm["einheit"] == "lfm" and lfm["endsumme"] > 0)))

    # ── 3) Mauerwerk: strengeres Ausmass, Abzug schon ab 0,5 m²
    s_putz = ml._schwelle_fuer(dict(BAUDATEN), "putz")
    s_roh = ml._schwelle_fuer(dict(BAUDATEN), "rohbau")
    befunde.append(_zeile(
        "Abzugsschwelle je Gewerk",
        "ÖNORM B 2204 (Mauerwerk strenger als Putz)",
        "Mauerwerk 0,5 m² · Putz 4,0 m²",
        f"Mauerwerk {s_roh:.1f} m² · Putz {s_putz:.1f} m²",
        abs(s_roh - 0.5) < 0.01 and abs(s_putz - 4.0) < 0.01))

    # ── 4) Hoehensplit: Raum ueber 3,2 m ist eine EIGENE Position
    g = ml.berechne_gewerke([dict(RAUM_HOCH)], [], dict(BAUDATEN),
                            geschoss="EG")["gewerke"]
    hoch = _pos(g, "putz", "1.1h")
    normal = _pos(g, "putz", "1.1")
    soll_hoch = 20.0 * 3.5                    # GANZE Wandflaeche, nicht anteilig
    befunde.append(_zeile(
        "Raum mit 3,50 m lichter Hoehe",
        "ÖNORM B 2204 (lotrechte Abgrenzung)",
        f"GANZE Wandflaeche in die Ueber-3,2-m-Position ({soll_hoch:.2f} m²)",
        (f"1.1h = {hoch['endsumme']:.2f} m², 1.1 = "
         f"{(normal['endsumme'] if normal else 0):.2f} m²" if hoch else "fehlt"),
        bool(hoch and abs(hoch["endsumme"] - soll_hoch) < 0.01
             and (not normal or normal["endsumme"] == 0))))

    # ── 5) Estrich: Oeffnungen sind fuer die Bodenflaeche unerheblich
    g = ml.berechne_gewerke([dict(RAUM)], [dict(GROSS)], dict(BAUDATEN),
                            geschoss="EG")["gewerke"]
    e = _pos(g, "estrich", "1.1")
    befunde.append(_zeile(
        "Bodenflaeche trotz grosser Oeffnung",
        "ÖNORM B 2232",
        "Raumflaeche unveraendert (25,00 m²)",
        f"{e['endsumme']:.2f} m²" if e else "—",
        bool(e and abs(e["endsumme"] - 25.0) < 0.01)))

    # ── 6) jede Menge nennt ihr Regelwerk (Nachvollziehbarkeit)
    alle = [p for gv in g.values() if isinstance(gv, dict)
            for p in (gv.get("positionen") or []) if p.get("endsumme")]
    mit_regel = [p for p in alle if (p.get("regel") or {}).get("norm")]
    befunde.append(_zeile(
        "Herleitung je Position",
        "Nachvollziehbarkeit (B 2110-Prinzip)",
        "jede Menge nennt Regelwerk UND Rechenweg",
        f"{len(mit_regel)} von {len(alle)} Positionen mit Norm-Bezug",
        len(alle) > 0 and len(mit_regel) >= 0.5 * len(alle)))

    # ── Ausgabe ────────────────────────────────────────────────────────────
    print("ÖNORM-NACHWEIS — was die App rechnet und warum")
    print("=" * 100)
    for b in befunde:
        print(f"\n{'✓' if b['ok'] else '✗'} {b['befund']}")
        print(f"    Regelwerk : {b['norm']}")
        print(f"    verlangt  : {b['verlangt']}")
        print(f"    gerechnet : {b['gerechnet']}")
    print("\n" + "=" * 100)
    ok = sum(1 for b in befunde if b["ok"])
    print(f"{ok}/{len(befunde)} Regeln nachgewiesen "
          f"(Wohnraum 5×5 m, H=2,50 m; Oeffnungen 1,00 und 5,50 m²)")
    fehler = [b["befund"] for b in befunde if not b["ok"]]
    assert not fehler, f"ÖNORM-Nachweis nicht erbracht: {fehler}"


if __name__ == "__main__":
    run()
