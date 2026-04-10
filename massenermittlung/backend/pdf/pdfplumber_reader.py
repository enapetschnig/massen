"""
PDF text extraction using pdfplumber.

Extracts all words with coordinates, font information, and transformation
matrix data. Separates rotated text from normal text based on the
character matrix (upright detection).
"""

import logging
from pathlib import Path
from typing import Any

import pdfplumber

logger = logging.getLogger(__name__)


def _is_rotated(char: dict) -> bool:
    """
    Determine whether a character is rotated based on its transformation matrix.

    pdfplumber exposes the PDF text matrix as ``matrix`` – a 6-element tuple
    (a, b, c, d, e, f).  For upright (non-rotated) text the off-diagonal
    components b and c are (close to) zero.
    """
    matrix = char.get("matrix")
    if not matrix or len(matrix) < 4:
        return False
    _, b, c, _ = matrix[:4]
    # Allow a small tolerance for floating-point imprecision
    return abs(b) > 0.01 or abs(c) > 0.01


def _build_word_entry(word: dict) -> dict[str, Any]:
    """Convert a pdfplumber word dict into a normalised entry."""
    return {
        "text": word.get("text", ""),
        "x0": round(word.get("x0", 0), 2),
        "y0": round(word.get("top", 0), 2),
        "x1": round(word.get("x1", 0), 2),
        "y1": round(word.get("bottom", 0), 2),
        "fontname": word.get("fontname", ""),
        "size": round(word.get("size", 0), 2) if word.get("size") else None,
    }


def extract_text_data(pdf_path: str) -> dict[str, Any]:
    """
    Extract structured text data from a PDF using pdfplumber.

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
    """
    path = Path(pdf_path)
    if not path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    result: dict[str, Any] = {"datei": path.name, "pages": []}

    with pdfplumber.open(str(path)) as pdf:
        for page_num, page in enumerate(pdf.pages, start=1):
            page_data: dict[str, Any] = {
                "seitennummer": page_num,
                "seitenbreite": round(page.width, 2),
                "seitenhoehe": round(page.height, 2),
                "normal_text": [],
                "rotierter_text": [],
            }

            # ---- Character-level analysis for rotation detection ----------
            chars = page.chars or []
            rotated_char_indices: set[int] = set()
            for idx, char in enumerate(chars):
                if _is_rotated(char):
                    rotated_char_indices.add(idx)

            # ---- Word-level extraction ------------------------------------
            words = page.extract_words(
                keep_blank_chars=False,
                extra_attrs=["fontname", "size"],
            ) or []

            for word in words:
                entry = _build_word_entry(word)
                # Heuristic: if the word's top/bottom overlaps with rotated
                # characters we classify it as rotated.  A simpler (but
                # effective) approach: check characters whose positions fall
                # within the word bbox.
                word_is_rotated = False
                for idx in rotated_char_indices:
                    c = chars[idx]
                    if (
                        c.get("x0", 0) >= word.get("x0", 0) - 1
                        and c.get("x0", 0) <= word.get("x1", 0) + 1
                        and c.get("top", 0) >= word.get("top", 0) - 1
                        and c.get("top", 0) <= word.get("bottom", 0) + 1
                    ):
                        word_is_rotated = True
                        break

                if word_is_rotated:
                    page_data["rotierter_text"].append(entry)
                else:
                    page_data["normal_text"].append(entry)

            logger.info(
                "Seite %d: %d normale Wörter, %d rotierte Wörter",
                page_num,
                len(page_data["normal_text"]),
                len(page_data["rotierter_text"]),
            )
            result["pages"].append(page_data)

    return result
