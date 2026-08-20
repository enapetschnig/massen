"""WÄCHTER: Glasfront-Anker (Portal-Beschriftungen) — Erkennungs-Session 2026-08-13.

Der Befund, den dieser Wächter konserviert: die Hebe-Schiebe-Türen der
Angerer-Wohnküche sind mit "FPH 2,75 / STUK +2,20" beschriftet — STUK unter
FPH, als Fenster unplausibel (Höhe −0,55 m). Der alte Parser verwarf sie
kommentarlos, und damit fehlte der Front-Versiegelung genau der Anker an der
Glasfront, durch die der Watershed in die Terrasse flutet (WK +9,7 % Zellen).

Drei Zusagen werden festgenagelt:
1. Portal-Beschriftungen (STUK − FPH < 0 bei FPH ≥ 2 m) werden NICHT
   verworfen, sondern als typ='glasfront' exportiert.
2. Sie sind KEIN Bauteil: kein hoehe_m, und nachzeichnen exportiert sie
   NICHT ans Frontend (dort würden sie als Phantom-Türen gezählt).
3. Ein normales Fenster (STUK > FPH) bleibt ein Fenster — die Portal-Regel
   darf den Normalfall nicht anfassen.

Dazu die Standard-Sicherung: FRONT_SEAL bleibt hinter dem Schalter, der
Front-Pfad in raumnetz akzeptiert 'glasfront' als Anker-Typ.
"""
import os
import re
import sys

WURZEL = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, os.path.join(WURZEL, "api"))


def _spans(paare):
    """Baut Text-Spans wie aus get_text('dict'): [("FPH 2,75", x, y), …]"""
    return [{"text": t, "bbox": (x, y, x + 20, y + 6), "size": 3.0,
             "cx": x + 10, "cy": y + 3} for (t, x, y) in paare]


