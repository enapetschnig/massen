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


def ist_aussenanlage(name, f_m2, u_m):
    """Ist dieser Stempel eine FREIFLÄCHE (Wiese, Spielplatz, Pflaster)?

    Am WM-Plan stehen 8 solcher Stempel mit zusammen 1175 m² — sie erschienen
    als Räume in der Liste und überzogen den halben Plan mit Umriss-Lappen.
    Auf die MENGEN wirken sie nicht (end-zu-Ende gemessen: 0 Positionen ändern
    sich, weil jedes Innen-Gewerk auf kategorie_of() == 'Innenraum_warm'
    filtert) — aber ein Polier, der 'Kinderspielfläche 313,96 m²' in seiner
    Raumliste findet, glaubt der ganzen Liste nicht mehr.

    Die Regel ist SPRACHUNABHÄNGIG und kommt aus dem Stempel selbst:
    ein Raumstempel führt Fläche UND Umfang, weil beides für den Innenausbau
    gebraucht wird; eine Geländefläche bekommt nur eine Fläche.

        INNEN-Stempel   107 · 83 mit U-Angabe (78%)
        AUSSEN-Stempel   15 ·  0 mit U-Angabe ( 0%)

    Weil 22% echter Räume ebenfalls kein U tragen, reicht das allein nicht.
    Erst die Kombination aus drei Bedingungen ist am Korpus trennscharf:
    kein U + keine bekannte Raum-Kategorie + mindestens 100 m².

        122 Stempel auf 4 Plänen -> 12 erkannt, 0 Fehlalarm, 3 verpasst
        (die verpassten sind Radabstellplätze mit 22,70 m², unter der
         Flächenschwelle — sie bleiben lieber Raum als falsch verschwunden)

    Die Schwelle ist bewusst konservativ: einen echten Raum aus dem Plan zu
    nehmen wäre viel teurer, als eine Wiese stehen zu lassen.
    """
    if u_m:
        return False
    if kategorie_of(name) is not None:
        return False
    try:
        return float(f_m2 or 0) >= 100.0
    except (TypeError, ValueError):
        return False


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
                  summe=None, quelle="", anker=None):
        wert = summe
        if wert is None:
            wert = (anzahl or 1) * (laenge or 1) * (breite or 1) * (hoehe or 1)
        z = {
            "text": text,
            "anzahl": anzahl or None,
            "laenge": laenge or None,
            "breite": breite or None,
            "hoehe": hoehe or None,
            "wert": round(wert, 4),
            "quelle": quelle,
        }
        # Plan-Anker (Traceability): {"raum": <Name>} koppelt die Aufmaß-Zeile an
        # ihr Plan-Element — das Frontend macht die Zeile klickbar und lässt den
        # Raum im Nachzeichnen-Overlay pulsieren. Jede Menge hat einen Beleg-Ort.
        if anker:
            z["anker"] = anker
        self.zeilen.append(z)

    @property
    def endsumme(self):
        return round(sum(z["wert"] for z in self.zeilen), 2)

    @property
    def regel(self):
        """AUFMASSREGEL maschinenlesbar aus der Quellen-Angabe.

        Jede Menge MUSS nach einer benannten Regel ermittelt sein — das ist der
        Kern eines prüfbaren Aufmaßes (und die Zusage „Massen laut ÖNORM"). Die
        Regel steht seit jeher als Fließtext in `quelle`; hier wird sie in ihre
        Bestandteile zerlegt, damit Oberfläche, Export und WÄCHTER sie prüfen
        können statt sie nur anzuzeigen:
          norm      — 'ÖNORM B 2204' (das Regelwerk)
          stelle    — '§5.5.1.3', falls die Position eine Fundstelle nennt
          angelehnt — True bei „in Anlehnung an" (ehrlich: keine wörtliche
                      Übernahme, sondern sinngemäße Anwendung)
          formel    — der Rechenweg im Klartext ('Σ(U×H) − Öffnungen>4.0m²')
        Ohne erkennbare Norm → None; der Wächter macht daraus „Regel fehlt"."""
        q = (self.quelle or "").strip()
        if not q:
            return None
        st = re.search(r"§\s*([\d.]+)", q)
        # Formel = der Teil nach dem letzten '·' (so sind die Quellen gebaut)
        formel = (q.split("·")[-1].strip() if "·" in q else q)
        basis = {
            "stelle": (f"§{st.group(1)}" if st else None),
            "angelehnt": bool(re.search(r"in\s+Anlehnung", q, re.I)),
            "formel": formel,
            "text": q,
        }
        m = re.search(r"(ÖNORM|ONORM)\s+([A-Z])\s*(\d{4})(-\d)?", q)
        if m:
            _n = f"ÖNORM {m.group(2)} {m.group(3)}{m.group(4) or ''}"
            # NORM_OFFEN: das Regelwerk ist benannt, aber ein PARAMETER darin
            # (z.B. eine Abzugsschwelle) ist nicht normbelegt. Das muss sichtbar
            # bleiben — sonst sieht eine übernommene Fremd-Praxis wie eine
            # österreichische Regel aus.
            if re.search(r"nicht\s+normbelegt|nicht\s+AT-belegt", q, re.I):
                return dict(basis, art="norm_offen", norm=_n)
            return dict(basis, art="norm", norm=_n)
        # FREMDNORM: eine deutsche/europäische Norm in einer ÖNORM-Anwendung
        # ist ein BEFUND, kein Feature — sie wird ausdrücklich als solche
        # ausgewiesen, damit sie nicht als österreichische Regel durchgeht.
        f = re.search(r"\b(DIN|EN|ISO|VOB)\s*([0-9]{3,5})?", q)
        if f:
            return dict(basis, art="fremdnorm",
                        norm=(f"{f.group(1)} {f.group(2)}".strip() if f.group(2)
                              else f.group(1)))
        # STÜCKZAHL: eine Zählung braucht keine Aufmaßregel (ehrlich benannt).
        if re.search(r"Stück|Stk|Anzahl", q, re.I):
            return dict(basis, art="stueckzahl", norm=None)
        # PRAXIS: Fachpraxis/Annahme ohne belegten Norm-Bezug — offen, aber
        # ausgewiesen (im Ziel-Workflow entspricht das „Regel fehlt").
        return dict(basis, art="praxis", norm=None)

    def to_dict(self):
        return {
            "posnr": self.posnr,
            "beschreibung": self.beschreibung,
            "einheit": self.einheit,
            "endsumme": self.endsumme,
            "konfidenz": self.konfidenz,
            "quelle": self.quelle,
            "regel": self.regel,      # maschinenlesbare Aufmaßregel
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
        # ACHTUNG Herkunft: 2,5 m² stammt aus der DEUTSCHEN Maler-Praxis
        # (DIN 18363) — die österreichische B 2230-1 kennt diese Schwelle so
        # nicht. Bis eine AT-belegte Regel vorliegt, bleibt 2,5 als
        # pragmatischer Default und ist je Firma überschreibbar
        # (oeffnung_schwelle_maler) — bewusst NICHT still als Norm ausgegeben.
        return 2.5
    if gewerk in ("rohbau", "beton"):
        # ÖNORM-SCHWELLEN-MATRIX (Kernversprechen): Mauerwerks-/Beton-AUSMASS
        # zieht Öffnungen bereits ab 0,5 m² ab (strenges Ausmaß, B 2204
        # 4.2.4.2 bzw. vormals B 2206; Beton analog B 2211/B 2232-Familie) —
        # die 4,0-m²-Übermessung gilt nur für Putz & Co. (Leibungslogik).
        # Gegen die echte Angerer-Polier-Liste verifiziert: 13/13 in Toleranz,
        # HLZ-Mengen rücken NÄHER an die Polier-Realität.
        return 0.5
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


LEIBUNG_LFM_MAX_TIEFE_M = 0.25   # B 2204: Leibungen BIS 0,25 m Tiefe werden als
                                 # LAUFMETER der Abwicklung ausgeschrieben, erst
                                 # darüber als m² — bei üblichen Tiefen (6-19 cm)
                                 # ist lfm der Normalfall.


def laibungs_abwicklung(breite_m, hoehe_m, mit_sohlbank=False):
    """Abwicklungslänge der Leibung: 2×Höhe + Breite [+ Breite Sohlbank]."""
    return 2 * hoehe_m + breite_m + (breite_m if mit_sohlbank else 0)


def leibung_zeile(pos_lfm, pos_m2, label, breite_m, hoehe_m, netto):
    """Leibung NORMRICHTIG verbuchen (B 2204, #1-Rest): Tiefe ≤ 0,25 m →
    Laufmeter-Zeile in pos_lfm (Menge = Abwicklung), tiefer → abgewickelte
    m²-Zeile in pos_m2. Aufrufer hängt nur nicht-leere Positionen an."""
    abw = laibungs_abwicklung(breite_m, hoehe_m, netto["sohlbank"])
    if netto["tiefe"] <= LEIBUNG_LFM_MAX_TIEFE_M:
        pos_lfm.add_zeile(label, laenge=round(abw, 2), summe=abw,
                          quelle=(f"Abwicklung 2H+B{'+B (Sohlbank)' if netto['sohlbank'] else ''}"
                                  f" · Tiefe {netto['tiefe']*100:.0f} cm ≤ 25 cm → lfm (B 2204)"))
    else:
        pos_m2.add_zeile(label, summe=netto["laibung"],
                         quelle=(f"Tiefe {netto['tiefe']:.2f} m > 0,25 → m² · Abwicklung"
                                 + (" +Sohlbank" if netto["sohlbank"] else "")))


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
        # maßlose Öffnung: kein Abzug, keine Laibung — konsistent zum ≤Schwelle-Zweig
        # als 'übermessen' labeln (sonst zeigt das Öffnungs-Aufmaß fälschlich '>Schwelle
        # abgezogen' bei 0-Abzug). Verhalten der Abzugs-Logik unverändert (abzug=0).
        return {"flaeche": 0.0, "abzug": 0.0, "laibung": 0.0,
                "uebermessen": True, "tiefe": 0.0, "sohlbank": False}
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
    Türen ohne explizites _art werden als 'tuer' markiert (→ Innenwand-Fallback).

    CROSS-DEDUP: eine große Hebe-/Schiebetür zur Terrasse wird oft vom Fenster-Vision-
    Pass UND vom STUK/FPH-Text-Pass erfasst → sie läge in BEIDEN Listen und würde
    DOPPELT abgezogen. Türen, die positions-nah (≤30pt cx/cy) an einer schon erfassten
    Öffnung liegen, werden als dieselbe physische Öffnung erkannt; die BEMASSTE
    Variante bleibt. Nur aktiv, wenn beide Positionen tragen (sonst kein Dedup)."""
    out = [dict(w, _art=(w.get("_art") or "fenster")) for w in (windows or [])]
    for t in (tueren or []):
        tx, ty = t.get("cx"), t.get("cy")
        tb, th = t.get("breite_m"), t.get("hoehe_m")
        match_i = None
        if tx is not None and ty is not None:
            for _i, w in enumerate(out):
                wx, wy = w.get("cx"), w.get("cy")
                if not (wx is not None and wy is not None
                        and abs(wx - tx) <= 30 and abs(wy - ty) <= 30):
                    continue
                wb, wh = w.get("breite_m"), w.get("hoehe_m")
                # Nur DIESELBE Öffnung mergen: beide bemaßt → Maße müssen ~gleich sein
                # (≤0,2 m; sonst sind es zwei verschiedene Öffnungen nah beieinander);
                # ist eine Seite maßlos, genügt die Positions-Nähe.
                if tb and th and wb and wh:
                    if abs(wb - tb) <= 0.2 and abs(wh - th) <= 0.2:
                        match_i = _i
                        break
                else:
                    match_i = _i
                    break
        if match_i is None:
            out.append(dict(t, _art=(t.get("_art") or "tuer")))
        elif (not (out[match_i].get("breite_m") and out[match_i].get("hoehe_m"))
              and tb and th):
            out[match_i] = dict(t, _art=(t.get("_art") or "tuer"))  # bemaßte Variante behalten
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
    oder per Position (FE_-Code-Fenster mit cx/cy).

    BEI GLEICHNAMIGEN RAEUMEN reicht der Name nicht. Hier stand frueher
    `zuord[id(matches[0])].append(w)` — damit landeten in einem Wohnbau ALLE
    Fenster der drei "Wohnkueche" in der ERSTEN, die beiden anderen bekamen
    keines. Am echten Korpus teilen sich 66 von 113 Stempeln ihren Namen.

    Jetzt in dieser Reihenfolge:
      1. genau ein Namenstreffer  -> dorthin (der Normalfall, unveraendert)
      2. mehrere Treffer, Fenster hat eine Position -> der naechste davon
      3. mehrere Treffer, keine Position -> reihum verteilen. Das ist eine
         Annahme, aber die tragfaehigste: die SUMME der Abzuege bleibt so
         oder so gleich (die ÖNORM-Schwelle gilt je Oeffnung), unsicher ist
         nur die Aufteilung — und "je einer" ist bei drei gleich benannten
         Raeumen mit drei Fenstern deutlich naeher an der Wirklichkeit als
         "alle drei in den ersten".
    """
    zuord = {id(r): [] for r in rooms}
    # Name-Index für Vision-Fenster
    name_idx = {}
    for r in rooms:
        name_idx.setdefault(_nk(_room_name(r)), []).append(r)
    _reihum = {}
    for w in windows:
        # 1. Vision-Fenster: Zuordnung per Raum-Name
        wraum = w.get("raum")
        if wraum:
            _key = _nk(wraum)
            matches = name_idx.get(_key)
            if matches and len(matches) == 1:
                zuord[id(matches[0])].append(w)
                continue
            if matches:
                wx, wy = w.get("cx"), w.get("cy")
                if wx is not None and wy is not None:
                    _mit_pos = [r for r in matches if r.get("cx") is not None]
                    if _mit_pos:
                        _b = min(_mit_pos, key=lambda r: math.hypot(
                            r["cx"] - wx, r["cy"] - wy))
                        zuord[id(_b)].append(w)
                        continue
                _i = _reihum.get(_key, 0)
                _reihum[_key] = _i + 1
                zuord[id(matches[_i % len(matches)])].append(w)
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


def _room_key(r):
    """EINDEUTIGE Kennung eines Raums — nicht sein Name.

    Ein Wohnbau hat in jeder Wohnung ein "Bad". Wer Aufmass-Zeilen nach dem
    Namen gruppiert, wirft sie zusammen: gemessen wurden aus 6 Raeumen
    (3x Bad, 3x Wohnkueche, alle mit verschiedenen Massen) 2 Zeilen, und die
    Zeile "Bad" zeigte U=10,4 m, obwohl die drei Baeder 9,6 / 10,1 / 10,4 m
    haben. Am echten Korpus teilen sich 66 von 113 Stempeln ihren normierten
    Namen mit einem anderen.

    Wohnung und Geschoss trennen, wo sie gelesen wurden; die byte-exakte
    Flaeche trennt den Rest. Der Name allein waere die Beschriftung, nicht
    der Raum.
    """
    d = r.get("daten") or {}

    def _g(*keys):
        for k in keys:
            v = r.get(k) if r.get(k) is not None else d.get(k)
            if v not in (None, ""):
                return str(v)
        return ""

    f = r.get("flaeche_m2")
    if f is None:
        f = r.get("f_m2") if r.get("f_m2") is not None else d.get("flaeche_m2")
    try:
        fs = f"{float(f):.2f}"
    except (TypeError, ValueError):
        fs = ""
    return "|".join([_room_name(r), _g("wohnung", "top"), _g("geschoss"), fs])


def _anker(r):
    """Plan-Anker einer Aufmass-Zeile: Anzeigename UND eindeutige Kennung.

    "raum" bleibt der Klartext (Frontend zeigt ihn und springt damit an den
    Plan), "rkey" identifiziert den Raum eindeutig — siehe _room_key.
    """
    return {"raum": _room_name(r), "rkey": _room_key(r)}


def _u_lbl(r, u):
    """Aufmaß-Herleitung ehrlich halten: byte-exakter U-Stempel → 'U=…',
    Proportions-Schätzung (Scan ohne U-Stempel) → 'U≈… (geschätzt)'."""
    if r.get("umfang_geschaetzt") or (r.get("daten") or {}).get("umfang_geschaetzt"):
        return f"U≈{u} (geschätzt)"
    return f"U={u}"


# ════════════════════════════════════════════════════════════════════════
# GEWERKE
# ════════════════════════════════════════════════════════════════════════
def gewerk_putz(rooms, windows, baudaten, geschoss="EG", tueren=None):
    positionen = []
    schwelle = _schwelle_fuer(baudaten, "putz")
    oeffnungen = _oeffnungen_kombi(windows, tueren)
    fzuord = fenster_pro_raum(rooms, oeffnungen)
    innen = [r for r in rooms if kategorie_of(_room_name(r)) == "Innenraum_warm"]

    pos = LVPosition("1.1", f"Innenputz Wände bis 3,2 m — {geschoss}", "m²")
    pos.quelle = f"in Anlehnung an ÖNORM B 2204 (vormals B 2210) · Σ(U×H) − Öffnungen>{schwelle:.1f}m²"
    # ÖNORM-HÖHENSPLIT: Arbeiten in Räumen über 3,2 m lichter Höhe sind eine
    # EIGENE (teurere) Position — lotrechte Abgrenzung: die Wand eines hohen
    # Raums zählt zur GÄNZE in die Über-Position, kein anteiliger Split.
    pos_hoch = LVPosition("1.1h", f"Innenputz Wände über 3,2 m Raumhöhe — {geschoss}", "m²")
    pos_hoch.quelle = ("in Anlehnung an ÖNORM B 2204 · Räume >3,2 m lichte Höhe "
                       "(lotrechte Abgrenzung, gesamte Wandfläche)")
    pos_laib = LVPosition("1.1a", f"Leibungsputz bis 0,25 m Tiefe — {geschoss}", "lfm")
    pos_laib.quelle = ("ÖNORM B 2204 §5.5.1.3 · Leibungen ≤ 0,25 m Tiefe als "
                       "Laufmeter der Abwicklung (eigene Leibungs-Position)")
    pos_laib_m2 = LVPosition("1.1b", f"Leibungsputz über 0,25 m Tiefe — {geschoss}", "m²")
    pos_laib_m2.quelle = "ÖNORM B 2204 · Leibungen > 0,25 m Tiefe abgewickelt in m²"
    for r in innen:
        u = _room_value(r, "umfang_m")
        h = _room_value(r, "hoehe_m") or baudaten["geschosshoehe_m"]
        if not u:
            continue
        _ziel = pos_hoch if h > 3.2 else pos
        _ziel.add_zeile(f"{_room_name(r)} — Wand brutto", laenge=u, hoehe=h,
                        summe=u * h, quelle=f"{_u_lbl(r, u)} × H={h}",
                        anker=_anker(r))
        for w in fzuord.get(id(r), []):
            bw, hw = w.get("breite_m") or 0, w.get("hoehe_m") or 0
            netto = oeffnung_netto(bw, hw, _wand_cm_of(w, baudaten),
                                   w.get("fph_m", 0), schwelle)
            if netto["uebermessen"] or netto["abzug"] <= 0:
                continue
            _art = (w.get("_art") or "Öffnung").capitalize()
            _ziel.add_zeile(f"  Abzug {_art} {w.get('code','')}".rstrip(),
                            laenge=bw, hoehe=-hw, summe=-netto["abzug"],
                            quelle=f"Öffnung >{schwelle:.1f} m²",
                            anker=_anker(r))
            # Leibung → EIGENE Position (B 2204 §5.5.1.3 ist zweigleisig:
            # MIT Leibungs-Positionen wird abgezogen UND die Leibung separat
            # verrechnet); ≤0,25 m Tiefe als lfm (1.1a), darüber m² (1.1b).
            leibung_zeile(pos_laib, pos_laib_m2,
                          f"{_room_name(r)} — {w.get('code','')}".rstrip(" —"),
                          bw, hw, netto)
    pos.konfidenz = 0.9
    positionen.append(pos)
    if pos_hoch.zeilen:
        pos_hoch.konfidenz = 0.88
        positionen.append(pos_hoch)
    if pos_laib.zeilen:
        pos_laib.konfidenz = 0.85
        positionen.append(pos_laib)
    if pos_laib_m2.zeilen:
        pos_laib_m2.konfidenz = 0.85
        positionen.append(pos_laib_m2)

    pos = LVPosition("1.2", f"Innenputz Decken — {geschoss}", "m²")
    pos.quelle = "in Anlehnung an ÖNORM B 2204 (vormals B 2210) · Σ Raumfläche"
    for r in innen:
        f = _room_value(r, "flaeche_m2")
        if f:
            pos.add_zeile(_room_name(r), summe=f, quelle=f"F={f}",
                          anker=_anker(r))
    pos.konfidenz = 0.97
    positionen.append(pos)

    # AUSSENPUTZ / FASSADE (B 2204: der Verputzer macht auch die Fassade, nicht nur
    # den Innenputz — bisher fehlte die größte Putz-Position ganz). Fläche = Außenwand-
    # Ansichtsfläche brutto (Außenumfang × Höhe, DIESELBE durchgereichte Basis wie das
    # Rohbau-Gewerk → keine widersprüchlichen Zahlen) − Fassaden-Öffnungen>Schwelle.
    # Konfidenz bewusst niedriger: OB die Fassade verputzt wird (statt Klinker/Holz/
    # Sichtbeton/WDVS-Deckschicht) ist Bauweise — als Position anbieten, Kunde prüft.
    _aw_brutto = baudaten.get("_basis_aussenwand_flaeche_m2")
    if _aw_brutto:
        pos = LVPosition("1.3", f"Außenputz Fassade — {geschoss}", "m²")
        pos.quelle = (f"in Anlehnung an ÖNORM B 2204 · Außenwand-Ansichtsfläche brutto "
                      f"− Fassaden-Öffnungen>{schwelle:.1f} m² (Fassaden-Bauweise prüfen)")
        pos.add_zeile("Außenwand Ansichtsfläche brutto", summe=round(_aw_brutto, 2),
                      quelle="Außenumfang × Höhe (gemeinsame Basis)")
        for w in oeffnungen:
            if not _ist_aussenwand(w):
                continue
            netto = oeffnung_netto(w.get("breite_m", 0), w.get("hoehe_m", 0),
                                   baudaten.get("aussenwand_cm", 38),
                                   w.get("fph_m", 0), schwelle)
            if netto["uebermessen"] or netto["abzug"] <= 0:
                continue
            _art = (w.get("_art") or "Öffnung").capitalize()
            pos.add_zeile(f"  Abzug {_art} {w.get('code', '')}".rstrip(),
                          summe=-netto["abzug"],
                          quelle=f"Fassaden-Öffnung >{schwelle:.1f} m²")
        pos.konfidenz = 0.75
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
            pos.add_zeile(_room_name(r), laenge=u, hoehe=hh, summe=u * hh, anker=_anker(r),
                          quelle=f"{_u_lbl(r, u)} × H={hh}")
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
                      summe=_basis_decke * decke_m, quelle=f"F={_basis_decke:.2f} × d={decke_m:.2f}",
                      anker={"ebene": "konturen"})
        if _stiege_f:
            pos.add_zeile("abzügl. Deckenöffnung Stiege", laenge=-round(_stiege_f, 2),
                          hoehe=decke_m, summe=-_stiege_f * decke_m,
                          quelle=f"Stiegenhaus F={_stiege_f:.2f} × d={decke_m:.2f} (Aussparung)")
    else:
        pos.quelle = f"in Anlehnung an ÖNORM B 2204 (vormals B 2211) · Σ Fläche × Deckendicke {decke_m:.2f}m"
        for r in innen:
            f = _room_value(r, "flaeche_m2")
            if f:
                pos.add_zeile(_room_name(r), laenge=f, hoehe=decke_m, summe=f * decke_m, anker=_anker(r),
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
                      quelle=f"ΣF={grundflaeche:.2f} × d={bopl_m:.2f}",
                      anker={"ebene": "konturen"})
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
            pos.add_zeile(_room_name(r), summe=f, quelle=f"F={f}",
                          anker=_anker(r))
    pos.konfidenz = 0.97
    positionen.append(pos)

    pos = LVPosition("1.2", f"Randdämmstreifen — {geschoss}", "lfm")
    pos.quelle = "in Anlehnung an ÖNORM B 2232 · Σ Raumumfang"
    for r in innen:
        u = _room_value(r, "umfang_m")
        if u:
            pos.add_zeile(_room_name(r), laenge=u, summe=u, quelle=_u_lbl(r, u), anker=_anker(r))
    pos.konfidenz = 0.95
    positionen.append(pos)
    return positionen


