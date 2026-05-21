#!/usr/bin/env python3
"""ÖNORM-Massenermittlung mit Gewerk-Auswahl.

Baut auf scripts/oenorm_extract.py (Raum-Erkennung) auf und erzeugt pro
gewähltem Gewerk eine buchmäßige Massenermittlung (LV in Buchform):

  - Putz       (ÖNORM B 2210): Wandflächen, Öffnungsabzüge, Laibungen, Decken
  - Rohbau     (ÖNORM B 2208): Mauerwerk m², Decke/Bodenplatte Stahlbeton m³
  - Estrich    (ÖNORM B 2232): Bodenflächen pro Belag, Randdämmstreifen
  - Maler                    : Wand-/Deckenflächen mit Öffnungsabzug

Wandstärken / Deckendicke / Öffnungszahlen werden per Claude Vision aus dem
Plan gemessen (vision_baudaten) — diese Werte stehen nicht im Text-Layer.

Aufruf:  python3 scripts/massen_oenorm.py <plan.pdf> [gewerk1,gewerk2,...]
         Gewerke: putz, rohbau, estrich, maler  (Default: alle)
"""
from __future__ import annotations
import base64
import json
import math
import re
import sys
from pathlib import Path
from typing import Optional

import fitz

sys.path.insert(0, str(Path(__file__).parent))
from oenorm_extract import analyse_pdf, LVPosition, kategorie_of


# ════════════════════════════════════════════════════════════════════════
# ÖNORM-Konstanten & Standard-Annahmen
# ════════════════════════════════════════════════════════════════════════
# ÖNORM B 2210 (Putz): Öffnungen über dieser Einzelgröße werden abgezogen,
# darunter übermessen. Laibungen werden nur bei abgezogenen Öffnungen gerechnet.
OEFFNUNG_ABZUG_SCHWELLE_M2 = 2.5

# Fallback-Werte falls Vision nichts liefert (dokumentiert, in UI änderbar)
DEFAULT_BAUDATEN = {
    "aussenwand_cm": 38,
    "innenwand_tragend_cm": 25,
    "innenwand_nichttragend_cm": 12,
    "decke_cm": 20,
    "bodenplatte_cm": 25,
    "geschosshoehe_m": 2.70,
    "tuer_breite_m": 0.90,
    "tuer_hoehe_m": 2.10,
}


# ════════════════════════════════════════════════════════════════════════
# Vision: Baudaten aus dem Plan messen
# ════════════════════════════════════════════════════════════════════════
VISION_BAUDATEN_PROMPT = """Du bist ein erfahrener österreichischer Bautechniker.
Du siehst einen Bauplan (Grundriss / Polierplan / Einreichplan).

Bestimme folgende Bau-Kenndaten so genau wie möglich aus den gezeichneten
Wanddicken, Bemaßungen, Schnitten und der Material-Legende:

Antworte NUR mit JSON (keine Markdown-Fences):
{
  "aussenwand_cm": 50,
  "innenwand_tragend_cm": 25,
  "innenwand_nichttragend_cm": 12,
  "decke_cm": 20,
  "bodenplatte_cm": 25,
  "geschosshoehe_m": 2.70,
  "anzahl_fenster": 8,
  "anzahl_tueren_innen": 7,
  "anzahl_tueren_aussen": 2,
  "wandmaterial": "z.B. Ziegel wärmedämmend / Stahlbeton",
  "konfidenz": 0.85,
  "begruendung": "kurze Erklärung woran erkannt"
}

REGELN:
- Werte in cm (Wandstärken/Decke) bzw. m (Geschosshöhe).
- Wenn ein Wert nicht erkennbar: null setzen, niemals raten.
- Fenster/Türen zählen: nur was klar im Grundriss sichtbar ist."""


