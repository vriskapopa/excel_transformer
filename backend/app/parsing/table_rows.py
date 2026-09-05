"""Turn any table (Excel / PDF / markdown) into product lines."""

from __future__ import annotations

import re
from typing import Any

from app.parsing.normalize import normalize_article, normalize_text
from app.parsing.product_row import is_junk_text, is_plausible_article, numbers_look_like_product
from app.services.field_map import classify_header, is_numeric_token, map_row, parse_number

NUMERIC_KEYS = (
    "qty",
    "price",
    "amount",
    "rolls",
    "boxes",
    "meters",
    "area",
    "width",
    "net_weight",
    "gross_weight",
)

HEADER_HINTS = (
    "артикул",
    "articul",
    "article",
    "sku",
    "item",
    "design",
    "дизайн",
    "product",
    "qty",
    "quantity",
    "price",
    "цена",
    "amount",
    "сумма",
    "weight",
    "вес",
    "нетто",
    "брутто",
    "hs",
    "наименование",
    "модель",
    "model",
    "code",
    "код",
    "meter",
    "рулон",
    "width",
    "ширина",
    "miktar",
    "fiyat",
    "tutar",
    "adet",
    "stok",
    "malzeme",
    "货号",
    "数量",
    "单价",
    "金额",
    "desing",
    "desen",
    "renk",
)

_DATE_RE = re.compile(r"^\d{1,2}[./-]\d{1,2}([./-]\d{2,4})?$")
_QTY_PRICE_LINE = re.compile(
    r"(?im)^\s*(?P<article>[A-Z][A-Za-z0-9._/-]{1,24}(?:[ -]\d{2,5})?)\s+"
    r"(?P<qty>\d{1,3}(?:[.,]\d{3})+(?:[.,]\d+)?|\d+[.,]\d+|\d+)\s+"
    r"(?:MT\.?|MTS|PCS|KG|M\.)?\s*"
    r"(?P<price>\d+[.,]\d+)\s*(?:USD|EUR|US\$|\$)"
)
_METERS_LINE = re.compile(
    r"(?im)(?P<qty>\d+[.,]\d+|\d+)\s+METERS\s+(?P<article>[A-Z][A-Z0-9 .()/-]{2,70}?)"
    r"(?:\s+\d{6,12})?\s+(?P<price>\d+[.,]\d+)"
)
_SKIP_PLAINTEXT = (
    "invoice no",
    "page ",
    "tel:",
    "fax:",
    "e-mail",
    "email",
    "swift",
    "iban",
    "vat no",
    "продавец",
    "покупатель",
    "consignee",
    "shipper",
    "bank name",
    "post code",
    "zip code",
)


def _cell(value: Any) -> str:
    if value is None:
        return ""
    return normalize_text(str(value))


def header_score(cells: list[Any]) -> int:
    blob = " ".join(_cell(c).lower() for c in cells)
    if not blob.strip():
        return 0
    hits = sum(1 for hint in HEADER_HINTS if hint in blob)
    if "price" in blob or "цена" in blob or "fiyat" in blob or "单价" in blob:
        hits += 2
    if "артикул" in blob or "article" in blob or "sku" in blob or "货号" in blob:
        hits += 2
    return hits


def best_header_index(rows: list[list[Any]], *, scan: int = 45) -> int | None:
    best_i = None
    best = 0
    for idx, row in enumerate(rows[:scan]):
        score = header_score(row)
        if score > best:
            best = score
            best_i = idx
    return best_i if best >= 1 else None


def has_numeric_fields(mapped: dict[str, Any]) -> bool:
    return any(isinstance(mapped.get(key), (int, float)) for key in NUMERIC_KEYS)


def _close_amount(left: float, right: float) -> bool:
    return abs(left - right) <= max(0.05, 0.08 * max(abs(right), 1e-6))


def assign_numbers(mapped: dict[str, Any], nums: list[float]) -> None:
    nums = [n for n in nums if n is not None]
    if not nums:
        return
    qty = price = amount = meters = None
    if len(nums) >= 4:
        q, meters_or_price, p, total = nums[0], nums[1], nums[2], nums[3]
        if _close_amount(meters_or_price * p, total):
            qty, meters, price, amount = q, meters_or_price, p, total
        elif _close_amount(q * p, total):
            qty, price, amount = q, p, total
        else:
            qty, price, amount = q, meters_or_price, p
    elif len(nums) == 3:
        qty, price, amount = nums[0], nums[1], nums[2]
    elif len(nums) == 2:
        qty, price = nums[0], nums[1]
    else:
        qty = nums[0]

    if mapped.get("qty") is None and qty is not None:
        mapped["qty"] = qty
    if mapped.get("price") is None and price is not None:
        mapped["price"] = price
    if mapped.get("amount") is None and amount is not None:
        mapped["amount"] = amount
    if mapped.get("meters") is None and meters is not None:
        mapped["meters"] = meters


