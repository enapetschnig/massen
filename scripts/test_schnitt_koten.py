"""WÄCHTER: Schnitt-/Ansichtspläne liefern nicht mehr NICHTS.

Gemessen über 12 verschiedene Pläne (`mess_plankorpus_breit.py`): vier
davon sind Schnitte und Ansichten, und die lieferten bis 2026-08-02
überhaupt nichts ("keine Raumstempel"). Dabei geht die Geschosshöhe in
JEDE Wandfläche ein — Putz (LG 10), Maler (LG 46), Mauerwerk (LG 08). Sie
stammte aus einer KI-Bildlesung, während dieselbe Zahl byte-exakt im
Text-Layer daneben steht (Velden-Schnitt 38 Höhenkoten, Haus A 76).

DIE ZUSAGE IST NICHT "wir kennen die Geschosshöhe". Sie ist:
  1. Auf einem Schnitt wird der MASSSTAB aus den Koten abgeleitet — und
     der ist die Selbstprüfung: eine maßstäbliche Zeichnung MUSS die
     Beziehung Kote ≈ a·y + b erfüllen. Beide Korpus-Schnitte sind 1:50;
     die Ableitung muss das auf ±5 % treffen, ohne es zu wissen.
  2. Auf einem GRUNDRISS darf nichts herauskommen. Das ist die härtere
     Hälfte: dort reihen sich Raumhöhen-Koten (+2,04 / +2,20) zufällig
     auf und ergaben im Versuch 937 bzw. 1757 pt/m. Ein Blatt ohne
     Schnitt darf keine Höhen behaupten.
  3. Die Marken-Zuordnung (KG/EG/OG/DG → Kote) ist die SCHWÄCHERE Quelle
     und muss sich selbst verwerfen, wenn sie unstimmig ist.

Drei einfachere Verfahren sind gemessen und unzureichend — nicht erneut
bauen: „Kote neben der Geschoss-Marke" (ordnet dem EG +2,80 zu),
„häufigste Differenz 2,2–4,5 m" (Haus A klar 2,86 m, Velden 2,50 und 3,30
gleichauf), „linearer Fit über ALLE Koten" (R² = 0,008 / 0,612, weil ein
Blatt mehrere Schnitte mit eigenen Nullpunkten trägt).
"""
import glob
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "api"))

# (Muster, Label, erwartet_schnitt, erwarteter Maßstab 1:N oder None)
PLAENE = [
    ("WA_Velden_Franzosen Allee_Ausführung_ Schnit", "Velden-Schnitt", True, 50),
    ("05_AU.3.1.1 HAUS A SCH", "Haus A Schnitt", True, 50),
    ("A-5_Einreichplan_Alfred-Angerer", "Angerer (Grundriss)", False, None),
    ("AP.01 Layout-1 (1).pdf", "AP.01 (Grundriss)", False, None),
    ("AU_WM_01 Erdgeschoss_INDEX E.pdf", "WM (Grundriss)", False, None),
    ("WA_Velden_Franzosen Allee_Ausführung_TG", "Velden TG (Grundriss)", False, None),
]


def run():
    import fitz
    import schnitt as SCH
    print("SCHNITT-KOTEN — Maßstab und Höhen byte-exakt aus dem Text-Layer")
    print("=" * 96)
    print(f"{'Plan':<26}{'Koten':>7}{'Gruppe':>8}{'Maßstab':>10}"
          f"{'Niveaus':>9}{'GH':>4}   Zusage")
    print("-" * 96)
    fehler = []
    gepr = 0
    for muster, lbl, soll, ms_soll in PLAENE:
        g = sorted(glob.glob(os.path.expanduser(f"~/Downloads/*{muster}*")))
        if not g:
            print(f"{lbl:<26}  (nicht in ~/Downloads)")
            continue
        gepr += 1
        doc = fitz.open(g[0])
        e = SCH.lies_schnitt(doc[0])
        doc.close()
        ist = bool(e)
        ok = ist == soll
        if not ok:
            fehler.append(
                f"{lbl}: Schnitt erkannt={ist}, erwartet {soll}"
                + (f" — behauptet {e.get('massstab_label')} aus "
                   f"{e.get('n_gruppe')} Koten" if e else ""))
        if e and ms_soll:
            # Maßstab MUSS stimmen — er ist die Selbstprüfung der Methode.
            n = int(str(e["massstab_label"]).split(":")[1])
            if abs(n - ms_soll) / ms_soll > 0.05:
                fehler.append(f"{lbl}: Maßstab {e['massstab_label']} statt "
                              f"1:{ms_soll} — die Geraden-Anpassung trägt nicht")
                ok = False
        if e:
            # Marken-Zuordnung muss in sich stimmig sein oder leer.
            _mk = sorted((e.get("geschoss_marken") or {}).values())
            for i in range(len(_mk) - 1):
                if not (SCH.GH_MIN_M <= round(_mk[i + 1] - _mk[i], 2)
                        <= SCH.GH_MAX_M):
                    fehler.append(f"{lbl}: Geschoss-Marken unstimmig "
                                  f"({_mk}) — hätten verworfen werden müssen")
                    ok = False
                    break
            # Jede ausgewiesene Geschosshöhe muss im Bauwerks-Bereich liegen.
            for _h in (e.get("geschosshoehen_m") or []):
                if not (SCH.GH_MIN_M <= _h <= SCH.GH_MAX_M):
                    fehler.append(f"{lbl}: Geschosshöhe {_h} m außerhalb "
                                  f"{SCH.GH_MIN_M}–{SCH.GH_MAX_M} m")
                    ok = False
            print(f"{lbl:<26}{e['n_koten']:>7}{e['n_gruppe']:>8}"
                  f"{e['massstab_label']:>10}{len(e['niveaus_m']):>9}"
                  f"{len(e['geschosshoehen_m']):>4}   {'✓' if ok else 'FALSCH'}")
            print(f"{'':<26}   {SCH.hinweis(e)[:150]}")
        else:
            print(f"{lbl:<26}{'—':>7}{'—':>8}{'—':>10}{'—':>9}{'—':>4}   "
                  f"{'✓ (kein Schnitt)' if ok else 'FALSCH'}")
    print("-" * 96)
    if gepr < 4:
        fehler.append(f"nur {gepr} Pläne geprüft — Aussage nicht belastbar")
    if fehler:
        print("FEHLER:")
        for f in fehler:
            print(f"  ✗ {f}")
    else:
        print("WÄCHTER ok: beide Schnitte liefern 1:50 aus ihren eigenen Koten "
              "(Selbstprüfung),\n           alle vier Grundrisse liefern "
              "nichts — kein Blatt behauptet Höhen, die es nicht trägt")
    assert not fehler, f"{len(fehler)} Schnitt-Fehler"


if __name__ == "__main__":
    run()
