from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.models.enums import DocType
from app.parsing.classifier import classify_document
from app.parsing.normalize import normalize_article


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("MO SHO-01", "MOSHO-01"),
        ("mo sho-01", "MOSHO-01"),
        ("  MO   SHO-01  ", "MOSHO-01"),
        ("МО SHO-01", "МОSHO-01"),
        ("", ""),
        (None, ""),
    ],
)
def test_normalize_article(raw: str | None, expected: str) -> None:
    assert normalize_article(raw) == expected


def test_classify_invoice_by_keywords() -> None:
    result = classify_document(
        filename="scan.pdf",
        text="Commercial Invoice No 626-1 Unit Price Amount Quantity",
    )
    assert result.doc_type == DocType.INVOICE


def test_classify_packing_list() -> None:
    result = classify_document(
        filename="docs.xlsx",
        text="Packing List Net Weight Gross Weight Rolls CBM",
        sheet_names=["Packing list"],
    )
    assert result.doc_type == DocType.PACKING_LIST


def test_classify_does_not_guess_on_weak_signal() -> None:
    result = classify_document(filename="file.pdf", text="hello world")
    assert result.doc_type is None