def enrich_mapped(raw: dict[str, Any], mapped: dict[str, Any]) -> dict[str, Any]:
    """Fill article / qty / price when column titles are missing or unknown."""
    mapped = dict(mapped)
    texts: list[str] = []
    nums: list[float] = []
    for key, value in raw.items():
        header = _cell(key).lower()
        if header and classify_header(header):
            continue
        text = _cell(value)
        if not text:
            continue
        if is_numeric_token(value) and not _DATE_RE.match(text.replace(" ", "")):
            num = parse_number(value)
            if num is not None:
                nums.append(num)
            continue
        if not is_junk_text(text) and not text.endswith(":"):
            texts.append(text)

    if not mapped.get("article") and texts:
        ranked = sorted(texts, key=lambda item: (len(item), item))
        mapped["article"] = next(
            (item for item in ranked if any(ch.isdigit() for ch in item) and any(ch.isalpha() for ch in item)),
            ranked[0],
        )

    if not has_numeric_fields(mapped):
        assign_numbers(mapped, nums)
    return mapped


def pick_article(raw: dict[str, Any], mapped: dict[str, Any]) -> str:
    for key in ("article", "model"):
        text = _cell(mapped.get(key))
        if text and not is_junk_text(text):
            return text
    ranked: list[tuple[int, str]] = []
    for col, value in raw.items():
        text = _cell(value)
        if not text or is_junk_text(text):
            continue
        if text.replace(" ", "").replace(".", "").replace(",", "").isdigit():
            continue
        lowered = str(col).lower()
        rank = 50
        if any(tok in lowered for tok in ("артикул", "articul", "article", "sku", "item no", "style", "stok", "desing", "desen")):
            rank = 0
        elif "design" in lowered or "дизайн" in lowered or "model" in lowered or "renk" in lowered:
            rank = 1
        elif "product" in lowered or "наименование" in lowered or "desc" in lowered:
            rank = 3
        ranked.append((rank, text))
    if not ranked:
        desc = _cell(mapped.get("description"))
        return desc if desc and not is_junk_text(desc) else ""
    ranked.sort()
    return ranked[0][1]


def is_usable_row(article: str, mapped: dict[str, Any]) -> bool:
    label = (article or "").strip().upper()
    if label.startswith(("TOTAL", "ИТОГО", "СУММА", "GRAND TOTAL", "GENEL")):
        return False
    if article and any(
        tok in article.lower()
        for tok in ("директор", "director", "swift", "iban", "генеральн", "продавец", "покупатель")
    ):
        return False
    if article and not is_plausible_article(article):
        return False
    if not numbers_look_like_product(mapped):
        return False
    if has_numeric_fields(mapped):
        return True
    if article and (mapped.get("tnved_code") or mapped.get("hs_code")):
        return True
    return False


def build_line(
    raw: dict[str, Any],
    *,
    sheet_name: str,
    row_index: int,
) -> dict[str, Any] | None:
    mapped = enrich_mapped(raw, map_row(raw))
    article = pick_article(raw, mapped) or _cell(mapped.get("article"))
    color = mapped.get("color")
    if article and color and re.fullmatch(r"\d{1,4}", str(color).strip()) and not re.search(r"\d", article):
        article = f"{article} {int(color):02d}"
        mapped["article"] = article
    if not is_usable_row(article, mapped):
        return None
    if not article:
        article = f"позиция {row_index}"
    stored = dict(raw)
    for key, value in mapped.items():
        if value is not None and value != "":
            stored[key] = value
    return {
        "row_index": row_index,
        "sheet_name": sheet_name,
        "article": article,
        "model": mapped.get("model"),
        "normalized_article": normalize_article(article),
        "raw": stored,
    }


def unique_columns(headers: list[Any]) -> list[str]:
    seen: dict[str, int] = {}
    columns: list[str] = []
    for raw in headers:
        base = _cell(raw).lower() or "column"
        n = seen.get(base, 0)
        seen[base] = n + 1
        columns.append(base if n == 0 else f"{base}_{n+1}")
    return columns


