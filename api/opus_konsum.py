"""Opus-Bauingenieur-Konsum + Kreuz-Kontrolle (Vier-Augen-Prinzip).

Reine, testbare Funktionen, die das ganzheitliche Opus-4.8-Urteil in die
Massenermittlung einweben — IMMER additiv, IMMER beleg-/konfidenz-gegated,
NIEMALS überschreibt Opus eine byte-exakte oder Schnitt-/Legende-Quelle.

Leitprinzip (User): "sie sollten sich gegenseitig auch kontrollieren und nichts
raten." → Opus ist eine DRITTE unabhängige Quelle im Doppelcheck. Es bestätigt
oder widerspricht, es ersetzt nie. Bei zu geringer Konfidenz wird der Wert
verworfen statt geraten.
"""

KONF_MIN = 0.6   # Feld-Gate: unter dieser Konfidenz wird ein Opus-Wert verworfen


def _f(v, default=0.0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def opus_usable(best_opus):
    """True, wenn das Opus-Urteil überhaupt konsumiert werden darf."""
    return bool(best_opus) and not best_opus.get("unsicherheit_flag")


def mauerwerk_zusatz(best_opus, aussenumfang_m):
    """Geschlossene GEMAUERTE überdachte Bereiche (z.B. eine als 'Parkplatz'
    beschriftete, im Schnitt aber gemauerte GARAGE) → ihr Wand-Umfang gehört
    auf die Mauerwerks-Hülle (Linie A).

    Returns (zusatz_m, [namen]). Plausi: je Bereich ≤ 60% der Hülle.
    """
    if not opus_usable(best_opus):
        return 0.0, []
    zusatz, namen = 0.0, []
    for b in (best_opus.get("ueberdachte_bereiche") or []):
        if b.get("geschlossen_typ") != "gemauert":
            continue
        if _f(b.get("konfidenz")) < KONF_MIN:
            continue
        mz = _f(b.get("mauerwerk_umfang_zusatz_m"))
        if 0 < mz <= aussenumfang_m * 0.6:
            zusatz += mz
            namen.append(b.get("name"))
    return round(zusatz, 2), namen


def slab_zusatz(best_opus, aussenumfang_m):
    """Bereiche, die laut Bauingenieur auf der DURCHGEHENDEN Bodenplatte stehen
    → ihr Platten-Rand-Zusatz als gegroundeter Slab-Kandidat (Linie B).

    Returns opus_slab (= aussenumfang_m + Σ zusatz) oder None.
    """
    if not opus_usable(best_opus):
        return None
    zsum = 0.0
    for b in (best_opus.get("ueberdachte_bereiche") or []):
        if not b.get("auf_slab"):
            continue
        if _f(b.get("konfidenz")) < KONF_MIN:
            continue
        fz = _f(b.get("fundament_umfang_zusatz_m"))
        if 0 < fz <= aussenumfang_m * 0.6:
            zsum += fz
    if zsum <= 0:
        return None
    return round(aussenumfang_m + zsum, 2)


def hoehe_rohbau(best_opus):
    """Rohbau-Geschoss-Höhe aus dem Schnitt (FBOK→Rohdecke-OK), konf-gegated.
    Returns float in [2.2, 4.5] oder None."""
    if not opus_usable(best_opus):
        return None
    h = best_opus.get("hoehe") or {}
    if _f(h.get("konfidenz")) < KONF_MIN:
        return None
    r = _f(h.get("rohbau_m"), None) if h.get("rohbau_m") is not None else None
    if r and 2.2 <= r <= 4.5:
        return round(r, 2)
    return None


def dach_typ(best_opus):
    """Dachtyp ('flach'/'pult'/'sattel'/'walm'), konf-gegated. Returns str|None."""
    if not opus_usable(best_opus):
        return None
    d = best_opus.get("dach") or {}
    if _f(d.get("konfidenz")) < KONF_MIN:
        return None
    return d.get("dach_typ") or None


def saeulen(best_opus):
    """Anzahl freistehender tragender Stützen (0/None wenn keine)."""
    if not opus_usable(best_opus):
        return 0
    try:
        return int(best_opus.get("saeulen_anzahl") or 0)
    except (TypeError, ValueError):
        return 0


# ── ECHTE Unabhängigkeit: zwei Leser desselben Plan-BILDES (Schnitt-Vision +
# Opus) sind NICHT unabhängig — sie teilen dieselbe Fehlerquelle. Nur Quellen
# mit QUALITATIV unterschiedlicher Methode dürfen sich gegenseitig „bestätigen":
#   "text"   = byte-exakter PDF-Text-Layer (Raumhöhen, Legende-Maße)
#   "vision" = ein Bild-Lese-Pass (Schnitt-Vision ODER Opus — gleiche Methode!)
# >=2 UNTERSCHIEDLICHE Typen einig → "bestätigt" (verdiente hohe Konfidenz).
# Mehrere einig, aber alle gleicher Typ → "verstaerkt" (nur Redundanz, gedeckelt).
def _quellen_struktur(vv):
    """vv: Liste (name, wert, typ). Liefert (quellen_payload, typen_set)."""
    typen = set(t for _, _, t in vv)
    payload = [{"quelle": q, "wert": w, "typ": t} for q, w, t in vv]
    return payload, typen


def _norm_quellen(quellen):
    """Akzeptiert (name, wert) ODER (name, wert, typ); fehlt typ → 'vision'."""
    out = []
    for item in quellen:
        if len(item) == 3:
            out.append((item[0], item[1], item[2]))
        else:
            out.append((item[0], item[1], "vision"))
    return out


def doppelcheck_num(label, key, einheit, quellen, tol):
    """Kreuz-Kontrolle EINER numerischen Größe über mehrere Quellen.

    quellen: (name, wert) oder (name, wert, typ). Werte nicht-numerisch/<=0 raus.
    Ab ZWEI gültigen Quellen ein Eintrag. status:
      - "widerspruch"  wenn nicht alle innerhalb tol zum Median liegen
      - "bestätigt"    wenn einig UND >=2 unterschiedliche Quellen-TYPEN (Text×Vision)
      - "verstaerkt"   wenn einig, aber alle vom selben Typ (nur Redundanz)
    Returns dict|None. So wird Konfidenz VERDIENT, nicht durch Schein-Unabhängigkeit.
    """
    vv = []
    for q, v, t in _norm_quellen(quellen):
        try:
            fv = float(v)
        except (TypeError, ValueError):
            continue
        if fv > 0:
            vv.append((q, round(fv, 2), t))
    if len(vv) < 2:
        return None
    med = sorted(v for _, v, _ in vv)[len(vv) // 2]
    agree = all(abs(v - med) <= tol for _, v, _ in vv)
    payload, typen = _quellen_struktur(vv)
    if not agree:
        status = "widerspruch"
    elif len(typen) >= 2:
        status = "bestätigt"
    else:
        status = "verstaerkt"
    return {
        "groesse": label, "key": key, "einheit": einheit, "wert": med,
        "quellen": payload, "typen_n": len(typen), "unabhaengig": len(typen) >= 2,
        "status": status,
    }


def doppelcheck_kat(label, key, quellen):
    """Kreuz-Kontrolle einer KATEGORIALEN Größe (z.B. Dachtyp). quellen:
    (name, wert) oder (name, wert, typ); leere Werte raus. Gleiche Typ-Logik wie
    doppelcheck_num: gleich + >=2 Typen → 'bestätigt', gleich + 1 Typ → 'verstaerkt',
    uneinig → 'widerspruch'. Returns dict|None."""
    vv = [(q, str(v).lower(), t) for q, v, t in _norm_quellen(quellen) if v]
    if len(vv) < 2:
        return None
    payload, typen = _quellen_struktur(vv)
    einig = len(set(w for _, w, _ in vv)) == 1
    if not einig:
        status = "widerspruch"
    elif len(typen) >= 2:
        status = "bestätigt"
    else:
        status = "verstaerkt"
    return {
        "groesse": label, "key": key, "einheit": "", "wert": vv[0][1],
        "quellen": payload, "typen_n": len(typen), "unabhaengig": len(typen) >= 2,
        "status": status,
    }
