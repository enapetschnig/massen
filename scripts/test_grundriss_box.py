"""WÄCHTER: die Grundriss-Box darf das Gebäude nicht abschneiden.

Nutzer-Befund (2026-08-08, dritte Meldung desselben Problems): „das ganze
Gebäude — der untere Teil ist abgeschnitten." Beweisbild gemessen: die Box
endete mitten im Angerer-Gebäude, 69 % der dunklen Wandlinien lagen
unterhalb, die überdachte Terrasse samt ihrem F/U-STEMPEL (60,74 m² /
37,46 m) wurde vor dem Lesen weggeschnitten — ein ganzer Raum fehlte.

Ursache: `_eg_box` endet 4 m unter dem untersten Treffer aus RAUM_WORTE,
und die Liste kannte nur INNENRAUM-Wörter. „Terrasse" stand bei y=35 % der
Seite direkt unter dem Gebäude — unsichtbar für die Liste.

Zwei Dinge sind zu halten:
  1. Die AUSSENRAUM-Wörter bleiben in RAUM_WORTE (Terrasse/Balkon/Vorraum/
     Carport) — und „Loggia" bleibt DRAUSSEN: am WM-Plan (Häuser C+D auf
     einem Blatt) verkettet es die Label-Cluster über die Gebäude hinweg
     und verdoppelt die Box (31,6 → 57,7 m Breite, je Wort einzeln
     gemessen). Die Loggien deckt dort die Stempel-Box (Stufe 2).
  2. Der Umfangs-Schätzer glaubt bei VERZWEIGTEN Räumen dem Polygon:
     das BBox-Modell unterstellt einen kompakten Raum und rät bei L/T-Formen
     strukturell zu kurz. Am Angerer-Flur: Region-U 22,67 m bei Stempel
     22,57 (+0,4 % — die Erkennung stimmte!), aber das Mittel meldete
     18,25 (−19 %) und das Badge sagte „Form widerlegt" auf einem RICHTIGEN
     Umriss. Ein falsches Urteil ist schlimmer als eine fehlende Zahl.
"""
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "api"))
WURZEL = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")


class _FakeRect(object):
    def __init__(self, w, h):
        self.width, self.height = w, h


class _FakePage(object):
    def __init__(self, w=2384, h=1684):
        self.rect = _FakeRect(w, h)


