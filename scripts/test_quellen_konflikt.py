"""WÄCHTER: bei widersprüchlichen Quellen entscheidet die QUELLE, nicht die Zahl.

Bauteil-Stärken kommen aus zwei Wegen: der Legende (byte-exakt aus dem
Text-Layer gelesen) und dem Schnitt (von einem Vision-Modell geschätzt).
Widersprechen sie sich, muss klar sein, welcher gewinnt.

Hier stand allein der Median. Bei GENAU ZWEI Werten ist sorted(...)[1] aber
immer der GRÖSSERE — die Entscheidung hing also daran, welche Zahl zufällig
höher war, nicht daran, welche Quelle etwas taugt.

Am Referenzplan fiel das richtig aus, aber nur zufällig:

    Decke — Legende 25,0 cm (Text)  ·  Schnitt 20,0 cm (Vision)   -> 25 ✓
    umgekehrt: Legende 20,0 cm      ·  Schnitt 25,0 cm            -> 25 ✗

Im zweiten Fall hätte die geschätzte Lesung den byte-exakten Text
geschlagen. Die Decke geht als Fläche × Dicke in den Beton: bei 251,55 m²
Deckenfläche sind 5 cm Unterschied 12,6 m³ Beton.

Der Wächter prüft beide Implementierungen — die in api/opus_konsum.py und
die Inline-Kopie in api/extract.py müssen dieselbe Antwort geben.
"""
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))
import opus_konsum as ok   # noqa: E402

# (Name, Quellenliste, erwarteter Wert, muss Entscheidung nennen)
FAELLE = [
    ("Decke: Legende 25 (Text) vs Schnitt 20 (Vision)",
     [("Legende", 25.0, "text"), ("Schnitt", 20.0, "vision")], 25.0, True),
    ("UMGEKEHRT: Legende 20 (Text) vs Schnitt 25 (Vision)",
     [("Legende", 20.0, "text"), ("Schnitt", 25.0, "vision")], 20.0, True),
    ("einig: beide 25 — kein Eingriff",
     [("Legende", 25.0, "text"), ("Schnitt", 25.0, "vision")], 25.0, False),
    ("einig innerhalb Toleranz (25 / 24)",
     [("Legende", 25.0, "text"), ("Schnitt", 24.0, "vision")], 25.0, False),
    ("zwei Vision-Quellen im Streit — Median bleibt",
     [("Schnitt", 20.0, "vision"), ("Opus", 30.0, "vision")], 30.0, False),
    ("zwei Text-Quellen im Streit — Median der Texte",
     [("Legende", 20.0, "text"), ("Stempel", 30.0, "text")], 30.0, False),
]


def run():
    print("QUELLEN-KONFLIKT — wer gewinnt bei Widerspruch?")
    print("=" * 96)
    print(f"{'Fall':52}{'genommen':>10}{'erwartet':>10}{'Status':>14}  Begründung")
    print("-" * 96)
    fehler = []
    for name, quellen, soll, will_grund in FAELLE:
        d = ok.doppelcheck_num("Decke", "decke_cm", "cm", quellen, 1.5)
        if not d:
            fehler.append(f"{name}: kein Ergebnis")
            continue
        ist = d.get("wert")
        grund = d.get("entscheidung") or ""
        if abs(ist - soll) > 0.01:
            fehler.append(f"{name}: {ist} statt {soll}")
        if will_grund and not grund:
            fehler.append(f"{name}: Entscheidung nicht begründet")
        if not will_grund and grund:
            fehler.append(f"{name}: unnötige Entscheidung gemeldet ({grund})")
        print(f"{name[:51]:52}{ist:10.1f}{soll:10.1f}{d.get('status',''):>14}  "
              f"{grund[:34]}")
    print("-" * 96)

    # BEIDE Implementierungen müssen gleich antworten — sonst haengt das
    # Ergebnis davon ab, ob das Opus-Modul geladen ist.
    p = os.path.join(os.path.dirname(__file__), "..", "api", "extract.py")
    q = open(p, encoding="utf-8").read()
    hat_inline = re.search(r"_text = \[v for _, v, t in vv if t == \"text\"\]", q)
    if not hat_inline:
        fehler.append("api/extract.py: die Inline-Kopie bevorzugt die "
                      "Text-Quelle NICHT — dann entscheidet der Zufall, "
                      "welche Implementierung greift")
    else:
        print("Inline-Kopie in api/extract.py: bevorzugt die Text-Quelle ebenfalls ✓")

    # Und der Hinweis muss sagen, WOMIT gerechnet wird.
    if "Gerechnet wird mit" not in q:
        fehler.append("Prüfliste nennt den genommenen Wert nicht — "
                      "'Quellen widersprechen sich, bitte prüfen' lässt den "
                      "Polier raten, welche Zahl in den Mengen steckt")
    else:
        print("Prüfliste nennt den genommenen Wert und den Grund ✓")

    print()
    if fehler:
        print("FEHLER:")
        for f in fehler:
            print(f"  ✗ {f}")
    else:
        print(f"WÄCHTER ok: {len(FAELLE)} Konfliktfälle richtig aufgelöst, "
              f"beide Implementierungen einig")
    assert not fehler, f"{len(fehler)} Konflikt-Fehler"


if __name__ == "__main__":
    run()
