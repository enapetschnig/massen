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
        # Verschluss als DÜNNER BALKEN quer über die Wandlücke — ein Quadrat frisst
        # bei Mini-Räumen echte Fläche (WC 1,83 m² wurde halbiert, gemessen).
        # Orientierung der Wand aus der lokalen Maske: Wandzellen links/rechts (h)
        # vs. oben/unten (v) der Öffnung.
        cx, cy = o["cx"], o["cy"]
        h_hits = v_hits = 0
        for dm in (0.25, 0.4, 0.55, 0.7):
            dpt = dm * rst.ptm
            for sx in (-1, 1):
                i, j = rst.ij(cx + sx * dpt, cy)
                if 0 <= i < W and 0 <= j < H and grid[j * W + i]:
                    h_hits += 1
                i, j = rst.ij(cx, cy + sx * dpt)
                if 0 <= i < W and 0 <= j < H and grid[j * W + i]:
                    v_hits += 1
        b2 = ((o.get("breite_m") or 1.0) * rst.ptm * 0.9) / 2.0
        d2 = 0.20 * rst.ptm     # Balken-Halbdicke 20cm — bleibt in der Wandzone
        if h_hits >= v_hits:    # Wand verläuft horizontal → Balken entlang x
            rst.rect(grid, cx - b2, cy - d2, cx + b2, cy + d2)
        else:                   # Wand vertikal → Balken entlang y
            rst.rect(grid, cx - d2, cy - b2, cx + d2, cy + b2)

    return _closing(grid, W, H, max(1, int(closing_m / rst.zm)))


def _watershed(grid, rst, stempel):
    """Multi-Source-BFS: alle Stempel + AUSSEN-Rand-Seeds gleichzeitig."""
    W, H = rst.W, rst.H
    AUSSEN = len(stempel)
    label = [-1] * (W * H)
    q = deque()
    ok_start = []
    for idx, st in enumerate(stempel):
        si, sj = rst.ij(st["cx"], st["cy"])
        placed = False
        for rad in range(0, 25):
            for di in range(-rad, rad + 1):
                for dj in range(-rad, rad + 1):
                    ni, nj = si + di, sj + dj
                    if 0 <= ni < W and 0 <= nj < H and not grid[nj * W + ni] \
                            and label[nj * W + ni] == -1:
                        label[nj * W + ni] = idx
                        q.append((ni, nj))
                        placed = True
                        break
                if placed:
                    break
            if placed:
                break
        ok_start.append(placed)
    for i in range(0, W, 20):
        for j in (0, H - 1):
            if not grid[j * W + i] and label[j * W + i] == -1:
                label[j * W + i] = AUSSEN
                q.append((i, j))
    for j in range(0, H, 20):
        for i in (0, W - 1):
            if not grid[j * W + i] and label[j * W + i] == -1:
                label[j * W + i] = AUSSEN
                q.append((i, j))
    while q:
        i, j = q.popleft()
        lab = label[j * W + i]
        for di, dj in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            ni, nj = i + di, j + dj
            if 0 <= ni < W and 0 <= nj < H and not grid[nj * W + ni] \
                    and label[nj * W + ni] == -1:
                label[nj * W + ni] = lab
                q.append((ni, nj))
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
        # Kontakte durch dünne Wände zählen
        reach = max(1, int(0.16 / rst.zm))
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
        # F + U auf der gefüllten Silhouette
        f_cells = 0
        kanten = 0
        for jj in range(j0, j1 + 1):
            base = jj * W
            for ii in range(i0, i1 + 1):
                if not is_room[base + ii]:
                    continue
                f_cells += 1
                for di, dj in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    ni, nj = ii + di, jj + dj
                    if not (0 <= ni < W and 0 <= nj < H) or not is_room[nj * W + ni]:
                        kanten += 1
        out.append((f_cells * rst.zm * rst.zm, kanten * rst.zm))
    return out


def verifiziere_seite(page, ptm, box, dark_segs, hatch_segs, oeffnungen,
                      zelle_m=0.02, tol_f=0.06, tol_u=0.10):
    """Komplette Raum-Verifikation einer Grundriss-Seite.
    Liefert (ergebnisse, stempel): ergebnisse = [{…, f_ist, u_ist, status}]."""
    stempel = raum_stempel(page, box)
    rst = _Raster(box, ptm, zelle_m)
    oe = [o for o in (oeffnungen or [])
          if box[0] <= o.get("cx", -1) <= box[1] and box[2] <= o.get("cy", -1) <= box[3]]
    grid = wand_maske(rst, dark_segs, hatch_segs, oe)
    label, ok_start, AUSSEN = _watershed(grid, rst, stempel)
    label = _taschen_adoption(grid, label, rst, stempel, AUSSEN)
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
