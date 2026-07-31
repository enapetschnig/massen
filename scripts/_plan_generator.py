"""Synthetische Baupläne mit BYTE-EXAKTER Wahrheit erzeugen.

Warum: "funktioniert für alle Pläne" scheitert nicht an der ANZAHL der
Testpläne, sondern an ihrer VARIANZ. Vier echte Grundrisse decken vier
Maßstäbe, vier Stempelformate, eine Seitendrehung ab — nämlich je genau eine.
Was passiert bei 1:200? Bei einem Stempel ohne Umfang? Bei einer gedrehten
Seite? Bei sechzig Räumen?

Hier wird der Plan GEBAUT, darum ist jede Zahl bekannt: Raumnamen, Flächen und
Umfänge stehen fest, bevor die Pipeline sie liest. Das ist dieselbe Methode,
mit der schon der Scan-Korpus hergestellt wurde — und die dort ein Verfahren
widerlegt hat, das an echten Plänen gut aussah.

Ein erzeugter Plan trägt alles, was die Pipeline braucht:
  * Maßstab-Label ("1:50") — Kreuzcheck der Kalibrierung
  * eine echte Maßkette (cm-Zahlen an proportionalen Positionen)
  * Wände als gefüllte Rechtecke (Außenhülle + Trennwände)
  * Raumstempel in wählbarem Format
"""
import math
import os

import fitz

# ÖNORM-Blattformate in pt (1 pt = 1/72 Zoll)
A1 = (2384.0, 1684.0)
A0 = (3370.0, 2384.0)


def _fmt(x, komma=True, nk=2):
    s = f"{x:.{nk}f}"
    return s.replace(".", ",") if komma else s


