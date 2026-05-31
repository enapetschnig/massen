"""Selbst-Kalibrierung gegen hochgeladene Polier-Soll-Listen (der MOAT).

Ein Baubetrieb lädt seine echte manuelle Materialliste (Soll) hoch. Wir vergleichen
Position für Position mit unserer Berechnung (Ist) und leiten firmenspezifische
Korrektur-Faktoren ab — aber NUR mit harten Überanpassungs-Guards, denn eine einzige
falsche Liste darf NIEMALS alle künftigen Pläne verfälschen.

REINE Funktionen (kein Supabase, kein I/O) → vollständig unit-testbar. Die Persistenz
(kalibrierungen/soll_listen) und das Einweben in build_materialliste passieren im
Endpoint. Auflösungs-Reihenfolge der Faktoren: USER-Override > Firma > Global > Default.

GUARDS (nicht verhandelbar):
- min_belege >= 2: ein Faktor wird erst gelernt, wenn ihn ≥2 unabhängige Soll-Listen
  stützen (nie aus einer einzelnen Liste).
- IQR-Ausreißer-Filter über die Belege je Faktor.
- Ratio je Liste auf [0.6, 1.6] geklemmt (eine Liste verschiebt einen Faktor max ±60%).
- Gelernter Faktor absolut auf [0.5, 2.5] geklemmt.
- Nur PARAMETER (Aufschläge), nie byte-exakte Flächen/Maße.
- Generalisiert: keine Plan-/Firmen-Hardcodes; jede Position wird per Schlüsselwort gematcht.
"""
import re

RATIO_MIN, RATIO_MAX = 0.6, 1.6        # eine Liste verschiebt max ±60%
FAKTOR_MIN, FAKTOR_MAX = 0.5, 2.5      # absoluter Sanity-Bereich gelernter Faktoren
MIN_BELEGE = 2                          # nie aus einer einzigen Liste lernen

# Welche Material-Position kalibriert welchen PARAMETER. Bewusst klein gehalten
# (high-signal, klar 1:1-zuordenbar) — lieber wenige robuste Faktoren als viele
# wackelige. Matcher = Schlüsselwörter (lowercase) in Bauteil bzw. Material.
FAKTOR_REGELN = [
    {"faktor": "bodenplatte_aufschlag", "default": 1.15,
     "ist": {"bauteil": "bodenplatte", "material": ("ekv", "beton", "c25")},
     "soll": ("bodenplatte", "fundamentplatte", "ekv")},
    {"faktor": "decke_aufschlag", "default": 1.10,
     "ist": {"bauteil": "decke", "material": ("beton", "c25", "schaltafel")},
     "soll": ("decke", "geschossdecke")},
    {"faktor": "frostgraben_aufschlag", "default": 1.15,
     "ist": {"bauteil": "frostschürze", "material": ("xps", "beton", "steckeisen")},
     "soll": ("frostschürze", "frostschuerze", "sockel")},
    {"faktor": "aussenumfang_aufschlag", "default": 1.55,
     "ist": {"bauteil": "mauerwerk", "material": ("hlz 50", "hlz50", "aussenwand", "außenwand")},
     "soll": ("hlz 50", "hlz50", "außenwand", "aussenwand", "mauerwerk")},
    {"faktor": "ekv_decke_aufschlag", "default": 1.35,
     "ist": {"bauteil": "decke", "material": ("ekv", "abdichtung", "bitumen")},
     "soll": ("dachabdichtung", "ekv-dach", "abdichtung")},
]


def _to_float(s):
    """Deutsche Dezimalzahl ('1.234,56' / '123,4' / '123.4') → float|None."""
    if s is None:
        return None
    if isinstance(s, (int, float)):
        return float(s)
    t = str(s).strip()
    t = re.sub(r"[^\d.,\-]", "", t)
    if not t:
        return None
    if "," in t and "." in t:          # 1.234,56 → 1234.56
        t = t.replace(".", "").replace(",", ".")
    elif "," in t:                      # 123,4 → 123.4
        t = t.replace(",", ".")
    try:
        return float(t)
    except ValueError:
        return None


def parse_soll_liste(text):
    """Parst eine Polier-Soll-Liste (CSV ';'/',' ODER Freitext) → Liste von
    {bezeichnung, menge, einheit}. Robust gegen Spalten-Reihenfolge und deutsche
    Dezimalkommas. Zeilen ohne erkennbare Menge werden übersprungen."""
    if not text:
        return []
    positionen = []
    for raw in str(text).splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        # CSV?
        for sep in (";", "\t", "|"):
            if sep in line:
                teile = [t.strip() for t in line.split(sep)]
                break
        else:
            teile = None
        if teile and len(teile) >= 2:
            # Menge = erste Spalte, die GANZ eine Zahl (+ optionale Einheit) ist —
            # nicht bloß "enthält eine Ziffer" (sonst frisst "C25/30" die Menge).
            _unit = r"(m²|m2|m³|m3|lfm|stk|kg|t|palette|rolle|m)"
            menge, einheit, bez = None, "", []
            for t in teile:
                tt = t.strip()
                if menge is None and re.fullmatch(r"[\d.][\d.,]*\s*" + _unit + r"?", tt, re.I):
                    menge = _to_float(tt)
                    mu = re.search(_unit, tt, re.I)
                    if mu:
                        einheit = mu.group(1)
                elif re.fullmatch(_unit, tt, re.I) and not einheit:
                    einheit = tt   # reine Einheiten-Spalte
                else:
                    bez.append(t)
            if menge is not None:
                positionen.append({"bezeichnung": " ".join([b for b in bez if b]).strip(),
                                   "menge": menge, "einheit": einheit})
                continue
        # Freitext: "Bezeichnung ............ 123,45 m²"
        m = re.search(r"(.+?)\s+([\d.,]+)\s*(m²|m2|m³|m3|lfm|stk|kg|t|palette|rolle|m)?\s*$", line, re.I)
        if m:
            menge = _to_float(m.group(2))
            if menge is not None:
                positionen.append({"bezeichnung": m.group(1).strip(),
                                   "menge": menge, "einheit": (m.group(3) or "").lower()})
    return positionen


