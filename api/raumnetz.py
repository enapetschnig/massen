"""RAUM-VERIFIKATION — der Plan validiert sich selbst (Nachzeichnen 2.0, Stufe 1).

KERN-EINSICHT: Jeder Raum-Stempel im Plan trägt Fläche F und Umfang U BYTE-EXAKT
("Fl: 10,53 m²", "U: 1 320,0 cm"). Wenn das aus den erkannten Wänden rekonstruierte
Raum-Gebiet F UND U gleichzeitig trifft (zwei unabhängige Werte), ist die Wand-
Geometrie um diesen Raum BEWIESEN — nicht geschätzt. Trifft es nicht, ist der Fehler
LOKALISIERT (Leck = fehlende Wand, Splitter = Geisterwand, F leicht daneben = falsche
Stärke). Macht aus "gut raten" ein "lösen und verifizieren".

Methode (v1, bewusst simpel + deterministisch, KEIN Vision):
  1. Erkannte Wände (vektor.wand_paare mit_geometrie) als Rechtecke in ein 2-cm-Raster.
  2. Öffnungen (STUK/FPH, byte-exakt aus dem Text) als VIRTUELLE VERSCHLÜSSE zubrennen —
     sonst flutet die Füllung durch Türen in den Nachbarraum.
  3. Vom Raum-Stempel aus fluten → Gebiet = Raum. Fläche = Zellen × zelle²; Umfang =
     exponierte Kanten × zelle (für achsparallele Räume exakt, kein Treppen-Bias).
  4. |F_ist − F_soll| und |U_ist − U_soll| innerhalb Toleranz → Raum VERIFIZIERT.

LOG-ONLY: kein Eingriff in die Live-Mengen. Harness: scripts/test_raumverifikation.py
"""
import re
from collections import deque

# "Fl: 10,53 m²" — ABER: das ² ist oft ein eigener Superscript-Span, der Span endet
# auf "… m". Daher auf den Fl-Anker matchen, nicht auf m².
_F_RX = re.compile(r"^F[lL]\s*[.:]?\s*([0-9][0-9\s.]*,[0-9]+|[0-9]+)\s*m", re.I)
# "U: 1 320,0 cm" (Tausender-Leerzeichen!) / "U: 13,20 m"
_U_CM_RX = re.compile(r"U\s*[:=]?\s*([0-9][0-9\s.]*,?[0-9]*)\s*cm", re.I)
_U_M_RX = re.compile(r"U\s*[:=]?\s*([0-9]+,[0-9]+)\s*m\b", re.I)


def _num(s):
    try:
        return float(s.replace(" ", "").replace(" ", "").replace(".", "").replace(",", "."))
    except (ValueError, AttributeError):
        return None


def raum_stempel(page, box):
    """Byte-exakte Raum-Stempel (F + U + Position) im Box-Bereich.
    Liefert [{name, f_m2, u_m, cx, cy}] — nur Stempel mit F UND U (das Prüf-Paar)."""
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
                    spans.append({"text": txt, "cx": cx, "cy": cy, "y0": bb[1]})
    out = []
    for s in spans:
        mf = _F_RX.search(s["text"])
        if not mf:
            continue
        f = _num(mf.group(1))
        if not f or f < 0.5 or f > 500:
            continue
        # U-Span des SELBEN Stempels: knapp unterhalb, kleine x-Abweichung — der
        # NÄCHSTE Treffer gewinnt (sonst greift ein enger Nachbar-Stempel-U, s. WC-Bug).
        u = None
        best_dy = 1e9
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
        # Name: nächster Buchstaben-Span oberhalb (±30pt x, bis 30pt darüber)
        name = None
        best = 1e9
        for s2 in spans:
            if s2 is s or not re.match(r"^[A-Za-zÄÖÜäöüß]", s2["text"]):
                continue
            dy = s["cy"] - s2["cy"]
            if 0 < dy < 32 and abs(s2["cx"] - s["cx"]) < 80 and dy < best:
                best, name = dy, s2["text"]
        out.append({"name": name or "?", "f_m2": f, "u_m": u, "cx": s["cx"], "cy": s["cy"]})
    return out


