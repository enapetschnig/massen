"""Legende-Parser — liest die Bauteil-Aufbau-Legende byte-exakt aus dem
Text-Layer, so wie ein Bautechniker sie liest.

Österreichische Pläne enthalten typisch eine Bauteil-Legende, die pro
Wand-/Decken-/Boden-Code den Schichtaufbau auflistet:
    AW1   Innenputz 1,5cm / Hochlochziegel 50,0cm / Thermoputz 3,5cm
    IW2   Innenputz 1,5cm / Hochlochziegel 12,0cm / Innenputz 1,5cm
    D1    Stahlbeton 20,0cm / Sauberkeitsschicht 10,0cm / ...

Statt Wandstärken/Deckendicke zu RATEN (85/10/5%-Verteilung, Default 25cm),
lesen wir die echten Werte aus der Legende — generalisiert auf jeden
Architekten, weil jeder Plan seine eigenen Codes selbst definiert.

Liefert:
  {
    "wand_typen": {"AW1": {"dicke_cm": 50.0, "material": "Hochlochziegel", "art": "aussen"}, ...},
    "wand_counts": {"AW1": 10, "AW2": 3, "IW1": 3, "IW2": 9},   # Vorkommen im Plan
    "decke_cm": 20.0, "bodenplatte_cm": 20.0, "sauberkeitsschicht_cm": 10.0,
    "estrich_cm": 7.0,
    "quelle": "text-legende", "konfidenz": 0.95
  }
"""
from __future__ import annotations
import re

# Tragende/strukturelle Wand-Materialien (deren Dicke = Rohbau-Wandstärke).
# Breit gefasst für verschiedene Architekten/Hersteller (AT-Markt).
STRUKTUR_MATERIAL = re.compile(
    r"(hochlochziegel|hlz|ziegel|porotherm|poroton|planziegel|porenbeton|"
    r"stahlbeton|stb\b|beton|ytong|kalksandstein|\bks\b|vollziegel|"
    r"leichtbeton|liapor|liapor|mauerwerk)", re.I)
# Eine Schicht-Zeile: "<Material> ... <Wert> cm" (auch mm-Toleranz)
SCHICHT_RX = re.compile(r"([A-Za-zÄÖÜäöüß\-]+).*?(\d+(?:[,.]\d+)?)\s*cm", re.I)
# Reine Dicken-Angabe ohne Material ("38,0 cm" / "38 cm") — getrennte Layouts
THICK_RX = re.compile(r"(\d+(?:[,.]\d+)?)\s*cm\b", re.I)
# Bauteil-Codes — ÖNORM-Standard (Außen/Innen/Trenn/Brand-Wand), toleranter
# Separator (AW1 / AW 1 / AW-1). Bare "W" bewusst NICHT (zu viele Fehltreffer).
WAND_CODE_RX = re.compile(r"^(AW|IW|TW|BW)\s*[-_.]?\s*(\d+)\b", re.I)
DECKE_CODE_RX = re.compile(r"^D\s*[-_.]?\s*(\d+)\b", re.I)
BODEN_CODE_RX = re.compile(r"^B\s*[-_.]?\s*(\d+)\b", re.I)
WAND_REF_RX = re.compile(r"^(AW|IW|TW|BW)\s*[-_.]?\s*(\d+)\b", re.I)


def _num(s):
    try:
        return float(s.replace(",", "."))
    except (ValueError, AttributeError):
        return None


def _near(spans, anchor, dx=210, dy=58):
    """Spans im Umkreis des Anchor-Spans (Legende ist ein vertikaler Schicht-Stack)."""
    ax, ay = anchor["cx"], anchor["cy"]
    return [s for s in spans
            if s is not anchor and abs(s["cx"] - ax) <= dx and abs(s["cy"] - ay) <= dy]


def _dist(o, anchor):
    return ((o["cx"] - anchor["cx"]) ** 2 + ((o["cy"] - anchor["cy"]) * 1.6) ** 2) ** 0.5


def _struktur_dicke_near(spans, anchor, material_rx, lo, hi):
    """Findet die Schicht-Dicke eines Struktur-Materials nahe einem Code-Anchor —
    robust gegen BEIDE Legende-Layouts: Material+Dicke im selben Span
    ("Hochlochziegel 50,0 cm") ODER getrennt ("Porotherm" | "38,0 cm").
    Liefert (dicke_cm, material) oder (None, None)."""
    cluster = _near(spans, anchor, dx=240, dy=40)
    best_d, best_mat, best_dist = None, None, 1e9
    # (A) kombiniert
    for o in cluster:
        if not material_rx.search(o["text"]):
            continue
        sm = SCHICHT_RX.search(o["text"])
        if sm:
            d = _num(sm.group(2))
            if d and lo <= d <= hi and _dist(o, anchor) < best_dist:
                best_dist, best_d, best_mat = _dist(o, anchor), d, sm.group(1)
    if best_d is not None:
        return best_d, best_mat
    # (B) getrennt: Material-Span vorhanden, Dicke in separatem Span
    mat_span = next((o for o in cluster if material_rx.search(o["text"])), None)
    if mat_span:
        for o in cluster:
            if material_rx.search(o["text"]):
                continue
            tm = THICK_RX.search(o["text"])
            if tm:
                d = _num(tm.group(1))
                if d and lo <= d <= hi and _dist(o, anchor) < best_dist:
                    best_dist, best_d = _dist(o, anchor), d
        if best_d is not None:
            return best_d, mat_span["text"].strip()
    return None, None


