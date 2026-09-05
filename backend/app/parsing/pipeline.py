from __future__ import annotations

from pathlib import Path

from app.models.enums import DocType
from app.parsing.anydoc_reader import read_anydoc
from app.parsing.classifier import classify_document
from app.parsing.excel_reader import read_excel
from app.parsing.pdf_extractor import read_image, read_pdf, sniff_kind
from app.parsing.schemas import ParsedDocument, ParsedLine
from app.parsing.table_rows import merge_line_groups


def _as_lines(raw_lines: list[dict]) -> list[ParsedLine]:
    return [ParsedLine.model_validate(item) for item in raw_lines]


def parse_file(path: str, *, filename: str | None = None, allow_ocr: bool = True) -> ParsedDocument:
    file_path = str(path)
    name = filename or Path(path).name
    kind = sniff_kind(file_path)

    document = ParsedDocument(filename=name, file_path=file_path, mime_hint=kind)
    anydoc_hit = read_anydoc(file_path)
    anydoc_lines = (anydoc_hit or {}).get("lines") or []

    try:
        if kind == "excel":
            sheets, pandas_lines, preview = read_excel(file_path)
            document.sheets = sheets
            document.text_preview = preview
            if anydoc_hit and anydoc_hit.get("text"):
                document.text_preview = f"{anydoc_hit['text']}\n{preview}"
            document.lines = _as_lines(merge_line_groups(pandas_lines, anydoc_lines))
        elif kind == "pdf":
            extracted = read_pdf(file_path, allow_ocr=allow_ocr)
            document.text_preview = extracted["text"]
            document.ocr_used = extracted["ocr_used"]
            document.ocr_confidence = extracted["ocr_confidence"]
            document.warnings.extend(extracted["warnings"])
            if anydoc_hit:
                document.text_preview = anydoc_hit.get("text") or document.text_preview
                document.warnings.extend(anydoc_hit.get("warnings") or [])
            document.lines = _as_lines(merge_line_groups(extracted["lines"], anydoc_lines))
        elif kind == "image":
            extracted = read_image(file_path, allow_ocr=allow_ocr)
            document.text_preview = extracted["text"]
            document.ocr_used = extracted["ocr_used"]
            document.ocr_confidence = extracted["ocr_confidence"]
            document.warnings.extend(extracted["warnings"])
            document.lines = _as_lines(extracted["lines"])
        else:
            document.warnings.append(f"unsupported_extension:{Path(file_path).suffix}")
    except Exception as exc:
        document.warnings.append(f"parse_failed:{exc}")
        if anydoc_lines:
            document.text_preview = (anydoc_hit or {}).get("text") or ""
            document.lines = _as_lines(anydoc_lines)

    classification = classify_document(
        filename=name,
        text=document.text_preview,
        sheet_names=document.sheets,
    )
    document.doc_type = classification.doc_type
    document.classification_score = classification.score
    document.classification_hits = classification.hits
    if document.doc_type is None and document.lines:
        document.doc_type = DocType.INVOICE
        document.warnings.append("doc_type_defaulted_invoice")
    elif classification.doc_type is None:
        document.warnings.append("doc_type_unclassified_needs_operator")

    return document
