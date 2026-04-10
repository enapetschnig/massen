"""
Parser Agent - Hochpräzise PDF-Erkennung für österreichische Baupläne.

VISION-FIRST-ARCHITEKTUR (wie ein erfahrener Bautechniker):

  Pass 1 - ÜBERBLICK: Claude Vision analysiert den gesamten Plan als Bild.
           Erkennt Maßstab, Geschoss, Raumaufteilung, grobe Struktur.

  Pass 2 - DETAILANALYSE: Für jeden erkannten Raum wird der Bereich
           ausgeschnitten und hochauflösend an Claude Vision gesendet.
           Präzise Extraktion aller Maße, Fenster, Türen pro Raum.

  Pass 3 - TEXTVERIFIKATION: pdfplumber + PyMuPDF extrahieren allen
           maschinenlesbaren Text. Dieser wird mit den Vision-Ergebnissen
           abgeglichen und ergänzt → Maximalgenauigkeit.

Warum Vision-First?
- Echte Baupläne sind CAD-Exports mit Text in Vektorgrafiken
- Maße stehen rotiert an Wänden (90° oder beliebig)
- Räume sind durch Linien definiert, nicht durch Text
- Ein Mensch "liest" den Plan auch visuell, nicht als Textdatei
"""

from __future__ import annotations

import base64
import json
import logging
import math
import os
import re
from typing import Any, Optional

import anthropic
from agents import get_anthropic_api_key as _get_api_key

logger = logging.getLogger(__name__)

# Opus für maximale Präzision bei der visuellen Analyse
VISION_MODEL = "claude-sonnet-4-20250514"
TEXT_MODEL = "claude-sonnet-4-20250514"

# ---------------------------------------------------------------------------
# Hilfsfunktionen
# ---------------------------------------------------------------------------

def _parse_json_response(text: str) -> dict:
    """Robustes JSON-Parsing mit mehreren Fallback-Strategien."""
    # Direkt
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # Markdown-Block
    match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass
    # Erstes { bis letztes }
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(text[start:end + 1])
        except json.JSONDecodeError:
            pass
    logger.error("JSON-Parsing fehlgeschlagen: %s", text[:300])
    return {}


def _pdf_page_to_png(pdf_path: str, page_idx: int = 0, dpi: int = 300) -> bytes:
    """Rendert eine PDF-Seite als hochauflösendes PNG."""
    import fitz
    doc = fitz.open(pdf_path)
    if page_idx >= len(doc):
        doc.close()
        return b""
    page = doc[page_idx]
    mat = fitz.Matrix(dpi / 72, dpi / 72)
    pix = page.get_pixmap(matrix=mat)
    img_bytes = pix.tobytes("png")
    doc.close()
    return img_bytes


def _pdf_page_to_png_region(pdf_path: str, page_idx: int, rect: tuple,
                            dpi: int = 400) -> bytes:
    """Rendert einen Ausschnitt einer PDF-Seite als hochauflösendes PNG."""
    import fitz
    doc = fitz.open(pdf_path)
    if page_idx >= len(doc):
        doc.close()
        return b""
    page = doc[page_idx]
    # rect = (x0, y0, x1, y1) in PDF-Punkten
    clip = fitz.Rect(rect[0], rect[1], rect[2], rect[3])
    # Etwas Rand hinzufügen
    clip.x0 = max(0, clip.x0 - 20)
    clip.y0 = max(0, clip.y0 - 20)
    clip.x1 = min(page.rect.width, clip.x1 + 20)
    clip.y1 = min(page.rect.height, clip.y1 + 20)
    mat = fitz.Matrix(dpi / 72, dpi / 72)
    pix = page.get_pixmap(matrix=mat, clip=clip)
    img_bytes = pix.tobytes("png")
    doc.close()
    return img_bytes


def _get_page_count(pdf_path: str) -> int:
    """Gibt die Seitenanzahl des PDFs zurück."""
    import fitz
    doc = fitz.open(pdf_path)
    count = len(doc)
    doc.close()
    return count


