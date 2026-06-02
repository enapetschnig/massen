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
OEFFNUNG_ABZUG_SCHWELLE_M2 = 4.0  # ÖNORM B 2204:2019 §5.5.1.3: sind KEINE eigenen
                                  # Laibungs-Positionen vorgesehen, werden Öffnungen
                                  # BIS 4,0 m² durchgemessen (übermessen, keine eigene
                                  # Laibung); ÜBER 4,0 m² abziehen + Laibung verrechnen.
                                  # Konsistent mit B 2210 (Putz: Fenster <4 m² = Putzfläche)
                                  # & B 2215. Strenges Mauerwerks-Ausmaß (B 2206) nennt
                                  # 0,5 m² als Untergrenze — daher je Firma/Gewerk einstellbar.

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
    # Fuzzy-Fallback: Tippfehler/Schreibvarianten (z.B. "Terasse"→"Terrasse",
    # "Wohnküche"→"Wohnkueche") tolerieren. Generalisiert auf OCR-Varianten
    # ohne jeden Tippfehler einzeln pflegen zu müssen.
    import difflib
    for kat, names in KATEGORIE.items():
        for c in candidates:
            cl = c.lower()
            if len(cl) < 4:
                continue
            for n in names:
                if difflib.SequenceMatcher(None, cl, n.lower()).ratio() >= 0.86:
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
# Öffnungs-Logik (ÖNORM B 2204 §5.5.1.3 / B 2210)
# ════════════════════════════════════════════════════════════════════════
RAHMEN_RUECKSPRUNG_CM = 6.0   # Stock/Rahmen springt ggü. Wandflucht zurück → Laibungstiefe


def _schwelle_fuer(baudaten, gewerk=None):
    """Öffnungs-Abzugsschwelle (m²): je Gewerk überschreibbar, sonst global, sonst
    Default. So kann eine Firma z.B. strenges Mauerwerks-Ausmaß (B 2206, 0,5 m²)
    setzen, ohne den Putz-Default (4,0 m²) anzutasten."""
    bd = baudaten or {}
    if gewerk is not None and bd.get(f"oeffnung_schwelle_{gewerk}") is not None:
        return float(bd[f"oeffnung_schwelle_{gewerk}"])
    if bd.get("oeffnung_schwelle") is not None:
        return float(bd["oeffnung_schwelle"])
    return OEFFNUNG_ABZUG_SCHWELLE_M2


def oeffnung_abzug(breite_m, hoehe_m, schwelle=None):
    """Öffnung wird abgezogen, wenn Einzelfläche > Schwelle (sonst übermessen)."""
    s = OEFFNUNG_ABZUG_SCHWELLE_M2 if schwelle is None else schwelle
    return (breite_m * hoehe_m) > s


def laibungsflaeche(breite_m, hoehe_m, tiefe_m, mit_sohlbank=False):
    """Abgewickelte Laibungsfläche = Tiefe × (2×Höhe + Breite [+Breite Sohlbank])."""
    umfang = 2 * hoehe_m + breite_m
    if mit_sohlbank:
        umfang += breite_m
    return tiefe_m * umfang


def _wand_cm_of(w, baudaten):
    """Wandstärke einer Öffnung: aus wand_typ (AW/IW), sonst Fallback per Art
    (Fenster→Außenwand, Tür→Innenwand). wand_typ tragen nur Text-Layer-Öffnungen."""
    bd = baudaten or {}
    aw = bd.get("aussenwand_cm") or 50.0
    iw = bd.get("innenwand_tragend_cm") or 25.0
    wt = (w.get("wand_typ") or "").lower()
    if wt:
        return aw if wt.startswith("a") else iw
    return iw if (w.get("_art") == "tuer") else aw


