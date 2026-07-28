"""WÄCHTER Sektor-Synchronität: die App darf kein Gewerk anbieten, das sie
nicht rechnet — und keines verstecken, das sie rechnet.

Befund, der zu diesem Guard führte (dokumentiert in docs/OENORM_ROADMAP.md):
das Dashboard bot „Trockenbau" zur Auswahl an, obwohl die Pipeline dieses
Gewerk NIE berechnet hat — der Nutzer wählte es und bekam dafür nichts.
Umgekehrt fehlte „Erdarbeiten" in der Auswahl, obwohl es berechnet wird.
Beides ist ein Versprechen-/Leistung-Bruch und driftet leicht wieder
auseinander, wenn Frontend und Engine getrennt gepflegt werden.
"""
import os
import re
import sys

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, os.path.join(ROOT, "api"))
import massen_logic as ml   # noqa: E402

# Sektoren mit eigenem Pfad außerhalb der GEWERKE-Tabelle:
#  dach      — eigener byte-exakter Dach-Pass (dach_positionen)
#  allgemein — Default ohne Sektor-Vorauswahl
SONDER = {"dach", "allgemein"}


def _dropdown_werte():
    pfad = os.path.join(ROOT, "public", "dashboard.html")
    html = open(pfad, encoding="utf-8").read()
    m = re.search(r'<select id="proj-gewerk".*?</select>', html, re.S)
    assert m, "Gewerk-Auswahl im Dashboard nicht gefunden"
    werte = re.findall(r'<option value="([^"]*)"', m.group(0))
    return {w for w in werte if w}          # leerer Platzhalter raus


def _sektorliste_js():
    pfad = os.path.join(ROOT, "public", "js", "upload.js")
    js = open(pfad, encoding="utf-8").read()
    m = re.search(r"var _SEKTOREN = \[(.*?)\];", js, re.S)
    assert m, "_SEKTOREN in upload.js nicht gefunden"
    return set(re.findall(r"'([a-z]+)'", m.group(1)))


def run():
    berechnet = set(ml.GEWERKE.keys())
    angeboten = _dropdown_werte()
    durchgelassen = _sektorliste_js()

    # 1) Nichts anbieten, was nicht gerechnet wird
    leere_versprechen = angeboten - berechnet - SONDER
    assert not leere_versprechen, (
        f"Dashboard bietet Gewerke an, die die Pipeline NICHT rechnet: "
        f"{sorted(leere_versprechen)} — der Nutzer waehlt und bekommt nichts")

    # 2) Nichts verstecken, was gerechnet wird
    verschwiegen = berechnet - angeboten
    assert not verschwiegen, (
        f"Pipeline rechnet Gewerke, die im Dashboard fehlen: "
        f"{sorted(verschwiegen)} — nicht auswaehlbar")

    # 3) Die JS-Weiche darf nichts durchlassen, was es nicht gibt
    unbekannt = durchgelassen - berechnet - SONDER
    assert not unbekannt, (
        f"_SEKTOREN laesst unbekannte Sektoren durch: {sorted(unbekannt)}")

    # 4) und nichts blockieren, was angeboten wird
    blockiert = (angeboten - SONDER) - durchgelassen
    assert not blockiert, (
        f"angeboten, aber von _SEKTOREN blockiert (faellt still auf "
        f"'allgemein'): {sorted(blockiert)}")

    print(f"OK — Sektoren synchron: {len(berechnet)} berechnete Gewerke "
          f"({', '.join(sorted(berechnet))}) + {len(SONDER)} Sonderpfade; "
          f"Auswahl und Engine decken sich, kein leeres Versprechen")


if __name__ == "__main__":
    run()
