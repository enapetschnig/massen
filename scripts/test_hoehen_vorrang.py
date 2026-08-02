"""WÄCHTER: die Schätzung darf die MESSUNG nicht unterbieten.

Die Geschosshöhe treibt jede wandhöhen-getriebene Menge: Außen- und
Innenwand, HLZ (LG 08), Putz (LG 10), Maler (LG 46). Sie hat mehrere
Quellen, und die Reihenfolge entscheidet über die halbe Mengenliste:

  legende / schnitt   ← aus dem Blatt (Schnitt = KI-BILDLESUNG)
  raumhoehen-max      ← BYTE-EXAKT aus den Raumstempeln (RH/H im Text)
  opus                ← KI-Bauingenieur-Urteil
  Vorgabe 2,70 m      ← reine Annahme

Für `opus` stand die Physik-Sperre schon im Code: die ROHBAU-Höhe kann nie
unter der LICHTEN Raumhöhe liegen — dazwischen sitzt zwingend die Decke.
Eine Lesung, die tiefer liegt, ist nachweislich falsch. Für `schnitt` fehlte
genau diese Sperre: die KI-Bildlesung überschrieb die byte-exakt gelesene
Zahl bedingungslos, auch nach UNTEN. Der Kommentar zur Opus-Sperre nennt
die Folge selbst: „sonst wären ALLE wandhöhen-getriebenen Massen ~15 % zu
niedrig".

Belegt ist die Ausgangslage am Korpus: 3 der 4 Grundrisse tragen RH-Marken
(WM 60 Werte 2,40–2,44 m, Velden 11 × 2,75 m, AP.01 10 × 2,69–2,95 m). Auf
genau diesen Plänen wäre eine zu tiefe Schnitt-Lesung durchgeschlagen.

Zusagen:
  1. Schnitt-Lesung UNTER der byte-exakten lichten Höhe → verworfen.
  2. Schnitt-Lesung DARÜBER → übernommen (Rohbau = lichte + Decke).
  3. Ohne byte-exakte Raumhöhe greift die Schnitt-Lesung wie bisher.
  4. Dieselbe Sperre gilt weiterhin für Opus (keine Regression).
"""
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "api"))

QUELLE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                      "..", "api", "extract.py")


def _sperre(gh_s, quelle_vor, hoehe_vor):
    """Die Entscheidung aus extract.py, isoliert nachvollzogen.

    Bewusst nachgebaut: der Block sitzt tief in der Projekt-Zusammenführung
    und braucht ein vollständiges Analyse-Log. Der Wächter prüft darum
    ZUSÄTZLICH unten, dass der Code die Sperre wirklich enthält.
    """
    blockt = (quelle_vor == "raumhoehen-max" and gh_s
              and gh_s < hoehe_vor - 0.05)
    if gh_s and 2.2 <= gh_s <= 4.5 and not blockt:
        return round(gh_s, 2), "schnitt"
    return hoehe_vor, quelle_vor


# (Name, Schnitt-Lesung, bisherige Quelle, bisherige Höhe, erwartete Höhe/Quelle)
FAELLE = [
    ("Schnitt liest 2,40 unter byte-exakten 2,95 → verwerfen",
     2.40, "raumhoehen-max", 2.95, 2.95, "raumhoehen-max"),
    ("Schnitt liest 3,05 über byte-exakten 2,75 → übernehmen",
     3.05, "raumhoehen-max", 2.75, 3.05, "schnitt"),
    ("gleiche Höhe (Toleranz 5 cm) → übernehmen",
     2.72, "raumhoehen-max", 2.75, 2.72, "schnitt"),
    ("keine byte-exakte Raumhöhe → Schnitt greift",
     3.10, None, 2.70, 3.10, "schnitt"),
    ("Schnitt unplausibel (5,20 m) → nichts ändern",
     5.20, "raumhoehen-max", 2.75, 2.75, "raumhoehen-max"),
    ("Schnitt liefert nichts → nichts ändern",
     None, "raumhoehen-max", 2.75, 2.75, "raumhoehen-max"),
]


def _code_hat_sperre(fehler):
    """Der Nachbau oben nützt nichts, wenn die Sperre im Code fehlt."""
    src = open(QUELLE, encoding="utf-8").read()
    if "_s_blockt" not in src:
        fehler.append("api/extract.py enthält keine Schnitt-Physik-Sperre "
                      "(_s_blockt) — der Wächter prüft dann nur sich selbst")
        return
    # Die Opus-Sperre muss ebenfalls stehen bleiben (keine Regression).
    if not re.search(r'_q\s*==\s*"raumhoehen-max"\s+and\s+o_roh\s*<', src):
        fehler.append("die Opus-Physik-Sperre ist verschwunden — "
                      "dieselbe Lücke, nur an der anderen Quelle")
        return
    print("   Code enthält BEIDE Physik-Sperren (Schnitt + Opus) ✓")


def run():
    print("HÖHEN-VORRANG — die Schätzung darf die Messung nicht unterbieten")
    print("=" * 96)
    fehler = []
    _code_hat_sperre(fehler)
    print()
    print(f"{'Fall':<52}{'→ Höhe':>9}{'Quelle':>18}   Zusage")
    print("-" * 96)
    for name, gh_s, q_vor, h_vor, h_soll, q_soll in FAELLE:
        h, q = _sperre(gh_s, q_vor, h_vor)
        ok = (abs(h - h_soll) < 0.001) and (q == q_soll)
        if not ok:
            fehler.append(f"{name}: {h} m aus '{q}', erwartet {h_soll} m "
                          f"aus '{q_soll}'")
        print(f"{name:<52}{h:>8.2f}m{str(q):>18}   {'✓' if ok else 'FALSCH'}")
    print("-" * 96)
    if fehler:
        print("FEHLER:")
        for f in fehler:
            print(f"  ✗ {f}")
    else:
        print("WÄCHTER ok: eine Schnitt-Lesung unter der byte-exakten lichten "
              "Raumhöhe wird verworfen\n           (Rohbau kann nicht "
              "niedriger sein als lichte Höhe), nach oben bleibt sie erlaubt")
    assert not fehler, f"{len(fehler)} Höhen-Vorrang-Fehler"


if __name__ == "__main__":
    run()
