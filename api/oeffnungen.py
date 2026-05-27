"""Öffnungs-Extraktion aus Text-Layer (Türen + Fenster).

ÖNORM A 6240-2 dokumentiert die Standard-Plan-Beschriftung:
  - STUK = Sturz-Unter-Kante (Rohbau-Maß über Fußboden-Oberkante FBOK)
  - FPH  = Fertige Parapet-Höhe über FBOK (Brüstung)
  - RPH  = Roh-Parapet-Höhe über RDOK (Rohdecke)
  - AW / IW = Außenwand / Innenwand
  - Tür-Codes variieren: "D 1", "T 1", "DR" (Drehflügel), "EI 30-C" (Brandschutz)

Aus diesen Codes berechnen wir pro Öffnung:
  - Höhe = STUK − FPH
  - Breite = nahegelegene Zahlen-Span (z.B. "80" cm oder "1,30" m)
  - Typ = Tür wenn FPH=0, sonst Fenster (Hauptregel, kann durch D-Code überstimmt werden)
  - Raum = nächster Raum-Center

Die Span-Cluster sind im Plan typisch innerhalb 25-40pt voneinander entfernt.
"""
from __future__ import annotations
import re
import math
from typing import Optional


# Anker-Patterns (Wortgrenzen damit "FPHX" nicht als FPH matcht)
FPH_RX = re.compile(r"^FPH\s*[:+]?\s*([0-9]+[,.][0-9]+|[0-9]+)\b", re.I)
STUK_RX = re.compile(r"^STUK\s*[:+]?\s*([0-9]+[,.][0-9]+|[0-9]+)\b", re.I)
RPH_RX = re.compile(r"^RPH\s*[:+]?\s*([0-9]+[,.][0-9]+|[0-9]+)\b", re.I)
# Allein stehende cm- oder m-Zahl, plausibel als Öffnungs-Breite
BREITE_CM_RX = re.compile(r"^([0-9]{2,3})$")  # "60", "80", "120"
BREITE_M_RX = re.compile(r"^([0-9])[,.]([0-9]{1,2})$")  # "0,80", "1,30", "2,40"
WAND_RX = re.compile(r"^(AW|IW)\s*\d?$", re.I)
# Tür-Marker
TUER_CODE_RX = re.compile(r"^(D\s*\d+|T\s*\d+|DR|EI\s*\d|RS\s*\d)$", re.I)


def _parse_num(s: str) -> Optional[float]:
    try:
        return float(s.replace(",", "."))
    except (ValueError, AttributeError):
        return None


def _dist(a, b):
    return math.hypot(a["cx"] - b["cx"], a["cy"] - b["cy"])