def gewerk_maler(rooms, windows, baudaten, geschoss="EG", tueren=None):
    positionen = []
    innen = [r for r in rooms if kategorie_of(_room_name(r)) == "Innenraum_warm"]
    schwelle = _schwelle_fuer(baudaten, "maler")
    oeffnungen = _oeffnungen_kombi(windows, tueren)
    fzuord = fenster_pro_raum(rooms, oeffnungen)

    pos = LVPosition("1.1", f"Anstrich Wände bis 3,2 m — {geschoss}", "m²")
    # NORM-BEZUG (Befund aus dem ÖNORM-Audit, docs/OENORM_ROADMAP.md):
    # Maßgeblich ist in Österreich die ÖNORM B 2230-1 (Malerarbeiten) — NICHT
    # die deutsche DIN 18363, die hier bis 2026-07 zitiert wurde. Die
    # Abzugsschwelle 2,5 m² stammt aber aus der DEUTSCHEN Praxis und ist durch
    # B 2230-1 NICHT belegt. Sie wird darum ausdrücklich als offener Parameter
    # ausgewiesen (art='norm_offen') statt still als österreichische Regel
    # auszugehen — je Firma über oeffnung_schwelle_maler überschreibbar.
    pos.quelle = (f"ÖNORM B 2230-1 (Malerarbeiten) · Abzugsschwelle "
                  f"{schwelle:.1f} m² NICHT normbelegt (je Firma zu setzen) · "
                  f"Σ(U×H) − Öffnungen>{schwelle:.1f}m²")
    pos_laib = LVPosition("1.1a", f"Anstrich Leibungen bis 0,25 m Tiefe — {geschoss}", "lfm")
    pos_laib.quelle = "Leibungen ≤ 0,25 m Tiefe als Laufmeter der Abwicklung (B 2204-Systematik)"
    pos_laib_m2 = LVPosition("1.1b", f"Anstrich Leibungen über 0,25 m Tiefe — {geschoss}", "m²")
    pos_laib_m2.quelle = "Leibungen > 0,25 m Tiefe abgewickelt in m²"
    # ÖNORM-HÖHENSPLIT (wie Putz): Räume >3,2 m lichte Höhe zur Gänze in die
    # eigene, teurere Position (Gerüst-/Steigaufwand — lotrechte Abgrenzung).
    pos_hoch = LVPosition("1.1h", f"Anstrich Wände über 3,2 m Raumhöhe — {geschoss}", "m²")
    pos_hoch.quelle = "Räume >3,2 m lichte Höhe (lotrechte Abgrenzung, gesamte Wandfläche)"
    for r in innen:
        u = _room_value(r, "umfang_m")
        h = _room_value(r, "hoehe_m") or baudaten["geschosshoehe_m"]
        if not u:
            continue
        _ziel = pos_hoch if h > 3.2 else pos
        _ziel.add_zeile(f"{_room_name(r)} — Wand", laenge=u, hoehe=h, summe=u * h,
                        quelle=f"{_u_lbl(r, u)} × H={h}", anker=_anker(r))
        for w in fzuord.get(id(r), []):
            bw, hw = w.get("breite_m") or 0, w.get("hoehe_m") or 0
            netto = oeffnung_netto(bw, hw, _wand_cm_of(w, baudaten),
                                   w.get("fph_m", 0), schwelle)
            if netto["uebermessen"] or netto["abzug"] <= 0:
                continue
            _art = (w.get("_art") or "Öffnung").capitalize()
            _ziel.add_zeile(f"  Abzug {_art} {w.get('code','')}".rstrip(),
                            laenge=bw, hoehe=-hw, summe=-netto["abzug"],
                            anker=_anker(r))
            leibung_zeile(pos_laib, pos_laib_m2,
                          f"{_room_name(r)} — {w.get('code','')}".rstrip(" —"),
                          bw, hw, netto)
    pos.konfidenz = 0.88
    positionen.append(pos)
    if pos_hoch.zeilen:
        pos_hoch.konfidenz = 0.85
        positionen.append(pos_hoch)
    if pos_laib.zeilen:
        pos_laib.konfidenz = 0.85
        positionen.append(pos_laib)
    if pos_laib_m2.zeilen:
        pos_laib_m2.konfidenz = 0.85
        positionen.append(pos_laib_m2)

    pos = LVPosition("1.2", f"Anstrich Decken — {geschoss}", "m²")
    pos.quelle = "ÖNORM B 2230-1 (Malerarbeiten) · Σ Raumfläche"
    for r in innen:
        f = _room_value(r, "flaeche_m2")
        if f:
            pos.add_zeile(_room_name(r), summe=f, anker=_anker(r))
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


