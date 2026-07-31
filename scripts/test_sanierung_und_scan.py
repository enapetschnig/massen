"""WÄCHTER: die zwei Plantypen, die unser echter Korpus NICHT enthält.

Ich habe geschrieben "gebaute Pläne decken Varianz ab, nicht Praxis" und drei
fehlende Typen aufgezählt. Zwei davon kann man sehr wohl bauen — und genau
das passiert hier, statt sie als unerreichbar stehen zu lassen:

  SANIERUNG   Umbauplan mit Farb-Legende (Neubau/Bestand/Abbruch). Der
              häufigste Plantyp auf dem Tisch eines Baubetriebs, und der
              gefährlichste: wird Bestand als Neubau gerechnet, steht die
              ganze Kalkulation falsch. Vier Fälle, weil beide Richtungen
              zählen — Alarm wenn nötig, KEIN Alarm wenn nicht.

  SCAN        Bildplan ohne Text-Layer. Muss sauber in den Scan-Modus
              fallen: das Bild rendern, ehrlich melden, dass der Maßstab
              fehlt — und niemals Phantom-Mengen erfinden.

Die Wahrheit steht in beiden Fällen vorher fest (Anzahl der Bauteile je
Klasse, Anzahl der Räume), darum wird gegen sie geprüft und nicht gegen eine
zweite Schätzung.
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "api"))
from _plan_generator import PlanBauer, sanierungsplan   # noqa: E402


def _sanierung(tmp, fehler):
    import fitz
    import farben
    print("SANIERUNG — Farb-Legende Neubau/Bestand/Abbruch")
    print("-" * 92)

    # 1) echter Umbauplan: Legende DA und Bauteile GEZEICHNET → Alarm
    w = sanierungsplan(os.path.join(tmp, "san.pdf"))
    doc = fitz.open(w["pfad"])
    leg = farben.lies_farb_legende(doc[0])
    erg = farben.analysiere_dokument(doc)
    doc.close()
    for wort, rgb in (("neubau", w["farben"]["Neubau"]),
                      ("bestand", w["farben"]["Bestand"]),
                      ("abbruch", w["farben"]["Abbruch"])):
        ist = (leg.get(wort) or {}).get("rgb")
        ok = ist is not None and all(abs(a - b) < 0.01 for a, b in zip(ist, rgb))
        print(f"   Legende {wort:<9} gebaut {rgb} → gelesen {ist}  "
              f"{'✓' if ok else 'FALSCH'}")
        if not ok:
            fehler.append(f"Sanierung: Legende '{wort}' als {ist} statt {rgb}")
    if not (erg.get("hat_bestand") and erg.get("hat_abbruch")):
        fehler.append(f"Sanierungsplan nicht als Umbau erkannt: "
                      f"bestand={erg.get('hat_bestand')} "
                      f"abbruch={erg.get('hat_abbruch')}")
    else:
        print(f"   Urteil: Bestand ✓ Abbruch ✓ · Hinweis steht "
              f"({len(erg.get('hinweis') or '')} Zeichen)")
    dbg = erg.get("_debug") or {}
    # die gebauten Anzahlen müssen sich wiederfinden (14 Bauteile + 1 Legende)
    if dbg.get("n_bestand_wort") != w["n"]["bestand"] + 1:
        fehler.append(f"Bestand-Wörter: {dbg.get('n_bestand_wort')} statt "
                      f"{w['n']['bestand'] + 1}")
    if dbg.get("n_abbruch_wort") != w["n"]["abbruch"] + 1:
        fehler.append(f"Abbruch-Wörter: {dbg.get('n_abbruch_wort')} statt "
                      f"{w['n']['abbruch'] + 1}")
    print(f"   Bauteil-Zählung: Bestand {dbg.get('n_bestand_wort')} "
          f"(gebaut {w['n']['bestand']}+1 Legende) · "
          f"Abbruch {dbg.get('n_abbruch_wort')} "
          f"(gebaut {w['n']['abbruch']}+1) ✓")

    # 2) REINER NEUBAU: kein Bestand, kein Abbruch → KEIN Alarm.
    # Das ist die wichtigere Hälfte: ein Fehlalarm auf einem Neubau lässt den
    # Kalkulanten an einer richtigen Massenermittlung zweifeln.
    b = PlanBauer(massstab=50)
    b.raum("Wohnküche", 1.0, 1.0, 5.2, 4.6).raum("Bad", 6.7, 1.0, 2.4, 2.8) \
     .raum("Zimmer 1", 1.0, 5.9, 4.0, 3.6)
    p2 = b.schreibe(os.path.join(tmp, "neubau.pdf"))
    doc = fitz.open(p2)
    e2 = farben.analysiere_dokument(doc)
    doc.close()
    if e2.get("hat_bestand") or e2.get("hat_abbruch") or e2.get("hinweis"):
        fehler.append(f"reiner Neubau fälschlich als Umbau geflaggt: {e2}")
    else:
        print("   reiner Neubau → kein Bestand/Abbruch, kein Hinweis ✓ (No-Op)")

    # 3) NUR LEGENDE, NICHTS GEZEICHNET (Plankopf-Boilerplate): kein Alarm.
    w3 = sanierungsplan(os.path.join(tmp, "boiler.pdf"),
                        n_bestand=0, n_abbruch=0)
    doc = fitz.open(w3["pfad"])
    e3 = farben.analysiere_dokument(doc)
    doc.close()
    if e3.get("hat_bestand") or e3.get("hat_abbruch"):
        fehler.append("Boilerplate-Legende ohne Bauteile löst Alarm aus — "
                      "genau das soll das Präzisions-Gate verhindern")
    else:
        print("   Legende ohne Bauteile → kein Alarm ✓ (Präzisions-Gate)")


def _scan(tmp, fehler):
    import fitz
    import nachzeichnen
    print("\nSCAN — Bildplan ohne Text-Layer")
    print("-" * 92)
    b = PlanBauer(massstab=50)
    b.raum("Wohnküche", 1.0, 1.0, 5.2, 4.6).raum("Bad", 6.7, 1.0, 2.4, 2.8) \
     .raum("Zimmer 1", 1.0, 5.9, 4.0, 3.6).raum("Vorraum", 5.2, 5.9, 2.2, 3.6)
    quelle = b.schreibe(os.path.join(tmp, "vektor.pdf"))
    n_soll = len(b.wahrheit())

    # in ein reines BILD-PDF verwandeln (kein Text mehr — wie ein Scan)
    src = fitz.open(quelle)
    pix = src[0].get_pixmap(matrix=fitz.Matrix(2.2, 2.2))
    src.close()
    ziel = fitz.open()
    seite = ziel.new_page(width=pix.width / 2.2, height=pix.height / 2.2)
    seite.insert_image(seite.rect, pixmap=pix)
    scan = os.path.join(tmp, "scan.pdf")
    ziel.save(scan)
    ziel.close()

    doc = fitz.open(scan)
    n_worte = len(doc[0].get_text("words"))
    try:
        r = nachzeichnen.analysiere_doc(doc, max_px=1400)
    except Exception as e:
        fehler.append(f"Scan bringt die Pipeline zum Absturz: "
                      f"{type(e).__name__}: {e}")
        doc.close()
        return
    doc.close()
    print(f"   Text-Layer: {n_worte} Wörter (echter Scan = 0)")
    if n_worte > 5:
        fehler.append(f"Testaufbau kaputt: das 'Scan'-PDF trägt noch "
                      f"{n_worte} Wörter — dann prüft der Fall nichts")
    rr = [x for x in (r.get("raeume") or []) if x.get("f_m2")]
    print(f"   Ergebnis: ok={r.get('ok')} · {len(rr)} Räume · "
          f"Grund: {str(r.get('grund'))[:52]}")
    # Die Zusage ist NICHT "der Scan wird gelesen" — das kann die Vektor-
    # Pipeline nicht. Die Zusage ist: kein Absturz, keine erfundenen Mengen,
    # und eine Antwort, mit der der Nutzer etwas anfangen kann.
    if rr:
        fehler.append(f"Scan ohne Text-Layer liefert {len(rr)} Räume mit "
                      f"Flächen — das wären erfundene Mengen "
                      f"(gebaut waren {n_soll})")
    else:
        print(f"   keine erfundenen Räume ✓ (gebaut waren {n_soll}, "
              f"ohne Text-Layer ist keiner davon lesbar)")
    if r.get("ok"):
        if not (r.get("basis_png") or r.get("bild_w")):
            fehler.append("Scan gilt als ok, liefert aber kein Bild — "
                          "der Nutzer sähe eine leere Fläche")
        else:
            print("   Bild wird gerendert ✓ (Nutzer kann den Maßstab setzen)")
    elif not r.get("grund"):
        fehler.append("Scan abgelehnt OHNE Begründung — der Nutzer weiß "
                      "nicht, was er tun soll")
    else:
        print("   ehrlich abgelehnt mit Begründung ✓")


def run():
    print("PLANTYPEN, DIE DER ECHTE KORPUS NICHT HAT")
    print("=" * 92)
    fehler = []
    with tempfile.TemporaryDirectory() as tmp:
        _sanierung(tmp, fehler)
        _scan(tmp, fehler)
    print("-" * 92)
    if fehler:
        print("FEHLER:")
        for f in fehler:
            print(f"  ✗ {f}")
    else:
        print("WÄCHTER ok: Sanierungsplan (Legende byte-exakt, Bauteile "
              "gezählt, Neubau ohne Fehlalarm,\n"
              "           Boilerplate abgefangen) und Scan ohne Text-Layer "
              "(kein Absturz, keine erfundenen Mengen)")
    assert not fehler, f"{len(fehler)} Plantyp-Fehler"


if __name__ == "__main__":
    run()
