"""MESSUNG: läuft die Erkennung auf ALLEN Plänen — nicht nur auf den vier Referenzen?

Jede Kennzahl dieses Projekts stand bisher auf vier Plänen. "Sollte für alle
Pläne funktionieren" lässt sich daraus nicht behaupten. Dieses Skript nimmt
JEDEN Plan, den es findet (Seitenformat ≥ 1200 pt = Planformat, keine
Dokumente), schickt ihn durch dieselbe Pipeline wie die Produktion und misst,
was herauskommt.

Gemessen wird pro Plan:
    Stempel     wie viele Raumstempel byte-exakt gelesen wurden
    Umriss      wie viele davon einen Umriss am Plan bekommen (Abdeckung)
    Treue       Median |Polygonfläche − Stempelfläche| / Stempelfläche
    Freifläche  wie viele als Geländefläche ausgesortiert wurden
    Zeit        Laufzeit — ein Plan, der 5 Minuten braucht, ist in der App tot

Ein Plan ohne Stempel ist KEIN Fehler: Schnitte, Ansichten und Lagepläne
tragen keine Raumstempel. Der Unterschied zwischen "nichts zu holen" und
"kaputt" ist genau das, was hier sichtbar werden soll — darum wird jeder Plan
eingeordnet statt nur gezählt.

Lauf:  massenermittlung/venv/bin/python3 scripts/mess_plankorpus_breit.py [N]
       (N = höchstens N Pläne, für einen schnellen Durchlauf)
"""
import glob
import json
import math
import multiprocessing as mp
import os
import statistics
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))

MIN_PLAN_PT = 1200.0     # kleiner ist ein Dokument, kein Plan
# Produktion (vercel.json) erlaubt 600 s je Aufruf. Hier wird bei 540 s
# abgebrochen, damit ein Plan, der die Grenze reißt, als solcher erscheint —
# und nicht der Messlauf ewig hängt.
TIMEOUT_S = 540
LANGSAM_S = 300.0        # ab hier ist ein Plan in der Bedienung unzumutbar
GRENZE_S = 480.0         # darüber ist er in Produktion nicht mehr sicher


def _poly_f(ps):
    a = 0.0
    for i in range(len(ps)):
        a += ps[i - 1][0] * ps[i][1] - ps[i][0] * ps[i - 1][1]
    return abs(a) / 2.0


def _einer(pfad):
    """Einen Plan durch die Pipeline schicken -> Ergebnis-dict (nie Exception)."""
    t0 = time.time()
    erg = {"datei": os.path.basename(pfad), "ok": False, "grund": None,
           "stempel": 0, "umriss": 0, "frei": 0, "treue": None,
           "sek": 0.0, "seiten": 0, "format": None}
    try:
        import fitz
        import nachzeichnen
        doc = fitz.open(pfad)
        erg["seiten"] = doc.page_count
        r0 = doc[0].rect
        erg["format"] = f"{r0.width:.0f}x{r0.height:.0f}"
        res = nachzeichnen.analysiere_doc(doc, max_px=1400)
        doc.close()
        erg["sek"] = round(time.time() - t0, 1)
        if not res.get("ok"):
            erg["grund"] = "analysiere_doc meldet ok=False"
            return erg
        erg["ok"] = True
        rr = [x for x in (res.get("raeume") or []) if x.get("f_m2")]
        erg["stempel"] = len(rr)
        frei = [x for x in rr if x.get("aussenanlage")]
        erg["frei"] = len(frei)
        mit = [x for x in rr if x.get("region_px") and not x.get("aussenanlage")]
        erg["umriss"] = len(mit)
        ech = [x for x in mit if not x.get("region_geschaetzt")]
        if ech:
            sk = statistics.median(
                math.sqrt(_poly_f(x["region_px"]) / x["f_m2"]) for x in ech)
            if sk > 0:
                erg["treue"] = round(statistics.median(
                    abs(_poly_f(x["region_px"]) / (sk * sk) - x["f_m2"]) / x["f_m2"]
                    for x in ech) * 100, 1)
        erg["waende"] = len(res.get("waende") or [])
        erg["oeffnungen"] = len(res.get("oeffnungen") or [])
    except Exception as e:                     # pragma: no cover
        erg["sek"] = round(time.time() - t0, 1)
        erg["grund"] = f"{type(e).__name__}: {str(e)[:90]}"
    return erg


def _plaene():
    """Alle Plandateien — OHNE Duplikate.

    Das ist keine Kosmetik: ~/Downloads enthält den WM-Plan fünfmal und die
    drei anderen je zweimal. Ohne Entdopplung meldet die Messung "11 Pläne
    tragen Raumstempel, 436 Stempel" — tatsächlich sind es VIER verschiedene
    Grundrisse mit 113 Stempeln. Eine Kennzahl, die Kopien zählt, behauptet
    eine Breite, die es nicht gibt.

    Verglichen wird der Datei-Inhalt (sha256), nicht der Name — die Kopien
    heißen "(1)", "(2)", "testtt.pdf".
    """
    import hashlib
    import fitz
    out, gesehen = [], {}
    for p in sorted(glob.glob(os.path.expanduser("~/Downloads/*.pdf"))):
        try:
            d = fitz.open(p)
            r = d[0].rect
            d.close()
            if max(r.width, r.height) < MIN_PLAN_PT:
                continue
            with open(p, "rb") as fh:
                h = hashlib.sha256(fh.read()).hexdigest()
            if h in gesehen:
                continue
            gesehen[h] = p
            out.append(p)
        except Exception:
            continue
    return out


