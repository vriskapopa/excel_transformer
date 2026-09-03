"""Excel export workers — Word spec §3.2 / §4.1 / §7.

Profile 18233: split by invoice sub-kit (626-1, 626-2) →
  Invoice.xlsx + Packing.xlsx + Specification.xlsx (+ PDF description stub).
Profile BEIJING: one workbook with sheets Invoice, Packing list, Specification, Description.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from openpyxl import Workbook


def _write_sheet(ws, headers: list[str], rows: list[list[Any]]) -> None:
    ws.append(headers)
    for row in rows:
        ws.append(row)


def _item_rows(items: list[dict[str, Any]], kind: str) -> list[list[Any]]:
    rows: list[list[Any]] = []
    for item in items:
        commercial = item.get("commercial_data") or {}
        packing = item.get("packing_data") or {}
        customs = item.get("customs_data") or {}
        article = item.get("article") or item.get("normalized_article") or ""
        if kind == "invoice":
            rows.append(
                [
                    article,
                    item.get("model"),
                    commercial.get("color"),
                    commercial.get("qty"),
                    commercial.get("unit"),
                    commercial.get("price"),
                    commercial.get("amount"),
                    commercial.get("currency"),
                    customs.get("hs_code"),
                ]
            )
        elif kind == "packing":
            rows.append(
                [
                    article,
                    packing.get("rolls") or packing.get("boxes"),
                    packing.get("meters"),
                    packing.get("area"),
                    packing.get("net_weight"),
                    packing.get("gross_weight"),
                    packing.get("volume"),
                ]
            )
        elif kind == "specification":
            rows.append(
                [
                    article,
                    commercial.get("color"),
                    packing.get("rolls") or packing.get("boxes"),
                    packing.get("meters"),
                    packing.get("area"),
                    packing.get("net_weight"),
                    packing.get("gross_weight"),
                    customs.get("tnved_code") or customs.get("hs_code"),
                    customs.get("description_en"),
                    customs.get("description_ru"),
                ]
            )
        elif kind == "description":
            rows.append(
                [
                    article,
                    customs.get("tnved_code"),
                    customs.get("description_en"),
                    customs.get("description_ru"),
                    customs.get("country"),
                    customs.get("manufacturer"),
                ]
            )
    return rows


def export_beijing(items: list[dict[str, Any]], output_path: Path, header: dict[str, Any] | None = None) -> Path:
    wb = Workbook()
    # Invoice
    ws = wb.active
    ws.title = "Invoice"
    if header:
        ws.append(["Buyer", header.get("buyer")])
        ws.append(["Seller", header.get("seller")])
        ws.append(["Contract", header.get("contract_no")])
        ws.append(["Incoterms", header.get("incoterms")])
        ws.append(["Date", header.get("date")])
        ws.append([])
    _write_sheet(
        ws,
        ["Article", "Model", "Color", "Qty", "Unit", "Price", "Amount", "Currency", "HS Code"],
        _item_rows(items, "invoice"),
    )

    ws_pl = wb.create_sheet("Packing list")
    _write_sheet(
        ws_pl,
        ["Article", "Places", "Meters", "Area", "Net Weight", "Gross Weight", "Volume"],
        _item_rows(items, "packing"),
    )

    ws_spec = wb.create_sheet("Specification")
    _write_sheet(
        ws_spec,
        [
            "Article",
            "Color",
            "Places",
            "Meters",
            "Area",
            "Net Weight",
            "Gross Weight",
            "TN VED",
            "Description EN",
            "Description RU",
        ],
        _item_rows(items, "specification"),
    )

    ws_desc = wb.create_sheet("Description")
    _write_sheet(
        ws_desc,
        ["Article", "TN VED", "Description EN", "Description RU", "Country", "Manufacturer"],
        _item_rows(items, "description"),
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(output_path)
    return output_path


def export_18233(
    items: list[dict[str, Any]],
    output_dir: Path,
    header: dict[str, Any] | None = None,
    shipment_title: str = "18233",
) -> list[Path]:
    """One Invoice + Packing + Specification-with-colors per sub-kit."""
    output_dir.mkdir(parents=True, exist_ok=True)
    by_subkit: dict[str, list[dict[str, Any]]] = {}
    for item in items:
        commercial = item.get("commercial_data") or {}
        subkit = item.get("invoice_subkit") or commercial.get("invoice_subkit") or "ALL"
        by_subkit.setdefault(str(subkit), []).append(item)

    paths: list[Path] = []
    for subkit, group in sorted(by_subkit.items()):
        inv_path = output_dir / f"{shipment_title} ИНВОЙС {subkit}.xlsx"
        pl_path = output_dir / f"{shipment_title} ПАКИНГ {subkit}.xlsx"
        desc_path = output_dir / f"{shipment_title} {subkit} описание.txt"

        for path, kind, headers in (
            (
                inv_path,
                "invoice",
                ["Article", "Model", "Color", "Qty", "Unit", "Price", "Amount", "Currency", "HS Code"],
            ),
            (
                pl_path,
                "packing",
                ["Article", "Places", "Meters", "Area", "Net Weight", "Gross Weight", "Volume"],
            ),
        ):
            wb = Workbook()
            ws = wb.active
            ws.title = kind
            if header and kind == "invoice":
                ws.append(["Buyer", (header or {}).get("buyer")])
                ws.append(["Seller", (header or {}).get("seller")])
                ws.append(["Contract", (header or {}).get("contract_no")])
                ws.append(["Incoterms", (header or {}).get("incoterms")])
                ws.append([])
            _write_sheet(ws, headers, _item_rows(group, kind))
            wb.save(path)
            paths.append(path)

        # PDF description is a later step; write a plain-text stub so export is complete.
        lines = [
            f"Description for {shipment_title} sub-kit {subkit}",
            f"Header: {header or {}}",
            "",
        ]
        for item in group:
            customs = item.get("customs_data") or {}
            lines.append(
                f"{item.get('article')}: {customs.get('tnved_code')} | "
                f"{customs.get('description_en')} / {customs.get('description_ru')}"
            )
        desc_path.write_text("\n".join(lines), encoding="utf-8")
        paths.append(desc_path)

    return paths