# ---------------------------------------------------------------------------
# Pass 1: ÜBERBLICK - Claude Vision analysiert den ganzen Plan
# ---------------------------------------------------------------------------

PASS1_SYSTEM = """Du bist der beste Bautechniker Österreichs mit 30 Jahren Erfahrung im Lesen von Bauplänen.

Du siehst einen österreichischen Bauplan als Bild. Analysiere ihn wie ein Profi:

SCHRITT 1 - PLAN-METADATEN:
- Maßstab (z.B. 1:100, 1:50) - suche nach "M 1:..." oder im Plankopf
- Geschoss/Ebene (EG, OG1, KG, DG, etc.)
- Planungsbüro (wenn erkennbar im Stempel)
- Nord-Pfeil Richtung

SCHRITT 2 - RÄUME ERKENNEN:
Für JEDEN Raum den du siehst:
- Exakter Name (z.B. "Wohnküche", "Schlafzimmer", "Bad/WC")
- Bodenbelag (Parkett, Fliesen, Estrich, etc.)
- Fläche in m² (steht meist im Raum)
- Umfang in m (oft als "U: XX,XX m")
- Raumhöhe (oft als "H: X,XX m")
- Ungefähre Position im Plan (oben-links, mitte, etc.)

SCHRITT 3 - FENSTER ERKENNEN:
Österreichische Fensternotation: FE_[Nr] / RPH [Wert] / FPH [Wert] / AL[B] / AL[H] / RB[B] / RB[H]
- FE_[Nr]: Fensternummer
- RPH: Rohbauparapethöhe in mm
- FPH: Fertigparapethöhe in mm
- AL: Architekturlichte (Fertigmaß) Breite × Höhe in mm
- RB: Rohbauöffnung Breite × Höhe in mm
- ACHTUNG: Manchmal stehen die Werte in cm statt mm!
- Ordne jedes Fenster einem Raum zu

SCHRITT 4 - TÜREN ERKENNEN:
- T[Nr] / [Breite]×[Höhe] / [Typ]
- Breite und Höhe in mm oder cm
- Ordne jede Tür den angrenzenden Räumen zu

SCHRITT 5 - MAẞE UND WANDSTÄRKEN:
- Wandstärken (typisch: 25cm Außenwand, 12-17.5cm Innenwand)
- Einzelne Maßketten an den Wänden
- Lichte Raummaße

WICHTIG:
- Lies JEDEN einzelnen Text im Plan, auch kleine Beschriftungen
- Fensternotationen stehen oft mehrzeilig oder rotiert - lies alles zusammen
- Bei Unsicherheit: trotzdem angeben mit niedrigerer Konfidenz
- KEINE Informationen erfinden! Nur was du tatsächlich lesen kannst

Antworte NUR mit validem JSON (kein Markdown):
{
  "massstab": "1:100",
  "geschoss": "EG",
  "planbuero": "Architekt XY" oder null,
  "raeume": [
    {
      "name": "Wohnküche",
      "bodenbelag": "Parkett",
      "flaeche_m2": 26.37,
      "umfang_m": 20.66,
      "hoehe_m": 2.42,
      "position_beschreibung": "mitte-links",
      "position_rect_pct": [10, 30, 45, 65],
      "konfidenz": 0.95
    }
  ],
  "fenster": [
    {
      "bezeichnung": "FE_31",
      "raum": "Wohnküche",
      "rph_mm": -240,
      "fph_mm": 0,
      "al_breite_mm": 1200,
      "al_hoehe_mm": 2310,
      "rb_breite_mm": 1300,
      "rb_hoehe_mm": 2880,
      "konfidenz": 0.90,
      "notiz": "Werte aus mehrzeiliger Beschriftung zusammengesetzt"
    }
  ],
  "tueren": [
    {
      "bezeichnung": "T1",
      "raum": "Wohnküche",
      "breite_mm": 900,
      "hoehe_mm": 2100,
      "typ": "Drehflügel",
      "konfidenz": 0.85
    }
  ],
  "wandstaerken_mm": [250, 175, 125],
  "zusaetzliche_texte": ["Planstempel: ...", "Maßkette: 3.50 + 2.10 + 4.80"],
  "warnungen": [],
  "gesamt_konfidenz": 0.87
}"""


