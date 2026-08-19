"""RAUM-VERIFIKATION — der Plan validiert sich selbst (Nachzeichnen 2.0).

KERN-EINSICHT: Jeder Raum-Stempel im Plan trägt Fläche F und Umfang U BYTE-EXAKT
("Fl: 10,53 m²" — das ² ist ein eigener Superscript-Span; "U: 1 320,0 cm" mit
Tausender-LEERZEICHEN). Wenn das aus den Plan-Vektoren rekonstruierte Raum-Gebiet
F UND U gleichzeitig trifft (zwei unabhängige Werte), ist die Wand-Geometrie um
diesen Raum BEWIESEN — nicht geschätzt. Trifft es nicht, ist der Fehler LOKALISIERT.

PIPELINE (alles deterministisch, KEIN Vision):
  1. WAND-MASKE aus dem Linework, SCHRAFFUR-VERANKERT: echte Wände sind poché-
     schraffiert, Möbel nicht (empirisch bewiesen, s. Schraffur-Gate in vektor.py).
     Schraffur-Striche + nur die dunklen Kanten NAHE der Schraffur = Wände;
     Möbel-Linework fällt raus. (Wand-PAARE decken die Topologie nicht — gemessen:
     Innenwände fehlten fast komplett; rohes Linework zerhackt Räume mit Möbeln.)
  2. Öffnungs-VERSCHLÜSSE aus STUK/FPH (byte-exakt) + morphologisches CLOSING
     (Schraffur-Strich-Lücken überbrücken; Kanäle schmäler als echte Türen sind
     keine Durchgänge).
  3. MULTI-SOURCE-WATERSHED: alle Stempel + AUSSEN-Seeds fluten gleichzeitig —
     löst offene Durchgänge (Flur↔Wohnküche ohne Tür).
  4. LOCH-FÜLLUNG: Möbel-Inseln (Badewanne …) liegen IM Raum — ihre Fläche zählt
     zu F (so misst auch der Plan), und U wird die echte Wandlinie.
  5. F-GEFÜHRTE TASCHEN-ADOPTION: abgeriegelte Frei-Taschen (Phantom-Wand von
     schraffiertem Küchenblock) werden dem Nachbar-Raum zugeschlagen, WENN das
     dessen F Richtung Soll bewegt — die byte-exakte Soll-Fläche entscheidet.

LOG-ONLY: kein Eingriff in die Live-Mengen. Harness: scripts/test_raumverifikation.py
"""
import math
import os
import re
from collections import deque

_KOMPAKT_MIN = 3   # Kompaktheits-Schwelle des F-Ausgleichs (Ziel-Nachbarn von 8; Sweep: 3 minimiert U-Fehler bei exaktem F)

# Wörter, die im Raum-Stempel stehen, aber KEINE Raumnamen sind (Bodenbeläge/Material/
# Außenflächen-Beschriftungen — empirisch am WM-Plan gefunden)
# Bodenbeläge sind KEINE Raumnamen. Der Belag steht im Stempel zwischen Name
# und Flächenwert, also NÄHER am Wert — er gewinnt die Nächster-Span-Suche,
# wenn er nicht gesperrt ist. Diese Liste war auf den Wohnbau zugeschnitten:
# an einem gebauten Schulgrundriss hießen vier Klassenzimmer und das
# Lehrerzimmer "Linoleum" (Flächen byte-exakt, Namen falsch) — der Belag, den
# man im Wohnbau nie sieht. Darum jetzt die im österreichischen Hochbau
# üblichen Beläge quer durch alle Bauarten: Bildungs-, Gesundheits-,
# Gewerbe- und Industriebau.
# EHRLICHE GRENZE: das bleibt eine Sperrliste und ist damit nie vollständig.
# Sie ist die zweite Verteidigungslinie hinter der Bündigkeits-Regel; ein
# unbekannter Belag kostet einen Namen, nie eine Menge.
_KEIN_RAUMNAME = ("fliesen", "parkett", "laminat", "teppich", "estrich", "beton",
                  "betonplatten", "kies", "wiese", "rasen", "pflaster", "asphalt",
                  "holz", "vlies", "epoxy", "keramik", "stein", "feinstein",
                  # Bildungs-/Gesundheitsbau
                  "linoleum", "vinyl", "kautschuk", "pvc", "kork",
                  # Gewerbe-/Industriebau
                  "industrieboden", "hartstoff", "gussasphalt", "terrazzo",
                  "sichtbeton", "doppelboden", "hohlboden", "spachtelboden",
                  "beschichtung", "anhydrit", "zementestrich",
                  # Naturstein/Sonstiges
                  "marmor", "granit", "naturstein", "schiefer", "osb")
# Einheiten-Reste: beim Trennen von "24,52 m" bleibt ein nacktes "m" übrig und
# gewann als Raumname (TG-Plan: Raum "m", 21,21 m²). Ein Raum heißt nie so.
_EINHEIT_REST = {"m", "m2", "m²", "cm", "mm", "st", "stk", "lfm", "pa", "kg"}


def _ist_raumname(t):
    """Kann dieser Text-Span überhaupt ein Raumname sein?

    Zwei Buchstaben Minimum (WC/AR sind echte Raumnamen, ein nacktes 'm' nie)
    und keine Einheit. Bewusst getrennt von den Belag-/Code-Sperren, damit die
    Regel an BEIDEN Auswerte-Zweigen gleich gilt.
    """
    t = (t or "").strip()
    if len(t) < 2 or not re.match(r"^[A-Za-zÄÖÜäöüß]", t):
        return False
    return t.lower().rstrip(".:") not in _EINHEIT_REST

# Punkt-Dezimal ("Fl: 5.90m²", 1762788650811-Plan) UND Komma mit Tausender-Punkt.
# BF: = Bodenfläche (Polierplan-Konvention, AP.01: 6 von 9 Seeds fehlten sonst).
#
# SCHREIBWEISEN-SWEEP (scripts/mess_stempel_konventionen.py): an gebauten
# Stempeln gemessen las der Leser die vier Konventionen unserer echten Pläne
# vollständig — und von acht FREMDEN Schreibweisen genau eine. "NF:"
# (Nutzfläche) und "Fläche:" sind österreichischer Alltag, "qm" steht auf
# jedem älteren Plan. Wer so einen Plan hochlud, bekam NULL Räume, nicht
# etwa weniger.
#
# Ergänzt sind darum: Fläche/Flaeche, NF (Nutzfläche), '=' als Trenner und
# die Einheiten m² / m2 / qm.
# BEWUSST NICHT ergänzt:
#   'A:'  — zu mehrdeutig, 'A' bezeichnet auf Plänen Achsen und Ansichten
#   'WNF' — das ist der WOHNUNGS-Summenstempel (TOP 37 / Loggia / WNF 45,26),
#           der absichtlich ausgefiltert wird; als Flächen-Anker würde er die
#           Wohnungssummen als Phantom-Räume zurückbringen (am WM-Plan
#           gemessen, siehe Wohnungs-Stempel-Gate weiter unten)
_F_EINHEIT = r"(?:m\s*[²2]?|qm)"
# [.:=]{0,2} statt {0,1}: "Fl.:" traegt BEIDE Trennzeichen (Punkt und
# Doppelpunkt) — mit nur einem erlaubten Zeichen fiel diese Schreibweise
# komplett durch (0 von 4 Stempeln gelesen).
_F_ANKER = (r"(?:F[lL]\s*[.:=]{0,2}|BF\s*[.:=]{0,2}|NF\s*[.:=]{0,2}"
            r"|F\s*[.:=]|Fl[\u00e4a]che\s*[.:=]{0,2})")
_F_ZAHL = r"([0-9][0-9\s.]*,[0-9]+|[0-9]+\.[0-9]{1,2}|[0-9]+)"
_F_RX = re.compile(r"^" + _F_ANKER + r"\s*" + _F_ZAHL + r"\s*" + _F_EINHEIT,
                   re.I)
# Solo-Anker ("BF:" allein, Zahl als Tab-Spalte 20-28pt rechts — AP.01-Encoding)
_F_ANKER_RX = re.compile(r"^" + _F_ANKER + r"$", re.I)
_U_ANKER_RX = re.compile(r"^U\s*[.:]$", re.I)
# Bauteil-/Wandtyp-Codes sind KEINE Raumnamen (stehen auf Polierplänen näher
# am Stempel als der Name und gewannen die Nächster-Span-Suche: 'IW 2' statt Bad)
# \b allein reicht nicht: bei 'RDOK-0,24' trennt der Bindestrich, bei 'OK0,71'
# steht die Ziffer direkt am Buchstaben — dort gibt es keine Wortgrenze, der
# Code rutschte als Raumname durch (am WM-Plan gemessen).
_CODE_RX = re.compile(r"^(?:IW|AW|TW|STB|RBL|STUK|RPH|FBH|FFB|RH|BF"
                      r"|FFOK|RDOK|RFOK|FOK|OK|UK)(?:\b|(?=[0-9]))",
                      re.I)   # + Höhenkoten (WM: 'RDOK-0,24' gewann sonst als Name)
_U_CM_RX = re.compile(r"U\s*[:=]?\s*([0-9][0-9\s.]*,?[0-9]*)\s*cm", re.I)
_U_M_RX = re.compile(r"U\s*[:=]?\s*([0-9]+,[0-9]+)\s*m\b", re.I)


def _num(s):
    try:
        s2 = s.strip()
        if re.match(r"^[0-9]+\.[0-9]{1,2}$", s2):
            return float(s2)    # Punkt-DEZIMAL ("5.90"), kein Tausender-Punkt
        return float(s.replace(" ", "").replace(" ", "").replace(".", "").replace(",", "."))
    except (ValueError, AttributeError):
        return None


# ────────────────────────────────────────────────────────────────────
# Byte-exakte Raum-Stempel (F + U + Position)
# ────────────────────────────────────────────────────────────────────
def raum_stempel(page, box):
    bx0, bx1, by0, by1 = box
    spans = []
    for block in page.get_text("dict").get("blocks", []):
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                txt = (span.get("text") or "").strip()
                if not txt:
                    continue
                bb = span.get("bbox") or (0, 0, 0, 0)
                cx, cy = (bb[0] + bb[2]) / 2.0, (bb[1] + bb[3]) / 2.0
                if bx0 <= cx <= bx1 and by0 <= cy <= by1:
                    spans.append({"text": txt, "cx": cx, "cy": cy,
                                  "x0": bb[0], "x1": bb[2],
                                  "h": max(1.0, bb[3] - bb[1])})
    # GEZIELTER SPLIT-ZAHL-JOIN: manche Encoder trennen MITTEN in der Zahl
    # ("Fl: 64." + "15m²", 1762788650811). Nur joinen wenn der linke Span auf
    # Ziffer+[.,] ENDET und der rechte mit Ziffer BEGINNT (der breite Join
    # regressierte Angerer 4/9→3/9 — U-/Namens-Zuordnung hängt an Span-Geometrie).
    # ANKER-JOIN (AP.01-Polierplan): "BF:" steht als SOLO-Span, die Zahl folgt
    # als Tab-Spalte 20-28pt rechts — verschmelzen, damit _F_RX greift.
    # Angerer-sicher: dessen Stempel ('Fl: 10,53 m') sind nie Solo-Anker.
    for sp in spans:
        if not _F_ANKER_RX.match(sp["text"]):
            continue
        rechts = sorted((s2 for s2 in spans if s2 is not sp and s2["text"]
                         and abs(s2["cy"] - sp["cy"]) < 2.5
                         and -0.5 <= s2["x0"] - sp["x1"] < 40.0
                         and re.match(r"^[0-9]", s2["text"])),
                        key=lambda s2: s2["x0"])
        if rechts:
            sp["text"] = sp["text"] + " " + rechts[0]["text"]
            sp["x1"] = rechts[0]["x1"]
            rechts[0]["text"] = ""
    # VERTIKAL-JOIN (rotierte ArchiCAD-/GSPublisher-Stempel, TG-Plan: 'F:' /
    # 'U:' stehen als Zeile, der WERT-Span darüber, |dcx|<6 / dy 0-60 — exakt
    # die Konvention der Produktions-Rotated-Claims). Nur wenn der
    # horizontale Join nichts fand.
    for sp in spans:
        if not (sp["text"] and (_F_ANKER_RX.match(sp["text"])
                                or _U_ANKER_RX.match(sp["text"]))):
            continue
        oben = sorted((s2 for s2 in spans if s2 is not sp and s2["text"]
                       and abs(s2["cx"] - sp["cx"]) < 6.0
                       and 0 < sp["cy"] - s2["cy"] <= 60.0
                       and re.match(r"^[0-9]", s2["text"])),
                      key=lambda s2: sp["cy"] - s2["cy"])
        if oben:
            sp["text"] = sp["text"] + " " + oben[0]["text"]
            sp["_vjoin"] = round(sp["cy"] - oben[0]["cy"], 1)
            oben[0]["text"] = ""
    spans = [s2 for s2 in spans if s2["text"]]
    for sp in spans:
        if not re.search(r"[0-9][.,]$", sp["text"]):
            continue
        for _runde in range(3):     # kettenweise: 'Fl: 64.'+'1'+'5m²' (3 Spans!)
            rechts = sorted((s2 for s2 in spans if s2 is not sp and s2["text"]
                             and abs(s2["cy"] - sp["cy"]) < 2.5
                             and -0.5 <= s2["x0"] - sp["x1"] < 6.0
                             and re.match(r"^[0-9]", s2["text"])),
                            key=lambda s2: s2["x0"])
            if not rechts:
                break
            sp["text"] = sp["text"] + rechts[0]["text"]
            sp["x1"] = rechts[0]["x1"]
            rechts[0]["text"] = ""
    spans = [s2 for s2 in spans if s2["text"]]
    def _u_unter(s):
        """'U: xx,xx m'-Span direkt unter dem F-Span (byte-exakt) — gemeinsam für
        Haupt- UND Fallback-Zweig (WM-Sezierung: 20/21 Fallback-Stempel tragen U,
        der harte u_m=None ließ abgedriftete Regionen unsichtbar 'verifiziert')."""
        u, best_dy = None, 1e9
        for s2 in spans:
            dy = s2["cy"] - s["cy"]
            # unter dem F-Span (klassisch) ODER in derselben Zeile daneben
            # (rotierte Stempel: 'F: … U: …'-Anker nebeneinander)
            gleiche_zeile = abs(dy) < 3 and 0 < abs(s2["cx"] - s["cx"]) <= 90
            if not gleiche_zeile and (abs(s2["cx"] - s["cx"]) > 40
                                      or not (0 < dy <= 30)):
                continue
            dy = abs(dy)
            if dy >= best_dy:
                continue
            mu = _U_CM_RX.search(s2["text"])
            v = _num(mu.group(1)) if mu else None
            if v and 100 <= v <= 30000:
                u, best_dy = v / 100.0, dy
                continue
            mu = _U_M_RX.search(s2["text"])
            v = _num(mu.group(1)) if mu else None
            if v and 1 <= v <= 300:
                u, best_dy = v, dy
        return u

    out = []
    for s in spans:
        mf = _F_RX.search(s["text"])
        if not mf:
            continue
        f = _num(mf.group(1))
        # Deckel 3000 statt 500: TG-Hallen tragen 555,90+ m² (Velden gemessen);
        # Zahlen-Müll fängt weiterhin der m²-Kontext der RX
        if not f or f < 0.5 or f > 3000:
            continue
        u = _u_unter(s)
        name, best = None, 1e9
        for s2 in spans:
            if s2 is s or not _ist_raumname(s2["text"]):
                continue
            if _CODE_RX.match(s2["text"]):
                continue    # Wandtyp-/Bauteil-Code, kein Raumname (AP.01: 'IW 2')
            if re.match(r"^[FUHB]\s*[.:]", s2["text"]):
                continue    # F:/U:/H:/B:-Anker-Zeilen (rotierte Stempel)
            _t0 = s2["text"].strip().lower()
            if any(_t0.startswith(b2) for b2 in _KEIN_RAUMNAME):
                continue    # Belag ist kein Raumname (TG: 'Fliesen' gewann)
            dy = s["cy"] - s2["cy"]
            dy_max = 32 + (s.get("_vjoin") or 0)   # rotiert: Name über dem Wert
            if 0 < dy < dy_max and abs(s2["cx"] - s["cx"]) < 80 and dy < best:
                best, name = dy, s2["text"]
        out.append({"name": name or "?", "f_m2": f, "u_m": u, "cx": s["cx"], "cy": s["cy"]})

    # FALLBACK (Büro-Format ohne "Fl:"-Anker, z.B. AU/WM): nackte "88,11 m"-Spans sind
    # nur dann Flächen, wenn DIREKT daneben ein eigener "²"-Span liegt (das ² ist als
    # Superscript ein separater Span) — unterscheidet Flächen von Längenangaben.
    #
    # DIE SCHWELLE IST NEU, und sie ist wichtiger als sie aussieht. Vorher stand
    # hier "if not out:" — ein EINZIGER Treffer des Anker-Zweigs schaltete den
    # Fallback komplett ab. Gemessen beim Versuch, 'WNF' als Flächen-Anker
    # aufzunehmen: der WM-Plan fiel von 77 Stempeln auf 5, weil vier Wohnungs-
    # Summenstempel ("TOP 25 · WNF 45,26 m²") anschlugen und damit die 77 echten
    # Raumstempel des Büro-Formats verdrängten. Nicht 77+4, sondern 5.
    #
    # Das ist eine Falle für JEDE Anker-Erweiterung: ein Plan im Büro-Format,
    # der irgendwo ein einzelnes "NF:" oder "Fläche:" im Plankopf trägt, hätte
    # still ALLE Räume verloren. Darum greift der Fallback jetzt auch, wenn der
    # Anker-Zweig nur eine Handvoll fand — ein Grundriss mit drei Räumen ist
    # selten, ein Streutreffer häufig. Die Ergebnisse werden zusammengeführt,
    # Doppelte nach Position verworfen (der Anker-Fund gewinnt: er trägt einen
    # ausdrücklichen Flächen-Marker).
    _anker_funde = list(out)
    if len(out) < 5:
        hoch2 = [s2 for s2 in spans if len(s2["text"]) == 1 and s2["text"] in ("²", "2")]
        nackt_rx = re.compile(r"^([0-9]{1,3},[0-9]{1,2})\s*m$")
        # "qm" ist eindeutig Quadratmeter — anders als das nackte "m", das
        # auch eine Laenge sein kann. Darum braucht diese Schreibweise
        # KEINEN hochgestellten ²-Nachbar-Span als Beweis.
        qm_rx = re.compile(r"^([0-9]{1,3},[0-9]{1,2})\s*qm$", re.I)
        for s in spans:
            m2 = nackt_rx.match(s["text"])
            _ist_qm = False
            if not m2:
                m2 = qm_rx.match(s["text"])
                _ist_qm = bool(m2)
            if not m2:
                continue
            f = _num(m2.group(1))
            if not f or f < 1.0 or f > 500:
                continue
            if not _ist_qm and not any(
                    0 < (h["cx"] - s["cx"]) < 60 and abs(h["cy"] - s["cy"]) < 8
                    for h in hoch2):
                continue    # kein ²-Nachbar → Länge, keine Fläche
            # WOHNUNGS-STEMPEL-GATE (WM: 'TOP 25 / Loggia 11,25 / WNF 45,26 /
            # 56,51 m²' — der Summen-Seed flutete den Watershed als 'Loggia
            # 56,51'): Wohnungs-Stempel = Flächen-SPALTE (weitere m²-Werte
            # exakt übereinander, |dcx|<6) + 'TOP n'-Header im Umkreis. BEIDE
            # Signale nötig — TOP-Nähe allein fraß den echten Vorraum-Stempel
    # daneben (98pt), Flächen-Zählung allein scheiterte an Längen-Spans.
            spalte = any(s2 is not s and abs(s2["cx"] - s["cx"]) < 6
                         and 0 < abs(s2["cy"] - s["cy"]) <= 30
                         and nackt_rx.match(s2["text"]) for s2 in spans)
            top_nah = any(abs(s2["cy"] - s["cy"]) < 60
                          and abs(s2["cx"] - s["cx"]) < 150
                          and re.match(r"^TOP\b", s2["text"], re.I)
                          for s2 in spans)
            if spalte and top_nah:
                continue
            # Mehrzeilige Stempel-Blöcke (Wohn-/Nutzfläche …): größten Wert im Umkreis behalten
            dup = next((o for o in out if abs(o["cx"] - s["cx"]) < 25
                        and abs(o["cy"] - s["cy"]) < 25), None)
            if dup:
                if f > dup["f_m2"]:
                    dup.update({"f_m2": f, "cx": s["cx"], "cy": s["cy"]})
                continue
            name, best = None, 1e9
            # BÜNDIGKEIT: ein Raumstempel ist eine Textsäule — der Name steht
            # ÜBER dem Wert und ist mit ihm bündig (links, mittig oder rechts).
            # Eine Zeichnungsbeschriftung DANEBEN ist kein Name. Am WM-Plan
            # gemessen: 'Lift D' stand auf derselben Zeile 37pt rechts vom
            # Wert und schlug das 'Stiegenhaus' darüber, weil der waagrechte
            # Abstand nur mit 0,3 gewichtet wurde. Ergebnis: das Stiegenhaus
            # hieß 'Lift' — und bekam damit die Gewerke eines Aufzugsschachts.
            # Die Schranke hängt an der Schrifthöhe, nicht an festen Punkten,
            # damit sie auf jedem Planmaßstab gleich streng ist.
            _buend = max(18.0, 2.2 * s.get("h", 10.0))
            for s2 in spans:
                if s2 is s or not _ist_raumname(s2["text"]) \
                        or len(s2["text"].strip()) < 3:
                    continue
                # Bodenbeläge/Materialien sind KEINE Raumnamen (standen im Stempel näher
                # als der Name — gemessen am WM-Plan: 'Fliesen', 'Betonplatten' …)
                t0 = s2["text"].strip().lower()
                if any(t0.startswith(b) for b in _KEIN_RAUMNAME):
                    continue
                if _CODE_RX.match(s2["text"]):
                    continue    # Bauteil-/Koten-Code (WM: 'RDOK-0,24' statt Vorraum)
                d = abs(s["cy"] - s2["cy"]) + abs(s["cx"] - s2["cx"]) * 0.3
                if not (s2["cy"] < s["cy"] + 5 and d < 90):
                    continue
                # bündig auf EINER der drei Kanten (links/mittig/rechts)?
                if min(abs(s["cx"] - s2["cx"]), abs(s["x0"] - s2["x0"]),
                       abs(s["x1"] - s2["x1"])) <= _buend:
                    if d < best:
                        best, name = d, s2["text"]
            # KEIN Rückfall auf "irgendeinen Kandidaten": gemessen liefert der
            # 'BD 25 /25', 'C/D/E - IW03', 'RB266' — Bauteil-Beschriftungen,
            # die als Raumname in die Gewerkezuordnung gehen. Ein FALSCHER
            # Name ist schlechter als keiner; '?' ist die ehrliche Antwort und
            # das Frontend bietet dafür die Nachbenennung an.
            out.append({"name": name or "?", "f_m2": f, "u_m": _u_unter(s),
                        "cx": s["cx"], "cy": s["cy"]})
        # ZUSAMMENFÜHREN statt ersetzen: die Anker-Funde von oben bleiben, der
        # Fallback ergänzt nur, was er an anderer Stelle findet. Doppelte
        # (derselbe Stempel über beide Wege gelesen) fallen nach Position raus —
        # der Anker-Fund gewinnt, weil er einen ausdrücklichen Flächen-Marker
        # trägt und nicht nur eine nackte Zahl mit ²-Nachbar.
        if _anker_funde:
            _neu = [x for x in out if x not in _anker_funde
                    and not any(abs(x["cx"] - a["cx"]) < 25
                                and abs(x["cy"] - a["cy"]) < 25
                                for a in _anker_funde)]
            out = _anker_funde + _neu
    return out


# ────────────────────────────────────────────────────────────────────
# Raster-Werkzeuge
# ────────────────────────────────────────────────────────────────────
def _dist_bfs(src_mask, W, H, r_max):
    """Multi-Source-BFS-Distanz (4-conn) von allen gesetzten Zellen, gekappt bei r_max."""
    INF = 32767
    dist = [INF] * (W * H)
    q = deque()
    for idx in range(W * H):
        if src_mask[idx]:
            dist[idx] = 0
            q.append(idx)
    while q:
        idx = q.popleft()
        d = dist[idx] + 1
        if d > r_max:
            continue
        i, j = idx % W, idx // W
        for di, dj in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            ni, nj = i + di, j + dj
            if 0 <= ni < W and 0 <= nj < H and dist[nj * W + ni] > d:
                dist[nj * W + ni] = d
                q.append(nj * W + ni)
    return dist


def _closing(grid, W, H, r_cells):
    """Morphologisches Schließen: versiegelt nur Kanäle schmäler als 2r (kein Flächen-Verlust)."""
    d1 = _dist_bfs(grid, W, H, r_cells)
    dil = bytearray(1 if d1[i] <= r_cells else 0 for i in range(W * H))
    frei = bytearray(0 if dil[i] else 1 for i in range(W * H))
    d2 = _dist_bfs(frei, W, H, r_cells)
    return bytearray(1 if (dil[i] and d2[i] > r_cells) else 0 for i in range(W * H))


class _Raster:
    def __init__(self, box, ptm, zelle_m=0.02):
        self.bx0, self.bx1, self.by0, self.by1 = box
        self.ptm = ptm
        self.cell = zelle_m * ptm
        self.zm = zelle_m
        # KEIN Ursprungs-Snap hier — zweimal gemessen, zweimal anders:
        # Seiten-Gitter-Snap heilte die IoU-Beweise (3->5), wuerfelte aber
        # ALLE schwellennahen Tuer-Rundungen neu (28->33 undicht). Die
        # Phasen-Treue stellt stattdessen der AUFRUFER her: die Render-Box
        # wird in GANZEN Zellen von der Mess-Box aus erweitert
        # (nachzeichnen, "phasengleiche Erweiterung") — damit ist die
        # Zellzuordnung im alten Bereich byte-identisch zur Zeit VOR der
        # Box-Erweiterung, und weder Tueren noch Beweise wuerfeln neu.
        self.W = int((self.bx1 - self.bx0) / self.cell) + 2
        self.H = int((self.by1 - self.by0) / self.cell) + 2

    def ij(self, x, y):
        return int((x - self.bx0) / self.cell), int((y - self.by0) / self.cell)

    def line(self, grid, x0, y0, x1, y1):
        n = max(1, int(math.hypot(x1 - x0, y1 - y0) / self.cell))
        for k in range(n + 1):
            t = k / n
            i, j = self.ij(x0 + (x1 - x0) * t, y0 + (y1 - y0) * t)
            if 0 <= i < self.W and 0 <= j < self.H:
                grid[j * self.W + i] = 1

    def rect(self, grid, x0, y0, x1, y1):
        i0, j0 = self.ij(min(x0, x1), min(y0, y1))
        i1, j1 = self.ij(max(x0, x1), max(y0, y1))
        i0, i1 = max(0, i0), min(self.W - 1, i1)
        j0, j1 = max(0, j0), min(self.H - 1, j1)
        for j in range(j0, j1 + 1):
            base = j * self.W
            for i in range(i0, i1 + 1):
                grid[base + i] = 1


