"""Profile 18233 — dedicated parsers for Zhongfang Invoice / PL / Specification.

MVP brief (28.08.2026):
- Only fixed structures 626-1 / 626-2
- Match by normalized article/model (DESIGN / PRODUCT NAME)
- Keep Spec roll detail; aggregate for summary docs
- Invoice ↔ Spec: rolls, meters, width, area, price, amount
- Packing List ↔ Spec aggregates by design family: rolls, meters, area, NW, GW
- Acceptance: 626-1 → 13 positions; 626-2 → 17 positions
- Never silently replace disputed values
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd

from app.models.enums import ErrorSeverity, ErrorType
from app.parsing.normalize import normalize_article, normalize_text
from app.services.reconcile import ReconciledItem, ValidationFlag

HEADER_MARKERS = ("NO.", "DESIGN", "ROLL NO", "PRODUCT NAME")
GROUP_PREFIXES = (
    "SOFA FABRIC",
    "ARTIFICIAL LEATHER",
)
SKIP_DESIGNS = {"DESIGN", "TOTAL", "TOTAL:"}


def _cell(df: pd.DataFrame, row: int, col: int) -> Any:
    if row >= len(df) or col >= df.shape[1]:
        return None
    value = df.iat[row, col]
    if pd.isna(value):
        return None
    return value


def _num(value: Any) -> float | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(" ", "").replace(",", ".")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _text(value: Any) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    return normalize_text(str(value).replace("\n", " "))


def _find_header_row(df: pd.DataFrame, markers: tuple[str, ...]) -> int | None:
    limit = min(len(df), 40)
    for idx in range(limit):
        row_text = " | ".join(_text(df.iat[idx, c]).upper() for c in range(min(df.shape[1], 15)))
        hits = sum(1 for marker in markers if marker in row_text)
        if hits >= 2:
            return idx
    return None


def _is_group_design(design: str) -> bool:
    upper = design.upper()
    return any(upper.startswith(prefix) or f" {prefix}" in upper for prefix in GROUP_PREFIXES)


def _design_family(article: str) -> str:
    """Noble 110 -> NOBLE; NAPPA 000 -> NAPPA; Magic 01 -> MAGIC."""
    parts = article.strip().split()
    if not parts:
        return normalize_article(article)
    return normalize_article(parts[0])


def _extract_family_from_pl_design(design: str) -> str:
    """SOFA FABRIC Noble -> NOBLE; ARTIFICIAL LEATHER NAPPA -> NAPPA."""
    cleaned = re.sub(r"(?i)sofa\s*fabric", " ", design)
    cleaned = re.sub(r"(?i)artificial\s*leather", " ", cleaned)
    cleaned = normalize_text(cleaned)
    return normalize_article(cleaned.split()[0] if cleaned.split() else cleaned)


@dataclass
class Parsed18233Bundle:
    subkit: str | None
    invoice_rows: list[dict[str, Any]] = field(default_factory=list)
    packing_groups: list[dict[str, Any]] = field(default_factory=list)
    spec_rolls: list[dict[str, Any]] = field(default_factory=list)
    spec_aggregates: dict[str, dict[str, Any]] = field(default_factory=dict)
    header_hints: dict[str, Any] = field(default_factory=dict)


def detect_subkit(paths: list[str | Path]) -> str | None:
    blob = " ".join(Path(p).name for p in paths)
    match = re.search(r"\b(\d{2,4}-\d)\b", blob)
    return match.group(1) if match else None


def _iter_excel_sheets(path: str | Path) -> list[tuple[str, pd.DataFrame]]:
    book = pd.read_excel(path, sheet_name=None, header=None, dtype=object)
    if isinstance(book, dict):
        return [(str(name), frame) for name, frame in book.items()]
    return [("Sheet1", book)]


def _merge_unique(primary: list[dict[str, Any]], extra: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
    have = {row.get(key) for row in primary if row.get(key)}
    out = list(primary)
    for row in extra:
        item_key = row.get(key)
        if not item_key or item_key in have:
            continue
        out.append(row)
        have.add(item_key)
    return out


def parse_invoice(path: str | Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    best: list[dict[str, Any]] = []
    hints: dict[str, Any] = {}
    extras: list[dict[str, Any]] = []
    for _name, df in _iter_excel_sheets(path):
        products, sheet_hints = _parse_invoice_sheet(df)
        if len(products) > len(best):
            extras.extend(best)
            best, hints = products, sheet_hints
        else:
            extras.extend(products)
            if not hints:
                hints = sheet_hints
    return _merge_unique(best, extras, "normalized_article"), hints


def _parse_invoice_sheet(df: pd.DataFrame) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    header = _find_header_row(df, ("NO.", "DESIGN", "ROLLS", "METERS"))
    if header is None:
        header = 8
    hints: dict[str, Any] = {}
    # crude header scrape
    for r in range(0, header):
        for c in range(min(df.shape[1], 10)):
            cell = _text(_cell(df, r, c))
            if cell.upper().startswith("INV.NO") or cell.upper() == "INV.NO.":
                hints["invoice_no"] = _text(_cell(df, r, c + 1)) or hints.get("invoice_no")
            if "CONTRACT" in cell.upper():
                hints["contract_no"] = cell
            if cell.upper().startswith("DATE"):
                hints["date"] = _text(_cell(df, r, c + 1)) or hints.get("date")
            if cell.upper().startswith("BUYER"):
                hints["buyer"] = cell

    # Collect raw rows then attach prices from following group summary
    raw_rows: list[dict[str, Any]] = []
    for r in range(header + 1, len(df)):
        design = _text(_cell(df, r, 1))
        if not design:
            continue
        if design.upper().startswith("TOTAL"):
            break
        no = _cell(df, r, 0)
        row = {
            "row_index": r,
            "no": no,
            "design": design,
            "hs_code": _text(_cell(df, r, 2)) or None,
            "rolls": _num(_cell(df, r, 3)),
            "width": _num(_cell(df, r, 4)),
            "area": _num(_cell(df, r, 5)),
            "meters": _num(_cell(df, r, 6)),
            "unit": _text(_cell(df, r, 7)) or None,
            "price": _num(_cell(df, r, 8)),
            "amount": _num(_cell(df, r, 9)),
            "is_group": _is_group_design(design) or no is None,
        }
        raw_rows.append(row)

    products: list[dict[str, Any]] = []
    pending: list[dict[str, Any]] = []
    for row in raw_rows:
        if row["is_group"]:
            # Apply group price/amount split is not silent — price inherited only when product price empty
            for prod in pending:
                if prod.get("price") is None and row.get("price") is not None:
                    prod["price"] = row["price"]
                    prod["price_from_group"] = row["design"]
                if prod.get("amount") is None and prod.get("price") is not None and prod.get("meters") is not None:
                    prod["amount"] = round(float(prod["meters"]) * float(prod["price"]), 2)
                    prod["amount_calculated"] = True
                # Keep group amount on group only; do not invent per-line amount from group total silently
            pending = []
            continue
        if _text(row["design"]).upper() in SKIP_DESIGNS:
            continue
        # Product lines must have a numeric NO (skip header leftovers)
        if not isinstance(row["no"], (int, float)) and not str(row["no"] or "").isdigit():
            continue
        article = row["design"]
        row["article"] = article
        row["normalized_article"] = normalize_article(article)
        row["design_family"] = _design_family(article)
        products.append(row)
        pending.append(row)

    # trailing products without group footer
    for prod in pending:
        if prod.get("amount") is None and prod.get("price") is not None and prod.get("meters") is not None:
            prod["amount"] = round(float(prod["meters"]) * float(prod["price"]), 2)
            prod["amount_calculated"] = True

    return products, hints


def parse_packing_list(path: str | Path) -> list[dict[str, Any]]:
    best: list[dict[str, Any]] = []
    extras: list[dict[str, Any]] = []
    for _name, df in _iter_excel_sheets(path):
        groups = _parse_packing_sheet(df)
        if len(groups) > len(best):
            extras.extend(best)
            best = groups
        else:
            extras.extend(groups)
    return _merge_unique(best, extras, "normalized_family")


def _parse_packing_sheet(df: pd.DataFrame) -> list[dict[str, Any]]:
    header = _find_header_row(df, ("DESIGN", "ROLLS", "NET", "GROSS"))
    if header is None:
        header = 8
    groups: list[dict[str, Any]] = []
    for r in range(header + 1, len(df)):
        design = _text(_cell(df, r, 1))
        if not design:
            continue
        if design.upper().startswith("TOTAL"):
            break
        family = _extract_family_from_pl_design(design)
        groups.append(
            {
                "row_index": r,
                "design": design,
                "design_family": family,
                "normalized_family": family,
                "gm": _num(_cell(df, r, 2)),
                "rolls": _num(_cell(df, r, 3)),
                "meters": _num(_cell(df, r, 4)),
                "net_weight": _num(_cell(df, r, 5)),
                "gross_weight": _num(_cell(df, r, 6)),
                "area": _num(_cell(df, r, 7)),
            }
        )
    return groups


def _looks_aggregated(rows: list[dict[str, Any]]) -> bool:
    if len(rows) < 2:
        return True
    keys = [row.get("normalized_article") for row in rows]
    return len(set(keys)) == len(keys)


def _parse_specification_sheet(df: pd.DataFrame) -> list[dict[str, Any]]:
    header = _find_header_row(df, ("ROLL", "PRODUCT", "METERS", "WIDTH"))
    if header is None:
        header = _find_header_row(df, ("ART", "PRODUCT", "METERS", "CUSTOMS"))
    if header is None:
        header = 6
    rolls: list[dict[str, Any]] = []
    for r in range(header + 1, len(df)):
        product = _text(_cell(df, r, 2))
        if not product:
            continue
        if product.upper().startswith("TOTAL"):
            break
        roll = {
            "row_index": r,
            "roll_no": _text(_cell(df, r, 0)) or None,
            "date": _text(_cell(df, r, 1)) or None,
            "article": product,
            "normalized_article": normalize_article(product),
            "design_family": _design_family(product),
            "lot_no": _text(_cell(df, r, 3)) or None,
            "price": _num(_cell(df, r, 4)),
            "meters": _num(_cell(df, r, 5)),
            "width": _num(_cell(df, r, 6)),
            "area": _num(_cell(df, r, 7)),
            "net_weight": _num(_cell(df, r, 8)),
            "gross_weight": _num(_cell(df, r, 9)),
            "description": _text(_cell(df, r, 10)) or None,
        }
        if roll["area"] is None and roll["meters"] is not None and roll["width"] is not None:
            roll["area"] = round(float(roll["meters"]) * float(roll["width"]), 3)
            roll["area_calculated"] = True
        rolls.append(roll)
    return rolls


def parse_specification(path: str | Path) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    best: list[dict[str, Any]] = []
    extras: list[dict[str, Any]] = []
    for _name, df in _iter_excel_sheets(path):
        rolls = _parse_specification_sheet(df)
        if len(rolls) > len(best):
            extras.extend(best)
            best = rolls
        else:
            extras.extend(rolls)
    rolls = _merge_unique(best, extras, "normalized_article") if _looks_aggregated(best) else best
    # Roll-level spec: keep the richest sheet only so meters are not doubled
    if not _looks_aggregated(best):
        rolls = best
    aggregates: dict[str, dict[str, Any]] = {}
    for roll in rolls:
        key = roll["normalized_article"]
        agg = aggregates.setdefault(
            key,
            {
                "article": roll["article"],
                "normalized_article": key,
                "design_family": roll["design_family"],
                "rolls": 0,
                "meters": 0.0,
                "area": 0.0,
                "net_weight": 0.0,
                "gross_weight": 0.0,
                "price": None,
                "width": None,
            },
        )
        agg["rolls"] += 1
        agg["meters"] += float(roll["meters"] or 0)
        agg["area"] += float(roll["area"] or 0)
        agg["net_weight"] += float(roll["net_weight"] or 0)
        agg["gross_weight"] += float(roll["gross_weight"] or 0)
        if roll["price"] is not None:
            agg["price"] = roll["price"]
        if roll["width"] is not None:
            agg["width"] = roll["width"]

    for agg in aggregates.values():
        agg["meters"] = round(agg["meters"], 4)
        agg["area"] = round(agg["area"], 4)
        agg["net_weight"] = round(agg["net_weight"], 4)
        agg["gross_weight"] = round(agg["gross_weight"], 4)

    return rolls, aggregates


def parse_bundle(paths: list[str | Path]) -> Parsed18233Bundle:
    by_kind: dict[str, Path] = {}
    for path in paths:
        p = Path(path)
        name = p.name.upper()
        if "INVOICE" in name or "ИНВОЙС" in name:
            by_kind["invoice"] = p
        elif "-PL" in name or "PACKING" in name or name.endswith("PL.XLSX") or "ПАКИНГ" in name:
            by_kind["packing"] = p
        elif "SPEC" in name or "СПЕЦИФ" in name:
            by_kind["specification"] = p

    bundle = Parsed18233Bundle(subkit=detect_subkit(paths))
    if "invoice" in by_kind:
        bundle.invoice_rows, bundle.header_hints = parse_invoice(by_kind["invoice"])
    if "packing" in by_kind:
        bundle.packing_groups = parse_packing_list(by_kind["packing"])
    if "specification" in by_kind:
        bundle.spec_rolls, bundle.spec_aggregates = parse_specification(by_kind["specification"])
    return bundle


def _nearly_equal(a: Any, b: Any, tol: float = 0.05) -> bool:
    if a is None or b is None:
        return a is b
    try:
        return abs(float(a) - float(b)) <= tol
    except (TypeError, ValueError):
        return str(a).strip().upper() == str(b).strip().upper()


def _compare(
    item: ReconciledItem,
    field_name: str,
    left: Any,
    right: Any,
    left_name: str,
    right_name: str,
) -> None:
    if left is None or right is None:
        if left is None and right is None:
            return
        item.flags.append(
            ValidationFlag(
                field_name=field_name,
                error_type=ErrorType.MISSING_PAIR,
                severity=ErrorSeverity.YELLOW,
                details={left_name: left, right_name: right},
                message=f"Пустое значение «{field_name}» в {left_name if left is None else right_name}",
            )
        )
        return
    if not _nearly_equal(left, right):
        item.flags.append(
            ValidationFlag(
                field_name=field_name,
                error_type=ErrorType.MISMATCH,
                severity=ErrorSeverity.RED,
                details={left_name: left, right_name: right},
                message=f"Расхождение «{field_name}»: {left_name}={left}, {right_name}={right}",
            )
        )


def reconcile_18233(bundle: Parsed18233Bundle) -> list[ReconciledItem]:
    import json
    from pathlib import Path

    ref_path = Path(__file__).resolve().parent / "data" / "reference_18233.json"
    reference: dict[str, dict] = {}
    if ref_path.exists():
        reference = json.loads(ref_path.read_text(encoding="utf-8"))

    items: list[ReconciledItem] = []
    inv_by_key = {normalize_article(r["article"]): r for r in bundle.invoice_rows}
    spec_by_key = bundle.spec_aggregates
    pl_by_family: dict[str, list[dict[str, Any]]] = {}
    for g in bundle.packing_groups:
        pl_by_family.setdefault(g["normalized_family"], []).append(g)

    # Preserve Invoice order (acceptance order), then any Spec-only leftovers
    ordered_keys: list[str] = [normalize_article(r["article"]) for r in bundle.invoice_rows]
    for key in spec_by_key:
        if key not in ordered_keys:
            ordered_keys.append(key)

    for key in ordered_keys:
        inv = inv_by_key.get(key)
        spec = spec_by_key.get(key)
        article = (inv or spec or {}).get("article") or key
        item = ReconciledItem(
            article=article,
            model=article,
            normalized_article=key,
            invoice_subkit=bundle.subkit,
        )
        if inv:
            item.source_traces["invoice"] = inv
            item.commercial_data.update(
                {
                    "qty": inv.get("meters"),
                    "unit": inv.get("unit") or "meters",
                    "price": inv.get("price"),
                    "amount": inv.get("amount"),
                    "currency": "CNY",
                    "invoice_subkit": bundle.subkit,
                }
            )
            item.packing_data.update(
                {
                    "rolls": inv.get("rolls"),
                    "meters": inv.get("meters"),
                    "area": inv.get("area"),
                    "width": inv.get("width"),
                }
            )
            item.customs_data["hs_code"] = inv.get("hs_code")
        if spec:
            item.source_traces["specification"] = {
                k: v for k, v in spec.items() if k != "raw"
            }
            item.packing_data["rolls"] = item.packing_data.get("rolls") or spec.get("rolls")
            _fill = item.packing_data
            for field_name in ("meters", "area", "width", "net_weight", "gross_weight"):
                if _fill.get(field_name) in (None, "") and spec.get(field_name) not in (None, ""):
                    _fill[field_name] = spec.get(field_name)
            # эталон uses 2 decimal weights
            if _fill.get("net_weight") is not None:
                _fill["net_weight"] = round(float(_fill["net_weight"]), 2)
            if _fill.get("gross_weight") is not None:
                _fill["gross_weight"] = round(float(_fill["gross_weight"]), 2)
            if item.commercial_data.get("price") is None:
                item.commercial_data["price"] = spec.get("price")
            if item.commercial_data.get("amount") is None and item.commercial_data.get("price") and (
                item.packing_data.get("meters") or spec.get("meters")
            ):
                meters = float(item.packing_data.get("meters") or spec.get("meters") or 0)
                item.commercial_data["amount"] = round(
                    meters * float(item.commercial_data["price"]), 2
                )
                item.commercial_data["amount_calculated"] = True

        # Reference fill from эталон (exact article only) — operator may still override
        ref = reference.get(key)
        if ref:
            item.source_traces["reference"] = ref
            if not item.customs_data.get("tnved_code"):
                item.customs_data["tnved_code"] = ref.get("tnved_code")
            if not item.customs_data.get("description"):
                item.customs_data["description"] = ref.get("description")
            if not item.customs_data.get("country"):
                item.customs_data["country"] = ref.get("country")
            if not item.customs_data.get("manufacturer"):
                item.customs_data["manufacturer"] = ref.get("manufacturer")
            if not item.customs_data.get("hs_code") and ref.get("hs_code"):
                item.customs_data["hs_code"] = ref.get("hs_code")
        else:
            item.flags.append(
                ValidationFlag(
                    field_name="tnved_code",
                    error_type=ErrorType.CATALOG_NOT_FOUND,
                    severity=ErrorSeverity.YELLOW,
                    details={"normalized_article": key},
                    message="Нет эталонного описания/ТН ВЭД — заполните вручную",
                )
            )

        if not item.customs_data.get("tnved_code"):
            item.flags.append(
                ValidationFlag(
                    field_name="tnved_code",
                    error_type=ErrorType.MISSING_PAIR,
                    severity=ErrorSeverity.YELLOW,
                    details={},
                    message="Пустой таможенный код",
                )
            )
        if not (
            item.customs_data.get("description")
            or item.customs_data.get("description_ru")
            or item.customs_data.get("description_en")
        ):
            item.flags.append(
                ValidationFlag(
                    field_name="description",
                    error_type=ErrorType.MISSING_PAIR,
                    severity=ErrorSeverity.YELLOW,
                    details={},
                    message="Пустое описание товара",
                )
            )

        family = _design_family(article)
        pl_groups = pl_by_family.get(family) or []
        if pl_groups:
            # store merged group for export when multiple PL lines share family (Magic)
            if len(pl_groups) == 1:
                item.source_traces["packing_list_group"] = pl_groups[0]
            else:
                merged = {
                    "design": pl_groups[0].get("design"),
                    "design_family": family,
                    "normalized_family": family,
                    "gm": pl_groups[0].get("gm"),
                    "rolls": sum(float(g.get("rolls") or 0) for g in pl_groups),
                    "meters": sum(float(g.get("meters") or 0) for g in pl_groups),
                    "net_weight": sum(float(g.get("net_weight") or 0) for g in pl_groups),
                    "gross_weight": sum(float(g.get("gross_weight") or 0) for g in pl_groups),
                    "area": sum(float(g.get("area") or 0) for g in pl_groups),
                    "parts": pl_groups,
                }
                item.source_traces["packing_list_group"] = merged

        if inv and spec:
            _compare(item, "rolls", inv.get("rolls"), spec.get("rolls"), "invoice", "specification")
            _compare(item, "meters", inv.get("meters"), spec.get("meters"), "invoice", "specification")
            _compare(item, "width", inv.get("width"), spec.get("width"), "invoice", "specification")
            _compare(item, "area", inv.get("area"), spec.get("area"), "invoice", "specification")
            if inv.get("price") is not None and spec.get("price") is not None:
                _compare(item, "price", inv.get("price"), spec.get("price"), "invoice", "specification")
        elif inv and not spec:
            item.flags.append(
                ValidationFlag(
                    field_name="article",
                    error_type=ErrorType.MISSING_PAIR,
                    severity=ErrorSeverity.YELLOW,
                    details={"missing_in": "specification"},
                    message="Позиция есть в Invoice, нет в Specification",
                )
            )
        elif spec and not inv:
            item.flags.append(
                ValidationFlag(
                    field_name="article",
                    error_type=ErrorType.MISSING_PAIR,
                    severity=ErrorSeverity.YELLOW,
                    details={"missing_in": "invoice"},
                    message="Позиция есть в Specification, нет в Invoice",
                )
            )

        items.append(item)

    family_items: dict[str, list[ReconciledItem]] = {}
    for item in items:
        family_items.setdefault(_design_family(item.article or item.normalized_article), []).append(item)

    for family, group_items in family_items.items():
        pl_groups = pl_by_family.get(family) or []
        if not pl_groups:
            for item in group_items:
                item.flags.append(
                    ValidationFlag(
                        field_name="design_family",
                        error_type=ErrorType.MISSING_PAIR,
                        severity=ErrorSeverity.YELLOW,
                        details={"family": family},
                        message=f"Нет группы Packing List для семейства {family}",
                    )
                )
            continue
        pl = {
            "rolls": sum(float(g.get("rolls") or 0) for g in pl_groups),
            "meters": sum(float(g.get("meters") or 0) for g in pl_groups),
            "area": sum(float(g.get("area") or 0) for g in pl_groups),
            "net_weight": sum(float(g.get("net_weight") or 0) for g in pl_groups),
            "gross_weight": sum(float(g.get("gross_weight") or 0) for g in pl_groups),
        }
        sums = {
            "rolls": sum(float((i.packing_data or {}).get("rolls") or 0) for i in group_items),
            "meters": sum(float((i.packing_data or {}).get("meters") or 0) for i in group_items),
            "area": sum(float((i.packing_data or {}).get("area") or 0) for i in group_items),
            "net_weight": sum(float((i.packing_data or {}).get("net_weight") or 0) for i in group_items),
            "gross_weight": sum(float((i.packing_data or {}).get("gross_weight") or 0) for i in group_items),
        }
        for field_name in ("rolls", "meters", "area", "net_weight", "gross_weight"):
            left = pl.get(field_name)
            right = round(sums[field_name], 4)
            if left is None:
                continue
            if not _nearly_equal(left, right, tol=0.1):
                for item in group_items:
                    item.flags.append(
                        ValidationFlag(
                            field_name=field_name,
                            error_type=ErrorType.MISMATCH,
                            severity=ErrorSeverity.RED,
                            details={
                                "packing_list": left,
                                "spec_family_sum": right,
                                "family": family,
                            },
                            message=(
                                f"Сумма Specification по семейству {family} "
                                f"не сходится с Packing List по «{field_name}»"
                            ),
                        )
                    )

    for fam, groups in pl_by_family.items():
        if fam not in family_items:
            orphan = ReconciledItem(
                article=groups[0].get("design"),
                model=None,
                normalized_article=fam,
                invoice_subkit=bundle.subkit,
                source_traces={"packing_list_group": groups[0]},
            )
            orphan.flags.append(
                ValidationFlag(
                    field_name="article",
                    error_type=ErrorType.MISSING_PAIR,
                    severity=ErrorSeverity.YELLOW,
                    details={"family": fam},
                    message="Группа Packing List без позиций Invoice/Specification",
                )
            )
            items.append(orphan)

    return items