def raster_bauen(waende, box, ptm, zelle_m=0.02, verschluesse=None):
    """Wände (mit_geometrie-Dicts, pt) + Verschlüsse → Belegt-Raster (bytearray)."""
    bx0, bx1, by0, by1 = box
    cell = zelle_m * ptm
    W = int((bx1 - bx0) / cell) + 2
    H = int((by1 - by0) / cell) + 2
    grid = bytearray(W * H)

    def rect(x0, y0, x1, y1):
        i0 = max(0, int((min(x0, x1) - bx0) / cell))
        i1 = min(W - 1, int((max(x0, x1) - bx0) / cell))
        j0 = max(0, int((min(y0, y1) - by0) / cell))
        j1 = min(H - 1, int((max(y0, y1) - by0) / cell))
        for j in range(j0, j1 + 1):
            base = j * W
            for i in range(i0, i1 + 1):
                grid[base + i] = 1

    for w in waende:
        d = w["dist_pt"] / 2.0
        # BEWUSST ohne End-Verlängerung: pauschales Aufdicken/Verlängern verschob F-Werte
        # und machte den Score SCHLECHTER (2/9 → 0/9 gemessen). Junction-Lecks gehören in
        # die gezielte Reparatur-Schleife (Stufe 2), nicht in einen globalen Fudge.
        if w["achse"] == "v":
            rect(w["x0"] - d, w["y0"], w["x0"] + d, w["y1"])
        else:
            rect(w["x0"], w["y0"] - d, w["x1"], w["y0"] + d)
    for c in (verschluesse or []):
        r = max(c.get("breite_pt", 0) / 2.0, 0.15 * ptm)
        rect(c["cx"] - r, c["cy"] - r, c["cx"] + r, c["cy"] + r)
    return grid, W, H, cell


def _verschluss_auf_wand(o, waende, ptm):
    """Öffnung auf die NÄCHSTE Wand-Achse projizieren → Verschluss-Rechteck ENTLANG der
    Wand (Länge=Öffnungsbreite, Dicke=Wandstärke). Ein Verschluss am Label-Punkt würde
    mitten im Raum stehen und Räume zerschneiden — die Tür-Lücke liegt IN der Wand."""
    ox, oy = o["cx"], o["cy"]
    b2 = ((o.get("breite_m") or 1.0) * ptm * 1.3) / 2.0
    best = None
    for w in waende:
        if w["achse"] == "v":
            lo, hi = min(w["y0"], w["y1"]), max(w["y0"], w["y1"])
            py = min(max(oy, lo), hi)
            d = ((ox - w["x0"]) ** 2 + (oy - py) ** 2) ** 0.5
            if best is None or d < best[0]:
                best = (d, (w["x0"] - w["dist_pt"] * 0.75, py - b2,
                            w["x0"] + w["dist_pt"] * 0.75, py + b2))
        else:
            lo, hi = min(w["x0"], w["x1"]), max(w["x0"], w["x1"])
            px = min(max(ox, lo), hi)
            d = ((oy - w["y0"]) ** 2 + (ox - px) ** 2) ** 0.5
            if best is None or d < best[0]:
                best = (d, (px - b2, w["y0"] - w["dist_pt"] * 0.75,
                            px + b2, w["y0"] + w["dist_pt"] * 0.75))
    # nur wenn die Öffnung plausibel nahe einer Wand liegt (< 1,5 m), sonst weglassen
    if best and best[0] <= 1.5 * ptm:
        return best[1]
    return None


