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


# MENGEN-Einheiten (stark) — eine Zeile/Spalte mit GENAU diesen Einheiten ist eine
# echte Menge. Bewusst OHNE bloßes "m"/"mm"/"cm": die stecken in Produktnamen
# ("Noppenfolie 1m", "XPS 140mm", "Mauersperrbahn 25cm") und sind KEINE Mengen.
STARK_EINHEIT = (r"(?:m²|m2|m³|m3|lfm|stk|dtk|kg|paletten?|rollen?|bund|kanister|"
                 r"s[aä]cke?|kartons?|pakete?|pack|stück)")
_PURE_MENGE_RX = re.compile(r"^([\d][\d.,]*)\s*" + STARK_EINHEIT + r"\.?$", re.I)
_INLINE_MENGE_RX = re.compile(r"(.+?)\s+([\d][\d.,]*)\s*" + STARK_EINHEIT + r"\.?\s*$", re.I)
_EINHEIT_RX = re.compile(STARK_EINHEIT, re.I)


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
    """Parst eine Polier-Soll-Liste → Liste von {bezeichnung, menge, einheit}.

    Beherrscht DREI reale Formate robust:
      1. CSV/TSV  ('Bodenplatte Beton;48,5;m³')
      2. einzeilig ('Decke Beton ......... 1.234,56 m³')
      3. ALTERNIEREND — das übliche PDF-Layout, bei dem Bezeichnung und Menge in
         getrennten Zeilen extrahiert werden:
             'HLZ 50cm H.I. Plan'
             '48 Paletten'
         Hier wird die Bezeichnung gepuffert, bis eine reine Mengen-Zeile folgt.

    Schlüssel zur Unterscheidung: eine Menge endet auf einer STARKEN Einheit
    (Stk/Palette/m²/m³/lfm/…), NICHT auf bloßem m/mm/cm — sonst würde
    'Noppenfolie 1m' fälschlich als Menge 1 gelesen. Zeilen ohne erkennbare Menge
    werden übersprungen (bzw. als Bezeichnung gepuffert)."""
    if not text:
        return []
    positionen = []
    puffer = []   # gesammelte Bezeichnungs-Zeilen, die auf ihre Menge warten

    def _einheit(s):
        m = _EINHEIT_RX.search(s)
        return m.group(0).lower() if m else ""

    for raw in str(text).splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.endswith(":"):          # Abschnitts-Überschrift ("Frostschürze:")
            puffer = []
            continue
        # 1) CSV / TSV
        teile = None
        for sep in (";", "\t", "|"):
            if sep in line:
                teile = [t.strip() for t in line.split(sep)]
                break
        if teile and len(teile) >= 2:
            menge, einheit, bez = None, "", []
            for t in teile:
                tt = t.strip()
                if menge is None and re.fullmatch(r"[\d.][\d.,]*\s*" + STARK_EINHEIT + r"?\.?", tt, re.I):
                    menge = _to_float(tt)
                    einheit = _einheit(tt)
                elif re.fullmatch(STARK_EINHEIT + r"\.?", tt, re.I) and not einheit:
                    einheit = tt.rstrip(".").lower()   # reine Einheiten-Spalte
                else:
                    bez.append(t)
            if menge is not None:
                positionen.append({"bezeichnung": " ".join([b for b in bez if b]).strip(),
                                   "menge": menge, "einheit": einheit})
                puffer = []
                continue
        # 2) reine Mengen-Zeile ('48 Paletten') → schließt die gepufferte Bezeichnung ab
        mq = _PURE_MENGE_RX.match(line)
        if mq:
            menge = _to_float(mq.group(1))
            if puffer and menge is not None:
                positionen.append({"bezeichnung": " ".join(puffer).strip(),
                                   "menge": menge, "einheit": _einheit(line)})
            puffer = []
            continue
        # 3) einzeilig ('Bezeichnung … 123 m²' mit STARKER Einheit am Ende)
        mi = _INLINE_MENGE_RX.match(line)
        if mi:
            menge = _to_float(mi.group(2))
            if menge is not None:
                positionen.append({"bezeichnung": mi.group(1).strip(),
                                   "menge": menge, "einheit": _einheit(line[mi.start(2):])})
                puffer = []
                continue
        # sonst: Bezeichnungs-Zeile → puffern (alternierendes Layout)
        puffer.append(line)
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


def hlz_verteilung_aus_soll(soll_positions):
    """Lernt die Wandstärken-VERTEILUNG aus den HLZ-Paletten einer Soll-Liste —
    die eine Größe, die NICHT byte-exakt aus dem Plan lesbar ist (sie steckt in
    der Schraffur). Aus 'HLZ 50cm … 48 Paletten' etc. die Anteile ableiten:
    ≥38cm = Außenwand-Bucket, ≤25cm = Innenwand-Bucket (25cm gilt als innere
    tragende Wand — die häufige Konvention). Liefert {wand_anteil_*: pct} oder None.
    Anders als die Ratio-Faktoren ist DAS eine DIREKTE Messung der echten Firma-
    Bauweise → schon EINE Soll-Liste ist aussagekräftig (Median über mehrere stabilisiert)."""
    pal = {}
    for p in (soll_positions or []):
        bez = (p.get("bezeichnung") or "").lower()
        einh = (p.get("einheit") or "").lower()
        m = re.search(r"hlz\s*(\d{2})\s*cm", bez)
        if m and ("palette" in einh or "palette" in bez or "pal" in einh):
            d = int(m.group(1))
            menge = _to_float(p.get("menge")) or 0
            if menge > 0:
                pal[d] = pal.get(d, 0) + menge
    if not pal:
        return None
    out = {}
    aussen = {d: pal[d] for d in (50, 38) if d in pal}
    innen = {d: pal[d] for d in (25, 20, 12) if d in pal}
    sa = sum(aussen.values())
    si = sum(innen.values())
    if sa > 0:
        out["wand_anteil_50cm"] = round(aussen.get(50, 0) / sa * 100, 1)
        out["wand_anteil_38cm"] = round(aussen.get(38, 0) / sa * 100, 1)
        out["wand_anteil_25cm_aussen"] = 0.0
    if si > 0:
        out["wand_anteil_25cm_innen"] = round(innen.get(25, 0) / si * 100, 1)
        out["wand_anteil_20cm"] = round(innen.get(20, 0) / si * 100, 1)
        out["wand_anteil_12cm"] = round(innen.get(12, 0) / si * 100, 1)
    return out or None


def aggregiere_verteilungen(verteilungen):
    """Median je Anteil-Schlüssel über mehrere Soll-Listen-Verteilungen → stabile
    firmenspezifische Wandverteilung. Eine Liste reicht (direkte Messung), mehrere
    stabilisieren. Liefert {wand_anteil_*: pct} (leere/None-Einträge ignoriert)."""
    keys = {}
    for v in (verteilungen or []):
        for k, val in (v or {}).items():
            if val is not None:
                keys.setdefault(k, []).append(float(val))
    return {k: round(_median(vals), 1) for k, vals in keys.items() if vals}


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