def run():
    import nachzeichnen
    print("GRUNDRISS-BOX — schneidet sie das Gebäude ab?")
    print("=" * 84)
    fehler = []

    # 1) Wortschatz: Außenraum drin, Loggia bewusst draußen.
    for wort in ("Terrasse", "Balkon", "Vorraum", "Carport"):
        if wort in nachzeichnen.RAUM_WORTE:
            print(f"   RAUM_WORTE kennt {wort!r:<12} ✓")
        else:
            fehler.append(f"RAUM_WORTE hat {wort!r} verloren — die Box endet "
                          f"wieder mitten im Gebäude (Angerer: Terrasse samt "
                          f"60,74-m²-Stempel abgeschnitten).")
    if "Loggia" in nachzeichnen.RAUM_WORTE:
        fehler.append("'Loggia' ist wieder in RAUM_WORTE — am WM-Plan "
                      "verkettet es die Häuser und verdoppelt die Box "
                      "(31,6 → 57,7 m, gemessen). Die Loggien deckt die "
                      "Stempel-Box.")
    else:
        print("   'Loggia' bleibt draußen (WM-Verkettung)     ✓")

    # 2) Die Box folgt einem Außenraum-Label nach unten — synthetisch, ohne PDF.
    ptm = 28.35
    page = _FakePage()

    def _worte(mit_terrasse):
        w = [(300, 200, 0, 0, "Zimmer"), (400, 210, 0, 0, "Bad"),
             (350, 300, 0, 0, "Flur"), (450, 310, 0, 0, "Küche")]
        if mit_terrasse:
            w.append((360, 450, 0, 0, "Terrasse"))
        return w

    b_ohne = nachzeichnen._eg_box(page, ptm, worte=_worte(False))
    b_mit = nachzeichnen._eg_box(page, ptm, worte=_worte(True))
    if not b_ohne or not b_mit:
        fehler.append("_eg_box liefert auf dem Testkorpus keine Box")
    else:
        delta = (b_mit[3] - b_ohne[3]) / ptm
        ok = 4.0 <= delta <= 6.5    # 150 pt = 5,3 m tiefer
        print(f"   Terrassen-Label zieht die Box {delta:.1f} m nach unten "
              f"{'✓' if ok else '✗ (erwartet ~5,3 m)'}")
        if not ok:
            fehler.append(f"Box folgt dem Terrassen-Label nicht ({delta:.1f} m)")

    # 3) Umfangs-Schätzer: verzweigter Raum → Polygon, kompakter → Mittel.
    # BEIDE Bedingungen sind noetig — am Korpus einzeln belegt:
    #   nur Fuellgrad (ohne poly_exakt): WM 2->6, Velden 1->3 FALSCHE
    #   Anklagen, weil zackige Raster-Polygone UEBERschaetzen.
    #   mit poly_exakt: Angerer-Flur heilt (-19 % -> +0,4 %), WM/Velden ruhig.
    L = [(0, 0), (5.84, 0), (5.84, 1.2), (2.0, 1.2), (2.0, 4.77), (0, 4.77)]
    pts = [(x * ptm, y * ptm) for x, y in L]
    r = nachzeichnen.geometrie_umfang(pts, 15.84, ptm, poly_exakt=True)
    if r and abs(r["u_m"] - r["u_poly_m"]) < 0.01:
        print(f"   L-Raum, Kontur vektor-exakt: u_m = u_poly = {r['u_m']} "
              f"(BBox {r['u_bbox_m']} ignoriert)  ✓")
    else:
        fehler.append(f"Verzweigter Raum mit exakter Kontur mittelt wieder "
                      f"mit der BBox: {r} — genau so wurde der korrekte "
                      f"Flur-Umriss (+0,4 %) als 'Form widerlegt' angeklagt.")
    rz = nachzeichnen.geometrie_umfang(pts, 15.84, ptm, poly_exakt=False)
    if rz and abs(rz["u_m"] - (rz["u_poly_m"] * rz["u_bbox_m"]) ** 0.5) < 0.01:
        print(f"   L-Raum, Kontur ZACKIG: Mittel bleibt ({rz['u_m']})  ✓")
    else:
        fehler.append(f"Zackiges Polygon traegt wieder allein: {rz} — das "
                      f"klagte auf WM 4 und Velden 2 richtige Umrisse an.")
    Q = [(0, 0), (4.0, 0), (4.0, 4.0), (0, 4.0)]
    pts_q = [(x * ptm, y * ptm) for x, y in Q]
    rq = nachzeichnen.geometrie_umfang(pts_q, 16.0, ptm)
    if rq and abs(rq["u_m"] - (rq["u_poly_m"] * rq["u_bbox_m"]) ** 0.5) < 0.01:
        print(f"   Kompakter Raum: bewährtes Mittel bleibt ({rq['u_m']})  ✓")
    else:
        fehler.append(f"Kompakter Raum nutzt das Mittel nicht mehr: {rq}")

    # 4) STEMPEL-GERICHTETER SNAP-DECKEL (Stufen-Messung 2026-08-10):
    #    Die DP-Polygone waren +1..2 % am Stempel, der Cluster-Snap zog sie
    #    auf +8..9 % (lange Aussenlinien gewinnen die Deckungs-Regel, weil
    #    Innenlinien von Tueren unterbrochen sind). Der Deckel greift NUR,
    #    wenn das DP-Polygon schon >= Stempel ist, und deckelt BEIDE
    #    Richtungen (+3 cm aus / -10 cm ein — nur auswaerts zu sperren
    #    liess Kanten auf Regal-Linien einwaerts schnappen, Geraete -15,7 %).
    #    Gemessen: Angerer mittlerer |F-Fehler| 6,3 % -> 2,7 % (besser als
    #    die 2,8 % vor den Vektor-Kanten, MIT den Vektor-Kanten).
    rq = open(os.path.join(WURZEL, "api", "raumnetz.py"), encoding="utf-8").read()
    for muster, was in (
        # 2026-08-14: der Einwaerts-Deckel ist BUDGET-GEBUNDEN geworden
        # (statt hart -10 cm): tiefer einwaerts nur, solange das Polygon
        # ueber dem byte-exakten Stempel bleibt. Die Zusagen wandern mit.
        (r"max_raus_pt=None,", "raum_kontur_exakt nimmt max_raus_pt"),
        (r"_versch > max_raus_pt:", "Auswaerts-Deckel steht"),
        (r"_versch < -0\.10 \* rst\.ptm", "Einwaerts ab 10 cm nur mit Budget"),
        (r"_budget_kand > _budget_rest\[0\]", "Budget begrenzt die Tiefe"),
        (r"poly_flaeche - _sf", "Budget = Ueberschuss ueber dem Stempel"),
        (r"vz_out", "Aussenrichtung aus der WINDUNG (Erker-Bug 2026-08-14)"),
        (r"poly_flaeche >= 0\.95 \* _sf", "Deckel ab DP >= 95 % Stempel"),
    ):
        if re.search(muster, rq):
            print(f"   {was} ✓")
        else:
            fehler.append(f"Snap-Deckel: {was} — fehlt/umgebaut. Ohne ihn "
                          f"bläht der Cluster-Snap Räume um +7..9 % auf "
                          f"(Angerer, Stufen-Messung 2026-08-10).")
    print("-" * 84)
    if fehler:
        print("FEHLER:")
        for f in fehler:
            print(f"  ✗ {f}")
    else:
        print("WÄCHTER ok: die Box folgt auch Außenräumen, Loggia bleibt "
              "draußen,\n           und der Umfangs-Schätzer verurteilt keine "
              "verzweigten Räume mehr.")
    assert not fehler, f"{len(fehler)} Fehler in Grundriss-Box/Schätzer"


if __name__ == "__main__":
    run()