def run():
    import oeffnungen as O
    print("GLASFRONT-ANKER — Portal-Beschriftung wird Anker, kein Phantom-Bauteil")
    print("=" * 78)
    fehler = []

    # 1) Portal-Label (Angerer-Wortlaut): STUK unter FPH → glasfront-Anker.
    res = O.extract_oeffnungen_from_text(
        _spans([("FPH 2,75", 100, 100), ("STUK +2,20", 100, 106)]), [])
    gf = [o for o in res if o.get("typ") == "glasfront"]
    fen = [o for o in res if o.get("typ") == "fenster"]
    if len(gf) != 1 or fen:
        fehler.append(f"Portal-Label: {len(gf)} glasfront / {len(fen)} fenster "
                      f"— erwartet 1/0. Ohne den Anker bleibt die Glasfront "
                      f"unversiegelbar (WK +9,7 % Zellen).")
    else:
        print(f"   FPH 2,75/STUK +2,20 → 1 glasfront-Anker, 0 Fenster   ✓")
        if gf[0].get("hoehe_m") is not None:
            fehler.append("glasfront hat hoehe_m — sie ist Anker, kein Bauteil")
        else:
            print("   Anker ohne hoehe_m (kein Bauteil)                    ✓")

    # 2) Niedrige Widersprüche (FPH < 2 m) bleiben verworfen — das sind
    #    Tippfehler/Fremdlabels, keine Portale.
    res2 = O.extract_oeffnungen_from_text(
        _spans([("FPH 1,00", 100, 100), ("STUK +0,80", 100, 106)]), [])
    if any(o.get("typ") == "glasfront" for o in res2):
        fehler.append("FPH 1,00/STUK 0,80 wurde glasfront — die Portal-Regel "
                      "greift nur bei FPH ≥ 2 m, sonst adelt sie Tippfehler")
    else:
        print("   FPH 1,00/STUK +0,80 bleibt verworfen (kein Portal)   ✓")

    # 3) Normalfall unangetastet: echtes Fenster bleibt Fenster.
    res3 = O.extract_oeffnungen_from_text(
        _spans([("FPH 0,90", 100, 100), ("STUK +2,20", 100, 106),
                ("1,30", 100, 112)]), [])
    fen3 = [o for o in res3 if o.get("typ") == "fenster"]
    if len(fen3) != 1:
        fehler.append(f"Normalfenster FPH 0,90/STUK 2,20: {len(fen3)} Fenster "
                      f"statt 1 — die Portal-Regel hat den Normalfall verändert")
    else:
        print("   FPH 0,90/STUK +2,20 bleibt ein normales Fenster       ✓")

    # 3b) RPH-FENSTER (Befund 2026-08-14): "RPH 85 / STUK +2,14" — die
    #     rohe Parapethoehe. rph_spans wurden seit jeher gesammelt und NIE
    #     verwendet; das Speis-Fenster blieb unverschlossen (+15,5 %).
    res4 = O.extract_oeffnungen_from_text(
        _spans([("RPH 85", 100, 100), ("STUK +2,14", 100, 106),
                ("1,40", 100, 112)]), [])
    fen4 = [o for o in res4 if o.get("typ") == "fenster"]
    if len(fen4) != 1:
        fehler.append(f"RPH 85/STUK 2,14: {len(fen4)} Fenster statt 1 — "
                      f"RPH-beschriftete Fenster fallen wieder unter den Tisch")
    else:
        print("   RPH 85/STUK +2,14 wird ein Fenster                    ✓")
    # FPH und RPH am SELBEN Fenster: nur EIN Fenster (Dubletten-Schutz).
    res5 = O.extract_oeffnungen_from_text(
        _spans([("FPH 0,90", 100, 100), ("RPH 85", 100, 103),
                ("STUK +2,20", 100, 106), ("1,30", 100, 112)]), [])
    fen5 = [o for o in res5 if o.get("typ") == "fenster"]
    if len(fen5) != 1:
        fehler.append(f"FPH+RPH am selben Fenster: {len(fen5)} Fenster — "
                      f"Dublette zaehlt doppelt in Mengen und Aufmass")
    else:
        print("   FPH+RPH am selben Fenster: genau EIN Fenster          ✓")

    # 3c) OG-Fenster mit ABSOLUTER Sturzkote ("RPH 85 / STUK +5,54",
    #     Hoehe 4,69 m unplausibel): das Fenster existiert — es wird
    #     GLASFRONT-ANKER (dichtet die Nische), aber KEIN Fenster mit
    #     erfundener Hoehe in den Mengen.
    res6 = O.extract_oeffnungen_from_text(
        _spans([("RPH 85", 100, 100), ("STUK +5,54", 100, 106)]), [])
    gf6 = [o for o in res6 if o.get("typ") == "glasfront"]
    fen6 = [o for o in res6 if o.get("typ") == "fenster"]
    if len(gf6) != 1 or fen6:
        fehler.append(f"RPH 85/STUK +5,54: {len(gf6)} glasfront / "
                      f"{len(fen6)} fenster — erwartet 1/0 (Anker ja, "
                      f"Bauteil mit erfundener Hoehe nein)")
    else:
        print("   RPH 85/STUK +5,54 (absolut) → Anker, kein Bauteil     ✓")

    # 3d) BODENTIEFES Element mit absoluter Kote ("RPH 0 / STUK +5,59"):
    #     glasfront-Anker — Elternbad lief sonst zur Glaslinie (+9,1 %).
    res7 = O.extract_oeffnungen_from_text(
        _spans([("RPH 0", 100, 100), ("STUK +5,59", 100, 106)]), [])
    gf7 = [o for o in res7 if o.get("typ") == "glasfront"]
    if len(gf7) != 1:
        fehler.append(f"RPH 0/STUK +5,59: {len(gf7)} glasfront — das "
                      f"bodentiefe OG-Element verliert seinen Siegel-Anker")
    else:
        print("   RPH 0/STUK +5,59 (bodentief absolut) → Anker          ✓")
    # 4) Quelltext-Zusagen: raumnetz akzeptiert den Anker-Typ, FRONT_SEAL
    #    bleibt geschaltet, nachzeichnen exportiert ihn nicht ans Frontend.
    rn = open(os.path.join(WURZEL, "api", "raumnetz.py"), encoding="utf-8").read()
    nz = open(os.path.join(WURZEL, "api", "nachzeichnen.py"), encoding="utf-8").read()
    # Der pauschale TUER-Fall-C bleibt DRAUSSEN (Suite-Rotlauf 2026-08-20:
    # Tuer-Dichtung 32->29 dicht). Wiederaufnahme nur mit engerem Gate
    # UND gruener Tuer-Dichtung.
    if '"glasfront", "tuer"' in rn:
        fehler.append("Tuer-Fall-C ist zurueck in _ist_parapet — er machte "
                      "3 Tueren undicht (Suite-Rotlauf); nur mit engerem "
                      "Gate und gruener Tuer-Dichtung wieder aufnehmen")
    else:
        print("   pauschaler Tuer-Fall-C bleibt draussen                ✓")
    if not re.search(r'in \("fenster", "glasfront"\)', rn):
        fehler.append("raumnetz: glasfront ist kein Front-Anker mehr")
    else:
        print("   raumnetz nimmt glasfront als Front-Anker              ✓")
    # Seit 2026-08-14 STANDARD AN (Korpus: Sadiku 5,0->4,4, Bad WC
    # geheilt, Angerer unveraendert) — abschaltbar muss es bleiben.
    if 'os.environ.get("FENSTER_SEAL", "1") != "0"' not in rn:
        fehler.append("FENSTER_SEAL nicht Standard-an-mit-Ausschalter — "
                      "entweder wieder stumm-gated (Sadiku verliert 0,6 pp) "
                      "oder Notausstieg weg")
    else:
        print("   FENSTER_SEAL Standard an, FENSTER_SEAL=0 schaltet ab   ✓")
    nz2 = open(os.path.join(WURZEL, "api", "nachzeichnen.py"),
               encoding="utf-8").read()
    if 'os.environ.get("MASSPAAR_ANKER", "1") != "0"' not in nz2:
        fehler.append("MASSPAAR_ANKER nicht Standard-an-mit-Ausschalter")
    else:
        print("   MASSPAAR_ANKER Standard an, =0 schaltet ab            ✓")
    if "_wanddist" not in nz2:
        fehler.append("Masspaar-Anker ohne Wand-Abstandsfilter — dann wird "
                      "jede Masskettenzahl ein Fenster")
    else:
        print("   Masspaar nur AUF der Wand (Massketten fallen durch)   ✓")
    if "_vzr * _tief" not in rn:
        fehler.append("Flucht-Schub fehlt — der Balken saesse wieder an der "
                      "Anker-Zeile AUSSEN an der Nische (gemessen wirkungslos: "
                      "der Raum flutet die Nische bis zum Balken)")
    else:
        print("   Balken wird an die innere Wandflucht geschoben        ✓")
    if 'os.environ.get("FRONT_SEAL")' not in rn:
        fehler.append("FRONT_SEAL-Schalter entfernt — Front-Siegel wäre "
                      "ungeprüft aktiv (Korpus-Messung steht aus)")
    else:
        print("   FRONT_SEAL bleibt hinter dem Schalter                 ✓")
    if not re.search(r'typ.*==\s*"glasfront":\s*\n.*#', nz) and \
       'o.get("typ") == "glasfront"' not in nz:
        fehler.append("nachzeichnen exportiert glasfront ans Frontend — "
                      "dort würde sie als Phantom-Tür gezählt und gezeichnet")
    else:
        print("   nachzeichnen hält den Anker vom Frontend fern         ✓")

    print("-" * 78)
    if fehler:
        print("FEHLER:")
        for f in fehler:
            print(f"  ✗ {f}")
    else:
        print("WÄCHTER ok: der Anker existiert, ist kein Bauteil, und der "
              "Schalter steht.")
    assert not fehler, f"{len(fehler)} Glasfront-Anker-Fehler"


if __name__ == "__main__":
    run()
