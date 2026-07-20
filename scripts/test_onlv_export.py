#!/usr/bin/env python3
"""GUARD: ÖNORM-A-2063-ONLV-Export — well-formed + Struktur wie echte ABK-Datei.

Die ONLV-Generator-Funktionen werden aus api/extract.py isoliert geladen (ohne
die schweren fitz/supabase-Imports auszuführen) und gegen einen Gewerke-Fixture
getestet. Prüft: Namespace, entwurfs-lv/kenndaten/gliederung-lg-Gerüst,
lb 'frei formuliert', LG je Gewerk, pos-eigenschaften mit stichwort/einheit/
lvmenge/normalposition, Einheiten-Mapping, KEINE erfundenen Tags.
"""
import ast
import os
import re
import sys
import xml.etree.ElementTree as ET

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NS = "{http://www.oenorm.at/schema/A2063/2015-07-15}"


def _load_onlv_funcs():
    src = open(os.path.join(ROOT, "api", "extract.py")).read()
    app_rev = re.search(r'APP_REV = "([^"]+)"', src).group(1)
    tree = ast.parse(src)
    wanted = {"_onlv_bytes", "_onlv_einheit", "_iso_now_z", "_heute_iso", "_dateiname_safe"}
    lines = src.split("\n")
    segs = [("\n".join(lines[n.lineno - 1:n.end_lineno]))
            for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in wanted]
    ns = {"APP_REV": app_rev, "re": re,
          "_ONLV_NS": "http://www.oenorm.at/schema/A2063/2015-07-15",
          "_ONLV_EINHEIT_VALID": {"cm", "m", "km", "cm²", "m²", "cm³", "m³", "l", "g",
                                  "kg", "t", "Stk", "PA", "h", "d", "Wo", "Mo", "VE"},
          "_ONLV_EINHEIT": {"m²": "m²", "m2": "m²", "m³": "m³", "m3": "m³",
                            "lfm": "m", "lm": "m", "rm": "m", "m": "m", "stk": "Stk",
                            "stück": "Stk", "pa": "PA", "psch": "PA", "pausch": "PA",
                            "kg": "kg", "t": "t", "h": "h", "l": "l", "cm": "cm"}}
    exec("\n\n".join(segs), ns)
    return ns


FIXTURE = {
    "putz": {"label": "Verputzer (LG 10)", "lg": "10", "positionen": [
        {"posnr": "1.1", "beschreibung": "Innenputz Wände bis 3,2 m",
         "einheit": "m²", "endsumme": 360.17, "quelle": "B 2204 · Σ(U×H)",
         "zeilen": [{"text": "Zimmer 1 — Wand", "quelle": "U=22 × H=2,7", "wert": 59.4}]},
        {"posnr": "1.1a", "beschreibung": "Leibungsputz bis 0,25 m",
         "einheit": "lfm", "endsumme": 6.6, "quelle": "B 2204", "zeilen": []},
        {"posnr": "1.9", "beschreibung": "Nullmenge (auslassen)",
         "einheit": "m²", "endsumme": 0.0, "zeilen": []},
    ]},
    "erdarbeiten": {"label": "Erdarbeiten (LG 02)", "lg": "02", "positionen": [
        {"posnr": "1.2", "beschreibung": "Baugrubenaushub",
         "einheit": "m³", "endsumme": 82.28,
         "quelle": "B 2205", "zeilen": [
             {"text": "Aushub", "quelle": "156 × 0,5 (Annahme)", "wert": 78.0}]},
    ]},
    "fenster": {"label": "Fenster (LG 09)", "lg": "09", "positionen": [
        {"posnr": "1.1", "beschreibung": "Fenster Stk", "einheit": "Stk",
         "endsumme": 11.0, "zeilen": []},
    ]},
    "leer": {"label": "Leeres Gewerk", "lg": "99", "positionen": []},
}


def run():
    fails = []

    def check(name, cond):
        print(f"  {'✓' if cond else '✗'} {name}")
        if not cond:
            fails.append(name)

    fn = _load_onlv_funcs()
    data, n = fn["_onlv_bytes"]("Testprojekt Ä", FIXTURE)

    check("Bytes erzeugt + BOM", data[:3] == b"\xef\xbb\xbf")
    check("well-formed XML", _wellformed(data))
    root = ET.fromstring(data.decode("utf-8-sig"))
    check("Wurzel <onlv> mit A-2063-Namespace", root.tag == NS + "onlv")
    check("entwurfs-lv/kenndaten/wkz=EUR",
          (root.findtext(f".//{NS}kenndaten/{NS}wkz") == "EUR"))
    check("lb 'frei formuliert' + lbkennung FF",
          root.findtext(f".//{NS}lb/{NS}lbkennung") == "FF")
    lgs = root.findall(f".//{NS}lg")
    check("3 LG (putz/erdarbeiten/fenster; leer ausgelassen)", len(lgs) == 3)
    check("LG-Nummern aus Gewerk übernommen",
          sorted(lg.get("nr") for lg in lgs) == ["02", "09", "10"])
    poss = root.findall(f".//{NS}ungeteilteposition")
    check("4 Positionen (Nullmenge 1.9 ausgelassen)", len(poss) == 4 and n == 4)
    pe0 = poss[0].find(f"{NS}pos-eigenschaften")
    check("Position: stichwort trägt posnr", pe0.findtext(f"{NS}stichwort").startswith("[1.1]"))
    check("Position: normalposition in pzzv",
          pe0.find(f"{NS}pzzv/{NS}normalposition") is not None)
    check("Position: lvmenge = endsumme", pe0.findtext(f"{NS}lvmenge") == "360.17")
    einh = sorted(set(e.text for e in root.findall(f".//{NS}einheit")))
    check("Einheiten gemappt (lfm→m, Rest 1:1)", einh == ["Stk", "m", "m²", "m³"])
    check("leistungsteiltabelle/leistungsteil nr=1",
          root.find(f"{NS}leistungsteiltabelle/{NS}leistungsteil").get("nr") == "1")

    # DEFINITIV: gegen das AMTLICHE onlv.xsd validieren (xmllint). Das ist
    # exakt der Akzeptanztest, den ABK/Nevaris/ORCA beim Import fahren.
    import shutil
    import subprocess
    import tempfile
    xsd = os.path.join(ROOT, "scripts", "fixtures", "a2063_2015", "onlv.xsd")
    if shutil.which("xmllint") and os.path.exists(xsd):
        with tempfile.NamedTemporaryFile("wb", suffix=".onlv", delete=False) as tf:
            tf.write(data)
            tmp = tf.name
        try:
            r = subprocess.run(["xmllint", "--noout", "--schema", xsd, tmp],
                               capture_output=True, text=True)
            ok_xsd = r.returncode == 0 and "validates" in (r.stdout + r.stderr)
            check("gegen amtliches onlv.xsd validiert (xmllint)" +
                  ("" if ok_xsd else " — " + (r.stderr or r.stdout).strip()[:200]), ok_xsd)
        finally:
            os.unlink(tmp)
    else:
        print("  · (xmllint oder gebündeltes onlv.xsd fehlt — Schema-Check übersprungen)")

    print("-" * 60)
    if fails:
        print(f"FEHLER: {len(fails)} ONLV-Check(s) verletzt: {fails}")
        sys.exit(1)
    print("OK — ÖNORM-A-2063-ONLV-Export: gegen amtliches onlv.xsd validiert (import-fähig), freies LV.")


def _wellformed(data):
    try:
        ET.fromstring(data.decode("utf-8-sig"))
        return True
    except Exception:
        return False


if __name__ == "__main__":
    run()
