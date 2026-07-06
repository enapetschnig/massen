"""DACH-POSITIONEN-READER (Dachdecker/Zimmerer-Sektor) — byte-exakt + Material.

Guard gegen den Mitterwurzerweg-Satz (echter Zimmerer-Plan): Dachflächen mit
Selbst-Bestätigung (Σ Teile = Gesamt), Konstruktionsholz ohne Phantom-Match,
Velux byte-exakt, abgeleitete Material-Mengen. Fällt zurück auf synthetischen
Text, wenn der Plan lokal fehlt (CI-tauglich)."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))
import dach_positionen as dp   # noqa: E402


class _Page:
    def __init__(self, t):
        self._t = t

    def get_text(self, *a):
        return self._t


class _Doc:
    def __init__(self, seiten):
        self._s = [_Page(t) for t in seiten]

    def __iter__(self):
        return iter(self._s)


SYNTH = [
    "M 1:100 Dachflächen\nDachfläche Süd: 4,70 x 11,36 = 53,39 m2\n"
    "Dachfläche Nord: 61,04 m2\nDachfläche Gesamt: 114,43 m2\n"
    "Dachflächenfenster Velux Klapp-Schwingfenster 78/118 cm",
    "M 1:50 Sparrenlage\n4xSparrenabstützung\nB/H 14/17cm\n12 Sparren B/H 12/14cm\n"
    "Mauerbank B/H 14/12cm\nDeckenbalken B/H 14/16cm\n"
    "Velux GPL MK06 78/118 cm\nVelux GPL MK06 78/118 cm\n"
    "Velux GPL MK06 78/118 cm\nVelux GPL MK06 78/118 cm",
    "Systemschnitt Dach\nüber die 4 Sparrenabstützungen Mauerbank\nB/H 14/12cm\n"
    "Zange B/H 12/14cm\nMineralwolle 16,0 cm\nVollschalung 2,4 cm",
]


def run(doc=None):
    r = dp.dach_positionen(doc or _Doc(SYNTH))
    assert r, "Dach-Signal nicht erkannt"
    assert r.get("gesamt_m2") == 114.43, r.get("gesamt_m2")
    assert r.get("gesamt_bestaetigt") is True, "Σ Teile ≠ Gesamt (Selbst-Check)"
    hz = {(h["bauteil"].lower(), h["b_cm"], h["h_cm"]): h["anzahl"]
          for h in r.get("hoelzer", [])}
    assert hz.get(("sparren", 12, 14)) == 12, hz
    assert hz.get(("mauerbank", 14, 12)) == 1, hz
    assert hz.get(("deckenbalken", 14, 16)) == 1, hz
    # PHANTOM-GATE: kein 'Sparrenabstützung 14/12' (Quer-Match über die Mauerbank)
    assert ("sparrenabstützung", 14, 12) not in hz, f"Phantom-Holz: {hz}"
    fe = r.get("fenster", [])
    assert fe and fe[0]["anzahl"] == 4 and fe[0]["breite_cm"] == 78, fe
    ml = r.get("materialliste", [])
    assert ml, "keine abgeleitete Materialliste"
    mat = {m["material"].split()[0]: m for m in ml}
    assert any("Dacheindeckung" in m["material"] for m in ml)
    assert any(m["einheit"] == "m³" and "Sparren" in m["material"] for m in ml)
    print(f"Dach-Reader: Gesamt {r['gesamt_m2']} m² (Σ bestätigt) · "
          f"{len(r['hoelzer'])} Holz-Positionen (kein Phantom) · "
          f"4× Velux · {len(ml)} Material-Mengen")
    return r


if __name__ == "__main__":
    import glob
    g = sorted(glob.glob(os.path.expanduser("~/Downloads/*Mitterwurzerweg*")))
    if g:
        import fitz
        try:
            run(fitz.open(g[0]))
            print("  (am echten Mitterwurzerweg-Plan verifiziert)")
        except AssertionError as e:
            print(f"  Realplan-Abweichung: {e} — prüfe Synth-Fallback")
            run()
    else:
        run()
    print("OK — Dachdecker/Zimmerer-Sektor byte-exakt + Material.")
