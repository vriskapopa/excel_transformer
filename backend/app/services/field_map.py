"""Map heterogeneous Excel column names to canonical fields.

Strict article matching only — column synonyms are for extraction, not for
merging positions by meaning (Word spec §2, §6).
"""

from __future__ import annotations

from typing import Any

from app.parsing.normalize import normalize_text

# Canonical key -> accepted header fragments (lowercase)
COLUMN_ALIASES: dict[str, tuple[str, ...]] = {
    "article": ("article", "артикул", "арт", "art.", "art ", "sku", "item no", "style", "design", "дизайн", "product name", "product", "наименование"),
    "model": ("model", "модель", "design", "дизайн"),
    "color": ("color", "colour", "цвет"),
    "qty": ("qty", "quantity", "кол-во", "количество", "pcs", "шт"),
    "unit": ("unit", "uom", "ед", "единица"),
    "price": ("unit price", "price", "цена"),
    "amount": ("amount", "сумма", "total"),
    "currency": ("currency", "валюта", "ccy"),
    "rolls": ("rolls", "roll", "рулон"),
    "boxes": ("boxes", "box", "cartons", "carton", "короб", "мест"),
    "meters": ("meters", "metres", "meter", "пог", "м.п", "мп", "length"),
    "area": ("area", "м²", "m2", "sqm", "площад"),
    "width": ("width", "ширина"),
    "net_weight": ("net weight", "n.w", "nw", "нетто", "net wt"),
    "gross_weight": ("gross weight", "g.w", "gw", "брутто", "gross wt"),
    "volume": ("volume", "cbm", "объем", "объём", "м³"),
    "hs_code": ("hs code", "hs", "h.s"),
    "tnved_code": ("tn ved", "tnved", "тн вэд", "тнвэд", "customs code", "код тн"),
    "description_en": ("description en", "description (en)", "desc en", "english"),
    "description_ru": ("description ru", "description (ru)", "desc ru", "russian", "наименование"),
    "description": ("description", "описание", "наименование товара", "goods"),
    "country": ("country", "страна", "origin"),
    "manufacturer": ("manufacturer", "maker", "изготовитель", "производитель"),
    "brand": ("brand", "trade mark", "марка", "бренд"),
}


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = normalize_text(str(value)).replace(" ", "").replace(",", ".")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def map_row(raw: dict[str, Any]) -> dict[str, Any]:
    """Extract canonical fields from a raw parsed row dict."""
    mapped: dict[str, Any] = {}
    for key, value in raw.items():
        header = normalize_text(str(key)).lower()
        if not header:
            continue
        for canonical, aliases in COLUMN_ALIASES.items():
            if canonical in mapped and mapped[canonical] not in (None, ""):
                continue
            if any(alias in header for alias in aliases):
                if canonical in {
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
                }:
                    mapped[canonical] = _to_float(value)
                else:
                    text = normalize_text(str(value)) if value is not None else ""
                    mapped[canonical] = text or None
                break
    return mapped
