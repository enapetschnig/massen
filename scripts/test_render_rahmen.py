"""WÄCHTER: das gerenderte Plan-Bild und die gezeichneten Koordinaten müssen
denselben Ursprung haben.

DER FEHLER, den dieser Wächter für immer festnagelt (23.08.2026, am hand-
gezogenen Korpus gefunden, adversarial 3/3 verifiziert):

`_view_bbox` zieht eine 4-m-Marge um den Grundriss. Bei 1:50 sind das 229 pt —
sitzt der oberste Raumstempel nur 187 pt unter der Blattkante, ragt die Box
über das Blatt hinaus (by0 = −42,8 pt). `page.get_pixmap(clip=…)` verschneidet
den Clip dann STILL mit `page.rect`: das Bild beginnt real bei y = 0, während
`to_px` weiter ab −42,8 pt rechnete. Folge: JEDE gezeichnete Koordinate —
Räume, Wände, Öffnungen, Fluchten und Raum-Stempel gleichermaßen — lag
71,6 px = 73 cm zu tief. Der Nutzer sah "die Raumerkennung funktioniert gar
nicht"; in Wahrheit war die Geometrie korrekt und nur der Rahmen falsch.

WARUM KEINE BESTEHENDE KENNZAHL DAS SAH: "Stempel liegt in der Region",
"Umriss auf einer Wand" und "Umriss auf einer Maßketten-Flucht" vergleichen
alle Geometrie mit Geometrie — und beide Seiten laufen durch dasselbe `to_px`.
Eine gemeinsame Verschiebung kürzt sich exakt heraus (`umriss_wand` war auf
dem kaputten Plan sogar 1,00). Jede Kennzahl dieses Typs ist gegen diesen
Fehler prinzipiell blind. Es braucht eine Referenz AUSSERHALB der Kette: das
Seitenrechteck.

GEPRÜFT WIRD DESHALB (beides ohne Handarbeit, auf jedem Plan):
  1. RAHMEN: Bildgröße == Render-Box × scale (±3 px für PyMuPDFs Aufrundung).
  2. EINBETTUNG: keine gezeichnete Koordinate liegt außerhalb des Bildes.
     Auf dem kaputten Plan reichten die Umrisse bis y = 1789 bei Bildhöhe
     1729 — ein Selbstwiderspruch, den nur diese Prüfung sieht.
  3. QUELLTEXT: die Render-Box wird auf page.rect gekappt und to_px benutzt
     ihren Ursprung (kein stiller Rückfall auf die Mess-Box).

Lauf: massenermittlung/venv/bin/python3 scripts/test_render_rahmen.py
"""
from __future__ import annotations

import os
import re
import sys

WURZEL = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# Beide Blätter des Referenzprojekts: A-5 (1:100, Box im Blatt) und AP.01
# (1:50, Box ragte über das Blatt) — der Wächter braucht beide Fälle.
PLAENE = [
    ("A-5 Einreichplan", "307be5ed-2ea7-4b4d-9018-bab138ea1425"),
    ("AP.01 Polierplan", "e595ff51-5d0a-44dd-ba22-13b8052423e5"),
]


def _env():
    pfad = os.path.join(WURZEL, "massenermittlung", ".env")
    werte = {}
    if os.path.exists(pfad):
        for zeile in open(pfad, encoding="utf-8"):
            if "=" in zeile and not zeile.strip().startswith("#"):
                k, _, v = zeile.strip().partition("=")
                werte[k] = v.strip().strip('"').strip("'")
    return (os.environ.get("SUPABASE_URL") or werte.get("SUPABASE_URL"),
            os.environ.get("SUPABASE_SERVICE_KEY") or werte.get("SUPABASE_SERVICE_KEY"))


def pruefe_quelltext():
    """Der Mechanismus selbst — läuft auch ohne Datenbank."""
    fehler = []
    src = open(os.path.join(WURZEL, "api", "nachzeichnen.py"), encoding="utf-8").read()

    if not re.search(r"rx0,\s*ry0\s*=\s*max\(bx0,\s*page\.rect\.x0\),\s*"
                     r"max\(by0,\s*page\.rect\.y0\)", src):
        fehler.append("Render-Box wird nicht mehr auf page.rect gekappt — "
                      "der 73-cm-Versatz kann zurückkehren")
    else:
        print("   Render-Box auf das Blatt gekappt (rx0/ry0)              ✓")

    if not re.search(r"def to_px\(x, y\):\s*\n\s*return \[round\(\(x - rx0\)", src):
        fehler.append("to_px rechnet nicht mit dem Render-Ursprung rx0/ry0 — "
                      "Bild und Koordinaten laufen wieder auseinander")
    else:
        print("   to_px benutzt den Render-Ursprung                       ✓")

    n_clip = len(re.findall(r"clip=_?f(?:itz|zl)\.Rect\(rx0, ry0, rx1, ry1\)", src))
    if n_clip < 2:
        fehler.append(f"nur {n_clip}/2 get_pixmap-Aufrufe clippen auf die "
                      f"Render-Box (Voll- UND Leicht-Pass müssen es tun)")
    else:
        print(f"   beide Render-Pfade clippen auf die Render-Box ({n_clip}/2)   ✓")

    if src.count('"box_pt": [round(rx0, 1)') < 2:
        fehler.append("meta['box_pt'] meldet nicht die Render-Box — Aufmaßblatt "
                      "und Frontend rechnen bildrelative Geometrie falsch zurück")
    else:
        print("   meta['box_pt'] meldet die Render-Box                    ✓")
    return fehler