async def _pass1_overview(pdf_path: str, page_idx: int = 0) -> dict:
    """Pass 1: Gesamtüberblick des Plans via Claude Vision."""
    logger.info("PASS 1: Überblick-Analyse (Seite %d)", page_idx)

    img_bytes = _pdf_page_to_png(pdf_path, page_idx, dpi=200)
    if not img_bytes:
        return {"warnungen": ["Seite konnte nicht gerendert werden"], "gesamt_konfidenz": 0}

    img_b64 = base64.b64encode(img_bytes).decode("utf-8")
    img_size_mb = len(img_bytes) / (1024 * 1024)
    logger.info("  Bild: %.1f MB, sende an Claude Vision", img_size_mb)

    client = anthropic.AsyncAnthropic(api_key=_get_api_key())

    response = await client.messages.create(
        model=VISION_MODEL,
        max_tokens=8192,
        system=PASS1_SYSTEM,
        messages=[{
            "role": "user",
            "content": [
                {
                    "type": "image",
                    "source": {"type": "base64", "media_type": "image/png", "data": img_b64},
                },
                {
                    "type": "text",
                    "text": "Analysiere diesen österreichischen Bauplan vollständig. "
                            "Extrahiere ALLE Räume, Fenster, Türen und Maße die du erkennen kannst. "
                            "Sei so gründlich wie möglich - jede Information zählt für die Massenermittlung.",
                },
            ],
        }],
    )

    raw = response.content[0].text if response.content else "{}"
    result = _parse_json_response(raw)

    if not result:
        result = {"warnungen": ["Vision-Analyse konnte nicht geparst werden"], "gesamt_konfidenz": 0}

    result.setdefault("raeume", [])
    result.setdefault("fenster", [])
    result.setdefault("tueren", [])
    result.setdefault("warnungen", [])
    result.setdefault("gesamt_konfidenz", 0)

    logger.info("  Pass 1 Ergebnis: %d Räume, %d Fenster, %d Türen, Konfidenz: %s",
                len(result["raeume"]), len(result["fenster"]), len(result["tueren"]),
                result.get("gesamt_konfidenz"))

    return result


# ---------------------------------------------------------------------------
# Pass 2: DETAILANALYSE - Ausschnitte hochauflösend analysieren
# ---------------------------------------------------------------------------

PASS2_SYSTEM = """Du bist ein Detailexperte für österreichische Baupläne.

Du siehst einen AUSSCHNITT eines Bauplans - einen bestimmten Raum oder Bereich.
Der Überblick hat bereits folgende Information geliefert: {context}

Deine Aufgabe: PRÄZISE VERIFIKATION und ERGÄNZUNG.

1. Lies JEDEN Text in diesem Ausschnitt buchstabengenau ab
2. Prüfe ob die Überblick-Werte korrekt sind
3. Finde Details die im Überblick übersehen wurden:
   - Zusätzliche Fenster-Parameter (RPH, FPH, AL, RB)
   - Zusätzliche Maße
   - Wandstärken
   - Bodenbelag-Details
   - Installationshinweise

Antworte NUR mit validem JSON:
{
  "korrekturen": [
    {"feld": "flaeche_m2", "alter_wert": 26.37, "neuer_wert": 26.73, "grund": "Zahl genauer gelesen"}
  ],
  "ergaenzungen": {
    "zusaetzliche_masse": ["3.50 m (Wandlänge Nord)"],
    "zusaetzliche_fenster_details": {},
    "zusaetzliche_texte": []
  },
  "konfidenz": 0.92
}"""


