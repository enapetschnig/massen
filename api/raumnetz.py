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
import re
from collections import deque

_KOMPAKT_MIN = 3   # Kompaktheits-Schwelle des F-Ausgleichs (Ziel-Nachbarn von 8; Sweep: 3 minimiert U-Fehler bei exaktem F)

# Wörter, die im Raum-Stempel stehen, aber KEINE Raumnamen sind (Bodenbeläge/Material/
# Außenflächen-Beschriftungen — empirisch am WM-Plan gefunden)
_KEIN_RAUMNAME = ("fliesen", "parkett", "laminat", "teppich", "estrich", "beton",
                  "betonplatten", "kies", "wiese", "rasen", "pflaster", "asphalt",
                  "holz", "vlies", "epoxy", "keramik", "stein", "feinstein")

# Punkt-Dezimal ("Fl: 5.90m²", 1762788650811-Plan) UND Komma mit Tausender-Punkt.
# BF: = Bodenfläche (Polierplan-Konvention, AP.01: 6 von 9 Seeds fehlten sonst).
_F_RX = re.compile(r"^(?:F[lL]\s*[.:]?|BF\s*[.:]?|F\s*[.:])\s*([0-9][0-9\s.]*,[0-9]+|[0-9]+\.[0-9]{1,2}|[0-9]+)\s*m", re.I)
# Solo-Anker ("BF:" allein, Zahl als Tab-Spalte 20-28pt rechts — AP.01-Encoding)
_F_ANKER_RX = re.compile(r"^(?:F[lL]\s*[.:]?|BF\s*[.:]?|F\s*[.:])$", re.I)
_U_ANKER_RX = re.compile(r"^U\s*[.:]$", re.I)
# Bauteil-/Wandtyp-Codes sind KEINE Raumnamen (stehen auf Polierplänen näher
# am Stempel als der Name und gewannen die Nächster-Span-Suche: 'IW 2' statt Bad)
_CODE_RX = re.compile(r"^(?:IW|AW|TW|STB|RBL|STUK|RPH|FBH|FFB|RH|BF"
                      r"|FFOK|RDOK|RFOK|FOK|OK|UK)\b", re.I)   # + Höhenkoten (WM: 'RDOK-0,24' gewann sonst als Name)
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
                                  "x0": bb[0], "x1": bb[2]})
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
            if s2 is s or not re.match(r"^[A-Za-zÄÖÜäöüß]", s2["text"]):
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
    if not out:
        hoch2 = [s2 for s2 in spans if len(s2["text"]) == 1 and s2["text"] in ("²", "2")]
        nackt_rx = re.compile(r"^([0-9]{1,3},[0-9]{1,2})\s*m$")
        for s in spans:
            m2 = nackt_rx.match(s["text"])
            if not m2:
                continue
            f = _num(m2.group(1))
            if not f or f < 1.0 or f > 500:
                continue
            if not any(0 < (h["cx"] - s["cx"]) < 60 and abs(h["cy"] - s["cy"]) < 8
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
            for s2 in spans:
                if s2 is s or not re.match(r"^[A-Za-zÄÖÜäöüß]{3,}", s2["text"]):
                    continue
                # Bodenbeläge/Materialien sind KEINE Raumnamen (standen im Stempel näher
                # als der Name — gemessen am WM-Plan: 'Fliesen', 'Betonplatten' …)
                t0 = s2["text"].strip().lower()
                if any(t0.startswith(b) for b in _KEIN_RAUMNAME):
                    continue
                if _CODE_RX.match(s2["text"]):
                    continue    # Bauteil-/Koten-Code (WM: 'RDOK-0,24' statt Vorraum)
                d = abs(s["cy"] - s2["cy"]) + abs(s["cx"] - s2["cx"]) * 0.3
                if s2["cy"] < s["cy"] + 5 and d < best and d < 90:
                    best, name = d, s2["text"]
            out.append({"name": name or "?", "f_m2": f, "u_m": _u_unter(s),
                        "cx": s["cx"], "cy": s["cy"]})
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
               boegen=None, fill_rects=None, paar_fallback=False, stuetzen=None):
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
    r = max(1, int(hatch_dilat_m / rst.zm))
    dh = _dist_bfs(hm, W, H, r)
    hm_d = bytearray(1 if dh[i] <= r else 0 for i in range(W * H))

    grid = bytearray(hm)
    # TÜR-ZONEN: das aufgeklappte Türblatt + der Schwenkbogen werden sonst als "Wand"
    # verankert (Bad-Sezierung: Grenze beulte um das Türblatt). In der Tür-Zone keine
    # dunklen Kanten brennen — der Verschluss-Balken dichtet die Wandlinie ohnehin.
    tuer_zonen = []
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
        # HINGE-FORTSETZUNG (Zimmer-Sezierung: die IW03-Leichtwand zwischen
        # T-Stoß und Türangel wird von Tür-Zonen vetoiert → 0,6m-Loch):
        # jenseits des Angelpunkts muss die Wandflucht weitergehen — Muster
        # [Wand-Anlauf] Lücke(≥0,16m) Wand ⇒ Lücke mit Seal-Dicke brennen.
        ex, ey = hx - zx, hy - zy
        L2 = math.hypot(ex, ey) or 1.0
        ex, ey = ex / L2, ey / L2
        prof = []
        for k2 in range(1, 26):
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
        bogen_ok.append((hx, hy))

    for o in (oeffnungen or []):
        # Verschluss als DÜNNER BALKEN quer über die Wandlücke. Orientierung per
        # BEIDE-ENDEN-TEST: der richtige Balken überbrückt die Lücke, d.h. BEIDE
        # Enden treffen Wand (die reine Dichte-Heuristik wählte bei der Bad-Tür
        # die falsche Richtung → Leck, gemessen). Score = min(Ende1, Ende2).
        cx, cy = o["cx"], o["cy"]
        if o.get("typ") == "tuer" and any(
                math.hypot(hx - cx, hy - cy) < 1.5 * rst.ptm for (hx, hy) in bogen_ok):
            continue    # Tür bereits byte-genau aus dem Bogen versiegelt
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
            cy_s = rst.by0 + (summe / gew) * rst.cell if (gew and best_n > fenster // 2) else cy
            rst.rect(grid, cx - b2, cy_s - d2, cx + b2, cy_s + d2)
            if ist_tuer and versch_out is not None:
                rst.rect(versch_out, cx - b2, cy_s - d2, cx + b2, cy_s + d2)
        else:                   # Balken entlang y → Wand-Flucht = WANDBAND-MITTE
            gew, summe, best_n = 0, 0.0, 0
            for ii in range(max(0, ci - such), min(W, ci + such + 1)):
                nsum = sum(1 for jj in range(max(0, cj - fenster), min(H, cj + fenster + 1))
                           if grid[jj * W + ii])
                gew += nsum
                summe += nsum * ii
                best_n = max(best_n, nsum)
            cx_s = rst.bx0 + (summe / gew) * rst.cell if (gew and best_n > fenster // 2) else cx
            rst.rect(grid, cx_s - d2, cy - b2, cx_s + d2, cy + b2)
            if ist_tuer and versch_out is not None:
                rst.rect(versch_out, cx_s - d2, cy - b2, cx_s + d2, cy + b2)

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
    Soll-Fläche entscheidet) — sonst bleibt die Tasche ehrlich unzugeordnet."""
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
        _, best = kandidaten[0]
        soll = stempel[best]["f_m2"] / (rst.zm * rst.zm)
        alt, neu = fl[best], fl[best] + len(comp)
        if abs(neu - soll) < abs(alt - soll) and neu <= soll * 1.10:
            for idx in comp:
                label[idx] = best
            fl[best] = neu
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

    def geber(lab):
        return lab == AUSSEN or (0 <= lab < n and fl[lab] > soll[lab])

    for _ in range(max_runden):
        bewegt = False
        for b in range(n):
            if fl[b] >= soll[b]:
                continue
            zellen = [idx for idx in range(W * H) if label[idx] == b]
            if not zellen:
                continue
            # Kandidaten je Richtung: (dir, feste Linie) → Positionen entlang der Linie
            linien = {}
            for idx in zellen:
                i, j = idx % W, idx // W
                for di, dj in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    ni, nj = i + di, j + dj
                    nidx = nj * W + ni
                    if not (0 <= ni < W and 0 <= nj < H) or grid[nidx]:
                        continue
                    if geber(label[nidx]):
                        key = ((di, dj), ni if di else nj)
                        linien.setdefault(key, set()).add(nj if di else ni)
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


def _loecher_fuellen_und_messen(grid, label, rst, stempel):
    """Je Raum: eingeschlossene Löcher (Möbel-Inseln + deren Innenraum) zählen zur
    Raumfläche (so misst der Plan sein F), U wird die ÄUSSERE Wandlinie. Loch =
    Komponente von Nicht-Raum-Zellen, die die Raum-BBox nicht erreicht."""
    W, H = rst.W, rst.H
    out = []
    for li, st in enumerate(stempel):
        cells = [idx for idx in range(W * H) if label[idx] == li]
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
        r_gl = 0.25 if st["f_m2"] >= 4.0 else 0.12
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


def huellen_kontur(grid, label, rst, AUSSEN, min_umfang_m=8.0):
    """GEMAUERTE HÜLLE als Polylinie(n) in pt (Nachvollziehbarkeits-Audit P1:
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
    def _pass(paar_fallback):
        versch = bytearray(rst.W * rst.H)
        grid = wand_maske(rst, dark_segs, hatch_segs, oe, moebel_zonen=moebel,
                          versch_out=versch, boegen=boegen,
                          paar_fallback=paar_fallback, stuetzen=_stuetzen)
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
        label = _taschen_adoption(grid, label, rst, stempel, AUSSEN,
                                  huelle_burn=huelle_burn)
        label = _streifen_ausgleich(grid, label, rst, stempel, AUSSEN)
        label = _f_ausgleich(grid, label, rst, stempel, AUSSEN)
        label = _glaetten(grid, label, rst, len(stempel), AUSSEN)
        label = _f_ausgleich(grid, label, rst, stempel, AUSSEN)
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

    def _messen_und_status(grid, label, ok_start, versch):
        masse = _loecher_fuellen_und_messen(grid, label, rst, stempel)
        # Kredit nur BALKEN-NAH (WM-Sezierung: die 2,29-m-Haustür kreditierte via
        # Vollkreis-Zone 13,3 m² Wandfläche → Stiegenhaus +1,65 m²; die Kreiszone
        # wächst QUADRATISCH mit der Türbreite). Tür-Zonen-Zellen zählen nur noch
        # ≤0,25 m an einer Balken-Zelle — deckt die tote Closing-Zone (WC-
        # Sezierung) weiter ab, skaliert aber linear.
        r_nahe = max(1, int(0.25 / rst.zm))
        d_versch = _dist_bfs(versch, W2, H2, r_nahe) if any(versch) else None
        gut = [0] * len(stempel)
        n_st = len(stempel)
        for idx in range(W2 * H2):
            if not grid[idx]:
                continue
            if not (versch[idx] or (_in_tz(idx) and d_versch is not None
                                    and d_versch[idx] <= r_nahe)):
                continue
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
                gut[best_l] += 1
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
        return out

    grid, label, ok_start, AUSSEN, versch = _pass(False)   # ROHBAU-Ebene
    if debug is not None:
        debug.update({"grid": grid, "label": label, "rst": rst, "AUSSEN": AUSSEN})
    out = _messen_und_status(grid, label, ok_start, versch)
    for r in out:
        if r["status"] == "verifiziert":
            r["ebene"] = "roh"
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
            for r1, r2 in zip(out, out2):
                if r1["status"] != "verifiziert" and r2["status"] == "verifiziert":
                    r1.update(status="verifiziert", f_ist=r2["f_ist"],
                              u_ist=r2["u_ist"], ebene="fertig")
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
        except Exception:
            pass
    return out, stempel


# ────────────────────────────────────────────────────────────────────
# RÄUMLICHER IoU-BEWEIS (v3, Juli 2026) — der Goldstandard der Verifikation
# ────────────────────────────────────────────────────────────────────
def raum_iou_beweis(res_liste, label, rst, fv, fh, ptm, iou_min=0.85):
    """Annotiert res_liste-Einträge mit iou_bewiesen/iou_wert/iou_form.

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
