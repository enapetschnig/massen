"""AUFMASS-WERKZEUG: Messungen und Positionen (Umbau E1).

Warum dieses Modul existiert — der strukturelle Befund vom 2026-08-10:
Bis hierher gab es keine MESSUNG als Objekt. Es gab die KI-Lesung
(`elemente`) und die im Speicher berechneten `LVPosition`. Der Nutzer konnte
damit nichts messen, was die KI nicht erkannt hat, und keine Menge
korrigieren, ohne den Umweg über Overrides. Genau das ist der Unterschied
zwischen einer Erkennungs-Demo und einem Aufmaß-Werkzeug.

Ab hier gilt: **die Geometrie ist die Wahrheit.** Wert und Formel werden aus
den Punkten gerechnet, nie umgekehrt. Damit ist jede Menge

  * prüfbar   — die Formel steht daneben ("5,84 × 4,77 − 1,20 × 0,90"),
  * zeigbar   — die Punkte liegen im Plan und lassen sich einzeichnen,
  * korrigierbar — der Mensch zieht einen Punkt, die Zahl folgt.

Die Rechenwege sind bewusst hier und NICHT im Frontend: dieselbe Formel muss
im Protokoll, im Export und in der Anzeige dieselbe Zahl ergeben. Ein zweiter
Rechenweg im Browser wäre eine zweite Wahrheit.
"""
import math

# Einheiten je Messungstyp — der Typ bestimmt, was gerechnet wird.
TYP_EINHEIT = {
    "flaeche": "m2",
    "abzug": "m2",
    "laenge": "m",
    "stueck": "stk",
    "volumen": "m3",
    "bauteil": "m2",
    "treppe": "m2",
}
FORMEN = ("polygon", "rechteck", "polylinie", "punkt")


def _f(x):
    """Deutsche Zahl fürs Protokoll: 5.84 -> '5,84' (max 2 Nachkommastellen)."""
    return f"{round(float(x), 2):.2f}".replace(".", ",")


def polygon_flaeche(punkte):
    """Gauß'sche Trapezformel. punkte: [[x, y], …] in derselben Einheit."""
    n = len(punkte or [])
    if n < 3:
        return 0.0
    s = 0.0
    for i in range(n):
        x1, y1 = punkte[i - 1][0], punkte[i - 1][1]
        x2, y2 = punkte[i][0], punkte[i][1]
        s += x1 * y2 - x2 * y1
    return abs(s) / 2.0


def polylinie_laenge(punkte, geschlossen=False):
    n = len(punkte or [])
    if n < 2:
        return 0.0
    s = 0.0
    bis = n if geschlossen else n - 1
    for i in range(bis):
        x1, y1 = punkte[i][0], punkte[i][1]
        x2, y2 = punkte[(i + 1) % n][0], punkte[(i + 1) % n][1]
        s += math.hypot(x2 - x1, y2 - y1)
    return s


def _rechteck_seiten(punkte, ptm):
    """Seitenlängen eines (auch gedrehten) Rechtecks in Metern.

    Für die Formel "5,84 × 4,77" — die der Polier nachrechnen kann. Bei einem
    nicht-rechteckigen Polygon gibt es keine zwei Seiten, dann None.
    """
    if len(punkte or []) != 4:
        return None
    a = polylinie_laenge([punkte[0], punkte[1]]) / ptm
    b = polylinie_laenge([punkte[1], punkte[2]]) / ptm
    c = polylinie_laenge([punkte[2], punkte[3]]) / ptm
    d = polylinie_laenge([punkte[3], punkte[0]]) / ptm
    # gegenüberliegende Seiten müssen gleich sein (1 cm Toleranz)
    if abs(a - c) > 0.01 or abs(b - d) > 0.01:
        return None
    return (a, b)