def vision_baudaten(pdf_path: Path, api_key: str) -> dict:
    """Misst Wandstärken, Deckendicke, Öffnungszahlen per Claude Vision."""
    import anthropic
    client = anthropic.Anthropic(api_key=api_key)
    doc = fitz.open(pdf_path)
    page = doc[0]

    # Plan rendern — adaptive Auflösung unter 4.5 MB / 8000 px
    dpi = 220
    while dpi >= 90:
        mat = fitz.Matrix(dpi / 72, dpi / 72)
        pix = page.get_pixmap(matrix=mat)
        img = pix.tobytes("jpeg", jpg_quality=82)
        if len(img) < 4.5 * 1024 * 1024 and pix.width <= 8000 and pix.height <= 8000:
            break
        dpi -= 40
    doc.close()

    b64 = base64.standard_b64encode(img).decode()
    try:
        resp = client.messages.create(
            model="claude-sonnet-4-20250514", max_tokens=1024,
            temperature=0,  # deterministisch — sonst schwanken Wandstärken
            system=VISION_BAUDATEN_PROMPT,
            messages=[{"role": "user", "content": [
                {"type": "image", "source": {"type": "base64",
                 "media_type": "image/jpeg", "data": b64}},
                {"type": "text", "text": "Bestimme die Bau-Kenndaten dieses Plans."}
            ]}],
        )
        raw = resp.content[0].text if resp.content else "{}"
        try:
            data = json.loads(raw)
        except Exception:
            m = re.search(r"\{[\s\S]*\}", raw)
            data = json.loads(m.group()) if m else {}
    except Exception as e:
        print(f"[vision] Baudaten-Messung fehlgeschlagen: {e}")
        data = {}

    # Konfidenz-Schwelle: bei unsicherer Vision (<0.7) lieber dokumentierte
    # Defaults nutzen — eine geratene Wandstärke verfälscht das Beton-Volumen
    # massiv. Der Nutzer kann die Werte in der UI ohnehin überschreiben.
    vis_konf = data.get("konfidenz") or 0
    vision_vertrauen = vis_konf >= 0.7

    # Mit Defaults auffüllen, Quelle pro Wert vermerken
    result = {"_quellen": {}}
    for key, default in DEFAULT_BAUDATEN.items():
        v = data.get(key)
        if vision_vertrauen and v is not None and isinstance(v, (int, float)) and v > 0:
            result[key] = v
            result["_quellen"][key] = "vision"
        else:
            result[key] = default
            result["_quellen"][key] = "default" + (
                " (Vision unsicher)" if (v and not vision_vertrauen) else "")
    for extra in ("anzahl_fenster", "anzahl_tueren_innen", "anzahl_tueren_aussen",
                  "wandmaterial", "konfidenz", "begruendung"):
        result[extra] = data.get(extra)
    return result


# ════════════════════════════════════════════════════════════════════════
# Öffnungs-Logik (ÖNORM B 2210)
# ════════════════════════════════════════════════════════════════════════
def oeffnung_abzug(breite_m: float, hoehe_m: float) -> bool:
    """ÖNORM B 2210: Öffnung wird abgezogen, wenn Einzelfläche > 2,5 m²."""
    return (breite_m * hoehe_m) > OEFFNUNG_ABZUG_SCHWELLE_M2


def laibungsflaeche(breite_m: float, hoehe_m: float, tiefe_m: float,
                    mit_sohlbank: bool = False) -> float:
    """Abgewickelte Laibungsfläche einer Öffnung.
    = Laibungstiefe × (2 × Höhe + Breite [+ Breite falls Sohlbank])."""
    umfang = 2 * hoehe_m + breite_m
    if mit_sohlbank:
        umfang += breite_m
    return tiefe_m * umfang


# ════════════════════════════════════════════════════════════════════════
# Fenster / Türen den Räumen zuordnen
# ════════════════════════════════════════════════════════════════════════
def fenster_pro_raum(rooms: list[dict], windows: list[dict]) -> dict:
    """Ordnet jedes Fenster dem nächstgelegenen Raum zu."""
    zuord = {id(r): [] for r in rooms}
    for w in windows:
        wx, wy = w.get("cx"), w.get("cy")
        if wx is None:
            continue
        best, best_d = None, 1e9
        for r in rooms:
            d = math.hypot(r["cx"] - wx, r["cy"] - wy)
            if d < best_d:
                best_d, best = d, r
        if best and best_d < 400:
            zuord[id(best)].append(w)
    return zuord


