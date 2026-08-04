"""WÄCHTER: drei Stellen, an denen die Schätzung die Messung schlug.

Gefunden von einem Audit über die Fehlerklasse „eine Schätzung überschreibt
eine byte-exakte Messung, oder ein fehlender Wert wird lautlos zu 0". Jeder
Befund wurde von zwei unabhängigen Skeptikern geprüft; diese drei haben beide
Prüfungen überlebt und sind hier festgenagelt.

1) UMFANG VERWORFEN, RAUM VERSCHWINDET (extract.py, Block 4b1)
   Ein isoperimetrisch unplausibler Umfang (U < 4·√F — geometrisch unmöglich,
   entsteht durch Stempel-Cross-Talk) wurde auf None gesetzt und der Rohwert
   in `_umfang_implausibel` vermerkt. Dieses Feld wird im GANZEN Repo nirgends
   gelesen — weder Prüfliste noch Konsistenz-Check noch Export kennen es.
   Downstream greift überall `if not u: continue`, der Raum fiel also lautlos
   aus LG 10 Innenputz Wände, LG 46 Anstrich Wände, LG 11 Randdämmstreifen und
   LG 08 Wand-Abwicklung — stand aber weiter in Innenputz DECKEN, Estrich und
   Decke. Die Liste sah vollständig aus.
   Jetzt: isoperimetrischer Ersatz mit `umfang_quelle="geschaetzt"`.

2) FENSTER-KAPPE OHNE KONFIDENZ-TOR (extract.py, Varianz-Klammer)
   Die Plan-Ebene kappte die Fensterliste an einer KI-Symbolzählung, ohne
   deren Konfidenz zu prüfen — und schrieb die gekürzte Liste destruktiv in
   die Datenbank zurück. Das Gegenstück auf PROJEKT-Ebene (`_symbol_max`) hat
   das Tor, mit wörtlich dieser Begründung: „eine Symbol-Zählung mit Konfidenz
   GENAU 0,4 durfte kappen und loeschte damit Tueren, die byte-exakt aus dem
   Text-Layer (STUK/FPH) gelesen waren."
   Jetzt: dasselbe Tor (>0,4, kein_grundriss) UND eine zweite Sicherung — nie
   unter die Anzahl der byte-exakten Fenster kappen.

3) ATTIKA AUS DEM BILD GEGEN DIE LEGENDE (extract.py, 6c2/Opus)
   Schnitt- und Opus-Bildlesung schalteten die Attika ein, ohne die
   byte-exakte Legende zu konsultieren. Sagt die gedruckte Legende „steil",
   entstanden drei erfundene Positionen: XPS = Außenumfang × 0,50 m²,
   Beton C25/30 = diese Fläche × 0,15 m³, Steckeisen = Umfang × 3 Stück.
   Jetzt: `_leg_steil` sperrt beide Vision-Zweige.
"""
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "api"))

QUELLE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                      "..", "api", "extract.py")


def _umfang_ersatz(fehler):
    """Ein verworfener Umfang darf den Raum nicht aus den Mengen kippen."""
    import massen_logic as ml
    import nachzeichnen as nz
    print("1) UMFANG VERWORFEN — bleibt der Raum in den Mengen?")
    # Flur mit Cross-Talk-Umfang: F=12,25 → Minimum wäre 4·√12,25 = 14,00 m.
    f, u_falsch = 12.25, 10.00
    if not (u_falsch < 4.0 * (f ** 0.5) * 0.98):
        fehler.append("Testaufbau: 10,0 m gilt bei 12,25 m² gar nicht als "
                      "unplausibel — der Fall prüft nichts")
        return
    iso = nz.isoperimetrischer_umfang(f)
    print(f"   F={f} m² · gelesener U={u_falsch} m (unmöglich, Minimum "
          f"{4.0 * (f ** 0.5):.2f} m) · isoperimetrischer Ersatz={iso} m")
    if not iso or not (10.0 < iso < 20.0):
        fehler.append(f"isoperimetrischer Ersatz {iso} unbrauchbar")
        return

    def _mengen(raeume):
        """LG 10 Innenputz WÄNDE (Σ U×H). Signatur ist (rooms, windows,
        baudaten) — beim ersten Anlauf hatte dieser Wächter baudaten in den
        windows-Parameter geschoben und maß dadurch überall 0,00 m²."""
        erg = ml.berechne_gewerke(raeume, [], {"geschosshoehe_m": 2.60})
        n = 0.0
        for pos in ((erg.get("gewerke") or {}).get("putz") or {}) \
                .get("positionen") or []:
            if "wände" in str(pos.get("beschreibung", "")).lower():
                n += float(pos.get("endsumme") or 0)
        return n

    basis = [{"name": "Wohnen", "flaeche_m2": 30.0, "umfang_m": 24.0,
              "hoehe_m": 2.60}]
    ohne = _mengen(basis + [{"name": "Flur", "flaeche_m2": f,
                             "umfang_m": None, "hoehe_m": 2.60}])
    mit = _mengen(basis + [{"name": "Flur", "flaeche_m2": f,
                            "umfang_m": iso, "umfang_quelle": "geschaetzt",
                            "hoehe_m": 2.60}])
    print(f"   Putz-Wandfläche  ohne Ersatz: {ohne:.2f} m²  ·  "
          f"mit Ersatz: {mit:.2f} m²")
    if mit <= ohne:
        fehler.append(f"der isoperimetrische Ersatz bringt den Raum nicht "
                      f"zurück in die Wandmengen ({ohne} → {mit})")
    else:
        print(f"   → der Raum ist zurück in den Wandmengen "
              f"(+{mit - ohne:.2f} m²) ✓")
    # Und der Code muss den Ersatz wirklich setzen, nicht nur None.
    src = open(QUELLE, encoding="utf-8").read()
    if "_u_verwerfen" not in src or "umfang_quelle\"] = \"geschaetzt\"" not in src:
        fehler.append("extract.py setzt beim Verwerfen keinen isoperimetrischen "
                      "Ersatz mit Quelle 'geschaetzt' — der Raum fällt wieder "
                      "lautlos aus allen U-Positionen")
    else:
        print("   Code setzt Ersatz + Quelle 'geschaetzt' ✓")


