"""WÄCHTER: rechnet die App für MEHRERE Bereiche der Baubranche — oder nur für Wohnbau?

Die Zusage "für mehrere Bereiche der Baubranche" stand bisher auf vier echten
Plänen, die alle Wohnbau sind (drei Wohnanlagen, eine Tiefgarage darunter).
Das ist ein Beispiel, keine Zusage.

Hier werden sektortypische Grundrisse GEBAUT (scripts/_plan_generator.py) —
Bürogeschoss, Gewerbehalle, Hotel, Schule, Parkdeck, Reihenhauszeile,
Landwirtschaft — und durch dieselbe Kette geschickt wie ein echter Plan:

    PDF -> nachzeichnen.analysiere_doc -> massen_logic.berechne_gewerke

Geprüft wird zweierlei:
  1. LESEN     jeder Raum byte-exakt (Name, Fläche, Umfang) — sonst nützt
               die beste Mengen-Engine nichts
  2. GEWERKE   welche Gewerke bekommen aus DIESEM Gebäudetyp eine Menge,
               je mit ÖNORM-Leistungsgruppe

Ein Gewerk, das bei einem Typ ausbleibt, ist kein Fehler: eine Halle ohne
Nassraum bekommt keine Wandfliesen. Der Wächter verlangt darum keine feste
Liste, sondern: jeder Bautyp muss von MEHREREN Gewerken bedient werden, und
über alle Typen hinweg muss die Breite stehen.
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "api"))
import massen_logic as ml            # noqa: E402
from _plan_generator import A0, A1, PlanBauer   # noqa: E402

# Bauteil-Annahmen je Bauart — ein Industriebau ist Stahlbeton, ein
# Wohnhaus Mauerwerk. Ohne diese Unterscheidung misst man nicht die
# Sektor-Breite, sondern eine Wohnbau-Schablone.
MASSIV = {"geschosshoehe_m": 2.8, "aussenwand_cm": 50.0,
          "innenwand_tragend_cm": 25.0, "innenwand_nichttragend_cm": 12.0,
          "decke_cm": 22.0, "bodenplatte_cm": 25.0, "hat_keller": False,
          "wandmaterial": "Hochlochziegel"}
BETON = {"geschosshoehe_m": 6.5, "aussenwand_cm": 30.0,
         "innenwand_tragend_cm": 25.0, "innenwand_nichttragend_cm": 12.5,
         "decke_cm": 30.0, "bodenplatte_cm": 35.0, "hat_keller": False,
         "anzahl_saeulen": 8, "wandmaterial": "Stahlbeton"}


def _buero():
    b = PlanBauer(massstab=100, blatt=A1)
    b.raum("Großraumbüro", 1.0, 1.0, 14.0, 9.0, "Teppich")
    b.raum("Besprechung", 16.0, 1.0, 6.0, 4.5, "Teppich")
    b.raum("Teeküche", 16.0, 6.5, 3.0, 3.5, "Fliesen")
    b.raum("WC Damen", 20.0, 6.5, 2.6, 3.5, "Fliesen")
    b.raum("Gang", 1.0, 11.0, 21.6, 2.4, "Feinsteinzeug")
    return b, MASSIV


def _halle():
    b = PlanBauer(massstab=200, blatt=A0)
    b.raum("Produktionshalle", 1.0, 1.0, 42.0, 26.0, "Beton")
    b.raum("Lager", 44.0, 1.0, 12.0, 14.0, "Beton")
    b.raum("Meisterbüro", 44.0, 16.0, 6.0, 5.0, "Laminat")
    b.raum("Sozialraum", 51.0, 16.0, 5.0, 5.0, "Fliesen")
    return b, BETON


def _hotel():
    b = PlanBauer(massstab=100, blatt=A1)
    for i in range(10):
        sp, ze = i % 5, i // 5
        b.raum(f"Gästezimmer {i+1}", 1.0 + sp * 4.6, 1.0 + ze * 7.4,
               4.2, 5.4, "Teppich")
        b.raum(f"Bad {i+1}", 1.0 + sp * 4.6, 6.7 + ze * 7.4, 4.2, 1.6,
               "Fliesen")
    b.raum("Flur", 1.0, 15.9, 22.6, 2.4, "Feinsteinzeug")
    return b, MASSIV


def _schule():
    b = PlanBauer(massstab=100, blatt=A1)
    for i in range(4):
        b.raum(f"Klasse {i+1}", 1.0 + i * 8.4, 1.0, 8.0, 7.5, "Linoleum")
    b.raum("Lehrerzimmer", 1.0, 9.0, 7.0, 5.0, "Linoleum")
    b.raum("WC Knaben", 8.5, 9.0, 4.0, 5.0, "Fliesen")
    b.raum("WC Mädchen", 13.0, 9.0, 4.0, 5.0, "Fliesen")
    b.raum("Gang", 1.0, 14.5, 32.4, 3.0, "Feinsteinzeug")
    return b, MASSIV


def _parkdeck():
    b = PlanBauer(massstab=200, blatt=A0)
    b.raum("Parkdeck", 1.0, 1.0, 38.0, 24.0, "Beton")
    b.raum("Technikraum", 41.0, 1.0, 6.0, 5.0, "Beton")
    b.raum("Trafo", 41.0, 7.0, 5.0, 5.0, "Beton")
    b.raum("Stiegenhaus", 41.0, 13.0, 4.5, 5.5, "Feinsteinzeug")
    return b, BETON


def _reihenhaus():
    b = PlanBauer(massstab=50, blatt=A0)
    for i in range(3):
        x = 1.0 + i * 7.6
        b.raum(f"Wohnküche H{i+1}", x, 1.0, 7.0, 5.5, "Parkett")
        b.raum(f"Bad H{i+1}", x, 7.0, 3.2, 2.6, "Fliesen")
        b.raum(f"Zimmer H{i+1}", x + 3.6, 7.0, 3.4, 2.6, "Parkett")
    return b, MASSIV


def _landwirtschaft():
    b = PlanBauer(massstab=200, blatt=A0)
    b.raum("Maschinenhalle", 1.0, 1.0, 30.0, 18.0, "Beton")
    b.raum("Futterlager", 32.0, 1.0, 14.0, 10.0, "Beton")
    b.raum("Milchkammer", 32.0, 12.0, 5.0, 5.0, "Fliesen")
    return b, BETON


SEKTOREN = [
    ("Bürogebäude (Geschoss)", _buero),
    ("Gewerbe-/Industriehalle", _halle),
    ("Hotel / Beherbergung", _hotel),
    ("Bildungsbau (Schule)", _schule),
    ("Parkdeck / Tiefgarage", _parkdeck),
    ("Reihenhauszeile", _reihenhaus),
    ("Landwirtschaftsbau", _landwirtschaft),
]

BEREICH = {
    "rohbau": "Baumeister/Maurer", "beton": "Stahlbetonbau",
    "erdarbeiten": "Erdbau", "putz": "Verputzer", "estrich": "Estrichleger",
    "maler": "Maler", "fliesen": "Fliesenleger", "fenster": "Fensterbau",
    "daemmung": "WDVS/Fassade", "geruest": "Gerüstbau",
}


def _durchlauf(bauer, bd, ordner, i):
    import math
    import fitz
    import nachzeichnen
    pfad = os.path.join(ordner, f"sektor{i}.pdf")
    bauer.schreibe(pfad)
    soll = {w["name"]: w for w in bauer.wahrheit()}
    doc = fitz.open(pfad)
    try:
        r = nachzeichnen.analysiere_doc(doc, max_px=1400)
    finally:
        doc.close()
    if not r.get("ok"):
        return {"ok": False, "grund": "analysiere_doc: ok=False"}
    ist = [x for x in (r.get("raeume") or [])
           if x.get("f_m2") and not x.get("aussenanlage")]
    exakt = 0
    for nm, w in soll.items():
        k = [x for x in ist if str(x.get("name")) == nm]
        if k and abs((k[0].get("f_m2") or 0) - w["f_m2"]) < 0.005:
            exakt += 1
    rooms = [{"name": x.get("name"), "flaeche_m2": x.get("f_m2"),
              "umfang_m": x.get("u_m"), "hoehe_m": None} for x in ist]
    oeff = [{"code": o.get("code"), "breite_m": o.get("breite_m"),
             "hoehe_m": o.get("hoehe_m"),
             "_art": ("tuer" if (o.get("art") == "tuer"
                                 or o.get("typ") == "tuer") else "fenster")}
            for o in (r.get("oeffnungen") or []) if o.get("breite_m")]
    f_ges = sum(x["flaeche_m2"] for x in rooms if x.get("flaeche_m2"))
    bdd = dict(bd)
    if f_ges > 0:
        u_min = 4.0 * math.sqrt(f_ges)
        bdd["_basis_bodenplatte_m2"] = round(f_ges, 2)
        bdd["_basis_aussenumfang_m"] = round(u_min, 2)
        bdd["_basis_aussenwand_flaeche_m2"] = round(
            u_min * bdd.get("geschosshoehe_m", 3.0), 2)
    g = ml.berechne_gewerke(rooms, [o for o in oeff if o["_art"] != "tuer"],
                            bdd, geschoss="EG",
                            tueren=[o for o in oeff if o["_art"] == "tuer"])
    akt = [k for k, v in (g.get("gewerke") or {}).items()
           if isinstance(v, dict) and any(p.get("endsumme")
                                          for p in (v.get("positionen") or []))]
    ohne_lg = [k for k in akt if not (g["gewerke"][k] or {}).get("lg")]
    return {"ok": True, "n_soll": len(soll), "n_ist": len(ist),
            "exakt": exakt, "gewerke": sorted(akt), "ohne_lg": ohne_lg,
            "f_ges": f_ges}


def run():
    print("SEKTOREN — rechnet die App für mehrere Bereiche der Baubranche?")
    print("=" * 104)
    print(f"{'Bauart':<28}{'Räume':>8}{'byte-exakt':>12}{'m² BGF':>10}"
          f"{'Gewerke':>9}  Bereiche")
    print("-" * 104)
    fehler, alle_gew, zeilen = [], {}, 0
    with tempfile.TemporaryDirectory() as tmp:
        for i, (name, bau) in enumerate(SEKTOREN):
            try:
                b, bd = bau()
                e = _durchlauf(b, bd, tmp, i)
            except Exception as ex:
                fehler.append(f"{name}: ABSTURZ {type(ex).__name__}: {ex}")
                print(f"{name[:27]:<28}   ABSTURZ {type(ex).__name__}")
                continue
            if not e["ok"]:
                fehler.append(f"{name}: {e['grund']}")
                print(f"{name[:27]:<28}   {e['grund']}")
                continue
            zeilen += 1
            if e["exakt"] < e["n_soll"]:
                fehler.append(f"{name}: nur {e['exakt']}/{e['n_soll']} Räume "
                              f"byte-exakt gelesen")
            if len(e["gewerke"]) < 4:
                fehler.append(f"{name}: nur {len(e['gewerke'])} Gewerke "
                              f"({e['gewerke']}) — für diesen Bautyp zu schmal")
            if e["ohne_lg"]:
                fehler.append(f"{name}: Gewerke ohne Leistungsgruppe: "
                              f"{e['ohne_lg']}")
            for k in e["gewerke"]:
                alle_gew.setdefault(k, []).append(name)
            print(f"{name[:27]:<28}{e['n_ist']:>4}/{e['n_soll']:<3}"
                  f"{e['exakt']:>12}{e['f_ges']:>10.0f}{len(e['gewerke']):>9}  "
                  f"{', '.join(BEREICH.get(k, k) for k in e['gewerke'])[:38]}")
    print("-" * 104)
    if alle_gew:
        print(f"\nAuf WIE VIELEN der {zeilen} Bauarten rechnet jedes Gewerk?")
        for k, v in sorted(alle_gew.items(), key=lambda kv: -len(kv[1])):
            print(f"   {BEREICH.get(k, k):<22}{len(v):>2}/{zeilen}  "
                  f"{'█' * len(v):<8}  {', '.join(x.split(' ')[0] for x in v)[:46]}")

    # ZUSAGEN
    if zeilen < 5:
        fehler.append(f"nur {zeilen} Bauarten durchgelaufen — Aussage über "
                      f"'mehrere Bereiche' nicht belastbar")
    # Kein Gewerk darf NUR im Wohnbau rechnen — sonst ist die Breite eine
    # Wohnbau-Schablone mit anderen Etiketten.
    einsam = [k for k, v in alle_gew.items() if len(v) < 2]
    if einsam:
        fehler.append(f"Gewerke, die nur auf EINER Bauart rechnen: {einsam}")
    print()
    if fehler:
        print("FEHLER:")
        for f in fehler:
            print(f"  ✗ {f}")
    else:
        print(f"WÄCHTER ok: {zeilen} Bauarten — Büro, Halle, Hotel, Schule, "
              f"Parkdeck, Reihenhaus, Landwirtschaft.\n"
              f"           Alle Räume byte-exakt gelesen, "
              f"{len(alle_gew)} Gewerke mit ÖNORM-Leistungsgruppe, "
              f"jedes auf mindestens zwei Bauarten.")
    assert not fehler, f"{len(fehler)} Sektor-Fehler"


if __name__ == "__main__":
    run()
