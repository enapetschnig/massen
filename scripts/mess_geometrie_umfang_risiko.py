"""MESSUNG: wie verlässlich ist ein Umfang, den nur die Geometrie liefert?

Zwei Wege führen zum Raum-Umfang, und sie sind unterschiedlich sicher:

  U-STEMPEL   byte-exakt aus dem Text-Layer. `extract.py` fasst solche Räume
              ausdrücklich nicht an (`_verified["U"]` → continue).
  GEOMETRIE   aus dem rekonstruierten Polygon (`umfang_quelle = "geometrie"`),
              flächen-kalibriert — das Feld `u_geometrie`, genau wie
              `extract._plan_geo_umfaenge` es liest. Das ist der Normalfall
              auf Polierplänen ohne U-Angabe.

Am 2026-08-04 kam heraus, dass ein Polygon die RICHTIGE FLÄCHE bei FALSCHER
PROPORTION haben kann (WM-Loggia: 3,60 × 2,62 m gestempelt, 6,11 × 1,55 m
rekonstruiert). Wo ein U-Stempel existiert, fällt das auf — der Umriss wird
als „Form widerlegt" markiert und die MENGE nimmt ohnehin den Stempel.

Wo KEIN Stempel existiert, fällt es nicht auf, und der fehlerhafte Umfang
geht direkt in die Mengen: U × H ist die Wandabwicklung für Putz (LG 10),
Maler (LG 46) und den Sockel. Ein um 23 % zu großer Umfang ist ein um 23 %
zu großer Putz-Auftrag.

Diese Messung beziffert das Risiko ehrlich, in drei Zahlen:
  1. Wie viele Räume beziehen ihren Umfang NUR aus der Geometrie?
  2. Wie hoch ist die Fehlerquote der Geometrie DORT, WO sie prüfbar ist
     (Räume mit U-Stempel — die einzige harte Wahrheit)?
  3. Wie viel Wandfläche (U × H) hängt an ungeprüfter Geometrie?

Sie ist bewusst KEIN Wächter mit Schwelle: die Quote schwankt mit dem
Plan-Korpus. Sie ist die Kennzahl, an der eine Verbesserung sichtbar wird.
"""
import glob
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "api"))
import fitz            # noqa: E402
import nachzeichnen    # noqa: E402

PLAENE = [
    "A-5_Einreichplan_Alfred-Angerer",
    "AP.01 Layout-1",
    "AU_WM_01 Erdgeschoss",
    "WA_Velden_Franzosen Allee_Ausführung_TG",
]
TOL_U = 0.15        # ab hier widerspricht die Geometrie dem Stempel
H_ANNAHME = 2.60    # nur für die Größenordnung der betroffenen Wandfläche


def _find(teil):
    for p in glob.glob(os.path.expanduser("~/Downloads/*.pdf")):
        if teil.lower() in os.path.basename(p).lower():
            return p
    return None


def run():
    print("GEOMETRIE-UMFANG — wie verlässlich ist ein Umfang ohne Stempel?")
    print("=" * 96)
    print(f"{'Plan':<34}{'Räume':>6}{'U-Stempel':>10}{'nur Geo':>9}"
          f"{'Geo prüfbar':>12}{'davon falsch':>13}")
    print("-" * 96)
    G = {"n": 0, "stempel": 0, "geo": 0, "pruefbar": 0, "falsch": 0,
         "m2_geo": 0.0, "m2_falsch": 0.0}
    schlimm = []
    for teil in PLAENE:
        pf = _find(teil)
        if not pf:
            print(f"  (übersprungen, Datei fehlt: {teil})")
            continue
        doc = fitz.open(pf)
        try:
            erg = nachzeichnen.analysiere_doc(doc, max_px=1400)
        finally:
            doc.close()
        if not (erg or {}).get("ok"):
            continue
        raeume = erg.get("raeume") or []
        n = stempel = geo = pruefbar = falsch = 0
        for r in raeume:
            uS = r.get("u_m")
            # GENAU DAS FELD, DAS DIE PRODUKTION NIMMT. extract.py
            # `_plan_geo_umfaenge` liest `u_geometrie` (Flaechen-kalibriert),
            # NICHT `u_geometrie_poly` (roher Polygon-Umfang). Der Unterschied
            # ist klein, aber eine Risiko-Zahl, die ein anderes Feld misst als
            # die Produktion verwendet, beschreibt nicht die Produktion.
            uG = r.get("u_geometrie")
            n += 1
            if uS:
                stempel += 1
                if uG is not None:
                    # PRÜFBAR: hier kennen wir die Wahrheit und können die
                    # Geometrie an ihr messen. Das ist die einzige Stelle im
                    # ganzen Verfahren, an der das überhaupt geht.
                    pruefbar += 1
                    if abs(uG / uS - 1) > TOL_U:
                        falsch += 1
                        schlimm.append(
                            (os.path.basename(pf)[:16], r.get("name"),
                             uS, uG, (uG / uS - 1) * 100))
            elif uG is not None:
                # NUR GEOMETRIE: dieser Umfang geht ungeprüft in die Mengen.
                geo += 1
                G["m2_geo"] += uG * H_ANNAHME
        for k, v in (("n", n), ("stempel", stempel), ("geo", geo),
                     ("pruefbar", pruefbar), ("falsch", falsch)):
            G[k] += v
        q = (100.0 * falsch / pruefbar) if pruefbar else 0.0
        print(f"{os.path.basename(pf)[:33]:<34}{n:>6}{stempel:>10}{geo:>9}"
              f"{pruefbar:>12}{falsch:>9} ({q:.0f}%)")

    print("-" * 96)
    quote = (100.0 * G["falsch"] / G["pruefbar"]) if G["pruefbar"] else 0.0
    print(f"{'GESAMT':<34}{G['n']:>6}{G['stempel']:>10}{G['geo']:>9}"
          f"{G['pruefbar']:>12}{G['falsch']:>9} ({quote:.0f}%)")
    print()
    print(f"FEHLERQUOTE der Geometrie, wo sie prüfbar ist: {quote:.0f}% "
          f"({G['falsch']} von {G['pruefbar']})")
    for p, nm, uS, uG, ab in sorted(schlimm, key=lambda x: -abs(x[4]))[:6]:
        print(f"   {p:<18}{str(nm)[:20]:<22}Stempel {uS:>6.2f} m  →  "
              f"Geometrie {uG:>6.2f} m  ({ab:+.0f}%)")
    print()
    print(f"UNGEPRÜFT in den Mengen: {G['geo']} Räume beziehen ihren Umfang NUR")
    print(f"   aus der Geometrie — rund {G['m2_geo']:.0f} m² Wandabwicklung")
    print(f"   (U × {H_ANNAHME:.2f} m) für Putz, Maler und Sockel.")
    if G["pruefbar"] and G["geo"]:
        erw = G["geo"] * quote / 100.0
        print(f"   Träfe dort dieselbe Fehlerquote, wären das rund "
              f"{erw:.0f} Räume mit falschem Umfang —")
        print(f"   ohne dass der Plan es verraten könnte. Das ist eine "
              f"HOCHRECHNUNG, keine Messung:")
        print(f"   Räume ohne U-Stempel sind nicht dieselbe Grundgesamtheit "
              f"wie Räume mit.")
    print()
    print("Der Hebel ist damit klar benannt: nicht die Fläche (die stimmt),")
    print("sondern die PROPORTION des rekonstruierten Polygons.")


if __name__ == "__main__":
    run()