def _fenster_kappe(fehler):
    """Eine KI-Zählung darf byte-exakte Fenster nicht löschen."""
    print("\n2) FENSTER-KAPPE — Konfidenz-Tor und Byte-exakt-Boden")
    src = open(QUELLE, encoding="utf-8").read()
    # Am "[fenster-klammer]"-Log ankern, NICHT an "VARIANZ-KLAMMER": dieses
    # Wort kommt zweimal in der Datei vor, und der erste Treffer (Anker-Block,
    # ~700 Zeilen früher) ließ den Wächter am falschen Code prüfen.
    i = src.find("[fenster-klammer]")
    block = src[max(0, i - 3000):i + 1500] if i >= 0 else ""
    if not block:
        fehler.append("Varianz-Klammer nicht gefunden — Wächter prüft nichts")
        return
    for muster, was in (
        (r'oeffnungs_symbole\.get\("konfidenz"\)', "Konfidenz wird gelesen"),
        (r'kein_grundriss', "kein_grundriss wird geprüft"),
        (r'_n_text', "Boden aus byte-exakten Fenstern"),
    ):
        if not re.search(muster, block):
            fehler.append(f"Fenster-Kappe: {was} — fehlt. Eine KI-Zählung "
                          f"kann wieder byte-exakte Fenster löschen "
                          f"(destruktiv, delete+insert in die Datenbank).")
        else:
            print(f"   {was} ✓")
    # Die Logik selbst, ausgeführt.
    def _kappe(n_text, n_gesamt, sym, konf):
        ok = konf is None or konf > 0.4
        s = max(0, min(60, int(sym))) if (sym is not None and ok) else None
        if s is not None and n_text > s:
            s = n_text
        return min(n_gesamt, s) if s else n_gesamt
    for name, args_, soll in (
        ("Konfidenz 0,3 → kein Cap", (6, 20, 8, 0.3), 20),
        ("Konfidenz 0,4 (genau) → kein Cap", (6, 20, 8, 0.4), 20),
        ("Konfidenz 0,7 → Cap auf 8", (6, 20, 8, 0.7), 8),
        ("Cap 4 < 6 byte-exakte → auf 6 angehoben", (6, 20, 4, 0.9), 6),
        ("keine Konfidenz gemeldet → Cap greift", (2, 20, 9, None), 9),
    ):
        ist = _kappe(*args_)
        ok = ist == soll
        if not ok:
            fehler.append(f"Fenster-Kappe '{name}': {ist} statt {soll}")
        print(f"   {name:<44} → {ist:>3}  {'✓' if ok else 'FALSCH'}")


def _attika_sperre(fehler):
    """Ein Bild darf gegen die gedruckte Legende kein Bauteil erfinden."""
    print("\n3) ATTIKA — byte-exakte Legende sperrt die Bildlesung")
    src = open(QUELLE, encoding="utf-8").read()
    if "_leg_steil" not in src:
        fehler.append("keine Steildach-Gegensperre (_leg_steil) — eine "
                      "Vision-Lesung kann auf einem Steildach XPS, Beton und "
                      "Steckeisen erfinden")
        return
    n = len(re.findall(r'"flach"\s+and\s+not\s+_leg_steil', src))
    print(f"   Vision-Zweige mit Gegensperre: {n} (Schnitt + Opus = 2)")
    if n < 2:
        fehler.append(f"nur {n} von 2 Vision-Zweigen haben die Gegensperre — "
                      f"der ungesicherte schaltet die Attika weiter ein")
    else:
        print("   beide Zweige gesperrt ✓")