def extract_oeffnungen_from_text(spans: list, rooms: list, max_cluster_pt: float = 35.0,
                                  max_room_dist_pt: float = 200.0) -> list:
    """Extrahiert Öffnungen (Fenster + Türen) aus den Plan-Text-Spans.

    spans:  Liste von {"text", "cx", "cy", "bbox", "size"} (Text-Layer)
    rooms:  Liste der bereits erkannten Räume mit {"name", "cx", "cy"}
    max_cluster_pt: Spans näher als X pt gehören zur selben Öffnung
    max_room_dist_pt: max Entfernung Öffnung → Raum-Zuordnung
    """
    # 1) Anchor-Spans sammeln: jede FPH-Span ist Startpunkt einer Öffnung
    fph_spans = []  # {"value", "cx", "cy"}
    stuk_spans = []
    rph_spans = []
    breite_spans = []
    wand_spans = []
    tuer_marker_spans = []

    for s in spans:
        t = (s.get("text") or "").strip()
        if not t:
            continue
        m = FPH_RX.match(t)
        if m:
            v = _parse_num(m.group(1))
            if v is not None:
                # FPH-Werte: "0,00" → 0.0 (boden), "92" → 92 (cm) → 0.92,
                # "1,62" → 1.62 (m). Heuristik: wenn Wert > 5 → cm → /100
                vm = v / 100.0 if v > 5 else v
                fph_spans.append({"value_m": vm, "cx": s["cx"], "cy": s["cy"], "raw": t})
            continue
        m = STUK_RX.match(t)
        if m:
            v = _parse_num(m.group(1))
            if v is not None:
                vm = v / 100.0 if v > 5 else v
                stuk_spans.append({"value_m": vm, "cx": s["cx"], "cy": s["cy"], "raw": t})
            continue
        m = RPH_RX.match(t)
        if m:
            v = _parse_num(m.group(1))
            if v is not None:
                vm = v / 100.0 if v > 5 else v
                rph_spans.append({"value_m": vm, "cx": s["cx"], "cy": s["cy"], "raw": t})
            continue
        m = BREITE_CM_RX.match(t)
        if m:
            v_cm = int(m.group(1))
            if 50 <= v_cm <= 350:  # 50cm-3.5m Breiten plausibel
                breite_spans.append({"value_m": v_cm / 100.0, "cx": s["cx"], "cy": s["cy"], "raw": t})
            continue
        m = BREITE_M_RX.match(t)
        if m:
            v_m = float(m.group(1) + "." + m.group(2))
            if 0.50 <= v_m <= 3.50:
                breite_spans.append({"value_m": v_m, "cx": s["cx"], "cy": s["cy"], "raw": t})
            continue
        if WAND_RX.match(t):
            wand_spans.append({"typ": t.upper().replace(" ", "")[:2], "cx": s["cx"], "cy": s["cy"], "raw": t})
            continue
        if TUER_CODE_RX.match(t):
            tuer_marker_spans.append({"code": t.upper(), "cx": s["cx"], "cy": s["cy"], "raw": t})
            continue

    # 2) Cluster: pro FPH-Span einen Öffnungs-Kandidaten bilden
    oeffnungen = []
    for fph in fph_spans:
        # STUK im Cluster (mit FPH)
        stuk_near = [s for s in stuk_spans if math.hypot(s["cx"] - fph["cx"], s["cy"] - fph["cy"]) < max_cluster_pt]
        if not stuk_near:
            continue  # ohne STUK keine Höhe ableitbar
        # Nächste STUK nehmen
        stuk_near.sort(key=lambda s: math.hypot(s["cx"] - fph["cx"], s["cy"] - fph["cy"]))
        stuk = stuk_near[0]

        h_m = stuk["value_m"] - fph["value_m"]
        if h_m <= 0 or h_m > 3.5:
            continue  # unplausibel

        # Breite suchen — bevorzugt cm-Zahl (z.B. "80") nahegelegen, sonst m-Format
        breiten_near = [
            b for b in breite_spans
            if math.hypot(b["cx"] - fph["cx"], b["cy"] - fph["cy"]) < max_cluster_pt
        ]
        breite_m = None
        if breiten_near:
            breiten_near.sort(key=lambda b: math.hypot(b["cx"] - fph["cx"], b["cy"] - fph["cy"]))
            breite_m = breiten_near[0]["value_m"]
        else:
            # Erweiterter Radius — Breite kann etwas weiter weg stehen
            breiten_far = [
                b for b in breite_spans
                if math.hypot(b["cx"] - fph["cx"], b["cy"] - fph["cy"]) < max_cluster_pt * 2
            ]
            if breiten_far:
                breiten_far.sort(key=lambda b: math.hypot(b["cx"] - fph["cx"], b["cy"] - fph["cy"]))
                breite_m = breiten_far[0]["value_m"]

        # Wand-Typ (Außen/Innen)
        wand_near = [
            w for w in wand_spans
            if math.hypot(w["cx"] - fph["cx"], w["cy"] - fph["cy"]) < max_cluster_pt
        ]
        wand_typ = None
        if wand_near:
            wand_near.sort(key=lambda w: math.hypot(w["cx"] - fph["cx"], w["cy"] - fph["cy"]))
            wand_typ = wand_near[0]["typ"]

        # Tür-Marker im erweiterten Radius
        tuer_near = [
            t for t in tuer_marker_spans
            if math.hypot(t["cx"] - fph["cx"], t["cy"] - fph["cy"]) < max_cluster_pt * 1.5
        ]

        # Klassifikation: bodengleich (FPH < 0,15m) = Tür (alle Türöffnungen
        # haben FPH 0, egal ob Innentür, Außentür oder Fenstertür-Schiebetür).
        # Reine Fenster haben immer eine Brüstung > 0 — meist 0,90m
        # (Wohnraum), 1,60m (Bad/WC-Lüftung) oder 0,30m (Frühstücksecke).
        # Wenn explizite Tür-Codes (DR, EI, D 1) im Cluster → garantiert Tür.
        is_tuer = bool(tuer_near) or (fph["value_m"] < 0.15)

        typ = "tuer" if is_tuer else "fenster"

        # Raum-Zuordnung — nächster Innenraum (Loggia/Terrasse/Parkplatz
        # sind Außenbereiche, denen werden Öffnungen nicht zugeordnet, weil
        # die Beschriftung typisch zwischen Innenraum und Loggia steht).
        OUTDOOR = {"terrasse", "loggia", "balkon", "parkplatz", "carport"}
        def _is_outdoor(name):
            if not name: return False
            first = name.strip().split()[0].lower()
            return first in OUTDOOR
        raum_name = None
        if rooms:
            best, best_d = None, float("inf")
            for r in rooms:
                if r.get("cx") is None or r.get("cy") is None:
                    continue
                name = r.get("name") or r.get("bezeichnung") or ""
                # Bei AW-Öffnungen: Innenräume bevorzugen, Außenbereiche
                # nur als Fallback. Bei IW: alle Räume gleichberechtigt.
                if _is_outdoor(name):
                    continue
                d = math.hypot(r["cx"] - fph["cx"], r["cy"] - fph["cy"])
                if d < best_d and d < max_room_dist_pt:
                    best_d, best = d, r
            if best:
                raum_name = best.get("name") or best.get("bezeichnung")
            else:
                # Fallback — auch Outdoor-Räume akzeptieren wenn kein Innenraum nah genug
                for r in rooms:
                    if r.get("cx") is None: continue
                    d = math.hypot(r["cx"] - fph["cx"], r["cy"] - fph["cy"])
                    if d < best_d and d < max_room_dist_pt:
                        best_d, best = d, r
                if best:
                    raum_name = best.get("name") or best.get("bezeichnung")

        flaeche = round((breite_m or 0) * h_m, 3)
        oeffnungen.append({
            "typ": typ,
            "raum": raum_name,
            "breite_m": breite_m,
            "hoehe_m": round(h_m, 2),
            "flaeche_m2": flaeche,
            "fph_m": fph["value_m"],
            "stuk_m": stuk["value_m"],
            "wand_typ": wand_typ,
            "tuer_codes": [t["code"] for t in tuer_near],
            "cx": fph["cx"],
            "cy": fph["cy"],
            "quelle": "text-layer-stuk-fph",
            "konfidenz": 0.95 if (breite_m and raum_name) else 0.7,
        })

    # Dedup: zwei Beschriftungs-Cluster derselben Öffnung können entstehen,
    # weil ArchiCAD pro Tür/Fenster mehrere STUK+FPH-Anker setzt
    # (z.B. STUK-Achse oben + unten, oder beidseitig der Wand). Wir mergen:
    #   - räumlich nah (< 40 pt) + identische Maße → derselbe Eintrag
    #   - räumlich sehr nah (< 15 pt) → derselbe Eintrag, unabhängig von Maßen
    def _same_size(a, b, tol_m=0.05):
        for k in ("breite_m", "hoehe_m"):
            va, vb = a.get(k), b.get(k)
            if va is None or vb is None:
                return False
            if abs(va - vb) > tol_m:
                return False
        return True

    cleaned = []
    used = [False] * len(oeffnungen)
    for i, o in enumerate(oeffnungen):
        if used[i]:
            continue
        # Sammle alle Duplikate ein
        keep = o
        for j in range(i + 1, len(oeffnungen)):
            if used[j]:
                continue
            o2 = oeffnungen[j]
            d = math.hypot(o["cx"] - o2["cx"], o["cy"] - o2["cy"])
            if d < 15 or (d < 40 and _same_size(o, o2)):
                # Bevorzuge den mit höherer Konfidenz / mehr Daten
                cur_score = (1 if keep.get("breite_m") else 0) + (keep.get("konfidenz") or 0)
                new_score = (1 if o2.get("breite_m") else 0) + (o2.get("konfidenz") or 0)
                if new_score > cur_score:
                    keep = o2
                used[j] = True
        cleaned.append(keep)
        used[i] = True

    return cleaned
