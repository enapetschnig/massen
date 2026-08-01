"""WÄCHTER: Öffnungen ohne Maß dürfen nicht STUMM aus dem Abzug fallen.

Fehlt einer Öffnung ein Maß, ist ihre Abzugsfläche rechnerisch 0 —
`oeffnung_netto(breite=0, …)` liefert 0, ohne Fehler, ohne Warnung. Die
Mengenliste sieht dabei VOLLSTÄNDIG aus: nichts fehlt, nichts ist rot.
Das ist der teuerste Fehlertyp, weil nichts auffällt.

Die zweite Hälfte ist genauso wichtig: die ÖNORM übermisst Öffnungen bis
4,0 m². Eine fehlende Breite ändert die Menge also nur, wenn die Öffnung
diese Schwelle überhaupt reißen kann. Am WM-Plan sind das 17 von 46 — bei
den übrigen 29 ist das fehlende Maß FOLGENLOS. Ein Alarm über alle 46 wäre
darum falsch: er warnt vor etwas, das die Zahlen nicht berührt, und
entwertet damit die Warnungen, die es tun.

Warum kein Maß erfunden wird — drei gemessene und verworfene Wege:
  1. nächste cm-Zahl im Umkreis  → gehört dort zu einem anderen Bauteil
  2. Breite aus der Wand-Lücke   → Median-Abweichung 0,63 m am Angerer
  3. Lücke × gedruckte Zahl kreuzvalidiert → 1 Vorschlag auf 6 bekannte
     Fenster, und der lag 2,70 m daneben (3,30 statt 0,60 m). Die am
     Textanker gefundene Lücke misst bei JEDEM Fenster 1,53–1,65 m,
     unabhängig von der echten Breite (0,60–1,30 m) — der Anker trifft
     die Öffnung gar nicht.

Zusagen:
  1. Fehlt ein Maß UND kann es die Schwelle reißen → Hinweis mit Anzahl,
     betroffenen Leistungsgruppen und Richtung des Fehlers.
  2. Alle Maße vollständig → KEIN Hinweis (kein Fehlalarm).
  3. Gar keine Öffnungen → KEIN Hinweis.
  4. Fehlendes Maß, aber weit unter der Schwelle → Hinweis sagt
     ausdrücklich, dass die Mengen NICHT betroffen sind.
  5. Der stille Nulldurchgang selbst wird geprüft — sonst wäre der ganze
     Hinweis auf eine Annahme gebaut.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "api"))

# (Name, Öffnungen, Hinweis erwartet?, muss-enthalten)
FAELLE = [
    ("alles vollständig",
     [{"typ": "fenster", "breite_m": 1.2, "hoehe_m": 1.4},
      {"typ": "tuer", "breite_m": 0.9, "hoehe_m": 2.0}], False, ()),
    ("gar keine Öffnungen", [], False, ()),
    ("Fenster ohne Breite, Höhe 2,2 m (kann Schwelle reißen)",
     [{"typ": "fenster", "breite_m": None, "hoehe_m": 2.2},
      {"typ": "tuer", "breite_m": 0.9, "hoehe_m": 2.0}], True,
     ("LG 10", "LG 46", "LG 08", "1 Fenster")),
    ("Fenster ohne Breite, Höhe 1,0 m (bliebe übermessen)",
     [{"typ": "fenster", "breite_m": None, "hoehe_m": 1.0}], True,
     ("nicht betroffen",)),
    # Einzahl muss stimmen — "1 Türen" liest sich wie ein Programmfehler und
    # kostet Vertrauen in die Zahlen daneben.
    ("Tür ohne Höhe (Schwelle nicht ausschließbar)",
     [{"typ": "tuer", "breite_m": 0.9, "hoehe_m": None}], True,
     ("1 Tür ", "LG 08")),
    ("Mehrzahl bleibt Mehrzahl",
     [{"typ": "tuer", "breite_m": 0.9, "hoehe_m": None},
      {"typ": "tuer", "breite_m": None, "hoehe_m": 2.2}], True, ("2 Türen",)),
    ("Breite 0 zählt als fehlend (sonst 0 m² Abzug)",
     [{"typ": "fenster", "breite_m": 0, "hoehe_m": 2.4}], True, ("4 m²",)),
    ("gemischt: 1 wirksam + 2 folgenlos",
     [{"typ": "fenster", "breite_m": None, "hoehe_m": 2.4},
      {"typ": "fenster", "breite_m": None, "hoehe_m": 0.9},
      {"typ": "fenster", "breite_m": None, "hoehe_m": 1.0}], True,
     ("übrigen 2",)),
]


def _nulldurchgang(fehler):
    """Der GRUND für den Hinweis: fehlt ein Maß, ist der Abzug wirklich 0."""
    from massen_logic import OEFFNUNG_ABZUG_SCHWELLE_M2 as S
    from massen_logic import oeffnung_netto
    # groß genug, dass die ÖNORM sie SICHER abzieht — sonst prüft der
    # Vergleich nur die Übermessung und nicht den fehlenden Wert.
    b, h = 2.4, 2.2
    voll = oeffnung_netto(b, h, 25)["abzug"]
    leer = oeffnung_netto(0, h, 25)["abzug"]
    print(f"   Schwelle {S:g} m² · {b}×{h} m = {b * h:.2f} m²")
    print(f"   Abzug mit Maß: {voll:.2f} m² · ohne Breite: {leer:.2f} m²")
    if voll <= 0:
        fehler.append(f"Testaufbau: {b}×{h} m wird nicht abgezogen "
                      f"({voll}) — der Vergleich prüft nichts")
    elif leer != 0:
        fehler.append(f"Annahme falsch: fehlende Breite zieht {leer} m² ab — "
                      f"dann wäre der Hinweis überflüssig")
    else:
        print(f"   → stiller Nulldurchgang bestätigt: {voll:.2f} m² Abzug "
              f"gehen verloren, ohne Fehlermeldung ✓")


def _echter_plan(fehler):
    """Am echten Plan: Hinweis muss stehen, Zahlen müssen zum Plan passen."""
    import glob

    import fitz
    import nachzeichnen
    import oeffnungen as OE
    gepr = 0
    for muster, lbl in (("AU_WM_01 Erdgeschoss_INDEX E.pdf", "WM"),
                        ("A-5_Einreichplan_Alfred-Angerer", "Angerer")):
        g = sorted(glob.glob(os.path.expanduser(f"~/Downloads/*{muster}*")))
        if not g:
            print(f"   ({lbl} nicht in ~/Downloads — übersprungen)")
            continue
        gepr += 1
        doc = fitz.open(g[0])
        r = nachzeichnen.analysiere_doc(doc, max_px=1400)
        doc.close()
        meta = r.get("meta") or {}
        oe = r.get("oeffnungen") or []
        h = meta.get("oeffnungen_hinweis") or ""
        ohne = [o for o in oe if not (o.get("breite_m") and o.get("hoehe_m"))]
        print(f"   {lbl}: {len(oe)} Öffnungen, {len(ohne)} ohne Maß")
        print(f"      → {h[:100]}{'…' if len(h) > 100 else ''}"
              if h else "      → kein Hinweis")
        if ohne and not h:
            fehler.append(f"{lbl}: {len(ohne)} Öffnungen ohne Maß, aber KEIN "
                          f"Hinweis — genau der stille Fall")
        if not ohne and h:
            fehler.append(f"{lbl}: alle Maße vollständig, trotzdem Hinweis "
                          f"— Fehlalarm: {h[:70]!r}")
        if h and str(len(ohne)) not in h:
            fehler.append(f"{lbl}: Hinweis nennt die Anzahl {len(ohne)} "
                          f"nicht: {h[:70]!r}")
        # App und Wächter müssen dieselbe Funktion benutzen.
        if OE.hinweis_unvollstaendig(oe) != h:
            fehler.append(f"{lbl}: meta.oeffnungen_hinweis weicht von "
                          f"hinweis_unvollstaendig() ab — zwei Wahrheiten")
    if gepr == 0:
        fehler.append("kein echter Plan geprüft — Aussage nicht belastbar")


def run():
    import oeffnungen as OE
    print("ÖFFNUNGEN OHNE MASS — stiller Nulldurchgang beim ÖNORM-Abzug")
    print("=" * 92)
    fehler = []
    _nulldurchgang(fehler)
    print()
    print(f"{'Fall':<54}{'Hinweis':>9}   Zusage")
    print("-" * 92)
    for name, oe, soll, muss in FAELLE:
        h = OE.hinweis_unvollstaendig(oe)
        ist = bool(h)
        ok = ist == soll
        if not ok:
            fehler.append(f"{name}: Hinweis={ist}, erwartet {soll}")
        for m in muss:
            if m not in h:
                fehler.append(f"{name}: Hinweis enthält {m!r} nicht — "
                              f"{h[:80]!r}")
                ok = False
        print(f"{name:<54}{('ja' if ist else 'nein'):>9}   "
              f"{'✓' if ok else 'FALSCH'}")
        if ist:
            print(f"      {h[:120]}{'…' if len(h) > 120 else ''}")
    print("-" * 92)
    _echter_plan(fehler)
    print("-" * 92)
    if fehler:
        print("FEHLER:")
        for f in fehler:
            print(f"  ✗ {f}")
    else:
        print("WÄCHTER ok: fehlende Öffnungsmaße werden benannt statt still "
              "übergangen —\n           mit ÖNORM-Übermessung eingeordnet, "
              "und ohne Fehlalarm auf sauberen Plänen")
    assert not fehler, f"{len(fehler)} Öffnungs-Hinweis-Fehler"


if __name__ == "__main__":
    run()