def run(grenze=None):
    import fitz  # noqa: F401  (früh laden, damit _plaene() nicht scheitert)
    ps = _plaene()
    if grenze:
        ps = ps[:int(grenze)]
    print("PLAN-KORPUS BREIT — läuft die Erkennung auf ALLEN Plänen?")
    print("=" * 108)
    print(f"{len(ps)} VERSCHIEDENE Pläne im Planformat (≥{MIN_PLAN_PT:.0f} pt) "
          f"aus ~/Downloads — Kopien desselben Plans zählen nicht mit\n")
    if not ps:
        print("KEIN Plan gefunden — Messung wertlos")
        return

    with mp.Pool(processes=min(4, max(1, (os.cpu_count() or 4) - 2))) as pool:
        jobs = [pool.apply_async(_einer, (p,)) for p in ps]
        erg = []
        for j, p in zip(jobs, ps):
            try:
                erg.append(j.get(timeout=TIMEOUT_S))
            except mp.TimeoutError:
                erg.append({"datei": os.path.basename(p), "ok": False,
                            "grund": f"Zeitüberschreitung >{TIMEOUT_S}s",
                            "stempel": 0, "umriss": 0, "frei": 0,
                            "treue": None, "sek": TIMEOUT_S, "format": "?"})
            except Exception as e:
                erg.append({"datei": os.path.basename(p), "ok": False,
                            "grund": f"{type(e).__name__}: {e}", "stempel": 0,
                            "umriss": 0, "frei": 0, "treue": None,
                            "sek": 0, "format": "?"})

    # ZEIT EHRLICH MESSEN: der Sammellauf oben rechnet 4 Pläne GLEICHZEITIG,
    # in Produktion läuft ein Plan je Aufruf allein. Unter Konkurrenz war
    # derselbe WM-Plan 598 s "langsam", allein braucht er 226 s — die Harness
    # hätte also die Kernzahl dieses Rechners gemessen, nicht die App.
    # Darum: alles über LANGSAM_S noch einmal EINZELN nachmessen. Doppelte
    # Dateien (gleiche Größe) nur einmal.
    nach = [e for e in erg if e["sek"] >= LANGSAM_S]
    if nach:
        print(f"({len(nach)} Pläne liefen unter Last über {LANGSAM_S:.0f}s — "
              f"werden jetzt EINZELN nachgemessen)\n")
        gesehen = {}
        for e in sorted(nach, key=lambda x: -x["sek"]):
            p = next((q for q in ps if os.path.basename(q) == e["datei"]), None)
            if not p:
                continue
            gr = os.path.getsize(p)
            if gr in gesehen:
                e.update(gesehen[gr])
                e["allein"] = True
                continue
            neu = None
            with mp.Pool(processes=1) as p1:
                try:
                    neu = p1.apply_async(_einer, (p,)).get(timeout=TIMEOUT_S)
                except mp.TimeoutError:
                    neu = dict(e, sek=float(TIMEOUT_S), ok=False,
                               grund=f"Zeitüberschreitung >{TIMEOUT_S}s (allein)")
            # Der Einzellauf ERSETZT den Sammellauf komplett — sonst bleibt ein
            # "Zeitüberschreitung"-Grund aus der Last-Messung stehen und der
            # Wächter schlägt gegen eine Zahl an, die gar nicht mehr gilt.
            neu.pop("datei", None)
            e.update(neu)
            e["allein"] = True
            gesehen[gr] = dict(neu)
            print(f"   einzeln: {e['datei'][:48]:<50}{e['sek']:.0f}s")
        print()

    print(f"{'Plan':<46}{'Format':>11}{'Stmp':>6}{'Umr':>5}{'Frei':>5}"
          f"{'Treue':>8}{'sek':>7}  Status")
    print("-" * 108)
    for e in sorted(erg, key=lambda x: -x["stempel"]):
        st = "ok" if e["ok"] else f"FEHLER {e['grund']}"
        if e["ok"] and e["stempel"] == 0:
            st = "keine Raumstempel (Schnitt/Ansicht/Lageplan?)"
        tr_s = "—" if e["treue"] is None else f"{e['treue']}%"
        print(f"{e['datei'][:44]:<46}{str(e.get('format')):>11}{e['stempel']:>6}"
              f"{e['umriss']:>5}{e['frei']:>5}{tr_s:>8}"
              f"{e['sek']:>7.1f}  {st[:34]}")
    print("-" * 108)

    lief = [e for e in erg if e["ok"]]
    mit = [e for e in lief if e["stempel"] > 0]
    # DREI verschiedene Dinge, die vorher alle "kaputt" hießen:
    #   abgelehnt  ok=False, weil es gar kein Grundriss ist (Preisliste,
    #              Jahresplanung, Marketing-Deck). Das ist RICHTIGES Verhalten
    #              und darf keinen Wächter rot färben — sonst misst man die
    #              Sortierung von ~/Downloads statt die App.
    #   crash      eine Ausnahme ist durchgeschlagen. Nie in Ordnung.
    #   zu langsam über der Produktionsgrenze. Der Plan geht verloren.
    crash = [e for e in erg if not e["ok"] and e["grund"]
             and not e["grund"].startswith("analysiere_doc meldet")
             and "Zeitüberschreitung" not in e["grund"]]
    zu_lang = [e for e in erg if e["sek"] >= GRENZE_S
               or (e["grund"] or "").startswith("Zeitüberschreitung")]
    abgelehnt = [e for e in erg if not e["ok"] and e not in crash
                 and e not in zu_lang]
    langsam = [e for e in erg if LANGSAM_S <= e["sek"] < GRENZE_S]
    abd = [e["umriss"] / max(1, e["stempel"] - e["frei"]) for e in mit
           if e["stempel"] - e["frei"] > 0]
    tr = [e["treue"] for e in mit if e["treue"] is not None]
    print(f"KORPUS {len(erg)} Pläne")
    print(f"  LÄUFT DURCH   {len(lief)}/{len(erg)} ohne Absturz "
          f"({len(lief)/len(erg)*100:.0f}%)")
    print(f"  MIT RÄUMEN    {len(mit)} Pläne tragen Raumstempel "
          f"(Σ {sum(e['stempel'] for e in mit)} Stempel, "
          f"{sum(e['frei'] for e in mit)} davon Freifläche)")
    if abd:
        print(f"  ABDECKUNG     Median {statistics.median(abd)*100:.0f}% der "
              f"Räume bekommen einen Umriss  ·  "
              f"{sum(1 for a in abd if a >= 0.99)}/{len(abd)} Pläne bei 100%")
    if tr:
        print(f"  TREUE         Median {statistics.median(tr):.1f}%  ·  "
              f"schlechtester Plan {max(tr):.1f}%")
    _plan_sek = [e["sek"] for e in mit]
    print(f"  LAUFZEIT      Median {statistics.median([e['sek'] for e in erg]):.1f}s "
          f"· bei Plänen MIT Räumen "
          f"{(statistics.median(_plan_sek) if _plan_sek else 0):.1f}s "
          f"(langsamster {(max(_plan_sek) if _plan_sek else 0):.0f}s, "
          f"Produktionsgrenze {GRENZE_S:.0f}s)")
    print(f"  ABGELEHNT     {len(abgelehnt)} Dokumente ohne Grundriss "
          f"(Preislisten, Jahresplanungen — richtig abgewiesen, kein Fehler)")
    if langsam:
        print(f"\n  {len(langsam)} Pläne über {LANGSAM_S:.0f}s — in der "
              f"Bedienung unzumutbar, auch wenn sie durchlaufen:")
        for e in sorted(langsam, key=lambda x: -x["sek"]):
            print(f"     {e['datei'][:52]:<54}{e['sek']:.0f}s")
    if zu_lang:
        print(f"\n  {len(zu_lang)} Pläne über der Produktionsgrenze "
              f"({GRENZE_S:.0f}s) — die gehen in der App verloren:")
        for e in zu_lang:
            print(f"     {e['datei'][:52]:<54}{e['sek']:.0f}s")
    if crash:
        print(f"\n  {len(crash)} Pläne bringen die Pipeline zum ABSTURZ:")
        for e in crash:
            print(f"     {e['datei'][:52]:<54}{e['grund']}")
    ziel = os.path.join(os.environ.get("SCRATCH", "/tmp"),
                        "plankorpus_breit.json")
    try:
        with open(ziel, "w", encoding="utf-8") as fh:
            json.dump(erg, fh, ensure_ascii=False, indent=1)
        print(f"\nRohdaten: {ziel}")
    except OSError:
        pass

    # ZWEI ZUSAGEN, die getrennt gehalten werden müssen:
    #  1. Kein Plan bringt die Pipeline zum Absturz. Ein Dokument ohne
    #     Grundriss sauber abzuweisen ist RICHTIG und zählt hier nicht.
    #  2. Kein Plan reißt die Produktionsgrenze. Ein Plan, der 600 s braucht,
    #     ist für den Nutzer nicht vorhanden — das ist kein Schönheitsfehler.
    assert not crash, (f"{len(crash)} von {len(erg)} Plänen bringen die "
                       f"Pipeline zum Absturz: "
                       f"{[e['datei'] for e in crash][:4]}")
    assert not zu_lang, (f"{len(zu_lang)} Pläne brauchen mehr als "
                         f"{GRENZE_S:.0f}s und gehen in Produktion verloren: "
                         f"{[(e['datei'], e['sek']) for e in zu_lang][:4]}")


if __name__ == "__main__":
    run(sys.argv[1] if len(sys.argv) > 1 else None)