def oeffnung_netto(breite_m, hoehe_m, wand_cm, fph_m=0.0, schwelle=None,
                   rahmen_cm=RAHMEN_RUECKSPRUNG_CM):
    """ÖNORM B 2204 §5.5.1.3: Öffnung ≤ Schwelle → übermessen (kein Abzug, KEINE
    Laibung — die Laibungsarbeit gleicht den nicht abgezogenen Wandanteil aus);
    > Schwelle → Fläche abziehen + abgewickelte Laibung verrechnen. Laibungstiefe
    wandbezogen (Wandstärke − Rahmenrücksprung). Liefert
    {flaeche, abzug, laibung, uebermessen, tiefe, sohlbank}."""
    s = OEFFNUNG_ABZUG_SCHWELLE_M2 if schwelle is None else schwelle
    flaeche = (breite_m or 0) * (hoehe_m or 0)
    if flaeche <= 0:
        return {"flaeche": 0.0, "abzug": 0.0, "laibung": 0.0,
                "uebermessen": False, "tiefe": 0.0, "sohlbank": False}
    if flaeche <= s:
        return {"flaeche": round(flaeche, 3), "abzug": 0.0, "laibung": 0.0,
                "uebermessen": True, "tiefe": 0.0, "sohlbank": False}
    tiefe = max(0.04, (wand_cm or 0) / 100.0 - rahmen_cm / 100.0)
    mit_sohlbank = (fph_m or 0) > 0.15   # Fenster mit Parapet/Brüstung → Sohlbank-Abwicklung
    laib = laibungsflaeche(breite_m, hoehe_m, tiefe, mit_sohlbank=mit_sohlbank)
    return {"flaeche": round(flaeche, 3), "abzug": round(flaeche, 3),
            "laibung": round(laib, 3), "uebermessen": False,
            "tiefe": round(tiefe, 3), "sohlbank": mit_sohlbank}


def _oeffnungen_kombi(windows, tueren):
    """Fenster + Türen zu EINER getaggten Öffnungs-Liste (_art) für den ÖNORM-Abzug.
    Türen ohne explizites _art werden als 'tuer' markiert (→ Innenwand-Fallback)."""
    out = [dict(w, _art=(w.get("_art") or "fenster")) for w in (windows or [])]
    out += [dict(t, _art=(t.get("_art") or "tuer")) for t in (tueren or [])]
    return out


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
def gewerk_putz(rooms, windows, baudaten, geschoss="EG", tueren=None):
    positionen = []
    schwelle = _schwelle_fuer(baudaten, "putz")
    oeffnungen = _oeffnungen_kombi(windows, tueren)
    fzuord = fenster_pro_raum(rooms, oeffnungen)
    innen = [r for r in rooms if kategorie_of(_room_name(r)) == "Innenraum_warm"]

    pos = LVPosition("1.1", f"Innenputz Wände — {geschoss}", "m²")
    pos.quelle = f"ÖNORM B 2210/B 2204 · Σ(U×H) − Öffnungen>{schwelle:.1f}m² + Laibungen"
    for r in innen:
        u = _room_value(r, "umfang_m")
        h = _room_value(r, "hoehe_m") or baudaten["geschosshoehe_m"]
        if not u:
            continue
        pos.add_zeile(f"{_room_name(r)} — Wand brutto", laenge=u, hoehe=h,
                      summe=u * h, quelle=f"U={u} × H={h}")
        for w in fzuord.get(id(r), []):
            bw, hw = w.get("breite_m", 0), w.get("hoehe_m", 0)
            netto = oeffnung_netto(bw, hw, _wand_cm_of(w, baudaten),
                                   w.get("fph_m", 0), schwelle)
            if netto["uebermessen"] or netto["abzug"] <= 0:
                continue
            _art = (w.get("_art") or "Öffnung").capitalize()
            pos.add_zeile(f"  Abzug {_art} {w.get('code','')}".rstrip(),
                          laenge=bw, hoehe=-hw, summe=-netto["abzug"],
                          quelle=f"Öffnung >{schwelle:.1f} m²")
            pos.add_zeile(f"  Laibung {w.get('code','')}".rstrip(), summe=netto["laibung"],
                          quelle=(f"Tiefe {netto['tiefe']:.2f}m × Abwicklung"
                                  + (" +Sohlbank" if netto["sohlbank"] else "")))
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


