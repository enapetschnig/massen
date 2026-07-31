"""MESSUNG: welche Stempel-Schreibweisen liest die App — und welche nicht?

Ein fremder Polierplan lässt sich nicht erfinden; seine Eigenheit IST die
fremde Konvention. Was sich aber sehr wohl durchspielen lässt, sind die
Schreibweisen selbst. Unsere vier echten Pläne decken vier davon ab:

    Fl: 10,53 m²        Einreichplan (Angerer)
    BF:  ⇥ 10,53 m²     Polierplan, Tab-Spalte (AP.01)
    10,53 m + ²-Span    Bürokonvention (AU_WM)
    F: / U: rotiert     ArchiCAD-Export (Velden)

Hier werden zusätzlich Schreibweisen geprüft, für die der Leser NICHT gebaut
wurde — bewusst, denn nur so entsteht eine ehrliche Karte statt einer
Selbstbestätigung. Ein Fehlschlag ist hier kein Defekt, sondern ein
gemessener Rand: er sagt, welchen Plan ein Nutzer heute NICHT hochladen kann.

Das Ergebnis ist eine Grenze, keine Behauptung.
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "api"))

# (Beschreibung, Zeilen des Stempels, ist_bekannt)
# {F} wird durch "12,34" ersetzt, {U} durch "14,20"
KONVENTIONEN = [
    ("Fl: {F} m²  (Einreichplan)",        ["Zimmer", "Fl: {F} m²", "U: {U} m"], True),
    ("F: {F} m²",                          ["Zimmer", "F: {F} m²", "U: {U} m"], True),
    ("BF: {F} m²  (Polierplan)",           ["Zimmer", "BF: {F} m²", "U: {U} m"], True),
    ("nackt {F} m + ²-Span  (Büro)",       ["Zimmer", "@NACKT", "U: {U} m"], True),
    # ── ab hier NICHT gebaut, bewusst geprüft ────────────────────────────
    ("Fläche: {F} m²",                     ["Zimmer", "Fläche: {F} m²", "U: {U} m"], False),
    ("NF: {F} m²  (Nutzfläche)",           ["Zimmer", "NF: {F} m²", "U: {U} m"], False),
    ("WNF {F} m²  (Wohnnutzfläche)",       ["Zimmer", "WNF {F} m²", "U: {U} m"], False),
    ("{F} qm  (qm statt m²)",              ["Zimmer", "{F} qm", "U: {U} m"], False),
    ("F = {F} m²  (Gleichheitszeichen)",   ["Zimmer", "F = {F} m²", "U: {U} m"], False),
    ("Fl.: {F} m2  (Punkt + m2)",          ["Zimmer", "Fl.: {F} m2", "U: {U} m"], False),
    ("A: {F} m²  (A für Area)",            ["Zimmer", "A: {F} m²", "U: {U} m"], False),
    ("U vor F (Reihenfolge getauscht)",    ["Zimmer", "U: {U} m", "Fl: {F} m²"], False),
    ("NAME IN VERSALIEN",                  ["ZIMMER", "Fl: {F} m²", "U: {U} m"], True),
    ("Name RECHTS neben dem Wert",         ["@RECHTS", "Fl: {F} m²", "U: {U} m"], True),
]

F_WERT, U_WERT = 12.34, 14.20


def _plan(pfad, zeilen):
    """Ein Blatt mit VIER identisch aufgebauten Stempeln (verschiedene Flächen)."""
    import fitz
    doc = fitz.open()
    pg = doc.new_page(width=2384, height=1684)
    ptm = 2835.0 / 50
    pg.insert_text((100, 60), "M 1:50", fontsize=11)
    soll = []
    for i in range(4):
        f = round(F_WERT + i * 3.11, 2)
        u = round(U_WERT + i * 1.07, 2)
        soll.append((f, u))
        x = 200 + (i % 2) * 520
        y = 200 + (i // 2) * 380
        # Wandrahmen, damit die Seite wie ein Grundriss aussieht
        pg.draw_rect(fitz.Rect(x - 60, y - 60, x + 300, y + 220),
                     color=(0.35, 0.35, 0.35), width=6)
        zy = y
        for z in zeilen:
            if z == "@NACKT":
                t = f"{f:.2f}".replace('.', ',') + " m"
                pg.insert_text((x, zy), t, fontsize=9)
                pg.insert_text((x + 4.6 * len(t), zy - 2), "²", fontsize=6)
            elif z == "@RECHTS":
                pg.insert_text((x + 120, zy), "Zimmer", fontsize=9)
            else:
                t = (z.replace("{F}", f"{f:.2f}".replace('.', ','))
                      .replace("{U}", f"{u:.2f}".replace('.', ',')))
                pg.insert_text((x, zy), t, fontsize=9)
            zy += 13
    doc.save(pfad)
    doc.close()
    return soll


def _streutreffer(tmp):
    """EIN fremder Anker auf einem Plan im Büro-Format darf nicht alles löschen.

    Das war eine echte Falle: der Anker-Zweig schaltete den Fallback-Zweig ab,
    sobald er IRGENDETWAS fand. Beim Versuch, 'WNF' als Anker aufzunehmen,
    fiel der WM-Plan von 77 Stempeln auf 5 — vier Wohnungs-Summenstempel
    verdrängten 77 echte Räume. Dieselbe Falle stellt jeder Plankopf, der
    irgendwo ein einzelnes 'Fläche:' oder 'NF:' trägt.

    Hier steht sie als Fall im Wächter: vier Räume im Büro-Format (nackte
    Zahl + ²-Span) plus EIN 'Fläche: 999,00 m²' im Plankopf.
    """
    import fitz
    import raumnetz
    pfad = os.path.join(tmp, "streu.pdf")
    doc = fitz.open()
    pg = doc.new_page(width=2384, height=1684)
    pg.insert_text((100, 60), "M 1:50", fontsize=11)
    # der Streutreffer im Plankopf
    pg.insert_text((1900, 60), "Fläche: 999,00 m²", fontsize=9)
    soll = []
    for i in range(4):
        f = round(12.34 + i * 3.11, 2)
        soll.append(f)
        x, y = 200 + (i % 2) * 520, 200 + (i // 2) * 380
        pg.draw_rect(fitz.Rect(x - 60, y - 60, x + 300, y + 220),
                     color=(0.35, 0.35, 0.35), width=6)
        pg.insert_text((x, y), "Zimmer", fontsize=9)
        t = f"{f:.2f}".replace('.', ',') + " m"
        pg.insert_text((x, y + 13), t, fontsize=9)
        pg.insert_text((x + 4.6 * len(t), y + 11), "²", fontsize=6)
    doc.save(pfad)
    doc.close()
    doc = fitz.open(pfad)
    r = doc[0].rect
    st = raumnetz.raum_stempel(doc[0], (r.x0, r.x1, r.y0, r.y1))
    doc.close()
    gefunden = sum(1 for f in soll
                   if any(abs((x.get("f_m2") or 0) - f) < 0.005 for x in st))
    print(f"\nSTREUTREFFER-FALLE: 4 Büro-Stempel + 1 'Fläche:' im Plankopf")
    print(f"   {len(st)} Stempel gelesen, davon {gefunden}/4 der echten Räume")
    return gefunden, len(soll)


def run():
    import raumnetz
    import fitz
    print("STEMPEL-KONVENTIONEN — welche Schreibweise liest die App?")
    print("=" * 96)
    print(f"{'Schreibweise':<40}{'gebaut für':>12}{'gelesen':>10}"
          f"{'F exakt':>9}{'U exakt':>9}   ")
    print("-" * 96)
    bekannt_ok = bekannt_n = fremd_ok = fremd_n = 0
    fehlend = []
    with tempfile.TemporaryDirectory() as tmp:
        for i, (name, zeilen, bekannt) in enumerate(KONVENTIONEN):
            p = os.path.join(tmp, f"k{i}.pdf")
            soll = _plan(p, zeilen)
            doc = fitz.open(p)
            r = doc[0].rect
            st = raumnetz.raum_stempel(doc[0], (r.x0, r.x1, r.y0, r.y1))
            doc.close()
            f_ok = sum(1 for (f, _u) in soll
                       if any(abs((x.get("f_m2") or 0) - f) < 0.005 for x in st))
            u_ok = sum(1 for (_f, u) in soll
                       if any(abs((x.get("u_m") or 0) - u) < 0.005 for x in st))
            if bekannt:
                bekannt_n += 1
                bekannt_ok += 1 if f_ok == 4 else 0
            else:
                fremd_n += 1
                fremd_ok += 1 if f_ok == 4 else 0
                if f_ok < 4:
                    fehlend.append(name)
            print(f"{name[:39]:<40}{'ja' if bekannt else 'NEIN':>12}"
                  f"{len(st):>10}{f_ok:>7}/4{u_ok:>7}/4"
                  f"   {'✓' if f_ok == 4 else '—'}")
        _sg, _ss = _streutreffer(tmp)
    print("-" * 96)
    print(f"BEKANNTE Schreibweisen  {bekannt_ok}/{bekannt_n} vollständig gelesen")
    print(f"FREMDE  Schreibweisen   {fremd_ok}/{fremd_n} vollständig gelesen")
    if fehlend:
        print(f"\nWAS EIN NUTZER HEUTE NICHT HOCHLADEN KANN ({len(fehlend)}):")
        for f in fehlend:
            print(f"   ✗ {f}")
        print("\nDas ist die gemessene Grenze — keine Behauptung, keine Ausrede.")
    # ZUSAGE: die vier Schreibweisen unserer echten Pläne MÜSSEN sitzen.
    # Für die fremden gibt es bewusst KEINE Zusicherung — sie sind die Karte,
    # nicht das Versprechen. Ein Wächter, der sie erzwingt, würde nur dazu
    # führen, dass man Muster nachstopft statt zu verstehen.
    assert bekannt_ok == bekannt_n, (
        f"nur {bekannt_ok}/{bekannt_n} der BEKANNTEN Stempel-Schreibweisen "
        f"gelesen — das ist eine Regression an den echten Plänen")
    # Und die Falle, die 77 Raeume gekostet haette:
    assert _sg == _ss, (
        f"Streutreffer-Falle offen: EIN fremder Anker im Plankopf laesst nur "
        f"{_sg} von {_ss} echten Raumstempeln uebrig — genau so fiel der "
        f"WM-Plan im Versuch von 77 auf 5")


if __name__ == "__main__":
    run()
