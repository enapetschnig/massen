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
                  "holz", "vlies", "epoxy", "keramik", "stein")

_F_RX = re.compile(r"^F[lL]\s*[.:]?\s*([0-9][0-9\s.]*,[0-9]+|[0-9]+)\s*m", re.I)
_U_CM_RX = re.compile(r"U\s*[:=]?\s*([0-9][0-9\s.]*,?[0-9]*)\s*cm", re.I)
_U_M_RX = re.compile(r"U\s*[:=]?\s*([0-9]+,[0-9]+)\s*m\b", re.I)


def _num(s):
    try:
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
                    spans.append({"text": txt, "cx": cx, "cy": cy})
    out = []
    for s in spans:
        mf = _F_RX.search(s["text"])
        if not mf:
            continue
        f = _num(mf.group(1))
        if not f or f < 0.5 or f > 500:
            continue
        u, best_dy = None, 1e9
        for s2 in spans:
            dy = s2["cy"] - s["cy"]
            if abs(s2["cx"] - s["cx"]) > 40 or not (0 < dy <= 30) or dy >= best_dy:
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
        name, best = None, 1e9
        for s2 in spans:
            if s2 is s or not re.match(r"^[A-Za-zÄÖÜäöüß]", s2["text"]):
                continue
            dy = s["cy"] - s2["cy"]
            if 0 < dy < 32 and abs(s2["cx"] - s["cx"]) < 80 and dy < best:
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
                d = abs(s["cy"] - s2["cy"]) + abs(s["cx"] - s2["cx"]) * 0.3
                if s2["cy"] < s["cy"] + 5 and d < best and d < 90:
                    best, name = d, s2["text"]
            out.append({"name": name or "?", "f_m2": f, "u_m": None,
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
               hatch_dilat_m=0.10, closing_m=0.14):
    """Schraffur-verankerte Wand-Maske: Schraffur + dunkle Kanten NAHE der Schraffur
    (Möbel haben keine Poché) + Öffnungs-Verschlüsse + Closing."""
    W, H = rst.W, rst.H
    hm = bytearray(W * H)
    for s in hatch_segs:
        rst.line(hm, s[0], s[1], s[2], s[3])
    r = max(1, int(hatch_dilat_m / rst.zm))
    dh = _dist_bfs(hm, W, H, r)
    hm_d = bytearray(1 if dh[i] <= r else 0 for i in range(W * H))

    grid = bytearray(hm)
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
            rst.line(grid, s[0], s[1], s[2], s[3])

    for o in (oeffnungen or []):
        # Verschluss als DÜNNER BALKEN quer über die Wandlücke. Orientierung per
        # BEIDE-ENDEN-TEST: der richtige Balken überbrückt die Lücke, d.h. BEIDE
        # Enden treffen Wand (die reine Dichte-Heuristik wählte bei der Bad-Tür
        # die falsche Richtung → Leck, gemessen). Score = min(Ende1, Ende2).
        cx, cy = o["cx"], o["cy"]
        b2 = ((o.get("breite_m") or 1.0) * rst.ptm * 0.9) / 2.0
        d2 = 0.20 * rst.ptm

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
        if score_h >= score_v:  # Balken entlang x (Wand verläuft horizontal)
            rst.rect(grid, cx - b2, cy - d2, cx + b2, cy + d2)
        else:                   # Balken entlang y
            rst.rect(grid, cx - d2, cy - b2, cx + d2, cy + b2)

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


def _taschen_adoption(grid, label, rst, stempel, AUSSEN):
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
                if 0 <= nl < n and nl != lab:
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
            if fl[ziel] >= soll[ziel]:
                continue        # Soll inzwischen erreicht (innerhalb der Welle)
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


def verifiziere_seite(page, ptm, box, dark_segs, hatch_segs, oeffnungen,
                      zelle_m=0.02, tol_f=0.06, tol_u=0.10, debug=None):
    """Komplette Raum-Verifikation einer Grundriss-Seite.
    Liefert (ergebnisse, stempel): ergebnisse = [{…, f_ist, u_ist, status}].
    debug: dict → bekommt grid/label/W/H/rst für Visualisierung."""
    stempel = raum_stempel(page, box)
    rst = _Raster(box, ptm, zelle_m)
    oe = [o for o in (oeffnungen or [])
          if box[0] <= o.get("cx", -1) <= box[1] and box[2] <= o.get("cy", -1) <= box[3]]
    grid = wand_maske(rst, dark_segs, hatch_segs, oe)
    label, ok_start, AUSSEN = _watershed(grid, rst, stempel)
    label = _taschen_adoption(grid, label, rst, stempel, AUSSEN)
    label = _f_ausgleich(grid, label, rst, stempel, AUSSEN)
    label = _glaetten(grid, label, rst, len(stempel), AUSSEN)
    label = _f_ausgleich(grid, label, rst, stempel, AUSSEN)   # F nach Glättung re-fixen
    if debug is not None:
        debug.update({"grid": grid, "label": label, "rst": rst, "AUSSEN": AUSSEN})
    masse = _loecher_fuellen_und_messen(grid, label, rst, stempel)
    out = []
    for idx, st in enumerate(stempel):
        if not ok_start[idx]:
            out.append(dict(st, status="kein_start", f_ist=None, u_ist=None))
            continue
        f_ist, u_ist = masse[idx]
        f_ok = abs(f_ist - st["f_m2"]) / st["f_m2"] <= tol_f
        u_ok = st.get("u_m") is None or abs(u_ist - st["u_m"]) / st["u_m"] <= tol_u
        status = "verifiziert" if (f_ok and u_ok) else ("u_daneben" if f_ok else "f_daneben")
        out.append(dict(st, status=status, f_ist=round(f_ist, 2), u_ist=round(u_ist, 2)))
    return out, stempel