def gewerk_rohbau(rooms, windows, baudaten, geschoss="EG", tueren=None):
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
    # Σ(U×H) ist byte-exakt: Raum-Umfänge kommen aus dem Text-Layer, die Höhe je Raum
    # aus dem Text oder — uniform — aus der verifizierten Geschoss-Höhe. Das ist ein
    # exakter Kontrollwert, kein wackeliger Schätzwert. Konfidenz nach Höhen-Herkunft:
    #   • genug Räume mit eigener (byte-exakter) Höhe → 0.88
    #   • Geschoss-Höhe aus Schnitt/Legende verifiziert → 0.85 (U exakt × verifizierte H)
    #   • nur Default-Höhe geraten → 0.72
    _h_text = sum(1 for r in innen if _room_value(r, "hoehe_m"))
    _ghq = (baudaten.get("_quellen", {}).get("geschosshoehe_m") or "").lower()
    _gh_verifiziert = any(k in _ghq for k in ("schnitt", "legende", "doppelcheck", "raumhoehen"))
    if _h_text >= max(1, len(innen) * 0.5):
        pos.konfidenz = 0.88
    elif _gh_verifiziert:
        pos.konfidenz = 0.85
    else:
        pos.konfidenz = 0.72
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
    # Fläche byte-exakt (Σ Raumfläche) × Dicke. Konfidenz nach DICKE-Quelle:
    # Legende/Doppelcheck = byte-exakt (hoch), Schnitt/Vision = mittel, sonst Default.
    _dq = (baudaten.get("_quellen", {}).get("decke_cm") or "").lower()
    pos.konfidenz = (0.92 if ("legende" in _dq or "doppelcheck" in _dq)
                     else 0.82 if ("schnitt" in _dq or "vision" in _dq) else 0.65)
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
        # Grundfläche byte-exakt × Dicke. Konfidenz nach DICKE-Quelle wie bei der Decke.
        _bq = (baudaten.get("_quellen", {}).get("bodenplatte_cm") or "").lower()
        pos.konfidenz = (0.9 if ("legende" in _bq or "doppelcheck" in _bq)
                         else 0.8 if ("schnitt" in _bq or "vision" in _bq) else 0.62)
        positionen.append(pos)
    return positionen


def gewerk_estrich(rooms, windows, baudaten, geschoss="EG", tueren=None):
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


def gewerk_maler(rooms, windows, baudaten, geschoss="EG", tueren=None):
    positionen = []
    innen = [r for r in rooms if kategorie_of(_room_name(r)) == "Innenraum_warm"]
    schwelle = _schwelle_fuer(baudaten, "maler")
    oeffnungen = _oeffnungen_kombi(windows, tueren)
    fzuord = fenster_pro_raum(rooms, oeffnungen)

    pos = LVPosition("1.1", f"Anstrich Wände — {geschoss}", "m²")
    pos.quelle = f"ÖNORM B 2204 · Σ(U×H) − Öffnungen>{schwelle:.1f}m² + Laibungen"
    for r in innen:
        u = _room_value(r, "umfang_m")
        h = _room_value(r, "hoehe_m") or baudaten["geschosshoehe_m"]
        if not u:
            continue
        pos.add_zeile(f"{_room_name(r)} — Wand", laenge=u, hoehe=h, summe=u * h,
                      quelle=f"U={u} × H={h}")
        for w in fzuord.get(id(r), []):
            bw, hw = w.get("breite_m", 0), w.get("hoehe_m", 0)
            netto = oeffnung_netto(bw, hw, _wand_cm_of(w, baudaten),
                                   w.get("fph_m", 0), schwelle)
            if netto["uebermessen"] or netto["abzug"] <= 0:
                continue
            _art = (w.get("_art") or "Öffnung").capitalize()
            pos.add_zeile(f"  Abzug {_art} {w.get('code','')}".rstrip(),
                          laenge=bw, hoehe=-hw, summe=-netto["abzug"])
            pos.add_zeile(f"  Laibung {w.get('code','')}".rstrip(), summe=netto["laibung"],
                          quelle=f"Tiefe {netto['tiefe']:.2f}m × Abwicklung")
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


def berechne_gewerke(rooms, windows, baudaten, geschoss="EG", gewerke=None, tueren=None):
    """Erzeugt pro gewähltem Gewerk die LV-Positionen.
    rooms: Liste von Raum-dicts (name/flaeche_m2/umfang_m/hoehe_m/cx/cy).
    windows/tueren: Öffnungen (für ÖNORM-Abzug + Laibung).
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
            positionen = fn(rooms, windows or [], bd, geschoss, tueren=tueren)
            result["gewerke"][g] = {
                "label": label,
                "positionen": [p.to_dict() for p in positionen],
            }
        except Exception as e:
            result["gewerke"][g] = {"label": label, "positionen": [], "error": str(e)}
    return result