def parse_legende(spans: list) -> dict:
    """spans: [{"text","cx","cy","size"}] aus dem PDF-Text-Layer."""
    result = {
        "wand_typen": {}, "wand_counts": {},
        "decke_cm": None, "bodenplatte_cm": None,
        "sauberkeitsschicht_cm": None, "estrich_cm": None,
        # Boden-Aufbau-Schichten (byte-exakt aus Legende, wie ein Mensch liest)
        "belag_cm": None, "schuettung_cm": None, "trittschall_cm": None,
        # Infrastruktur-Objekte aus dem Plan-Text gezählt (Position-dedupliziert)
        "kamin_anzahl": 0, "sickerschacht_anzahl": 0,
        "dach_typ": None, "dach_indizien": [],
        "quelle": "text-legende", "konfidenz": 0.0,
    }
    if not spans:
        return result

    # Dachtyp aus dem Decken-/Dach-Aufbau ableiten (wie ein Mensch: sieht
    # "Sarnafil/Abdichtung 2lagig/Bitumen-Dachbahn" → Flachdach → Attika;
    # "Ziegel/Lattung/Sparren/Konterlattung" → Steildach → keine Attika).
    FLACH = re.compile(r"sarnafil|abdichtung|bitumen|dachbahn|kiesschüttung|gefälled|fpo|epdm|flachdach|attika", re.I)
    STEIL = re.compile(r"\b(dachziegel|biberschwanz|sparren|lattung|konterlattung|first|steildach|dachstuhl)\b", re.I)
    flach_score = steil_score = 0
    for s in spans:
        t = s["text"]
        if FLACH.search(t):
            flach_score += 1; result["dach_indizien"].append(t.strip()[:40])
        if STEIL.search(t):
            steil_score += 1
    if flach_score and flach_score >= steil_score:
        result["dach_typ"] = "flach"
    elif steil_score:
        result["dach_typ"] = "steil"

    def _norm_code(pfx, nr):
        return f"{pfx.upper()}{nr}"

    # 1) Wand-Codes in der LEGENDE auflösen (Code-Anchor → Struktur-Dicke daneben)
    for s in spans:
        t = s["text"].strip()
        m = WAND_CODE_RX.match(t)
        if not m:
            continue
        # Nur Legende-Anchors: entweder reiner Code ("AW1"/"AW 1") oder mit
        # Zusatz "tragend/nicht tragend" (typisch Legende). An den Wänden im
        # Grundriss steht meist nur "AW 1" allein — die zählen wir separat.
        rest = t[m.end():].strip().lower()
        ist_legende_anchor = (rest == "" or "tragend" in rest)
        if not ist_legende_anchor:
            continue
        code = _norm_code(m.group(1), m.group(2))
        if code in result["wand_typen"]:
            continue
        # Struktur-Dicke (>=5cm schließt Putz/Dämmung aus), kombiniert ODER getrennt
        best_dicke, best_mat = _struktur_dicke_near(spans, s, STRUKTUR_MATERIAL, 5, 60)
        if best_dicke:
            art = "aussen" if m.group(1).upper().startswith("AW") else "innen"
            result["wand_typen"][code] = {
                "dicke_cm": best_dicke, "material": best_mat, "art": art,
            }

    STB_RX = re.compile(r"stahlbeton|stb\b", re.I)

    # 2) Decke (D-Code) → Stahlbeton-Dicke (kombiniert ODER getrennt)
    for s in spans:
        if not DECKE_CODE_RX.match(s["text"].strip()):
            continue
        d, _mat = _struktur_dicke_near(spans, s, STB_RX, 12, 40)
        if d:
            result["decke_cm"] = d
            break

    # 3a) Bodenplatte aus dem B-Code-Block (Stahlbeton, kombiniert ODER getrennt)
    for s in spans:
        if not BODEN_CODE_RX.match(s["text"].strip()):
            continue
        d, _mat = _struktur_dicke_near(spans, s, STB_RX, 15, 40)
        if d:
            result["bodenplatte_cm"] = d
            break

    # 3b) Sauberkeitsschicht / Estrich — global aus Legende (eindeutige Begriffe)
    for s in spans:
        low = s["text"].lower()
        sm = SCHICHT_RX.search(s["text"])
        if not sm:
            continue
        d = _num(sm.group(2))
        if d is None:
            continue
        if "sauberkeit" in low and result["sauberkeitsschicht_cm"] is None and 3 <= d <= 20:
            result["sauberkeitsschicht_cm"] = d
        elif "estrich" in low and result["estrich_cm"] is None and 3 <= d <= 12:
            result["estrich_cm"] = d
        elif ("belag" in low or "steinzeug" in low or "parkett" in low or "fliesen" in low) \
                and result["belag_cm"] is None and 0.5 <= d <= 5:
            result["belag_cm"] = d
        elif ("schüttung" in low or "schuettung" in low) and result["schuettung_cm"] is None and 2 <= d <= 20:
            result["schuettung_cm"] = d
        elif "trittschall" in low and result["trittschall_cm"] is None and 1 <= d <= 8:
            result["trittschall_cm"] = d

    # 3c) Infrastruktur-Objekte zählen (Position-dedupliziert — dasselbe Objekt
    # wird oft mehrfach beschriftet). Wie ein Mensch: zählt Kamine/Schächte.
    # Annotations-Wörter die KEIN echtes Objekt markieren (Abstands-/Schutz-Hinweise)
    ANNO = re.compile(r"radius|abstand|schutz|mindest|brand|\d+\s*m\b", re.I)
    def _zaehle_objekt(keyword, dedup_pt=120):
        positionen = []
        for s in spans:
            tl = s["text"].lower()
            if keyword not in tl or ANNO.search(s["text"]):
                continue
            if not any(abs(s["cx"]-px) < dedup_pt and abs(s["cy"]-py) < dedup_pt for px, py in positionen):
                positionen.append((s["cx"], s["cy"]))
        return len(positionen)
    # Kamin: EFH hat i.d.R. genau einen — Erwähnung (auch als Abstands-
    # Annotation "10m Radius Kamin") beweist Vorhandensein → mind. 1.
    kamin_gefiltert = _zaehle_objekt("kamin")
    kamin_erwaehnt = any("kamin" in s["text"].lower() for s in spans)
    result["kamin_anzahl"] = kamin_gefiltert or (1 if kamin_erwaehnt else 0)
    result["sickerschacht_anzahl"] = _zaehle_objekt("sickerschacht")

    # 4) Wand-Code-VORKOMMEN im Grundriss zählen (Verteilung statt Annahme)
    for s in spans:
        m = WAND_REF_RX.match(s["text"].strip())
        if m:
            code = _norm_code(m.group(1), m.group(2))
            result["wand_counts"][code] = result["wand_counts"].get(code, 0) + 1

    # Konfidenz: wie viel der Legende konnten wir lesen?
    gelesen = (len(result["wand_typen"]) + bool(result["decke_cm"]) +
               bool(result["bodenplatte_cm"]) + bool(result["sauberkeitsschicht_cm"]))
    result["konfidenz"] = min(0.97, 0.55 + 0.1 * gelesen) if result["wand_typen"] else 0.0
    return result


