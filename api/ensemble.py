"""Deterministische Reconciliation für Self-Consistency + Multi-Source-Lesungen.

REINE Funktionen, voll unit-testbar (kein I/O, kein API-Call). Sie machen aus
mehreren — möglicherweise abweichenden — Lesungen EINEN stabilen Wert UND eine
EHRLICHE Übereinstimmungs-Konfidenz.

Leitidee (User: „es soll immer konstant sein" + „beste Genauigkeit"):
- Mehrere unabhängige Lesungen einer wackeligen Größe (Fenster-Anzahl, Säulen,
  Öffnungsbreiten) werden NICHT per „höchste Konfidenz" (lauf-variabel) gewählt,
  sondern per MODUS/MEDIAN zusammengeführt → das mittelt Fehl-Lesungen heraus.
- Die ÜBEREINSTIMMUNG der Lesungen IST die Konfidenz (nicht eine geratene Zahl):
  3/3 einig → hoch, 2/3 → mittel, alle verschieden → niedrig + „prüfen".
- Ein byte-exakter Text-Layer-Wert ist immer Anker und schlägt jede Vision-Lesung.

Alles deterministisch: gleiche Eingangs-Lesungen → gleicher Wert + gleiche Konfidenz.
"""
from collections import Counter


def _zahlen(werte):
    out = []
    for v in werte:
        if v is None:
            continue
        try:
            out.append(float(v))
        except (TypeError, ValueError):
            continue
    return out


def modus_zahl(werte, default=None):
    """Häufigster GANZZAHLIGER Wert (Mode) über die Lesungen. Bei Gleichstand der
    KLEINERE Wert — deterministisch und konservativ (lieber nicht über-zählen)."""
    xs = [int(round(v)) for v in _zahlen(werte)]
    if not xs:
        return default
    c = Counter(xs)
    top = max(c.values())
    return min(k for k, n in c.items() if n == top)


