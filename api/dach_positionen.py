"""DACH-POSITIONEN-READER (Dachdecker/Zimmerer-Sektor) — byte-exakter Text-Pass.

Sanierungs-/Angebotspläne der Zimmerer tragen die Positionen als TEXT am Plan
(Baubetriebe-Audit, Mitterwurzerweg-Satz: 'Dachfläche Süd: 4,70 x 11,36 =
53,39 m²', '12 Sparren B/H 12/14cm', 'Velux GPL MK06 78/118 cm', 'Pos. 6)
Flachdachaufbau … ca. 34 m²', Schichtaufbauten mit cm-Dicken). Dieser Reader
liest sie byte-exakt über ALLE Seiten — kein Vision-Rauschen, keine Geometrie.

Read-only/best-effort: liefert {} wenn nichts gefunden — greift NIE in die
bestehende Mengenermittlung ein (eigener Sektor-Block im Response).
"""
import re

_FLAECHE_RX = re.compile(
    r"Dachfl[äa]+che[nr]?\s+([A-Za-zÄÖÜäöüß]+)\s*:?\s*"
    r"(?:([\d.,]+)\s*[x×]\s*([\d.,]+)\s*=\s*)?([\d.,]+)\s*m[²2]", re.I)
_HOLZ_RX = re.compile(
    r"(?:(\d+)\s*[x×]?\s*)?(Sparren(?:abst[üu]tzung)?|Pfette[n]?|Mauerbank|"
    r"Deckenbalken|Gratsparren|Schifter|Steher|Zange[n]?|Wechsel|Aufdoppelung)"
    r"\s{0,3}B\s*/\s*H\s*:?\s*(\d+)\s*/\s*(\d+)\s*cm", re.I)
_FENSTER_RX = re.compile(
    r"(?:(\d+)\s*(?:x|×|stk\.?|st[üu]ck)\s*)?"     # optionale Vorzahl '3x'/'3 Stk'
    r"(Velux|Roto|Fakro)\s*((?:[A-Z]{2,4}\s+)?[A-Z0-9]{3,6})?\s*"
    r"(\d{2,3})\s*/\s*(\d{2,3})\s*cm", re.I)
_POS_RX = re.compile(
    r"Pos\.?\s*(\d+)\s*\)\s*([^\n]{5,90}?)"
    r"(?:\s*ca\.?\s*([\d.,]+)\s*m[²2])?(?:\n|$)", re.I)
_KAMIN_RX = re.compile(r"(\d+)\s*[x×]\s*Kamin[^\n]{0,40}?(abbrechen|abtragen|schleifen|k[üu]rzen)", re.I)
_SCHICHT_RX = re.compile(
    r"^[\s\-–•]*([A-ZÄÖÜ][A-Za-zÄÖÜäöüß/\- ]{3,44}?)\s+([\d.,]+)\s*cm\s*$", re.M)


def _f(s):
    try:
        t = str(s).strip()
        if "," in t:                       # deutsche Dezimalzahl (Punkt=Tausender)
            return float(t.replace(".", "").replace(",", "."))
        if re.fullmatch(r"-?\d{1,3}(?:\.\d{3})+", t):
            return float(t.replace(".", ""))   # 1.234 = Tausenderpunkt → 1234
        return float(t)                    # einzelner Punkt ≠3 Nachk. = Dezimal
    except (TypeError, ValueError):
        return None