def baudaten_aus_legende(leg: dict) -> dict:
    """Übersetzt die Legende in Baudaten-Felder (für massen_logic / materialliste).
    Liefert nur Felder die WIRKLICH aus der Legende gelesen wurden — die
    überschreiben dann Vision-Schätzungen + Defaults (Legende ist byte-exakt)."""
    if not leg or not leg.get("wand_typen"):
        return {}
    bd = {}
    wt = leg["wand_typen"]
    # Außenwand = dickste AW; Innenwand tragend = dickste IW; n.tr. = dünnste IW
    aw = [v["dicke_cm"] for k, v in wt.items() if v["art"] == "aussen"]
    iw = [v["dicke_cm"] for k, v in wt.items() if v["art"] == "innen"]
    if aw:
        bd["aussenwand_cm"] = max(aw)
    if iw:
        bd["innenwand_tragend_cm"] = max(iw)
        bd["innenwand_nichttragend_cm"] = min(iw)
    if leg.get("decke_cm"):
        bd["decke_cm"] = leg["decke_cm"]
    if leg.get("bodenplatte_cm"):
        bd["bodenplatte_cm"] = leg["bodenplatte_cm"]
    if bd:
        bd["konfidenz"] = leg.get("konfidenz", 0.9)
        bd["_quelle"] = "legende"
    return bd


def wand_verteilung_aus_counts(leg: dict) -> dict:
    """Leitet die Wandstärken-Verteilung (%) aus den tatsächlichen Code-
    Vorkommen + Legende-Dicken ab — ersetzt die hartcodierten 85/10/5%.

    Liefert {aussen: {dicke_cm: anteil_pct}, innen: {dicke_cm: anteil_pct}}.
    Anteil = (Vorkommen dieses Codes) / (Σ Vorkommen der Kategorie)."""
    wt = leg.get("wand_typen") or {}
    counts = leg.get("wand_counts") or {}
    if not wt or not counts:
        return {}
    aussen, innen = {}, {}
    sum_a = sum(counts.get(k, 0) for k, v in wt.items() if v["art"] == "aussen")
    sum_i = sum(counts.get(k, 0) for k, v in wt.items() if v["art"] == "innen")
    for code, v in wt.items():
        c = counts.get(code, 0)
        if v["art"] == "aussen" and sum_a:
            aussen[v["dicke_cm"]] = aussen.get(v["dicke_cm"], 0) + c / sum_a * 100
        elif v["art"] == "innen" and sum_i:
            innen[v["dicke_cm"]] = innen.get(v["dicke_cm"], 0) + c / sum_i * 100
    return {"aussen": aussen, "innen": innen}
