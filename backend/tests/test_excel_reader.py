from __future__ import annotations

import sys
from pathlib import Path

from openpyxl import Workbook

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.parsing.excel_reader import read_excel
from app.parsing.pipeline import parse_file


def test_read_excel_normalizes_article(tmp_path: Path) -> None:
    path = tmp_path / "invoice.xlsx"
    book = Workbook()
    sheet = book.active
    sheet.title = "Invoice"
    sheet.append(["Article", "Qty", "Price"])
    sheet.append(["MO SHO-01", 10, 12.5])
    sheet.append(["mo  sho-01", 2, 12.5])
    book.save(path)

    sheets, lines, preview = read_excel(str(path))
    assert sheets == ["Invoice"]
    assert "Invoice" in preview
    assert [line["normalized_article"] for line in lines] == ["MOSHO-01", "MOSHO-01"]
    assert lines[0]["article"] == "MO SHO-01"


def test_parse_file_classifies_invoice_excel(tmp_path: Path) -> None:
    path = tmp_path / "Commercial_Invoice.xlsx"
    book = Workbook()
    sheet = book.active
    sheet.title = "Invoice"
    sheet.append(["Article", "Quantity", "Unit Price", "Amount"])
    sheet.append(["ABC-9", 1, 10, 10])
    book.save(path)

    document = parse_file(str(path), allow_ocr=False)
    assert document.doc_type is not None
    assert document.doc_type.value == "INVOICE"
    assert document.lines[0].normalized_article == "ABC-9"