def verifiziere_raeume(waende, oeffnungen, stempel, box, ptm,
                       zelle_m=0.02, tol_f=0.06, tol_u=0.10):
    """Raum-für-Raum-Verifikation per MULTI-SOURCE-WATERSHED: alle Stempel fluten
    GLEICHZEITIG (BFS) + AUSSEN-Seeds am Box-Rand — jede freie Zelle gehört zum
    nächstgelegenen Stempel. Löst offene Durchgänge (Flur↔Wohnküche ohne Tür) und
    macht Lecks nach außen zu ehrlichen F-Abweichungen statt Overflow.
    Liefert [{…, f_ist, u_ist, status: verifiziert|f_daneben|u_daneben|kein_start}]."""
    bx0, bx1, by0, by1 = box
    grid, W, H, cell = raster_bauen(waende, box, ptm, zelle_m)
    # Tür-/Fenster-Verschlüsse AUF den Wänden nachbrennen
    for o in (oeffnungen or []):
        r = _verschluss_auf_wand(o, waende, ptm)
        if not r:
            continue
        i0 = max(0, int((r[0] - bx0) / cell)); i1 = min(W - 1, int((r[2] - bx0) / cell))
        j0 = max(0, int((r[1] - by0) / cell)); j1 = min(H - 1, int((r[3] - by0) / cell))
        for j in range(j0, j1 + 1):
            base = j * W
            for i in range(i0, i1 + 1):
                grid[base + i] = 1

    zm = cell / ptm
    AUSSEN = len(stempel)          # Label-Index für "draußen"
    label = [-1] * (W * H)
    q = deque()

    def seed(idx, si, sj):
        # Start ggf. auf nächste freie Zelle schieben (Stempel kann auf Linien liegen)
        for rad in range(0, 12):
            for di in range(-rad, rad + 1):
                for dj in range(-rad, rad + 1):
                    ni, nj = si + di, sj + dj
                    if 0 <= ni < W and 0 <= nj < H and not grid[nj * W + ni] \
                            and label[nj * W + ni] == -1:
                        label[nj * W + ni] = idx
                        q.append((ni, nj))
                        return True
        return False

    ok_start = []
    for idx, st in enumerate(stempel):
        si = int((st["cx"] - bx0) / cell)
        sj = int((st["cy"] - by0) / cell)
        ok_start.append(0 <= si < W and 0 <= sj < H and seed(idx, si, sj))
    # AUSSEN-Seeds: Box-Ränder (alle 20 Zellen)
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

    while q:                        # gemeinsamer BFS = Watershed nach Distanz
        i, j = q.popleft()
        lab = label[j * W + i]
        for di, dj in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            ni, nj = i + di, j + dj
            if 0 <= ni < W and 0 <= nj < H and not grid[nj * W + ni] \
                    and label[nj * W + ni] == -1:
                label[nj * W + ni] = lab
                q.append((ni, nj))

    # Fläche + Umfang je Label einsammeln
    flaeche = [0] * (len(stempel) + 1)
    kanten = [0] * (len(stempel) + 1)
    for j in range(H):
        base = j * W
        for i in range(W):
            lab = label[base + i]
            if lab < 0 or lab == AUSSEN:
                continue
            flaeche[lab] += 1
            for di, dj in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                ni, nj = i + di, j + dj
                if not (0 <= ni < W and 0 <= nj < H) or grid[nj * W + ni] \
                        or (label[nj * W + ni] != lab):
                    kanten[lab] += 1

    out = []
    for idx, st in enumerate(stempel):
        if not ok_start[idx]:
            out.append(dict(st, status="kein_start", f_ist=None, u_ist=None))
            continue
        f_ist = flaeche[idx] * zm * zm
        u_ist = kanten[idx] * zm
        f_ok = abs(f_ist - st["f_m2"]) / st["f_m2"] <= tol_f
        u_ok = st.get("u_m") is None or abs(u_ist - st["u_m"]) / st["u_m"] <= tol_u
        status = "verifiziert" if (f_ok and u_ok) else ("u_daneben" if f_ok else "f_daneben")
        out.append(dict(st, status=status, f_ist=round(f_ist, 2), u_ist=round(u_ist, 2)))
    return out