# Nassraum-Namen für den Fliesenleger (aus dem Raumnamen — die Kategorie
# 'Innenraum_warm' mischt trockene und nasse Räume, daher eine eigene Liste).
_NASSRAEUME = {
    "Bad", "Badezimmer", "WC", "Dusche", "Duschbad", "Sauna", "Nassraum",
    "Waschküche", "Waschkueche", "Waschraum", "Waschen", "Kiwa", "Sanitär", "Sanitaer",
}


def _ist_nassraum(name):
    nm = (name or "").strip()
    teile = [nm] + nm.split() + [p.strip() for p in nm.split("-")]
    return any(t in _NASSRAEUME for t in teile)


def gewerk_fliesen(rooms, windows, baudaten, geschoss="EG", tueren=None):
    """Fliesenleger (LG 27 / ÖNORM B 2207): Nassraum-Böden (Raumfläche) + Nassraum-
    Wände (Umfang × Fliesenhöhe). Nassräume aus dem Raumnamen. Die Fliesenhöhe ist
    eine DOKUMENTIERTE Annahme (Bad/Dusche 2,0 m, WC 1,5 m) — bauseits zu prüfen,
    daher niedrigere Konfidenz bei den Wandfliesen. Leer (→ Gewerk ausgelassen),
    wenn der Plan keine Nassräume trägt."""
    nass = [r for r in rooms if _ist_nassraum(_room_name(r))]
    if not nass:
        return []
    positionen = []

    pos_b = LVPosition("1.1", f"Bodenfliesen Nassräume — {geschoss}", "m²")
    pos_b.quelle = "in Anlehnung an ÖNORM B 2207 · Σ Nassraum-Bodenfläche"
    for r in nass:
        f = _room_value(r, "flaeche_m2")
        if f:
            pos_b.add_zeile(_room_name(r), summe=f, quelle=f"F={f}", anker=_anker(r))
    if pos_b.zeilen:
        pos_b.konfidenz = 0.9
        positionen.append(pos_b)

    pos_w = LVPosition("1.2", f"Wandfliesen Nassräume — {geschoss}", "m²")
    pos_w.quelle = ("in Anlehnung an ÖNORM B 2207 · Nassraum-Umfang × Fliesenhöhe "
                    "− Öffnungen im Fliesenband (Annahme Bad/Dusche 2,0 m, WC 1,5 m — "
                    "Fliesenhöhe bauseits prüfen)")
    oeffnungen = _oeffnungen_kombi(windows, tueren)
    fzuord = fenster_pro_raum(nass, oeffnungen)
    for r in nass:
        u = _room_value(r, "umfang_m")
        if not u:
            continue
        nm = (_room_name(r) or "").lower()
        h = 1.5 if ("wc" in nm and "bad" not in nm and "dusch" not in nm) else 2.0
        pos_w.add_zeile(f"{_room_name(r)} — Wandfläche", laenge=u, hoehe=h, anker=_anker(r),
                        summe=u * h, quelle=f"{_u_lbl(r, u)} × h={h} (angenommen)")
        # Öffnungen im Fliesenband [0..h] abziehen: Tür (fph=0) → volle Bandhöhe,
        # Fenster ab Parapet fph → nur der Teil unter der Fliesenhöhe ist gefliest.
        for w in fzuord.get(id(r), []):
            bw, hw = w.get("breite_m") or 0, w.get("hoehe_m") or 0
            fph = w.get("fph_m", 0) or 0
            band = min(h, fph + hw) - max(0.0, fph)   # Öffnungshöhe innerhalb des Bands
            if bw <= 0 or band <= 0:
                continue
            abzug = round(bw * band, 2)
            if abzug < 0.1:
                continue
            _art = (w.get("_art") or "Öffnung").capitalize()
            pos_w.add_zeile(f"  Abzug {_art} {w.get('code', '')}".rstrip(),
                            summe=-abzug, quelle=f"{bw}×{round(band, 2)} m im Fliesenband",
                            anker=_anker(r))
    if pos_w.zeilen:
        pos_w.konfidenz = 0.75
        positionen.append(pos_w)
    return positionen