def median_bucket(werte, bucket=0.05, default=None):
    """Median, gerastert auf `bucket` (z.B. 0.05 m = 5 cm). Das Rastern macht die
    Maße reproduzierbar (kleine Lese-Schwankungen kippen den Wert nicht)."""
    xs = sorted(_zahlen(werte))
    if not xs:
        return default
    n = len(xs)
    m = xs[n // 2] if n % 2 else (xs[n // 2 - 1] + xs[n // 2]) / 2.0
    if bucket and bucket > 0:
        m = round(m / bucket) * bucket
    return round(m, 4)


def mehrheit(stimmen, n_total=None):
    """True, wenn ein Element in der STRIKTEN Mehrheit der Lesungen vorkam
    (≥ floor(n/2)+1). Für „existiert dieses Fenster wirklich?" über N Lesungen."""
    ja = sum(1 for s in stimmen if s)
    n = n_total if n_total is not None else len(stimmen)
    return n > 0 and ja >= (n // 2 + 1)


def uebereinstimmung(werte, runde=2):
    """Anteil der Lesungen, die mit dem häufigsten (gerundeten) Wert übereinstimmen
    ∈ [0,1]. Das ist die EHRLICHE Konfidenz-Basis (nicht geraten)."""
    xs = _zahlen(werte)
    if not xs:
        return 0.0
    c = Counter(round(v, runde) for v in xs)
    return max(c.values()) / len(xs)


def konfidenz_aus_agreement(agreement, n, text_anker=False):
    """Mappt Übereinstimmung (0..1) + Stichproben-Zahl auf eine kalibrierte,
    DETERMINISTISCHE Konfidenz ∈ [0.3, 0.97]. Byte-exakter Anker → 0.97."""
    if text_anker:
        return 0.97
    try:
        agreement = max(0.0, min(1.0, float(agreement)))
        n = int(n)
    except (TypeError, ValueError):
        return 0.5
    base = 0.4 + 0.5 * agreement                 # 0→0.40, voll einig→0.90
    base += min(0.06, 0.02 * max(0, n - 1))       # leichter Bonus für mehr Stichproben
    return round(max(0.3, min(0.97, base)), 2)


def reconcile_zaehlung(lesungen, text_wert=None, label=""):
    """Führt mehrere ZÄHL-Lesungen (z.B. Säulen-Anzahl je Lauf) zusammen.

    Returns dict: {wert, konfidenz, agreement, n, status, alternativen, quelle}.
      status: 'bestaetigt' (byte-exakt ODER alle einig), 'mehrheit', 'unklar'.
    text_wert (byte-exakt) schlägt — wenn vorhanden — als Anker.
    """
    xs = [int(round(v)) for v in _zahlen(lesungen)]
    if text_wert is not None:
        try:
            tw = int(round(float(text_wert)))
        except (TypeError, ValueError):
            tw = None
        if tw is not None:
            stützt = xs.count(tw)
            return {"label": label, "wert": tw, "quelle": "text-anker",
                    "konfidenz": konfidenz_aus_agreement(1.0, len(xs) or 1, text_anker=True),
                    "agreement": round((stützt / len(xs)) if xs else 1.0, 2),
                    "n": len(xs), "status": "bestaetigt",
                    "alternativen": sorted(set(xs) - {tw})}
    if not xs:
        return {"label": label, "wert": None, "quelle": "keine", "konfidenz": 0.0,
                "agreement": 0.0, "n": 0, "status": "unklar", "alternativen": []}
    wert = modus_zahl(xs)
    agr = uebereinstimmung(xs, runde=0)
    c = Counter(xs)
    if len(c) == 1:
        status = "bestaetigt"
    elif c[wert] >= (len(xs) // 2 + 1):
        status = "mehrheit"
    else:
        status = "unklar"
    return {"label": label, "wert": wert, "quelle": "ensemble",
            "konfidenz": konfidenz_aus_agreement(agr, len(xs)),
            "agreement": round(agr, 2), "n": len(xs), "status": status,
            "alternativen": sorted(k for k in c if k != wert)}


def reconcile_opus_urteile(urteile):
    """Führt mehrere Opus-Bauingenieur-Urteile (GLEICHER Plan, N parallele Läufe) zu
    EINEM robusten zusammen — gegen die Lauf-zu-Lauf-Streuung + gegen Total-Ausfälle
    (mind. 1 erfolgreicher Lauf reicht).

    Basis = Lauf mit der MEDIAN-Gesamtkonfidenz (repräsentativ, kein Ausreißer). Die
    VOLATILEN Skalare werden robustifiziert: saeulen_anzahl = Modus, dach_typ =
    Mehrheit, hoehe.rohbau_m = Median. Strukturen (ueberdachte_bereiche/wand_verteilung)
    kommen vom Basis-Lauf — der deterministische Namens-Guard schützt den Carport-Fall
    ohnehin downstream. Erwartet die ROH-Urteile (mit/ohne _fehler); filtert die Fehler.
    Leere/komplett gescheiterte Liste → None."""
    us = [u for u in (urteile or []) if isinstance(u, dict) and not u.get("_fehler")]
    if not us:
        return None
    if len(us) == 1:
        return dict(us[0], _ensemble_n=1)
    konfs = [(float(u.get("gesamtkonfidenz") or 0), i) for i, u in enumerate(us)]
    med_k = sorted(k for k, _ in konfs)[len(konfs) // 2]
    base = dict(us[min(konfs, key=lambda x: abs(x[0] - med_k))[1]])
    saeulen = [u.get("saeulen_anzahl") for u in us if u.get("saeulen_anzahl") is not None]
    if saeulen:
        base["saeulen_anzahl"] = modus_zahl(saeulen)
    dts = [(u.get("dach") or {}).get("dach_typ") for u in us if (u.get("dach") or {}).get("dach_typ")]
    if dts:
        base["dach"] = dict(base.get("dach") or {})
        base["dach"]["dach_typ"] = Counter(dts).most_common(1)[0][0]
    hs = [(u.get("hoehe") or {}).get("rohbau_m") for u in us if (u.get("hoehe") or {}).get("rohbau_m")]
    if hs:
        base["hoehe"] = dict(base.get("hoehe") or {})
        base["hoehe"]["rohbau_m"] = median_bucket([float(h) for h in hs], 0.05)
    base["_ensemble_n"] = len(us)
    base["_ensemble_saeulen"] = sorted(int(round(float(s))) for s in saeulen) if saeulen else []
    return base


def reconcile_masse(lesungen, bucket=0.05, text_wert=None, label=""):
    """Wie reconcile_zaehlung, aber für ein MASS (Breite/Höhe in m). Median auf
    bucket gerastert; Übereinstimmung im Bucket = Konfidenz."""
    xs = _zahlen(lesungen)
    if text_wert is not None:
        try:
            tw = round(float(text_wert), 4)
        except (TypeError, ValueError):
            tw = None
        if tw is not None:
            return {"label": label, "wert": tw, "quelle": "text-anker",
                    "konfidenz": konfidenz_aus_agreement(1.0, len(xs) or 1, text_anker=True),
                    "agreement": 1.0, "n": len(xs), "status": "bestaetigt"}
    if not xs:
        return {"label": label, "wert": None, "quelle": "keine", "konfidenz": 0.0,
                "agreement": 0.0, "n": 0, "status": "unklar"}
    wert = median_bucket(xs, bucket=bucket)
    # Übereinstimmung = Anteil der Lesungen im selben Bucket wie der Median
    in_bucket = sum(1 for v in xs if abs(v - wert) <= bucket / 2.0 + 1e-9)
    agr = in_bucket / len(xs)
    status = "bestaetigt" if agr >= 0.99 else ("mehrheit" if agr >= 0.5 else "unklar")
    return {"label": label, "wert": wert, "quelle": "ensemble",
            "konfidenz": konfidenz_aus_agreement(agr, len(xs)),
            "agreement": round(agr, 2), "n": len(xs), "status": status}
