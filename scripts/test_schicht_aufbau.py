"""WÄCHTER: mehrschichtige Wandaufbauten (Holzbau/WDVS) — Gesamtspanne statt Beplankung.

Der ÖNORM-Audit hielt als Kernbefund fest: "mehrschichtige Aufbauten
(Holzbau/WDVS) werden nachweislich falsch gepaart (6,95 m statt ~42 m)".
Die Ursache: ein Holzbau-Wandgrundriss zeichnet je Wand MEHRERE parallele
Linien (Beplankung innen, Ständer, Dämmung, Beplankung außen). Die
Wand-Paarung nahm das innerste Linienpaar und maß damit eine 3-cm-Platte
statt der 34-cm-Gesamtwand.

Der Fix ist im Code (nachzeichnen: Füllflächen-Gesamtspannen verdrängen
Schicht-Fehllesungen, zusätzlich additive Ergänzung), war aber NICHT
bewacht — genau die Konstellation, in der eine Kennzahl still zurückfällt.

Zusagen am ECHTEN Holzbau-Plan:
  1. Die Gesamtsumme aller Wandlängen bleibt im belegten Bereich (~74 m) —
     ein Rückfall auf die Beplankungs-Lesart (~7 m) muss rot werden.
  2. Die Schicht-Verdrängung greift nachweislich (Fehllesungen entfernt).
  3. Mindestens zwei verschiedene Wandstärken werden getrennt geführt
     (Außenwand-Aufbau vs. Innenwand) — sonst ist der Aufbau kollabiert.
"""
import glob
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))

MUSTER = "1762788650811_EG-Wand-Grundriss 01.pdf"


def run():
    import fitz
    import nachzeichnen
    print("SCHICHT-AUFBAU (Holzbau) — Gesamtspanne statt Beplankung?")
    print("=" * 78)
    g = sorted(glob.glob(os.path.expanduser(f"~/Downloads/*{MUSTER}")))
    if not g:
        print(f"(Holzbau-Plan '{MUSTER}' nicht in ~/Downloads — übersprungen)")
        return
    doc = fitz.open(g[0])
    r = nachzeichnen.analysiere_doc(doc, max_px=1400)
    doc.close()
    fehler = []
    if not r.get("ok"):
        print(f"  Plan nicht analysierbar: {r.get('grund')}")
        raise AssertionError("Holzbau-Plan fällt aus der Pipeline")

    summe = {str(k): float(v) for k, v in (r.get("summe_m") or {}).items()}
    ges = sum(summe.values())
    staerken = sorted(summe.items(), key=lambda kv: -kv[1])
    print(f"  Wandlängen je Stärke: "
          f"{', '.join(f'{k}cm {v:.2f}m' for k, v in staerken)}")
    print(f"  SUMME {ges:.2f} m   ·  {(r.get('meta') or {}).get('n_waende')} Wände")

    # 1) Gesamtsumme — der Beplankungs-Rückfall lag bei ~7 m
    if ges < 40.0:
        fehler.append(f"Wandlängen-Summe nur {ges:.2f} m — das ist die "
                      f"Beplankungs-Lesart (Schicht-Paarung gebrochen, "
                      f"belegt sind ~74 m)")
    # 2) mehrere Stärken getrennt geführt
    _echt = [k for k, v in summe.items() if v >= 3.0]
    if len(_echt) < 2:
        fehler.append(f"nur {len(_echt)} Wandstärke(n) ≥3 m — der "
                      f"Schichtaufbau ist zu EINER Stärke kollabiert")
    # 3) die dickste geführte Stärke muss ein echter Aufbau sein (≥30 cm),
    #    nicht eine einzelne Platte
    _max_cm = max((int(k) for k, v in summe.items() if v >= 3.0), default=0)
    if _max_cm < 30:
        fehler.append(f"dickste geführte Wand nur {_max_cm} cm — "
                      f"Gesamtspanne des Aufbaus nicht erkannt")
    else:
        print(f"  dickste geführte Wand: {_max_cm} cm (Gesamtspanne, "
              f"nicht Einzelschicht) ✓")

    print("-" * 78)
    if fehler:
        print("FEHLER:")
        for f in fehler:
            print(f"  ✗ {f}")
    else:
        print("WÄCHTER ok: Schichtaufbau wird als Gesamtspanne gemessen "
              "(Summe im belegten Bereich, Stärken getrennt)")
    assert not fehler, f"{len(fehler)} Schichtaufbau-Fehler"


if __name__ == "__main__":
    run()