def dach_positionen(doc):
    """PDF (fitz-Doc) → {flaechen, hoelzer, fenster, positionen, kamine,
    schichten, gesamt_m2} — nur befüllte Keys; {} wenn kein Dach-Signal."""
    flaechen, hoelzer, fenster, positionen, kamine, schichten = [], [], [], [], [], []
    fenster_roh = {}
    for nr, page in enumerate(doc):
        try:
            txt = page.get_text()
        except Exception:
            continue
        if not txt or ("dach" not in txt.lower() and "sparren" not in txt.lower()):
            continue
        for m in _FLAECHE_RX.finditer(txt):
            wert = _f(m.group(4))
            if not wert or wert > 5000:
                continue
            flaechen.append({
                "name": m.group(1), "m2": wert, "seite": nr,
                "rechnung": (f"{m.group(2)} × {m.group(3)}"
                             if m.group(2) and m.group(3) else None),
                "quelle": "byte-exakt",
            })
        for m in _HOLZ_RX.finditer(txt):
            hoelzer.append({
                "bauteil": m.group(2).strip(), "anzahl": int(m.group(1) or 1),
                "b_cm": int(m.group(3)), "h_cm": int(m.group(4)),
                "seite": nr, "quelle": "byte-exakt",
            })
        for m in _FENSTER_RX.finditer(txt):
            key = (m.group(2).title(), (m.group(3) or "").strip(),
                   m.group(4), m.group(5), nr)
            # Vorzahl '3x Velux …' zählt als 3 (früher als 1 unterzählt)
            fenster_roh[key] = fenster_roh.get(key, 0) + (int(m.group(1)) if m.group(1) else 1)
        for m in _POS_RX.finditer(txt):
            positionen.append({
                "pos": int(m.group(1)), "text": m.group(2).strip(),
                "m2": _f(m.group(3)), "seite": nr, "quelle": "byte-exakt",
            })
        for m in _KAMIN_RX.finditer(txt):
            kamine.append({"anzahl": int(m.group(1)),
                           "arbeit": m.group(2).lower(), "seite": nr})
        for m in _SCHICHT_RX.finditer(txt):
            d = _f(m.group(2))
            if d and 0.1 <= d <= 60:
                schichten.append({"material": m.group(1).strip(),
                                  "dicke_cm": d, "seite": nr})
    for (marke, typ, b, h, nr), n in fenster_roh.items():
        fenster.append({"marke": marke,
                        "typ": " ".join(typ.split()) if typ else None,
                        "breite_cm": int(b), "hoehe_cm": int(h),
                        "anzahl": n, "seite": nr, "quelle": "byte-exakt"})
    # DEDUPE über Seiten (der Systemschnitt wiederholt die Sparrenlage-Angaben;
    # Flächen stehen doppelt in Tabelle+Zeichnung): gleiche Signatur = ein Fund.
    _fl, _seen = [], set()
    for x in flaechen:
        k = (x["name"].lower(), x["m2"])
        if k in _seen:
            # Rechnung von der besseren Fundstelle behalten
            if x.get("rechnung"):
                for y in _fl:
                    if (y["name"].lower(), y["m2"]) == k and not y.get("rechnung"):
                        y["rechnung"] = x["rechnung"]
            continue
        _seen.add(k)
        _fl.append(x)
    flaechen = _fl
    _hz, _seen = [], set()
    for x in sorted(hoelzer, key=lambda h2: -h2["anzahl"]):
        # Anzahl im Dedupe-Key: zwei ECHT verschiedene Abschnitte gleichen
        # Querschnitts ('12 Sparren 8/16' + '8 Sparren 8/16') sind nicht dieselbe
        # Angabe → nicht mergen (früher kollabierten sie zu einem, ~40% Holz fehlte).
        k = (x["bauteil"].lower(), x["b_cm"], x["h_cm"], x["anzahl"])
        if k in _seen:
            continue
        _seen.add(k)
        _hz.append(x)
    hoelzer = _hz
    _sc, _seen = [], set()
    for x in schichten:
        k = (x["material"].lower(), x["dicke_cm"])
        if k in _seen:
            continue
        _seen.add(k)
        _sc.append(x)
    schichten = _sc
    if not (flaechen or hoelzer or fenster or positionen):
        return {}
    out = {}
    if flaechen:
        out["flaechen"] = flaechen
        ges = [f for f in flaechen if "gesamt" in f["name"].lower()]
        teile = [f for f in flaechen if "gesamt" not in f["name"].lower()]
        if ges:
            out["gesamt_m2"] = ges[0]["m2"]
            # PLAUSI: Σ Teilflächen gegen die Gesamt-Zeile (byte-exakter
            # Selbst-Check des Plans — dasselbe Prinzip wie die Raum-Stempel)
            if teile:
                s_teile = round(sum(f["m2"] for f in teile), 2)
                out["gesamt_bestaetigt"] = abs(s_teile - ges[0]["m2"]) <= 0.5
        elif teile:
            out["gesamt_m2"] = round(sum(f["m2"] for f in teile), 2)
    if hoelzer:
        out["hoelzer"] = hoelzer
    if fenster:
        out["fenster"] = fenster
    if positionen:
        # Dedupe (gleiche Pos-Nr. auf mehreren Seiten): erste gewinnt
        seen = set()
        out["positionen"] = [p for p in positionen
                             if not (p["pos"] in seen or seen.add(p["pos"]))]
    if kamine:
        out["kamine"] = kamine
    if schichten:
        out["schichten"] = schichten[:40]
    ml = dach_materialliste(out)
    if ml:
        out["materialliste"] = ml
    return out


# Dachdecker-/Zimmerer-KENNWERTE (österreichische Praxis; jede Firma kann sie
# über den Kalibrierungs-Moat justieren — Default = gängige Werte).
_DACH_KW = {
    "dachlatten_lfm_pro_m2": 3.3,     # 30-cm-Lattung
    "konterlatten_lfm_pro_m2": 2.6,   # ~40-cm-Sparrenabstand
    "unterspann_verschnitt": 1.15,    # Überlappung + Verschnitt
    "deckung_verschnitt": 1.05,
    "sparren_ueberstand_m": 0.50,     # Dachvorsprung je Sparren
}


