"""MESSUNG/DIFF: welchen NAMEN bekommt jeder Stempel — und ändert ein Eingriff ihn?

Der Name entscheidet mehr, als er aussieht: nach ihm werden Gewerke zugeordnet
(Bad → Fliesen, Stiegenhaus → Estrich), Fenster verteilt und in der
Kreuztabelle gruppiert. Am WM-Plan hieß das Stiegenhaus 'Lift D' bzw.
'Lift E' — die Zeichnungsbeschriftung des Aufzugs stand auf derselben Zeile
wie der Flächenwert und schlug den echten Namen darüber.

Aufruf:
    mess_raumnamen.py            -> Namensliste ausgeben
    mess_raumnamen.py <datei>    -> gegen einen früheren Stand vergleichen
Der Stand wird immer nach scratchpad geschrieben, damit ein Vorher/Nachher
ohne Handarbeit möglich ist.
"""
import glob
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))
import fitz            # noqa: E402
import raumnetz        # noqa: E402

PLAENE = [
    "A-5_Einreichplan_Alfred-Angerer",
    "AP.01 Layout-1",
    "AU_WM_01 Erdgeschoss",
    "WA_Velden_Franzosen Allee_Ausführung_TG",
]


def _stand():
    """-> {plan: [(name, f_m2, u_m), ...]} — direkt aus dem Stempel-Leser."""
    st = {}
    for m in PLAENE:
        g = sorted(glob.glob(os.path.expanduser(f"~/Downloads/*{m}*.pdf")))
        if not g:
            continue
        doc = fitz.open(g[0])
        try:
            pg = doc[0]
            r = pg.rect
            # ganze Seite als Box — hier geht es nur um Namen, nicht um Lage
            sp = raumnetz.raum_stempel(pg, (r.x0, r.x1, r.y0, r.y1))
        finally:
            doc.close()
        st[os.path.basename(g[0])] = sorted(
            [(x.get("name"), x.get("f_m2"), x.get("u_m")) for x in sp],
            key=lambda t: (t[1] or 0, str(t[0])))
    return st


def run(vorher=None):
    st = _stand()
    ziel = os.path.join(
        os.environ.get("SCRATCH", "/tmp"), "raumnamen_stand.json")
    try:
        with open(ziel, "w", encoding="utf-8") as fh:
            json.dump(st, fh, ensure_ascii=False, indent=1)
    except OSError:
        ziel = None

    print("RAUMNAMEN je Stempel")
    print("=" * 92)
    alt = None
    if vorher and os.path.exists(vorher):
        with open(vorher, encoding="utf-8") as fh:
            alt = json.load(fh)

    ges = frag = 0
    for plan, rows in st.items():
        ges += len(rows)
        frag += sum(1 for n, _f, _u in rows if not n or n == "?")
        if alt is None:
            print(f"\n{plan}  ({len(rows)} Stempel)")
            for n, f, u in rows:
                print(f"   {str(n)[:30]:<32}{(f or 0):>8.2f} m²"
                      f"{('  U ' + format(u, '.2f') + ' m') if u else ''}")
            continue
        a = {(f, u): n for n, f, u in alt.get(plan, [])}
        diff = [(n, f, u, a.get((f, u))) for n, f, u in rows
                if (f, u) in a and a[(f, u)] != n]
        neu = [(n, f, u) for n, f, u in rows if (f, u) not in a]
        weg = [(n, f, u) for n, f, u in alt.get(plan, []) if (f, u) not in
               {(f2, u2) for _n2, f2, u2 in rows}]
        if not (diff or neu or weg):
            print(f"\n{plan}: unverändert ({len(rows)} Stempel)")
            continue
        print(f"\n{plan}: {len(diff)} umbenannt, {len(neu)} neu, {len(weg)} weg")
        for n, f, u, a_ in diff:
            print(f"   {(f or 0):>8.2f} m²   {str(a_)[:26]:<28} → {n}")
        for n, f, u in neu:
            print(f"   {(f or 0):>8.2f} m²   —  NEU → {n}")
        for n, f, u in weg:
            print(f"   {(f or 0):>8.2f} m²   {str(n)[:26]:<28} → FÄLLT WEG")

    print("\n" + "-" * 92)
    print(f"{ges} Stempel · {frag} ohne Namen ('?')")
    if ziel:
        print(f"Stand geschrieben: {ziel}")


if __name__ == "__main__":
    run(sys.argv[1] if len(sys.argv) > 1 else None)
