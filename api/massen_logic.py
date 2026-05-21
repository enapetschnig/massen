"""ÖNORM-Massenermittlung — reine Berechnungs-Logik (deploybar auf Vercel).

Dieses Modul enthält KEINE fitz/anthropic-Abhängigkeiten — es bekommt fertig
extrahierte Räume + (per Vision gemessene) Baudaten und erzeugt pro Gewerk
eine buchmäßige Massenermittlung (LV in Buchform).

Wird von api/extract.py importiert. Gewerke:
  - putz    (ÖNORM B 2210): Wandflächen, Öffnungsabzüge, Laibungen, Decken
  - rohbau  (ÖNORM B 2208): Wand-Abwicklung, Decke/Bodenplatte Stahlbeton m³
  - estrich (ÖNORM B 2232): Bodenflächen, Randdämmstreifen
  - maler                 : Wand-/Deckenflächen mit Öffnungsabzug
"""
from __future__ import annotations
import math
import re

# ════════════════════════════════════════════════════════════════════════
# ÖNORM-Konstanten & Standard-Annahmen
# ════════════════════════════════════════════════════════════════════════
OEFFNUNG_ABZUG_SCHWELLE_M2 = 2.5  # ÖNORM B 2210: darüber abziehen + Laibung

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

KATEGORIE = {
    "Innenraum_warm": {
        "Wohnküche", "Wohnkueche", "Wohnen", "Wohnzimmer", "Wohnraum", "Esszimmer",
        "Zimmer", "Schlafzimmer", "Kinderzimmer", "Küche", "Kueche", "Bad", "WC",
        "Dusche", "Sauna", "Vorraum", "Vorzimmer", "Flur", "Gang", "Diele", "Garderobe",
        "Abstellraum", "Speis", "Speisekammer", "AR", "HWR", "HSR", "HAR",
        "Büro", "Buero", "Atelier", "Studio", "Praxis", "Arbeitszimmer",
        "Waschküche", "Waschkueche", "Waschraum", "Waschen", "Kiwa",
        "Windfang", "Foyer", "Eingang", "Eingangsbereich", "Fitness",
    },
    "Loggia": {"Loggia", "Balkon", "Terrasse", "Parkplatz", "Carport"},
    "Stiegenhaus": {"Stiegenhaus", "Stiege", "STGH", "STG", "Treppenhaus"},
    "Nebenraum_kalt": {
        "Tiefgarage", "Garage", "Keller", "Kellerabteil", "Technik", "Technikraum",
        "Müllraum", "E-Technik", "Elektroraum", "Pelletslager", "Pelletslagerraum",
        "Fahrradraum", "Kinderwagenraum", "Schleuse", "Werkstätte", "Werkstatt", "Lager",
    },
}


def kategorie_of(name: str):
    """Kategorisiert einen Raumnamen — exact, first-word, Bindestrich-Teile."""
    if not name:
        return None
    name = name.strip()
    candidates = [name]
    if " " in name:
        candidates.append(name.split()[0])
    if "-" in name:
        candidates.extend(p.strip() for p in name.split("-"))
    for kat, names in KATEGORIE.items():
        for c in candidates:
            if c in names:
                return kat
    return None


# ════════════════════════════════════════════════════════════════════════
# LV-Position (Buchform)
# ════════════════════════════════════════════════════════════════════════
class LVPosition:
    def __init__(self, posnr, beschreibung, einheit):
        self.posnr = posnr
        self.beschreibung = beschreibung
        self.einheit = einheit
        self.zeilen = []
        self.quelle = ""
        self.konfidenz = 1.0

    def add_zeile(self, text, anzahl=0, laenge=0, breite=0, hoehe=0,
                  summe=None, quelle=""):
        wert = summe
        if wert is None:
            wert = (anzahl or 1) * (laenge or 1) * (breite or 1) * (hoehe or 1)
        self.zeilen.append({
            "text": text,
            "anzahl": anzahl or None,
            "laenge": laenge or None,
            "breite": breite or None,
            "hoehe": hoehe or None,
            "wert": round(wert, 4),
            "quelle": quelle,
        })

    @property
    def endsumme(self):
        return round(sum(z["wert"] for z in self.zeilen), 2)

    def to_dict(self):
        return {
            "posnr": self.posnr,
            "beschreibung": self.beschreibung,
            "einheit": self.einheit,
            "endsumme": self.endsumme,
            "konfidenz": self.konfidenz,
            "quelle": self.quelle,
            "zeilen": self.zeilen,
        }


