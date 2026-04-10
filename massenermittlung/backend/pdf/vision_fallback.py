"""
Vision-based fallback for unreadable PDF pages.

When pdfplumber and PyMuPDF fail to extract meaningful text from a page,
this module renders the page as a high-resolution PNG and sends it to
the Anthropic Claude Vision API for OCR-style text extraction.
"""

import base64
import logging
import os
from pathlib import Path
from typing import Any

import anthropic
import fitz  # PyMuPDF

logger = logging.getLogger(__name__)

# Default rendering resolution (DPI) – 300 provides a good balance between
# quality and payload size for the Vision API.
DEFAULT_DPI = 300
DEFAULT_MODEL = "claude-sonnet-4-20250514"


def _render_page_as_png(pdf_path: str, page_number: int, dpi: int = DEFAULT_DPI) -> bytes:
    """
    Render a single PDF page as a PNG image using PyMuPDF.

    Args:
        pdf_path: Path to the PDF file.
        page_number: 0-based page index.
        dpi: Resolution for rendering.

    Returns:
        PNG image data as bytes.
    """
    doc = fitz.open(pdf_path)
    try:
        if page_number < 0 or page_number >= len(doc):
            raise ValueError(
                f"Page {page_number} out of range (document has {len(doc)} pages)"
            )
        page = doc[page_number]
        zoom = dpi / 72.0
        matrix = fitz.Matrix(zoom, zoom)
        pixmap = page.get_pixmap(matrix=matrix, alpha=False)
        return pixmap.tobytes(output="png")
    finally:
        doc.close()


def _call_claude_vision(image_png: bytes, api_key: str | None = None) -> str:
    """
    Send a PNG image to the Claude Vision API and request text extraction.

    Args:
        image_png: Raw PNG bytes.
        api_key: Anthropic API key.  Falls back to the
                 ``ANTHROPIC_API_KEY`` environment variable.

    Returns:
        Extracted text content as a string.
    """
    key = api_key or os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise RuntimeError(
            "ANTHROPIC_API_KEY is not set. Provide it as an argument or "
            "set the environment variable."
        )

    client = anthropic.Anthropic(api_key=key)

    image_b64 = base64.standard_b64encode(image_png).decode("ascii")

    message = client.messages.create(
        model=DEFAULT_MODEL,
        max_tokens=4096,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/png",
                            "data": image_b64,
                        },
                    },
                    {
                        "type": "text",
                        "text": (
                            "Du bist ein OCR-Spezialist für Baupläne und "
                            "technische Zeichnungen. Extrahiere den gesamten "
                            "sichtbaren Text aus diesem Bild. Gib den Text "
                            "zeilenweise zurück und behalte die räumliche "
                            "Anordnung so gut wie möglich bei. Wenn du "
                            "Maßangaben, Raumnummern oder Beschriftungen "
                            "erkennst, kennzeichne sie mit ihrem Typ in "
                            "eckigen Klammern, z.B. [Raum] Wohnzimmer, "
                            "[Maß] 3.50 m. Gib NUR den extrahierten Text "
                            "zurück, keine Erklärungen."
                        ),
                    },
                ],
            }
        ],
    )

    return message.content[0].text


def extract_text_data(
    pdf_path: str,
    page_numbers: list[int] | None = None,
    api_key: str | None = None,
    dpi: int = DEFAULT_DPI,
) -> dict[str, Any]:
    """
    Extract text from PDF pages via Claude Vision API.

    This is intended as a fallback when text-based extraction yields
    insufficient results (e.g. scanned documents, image-only PDFs).

    Args:
        pdf_path: Path to the PDF file.
        page_numbers: 0-based page indices to process.  ``None`` means
                      all pages.
        api_key: Anthropic API key (falls back to env var).
        dpi: Rendering resolution for page images.

    Returns:
        A dict matching the interface of ``pdfplumber_reader.extract_text_data``:
        ``pages`` list, each with ``seitennummer``, ``seitenbreite``,
        ``seitenhoehe``, ``normal_text``, and ``rotierter_text``.
    """
    path = Path(pdf_path)
    if not path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    doc = fitz.open(str(path))
    total_pages = len(doc)

    if page_numbers is None:
        page_numbers = list(range(total_pages))

    result: dict[str, Any] = {"datei": path.name, "pages": [], "methode": "vision"}

    for page_num in page_numbers:
        if page_num < 0 or page_num >= total_pages:
            logger.warning("Skipping out-of-range page %d", page_num)
            continue

        page = doc[page_num]
        rect = page.rect

        page_data: dict[str, Any] = {
            "seitennummer": page_num + 1,
            "seitenbreite": round(rect.width, 2),
            "seitenhoehe": round(rect.height, 2),
            "normal_text": [],
            "rotierter_text": [],
        }

        try:
            logger.info("Rendering page %d for vision extraction ...", page_num + 1)
            png_data = _render_page_as_png(str(path), page_num, dpi=dpi)

            raw_text = _call_claude_vision(png_data, api_key=api_key)

            # Parse the returned text into word entries.  Since the Vision
            # API does not return bounding-box coordinates we synthesize
            # approximate positions based on line/word order.
            lines = raw_text.strip().split("\n")
            y_pos = 10.0
            line_height = 14.0

            for line in lines:
                if not line.strip():
                    y_pos += line_height
                    continue
                words = line.split()
                x_pos = 10.0
                for word in words:
                    entry = {
                        "text": word,
                        "x0": round(x_pos, 2),
                        "y0": round(y_pos, 2),
                        "x1": round(x_pos + len(word) * 7, 2),
                        "y1": round(y_pos + line_height, 2),
                        "fontname": "vision-extracted",
                        "size": 12.0,
                    }
                    page_data["normal_text"].append(entry)
                    x_pos += len(word) * 7 + 5
                y_pos += line_height

            logger.info(
                "Seite %d (Vision): %d Wörter extrahiert",
                page_num + 1,
                len(page_data["normal_text"]),
            )
        except Exception:
            logger.exception("Vision extraction failed for page %d", page_num + 1)

        result["pages"].append(page_data)

    doc.close()
    return result