def lines_from_matrix(
    rows: list[list[Any]],
    *,
    sheet_name: str,
    header_row: int | None = None,
) -> list[dict[str, Any]]:
    if not rows:
        return []
    if header_row is None:
        header_row = best_header_index(rows)
    if header_row is None:
        columns = [f"column_{i+1}" for i in range(max(len(r) for r in rows))]
        body = rows
        start = 0
    else:
        columns = unique_columns(rows[header_row])
        body = rows[header_row + 1 :]
        start = header_row + 1
        if body and header_score(body[0]) >= 1:
            numeric = sum(1 for cell in body[0] if is_numeric_token(cell))
            if numeric <= 1:
                body = body[1:]
                start += 1

    lines: list[dict[str, Any]] = []
    for offset, values in enumerate(body):
        if not any(_cell(v) for v in values):
            continue
        raw = {columns[i]: (values[i] if i < len(values) else None) for i in range(len(columns))}
        line = build_line(raw, sheet_name=sheet_name, row_index=start + offset)
        if line:
            lines.append(line)
    return lines


def lines_from_plaintext(text: str, *, sheet_name: str = "text") -> list[dict[str, Any]]:
    """Last-resort parser for PDF text when table detection failed."""
    lines: list[dict[str, Any]] = []
    for idx, raw_line in enumerate(text.splitlines()):
        line = normalize_text(raw_line)
        low = line.lower()
        if len(line) < 5:
            continue
        if any(tok in low for tok in _SKIP_PLAINTEXT):
            continue
        if low.startswith(("total", "итого", "genel toplam", "grand total")):
            continue
        tokens = line.split()
        nums: list[float] = []
        words: list[str] = []
        for tok in tokens:
            if _DATE_RE.match(tok):
                continue
            if is_numeric_token(tok):
                num = parse_number(tok)
                if (
                    num is not None
                    and words
                    and float(num).is_integer()
                    and 10 <= abs(num) <= 9999
                    and len(nums) == 0
                    and any(ch.isalpha() for ch in words[-1])
                ):
                    words.append(tok)
                    continue
                if num is not None:
                    nums.append(num)
                continue
            words.append(tok)
        if len(nums) < 2 or not words:
            continue
        article = " ".join(words)
        blob = article.lower()
        if sum(1 for hint in HEADER_HINTS if hint in blob) >= 2:
            continue
        if is_junk_text(article) or len(article) > 80:
            continue
        if not any(ch.isalpha() for ch in article):
            continue
        if not any(ch.isdigit() for ch in article) and len(nums) < 3:
            continue
        raw: dict[str, Any] = {"article": article}
        assign_numbers(raw, nums)
        built = build_line(raw, sheet_name=sheet_name, row_index=idx + 1)
        if built:
            lines.append(built)
    return lines


def lines_from_qty_price_text(text: str, *, sheet_name: str = "qty_price") -> list[dict[str, Any]]:
    """Invoice-style lines: ARTICLE 1.740,82 MT. 5,78 USD or 110.60 METERS BLOOM … 5.40."""
    lines: list[dict[str, Any]] = []
    seen: set[str] = set()
    matches = list(_QTY_PRICE_LINE.finditer(text or "")) + list(_METERS_LINE.finditer(text or ""))
    for idx, match in enumerate(matches, start=1):
        article = normalize_text(match.group("article"))
        qty = parse_number(match.group("qty"))
        price = parse_number(match.group("price"))
        if not article or qty is None or price is None:
            continue
        key = normalize_article(article)
        if key in seen:
            continue
        seen.add(key)
        raw = {"article": article, "qty": qty, "price": price, "amount": round(qty * price, 2)}
        built = build_line(raw, sheet_name=sheet_name, row_index=idx)
        if built:
            lines.append(built)
    return lines


def merge_line_groups(*groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep the richest row per article; drop empty duplicates."""
    by_key: dict[str, tuple[int, dict[str, Any]]] = {}
    extras: list[dict[str, Any]] = []
    for group in groups:
        for line in group or []:
            mapped = map_row(line.get("raw") or {})
            score = sum(1 for key in NUMERIC_KEYS if isinstance(mapped.get(key), (int, float)))
            if line.get("article"):
                score += 1
            key = line.get("normalized_article") or ""
            if not key:
                extras.append(line)
                continue
            prev = by_key.get(key)
            if prev is None or score > prev[0]:
                by_key[key] = (score, line)
    ranked = sorted(by_key.values(), key=lambda item: -item[0])
    return [item[1] for item in ranked] + extras
