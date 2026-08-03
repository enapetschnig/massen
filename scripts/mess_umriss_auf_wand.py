"""MESSUNG: taugt „Umriss liegt auf Wand" als zweiter Form-Beweis?

Ausgangslage (Nutzer-Befund am Bildschirm): „das einzige Bad, das komplett
richtig erkannt wird, sonst passt es eigentlich bei keinem Raum". Die App
zeigte trotzdem überwiegend Haken — weil FORM nur dort geprüft wurde, wo der
Plan einen UMFANG stempelt. Ohne U-Stempel blieb die Form ungeprüft, der
Umriss wurde aber trotzdem gezeichnet: eine Behauptung ohne Beleg.

Der Plan enthält die Wahrheit sichtbar: eine richtige Raumgrenze verläuft
ENTLANG der gezeichneten Wände. `raumnetz.umriss_auf_wand` misst genau das.

ERSTER ANLAUF WAR ZIRKULÄR — hier festgehalten, damit ihn niemand wiederholt:
als „schlecht" galt zuerst eine Flächen-Treue ≥20 %. Solche Umrisse GIBT ES
NICHT: `raum_regionen` wirft sie vorher weg. Der Korpus meldete 36 gute und
0 schlechte — eine Trennschärfe gegen eine leere Klasse ist keine Messung.

Jetzt zwei Wahrheiten, die vom Umriss-Gate UNABHÄNGIG sind und beide ohne
Referenzplan auskommen:
  LAGE-FEHLER   Der eigene Raumstempel liegt NICHT im eigenen Umriss.
                Dann ist der Umriss definitiv an der falschen Stelle.
  ÜBERLAPPUNG   Zwei Umrisse beanspruchen dieselbe Fläche. Zwei Räume können
                nicht am selben Ort sein — mindestens einer ist falsch.

Geprüft wird eine KONKRETE Regel, nicht eine Korrelation:
    Form gilt als bewiesen, wenn Flächen-Treue ≤ TREUE_MAX
    UND Umriss-auf-Wand ≥ WAND_MIN.
Gemessen wird, wie viele Räume die Regel neu bestätigt — und wie viele davon
nach den beiden Wahrheiten oben nachweislich falsch sind. Jeder einzelne
Fehltreffer ist ein grüner Haken auf einem falschen Umriss und damit ein K.o.

AUCH DIESE BEIDEN WAHRHEITEN REICHEN NICHT: sie verwarfen im ganzen Korpus
NULL Räume. Eine Präzision von 100 % gegen einen Test, der nie anschlägt,
ist keine Aussage — deshalb unten die Gegenprobe am gestempelten Umfang.

ERGEBNIS 2026-08-04: die Regel ist WIDERLEGT (80 % Präzision, 8 richtig /
2 falsch). Der Fehlermodus ist prinzipiell: richtige Fläche, falsche
Proportion. Details im Docstring von raumnetz.umriss_auf_wand. Dieses
Skript bleibt als Beleg und als Wächter gegen einen Wiederaufbau.
"""
import glob
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))
import fitz            # noqa: E402
import nachzeichnen    # noqa: E402

PLAENE = [
    "A-5_Einreichplan_Alfred-Angerer",
    "AP.01 Layout-1",
    "AU_WM_01 Erdgeschoss",
    "WA_Velden_Franzosen Allee_Ausführung_TG",
]
TREUE_MAX = 0.05      # Flächen-Treue gegen den byte-exakten Stempel
WAND_MIN = 0.85       # Anteil des Umrisses, der auf einer Wand liegt
ZACK_MAX = 1.25       # Polygon-Umfang / Bounding-Box-Umfang
UEBERLAPP_MIN = 0.10  # ab hier gilt eine Überlappung als echter Widerspruch


def _find(teil):
    for muster in (os.path.expanduser("~/Downloads/*.pdf"),
                   os.path.join(os.path.dirname(__file__), "fixtures", "*.pdf")):
        for p in glob.glob(muster):
            if teil.lower() in os.path.basename(p).lower():
                return p
    return None


def _poly_f(ps):
    a = 0.0
    for i in range(len(ps)):
        a += ps[i - 1][0] * ps[i][1] - ps[i][0] * ps[i - 1][1]
    return abs(a) / 2.0