class PlanBauer:
    """Baut einen Grundriss aus Rechteck-Räumen und kennt dessen Wahrheit."""

    def __init__(self, massstab=50, blatt=A1, wand_cm=25.0, aussen_cm=38.0,
                 rotation=0):
        self.massstab = massstab
        self.blatt = blatt
        self.ptm = 2835.0 / massstab      # pt je Meter (1 m = 100cm/Maßstab in cm)
        self.wand_m = wand_cm / 100.0
        self.aussen_m = aussen_cm / 100.0
        self.rotation = rotation
        self.raeume = []                  # (name, x0, y0, b, h) in METERN
        self.belag = {}

    def raum(self, name, x0, y0, b, h, belag="Parkett"):
        """Raum in Metern, Ursprung links oben. Maße sind LICHTE Innenmaße."""
        self.raeume.append((name, float(x0), float(y0), float(b), float(h)))
        self.belag[name] = belag
        return self

    # ── Wahrheit ────────────────────────────────────────────────────────
    def wahrheit(self):
        """-> [{name, f_m2, u_m}] — exakt, per Konstruktion."""
        return [{"name": n, "f_m2": round(b * h, 2), "u_m": round(2 * (b + h), 2)}
                for (n, _x, _y, b, h) in self.raeume]

    # ── Zeichnen ────────────────────────────────────────────────────────
    def _pt(self, xm, ym):
        return (self.rand + xm * self.ptm, self.rand + ym * self.ptm)

    def schreibe(self, pfad, stempel_format="fl", mit_umfang=True,
                 komma=True, kette=True):
        """stempel_format: 'fl' → "Fl: 12,34 m²"
                           'bf' → "BF:" + Tab-Spalte (Polierplan-Encoding)
                           'nackt' → "12,34 m" + separater "²"-Span (Büro)
        """
        W, H = self.blatt
        doc = fitz.open()
        pg = doc.new_page(width=W, height=H)
        self.rand = 0.10 * min(W, H)
        gr = (0.35, 0.35, 0.35)

        # Außenhülle: ein Rechteck um alle Räume, Wandstärke aussen_m
        xs0 = min(r[1] for r in self.raeume)
        ys0 = min(r[2] for r in self.raeume)
        xs1 = max(r[1] + r[3] for r in self.raeume)
        ys1 = max(r[2] + r[4] for r in self.raeume)
        a = self.aussen_m
        p0 = self._pt(xs0 - a, ys0 - a)
        p1 = self._pt(xs1 + a, ys1 + a)
        # vier Balken statt Rahmen — die Pipeline sucht gefüllte Wandflächen
        d = a * self.ptm
        for rect in (
            fitz.Rect(p0[0], p0[1], p1[0], p0[1] + d),          # oben
            fitz.Rect(p0[0], p1[1] - d, p1[0], p1[1]),          # unten
            fitz.Rect(p0[0], p0[1], p0[0] + d, p1[1]),          # links
            fitz.Rect(p1[0] - d, p0[1], p1[0], p1[1]),          # rechts
        ):
            pg.draw_rect(rect, color=gr, fill=gr, width=0)

        # Trennwände: zwischen benachbarten Räumen einen Balken setzen
        dw = self.wand_m * self.ptm
        for (_n, x0, y0, b, h) in self.raeume:
            q0 = self._pt(x0, y0)
            q1 = self._pt(x0 + b, y0 + h)
            for rect in (
                fitz.Rect(q0[0] - dw, q0[1] - dw, q1[0] + dw, q0[1]),
                fitz.Rect(q0[0] - dw, q1[1], q1[0] + dw, q1[1] + dw),
                fitz.Rect(q0[0] - dw, q0[1] - dw, q0[0], q1[1] + dw),
                fitz.Rect(q1[0], q0[1] - dw, q1[0] + dw, q1[1] + dw),
            ):
                pg.draw_rect(rect, color=gr, fill=gr, width=0)

        # Maßstab-Label
        pg.insert_text((self.rand, self.rand * 0.5), f"M 1:{self.massstab}",
                       fontsize=11)

        # MASSKETTE: cm-Zahlen an proportionalen Positionen. Genau daran
        # kalibriert vektor.kalibriere() den pt/m-Faktor.
        if kette:
            y = self.rand + (ys1 + a + 0.9) * self.ptm
            xk = xs0 - a
            for (_n, x0, _y0, b, _h) in sorted(self.raeume,
                                               key=lambda r: (r[2], r[1]))[:6]:
                if x0 < xk - 0.01:
                    continue
                mitte = self.rand + (xk + (x0 + b - xk) / 2.0) * self.ptm
                pg.insert_text((mitte, y), f"{round((x0 + b - xk) * 100):d}",
                               fontsize=8)
                xk = x0 + b

        # Raumstempel
        for (n, x0, y0, b, h) in self.raeume:
            cx = self.rand + (x0 + b / 2.0) * self.ptm
            cy = self.rand + (y0 + h / 2.0) * self.ptm
            f, u = b * h, 2 * (b + h)
            zeilen = [n, self.belag.get(n, "Parkett")]
            pg.insert_text((cx - 26, cy - 13), zeilen[0], fontsize=9)
            pg.insert_text((cx - 26, cy - 2), zeilen[1], fontsize=8)
            if stempel_format == "fl":
                pg.insert_text((cx - 26, cy + 10),
                               f"Fl: {_fmt(f, komma)} m²", fontsize=8)
            elif stempel_format == "bf":
                pg.insert_text((cx - 26, cy + 10), "BF:", fontsize=8)
                pg.insert_text((cx - 26 + 24, cy + 10),
                               f"{_fmt(f, komma)} m²", fontsize=8)
            else:   # nackt: Zahl + separater Hochstell-Span
                t = f"{_fmt(f, komma)} m"
                pg.insert_text((cx - 26, cy + 10), t, fontsize=8)
                pg.insert_text((cx - 26 + 4.4 * len(t), cy + 8), "²", fontsize=6)
            if mit_umfang:
                pg.insert_text((cx - 26, cy + 21),
                               f"U: {_fmt(u, komma)} m", fontsize=8)
        if self.rotation:
            pg.set_rotation(self.rotation)
        doc.save(pfad)
        doc.close()
        return pfad


