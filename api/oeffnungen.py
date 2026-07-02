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


# Anker-Patterns. Trenner :/+/. optional, damit "FPH 0,90", "FPH:0.90" und
# "FPH0,90" gleichermaßen matchen. FBH = Fenster-Brüstungs-Höhe (Synonym zur
# Parapethöhe FPH — vom Nutzer als reales Plan-Code bestätigt) → wie FPH behandelt.
FPH_RX = re.compile(r"^F(?:PH|BH)\s*[:+.]?\s*([0-9]+[,.][0-9]+|[0-9]+)\b", re.I)
STUK_RX = re.compile(r"^STUK\s*[:+.]?\s*([0-9]+[,.][0-9]+|[0-9]+)\b", re.I)
RPH_RX = re.compile(r"^RPH\s*[:+.]?\s*([0-9]+[,.][0-9]+|[0-9]+)\b", re.I)
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
        # Fallback: bei versetzter Beschriftung (FPH/STUK weiter auseinander)
        # bis 1.5× Radius suchen — nur wenn im engen Radius nichts ist.
        # Konservativ gehalten (1.5× statt 2×) gegen Fehl-Paarung; die Höhen-
        # Plausi (0 < h ≤ 3.5m unten) verwirft den Rest.
        if not stuk_near:
            stuk_near = [s for s in stuk_spans if math.hypot(s["cx"] - fph["cx"], s["cy"] - fph["cy"]) < max_cluster_pt * 1.5]
        if not stuk_near:
            continue  # ohne STUK keine Höhe ableitbar
        # Nächste STUK nehmen
        stuk_near.sort(key=lambda s: math.hypot(s["cx"] - fph["cx"], s["cy"] - fph["cy"]))
        stuk = stuk_near[0]

        h_m = stuk["value_m"] - fph["value_m"]
        if h_m <= 0 or h_m > 3.5:
            continue  # unplausibel

        # Breite suchen — Plausibilitäts-Score statt nur nächstgelegen:
        #   - Distanz zum FPH-Anker (näher = besser)
        #   - Aspect Ratio B/H im plausiblen Bereich [0.4, 4.0]
        #   - Türen (FPH<0,15): Breite typisch 0.60-1.50m → Bonus
        #   - Quadratfenster (Lüfter): wenn H~60cm, Breite ~60cm bevorzugt
        breiten_kand = [
            (math.hypot(b["cx"] - fph["cx"], b["cy"] - fph["cy"]), b)
            for b in breite_spans
            if math.hypot(b["cx"] - fph["cx"], b["cy"] - fph["cy"]) < max_cluster_pt * 2
        ]
        breiten_kand.sort()
        is_tuer_candidate = fph["value_m"] < 0.15
        breite_m = None
        best_score = -1.0
        for dist, b in breiten_kand:
            bw = b["value_m"]
            score = 100.0 - dist  # näher = besser, Basis-Score
            # Distanzgrenze: Spans innerhalb 35pt sind Cluster, außerhalb Penalty
            if dist > max_cluster_pt:
                score -= 30
            # Aspect-Ratio-Filter — Standard-Innentür ist 80×205cm = 0.39,
            # Standard-Fenster mind. 0.50, also Untergrenze 0.25 (60cm×200cm).
            ratio = bw / h_m if h_m > 0 else 0
            if ratio < 0.25 or ratio > 4.0:
                score -= 60  # unplausibel
            # Türen-Heuristik: bevorzuge Standard-Innentüren in cm-Schritten
            #   60, 70, 80, 90, 100 cm — diese werden seriell gefertigt
            #   und sind die häufigsten Werte im Plan.
            # 1,03/1,05/1,10 sind ungewöhnliche Tür-Breiten → oft Wand-Maße
            # die fälschlich als Breite interpretiert werden.
            if is_tuer_candidate:
                STANDARD_TUER_CM = {60, 70, 80, 90, 100}
                bw_cm = round(bw * 100)
                # Toleranz ±2cm für Rundungs-Mismatch zwischen Plan und Schema
                is_standard = any(abs(bw_cm - sc) <= 2 for sc in STANDARD_TUER_CM)
                if is_standard:
                    score += 35  # starker Bonus für Standard-Tür-Maße
                elif 0.60 <= bw <= 1.50:
                    score += 5   # leicht plausibel
                elif bw > 1.50:
                    score -= 10  # Schiebetür-Bereich
            # Lüftungsfenster (H zwischen 0,40 und 0,80): bevorzuge ~quadratisch
            if 0.40 <= h_m <= 0.80:
                if abs(bw - h_m) < 0.30:
                    score += 25  # nahe an Quadrat → Lüftung
                elif bw > 2 * h_m:
                    score -= 20  # zu langgestreckt für Lüftungsfenster
            if score > best_score:
                best_score = score
                breite_m = bw

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

    # 2b) STUK-ONLY-Konvention (Polierpläne): Türen tragen oft NUR "STUK +2,04" OHNE
    # FPH-Zeile — Parapet 0 ist implizit (empirisch am AP.01-Polierplan: 19 STUK-Spans,
    # 1 FPH-Span → 18 Türen waren unsichtbar). Jeder STUK ohne FPH im Cluster-Radius
    # wird als Tür-Anker behandelt (fph=0, Höhe=STUK über FBOK). Konservativ: nur
    # plausible Tür-Sturzhöhen, Konfidenz niedriger als beim vollen FPH+STUK-Paar.
    OUTDOOR2 = {"terrasse", "loggia", "balkon", "parkplatz", "carport"}
    for stuk in stuk_spans:
        if any(math.hypot(f["cx"] - stuk["cx"], f["cy"] - stuk["cy"]) < max_cluster_pt * 1.5
               for f in fph_spans):
            continue    # gehört zu einem FPH-Cluster (oben behandelt)
        h_m = stuk["value_m"]
        if not (1.7 <= h_m <= 3.2):
            continue    # keine plausible Tür-Sturzhöhe (Standard 2,01–2,20 m)
        b_kand = [
            (math.hypot(b["cx"] - stuk["cx"], b["cy"] - stuk["cy"]), b)
            for b in breite_spans
            if math.hypot(b["cx"] - stuk["cx"], b["cy"] - stuk["cy"]) < max_cluster_pt * 2
        ]
        b_kand.sort()
        breite_m = None
        for _d, b in b_kand:
            if 0.55 <= b["value_m"] <= 2.60:
                breite_m = b["value_m"]
                break
        raum_name = None
        if rooms:
            best, best_d = None, float("inf")
            for r in rooms:
                if r.get("cx") is None or r.get("cy") is None:
                    continue
                nm = (r.get("name") or r.get("bezeichnung") or "").strip()
                if nm and nm.split()[0].lower() in OUTDOOR2:
                    continue
                d = math.hypot(r["cx"] - stuk["cx"], r["cy"] - stuk["cy"])
                if d < best_d and d < max_room_dist_pt:
                    best_d, best = d, r
            if best:
                raum_name = best.get("name") or best.get("bezeichnung")
        oeffnungen.append({
            "typ": "tuer",
            "raum": raum_name,
            "breite_m": breite_m,
            "hoehe_m": round(h_m, 2),
            "flaeche_m2": round((breite_m or 0) * h_m, 3),
            "fph_m": 0.0,
            "stuk_m": h_m,
            "wand_typ": None,
            "tuer_codes": [],
            "cx": stuk["cx"],
            "cy": stuk["cy"],
            "quelle": "text-layer-stuk-only",
            "konfidenz": 0.7 if (breite_m and raum_name) else 0.55,
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

    def _same_fph_stuk(a, b, tol_m=0.05):
        return (abs((a.get("fph_m") or 0) - (b.get("fph_m") or 0)) < tol_m
                and abs((a.get("stuk_m") or 0) - (b.get("stuk_m") or 0)) < tol_m)

    cleaned = []
    used = [False] * len(oeffnungen)
    for i, o in enumerate(oeffnungen):
        if used[i]:
            continue
        keep = o
        for j in range(i + 1, len(oeffnungen)):
            if used[j]:
                continue
            o2 = oeffnungen[j]
            d = math.hypot(o["cx"] - o2["cx"], o["cy"] - o2["cy"])
            # Mehrere Dedup-Kriterien:
            #   - räumlich sehr nah (<15pt) → derselbe Eintrag
            #   - räumlich nah + identische Maße (<40pt) → selbe Öffnung
            #   - räumlich mäßig nah + identisches FPH/STUK (<80pt) →
            #     dieselbe Öffnung von zwei Achsen aus beschriftet
            same_anchor = _same_fph_stuk(o, o2)
            same_size = _same_size(o, o2)
            cur_b = keep.get("breite_m") or 0
            new_b = o2.get("breite_m") or 0
            # Konservativer Dedup:
            #   - d<15pt → IMMER (sehr nah, vermutlich Beschriftungs-Doppel)
            #   - d<40pt + identische Maße → derselbe Eintrag
            #   - d<50pt + gleiches FPH/STUK + ähnliche Breite (Δ<0.5m) →
            #     selbe Tür von zwei Seiten beschriftet
            # NICHT: gleiches FPH/STUK + verschiedene Maße — könnten zwei
            # verschiedene Standard-Türen (z.B. 80cm und Schiebe 2.20m) sein.
            is_dup = (
                d < 15
                or (d < 40 and same_size)
                or (d < 50 and same_anchor and abs(cur_b - new_b) < 0.5)
            )
            if not is_dup:
                continue
            # Bei Tür-Dedup mit unterschiedlichen Breiten: plausiblere Breite
            # (0.60-1.20m) wird bevorzugt; Schiebetür-Maße (>1.50m) bleiben
            # in eigenem Cluster mangels Dedup-Match (s.o.).
            if same_anchor and (keep.get("fph_m") or 0) < 0.15 and abs(cur_b - new_b) < 0.5:
                if 0.60 <= new_b <= 1.20 and not (0.60 <= cur_b <= 1.20):
                    keep = o2
                elif 0.60 <= new_b <= 1.20 and 0.60 <= cur_b <= 1.20 and new_b < cur_b:
                    keep = o2
            else:
                cur_score = (1 if keep.get("breite_m") else 0) + (keep.get("konfidenz") or 0)
                new_score = (1 if o2.get("breite_m") else 0) + (o2.get("konfidenz") or 0)
                if new_score > cur_score:
                    keep = o2
            used[j] = True
        cleaned.append(keep)
        used[i] = True

    return cleaned
