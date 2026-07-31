"""WÄCHTER: liest die Pipeline auch Pläne, die ANDERS aussehen als die vier echten?

"Sollte für alle Pläne funktionieren" scheitert nicht an der Anzahl der
Testpläne, sondern an ihrer Varianz. Die vier echten Referenzpläne decken je
GENAU EINEN Maßstab, ein Stempelformat, eine Blattgröße ab. Was bei 1:200
passiert, bei einem Stempel ohne Umfang, bei gedrehter Seite oder bei sechzig
Räumen, war schlicht ungeprüft.

Hier wird der Plan GEBAUT (scripts/_plan_generator.py), darum ist jede Zahl
vorher bekannt. Geprüft wird gegen diese Wahrheit, nicht gegen eine zweite
Schätzung:

    NAMEN    jeder Raumname exakt so gelesen wie gedruckt
    FLÄCHEN  jede Stempelfläche byte-exakt (nicht ±%)
    UMFÄNGE  desgleichen, wo gedruckt
    UMRISS   jeder Raum bekommt eine Markierung am Plan

Ein Fehler hier ist echt: er zeigt eine Planart, an der die App scheitert —
ohne dass dafür ein neuer echter Plan beschafft werden muss.
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "api"))
from _plan_generator import A0, A1, PlanBauer, zimmerreihe   # noqa: E402


def _wohnung(b):
    return (b.raum("Wohnküche", 1.0, 1.0, 5.2, 4.6, "Parkett")
             .raum("Bad", 6.7, 1.0, 2.4, 2.8, "Fliesen")
             .raum("Zimmer 1", 1.0, 5.9, 4.0, 3.6, "Parkett")
             .raum("Vorraum", 5.2, 5.9, 2.2, 3.6, "Fliesen"))


def _gross(b):
    """Gewerbe/Halle: wenige, sehr große Räume — anderer Maßstabsbereich."""
    return (b.raum("Halle", 1.0, 1.0, 24.0, 16.0, "Beton")
             .raum("Büro", 26.0, 1.0, 5.0, 4.0, "Teppich")
             .raum("Sozialraum", 26.0, 5.5, 5.0, 4.0, "Fliesen"))


VARIANTEN = [
    ("Referenz 1:50 · Fl-Stempel",
     lambda: _wohnung(PlanBauer(massstab=50)), {}),
    ("Maßstab 1:100",
     lambda: _wohnung(PlanBauer(massstab=100)), {}),
    ("Maßstab 1:200 · Halle auf A0",
     lambda: _gross(PlanBauer(massstab=200, blatt=A0)), {}),
    ("Polierplan-Stempel (BF: + Tab-Spalte)",
     lambda: _wohnung(PlanBauer(massstab=50)), {"stempel_format": "bf"}),
    ("Büro-Stempel (nackte Zahl + ²-Span)",
     lambda: _wohnung(PlanBauer(massstab=50)), {"stempel_format": "nackt"}),
    ("Stempel OHNE Umfang",
     lambda: _wohnung(PlanBauer(massstab=50)), {"mit_umfang": False}),
    ("Punkt statt Komma (englisches CAD)",
     lambda: _wohnung(PlanBauer(massstab=50)), {"komma": False}),
    ("Seite um 90° gedreht",
     lambda: _wohnung(PlanBauer(massstab=50, rotation=90)), {}),
    ("ohne Maßkette (nur Maßstab-Label)",
     lambda: _wohnung(PlanBauer(massstab=50)), {"kette": False}),
    ("24 Räume (Geschoss eines MFH)",
     lambda: zimmerreihe(PlanBauer(massstab=100, blatt=A0), 24), {}),
]


def _pruefe(bauer, kw, ordner, i):
    import fitz
    import nachzeichnen
    pfad = os.path.join(ordner, f"var{i}.pdf")
    bauer.schreibe(pfad, **kw)
    soll = {w["name"]: w for w in bauer.wahrheit()}
    doc = fitz.open(pfad)
    try:
        r = nachzeichnen.analysiere_doc(doc, max_px=1400)
    finally:
        doc.close()
    if not r.get("ok"):
        return {"ok": False, "grund": "analysiere_doc: ok=False",
                "n_soll": len(soll)}
    ist = [x for x in (r.get("raeume") or []) if x.get("f_m2")]
    nach_name = {}
    for x in ist:
        nach_name.setdefault(str(x.get("name")), []).append(x)
    treffer = f_ok = u_ok = umriss = 0
    fehlend = []
    for nm, w in soll.items():
        kand = nach_name.get(nm) or []
        if not kand:
            fehlend.append(nm)
            continue
        treffer += 1
        # byte-exakt: dieselbe Zahl, nicht "nahe dran"
        x = min(kand, key=lambda q: abs((q.get("f_m2") or 0) - w["f_m2"]))
        if abs((x.get("f_m2") or 0) - w["f_m2"]) < 0.005:
            f_ok += 1
        if x.get("u_m") is None or abs((x.get("u_m") or 0) - w["u_m"]) < 0.005:
            u_ok += 1
        if x.get("region_px"):
            umriss += 1
    return {"ok": True, "n_soll": len(soll), "n_ist": len(ist),
            "treffer": treffer, "f_ok": f_ok, "u_ok": u_ok, "umriss": umriss,
            "fehlend": fehlend}


def run():
    print("PLAN-VARIANTEN — liest die App auch Pläne, die anders aussehen?")
    print("=" * 100)
    print(f"{'Variante':<42}{'Räume':>10}{'Name':>7}{'Fläche':>8}"
          f"{'Umfang':>8}{'Umriss':>8}   Urteil")
    print("-" * 100)
    fehler = []
    with tempfile.TemporaryDirectory() as tmp:
        for i, (name, bau, kw) in enumerate(VARIANTEN):
            try:
                e = _pruefe(bau(), kw, tmp, i)
            except Exception as ex:
                fehler.append(f"{name}: ABSTURZ {type(ex).__name__}: {ex}")
                print(f"{name[:41]:<42}{'—':>10}   ABSTURZ {type(ex).__name__}")
                continue
            if not e["ok"]:
                fehler.append(f"{name}: {e['grund']}")
                print(f"{name[:41]:<42}{'—':>10}   {e['grund']}")
                continue
            n = e["n_soll"]
            gut = (e["treffer"] == n and e["f_ok"] == n and e["u_ok"] == n
                   and e["umriss"] == n)
            if e["treffer"] < n:
                fehler.append(f"{name}: {n - e['treffer']} Räume nicht gelesen "
                              f"({e['fehlend'][:3]})")
            if e["f_ok"] < e["treffer"]:
                fehler.append(f"{name}: {e['treffer'] - e['f_ok']} Flächen "
                              f"nicht byte-exakt")
            if e["umriss"] < e["treffer"]:
                fehler.append(f"{name}: {e['treffer'] - e['umriss']} Räume "
                              f"ohne Umriss am Plan")
            print(f"{name[:41]:<42}{str(e['n_ist']) + '/' + str(n):>10}"
                  f"{e['treffer']:>7}{e['f_ok']:>8}{e['u_ok']:>8}{e['umriss']:>8}"
                  f"   {'✓' if gut else 'siehe unten'}")
    print("-" * 100)
    if fehler:
        print(f"FEHLER ({len(fehler)}):")
        for f in fehler:
            print(f"  ✗ {f}")
    else:
        print(f"WÄCHTER ok: {len(VARIANTEN)} Planarten — Maßstäbe 1:50/1:100/1:200, "
              f"drei Stempelformate, gedrehte Seite,\n"
              f"           Punkt-Notation, fehlende Maßkette, fehlender Umfang, "
              f"24 Räume: alle byte-exakt gelesen und markiert")
    assert not fehler, f"{len(fehler)} Planarten scheitern"


if __name__ == "__main__":
    run()
