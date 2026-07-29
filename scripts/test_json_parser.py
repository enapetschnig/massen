"""WÄCHTER Vision-Antwort-Parser: keine Auswertung darf an der Verpackung
scheitern.

Am 2510-Scan belegt: das Modell antwortet auf den Grundriss-Pass mit ZWEI
JSON-Blöcken — erst falsch (Pixel), dann die Selbstkorrektur ("Korrektur mit
korrekten Prozentwerten"). Der frühere gierige Ausdruck \\{[\\s\\S]*\\} spannte
von der ERSTEN bis zur LETZTEN Klammer über beide Blöcke → ungültiges JSON →
das Ergebnis wurde KOMPLETT verworfen und der Scan zeigte keine Räume.
Betroffen waren 8 Stellen quer durch alle Vision-Pässe.
"""
import json
import os
import re
import sys

ROOT = os.path.join(os.path.dirname(__file__), "..")
_src = open(os.path.join(ROOT, "api", "extract.py"), encoding="utf-8").read()
_i = _src.index("def _json_aus_antwort")
_j = _src.index("\nAPP_REV")
_ns = {"re": re, "json": json}
exec(compile(_src[_i:_j], "parser", "exec"), _ns)
_parse = _ns["_json_aus_antwort"]


def run():
    # 1) DER ECHTE FALL: zwei Blöcke, der zweite ist die Korrektur
    roh = ('```json\n{"grundrisse": [{"geschoss": "KG", "x0_pct": 2, '
           '"y0_pct": 725, "x1_pct": 470, "y1_pct": 1270}]}\n```\n\n'
           'Korrektur mit korrekten Prozentwerten (0-100 Skala):\n\n'
           '```json\n{"grundrisse": [{"geschoss": "KG", "x0_pct": 1, '
           '"y0_pct": 57, "x1_pct": 18, "y1_pct": 100}]}\n```')
    d = _parse(roh)
    assert d and d.get("grundrisse"), "zwei Blöcke → nichts geparst"
    g = d["grundrisse"][0]
    assert g["y0_pct"] == 57, \
        f"muss die KORREKTUR nehmen, nahm {g['y0_pct']}"

    # 2) Markdown-Zaun, obwohl der Prompt 'kein Markdown' verlangt
    assert _parse('```json\n{"raeume": [1,2]}\n```') == {"raeume": [1, 2]}
    assert _parse('```\n{"a": 1}\n```') == {"a": 1}

    # 3) blankes JSON und JSON im Fließtext
    assert _parse('{"a": 1}') == {"a": 1}
    assert _parse('Hier: {"a": 2} — fertig') == {"a": 2}

    # 4) verschachtelte Klammern bleiben heil (Balance, nicht gierig)
    tief = '{"a": {"b": {"c": [1, 2]}}, "d": 3}'
    assert _parse("Text " + tief + " Text") == json.loads(tief)

    # 5) kaputt/leer → {} statt Absturz
    for murks in ("", None, "kein json", "{unvollständig", "```json\n{ap```"):
        assert _parse(murks) == {}, f"{murks!r} muss {{}} liefern"

    # 6) erster Block kaputt, zweiter gut → der gute gewinnt
    assert _parse('{"kaputt": ] } danach {"gut": 1}') == {"gut": 1}

    # 7) in extract.py darf KEIN gieriger Parser mehr stehen
    assert 're.search(r"\\{[\\s\\S]*\\}"' not in _src, \
        "gieriger JSON-Ausdruck wieder eingeschlichen"

    print("OK — Vision-Parser: Selbstkorrektur gewinnt · Markdown-Zaun · "
          "verschachtelt · kaputt→{} · kein gieriger Ausdruck mehr im Code")


if __name__ == "__main__":
    run()
