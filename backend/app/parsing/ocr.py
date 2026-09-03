from __future__ import annotations

from pathlib import Path
from typing import Any

_EASYOCR_READER = None


def _reader():
    global _EASYOCR_READER
    if _EASYOCR_READER is None:
        import easyocr

        _EASYOCR_READER = easyocr.Reader(["en", "ru"], gpu=False, verbose=False)
    return _EASYOCR_READER


def ocr_image(path: str) -> tuple[str, float | None, list[dict[str, Any]]]:
    """Run EasyOCR on a raster file. Raises ImportError if EasyOCR is not installed."""
    reader = _reader()
    results = reader.readtext(str(path))
    texts: list[str] = []
    confidences: list[float] = []
    blocks: list[dict[str, Any]] = []
    for box, text, conf in results:
        texts.append(text)
        confidences.append(float(conf))
        blocks.append({"text": text, "confidence": float(conf), "box": box})
    mean_conf = sum(confidences) / len(confidences) if confidences else None
    return "\n".join(texts), mean_conf, blocks


def ocr_pdf_pages(path: str, *, dpi: int = 200) -> tuple[str, float | None]:
    """Rasterize PDF pages with pypdfium2 (if present) and OCR them."""
    try:
        import pypdfium2 as pdfium
    except ImportError as exc:
        raise RuntimeError(
            "Searchable PDF text was empty and PDF rasterization is unavailable "
            "(install pypdfium2 + easyocr for scan OCR)."
        ) from exc

    pdf = pdfium.PdfDocument(path)
    page_texts: list[str] = []
    confidences: list[float] = []
    tmp_dir = Path(path).parent
    for index, page in enumerate(pdf):
        bitmap = page.render(scale=dpi / 72)
        pil_image = bitmap.to_pil()
        image_path = tmp_dir / f".ocr_page_{index}.png"
        pil_image.save(image_path)
        try:
            text, conf, _ = ocr_image(str(image_path))
        finally:
            image_path.unlink(missing_ok=True)
        page_texts.append(text)
        if conf is not None:
            confidences.append(conf)
        page.close()
    pdf.close()
    mean_conf = sum(confidences) / len(confidences) if confidences else None
    return "\n".join(page_texts), mean_conf
