"""SCHNITT-LESUNG: Höhenkoten byte-exakt aus dem Text-Layer.

Warum das nötig ist — gemessen 2026-08-02 über 12 verschiedene Pläne
(`scripts/mess_plankorpus_breit.py`): vier davon sind Schnitte und
Ansichten, und die liefern heute NICHTS ("keine Raumstempel"). Dabei geht
die Geschosshöhe in JEDE Wandfläche ein (Putz LG 10, Maler LG 46, Mauerwerk
LG 08, Trockenbau LG 39). Sie stammt bisher aus einer KI-Bildlesung des
Blattes — während dieselbe Zahl byte-exakt daneben geschrieben steht:
der Velden-Schnitt trägt 38 Höhenkoten, der Haus-A-Schnitt 76.

Der Weg dorthin war nicht der erste, der naheliegt. Drei einfachere
Ableitungen wurden gemessen und sind unzureichend:

  1. "Kote neben der Geschoss-Marke nehmen" → ordnet dem EG die Kote
     +2,80 zu. Der nächste Nachbar ist nicht die zugehörige Kote.
  2. "häufigste Differenz zwischen 2,2 und 4,5 m" → Haus A liefert klar
     2,86 m (9 Belege), Velden aber 2,50 und 3,30 gleichauf (je 5).
  3. "linearer Fit über ALLE Koten" (ein maßstäblicher Schnitt MUSS
     linear sein) → R² = 0,008 (Velden) / 0,612 (Haus A). Er scheitert,
     weil ein Blatt MEHRERE Schnitte nebeneinander trägt, jeder mit
     eigenem Nullpunkt. Ausreißer-Abwurf rettet es nur scheinbar: R²
     steigt auf 0,999, nutzt aber 6 von 76 Koten — eine Überanpassung.

Was trägt, ist RANSAC: die GRÖSSTE Kotenmenge suchen, die einer einzigen
Geraden Kote ≈ a·y + b folgt. Mehrere Schnitte auf einem Blatt stören dann
nicht mehr — jeder bildet seine eigene Gerade, und die größte gewinnt.

DIE SELBSTPRÜFUNG IST DER EIGENTLICHE GEWINN: aus der Steigung fällt der
ZEICHNUNGSMASSSTAB heraus. Gemessen ergab das 56,7 / 57,1 pt/m auf den
beiden Schnittplänen und 58,0 / 56,8 pt/m für deren jeweils zweite Gruppe —
alle vier ≈ 57 pt/m, und 1 m im Maßstab 1:50 sind exakt 56,7 pt. Vier
unabhängige Ableitungen treffen den wahren Maßstab auf 1 % genau. Auf
Grundrissblättern ohne Schnitt kommen dagegen 937 bzw. 1757 pt/m heraus
(dort reihen sich zufällig Raumhöhen-Koten auf) — der Maßstab trennt also
sauber, ob ein Blatt überhaupt einen Schnitt trägt.

Dieses Modul ÄNDERT KEINE MENGEN. Es liefert die gelesenen Fakten, damit
sie am Plan sichtbar und nachvollziehbar werden. Eine Zahl in die Mengen zu
schieben, die nur auf EINER Quelle beruht, wäre derselbe Fehler wie eine
geratene Fensterbreite: erst wenn zwei unabhängige Quellen übereinstimmen
(RANSAC-Niveaus UND Geschoss-Marken), ist sie belastbar.
"""
import re

# +2,80 / -3,10 / +0,03 — österreichische Höhenkote, immer mit Vorzeichen
KOTE_RX = re.compile(r"^([+\-])\s?(\d{1,2})[,.](\d{2})$")
# KG / EG / OG / DG, auch "OG1", "1.OG", mit Doppelpunkt oder Punkt dahinter
GESCHOSS_RX = re.compile(r"^([12]?\.?\s?(?:KG|EG|OG|DG)[12]?)[.:]?$", re.I)

# Plausibler Zeichnungsmaßstab: 1:20 (141,7 pt/m) bis 1:200 (14,2 pt/m).
# Alles außerhalb heißt: die Koten reihen sich zufällig auf, es ist kein
# Schnitt. Genau daran scheitern die Grundrissblätter (937 / 1757 pt/m).
MASSSTAB_MIN_PT_M = 12.0
MASSSTAB_MAX_PT_M = 150.0
# Geschosshöhe roh: unter 2,2 m ist kein Aufenthaltsraum, über 4,5 m ist
# es eine Halle oder zwei Geschosse auf einmal.
GH_MIN_M = 2.2
GH_MAX_M = 4.5


def _koten_und_marken(page):
    """-> ([(y, wert_m, x)], [(name, y, x)]) aus dem Text-Layer."""
    koten, marken = [], []
    for w in page.get_text("words"):
        t = (w[4] or "").strip()
        if not t:
            continue
        m = KOTE_RX.match(t)
        if m:
            v = float(f"{m.group(2)}.{m.group(3)}")
            if m.group(1) == "-":
                v = -v
            koten.append(((w[1] + w[3]) / 2.0, v, (w[0] + w[2]) / 2.0))
            continue
        g = GESCHOSS_RX.match(t)
        if g:
            marken.append((g.group(1).upper().replace(" ", ""),
                           (w[1] + w[3]) / 2.0, (w[0] + w[2]) / 2.0))
    return koten, marken