# ════════════════════════════════════════════════════════════════════════
# GEWERK: Putz (ÖNORM B 2210)
# ════════════════════════════════════════════════════════════════════════
def gewerk_putz(rooms, windows, baudaten, geschoss="EG") -> list[LVPosition]:
    positionen = []
    laibung_t = baudaten["aussenwand_cm"] / 100.0 * 0.33  # Laibungstiefe ≈ ⅓ Wandstärke
    fzuord = fenster_pro_raum(rooms, windows)
    innen = [r for r in rooms if kategorie_of(r.get("name", "")) == "Innenraum_warm"]

    # ── Pos 1: Innenputz Wände ──
    pos = LVPosition("1.1", f"Innenputz Wände — {geschoss}", "m²")
    pos.quelle = "ÖNORM B 2210 · Σ(U×H) − Öffnungen>2,5m² + Laibungen"
    for r in innen:
        u, h = r.get("umfang_m"), r.get("hoehe_m") or baudaten["geschosshoehe_m"]
        if not u:
            continue
        brutto = u * h
        pos.add_zeile(f"{r['name']} — Wand brutto", laenge=u, hoehe=h, summe=brutto,
                      quelle=f"U={u} × H={h}")
        # Fenster-Abzüge dieses Raums
        for w in fzuord.get(id(r), []):
            bw, hw = w.get("breite_m", 0), w.get("hoehe_m", 0)
            if bw and hw and oeffnung_abzug(bw, hw):
                pos.add_zeile(f"  Abzug Fenster {w.get('code','')}",
                              laenge=bw, hoehe=-hw, summe=-(bw * hw),
                              quelle="Öffnung >2,5 m²")
                lb = laibungsflaeche(bw, hw, laibung_t)
                pos.add_zeile(f"  Laibung Fenster {w.get('code','')}",
                              summe=lb, quelle=f"Tiefe {laibung_t:.2f}m × Abwicklung")
    pos.konfidenz = 0.9
    positionen.append(pos)

    # ── Pos 2: Innenputz Decken ──
    pos = LVPosition("1.2", f"Innenputz Decken — {geschoss}", "m²")
    pos.quelle = "ÖNORM B 2210 · Σ Raumfläche"
    for r in innen:
        if r.get("flaeche_m2"):
            pos.add_zeile(r["name"], summe=r["flaeche_m2"], quelle=f"F={r['flaeche_m2']}")
    pos.konfidenz = 0.97
    positionen.append(pos)

    return positionen


