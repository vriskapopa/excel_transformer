from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi import HTTPException

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.api.routes import shipments as shipments_route
from app.models.enums import DocType
from app.parsing.pdf_extractor import sniff_kind


def test_sniff_kind_recognizes_pdf() -> None:
    assert sniff_kind("invoice.pdf") == "pdf"
    assert sniff_kind("scan.PNG") == "image"
    assert sniff_kind("book.xlsx") == "excel"


def test_allow_ocr_for_pdf_and_images() -> None:
    assert shipments_route._allow_ocr_for_upload(Path("a.pdf")) is True
    assert shipments_route._allow_ocr_for_upload(Path("a.jpg")) is True
    assert shipments_route._allow_ocr_for_upload(Path("a.xlsx")) is False


def test_validate_upload_rejects_unknown_extension() -> None:
    with pytest.raises(HTTPException) as exc:
        shipments_route._validate_upload_filename("notes.doc")
    assert exc.value.status_code == 400
    assert "не поддерживается" in exc.value.detail


def test_guess_doc_type_for_description_pdf() -> None:
    assert (
        shipments_route._guess_doc_type("18233 626-1 описание.pdf", DocType.CATALOG)
        == DocType.SPECIFICATION
    )
    assert (
        shipments_route._guess_doc_type("permit_rd.pdf", DocType.INVOICE) == DocType.PERMIT
    )
