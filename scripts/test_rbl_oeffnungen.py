"""WÄCHTER: Rohbaulichte (RBL) — die zweite österreichische Öffnungs-Konvention.

Nutzer-Wunsch: „auch Fenster richtig erkennen". Gemessen ergab sich, dass
zwei der vier echten Pläne (AP.01, Velden) GAR KEINE Öffnungen lieferten —
nicht wenige, sondern null. Ursache: die Extraktion ankert ausschließlich
auf FPH (Fensterparapethöhe). Polierpläne beschriften Öffnungen aber mit
einem RBL-PAAR:

    RBL88        ← Breite 88 cm
    RBL2,24      ← Höhe 2,24 m

Die beiden Spans stehen 11–12 pt auseinander. Die Reihenfolge (erst Breite,
dann Höhe) ist am gerenderten Plan geprüft: die Hinweislinie des Paares
zeigt auf eine 88×224-Tür. Ein früher Versuch, die Zuordnung über das
nächste STUK aufzulösen, war falsch — das nächstgelegene STUK gehört oft
zu einer ANDEREN Öffnung mit eigener Hinweislinie (5 von 16 „eindeutig",
und die waren vertauscht).

Ohne Öffnung gibt es keinen ÖNORM-Abzug: Putz, Maler und Mauerwerk rechnen
dann mit der vollen Wandfläche. Das ist der teuerste Fehlertyp, weil die
Liste vollständig aussieht.

Zusagen:
  1. RBL-Paare werden zu Öffnungen mit BEIDEN Maßen (Fläche = Abzugsbasis).
  2. Höhe ≥ 1,90 m → Tür, darunter Fenster (am Korpus geprüft).
  3. Pläne mit FPH-Konvention bleiben UNVERÄNDERT — RBL ergänzt, ersetzt nie.
"""
import glob
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))

# (Muster, Label, min_fenster, min_tueren, "unverändert"-Erwartung)
PLAENE = [
    ("A-5_Einreichplan_Alfred-Angerer", "Angerer", 6, 5, True),
    ("AP.01 Layout-1 (1).pdf", "AP.01", 5, 22, False),
    ("AU_WM_01 Erdgeschoss_INDEX E.pdf", "WM", 24, 50, True),
    ("WA_Velden_Franzosen Allee_Ausführung_TG", "Velden", 0, 6, False),
]


def _spans(pg):
    out = []
    for b in pg.get_text("dict").get("blocks", []):
        if b.get("type") != 0:
            continue
        for l in b.get("lines", []):
            for s in l.get("spans", []):
                t = (s.get("text") or "").strip()
                if not t:
                    continue
                bb = tuple(s.get("bbox") or (0, 0, 0, 0))
                out.append({"text": t, "bbox": bb, "size": s.get("size", 0),
                            "cx": (bb[0] + bb[2]) / 2.0,
                            "cy": (bb[1] + bb[3]) / 2.0})
    return out


def run():
    import fitz
    import oeffnungen as OE
    print("RBL-ÖFFNUNGEN — Rohbaulichte als zweite Konvention")
    print("=" * 88)
    print(f"{'Plan':<12}{'Fenster':>9}{'m. Breite':>11}{'Türen':>8}"
          f"{'RBL-Quelle':>12}   Zusage")
    print("-" * 88)
    fehler = []
    gepr = 0
    for muster, lbl, min_f, min_t, unveraendert in PLAENE:
        g = sorted(glob.glob(os.path.expanduser(f"~/Downloads/*{muster}*")))
        if not g:
            print(f"{lbl:<12}  (Plan nicht in ~/Downloads)")
            continue
        gepr += 1
        doc = fitz.open(g[0])
        oe = OE.extract_oeffnungen_from_text(_spans(doc[0]), [])
        doc.close()
        fe = [o for o in oe if o.get("typ") == "fenster"]
        tu = [o for o in oe if o.get("typ") == "tuer"]
        mb = [o for o in fe if o.get("breite_m")]
        rbl = [o for o in oe if o.get("quelle") == "rbl"]
        ok = len(fe) >= min_f and len(tu) >= min_t
        if not ok:
            fehler.append(f"{lbl}: {len(fe)} Fenster / {len(tu)} Türen — "
                          f"erwartet mindestens {min_f} / {min_t}")
        if unveraendert and rbl:
            fehler.append(f"{lbl} nutzt die FPH-Konvention, bekam aber "
                          f"{len(rbl)} RBL-Öffnungen — RBL darf nur ERGÄNZEN")
        # jede RBL-Öffnung MUSS beide Maße tragen (sonst kein Abzug)
        ohne = [o for o in rbl if not (o.get("breite_m") and o.get("hoehe_m"))]
        if ohne:
            fehler.append(f"{lbl}: {len(ohne)} RBL-Öffnungen ohne vollständige "
                          f"Maße — ohne Fläche kein ÖNORM-Abzug")
        print(f"{lbl:<12}{len(fe):>9}{len(mb):>11}{len(tu):>8}{len(rbl):>12}   "
              f"{'✓' if ok else 'ZU WENIG'}")
        for o in rbl[:2]:
            print(f"{'':<12}   RBL: {o['breite_m']:.2f} × {o['hoehe_m']:.2f} m "
                  f"= {o['breite_m'] * o['hoehe_m']:.2f} m² → {o['typ']}")
    print("-" * 88)
    if gepr < 3:
        fehler.append(f"nur {gepr} Pläne geprüft — Aussage nicht belastbar")
    if fehler:
        print("FEHLER:")
        for f in fehler:
            print(f"  ✗ {f}")
    else:
        print("WÄCHTER ok: RBL-Paare liefern vollständige Öffnungsmaße, "
              "FPH-Pläne bleiben unverändert")
    assert not fehler, f"{len(fehler)} RBL-Fehler"


if __name__ == "__main__":
    run()