def rechne(typ, geometrie, ptm, abzuege=None, hoehe_m=None):
    """Aus Geometrie -> (wert, einheit, formel). ptm: pt pro Meter.

    abzuege: Liste bereits gerechneter Abzugs-Messungen (dicts mit wert),
    die von einer Fläche abgezogen werden. Der ÖNORM-Übermessungsregel
    (Öffnungen <= 4 m² werden übermessen) folgt NICHT dieses Modul, sondern
    massen_logic bei der Position — hier zählt, was der Mensch gezeichnet hat.
    """
    typ = (typ or "").strip()
    g = geometrie or {}
    punkte = g.get("punkte") or []
    einheit = TYP_EINHEIT.get(typ, "m2")
    if not ptm or ptm <= 0:
        return (None, einheit, None)

    if typ == "stueck":
        wert = float(g.get("anzahl") or len(punkte) or 0)
        return (wert, "stk", f"{int(wert)} Stk")

    if typ == "laenge":
        m = polylinie_laenge(punkte, bool(g.get("geschlossen"))) / ptm
        teile = []
        n = len(punkte)
        bis = n if g.get("geschlossen") else n - 1
        for i in range(max(0, bis)):
            teil = polylinie_laenge([punkte[i], punkte[(i + 1) % n]]) / ptm
            teile.append(_f(teil))
        formel = " + ".join(teile) if len(teile) > 1 else (teile[0] if teile else "")
        return (round(m, 3), "m", formel)

    if typ == "treppe":
        # digiplan-Paritaet: das Treppen-Werkzeug rechnet aus dem Grundriss-
        # Polygon + Geschosshoehe die STIEGENUNTERSICHT (schraege Flaeche,
        # die der Trockenbauer/Maler verputzt) und das BETON-VOLUMEN
        # (Keilprisma) mit. Wert der Messung = Untersicht in m2; Volumen
        # steht in der Formel und in meta (fuer eine eigene Position).
        a0 = polygon_flaeche(punkte) / (ptm * ptm)
        h = float(hoehe_m or g.get("hoehe_m") or 2.75)
        xs = [p0[0] for p0 in punkte]; ys = [p0[1] for p0 in punkte]
        L = max(max(xs) - min(xs), max(ys) - min(ys)) / ptm  # Lauflaenge
        if L <= 0 or a0 <= 0:
            return (None, "m2", None)
        schr = math.sqrt(1.0 + (h / L) ** 2)
        unters = a0 * schr
        vol = a0 * h / 2.0
        formel = (f"{_f(a0)} × {_f(schr)} schräg (H {_f(h)}, "
                  f"V≈{_f(vol)} m³)")
        return (round(unters, 3), "m2", formel)

    # Flächen-Familie: flaeche | abzug | bauteil | volumen
    a = polygon_flaeche(punkte) / (ptm * ptm)
    seiten = _rechteck_seiten(punkte, ptm)
    formel = (f"{_f(seiten[0])} × {_f(seiten[1])}" if seiten
              else f"Polygon {len(punkte)} Punkte")

    if typ == "volumen":
        h = float(hoehe_m or g.get("hoehe_m") or 0)
        return (round(a * h, 3), "m3", f"({formel}) × {_f(h)}")

    for ab in (abzuege or []):
        w = ab.get("wert")
        if w:
            a -= float(w)
            formel += f" − {_f(w)}"
    return (round(a, 3), einheit, formel)


def aus_raum(raum, ptm, nummer=None):
    """KI-Raum -> Messungs-VORSCHLAG (Etappe E3).

    Der Umriss, den die Erkennung gefunden hat, wird zur Messung mit
    `quelle='ki'` und `status='vorschlag'`. Der Mensch bestätigt oder zieht
    die Punkte zurecht — dann wird daraus eine bestätigte Messung. Damit ist
    die Erkennungsqualität entkoppelt: eine verfehlte Region kostet
    Handarbeit, nie eine falsche Menge.
    """
    pts = raum.get("region_pt") or []
    if len(pts) < 3:
        return None
    geo = {"form": "polygon", "punkte": [[float(p[0]), float(p[1])] for p in pts]}
    wert, einheit, formel = rechne("flaeche", geo, ptm)
    # Der byte-exakte Stempel schlaegt die Geometrie — steht er im Plan,
    # ist ER der Wert, und die Formel sagt das auch.
    f_stempel = raum.get("f_m2")
    if f_stempel:
        wert, formel = float(f_stempel), f"{_f(f_stempel)} lt. Raumstempel"
    return {
        "typ": "flaeche", "nummer": nummer,
        "bezeichnung": (raum.get("name") or "Raum"),
        "geometrie": geo, "formel": formel, "wert": wert, "einheit": einheit,
        "quelle": "ki", "status": "vorschlag",
        "raum_ref": raum.get("name"),
    }


def protokoll(messungen, positionen):
    """Aufmaßprotokoll je Position: jede Messung mit Nummer, Formel, Wert.

    Das ist die Ausgabe, die der Rechnung beiliegt — und der Grund, warum die
    Formel in der Messung steht und nicht erst hier entsteht: gedruckt wird,
    was gerechnet wurde.
    """
    nach_pos = {}
    for m in (messungen or []):
        if (m.get("status") or "aktiv") == "verworfen":
            continue
        nach_pos.setdefault(m.get("position_id"), []).append(m)
    out = []
    for p in (positionen or []):
        ms = nach_pos.get(p.get("id")) or []
        summe = sum(float(m.get("wert") or 0) for m in ms
                    if m.get("typ") != "abzug")
        summe -= sum(float(m.get("wert") or 0) for m in ms
                     if m.get("typ") == "abzug")
        vp = float(p.get("verschnitt_pct") or 0)
        out.append({
            "nr": p.get("nr"), "bezeichnung": p.get("bezeichnung"),
            "einheit": p.get("einheit"),
            "zeilen": [{
                "nummer": m.get("nummer"), "bezeichnung": m.get("bezeichnung"),
                "formel": m.get("formel"), "wert": m.get("wert"),
                "typ": m.get("typ"), "quelle": m.get("quelle"),
            } for m in sorted(ms, key=lambda x: (x.get("nummer") or 0))],
            "summe": round(summe, 3),
            "verschnitt_pct": vp,
            "endsumme": round(summe * (1.0 + vp / 100.0), 3),
            "n_messungen": len(ms),
        })
    ohne = nach_pos.get(None) or []
    return {"positionen": out,
            "ohne_position": [{"nummer": m.get("nummer"),
                               "bezeichnung": m.get("bezeichnung"),
                               "wert": m.get("wert"), "einheit": m.get("einheit")}
                              for m in ohne],
            "n_ohne_position": len(ohne)}
