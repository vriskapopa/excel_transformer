from __future__ import annotations

import re
from typing import Any, Iterable

import pandas as pd

from app.parsing.normalize import normalize_text
from app.parsing.table_rows import lines_from_matrix

ARTICLE_HEADERS = (
    "articule",
    "articul",
    "article",
    "art.",
    "art",
    "артикул",
    "арт",
    "model",
    "модель",
    "design",
    "дизайн",
    "product name",
    "product",
    "наименование",
    "item no",
    "item no.",
    "item number",
    "style",
    "sku",
    "код",
)

HEADER_SCAN_ROWS = 30


def _cell_str(value: Any) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    return normalize_text(str(value))


def _header_key(value: Any) -> str:
    return _cell_str(value).lower()


def detect_header_row(rows: list[list[Any]]) -> int | None:
    best_idx: int | None = None
    best_hits = 0
    limit = min(len(rows), HEADER_SCAN_ROWS)
    for idx in range(limit):
        keys = [_header_key(cell) for cell in rows[idx]]
        hits = 0
        joined = " | ".join(keys)
        for header in ARTICLE_HEADERS:
            if any(header == key or header in key for key in keys) or header in joined:
                hits += 1
        extra = ("qty", "quantity", "price", "amount", "weight", "hs", "tn")
        hits += sum(1 for token in extra if any(token in key for key in keys))
        if hits > best_hits:
            best_hits = hits
            best_idx = idx
    if best_hits < 1:
        return None
    return best_idx


def _unique_columns(headers: Iterable[Any]) -> list[str]:
    seen: dict[str, int] = {}
    result: list[str] = []
    for raw in headers:
        base = _header_key(raw) or "column"
        n = seen.get(base, 0)
        seen[base] = n + 1
        result.append(base if n == 0 else f"{base}_{n+1}")
    return result


def _article_rank(key: str) -> int | None:
    lowered = key.lower()
    if "price" in lowered or "cart" in lowered:
        return None
    if "артикул" in lowered or "articul" in lowered:
        return 0
    if re.search(r"(^|[^a-zа-я])article([^a-zа-я]|$)", lowered) and "name" not in lowered:
        return 1
    if any(token in lowered for token in ("sku", "item no", "style")) or lowered.strip() in {
        "art",
        "art.",
        "арт",
    }:
        return 2
    if "design" in lowered or "дизайн" in lowered:
        return 3
    if "product name" in lowered or "наименование" in lowered or lowered.strip() == "product":
        return 5
    return None


def _pick_article(row: dict[str, Any]) -> tuple[str | None, str | None]:
    article = None
    article_rank = 99
    model = None
    for key, value in row.items():
        text = _cell_str(value)
        if not text:
            continue
        lowered = key.lower()
        rank = _article_rank(key)
        if rank is not None and rank < article_rank:
            article = text
            article_rank = rank
        if "model" in lowered or "модель" in lowered:
            if model is None:
                model = text
    if article is None and model is not None:
        article = model
    return article, model


def dataframe_to_lines(
    frame: pd.DataFrame,
    *,
    sheet_name: str,
    header_row: int | None = None,
) -> list[dict[str, Any]]:
    if frame.empty:
        return []
    raw_rows = frame.where(pd.notna(frame), None).values.tolist()
    return lines_from_matrix(raw_rows, sheet_name=sheet_name, header_row=header_row)


def read_excel(path: str) -> tuple[list[str], list[dict[str, Any]], str]:
    """Read all sheets. Returns sheet names, parsed line dicts, concatenated preview text."""
    book = pd.read_excel(path, sheet_name=None, header=None, dtype=object, engine=None)
    sheets = list(book.keys())
    lines: list[dict[str, Any]] = []
    preview_chunks: list[str] = []

    for sheet_name, frame in book.items():
        preview_chunks.append(sheet_name)
        sample = frame.head(40).fillna("").astype(str)
        preview_chunks.append(" ".join(sample.to_numpy().ravel().tolist()))
        lines.extend(dataframe_to_lines(frame, sheet_name=str(sheet_name)))

    return sheets, lines, "\n".join(preview_chunks)