# ════════════════════════════════════════════════════════════════════════
# GEWERK: Rohbau / Maurer (ÖNORM B 2208)
# ════════════════════════════════════════════════════════════════════════
def gewerk_rohbau(rooms, windows, baudaten, geschoss="EG") -> list[LVPosition]:
    positionen = []
    innen = [r for r in rooms if kategorie_of(r.get("name", "")) == "Innenraum_warm"]
    h = baudaten["geschosshoehe_m"]

    # ── Pos 1: Wand-Abwicklung (Raum-Innenseiten) ──
    # WICHTIG: Σ(U×H) pro Raum zählt jede Innenwand DOPPELT (von beiden
    # angrenzenden Räumen). Für Mauerwerks-VOLUMEN ist das nicht direkt
    # nutzbar — dafür braucht es die Wand-Geometrie (Außen-/Innenwand-
    # Trennung). Diese Position ist die abgewickelte Raum-Innenwandfläche
    # und dient als Kontrollwert; sie ist NICHT das Mauerwerks-Aufmaß.
    pos = LVPosition("1.1", f"Wand-Abwicklung Raum-Innenseiten — {geschoss}", "m²")
    pos.quelle = ("Σ(U×H) aller Räume — Innenwände doppelt gezählt. "
                  "Mauerwerks-Volumen erfordert Wand-Geometrie (eigener Schritt).")
    sum_wand = 0.0
    for r in innen:
        u = r.get("umfang_m")
        hh = r.get("hoehe_m") or h
        if u:
            pos.add_zeile(r["name"], laenge=u, hoehe=hh, summe=u * hh,
                          quelle=f"U={u} × H={hh}")
            sum_wand += u * hh
    pos.konfidenz = 0.6  # bewusst niedrig: Kontrollwert, kein Aufmaß
    positionen.append(pos)

    # ── Pos 2: Decke Stahlbeton (m³) ──
    decke_m = baudaten["decke_cm"] / 100.0
    pos = LVPosition("1.2", f"Stahlbeton-Decke über {geschoss}", "m³")
    pos.quelle = f"ÖNORM B 2208 · Σ Fläche × Deckendicke {decke_m:.2f}m"
    for r in innen:
        if r.get("flaeche_m2"):
            pos.add_zeile(r["name"], laenge=r["flaeche_m2"], hoehe=decke_m,
                          summe=r["flaeche_m2"] * decke_m,
                          quelle=f"F={r['flaeche_m2']} × d={decke_m:.2f}")
    pos.konfidenz = 0.85 if baudaten["_quellen"].get("decke_cm") == "vision" else 0.6
    positionen.append(pos)

    # ── Pos 3: Bodenplatte (m³) — nur für EG/KG sinnvoll ──
    if geschoss.upper() in ("EG", "KG", "UG"):
        bopl_m = baudaten["bodenplatte_cm"] / 100.0
        grundflaeche = sum(r.get("flaeche_m2", 0) or 0 for r in innen)
        pos = LVPosition("1.3", f"Bodenplatte Stahlbeton — {geschoss}", "m³")
        pos.quelle = f"Grundfläche × Plattendicke {bopl_m:.2f}m"
        pos.add_zeile("Bodenplatte gesamt", laenge=grundflaeche, hoehe=bopl_m,
                      summe=grundflaeche * bopl_m,
                      quelle=f"ΣF={grundflaeche:.2f} × d={bopl_m:.2f}")
        pos.konfidenz = 0.8 if baudaten["_quellen"].get("bodenplatte_cm") == "vision" else 0.55
        positionen.append(pos)

    return positionen


# ════════════════════════════════════════════════════════════════════════
# GEWERK: Estrich (ÖNORM B 2232)
# ════════════════════════════════════════════════════════════════════════
def gewerk_estrich(rooms, windows, baudaten, geschoss="EG") -> list[LVPosition]:
    positionen = []
    innen = [r for r in rooms if kategorie_of(r.get("name", "")) == "Innenraum_warm"]

    pos = LVPosition("1.1", f"Estrich-Fläche — {geschoss}", "m²")
    pos.quelle = "ÖNORM B 2232 · Σ Raumfläche"
    for r in innen:
        if r.get("flaeche_m2"):
            pos.add_zeile(r["name"], summe=r["flaeche_m2"], quelle=f"F={r['flaeche_m2']}")
    pos.konfidenz = 0.97
    positionen.append(pos)

    # Randdämmstreifen = Σ Raumumfang (lfm)
    pos = LVPosition("1.2", f"Randdämmstreifen — {geschoss}", "lfm")
    pos.quelle = "ÖNORM B 2232 · Σ Raumumfang"
    for r in innen:
        if r.get("umfang_m"):
            pos.add_zeile(r["name"], laenge=r["umfang_m"], summe=r["umfang_m"],
                          quelle=f"U={r['umfang_m']}")
    pos.konfidenz = 0.95
    positionen.append(pos)

    return positionen


