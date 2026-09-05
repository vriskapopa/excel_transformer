"""Map heterogeneous Excel column names to canonical fields.

Strict article matching only — column synonyms are for extraction, not for
merging positions by meaning (Word spec §2, §6).
"""

from __future__ import annotations

import re
from typing import Any

from app.parsing.normalize import normalize_text

# Canonical key -> accepted header fragments (lowercase)
COLUMN_ALIASES: dict[str, tuple[str, ...]] = {
    "article": (
        "артикул",
        "articul",
        "article",
        "арт",
        "art.",
        "sku",
        "item no",
        "item code",
        "item",
        "part no",
        "part number",
        "style",
        "design",
        "дизайн",
        "код товара",
        "stok kodu",
        "musteri kodu",
        "müşteri kodu",
        "malzeme",
        "货号",
        "品号",
    ),
    "model": ("model", "модель", "design", "дизайн"),
    "color": ("color", "colour", "цвет", "renk"),
    "qty": ("qty", "quantity", "кол-во", "количество", "pcs", "шт", "miktar", "adet", "数量", "件数"),
    "unit": ("unit", "uom", "ед", "единица", "birim"),
    "price": ("unit price", "per meter", "за пог", "price", "цена", "birim fiyat", "fiyat", "单价", "unit $"),
    "amount": ("total price", "amount", "сумма", "total", "tutar", "金额", "line total", "line $"),
    "currency": ("currency", "валюта", "ccy"),
    "rolls": ("number of rolls", "rolls", "roll", "рулонов", "рулон"),
    "boxes": ("boxes", "box", "cartons", "carton", "короб", "мест"),
    "meters": ("погонных метров", "meters", "metres", "meter", "пог", "м.п", "мп", "length"),
    "area": ("кв.м", "area", "м²", "m2", "sqm", "площад"),
    "width": ("widht", "width", "ширина"),
    "net_weight": ("net weight", "n.w", "nw", "нетто", "net wt"),
    "gross_weight": ("gross weight", "g.w", "gw", "брутто", "gross wt"),
    "volume": ("volume", "cbm", "объем", "объём", "м³"),
    "hs_code": ("hs-code", "hs code", "гармонизир", "hs", "h.s"),
    "tnved_code": ("customs code", "таможенный код", "tn ved", "tnved", "тн вэд", "тнвэд", "код тн"),
    "description_en": ("description en", "description (en)", "desc en", "english"),
    "description_ru": ("description ru", "description (ru)", "desc ru", "russian"),
    "description": ("product name", "наименование товара", "наименование", "description", "описание", "goods"),
    "country": ("country", "страна", "origin"),
    "manufacturer": ("manufacturer", "maker", "изготовитель", "производитель"),
    "brand": ("brand", "trade mark", "марка", "бренд"),
}

_NUMERIC_FIELDS = {
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
    "volume",
}


_US_MONEY = re.compile(r"^-?\d{1,3}(,\d{3})+(\.\d+)?$")
_EU_MONEY = re.compile(r"^-?\d{1,3}(\.\d{3})+(,\d+)$")


def parse_number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = normalize_text(str(value)).replace("\u00a0", "").replace(" ", "")
    if not text:
        return None
    if _US_MONEY.match(text):
        text = text.replace(",", "")
    elif _EU_MONEY.match(text):
        text = text.replace(".", "").replace(",", ".")
    elif text.count(",") == 1 and text.count(".") == 0:
        text = text.replace(",", ".")
    try:
        return float(text)
    except ValueError:
        return None


def is_numeric_token(value: Any) -> bool:
    if isinstance(value, bool):
        return False
    if isinstance(value, (int, float)):
        return True
    text = normalize_text(str(value))
    if not text or any(ch.isalpha() for ch in text):
        return False
    return parse_number(text) is not None


def _to_float(value: Any) -> float | None:
    return parse_number(value)


def classify_header(header: str) -> str | None:
    """Pick the most specific canonical field for a column title."""
    h = normalize_text(header).lower()
    if not h or h.startswith("column"):
        return None
    if "артикул" in h or "articul" in h:
        return "article"
    if any(tok in h for tok in ("stok kodu", "müşteri kodu", "musteri kodu", "货号", "品号", "desing", "desen adi", "desen adı")):
        return "article"
    if re.search(r"(^|[^a-z])(design|desen)([^a-z]|$)", h) and "code" not in h:
        return "article"
    if re.search(r"(^|[^a-z])article([^a-z]|$)", h) and "name" not in h:
        return "article"
    if "product name" in h or "наименование товара" in h:
        return "description"
    if "номер рулона" in h or "rulon" in h or "roll no" in h or "roll nr" in h:
        return None
    if "number of rolls" in h or "количество рулон" in h or re.search(r"\brolls\b", h):
        return "rolls"
    if "погонных метров" in h or "q-ty meters" in h or "metres" in h or "meters" in h:
        return "meters"
    if "amount (m)" in h or h.strip() in {"amount (m)", "nett", "brutt"}:
        if "kg" in h or h.strip() in {"nett", "nett kg"}:
            return "net_weight"
        if "brutt" in h or "gross" in h:
            return "gross_weight"
        return "meters"
    if h.strip() in {"код", "тнвэд", "tnved"}:
        return "tnved_code"
    if "nett" in h and "kg" in h:
        return "net_weight"
    if "ширина" in h or "widht" in h or "width" in h:
        return "width"
    if "кв.м" in h or "q-ty m2" in h or "м²" in h or "area" in h:
        return "area"
    if "total price" in h or "цена, долл" in h or "сумма" in h or "tutar" in h or "金额" in h:
        return "amount"
    if "per meter" in h or "за пог" in h or "unit price" in h or "birim fiyat" in h or "单价" in h:
        return "price"
    if "miktar" in h or "adet" in h or "数量" in h:
        return "qty"
    if h in {"fiyat", "price $", "unit $", "usd"} or (("$" in h or "€" in h) and "total" not in h and "amount" not in h):
        return "price"
    if "нетто" in h or "n.w" in h or "net weight" in h:
        return "net_weight"
    if "брутто" in h or "g.w" in h or "gross weight" in h:
        return "gross_weight"
    if "таможенный код" in h or "customs code" in h or "тн вэд" in h:
        return "tnved_code"
    if "hs-code" in h or "hs code" in h or "гармонизир" in h:
        return "hs_code"
    if "наименование" in h and "артикул" not in h:
        return "description"

    best: tuple[int, str] | None = None
    for canonical, aliases in COLUMN_ALIASES.items():
        for alias in aliases:
            if alias in h:
                score = len(alias)
                if best is None or score > best[0]:
                    best = (score, canonical)
    return best[1] if best else None


def map_row(raw: dict[str, Any]) -> dict[str, Any]:
    """Extract canonical fields from a raw parsed row dict."""
    mapped: dict[str, Any] = {}
    for key, value in raw.items():
        header = normalize_text(str(key)).lower()
        if not header:
            continue
        canonical = classify_header(header)
        if canonical is None:
            continue
        if canonical in mapped and mapped[canonical] not in (None, ""):
            continue
        if canonical in _NUMERIC_FIELDS:
            mapped[canonical] = _to_float(value)
        else:
            text = normalize_text(str(value)) if value is not None else ""
            mapped[canonical] = text or None
    if not mapped.get("article") and mapped.get("model"):
        mapped["article"] = mapped["model"]
    color = mapped.get("color")
    article = mapped.get("article")
    if article and color and re.fullmatch(r"\d{1,4}", str(color).strip()) and not re.search(r"\d", str(article)):
        mapped["article"] = f"{article} {int(color):02d}"
    return mapped
