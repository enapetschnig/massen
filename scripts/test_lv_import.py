"""WÄCHTER LV-Import (ÖNORM A 2063): Positionen übernehmen statt abtippen.

Der Gegenweg zum Export. Ein Baubetrieb bekommt das LV vom Auftraggeber und
will die MENGEN einsetzen — nicht 200 Positionen abtippen. Wichtigste Zusage:
der RUNDLAUF trägt (was wir schreiben, lesen wir auch wieder) UND fremde
Dateien werden toleriert, denn ABK/Nevaris/ORCA unterscheiden sich in
Namensraum und Gliederung.
"""
import os
import sys
import xml.etree.ElementTree as ET

ROOT = os.path.join(os.path.dirname(__file__), "..")
_src = open(os.path.join(ROOT, "api", "extract.py"), encoding="utf-8").read()
_i = _src.index("def _onlv_lesen")
_j = _src.index('@app.post("/api/lv-import")')
_ns = {"ET": ET}
exec(compile(_src[_i:_j], "imp", "exec"), _ns)
_lesen = _ns["_onlv_lesen"]

NS = "http://www.oenorm.at/schema/A2063/2015-07-15"


def _lv(namespace=True, tag="ungeteilteposition", nr_als_attribut=True):
    """Minimales A-2063-LV bauen — mit/ohne Namensraum, verschiedene Varianten."""
    n = f' xmlns="{NS}"' if namespace else ""
    nr = ' nr="01.01"' if nr_als_attribut else ""
    return (f'<?xml version="1.0" encoding="utf-8"?><onlv{n}>'
            f'<entwurfs-lv><gliederung-lg>'
            f'<{tag} mfv=""{nr}><pos-eigenschaften>'
            f'<stichwort>Estrich 60 mm</stichwort>'
            f'<einheit>m2</einheit><lvmenge>123.45</lvmenge>'
            f'<langtext><p>Zementestrich</p><p>nach Norm</p></langtext>'
            f'</pos-eigenschaften></{tag}>'
            f'</gliederung-lg></entwurfs-lv></onlv>').encode("utf-8")


def run():
    # 1) RUNDLAUF mit unserem eigenen Export (die harte Zusage)
    eigen = os.path.join(ROOT, "scripts", "fixtures", "lv_rundlauf.onlv")
    if os.path.exists(eigen):
        r = _lesen(open(eigen, "rb").read())
        assert r.get("ok") and r["n"] >= 5, f"eigener Export nicht lesbar: {r}"

    # 2) Standardfall: mit Namensraum
    r = _lesen(_lv())
    assert r["ok"] and r["n"] == 1, r
    p = r["positionen"][0]
    assert p["stichwort"] == "Estrich 60 mm"
    assert p["einheit"] == "m2"
    assert abs(p["menge"] - 123.45) < 1e-6
    assert p["nr"] == "01.01"
    assert "Zementestrich" in (p["langtext"] or "")

    # 3) FREMDE Datei OHNE Namensraum — darf nicht scheitern
    r = _lesen(_lv(namespace=False))
    assert r["ok"] and r["n"] == 1, "ohne Namensraum nicht gelesen"

    # 4) geteilteposition (andere Gliederung) wird ebenfalls erkannt
    r = _lesen(_lv(tag="geteilteposition"))
    assert r["ok"] and r["n"] == 1, "geteilteposition nicht erkannt"

    # 5) Positionsnummer als ELEMENT statt Attribut (Erzeuger-Unterschied)
    roh = _lv(nr_als_attribut=False).replace(
        b"<stichwort>", b"<posnr>02.02</posnr><stichwort>")
    r = _lesen(roh)
    assert r["ok"] and r["positionen"][0]["nr"] == "02.02", r["positionen"][0]

    # 6) Fehlerfaelle: ehrliche Meldung statt Absturz
    for murks in (b"", b"kein xml", b"<html><body>nein</body></html>",
                  b'<?xml version="1.0"?><onlv/>'):
        r = _lesen(murks)
        assert r["ok"] is False and r.get("grund"), f"{murks[:20]!r} -> {r}"

    # 7) Menge darf fehlen (LV ohne Mengen = genau der Normalfall beim Import!)
    ohne = _lv().replace(b"<lvmenge>123.45</lvmenge>", b"")
    r = _lesen(ohne)
    assert r["ok"] and r["positionen"][0]["menge"] is None, \
        "LV ohne Mengen muss lesbar sein — das ist der Hauptfall"

    print("OK — LV-Import: Rundlauf trägt · mit/ohne Namensraum · "
          "geteilte+ungeteilte Position · Nr. als Attribut ODER Element · "
          "LV OHNE Mengen lesbar (Hauptfall) · kaputte Datei → ehrliche Meldung")


if __name__ == "__main__":
    run()