def sanierungsplan(pfad, massstab=50, blatt=A1, n_bestand=14, n_abbruch=9):
    """UMBAU-/SANIERUNGSPLAN mit Farb-Legende — der Plantyp, den ein
    Baubetrieb am häufigsten auf dem Tisch hat und den unser Korpus nicht
    enthielt.

    Aufgebaut wie ein echter Umbauplan:
      * Legende mit drei Farbfeldern + Wörtern (Neubau/Bestand/Abbruch)
      * Bauteile in genau diesen Farben GEZEICHNET, nicht nur beschriftet
      * die Wörter stehen zusätzlich am Objekt (so unterscheidet das
        Präzisions-Gate echte Bauteil-Labels von Plankopf-Boilerplate)

    Wahrheit per Konstruktion: welche Farbe welche Bedeutung trägt und wie
    viele Bauteile es je Klasse gibt.
    """
    W, H = blatt
    ptm = 2835.0 / massstab
    doc = fitz.open()
    pg = doc.new_page(width=W, height=H)
    rand = 0.10 * min(W, H)
    # Legende: Wort + Farbfeld direkt rechts daneben (Swatch-Suche: max_dx 180)
    farben = {"Neubau": (1.0, 0.0, 0.0),        # rot  = neu
              "Bestand": (0.0, 0.0, 0.0),       # schwarz = Bestand
              "Abbruch": (1.0, 1.0, 0.0)}       # gelb = Abbruch
    ly = rand * 0.45
    pg.insert_text((rand, ly - 14), f"M 1:{massstab}", fontsize=11)
    for i, (wort, rgb) in enumerate(farben.items()):
        y = ly + i * 15
        pg.insert_text((rand, y), wort, fontsize=9)
        pg.draw_rect(fitz.Rect(rand + 62, y - 8, rand + 90, y - 1),
                     color=rgb, fill=rgb, width=0)
    # Bauteile in den Legende-Farben, jedes mit seinem Wort daneben
    def _balken(x_m, y_m, b_m, h_m, rgb, wort):
        r = fitz.Rect(rand + x_m * ptm, rand + 60 + y_m * ptm,
                      rand + (x_m + b_m) * ptm, rand + 60 + (y_m + h_m) * ptm)
        pg.draw_rect(r, color=rgb, fill=rgb, width=0)
        pg.insert_text((r.x0, r.y1 + 8), wort, fontsize=7)
    for i in range(n_bestand):
        _balken(1.0 + (i % 7) * 2.2, 1.0 + (i // 7) * 1.6, 1.8, 0.30,
                farben["Bestand"], "Bestand")
    for i in range(n_abbruch):
        _balken(1.0 + (i % 5) * 2.2, 5.0 + (i // 5) * 1.6, 1.8, 0.30,
                farben["Abbruch"], "Abbruch")
    for i in range(6):
        _balken(1.0 + (i % 4) * 2.2, 9.0 + (i // 4) * 1.6, 1.8, 0.30,
                farben["Neubau"], "Neubau")
    doc.save(pfad)
    doc.close()
    return {"pfad": pfad, "farben": farben,
            "n": {"bestand": n_bestand, "abbruch": n_abbruch, "neubau": 6}}


def zimmerreihe(bauer, n, b=3.6, h=4.2, pro_reihe=4, namen=None):
    """n Räume in einem Raster — für Stress- und Skalenvarianten."""
    for i in range(n):
        sp, ze = i % pro_reihe, i // pro_reihe
        nm = (namen[i] if namen and i < len(namen) else f"Zimmer {i+1}")
        bauer.raum(nm, 1.0 + sp * (b + 0.25), 1.0 + ze * (h + 0.25), b, h)
    return bauer