def pruefe_plaene():
    """Rahmen + Einbettung am echten Plan — braucht Supabase.

    WICHTIG: NICHT über extract._nachzeichnen_roh laufen. Der Pfad liefert
    gecachte Ergebnisse (agent_log['nachzeichnen_cache']) und hat im
    Negativ-Test einen wieder eingebauten Bug NICHT gemeldet — der Wächter
    hätte den Cache geprüft statt den Code. analysiere_doc rechnet frisch.
    """
    url, key = _env()
    if not url or not key:
        print("   (übersprungen: keine Supabase-Zugangsdaten)")
        return []
    sys.path.insert(0, os.path.join(WURZEL, "api"))
    import fitz  # noqa: E402
    import nachzeichnen  # noqa: E402
    from supabase import create_client  # noqa: E402

    sb = create_client(url, key)
    fehler = []
    for name, pid in PLAENE:
        try:
            plan = sb.table("plaene").select("storage_path").eq(
                "id", pid).single().execute().data
            pdf = sb.storage.from_("plaene").download(plan["storage_path"])
            doc = fitz.open(stream=pdf, filetype="pdf")
            erg = nachzeichnen.analysiere_doc(doc, max_px=1800)
        except Exception as e:
            print(f"   {name}: Lauf fehlgeschlagen ({e!r}) — übersprungen")
            continue
        if not erg or not erg.get("ok"):
            print(f"   {name}: kein Grundriss — übersprungen")
            continue
        m = erg.get("meta") or {}
        box, sc = m.get("box_pt"), m.get("scale")
        bw, bh = erg.get("bild_w"), erg.get("bild_h")
        if not box or not sc or not bw:
            fehler.append(f"{name}: meta unvollständig")
            continue

        soll_w, soll_h = (box[2] - box[0]) * sc, (box[3] - box[1]) * sc
        if abs(bw - soll_w) > 3.0 or abs(bh - soll_h) > 3.0:
            fehler.append(f"{name}: Bild {bw}×{bh} px, aus box_pt erwartet "
                          f"{soll_w:.1f}×{soll_h:.1f} — der Clip wurde gekappt, "
                          f"jede Koordinate ist verschoben")
        else:
            print(f"   {name}: Rahmen stimmt ({bw}×{bh} px)".ljust(58) + "✓")

        # Einbettung: nichts Gezeichnetes darf aus dem Bild ragen.
        koords = []
        for r in erg.get("raeume") or []:
            koords += [(p[0], p[1]) for p in (r.get("region_px") or [])]
            if r.get("px"):
                koords.append((r["px"][0], r["px"][1]))
        for w in erg.get("waende") or []:
            px = w.get("px") or []
            if len(px) >= 4:
                koords += [(px[0], px[1]), (px[2], px[3])]
        if koords:
            # 2 px Luft für Rundung; grobe Ausreißer sind der echte Befund.
            raus = [(x, y) for x, y in koords
                    if x < -2 or y < -2 or x > bw + 2 or y > bh + 2]
            if raus:
                ymax = max(y for _, y in koords)
                fehler.append(f"{name}: {len(raus)} von {len(koords)} gezeichneten "
                              f"Punkten liegen ausserhalb des Bildes "
                              f"(max y {ymax:.0f} bei Bildhöhe {bh})")
            else:
                print(f"   {name}: alle {len(koords)} Punkte im Bild".ljust(58) + "✓")
    return fehler


def main():
    print("WÄCHTER Render-Rahmen — Bild und Koordinaten teilen den Ursprung\n")
    fehler = pruefe_quelltext()
    print()
    fehler += pruefe_plaene()
    print("\n" + "-" * 74)
    if fehler:
        print("FEHLER:")
        for f in fehler:
            print("  ✗", f)
        return 1
    print("WÄCHTER ok: Render-Box gekappt, to_px am Bildursprung, "
          "nichts liegt ausserhalb des Bildes.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
