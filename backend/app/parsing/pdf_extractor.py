from __future__ import annotations

from pathlib import Path
from typing import Any

from app.parsing.normalize import normalize_text
from app.parsing.ocr import ocr_image, ocr_pdf_pages
from app.parsing.table_rows import lines_from_matrix, lines_from_plaintext, lines_from_qty_price_text

MIN_SEARCHABLE_CHARS = 40


def _extract_with_pypdf(path: str) -> tuple[str, list[str]]:
    try:
        from pypdf import PdfReader
    except ImportError:
        return "", ["pdf_reader_unavailable"]
    try:
        reader = PdfReader(path)
        parts = [(page.extract_text() or "") for page in reader.pages]
        return "\n".join(parts), []
    except Exception as exc:
        return "", [f"pypdf_failed:{exc}"]


def _extract_searchable_pdf(path: str) -> tuple[str, list[dict[str, Any]], list[str]]:
    text_parts: list[str] = []
    lines: list[dict[str, Any]] = []
    warnings: list[str] = []
    try:
        import pdfplumber
    except ImportError:
        text, extra = _extract_with_pypdf(path)
        warnings.extend(extra or ["pdfplumber_missing_used_pypdf"])
        if not text.strip():
            warnings.append("pdf_has_no_text_layer")
        return text, lines, warnings

    with pdfplumber.open(path) as pdf:
        for page_idx, page in enumerate(pdf.pages):
            page_text = page.extract_text() or ""
            text_parts.append(page_text)
            tables = page.extract_tables() or []
            for table_idx, table in enumerate(tables):
                if not table:
                    continue
                lines.extend(
                    lines_from_matrix(
                        table,
                        sheet_name=f"page_{page_idx + 1}_table_{table_idx + 1}",
                    )
                )
    text = "\n".join(text_parts)
    priced = lines_from_qty_price_text(text, sheet_name="pdf_qty_price")
    if not lines:
        lines = priced or lines_from_plaintext(text, sheet_name="pdf_text")
        if not lines:
            warnings.append("pdf_has_text_but_no_article_table")
    elif priced:
        lines = lines + priced
    return text, lines, warnings


def read_pdf(path: str, *, allow_ocr: bool = True) -> dict[str, Any]:
    try:
        text, lines, warnings = _extract_searchable_pdf(path)
    except Exception as exc:
        return {
            "text": "",
            "lines": [],
            "warnings": [f"pdf_read_failed:{exc}"],
            "ocr_used": False,
            "ocr_confidence": None,
        }
    ocr_used = False
    ocr_confidence: float | None = None

    if len(text.strip()) < MIN_SEARCHABLE_CHARS:
        if not allow_ocr:
            warnings.append("pdf_not_searchable_ocr_disabled")
            return {
                "text": text,
                "lines": lines,
                "warnings": warnings,
                "ocr_used": False,
                "ocr_confidence": None,
            }
        try:
            ocr_text, ocr_confidence = ocr_pdf_pages(path)
            ocr_used = True
            text = (text + "\n" + ocr_text).strip()
            if not lines:
                lines = lines_from_plaintext(ocr_text, sheet_name="ocr")
                if not lines:
                    warnings.append("ocr_text_extracted_tables_not_detected")
        except Exception as exc:  # OCR is optional at this stage
            warnings.append(f"ocr_failed:{exc}")

    return {
        "text": text,
        "lines": lines,
        "warnings": warnings,
        "ocr_used": ocr_used,
        "ocr_confidence": ocr_confidence,
    }


def read_image(path: str, *, allow_ocr: bool = True) -> dict[str, Any]:
    if not allow_ocr:
        return {
            "text": "",
            "lines": [],
            "warnings": ["image_ocr_disabled"],
            "ocr_used": False,
            "ocr_confidence": None,
        }
    try:
        text, conf, _blocks = ocr_image(path)
        return {
            "text": text,
            "lines": [],
            "warnings": ["image_ocr_no_structured_table"],
            "ocr_used": True,
            "ocr_confidence": conf,
        }
    except Exception as exc:
        return {
            "text": "",
            "lines": [],
            "warnings": [f"ocr_failed:{exc}"],
            "ocr_used": False,
            "ocr_confidence": None,
        }


def sniff_kind(path: str) -> str:
    suffix = Path(path).suffix.lower()
    if suffix in {".xlsx", ".xls", ".xlsm"}:
        return "excel"
    if suffix == ".pdf":
        return "pdf"
    if suffix in {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp"}:
        return "image"
    return "unknown"