# ════════════════════════════════════════════════════════════════════════
# GEWERK: Maler
# ════════════════════════════════════════════════════════════════════════
def gewerk_maler(rooms, windows, baudaten, geschoss="EG") -> list[LVPosition]:
    # Maler-Flächen = Putz-Flächen (gleiche Geometrie, ohne Laibungstiefe-Detail)
    positionen = []
    innen = [r for r in rooms if kategorie_of(r.get("name", "")) == "Innenraum_warm"]
    fzuord = fenster_pro_raum(rooms, windows)

    pos = LVPosition("1.1", f"Anstrich Wände — {geschoss}", "m²")
    pos.quelle = "Σ(U×H) − Öffnungen >2,5 m²"
    for r in innen:
        u, h = r.get("umfang_m"), r.get("hoehe_m") or baudaten["geschosshoehe_m"]
        if not u:
            continue
        pos.add_zeile(f"{r['name']} — Wand", laenge=u, hoehe=h, summe=u * h,
                      quelle=f"U={u} × H={h}")
        for w in fzuord.get(id(r), []):
            bw, hw = w.get("breite_m", 0), w.get("hoehe_m", 0)
            if bw and hw and oeffnung_abzug(bw, hw):
                pos.add_zeile(f"  Abzug Fenster {w.get('code','')}",
                              laenge=bw, hoehe=-hw, summe=-(bw * hw))
    pos.konfidenz = 0.88
    positionen.append(pos)

    pos = LVPosition("1.2", f"Anstrich Decken — {geschoss}", "m²")
    pos.quelle = "Σ Raumfläche"
    for r in innen:
        if r.get("flaeche_m2"):
            pos.add_zeile(r["name"], summe=r["flaeche_m2"])
    pos.konfidenz = 0.97
    positionen.append(pos)

    return positionen


GEWERKE = {
    "putz":    ("Verputzer (ÖNORM B 2210)", gewerk_putz),
    "rohbau":  ("Maurer / Rohbau (ÖNORM B 2208)", gewerk_rohbau),
    "estrich": ("Estrich / Boden (ÖNORM B 2232)", gewerk_estrich),
    "maler":   ("Maler / Anstrich", gewerk_maler),
}


# ════════════════════════════════════════════════════════════════════════
# Multi-Plan-Merge: Räume aus mehreren Plänen vereinen
# ════════════════════════════════════════════════════════════════════════
def merge_plan_rooms(plan_room_lists: list[list[dict]]) -> list[dict]:
    """Vereint Räume aus mehreren Plänen desselben Bauvorhabens.
    Einreichplan liefert F+U+Bodenbelag, Polierplan liefert H — gemeinsam
    ergeben sie vollständige Raum-Datensätze. Schlüssel: normierter Name."""
    def nk(s):
        return re.sub(r"[\s\-_/]+", "", (s or "").lower())

    merged = {}
    for rooms in plan_room_lists:
        for r in rooms:
            key = nk(r.get("name"))
            if not key:
                continue
            if key not in merged:
                merged[key] = dict(r)
            else:
                # Fehlende Werte aus diesem Plan ergänzen
                for fld in ("flaeche_m2", "umfang_m", "hoehe_m", "bodenbelag"):
                    if not merged[key].get(fld) and r.get(fld):
                        merged[key][fld] = r[fld]
    return list(merged.values())