# ════════════════════════════════════════════════════════════════════════
# Öffnungs-Logik (ÖNORM B 2210)
# ════════════════════════════════════════════════════════════════════════
def oeffnung_abzug(breite_m, hoehe_m):
    """Öffnung wird abgezogen, wenn Einzelfläche > 2,5 m² (sonst übermessen)."""
    return (breite_m * hoehe_m) > OEFFNUNG_ABZUG_SCHWELLE_M2


def laibungsflaeche(breite_m, hoehe_m, tiefe_m, mit_sohlbank=False):
    """Abgewickelte Laibungsfläche = Tiefe × (2×Höhe + Breite [+Breite Sohlbank])."""
    umfang = 2 * hoehe_m + breite_m
    if mit_sohlbank:
        umfang += breite_m
    return tiefe_m * umfang


def _nk(s):
    return re.sub(r"[\s\-_/]+", "", (s or "").lower())


def fenster_pro_raum(rooms, windows):
    """Ordnet jedes Fenster einem Raum zu — per Raum-Name (Vision-Fenster)
    oder per Position (FE_-Code-Fenster mit cx/cy)."""
    zuord = {id(r): [] for r in rooms}
    # Name-Index für Vision-Fenster
    name_idx = {}
    for r in rooms:
        name_idx.setdefault(_nk(_room_name(r)), []).append(r)
    for w in windows:
        # 1. Vision-Fenster: Zuordnung per Raum-Name
        wraum = w.get("raum")
        if wraum:
            matches = name_idx.get(_nk(wraum))
            if matches:
                zuord[id(matches[0])].append(w)
                continue
        # 2. FE_-Code-Fenster: Zuordnung per Position
        wx, wy = w.get("cx"), w.get("cy")
        if wx is None:
            continue
        best, best_d = None, 1e9
        for r in rooms:
            rx, ry = r.get("cx"), r.get("cy")
            if rx is None:
                continue
            d = math.hypot(rx - wx, ry - wy)
            if d < best_d:
                best_d, best = d, r
        if best and best_d < 400:
            zuord[id(best)].append(w)
    return zuord


def _room_value(r, *keys):
    """Liest einen Wert aus dem Raum-dict — egal ob flach oder unter 'daten'."""
    for k in keys:
        if r.get(k) is not None:
            return r.get(k)
    d = r.get("daten") or {}
    for k in keys:
        if d.get(k) is not None:
            return d.get(k)
    return None


def _room_name(r):
    return r.get("name") or r.get("bezeichnung") or (r.get("daten") or {}).get("name") or "?"