def gewerk_fenster(rooms, windows, baudaten, geschoss="EG", tueren=None):
    """Fensterbau / Bauelemente (LG 09 Fenster/Türen — STÜCK-Liste): die byte-exakt
    aus dem Plan extrahierten Öffnungen (Maße + Codes) als Fenster-/Türliste, nach
    Maß gruppiert mit Stückzahl + Σ Ansichtsfläche. Ein Fensterbau-Betrieb braucht
    genau diese Zusammenstellung. Leer (→ Gewerk ausgelassen), wenn keine bemaßten
    Öffnungen erkannt wurden."""
    oeffnungen = _oeffnungen_kombi(windows, tueren)
    fenster = [o for o in oeffnungen if (o.get("_art") or "fenster") != "tuer"]
    tueren_a = [o for o in oeffnungen if o.get("_art") == "tuer" and _ist_aussenwand(o)]
    tueren_i = [o for o in oeffnungen if o.get("_art") == "tuer" and not _ist_aussenwand(o)]
    positionen = []

    def _liste(posnr, titel, quelle, items, konf):
        if not items:
            return
        grp = {}
        for o in items:
            bw, hw = round(o.get("breite_m") or 0, 2), round(o.get("hoehe_m") or 0, 2)
            g = grp.setdefault((bw, hw), {"n": 0, "codes": set()})
            g["n"] += 1
            if o.get("code"):
                g["codes"].add(str(o.get("code")))
        pos = LVPosition(posnr, f"{titel} — {geschoss}", "Stk")
        pos.quelle = quelle
        for (bw, hw), g in sorted(grp.items(), key=lambda x: -(x[0][0] * x[0][1])):
            m2 = round(bw * hw, 2)
            masz = f"{bw:.2f}×{hw:.2f} m" if (bw and hw) else "ohne Maß"
            codes = ", ".join(sorted(g["codes"]))
            pos.add_zeile(f"{masz}{(' [' + codes + ']') if codes else ''}",
                          anzahl=g["n"], summe=g["n"],
                          quelle=(f"{g['n']}× à {m2} m² = {round(g['n'] * m2, 2)} m² Ansichtsfläche"
                                  if m2 else f"{g['n']} Stk (Maß am Plan prüfen)"))
        pos.konfidenz = konf
        positionen.append(pos)

    _liste("1.1", "Fenster", "byte-exakt aus dem Plan (Fenster-Codes/Maße) · Stück-Liste", fenster, 0.85)
    _liste("1.2", "Außentüren", "byte-exakt · Türen in Außenwänden · Stück-Liste", tueren_a, 0.8)
    _liste("1.3", "Innentüren", "byte-exakt · Innentüren · Stück-Liste", tueren_i, 0.8)
    return positionen


