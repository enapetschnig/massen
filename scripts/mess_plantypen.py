"""MESSUNG Plan-Typ-Abdeckung: was macht die App mit WELCHER Art Dokument?

„Für alle Pläne funktionieren" heißt nicht „aus jedem Blatt Räume lesen" —
ein Schnitt hat keine Grundrissflächen, ein Ansichtsblatt keine Räume, ein
Katasterauszug gar kein Gebäude. Richtig ist: jedes Dokument bekommt die
Behandlung, die zu ihm passt, und wo nichts zu holen ist, sagt die App das
EHRLICH statt etwas zu erfinden.

Diese Messung führt genau das vor — je Dokument der erkannte Typ und das
Ergebnis. Rein lesend, kein API-Guthaben nötig.
"""
import glob
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))
import fitz            # noqa: E402
import nachzeichnen    # noqa: E402

DL = os.path.expanduser("~/Downloads")

# (Suchmuster, erwartete Behandlung) — die ERWARTUNG steht im Test, damit
# eine Verschlechterung auffällt (z.B. ein Grundriss, der plötzlich als
# Schnitt gilt, oder ein Beleg, der als Plan durchgeht).
KORPUS = [
    ("A-5_Einreichplan_Alfred-Angerer", "grundriss", "EFH-Einreichplan, F/U-Stempel"),
    ("AP.01 Layout-1", "grundriss", "Polierplan mit Installationen"),
    ("AU_WM_01 Erdgeschoss", "grundriss", "Großwohnbau, 70 Räume"),
    ("1762788650811_EG-Wand-Grundriss", "grundriss", "Holzbau-Wandgrundriss"),
    ("WA_Velden_Franzosen Allee_Ausführung_TG", "grundriss", "Tiefgarage, gedreht"),
    ("WA_Velden_Franzosen Allee_Ausführung_ Schnitt", "kein_grundriss", "Schnitt-Blatt"),
    ("05_AU.3.1.1 HAUS A SCH", "kein_grundriss", "Schnitt-Satz"),
    ("Mitterwurzerweg", "kein_grundriss", "Dach-Ansichten (Dach-Sektor liest die Flächen)"),
    ("7413-M-1-TPL", "kein_grundriss", "Katasterauszug, kein Gebäudeplan"),
    ("Leistungsschau_Folder", "kein_grundriss", "Werbe-Folder mit '1:00'"),
]


def _typ(pfad):
    """-> (typ, raeume, mit_umriss, grund)"""
    try:
        d = fitz.open(pfad)
    except Exception as e:
        return "crash", 0, 0, str(e)[:40]
    try:
        r = nachzeichnen.analysiere_doc(d, max_px=1200)
    except Exception as e:
        return "crash", 0, 0, str(e)[:40]
    if not r.get("ok"):
        return "kein_grundriss", 0, 0, (r.get("grund") or "")[:44]
    rs = r.get("raeume") or []
    mit = sum(1 for x in rs if (x.get("region_px") or []))
    if r.get("typ") == "scan":
        return "scan", len(rs), mit, "Bild-Plan (Vision)"
    if not rs:
        return "kein_grundriss", 0, 0, "keine Raum-Stempel"
    return "grundriss", len(rs), mit, ""


def run():
    print(f"{'Dokument':<40}{'erwartet':<15}{'gemessen':<15}{'Räume':>6}{'Umriss':>7}  Anmerkung")
    print("-" * 108)
    treffer = fehlt = abweichung = 0
    for muster, erwartet, was in KORPUS:
        g = sorted(glob.glob(os.path.join(DL, f"*{muster}*")))
        g = [x for x in g if x.lower().endswith(".pdf")]
        if not g:
            print(f"{muster[:38]:<40}{erwartet:<15}{'(Datei fehlt)':<15}")
            fehlt += 1
            continue
        typ, n, mit, grund = _typ(g[0])
        ok = (typ == erwartet) or (erwartet == "grundriss" and typ == "scan")
        if ok:
            treffer += 1
        else:
            abweichung += 1
        mark = "" if ok else "  ← ABWEICHUNG"
        print(f"{os.path.basename(g[0])[:38]:<40}{erwartet:<15}{typ:<15}"
              f"{n:>6}{mit:>7}  {was}{mark}")
    print("-" * 108)
    n_ges = treffer + abweichung
    print(f"{treffer}/{n_ges} Dokumente wie erwartet behandelt"
          + (f" · {fehlt} Datei(en) nicht vorhanden" if fehlt else ""))
    print("\nWAS DAS HEISST: Grundrisse liefern Räume mit Umriss; Schnitte,")
    print("Ansichten, Katasterauszüge und Werbe-Folder werden EHRLICH als")
    print("'kein Grundriss' abgewiesen statt Phantom-Mengen zu erfinden.")
    print("Dach-Ansichten liest der Dach-Sektor separat byte-exakt")
    print("(scripts/test_dach_positionen.py: 114,43 m² am selben Blatt).")

    assert n_ges >= 8, f"Korpus zu klein ({n_ges}) — Aussage nicht belastbar"
    assert abweichung == 0, f"{abweichung} Dokument(e) falsch behandelt"


if __name__ == "__main__":
    run()
