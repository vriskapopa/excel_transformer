"""Smoke checks for known bug scenarios."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.api.routes.shipments import _looks_like_18233
from app.parsing.pipeline import parse_file
from app.services.export_18233_templates import export_18233_from_templates
from app.services.materials_18233 import kit_sources
from app.services.profile_18233 import parse_bundle, reconcile_18233
from app.services.reconcile import items_to_dicts


def test_spec_alone_has_articles() -> None:
    src = kit_sources("626-1")["specification"]
    bundle = parse_bundle([src])
    items = [i for i in reconcile_18233(bundle) if i.article]
    assert len(items) == 13
    assert all(i.article for i in items)


def test_generic_reads_product_name() -> None:
    src = kit_sources("626-1")["specification"]
    doc = parse_file(str(src), allow_ocr=False)
    assert doc.lines
    assert sum(1 for line in doc.lines if line.normalized_article) >= 250


def test_auto_detect_18233_filenames() -> None:
    paths = list(kit_sources("626-1").values())
    assert _looks_like_18233(paths) is True


def test_ready_etalon_filename_detected() -> None:
    from app.api.routes.shipments import _is_ready_etalon_filename

    assert _is_ready_etalon_filename("18233 626-1 СПЕЦИФИКАЦИЯ С ЦВЕТАМИ.xlsx") is True
    assert _is_ready_etalon_filename("18233 ИНВОЙС 626-1.XLSX") is True
    assert _is_ready_etalon_filename("626-1-YS-RMB-EXW-Specification.xls") is False
    assert _is_ready_etalon_filename("626-1-YS-RMB-EXW-INVOICE.XLSX") is False


def test_cyrillic_role_classification() -> None:
    from app.api.routes.shipments import _classify_18233_filename

    assert _classify_18233_filename("18233 ИНВОЙС 626-1.XLSX") == "invoice"
    assert _classify_18233_filename("18233 ПАКИНГ 626-1.XLSX") == "packing"
    assert _classify_18233_filename("18233 626-1 СПЕЦИФИКАЦИЯ С ЦВЕТАМИ.xlsx") == "specification"


def test_beijing_profile_still_forced_to_18233_for_zhongfang(tmp_path: Path) -> None:
    # Simulate wrong UI profile: files are 18233 kit
    paths = list(kit_sources("626-1").values())
    assert _looks_like_18233(paths)
    items = items_to_dicts(reconcile_18233(parse_bundle(paths)))
    products = [
        i
        for i in items
        if (i.get("source_traces") or {}).get("invoice")
        or (i.get("source_traces") or {}).get("specification")
    ]
    assert len(products) == 13
    export_18233_from_templates(items, tmp_path / "out", header={"invoice_no": "ZFRMB26148-626-1"})
    assert list((tmp_path / "out").glob("*.xlsx"))
