"""ÖNORM-Massenermittlung — reine Berechnungs-Logik (deploybar auf Vercel).

Dieses Modul enthält KEINE fitz/anthropic-Abhängigkeiten — es bekommt fertig
extrahierte Räume + (per Vision gemessene) Baudaten und erzeugt pro Gewerk
eine buchmäßige Massenermittlung (LV in Buchform).

Wird von api/extract.py importiert. Gewerke:
  - putz    (in Anlehnung an ÖNORM B 2204 (vormals B 2210)): Wandflächen, Öffnungsabzüge, Laibungen, Decken
  - rohbau  (in Anlehnung an ÖNORM B 2204 (vormals B 2211)): Wand-Abwicklung, Decke/Bodenplatte Stahlbeton m³
  - estrich (in Anlehnung an ÖNORM B 2232): Bodenflächen, Randdämmstreifen
  - maler                 : Wand-/Deckenflächen mit Öffnungsabzug
"""
from __future__ import annotations
import math
import re

# ════════════════════════════════════════════════════════════════════════
# ÖNORM-Konstanten & Standard-Annahmen
# ════════════════════════════════════════════════════════════════════════
OEFFNUNG_ABZUG_SCHWELLE_M2 = 4.0  # in Anlehnung an ÖNORM B 2204:2019 §5.5.1.3: sind KEINE eigenen
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
# Öffnungs-Logik (in Anlehnung an ÖNORM B 2204 §5.5.1.3)
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
    if gewerk == "maler":
        # ÖNORM-Audit: Malerarbeiten sind NICHT Teil der B 2204 — die Maler-
        # Aufmaßpraxis (analog DIN 18363) übermisst nur bis 2,5 m².
        return 2.5
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
    """in Anlehnung an ÖNORM B 2204 §5.5.1.3: Öffnung ≤ Schwelle → übermessen (kein Abzug, KEINE
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


def _ist_aussenwand(w):
    """Sitzt die Öffnung in einer Außenwand? wand_typ schlägt den Art-Fallback
    (Fenster→außen, Tür→innen)."""
    wt = (w.get("wand_typ") or "").lower()
    if wt:
        return wt.startswith("a")
    return w.get("_art") != "tuer"


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
    pos.quelle = f"in Anlehnung an ÖNORM B 2204 (vormals B 2210) · Σ(U×H) − Öffnungen>{schwelle:.1f}m²"
    pos_laib = LVPosition("1.1a", f"Leibungsputz — {geschoss}", "m²")
    pos_laib.quelle = ("ÖNORM B 2204 §5.5.1.3 (eigene Leibungs-Position: "
                       "Öffnung > Schwelle abgezogen, Leibung separat)")
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
            # Leibung → EIGENE Position 1.1a (B 2204 §5.5.1.3 ist zweigleisig:
            # MIT Leibungs-Positionen wird abgezogen UND die Leibung separat
            # verrechnet — vorher steckte sie in der Wandputz-Position, das
            # machte das LV strukturell nicht angebots-vergleichbar).
            pos_laib.add_zeile(f"{_room_name(r)} — {w.get('code','')}".rstrip(" —"),
                               summe=netto["laibung"],
                               quelle=(f"Tiefe {netto['tiefe']:.2f}m × Abwicklung"
                                       + (" +Sohlbank" if netto["sohlbank"] else "")))
    pos.konfidenz = 0.9
    positionen.append(pos)
    if pos_laib.zeilen:
        pos_laib.konfidenz = 0.85
        positionen.append(pos_laib)

    pos = LVPosition("1.2", f"Innenputz Decken — {geschoss}", "m²")
    pos.quelle = "in Anlehnung an ÖNORM B 2204 (vormals B 2210) · Σ Raumfläche"
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

    # Pos 1.0: Mauerwerk Außenwand — Ansichtsfläche netto (in Anlehnung an ÖNORM B 2204 (vormals B 2206) mit
    # Öffnungs-Abzug). Nutzt die GEMEINSAME Basis: dieselbe gemessene Außenwand-
    # Fläche, die auch die Bestell-Liste treibt → beide Ansichten zeigen dieselbe
    # Wand (keine widersprüchlichen Zahlen). Nur aktiv, wenn die Basis durchgereicht
    # ist (sonst keine Wand-Geometrie → Position wird ausgelassen).
    _aw_brutto = baudaten.get("_basis_aussenwand_flaeche_m2")
    if _aw_brutto:
        _schw = _schwelle_fuer(baudaten, "rohbau")
        _abzug = 0.0
        for w in _oeffnungen_kombi(windows, tueren):
            if not _ist_aussenwand(w):
                continue
            _abzug += oeffnung_netto(w.get("breite_m", 0), w.get("hoehe_m", 0),
                                     baudaten.get("aussenwand_cm", 50),
                                     w.get("fph_m", 0), _schw)["abzug"]
        pos = LVPosition("1.0", f"Mauerwerk Außenwand Ansichtsfläche — {geschoss}", "m²")
        pos.quelle = f"in Anlehnung an ÖNORM B 2204 (vormals B 2206) · Außenwand brutto − Öffnungen>{_schw:.1f}m²"
        pos.add_zeile("Außenwand brutto", summe=round(_aw_brutto, 2),
                      quelle="Umfang × Höhe (gemeinsame Basis)")
        if _abzug > 0:
            pos.add_zeile("  Abzug große Öffnungen", summe=-round(_abzug, 2),
                          quelle=f"Einzelfläche >{_schw:.1f} m²")
        pos.konfidenz = 0.8
        positionen.append(pos)

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

    # Pos 2: Stahlbeton-Decke m³ — GEMEINSAME Basis mit der Bestell-Liste: wenn die
    # gemessene Decken-Fläche (Footprint+Auskragung) durchgereicht ist, dieselbe
    # nutzen → identische m³ in beiden Ansichten. Sonst lichte Σ-Raumfläche.
    decke_m = baudaten["decke_cm"] / 100.0
    pos = LVPosition("1.2", f"Stahlbeton-Decke über {geschoss}", "m³")
    _basis_decke = baudaten.get("_basis_decke_m2")
    # ÖNORM-Audit (Deckenöffnungen): STIEGENLÖCHER gehören nicht in die
    # Betonmenge (B 2204/LB-HB LG07: große Aussparungen als eigene Positionen).
    # Stiegenhaus-Räume sind der byte-exakte Kandidat — nur abziehen wenn
    # vorhanden (eingeschossige EFH ohne Stiegenhaus bleiben byte-identisch).
    _stiege_f = sum(_room_value(r, "flaeche_m2") or 0 for r in rooms
                    if kategorie_of(_room_name(r)) == "Stiegenhaus")
    if _basis_decke:
        pos.quelle = f"in Anlehnung an ÖNORM B 2204 (vormals B 2211) · Decken-Fläche × Dicke {decke_m:.2f}m (gemeinsame Basis)"
        pos.add_zeile("Decke gesamt", laenge=round(_basis_decke, 2), hoehe=decke_m,
                      summe=_basis_decke * decke_m, quelle=f"F={_basis_decke:.2f} × d={decke_m:.2f}")
        if _stiege_f:
            pos.add_zeile("abzügl. Deckenöffnung Stiege", laenge=-round(_stiege_f, 2),
                          hoehe=decke_m, summe=-_stiege_f * decke_m,
                          quelle=f"Stiegenhaus F={_stiege_f:.2f} × d={decke_m:.2f} (Aussparung)")
    else:
        pos.quelle = f"in Anlehnung an ÖNORM B 2204 (vormals B 2211) · Σ Fläche × Deckendicke {decke_m:.2f}m"
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

    # Pos 3: Bodenplatte m³ (nur EG/KG/UG) — GEMEINSAME Basis: gemessene
    # Bodenplatten-Fläche wenn durchgereicht, sonst Σ Grundfläche.
    if geschoss.upper() in ("EG", "KG", "UG"):
        bopl_m = baudaten["bodenplatte_cm"] / 100.0
        _basis_bopl = baudaten.get("_basis_bodenplatte_m2")
        grundflaeche = (_basis_bopl if _basis_bopl
                        else sum((_room_value(r, "flaeche_m2") or 0) for r in innen))
        pos = LVPosition("1.3", f"Bodenplatte Stahlbeton — {geschoss}", "m³")
        _gb = " (gemeinsame Basis)" if _basis_bopl else ""
        pos.quelle = f"Grundfläche × Plattendicke {bopl_m:.2f}m{_gb}"
        pos.add_zeile("Bodenplatte gesamt", laenge=round(grundflaeche, 2), hoehe=bopl_m,
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
    pos.quelle = "in Anlehnung an ÖNORM B 2232 · Σ Raumfläche"
    for r in innen:
        f = _room_value(r, "flaeche_m2")
        if f:
            pos.add_zeile(_room_name(r), summe=f, quelle=f"F={f}")
    pos.konfidenz = 0.97
    positionen.append(pos)

    pos = LVPosition("1.2", f"Randdämmstreifen — {geschoss}", "lfm")
    pos.quelle = "in Anlehnung an ÖNORM B 2232 · Σ Raumumfang"
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
    pos.quelle = (f"Maler-Aufmaßpraxis (analog DIN 18363) · "
                  f"Σ(U×H) − Öffnungen>{schwelle:.1f}m² + Laibungen")
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


def gewerk_beton(rooms, windows, baudaten, geschoss="EG", tueren=None):
    """Stahlbeton-Bauteile außer Decke/Bodenplatte (die liegen im Rohbau): freistehende
    Stützen/Säulen + Kamin. Säulen-m³ mit DEMSELBEN Faktor wie die Bestell-Liste
    (gemeinsame Basis) → beide Ansichten rechnen gleich. Leer, wenn nichts erkannt."""
    positionen = []
    n_saeulen = int(baudaten.get("anzahl_saeulen") or 0)
    if n_saeulen > 0:
        m3_pro = float(baudaten.get("saeule_beton_m3_pro_stk") or 0.5)
        pos = LVPosition("1.1", f"Stahlbeton-Stützen — {geschoss}", "m³")
        pos.quelle = f"{n_saeulen} Stk × {m3_pro:.2f} m³/Stk (inkl. Fundament)"
        pos.add_zeile(f"{n_saeulen} Stützen", anzahl=n_saeulen, summe=n_saeulen * m3_pro,
                      quelle=f"{n_saeulen} × {m3_pro:.2f}")
        _sq = (baudaten.get("_quellen", {}).get("anzahl_saeulen") or "").lower()
        pos.konfidenz = 0.75 if any(k in _sq for k in ("schnitt", "opus", "vision")) else 0.5
        positionen.append(pos)
    n_kamine = int(baudaten.get("anzahl_kamine") or 0)
    if n_kamine > 0:
        pos = LVPosition("1.2", f"Kamin / Schornstein — {geschoss}", "Stk")
        pos.quelle = "Anzahl aus Plan/Legende"
        pos.add_zeile(f"{n_kamine} Kamin(e)", anzahl=n_kamine, summe=n_kamine, quelle=f"{n_kamine} Stk")
        pos.konfidenz = 0.6
        positionen.append(pos)
    return positionen


# LG-Nummern = offizielle Standardisierte LB-Hochbau (StLB-HB Version 020,
# BMWET) — byte-exakt aus der Leistungsbeschreibung gelesen. Öffentlicher
# Standard (keine ONLV-Lizenz nötig, die betrifft nur die Positions-TEXTE);
# damit mappt der ÖNORM-Export sauber in die AVA-Software der Baubetriebe
# (ORCA/ABK/Bau-SU), die nach LG/ULG/Position gliedern.
GEWERKE = {
    "putz":    ("Verputzer (LG 10 Putz — in Anlehnung an ÖNORM B 2204)", gewerk_putz, "10"),
    "rohbau":  ("Maurer / Rohbau (LG 08 Mauerarbeiten — in Anlehnung an ÖNORM B 2204)", gewerk_rohbau, "08"),
    "beton":   ("Stahlbeton (LG 07 Beton- und Stahlbetonarbeiten)", gewerk_beton, "07"),
    "estrich": ("Estrich / Boden (LG 11 Estricharbeiten — in Anlehnung an ÖNORM B 2232)", gewerk_estrich, "11"),
    "maler":   ("Maler / Anstrich (LG 46 Beschichtung auf Mauerwerk, Putz und Beton)", gewerk_maler, "46"),
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
    # Durchreich-Keys: Zähl-/Material-Infos + Phase-2-Größen (gemeinsame Basis aus der
    # Bestell-Liste, Inventar-Zählungen, je-Gewerk-Öffnungsschwellen). Werden nicht
    # auf DEFAULT_BAUDATEN gefiltert, sondern 1:1 übernommen.
    _DURCHREICH = ("anzahl_fenster", "anzahl_tueren_innen", "anzahl_tueren_aussen",
                   "wandmaterial", "konfidenz",
                   "_basis_aussenwand_flaeche_m2", "_basis_innenwand_flaeche_m2",
                   "_basis_decke_m2", "_basis_bodenplatte_m2", "_basis_aussenumfang_m",
                   "anzahl_saeulen", "anzahl_kamine", "saeule_beton_m3_pro_stk",
                   "oeffnung_schwelle", "oeffnung_schwelle_putz", "oeffnung_schwelle_maler",
                   "oeffnung_schwelle_rohbau")
    for extra in _DURCHREICH:
        if (baudaten or {}).get(extra) is not None:
            bd[extra] = baudaten[extra]
    # Herkunft der Inventar-Zählung für die Konfidenz im Beton-Gewerk
    for qk in ("anzahl_saeulen", "anzahl_kamine"):
        _q = (baudaten or {}).get("_quellen", {}).get(qk)
        if _q:
            bd["_quellen"][qk] = _q

    result = {"baudaten": bd, "gewerke": {}}
    for g in gewerke:
        if g not in GEWERKE:
            continue
        label, fn, lg = GEWERKE[g]
        try:
            positionen = fn(rooms, windows or [], bd, geschoss, tueren=tueren)
            if not positionen and g == "beton":
                continue   # kein Säulen/Kamin erkannt → leeres Beton-Gewerk auslassen
            result["gewerke"][g] = {
                "label": label, "lg": lg,
                "positionen": [p.to_dict() for p in positionen],
            }
        except Exception as e:
            result["gewerke"][g] = {"label": label, "lg": lg, "positionen": [], "error": str(e)}
    return result


def oeffnungs_aufmass(fenster, tueren, baudaten):
    """ÖFFNUNGS-AUFMASS ('Massen zuerst'-Umbau): JEDE Öffnung als eigene, prüfbare
    Zeile — Raum · Typ · B×H · Fläche · angewandte ÖNORM-Regel (B 2204 §5.5.1.3:
    ≤4,0 m² übermessen OHNE Laibung / >4,0 m² Abzug MIT Laibungszeile) · Laibungs-m²
    samt Formel. Damit ist sichtbar, WELCHE Laibungen drin sind und warum."""
    bd = baudaten or {}
    zeilen = []
    for o in _oeffnungen_kombi(fenster, tueren):
        b, h = o.get("breite_m") or 0, o.get("hoehe_m") or 0
        aussen = _ist_aussenwand(o)
        # ÖNORM-Audit-Bugfix: 'innenwand_cm' existiert nicht (DEFAULT_BAUDATEN
        # kennt innenwand_tragend_cm) → IW-Laibungstiefe war 0,06 statt 0,19 m,
        # der Prüfbeleg widersprach der eigenen Putz-LV. Gleiche Quelle wie LV:
        wand_cm = _wand_cm_of(o, bd)
        schwelle = _schwelle_fuer(bd, "putz")
        n = oeffnung_netto(b, h, wand_cm, o.get("fph_m", 0), schwelle)
        if n["uebermessen"]:
            regel = f"übermessen (≤{schwelle:.1f} m² — kein Abzug, keine Laibung)"
            formel = f"{b:.2f}×{h:.2f}={n['flaeche']:.2f} m² ≤ {schwelle:.1f}"
        else:
            regel = f"Abzug + Laibung (>{schwelle:.1f} m²)"
            u_l = 2 * h + b + (b if n["sohlbank"] else 0)
            formel = (f"{b:.2f}×{h:.2f}={n['flaeche']:.2f} m² · Laibung ({'2H+2B' if n['sohlbank'] else '2H+B'}"
                      f"={u_l:.2f} m)×{n['tiefe']:.2f} m={n['laibung']:.2f} m²")
        zeilen.append({
            "raum": o.get("raum"),
            "typ": o.get("_art"),
            "wand": "AW" if aussen else "IW",
            "breite_m": round(b, 2), "hoehe_m": round(h, 2),
            "flaeche_m2": n["flaeche"],
            "regel": regel,
            "abzug_m2": n["abzug"],
            "laibung_m2": n["laibung"],
            "sohlbank": n["sohlbank"],
            "formel": formel,
        })
    zeilen.sort(key=lambda z: (z["typ"] or "", z["raum"] or ""))
    return {
        "zeilen": zeilen,
        "summen": {
            "n": len(zeilen),
            "n_uebermessen": sum(1 for z in zeilen if z["abzug_m2"] == 0),
            "n_abzug": sum(1 for z in zeilen if z["abzug_m2"] > 0),
            "abzug_m2": round(sum(z["abzug_m2"] for z in zeilen), 2),
            "laibung_m2": round(sum(z["laibung_m2"] for z in zeilen), 2),
        },
        "norm": "in Anlehnung an ÖNORM B 2204 §5.5.1.3",
    }