def _summe_ist(ist_bauteile, regel):
    """Σ Menge aller Ist-Positionen, die zu dieser Regel passen."""
    bt_key = regel["ist"]["bauteil"]
    mat_keys = regel["ist"]["material"]
    total = 0.0
    found = False
    for bauteil, positionen in (ist_bauteile or {}).items():
        if bt_key not in bauteil.lower():
            continue
        for p in positionen:
            mat = (p.get("material") or "").lower()
            if any(k in mat for k in mat_keys):
                m = _to_float(p.get("menge"))
                if m and m > 0:
                    total += m
                    found = True
    return total if found else None


def _summe_soll(soll_positions, regel):
    """Σ Menge aller Soll-Positionen, deren Bezeichnung zur Regel passt."""
    keys = regel["soll"]
    total = 0.0
    found = False
    for p in (soll_positions or []):
        bez = (p.get("bezeichnung") or "").lower()
        if any(k in bez for k in keys):
            m = _to_float(p.get("menge"))
            if m and m > 0:
                total += m
                found = True
    return total if found else None


def belege_aus_vergleich(ist_bauteile, soll_positions):
    """Vergleicht Ist (Materiallisten-bauteile, mit DEFAULT-Faktoren gerechnet) gegen
    die Soll-Liste und liefert je Faktor EINEN Beleg: {faktor, ratio, ist, soll}.
    ratio = soll/ist, geklemmt auf [RATIO_MIN, RATIO_MAX]. Nur Faktoren, für die
    BEIDE Seiten eine Menge liefern. Das ist die Evidenz EINER Liste — gelernt wird
    erst über mehrere (siehe lerne_faktoren)."""
    belege = []
    for regel in FAKTOR_REGELN:
        ist = _summe_ist(ist_bauteile, regel)
        soll = _summe_soll(soll_positions, regel)
        if not ist or not soll or ist <= 0:
            continue
        ratio = max(RATIO_MIN, min(RATIO_MAX, soll / ist))
        belege.append({"faktor": regel["faktor"], "ratio": round(ratio, 4),
                       "ist": round(ist, 2), "soll": round(soll, 2)})
    return belege


def _median(xs):
    s = sorted(xs)
    n = len(s)
    if n == 0:
        return None
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2.0


def _iqr_filter(xs):
    """Verwirft Ausreißer außerhalb [Q1-1.5·IQR, Q3+1.5·IQR]. <4 Werte → unverändert."""
    s = sorted(xs)
    if len(s) < 4:
        return s
    q1 = s[len(s) // 4]
    q3 = s[(3 * len(s)) // 4]
    iqr = q3 - q1
    lo, hi = q1 - 1.5 * iqr, q3 + 1.5 * iqr
    return [x for x in s if lo <= x <= hi] or s


def lerne_faktoren(ratios_je_faktor, min_belege=MIN_BELEGE):
    """Aus den gesammelten Belegen (ratios je Faktor, über MEHRERE Soll-Listen)
    die gelernten Faktoren bilden. GUARDS: ≥min_belege, IQR-Filter, Median,
    absolute Klemmung. Liefert {faktor: {wert, n_belege, ratio_median}} — NUR
    Faktoren, die die Schwelle erreichen (sonst greifen die Defaults)."""
    regel_default = {r["faktor"]: r["default"] for r in FAKTOR_REGELN}
    out = {}
    for faktor, ratios in (ratios_je_faktor or {}).items():
        ratios = [float(x) for x in ratios if x is not None]
        if len(ratios) < min_belege:
            continue
        gefiltert = _iqr_filter(ratios)
        if len(gefiltert) < min_belege:
            continue
        rmed = _median(gefiltert)
        default = regel_default.get(faktor, 1.0)
        wert = max(FAKTOR_MIN, min(FAKTOR_MAX, round(default * rmed, 4)))
        out[faktor] = {"wert": wert, "n_belege": len(gefiltert),
                       "ratio_median": round(rmed, 4), "default": default}
    return out


def resolve_kalibrierung(firma_faktoren, global_faktoren):
    """Mischt globale Basis (e-power) + firmenspezifische Kalibrierung zu EINEM
    {faktor: wert}-Dict für build_materialliste. FIRMA schlägt GLOBAL (die eigene
    Bauweise ist genauer als die allgemeine Basis). Erwartet je {faktor: {wert,...}}
    ODER {faktor: wert}; liefert flaches {faktor: wert}."""
    def _flat(d):
        out = {}
        for k, v in (d or {}).items():
            out[k] = v.get("wert") if isinstance(v, dict) else v
        return out
    merged = {**_flat(global_faktoren), **_flat(firma_faktoren)}
    return {k: float(v) for k, v in merged.items() if v is not None}