# ════════════════════════════════════════════════════════════════════════
# GEWERKE
# ════════════════════════════════════════════════════════════════════════
def gewerk_putz(rooms, windows, baudaten, geschoss="EG"):
    positionen = []
    laibung_t = baudaten["aussenwand_cm"] / 100.0 * 0.33
    fzuord = fenster_pro_raum(rooms, windows)
    innen = [r for r in rooms if kategorie_of(_room_name(r)) == "Innenraum_warm"]

    pos = LVPosition("1.1", f"Innenputz Wände — {geschoss}", "m²")
    pos.quelle = "ÖNORM B 2210 · Σ(U×H) − Öffnungen>2,5m² + Laibungen"
    for r in innen:
        u = _room_value(r, "umfang_m")
        h = _room_value(r, "hoehe_m") or baudaten["geschosshoehe_m"]
        if not u:
            continue
        pos.add_zeile(f"{_room_name(r)} — Wand brutto", laenge=u, hoehe=h,
                      summe=u * h, quelle=f"U={u} × H={h}")
        for w in fzuord.get(id(r), []):
            bw, hw = w.get("breite_m", 0), w.get("hoehe_m", 0)
            if bw and hw and oeffnung_abzug(bw, hw):
                pos.add_zeile(f"  Abzug Fenster {w.get('code','')}",
                              laenge=bw, hoehe=-hw, summe=-(bw * hw),
                              quelle="Öffnung >2,5 m²")
                lb = laibungsflaeche(bw, hw, laibung_t)
                pos.add_zeile(f"  Laibung Fenster {w.get('code','')}", summe=lb,
                              quelle=f"Tiefe {laibung_t:.2f}m × Abwicklung")
    pos.konfidenz = 0.9
    positionen.append(pos)

    pos = LVPosition("1.2", f"Innenputz Decken — {geschoss}", "m²")
    pos.quelle = "ÖNORM B 2210 · Σ Raumfläche"
    for r in innen:
        f = _room_value(r, "flaeche_m2")
        if f:
            pos.add_zeile(_room_name(r), summe=f, quelle=f"F={f}")
    pos.konfidenz = 0.97
    positionen.append(pos)
    return positionen


def gewerk_rohbau(rooms, windows, baudaten, geschoss="EG"):
    positionen = []
    innen = [r for r in rooms if kategorie_of(_room_name(r)) == "Innenraum_warm"]
    h_def = baudaten["geschosshoehe_m"]

    # Pos 1: Wand-Abwicklung (Kontrollwert — kein Mauerwerks-Aufmaß)
    pos = LVPosition("1.1", f"Wand-Abwicklung Raum-Innenseiten — {geschoss}", "m²")
    pos.quelle = ("Σ(U×H) aller Räume — Innenwände doppelt gezählt. "
                  "Mauerwerks-Volumen erfordert Wand-Geometrie (eigener Schritt).")
    for r in innen:
        u = _room_value(r, "umfang_m")
        hh = _room_value(r, "hoehe_m") or h_def
        if u:
            pos.add_zeile(_room_name(r), laenge=u, hoehe=hh, summe=u * hh,
                          quelle=f"U={u} × H={hh}")
    pos.konfidenz = 0.6
    positionen.append(pos)

    # Pos 2: Stahlbeton-Decke m³
    decke_m = baudaten["decke_cm"] / 100.0
    pos = LVPosition("1.2", f"Stahlbeton-Decke über {geschoss}", "m³")
    pos.quelle = f"ÖNORM B 2208 · Σ Fläche × Deckendicke {decke_m:.2f}m"
    for r in innen:
        f = _room_value(r, "flaeche_m2")
        if f:
            pos.add_zeile(_room_name(r), laenge=f, hoehe=decke_m, summe=f * decke_m,
                          quelle=f"F={f} × d={decke_m:.2f}")
    pos.konfidenz = 0.85 if baudaten.get("_quellen", {}).get("decke_cm") == "vision" else 0.6
    positionen.append(pos)

    # Pos 3: Bodenplatte m³ (nur EG/KG/UG)
    if geschoss.upper() in ("EG", "KG", "UG"):
        bopl_m = baudaten["bodenplatte_cm"] / 100.0
        grundflaeche = sum((_room_value(r, "flaeche_m2") or 0) for r in innen)
        pos = LVPosition("1.3", f"Bodenplatte Stahlbeton — {geschoss}", "m³")
        pos.quelle = f"Grundfläche × Plattendicke {bopl_m:.2f}m"
        pos.add_zeile("Bodenplatte gesamt", laenge=grundflaeche, hoehe=bopl_m,
                      summe=grundflaeche * bopl_m,
                      quelle=f"ΣF={grundflaeche:.2f} × d={bopl_m:.2f}")
        pos.konfidenz = 0.8 if baudaten.get("_quellen", {}).get("bodenplatte_cm") == "vision" else 0.55
        positionen.append(pos)
    return positionen