def gewerk_daemmung(rooms, windows, baudaten, geschoss="EG", tueren=None):
    """Fassadendämmung / WDVS (LG 44 Wärmedämmverbundsysteme). Fläche = Außenwand-
    Ansichtsfläche brutto − Fassaden-Öffnungen>Schwelle (DIESELBE Basis wie Rohbau/
    Außenputz → keine widersprüchlichen Zahlen), plus separate Laibungsdämmung
    (WDVS-Leibungen werden mitgedämmt). OB die Fassade ein WDVS bekommt (statt
    Klinker/Sichtbeton/hinterlüftet/Holz) ist Bauweise → als Position anbieten, der
    Kunde prüft. Leer (→ Gewerk ausgelassen), wenn keine Außenwand-Basis da ist."""
    _aw_brutto = baudaten.get("_basis_aussenwand_flaeche_m2")
    if not _aw_brutto:
        return []
    schwelle = _schwelle_fuer(baudaten, "putz")   # WDVS folgt der Putz-Öffnungslogik
    oeffnungen = _oeffnungen_kombi(windows, tueren)
    positionen = []
    pos = LVPosition("1.1", f"WDVS Fassadendämmung — {geschoss}", "m²")
    pos.quelle = (f"LG 44 WDVS · Außenwand-Ansichtsfläche brutto − Fassaden-"
                  f"Öffnungen>{schwelle:.1f} m² (Fassaden-Bauweise prüfen)")
    pos.add_zeile("Außenwand Ansichtsfläche brutto", summe=round(_aw_brutto, 2),
                  quelle="Außenumfang × Höhe (gemeinsame Basis wie Rohbau/Außenputz)",
                  anker={"ebene": "konturen"})
    pos_laib = LVPosition("1.1a", f"Laibungsdämmung bis 0,25 m Tiefe — {geschoss}", "lfm")
    pos_laib.quelle = ("WDVS-Leibungen an Fassaden-Öffnungen · ≤ 0,25 m Tiefe als "
                       "Laufmeter der Abwicklung (B 2204-Systematik)")
    pos_laib_m2 = LVPosition("1.1b", f"Laibungsdämmung über 0,25 m Tiefe — {geschoss}", "m²")
    pos_laib_m2.quelle = "WDVS-Leibungen > 0,25 m Tiefe abgewickelt in m²"
    for w in oeffnungen:
        if not _ist_aussenwand(w):
            continue
        netto = oeffnung_netto(w.get("breite_m", 0), w.get("hoehe_m", 0),
                               baudaten.get("aussenwand_cm", 38),
                               w.get("fph_m", 0), schwelle)
        if netto["uebermessen"] or netto["abzug"] <= 0:
            continue
        _art = (w.get("_art") or "Öffnung").capitalize()
        # Hüllen-Anker auch am ABZUG: die Zeile gehört zur Fassade — ohne
        # Anker war sie die einzige WDVS-Zeile ohne "Im Plan zeigen"
        # (vom erweiterten Hüllen-Anker-Wächter gefunden).
        pos.add_zeile(f"  Abzug {_art} {w.get('code','')}".rstrip(),
                      summe=-netto["abzug"], quelle=f"Fassaden-Öffnung >{schwelle:.1f} m²",
                      anker=({"raum": w.get("raum")} if w.get("raum")
                             else {"ebene": "konturen"}))
        leibung_zeile(pos_laib, pos_laib_m2,
                      f"{_art} {w.get('code','')}".rstrip(" —"),
                      w.get("breite_m", 0), w.get("hoehe_m", 0), netto)
    pos.konfidenz = 0.7
    positionen.append(pos)
    if pos_laib.zeilen:
        pos_laib.konfidenz = 0.65
        positionen.append(pos_laib)
    if pos_laib_m2.zeilen:
        pos_laib_m2.konfidenz = 0.65
        positionen.append(pos_laib_m2)
    return positionen