async def _pass2_detail(pdf_path: str, page_idx: int, raum: dict, overview_context: str) -> dict:
    """Pass 2: Detailanalyse eines Raum-Ausschnitts."""
    # Wenn der Raum eine Position hat, schneide den Bereich aus
    rect_pct = raum.get("position_rect_pct")
    if not rect_pct or len(rect_pct) != 4:
        return {"korrekturen": [], "ergaenzungen": {}, "konfidenz": 0.5}

    import fitz
    doc = fitz.open(pdf_path)
    if page_idx >= len(doc):
        doc.close()
        return {"korrekturen": [], "ergaenzungen": {}, "konfidenz": 0.5}
    page = doc[page_idx]
    pw, ph = page.rect.width, page.rect.height
    doc.close()

    # Prozent → PDF-Punkte
    rect = (
        rect_pct[0] / 100 * pw,
        rect_pct[1] / 100 * ph,
        rect_pct[2] / 100 * pw,
        rect_pct[3] / 100 * ph,
    )

    img_bytes = _pdf_page_to_png_region(pdf_path, page_idx, rect, dpi=400)
    if not img_bytes:
        return {"korrekturen": [], "ergaenzungen": {}, "konfidenz": 0.5}

    img_b64 = base64.b64encode(img_bytes).decode("utf-8")

    system = PASS2_SYSTEM.replace("{context}", json.dumps(raum, ensure_ascii=False))

    client = anthropic.AsyncAnthropic(api_key=_get_api_key())

    response = await client.messages.create(
        model=VISION_MODEL,
        max_tokens=4096,
        system=system,
        messages=[{
            "role": "user",
            "content": [
                {
                    "type": "image",
                    "source": {"type": "base64", "media_type": "image/png", "data": img_b64},
                },
                {
                    "type": "text",
                    "text": f"Detailanalyse für Raum '{raum.get('name', '?')}'. "
                            "Lies jeden Text in diesem Ausschnitt präzise ab und korrigiere/ergänze die Überblick-Daten.",
                },
            ],
        }],
    )

    raw = response.content[0].text if response.content else "{}"
    result = _parse_json_response(raw)
    result.setdefault("korrekturen", [])
    result.setdefault("ergaenzungen", {})
    result.setdefault("konfidenz", 0.5)
    return result


# ---------------------------------------------------------------------------
# Pass 3: TEXTVERIFIKATION - maschinenlesbarer Text als Cross-Check
# ---------------------------------------------------------------------------

def _extract_machine_text(pdf_path: str) -> list[dict]:
    """Extrahiert allen maschinenlesbaren Text mit beiden Libraries."""
    all_text = []

    # pdfplumber
    try:
        import pdfplumber
        with pdfplumber.open(pdf_path) as pdf:
            for page_idx, page in enumerate(pdf.pages):
                words = page.extract_words(
                    x_tolerance=3, y_tolerance=3,
                    keep_blank_chars=False, use_text_flow=False,
                )
                for w in words:
                    all_text.append({
                        "text": w.get("text", ""),
                        "x0": float(w.get("x0", 0)),
                        "y0": float(w.get("top", 0)),
                        "x1": float(w.get("x1", 0)),
                        "y1": float(w.get("bottom", 0)),
                        "seite": page_idx,
                        "quelle": "pdfplumber",
                    })

                # Rotierter Text über chars
                for char in (page.chars or []):
                    matrix = char.get("matrix", (1, 0, 0, 1, 0, 0))
                    if matrix and len(matrix) >= 4:
                        if abs(matrix[1]) > 0.01 or abs(matrix[2]) > 0.01:
                            all_text.append({
                                "text": char.get("text", ""),
                                "x0": float(char.get("x0", 0)),
                                "y0": float(char.get("top", 0)),
                                "x1": float(char.get("x1", 0)),
                                "y1": float(char.get("bottom", 0)),
                                "seite": page_idx,
                                "rotiert": True,
                                "quelle": "pdfplumber_rotated",
                            })
    except Exception as e:
        logger.warning("pdfplumber Extraktion fehlgeschlagen: %s", e)

    # PyMuPDF als Ergänzung
    try:
        import fitz
        doc = fitz.open(pdf_path)
        for page_idx, page in enumerate(doc):
            text_dict = page.get_text("dict", flags=11)
            for block in text_dict.get("blocks", []):
                if block.get("type") != 0:
                    continue
                for line in block.get("lines", []):
                    for span in line.get("spans", []):
                        text = span.get("text", "").strip()
                        if not text:
                            continue
                        bbox = span.get("bbox", (0, 0, 0, 0))
                        # Nur hinzufügen wenn nicht schon von pdfplumber erfasst
                        is_new = True
                        for existing in all_text:
                            if (existing["seite"] == page_idx and
                                text in existing["text"] and
                                abs(bbox[0] - existing["x0"]) < 5):
                                is_new = False
                                break
                        if is_new:
                            all_text.append({
                                "text": text,
                                "x0": float(bbox[0]),
                                "y0": float(bbox[1]),
                                "x1": float(bbox[2]),
                                "y1": float(bbox[3]),
                                "seite": page_idx,
                                "quelle": "pymupdf",
                            })
        doc.close()
    except Exception as e:
        logger.warning("PyMuPDF Extraktion fehlgeschlagen: %s", e)

    return all_text


