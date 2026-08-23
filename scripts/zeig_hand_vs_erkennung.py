"""BILD: Handarbeit (grün) gegen Erkennung (rot) auf dem echten Plan.

Warum ein Bild und keine weitere Kennzahl: die Gegenprobe "Umriss auf Wand"
kann nicht unterscheiden, ob die REGION daneben liegt oder ob die WAND falsch
erkannt wurde — sie misst beides gegeneinander. Ein Rendering über dem
Original-Plan zeigt in einem Blick, wer recht hat (Muster aus
project_nachzeichnen2_raumverifikation: Label-Karte rendern schlägt blindes
Parameter-Drehen).

Gezeichnet wird:
  GRÜN   die handgezogenen Umrisse (Wahrheit des Nutzers)
  ROT    die erkannten Regionen
  BLAU   die erkannten Wandlinien (unabhängige Vektor-Quelle)
  GELB   die Raum-Stempel-Position (byte-exakt aus dem PDF-Textlayer)

Lauf: massenermittlung/venv/bin/python3 scripts/zeig_hand_vs_erkennung.py
"""
from __future__ import annotations

import io
import json
import os
import sys
import urllib.request

WURZEL = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROJEKT = "82278c64-6a98-4b24-815b-52feaed59184"
AUS = os.path.join(WURZEL, "hand_vs_erkennung.png")
NUR_PLAN = None


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


def _hole(pfad):
    url, key = _env()
    req = urllib.request.Request(url + pfad, headers={
        "apikey": key, "Authorization": "Bearer " + key})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


def _nrm(s):
    s = (s or "").lower()
    for a, b in (("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("ß", "ss")):
        s = s.replace(a, b)
    return "".join(c for c in s if c.isalnum())


def main():
    from PIL import Image, ImageDraw

    url, key = _env()
    os.environ.setdefault("SUPABASE_URL", url)
    os.environ.setdefault("SUPABASE_SERVICE_KEY", key)
    sys.path.insert(0, os.path.join(WURZEL, "api"))
    import extract  # noqa: E402

    plaene = _hole(f"/rest/v1/plaene?projekt_id=eq.{PROJEKT}"
                   f"&select=id,dateiname,agent_log")
    if "--plan" in sys.argv:
        globals()["NUR_PLAN"] = sys.argv[sys.argv.index("--plan") + 1]
    ziel = None
    for p in plaene:
        if NUR_PLAN and p["id"] != NUR_PLAN:
            continue
        log = p.get("agent_log") or {}
        for key_k, k in log.items():
            if "korrektur" in key_k and isinstance(k, dict) and k.get("raum_regionen"):
                ziel = (p, k["raum_regionen"])
    if not ziel and NUR_PLAN:
        # Quervergleich: Plan ohne Handarbeit — nur Erkennung + Wände zeigen
        plan = next(p for p in plaene if p["id"] == NUR_PLAN)
        hand = {}
    elif not ziel:
        print("Keine handgezogenen Umrisse gefunden.")
        sys.exit(1)
    else:
        plan, hand = ziel
    print(f"Plan: {plan['dateiname']}  ({len(hand)} Hand-Räume)")

    class B:
        pass
    b = B()
    b.plan_id = plan["id"]
    b.projekt_id = None
    b.seite = None
    b.leicht = False
    erg = extract._nachzeichnen_roh(b)
    if not erg or not erg.get("ok"):
        print("Nachzeichnen fehlgeschlagen:", (erg or {}).get("grund"))
        sys.exit(1)

    png = erg.get("basis_png")
    bild = Image.open(io.BytesIO(png)).convert("RGB")
    d = ImageDraw.Draw(bild, "RGBA")
    print(f"Bild {bild.width}x{bild.height} · gemeldet "
          f"{erg.get('bild_w')}x{erg.get('bild_h')}")

    # Wände (blau, dünn) — die unabhängige Vektor-Quelle
    for w in erg.get("waende") or []:
        px = w.get("px")
        if px and len(px) >= 4:
            d.line([px[0], px[1], px[2], px[3]], fill=(40, 90, 230, 190), width=3)

    ist_map = {}
    for r in erg.get("raeume") or []:
        if r.get("region_px") and len(r["region_px"]) >= 3:
            ist_map[_nrm(r.get("name"))] = r

    schluessel_liste = sorted(hand.keys()) or sorted(ist_map.keys())
    for schluessel in schluessel_liste:
        v = hand.get(schluessel)
        r_ist = ist_map.get(schluessel)
        # Erkennung: ROT
        if r_ist:
            pts = [tuple(p) for p in r_ist["region_px"]]
            d.line(pts + [pts[0]], fill=(230, 30, 30, 255), width=6)
            # Stempel-Position (byte-exakt aus dem Textlayer): GELB
            if r_ist.get("px"):
                x, y = r_ist["px"]
                d.ellipse([x - 11, y - 11, x + 11, y + 11],
                          fill=(255, 210, 0, 255), outline=(120, 90, 0, 255), width=3)
        # Handarbeit: GRÜN
        if v:
            pts = [tuple(p) for p in v["region_px"]]
            d.line(pts + [pts[0]], fill=(20, 175, 70, 255), width=6)

    d.rectangle([10, 10, 640, 132], fill=(255, 255, 255, 235),
                outline=(30, 30, 30, 255), width=2)
    d.text((26, 26), "GRUEN = von Hand gezogen (Wahrheit)", fill=(20, 140, 60))
    d.text((26, 52), "ROT   = Erkennung (Regionen)", fill=(200, 20, 20))
    d.text((26, 78), "BLAU  = erkannte Wandlinien", fill=(30, 70, 200))
    d.text((26, 104), "GELB  = Raum-Stempel (byte-exakt aus dem PDF)",
           fill=(150, 110, 0))

    ziel_datei = AUS.replace(".png", "_" + plan["dateiname"][:12].replace(" ", "_") + ".png") if NUR_PLAN else AUS
    bild.save(ziel_datei)
    print("geschrieben:", ziel_datei)


if __name__ == "__main__":
    main()
