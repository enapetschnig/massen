"""WÄCHTER: Klick-Handler im HTML-Attribut müssen gültig sein.

Ein stiller Fehler, der im Browser gefunden wurde und drei Stellen betraf —
zwei davon monatelang:

    onclick="nzHighlightRaum(" + JSON.stringify(name) + ")"

JSON.stringify liefert DOPPELTE Anführungszeichen. Das Attribut selbst steht
aber in doppelten. Der Browser liest also

    onclick="nzHighlightRaum("     ← Attribut endet hier
    Zimmer                          ← wird ein eigenes Attribut
    1")"                            ← Müll

Ergebnis: ein Syntaxfehler, der Klick bleibt wirkungslos. Kein Test schlug
an, keine Fehlermeldung erschien, die Zelle sah klickbar aus — nur passierte
nichts. Genau diese Sorte Fehler kostet Vertrauen: "Im Plan zeigen" ist die
Nachvollziehbarkeits-Zusage der App.

Der Wächter sucht im ausgelieferten JavaScript nach Inline-Handlern, die in
einem doppelt gequoteten Attribut mit JSON.stringify (oder einem anderen
doppelten Anführungszeichen) gebaut werden.
"""
import os
import re
import sys

WURZEL = os.path.join(os.path.dirname(__file__), "..")
DATEIEN = ["public/js/upload.js"]


def run():
    print("KLICK-HANDLER — Inline-Attribute auf gültige Anführungszeichen")
    print("=" * 84)
    fehler = []
    geprueft = 0
    for rel in DATEIEN:
        p = os.path.join(WURZEL, rel)
        if not os.path.exists(p):
            continue
        zeilen = open(p, encoding="utf-8").read().split("\n")
        # Ein Inline-Handler wird über mehrere Zeilen zusammengesetzt; darum
        # jede Zeile mit on…=" ansehen UND die beiden folgenden.
        for i, z in enumerate(zeilen):
            if not re.search(r'on(click|change|input|submit)="', z):
                continue
            geprueft += 1
            fenster = " ".join(zeilen[i:i + 3])
            # Der Aufruf endet erst mit ')"' — alles davor gehört zum Attribut.
            m = re.search(r'on\w+="[^"]*"\s*\+\s*(.+?)\+\s*\'\)"', fenster)
            teil = m.group(1) if m else fenster
            if "JSON.stringify" in teil and 'on\\w+="' not in teil:
                # JSON.stringify IN einem doppelt gequoteten Attribut
                if re.search(r'on\w+="[^"]*\'?\s*\+\s*JSON\.stringify', fenster):
                    fehler.append(
                        f"{rel}:{i + 1} — JSON.stringify in einem doppelt "
                        f"gequoteten Attribut: liefert doppelte "
                        f"Anführungszeichen und zerlegt das Attribut.\n"
                        f"      {z.strip()[:100]}")
    print(f"{geprueft} Inline-Handler geprüft in {len(DATEIEN)} Datei(en)")
    if fehler:
        print("\nFEHLER:")
        for f in fehler:
            print(f"  ✗ {f}")
        print("\nRichtig ist: innen EINFACHE Anführungszeichen, den Wert erst")
        print("JS-escapen (\\ und ') und dann HTML-escapen. In upload.js macht")
        print("das die Funktion _raumKlick(name) — sie ist die eine Stelle.")
    else:
        print("WÄCHTER ok: kein Inline-Handler baut sein Argument mit "
              "doppelten Anführungszeichen")
    assert not fehler, f"{len(fehler)} kaputte Klick-Handler"


if __name__ == "__main__":
    run()
