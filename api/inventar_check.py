"""Bauteil-Inventar-Crosscheck (Phase 5).

Vergleicht das aus dem Plan visuell erkannte Bauteil-Inventar (Säulen, Treppen,
Kamine, Unterzüge, Schächte, …) mit dem, was die Materialliste / ÖNORM-LV
tatsächlich abgebildet hat → flaggt „im Plan gesehen, in der Massenermittlung
(noch) nicht erfasst".

Reine, testbare Logik. Hinter OPUS_INVENTAR (Default AUS) gegated — solange aus,
vollständig dormant. FLAG-ONLY: erzeugt KEINE Mengen. Eine Auto-Menge aus
Standardmaßen × geschätzter Zählung wäre falsche Präzision, bis die Vision-
Erkennung am echten Plan validiert ist. Erst melden, dann (Phase 5b) Mengen.
"""

# Bekannte tragende Bauteile → Stichwörter, unter denen sie in der Liste/LV stehen
INVENTAR_TYPEN = {
    "saeule":    {"label": "Stützen/Säulen",     "deckung": ("stütze", "stuetze", "säule", "saeule", "stahlbeton-stütz")},
    "treppe":    {"label": "Treppe/Stiege",      "deckung": ("treppe", "stiege", "podest", "lauf")},
    "kamin":     {"label": "Kamin/Schornstein",  "deckung": ("kamin", "schornstein", "fang")},
    "unterzug":  {"label": "Unterzug/Überzug",   "deckung": ("unterzug", "überzug", "ueberzug", "sturz", "träger", "traeger")},
    "schacht":   {"label": "Schacht/Aufzug",     "deckung": ("schacht", "aufzug", "lift")},
    "ringanker": {"label": "Ringanker",          "deckung": ("ringanker", "ringbalken")},
    "balkon":    {"label": "Balkon/Podest",      "deckung": ("balkon", "podest", "loggia", "kragplatte")},
}

MIN_KONF = 0.55   # Inventar-Eintrag erst ab dieser Konfidenz ernst nehmen


def _norm_typ(t):
    """Roh-Typ-String → bekannter Inventar-Schlüssel (oder None)."""
    t = (t or "").lower()
    for key, meta in INVENTAR_TYPEN.items():
        if key in t or any(d in t for d in meta["deckung"]):
            return key
    return None


def _liste_deckt(typ, bauteile_keys, gewerke_text):
    """Ist der Typ in den Materialliste-Bauteilen ODER den ÖNORM-Gewerk-Texten
    bereits abgebildet?"""
    deckung = INVENTAR_TYPEN[typ]["deckung"]
    hay = (" ".join(bauteile_keys) + " " + (gewerke_text or "")).lower()
    return any(d in hay for d in deckung)


def crosscheck_inventar(inventar, materialliste, gewerke):
    """inventar: Liste {typ, anzahl?, beleg, konfidenz, position?} aus der Vision.
    materialliste/gewerke: die berechneten Ergebnisse.
    Liefert {erkannt, gedeckt, fehlend, flaggen}:
      • erkannt  — alle ernstgenommenen Inventar-Einträge (Beleg + Konfidenz ok)
      • gedeckt  — davon in der Liste/LV abgebildet
      • fehlend  — im Plan gesehen, aber NICHT abgebildet
      • flaggen  — Prüf-Hinweise (prio/thema/hinweis) für die fehlenden
    """
    bauteile_keys = list(((materialliste or {}).get("bauteile") or {}).keys())
    gtext = " ".join(
        (p.get("beschreibung") or "")
        for g in ((gewerke or {}).get("gewerke") or {}).values()
        for p in (g.get("positionen") or []))

    erkannt, gedeckt, fehlend, flaggen = [], [], [], []
    for it in (inventar or []):
        it = it or {}
        try:
            konf = float(it.get("konfidenz") or 0)
        except (TypeError, ValueError):
            konf = 0.0
        beleg = (it.get("beleg") or "").strip()
        if konf < MIN_KONF or not beleg:
            continue   # zu unsicher / kein Beleg → ignorieren (keine Geister-Flaggen)
        typ = _norm_typ(it.get("typ"))
        if not typ:
            continue
        eintrag = {"typ": typ, "label": INVENTAR_TYPEN[typ]["label"],
                   "anzahl": it.get("anzahl"), "beleg": beleg,
                   "konfidenz": round(konf, 2), "position": it.get("position")}
        erkannt.append(eintrag)
        if _liste_deckt(typ, bauteile_keys, gtext):
            gedeckt.append(eintrag)
        else:
            fehlend.append(eintrag)
            _n = eintrag["anzahl"]
            _nstr = (str(_n) + "× ") if _n else ""
            flaggen.append({
                "prio": "mittel",
                "thema": "Im Plan gesehen · " + eintrag["label"],
                "hinweis": (_nstr + eintrag["label"] + " im Plan erkannt (Beleg: " + beleg +
                            "), aber in der Massenermittlung NICHT abgebildet — prüfen/ergänzen.")})
    return {"erkannt": erkannt, "gedeckt": gedeckt, "fehlend": fehlend, "flaggen": flaggen}