def gewerk_geruest(rooms, windows, baudaten, geschoss="EG", tueren=None):
    """Fassadengerüst (LG 04 Gerüste). Eingerüstete Fläche = Außenwand-Ansichts-
    fläche brutto; Öffnungen werden NICHT abgezogen — das Gerüst läuft davor durch
    (übermessen). DIESELBE Basis wie Rohbau/Außenputz → keine Widersprüche. OB ein
    Fassadengerüst nötig ist (Geschossanzahl, Fassadenarbeiten), ist Projekt-Sache
    → als Position anbieten. Leer (→ ausgelassen) ohne Außenwand-Basis."""
    _aw_brutto = baudaten.get("_basis_aussenwand_flaeche_m2")
    if not _aw_brutto:
        return []
    pos = LVPosition("1.1", f"Fassadengerüst — {geschoss}", "m²")
    pos.quelle = ("LG 04 Gerüste · eingerüstete Ansichtsfläche = Außenumfang × Höhe · "
                  "Öffnungen übermessen (Gerüst läuft durch)")
    pos.add_zeile("Eingerüstete Fassadenfläche", summe=round(_aw_brutto, 2),
                  quelle="Außenwand-Ansichtsfläche brutto (gemeinsame Basis)",
                  anker={"ebene": "konturen"})
    pos.konfidenz = 0.7
    return [pos]


# LG-Nummern = offizielle Standardisierte LB-Hochbau (StLB-HB Version 020,
# BMWET) — byte-exakt aus der Leistungsbeschreibung gelesen. Öffentlicher
# Standard (keine ONLV-Lizenz nötig, die betrifft nur die Positions-TEXTE);
# damit mappt der ÖNORM-Export sauber in die AVA-Software der Baubetriebe
# (ORCA/ABK/Bau-SU), die nach LG/ULG/Position gliedern.
def gewerk_erdarbeiten(rooms, windows, baudaten, geschoss="EG", tueren=None):
    """Erdarbeiten (LG 02 — in Anlehnung an ÖNORM B 2205). ANNAHME-Positionen
    nach dem WDVS/Gerüst-Muster: OB und wie tief ausgehoben wird, ist Projekt-
    Sache (Baugrund, Keller, Frosttiefe) — die Mengen-BASIS ist aus dem Plan
    belegt (Bodenplatten-Fläche + Außenumfang). Jede Annahme steht in der
    Zeile und ist je Firma überschreibbar (aushub_tiefe_m, humus_tiefe_m,
    arbeitsraum_m). Leer (→ Gewerk ausgelassen) ohne Flächen-Basis."""
    bopl = baudaten.get("_basis_bodenplatte_m2")
    if not bopl:
        # Fallback: Grundfläche des erdnächsten Geschosses aus den Räumen
        kg = [r for r in rooms if str(r.get("geschoss") or "").upper() in ("KG", "UG")]
        eg = [r for r in rooms if str(r.get("geschoss") or "").upper() in ("EG", "")]
        basis = kg or eg
        bopl = sum(float(_room_value(r, "flaeche_m2") or 0) for r in basis
                   if kategorie_of(_room_name(r)) in
                   ("Innenraum_warm", "Nebenraum_kalt", "Stiegenhaus"))
    if not bopl or bopl <= 0:
        return []
    umf = baudaten.get("_basis_aussenumfang_m") or 4.0 * math.sqrt(bopl)
    hat_keller = any(str(r.get("geschoss") or "").upper() in ("KG", "UG") for r in rooms)
    arbeitsraum = float(baudaten.get("arbeitsraum_m") or 0.8)
    humus_t = float(baudaten.get("humus_tiefe_m") or 0.20)
    aushub_t = float(baudaten.get("aushub_tiefe_m") or (2.60 if hat_keller else 0.50))
    grube = bopl + umf * arbeitsraum   # Grubenfläche inkl. Arbeitsraum-Streifen

    positionen = []
    pos = LVPosition("1.1", "Humusabtrag und Zwischenlagerung", "m³")
    pos.quelle = "in Anlehnung an ÖNORM B 2205 · Grubenfläche × Humus-Annahme 0,20 m"
    pos.add_zeile("Baufeld (Bodenplatte + Arbeitsraum)", laenge=round(grube, 2),
                  hoehe=humus_t, summe=grube * humus_t,
                  quelle=(f"({bopl:.1f} m² + U {umf:.1f} m × {arbeitsraum:.1f} m) "
                          f"× {humus_t:.2f} m (Annahme)"),
                  anker={"ebene": "konturen"})
    pos.konfidenz = 0.55
    positionen.append(pos)

    pos = LVPosition("1.2", "Baugrubenaushub — "
                     + ("Keller erkannt" if hat_keller else "frostfreie Gründung"), "m³")
    pos.quelle = ("in Anlehnung an ÖNORM B 2205 · Grubenfläche × Aushubtiefe-ANNAHME — "
                  "Tiefe/Böschung sind Projekt-Sache (Baugrundgutachten); "
                  "aushub_tiefe_m je Firma überschreibbar")
    pos.add_zeile("Aushub bis Aushubsohle", laenge=round(grube, 2), hoehe=aushub_t,
                  summe=grube * aushub_t,
                  quelle=(f"{grube:.1f} m² × {aushub_t:.2f} m "
                          f"({'KG im Plan' if hat_keller else 'kein KG'} — Annahme)"),
                  anker={"ebene": "konturen"})
    pos.konfidenz = 0.5
    positionen.append(pos)

    pos = LVPosition("1.3", "Rollierung/Frostkoffer unter Bodenplatte", "m³")
    pos.quelle = "Bodenplatten-Fläche × 0,15 m Rollierung (Annahme, üblich 10–20 cm)"
    pos.add_zeile("Rollierung 15 cm", laenge=round(bopl, 2), hoehe=0.15,
                  summe=bopl * 0.15, quelle=f"{bopl:.1f} m² × 0,15 m",
                  anker={"ebene": "konturen"})
    pos.konfidenz = 0.55
    positionen.append(pos)

    pos = LVPosition("1.4", "Hinterfüllung Arbeitsraum (lagenweise verdichtet)", "m³")
    pos.quelle = "Außenumfang × Arbeitsraum-Streifen × Aushubtiefe (Annahme)"
    pos.add_zeile("Arbeitsraum-Verfüllung", laenge=round(umf * arbeitsraum, 2),
                  hoehe=aushub_t, summe=umf * arbeitsraum * aushub_t,
                  quelle=f"U {umf:.1f} m × {arbeitsraum:.1f} m × {aushub_t:.2f} m",
                  anker={"ebene": "konturen"})
    pos.konfidenz = 0.5
    positionen.append(pos)
    return positionen


