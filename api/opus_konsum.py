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


def doppelcheck_num(label, key, einheit, quellen, tol):
    """Kreuz-Kontrolle EINER Größe über mehrere unabhängige Quellen.

    quellen: Liste von (quelle_name, wert). Werte, die nicht numerisch/>0 sind,
    werden ignoriert. Erst ab ZWEI gültigen Quellen entsteht ein Eintrag:
    stimmen alle innerhalb tol zum Median → "bestätigt", sonst "widerspruch".
    So wird Konfidenz VERDIENT (Übereinstimmung), nicht gefaket.

    Returns dict (doppelcheck-Eintrag) oder None.
    """
    vv = []
    for q, v in quellen:
        try:
            fv = float(v)
        except (TypeError, ValueError):
            continue
        if fv > 0:
            vv.append((q, round(fv, 2)))
    if len(vv) < 2:
        return None
    med = sorted(v for _, v in vv)[len(vv) // 2]
    agree = all(abs(v - med) <= tol for _, v in vv)
    return {
        "groesse": label, "key": key, "einheit": einheit, "wert": med,
        "quellen": [{"quelle": q, "wert": v} for q, v in vv],
        "status": "bestätigt" if agree else "widerspruch",
    }


def doppelcheck_kat(label, key, quellen):
    """Kreuz-Kontrolle einer KATEGORIALEN Größe (z.B. Dachtyp). quellen:
    (name, wert)-Liste; leere Werte werden ignoriert. Ab zwei Quellen:
    alle gleich → 'bestätigt', sonst 'widerspruch'. Returns dict|None."""
    vv = [(q, str(v).lower()) for q, v in quellen if v]
    if len(vv) < 2:
        return None
    return {
        "groesse": label, "key": key, "einheit": "", "wert": vv[0][1],
        "quellen": [{"quelle": q, "wert": v} for q, v in vv],
        "status": "bestätigt" if len(set(v for _, v in vv)) == 1 else "widerspruch",
    }