def gewerk_estrich(rooms, windows, baudaten, geschoss="EG"):
    positionen = []
    innen = [r for r in rooms if kategorie_of(_room_name(r)) == "Innenraum_warm"]

    pos = LVPosition("1.1", f"Estrich-Fläche — {geschoss}", "m²")
    pos.quelle = "ÖNORM B 2232 · Σ Raumfläche"
    for r in innen:
        f = _room_value(r, "flaeche_m2")
        if f:
            pos.add_zeile(_room_name(r), summe=f, quelle=f"F={f}")
    pos.konfidenz = 0.97
    positionen.append(pos)

    pos = LVPosition("1.2", f"Randdämmstreifen — {geschoss}", "lfm")
    pos.quelle = "ÖNORM B 2232 · Σ Raumumfang"
    for r in innen:
        u = _room_value(r, "umfang_m")
        if u:
            pos.add_zeile(_room_name(r), laenge=u, summe=u, quelle=f"U={u}")
    pos.konfidenz = 0.95
    positionen.append(pos)
    return positionen


def gewerk_maler(rooms, windows, baudaten, geschoss="EG"):
    positionen = []
    innen = [r for r in rooms if kategorie_of(_room_name(r)) == "Innenraum_warm"]
    fzuord = fenster_pro_raum(rooms, windows)

    pos = LVPosition("1.1", f"Anstrich Wände — {geschoss}", "m²")
    pos.quelle = "Σ(U×H) − Öffnungen >2,5 m²"
    for r in innen:
        u = _room_value(r, "umfang_m")
        h = _room_value(r, "hoehe_m") or baudaten["geschosshoehe_m"]
        if not u:
            continue
        pos.add_zeile(f"{_room_name(r)} — Wand", laenge=u, hoehe=h, summe=u * h,
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
        f = _room_value(r, "flaeche_m2")
        if f:
            pos.add_zeile(_room_name(r), summe=f)
    pos.konfidenz = 0.97
    positionen.append(pos)
    return positionen


GEWERKE = {
    "putz":    ("Verputzer (ÖNORM B 2210)", gewerk_putz),
    "rohbau":  ("Maurer / Rohbau (ÖNORM B 2208)", gewerk_rohbau),
    "estrich": ("Estrich / Boden (ÖNORM B 2232)", gewerk_estrich),
    "maler":   ("Maler / Anstrich", gewerk_maler),
}


def berechne_gewerke(rooms, windows, baudaten, geschoss="EG", gewerke=None):
    """Erzeugt pro gewähltem Gewerk die LV-Positionen.
    rooms: Liste von Raum-dicts (name/flaeche_m2/umfang_m/hoehe_m/cx/cy).
    baudaten: dict mit Wandstärken/Decke/Geschosshöhe (+ optional _quellen).
    gewerke: Liste der Gewerk-Keys; None = alle."""
    if gewerke is None:
        gewerke = list(GEWERKE.keys())
    # Baudaten mit Defaults absichern
    bd = dict(DEFAULT_BAUDATEN)
    bd["_quellen"] = {}
    for k in DEFAULT_BAUDATEN:
        v = (baudaten or {}).get(k)
        if v is not None and isinstance(v, (int, float)) and v > 0:
            bd[k] = v
            bd["_quellen"][k] = (baudaten or {}).get("_quellen", {}).get(k, "vision")
        else:
            bd["_quellen"][k] = "default"
    for extra in ("anzahl_fenster", "anzahl_tueren_innen", "anzahl_tueren_aussen",
                  "wandmaterial", "konfidenz"):
        if (baudaten or {}).get(extra) is not None:
            bd[extra] = baudaten[extra]

    result = {"baudaten": bd, "gewerke": {}}
    for g in gewerke:
        if g not in GEWERKE:
            continue
        label, fn = GEWERKE[g]
        try:
            positionen = fn(rooms, windows or [], bd, geschoss)
            result["gewerke"][g] = {
                "label": label,
                "positionen": [p.to_dict() for p in positionen],
            }
        except Exception as e:
            result["gewerke"][g] = {"label": label, "positionen": [], "error": str(e)}
    return result