def dach_materialliste(dp, kw=None):
    """Dach-Positionen (byte-exakt) → bestellbare Material-Mengen mit Rechenweg.
    Ein Dachdecker/Zimmerer braucht m²/lfm/m³, nicht nur die Roh-Zahlen.
    Flächen-basiert = hohe Konfidenz (Fläche byte-exakt × Kennwert); Holz =
    mittel (Länge aus der Dachflächen-Rechnung abgeleitet, am Plan prüfbar)."""
    k = dict(_DACH_KW, **(kw or {}))
    A = dp.get("gesamt_m2")
    schichten = dp.get("schichten") or []
    flaechen = dp.get("flaechen") or []
    out = []

    def _pos(bauteil, material, einheit, menge, formel, konf):
        out.append({"bauteil": bauteil, "material": material, "einheit": einheit,
                    "menge": round(float(menge), 2), "formel": formel,
                    "konfidenz": konf, "quelle": "dach-byte-exakt"})

    if A and A > 0:
        _pos("Dachdeckung", "Dacheindeckung (Ziegel/Blech lt. Wahl)", "m²",
             A * k["deckung_verschnitt"],
             f"{A} m² × {k['deckung_verschnitt']} Verschnitt", 0.85)
        _pos("Dachlattung", "Dachlatten", "lfm", A * k["dachlatten_lfm_pro_m2"],
             f"{A} m² × {k['dachlatten_lfm_pro_m2']} lfm/m²", 0.75)
        _pos("Dachlattung", "Konterlatten", "lfm", A * k["konterlatten_lfm_pro_m2"],
             f"{A} m² × {k['konterlatten_lfm_pro_m2']} lfm/m²", 0.75)
        _pos("Unterdach", "Unterspannbahn", "m²", A * k["unterspann_verschnitt"],
             f"{A} m² × {k['unterspann_verschnitt']} Überlappung", 0.8)
        # Schicht-Dicken (byte-exakt aus dem Systemschnitt) → Dämmung/Schalung m³/m²
        # NICHT-DACH-Filter: der Schnitt trägt oft auch Fassaden-/Boden-/Wand-
        # Schichten (…dämmung), die NICHT zur Dachfläche gehören — sonst würde z.B.
        # Fassaden-/Trittschalldämmung mit der DACHfläche multipliziert (falsches m³).
        _nicht_dach = ("fassad", "trennwand", "trittschall", "perimeter", "estrich",
                       "sockel", "kellerdeck", "bodenplatt", "innenputz",
                       "außenputz", "aussenputz", "wandputz", "vorsatzschal")
        for s in schichten:
            mn = (s.get("material") or "").lower()
            dcm = s.get("dicke_cm")
            if not dcm:
                continue
            if any(t in mn for t in _nicht_dach):
                continue   # kein Dach-Aufbau → nicht × Dachfläche rechnen
            if any(t in mn for t in ("dämmung", "daemmung", "mineralwolle",
                                     "pur", "xps", "gefälle")):
                _pos("Dämmung", f"{s['material']} {dcm}cm", "m³",
                     A * dcm / 100.0, f"{A} m² × {dcm}cm", 0.7)
            elif "schalung" in mn:
                _pos("Schalung", f"{s['material']} {dcm}cm", "m²", A,
                     f"= Dachfläche {A} m²", 0.75)

    # Konstruktionsholz m³: Anzahl × Querschnitt × Länge (Länge aus der
    # Dachflächen-Rechnung — Schräg-Länge für Sparren, First-Länge für
    # liegende Hölzer; am Plan prüfbar, daher Konfidenz 0,5).
    schraeg = first = None
    for f in flaechen:
        r = f.get("rechnung")
        if r and "×" in r:
            try:
                a, b = [_f(x) for x in r.split("×")]
                if a and b:
                    schraeg = schraeg or min(a, b)   # Schräglänge (Sparren-Lauf)
                    first = first or max(a, b)       # First-/Traufenlänge
            except Exception:
                pass
    LIEGEND = ("mauerbank", "pfette", "zange", "deckenbalken")
    for h in (dp.get("hoelzer") or []):
        b, hh, n = h.get("b_cm"), h.get("h_cm"), h.get("anzahl") or 1
        if not (b and hh):
            continue
        ist_liegend = any(t in h["bauteil"].lower() for t in LIEGEND)
        L = (first if ist_liegend else (schraeg + k["sparren_ueberstand_m"])) \
            if (first and schraeg) else None
        if L:
            _pos("Konstruktionsholz", f"{h['bauteil']} {b}/{hh} cm", "m³",
                 n * (b / 100.0) * (hh / 100.0) * L,
                 f"{n}× {b}/{hh}cm × {round(L, 2)}m Länge", 0.5)
    return out