def _ransac(punkte, tol_m=0.05, min_dy_pt=40.0):
    """Größte Kotenmenge auf EINER Geraden Kote ≈ a·y + b.

    Deterministisch: alle Paare in fester Reihenfolge, größte Inlier-Menge
    gewinnt, Gleichstand über die flachere Steigung. Kein Zufall — dieselbe
    Eingabe liefert garantiert dasselbe Ergebnis (die App muss bei gleichem
    Plan immer dieselbe Menge ausweisen).
    """
    n = len(punkte)
    if n < 6:
        return None
    best = None
    for i in range(n):
        yi, vi, _ = punkte[i]
        for j in range(i + 1, n):
            yj, vj, _ = punkte[j]
            dy = yj - yi
            if abs(dy) < min_dy_pt:
                continue
            a = (vj - vi) / dy
            if a >= 0:          # Papier nach unten = Höhe nimmt AB
                continue
            b = vi - a * yi
            inlier = [p for p in punkte if abs(p[1] - (a * p[0] + b)) <= tol_m]
            rang = (len(inlier), -abs(a))
            if best is None or rang > best[0]:
                best = (rang, a, b, inlier)
    return best


def lies_schnitt(page):
    """Liest Maßstab und Höhen-Niveaus aus einem Schnitt/einer Ansicht.

    -> dict oder {} wenn das Blatt keinen auswertbaren Schnitt trägt.
       {"massstab_pt_m", "massstab_label", "niveaus_m", "geschosshoehen_m",
        "n_koten", "n_gruppe", "geschoss_marken", "quelle"}
    """
    koten, marken = _koten_und_marken(page)
    if len(koten) < 6:
        return {}
    r = _ransac(koten)
    if not r:
        return {}
    (n_gruppe, _), a, _b, inlier = r
    massstab = abs(1.0 / a) if a else 0.0
    if not (MASSSTAB_MIN_PT_M <= massstab <= MASSSTAB_MAX_PT_M):
        return {}               # kein Schnitt — nur zufällig gereihte Koten
    if n_gruppe < 6:
        return {}

    # Niveaus: Werte der Gruppe. Mehrfach markierte zuerst — an einem
    # Fußboden-Niveau hängen typisch mehrere Koten (Rohdecke, Fertigfußboden,
    # beide Schnittseiten).
    zaehl = {}
    for _y, v, _x in inlier:
        k = round(v, 2)
        zaehl[k] = zaehl.get(k, 0) + 1
    mehrfach = sorted(v for v, c in zaehl.items() if c >= 2)
    basis = mehrfach if len(mehrfach) >= 2 else sorted(zaehl)
    gh = [round(basis[i + 1] - basis[i], 2) for i in range(len(basis) - 1)]
    gh = [x for x in gh if GH_MIN_M <= x <= GH_MAX_M]

    # Geschoss-Marken der jeweils nächsten Niveau-Kote zuordnen — NUR als
    # zweite, unabhängige Quelle. Der naive "nächster Nachbar über alle
    # Koten" war gemessen falsch (EG → +2,80); hier wird gegen die
    # RANSAC-BESTÄTIGTEN Niveaus zugeordnet, nicht gegen alle Koten.
    zuordnung = {}
    for name, my, _mx in marken:
        best = None
        for _y, v, _x in inlier:
            d = abs(_y - my)
            if best is None or d < best[0]:
                best = (d, round(v, 2))
        if best and best[0] <= 120.0:
            zuordnung.setdefault(name, best[1])
    # PLAUSIBILITÄTS-GATE auf die Marken-Zuordnung: aufeinanderfolgende
    # Geschosse müssen um eine echte Geschosshöhe auseinanderliegen. Am
    # Velden-Schnitt ergab die Zuordnung KG -2,20 / EG +3,05 — das sind
    # 5,25 m und damit kein Geschoss, sondern eine falsch getroffene Kote.
    # Die Marken sind die SCHWÄCHERE Quelle; sind sie unstimmig, werden sie
    # ganz verworfen statt halbrichtig ausgewiesen.
    if len(zuordnung) >= 2:
        _w = sorted(zuordnung.values())
        if any(not (GH_MIN_M <= round(_w[i + 1] - _w[i], 2) <= GH_MAX_M)
               for i in range(len(_w) - 1)):
            zuordnung = {}

    return {
        "massstab_pt_m": round(massstab, 1),
        "massstab_label": f"1:{int(round(2834.6 / massstab))}",
        "niveaus_m": basis,
        "geschosshoehen_m": gh,
        "n_koten": len(koten),
        "n_gruppe": n_gruppe,
        "geschoss_marken": zuordnung,
        "quelle": "Höhenkoten (Text-Layer, byte-exakt)",
    }


def hinweis(erg):
    """Ein Satz für die Planansicht — was wurde gelesen, wie belegt ist es."""
    if not erg:
        return ""
    teile = [f"Schnitt gelesen: {erg['n_gruppe']} von {erg['n_koten']} "
             f"Höhenkoten liegen auf einer Geraden → Maßstab "
             f"{erg['massstab_label']} ({erg['massstab_pt_m']} pt/m)"]
    if erg.get("niveaus_m"):
        _n = ", ".join(f"{v:+.2f}".replace(".", ",") for v in erg["niveaus_m"][:8])
        teile.append(f"Höhen-Niveaus: {_n} m")
    if erg.get("geschosshoehen_m"):
        _g = ", ".join(f"{v:.2f}".replace(".", ",") for v in erg["geschosshoehen_m"])
        teile.append(f"Geschosshöhen daraus: {_g} m")
    if erg.get("geschoss_marken"):
        _m = " · ".join(f"{k} {v:+.2f}".replace(".", ",")
                        for k, v in sorted(erg["geschoss_marken"].items(),
                                           key=lambda t: t[1]))
        teile.append(f"beschriftete Geschosse: {_m} m")
    return ". ".join(teile) + "."