# ════════════════════════════════════════════════════════════════════════
# Haupt-Pipeline
# ════════════════════════════════════════════════════════════════════════
def massenermittlung(pdf_paths, gewerke: list[str], api_key: Optional[str] = None) -> dict:
    """Vollständige ÖNORM-Massenermittlung für gewählte Gewerke.
    pdf_paths: ein Pfad ODER eine Liste von Pfaden (Multi-Plan-Bauvorhaben)."""
    if isinstance(pdf_paths, (str, Path)):
        pdf_paths = [Path(pdf_paths)]
    else:
        pdf_paths = [Path(p) for p in pdf_paths]

    # Alle Pläne analysieren
    plaene = [analyse_pdf(p) for p in pdf_paths]
    rooms = merge_plan_rooms([pl["rooms"] for pl in plaene])
    windows = []
    for pl in plaene:
        windows.extend(pl.get("windows") or [])
    geschoss = next((pl.get("geschoss") for pl in plaene if pl.get("geschoss")), "EG")
    massstab = next((pl.get("massstab") for pl in plaene if pl.get("massstab")), None)

    # Baudaten per Vision — vom Plan mit der höchsten Vision-Konfidenz
    # (Polierpläne liefern verlässlichere Wandstärken als Einreichpläne).
    if api_key:
        kandidaten = []
        for p in pdf_paths:
            bd = vision_baudaten(p, api_key)
            kandidaten.append((bd.get("konfidenz") or 0, bd))
        kandidaten.sort(key=lambda x: -x[0])
        baudaten = kandidaten[0][1]
    else:
        baudaten = dict(DEFAULT_BAUDATEN)
        baudaten["_quellen"] = {k: "default" for k in DEFAULT_BAUDATEN}

    ergebnis = {
        "pdf": ", ".join(p.name for p in pdf_paths),
        "anzahl_plaene": len(pdf_paths),
        "geschoss": geschoss,
        "massstab": massstab,
        "raeume": len(rooms),
        "baudaten": baudaten,
        "gewerke": {},
    }
    for g in gewerke:
        if g not in GEWERKE:
            continue
        label, fn = GEWERKE[g]
        positionen = fn(rooms, windows, baudaten, geschoss)
        ergebnis["gewerke"][g] = {
            "label": label,
            "positionen": [p.to_dict() for p in positionen],
        }
    return ergebnis


def print_report(erg: dict):
    print(f"\n{'═'*74}\n  ÖNORM-MASSENERMITTLUNG · {erg['pdf']}\n{'═'*74}")
    print(f"  Geschoss: {erg['geschoss']} | Maßstab: {erg['massstab']} | Räume: {erg['raeume']}")
    bd = erg["baudaten"]
    print(f"\n  Baudaten (Q=Quelle):")
    for k in ("aussenwand_cm", "innenwand_tragend_cm", "innenwand_nichttragend_cm",
              "decke_cm", "bodenplatte_cm", "geschosshoehe_m"):
        q = bd["_quellen"].get(k, "?")
        print(f"    {k:<28} {bd[k]:>7}   [{q}]")
    if bd.get("wandmaterial"):
        print(f"    wandmaterial: {bd['wandmaterial']}")
    if bd.get("konfidenz"):
        print(f"    Vision-Konfidenz: {bd['konfidenz']}")

    for gkey, gdata in erg["gewerke"].items():
        print(f"\n{'─'*74}\n  GEWERK: {gdata['label']}\n{'─'*74}")
        for p in gdata["positionen"]:
            print(f"  {p['posnr']:<6} {p['beschreibung']:<46} "
                  f"{p['endsumme']:>11.2f} {p['einheit']:<4} {p['konfidenz']*100:.0f}%")
            for z in p["zeilen"][:60]:
                detail = []
                if z.get("anzahl"): detail.append(f"n={z['anzahl']}")
                if z.get("laenge"): detail.append(f"L={z['laenge']}")
                if z.get("hoehe"): detail.append(f"H={z['hoehe']}")
                ds = " ".join(detail)
                print(f"         {z['text']:<44} {ds:<22} = {z['wert']:>10.3f}")


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    # Mehrere PDFs mit ';' getrennt, Gewerke mit ',' getrennt
    pdf_arg = sys.argv[1]
    pdfs = [Path(p.strip()).expanduser() for p in pdf_arg.split(";")]
    gewerke = sys.argv[2].split(",") if len(sys.argv) > 2 else list(GEWERKE.keys())

    env_path = Path(__file__).parent.parent / "massenermittlung" / ".env"
    api_key = None
    if env_path.exists():
        for ln in env_path.read_text().splitlines():
            if ln.startswith("ANTHROPIC_API_KEY="):
                api_key = ln.split("=", 1)[1].strip()

    erg = massenermittlung(pdfs, gewerke, api_key)
    print_report(erg)

    out = Path("/tmp/massen_oenorm.json")
    out.write_text(json.dumps(erg, indent=2, ensure_ascii=False, default=str))
    print(f"\n📄 JSON: {out}")


if __name__ == "__main__":
    main()
