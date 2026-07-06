"""WÄCHTER Edge-Case-Robustheit: 'für alle Pläne' heißt auch — NIE crashen,
immer eine ehrliche, handlungsleitende Meldung. Synthetische Härtefälle."""
import glob
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))
import fitz            # noqa: E402
import nachzeichnen    # noqa: E402


def run():
    # 1) Leere Seite → ehrliches ok=False
    d = fitz.open(); d.new_page(width=595, height=842)
    r = nachzeichnen.analysiere_doc(d)
    assert r.get("ok") is False and r.get("grund")

    # 2) Scan (nur Bild) → handlungsleitende Scan-Meldung
    d2 = fitz.open(); p2 = d2.new_page(width=2384, height=1684)
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 100, 100), False)
    p2.insert_image(fitz.Rect(0, 0, 2384, 1684), pixmap=pix)
    r2 = nachzeichnen.analysiere_doc(d2)
    assert r2.get("ok") is False and "Scan" in (r2.get("grund") or "")

    # 3) Null-Seiten-PDF → kein Crash
    r3 = nachzeichnen.analysiere_doc(fitz.open())
    assert r3.get("ok") is False

    # 4) A4-Brief → ehrliches ok=False
    d5 = fitz.open(); p5 = d5.new_page(width=595, height=842)
    p5.insert_text((50, 100), "Sehr geehrte Damen und Herren, Rechnung Nr. 123")
    r5 = nachzeichnen.analysiere_doc(d5)
    assert r5.get("ok") is False

    # 4b) UNGÜLTIGER MASSSTAB '1:00'/'1:0' (Robustheits-Sweep: ein Werbe-Folder
    # trug '1:00' → 2835/0 = ZeroDivisionError-Crash). Muss ehrlich ✗, kein Crash.
    import vektor    # noqa: E402
    assert vektor._label_ptm("1:0") is None
    assert vektor._label_ptm("1:00") is None
    assert vektor._label_ptm("1:50") is not None   # echter Maßstab bleibt gültig
    d6 = fitz.open(); p6 = d6.new_page(width=842, height=595)
    p6.insert_text((50, 100), "Leistungsschau 1:00 Programm 2025")
    r6 = nachzeichnen.analysiere_doc(d6)   # darf NICHT crashen
    assert r6.get("ok") is False

    # 5) Rotierte Seite eines ECHTEN Plans → funktioniert weiterhin
    g = sorted(glob.glob(os.path.expanduser(
        "~/Downloads/*A-5_Einreichplan_Alfred-Angerer*")))
    if g:
        d3 = fitz.open(g[0]); d3[0].set_rotation(90)
        r4 = nachzeichnen.analysiere_doc(d3)
        assert r4.get("ok") is True, "rotierter Plan muss analysierbar bleiben"

    print("OK — Edge-Cases: leer/Scan/0-Seiten/Brief ehrlich ✗ ohne Crash, "
          "Scan-Meldung handlungsleitend, 90°-rotierter Plan ✓")


if __name__ == "__main__":
    run()