def _cross_check_with_text(vision_result: dict, machine_text: list[dict]) -> dict:
    """
    Vergleicht Vision-Ergebnisse mit maschinenlesbarem Text.
    Korrigiert Zahlendreher und ergänzt fehlende Daten.
    """
    corrections = []
    additions = []

    # Alle Zahlen aus dem maschinenlesbaren Text extrahieren
    text_numbers = {}
    for t in machine_text:
        # Flächen
        m = re.search(r"(\d+[.,]\d+)\s*m[²2]", t["text"])
        if m:
            val = float(m.group(1).replace(",", "."))
            text_numbers.setdefault("flaechen", []).append(val)

        # Umfang
        m = re.search(r"U\s*[:=]\s*(\d+[.,]\d+)", t["text"])
        if m:
            val = float(m.group(1).replace(",", "."))
            text_numbers.setdefault("umfaenge", []).append(val)

        # Höhe
        m = re.search(r"[RH]?H\s*[:=]\s*(\d+[.,]\d+)", t["text"])
        if m:
            val = float(m.group(1).replace(",", "."))
            text_numbers.setdefault("hoehen", []).append(val)

        # Fenster-Bezeichnungen
        m = re.search(r"FE[_\s-]?\d+", t["text"], re.IGNORECASE)
        if m:
            text_numbers.setdefault("fenster_codes", []).append(m.group())

        # Maßstab
        m = re.search(r"(?:M\s*)?1\s*:\s*(\d+)", t["text"])
        if m:
            text_numbers.setdefault("massstab", []).append(f"1:{m.group(1)}")

    # Flächen aus Vision mit Text vergleichen
    for raum in vision_result.get("raeume", []):
        vision_flaeche = raum.get("flaeche_m2")
        if vision_flaeche and "flaechen" in text_numbers:
            # Suche die nächste passende Fläche im Text
            closest = min(text_numbers["flaechen"],
                         key=lambda x: abs(x - vision_flaeche),
                         default=None)
            if closest and abs(closest - vision_flaeche) > 0.01 and abs(closest - vision_flaeche) < 5:
                corrections.append({
                    "raum": raum.get("name"),
                    "feld": "flaeche_m2",
                    "vision_wert": vision_flaeche,
                    "text_wert": closest,
                    "differenz": abs(closest - vision_flaeche),
                })
                # Text-Wert bevorzugen (maschinenlesbar = exakter)
                raum["flaeche_m2"] = closest
                raum["_korrigiert_durch_text"] = True

    # Maßstab-Verifikation
    if "massstab" in text_numbers and vision_result.get("massstab"):
        text_massstab = text_numbers["massstab"][0]
        if text_massstab != vision_result["massstab"]:
            corrections.append({
                "feld": "massstab",
                "vision_wert": vision_result["massstab"],
                "text_wert": text_massstab,
            })
            vision_result["massstab"] = text_massstab

    # Fehlende Fenster-Codes ergänzen
    vision_fenster_codes = {f.get("bezeichnung", "").upper() for f in vision_result.get("fenster", [])}
    for code in text_numbers.get("fenster_codes", []):
        if code.upper() not in vision_fenster_codes:
            additions.append(f"Fenstercode '{code}' im Text gefunden aber nicht in Vision")

    vision_result["_text_korrekturen"] = corrections
    vision_result["_text_ergaenzungen"] = additions

    return vision_result