GEWERKE = {
    "putz":    ("Verputzer (LG 10 Putz — in Anlehnung an ÖNORM B 2204)", gewerk_putz, "10"),
    "rohbau":  ("Maurer / Rohbau (LG 08 Mauerarbeiten — in Anlehnung an ÖNORM B 2204)", gewerk_rohbau, "08"),
    "beton":   ("Stahlbeton (LG 07 Beton- und Stahlbetonarbeiten)", gewerk_beton, "07"),
    "estrich": ("Estrich / Boden (LG 11 Estricharbeiten — in Anlehnung an ÖNORM B 2232)", gewerk_estrich, "11"),
    "maler":   ("Maler / Anstrich (LG 46 Beschichtung auf Mauerwerk, Putz und Beton)", gewerk_maler, "46"),
    "fliesen": ("Fliesenleger (LG 27 Fliesen- und Plattenarbeiten — in Anlehnung an ÖNORM B 2207)", gewerk_fliesen, "27"),
    "fenster": ("Fensterbau / Bauelemente (LG 09 Fenster, Fenstertüren — Stück-Liste)", gewerk_fenster, "09"),
    "daemmung": ("Fassadendämmung / WDVS (LG 44 Wärmedämmverbundsysteme)", gewerk_daemmung, "44"),
    "geruest": ("Gerüstbau (LG 04 Gerüste — Fassadengerüst, eingerüstete Ansichtsfläche)", gewerk_geruest, "04"),
    "erdarbeiten": ("Erdarbeiten (LG 02 — in Anlehnung an ÖNORM B 2205, Annahme-Positionen)", gewerk_erdarbeiten, "02"),
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
            if not positionen:
                # Leeres Gewerk auslassen — Beton ohne Säulen/Kamin, Fliesen ohne
                # Nassräume: eine leere LV-Sektion ist nie nützlich (vorher nur für
                # Beton; generalisiert, seit Fliesen dazukam).
                continue
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


# ════════════════════════════════════════════════════════════════════════
# AUFMASS-KREUZTABELLE (Räume × Positionen)
# ════════════════════════════════════════════════════════════════════════
def aufmass_matrix(gewerke, raeume=None):
    """KREUZTABELLE Räume × Positionen — die Kontrollansicht des Aufmaßes.

    Jede Rechenzeile trägt bereits ihren Plan-Anker {"raum": <Name>}; daraus
    fällt die Matrix ohne neue Erkennung ab: Zeilen = Räume (mit F/U), Spalten
    = Positionen, Zellen = die dem Raum zurechenbare Menge (Brutto minus seine
    Abzüge). So ist auf einen Blick prüfbar, ob jeder Raum die Positionen trägt,
    die er tragen soll — und welche Menge NICHT raumscharf belegt ist.

    gewerke: dict {key: {label, lg, positionen:[...]}} wie aus berechne_gewerke
    raeume:  optionale Raumliste (F/U je Raum für die Zeilenköpfe)
    -> {positionen, raeume, ohne_anker, deckung_pct}
    """
    spalten, zellen = [], {}
    ohne = []
    for gkey, gv in (gewerke or {}).items():
        if not isinstance(gv, dict):
            continue
        for p in (gv.get("positionen") or []):
            skey = f"{gkey}::{p.get('posnr')}"
            spalten.append({
                "key": skey, "gewerk": gkey,
                "gewerk_label": gv.get("label") or gkey,
                "lg": gv.get("lg"), "posnr": p.get("posnr"),
                "beschreibung": p.get("beschreibung"),
                "einheit": p.get("einheit"),
                "endsumme": p.get("endsumme"),
                "regel": p.get("quelle"),          # die Aufmaßregel im Klartext
                "regel_obj": p.get("regel"),       # maschinenlesbar (art/norm/formel)
            })
            for z in (p.get("zeilen") or []):
                _a = z.get("anker") or {}
                # Nach der eindeutigen Raumkennung gruppieren, NICHT nach dem
                # Namen — sonst werden die drei "Bad" eines Wohnbaus zu einer
                # Zeile und zeigen die Zahlen des letzten. "raum" bleibt der
                # Anzeigetext. Aeltere Zeilen ohne rkey fallen auf den Namen
                # zurueck (dann eben mit der alten Ungenauigkeit, aber ohne
                # Absturz).
                rk = (_a.get("rkey") or _a.get("raum") or "").strip()
                w = z.get("wert")
                if w is None:
                    continue
                if rk:
                    zellen.setdefault(rk, {}).setdefault(skey, 0.0)
                    zellen[rk][skey] += float(w)
                else:
                    ohne.append({"pos": skey, "beschreibung": p.get("beschreibung"),
                                 "text": z.get("text"), "wert": float(w)})

    # Zeilenköpfe: bekannte Räume zuerst (mit F/U), dann nur-in-Zeilen genannte.
    # Schluessel ist dieselbe Kennung wie im Anker.
    fu = {}
    for r in (raeume or []):
        n = (r.get("name") or r.get("raum") or "").strip()
        if n:
            fu[_room_key(r)] = {
                "raum": n,
                "f_m2": r.get("flaeche_m2") if r.get("flaeche_m2") is not None
                else r.get("f_m2"),
                "u_m": r.get("umfang_m") if r.get("umfang_m") is not None
                else r.get("u_m"),
                "geschoss": r.get("geschoss"),
                "wohnung": r.get("wohnung") or r.get("top")}
    keys = list(fu.keys()) + [k for k in zellen if k not in fu]
    zeilen_out = []
    for k in keys:
        mengen = {sk: round(v, 2) for sk, v in (zellen.get(k) or {}).items()
                  if abs(v) >= 0.005}
        _k = fu.get(k) or {}
        zeilen_out.append({
            # Anzeigename: bei gleichnamigen Raeumen die Wohnung dazu, sonst
            # sieht der Nutzer dreimal "Bad" und kann sie nicht auseinander-
            # halten.
            "raum": (_k.get("raum") or (k.split("|")[0] if k else "?")),
            "wohnung": _k.get("wohnung"),
            "rkey": k,
            "f_m2": _k.get("f_m2"),
            "u_m": _k.get("u_m"),
            "geschoss": _k.get("geschoss"),
            "mengen": mengen,
            "n_positionen": len(mengen),
        })

    verankert = sum(abs(v) for m in zellen.values() for v in m.values())
    frei = sum(abs(o["wert"]) for o in ohne)
    ges = verankert + frei
    return {
        "positionen": spalten,
        "raeume": zeilen_out,
        "ohne_anker": ohne,
        "deckung_pct": round(verankert / ges * 100, 1) if ges else 0.0,
    }


# ════════════════════════════════════════════════════════════════════════
# EIGENE POSITIONEN mit Pflicht-Aufmaßregel
# ════════════════════════════════════════════════════════════════════════
# Im Ziel-Workflow hinterlegt der Betrieb SEINE Leistungspositionen und
# verknüpft jede mit einer Aufmaßregel — ohne Regel ist die Position gesperrt
# („Regel fehlt"). Hier ist der berechenbare Katalog dazu: jede Regel weiß,
# welche Menge sie aus Räumen/Öffnungen bildet, in welcher Einheit, und nach
# welchem Regelwerk. Das Ergebnis ist eine ganz normale LVPosition — mit
# vollem Rechenweg UND Plan-Ankern, also in Kreuztabelle, Aufmaßblatt und
# A-2063-Export sofort mit dabei.
AUFMASS_REGELN = {
    "boden": {
        "name": "Bodenfläche (Raumfläche)",
        "einheit": "m²", "norm": "ÖNORM B 2232",
        "formel": "Σ Raumfläche F",
    },
    "decke": {
        "name": "Deckenfläche",
        "einheit": "m²", "norm": "ÖNORM B 2204",
        "formel": "Σ Raumfläche F (Deckenuntersicht)",
    },
    "wand_brutto": {
        "name": "Wandfläche brutto (ohne Öffnungsabzug)",
        "einheit": "m²", "norm": "ÖNORM B 2204",
        "formel": "Σ (Umfang U × Höhe H)",
    },
    "wand_netto": {
        "name": "Wandfläche netto (Öffnungen über Schwelle abgezogen)",
        "einheit": "m²", "norm": "ÖNORM B 2204",
        "formel": "Σ (U × H) − Öffnungen > Schwelle",
    },
    "umfang": {
        "name": "Raumumfang",
        "einheit": "m", "norm": "ÖNORM B 2204",
        "formel": "Σ Umfang U",
    },
    "sockel": {
        "name": "Sockelleiste (Umfang abzüglich Türbreiten)",
        "einheit": "m", "norm": "ÖNORM B 2232",
        "formel": "Σ (U − Σ Türbreiten des Raums)",
    },
}


def eigene_position(regel_id, posnr, bezeichnung, rooms, windows=None,
                    tueren=None, baudaten=None, raum_filter=None,
                    verschnitt_pct=0.0, geschoss="EG"):
    """Eine BETRIEBS-EIGENE Position nach gewählter Aufmaßregel rechnen.

    regel_id      Schlüssel aus AUFMASS_REGELN — PFLICHT. Ohne gültige Regel
                  gibt es keine Menge (das ist die „Regel fehlt"-Sperre).
    raum_filter   optional: Liste von Raumnamen; sonst alle passenden Räume.
    verschnitt_pct Aufschlag in Prozent (z.B. 5 für 5 % Verschnitt) — wird als
                  EIGENE, sichtbare Zeile geführt, nie still eingerechnet.
    Rückgabe: LVPosition (mit Rechenweg + Plan-Ankern) oder None.
    """
    regel = AUFMASS_REGELN.get(regel_id)
    if not regel:
        return None
    bd = baudaten or {}
    h_def = bd.get("geschosshoehe_m") or 2.5
    pos = LVPosition(posnr or "1.1", bezeichnung or regel["name"],
                     regel["einheit"])
    pos.quelle = f"{regel['norm']} · {regel['formel']}"
    pos.konfidenz = 0.9

    namen = None
    if raum_filter:
        namen = {re.sub(r"[\s\-_/]+", "", str(n).lower()) for n in raum_filter}

    oeff = _oeffnungen_kombi(windows or [], tueren or [])
    ziel = [r for r in (rooms or [])
            if not namen
            or re.sub(r"[\s\-_/]+", "", (_room_name(r) or "").lower()) in namen]
    fz = fenster_pro_raum(ziel, oeff)
    schwelle = _schwelle_fuer(bd)

    for r in ziel:
        nm = _room_name(r)
        f = _room_value(r, "flaeche_m2")
        u = _room_value(r, "umfang_m")
        h = _room_value(r, "hoehe_m") or h_def
        ank = _anker(r)
        if regel_id in ("boden", "decke"):
            if f:
                pos.add_zeile(nm, summe=f, quelle=f"F={f}", anker=ank)
        elif regel_id == "umfang":
            if u:
                pos.add_zeile(nm, summe=u, quelle=_u_lbl(r, u), anker=ank)
        elif regel_id == "sockel":
            if u:
                tb = sum((t.get("breite_m") or 0) for t in fz.get(id(r), [])
                         if (t.get("_art") or "") == "tuer")
                pos.add_zeile(nm, summe=max(0.0, u - tb),
                              quelle=f"{_u_lbl(r, u)} − Türen {round(tb, 2)} m",
                              anker=ank)
        elif regel_id in ("wand_brutto", "wand_netto"):
            if not u:
                continue
            pos.add_zeile(f"{nm} — Wand brutto", laenge=u, hoehe=h, summe=u * h,
                          quelle=f"{_u_lbl(r, u)} × H={h}", anker=ank)
            if regel_id == "wand_netto":
                for w in fz.get(id(r), []):
                    bw, hw = w.get("breite_m") or 0, w.get("hoehe_m") or 0
                    netto = oeffnung_netto(bw, hw, _wand_cm_of(w, bd),
                                           w.get("fph_m", 0), schwelle)
                    if netto["uebermessen"] or netto["abzug"] <= 0:
                        continue
                    pos.add_zeile(
                        f"  Abzug {(w.get('_art') or 'Öffnung').capitalize()} "
                        f"{w.get('code', '')}".rstrip(),
                        laenge=bw, hoehe=-hw, summe=-netto["abzug"],
                        quelle=f"Öffnung > {schwelle:.1f} m²", anker=ank)
    if not pos.zeilen:
        return None
    # VERSCHNITT als eigene Zeile — sichtbar, nicht still eingerechnet.
    try:
        v = float(verschnitt_pct or 0)
    except (TypeError, ValueError):
        v = 0.0
    if v > 0:
        basis = pos.endsumme
        pos.add_zeile(f"Verschnitt {v:.1f} %", summe=round(basis * v / 100.0, 3),
                      quelle=f"{v:.1f} % auf {basis} {regel['einheit']}")
    return pos