def wand_maske(rst, dark_segs, hatch_segs, oeffnungen,
               hatch_dilat_m=0.10, closing_m=0.08, moebel_zonen=None, versch_out=None,
               boegen=None, fill_rects=None, paar_fallback=False, stuetzen=None,
               hatch_out=None):
    """Schraffur-verankerte Wand-Maske: Schraffur + dunkle Kanten NAHE der Schraffur
    (Möbel haben keine Poché) + Öffnungs-Verschlüsse + Closing.
    fill_rects: Wand-Körper als Flächen-Fills (Ziegel-Ton-Polygone mancher
    Wand-Grundrisse) — direkt Wand UND Anker-Basis wie Schraffur."""
    W, H = rst.W, rst.H
    hm = bytearray(W * H)
    for s in hatch_segs:
        rst.line(hm, s[0], s[1], s[2], s[3])
    for (fx0, fy0, fx1, fy1) in (fill_rects or []):
        rst.rect(hm, fx0, fy0, fx1, fy1)
    if hatch_out is not None:
        hatch_out[:] = hm      # rohe Poché-Maske (fuer den Durchgang-Kredit)
    r = max(1, int(hatch_dilat_m / rst.zm))
    dh = _dist_bfs(hm, W, H, r)
    hm_d = bytearray(1 if dh[i] <= r else 0 for i in range(W * H))

    grid = bytearray(hm)
    # TÜR-ZONEN: das aufgeklappte Türblatt + der Schwenkbogen werden sonst als "Wand"
    # verankert (Bad-Sezierung: Grenze beulte um das Türblatt). In der Tür-Zone keine
    # dunklen Kanten brennen — der Verschluss-Balken dichtet die Wandlinie ohnehin.
    tuer_zonen = []
    def _tuer_spalt(ci0, cj0, b_m, achse):
        """Die Zeile/Spalte mit TUER-STRUKTUR: Wand - Luecke - Wand.

        SUCHFENSTER 0,70 m — gemessen und so belassen. Naheliegend waere
        1,0 m: der Textanker streut bis 1,13 m neben die Tuer, und 23 der
        verbliebenen 29 undichten Tueren BEKAMEN einen Balken, der in einer
        anderen Zeile sass als das Leck. Genau dieser Schluss wurde geprueft
        (nur im Zweitdurchgang auf 1,0 m geweitet) und ist WIDERLEGT:
        undicht 29 -> 35. Ein weiteres Fenster findet Phantom-Spalte —
        Wand-Luecke-Wand-Strukturen, die keine Tuer sind — und mauert sie zu,
        was neue Lecks erzeugt. Nicht erneut weiten.
        """
        b_zell = max(3, int(round((b_m or 0.9) * rst.ptm / rst.cell)))
        cap = max(4, int(round(1.6 * rst.ptm / rst.cell)))
        fen2 = max(2, int(round(0.70 * rst.ptm / rst.cell)))
        sp_min = max(3, int(round(0.45 * rst.ptm / rst.cell)))
        sp_max = int(round(2.3 * rst.ptm / rst.cell))
        best = None
        for off in range(-fen2, fen2 + 1):
            if achse == "h":
                jj = cj0 + off
                if not (0 <= jj < H):
                    continue
                li = re2 = None
                for d in range(cap + 1):
                    if li is None and 0 <= ci0 - d < W and grid[jj * W + ci0 - d]:
                        li = ci0 - d
                    if re2 is None and 0 <= ci0 + d < W and grid[jj * W + ci0 + d]:
                        re2 = ci0 + d
                    if li is not None and re2 is not None:
                        break
                if li is None or re2 is None:
                    continue
                sp, fest, lo, hi = re2 - li - 1, jj, li, re2
            else:
                ii = ci0 + off
                if not (0 <= ii < W):
                    continue
                ob = un = None
                for d in range(cap + 1):
                    if ob is None and 0 <= cj0 - d < H and grid[(cj0 - d) * W + ii]:
                        ob = cj0 - d
                    if un is None and 0 <= cj0 + d < H and grid[(cj0 + d) * W + ii]:
                        un = cj0 + d
                    if ob is not None and un is not None:
                        break
                if ob is None or un is None:
                    continue
                sp, fest, lo, hi = un - ob - 1, ii, ob, un
            if not (sp_min <= sp <= sp_max):
                continue
            sc = (abs(sp - b_zell), abs(off))
            if best is None or sc < best[0]:
                best = (sc, fest, lo, hi)
        return (best[1], best[2], best[3]) if best else None

    for o in (oeffnungen or []):
        if o.get("typ") == "tuer":
            r_z = (o.get("breite_m") or 0.9) * 0.9 * rst.ptm
            tuer_zonen.append((o["cx"], o["cy"], r_z * r_z))
    # BOGEN-ZONEN: der Tür-Aufschlagbogen kennt Angelpunkt + Radius byte-genau —
    # Kreis um den Angelpunkt (1,15×r) überdeckt Türblatt + Schwenkbogen exakt
    # (präziser zentriert als die Text-Zonen, deren Anker bis 0,63m daneben liegt).
    for bg in (boegen or []):
        r_z = bg["r_m"] * 1.15 * rst.ptm
        tuer_zonen.append((bg["hinge"][0], bg["hinge"][1], r_z * r_z))

    # MÖBEL-ZONEN (Waschen-Sezierung: Grenze schlängelte um wandständige WM/DR-Geräte,
    # deren Kanten <10cm an der Poché liegen): geschlossene Geräte-Rechtecke werden wie
    # Tür-Zonen behandelt — Kanten nicht brennen; die Poché (Wand-Kern) brennt weiter,
    # echte Pfeiler bleiben also Wand.
    zonen = list(tuer_zonen) + list(moebel_zonen or [])

    def in_tuerzone(mx, my):
        for (zx, zy, r2) in zonen:
            if (mx - zx) ** 2 + (my - zy) ** 2 <= r2:
                return True
        return False

    unverankert = []
    for s in dark_segs:
        n = max(2, int(math.hypot(s[2] - s[0], s[3] - s[1]) / rst.cell))
        hits = 0
        probes = 0
        for k in range(0, n + 1, max(1, n // 8)):
            t = k / n
            i, j = rst.ij(s[0] + (s[2] - s[0]) * t, s[1] + (s[3] - s[1]) * t)
            probes += 1
            if 0 <= i < W and 0 <= j < H and hm_d[j * W + i]:
                hits += 1
        if probes and hits / probes >= 0.55:
            if zonen and in_tuerzone((s[0] + s[2]) / 2.0, (s[1] + s[3]) / 2.0):
                continue    # Türblatt/-bogen — keine Wand
            rst.line(grid, s[0], s[1], s[2], s[3])
        else:
            unverankert.append(s)

    # ── STÜTZEN-KNOTEN-SCHLUSS (Wandknoten-Sezierung, byte-exakt geankert):
    # R60-verkapselte Stützen sitzen in 0,6-0,9m-Buchten zwischen pochierten
    # Wandbändern; die schließende Kapselungs-Front ist eine EINZELNE dünne
    # unpochierte Linie (Trockenbau trägt ORTHOGONALE Dämm-Kreuzschraffur —
    # für wand_poche unsichtbar, das nur Diagonalen sammelt). Kurze achs-
    # parallele unverankerte Linien, deren BEIDE Enden in der Poché-Dilatation
    # ankern UND deren Mitte ≤1,8m an einem 'Stütze…'-Text-Span liegt, brennen
    # als Rect (line-Sampling ließ 1-Zell-Löcher, gemessen). Das Stützen-Gate
    # ist ZWINGEND: ohne zerschnitten Treppen/Duschwände/Pflasterkanten
    # 4 Räume (43→41 gemessen). Ohne Stütze-Spans (TG: 0) beweisbar inert.
    if stuetzen:
        _kn_rc = max(1, int(round(0.08 / rst.zm)))
        _kn_r2 = (1.8 * rst.ptm) ** 2

        def _kn_pnah(x, y):
            ci, cj = rst.ij(x, y)
            for nj in range(max(0, cj - _kn_rc), min(H, cj + _kn_rc + 1)):
                base = nj * W
                for ni in range(max(0, ci - _kn_rc), min(W, ci + _kn_rc + 1)):
                    if hm_d[base + ni]:
                        return True
            return False

        for s in unverankert:
            dx, dy = abs(s[2] - s[0]), abs(s[3] - s[1])
            _L = math.hypot(dx, dy)
            if not (0.4 * rst.ptm <= _L <= 1.5 * rst.ptm):
                continue
            if min(dx, dy) > 0.06 * rst.ptm:
                continue
            _mx, _my = (s[0] + s[2]) / 2.0, (s[1] + s[3]) / 2.0
            if not any((_mx - ax) ** 2 + (_my - ay) ** 2 <= _kn_r2
                       for (ax, ay) in stuetzen):
                continue
            if zonen and in_tuerzone(_mx, _my):
                continue
            if _kn_pnah(s[0], s[1]) and _kn_pnah(s[2], s[3]):
                rst.rect(grid, min(s[0], s[2]), min(s[1], s[3]),
                         max(s[0], s[2]), max(s[1], s[3]))

    # WAND-PAAR-FALLBACK (nur FERTIG-Ebene, Bad-Anatomie-Sezierung): unpochierte
    # Doppellinien (Installations-/Vorwände, leichte Trennwände) sind die
    # FERTIG-Grenzen — Stempel messen Fertigmaße. Auf der ROHBAU-Ebene (Default
    # False) bleibt alles byte-identisch; die Fälle sind NUR auf Ebenen-Ebene
    # trennbar (gemessen: jedes lokale Paar-Gate regressiert einen der Pläne —
    # Poché-Gate: Angerer 6/9 aber WM 4→3; Grid-Gate: tötet die Bad-Heilung;
    # Mittellinie: verfehlt den raumseitigen Streifen geometrisch).
    if paar_fallback:
        _ACHS = 0.6
        min_l = 0.6 * rst.ptm
        kand = {"h": [], "v": []}
        for s in unverankert:
            dx, dy = abs(s[2] - s[0]), abs(s[3] - s[1])
            if math.hypot(dx, dy) < min_l:
                continue
            mx_, my_ = (s[0] + s[2]) / 2.0, (s[1] + s[3]) / 2.0
            if zonen and in_tuerzone(mx_, my_):
                # Tür-Zonen (Text+Bogen) vetoen nur KURZE Linien (<1,5m =
                # Türblatt r_m≤1,1m); lange Fassaden-/Brüstungslinien durch
                # die Zone sind Wände (WM: Südglasfront 3,04m vetoiert →
                # Zimmer lief in die Loggia). Möbel-Zonen: volles Veto.
                in_moebel = any((mx_ - zx) ** 2 + (my_ - zy) ** 2 <= r2
                                for (zx, zy, r2) in (moebel_zonen or []))
                if in_moebel or math.hypot(s[2] - s[0], s[3] - s[1]) < 1.5 * rst.ptm:
                    continue
            if dy <= _ACHS and dx > _ACHS:
                kand["h"].append((min(s[0], s[2]), max(s[0], s[2]), (s[1] + s[3]) / 2.0))
            elif dx <= _ACHS and dy > _ACHS:
                kand["v"].append((min(s[1], s[3]), max(s[1], s[3]), (s[0] + s[2]) / 2.0))
        d_lo, d_hi = 0.06 * rst.ptm, 0.30 * rst.ptm
        paare = []
        for a in ("h", "v"):
            ks = sorted(kand[a], key=lambda t: t[2])
            for i1 in range(len(ks)):
                lo1, hi1, q1 = ks[i1]
                for i2 in range(i1 + 1, len(ks)):
                    lo2, hi2, q2 = ks[i2]
                    dq = q2 - q1
                    if dq > d_hi:
                        break
                    if dq < d_lo:
                        continue
                    lo, hi = max(lo1, lo2), min(hi1, hi2)
                    if hi - lo >= min_l:
                        paare.append((a, lo, hi, (q1 + q2) / 2.0, dq))
        rz = max(1, int(0.30 * rst.ptm / rst.cell))

        def _wand_nahe(x, y):
            ci, cj = rst.ij(x, y)
            for nj in range(max(0, cj - rz), min(H, cj + rz + 1)):
                base = nj * W
                for ni in range(max(0, ci - rz), min(W, ci + rz + 1)):
                    if grid[base + ni]:
                        return True
            return False

        offen = paare
        for _runde in range(4):
            rest, neu = [], 0
            for p in offen:
                a, lo, hi, mitte, dq = p
                e1 = (lo, mitte) if a == "h" else (mitte, lo)
                e2 = (hi, mitte) if a == "h" else (mitte, hi)
                # BEIDE Enden andocken (einseitig = Möbel, gemessen)
                if _wand_nahe(*e1) and _wand_nahe(*e2):
                    if a == "h":
                        rst.rect(grid, lo, mitte - dq / 2.0, hi, mitte + dq / 2.0)
                    else:
                        rst.rect(grid, mitte - dq / 2.0, lo, mitte + dq / 2.0, hi)
                    neu += 1
                else:
                    rest.append(p)
            offen = rest
            if not neu:
                break

    # TÜR-VERSCHLÜSSE AUS BOGEN-GEOMETRIE (v3 — der Plan zeichnet die Tür selbst):
    # Öffnungslinie = Strecke Angelpunkt → geschlossenes Radius-Ende. Welches Ende
    # 'zu' ist, entscheidet die Poché (das geschlossene Ende liegt IN der Wandflucht,
    # die offene Blattspitze im Freiraum). Byte-genau in Lage UND Breite — ersetzt
    # den Text-Anker-Snap (gemessen: Text bis 0,63m neben der Tür).
    bogen_ok = []
    for bg in (boegen or []):
        hx, hy = bg["hinge"]

        def _poche_naehe(pt, r_such=0.28):
            r2 = (r_such * rst.ptm) ** 2
            return sum(1 for h in hatch_segs
                       if ((h[0] + h[2]) / 2 - pt[0]) ** 2
                       + ((h[1] + h[3]) / 2 - pt[1]) ** 2 <= r2)

        na, nb = _poche_naehe(bg["a"]), _poche_naehe(bg["b"])
        if min(na, nb) >= 5 and max(na, nb) < 1.5 * min(na, nb):
            # AMBIGES Endpunkt-Poché (Tür an Wand-Ecke, WM 24:21 gemessen —
            # der Seal brannte QUER durch den Vorraum und trennte den
            # Eingangs-Arm ab): die LINIEN-Abdeckung auf der Poché-Dilatation
            # entscheidet (die geschlossene Türlinie liegt in der Wandflucht).
            def _lin_cov(ende):
                n_p = 20
                hits = 0
                for k in range(n_p + 1):
                    t = k / n_p
                    i, j = rst.ij(hx + (ende[0] - hx) * t, hy + (ende[1] - hy) * t)
                    if 0 <= i < W and 0 <= j < H and hm_d[j * W + i]:
                        hits += 1
                return hits / (n_p + 1.0)

            _ca, _cb = _lin_cov(bg["a"]), _lin_cov(bg["b"])
            if abs(_ca - _cb) >= 0.10:
                na, nb = (1, 0) if _ca > _cb else (0, 1)
        if na == nb:
            # LOGGIA-/LEICHTWAND-TÜREN (WM: na=nb=0, beidseitig keine Poché —
            # 3 Bögen blieben unversiegelt, Zimmer liefen in die Loggia):
            # CAD-Wahrheit als Richtungs-Quelle — die geschlossene Türlinie
            # liegt IN der Wandflucht, JENSEITS des zu-Endes läuft die Wand
            # weiter (Fassade/Brüstung im grid); jenseits der Blattspitze ist
            # Freiraum. Verlängerungs-Probe (Punkt-Nähe scheiterte: beide
            # Enden liegen nahe der Fassade, gemessen WM 4V→3V).
            def _flucht_fort(ende):
                dx, dy = ende[0] - hx, ende[1] - hy
                L0 = math.hypot(dx, dy) or 1.0
                dx, dy = dx / L0, dy / L0
                n_w = 0
                for dm in (0.15, 0.35, 0.55, 0.75, 0.95):
                    i, j = rst.ij(ende[0] + dx * dm * rst.ptm,
                                  ende[1] + dy * dm * rst.ptm)
                    if 0 <= i < W and 0 <= j < H and grid[j * W + i]:
                        n_w += 1
                return n_w

            na, nb = _flucht_fort(bg["a"]), _flucht_fort(bg["b"])
            if os.environ.get("TUER_DEBUG"):
                print(f"[bogen] kandidat hinge=({hx:.0f},{hy:.0f}) na={na} nb={nb}")
            if na == nb:
                # TIE-BREAKER: kollineare DUNKLE SEGMENTE jenseits der Enden
                # (CAD-Linien statt Grid — unpochierte Fassaden-/Fensterbänder
                # sind zum Seal-Zeitpunkt noch nicht im Grid; WM Bogen[12]
                # 13:0 gemessen).
                def _seg_fort(ende):
                    dx, dy = ende[0] - hx, ende[1] - hy
                    L0 = math.hypot(dx, dy) or 1.0
                    dx, dy = dx / L0, dy / L0
                    n = 0
                    for s in dark_segs:
                        mx, my = (s[0] + s[2]) / 2, (s[1] + s[3]) / 2
                        t = ((mx - ende[0]) * dx + (my - ende[1]) * dy) / rst.ptm
                        q = abs(-(mx - ende[0]) * dy + (my - ende[1]) * dx) / rst.ptm
                        if 0.05 <= t <= 1.0 and q <= 0.15:
                            sdx, sdy = s[2] - s[0], s[3] - s[1]
                            sl = math.hypot(sdx, sdy) or 1.0
                            if abs((sdx * dx + sdy * dy) / sl) >= 0.9396926:
                                n += 1
                    return n

                na, nb = _seg_fort(bg["a"]), _seg_fort(bg["b"])
                if not (max(na, nb) >= 4 and max(na, nb) >= 3 * min(na, nb)):
                    continue    # weiter unklar → Text-Balken-Fallback
        zx, zy = bg["a"] if na > nb else bg["b"]
        # Strecke hinge→zu quer brennen — Band-Dicke ADAPTIV aus dem lokalen
        # Poché-Querprofil (V7-Sezierung: fixe ±0,10m fraßen auf 12cm-LEICHT-
        # wänden Raumfläche; fixe ±0,06m brachen Angerers 25er-Wände —
        # gemessen 6/9→5/9). Poché-verankerte Wände behalten ihr breites
        # Band, unpochierte Leichtwände bekommen das schmale.
        L = math.hypot(zx - hx, zy - hy) or 1.0
        px, py = -(zy - hy) / L, (zx - hx) / L     # Einheits-Normale
        _mx, _my = (hx + zx) / 2.0, (hy + zy) / 2.0
        _lauf = 0
        for _o in range(-8, 9):
            _i, _j = rst.ij(_mx + px * _o * 0.04 * rst.ptm,
                            _my + py * _o * 0.04 * rst.ptm)
            if 0 <= _i < W and 0 <= _j < H and hm_d[_j * W + _i]:
                _lauf += 1
        _dicke_m = _lauf * 0.04
        d2b = max(0.06, min(0.10, _dicke_m / 2.0 + 0.02)) * rst.ptm
        off = -d2b
        while off <= d2b:
            rst.line(grid, hx + px * off, hy + py * off, zx + px * off, zy + py * off)
            off += rst.cell
        # BLATT-VERBREITERUNG — GEMESSEN UND VERWORFEN (2026-08-04): das
        # Mitversiegeln des Fixglases hinter dem Blatt (≤1,6 m bis zum
        # Pfosten) erzeugte MEHR Lecks, nicht weniger (Korpus-Türen 26→28
        # undicht, WM 58→56/77, Velden 15→14): die Verlängerung sprang über
        # ECHTE Durchgänge und traf dort irgendeine Wand — der simple
        # „irgendwo Wand in Quernähe"-Jamb-Test reicht nicht. Ein erneuter
        # Versuch braucht den starken Pfosten-Beweis (beide Enden gehören
        # zu EINEM Wandzug, BFS wie in _tuer_lecks). Bis dahin bleibt der
        # Bogen-Verschluss exakt auf der Blattbreite.
        # FRONT OHNE BOGEN — ebenfalls VERWORFEN (gleiche Messung): der
        # Front-Linien-Snap ohne Bogen-Anker findet eine längenpassende
        # Linie am Text-Anker, aber der Anker streut bis 1,13 m — die
        # gefundene Linie ist dann Möbel/Maß statt Front. Mit Bogen als
        # zweitem Anker funktioniert derselbe Snap (GLASFRONT-UNSKIP),
        # ohne ihn ist die Lage zu unbestimmt.
        # HINGE-FORTSETZUNG (Zimmer-Sezierung: die IW03-Leichtwand zwischen
        # T-Stoß und Türangel wird von Tür-Zonen vetoiert → 0,6m-Loch):
        # jenseits des Angelpunkts muss die Wandflucht weitergehen — Muster
        # [Wand-Anlauf] Lücke(≥0,16m) Wand ⇒ Lücke mit Seal-Dicke brennen.
        ex, ey = hx - zx, hy - zy
        L2 = math.hypot(ex, ey) or 1.0
        ex, ey = ex / L2, ey / L2
        prof = []
        # PROFIL 1,8 m statt 1,0 m (Tür-Dichtungs-Messung 2026-07-31): das
        # Muster [Wandanlauf · Lücke ≥0,16m · Wand] braucht Anlauf + GANZE
        # Türbreite. An Tür 1 des Angerer-Plans: 0,35 m Anlauf + 0,81 m Lücke
        # = 1,16 m — der ferne Pfosten lag AUSSERHALB des 1,0-m-Profils, der
        # Burn unterblieb ('fortsetzung=nein' bei 6 von 8 Bögen), und die Tür
        # galt trotzdem als bogenversiegelt: die Raumfarbe lief durch. Die
        # Lücken- und Wand-Bedingung bleiben unverändert — gebrannt wird nur
        # eine BEGRENZTE Lücke zwischen zwei Wänden auf der Angel-Linie.
        for k2 in range(1, 46):
            dm = 0.04 * k2
            i2, j2 = rst.ij(hx + ex * dm * rst.ptm, hy + ey * dm * rst.ptm)
            prof.append(bool(0 <= i2 < W and 0 <= j2 < H and grid[j2 * W + i2]))
        k = 0
        while k < len(prof) and prof[k]:
            k += 1
        g0 = k
        while k < len(prof) and not prof[k]:
            k += 1
        if k < len(prof) and (k - g0) * 0.04 >= 0.16:
            tx = hx + ex * 0.04 * (k + 1) * rst.ptm
            ty = hy + ey * 0.04 * (k + 1) * rst.ptm
            off = -d2b
            while off <= d2b:
                rst.line(grid, hx + px * off, hy + py * off,
                         tx + px * off, ty + py * off)
                off += rst.cell
        if os.environ.get("TUER_DEBUG"):
            print(f"[bogen] hinge=({hx:.0f},{hy:.0f}) z=({zx:.0f},{zy:.0f}) "
                  f"r={bg['r_m']:.2f} fortsetzung={'ja' if k < len(prof) and (k - g0) * 0.04 >= 0.16 else 'nein'}")
        bogen_ok.append((hx, hy, bg["r_m"]))

    for o in (oeffnungen or []):
        # Verschluss als DÜNNER BALKEN quer über die Wandlücke. Orientierung per
        # BEIDE-ENDEN-TEST: der richtige Balken überbrückt die Lücke, d.h. BEIDE
        # Enden treffen Wand (die reine Dichte-Heuristik wählte bei der Bad-Tür
        # die falsche Richtung → Leck, gemessen). Score = min(Ende1, Ende2).
        cx, cy = o["cx"], o["cy"]
        _gb_glas = False
        if o.get("typ") == "tuer":
            _gb_r = [_r3 for (_hx3, _hy3, _r3) in bogen_ok
                     if math.hypot(_hx3 - cx, _hy3 - cy) < 1.5 * rst.ptm]
            if _gb_r:
                # GLASFRONT-UNSKIP (Sezierung [44]): der nahe Bogen deckt die
                # Textbreite nur bis 2,6×r — eine 3,05m-Fenstertür mit 0,94m-
                # Bogen ließ ~2m Glasfront unversiegelt. Nur im ROH-Pass
                # (FERTIG bleibt byte-identisch: der Burn kollidierte dort mit
                # dem Wand-Paar-Fallback, [49] U 24,96→33,44 gemessen).
                if paar_fallback or (o.get("breite_m") or 1.0) <= 2.6 * max(_gb_r):
                    continue    # Tür bereits byte-genau aus dem Bogen versiegelt
                _gb_glas = True
                # FRONT-LINIEN-SNAP: Orientierung/Lage/Ausdehnung von der
                # gemessenen FRONT-LINIE (|L−breite|≤0,35m, ≤0,40m am Anker —
                # alle 9 WM-Unskips haben sie; 4 davon 5,7° SCHRÄG, für jede
                # achsparallele Suche unsichtbar). Kein versch_out: der
                # Glasfront-Balken ersetzt die echte Grenzlinie, frisst keine
                # Raumfläche ([12] +6,8% F durch Kredit, gemessen).
                _gb_best = None
                _gb_br = (o.get("breite_m") or 1.0) * rst.ptm
                for _s3 in dark_segs:
                    _sdx, _sdy = _s3[2] - _s3[0], _s3[3] - _s3[1]
                    _sl = math.hypot(_sdx, _sdy)
                    if _sl < 1e-6 or abs(_sl - _gb_br) > 0.35 * rst.ptm:
                        continue
                    _ux, _uy = _sdx / _sl, _sdy / _sl
                    _t = (cx - _s3[0]) * _ux + (cy - _s3[1]) * _uy
                    if not (-0.2 * _sl <= _t <= 1.2 * _sl):
                        continue
                    _dq = abs(-(cx - _s3[0]) * _uy + (cy - _s3[1]) * _ux)
                    if _dq <= 0.40 * rst.ptm and (_gb_best is None or _dq < _gb_best[0]):
                        _gb_best = (_dq, _s3, _ux, _uy)
                if _gb_best is not None:
                    _s3, _ux, _uy = _gb_best[1], _gb_best[2], _gb_best[3]
                    _d2g = 0.10 * rst.ptm
                    _px, _py = -_uy, _ux
                    _off = -_d2g
                    while _off <= _d2g:
                        rst.line(grid, _s3[0] + _px * _off, _s3[1] + _py * _off,
                                 _s3[2] + _px * _off, _s3[3] + _py * _off)
                        _off += rst.cell
                    continue
        b2 = ((o.get("breite_m") or 1.0) * rst.ptm * 0.9) / 2.0
        # Balken-Tiefe tür-adaptiv: Innentüren sitzen in ~12cm-Wänden — ein 0,4m tiefer
        # Balken frisst Raumfläche, die laut Plan-F zum Raum gehört (Tür-Diagnose:
        # 5-6 Türen ≈ 1,6-1,9m² = exakt Flur+WC-Defizit). Fenster (Außenwand 50cm)
        # behalten die volle Tiefe (sonst Leck zur AUSSEN-Seite).
        d2 = (0.10 if o.get("typ") == "tuer" else 0.22) * rst.ptm

        def ende_score(dx, dy):
            hits = 0
            for dm in (0.02, 0.10, 0.18, 0.26):
                dpt = b2 + dm * rst.ptm
                i, j = rst.ij(cx + dx * dpt, cy + dy * dpt)
                if 0 <= i < W and 0 <= j < H and grid[j * W + i]:
                    hits += 1
            return hits

        score_h = min(ende_score(-1, 0), ende_score(1, 0))
        score_v = min(ende_score(0, -1), ende_score(0, 1))
        # WAND-FLUCHT-SNAP: der Balken gehört in die Flucht der Nachbar-Wandstücke,
        # nicht an die Label-Position (Bad-Sezierung: Grenze beulte durch die Tür,
        # weil der Balken unterhalb der Wandlinie saß). Dominante Wand-Zeile/-Spalte
        # im ±0,7m-Fenster suchen und den Balken dorthin zentrieren.
        such = int(0.35 / rst.zm)
        fenster = int(0.7 / rst.zm)
        ci, cj = rst.ij(cx, cy)
        ist_tuer = o.get("typ") == "tuer"
        if score_h == 0 and score_v == 0:
            # ORIENTIERUNGS-TIE (Zimmer-Sezierung: Text-Anker 0,3m im Raum,
            # beide Enden-Proben verfehlen die dünne Wand → Fenster-Balken
            # brannte blind quer IN den Raum): Achse = stärkstes WAND-BAND
            # im Suchfenster (Zeilen- vs. Spalten-Support).
            bn_r = 0
            for jj in range(max(0, cj - such), min(H, cj + such + 1)):
                bn_r = max(bn_r, sum(1 for ii in range(max(0, ci - fenster),
                                                       min(W, ci + fenster + 1))
                                     if grid[jj * W + ii]))
            bn_c = 0
            for ii in range(max(0, ci - such), min(W, ci + such + 1)):
                bn_c = max(bn_c, sum(1 for jj in range(max(0, cj - fenster),
                                                       min(H, cj + fenster + 1))
                                     if grid[jj * W + ii]))
            score_h, score_v = (1, 0) if bn_r >= bn_c else (0, 1)
        if score_h >= score_v:  # Balken entlang x → Wand-Flucht = WANDBAND-MITTE
            # gewichteter Schwerpunkt statt dominanter Einzel-Zeile: bei einer 12cm-Wand
            # ist die Argmax-Zeile ambig (WC-Sezierung: Balken saß 15-20cm daneben) —
            # der Schwerpunkt aller Wandzellen im Fenster ist die Bandmitte.
            gew, summe, best_n = 0, 0.0, 0
            for jj in range(max(0, cj - such), min(H, cj + such + 1)):
                nsum = sum(1 for ii in range(max(0, ci - fenster), min(W, ci + fenster + 1))
                           if grid[jj * W + ii])
                gew += nsum
                summe += nsum * jj
                best_n = max(best_n, nsum)
            _gb_band = bool(gew and best_n > fenster // 2)
            cy_s = rst.by0 + (summe / gew) * rst.cell if _gb_band else cy
            # BALKEN-FALLBACK-SNAP (Sezierung: versagt der Wandband-Snap,
            # brannte der Balken am rohen Text-Anker — bis 0,63m daneben,
            # bei [44] 0,37m IM Raum → +2,6m U-Schlitz). Fenster: nächste
            # lange grid-nahe Parallel-Linie; Tür: WAND-FLÄCHEN-PAAR-Gate
            # (echte Sturz-/Wandkanten kommen als Parallel-Paar ≤0,12m, das
            # offene Türblatt ist eine Einzellinie — Grid/Poché-Gates sind
            # wegen Türzonen-Veto/Leichtwand blind). Nur ROH-Pass.
            if not paar_fallback and (not ist_tuer or not _gb_band):
                _gb_fang2 = (0.52 if ist_tuer else 0.45) * rst.ptm
                _gb_cands = []
                for _s3 in dark_segs:
                    if abs(_s3[3] - _s3[1]) > 0.06 * rst.ptm:
                        continue
                    _lo = _s3[0] if _s3[0] <= _s3[2] else _s3[2]
                    _hi = _s3[2] if _s3[0] <= _s3[2] else _s3[0]
                    if _hi - _lo < (0.9 if ist_tuer else 1.5) * rst.ptm:
                        continue
                    _ov = min(_hi, cx + b2) - max(_lo, cx - b2)
                    if _ov < 0.8 * (b2 + b2):
                        continue
                    _sy = (_s3[1] + _s3[3]) / 2.0
                    _dq = abs(_sy - cy_s)
                    if _dq > _gb_fang2:
                        continue
                    if not ist_tuer:
                        _ok = 0
                        _ov0, _ov1 = max(_lo, cx - b2), min(_hi, cx + b2)
                        for _tf in (0.25, 0.5, 0.75):
                            _pi, _pj = rst.ij(_ov0 + _tf * (_ov1 - _ov0), _sy)
                            if not (0 <= _pi < W):
                                continue
                            for _dj in (-2, -1, 0, 1, 2):
                                _jj = _pj + _dj
                                if 0 <= _jj < H and grid[_jj * W + _pi]:
                                    _ok += 1
                                    break
                        if _ok < 2:
                            continue
                    _gb_cands.append((_dq, _sy))
                _gb_fb = None
                for (_dq, _sy) in sorted(_gb_cands):
                    if not ist_tuer:
                        _gb_fb = (_dq, _sy)
                        break
                    if any(0.005 * rst.ptm < abs(_sy - _sy2) <= 0.12 * rst.ptm
                           for (_dq2, _sy2) in _gb_cands):
                        _gb_fb = (_dq, _sy)
                        break
                if _gb_fb is not None:
                    cy_s = _gb_fb[1]
            _sp3 = _tuer_spalt(ci, cj, o.get("breite_m"), "h") if ist_tuer else None
            if _sp3 is not None:
                _jj3, _li3, _re3 = _sp3
                _y3 = rst.by0 + _jj3 * rst.cell
                _x0 = rst.bx0 + (_li3 - 1) * rst.cell
                _x1 = rst.bx0 + (_re3 + 1) * rst.cell
                rst.rect(grid, _x0, _y3 - d2, _x1, _y3 + d2)
                if versch_out is not None and not _gb_glas:
                    rst.rect(versch_out, _x0, _y3 - d2, _x1, _y3 + d2)
            else:
                rst.rect(grid, cx - b2, cy_s - d2, cx + b2, cy_s + d2)
                if ist_tuer and versch_out is not None and not _gb_glas:
                    rst.rect(versch_out, cx - b2, cy_s - d2, cx + b2, cy_s + d2)
        else:                   # Balken entlang y → Wand-Flucht = WANDBAND-MITTE
            gew, summe, best_n = 0, 0.0, 0
            for ii in range(max(0, ci - such), min(W, ci + such + 1)):
                nsum = sum(1 for jj in range(max(0, cj - fenster), min(H, cj + fenster + 1))
                           if grid[jj * W + ii])
                gew += nsum
                summe += nsum * ii
                best_n = max(best_n, nsum)
            _gb_band = bool(gew and best_n > fenster // 2)
            cx_s = rst.bx0 + (summe / gew) * rst.cell if _gb_band else cx
            # Balken-Fallback-Snap vertikal (siehe horizontalen Zweig)
            if not paar_fallback and (not ist_tuer or not _gb_band):
                _gb_fang2 = (0.52 if ist_tuer else 0.45) * rst.ptm
                _gb_cands = []
                for _s3 in dark_segs:
                    if abs(_s3[2] - _s3[0]) > 0.06 * rst.ptm:
                        continue
                    _lo = _s3[1] if _s3[1] <= _s3[3] else _s3[3]
                    _hi = _s3[3] if _s3[1] <= _s3[3] else _s3[1]
                    if _hi - _lo < (0.9 if ist_tuer else 1.5) * rst.ptm:
                        continue
                    _ov = min(_hi, cy + b2) - max(_lo, cy - b2)
                    if _ov < 0.8 * (b2 + b2):
                        continue
                    _sx = (_s3[0] + _s3[2]) / 2.0
                    _dq = abs(_sx - cx_s)
                    if _dq > _gb_fang2:
                        continue
                    if not ist_tuer:
                        _ok = 0
                        _ov0, _ov1 = max(_lo, cy - b2), min(_hi, cy + b2)
                        for _tf in (0.25, 0.5, 0.75):
                            _pi, _pj = rst.ij(_sx, _ov0 + _tf * (_ov1 - _ov0))
                            if not (0 <= _pj < H):
                                continue
                            for _di in (-2, -1, 0, 1, 2):
                                _ii = _pi + _di
                                if 0 <= _ii < W and grid[_pj * W + _ii]:
                                    _ok += 1
                                    break
                        if _ok < 2:
                            continue
                    _gb_cands.append((_dq, _sx))
                _gb_fb = None
                for (_dq, _sx) in sorted(_gb_cands):
                    if not ist_tuer:
                        _gb_fb = (_dq, _sx)
                        break
                    if any(0.005 * rst.ptm < abs(_sx - _sx2) <= 0.12 * rst.ptm
                           for (_dq2, _sx2) in _gb_cands):
                        _gb_fb = (_dq, _sx)
                        break
                if _gb_fb is not None:
                    cx_s = _gb_fb[1]
            _sp3 = _tuer_spalt(ci, cj, o.get("breite_m"), "v") if ist_tuer else None
            if _sp3 is not None:
                _ii3, _ob3, _un3 = _sp3
                _x3 = rst.bx0 + _ii3 * rst.cell
                _y0 = rst.by0 + (_ob3 - 1) * rst.cell
                _y1 = rst.by0 + (_un3 + 1) * rst.cell
                rst.rect(grid, _x3 - d2, _y0, _x3 + d2, _y1)
                if versch_out is not None and not _gb_glas:
                    rst.rect(versch_out, _x3 - d2, _y0, _x3 + d2, _y1)
            else:
                rst.rect(grid, cx_s - d2, cy - b2, cx_s + d2, cy + b2)
                if ist_tuer and versch_out is not None and not _gb_glas:
                    rst.rect(versch_out, cx_s - d2, cy - b2, cx_s + d2, cy + b2)

    # ============================================================
    # ZWEITER DURCHGANG: Türen schließen, wenn die Wandmaske FERTIG ist.
    #
    # Gemessen (2026-08-01, 39 undichte Türen im Korpus): die Schleife oben
    # sucht die Türlücke mit `_tuer_spalt` gegen ein Gitter, das noch im BAU
    # ist — Schraffur und dunkle Kanten sind da, aber alle Öffnungs-Balken
    # der übrigen Türen und Fenster fehlen noch. Findet die Suche dort nichts,
    # fällt der Code auf einen Balken am Textanker zurück, und der sitzt bis
    # 0,63 m neben der Tür. Am Bild belegt: bei einer echten 0,82-m-Tür
    # zwischen zwei Räumen lag KEIN Balken an der Lücke, die Raumfarbe lief
    # rundherum durch.
    #
    # Drei naheliegendere Erklärungen wurden vorher mit Zahlen widerlegt:
    #   · „der Tür-Bogen unterdrückt den Balken"   → 0 von 39 haben einen
    #     Bogen in 2 m Umkreis
    #   · „die Suche greift zu kurz"               → 37 von 39 finden schon
    #     mit den heutigen Parametern einen Spalt
    #   · „die Achse wird falsch gewählt"          → nur 4 von 39 liegen
    #     ausschließlich auf der anderen Achse
    #
    # Darum hier, am FERTIGEN Gitter: jede Tür, die noch eine Wand·Lücke·Wand-
    # Struktur zeigt, wird von Wand zu Wand geschlossen. Beide Achsen, weil
    # die Achsenwahl oben auf demselben unfertigen Gitter beruhte. `_closing`
    # danach fügt nur hinzu — was hier gebrannt wird, bleibt bestehen.
    for _o2 in (oeffnungen or []):
        if _o2.get("typ") != "tuer":
            continue
        _cx2, _cy2 = _o2.get("cx"), _o2.get("cy")
        if _cx2 is None or _cy2 is None:
            continue
        _ci2, _cj2 = rst.ij(_cx2, _cy2)
        if not (0 <= _ci2 < W and 0 <= _cj2 < H):
            continue
        _d22 = 0.10 * rst.ptm          # gleiche Tiefe wie oben: ein tieferer
        _b2 = _o2.get("breite_m")      # Balken frisst Raumfläche
        for _ach in ("h", "v"):
            _sp2 = _tuer_spalt(_ci2, _cj2, _b2, _ach)
            if _sp2 is None:
                continue
            _fest2, _lo2, _hi2 = _sp2
            # PLAUSIBILITÄTS-TOR: nur schließen, was auch wirklich eine Tür
            # sein kann. Ohne dieses Tor mauerte der Durchgang Lücken bis
            # 2,56 m zu — das sind Raumdurchgänge, keine Türblätter, und sie
            # gehören zum Raum. Gemessen ohne Tor: Türen 39→24 (gut), aber
            # räumlicher Beweis 5→4 und Rohbau-Raumcheck 8→7 (zwei Räume
            # zerschnitten). Mit Tor bleibt der Türgewinn, ohne die Räume zu
            # zerteilen.
            _spw = (_hi2 - _lo2 - 1) * rst.cell / rst.ptm
            if _b2:
                if abs(_spw - _b2) > 0.60:
                    continue           # passt nicht zur beschrifteten Breite
            elif _spw > 1.80:
                continue               # ohne Nennmaß: breiter als jede Tür
            if _ach == "h":
                _y2 = rst.by0 + _fest2 * rst.cell
                rst.rect(grid, rst.bx0 + (_lo2 - 1) * rst.cell, _y2 - _d22,
                         rst.bx0 + (_hi2 + 1) * rst.cell, _y2 + _d22)
                if versch_out is not None:
                    rst.rect(versch_out, rst.bx0 + (_lo2 - 1) * rst.cell,
                             _y2 - _d22, rst.bx0 + (_hi2 + 1) * rst.cell,
                             _y2 + _d22)
            else:
                _x2 = rst.bx0 + _fest2 * rst.cell
                rst.rect(grid, _x2 - _d22, rst.by0 + (_lo2 - 1) * rst.cell,
                         _x2 + _d22, rst.by0 + (_hi2 + 1) * rst.cell)
                if versch_out is not None:
                    rst.rect(versch_out, _x2 - _d22,
                             rst.by0 + (_lo2 - 1) * rst.cell, _x2 + _d22,
                             rst.by0 + (_hi2 + 1) * rst.cell)

    # ============================================================
    # WAND-PAAR-RUECKFALL: Plaene, die Waende OHNE Poche zeichnen.
    #
    # Diese Maske ist schraffur-verankert — dunkle Kanten zaehlen nur, wenn
    # Schraffur in der Naehe liegt. Das traegt, solange der Plan seine Waende
    # ausschraffiert. Der Velden-Ausfuehrungsplan (Tiefgarage) zeichnet sie
    # dagegen als reine Umrisslinien in Magenta, ohne Fuellung. Ergebnis,
    # gemessen: 1,3 % Wandflaeche statt der ueblichen 8-12 %, und nur 22 % des
    # Raum-Umrisses lag auf einer Wand (Angerer zum Vergleich: 90 %). Am
    # gerenderten Bild belegt: die Maske lag als Sprenkel auf Beschriftung,
    # die Wandlinien selbst trugen nichts.
    #
    # `vektor.wand_paare` findet genau diese Waende ueber PARALLELE
    # LINIENPAARE in Wandstaerke — auf Velden 213 Paare, 702 m, mit
    # plausiblen Staerken (12/11/25/50 cm). Diese Quelle braucht keine
    # Schraffur.
    #
    # GATE: nur wenn die Maske duenn geblieben ist (<3 % der Rasterflaeche).
    # Plaene, die heute tragen, liegen bei 5-12 % und werden nicht angefasst —
    # die Aenderung ist damit monoton und kann bestehende Ergebnisse nicht
    # verschlechtern.
    #
    # 3 % IST GEMESSEN, NICHT GERATEN. Der WM-Plan liegt mit 5,3 % zwischen
    # Velden (1,3 %) und dem Normalband (8-12 %) — es lag nahe, das Tor auf
    # 6 % zu heben und ihn mitzunehmen. Getestet und VERWORFEN: WM ginge dann
    # von 73 % auf 69 % Umriss-Wandanteil zurueck, Raeume ueber 90 % von 23
    # auf 16. Grund steht in der Staerken-Verteilung: von 1247 Wandpaaren auf
    # WM tragen 324 die Dicke 10 cm und 84 die Dicke 11 cm — das sind Moebel
    # und Einbauten, keine Waende. Wo die schraffur-verankerte Maske noch
    # etwas findet, ist sie die bessere Quelle.
    _anteil = sum(grid) / float(max(1, W * H))
    if _anteil < 0.03:
        try:
            import vektor as _vek
            _pa = _vek.wand_paare(dark_segs, rst.ptm, hatch=None,
                                  mit_geometrie=True)
            # TREPPEN-SERIEN-FILTER (Velden-Treppenhaus-Sezierung 2026-08):
            # Treppenstufen werden als „Wandpaare" gebrannt und zerhacken
            # Treppenhäuser (Velden: F 18,24 → 6,57 gemessen). Der Plan
            # zeichnet Stufenkanten FRAGMENTIERT (viele Stücke mit Lücken) —
            # darum: Stücke je Position (±1 pt) zur Union-Spanne bündeln
            # (Treppen-Bucket = viele Stücke, echte Wandlinie durchgehend),
            # Kette: ≥5 Buckets im Abstand 0,15-0,45 m, Overlap ≥40 % →
            # Treppen-Zone; Paare darin fliegen, Einfassungs-Wände bleiben.
            # GEMESSEN & VERWORFEN: Text-Anker („Steigung/Auftritt"-Label)
            # mit ±2,5-m-Zone + Längen-Guard ≤1,6 m — auf diesem Plan sind
            # auch die WÄNDE fragmentiert (kurze Stücke), der Längen-Guard
            # warf echte Wandstücke weg (DDB 15→u_daneben, 16→15/25).
            _tzonen = []
            for _ax in ("v", "h"):
                _buck = {}
                for _s in (dark_segs or []):
                    _dx, _dy = abs(_s[2] - _s[0]), abs(_s[3] - _s[1])
                    if _ax == "v" and _dx > 0.6:
                        continue
                    if _ax == "h" and _dy > 0.6:
                        continue
                    _pos = ((_s[0] + _s[2]) / 2.0 if _ax == "v"
                            else (_s[1] + _s[3]) / 2.0)
                    _lo = (min(_s[1], _s[3]) if _ax == "v"
                           else min(_s[0], _s[2]))
                    _hi = (max(_s[1], _s[3]) if _ax == "v"
                           else max(_s[0], _s[2]))
                    _b = round(_pos / 1.0)
                    _e2 = _buck.setdefault(_b, [0, 1e30, -1e30])
                    _e2[0] += 1
                    _e2[1] = min(_e2[1], _lo)
                    _e2[2] = max(_e2[2], _hi)
                _ser = sorted((_b * 1.0, v[1], v[2], v[0])
                              for _b, v in _buck.items() if v[0] >= 3)
                _ch = _ser[:1]
                for _e in _ser[1:]:
                    _vor = _ch[-1]
                    _gap = _e[0] - _vor[0]
                    _ov = min(_e[2], _vor[2]) - max(_e[1], _vor[1])
                    _ku = max(1e-9, min(_e[2] - _e[1], _vor[2] - _vor[1]))
                    if 0.15 * rst.ptm <= _gap <= 0.45 * rst.ptm \
                            and _ov / _ku >= 0.4:
                        _ch.append(_e)
                    else:
                        if len(_ch) >= 5:
                            _tzonen.append((_ax, _ch))
                        _ch = [_e]
                if len(_ch) >= 5:
                    _tzonen.append((_ax, _ch))
            if _tzonen:
                def _in_tzone(_w):
                    _pos = ((_w["x0"] + _w["x1"]) / 2.0 if _w.get("achse") == "v"
                            else (_w["y0"] + _w["y1"]) / 2.0)
                    _lo = (min(_w["y0"], _w["y1"]) if _w.get("achse") == "v"
                           else min(_w["x0"], _w["x1"]))
                    _hi = (max(_w["y0"], _w["y1"]) if _w.get("achse") == "v"
                           else max(_w["x0"], _w["x1"]))
                    for _ax2, _ch in _tzonen:
                        if _w.get("achse") != _ax2:
                            continue
                        _pmin = min(c[0] for c in _ch) - 0.10 * rst.ptm
                        _pmax = max(c[0] for c in _ch) + 0.10 * rst.ptm
                        if not (_pmin <= _pos <= _pmax):
                            continue
                        _smin = min(c[1] for c in _ch)
                        _smax = max(c[2] for c in _ch)
                        if min(_hi, _smax) - max(_lo, _smin) \
                                >= 0.5 * max(1e-9, _hi - _lo):
                            return True
                    return False

                _vor = len(_pa or [])
                _pa = [_w for _w in (_pa or []) if not _in_tzone(_w)]
                if _vor != len(_pa):
                    print(f"[wand-maske] Treppen-Serie: {_vor - len(_pa)} "
                          f"Stufen-Paare verworfen ({len(_tzonen)} Zonen)")
            _n_add = 0
            for _w in (_pa or []):
                _d2 = max(rst.cell, (_w.get("dist_pt") or 0) / 2.0)
                _x0, _y0 = _w.get("x0"), _w.get("y0")
                _x1, _y1 = _w.get("x1"), _w.get("y1")
                if None in (_x0, _y0, _x1, _y1):
                    continue
                if _w.get("achse") == "v":
                    rst.rect(grid, _x0 - _d2, _y0, _x1 + _d2, _y1)
                else:
                    rst.rect(grid, _x0, _y0 - _d2, _x1, _y1 + _d2)
                _n_add += 1
            if _n_add:
                print(f"[wand-maske] duenn ({_anteil*100:.1f}%) → "
                      f"{_n_add} Wandpaare ergaenzt "
                      f"({sum(grid)/float(W*H)*100:.1f}%)")
        except Exception as _pe:      # pragma: no cover
            print(f"[wand-maske] Wandpaar-Rueckfall fehlgeschlagen: {_pe!r}")

    return _closing(grid, W, H, max(1, int(closing_m / rst.zm)))


def _watershed(grid, rst, stempel, kern_m=0.45):
    """EROSIONS-MARKER-WATERSHED (Klassiker der Raum-Segmentierung):
    Phase 1 flutet nur den KERN-Freiraum (Wand-Abstand > kern_m) — Räume können
    nicht durch Türen (~90cm) in den Nachbarraum quellen (Tür-Hälse < 2×kern_m sind
    im Kern unterbrochen). Phase 2 teilt den Rand-Ring + Tür-Zonen per Nähe zu →
    die Grenze liegt in der TÜR-MITTE (Fehler ≤ Türbreite × Wanddicke/2, winzig)."""
    W, H = rst.W, rst.H
    AUSSEN = len(stempel)
    r_kern = max(2, int(kern_m / rst.zm))
    dist = _dist_bfs(grid, W, H, r_kern + 1)
    kern = bytearray(1 if (not grid[i] and dist[i] > r_kern) else 0
                     for i in range(W * H))

    label = [-1] * (W * H)
    q = deque()
    ok_start = []
    for idx, st in enumerate(stempel):
        si, sj = rst.ij(st["cx"], st["cy"])
        placed = False
        for maske in (kern, None):   # erst Kern; Mini-Räume (WC) haben evtl. keinen → freie Zelle
            for rad in range(0, 40):
                for di in range(-rad, rad + 1):
                    for dj in range(-rad, rad + 1):
                        ni, nj = si + di, sj + dj
                        if not (0 <= ni < W and 0 <= nj < H):
                            continue
                        frei = kern[nj * W + ni] if maske is not None else not grid[nj * W + ni]
                        if frei and label[nj * W + ni] == -1:
                            label[nj * W + ni] = idx
                            q.append((ni, nj))
                            placed = True
                            break
                    if placed:
                        break
                if placed:
                    break
            if placed:
                break
        ok_start.append(placed)
    for i in range(0, W, 20):
        for j in (0, H - 1):
            if kern[j * W + i] and label[j * W + i] == -1:
                label[j * W + i] = AUSSEN
                q.append((i, j))
    for j in range(0, H, 20):
        for i in (0, W - 1):
            if kern[j * W + i] and label[j * W + i] == -1:
                label[j * W + i] = AUSSEN
                q.append((i, j))
    # Phase 1: nur im Kern fluten
    while q:
        i, j = q.popleft()
        lab = label[j * W + i]
        for di, dj in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            ni, nj = i + di, j + dj
            if 0 <= ni < W and 0 <= nj < H and kern[nj * W + ni] \
                    and label[nj * W + ni] == -1:
                label[nj * W + ni] = lab
                q.append((ni, nj))
    # Phase 2: Rand-Ring + Tür-Hälse per Nähe von den Kernen aus zuteilen
    q = deque(idx for idx in range(W * H) if label[idx] != -1)
    while q:
        idx = q.popleft()
        lab = label[idx]
        i, j = idx % W, idx // W
        for di, dj in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            ni, nj = i + di, j + dj
            nidx = nj * W + ni
            if 0 <= ni < W and 0 <= nj < H and not grid[nidx] and label[nidx] == -1:
                label[nidx] = lab
                q.append(nidx)
    return label, ok_start, AUSSEN


def _taschen_adoption(grid, label, rst, stempel, AUSSEN, huelle_burn=None):
    """Unerreichte Frei-Taschen (label −1): F-geführt dem Nachbar-Raum zuschlagen.
    Nachbar = Label mit den meisten Kontakten beim Blick durch dünne Wände (≤16cm).
    Adoptiert NUR, wenn es das F des Nachbarn Richtung Soll bewegt (byte-exakte
    Soll-Fläche entscheidet) — sonst bleibt die Tasche ehrlich unzugeordnet.
    VERSCH-SPERRE GEMESSEN & VERWORFEN (2026-08-05): versch-Zellen (versiegelte
    Öffnungen) für die Sonde uncrossable zu machen, senkte die Türen-Lecks
    nicht (WM 19 → 25!) und kostete die Taschen-Gewinne (WM-Verifikation
    61 → 58) — die blockierten Taschen verändern die Grenz-Lösung im Ganzen.
    Der Trade des Kandidaten-Folge-Stands (+3 Verifikationen für +1 Leck)
    ist der bessere; bleibt beim bewährten Verhalten."""
    W, H = rst.W, rst.H
    W, H = rst.W, rst.H
    # aktuelle Flächen je Label
    fl = [0] * (len(stempel) + 1)
    for idx in range(W * H):
        if 0 <= label[idx] < len(stempel):
            fl[label[idx]] += 1
    seen = bytearray(W * H)
    for start in range(W * H):
        if seen[start] or grid[start] or label[start] != -1:
            continue
        # Tasche einsammeln
        comp = []
        q = deque([start])
        seen[start] = 1
        while q:
            idx = q.popleft()
            comp.append(idx)
            i, j = idx % W, idx // W
            for di, dj in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                ni, nj = i + di, j + dj
                nidx = nj * W + ni
                if 0 <= ni < W and 0 <= nj < H and not seen[nidx] \
                        and not grid[nidx] and label[nidx] == -1:
                    seen[nidx] = 1
                    q.append(nidx)
        if len(comp) < 25:      # < 0,01 m² — Rauschen
            continue
        if huelle_burn is not None:
            # Tasche grenzt an KÜNSTLICHE Hüllen-Schluss-Zellen → sie liegt
            # JENSEITS der echten Wand (Loggia-Geländer-Kante, gemessen:
            # U-Schlange der Loggia Entwässerung) — kein Rauminhalt.
            am_huellenschluss = False
            for idx in comp:
                i, j = idx % W, idx // W
                for di, dj in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    ni, nj = i + di, j + dj
                    if 0 <= ni < W and 0 <= nj < H and huelle_burn[nj * W + ni]:
                        am_huellenschluss = True
                        break
                if am_huellenschluss:
                    break
            if am_huellenschluss:
                continue
        # Kontakte durch dünne Wände zählen (Phantom-Wände von Möbel-/Küchen-Linework
        # können dicker wirken als echte Trennwände → großzügige Reichweite)
        reach = max(1, int(0.40 / rst.zm))
        kontakt = {}
        for idx in comp[::max(1, len(comp) // 400)]:
            i, j = idx % W, idx // W
            for di, dj in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                for r in range(1, reach + 1):
                    ni, nj = i + di * r, j + dj * r
                    if not (0 <= ni < W and 0 <= nj < H):
                        break
                    lab = label[nj * W + ni]
                    if not grid[nj * W + ni] and lab != -1:
                        kontakt[lab] = kontakt.get(lab, 0) + 1
                        break
                    if not grid[nj * W + ni]:
                        break
        kandidaten = sorted(((n, l) for l, n in kontakt.items() if l != AUSSEN), reverse=True)
        if not kandidaten:
            continue
        # KANDIDATEN-FOLGE statt Sieger-oder-nichts (Velden AR TOP 01-Sezierung):
        # der Kontakt-Sieger (hier: die übervolle Tiefgarage) wurde vom
        # F-Guard verworfen — und die Tasche blieb UNZUGEORDNET, obwohl der
        # untervolle Nachbar (AR TOP 01, −41 %) sie gebraucht hätte. Jetzt
        # bekommt der ERSTE Kandidat die Tasche, dessen F er Richtung Soll
        # bewegt — der byte-exakte Stempel entscheidet, nicht die Nähe allein.
        for _n_k, best in kandidaten:
            soll = stempel[best]["f_m2"] / (rst.zm * rst.zm)
            alt, neu = fl[best], fl[best] + len(comp)
            if abs(neu - soll) < abs(alt - soll) and neu <= soll * 1.10:
                for idx in comp:
                    label[idx] = best
                fl[best] = neu
                break
    return label


def _f_ausgleich(grid, label, rst, stempel, AUSSEN, max_verschub=40000):
    """F-GEFÜHRTER GRENZ-AUSGLEICH: in OFFENEN Bereichen (kein Wand-Schluss) teilt der
    Watershed per Distanz — falsch, wenn z.B. der Flur-GANG näher am Bad-Kern liegt.
    Die byte-exakten Soll-Flächen ziehen die Grenze an die richtige Stelle: übergroße
    Räume geben freie GRENZ-Zellen an untergroße Nachbarn ab (nie durch Wände), bis
    beide Richtung Soll konvergieren. U bleibt der unabhängige Prüfwert."""
    W, H = rst.W, rst.H
    n = len(stempel)
    soll = [int(st["f_m2"] / (rst.zm * rst.zm)) for st in stempel]
    fl = [0] * (n + 1)
    for idx in range(W * H):
        if 0 <= label[idx] <= n:
            fl[label[idx]] += 1
    # Grenz-Front initialisieren: freie Zellen eines ÜBERGROSSEN Raums ODER von AUSSEN
    # (AUSSEN = unbegrenzter Geber: Zellen, die ein Raum durch offene Terrassentüren an
    # draußen verlor, holt der Ausgleich zurück) mit untergroßem Nachbar-Raum.
    def abgabefaehig(lab):
        return (0 <= lab < n and fl[lab] > soll[lab]) or lab == AUSSEN

    # GEODÄTISCHE DISTANZ-SCHRANKE gegen Tentakel: eine Zelle darf nur zu Raum B
    # wechseln, wenn sie durch den FREIRAUM (Wände blockieren!) nahe an Bs Stempel
    # liegt (0,9·√F + 1,5 m Weglänge). Der Gang-Tentakel von Zimmer 2 war EUKLIDISCH
    # nah (direkt über der Wand — Euklid-Schranke griff nicht, gemessen), aber
    # GEODÄTISCH fern (Weg um die Wand herum). Nur für unterfüllte Räume gerechnet.
    INF = 32767
    geo = {}
    for li, st in enumerate(stempel):
        if fl[li] >= soll[li]:
            continue
        si, sj = rst.ij(st["cx"], st["cy"])
        # Start auf freie Zelle schieben (Stempel kann auf Linien liegen)
        start = None
        for rad in range(0, 15):
            for di in range(-rad, rad + 1):
                for dj in range(-rad, rad + 1):
                    ni, nj = si + di, sj + dj
                    if 0 <= ni < W and 0 <= nj < H and not grid[nj * W + ni]:
                        start = nj * W + ni
                        break
                if start is not None:
                    break
            if start is not None:
                break
        if start is None:
            continue
        r_lim = int((0.9 * (st["f_m2"] ** 0.5) + 1.5) / rst.zm)
        dist = [INF] * (W * H)
        dist[start] = 0
        q2 = deque([start])
        while q2:
            idx2 = q2.popleft()
            dd = dist[idx2] + 1
            if dd > r_lim:
                continue
            i2, j2 = idx2 % W, idx2 // W
            for di, dj in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                ni, nj = i2 + di, j2 + dj
                nidx = nj * W + ni
                if 0 <= ni < W and 0 <= nj < H and not grid[nidx] and dist[nidx] > dd:
                    dist[nidx] = dd
                    q2.append(nidx)
        geo[li] = (dist, r_lim)

    # SEED-ANKER-SHED (Foyer-ohne-Stempel-Sezierung): ein Basin aus echtem Raum
    # + stempellosem Flur gab beim AUSSEN-Shed die FALSCHE Seite ab (Radabstell:
    # 22.080 Zellen des echten Raums gingen an AUSSEN, die Korridor-Schlange
    # blieb — Zentroid 3,9m neben dem Stempel, U=45). VORAB geben übergroße
    # Räume ihre geodätisch JENSEITS der eigenen Stempel-Schranke liegenden
    # Zellen wellenweise von AUSSEN her ab — der Teil um den eigenen Stempel
    # bleibt. Shed stoppt am Soll (übergroße lange Flure geben nur ihre
    # fernsten Enden bis Soll ab; U bleibt der unabhängige Prüfwert).
    geo_self = {}
    for li, st in enumerate(stempel):
        if fl[li] <= soll[li]:
            continue
        si, sj = rst.ij(st["cx"], st["cy"])
        start = None
        for rad in range(0, 15):
            for di in range(-rad, rad + 1):
                for dj in range(-rad, rad + 1):
                    ni, nj = si + di, sj + dj
                    if 0 <= ni < W and 0 <= nj < H and not grid[nj * W + ni]:
                        start = nj * W + ni
                        break
                if start is not None:
                    break
            if start is not None:
                break
        if start is None:
            continue
        r_lim = int((0.9 * (st["f_m2"] ** 0.5) + 1.5) / rst.zm)
        dist = [INF] * (W * H)
        dist[start] = 0
        q2 = deque([start])
        while q2:
            idx2 = q2.popleft()
            dd = dist[idx2] + 1
            if dd > r_lim:
                continue
            i2, j2 = idx2 % W, idx2 // W
            for di, dj in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                ni, nj = i2 + di, j2 + dj
                nidx = nj * W + ni
                if 0 <= ni < W and 0 <= nj < H and not grid[nidx] and dist[nidx] > dd:
                    dist[nidx] = dd
                    q2.append(nidx)
        geo_self[li] = (dist, r_lim)
    if geo_self:
        # SEALED-POCKET-SHED (WM-Voll-Blatt, Radabstell-Basins): der Seed-
        # Anker-Shed startet NUR von AUSSEN-Zellen — ein Basin in einer
        # rundum versiegelten Tasche (Vorplatz: Gebäude + gebrannte
        # Pflasterkanten) hat KEINEN AUSSEN-Kontakt und behielt +176%.
        # Deutlich übergroße Räume (>1,10× Soll) ohne AUSSEN-Kontakt geben
        # ihre geodätisch JENSEITS liegenden Zellen direkt an AUSSEN ab
        # (Insel in der Tasche); der Wellen-Ausgleich holt danach bis Soll
        # zurück — wie im offenen Fall.
        _beruehrt = set()
        for idx in range(W * H):
            if label[idx] == AUSSEN and not grid[idx]:
                i5, j5 = idx % W, idx // W
                for di, dj in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    ni, nj = i5 + di, j5 + dj
                    if 0 <= ni < W and 0 <= nj < H and not grid[nj * W + ni]:
                        l5 = label[nj * W + ni]
                        if 0 <= l5 < n:
                            _beruehrt.add(l5)
        for li5, (d5, r5) in geo_self.items():
            if li5 in _beruehrt or fl[li5] <= soll[li5] * 1.10:
                continue
            for idx in range(W * H):
                if label[idx] == li5 and not grid[idx] and d5[idx] > r5:
                    label[idx] = AUSSEN
                    fl[li5] -= 1
                    fl[AUSSEN] += 1
        q3 = deque(idx for idx in range(W * H)
                   if label[idx] == AUSSEN and not grid[idx])
        while q3:
            idx3 = q3.popleft()
            i3, j3 = idx3 % W, idx3 // W
            for di, dj in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                ni, nj = i3 + di, j3 + dj
                if not (0 <= ni < W and 0 <= nj < H):
                    continue
                nidx = nj * W + ni
                lab3 = label[nidx]
                gs = geo_self.get(lab3)
                if (gs is not None and not grid[nidx] and fl[lab3] > soll[lab3]
                        and gs[0][nidx] > gs[1]):
                    label[nidx] = AUSSEN
                    fl[lab3] -= 1
                    fl[AUSSEN] += 1
                    q3.append(nidx)

    # WELLEN-basiertes, KOMPAKTES Wachstum: pro Welle wechseln nur Grenz-Zellen mit
    # ≥2 Ziel-Nachbarn (glatte Front statt fransiger Lappen — Fransen bliesen U +70%
    # auf; U ist der unabhängige Prüfwert). Front-Set wird je Welle fortgeschrieben.
    front = set()
    for idx in range(W * H):
        lab = label[idx]
        if grid[idx] or not abgabefaehig(lab):
            continue
        i, j = idx % W, idx // W
        for di, dj in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            ni, nj = i + di, j + dj
            if 0 <= ni < W and 0 <= nj < H:
                nl = label[nj * W + ni]
                if (0 <= nl < n and nl != lab) or (nl == AUSSEN and 0 <= lab < n):
                    front.add(idx)
                    break
    for _welle in range(400):
        wechsel = []
        for idx in front:
            lab = label[idx]
            if grid[idx] or not abgabefaehig(lab):
                continue
            i, j = idx % W, idx // W
            best = None
            for di, dj in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                ni, nj = i + di, j + dj
                if not (0 <= ni < W and 0 <= nj < H):
                    continue
                nl = label[nj * W + ni]
                if 0 <= nl < n and nl != lab and fl[nl] < soll[nl]:
                    g = geo.get(nl)
                    if g is not None and g[0][j * W + i] > g[1]:
                        continue    # geodätisch zu weit vom Ziel-Stempel → Tentakel-Verbot
                    defizit = soll[nl] - fl[nl]
                    if best is None or defizit > best[0]:
                        best = (defizit, nl)
                elif nl == AUSSEN and 0 <= lab < n and fl[lab] > soll[lab]:
                    # SHED: übergroßer Raum darf Rand-Zellen an AUSSEN abgeben (niedrigste
                    # Priorität) — sonst bleiben Räume ohne unterfüllten Nachbarn zu groß
                    # (Geräte-Abstellraum F +7% gemessen).
                    if best is None:
                        best = (0, AUSSEN)
            if best is None:
                continue
            # Kompaktheit über die 8er-NACHBARSCHAFT: eine gerade Front-Zelle hat dort
            # 3 Ziel-Nachbarn (4er nur 1 → der Ausgleich stockte sofort, gemessen:
            # identische Zahlen). ≥2 von 8 unterdrückt 1-Zellen-Fransen, lässt die
            # Front aber schichtweise wandern.
            ziel_nb8 = 0
            for di in (-1, 0, 1):
                for dj in (-1, 0, 1):
                    if di == 0 and dj == 0:
                        continue
                    ni, nj = i + di, j + dj
                    if 0 <= ni < W and 0 <= nj < H and label[nj * W + ni] == best[1]:
                        ziel_nb8 += 1
            if ziel_nb8 >= _KOMPAKT_MIN:
                wechsel.append((idx, lab, best[1]))
        if not wechsel:
            break
        neue_front = set()
        for idx, lab, ziel in wechsel:
            if ziel != AUSSEN and fl[ziel] >= soll[ziel]:
                continue        # Soll inzwischen erreicht (innerhalb der Welle)
            if ziel == AUSSEN and (not (0 <= lab < n) or fl[lab] <= soll[lab]):
                continue        # Shed nur solange der Geber übergroß ist
            label[idx] = ziel
            if 0 <= lab < n:
                fl[lab] -= 1
            fl[ziel] += 1
            i, j = idx % W, idx // W
            for di, dj in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                ni, nj = i + di, j + dj
                nidx = nj * W + ni
                if 0 <= ni < W and 0 <= nj < H and not grid[nidx]:
                    neue_front.add(nidx)
        front = {idx for idx in (front | neue_front)
                 if not grid[idx] and abgabefaehig(label[idx])}
    return label


def _streifen_ausgleich(grid, label, rst, stempel, AUSSEN, max_runden=40):
    """FORM-ERHALTENDER STREIFEN-AUSGLEICH: unterfüllte Räume wachsen um GANZE
    achsparallele Rand-Streifen (zusammenhängende Läufe ≥60cm) statt Zellen-Fronten —
    die Rechteck-Form bleibt erhalten, U fällt auf die Wandlinie (die Zellen-Fronten
    des Fein-Ausgleichs erzeugten Anbauten mit +20-70% U, gemessen)."""
    W, H = rst.W, rst.H
    n = len(stempel)
    soll = [int(st["f_m2"] / (rst.zm * rst.zm)) for st in stempel]
    fl = [0] * (n + 1)
    for idx in range(W * H):
        if 0 <= label[idx] <= n:
            fl[label[idx]] += 1
    min_run = max(3, int(0.6 / rst.zm))

    # PERF (Profiling am WM-Plan): geber() wurde 130,8 MILLIONEN mal gerufen —
    # 11,1 s reine Aufrufkosten plus der Anteil in der Schleife selbst. Die
    # Bedingung steht darum unten AUSGESCHRIEBEN an beiden Stellen. Sie liest
    # fl[] LIVE (fl ändert sich, während ein Streifen übernommen wird), darum
    # darf sie NICHT je Runde vorberechnet werden — Inlining ist exakt
    # gleichwertig, ein Cache wäre es nicht.
    def geber(lab):     # bleibt für Lesbarkeit/Tests, im Heißpfad ausgeschrieben
        return lab == AUSSEN or (0 <= lab < n and fl[lab] > soll[lab])

    for _ in range(max_runden):
        bewegt = False
        # WM-PERF (Profiling: dieser Schritt war 143s von 428s Gesamtlaufzeit): die
        # Raum-Zellen EINMAL je Runde in EINEM Grid-Durchlauf sammeln, statt für jeden
        # Raum den ganzen Grid neu zu scannen (O(W·H) statt O(n·W·H) je Runde). Der
        # label[idx]==b-Filter unten hält es exakt: ein Taker-Raum verliert nie Zellen
        # (niemand nimmt einem Unterfüller Zellen) und gewinnt sie erst BEI seiner
        # Verarbeitung → der Round-Start-Snapshot ist für den verarbeiteten Raum
        # deckungsgleich mit dem Live-Stand (verifiziert: Angerer/WM Grün-Zahl gleich).
        # Nur die Zellen der UNTERFÜLLTEN Räume einsammeln. Satte Räume werden
        # unten ohnehin per continue übersprungen — ihre Zellenlisten wurden
        # bisher trotzdem jede Runde neu aufgebaut. Am WM-Plan sind das die
        # meisten Räume, also der größte Teil der Sammelarbeit.
        unter = {b for b in range(n) if fl[b] < soll[b]}
        if not unter:
            break
        zellen_je = {}
        for idx in range(W * H):
            lab = label[idx]
            if lab in unter:
                zellen_je.setdefault(lab, []).append(idx)
        for b in range(n):
            if fl[b] >= soll[b]:
                continue
            zellen = [idx for idx in zellen_je.get(b, ()) if label[idx] == b]
            if not zellen:
                continue
            # Kandidaten je Richtung: (dir, feste Linie) → Positionen entlang der Linie
            linien = {}
            for idx in zellen:
                i, j = idx % W, idx // W
                # 4-Nachbarschaft ausgeschrieben: die Richtungs-Tupel-Schleife
                # kostete pro Zelle vier Tupel-Entpackungen, und geber() vier
                # Funktionsaufrufe. Bei 32 Mio. Zellbesuchen zählt beides.
                if i + 1 < W:
                    nidx = idx + 1
                    lab0 = label[nidx]
                    if not grid[nidx] and (lab0 == AUSSEN
                                           or (0 <= lab0 < n and fl[lab0] > soll[lab0])):
                        linien.setdefault(((1, 0), i + 1), set()).add(j)
                if i > 0:
                    nidx = idx - 1
                    lab0 = label[nidx]
                    if not grid[nidx] and (lab0 == AUSSEN
                                           or (0 <= lab0 < n and fl[lab0] > soll[lab0])):
                        linien.setdefault(((-1, 0), i - 1), set()).add(j)
                if j + 1 < H:
                    nidx = idx + W
                    lab0 = label[nidx]
                    if not grid[nidx] and (lab0 == AUSSEN
                                           or (0 <= lab0 < n and fl[lab0] > soll[lab0])):
                        linien.setdefault(((0, 1), j + 1), set()).add(i)
                if j > 0:
                    nidx = idx - W
                    lab0 = label[nidx]
                    if not grid[nidx] and (lab0 == AUSSEN
                                           or (0 <= lab0 < n and fl[lab0] > soll[lab0])):
                        linien.setdefault(((0, -1), j - 1), set()).add(i)
            # längsten zusammenhängenden Lauf finden
            best = None
            for key, poss in linien.items():
                ps = sorted(poss)
                start = prev = ps[0]
                for p in ps[1:] + [None]:
                    if p is not None and p == prev + 1:
                        prev = p
                        continue
                    ll = prev - start + 1
                    if ll >= min_run and (best is None or ll > best[0]):
                        best = (ll, key, start, prev)
                    if p is not None:
                        start = prev = p
            if best is None:
                continue
            _, ((di, dj), fest), lo, hi = best
            # Streifen übernehmen (nur Geber-Zellen, Budget: nicht über Soll hinaus)
            for p in range(lo, hi + 1):
                if fl[b] >= soll[b]:
                    break
                i, j = (fest, p) if di else (p, fest)
                nidx = j * W + i
                lab0 = label[nidx]
                if grid[nidx] or not geber(lab0):
                    continue
                label[nidx] = b
                if 0 <= lab0 < n:
                    fl[lab0] -= 1
                fl[b] += 1
                bewegt = True
        if not bewegt:
            break
    return label


def _glaetten(grid, label, rst, n_labels, AUSSEN, runden=5):
    """GRENZ-GLÄTTUNG (diskreter Mehrheitsfilter): der F-Ausgleich erzeugt fransige
    Grenzen in offenen Bereichen → U wird künstlich aufgebläht (+20% gemessen). Eine
    freie Grenzzelle wechselt zum Mehrheits-Label ihrer 8er-Nachbarschaft. Wände und
    AUSSEN-Zellen bleiben unangetastet; F wird danach re-ausgeglichen."""
    W, H = rst.W, rst.H
    for _ in range(runden):
        wechsel = []
        for idx in range(W * H):
            lab = label[idx]
            if grid[idx] or not (0 <= lab < n_labels):
                continue
            i, j = idx % W, idx // W
            counts = {}
            rand = False
            for di in (-1, 0, 1):
                for dj in (-1, 0, 1):
                    if di == 0 and dj == 0:
                        continue
                    ni, nj = i + di, j + dj
                    if not (0 <= ni < W and 0 <= nj < H):
                        continue
                    nidx = nj * W + ni
                    if grid[nidx]:
                        continue
                    nl = label[nidx]
                    if nl != lab:
                        rand = True
                    if 0 <= nl < n_labels:
                        counts[nl] = counts.get(nl, 0) + 1
            if not rand or not counts:
                continue
            best_l, best_n = lab, counts.get(lab, 0)
            for l2, n2 in counts.items():
                if n2 > best_n:
                    best_l, best_n = l2, n2
            if best_l != lab and best_n >= 5:
                wechsel.append((idx, best_l))
        if not wechsel:
            break
        for idx, l2 in wechsel:
            label[idx] = l2
    return label


def _region_glaetten(mask, i0, j0, i1, j1, W, r_cells):
    """Closing∘Opening einer Raum-Region in ihrer BBox (BFS-basiert, linear):
    füllt Einbuchtungen (Verschluss-Balken) und entfernt Zacken-Vorsprünge der
    Ausgleichs-Fronten. Liefert (geglättete BBox-Maske, bw, bh)."""
    bw, bh = i1 - i0 + 1, j1 - j0 + 1
    INF = 32767

    def dist_from(ist_quelle):
        dist = [INF] * (bw * bh)
        q = deque()
        for k in range(bw * bh):
            if ist_quelle(k):
                dist[k] = 0
                q.append(k)
        while q:
            k = q.popleft()
            dd = dist[k] + 1
            if dd > r_cells:
                continue
            ii, jj = k % bw, k // bw
            for di, dj in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                ni, nj = ii + di, jj + dj
                nk = nj * bw + ni
                if 0 <= ni < bw and 0 <= nj < bh and dist[nk] > dd:
                    dist[nk] = dd
                    q.append(nk)
        return dist

    def raw(k):
        ii, jj = k % bw, k // bw
        return mask[(j0 + jj) * W + (i0 + ii)]

    d1 = dist_from(raw)                                       # dilatieren
    dil = [1 if d1[k] <= r_cells else 0 for k in range(bw * bh)]
    d2 = dist_from(lambda k: not dil[k])                      # erodieren → CLOSING
    clo = [1 if (dil[k] and d2[k] > r_cells) else 0 for k in range(bw * bh)]
    d3 = dist_from(lambda k: not clo[k])                      # erodieren
    ero = [1 if (clo[k] and d3[k] > r_cells) else 0 for k in range(bw * bh)]
    d4 = dist_from(lambda k: ero[k])                          # dilatieren → OPENING
    return [1 if d4[k] <= r_cells else 0 for k in range(bw * bh)], bw, bh


def _kanten_begradigen(m, bw, bh, tol=5, quote=0.5):
    """ACHS-SNAP für die U-Messung: Wände sind achsparallel — fast-gerade Regions-
    Kanten (Rest-Jitter der Ausgleichs-Fronten, ±tol Zellen) werden auf ihre DOMINANTE
    Achslinie begradigt. Nur wenn ≥quote der Zeilen/Spalten dieselbe Kantenlage haben
    (L-Formen bleiben unangetastet, nur die dominante Kante wird glatt)."""
    from collections import Counter

    def snap_rows(links):
        werte = {}
        for j in range(bh):
            lo = hi = None
            for i in range(bw):
                if m[j * bw + i]:
                    if lo is None:
                        lo = i
                    hi = i
            if lo is not None:
                werte[j] = lo if links else hi
        if len(werte) < 8:
            return
        dom, cnt = Counter(werte.values()).most_common(1)[0]
        if cnt / len(werte) < quote:
            return
        for j, v in werte.items():
            if v == dom or abs(v - dom) > tol:
                continue
            if links:
                for i in range(min(v, dom), max(v, dom)):
                    m[j * bw + i] = 1 if dom < v else 0
            else:
                for i in range(min(v, dom) + 1, max(v, dom) + 1):
                    m[j * bw + i] = 1 if dom > v else 0

    def snap_cols(oben):
        werte = {}
        for i in range(bw):
            lo = hi = None
            for j in range(bh):
                if m[j * bw + i]:
                    if lo is None:
                        lo = j
                    hi = j
            if lo is not None:
                werte[i] = lo if oben else hi
        if len(werte) < 8:
            return
        dom, cnt = Counter(werte.values()).most_common(1)[0]
        if cnt / len(werte) < quote:
            return
        for i, v in werte.items():
            if v == dom or abs(v - dom) > tol:
                continue
            if oben:
                for j in range(min(v, dom), max(v, dom)):
                    m[j * bw + i] = 1 if dom < v else 0
            else:
                for j in range(min(v, dom) + 1, max(v, dom) + 1):
                    m[j * bw + i] = 1 if dom > v else 0

    snap_rows(True)
    snap_rows(False)
    snap_cols(True)
    snap_cols(False)


def _loecher_fuellen_und_messen(grid, label, rst, stempel, r_gl_gross=0.25):
    """Je Raum: eingeschlossene Löcher (Möbel-Inseln + deren Innenraum) zählen zur
    Raumfläche (so misst der Plan sein F), U wird die ÄUSSERE Wandlinie. Loch =
    Komponente von Nicht-Raum-Zellen, die die Raum-BBox nicht erreicht."""
    W, H = rst.W, rst.H
    out = []
    # PERF (Profiling: 22s): die Raum-Zellen EINMAL in einem Grid-Durchlauf sammeln
    # statt je Raum den ganzen Grid zu scannen (O(W·H) statt O(n·W·H)). Diese Funktion
    # MISST nur (verändert label nicht) → das Ergebnis ist byte-identisch.
    _cells_by_room = {}
    for idx in range(W * H):
        _lab = label[idx]
        if 0 <= _lab < len(stempel):
            _cells_by_room.setdefault(_lab, []).append(idx)
    for li, st in enumerate(stempel):
        cells = _cells_by_room.get(li)
        if not cells:
            out.append((0.0, 0.0))
            continue
        is_room = bytearray(W * H)
        i0 = j0 = 1 << 30
        i1 = j1 = -1
        for idx in cells:
            is_room[idx] = 1
            i, j = idx % W, idx // W
            i0, i1 = min(i0, i), max(i1, i)
            j0, j1 = min(j0, j), max(j1, j)
        i0, j0 = max(0, i0 - 1), max(0, j0 - 1)
        i1, j1 = min(W - 1, i1 + 1), min(H - 1, j1 + 1)
        # Komponenten der Nicht-Raum-Zellen in der BBox; Rand-berührend = kein Loch
        comp_seen = bytearray(W * H)
        for jj in range(j0, j1 + 1):
            for ii in range(i0, i1 + 1):
                sidx = jj * W + ii
                if is_room[sidx] or comp_seen[sidx]:
                    continue
                comp = []
                beruehrt_rand = False
                q = deque([sidx])
                comp_seen[sidx] = 1
                while q:
                    idx = q.popleft()
                    comp.append(idx)
                    i, j = idx % W, idx // W
                    if i <= i0 or i >= i1 or j <= j0 or j >= j1:
                        beruehrt_rand = True
                    for di, dj in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                        ni, nj = i + di, j + dj
                        nidx = nj * W + ni
                        if i0 <= ni <= i1 and j0 <= nj <= j1 and not comp_seen[nidx] \
                                and not is_room[nidx]:
                            comp_seen[nidx] = 1
                            q.append(nidx)
                if not beruehrt_rand:
                    for idx in comp:      # Loch → zählt zum Raum (Möbel-Insel)
                        is_room[idx] = 1
        # F auf der ROHEN gefüllten Silhouette (exakt); U auf der GEGLÄTTETEN —
        # Zacken der Ausgleichs-Fronten + Verschluss-Ausbuchtungen bliesen U ~+20%
        # auf, obwohl F exakt war (der Blocker der Verifikation, gemessen).
        f_cells = 0
        for jj in range(j0, j1 + 1):
            base = jj * W
            for ii in range(i0, i1 + 1):
                if is_room[base + ii]:
                    f_cells += 1
        # Glättungsradius größenabhängig: 25cm schließt Objekt-Buchten großer Räume,
        # frisst aber Mini-Räume (WC −13% gemessen) → kleine Räume 12cm.
        # 0,40m-Schacht-Glättung GEMESSEN & zurückgestellt (Bad-Roh-F-
        # Sezierung): heilt WM-Schacht-Buchten (50→51), kostet aber am TG
        # einen Raum (Stellplatz-Poché) — Seitwärts-Tausch, kein sauberer
        # Gewinn. Bleibt 0,25 bis das TG-Gating gebaut ist.
        r_gl = r_gl_gross if st["f_m2"] >= 4.0 else 0.12
        glatt, bw, bh = _region_glaetten(is_room, i0, j0, i1, j1, W,
                                         max(2, int(r_gl / rst.zm)))
        _kanten_begradigen(glatt, bw, bh, tol=max(3, int(0.10 / rst.zm)))
        kanten = 0
        for k in range(bw * bh):
            if not glatt[k]:
                continue
            ii, jj = k % bw, k // bw
            for di, dj in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                ni, nj = ii + di, jj + dj
                if not (0 <= ni < bw and 0 <= nj < bh) or not glatt[nj * bw + ni]:
                    kanten += 1
        out.append((f_cells * rst.zm * rst.zm, kanten * rst.zm))
    return out


def hatch_fill_filter(hatch_segs, box, ptm, cell_m=0.06, r_connect_m=0.12,
                      r_open_m=0.35, r_recover_m=0.20):
    """BODEN-/BELAGS-SCHRAFFUR aus der Wand-Poché filtern (Bad-Roh-F-Sezierung:
    monochrome Pläne tragen Fliesen-/Belags-Feinschraffur IM Rauminneren —
    Median-Strichlänge 5 cm, 90-200+ Striche je Bad — die wand_maske als Wand
    brannte; Räume wurden an der Fill-Grenze abgeschnitten, F −19..−43 %,
    Schweregrad = Schraffur-Dichte-Gradient der Gebäudeblöcke).
    PRINZIP: Wand-Poché ist ein dünnes BAND (reale Wanddicke ≤ ~0,45 m);
    ein Schraffur-Blob, der ein morphologisches Opening mit r_open überlebt
    (>~0,7 m dick in BEIDEN Richtungen), ist Bodenfläche → Striche darin
    fliegen. Läuft auf einem groben 6-cm-Raster (~2 s auf 5000 m²)."""
    bx0, bx1, by0, by1 = box
    cell = cell_m * ptm
    W2 = int((bx1 - bx0) / cell) + 2
    H2 = int((by1 - by0) / cell) + 2
    if W2 * H2 > 4_000_000 or not hatch_segs:
        return hatch_segs
    hmask = bytearray(W2 * H2)
    mids = []
    for s in hatch_segs:
        i = int(((s[0] + s[2]) / 2.0 - bx0) / cell)
        j = int(((s[1] + s[3]) / 2.0 - by0) / cell)
        mids.append((i, j))
        if 0 <= i < W2 and 0 <= j < H2:
            hmask[j * W2 + i] = 1
    rc = max(1, round(r_connect_m / cell_m))
    ro = max(1, round(r_open_m / cell_m))
    rr = max(0, round(r_recover_m / cell_m))
    d = _dist_bfs(hmask, W2, H2, rc)
    solid = bytearray(1 if d[i] <= rc else 0 for i in range(W2 * H2))
    bg = bytearray(0 if solid[i] else 1 for i in range(W2 * H2))
    dbg = _dist_bfs(bg, W2, H2, ro + 1)
    eroded = bytearray(1 if dbg[i] > ro else 0 for i in range(W2 * H2))
    dop = _dist_bfs(eroded, W2, H2, ro + rr)
    fill = bytearray(1 if dop[i] <= ro + rr else 0 for i in range(W2 * H2))
    keep = [s for s, (i, j) in zip(hatch_segs, mids)
            if not (0 <= i < W2 and 0 <= j < H2 and fill[j * W2 + i])]
    return keep


def _fassaden_schluss(grid, W, H, zm, tol_m=0.20, max_gap_m=2.5, min_run_m=0.50):
    """HÜLLEN-KANTEN-SCHLIESSUNG (WM-Sezierung: Loggia-Glasfronten/Tore sind nur
    dünne Linien OHNE Poché — grau 0,49-0,89 bzw. 0,14pt-schwarz — und fallen am
    Schraffur-Anker durch; die Fassade blieb an 6+ Stellen 1,2-2,3m offen, der
    Watershed flutete 14/21 Räume ins AUSSEN). Aus 4 Richtungen das äußerste
    Wand-Profil bilden; Lücken ≤max_gap zwischen KOLLINEAREN Fassaden-Runs
    (Niveau-Differenz ≤tol, Run ≥min_run) orthogonal schließen (2 Zellen dick).
    Gemessen: WM-Leck −37%, 6 Räume dicht; Angerer 5/9 unverändert (einzige
    Abweichung Park-U 30,20→30,04); legitime Stufen/Carports bleiben offen."""
    tol_c = max(1, int(tol_m / zm))
    min_run_c = max(2, int(min_run_m / zm))
    max_gap_c = int(max_gap_m / zm)

    def profil(axis, side):
        n = W if axis == "col" else H
        m = H if axis == "col" else W
        prof = [None] * n
        for a in range(n):
            rng = range(m) if side == 0 else range(m - 1, -1, -1)
            for b in rng:
                idx = (b * W + a) if axis == "col" else (a * W + b)
                if grid[idx]:
                    prof[a] = b
                    break
        return prof

    def runs_of(prof):
        runs = []
        i = 0
        n = len(prof)
        while i < n:
            if prof[i] is None:
                i += 1
                continue
            j = i
            lvl = [prof[i]]
            while j + 1 < n and prof[j + 1] is not None and abs(prof[j + 1] - prof[j]) <= 2:
                j += 1
                lvl.append(prof[j])
            lvl.sort()
            runs.append((i, j, lvl[len(lvl) // 2]))
            i = j + 1
        return runs

    n_neu = 0
    luecken = []    # ALLE Hüllen-Lücken (auch nicht geschlossene) → Brücken-Burn
    gap_max2 = int(4.5 / zm)
    for axis in ("col", "row"):
        for side in (0, 1):
            runs = [r for r in runs_of(profil(axis, side))
                    if r[1] - r[0] + 1 >= min_run_c]
            for ai in range(len(runs)):
                _a0, a1, l0 = runs[ai]
                for bi in range(ai + 1, len(runs)):
                    b0, _b1, l1 = runs[bi]
                    gap = b0 - a1 - 1
                    if gap > gap_max2:
                        break
                    if gap < 2:
                        continue
                    luecken.append((axis, a1, b0, min(l0, l1), max(l0, l1)))
                    if gap <= max_gap_c and abs(l0 - l1) <= tol_c:
                        n = max(1, b0 - a1)
                        for k in range(n + 1):
                            a = a1 + k
                            b = l0 + (l1 - l0) * k // n
                            for db in (0, 1):
                                bb = b + db
                                if 0 <= a < (W if axis == "col" else H) \
                                        and 0 <= bb < (H if axis == "col" else W):
                                    idx = (bb * W + a) if axis == "col" else (a * W + bb)
                                    grid[idx] = 1
                        n_neu += 1
                        break
    return n_neu, luecken


def umriss_auf_wand(poly_pt, grid, rst, r_cells=3):
    """Wie viel des Raum-Umrisses liegt WIRKLICH auf einer Wand? (0..1)

    Die zweite, unabhängige Beweisstufe. Bisher galt eine Raumform nur dann
    als bewiesen, wenn der Plan einen UMFANG stempelt (dann prüft U_ist gegen
    U_soll) oder der IoU-/Rohbau-Beweis griff. Auf Polierplänen ohne
    U-Stempel blieb die Form damit dauerhaft „ungeprüft" — obwohl der Plan
    die Wahrheit sichtbar enthält: eine richtige Raumgrenze verläuft ENTLANG
    der gezeichneten Wände.

    Genau das wird hier gemessen. Der Umriss wird in Zellenschritten
    abgelaufen; ein Abtastpunkt zählt, wenn innerhalb von r_cells eine
    Wandzelle liegt. Das Ergebnis ist ein Anteil und braucht KEINE fremde
    Wahrheit — nur den Plan selbst.

    Die Toleranz r_cells ist nötig, weil das Polygon auf der RAUMseite der
    Wand liegt (Douglas-Peucker über Randzellen) und die Wandzelle damit
    ein bis zwei Zellen weiter außen sitzt. Bei zelle_m = 0,02 sind 3 Zellen
    = 6 cm — schmaler als jede Wand, also kein Freibrief.

    Türöffnungen zählen mit: der Tür-Durchgang wird in der Maske ohnehin
    zugebrannt, ein Fenster liegt in der Außenwand. Ein Umriss, der quer
    durch einen Raum läuft oder im Freien liegt, fällt dagegen sofort durch.

    ALS BEWEIS WIDERLEGT — nicht erneut als grünen Haken bauen.
    Gemessen 2026-08-04 an 72 Umrissen auf 4 echten Plänen
    (scripts/mess_umriss_auf_wand.py). Die naheliegende Regel
        Flächen-Treue ≤ 5 %  UND  auf Wand ≥ 85 %  →  Form bewiesen
    erreicht auf der einzigen Teilmenge mit harter Wahrheit (46 Räume mit
    byte-exakt gestempeltem Umfang) nur 80 % Präzision: 8 richtig, 2 falsch.
    Der Fehlermodus ist grundsätzlich, nicht justierbar — WM-Loggia,
    Stempel 3,60 × 2,62 m, rekonstruiert 6,11 × 1,55 m: RICHTIGE FLÄCHE,
    falsche Proportion. Ein langer schmaler Streifen schmiegt sich an
    Wände sogar besonders gut an (89,7 %). Fläche und Wandnähe können die
    Proportion prinzipiell nicht prüfen; dafür braucht es die Maßketten
    (raum_iou_beweis) oder den gestempelten Umfang.
    Auch ein dritter Test half nicht: die Zackigkeit (Polygon-Umfang gegen
    Bounding-Box-Umfang) liegt bei beiden Fehltreffern bei 0,98 bzw. 1,16 —
    die Umrisse sind sauber, nur falsch proportioniert.

    Die Kennzahl bleibt trotzdem im Produkt: als ANGABE für den Prüfer
    („der Umriss folgt zu 46 % gezeichneten Wänden"), nicht als Urteil.
    Sie ist dort am aussagekräftigsten, wo sie tief liegt — Freiflächen
    (Parkplatz 46 %, Halbverband 22 %, Kinderspielfläche 49 %) haben
    naturgemäß keine Wände, ein Zimmer bei 33 % dagegen schon.

    poly_pt: [(x,y)] in pt (Plan-Koordinaten, wie raum_regionen liefert).
    -> float 0..1, oder None wenn nicht messbar.
    """
    if not poly_pt or len(poly_pt) < 3 or grid is None:
        return None
    W, H = rst.W, rst.H
    versatz = sorted(((di, dj)
                      for di in range(-r_cells, r_cells + 1)
                      for dj in range(-r_cells, r_cells + 1)),
                     key=lambda d: d[0] * d[0] + d[1] * d[1])
    treffer = gesamt = 0
    n = len(poly_pt)
    for k in range(n):
        x1, y1 = poly_pt[k]
        x2, y2 = poly_pt[(k + 1) % n]
        schritte = max(1, int(math.hypot(x2 - x1, y2 - y1) / rst.cell))
        for s in range(schritte):
            t = s / float(schritte)
            i, j = rst.ij(x1 + (x2 - x1) * t, y1 + (y2 - y1) * t)
            gesamt += 1
            # Nachbarschaft von INNEN nach AUSSEN absuchen: der weitaus
            # häufigste Fall ist ein Treffer direkt an der Abtaststelle.
            # Ein Scan von (-r,-r) an kostete dort ~24 Leerläufe je Punkt.
            for di, dj in versatz:
                ni, nj = i + di, j + dj
                if 0 <= ni < W and 0 <= nj < H and grid[nj * W + ni]:
                    treffer += 1
                    break
    return (treffer / float(gesamt)) if gesamt else None


def an_wand_schnappen(poly, grid, W, H, max_snap=8, min_len=4.0, tol=0.30):
    """Fast-achsparallele Polygonkanten EXAKT an die Wandkante legen.

    Nutzer-Befund: „die Markierungen gehen teilweise in die Wände rein — er
    muss ja erkennen, wo ein Raum aufhört und die Wand anfängt."

    Am Plan bei 12-facher Vergrößerung nachgesehen: die Kante sitzt im Kern
    richtig, ist aber leicht SCHRÄG (Douglas-Peucker verbindet zwei Rand-
    zellen, die ein bis zwei Zellen versetzt liegen) und wandert dadurch über
    die Wandlinie — mal im Raum, mal in der Wand. Exakt im Raster gemessen
    ist der Wand-Anteil zwar nur 0,7 %, aber genau dieser Saum ist das, was
    man sieht.

    Hier wird jede fast-achsparallele Kante auf die WAND geschnappt: von der
    Kante aus nach außen sondieren, bis die erste Wandzelle kommt, und die
    Kante auf die letzte freie Zelle davor legen. Findet die Sonde in
    max_snap Zellen keine Wand (offene Kante, Durchgang), bleibt die Kante
    unverändert — es wird nichts erfunden.

    poly: [(x,y)] in ZELLEN. -> neues Polygon in Zellen.
    """
    n = len(poly)
    if n < 4:
        return poly
    kanten = []
    for k in range(n):
        x1, y1 = poly[k]
        x2, y2 = poly[(k + 1) % n]
        dx, dy = x2 - x1, y2 - y1
        L = (dx * dx + dy * dy) ** 0.5
        achse = None
        if L >= min_len:
            if abs(dx) <= tol * abs(dy):
                achse = "v"          # senkrechte Kante, x ist konstant
            elif abs(dy) <= tol * abs(dx):
                achse = "h"          # waagrechte Kante, y ist konstant
        kanten.append({"p1": (x1, y1), "p2": (x2, y2), "achse": achse,
                       "fest": None})
    # Schwerpunkt: die Aussenrichtung jeder Kante zeigt vom Raum weg
    cx = sum(p[0] for p in poly) / n
    cy = sum(p[1] for p in poly) / n
    for e in kanten:
        if not e["achse"]:
            continue
        (x1, y1), (x2, y2) = e["p1"], e["p2"]
        if e["achse"] == "v":
            fest0 = (x1 + x2) / 2.0
            vz = 1 if fest0 > cx else -1
            proben = [y1 + (y2 - y1) * t for t in (0.25, 0.5, 0.75)]
            treffer = []
            for yy in proben:
                j = int(round(yy))
                if not (0 <= j < H):
                    continue
                for d in range(0, max_snap + 1):
                    i = int(round(fest0)) + vz * d
                    if not (0 <= i < W):
                        break
                    if grid[j * W + i]:
                        treffer.append(i - vz)      # letzte freie Zelle
                        break
            if len(treffer) >= 2:
                treffer.sort()
                e["fest"] = treffer[len(treffer) // 2] + (0.5 if vz > 0 else 0.5)
        else:
            fest0 = (y1 + y2) / 2.0
            vz = 1 if fest0 > cy else -1
            proben = [x1 + (x2 - x1) * t for t in (0.25, 0.5, 0.75)]
            treffer = []
            for xx in proben:
                i = int(round(xx))
                if not (0 <= i < W):
                    continue
                for d in range(0, max_snap + 1):
                    j = int(round(fest0)) + vz * d
                    if not (0 <= j < H):
                        break
                    if grid[j * W + i]:
                        treffer.append(j - vz)
                        break
            if len(treffer) >= 2:
                treffer.sort()
                e["fest"] = treffer[len(treffer) // 2] + 0.5
    # Kanten mit Schnapp-Ziel begradigen, Ecken als Schnittpunkte neu setzen
    neu_poly = []
    for k in range(n):
        e = kanten[k]
        v = kanten[(k - 1) % n]
        x, y = poly[k]
        if v["achse"] == "v" and v["fest"] is not None:
            x = v["fest"]
        if v["achse"] == "h" and v["fest"] is not None:
            y = v["fest"]
        if e["achse"] == "v" and e["fest"] is not None:
            x = e["fest"]
        if e["achse"] == "h" and e["fest"] is not None:
            y = e["fest"]
        neu_poly.append((x, y))
    return neu_poly


def _umriss_zellen(label, W, H, ridx, zm2, min_flaeche_m2=1.0, cells=None,
                   mitglied=None):
    """Rand-Trace + Douglas-Peucker EINES Raum-Beckens → DP-Polygon in Zellen.

    Aus raum_regionen herausfaktorisiert, damit Messung (raum_kontur_exakt)
    und Zeichnung (raum_regionen) denselben Umriss teilen — zwei Umrisse
    wären zwei Wahrheiten. cells: optional die Zellen des Raums (Perf —
    sonst voller Grid-Scan je Raum). Liefert (vereinfacht, n_cells);
    vereinfacht=None bei zu kleinem/zerfranstem Becken."""
    MN = ((1, 0), (1, 1), (0, 1), (-1, 1), (-1, 0), (-1, -1), (0, -1), (1, -1))
    rand = bytearray(W * H)
    n_cells = 0
    # mitglied: optionale Zugehoerigkeits-Maske (Raumzellen + kreditierte
    # Tuerdurchgangs-Zellen). Ohne sie gilt wie bisher label==ridx.
    if mitglied is not None:
        _drin = lambda ix: bool(mitglied[ix])
    else:
        _drin = lambda ix: label[ix] == ridx
    if cells is None:
        cells = [idx for idx in range(W * H) if _drin(idx)]
    for idx in cells:
        n_cells += 1
        i, j = idx % W, idx // W
        for di, dj in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            ni, nj = i + di, j + dj
            if not (0 <= ni < W and 0 <= nj < H) or not _drin(nj * W + ni):
                rand[idx] = 1
                break
    if n_cells * zm2 < min_flaeche_m2:
        return None, n_cells
    # Start = oberste-linkeste Randzelle (cells ist idx-aufsteigend) →
    # Moore-Trace im Uhrzeigersinn
    start = next((idx for idx in cells if rand[idx]), None)
    if start is None:
        return None, n_cells
    pfad = []
    i, j = start % W, start // W
    cur, richtung = (i, j), 0
    for _s in range(4 * (W + H)):
        pfad.append(cur)
        gefunden = False
        for k in range(8):
            d = MN[(richtung + k) % 8]
            ni, nj = cur[0] + d[0], cur[1] + d[1]
            if 0 <= ni < W and 0 <= nj < H and rand[nj * W + ni]:
                cur = (ni, nj)
                richtung = (richtung + k + 6) % 8
                gefunden = True
                break
        if not gefunden or (cur == (i, j) and len(pfad) > 2):
            break
    if len(pfad) < 6:
        return None, n_cells

    def _dp(pts, eps):
        if len(pts) < 3:
            return pts
        ax, ay = pts[0]
        bx, by = pts[-1]
        dx, dy = bx - ax, by - ay
        L = (dx * dx + dy * dy) ** 0.5 or 1.0
        dmax, imax = 0.0, 0
        for k in range(1, len(pts) - 1):
            px, py = pts[k]
            d = abs((px - ax) * dy - (py - ay) * dx) / L
            if d > dmax:
                dmax, imax = d, k
        if dmax > eps:
            return _dp(pts[:imax + 1], eps)[:-1] + _dp(pts[imax:], eps)
        return [pts[0], pts[-1]]

    # DP auf den OFFENEN Trace-Pfad (Start/Ende sind benachbart) — bei
    # geschlossenem Polygon würde Start==Ende die Rekursion degenerieren.
    return _dp(pfad, 2.0), n_cells


def _tuer_lecks(grid, label, rst, oeffnungen, stempel=None):
    if os.environ.get("GUARD_DEBUG"):
        from collections import Counter as _C
        print(f"[lecks-in] {dict(_C(o.get('typ') for o in (oeffnungen or [])))} "
              f"cx_fehlt={sum(1 for o in (oeffnungen or []) if o.get('cx') is None)}")
    """Undichte Türen lokalisieren: läuft die Raumfarbe durch die Öffnung?

    Spiegelbildlich zum Mess-Harness scripts/mess_tuer_dichtung.py (gleiche
    Fenster/Spannweiten/Sonden): pro Tür-Anker die Wand-Lücke-Wand-Struktur
    suchen (Anker streut bis 1,13 m daneben, darum Fenster 1,0 m / Kappe
    1,8 m, Spalt 0,45-2,6 m am nächsten an der Nennbreite), dann quer über
    die Lücke bis zur ersten Raum-Zelle je Seite sondieren. Gleiches Label
    beidseitig = Leck. → [(achse, fest, lo, hi)] der LECKENDEN Lücken.

    ── GEMESSENER TRADE, nicht erneut ohne neue Idee angehen ──────────────
    Der Guard unten schützt nur die VERIFIKATION. Ein Raum kann verifiziert
    bleiben, während seine Fläche über die 20-%-Schwelle driftet, an der
    `raum_regionen` den UMRISS verwirft — dann steht die Menge, aber am Plan
    ist nichts eingezeichnet. Bisect über 4 Commits (2026-08-06): genau das
    kostete auf WM 4 echte Umrisse (47 → 43), drei Loggien und zwei
    Wohnküchen, alle weiter „verifiziert".

    Den Guard um dieses zweite Schutzgut zu erweitern, WURDE GEBAUT UND
    GEMESSEN. Er wirkt — aber nur um den Preis der Türen:
      Umrisse schützen (Veto ODER Score):  grün 42 → 46, Umrisse 70 → 75,
        ABER WM 19 → 25 undichte Türen — mess_tuer_dichtung verweigert.
      Balken im Score mitzählen (damit sie nicht gratis wegfallen):
        Türen wieder dicht, aber grün zurück auf 42, Umrisse zurück auf 70.
        Netto nur −1 Verifikation und +6 % Laufzeit.
    Der Guard kann Umrisse also NUR gegen Türdichtheit eintauschen; beide
    Enden sind gemessen. Wer es wieder aufgreift, braucht einen Mechanismus,
    der den Umriss rettet OHNE den Balken zu entfernen — z. B. das
    Umriss-Gate für Räume mit Tür-Balken auf die Fläche VOR dem Balken
    beziehen, statt den Balken zurückzunehmen.
    """
    W, H = rst.W, rst.H
    lecks = []
    # KATEGORIE je Stempel (fuer den Front-Fall): Innenraum vs. ueberdachter
    # Aussenbereich (Terrasse/Loggia/Carport). Lazy — massen_logic haengt
    # nicht am Heisspfad.
    _kat = None
    if stempel:
        try:
            from massen_logic import kategorie_of as _ko
            _kat = [_ko((st.get("name") or "")) for st in stempel]
        except Exception:
            _kat = None
    for o in (oeffnungen or []):
      try:
        _ist_tuer = o.get("typ") == "tuer"
        # GLASFRONT-FALL (2026-08-10): ein FENSTER-Anker an der Grenze
        # Innenraum <-> Aussenkategorie markiert eine Hebe-Schiebe-/
        # Fixverglasungs-Front ohne Poché — dort laeuft der Watershed in
        # die Terrasse (WK-Zellen +9,7 %). NUR dieser Fall wird gesiegelt;
        # die generelle Front-Versiegelung ist als Sackgasse gemessen
        # (Kimi, Commit 105556f: WM 58->56, Velden 15->14).
        # HINTER SCHALTER (FRONT_SEAL=1), Stand 2026-08-10: Mechanik
        # funktioniert nachweislich in beide Richtungen — die falsche Front
        # (Parkplatz<->Bad, echtes Fenster in echter Wand) entfernt der
        # Verifikations-Guard korrekt, die richtige (WK<->Terrasse, 1,81 m)
        # wird gesiegelt. ABER: nur 1 von mehreren Glaselementen der Front
        # wird gefunden (die uebrigen Fenster-Anker verfehlen die
        # Spalt-Suche) — ein Segment dichtet nicht, der Watershed flutet
        # daneben durch (WK-Zellen +9,7 -> +9,4, wirkungslos). Erst die
        # Segment-Sezierung machen ([front]-Telemetrie unter GUARD_DEBUG),
        # dann aktivieren. Standard AUS = Verhalten unveraendert.
        _ist_front = (o.get("typ") in ("fenster", "glasfront")
                      and _kat is not None
                      and bool(os.environ.get("FRONT_SEAL")))
        # PARAPET-FALL (Wurzel-Befund Sadiku Bad WC / Angerer WK,
        # 2026-08-14): die Wand UNTER einem Fenster (Parapet 0,9-1,6 m)
        # liegt unter der Schnittebene — keine Poché, der Watershed sieht
        # keine Wand, der Raum flutet die Fensternische bis zur
        # Aussenkante (Bad WC +16,7 % Zellen, WK-Glasfront-Band). Der
        # Balken sitzt wie bei Tueren zwischen den Laibungs-Wandenden.
        # Fall C: EINE Seite ist ein Stempel-Raum, die andere AUSSEN
        # (kein Raumbecken binnen 1,2 m). Hinter FENSTER_SEAL, bis der
        # Korpus gemessen ist.
        # Standard AN seit 2026-08-14 (Korpus: Sadiku Oe 5,0->4,4 %, Bad WC
        # aus der Ausreisserliste; Angerer unveraendert; Guard entfernt
        # schaedliche Balken). FENSTER_SEAL=0 schaltet ab.
        # + "tuer" seit 2026-08-19 (Elternbad-Befund): bodentiefe Elemente
        # ("RPH 0 / STUK +5,59" = Fenstertuer/Balkontuer) sind wegen RPH 0
        # als TUER klassifiziert — der klassische Tuer-Pfad verlangt aber
        # dasselbe Label beidseitig und liess Innen/Aussen-Tueren durch
        # (Becken lief zur Glaslinie, Elternbad +9,1 %). Der Fluss traegt:
        # Parapet-Fall zuerst (eine Raum-Seite, eine Nicht-Raum-Seite);
        # Innentueren haben beidseitig Raum -> verworfen -> klassische
        # Tuer-Logik greift unveraendert.
        _ist_parapet = (o.get("typ") in ("fenster", "glasfront", "tuer")
                        and os.environ.get("FENSTER_SEAL", "1") != "0")
        if os.environ.get("GUARD_DEBUG") == "2":
            import traceback as _tb
            print(f"[anker] typ={o.get('typ')} cx={round(o.get('cx') or 0)} "
                  f"cy={round(o.get('cy') or 0)}")
        if not (_ist_tuer or _ist_front or _ist_parapet) or o.get("cx") is None:
            continue
        cx, cy = o["cx"], o["cy"]
        b = o.get("breite_m") or 0.9
        b_z = max(3, int(round(b * rst.ptm / rst.cell)))
        cap = max(4, int(round(1.8 * rst.ptm / rst.cell)))
        fen = max(2, int(round(1.0 * rst.ptm / rst.cell)))
        sp_min = max(3, int(round(0.45 * rst.ptm / rst.cell)))
        sp_max = int(round((2.6 if _ist_tuer else max(2.6, b * 1.25))
                           * rst.ptm / rst.cell))
        ci, cj = rst.ij(cx, cy)
        best = None
        for achse in ("h", "v"):
            for off in range(-fen, fen + 1):
                if achse == "h":
                    jj = cj + off
                    if not (0 <= jj < H):
                        continue
                    li = re2 = None
                    for d in range(cap + 1):
                        if li is None and 0 <= ci - d < W and grid[jj * W + ci - d]:
                            li = ci - d
                        if re2 is None and 0 <= ci + d < W and grid[jj * W + ci + d]:
                            re2 = ci + d
                        if li is not None and re2 is not None:
                            break
                    if li is None or re2 is None:
                        continue
                    sp, fest, lo, hi = re2 - li - 1, jj, li, re2
                else:
                    ii = ci + off
                    if not (0 <= ii < W):
                        continue
                    ob = un = None
                    for d in range(cap + 1):
                        if ob is None and 0 <= cj - d < H and grid[(cj - d) * W + ii]:
                            ob = cj - d
                        if un is None and 0 <= cj + d < H and grid[(cj + d) * W + ii]:
                            un = cj + d
                        if ob is not None and un is not None:
                            break
                    if ob is None or un is None:
                        continue
                    sp, fest, lo, hi = un - ob - 1, ii, ob, un
                if not (sp_min <= sp <= sp_max):
                    continue
                sc = (abs(sp - b_z), abs(off))
                if best is None or sc < best[0]:
                    best = (sc, achse, fest, lo, hi)
        if best is None:
            if (_ist_front or _ist_parapet) and os.environ.get("GUARD_DEBUG"):
                print(f"[front-miss] fenster ({cx:.0f},{cy:.0f}) b={b:.2f}m: "
                      f"kein Spalt {0.45:.2f}..{(sp_max*rst.cell/rst.ptm):.2f}m "
                      f"binnen cap={cap*rst.cell/rst.ptm:.1f}m gefunden")
            continue
        achse, fest, lo, hi = best[1], best[2], best[3], best[4]
        mid = (lo + hi) // 2
        max_s = max(3, int(round(1.2 * rst.ptm / rst.cell)))

        def _erste_raumzelle(vz):
            for d in range(1, max_s + 1):
                if achse == "h":
                    jj = fest + vz * d
                    if not (0 <= jj < H):
                        return None
                    idx = jj * W + mid
                else:
                    ii = fest + vz * d
                    if not (0 <= ii < W):
                        return None
                    idx = mid * W + ii
                if label[idx] >= 0:
                    return label[idx]
            return None

        l1, l2 = _erste_raumzelle(-1), _erste_raumzelle(+1)
        _parapet_trifft = False
        if _ist_parapet:
            # "Innen" = echter Stempel-Raum, der KEINE Aussenkategorie ist.
            # Alles andere (AUSSEN=None, stempellose Region, Loggia) ist
            # Nicht-Raum-Seite. Genau EINE Innen-Seite -> Nischen-Fall.
            def _raumseite(l):
                if l is None or not stempel or not (0 <= l < len(stempel)):
                    return False
                if _kat and 0 <= l < len(_kat) and _kat[l] == "Loggia":
                    return False
                return True
            _i1, _i2 = _raumseite(l1), _raumseite(l2)
            if _i1 == _i2 and os.environ.get("GUARD_DEBUG"):
                print(f"[parapet-verworfen] ({cx:.0f},{cy:.0f}) achse={achse} "
                      f"l1={l1} l2={l2} beide={'Raum' if _i1 else 'Nicht-Raum'}")
            if _i1 != _i2:
                _parapet_trifft = True
                l1 = l1 if _i1 else None    # Flucht-Schub Richtung Innen-Seite
                l2 = l2 if _i2 else None
                if os.environ.get("GUARD_DEBUG"):
                    _nm2 = stempel[(l1 if _i1 else l2)].get("name")
                    print(f"[parapet] {o.get('typ')} ({cx:.0f},{cy:.0f}) "
                          f"achse={achse} spann={(hi-lo)*rst.zm:.2f}m  "
                          f"{_nm2} <-> Nicht-Raum")
        if _ist_front and os.environ.get("GUARD_DEBUG"):
            _nm = lambda l: (stempel[l].get("name") if (stempel and l is not None
                             and 0 <= l < len(stempel)) else l)
            print(f"[front-kand] fenster ({cx:.0f},{cy:.0f}) b={b:.2f}m achse={achse} "
                  f"spann={(hi-lo-1)*rst.cell/rst.ptm:.2f}m  {_nm(l1)} <-> {_nm(l2)}")
        if _parapet_trifft:
            # DEN BALKEN AN DIE INNERE WANDFLUCHT SCHIEBEN (Befund WK:
            # neun Siegel, Wirkung null — der Balken lag an der Anker-
            # Zeile AUSSEN an der Nische, der Raum flutete die Nische bis
            # zum Balken und behielt sie). Die Laibungen (Pfosten lo/hi)
            # laufen einwaerts; ihr letztes gemeinsames Wand-Paar ist die
            # Raumgrenze. Bis 0,6 m einwaerts suchen.
            _vzr = -1 if l1 is not None else +1
            _tief = 0
            for _dd in range(1, int(0.6 * rst.ptm / rst.cell) + 1):
                _rr = fest + _vzr * _dd
                if not (0 <= _rr < (H if achse == "h" else W)):
                    break
                _j1 = (_rr * W + lo) if achse == "h" else (lo * W + _rr)
                _j2 = (_rr * W + hi) if achse == "h" else (hi * W + _rr)
                if grid[_j1] and grid[_j2]:
                    _tief = _dd
                else:
                    break
            fest = fest + _vzr * _tief
            if os.environ.get("GUARD_DEBUG") and _tief:
                print(f"[parapet]   -> Flucht {_tief} Zellen einwaerts")
        elif _ist_tuer:
            if l1 is None or l2 is None or l1 != l2:
                continue
        else:
            if not _ist_front:
                continue      # Fenster ohne FRONT_SEAL/Parapet-Treffer
            # Front: VERSCHIEDENE Raeume, genau eine Seite Aussenkategorie.
            if l1 is None or l2 is None or l1 == l2:
                continue
            # AUSSEN heisst: Loggia-Kategorie ODER Region ohne Stempel.
            # Befund Angerer-Ost (2026-08-13): die Glasfront WK<->Garten
            # grenzt an ein Becken OHNE Stempel (l2=10 bei 10 Stempeln) —
            # die reine Kategorie-Pruefung verwarf genau die Front, die
            # das Leck ist. Eine stempellose Region hinter einem Fenster-
            # Anker ist ein Aussenbereich-Indiz, kein Gegenbeweis. Die
            # INNEN-Seite muss weiterhin ein echter Stempel-Raum sein.
            def _aussen(l):
                return (not (0 <= l < len(_kat))) or _kat[l] == "Loggia"
            _a1, _a2k = _aussen(l1), _aussen(l2)
            if _a1 == _a2k:
                continue          # beide innen oder beide aussen -> kein Fall
            _li = l2 if _a1 else l1     # die Innen-Seite
            if not (0 <= _li < len(_kat)):
                continue
        # Lücke muss überwiegend FREI sein (sonst liegt der Verschluss
        # bereits, nur anders bewertet — nicht doppelt brennen).
        belegt = 0
        for t in range(lo + 1, hi):
            if grid[(fest * W + t) if achse == "h" else (t * W + fest)]:
                belegt += 1
        if belegt * 3 >= max(1, hi - lo - 1):
            continue
        # PFOSTEN-ZUSAMMENHANG: eine echte Tür sitzt in EINEM Wandzug —
        # beide Pfosten (die Wand-Enden li/re der Lücke) hängen über
        # Wandzellen LOKAL zusammen. Sind es zwei PARALLELE Wände (Nische,
        # Korridor-Vorsprung), würde der Balken eine Passage zumauern —
        # gemessen: WM-Bad −1,1 m² durch Balken quer zur Nische, Velden
        # E-Technik +0,6 m². Fenster des BFS: 1,6× die Spannweite — der
        # Wandzug schließt sich lokal um die Öffnung, der Weg ums Gebäude
        # zählt nicht als Verbindung.
        j1 = (fest * W + lo) if achse == "h" else (lo * W + fest)
        j2 = (fest * W + hi) if achse == "h" else (hi * W + fest)
        if not (grid[j1] and grid[j2]):
            continue
        if os.environ.get("GUARD_DEBUG") and not _ist_tuer:
            _n1 = (stempel[l1].get("name") if stempel and l1 is not None
                   and 0 <= l1 < len(stempel) else l1)
            _n2 = (stempel[l2].get("name") if stempel and l2 is not None
                   and 0 <= l2 < len(stempel) else l2)
            print(f"[front] {o.get('typ')} achse={achse} fest={fest} "
                  f"lo={lo} hi={hi} spann={(hi-lo)*rst.zm:.2f}m  {_n1} <-> {_n2}")
        span = hi - lo
        rad = max(int(span * 1.6), int(1.2 * rst.ptm / rst.cell))
        ci0, cj0 = j1 % W, j1 // W
        seen = bytearray(W * H)
        q = deque([j1])
        seen[j1] = 1
        verbunden = False
        while q and not verbunden:
            cur = q.popleft()
            ci_, cj_ = cur % W, cur // W
            for di, dj in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                ni, nj = ci_ + di, cj_ + dj
                if not (0 <= ni < W and 0 <= nj < H):
                    continue
                if abs(ni - ci0) > rad or abs(nj - cj0) > rad:
                    continue
                nidx = nj * W + ni
                if seen[nidx] or not grid[nidx]:
                    continue
                if nidx == j2:
                    verbunden = True
                    break
                seen[nidx] = 1
                q.append(nidx)
        if not verbunden:
            continue
        lecks.append((achse, fest, lo, hi))
      except Exception as _le:
        # SCHUTZFANG (Befund 2026-08-16): ein None-Vergleich in einer
        # DEBUG-Zeile wuergte die ganze Anker-Schleife ab — unter
        # GUARD_DEBUG sah die Telemetrie tagelang nur 2 von 27 Ankern,
        # waehrend Produktion (ohne Debug) korrekt lief. Ein einzelner
        # Anker-Fehler darf nie alle uebrigen Siegel kosten.
        if os.environ.get("GUARD_DEBUG"):
            import traceback
            print(f"[lecks-crash] {type(_le).__name__}: {_le}")
            traceback.print_exc()
        continue
    return lecks


# FASSADEN-LECK-VERSCHLUSS — GEMESSEN UND VERWORFEN (2026-08-05).
# Mechanismus: Raum↔AUSSEN-Übergänge ohne Wandzelle finden (Terrassentür
# ohne Bogen/FPH), gestuften Balken von Pfosten zu Pfosten entlang der
# Übergangs-Zeile, nur bei gezogener Grenzlinie (Rahmen/Rigol-Spur ≥60 %).
# Drei Befunde, alle am Korpus gemessen:
#  1. Übergang ≠ Leck: der F-Ausgleich balanciert die Becken-Grenze zur
#     byte-exakten Stempel-Fläche — die gemessene Grenze sitzt dabei ~0,5 m
#     INNERHALB der wahren Fassadenlinie, die Fläche stimmt trotzdem. Ein
#     Balken auf der gemessenen Linie schnitt reale Fläche weg (Angerer-
#     Terrasse F 31,12 → 26,40; der Guard reverted korrekt).
#  2. Balken auf der gezogenen Fassadenlinie stattdessen: F wächst über die
#     Stempel-Balance hinaus (F +9 %, aus dem Gate) — die Gutschriften sind
#     auf die alte Balance eingespielt (FERTIG/ROHBAU-Problem, keine Lösung
#     an dieser Stelle).
#  3. WM: AU-Türen 18 → 19 undicht (mess_tuer_dichtung Assertion).
#  Und strukturell: die Loggia-Glasfronten (der große Rest-Block) sind
# Raum-zu-Raum-Lecks, nicht Raum→AUSSEN — diese Klasse deckt der Mechanismus
# ohnehin nicht. Der Tür-Pfad (_tuer_lecks + Guard) bleibt unverändert.


def raum_kontur_exakt(poly_zl, grid, W, H, rst, dark_segs, stuetzen=None,
                      snap_m=0.35, paare=None, dbg_tag=None, max_raus_pt=None,
                      ein_budget_m2=None):
    """VEKTOR-EXAKTE Raumkontur: DP-Kanten (Zellen) an die gezeichneten
    Wandlinien des Plans snappen — pt-Präzision statt Rasterzelle.

    Nutzer-Befund: „so wie er die Räume in der App einzeichnet, passt es oft
    nicht ganz — er zeichnet die Räume nicht genau nach." Bisher snappte
    an_wand_schnappen auf die letzte freie RASTERZELLE vor der Wand —
    Zell-Auflösung (2-3 cm) plus Closing-Aufdickung, sichtbar als Saum mal
    im Raum, mal in der Wand. Die Wand-Außenkante liegt aber als VEKTOR-
    Linie im PDF: trägt eine Kante parallele dunkle Segmente im Fenster
    snap_m (kollineare Teilstücke geclustert, Deckung ≥50 % des Laufs),
    wird sie auf deren Stützgerade gelegt. Die Ecke ist dann der exakte
    Schnittpunkt zweier Wandlinien, nicht zwei gerundete Zellmitten — und
    F (Shoelace) / U (Kantensumme) auf dieser Kontur sind ohne Raster-
    Krenellierung und Halbzellen-Bias.

    Kandidaten-Ranking: erst Linien, die in der WAND-MASKE verankert sind
    (Poché-gestützt — Möbel-/Text-Linien sind das nicht), dann nächste
    Distanz. Kein Vektor-Treffer → Zell-Sonde wie an_wand_schnappen
    („raster"). Kein Wandtreffer → Stützen-Linie (offene Carport-Front,
    „stuetze") oder Kante bleibt unverändert („offen" — nichts erfinden).

    Rückgabe: {poly_pt, f_m2, u_m, snap_quote, vektor_quote, kanten} —
    snap_quote = Kantenlängen-Anteil mit Befestigung (vektor+raster+stuetze).
    """
    _budget_rest = [max(0.0, ein_budget_m2 or 0.0)]

    n = len(poly_zl or [])
    if n < 3:
        return None
    ptm, cell = rst.ptm, rst.cell
    pts = [(rst.bx0 + p[0] * cell, rst.by0 + p[1] * cell) for p in poly_zl]
    # Vektor-Vorfilter auf die Raum-BBox (Perf: dark_segs sind planweit)
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    mrg = snap_m * ptm + 2.0 * cell
    x0, x1 = min(xs) - mrg, max(xs) + mrg
    y0, y1 = min(ys) - mrg, max(ys) + mrg
    segs = []
    for s in (dark_segs or []):
        sx0, sy0, sx1, sy1 = s[0], s[1], s[2], s[3]
        if max(sx0, sx1) < x0 or min(sx0, sx1) > x1 \
                or max(sy0, sy1) < y0 or min(sy0, sy1) > y1:
            continue
        adx, ady = abs(sx1 - sx0), abs(sy1 - sy0)
        achse = "v" if adx <= 0.6 else ("h" if ady <= 0.6 else None)
        if achse is None:
            continue
        if math.hypot(adx, ady) < 3.0:     # <3 pt: Text/Symbol, keine Wand
            continue
        segs.append((achse, sx0, sy0, sx1, sy1))

    def _verankert(achse, c, a, b):
        """Liegt die Linie (v: x=c / h: y=c) im Lauf [a..b] in der Wand-Maske?
        5 Sonden längs, Treffer = Wandzelle ≤2 Zellen quer. Poché-Rücken."""
        tr = 0
        for t in (0.1, 0.3, 0.5, 0.7, 0.9):
            p_ = a + (b - a) * t
            ci = int((c - rst.bx0) / cell) if achse == "v" \
                else int((p_ - rst.bx0) / cell)
            cj = int((p_ - rst.by0) / cell) if achse == "v" \
                else int((c - rst.by0) / cell)
            for d in (-2, -1, 0, 1, 2):
                ii, jj = (ci + d, cj) if achse == "v" else (ci, cj + d)
                if 0 <= ii < W and 0 <= jj < H and grid[jj * W + ii]:
                    tr += 1
                    break
        return tr >= 3

    # AUSSENRICHTUNG AUS DER WINDUNG, nicht aus dem Schwerpunkt (Befund
    # Angerer-Erker 2026-08-14, KX-Telemetrie): bei NICHT-KONVEXEN Raeumen
    # zeigt die Schwerpunkt-Heuristik an Nischen-Kanten verkehrt — am
    # Sued-Erker gewann ein "+6cm"-Cluster, der geometrisch EINWAERTS lag,
    # und der Stempel-Deckel prüfte die falsche Richtung. Die Moore-
    # Kontur laeuft konsistent um den Raum; das Vorzeichen der signierten
    # Flaeche bestimmt fuer jede Kante die echte Aussennormale.
    _sig = 0.0
    for k in range(n):
        _ax, _ay = pts[k]
        _bx, _by = pts[(k + 1) % n]
        _sig += _ax * _by - _bx * _ay
    kanten = []
    for k in range(n):
        ax, ay = pts[k]
        bx, by = pts[(k + 1) % n]
        dx, dy = bx - ax, by - ay
        L = math.hypot(dx, dy)
        e = {"p1": (ax, ay), "p2": (bx, by), "L": L, "achse": None,
             "fest": None, "quelle": None, "vz_out": None}
        if L >= 0.10 * ptm:        # <10 cm: Zitterkante, nicht klassifizieren
            if abs(dx) <= 0.3 * abs(dy):
                e["achse"] = "v"
                _nx = dy if _sig > 0 else -dy
                e["vz_out"] = 1 if _nx > 0 else -1
            elif abs(dy) <= 0.3 * abs(dx):
                e["achse"] = "h"
                _ny = -dx if _sig > 0 else dx
                e["vz_out"] = 1 if _ny > 0 else -1
        kanten.append(e)

    snap_pt = snap_m * ptm
    # Schwerpunkt fuer die Aussenrichtung der Kanten (gleiche Konvention wie
    # der Raster-Rueckfall unten verwendet).
    _cxp = sum(p[0] for p in pts) / n
    _cyp = sum(p[1] for p in pts) / n
    for e in kanten:
        if not e["achse"]:
            continue
        (ax, ay), (bx, by) = e["p1"], e["p2"]
        if e["achse"] == "v":
            c_e, lo, hi = (ax + bx) / 2.0, min(ay, by), max(ay, by)
        else:
            c_e, lo, hi = (ay + by) / 2.0, min(ax, bx), max(ax, bx)
        l_kante = hi - lo
        # ── INNENKANTE ZUERST (Nutzer-Ansage 2026-08-08): "ein Raum ist nur
        # die Innenwand". Eine Wand ist ein LINIEN-PAAR (wand_paare:
        # Mittellinie + Dicke). Die Raumkante gehoert auf die RAUMSEITIGE
        # Linie des Paars — Mittellinie minus halbe Dicke Richtung Raum.
        # Das traegt die Seiten-Semantik, die der Einzellinien-Cluster nicht
        # hat: dort gewann die NAECHSTE Linie, mal innen, mal aussen
        # (gemessen +3-7 cm Drift; zwei Seitenwahl-Versuche ohne Paar-
        # Kontext blieben wirkungslos, s. Historie oben).
        if paare:
            _vz = e.get("vz_out") or (1 if c_e > (_cxp if e["achse"] == "v" else _cyp) else -1)
            _dbg = (dbg_tag is not None and os.environ.get("IK_DEBUG"))
            if _dbg:
                print(f"[ikc] tag={dbg_tag} achse={e['achse']} c_e={c_e:.1f} "
                      f"lo={lo:.1f} hi={hi:.1f} vz={_vz}")
            _bp = None
            for _w in paare:
                if _w.get("achse") != e["achse"]:
                    continue
                if e["achse"] == "v":
                    _wc, _wlo, _whi = _w["x0"], min(_w["y0"], _w["y1"]), max(_w["y0"], _w["y1"])
                else:
                    _wc, _wlo, _whi = _w["y0"], min(_w["x0"], _w["x1"]), max(_w["x0"], _w["x1"])
                _cov = min(hi, _whi) - max(lo, _wlo)
                _d = _w.get("dist_pt") or 0.0
                _face0 = _wc - _vz * _d / 2.0
                if _dbg and abs(_face0 - c_e) <= 2.0 * snap_pt and _cov > 0:
                    _grund = ("deck" if _cov < 0.5 * l_kante else
                              ("seite" if (_wc - c_e) * _vz < -0.25 * _d else
                               ("fenster" if abs(_face0 - c_e) > snap_pt else "ok")))
                    print(f"[ikk] tag={dbg_tag} achse={e['achse']} c_e={c_e:.1f} "
                          f"center={_wc:.1f} d={_d:.1f} face={_face0:.1f} "
                          f"cov={_cov:.0f}/{l_kante:.0f} dicke={_w.get('dicke_cm')} "
                          f"hatch={_w.get('hatch_dichte')} grund={_grund}")
                if _cov < 0.5 * l_kante:
                    continue          # Wand deckt den Kantenlauf nicht
                if (_wc - c_e) * _vz < -0.25 * _d:
                    continue          # Wand liegt NICHT auswaerts der Kante
                _face = _face0
                if abs(_face - c_e) > snap_pt:
                    continue
                # AUSWAERTS-DECKEL, vom Overlay abgeleitet (ik_Zimmer1.png):
                # die Rasterkante sitzt bereits AUF der gezeichneten
                # Innenlinie — jeder Kandidat, der die Kante mehr als ~3 cm
                # nach AUSSEN zieht, ist eine andere Linie (Putz/Aussenface/
                # Nachbar) und blaeht den Raum. Einwaerts (bis 10 cm) ist
                # erlaubt: dort korrigiert der Snap echte Raster-Ausfransung.
                _raus = (_face - c_e) * _vz
                if _raus > 0.03 * ptm or _raus < -0.10 * ptm:
                    continue
                # DIE NAECHSTE WAND gewinnt, nicht die naechste FLAECHE:
                # sortiert wird nach der Auswaerts-Distanz der MITTELLINIE.
                # Gemessen: Face-Distanz als Kriterium griff am Geraete-
                # Abstellraum ein Steinmauer-Textur-Paar weiter draussen
                # (+9,0 -> +18,7 %), waehrend dasselbe 35-cm-Fenster mit
                # Waschen (9,9 -> 1,8 %) und Flur zeigte, dass die echte
                # Innenlinie erreichbar ist. Ein zu enges 8-cm-Fenster
                # erreichte sie nicht (Raster-Kante liegt durch das Closing
                # ~4-8 cm INNERHALB der gezeichneten Innenlinie).
                # Auswahl: naechste FACE. Mit poché-gegateten Kandidaten ist
                # das die stabile Regel (Face-Distanz war schon mit dreckigen
                # Kandidaten die beste der drei gemessenen; die Ausreisser
                # kamen aus Textur-Paaren, die das Gate jetzt entfernt).
                if _bp is None or abs(_face - c_e) < _bp[0]:
                    _bp = (abs(_face - c_e), _face)
            if _bp is not None:
                e["fest"], e["quelle"] = _bp[1], "paar"
                if os.environ.get("IK_DEBUG"):
                    print(f"[ik] {e['achse']} c_e={c_e:7.1f} face={_bp[1]:7.1f} "
                          f"versatz_auswaerts={( _bp[1]-c_e)*_vz/ptm*100:+5.1f}cm "
                          f"L={l_kante/ptm:4.1f}m")
                continue
        # Kandidaten: gleiche Achslage, Abstand ≤ snap_pt → nach Koordinate
        # clustern (eine Wandlinie ist oft in Teilstücke gezeichnet: Türen,
        # Kreuzungen). Cluster-Deckung ≥50 % des Kantenlaufs nötig.
        kand = []
        for (achse, sx0, sy0, sx1, sy1) in segs:
            if achse != e["achse"]:
                continue
            if achse == "v":
                c_s, slo, shi = sx0, min(sy0, sy1), max(sy0, sy1)
            else:
                c_s, slo, shi = sy0, min(sx0, sx1), max(sx0, sx1)
            if abs(c_s - c_e) <= snap_pt:
                kand.append((c_s, slo, shi))
        kand.sort()
        cluster = []
        for (c_s, slo, shi) in kand:
            if cluster and abs(c_s - cluster[-1][0]) <= 1.5:
                cluster[-1][1].append((slo, shi))
                # gewichtete Cluster-Koordinate nachlaufend mitsammeln
                cluster[-1][0] = (cluster[-1][0] * cluster[-1][2] + c_s) \
                    / (cluster[-1][2] + 1)
                cluster[-1][2] += 1
            else:
                cluster.append([c_s, [(slo, shi)], 1])
        beste = None
        # STEMPEL-GERICHTETER AUSWAERTS-DECKEL (Stufen-Messung 2026-08-10):
        # Auf Angerer sind die DP-Polygone +1..2 % am Stempel, der Cluster-
        # Snap zog sie auf +8..9 % (laengere AUSSEN-Linien gewinnen die
        # 50-%-Deckung, weil Innenlinien von Tueren unterbrochen sind).
        # Auf WM sind echte Raeume auf Zellebene ZU KLEIN (-13..-21 %) und
        # der Auswaerts-Zug hilft. Darum entscheidet der Aufrufer per
        # max_raus_pt: DP >= Stempel -> Deckel (+3 cm), DP < Stempel ->
        # unbegrenzt wie bisher. Der Stempel gibt die Richtung vor.
        _vz_cl = None
        if max_raus_pt is not None:
            _vz_cl = e.get("vz_out") or (1 if c_e > (_cxp if e["achse"] == "v" else _cyp) else -1)
        _kxd = os.environ.get("KX_DEBUG")
        _kxd = (_kxd is not None and str(dbg_tag) == _kxd)
        for (c_cl, spans, _nz) in cluster:
            if _kxd:
                _d0 = 0.0; _e0 = lo
                for (_sl, _sh) in sorted(spans):
                    if _sh <= _e0: continue
                    _d0 += _sh - max(_sl, _e0); _e0 = _sh
                print(f"[kx] kante {e['achse']} c_e={c_e:.0f} "
                      f"lauf={l_kante/rst.ptm:.2f}m  cluster "
                      f"d={(c_cl-c_e)/rst.ptm*100:+.0f}cm "
                      f"deck={_d0/max(1,l_kante)*100:.0f}% n={_nz}")
            _budget_kand = 0.0
            if _vz_cl is not None:
                _versch = (c_cl - c_e) * _vz_cl
                # BEIDE Richtungen deckeln: nur auswaerts zu sperren liess
                # die Kante ungebremst EINWAERTS auf Moebel-/Regal-Linien
                # schnappen (gemessen: Geraete-Abstellraum +9,0 -> -15,7 %).
                if _versch > max_raus_pt:
                    continue
                if _versch < -0.10 * rst.ptm:
                    # STEMPEL-BUDGETIERTER TIEFEN-SNAP: einwaerts bis 0,30 m
                    # erlaubt, aber nur solange das Polygon ueber dem
                    # byte-exakten Stempel bleibt. VOLLE Verschiebung wird
                    # gebucht (Kantenlauf x Versatz).
                    if ein_budget_m2 is None or _versch < -0.301 * rst.ptm:
                        continue
                    _budget_kand = l_kante * (-_versch) / (rst.ptm * rst.ptm)
                    if _budget_kand > _budget_rest[0]:
                        if _kxd:
                            print(f"[kx]   -> tief d={_versch/rst.ptm*100:.0f}cm "
                                  f"braucht {_budget_kand:.2f}m2 > Budget "
                                  f"{_budget_rest[0]:.2f}")
                        continue
            # Deckung: Vereinigung der Spannen auf den Kantenlauf.
            # BAND_SNAP-Experiment (2026-08-17): budget-gedeckte TIEFEN-
            # Kandidaten (die innere Ausbaulinie) sind oft fragmentiert
            # (Eltern-Nordkante: -23cm mit 40%, -30cm mit 34%) — fuer SIE
            # gilt 0,30 statt 0,50; das Budget (Polygon >= Stempel)
            # deckelt den Schaden eines Fehl-Snaps ohnehin.
            deck = 0.0
            ende = lo
            for (slo, shi) in sorted(spans):
                if shi <= ende:
                    continue
                deck += shi - max(slo, ende)
                ende = shi
            _deck_min = (0.30 if (_budget_kand > 0 and
                                  os.environ.get("BAND_SNAP", "1") != "0") else 0.5)
            if deck < _deck_min * l_kante:
                continue
            ver = _verankert(e["achse"], c_cl, lo, hi)
            # BAND_SNAP: hat der Raum Schrumpf-Budget (Polygon ueber dem
            # Stempel), gewinnt unter den zulaessigen Kandidaten der
            # TIEFSTE Innen-Kandidat — die naechste Linie ist bei Band-
            # Raeumen genau die falsche (aeussere Rohbau-)Linie.
            if _budget_kand > 0 and os.environ.get("BAND_SNAP", "1") != "0":
                key = (0 if ver else 1, -abs(c_cl - c_e))
            else:
                key = (0 if ver else 1, abs(c_cl - c_e))
            if beste is None or key < beste[0]:
                beste = (key, c_cl, _budget_kand)
        if beste is not None:
            e["fest"], e["quelle"] = beste[1], "vektor"
            if len(beste) > 2 and beste[2]:
                _budget_rest[0] -= beste[2]
            if _kxd:
                print(f"[kx]   WAHL d={(beste[1]-c_e)/rst.ptm*100:+.0f}cm "
                      f"kost={beste[2] if len(beste)>2 else 0:.2f} "
                      f"budget_rest={_budget_rest[0]:.2f}")
            continue
        # RASTER-RUECKFALL (an_wand_schnappen-Logik, pt): von der Kante nach
        # außen sondieren bis zur ersten Wandzelle; Kante auf die letzte
        # freie Zelle davor. Offene Kante (Durchgang) bleibt unverändert.
        cxp = sum(p[0] for p in pts) / n
        cyp = sum(p[1] for p in pts) / n
        treffer = []
        for t in (0.25, 0.5, 0.75):
            p_ = lo + l_kante * t
            for d in range(0, 9):
                if e["achse"] == "v":
                    vz = e.get("vz_out") or (1 if c_e > cxp else -1)
                    ii = int((c_e - rst.bx0) / cell) + vz * d
                    jj = int((p_ - rst.by0) / cell)
                else:
                    vz = e.get("vz_out") or (1 if c_e > cyp else -1)
                    ii = int((p_ - rst.bx0) / cell)
                    jj = int((c_e - rst.by0) / cell) + vz * d
                if not (0 <= ii < W and 0 <= jj < H):
                    break
                if grid[jj * W + ii]:
                    zell = (ii - vz) if e["achse"] == "v" else (jj - vz)
                    fest_pt = (rst.bx0 if e["achse"] == "v" else rst.by0) \
                        + (zell + 0.5) * cell
                    treffer.append(fest_pt)
                    break
        if len(treffer) >= 2:
            treffer.sort()
            e["fest"], e["quelle"] = treffer[len(treffer) // 2], "raster"
            continue
        # STÜTZEN-LINIE (offene Carport-Front): ≥2 Stützen auf einer Flucht
        # im Fenster ≤1,5 m → die Dachkante läuft durch die Stützen.
        if stuetzen:
            nahe = []
            for (sx, sy) in stuetzen:
                if e["achse"] == "v":
                    if abs(sx - c_e) <= 1.5 * ptm and lo - ptm <= sy <= hi + ptm:
                        nahe.append(sx)
                else:
                    if abs(sy - c_e) <= 1.5 * ptm and lo - ptm <= sx <= hi + ptm:
                        nahe.append(sy)
            if len(nahe) >= 2:
                mittel = sum(nahe) / len(nahe)
                streu = (sum((v - mittel) ** 2 for v in nahe) / len(nahe)) ** 0.5
                if streu <= 0.30 * ptm:
                    e["fest"], e["quelle"] = mittel, "stuetze"
    # Ecken als Schnittpunkte der (evtl. gesnappten) Trägergeraden neu setzen
    neu = []
    for k in range(n):
        e = kanten[k]
        v = kanten[(k - 1) % n]
        x, y = pts[k]
        if v["achse"] == "v" and v["fest"] is not None:
            x = v["fest"]
        if v["achse"] == "h" and v["fest"] is not None:
            y = v["fest"]
        if e["achse"] == "v" and e["fest"] is not None:
            x = e["fest"]
        if e["achse"] == "h" and e["fest"] is not None:
            y = e["fest"]
        neu.append((x, y))
    # Duplikat-Ecken (durch Snap kollabiert) entfernen
    neu = [p for k, p in enumerate(neu)
           if math.hypot(p[0] - neu[k - 1][0], p[1] - neu[k - 1][1]) > 1e-6]
    if len(neu) < 3:
        return None
    a2 = 0.0
    u_pt = 0.0
    m = len(neu)
    for k in range(m):
        x1_, y1_ = neu[k]
        x2_, y2_ = neu[(k + 1) % m]
        a2 += x1_ * y2_ - x2_ * y1_
        u_pt += math.hypot(x2_ - x1_, y2_ - y1_)
    len_ges = sum(e["L"] for e in kanten) or 1.0
    len_snap = sum(e["L"] for e in kanten if e["quelle"])
    len_vek = sum(e["L"] for e in kanten if e["quelle"] == "vektor")
    return {"poly_pt": neu,
            "f_m2": abs(a2) / 2.0 / (ptm * ptm),
            "u_m": u_pt / ptm,
            "snap_quote": len_snap / len_ges,
            "vektor_quote": len_vek / len_ges,
            "kanten": [{"quelle": e["quelle"], "achse": e["achse"],
                        "fest": e["fest"],
                        "L_m": round(e["L"] / ptm, 2)} for e in kanten]}


def _draussen_maske(grid, label, W, H):
    """Unbeschriftete (−1) Freizellen, die mit dem RASTER-RAND verbunden sind.

    Flut-Phase 2 erreicht schmale Außenstreifen an dicken Fassaden nicht
    (kein Kern, kein Weg ums Gebäude) — sie bleiben −1, obwohl sie DRAUSSEN
    sind (Angerer-Südfassade: 12,7 m „unbekannte" Außenwand gemessen). Eine
    BFS vom Rand über freie Zellen trennt das von INNEREN −1-Taschen
    (Schächte): draussen[i]=1 ⇔ Außenbereich."""
    draussen = bytearray(W * H)
    q = deque()
    for i in range(W):
        for j in (0, H - 1):
            idx = j * W + i
            if not grid[idx] and label[idx] < 0 and not draussen[idx]:
                draussen[idx] = 1
                q.append(idx)
    for j in range(H):
        for i in (0, W - 1):
            idx = j * W + i
            if not grid[idx] and label[idx] < 0 and not draussen[idx]:
                draussen[idx] = 1
                q.append(idx)
    while q:
        idx = q.popleft()
        i, j = idx % W, idx // W
        for di, dj in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            ni, nj = i + di, j + dj
            if 0 <= ni < W and 0 <= nj < H:
                nidx = nj * W + ni
                if not draussen[nidx] and not grid[nidx] and label[nidx] < 0:
                    draussen[nidx] = 1
                    q.append(nidx)
    return draussen


def raum_umfassung(poly_pt, grid, label, rst, ridx, AUSSEN, stempel,
                   oeffnungen=None, boegen=None, dark_segs=None,
                   draussen=None):
    """UMFASSUNGS-ZERLEGUNG eines Raums — wo hört der Raum auf, und WOMIT?

    Nutzer-Befund: „er muss erkennen, wann ein Raum aufhört und anfängt, wo
    die Innenmauer, wo die Außenmauer ist." Die exakte Kontur (raum_kontur_
    exakt) sagt WO die Grenze läuft — diese Zerlegung sagt, WAS sie ist:
    jeder Umfang-Schritt wird quer nach außen sondiert und klassifiziert:

      aussenwand  — Wandband, dahinter AUSSEN
      innenwand   — Wandband, dahinter ein anderer Raum (Nachbar-Name dabei)
      tuer        — Öffnung im Band (Bogen byte-exakt bzw. Tür-Text), Raum
                    endet an der Laibung — die Farbe darf NICHT durchlaufen
      offen       — kein Wandband (Durchgang/Carport-Front)
      unbekannt   — Band dahinter unbeschriftet → ehrlich, nicht geraten

    Die Segment-Summen sind die Abwicklungs-Grundlage je Wandart (Innenputz
    außen ≠ innen). Wandstärke wird am Band selbst gemessen (Zellzahl × zm),
    nicht aus der Legende geraten.

    Rückgabe: {segmente: [{p0, p1, klasse, laenge_m, dicke_cm, nachbar}],
               klassen_m: {…}, anteil_klassifiziert, u_m} — segmente in
    Umlauf-Reihenfolge, Σ laenge_m == u_m (die Kontur ist partitioniert).
    """
    n = len(poly_pt or [])
    if n < 3 or grid is None or label is None:
        return None
    W, H = rst.W, rst.H
    ptm, zm = rst.ptm, rst.zm
    schritt_m = 0.05
    # Sondentiefe 1,05 m: die Maske dickt Außenwände auf (Poché-Dilatation +
    # Closing ≈ +0,2 m) — eine 50er-Hülle wird 0,7 m dick, die alten 0,75 m
    # starben IM Band (Wohnraum-Südfassade „unbekannt", gemessen). Innen
    # ändert das nichts: die erste FREIE Zelle hinter dem (dünneren) Band
    # entscheidet — sie kommt bei jeder Wandstärke vor der Kappe.
    max_sonde = 1.05

    def _sonde(x, y, nx, ny):
        """Quer-Sonde ab Konturpunkt (x,y) Richtung (nx,ny) (Einheitsvektor,
        nach außen). → (klasse, dicke_m, nachbar_label).

        Band-Dicke = das ERSTE zusammenhängende Wandband (1-Zell-Rasterlöcher
        geduldet, 2 freie Schritte hintereinander = Bandende) — das frühere
        „4 cm frei"-Fenster sprang über Laibungs-Lücken in das NÄCHSTE Band
        und maß 47-75 cm-Monster (gemessen am Angerer-Korpus). Nachbar-Label =
        Mehrheits-Label der ersten 3 freien Zellen hinter dem Band (das
        Ein-Zell-Votum kippte an Wand-Knoten zwischen Räumen)."""
        wand_an = None
        dicke = 0.0
        stille = 0
        d = 0.5 * zm
        freie = []                       # Labels hinter dem Band (für Mehrheit)
        raus = False                     # Sonde lief aus dem Raster
        while d <= max_sonde:
            i, j = rst.ij(x + nx * d * ptm, y + ny * d * ptm)
            if not (0 <= i < W and 0 <= j < H):
                raus = True
                break
            if grid[j * W + i]:
                if wand_an is not None and stille > 0:
                    # Loch IM Band: weiter zählen, Stille zurück
                    dicke = d - wand_an + zm
                    stille = 0
                elif wand_an is None:
                    wand_an = d
                    dicke = zm
                else:
                    dicke = d - wand_an + zm
            elif wand_an is not None:
                stille += 1
                freie.append((label[j * W + i], j * W + i))
                if stille >= 2:
                    break
            d += 0.5 * zm
        if wand_an is None:
            return ("offen", 0.0, None)
        # Raster-ENDE hinter einem Wandband = Gebäudekante: draußen liegt
        # jenseits der Plan-Box das Freie — das ist die Außenwand (sonst
        # blieben Fassaden an der Box-Kante „unbekannt", gemessen am
        # Angerer-Wohnraum: 12,7 m unbekannt, davon 8 m Südfassade).
        if raus:
            return ("aussenwand", min(dicke, 0.60), None)
        if not freie:
            # Sonde STIRBT IM BAND: Maske ist aufgedickt (Poché-Dilatation +
            # Closing ≈ +0,2 m über die reale Wand) — eine 50er-Außenwand
            # wird 0,7 m dick, die 0,75-m-Sonde kommt nicht durch. Nahe der
            # Raster-Kante ist ein ≥0,25-m-Band die Hülle (innen ist keine
            # Wand so dick UND so randnah) → Außenwand.
            if dicke >= 0.25 and min(x - rst.bx0, rst.bx1 - x,
                                     y - rst.by0, rst.by1 - y) <= 1.2 * ptm:
                return ("aussenwand", min(dicke, 0.60), None)
            return ("unbekannt", min(dicke, 0.60), None)   # Band aus dem Raster
        # Mehrheits-Label der ersten freien Zellen
        votes = {}
        for lf, _ix in freie[:3]:
            votes[lf] = votes.get(lf, 0) + 1
        lab = max(votes.items(), key=lambda kv: kv[1])[0]
        if lab == AUSSEN:
            return ("aussenwand", min(dicke, 0.60), None)
        if 0 <= lab < AUSSEN:
            return ("innenwand", min(dicke, 0.60), lab)
        # Label −1 hinter dem Band: Flut-Phase 2 erreicht schmale Außen-
        # streifen an dicken Fassaden nicht (kein Kern, kein Weg ums Gebäude
        # — Angerer-Südfassade 12,7 m „unbekannte" Außenwand gemessen).
        # Mit Rand verbundene −1-Zellen = draussen → Außenwand; innen
        # liegende −1-Taschen (Schächte) bleiben ehrlich unbekannt.
        if draussen is not None:
            for _lf2, _ix2 in freie:
                if draussen[_ix2]:
                    return ("aussenwand", min(dicke, 0.60), None)
        elif min(x - rst.bx0, rst.bx1 - x, y - rst.by0, rst.by1 - y) <= 1.2 * ptm:
            return ("aussenwand", min(dicke, 0.60), None)
        return ("unbekannt", min(dicke, 0.60), None)

    # Tür-Spannen entlang der Kontur: Bogen (byte-exakt: Angel + geschlossenes
    # Ende = Öffnungslinie in der Wandflucht) als Linien-Geometrie. FLÜGEL-
    # ABLAGE: hinge→a und hinge→b sind Öffnungslinie UND BLATT-Richtung —
    # das Blatt liegt im Freiraum (Tür-Zonen-Veto der Wand-Maske), die
    # Öffnungslinie im Band (Verschluss-Balken). Masken-Deckung entscheidet
    # (≥0,2 Differenz), sonst bleiben beide (unversiegelte Tür = beide frei).
    bogen_linien = []
    for bg in (boegen or []):
        hx, hy = bg["hinge"]

        def _deck(ende):
            tr = 0
            for k2 in range(21):
                t2 = k2 / 20.0
                i2, j2 = rst.ij(hx + (ende[0] - hx) * t2,
                                hy + (ende[1] - hy) * t2)
                if not (0 <= i2 < W and 0 <= j2 < H):
                    continue
                gef = False
                for di2 in (-1, 0, 1):
                    for dj2 in (-1, 0, 1):
                        ii3, jj3 = i2 + di2, j2 + dj2
                        if 0 <= ii3 < W and 0 <= jj3 < H and grid[jj3 * W + ii3]:
                            gef = True
                            break
                    if gef:
                        break
                tr += 1 if gef else 0
            return tr / 21.0

        ca, cb = _deck(bg["a"]), _deck(bg["b"])
        if ca >= cb + 0.2 and ca >= 0.5:
            bogen_linien.append((hx, hy, bg["a"][0], bg["a"][1]))
        elif cb >= ca + 0.2 and cb >= 0.5:
            bogen_linien.append((hx, hy, bg["b"][0], bg["b"][1]))
        else:
            # unklar/unversiegelt (beide <0,5) → beide (Fallback: sonst
            # verliert die Tür ihre Markierung — Waschen 2→1 gemessen)
            for ende in (bg["a"], bg["b"]):
                bogen_linien.append((hx, hy, ende[0], ende[1]))
    # Tür-TEXTE: der Anker sitzt NEBEN der Wand und trägt keine Richtung —
    # die Spanne wird auf die nächste Kontur-Kante projiziert (senkrechter
    # Abstand ≤0,45 m) und dort mittig mit Nennbreite markiert. (Früher lag
    # die Spanne waagrecht durch den Anker: an einer senkrechten Wand
    # markierte sie 1,85 m statt 0,86 m — gemessen am Angerer-WC.)
    text_tueren = [(o["cx"], o["cy"], (o.get("breite_m") or 0.9))
                   for o in (oeffnungen or [])
                   if o.get("typ") == "tuer" and o.get("cx") is not None]

    schritte = []        # [x, y, klasse, dicke_m, nachbar, kante, lauf_pt]
    for k in range(n):
        x1, y1 = poly_pt[k]
        x2, y2 = poly_pt[(k + 1) % n]
        dx, dy = x2 - x1, y2 - y1
        L = math.hypot(dx, dy)
        if L < 1e-6:
            continue
        # Normale: beide Seiten testen — die Seite mit dem eigenen Label ist
        # innen (robust auch für konkave Ecken, Schwerpunkt-Tricks versagen)
        nx0, ny0 = -dy / L, dx / L
        i_p, j_p = rst.ij(x1 + dx * 0.5 + nx0 * 2 * rst.cell,
                          y1 + dy * 0.5 + ny0 * 2 * rst.cell)
        innen_plus = (0 <= i_p < W and 0 <= j_p < H
                      and label[j_p * W + i_p] == ridx)
        nx, ny = (nx0, ny0) if not innen_plus else (-nx0, -ny0)
        n_s = max(1, int(L / (schritt_m * ptm)))
        for s in range(n_s):
            t = (s + 0.5) / n_s
            x, y = x1 + dx * t, y1 + dy * t
            klasse, dicke, nachbar = _sonde(x, y, nx, ny)
            # Dünnes Band (<5,5 cm) = Glasfront-/Leichtwand-Linie: die Klasse
            # (innen/außen) stimmt, die DICKE ist unzuverlässig → nicht in
            # die Median-Dicke einrechnen.
            if 0 < dicke < 0.055:
                dicke = 0.0
            schritte.append([x, y, klasse, dicke, nachbar, k, t * L])

    # TÜR-OVERLAY a) Bögen: Querschatten der Öffnungslinie (senkrecht ≤0,30 m,
    # Projektion innerhalb der Spanne, byte-exakt Angel→Ende). RICHTUNGS-
    # FILTER: die Tür-Linie liegt IN der Wand — Schritte der SENKRECHT
    # dazu anschließenden Wand projizieren sonst auf den Angelpunkt und
    # blähen die „Tür" um ~0,3 m über die Laibung hinaus (gemessen: 1,29 m
    # statt 0,86 m am Angerer-Korpus). Tür-ID mitführen: zwei Türen zur
    # selben Nachbar-Richtung bleiben ZWEI Segmente (kein 2-m-Verbund).
    for st in schritte:
        x, y = st[0], st[1]
        kx1, ky1 = poly_pt[st[5]]
        kx2, ky2 = poly_pt[(st[5] + 1) % n]
        kL = math.hypot(kx2 - kx1, ky2 - ky1) or 1.0
        kux, kuy = (kx2 - kx1) / kL, (ky2 - ky1) / kL
        trifft = None
        for _bi, (ax_, ay_, bx_, by_) in enumerate(bogen_linien):
            dx_, dy_ = bx_ - ax_, by_ - ay_
            L2 = dx_ * dx_ + dy_ * dy_
            if L2 < 1e-6:
                continue
            L_ = math.sqrt(L2)
            if abs((dx_ * kux + dy_ * kuy) / L_) < 0.7:
                continue    # Linie nicht parallel zur Kante des Schritts
            t = ((x - ax_) * dx_ + (y - ay_) * dy_) / L2
            if not (0.0 <= t <= 1.0):
                continue
            qx, qy = ax_ + t * dx_, ay_ + t * dy_
            if math.hypot(x - qx, y - qy) / ptm <= 0.30:
                trifft = _bi
                break
        if trifft is not None and st[2] in ("innenwand", "aussenwand", "unbekannt"):
            st[2] = "tuer"
            st.append(("bogen", trifft))
    # TÜR-OVERLAY b) Texte: auf die nächste Kante projiziert, Nennbreite mittig.
    # BREITE DURCHGANGS-REGEL: >1,4 m ohne Bogen ist auf Wohnungsplänen der
    # OFFENE DURCHGANG (kein Türblatt, kein Bogen — Flur↔Wohnküche 2,2 m am
    # Angerer-Plan, bisher fälschlich „tuer"). Ausnahme: Glas-/Schiebefronten
    # (WM-Loggia 2,5-3,1 m) haben KEINEN Bogen, aber gezogene Front-Linien —
    # ≥1 Linie parallel zur Kante, ≥50 % der Nennbreite, ≤0,35 m Abstand.
    for _ti, (tx, ty, tb_m) in enumerate(text_tueren):
        beste = None
        for k in range(n):
            x1, y1 = poly_pt[k]
            x2, y2 = poly_pt[(k + 1) % n]
            dx, dy = x2 - x1, y2 - y1
            L = math.hypot(dx, dy)
            if L < 1e-6:
                continue
            ux, uy = dx / L, dy / L
            s = (tx - x1) * ux + (ty - y1) * uy
            q = abs(-(tx - x1) * uy + (ty - y1) * ux)
            if -0.2 * L <= s <= 1.2 * L and (beste is None or q < beste[0]):
                beste = (q, k, s, ux, uy)
        if beste is None or beste[0] > 0.45 * ptm:
            continue
        _q, k_z, s_z, ux_z, uy_z = beste
        halbe = (tb_m / 2.0) * ptm
        klasse_t = "tuer"
        if tb_m > 1.4:
            bogen_da = False
            for (ax_, ay_, bx_, by_) in bogen_linien:
                mx_, my_ = (ax_ + bx_) / 2.0, (ay_ + by_) / 2.0
                if abs((mx_ - tx) * ux_z + (my_ - ty) * uy_z) <= halbe + 0.5 * ptm:
                    bogen_da = True
                    break
            glas_da = False
            if not bogen_da and dark_segs:
                for _s3 in dark_segs:
                    _dx3, _dy3 = _s3[2] - _s3[0], _s3[3] - _s3[1]
                    _L3 = math.hypot(_dx3, _dy3)
                    if _L3 < halbe or _L3 < 1e-6:
                        continue    # kürzer als 50 % der Nennbreite
                    if abs((_dx3 * ux_z + _dy3 * uy_z) / _L3) < 0.87:
                        continue    # nicht parallel zur Kante
                    _mx3, _my3 = (_s3[0] + _s3[2]) / 2.0, (_s3[1] + _s3[3]) / 2.0
                    _s3p = (_mx3 - tx) * ux_z + (_my3 - ty) * uy_z
                    _q3 = abs(-(_mx3 - tx) * uy_z + (_my3 - ty) * ux_z)
                    if abs(_s3p - s_z) <= halbe and _q3 <= 0.35 * ptm:
                        glas_da = True
                        break
            if not bogen_da and not glas_da:
                klasse_t = "offen"
        for st in schritte:
            if st[5] == k_z and abs(st[6] - s_z) <= halbe:
                if klasse_t == "offen" and st[2] in ("innenwand", "aussenwand",
                                                     "unbekannt"):
                    st[2] = "offen"
                    st[4] = None
                elif klasse_t == "tuer" and st[2] in ("innenwand", "aussenwand",
                                                      "unbekannt"):
                    st[2] = "tuer"
                    st.append(("text", _ti))

    # RAUHEIT GLÄTTEN: Einzelsonden kippen an Wand-Knoten/Rasterlücken
    # (gemessen: 5-cm-Fragmente „innenwand→eigener Raum"). Regeln:
    # (1) Nachbar = EIGENER Raum → unbekannt (die Sonde rutschte um eine
    #     Nische herum — keine Wand zwischen dem Raum und sich selbst);
    # (2) Mehrheits-Filter ±2 Schritte über der Klassenfolge — „tuer" ist
    #     klebrig (eine echte Tür soll kein Zitter-Split zerhacken).
    for st in schritte:
        if st[2] == "innenwand" and st[4] == ridx:
            st[2], st[4] = "unbekannt", None
    n_s = len(schritte)
    if n_s:
        gegl = []
        for i in range(n_s):
            if schritte[i][2] == "tuer":
                gegl.append(schritte[i])
                continue
            votes = {}
            for k in range(max(0, i - 2), min(n_s, i + 3)):
                kk = (schritte[k][2], schritte[k][4])
                votes[kk] = votes.get(kk, 0) + (3 if kk[0] == "tuer" else 1)
            best = max(votes.items(), key=lambda kv: kv[1])[0]
            gegl.append([schritte[i][0], schritte[i][1], best[0],
                         schritte[i][3], best[1], schritte[i][5],
                         schritte[i][6]])
        schritte = gegl

    # Laufbildung: gleiche Klasse+Nachbar(+Tür-ID) zusammenfassen; Mini-Läufe
    # (<12 cm) dem Nachbarlauf zuschlagen (Raster-Zitter), Tür-Läufe nie
    # verschmelzen. Die Tür-ID hält zwei Türen zur selben Nachbar-Richtung
    # als ZWEI Segmente auseinander (kein 2-m-Verbund über die Laibungen).
    lauefe = []
    for st in schritte:
        key = (st[2], st[4], (st[7] if st[2] == "tuer" and len(st) > 7 else None))
        if lauefe and lauefe[-1]["key"] == key:
            lauefe[-1]["pkt"].append(st)
        else:
            lauefe.append({"key": key, "pkt": [st]})
    if len(lauefe) > 1 and lauefe[0]["key"] == lauefe[-1]["key"]:
        lauefe[0]["pkt"] = lauefe[-1]["pkt"] + lauefe[0]["pkt"]
        lauefe.pop()
    min_l = max(1, int(0.12 / schritt_m))   # <12 cm = Raster-Zitter, kein Bauteil
    for _ in range(3):
        if len(lauefe) <= 1:
            break
        i_min = None
        for i, lf in enumerate(lauefe):
            if lf["key"][0] == "tuer":
                continue
            if len(lf["pkt"]) < min_l and (i_min is None
                                           or len(lf["pkt"]) < len(lauefe[i_min]["pkt"])):
                i_min = i
        if i_min is None:
            break
        vor = lauefe[(i_min - 1) % len(lauefe)]
        nach = lauefe[(i_min + 1) % len(lauefe)]
        ziel = vor if (vor["key"][0] != "tuer"
                       and len(vor["pkt"]) >= len(nach["pkt"])) else nach
        if ziel is vor:
            vor["pkt"] += lauefe[i_min]["pkt"]
            lauefe.pop(i_min)
            if i_min == len(lauefe):       # letzter Lauf → mit erstem fusioniert
                lauefe[0]["pkt"] = vor["pkt"] + lauefe[0]["pkt"] \
                    if vor is not lauefe[0] else vor["pkt"]
        else:
            nach["pkt"] = lauefe[i_min]["pkt"] + nach["pkt"]
            lauefe.pop(i_min)
    # INTERPOLATION: kurze „unbekannt"-Lücke (<0,35 m) zwischen ZWEI Läufen
    # derselben Klasse+Nachbar = Sonden-Aussetzer an einem Wand-Knoten —
    # die Flanken tragen die Klasse über die Lücke (statt Pixel-Restzweifel).
    for _ in range(2):
        fusion = False
        for i, lf in enumerate(lauefe):
            if lf["key"][0] != "unbekannt":
                continue
            l_m = len(lf["pkt"]) * schritt_m
            if l_m >= 0.35 or len(lauefe) < 3:
                continue
            vor = lauefe[(i - 1) % len(lauefe)]
            nach = lauefe[(i + 1) % len(lauefe)]
            if vor["key"] == nach["key"] and vor["key"][0] != "tuer":
                vor["pkt"] += lf["pkt"] + nach["pkt"]
                lauefe.pop((i + 1) % len(lauefe))
                lauefe.pop(i if i < len(lauefe) else 0)
                fusion = True
                break
        if not fusion:
            break

    # LÜCKEN-SCHLUCK zwischen Tür-Runs: Overlay-Aussetzer (1-2 Wand-Schritte
    # zwischen Bogen- und Text-Markierung derselben Tür) zerhackten eine
    # Tür in bis zu 13 Fragmente (gemessen am Angerer-Korpus). <0,20 m
    # „Wand" zwischen zwei Tür-Runs ist Türstock-Zitter, kein Pfosten.
    for _ in range(2):
        gefunden = False
        for i, lf in enumerate(lauefe):
            if lf["key"][0] == "tuer" or len(lauefe) < 3:
                continue
            if len(lf["pkt"]) * schritt_m >= 0.20:
                continue
            vor = lauefe[(i - 1) % len(lauefe)]
            nach = lauefe[(i + 1) % len(lauefe)]
            if vor["key"][0] == "tuer" and nach["key"][0] == "tuer":
                lf["key"] = ("tuer", None, ("luecke", i))
                gefunden = True
        if not gefunden:
            break
    # TÜR-RUNS WIEDER VEREINEN: Bogen-Flügel + Text-Spanne + Lücken-Schluck
    # derselben Tür erzeugen benachbarte Runs — aufeinanderfolgende Tür-Runs
    # sind EINE Tür. (Zwei echte Türen trägt einen Wand-Lauf ≥0,20 m
    # dazwischen → die bleiben getrennt; gemessen: WC 4 Fragmente statt 1.)
    vereinigt = []
    for lf in lauefe:
        if (vereinigt and lf["key"][0] == "tuer"
                and vereinigt[-1]["key"][0] == "tuer"):
            vereinigt[-1]["pkt"] += lf["pkt"]
        else:
            vereinigt.append(lf)
    lauefe = vereinigt

    namen = {i: (s.get("name") or f"Raum {i}") for i, s in enumerate(stempel or [])}
    segmente = []
    klassen_m = {}
    for lf in lauefe:
        klasse, nachbar = lf["key"][0], lf["key"][1]
        pkt = lf["pkt"]
        if klasse == "tuer":
            # Nachbar der (evtl. zusammengeführten) Tür = Mehrheits-Raum
            # hinter dem Band — „die Tür führt nach X"
            _nb = {}
            for p in pkt:
                if p[4] is not None:
                    _nb[p[4]] = _nb.get(p[4], 0) + 1
            nachbar = max(_nb.items(), key=lambda kv: kv[1])[0] if _nb else None
        x0, y0 = pkt[0][0], pkt[0][1]
        x1, y1 = pkt[-1][0], pkt[-1][1]
        laenge_m = sum(math.hypot(p2[0] - p1[0], p2[1] - p1[1])
                       for p1, p2 in zip(pkt, pkt[1:])) / ptm
        dicken = sorted(p[3] for p in pkt if p[3] > 0)
        dicke_cm = round(dicken[len(dicken) // 2] * 100) if dicken else None
        segmente.append({
            "p0": (round(x0, 1), round(y0, 1)),
            "p1": (round(x1, 1), round(y1, 1)),
            "klasse": klasse,
            "laenge_m": round(laenge_m, 2),
            "dicke_cm": dicke_cm,
            "nachbar": (namen.get(nachbar) if nachbar is not None else None),
        })
        klassen_m[klasse] = round(klassen_m.get(klasse, 0.0) + laenge_m, 2)
    u_m = round(sum(s["laenge_m"] for s in segmente), 2)
    bek = sum(v for k, v in klassen_m.items() if k != "unbekannt")
    return {"segmente": segmente, "klassen_m": klassen_m, "u_m": u_m,
            "anteil_klassifiziert": (round(bek / u_m, 3) if u_m else None)}


def _hals_oeffnung(label, W, H, ridx):
    """NISCHEN-TAB-ABWURF (Balkon-Sezierung 2026-08-18): Raum-Anhaengsel an
    einem HALS von <=2 Zellen (gekaperte Fensternische hinter einem Loch in
    der gezeichneten Linie) per morphologischer Oeffnung abtrennen:
    Erosion r=1 zerschneidet den Hals, groesste Komponente bleibt,
    Dilatation (auf die Originalregion beschraenkt) stellt die Kanten
    wieder her. None = kein Tab oder Verlust >10 % (echte schmale
    Raumteile sind breiter als 2 Zellen und ueberstehen die Erosion)."""
    zellen = [i for i in range(W * H) if label[i] == ridx]
    if len(zellen) < 60:
        return None
    m = bytearray(W * H)
    for i in zellen:
        m[i] = 1
    er = bytearray(W * H)
    for i in zellen:
        x, y = i % W, i // W
        if (0 < x < W - 1 and 0 < y < H - 1 and m[i - 1] and m[i + 1]
                and m[i - W] and m[i + W]):
            er[i] = 1
    from collections import deque as _dq
    gesehen = bytearray(W * H)
    beste = None
    for i in zellen:
        if not er[i] or gesehen[i]:
            continue
        komp = []
        q = _dq([i]); gesehen[i] = 1
        while q:
            c = q.popleft(); komp.append(c)
            x = c % W
            for nb in (c - 1, c + 1, c - W, c + W):
                if 0 <= nb < W * H and er[nb] and not gesehen[nb]                         and abs(nb % W - x) <= 1:
                    gesehen[nb] = 1; q.append(nb)
        if beste is None or len(komp) > len(beste):
            beste = komp
    if not beste:
        return None
    kern = bytearray(W * H)
    for i in beste:
        kern[i] = 1
    maske = bytearray(W * H)
    n_out = 0
    for i in zellen:
        x, y = i % W, i // W
        if kern[i] or (x > 0 and kern[i - 1]) or (x < W - 1 and kern[i + 1])                 or (y > 0 and kern[i - W]) or (y < H - 1 and kern[i + W]):
            maske[i] = 1
            n_out += 1
    if os.environ.get("TAB_DEBUG"):
        print(f"[tab] ridx={ridx} zellen={len(zellen)} kern={len(beste)} "
              f"n_out={n_out} ({n_out/len(zellen)*100:.1f}%)")
    # Sicherheitsboden 75 % — die eigentliche Richtigkeits-Pruefung macht
    # der Aufrufer gegen den STEMPEL (>=98 %). Eine 90-%-Kappe verwarf den
    # Balkon-Abwurf (89,5 %), dessen Ergebnis exakt auf dem Stempel lag.
    if n_out >= len(zellen) or n_out < 0.75 * len(zellen):
        return None
    return maske, n_out


def raum_regionen(label, rst, n_stempel, min_flaeche_m2=1.0, debug=None,
                  stempel_f=None, grid=None, dark_segs=None, stuetzen=None,
                  ist_f=None, hatch_segs=None, kredit_cells=None):
    """Pro Raum den REKONSTRUIERTEN Region-Umriss als Polygon in pt
    (Nachvollziehbarkeit: der Prüfer sieht die geometrische Lesart der App
    ÜBER dem Plan — verifizierte Räume decken sich, Prüf-Räume zeigen exakt,
    wo die Rekonstruktion abweicht). Moore-Verfolgung je Label; nur die
    GRÖSSTE Komponente je Raum (Fransen/Inseln fallen raus). → {idx: [(x,y)…]}."""
    W, H = rst.W, rst.H
    # Wand-PAARE einmal je Seite (nicht je Raum): Traeger des Innenkanten-
    # Snaps in raum_kontur_exakt. hatch=None wie beim Wandpaar-Rueckfall —
    # die Seiten-Bedingung (Wand auswaerts der Kante, Lauf-Deckung >=50 %)
    # haelt Bemassungs-/Terrassen-Paare von Innenkanten fern.
    # INNENKANTEN-SNAP (Nutzer-Richtung: "ein Raum ist nur die Innenwand"):
    # Mechanik gebaut, KALIBRIERUNG OFFEN — vorerst hinter IK_SNAP=1.
    # Gemessen am Angerer (proraum, mittlerer |F-Fehler| gegen Stempel):
    #   Basis 5,5 % · Snap 35-cm-Fenster 6,1 % (Geraete +18,7!) ·
    #   8-cm-Fenster 6,2 % (Waschen 1,8->10,7 — Fenster zu eng, die echte
    #   Innenlinie liegt durch das Closing ~4-8 cm AUSSERHALB der Rasterkante)
    #   naechste-WAND-Wahl (Mittellinien-Distanz) 6,9 % (Geraete 19,2,
    #   Flur -9,1 — Moebel-/Textur-Paare mit naher Mittellinie gewinnen).
    # OVERLAY-SESSION 2026-08-10 (ik_*.png im Session-Scratchpad) — drei
    # Befunde, die die Richtung DREHEN:
    #  1. Ohne Poché-Gate bestanden die Kandidaten aus Steinschlichtung
    #     (31,4 cm, Geraete +18,7 %), Tuerzargen (8,5 cm) und Pergola —
    #     alle hatch=None. Gate eingebaut (hatch_segs wird durchgereicht).
    #  2. Mit Gate + Auswaerts-Deckel (+3 cm) ist der Paar-Snap NEUTRAL
    #     (6,2 % vs 6,3 % Basis) — sauber, aber wirkungslos.
    #  3. DAS EIGENTLICHE PROBLEM IST NICHT DIE SEITENWAHL: die Rasterkanten
    #     sitzen laut Overlay BEREITS auf den gezeichneten Innenlinien,
    #     trotzdem messen die Polygone +5..11 % gegen die Stempel. Die
    #     Aufblaehung steckt in der REGIONS-ZUSAMMENSETZUNG (Tuerzonen/
    #     Glaettung/Ausgleich), nicht im Kanten-Snap. Naechste Session:
    #     Regions-Sezierung (Flur-Kurzstueck ist derselbe Komplex).
    # IK_SNAP bleibt AUS; IK_DEBUG=1 liefert Kanten+Kandidaten maschinen-
    # lesbar ([ikc]/[ikk]), Overlay-Renderer im Session-Scratchpad.
    _paare_ik = None
    if dark_segs and os.environ.get("IK_SNAP"):
        try:
            import vektor as _vik
            # POCHÉ-GATE — die Auswahlregel, vom Bild abgeleitet (Overlay
            # 2026-08-10, ik_Geraete/ik_Flur.png im Session-Scratchpad):
            # OHNE Gate bestand die Kandidatenliste aus Steinschlichtungs-
            # Paaren (31,4 cm, frass den Geraete-Ostrand +18,7 %), Tuerzargen
            # (8,5 cm) und Pergola-Linien — alle h=None. Echte Waende sind
            # poché-schraffiert; dieselbe Regel nutzt die Wandliste laengst.
            _paare_ik = _vik.wand_paare(dark_segs, rst.ptm, hatch=hatch_segs,
                                        mit_geometrie=True)
        except Exception:
            _paare_ik = None
    zm2 = rst.zm * rst.zm
    out = {}
    for ridx in range(n_stempel):
        vereinfacht, n_cells = _umriss_zellen(label, W, H, ridx, zm2,
                                              min_flaeche_m2)
        if vereinfacht is None or len(vereinfacht) < 3:
            continue
        # TAB-ABWURF nur wenn der Raum UEBER seinem Stempel liegt (Budget-
        # Richtung wie Snap-Deckel/BAND_SNAP) — dann ist ein per Hals
        # haengendes Anhaengsel fast sicher eine gekaperte Nische.
        # mitglied ist eine INDIZIERBARE Maske (bytearray) — ein set warf
        # TypeError und liess ALLE Umrisse auf Ersatz zurueckfallen
        # (gemessen: Sadiku 25x Ersatz, Angerer Oe 2,5->5,5).
        if os.environ.get("TAB_CUT", "1") != "0":
            _sf_tab = None
            try:
                if stempel_f and ridx < len(stempel_f) and stempel_f[ridx]:
                    _sf_tab = float(stempel_f[ridx])
            except Exception:
                _sf_tab = None
            if os.environ.get("TAB_DEBUG"):
                print(f"[tab?] ridx={ridx} n={n_cells} m2={n_cells*zm2:.2f} "
                      f"sf={_sf_tab}")
            if _sf_tab and n_cells * zm2 > 1.02 * _sf_tab:
                _tab = _hals_oeffnung(label, W, H, ridx)
                if _tab and _tab[1] * zm2 >= 0.98 * _sf_tab:
                    _v2, _n2 = _umriss_zellen(label, W, H, ridx, zm2,
                                              min_flaeche_m2,
                                              mitglied=_tab[0])
                    if _v2 and len(_v2) >= 3:
                        vereinfacht, n_cells = _v2, _n2
        # TUERDURCHGAENGE MITZEICHNEN, stempel-gerichtet (Nutzer-Befund
        # "beim Flur laesst er das erste kurze Stueck aus"): die MENGE
        # kreditiert die Tuerbuchten laengst (Balken-F-Gutschrift), nur der
        # gezeichnete Umriss kerbte an jeder Tuer ein (Flur DP -5,4 % bei
        # f_ist +0,2 %). Liegt das DP-Polygon UNTER dem Stempel und gibt es
        # kreditierte Zellen, wird mit Raum+Gutschrift neu getraced. Raeume,
        # deren Stempel die Buchten NICHT enthaelt (Zimmer 1: 2,70 x 3,90
        # exakt), bleiben unangetastet — dieselbe Stempel-Richtungs-Logik
        # wie beim Snap-Deckel.
        _kz = (kredit_cells or {}).get(ridx)
        if os.environ.get("RG_DEBUG"):
            print(f"[rgk] ridx={ridx} kz={len(_kz) if _kz else 0} "
                  f"dictkeys={sorted((kredit_cells or {}).keys())[:12]}")
        if _kz:
            _sf0 = None
            try:
                if stempel_f and ridx < len(stempel_f) and stempel_f[ridx]:
                    _sf0 = float(stempel_f[ridx])
            except (TypeError, ValueError):
                _sf0 = None
            _a0 = 0.0
            for _i in range(len(vereinfacht)):
                _p1 = vereinfacht[_i - 1]
                _p2 = vereinfacht[_i]
                _a0 += _p1[0] * _p2[1] - _p2[0] * _p1[1]
            _a0 = abs(_a0) / 2.0 * zm2
            if _sf0 and _a0 < 0.98 * _sf0:
                _mask = bytearray(W * H)
                _cells2 = []
                for _ix in range(W * H):
                    if label[_ix] == ridx:
                        _mask[_ix] = 1
                        _cells2.append(_ix)
                for _ix in _kz:
                    if not _mask[_ix]:
                        _mask[_ix] = 1
                        _cells2.append(_ix)
                # MASKE GLAETTEN (Flur-Sezierung 2026-08-19): die Kredit-
                # Streifen erzeugen Treppenzaehne (Flur: 67 Ecken statt 46)
                # — daran scheiterte der Vektor-Snap (Quote < 70 %), und
                # ohne ihn fehlt der Auswaerts-Zug. Ein Closing r=2
                # verschmilzt die Streifen mit dem Koerper; neue Zellen
                # werden Mitglieder (der Umriss darf die Tuerbucht
                # ueberspannen — genau dafuer ist der Kredit da).
                # Kleinraeume (<4 m2) NICHT schliessen: WC kippte durch
                # das r=2-Closing von -1,6 auf -7,5 % — bei 1,8 m2 ist
                # jede verschmolzene Ecke prozentual gross.
                if _sf0 and _sf0 < 4.0:
                    _cl = _mask
                else:
                    _cl = _closing(bytearray(_mask), W, H, 2)
                for _ix in range(W * H):
                    if _cl[_ix] and not _mask[_ix]:
                        _mask[_ix] = 1
                        _cells2.append(_ix)
                _v2, _n2 = _umriss_zellen(label, W, H, ridx, zm2,
                                          min_flaeche_m2, cells=_cells2,
                                          mitglied=_mask)
                if _v2 is not None and len(_v2) >= 3:
                    vereinfacht, n_cells = _v2, _n2
        # VERLÄSSLICHKEITS-GATE: die Polygon-Fläche (Shoelace) muss zur echten
        # Region-Fläche (Zellzahl) passen — offene/zerfranste Räume (Carport)
        # ergeben selbst-schneidende Traces, deren Umriss visuell irreführt.
        # Nur kompakte, flächen-treue Umrisse zeigen (sonst kein Umriss).
        A2 = 0.0
        m = len(vereinfacht)
        for k in range(m):
            x1, y1 = vereinfacht[k]
            x2, y2 = vereinfacht[(k + 1) % m]
            A2 += x1 * y2 - x2 * y1
        poly_flaeche = abs(A2) / 2.0 * zm2
        region_flaeche = n_cells * zm2
        # ACHS-AUSRICHTUNGS-GATE: echte Raumwände sind waagrecht/senkrecht →
        # ein sauberer Umriss besteht fast nur aus achsparallelen Kanten.
        # OFFENE Räume (Carport/Terrasse ohne Wandgrenze) ergeben einen
        # Zickzack-Trace mit langen DIAGONALEN durch den Freiraum — visuell
        # irreführend. ≥75% achsparallele Kantenlänge nötig (Flur-Korridor
        # bleibt, Park-Zickzack fällt).
        # ROTATIONS-NORMIERT (Befund 2026-07-28): gemessen wurde bisher gegen die
        # BLATT-Achsen — ein GEDREHTER Grundriss (Velden-TG: ganze Anlage schräg)
        # fiel damit komplett durch, obwohl die Rekonstruktion exakt war
        # (Flächen-Treue 0,1-7 %!). 36 von 41 abgewiesenen Räumen im Korpus
        # scheiterten allein hieran. Der ZWECK des Gates ist, Zickzack-Spuren
        # offener Bereiche abzuweisen — nicht gedrehte Gebäude. Darum: erst die
        # längen-gewichtete HAUPTRICHTUNG der Kanten bestimmen (Kreismittel über
        # 4·θ, weil rechtwinklige Richtungen mod 90° gleichwertig sind), dann die
        # Parallelität IN DIESEM Rahmen messen. Ein gedrehtes Rechteck erreicht
        # so ~1,0; eine echte Zickzack-Spur bleibt niedrig, weil ihre Kanten sich
        # keine zwei orthogonalen Richtungen teilen.
        import math as _m
        _C = _S = 0.0
        for k in range(m):
            x1, y1 = vereinfacht[k]
            x2, y2 = vereinfacht[(k + 1) % m]
            dx, dy = x2 - x1, y2 - y1
            L = (dx * dx + dy * dy) ** 0.5
            if L <= 0:
                continue
            th = _m.atan2(dy, dx)
            _C += L * _m.cos(4.0 * th)
            _S += L * _m.sin(4.0 * th)
        haupt = _m.atan2(_S, _C) / 4.0 if (_C or _S) else 0.0
        _cos_h, _sin_h = _m.cos(-haupt), _m.sin(-haupt)
        len_axis, len_ges = 0.0, 0.0
        for k in range(m):
            x1, y1 = vereinfacht[k]
            x2, y2 = vereinfacht[(k + 1) % m]
            _dx0, _dy0 = x2 - x1, y2 - y1
            # in den Rahmen der Hauptrichtung drehen
            dx = abs(_dx0 * _cos_h - _dy0 * _sin_h)
            dy = abs(_dx0 * _sin_h + _dy0 * _cos_h)
            L = (dx * dx + dy * dy) ** 0.5
            len_ges += L
            if dx < 0.35 * dy or dy < 0.35 * dx:
                len_axis += L
        axis_frac = (len_axis / len_ges) if len_ges else 0
        _fr = abs(poly_flaeche - region_flaeche) / region_flaeche if region_flaeche > 0 else 9
        # Ecken-Deckel: ≤40 immer. Ein FLÄCHEN-TREUER (fr≤0,08), achsparalleler
        # (≥0,75) Raum mit vielen Installations-/Schacht-NISCHEN ist legitim komplex
        # — bis 90 Ecken zeigen (WM-Gate-Diagnose 2026-07-06: 4 verifizierte Räume,
        # 47-50 Ecken, fr 0,003-0,007, wurden fälschlich vom starren 40er-Deckel
        # gefiltert). Zickzack-Räume (axis<0,75) bleiben via dem UNVERÄNDERTEN
        # Achs-Gate draußen; grob falsche Rekonstruktionen via fr≤0,08.
        ecken_ok = len(vereinfacht) <= 40 or (len(vereinfacht) <= 90 and _fr <= 0.08)
        # STEMPEL-GATE (2026-07-28, am Plan visuell verifiziert): entscheidend
        # ist nicht die Form, sondern ob der Umriss die RICHTIGE Fläche
        # umschließt. `_fr` vergleicht Polygon gegen REGION — ist die Region
        # falsch (Parkplatz floss über den offenen Carport: 75,8 statt 36,0 m²;
        # „Zimmer 2" umfuhr den Treppenbereich), ist _fr trotzdem perfekt.
        # Der byte-exakte F-STEMPEL ist die Wahrheit: stimmt die Polygonfläche
        # mit ihm überein, ist der Umriss BEWIESEN richtig — dann darf er auch
        # gedreht oder verwinkelt sein (Velden-TG steht schräg). Weicht er ab,
        # wird nichts gezeichnet, egal wie schön die Form ist.
        _sf = None
        try:
            if stempel_f and ridx < len(stempel_f):
                _sf = float(stempel_f[ridx]) if stempel_f[ridx] else None
        except (TypeError, ValueError):
            _sf = None
        if _sf and _sf > 0:
            # TUERDURCHGANG MITZAEHLEN. Der Tuer-Balken versiegelt Zellen, die
            # laut Plan-F zum Raum gehoeren — fuer die MENGE ist das laengst
            # gutgeschrieben (`_messen_und_status`, Balken-F-Gutschrift), das
            # UMRISS-GATE hier sah die nackte Polygonflaeche ohne sie. Dadurch
            # verlor ein Raum seinen Umriss allein deshalb, weil eine Tuer
            # dicht gemacht wurde: am Korpus 4 Umrisse auf WM (drei Loggien,
            # zwei Wohnkuechen — alle weiter "verifiziert", nur am Plan nicht
            # mehr eingezeichnet).
            # `ist_f` ist die bereits kreditierte Flaeche desselben Raums; die
            # Differenz zur Regionflaeche IST die Gutschrift. Damit prueft das
            # Gate dieselbe Flaeche wie die Menge — statt den Balken
            # zurueckzunehmen und die Tuer wieder lecken zu lassen (dieser
            # Tausch ist gemessen und im Docstring von `_tuer_lecks` als
            # Sackgasse festgehalten).
            _kred = 0.0
            try:
                if ist_f and ridx < len(ist_f) and ist_f[ridx]:
                    _kred = max(0.0, float(ist_f[ridx]) - region_flaeche)
            except (TypeError, ValueError):
                _kred = 0.0
            # NUR AUSGLEICHEN, NIE AUFBLAEHEN. Die Gutschrift ersetzt Flaeche,
            # die der Balken WEGGENOMMEN hat — mehr als das Defizit zum
            # Stempel kann sie nie sein. Ohne diese Kappe schob sie Raeume,
            # deren Polygon ohnehin zu GROSS ist, erst recht aus der Toleranz:
            # gemessen verloren dadurch 7 Raeume ihren Umriss ganz
            # (am Plan belegt 116 -> 109), waehrend 5 andere gewannen.
            _kred = min(_kred, max(0.0, _sf - poly_flaeche))
            _sr = abs(poly_flaeche + _kred - _sf) / _sf
            angenommen = bool(region_flaeche > 0 and _sr <= 0.20 and ecken_ok)
            _gr = (None if angenommen else
                   ("stempel_flaeche" if _sr > 0.20 else "ecken"))
        else:
            # ohne Stempel: bisherige Heuristik (Form muss für sich stehen)
            _sr = None
            angenommen = bool(region_flaeche > 0 and _fr <= 0.20 and ecken_ok
                              and axis_frac >= 0.75)
            _gr = (None if angenommen else
                   ("flaechen_treue" if _fr > 0.20 else
                    "ecken" if not ecken_ok else
                    "achs_parallel" if axis_frac < 0.75 else "leer"))
        # DIAGNOSE (opt-in): welches Gate weist einen Raum ab? Ohne das ist
        # „Raum ohne Umriss" eine Blackbox — mit dem Dict ist messbar, ob die
        # Flächen-Treue, die Eckenzahl oder die Achs-Parallelität der Grund war.
        if debug is not None:
            debug[ridx] = {
                "angenommen": angenommen,
                "fr": round(_fr, 3), "ecken": len(vereinfacht),
                "axis_frac": round(axis_frac, 3),
                "region_m2": round(region_flaeche, 2),
                "poly_m2": round(poly_flaeche, 2),
                "grund": _gr,
                "kredit_m2": round(_kred, 2) if (_sf and _sf > 0) else None,
                "stempel_f": _sf,
                "stempel_abw": (round(_sr, 3) if _sr is not None else None),
                "poly_pt": [(rst.bx0 + p[0] * rst.cell, rst.by0 + p[1] * rst.cell)
                            for p in vereinfacht],
            }
        if angenommen:
            # VEKTOR-EXAKTER Snap zuerst (Nutzer-Befund: Kontur muss auf der
            # Wandlinie liegen, nicht auf einer Rasterzelle davor). Gate:
            # Snap-Quote ≥70 % und Fläche darf vom DP-Polygon nicht grob
            # abweichen (Fehlsnap/Selbstschneidung) — sonst bisheriger Weg.
            _fin_pt = None
            if dark_segs is not None and grid is not None:
                try:
                    # Schwelle 0,95 statt 0,98 (Tuerzonen-Retrace 2026-08-10):
                    # nach dem Mitzeichnen der Tuerbuchten liegen kleine
                    # Raeume knapp UNTER dem Stempel (WC -3,3 %, Flur -3,1) —
                    # bei freiem Snap zog WC auf +8,4 %. Mit 0,95 deckelt der
                    # Snap auch sie; die echten Defizit-Raeume (WM -13..-21 %)
                    # bleiben frei und behalten ihren Auswaerts-Zug.
                    _mr = (0.03 * rst.ptm
                           if (_sf and _sf > 0 and poly_flaeche >= 0.95 * _sf)
                           else None)
                    _eb = (max(0.0, poly_flaeche - _sf)
                           if (_sf and _sf > 0 and _mr is not None) else None)
                    _kx = raum_kontur_exakt(vereinfacht, grid, W, H, rst,
                                            dark_segs, stuetzen=stuetzen,
                                            paare=_paare_ik, dbg_tag=ridx,
                                            max_raus_pt=_mr,
                                            ein_budget_m2=_eb)
                    if _kx and _kx["snap_quote"] >= 0.70 and poly_flaeche > 0 \
                            and abs(_kx["f_m2"] - poly_flaeche) / poly_flaeche <= 0.20:
                        _fin_pt = _kx["poly_pt"]
                        if debug is not None:
                            debug[ridx]["kontur_exakt"] = {
                                "snap_quote": round(_kx["snap_quote"], 3),
                                "vektor_quote": round(_kx["vektor_quote"], 3),
                                "f_m2": round(_kx["f_m2"], 2),
                                "u_m": round(_kx["u_m"], 2)}
                except Exception:
                    _fin_pt = None
            if _fin_pt is None:
                _fin = vereinfacht
                if grid is not None:
                    try:
                        _fin = an_wand_schnappen(vereinfacht, grid, W, H)
                    except Exception:
                        _fin = vereinfacht
                _fin_pt = [(rst.bx0 + p[0] * rst.cell, rst.by0 + p[1] * rst.cell)
                           for p in _fin]
            out[ridx] = _fin_pt
    return out


def huellen_kontur(grid, label, rst, AUSSEN, min_umfang_m=8.0):
    """GEMAUERTE HÜLLE als Polylinie(n) in pt (Nachvollziehbarkeits-Audit P1:
    der Außenumfang treibt ~20 der 35 Material-Positionen, war aber nie am
    der Außenumfang treibt ~20 der 35 Material-Positionen, war aber nie am
    Plan eingezeichnet). Kontur = Wand-Zellen mit AUSSEN-Nachbar, verfolgt
    per Moore-Nachbarschaft; nur Konturen ≥min_umfang (Nebengebäude bleiben,
    Deko-Inseln fallen raus). Liefert [{punkte: [(x,y)…], umfang_m}]."""
    W, H = rst.W, rst.H
    rand = bytearray(W * H)
    for j in range(H):
        base = j * W
        for i in range(W):
            if not grid[base + i]:
                continue
            for di, dj in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                ni, nj = i + di, j + dj
                if not (0 <= ni < W and 0 <= nj < H) or label[nj * W + ni] == AUSSEN:
                    rand[base + i] = 1
                    break
    besucht = bytearray(W * H)
    # Moore-Nachbarn im Uhrzeigersinn
    MN = ((1, 0), (1, 1), (0, 1), (-1, 1), (-1, 0), (-1, -1), (0, -1), (1, -1))
    konturen = []
    for start in range(W * H):
        if not rand[start] or besucht[start]:
            continue
        pfad = []
        i, j = start % W, start // W
        cur = (i, j)
        richtung = 0
        for _schritt in range(4 * (W + H) * 4):   # Sicherheits-Deckel
            pfad.append(cur)
            besucht[cur[1] * W + cur[0]] = 1
            gefunden = False
            for k in range(8):
                d = MN[(richtung + k) % 8]
                ni, nj = cur[0] + d[0], cur[1] + d[1]
                if 0 <= ni < W and 0 <= nj < H and rand[nj * W + ni]:
                    cur = (ni, nj)
                    richtung = (richtung + k + 6) % 8   # zurückdrehen
                    gefunden = True
                    break
            if not gefunden or cur == (i, j):
                break
        if len(pfad) < 8:
            continue
        # Ausdünnen: nur Richtungswechsel behalten (Polylinie statt Zellkette)
        punkte = []
        for n2, p in enumerate(pfad):
            if n2 == 0 or n2 == len(pfad) - 1:
                punkte.append(p)
                continue
            a, b = pfad[n2 - 1], pfad[n2 + 1]
            if (p[0] - a[0], p[1] - a[1]) != (b[0] - p[0], b[1] - p[1]):
                punkte.append(p)
        umf = 0.0
        for n2 in range(1, len(punkte)):
            umf += ((punkte[n2][0] - punkte[n2 - 1][0]) ** 2
                    + (punkte[n2][1] - punkte[n2 - 1][1]) ** 2) ** 0.5
        umf_m = umf * rst.zm
        if umf_m < min_umfang_m:
            continue
        konturen.append({
            "punkte": [(rst.bx0 + p[0] * rst.cell, rst.by0 + p[1] * rst.cell)
                       for p in punkte],
            "umfang_m": round(umf_m, 2),
        })
    konturen.sort(key=lambda k: -k["umfang_m"])
    return konturen[:4]


def verifiziere_seite(page, ptm, box, dark_segs, hatch_segs, oeffnungen,
                      zelle_m=0.02, tol_f=0.06, tol_u=0.10, debug=None,
                      pfade=None):
    """Komplette Raum-Verifikation einer Grundriss-Seite.
    Liefert (ergebnisse, stempel): ergebnisse = [{…, f_ist, u_ist, status}].
    debug: dict → bekommt grid/label/W/H/rst für Visualisierung."""
    stempel = raum_stempel(page, box)
    # hatch_fill_filter: WURZELURSACHEN-Fix (Boden-Feinschraffur → Wand) —
    # GEMESSEN & ZURÜCKGESTELLT: heilt die Cluster-F real (Bad 4,0→5,4-6,0),
    # aber WM netto 49 vs 50 (2 alte Grüne waren Zufalls-Fill-Beschneidung)
    # und TG 16→15 (Stellplatz-Schraffur). Wiedereinbau braucht TG-Gating
    # + die 2 Gate-Rand-Fälle; Sezier-Skripte im Session-Scratchpad.
    _stuetzen = []
    try:
        for _blk in page.get_text("dict").get("blocks", []):
            if _blk.get("type") != 0:
                continue
            for _ln in _blk.get("lines", []):
                for _sp in _ln.get("spans", []):
                    _t = (_sp.get("text") or "").strip()
                    if re.match(r"^St(ü|ue)tze(n)?\b", _t, re.I):
                        _bb = _sp.get("bbox") or (0, 0, 0, 0)
                        _cx0, _cy0 = (_bb[0] + _bb[2]) / 2.0, (_bb[1] + _bb[3]) / 2.0
                        if box[0] <= _cx0 <= box[1] and box[2] <= _cy0 <= box[3]:
                            _stuetzen.append((_cx0, _cy0))
    except Exception:
        _stuetzen = []
    rst = _Raster(box, ptm, zelle_m)
    # Wand-Paare fuer den Innenkanten-Snap der Kontur-MESSUNG — dieselbe
    # Quelle wie beim Zeichnen (raum_regionen), damit gezeichnete und
    # gemessene Kontur dieselbe raumseitige Wandlinie sehen.
    _paare_ik_m = None
    if dark_segs and os.environ.get("IK_SNAP"):
        try:
            import vektor as _vikm
            _paare_ik_m = _vikm.wand_paare(dark_segs, ptm, hatch=hatch_segs,
                                           mit_geometrie=True)
        except Exception:
            _paare_ik_m = None
    oe = [o for o in (oeffnungen or [])
          if box[0] <= o.get("cx", -1) <= box[1] and box[2] <= o.get("cy", -1) <= box[3]]
    moebel = []
    try:
        for p in (pfade if pfade is not None else page.get_drawings()):
            items = p.get("items") or []
            if len(items) != 1 or items[0][0] != "re":
                continue
            rc = items[0][1]
            w_m, h_m = rc.width / ptm, rc.height / ptm
            if 0.25 <= w_m <= 1.10 and 0.25 <= h_m <= 1.10:
                r = max(rc.width, rc.height) * 0.55
                moebel.append(((rc.x0 + rc.x1) / 2.0, (rc.y0 + rc.y1) / 2.0, r * r))
    except Exception:
        moebel = []
    # TÜR-BÖGEN (v3): der Aufschlag-Viertelkreis liefert Angelpunkt + Türbreite
    # byte-genau aus der Geometrie — primäre Verschluss-Quelle (Text nur Fallback).
    try:
        import vektor as _vek
        boegen = _vek.tuer_boegen(page, box, ptm, pfade=pfade)
    except Exception:
        boegen = []
    _hatch_roh = bytearray(rst.W * rst.H)   # rohe Poché (Durchgang-Kredit)

    def _pass(paar_fallback, hatch_use=None):
        versch = bytearray(rst.W * rst.H)
        grid = wand_maske(rst, dark_segs,
                          hatch_segs if hatch_use is None else hatch_use,
                          oe, moebel_zonen=moebel,
                          versch_out=versch, boegen=boegen,
                          paar_fallback=paar_fallback, stuetzen=_stuetzen,
                          hatch_out=_hatch_roh)
        vor_fs = bytes(grid)
        _n_fs, luecken = _fassaden_schluss(grid, rst.W, rst.H, rst.zm)
        huelle_burn = bytearray(1 if (grid[i_] and not vor_fs[i_]) else 0
                                for i_ in range(rst.W * rst.H))
        # STUFE-2-BRÜCKEN-BURN (Fassaden-Sezierung): Tor-/Front-Linien, deren
        # BEIDE Enden in der Wand-Maske ankern und die eine erkannte HÜLLEN-
        # Lücke überspannen, brennen. Der globale Brücken-Burn zerschnitt
        # Innenräume (gemessen: Zimmer 12,32→5,23) — die Lücken-Bedingung
        # macht ihn chirurgisch (S5-Tor 1,7m verband Radabstell mit dem
        # stempellosen Foyer zu einem 63,7m²-Basin).
        if luecken:
            d_w = _dist_bfs(grid, rst.W, rst.H, 2)

            def _ank(i, j):
                return 0 <= i < rst.W and 0 <= j < rst.H and d_w[j * rst.W + i] <= 2

            for s in dark_segs:
                L = math.hypot(s[2] - s[0], s[3] - s[1]) / rst.ptm
                if not (0.5 <= L <= 4.0):
                    continue
                i0_, j0_ = rst.ij(s[0], s[1])
                i1_, j1_ = rst.ij(s[2], s[3])
                if not (_ank(i0_, j0_) and _ank(i1_, j1_)):
                    continue
                mi, mj = (i0_ + i1_) // 2, (j0_ + j1_) // 2
                if not any(a1 <= (mi if axis == "col" else mj) <= b0
                           and lmin - 4 <= (mj if axis == "col" else mi) <= lmax + 4
                           for (axis, a1, b0, lmin, lmax) in luecken):
                    continue
                frei = 0
                for k in range(1, 8):
                    t = k / 8.0
                    ii, jj = rst.ij(s[0] + (s[2] - s[0]) * t, s[1] + (s[3] - s[1]) * t)
                    if 0 <= ii < rst.W and 0 <= jj < rst.H and not grid[jj * rst.W + ii]:
                        frei += 1
                if frei < 4:
                    continue    # Mitte schon Wand → nichts zu überbrücken
                rst.line(grid, s[0], s[1], s[2], s[3])
        label, ok_start, AUSSEN = _watershed(grid, rst, stempel)

        def _kette(grid_, lab):
            """Die Ausgleichs-Kette eines Passes (Taschen → Streifen → F →
            Glätten → F) — für den Varianten-Vergleich ausgelagert."""
            lab = _taschen_adoption(grid_, lab, rst, stempel, AUSSEN,
                                    huelle_burn=huelle_burn)
            lab = _streifen_ausgleich(grid_, lab, rst, stempel, AUSSEN)
            lab = _f_ausgleich(grid_, lab, rst, stempel, AUSSEN)
            lab = _glaetten(grid_, lab, rst, len(stempel), AUSSEN)
            lab = _f_ausgleich(grid_, lab, rst, stempel, AUSSEN)
            return lab

        label = _kette(grid, label)
        # LECK-GEFÜHRTER NACHVERSCHLUSS, mit VERIFIKATIONS-GUARD (Tür-
        # Dichtungs-Messung 2026-08-04: 32/56 undicht; WM-Bad −1,1 m² und
        # Velden E-Technik +0,6 m² durch Fehl-Balken ohne Guard). Bogen-/
        # Text-Verschlüsse verfehlen die Lücke (Schiebefronten ohne Bogen,
        # Text-Anker streut bis 1,13 m; der 1,0-m-Zweitdurchgang brannte
        # Balken in FREMDE Zeilen — 29→35, verworfen). Stattdessen: Leck
        # MESSEN (dieselbe Lokalisation wie der Harness), die Lücke mauern,
        # neu fluten — aber nur behalten, was KEINE Verifikation kostet:
        # kostet ein Balken einen verifizierten Raum, fliegt genau ER raus
        # (bis zu 3 Runden), nicht das ganze Paket. Nur ROH/BODEN-Ebene:
        # auf FERTIG kollidiert der Burn mit dem Wand-Paar-Fallback
        # ([49] U 24,96→33,44 gemessen — dort bleibt es byte-identisch).
        if not paar_fallback:
            _lecks = _tuer_lecks(grid, label, rst, oe, stempel=stempel)
            if _lecks:
                def _bauen(lk):
                    g_s = bytearray(grid)
                    v_s = bytearray(versch)
                    for (_ax, _fest, _lo, _hi) in lk:
                        for _t in range(_lo + 1, _hi):
                            _ix = ((_fest * rst.W + _t) if _ax == "h"
                                   else (_t * rst.W + _fest))
                            g_s[_ix] = 1
                            v_s[_ix] = 1    # Tür-Durchgang zählt zum Raum-F
                    return g_s, v_s

                out_u = _messen_und_status(grid, label, ok_start, versch)
                ver_u = {i2 for i2, r2 in enumerate(out_u)
                         if r2["status"] == "verifiziert"}
                g_s, v_s = _bauen(_lecks)
                lab_s, ok_s, _au_s = _watershed(g_s, rst, stempel)
                lab_s = _kette(g_s, lab_s)
                for _runde in range(4):
                    out_s = _messen_und_status(g_s, lab_s, ok_s, v_s)
                    ver_s = {i2 for i2, r2 in enumerate(out_s)
                             if r2["status"] == "verifiziert"}
                    reg = ver_u - ver_s
                    if os.environ.get("GUARD_DEBUG") and (reg or _runde == 0):
                        print(f"[guard] runde={_runde} lecks={len(_lecks)} "
                              f"ver_u={len(ver_u)} ver_s={len(ver_s)} reg={sorted(reg)}")
                    if not reg or _runde == 3:
                        break
                    # Balken neben den verlorenen Räumen entfernen:
                    # Zelle des Balkens ≤3 Zellen an einer Zelle des
                    # verlorenen Raum-Beckens (in der UNGESETZTEN Variante)
                    fallen = set()
                    for li2, (_ax, _fest, _lo, _hi) in enumerate(_lecks):
                        if li2 in fallen:
                            continue
                        stoss = False
                        for _t in range(max(0, _lo - 2), _hi + 3):
                            for _dj in range(-3, 4):
                                _ii = (_fest + _dj) if _ax == "h" else (_t + _dj)
                                _jj = _t if _ax == "h" else (_fest + _dj)
                                if not (0 <= _ii < rst.W and 0 <= _jj < rst.H):
                                    continue
                                if label[_jj * rst.W + _ii] in reg:
                                    stoss = True
                                    break
                            if stoss:
                                break
                        if stoss:
                            fallen.add(li2)
                    if not fallen:
                        break
                    _lecks = [lk for li2, lk in enumerate(_lecks)
                              if li2 not in fallen]
                    if not _lecks:
                        break
                    g_s, v_s = _bauen(_lecks)
                    lab_s, ok_s, _au_s = _watershed(g_s, rst, stempel)
                    lab_s = _kette(g_s, lab_s)
                if _lecks and not (ver_u - ver_s):
                    # überlebende Balken: keine Verifikation verloren
                    return g_s, lab_s, ok_s, _au_s, v_s
        return grid, label, ok_start, AUSSEN, versch

    # BALKEN-F-GUTSCHRIFT: Türdurchgangs-Zellen zählen laut Plan-F zum Raum (WC-Bild +
    # Tür-Topologie belegt: 5-6 Türen ≈ Flur+WC-Defizit). Jede Tür-Balken-Zelle wird
    # dem NÄCHSTEN Raum-Label gutgeschrieben — nur fürs Flächen-Konto, Topologie/U bleiben.
    W2, H2 = rst.W, rst.H
    # Tote Closing-Zone einbeziehen (WC-Sezierung): das Closing versiegelt Zellen
    # ZWISCHEN Balken und Türlaibung — auch die gehören zum Türdurchgang. Balken-Maske
    # um den Closing-Radius dilatieren, aber nur WAND-Zellen kreditieren.
    # Gutschrift-Zone = die GANZE Tür-Zone (r=0,9×Breite): der komplette Durchgangs-
    # bereich zählt laut Plan-F zum Raum; Balken+Laibungs-Closing versiegeln dort
    # Zellen fern des Balkens (WC-Render belegt).
    tz = []
    for o in oe:
        if o.get("typ") == "tuer":
            # BOGEN-versiegelte Türen: Seal sitzt AN der Wand → kein Flächen-
            # verlust → KEINE Gutschrift (Doppelzählung; WC gemessen: −0,24m²
            # = exakt aufs Rohbau-Rect, Zimmer 2 exakt auf den Stempel).
            if any(math.hypot(bg["hinge"][0] - o["cx"],
                              bg["hinge"][1] - o["cy"]) < 1.5 * ptm
                   for bg in (boegen or [])):
                continue
            r_z = (o.get("breite_m") or 0.9) * 0.9 * ptm
            tz.append((o["cx"], o["cy"], r_z * r_z))

    def _in_tz(idx):
        i2, j2 = idx % W2, idx // W2
        x = rst.bx0 + i2 * rst.cell
        y = rst.by0 + j2 * rst.cell
        for (zx, zy, r2) in tz:
            if (x - zx) ** 2 + (y - zy) ** 2 <= r2:
                return True
        return False

    def _messen_und_status(grid, label, ok_start, versch, r_gl_gross=0.25,
                           kredit_out=None):
        masse = _loecher_fuellen_und_messen(grid, label, rst, stempel,
                                            r_gl_gross=r_gl_gross)
        # Kredit nur BALKEN-NAH (WM-Sezierung: die 2,29-m-Haustür kreditierte via
        # Vollkreis-Zone 13,3 m² Wandfläche → Stiegenhaus +1,65 m²; die Kreiszone
        # wächst QUADRATISCH mit der Türbreite). Tür-Zonen-Zellen zählen nur noch
        # ≤0,25 m an einer Balken-Zelle — deckt die tote Closing-Zone (WC-
        # Sezierung) weiter ab, skaliert aber linear.
        r_nahe = max(1, int(0.25 / rst.zm))
        d_versch = _dist_bfs(versch, W2, H2, r_nahe) if any(versch) else None
        gut = [0] * len(stempel)
        n_st = len(stempel)

        # DURCHGANG-KREDIT (AP.01-Flur-Sezierung 2026-08-19, hinter
        # DURCHGANG_KREDIT): offene Durchgaenge (nur Sturz "STUK +2,20",
        # keine Tuer) werden von Linien+Closing als 30-50-cm-Baender
        # zugebrannt — BODEN ohne jede Poché (Flur f_ist -19 %). Echte
        # Waende haben Schraffur. Regel: eine Brandzelle OHNE Poché, die
        # binnen 0,55 m in einer Achse ZWISCHEN zwei Raumzellen liegt,
        # ist Boden und zaehlt wie versch.
        # Standard AN seit 2026-08-19 (Korpus: AP.01 Oe 4,3->2,8, Angerer
        # 2,5->2,4, Sadiku 3,3->3,2; Verifikationen 8/6/14 stabil).
        # DURCHGANG_KREDIT=0 schaltet ab.
        _dk_an = os.environ.get("DURCHGANG_KREDIT", "1") != "0" and any(_hatch_roh)
        _k_band = max(2, int(0.85 / rst.zm))
        # STEMPEL-GERICHTET: Boden-Brand-Kredit NUR an Raeume im DEFIZIT
        # (erste Fassung fuetterte satte Raeume ueber ihr F-Gate hinaus:
        # verifiziert 8 -> 5). versch-/Tuerzonen-Kredit bleibt wie er war.
        _zm2k = rst.zm * rst.zm
        _basis_f = [f for (f, _u) in masse]
        _sf_kappe = []
        for _li in range(len(masse)):
            try:
                _sf_kappe.append(float(stempel[_li].get("f_m2") or 0))
            except Exception:
                _sf_kappe.append(0.0)

        def _boden_brand(idx):
            if _hatch_roh[idx]:
                return False           # Poché = echte Wand
            _i0, _j0 = idx % W2, idx // W2
            for _achse in (1, W2):
                _seiten = 0
                for _vzb in (-1, 1):
                    _p = idx
                    for _ in range(_k_band):
                        _p += _vzb * _achse
                        if not (0 <= _p < W2 * H2):
                            break
                        if _achse == 1 and abs(_p % W2 - _i0) > _k_band:
                            break
                        if not grid[_p]:
                            if label[_p] >= 0:
                                _seiten += 1
                            break
                if _seiten == 2:
                    return True
            return False

        _idx_folge = []
        for idx in range(W2 * H2):
            if not grid[idx]:
                continue
            _kl0 = versch[idx] or (_in_tz(idx) and d_versch is not None
                                   and d_versch[idx] <= r_nahe)
            if _kl0:
                _idx_folge.append((0, idx))
            elif _dk_an and _boden_brand(idx):
                _idx_folge.append((1, idx))
        _idx_folge.sort()    # klassisch (0) VOR boden (1): die laufende
        # Stempel-Kappe muss den klassischen Kredit schon eingerechnet
        # haben, sonst rutscht Boden-Kredit VOR ihm durch (Zimmer 1 +7,4).
        for (_art, idx) in _idx_folge:
            _nur_boden = (_art == 1)
            i0_, j0_ = idx % W2, idx // W2
            best_l, best_d = None, 99
            for rad in range(1, 9):
                for di in (-rad, 0, rad):
                    for dj in (-rad, 0, rad):
                        if abs(di) != rad and abs(dj) != rad:
                            continue
                        ni, nj = i0_ + di, j0_ + dj
                        if 0 <= ni < W2 and 0 <= nj < H2:
                            l2 = label[nj * W2 + ni]
                            if 0 <= l2 < n_st and rad < best_d:
                                best_l, best_d = l2, rad
                if best_l is not None:
                    break
            if best_l is not None:
                if _nur_boden:
                    # LAUFENDE STEMPEL-KAPPE: Boden-Brand-Kredit nur, bis
                    # der Raum seinen Stempel erreicht — nie darueber.
                    # (Defizit-Schwelle allein reichte nicht: Raeume knapp
                    # unter dem Stempel wurden ueber das F-Gate gefuettert.)
                    if not _sf_kappe[best_l] or                             _basis_f[best_l] + gut[best_l] * _zm2k                             >= _sf_kappe[best_l]:
                        continue
                gut[best_l] += 1
                if kredit_out is not None:
                    kredit_out.setdefault(best_l, []).append(idx)
        zm2 = rst.zm * rst.zm
        masse = [(f + gut[li] * zm2, u) for li, (f, u) in enumerate(masse)]
        out = []
        for idx, st in enumerate(stempel):
            if not ok_start[idx]:
                out.append(dict(st, status="kein_start", f_ist=None, u_ist=None))
                continue
            f_ist, u_ist = masse[idx]
            f_ok = abs(f_ist - st["f_m2"]) / st["f_m2"] <= tol_f
            if not f_ok and f_ist < st["f_m2"]:
                # HALBZELLEN-BIAS (gerichtet): Wandlinien-Zellen zählen ganz
                # als Wand, die wahre Fläche reicht im Mittel eine halbe Zelle
                # hinein → F wird um bis zu U×zelle/2 UNTERschätzt (0,26m² bei
                # 0.037er-Raster, gemessen). Nur die UNTERE Gate-Seite weiten —
                # symmetrisch kippte Angerer Bad/Geräte über das obere Gate.
                f_tief = f_ist + u_ist * rst.zm / 2.0
                f_ok = abs(min(f_tief, st["f_m2"]) - st["f_m2"]) \
                    / st["f_m2"] <= tol_f
            if st.get("u_m") is not None:
                u_ok = abs(u_ist - st["u_m"]) / st["u_m"] <= tol_u
                if not u_ok and u_ist > st["u_m"]:
                    # U-RASTER-GATE (einseitig, analog F-Halbzellen v5b):
                    # die Silhouette kreneliert raster-linear (~2,0·zm·U,
                    # über 3 Raster 0.02/0.037/0.08 bei identischen Inputs
                    # gemessen; 46-172 Polygon-Ecken statt 4-8) — wand-
                    # flankierte Kanäle sind für Closing/Opening unsichtbar.
                    # Nur die ÜBERSCHUSS-Seite; echte Ausläufer (≥+27%)
                    # bleiben draußen (6 Stichproben geometrie-verifiziert).
                    u_ok = abs(u_ist / (1.0 + 2.0 * rst.zm) - st["u_m"]) \
                        / st["u_m"] <= tol_u
            else:
                # KOMPAKTHEITS-GATE statt Freifahrt (WM: Radabstell 'verifiziert'
                # mit U_ist=44,9 bei F=22,7 — Korridor-Schlange, aber ohne
                # Stempel-U lief das U-Gate leer). Isoperimetrie: U(Quadrat)=4√F;
                # reale Räume ≤ ~1,8×; Angerer 'Park' 1,25 bleibt ✓.
                u_ok = f_ist > 0 and u_ist <= 1.8 * 4.0 * (f_ist ** 0.5)
            status = "verifiziert" if (f_ok and u_ok) else ("u_daneben" if f_ok else "f_daneben")
            out.append(dict(st, status=status, f_ist=round(f_ist, 2), u_ist=round(u_ist, 2)))
        # VEKTOR-EXAKTE KONTUR-MESSUNG (Nutzer-Befund: „die Räume werden nicht
        # genau nachgezeichnet"). Dieselbe Kontur, die raum_regionen zeichnet,
        # misst hier F/U: Kanten auf den echten WANDLINIEN (pt), Ecken als
        # Schnittpunkte — ohne Raster-Krenellierung und Halbzellen-Bias, die
        # die beiden Einseit-Heuristiken oben erst nötig machten. Streng
        # MONOTON wie die Ebenen-Merges: nur f/u_daneben → verifiziert, nie
        # ein Verlust. Snap-Quote <85 % (offene/zerfranste Konturen) bleibt
        # bei der Raster-Messung — ehrlich statt erfunden.
        if any(r["status"] not in ("verifiziert", "kein_start") for r in out):
            _cells_r = {}
            for _i2 in range(W2 * H2):
                _l2 = label[_i2]
                if 0 <= _l2 < n_st:
                    _cells_r.setdefault(_l2, []).append(_i2)
            for idx2 in range(n_st):
                if out[idx2]["status"] in ("verifiziert", "kein_start"):
                    continue
                cells = _cells_r.get(idx2)
                if not cells:
                    continue
                try:
                    vereinfacht, _nc = _umriss_zellen(label, W2, H2, idx2,
                                                      zm2, cells=cells)
                    if not vereinfacht or len(vereinfacht) < 3:
                        continue
                    kx = raum_kontur_exakt(vereinfacht, grid, W2, H2, rst,
                                           dark_segs, stuetzen=_stuetzen,
                                           paare=_paare_ik_m)
                    if not kx:
                        continue
                    st = stempel[idx2]
                    # KEIN Snap-Quote-Gate hier: der Beweis kommt aus dem
                    # F+U-Doppel-Gate gegen die byte-exakten Stempel (zwei
                    # unabhängige Werte) — nicht aus der Wand-Nähe. Ein
                    # Carport hat legitime OFFENE Kanten (Angerer-Parkplatz:
                    # 48 % gesnappt, F +1 %, U +3 % → bewiesen), ein
                    # zerfranster Umriss scheitert am F/U-Gate selbst.
                    # Tür-Laibungs-Gutschrift wie beim Raster-Pfad (die
                    # Kontur läuft auf der Wandlinie — der Durchgang zählt
                    # laut Plan-F zum Raum, s. Balken-Gutschrift oben).
                    f_p = kx["f_m2"] + gut[idx2] * zm2
                    u_p = kx["u_m"]
                    # Plausibilität: die exakte Fläche darf vom Zell-Becken
                    # nicht grob abweichen (Fehlsnap/Selbstschneidung).
                    if abs(f_p - masse[idx2][0]) / max(masse[idx2][0], 1e-9) > 0.20:
                        continue
                    f_ok2 = abs(f_p - st["f_m2"]) / st["f_m2"] <= tol_f
                    if st.get("u_m") is not None:
                        u_ok2 = abs(u_p - st["u_m"]) / st["u_m"] <= tol_u
                    else:
                        u_ok2 = f_p > 0 and u_p <= 1.8 * 4.0 * (f_p ** 0.5)
                    if f_ok2 and u_ok2:
                        out[idx2].update(status="verifiziert",
                                         f_ist=round(f_p, 2),
                                         u_ist=round(u_p, 2),
                                         ebene="vektor")
                except Exception:
                    continue
        return out

    grid, label, ok_start, AUSSEN, versch = _pass(False)   # ROHBAU-Ebene
    # GUTSCHRIFT-ZELLEN je Raum einsammeln (Tuerdurchgaenge, die laut Plan-F
    # zum Raum zaehlen): die ZEICHNUNG soll dieselben Zellen zeigen duerfen,
    # die die MENGE laengst kreditiert — Nutzer-Befund "beim Flur laesst er
    # das erste kurze Stueck aus" = genau diese Tuerbuchten fehlen im
    # gezeichneten Umriss (Flur DP -5,4 % bei f_ist +0,2 %).
    _kredit_cells = {}
    if debug is not None:
        debug.update({"grid": grid, "label": label, "rst": rst, "AUSSEN": AUSSEN,
                      "hatch_roh": _hatch_roh, "versch": versch,
                      "stuetzen": _stuetzen, "boegen": boegen,
                      "kredit_cells": _kredit_cells,
                      "draussen": _draussen_maske(grid, label, rst.W, rst.H)})
    # TASCHEN-ANSPRUCH (Korridor-Graben AP.01-Flur, 2026-08-19, hinter
    # POCKET_CLAIM): das Gegenstueck zum Tab-Abwurf. Tuer-Balken zerlegen
    # einen Korridor in Segmente und lassen UNBEANSPRUCHTE Taschen
    # (freie Zellen ohne Label) zurueck — der Stempel zaehlt den Boden
    # aber durchgehend (Flur f_ist -19,3 %). Ein Raum UNTER seinem
    # Stempel darf angrenzende unbeanspruchte freie Zellen per BFS
    # beanspruchen, GEDECKELT beim Stempel: nie mehr Zellen, als die
    # byte-exakte Flaeche erlaubt. Reihenfolge nach groesstem Defizit.
    # TASCHEN-BRUECKE (Korridor-Graben AP.01-Flur, 2026-08-19, hinter
    # POCKET_CLAIM): Tuer-Balken zerlegen einen Korridor in SEGMENTE
    # desselben Labels; die Tasche dazwischen (freie Zellen ohne Label)
    # zaehlt der Stempel als Boden mit. BEANSPRUCHT wird eine Tasche NUR,
    # wenn sie durch duenne Balken (<=0,25 m) MINDESTENS ZWEI getrennte
    # Komponenten DESSELBEN Raums verbindet — Fensternischen beruehren nur
    # eine Komponente und bleiben unbeansprucht (erste Fassung frass durch
    # die Parapet-Balken die eigenen Nischen: max 9,9 -> 17,5 %). Deckel:
    # nie ueber den Stempel.
    if os.environ.get("POCKET_CLAIM") and stempel:
        try:
            from collections import deque as _dq3
            _zm2p = rst.zm * rst.zm
            _WH = rst.W * rst.H
            _K3 = max(2, int(0.25 / rst.zm))
            _vor = _messen_und_status(grid, label, ok_start, versch)

            def _tunnelziel(_start, _ri):
                _pos = _start
                for _ in range(_K3):
                    _neu = _pos + _ri
                    if not (0 <= _neu < _WH) or abs(_neu % rst.W - _pos % rst.W) > 1:
                        return None
                    _pos = _neu
                    if not grid[_pos]:
                        return _pos
                return None

            for _i3 in range(len(stempel)):
                try:
                    _sf3 = float(stempel[_i3].get("f_m2") or 0)
                except Exception:
                    continue
                _r3 = _vor[_i3] if _i3 < len(_vor) else None
                if not (_sf3 and _r3 and _r3.get("f_ist")
                        and _r3["f_ist"] < 0.97 * _sf3):
                    continue
                _budget_z = int((_sf3 - _r3["f_ist"]) / _zm2p)
                if os.environ.get("GUARD_DEBUG"):
                    print(f"[pocket?] {stempel[_i3].get('name')} "
                          f"defizit={_sf3 - _r3['f_ist']:.2f} budget_z={_budget_z}")
                if _budget_z < 8:
                    continue
                # Komponenten des Labels
                _komp_id = {}
                _nk = 0
                for _ix in range(_WH):
                    if label[_ix] != _i3 or _ix in _komp_id:
                        continue
                    _q = _dq3([_ix]); _komp_id[_ix] = _nk
                    while _q:
                        _c = _q.popleft()
                        for _nb in (_c - 1, _c + 1, _c - rst.W, _c + rst.W):
                            if 0 <= _nb < _WH and label[_nb] == _i3                                     and _nb not in _komp_id                                     and abs(_nb % rst.W - _c % rst.W) <= 1:
                                _komp_id[_nb] = _nk; _q.append(_nb)
                    _nk += 1
                # v3: auch EIN Segment laeuft weiter — grosse Taschen
                # hinter Tuer-Verschluessen (Windfang) brauchen keine
                # zweite Komponente. Der Zwei-Komponenten-Weg bleibt
                # zusaetzlich bestehen.
                # freie unbeanspruchte Taschen einsammeln
                _pseen = bytearray(_WH)
                _genommen = 0
                for _ix in range(_WH):
                    if _pseen[_ix] or grid[_ix] or label[_ix] >= 0:
                        continue
                    _q = _dq3([_ix]); _pseen[_ix] = 1
                    _tasche = [_ix]
                    while _q:
                        _c = _q.popleft()
                        for _nb in (_c - 1, _c + 1, _c - rst.W, _c + rst.W):
                            if 0 <= _nb < _WH and not _pseen[_nb]                                     and not grid[_nb] and label[_nb] < 0                                     and abs(_nb % rst.W - _c % rst.W) <= 1:
                                _pseen[_nb] = 1; _q.append(_nb)
                                _tasche.append(_nb)
                    if not (4 <= len(_tasche) <= _budget_z - _genommen):
                        continue
                    # Welche Komponenten erreicht die Tasche durch Balken?
                    # v3 (Windfang-Befund 2026-08-19): grosse Taschen
                    # (>=1,2 m2), die den Raum durch einen VERSCHLUSS-
                    # Balken erreichen (echte Tueroeffnung), sind auch mit
                    # EINER Komponente beanspruchbar. Fensternischen
                    # bleiben draussen: sie sind <=0,8 m2 — die GROESSE
                    # trennt (ihr Parapet-Balken ist ebenfalls versch).
                    _durch_versch = False
                    _erreicht = set()
                    for _c in _tasche:
                        for _ri in (-1, 1, -rst.W, rst.W):
                            _nb = _c + _ri
                            if not (0 <= _nb < _WH)                                     or abs(_nb % rst.W - _c % rst.W) > 1:
                                continue
                            if label[_nb] == _i3:
                                _erreicht.add(_komp_id.get(_nb, -1))
                            elif grid[_nb]:
                                _z = _tunnelziel(_nb, _ri)
                                if _z is not None and label[_z] == _i3:
                                    _erreicht.add(_komp_id.get(_z, -1))
                                    if versch[_nb]:
                                        _durch_versch = True
                        if len(_erreicht) >= 2:
                            break
                    _gross_durch_tuer = (len(_erreicht) >= 1
                                         and _durch_versch
                                         and len(_tasche) * _zm2p >= 1.2)
                    if os.environ.get("GUARD_DEBUG") and len(_tasche) * _zm2p >= 0.5:
                        print(f"[tasche] {len(_tasche)*_zm2p:.2f} m2 "
                              f"komp={len(_erreicht)} versch={_durch_versch}")
                    if len(_erreicht) >= 2 or _gross_durch_tuer:
                        for _c in _tasche:
                            label[_c] = _i3
                        _genommen += len(_tasche)
                if _genommen and os.environ.get("GUARD_DEBUG"):
                    print(f"[pocket] {stempel[_i3].get('name')}: "
                          f"{_genommen} Brueckenzellen "
                          f"({_genommen*_zm2p:.2f} m2)")
        except Exception as _pe:  # pragma: no cover
            import traceback as _tb3
            print(f"[pocket] fehlgeschlagen: {_pe}")
            _tb3.print_exc()

    out = _messen_und_status(grid, label, ok_start, versch,
                             kredit_out=_kredit_cells)
    for r in out:
        if r["status"] == "verifiziert":
            r["ebene"] = r.get("ebene") or "roh"   # "vektor" nicht überschreiben
    # SCHACHT-GLÄTTUNGS-EBENE (Bad-Roh-F-Sezierung, monoton wie Roh/Fertig):
    # kleine Räume mit Installations-/Schacht-BUCHTEN (0,6-0,8m) tragen bei
    # EXAKTEM F ein raster-krenelliertes U (+33% gemessen) — die 0,25er-
    # Glättung schließt die Buchten nicht. Dasselbe Grid mit 0,40er-Glättung
    # NEU vermessen (kein zweiter Watershed — nur die Silhouetten-Glättung der
    # Messung) und NUR dazu-mergen. Global auf 0,40 gestellt kostet den TG
    # einen Raum (Stellplatz-Poché); als reiner ADD-Merge kann er NICHTS
    # verlieren (TG-Grüne kommen aus der 0,25er-Ebene, hier unangetastet).
    # (0,55er-Zweitstufe gemessen & verworfen: die WM-Zimmer mit U +60% bei
    # exaktem F sind echte große Buchten, keine glättbare Krenellierung —
    # 0,55 heilte 0 Räume, nur Latenz. 0,40 bleibt die Schacht-Ebene.)
    if any(r["status"] not in ("verifiziert", "kein_start") for r in out):
        try:
            out_g = _messen_und_status(grid, label, ok_start, versch, r_gl_gross=0.40)
            for r1, rg in zip(out, out_g):
                if r1["status"] != "verifiziert" and rg["status"] == "verifiziert":
                    r1.update(status="verifiziert", f_ist=rg["f_ist"],
                              u_ist=rg["u_ist"], ebene=rg.get("ebene") or "schacht")
        except Exception:
            pass
    # BODEN-SCHRAFFUR-EBENE (Bad-Roh-F-Sezierung, monotoner ADD-Merge): auf
    # monochromen Plänen wird Fliesen-/Belags-Feinschraffur IM Rauminneren als
    # Wand gebrannt → kleine Räume werden an der Fill-Grenze abgeschnitten (F
    # −19..−43%). hatch_fill_filter trennt die dünne Wand-Poché von der fetten
    # Bodenfläche. Global kostet der Filter 2 WM-Zufalls-Grüne + 1 TG-Raum
    # (Stellplatz-Poché) — als reiner ADD-Merge kann er NICHTS verlieren.
    # GATE: nur wenn der Filter ≥8% der Schraffur entfernt (Boden-Tiling-
    # Signatur) — sonst kein Zusatz-Watershed (EFH/Farbpläne bleiben schnell).
    if any(r["status"] not in ("verifiziert", "kein_start") for r in out):
        try:
            hatch_f = hatch_fill_filter(hatch_segs, box, ptm)
            if hatch_segs and len(hatch_f) <= 0.92 * len(hatch_segs):
                g4, l4, ok4, _au4, v4 = _pass(False, hatch_use=hatch_f)
                out_f = _messen_und_status(g4, l4, ok4, v4, r_gl_gross=0.40)
                for r1, rf in zip(out, out_f):
                    if r1["status"] != "verifiziert" and rf["status"] == "verifiziert":
                        r1.update(status="verifiziert", f_ist=rf["f_ist"],
                                  u_ist=rf["u_ist"], ebene=rf.get("ebene") or "boden")
        except Exception:
            pass
    # ZWEI-EBENEN-VERIFIKATION (Bad-Anatomie-Sezierung): Stempel messen FERTIG-
    # Maße, die Maske ROHBAU. Pass 2 brennt zusätzlich die unpochierten
    # Doppellinien (Vorwände/leichte Trennwände = Fertig-Grenzen) und darf
    # Räume NUR dazugewinnen (monotoner Merge — Regressionsfreiheit hängt an
    # der Monotonie, gemessen: Angerer 5→6, WM 4 gehalten, IoU-Guard auf dem
    # unveränderten Pass-1-Grid). f_ist/u_ist kommen vom verifizierenden Pass.
    if any(r["status"] not in ("verifiziert", "kein_start") for r in out):
        try:
            g2, l2, ok2, _au2, v2 = _pass(True)   # FERTIG-Ebene
            out2 = _messen_und_status(g2, l2, ok2, v2)
            if debug is not None:
                debug["out_fertig"] = out2   # Sezier-Sicht auf den FERTIG-Pass
                debug["fertig_grid"] = g2
                debug["fertig_label"] = l2
            for r1, r2 in zip(out, out2):
                if r1["status"] != "verifiziert" and r2["status"] == "verifiziert":
                    r1.update(status="verifiziert", f_ist=r2["f_ist"],
                              u_ist=r2["u_ist"],
                              ebene=r2.get("ebene") or "fertig")
                elif (r1["status"] == "u_daneben"
                      and r2.get("u_m") is not None
                      and r2.get("u_ist") is not None):
                    # HYBRID (Bad-Vorwand-Sezierung): Stempel messen FERTIG.
                    # Der ROHBAU-Pass beweist F exakt (Basin inkl. Schacht-
                    # Nische = Rohbau-Raum), leckt aber im U durch die im
                    # Rohbau BEWUSST offene Vorwand-/Schacht-Zone ('DB lt.
                    # HKLS-E Plan'); der FERTIG-Pass versiegelt sie und trifft
                    # U, verliert aber legitim die Taschen-Fläche. Kreuz-
                    # Beweis: F=roh, U=fertig — Gates unverändert, streng
                    # monoton (nur u_daneben→verifiziert möglich).
                    _u2, _us = r2["u_ist"], r2["u_m"]
                    _uok = abs(_u2 - _us) / _us <= tol_u
                    if not _uok and _u2 > _us:
                        _uok = abs(_u2 / (1.0 + 2.0 * rst.zm) - _us) \
                            / _us <= tol_u
                    if _uok:
                        r1.update(status="verifiziert", u_ist=_u2,
                                  ebene="hybrid")
        except Exception as _e2:
            # PASS-2-TOD SICHTBAR machen (Bad-Roh-F-Sezierung: ein still
            # verschluckter Fertig-Pass-Abbruch degradierte das Ergebnis
            # unsichtbar auf ROH-only — im Experiment kostete das 14
            # Verifikationen ohne jedes Signal). Verhalten unverändert
            # (best-effort bleibt), aber Log + debug-Feld.
            print(f"[raumnetz] FERTIG-Pass abgebrochen: {type(_e2).__name__}: {str(_e2)[:120]}")
            if debug is not None:
                debug["fertig_pass_fehler"] = f"{type(_e2).__name__}: {str(_e2)[:200]}"
    return out, stempel


# ────────────────────────────────────────────────────────────────────
# RÄUMLICHER IoU-BEWEIS (v3, Juli 2026) — der Goldstandard der Verifikation
# ────────────────────────────────────────────────────────────────────
def raum_iou_beweis(res_liste, label, rst, fv, fh, ptm, iou_min=0.85, nur_bbox=False):
    """Annotiert res_liste-Einträge mit iou_bewiesen/iou_wert/iou_form.

    nur_bbox=True (GROSSPLÄNE, WM/TG): nur der raum-LOKALE erste Pass läuft — die
    Fluchten werden auf die Raum-Bounding-Box ±0,5m beschränkt. Das entfernt die
    globale Fluchten-Ambiguität (der Grund, warum F+U-Beweise auf dichten Plänen
    versagen), OHNE den kombinatorischen Full-Pool-Fallback (O(dichte⁴), der die
    Grossplan-Sperre auslöste). Damit greift der Goldstandard-Beweis auch auf den
    großen Plänen, wo Roh-Status + rohbau_ok null tragen (gemessen: TG 16/25, WM
    55/70 — Zusatz-Beweise 0). Streng monoton: setzt nur iou_bewiesen (add-only).

    Beweis: eine Rect- oder L-Form aus FLUCHT-Paaren muss die Raum-REGION
    räumlich decken (exakte IoU auf Zeilen-Runs, Schwelle kalibriert 0,85;
    Bad=0,93 zeigt: echte Einbauten drücken legitim). Eindeutigkeit: keine
    andersartige Form über der Schwelle ohne ≥0,02-Rückstand. Drei Such-
    stufen: BBox-Fenster ±0,5m → Form-Obergrenzen-Skip (erschöpfende
    BBox-Ecken-Suche; Obergrenze < Schwelle−0,02 ⇒ formuntauglich, ehrlich
    NICHT bewiesen) → Voll-Pool-Fallback (Grenzfälle wie Bad).
    F+U allein UNTERBESTIMMEN Formen (613 passende Boundings gemessen) —
    nur die räumliche Deckung beweist. 5/5 formtaugliche Angerer-Räume."""
    W, H = rst.W, rst.H
    for idx, r in enumerate(res_liste):
        f_ziel = r.get("f_m2") or 0
        f_ist, u_ist = r.get("f_ist"), r.get("u_ist")
        if not (f_ziel and f_ist and u_ist):
            continue
        cx, cy = r["cx"], r["cy"]
        runs = {}
        n_region = 0
        for j in range(H):
            base = j * W
            i = 0
            zeile = []
            while i < W:
                if label[base + i] == idx:
                    a = i
                    while i < W and label[base + i] == idx:
                        i += 1
                    zeile.append((a, i - 1))
                    n_region += i - a
                else:
                    i += 1
            if zeile:
                runs[j] = zeile
        if not n_region:
            continue
        zm2 = rst.zm * rst.zm

        def _ovl(zeile, i0, i1):
            n = 0
            for (a, b) in zeile:
                lo, hi = max(a, i0), min(b, i1)
                if hi >= lo:
                    n += hi - lo + 1
            return n

        def iou(L_, R_, O_, U_, kerbe=None):
            i0 = int((L_ - rst.bx0) / rst.cell)
            i1 = int((R_ - rst.bx0) / rst.cell)
            j0 = max(0, int((O_ - rst.by0) / rst.cell))
            j1 = min(H - 1, int((U_ - rst.by0) / rst.cell))
            ki = None
            if kerbe:
                ki = (int((kerbe[0] - rst.bx0) / rst.cell),
                      int((kerbe[1] - rst.bx0) / rst.cell),
                      int((kerbe[2] - rst.by0) / rst.cell),
                      int((kerbe[3] - rst.by0) / rst.cell))
            inter = 0
            for j in range(j0, j1 + 1):
                zeile = runs.get(j)
                if not zeile:
                    continue
                inter += _ovl(zeile, i0, i1)
                if ki and ki[2] <= j <= ki[3]:
                    inter -= _ovl(zeile, ki[0], ki[1])
            fa = (R_ - L_) * (U_ - O_) / ptm / ptm
            if kerbe:
                fa -= ((kerbe[1] - kerbe[0]) * (kerbe[3] - kerbe[2])) / ptm / ptm
            union = fa / zm2 + n_region - inter
            return inter / union if union else 0.0

        ober = max(1.15 * f_ziel, 1.10 * f_ziel + 0.25)

        def _rank(fvu, fhu):
            kand = []
            vp = [(a, b) for a in fvu if a < cx for b in fvu if b > cx
                  if 0.5 <= (b - a) / ptm <= 14.0]
            hp = [(a, b) for a in fhu if a < cy for b in fhu if b > cy
                  if 0.5 <= (b - a) / ptm <= 14.0]
            for (l_, r_) in vp:
                w_ = (r_ - l_) / ptm
                for (o_, u_) in hp:
                    h_ = (u_ - o_) / ptm
                    a_ = w_ * h_
                    if 0.98 * f_ziel <= a_ <= ober:
                        kand.append((abs(a_ - f_ist), l_, r_, o_, u_, None,
                                     f"Rechteck {w_:.2f}×{h_:.2f} m"))
                    if abs(2 * (w_ + h_) - u_ist) / u_ist <= 0.08:
                        for xi in (p for p in fvu if l_ < p < r_):
                            for yj in (p for p in fhu if o_ < p < u_):
                                for kx in ((l_, xi), (xi, r_)):
                                    for ky in ((o_, yj), (yj, u_)):
                                        ka = ((kx[1] - kx[0]) * (ky[1] - ky[0])
                                              / ptm / ptm)
                                        if ka < 0.5:
                                            continue
                                        if abs(a_ - ka - f_ist) <= 0.05 * f_ziel:
                                            kand.append(
                                                (abs(a_ - ka - f_ist), l_, r_, o_, u_,
                                                 (kx[0], kx[1], ky[0], ky[1]),
                                                 f"L-Polygon {w_:.2f}×{h_:.2f}"
                                                 f"−{ka:.1f} m²"))
            rects = [k for k in kand if k[5] is None]
            ls = sorted((k for k in kand if k[5] is not None),
                        key=lambda t: t[0])[:120]
            return sorted(((iou(k[1], k[2], k[3], k[4], k[5]),) + k
                           for k in rects + ls), key=lambda t: -t[0])

        def _entscheide(gerankt):
            if not gerankt:
                return None, False
            t = gerankt[0]

            def _gf(g):
                return (abs(g[2] - t[2]) < 0.12 * ptm
                        and abs(g[3] - t[3]) < 0.12 * ptm
                        and abs(g[4] - t[4]) < 0.12 * ptm
                        and abs(g[5] - t[5]) < 0.12 * ptm)
            ok = (t[0] >= iou_min - 1e-9
                  and all(_gf(g) or g[0] < iou_min - 1e-9
                          or t[0] - g[0] >= 0.02 for g in gerankt[1:]))
            return t, ok

        rj = sorted(runs)
        rx0 = rst.bx0 + min(z[0][0] for z in runs.values()) * rst.cell - 0.5 * ptm
        rx1 = rst.bx0 + (max(z[-1][1] for z in runs.values()) + 1) * rst.cell + 0.5 * ptm
        ry0 = rst.by0 + rj[0] * rst.cell - 0.5 * ptm
        ry1 = rst.by0 + (rj[-1] + 1) * rst.cell + 0.5 * ptm
        top, ok1 = _entscheide(_rank([p for p in fv if rx0 <= p <= rx1],
                                     [p for p in fh if ry0 <= p <= ry1]))
        if not ok1 and nur_bbox:
            # GROSSPLAN: nur der raum-lokale Pass (Perf) — der kombinatorische
            # Full-Pool-Fallback bleibt aus, Raum ehrlich unbewiesen statt teuer.
            continue
        if not ok1:
            # Form-Obergrenzen-Skip: erschöpfende BBox-Ecken-Suche
            bx0_, bx1_ = rx0 + 0.5 * ptm, rx1 - 0.5 * ptm
            by0_, by1_ = ry0 + 0.5 * ptm, ry1 - 0.5 * ptm
            max_iou = iou(bx0_, bx1_, by0_, by1_)
            for ex in (0, 1):
                for ey in (0, 1):
                    for fwn in range(2, 26, 2):
                        for fhn in range(2, 26, 2):
                            wn, hn = fwn * 0.25 * ptm, fhn * 0.25 * ptm
                            if wn >= (bx1_ - bx0_) or hn >= (by1_ - by0_):
                                continue
                            kx = (bx0_, bx0_ + wn) if ex == 0 else (bx1_ - wn, bx1_)
                            ky = (by0_, by0_ + hn) if ey == 0 else (by1_ - hn, by1_)
                            v = iou(bx0_, bx1_, by0_, by1_,
                                    (kx[0], kx[1], ky[0], ky[1]))
                            if v > max_iou:
                                max_iou = v
            if max_iou < iou_min - 0.02:
                r["iou_max_form"] = round(max_iou, 2)   # formuntauglich, ehrlich
                continue
            top, ok1 = _entscheide(_rank(fv, fh))
        if top is not None and ok1:
            r["iou_bewiesen"] = True
            r["iou_wert"] = round(top[0], 3)
            r["iou_form"] = top[7]
            # RECHTECK-KOORDINATEN AUFHEBEN (Seiten-pt): bisher wurde nur das
            # Urteil behalten und die Geometrie weggeworfen. Dieses Rechteck
            # stammt aus ECHTEN Wandfluchten, enthaelt den Raumstempel und
            # trifft die gestempelte Flaeche — es ist damit die beste
            # verfuegbare Raumkontur fuer Raeume, deren Watershed-Region
            # unbrauchbar ist. (l, r, o, u) + optionale Kerbe fuer L-Formen.
            r["iou_rect_pt"] = (top[2], top[3], top[4], top[5])
            r["iou_kerbe_pt"] = top[6]


def raum_rechteck_aus_fluchten(cx, cy, f_soll, fv, fh, ptm, tol=0.18,
                               min_seite_m=0.6, max_seite_m=25.0,
                               fremde_stempel=None, fremde_flaechen=None,
                               max_ueberlappung=0.15):
    """RAUM-RECHTECK aus Wandfluchten — für Räume OHNE beweisbare Region.

    Die IoU-Beweis-Suche findet dasselbe, ist aber an eine strenge Beweis-
    Schwelle gekoppelt; fällt ein Raum dort durch, blieb bisher nur ein grob
    an der Stempelstelle zentriertes Rechteck übrig, das sichtbar über die
    Wände hinausragte (am Live-Plan bestätigt: Zimmer 1).

    Hier wird NUR das Nötigste verlangt, dafür ohne Beweis-Anspruch:
      * der Raumstempel (cx,cy) liegt INNERHALB des Rechtecks
      * die Fläche trifft die byte-exakte Stempelfläche (±tol)
      * plausible Seitenlängen
    Gewählt wird das ÜBERLAPPUNGSÄRMSTE, dann das flächengenaueste, bei
    Gleichstand das ENGSTE (kleinste) Rechteck — so gewinnt die tatsächliche
    Raumbegrenzung gegen weiter außen liegende Fluchten.
    Rückgabe (l, r, o, u) in Seiten-pt oder None.

    fremde_flaechen: [(l, r, o, u, f_echt_pt2), ...] — schon gezeichnete
    Umrisse anderer Räume als Hüllrechteck plus ihre WAHRE Polygonfläche.
    Der Stempel-Test allein reicht nicht: ein Rechteck kann den halben
    Nachbarraum überdecken, ohne dessen Stempel zu enthalten. Am WM-Plan
    gemessen — 16 von 18 überlappenden Raumpaaren hatten genau hier ihre
    Ursache (Lift E überdeckte den Vorraum zu 95%). Überlappung wird nicht
    hart verboten, sondern als erstes Gütekriterium bewertet: so verliert
    kein Raum seinen Umriss, es gewinnt nur der, der niemanden verdrängt.
    """
    if not f_soll or f_soll <= 0 or not ptm or ptm <= 0:
        return None
    if not fv or not fh:
        return None
    links = sorted(p for p in fv if p < cx)
    rechts = sorted((p for p in fv if p > cx), reverse=True)
    oben = sorted(p for p in fh if p < cy)
    unten = sorted((p for p in fh if p > cy), reverse=True)
    if not (links and rechts and oben and unten):
        return None
    # von innen nach außen: die nächstliegenden Fluchten zuerst
    links.reverse(); rechts.reverse(); oben.reverse(); unten.reverse()
    lo, hi = min_seite_m * ptm, max_seite_m * ptm
    bester = None
    notnagel = None     # bestes Rechteck, das einen Nachbarn verdrängen würde
    for l_ in links[:14]:
        for r_ in rechts[:14]:
            b = r_ - l_
            if not (lo <= b <= hi):
                continue
            for o_ in oben[:14]:
                for u_ in unten[:14]:
                    h = u_ - o_
                    if not (lo <= h <= hi):
                        continue
                    a = b * h / (ptm * ptm)
                    d = abs(a - f_soll) / f_soll
                    if d > tol:
                        continue
                    # EIN RAUM, EIN STEMPEL: ein Rechteck, das den Stempel
                    # eines ANDEREN Raums mit einschließt, hat zwei Räume
                    # gefasst — der klassische Fehler (Zimmer 1 verschluckte
                    # das Bad, beide Umrisse lagen übereinander).
                    if fremde_stempel:
                        _kollision = False
                        for (fx, fy) in fremde_stempel:
                            if l_ < fx < r_ and o_ < fy < u_:
                                _kollision = True
                                break
                        if _kollision:
                            continue
                    # ÜBERLAPPUNG mit schon gezeichneten Räumen. Das Hüll-
                    # rechteck des fremden Umrisses ist eine OBERGRENZE der
                    # echten Überschneidung — verglichen wird darum gegen die
                    # wahre Polygonfläche, damit ein verwinkelter Nachbar kein
                    # legitimes Rechteck blockiert.
                    ov = 0.0
                    if fremde_flaechen:
                        _ca = b * h
                        for (fl_, fr_, fo_, fu_, ff_) in fremde_flaechen:
                            iw = min(r_, fr_) - max(l_, fl_)
                            ih = min(u_, fu_) - max(o_, fo_)
                            if iw <= 0 or ih <= 0:
                                continue
                            bez = min(_ca, ff_) if ff_ and ff_ > 0 else _ca
                            ov = max(ov, min(1.0, iw * ih / max(1e-9, bez)))
                    # Güte UNVERÄNDERT: Flächentreue zuerst, dann kompakter.
                    # Die Überlappung darf hier NICHT mitranken — gemessen
                    # wurde das: als Rangkriterium gewinnt ein Rechteck mit
                    # 0% Überlappung und 18% falscher Fläche, wandert dadurch
                    # woandershin und überlappt am Ende MEHR (25 -> 27 Räume
                    # am Korpus). Sie ist ein Ausschluss, kein Geschmack.
                    g = (round(d, 3), b * h)
                    if ov <= max_ueberlappung:
                        if bester is None or g < bester[0]:
                            bester = (g, (l_, r_, o_, u_))
                    elif notnagel is None or g < notnagel[0]:
                        notnagel = (g, (l_, r_, o_, u_))
    # RÜCKFALLEBENE: verdrängt jedes mögliche Rechteck einen Nachbarn, ist ein
    # grob platzierter Umriss immer noch besser als gar keiner — der Raum wäre
    # sonst im Plan unsichtbar und seine Menge nicht nachprüfbar.
    if bester:
        return bester[1]
    return notnagel[1] if notnagel else None
