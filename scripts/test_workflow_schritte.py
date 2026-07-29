"""WÄCHTER Workflow-Schritte: kein Bereich ohne Schritt, kein Schritt ins Leere.

Der Stepper fuehrt durch den Ablauf, in dem ein Aufmass entsteht:
Plaene -> Raeume -> Positionen -> Zuordnung -> Export. Er blendet dabei
fremde Bereiche aus. Zwei Fehler sind dabei leicht zu machen und im Betrieb
schwer zu bemerken:

  1. Ein neuer Bereich wird gebaut, aber keinem Schritt zugeordnet.
     -> Er haengt entweder in JEDEM Schritt herum oder ist NIE erreichbar.
     (Genau das war bei der Zuordnungs-Matrix passiert.)
  2. Ein Schritt zeigt auf einen Selektor, den es in der Seite nicht gibt.
     -> Der Schritt ist leer, der Nutzer sieht eine weisse Flaeche.

Der Waechter liest die echten Dateien (kein Nachbau) und prueft die
Zuordnung ueber die DOM-Verschachtelung: ein Bereich gilt als erreichbar,
wenn er SELBST oder einer seiner Vorfahren in einem Schritt steht.
"""
import os
import re
import sys
from html.parser import HTMLParser

WURZEL = os.path.join(os.path.dirname(__file__), "..")
HTML = os.path.join(WURZEL, "public", "projekt.html")
JS = os.path.join(WURZEL, "public", "js", "upload.js")

# Bereiche, die im Ablauf vorkommen MUESSEN. Wer hier fehlt, ist entweder
# tot oder allgegenwaertig — beides ist ein Fehler.
PFLICHT = [
    "upload-section", "plans-section",              # 1 Pläne
    "nachzeichnen-section", "pruefliste",           # 2 Räume
    "mengen-board", "ml-board", "konf-kopf",        # 3 Positionen
    "aufmass-matrix", "raum-aufmass",               # 4 Zuordnung
    "wand-aufmass", "oeffnungs-aufmass",
    "eigene-position",
    "projekt-chat",                                 # 5 Export & Fragen
]


class Baum(HTMLParser):
    """Sammelt je id/class die Vorfahren-Kette (ids und Klassen)."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stapel = []          # [(ids, klassen)] der offenen Elemente
        self.ketten = {}          # id -> [selektoren der Vorfahren + selbst]
        self.ids = []             # alle ids in Reihenfolge (Doppel-Erkennung)
        self._leer = {"br", "img", "input", "hr", "meta", "link", "source"}

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        eid = a.get("id")
        kl = (a.get("class") or "").split()
        selbst = ([("#" + eid)] if eid else []) + ["." + k for k in kl]
        if eid:
            self.ids.append(eid)
            kette = []
            for s_ids, s_kl in self.stapel:
                kette += s_ids + s_kl
            self.ketten[eid] = kette + selbst
        if tag not in self._leer:
            self.stapel.append((["#" + eid] if eid else [], ["." + k for k in kl]))

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in self._leer and self.stapel:
            self.stapel.pop()

    def handle_endtag(self, tag):
        if tag not in self._leer and self.stapel:
            self.stapel.pop()


def gruppen_lesen():
    """WF_GRUPPEN aus upload.js lesen -> {schritt: [selektoren]}."""
    q = open(JS, encoding="utf-8").read()
    m = re.search(r"var WF_GRUPPEN = \{(.*?)\n  \};", q, re.S)
    assert m, "WF_GRUPPEN in upload.js nicht gefunden"
    out = {}
    for zeile in re.finditer(r"(\d+):\s*\[(.*?)\]", m.group(1), re.S):
        out[int(zeile.group(1))] = re.findall(r"'([^']+)'", zeile.group(2))
    return out


def knoepfe_lesen():
    """data-wf-Knoepfe aus projekt.html -> {schritt: beschriftung}."""
    h = open(HTML, encoding="utf-8").read()
    out = {}
    for m in re.finditer(r'data-wf="(\d+)"[^>]*>([^<]+)<', h):
        out[int(m.group(1))] = m.group(2).strip()
    return out


def run():
    baum = Baum()
    baum.feed(open(HTML, encoding="utf-8").read())
    gruppen = gruppen_lesen()
    knopf = knoepfe_lesen()

    print("WORKFLOW-SCHRITTE — Ablauf der App")
    print("=" * 88)
    for s in sorted(knopf):
        sel = gruppen.get(s, [])
        print(f"{s}  {knopf[s]:<22} {len(sel)} Bereich(e)  {', '.join(sel)[:44]}")
    print("=" * 88)

    fehler = []

    # 1) doppelte ids — brechen getElementById und damit jeden Renderer
    doppelt = {i for i in baum.ids if baum.ids.count(i) > 1}
    if doppelt:
        fehler.append(f"doppelte ids in projekt.html: {sorted(doppelt)}")

    # 2) jeder Schritt > 0 hat einen Knopf und umgekehrt
    for s in gruppen:
        if s not in knopf:
            fehler.append(f"Schritt {s} hat Bereiche, aber keinen Knopf")
    for s in knopf:
        if s > 0 and s not in gruppen:
            fehler.append(f"Knopf '{knopf[s]}' zeigt auf keine Bereiche (leerer Schritt)")

    # 3) jeder Selektor eines Schrittes existiert wirklich in der Seite
    h = open(HTML, encoding="utf-8").read()
    for s, sel in gruppen.items():
        for x in sel:
            da = (f'id="{x[1:]}"' in h) if x.startswith("#") else (x[1:] in h)
            if not da:
                fehler.append(f"Schritt {s}: '{x}' kommt in projekt.html nicht vor")

    # 4) DER KERN: jeder Pflicht-Bereich haengt an GENAU EINEM Schritt
    #    (selbst oder ueber einen Vorfahren)
    print(f"\n{'Bereich':<26}{'Schritt':>9}  Zuordnung ueber")
    print("-" * 88)
    for eid in PFLICHT:
        kette = baum.ketten.get(eid)
        if kette is None:
            fehler.append(f"'{eid}' gibt es in projekt.html gar nicht")
            print(f"{eid:<26}{'—':>9}  FEHLT")
            continue
        treffer = [(s, x) for s, sel in gruppen.items()
                   for x in sel if x in kette]
        if not treffer:
            fehler.append(f"'{eid}' haengt an KEINEM Schritt "
                          f"(waere in jedem Schritt sichtbar)")
            print(f"{eid:<26}{'—':>9}  KEIN SCHRITT")
            continue
        schritte = sorted({s for s, _ in treffer})
        if len(schritte) > 1:
            fehler.append(f"'{eid}' haengt an mehreren Schritten {schritte} — "
                          f"der spaetere versteckt ihn im frueheren")
        s, ueber = treffer[0]
        print(f"{eid:<26}{s:>9}  {ueber}{' (selbst)' if ueber == '#' + eid else ''}")
    print("-" * 88)

    if fehler:
        print("\nFEHLER:")
        for f in fehler:
            print(f"  ✗ {f}")
    else:
        print(f"\nWÄCHTER ok: {len(knopf) - 1} Schritte, {len(PFLICHT)} Pflicht-Bereiche "
              f"je genau einem Schritt zugeordnet, keine doppelten ids")
    assert not fehler, f"{len(fehler)} Workflow-Fehler"


if __name__ == "__main__":
    run()