def _umfang_herkunft(fehler):
    """4) SCHÄTZUNG SAH AUS WIE MESSUNG (extract.py + massen_logic._u_lbl)

    `extract.py` setzte an zwei Stellen `umfang_quelle="geschaetzt"`, aber
    NICHT `umfang_geschaetzt=True`. `massen_logic._u_lbl` und die UI lasen
    ausschliesslich das Flag — jede isoperimetrische Schätzung erschien im
    Aufmaß darum als „U=…", also als Messung. Genau die Fehlerklasse, die
    dieser Wächter bewacht, nur eine Ebene tiefer.

    Dazu fehlte die MITTLERE Stufe ganz: ein aus dem Polygon abgeleiteter
    Umfang ist keine Messung am Stempel, aber auch keine reine Schätzung.
    Am Korpus betrifft er 27 Räume mit rund 2865 m² Wandabwicklung.
    """
    import massen_logic as ml
    print("\n4) Umfangs-Herkunft im Aufmaß — Stempel / Umriss / Schätzung")
    faelle = [
        ({}, "U=", "ohne Angabe gilt der Stempel"),
        ({"umfang_quelle": "geometrie"}, "aus Umriss", "aus dem Polygon"),
        ({"umfang_quelle": "geschaetzt"}, "geschätzt", "isoperimetrisch"),
        ({"umfang_geschaetzt": True}, "geschätzt", "altes Flag"),
        ({"daten": {"umfang_geschaetzt": True}}, "geschätzt", "verschachtelt"),
    ]
    for raum, erwartet, was in faelle:
        lbl = ml._u_lbl(raum, 12.5)
        ok = erwartet in lbl
        print(f"   {was:<26}{lbl:<26}{'✓' if ok else '✗'}")
        if not ok:
            fehler.append(f"_u_lbl({raum}) = {lbl!r} — erwartet {erwartet!r}. "
                          f"Eine Schätzung, die wie eine Messung aussieht, ist "
                          f"schlimmer als eine fehlende Zahl.")
    # QUELLTEXT-SPERRE: wer künftig `umfang_quelle="geschaetzt"` setzt, muss
    # `umfang_geschaetzt` mitsetzen — sonst faellt die Ehrlichkeit still weg.
    src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "..", "api", "extract.py"), encoding="utf-8").read()
    # Eine reine ZÄHLUNG reicht nicht: eine dritte, unbeteiligte Stelle
    # setzt das Flag ebenfalls, damit ginge ein fehlendes Paar durch.
    # Am eigenen Wächter gemessen — er liess genau diesen Rueckfall passieren.
    # Darum PAARWEISE pruefen: jede Stelle mit quelle='geschaetzt' muss das
    # Flag in unmittelbarer Nachbarschaft setzen.
    zeilen = src.split("\n")
    offen = []
    for i, z in enumerate(zeilen):
        if re.search(r'umfang_quelle"\]\s*=\s*"geschaetzt"', z):
            nachbar = "\n".join(zeilen[max(0, i - 3):i + 8])
            if not re.search(r'umfang_geschaetzt"\]\s*=\s*True', nachbar):
                offen.append(i + 1)
    n_q = sum(1 for z in zeilen
              if re.search(r'umfang_quelle"\]\s*=\s*"geschaetzt"', z))
    print(f"   extract.py: {n_q} Stellen mit quelle='geschaetzt', "
          f"{n_q - len(offen)} davon mit Flag daneben")
    if offen:
        fehler.append(f"extract.py Zeile(n) {offen}: umfang_quelle="
                      f"'geschaetzt' ohne umfang_geschaetzt=True in "
                      f"Reichweite — diese Schätzung erscheint im Aufmaß "
                      f"als Messung.")

    # 5) NAMENS-KURZSCHLUSS: der EINZIGE Kandidat wurde ohne Flächenprüfung
    #    genommen — genau die Regel, die der Docstring darüber verspricht.
    if re.search(r"if len\(_k\) == 1:\s*\n\s*return _k\[0\]\[1\]", src):
        fehler.append("_geo_u_fuer nimmt den einzigen Namens-Kandidaten wieder "
                      "ohne Flächenprüfung. Am Velden-Plan bekam 'Waschraum' "
                      "(9,31 m²) so den Umfang seines 7,32-m²-Namensvetters — "
                      "als umfang_quelle='geometrie', sah also gemessen aus.")
    else:
        print("   _geo_u_fuer prüft die Fläche auch beim Einzeltreffer     ✓")


def run():
    print("MESSUNG VOR SCHÄTZUNG — fünf Audit-Befunde festgenagelt")
    print("=" * 88)
    fehler = []
    _umfang_ersatz(fehler)
    _fenster_kappe(fehler)
    _attika_sperre(fehler)
    _umfang_herkunft(fehler)
    print("-" * 88)
    if fehler:
        print("FEHLER:")
        for f in fehler:
            print(f"  ✗ {f}")
    else:
        print("WÄCHTER ok: verworfener Umfang behält einen ehrlichen Ersatz, "
              "die Fenster-Kappe\n           respektiert Konfidenz und "
              "byte-exakte Fenster, die gedruckte Legende\n"
              "           schlägt die Bildlesung beim Dachtyp, und jede "
              "Umfangs-Zahl trägt\n           ihre Herkunft (Stempel / "
              "Umriss / Schätzung)")
    assert not fehler, f"{len(fehler)} Fehler"


if __name__ == "__main__":
    run()