# ---------------------------------------------------------------------------
# Hauptfunktion
# ---------------------------------------------------------------------------

async def run(kontext: dict, anweisung: str = "") -> dict:
    """
    Vision-First Parser mit 3-Pass-Architektur.

    Args:
        kontext: Dict mit 'pdf_path'.
        anweisung: Optionale Zusatzanweisung (z.B. Lernregeln).

    Returns:
        Strukturiertes Dict mit allen erkannten Plan-Elementen.
    """
    pdf_path = kontext.get("pdf_path", "")
    if not pdf_path or not os.path.exists(pdf_path):
        return {
            "massstab": None,
            "geschoss": None,
            "text_cluster": [],
            "raeume": [],
            "fenster": [],
            "tueren": [],
            "warnungen": [f"PDF nicht gefunden: {pdf_path}"],
            "gesamt_konfidenz": 0,
        }

    logger.info("========================================")
    logger.info("PARSER-AGENT: Vision-First 3-Pass-Pipeline")
    logger.info("PDF: %s", pdf_path)
    logger.info("========================================")

    warnungen = []
    num_pages = _get_page_count(pdf_path)
    logger.info("PDF hat %d Seite(n)", num_pages)

    all_raeume = []
    all_fenster = []
    all_tueren = []
    massstab = None
    geschoss = None

    # Für jede Seite die 3-Pass-Pipeline durchlaufen
    for page_idx in range(min(num_pages, 5)):  # Max 5 Seiten
        logger.info("--- Seite %d/%d ---", page_idx + 1, num_pages)

        # ═══════════════════════════════════════════
        # PASS 1: ÜBERBLICK via Claude Vision
        # ═══════════════════════════════════════════
        try:
            overview = await _pass1_overview(pdf_path, page_idx)
        except Exception as e:
            logger.error("Pass 1 fehlgeschlagen: %s", e)
            warnungen.append(f"Vision-Überblick Seite {page_idx + 1} fehlgeschlagen: {e}")
            # Fallback auf reinen Text
            overview = {"raeume": [], "fenster": [], "tueren": [], "gesamt_konfidenz": 0}

        if not massstab and overview.get("massstab"):
            massstab = overview["massstab"]
        if not geschoss and overview.get("geschoss"):
            geschoss = overview["geschoss"]

        # ═══════════════════════════════════════════
        # PASS 2: DETAILANALYSE für jeden Raum
        # ═══════════════════════════════════════════
        for raum in overview.get("raeume", []):
            if raum.get("position_rect_pct"):
                try:
                    logger.info("  Pass 2: Detail '%s'", raum.get("name", "?"))
                    detail = await _pass2_detail(
                        pdf_path, page_idx, raum,
                        json.dumps(raum, ensure_ascii=False),
                    )
                    # Korrekturen anwenden
                    for korrektur in detail.get("korrekturen", []):
                        feld = korrektur.get("feld")
                        neuer_wert = korrektur.get("neuer_wert")
                        if feld and neuer_wert is not None and feld in raum:
                            logger.info("    Korrektur: %s %s → %s", feld, raum[feld], neuer_wert)
                            raum[feld] = neuer_wert

                    # Konfidenz erhöhen wenn Detail bestätigt
                    if detail.get("konfidenz", 0) > raum.get("konfidenz", 0):
                        raum["konfidenz"] = detail["konfidenz"]

                except Exception as e:
                    logger.warning("  Pass 2 fehlgeschlagen für '%s': %s", raum.get("name"), e)

        # ═══════════════════════════════════════════
        # PASS 3: TEXT-CROSS-CHECK
        # ═══════════════════════════════════════════
        logger.info("  Pass 3: Text-Verifikation")
        machine_text = _extract_machine_text(pdf_path)
        logger.info("  %d maschinenlesbare Textelemente extrahiert", len(machine_text))

        overview = _cross_check_with_text(overview, machine_text)

        text_corrections = overview.get("_text_korrekturen", [])
        if text_corrections:
            logger.info("  %d Text-Korrekturen angewendet", len(text_corrections))
            for c in text_corrections:
                warnungen.append(
                    f"Text-Korrektur: {c.get('raum', 'Plan')}.{c['feld']} "
                    f"{c.get('vision_wert')} → {c.get('text_wert')}"
                )

        # Ergebnisse sammeln
        for raum in overview.get("raeume", []):
            raum["seite"] = page_idx
            # Wandfläche berechnen wenn Umfang und Höhe vorhanden
            if raum.get("umfang_m") and raum.get("hoehe_m") and not raum.get("wandflaeche_m2"):
                raum["wandflaeche_m2"] = round(raum["umfang_m"] * raum["hoehe_m"], 2)
            all_raeume.append(raum)

        for fenster in overview.get("fenster", []):
            fenster["seite"] = page_idx
            # Fensterfläche berechnen
            if (fenster.get("al_breite_mm") and fenster.get("al_hoehe_mm")
                    and not fenster.get("flaeche_m2")):
                fenster["flaeche_m2"] = round(
                    fenster["al_breite_mm"] * fenster["al_hoehe_mm"] / 1_000_000, 2
                )
            all_fenster.append(fenster)

        for tuer in overview.get("tueren", []):
            tuer["seite"] = page_idx
            all_tueren.append(tuer)

    # Gesamtkonfidenz berechnen
    all_konfidenzen = (
        [r.get("konfidenz", 0.5) for r in all_raeume] +
        [f.get("konfidenz", 0.5) for f in all_fenster] +
        [t.get("konfidenz", 0.5) for t in all_tueren]
    )
    gesamt_konfidenz = sum(all_konfidenzen) / len(all_konfidenzen) if all_konfidenzen else 0

    # Auch text_cluster für Kompatibilität mit dem Geometrie-Agenten erstellen
    text_cluster = []
    for i, raum in enumerate(all_raeume):
        text_cluster.append({
            "id": i + 1,
            "texte": [raum.get("name", ""), f"{raum.get('flaeche_m2', '')} m²"],
            "typ_hinweis": "raum",
            "konfidenz": raum.get("konfidenz", 0.5),
            "details": raum,
        })
    for i, fenster in enumerate(all_fenster):
        text_cluster.append({
            "id": len(all_raeume) + i + 1,
            "texte": [fenster.get("bezeichnung", "")],
            "typ_hinweis": "fenster",
            "konfidenz": fenster.get("konfidenz", 0.5),
            "details": fenster,
        })

    result = {
        "massstab": massstab,
        "geschoss": geschoss,
        "planbuero": overview.get("planbuero") if num_pages > 0 else None,
        "raeume": all_raeume,
        "fenster": all_fenster,
        "tueren": all_tueren,
        "text_cluster": text_cluster,
        "wandstaerken_mm": overview.get("wandstaerken_mm", [250, 175, 125]),
        "warnungen": warnungen,
        "gesamt_konfidenz": round(gesamt_konfidenz, 2),
        "seiten_analysiert": min(num_pages, 5),
    }

    logger.info("========================================")
    logger.info("PARSER FERTIG: %d Räume, %d Fenster, %d Türen",
                len(all_raeume), len(all_fenster), len(all_tueren))
    logger.info("Konfidenz: %.0f%%, Maßstab: %s, Geschoss: %s",
                gesamt_konfidenz * 100, massstab or "?", geschoss or "?")
    logger.info("========================================")

    return result