def _drin(pt, poly):
    """Punkt-in-Polygon (Strahlverfahren)."""
    x, y = pt[0], pt[1]
    d = False
    for i in range(len(poly)):
        x1, y1 = poly[i - 1][0], poly[i - 1][1]
        x2, y2 = poly[i][0], poly[i][1]
        if (y1 > y) != (y2 > y) and y2 != y1:
            if x < x1 + (y - y1) * (x2 - x1) / (y2 - y1):
                d = not d
    return d


def _ueberlappung(a, b, n=22):
    """Anteil von a, der auch in b liegt — grob über ein Punktraster."""
    xs = [p[0] for p in a]
    ys = [p[1] for p in a]
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    if x1 <= x0 or y1 <= y0:
        return 0.0
    innen = beide = 0
    for jj in range(n):
        for ii in range(n):
            p = (x0 + (x1 - x0) * (ii + 0.5) / n, y0 + (y1 - y0) * (jj + 0.5) / n)
            if _drin(p, a):
                innen += 1
                if _drin(p, b):
                    beide += 1
    return (beide / float(innen)) if innen else 0.0


def run():
    print("UMRISS AUF WAND — bestätigt die Regel nur RICHTIGE Umrisse?")
    print(f"REGEL: Flächen-Treue ≤ {TREUE_MAX:.0%}  UND  auf Wand ≥ {WAND_MIN:.0%}")
    print("=" * 100)
    n_ges = n_regel = n_falsch = 0
    n_heute = n_neu = 0
    fehltreffer = []
    u_korpus, u_fehl = [], []
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
            print(f"  (kein Ergebnis: {(erg or {}).get('grund')})")
            continue
        meta = erg.get("meta") or {}
        raeume = erg.get("raeume") or []
        ptm, skala = meta.get("ptm"), meta.get("scale")
        mit = [r for r in raeume if r.get("umriss_wand") is not None
               and r.get("region_px") and r.get("f_m2") and r.get("px")]
        print(f"\n{os.path.basename(pf)[:58]}: {len(mit)} von {len(raeume)} "
              f"Räume mit messbarem Umriss")
        if not mit:
            continue
        print(f"   {'Raum':<24}{'Treue':>7}{'aufWand':>9}  {'Regel':<7}"
              f"{'zackig':>8}  {'Stempel':<9}Befund")
        for r in mit:
            poly = r["region_px"]
            f_poly = _poly_f(poly) / (skala * skala) / (ptm * ptm)
            treue = abs(f_poly - r["f_m2"]) / r["f_m2"]
            uw = r["umriss_wand"]
            # ZACKIGKEIT: Polygon-Umfang gegen den Umfang der eigenen
            # Bounding-Box. Ein normaler Raum liegt bei ~1,0-1,2; ein Umriss
            # mit Fransen/Buchten schiesst darueber hinaus, OHNE dass die
            # Flaeche auffaellt (Flaeche ist gegen Fransen unempfindlich).
            _xs = [q[0] for q in poly]; _ys = [q[1] for q in poly]
            _ubb = 2.0 * ((max(_xs) - min(_xs)) + (max(_ys) - min(_ys)))
            _upoly = sum(((poly[i][0] - poly[i - 1][0]) ** 2
                          + (poly[i][1] - poly[i - 1][1]) ** 2) ** 0.5
                         for i in range(len(poly)))
            zack = (_upoly / _ubb) if _ubb else 99.0
            regel = treue <= TREUE_MAX and uw >= WAND_MIN and zack <= ZACK_MAX
            # ── unabhängige Wahrheiten ──────────────────────────────────
            lage_ok = _drin(r["px"], poly)
            ovl = 0.0
            for o in mit:
                if o is r or not o.get("region_px"):
                    continue
                ovl = max(ovl, _ueberlappung(poly, o["region_px"]))
            falsch = (not lage_ok) or ovl >= UEBERLAPP_MIN
            # ── was die App HEUTE schon grün nennt ──────────────────────
            _uS, _uI = r.get("u_m"), (r.get("u_geometrie_poly")
                                      if r.get("u_geometrie_poly") is not None
                                      else r.get("u_ist"))
            heute = bool(r.get("iou_bewiesen") or r.get("rohbau_ok") or
                         (_uS and _uI is not None
                          and abs(_uI / _uS - 1) <= 0.15))
            n_ges += 1
            n_heute += 1 if heute else 0
            # Teilmenge mit harter Form-Wahrheit: der Plan stempelt U.
            if _uS and _uI is not None:
                _stimmt = abs(_uI / _uS - 1) <= 0.15
                u_korpus.append((regel, _stimmt))
                if regel and not _stimmt:
                    u_fehl.append(
                        f"{os.path.basename(pf)[:18]} / {r.get('name')}: "
                        f"U_Stempel {_uS:.2f} m, aus dem Umriss {_uI:.2f} m "
                        f"({(_uI / _uS - 1) * 100:+.0f}%)")
            if regel:
                n_regel += 1
                if not heute:
                    n_neu += 1
                if falsch:
                    n_falsch += 1
                    fehltreffer.append(
                        f"{os.path.basename(pf)[:18]} / {r.get('name')}: "
                        + ("Stempel liegt NICHT im Umriss"
                           if not lage_ok else f"überlappt zu {ovl:.0%}"))
            print(f"   {str(r.get('name'))[:23]:<24}{treue * 100:>6.1f}%"
                  f"{uw * 100:>8.1f}%  {'JA' if regel else '—':<7}"
                  f"{zack:>8.2f}  {('ok' if lage_ok else 'DANEBEN'):<9}"
                  + ("FEHLTREFFER" if (regel and falsch)
                     else ("neu bestätigt" if (regel and not heute) else "")))

    # ── DIE EIGENTLICHE PRÜFUNG ────────────────────────────────────────
    # Lage-Fehler und Überlappung haben im ganzen Korpus NULL Räume
    # verworfen — eine Präzision gegen einen Test, der nie anschlägt, ist
    # keine Aussage. Die einzige harte Wahrheit über die FORM ist der
    # byte-exakt gestempelte UMFANG. Auf der Teilmenge mit U-Stempel lässt
    # sich die Regel darum wirklich prüfen: sagt sie dort dasselbe wie der
    # Stempel, ist die Übertragung auf Räume OHNE Stempel begründet.
    print("\n" + "=" * 100)
    print("GEGENPROBE am gestempelten Umfang (die einzige harte Form-Wahrheit)")
    if not u_korpus:
        print("   kein Raum mit U-Stempel UND Umriss — Regel bleibt UNGEPRÜFT.")
    else:
        tp = sum(1 for x in u_korpus if x[0] and x[1])
        fp = sum(1 for x in u_korpus if x[0] and not x[1])
        fn = sum(1 for x in u_korpus if (not x[0]) and x[1])
        tn = sum(1 for x in u_korpus if (not x[0]) and not x[1])
        print(f"   {len(u_korpus)} Räume mit U-Stempel:")
        print(f"      Regel JA  & Umfang bestätigt : {tp:>3}   (richtig)")
        print(f"      Regel JA  & Umfang WIDERSPRICHT: {fp:>3}   (FEHLTREFFER)")
        print(f"      Regel NEIN & Umfang bestätigt : {fn:>3}   (verpasst)")
        print(f"      Regel NEIN & Umfang widerspricht: {tn:>3}   (richtig)")
        if tp + fp:
            print(f"   PRÄZISION gegen den Stempel: {tp / float(tp + fp):.0%}")
        for f in u_fehl[:6]:
            print(f"      ✗ {f}")

    print("\n" + "=" * 100)
    print(f"KORPUS: {n_ges} Räume mit Umriss auf 4 echten Plänen")
    print(f"   heute schon als Form bewiesen:      {n_heute}")
    print(f"   von der Regel bestätigt:            {n_regel}  "
          f"(davon {n_neu} NEU)")
    print(f"   davon nachweislich FALSCH:          {n_falsch}")
    for f in fehltreffer[:8]:
        print(f"      ✗ {f}")
    if n_regel:
        print(f"   PRÄZISION der Regel: {(n_regel - n_falsch) / n_regel:.1%}")
    print()
    if n_falsch:
        print("URTEIL: NICHT einbauen — die Regel setzt grüne Haken auf Umrisse,")
        print("        die nachweislich an der falschen Stelle liegen.")
    elif n_neu:
        print(f"URTEIL: tragfähig — {n_neu} Räume bekommen einen ehrlichen Beweis")
        print("        mehr, ohne einen einzigen nachweislich falschen Haken.")
    else:
        print("URTEIL: wirkungslos — die Regel bestätigt nichts, was nicht")
        print("        ohnehin schon bewiesen war.")


if __name__ == "__main__":
    run()
