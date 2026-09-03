from __future__ import annotations

from pathlib import Path

from app.parsing.classifier import classify_document
from app.parsing.excel_reader import read_excel
from app.parsing.pdf_extractor import read_image, read_pdf, sniff_kind
from app.parsing.schemas import ParsedDocument, ParsedLine


def parse_file(path: str, *, filename: str | None = None, allow_ocr: bool = True) -> ParsedDocument:
    file_path = str(path)
    name = filename or Path(path).name
    kind = sniff_kind(file_path)

    document = ParsedDocument(filename=name, file_path=file_path, mime_hint=kind)

    if kind == "excel":
        sheets, line_dicts, preview = read_excel(file_path)
        document.sheets = sheets
        document.text_preview = preview
        document.lines = [ParsedLine.model_validate(item) for item in line_dicts]
    elif kind == "pdf":
        extracted = read_pdf(file_path, allow_ocr=allow_ocr)
        document.text_preview = extracted["text"]
        document.lines = [ParsedLine.model_validate(item) for item in extracted["lines"]]
        document.ocr_used = extracted["ocr_used"]
        document.ocr_confidence = extracted["ocr_confidence"]
        document.warnings.extend(extracted["warnings"])
    elif kind == "image":
        extracted = read_image(file_path, allow_ocr=allow_ocr)
        document.text_preview = extracted["text"]
        document.ocr_used = extracted["ocr_used"]
        document.ocr_confidence = extracted["ocr_confidence"]
        document.warnings.extend(extracted["warnings"])
    else:
        document.warnings.append(f"unsupported_extension:{Path(file_path).suffix}")

    classification = classify_document(
        filename=name,
        text=document.text_preview,
        sheet_names=document.sheets,
    )
    document.doc_type = classification.doc_type
    document.classification_score = classification.score
    document.classification_hits = classification.hits
    if classification.doc_type is None:
        document.warnings.append("doc_type_unclassified_needs_operator")

    return document
