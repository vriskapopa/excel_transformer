from __future__ import annotations

from pathlib import Path
from typing import Any

from app.parsing.normalize import normalize_article, normalize_text
from app.parsing.ocr import ocr_image, ocr_pdf_pages

MIN_SEARCHABLE_CHARS = 40


def _extract_searchable_pdf(path: str) -> tuple[str, list[dict[str, Any]], list[str]]:
    try:
        import pdfplumber
    except ImportError as exc:
        raise RuntimeError("pdfplumber is required to read PDF files") from exc

    text_parts: list[str] = []
    lines: list[dict[str, Any]] = []
    warnings: list[str] = []
    with pdfplumber.open(path) as pdf:
        for page_idx, page in enumerate(pdf.pages):
            page_text = page.extract_text() or ""
            text_parts.append(page_text)
            tables = page.extract_tables() or []
            for table_idx, table in enumerate(tables):
                if not table:
                    continue
                headers = [normalize_text(cell or "") for cell in table[0]]
                for row_idx, row in enumerate(table[1:], start=1):
                    raw = {
                        (headers[i] or f"column_{i+1}"): (row[i] if i < len(row) else None)
                        for i in range(len(headers) or len(row))
                    }
                    article = None
                    model = None
                    for key, value in raw.items():
                        lowered = key.lower()
                        text = normalize_text(str(value) if value is not None else "")
                        if not text:
                            continue
                        if article is None and any(
                            token in lowered for token in ("article", "артикул", "art", "sku")
                        ):
                            article = text
                        if model is None and ("model" in lowered or "модель" in lowered):
                            model = text
                    key_source = article or model
                    if not key_source:
                        continue
                    lines.append(
                        {
                            "row_index": row_idx,
                            "sheet_name": f"page_{page_idx + 1}_table_{table_idx + 1}",
                            "article": article,
                            "model": model,
                            "normalized_article": normalize_article(key_source),
                            "raw": raw,
                        }
                    )
    text = "\n".join(text_parts)
    if not lines and text.strip():
        warnings.append("pdf_has_text_but_no_article_table")
    return text, lines, warnings


def read_pdf(path: str, *, allow_ocr: bool = True) -> dict[str, Any]:
    text, lines, warnings = _extract_searchable_pdf(path)
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
