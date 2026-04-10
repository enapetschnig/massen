"""
Fallback PDF text extraction using PyMuPDF (fitz).

Provides the same interface as pdfplumber_reader but uses PyMuPDF, which
handles some edge-case PDFs more reliably.  Additionally extracts basic
image/drawing metadata from each page.
"""

import logging
import math
from pathlib import Path
from typing import Any

import fitz  # PyMuPDF

logger = logging.getLogger(__name__)


def _is_rotated(span: dict) -> bool:
    """
    Check whether a text span is rotated.

    PyMuPDF's ``dict`` output includes a ``dir`` tuple (cos, sin) that
    describes the writing direction.  Upright text has dir ≈ (1, 0).
    """
    dx, dy = span.get("dir", (1, 0))
    # Tolerance for floating-point imprecision
    return abs(dy) > 0.01 or abs(dx - 1.0) > 0.01


def _build_word_entry(span: dict, bbox: tuple) -> dict[str, Any]:
    """Create a normalised word entry from a PyMuPDF span."""
    return {
        "text": span.get("text", "").strip(),
        "x0": round(bbox[0], 2),
        "y0": round(bbox[1], 2),
        "x1": round(bbox[2], 2),
        "y1": round(bbox[3], 2),
        "fontname": span.get("font", ""),
        "size": round(span.get("size", 0), 2),
    }


def _extract_images_info(page: fitz.Page) -> list[dict[str, Any]]:
    """Return basic metadata for all images embedded on a page."""
    images: list[dict[str, Any]] = []
    for img in page.get_images(full=True):
        xref = img[0]
        try:
            base_image = page.parent.extract_image(xref)
            images.append({
                "xref": xref,
                "breite": base_image.get("width", 0),
                "hoehe": base_image.get("height", 0),
                "farbraum": base_image.get("colorspace", 0),
                "bpp": base_image.get("bpc", 0),
                "format": base_image.get("ext", ""),
            })
        except Exception:
            logger.debug("Could not extract image xref %d", xref)
    return images


def _extract_drawings_info(page: fitz.Page) -> list[dict[str, Any]]:
    """Return basic metadata for vector drawings on a page."""
    drawings: list[dict[str, Any]] = []
    try:
        paths = page.get_drawings()
    except Exception:
        return drawings

    for path in paths:
        rect = path.get("rect")
        if rect:
            drawings.append({
                "typ": path.get("type", ""),
                "x0": round(rect.x0, 2),
                "y0": round(rect.y0, 2),
                "x1": round(rect.x1, 2),
                "y1": round(rect.y1, 2),
                "fill": path.get("fill"),
                "stroke": path.get("color"),
                "breite": round(path.get("width", 0), 2),
            })
    return drawings


def extract_text_data(pdf_path: str) -> dict[str, Any]:
    """
    Extract structured text data from a PDF using PyMuPDF.

    Args:
        pdf_path: Filesystem path to the PDF file.

    Returns:
        A dict with a ``pages`` key containing a list of page dicts.
        Each page dict has:
            - ``seitennummer``: 1-based page number
            - ``seitenbreite``: page width in points
            - ``seitenhoehe``: page height in points
            - ``normal_text``: list of word dicts for upright text
            - ``rotierter_text``: list of word dicts for rotated text
            - ``bilder``: list of image metadata dicts
            - ``zeichnungen``: list of drawing metadata dicts
    """
    path = Path(pdf_path)
    if not path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    result: dict[str, Any] = {"datei": path.name, "pages": []}

    doc = fitz.open(str(path))
    try:
        for page_num in range(len(doc)):
            page = doc[page_num]
            rect = page.rect

            page_data: dict[str, Any] = {
                "seitennummer": page_num + 1,
                "seitenbreite": round(rect.width, 2),
                "seitenhoehe": round(rect.height, 2),
                "normal_text": [],
                "rotierter_text": [],
                "bilder": [],
                "zeichnungen": [],
            }

            # ---- Text extraction via dict output --------------------------
            text_dict = page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE)
            for block in text_dict.get("blocks", []):
                if block.get("type") != 0:
                    # Skip image blocks (type 1)
                    continue
                for line in block.get("lines", []):
                    for span in line.get("spans", []):
                        text = span.get("text", "").strip()
                        if not text:
                            continue
                        bbox = span.get("bbox", line.get("bbox", (0, 0, 0, 0)))
                        entry = _build_word_entry(span, bbox)
                        if _is_rotated(span):
                            page_data["rotierter_text"].append(entry)
                        else:
                            page_data["normal_text"].append(entry)

            # ---- Images and drawings --------------------------------------
            page_data["bilder"] = _extract_images_info(page)
            page_data["zeichnungen"] = _extract_drawings_info(page)

            logger.info(
                "Seite %d: %d normale Wörter, %d rotierte Wörter, "
                "%d Bilder, %d Zeichnungen",
                page_num + 1,
                len(page_data["normal_text"]),
                len(page_data["rotierter_text"]),
                len(page_data["bilder"]),
                len(page_data["zeichnungen"]),
            )
            result["pages"].append(page_data)
    finally:
        doc.close()

    return result
