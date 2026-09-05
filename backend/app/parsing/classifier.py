from __future__ import annotations

import re
from pathlib import Path

from app.models.enums import DocType
from app.parsing.normalize import tokens_for_search
from app.parsing.schemas import ClassificationResult

KEYWORD_WEIGHTS: dict[DocType, tuple[tuple[str, float], ...]] = {
    DocType.INVOICE: (
        ("commercial invoice", 4.0),
        ("invoice no", 3.0),
        ("invoice", 2.5),
        ("инвойс", 3.0),
        ("счет-фактура", 3.5),
        ("счёт-фактура", 3.5),
        ("unit price", 1.5),
        ("amount", 0.8),
        ("qty", 0.5),
        ("quantity", 0.5),
        ("количество", 0.5),
        ("цена", 0.6),
        ("сумма", 0.6),
    ),
    DocType.PACKING_LIST: (
        ("packing list", 4.5),
        ("packaging list", 4.0),
        ("упаковочный лист", 4.5),
        ("packing", 2.0),
        ("net weight", 2.0),
        ("gross weight", 2.0),
        ("нетто", 1.5),
        ("брутто", 1.5),
        ("rolls", 1.2),
        ("boxes", 1.0),
        ("cartons", 1.0),
        ("volume", 0.8),
        ("cbm", 1.0),
        ("weight", 0.6),
        ("вес", 0.8),
    ),
    DocType.SPECIFICATION: (
        ("specification", 4.0),
        ("спецификация", 4.5),
        ("spec.", 1.5),
        ("color", 1.0),
        ("colour", 1.0),
        ("цвет", 1.2),
        ("composition", 1.0),
        ("состав", 1.0),
        ("width", 0.8),
        ("ширина", 0.8),
    ),
    DocType.CATALOG: (
        ("catalog", 3.5),
        ("catalogue", 3.5),
        ("справочник", 4.0),
        ("reference", 1.5),
        ("tn ved", 3.0),
        ("тн вэд", 3.5),
        ("тнвэд", 3.5),
        ("hs code", 2.0),
        ("код тн", 2.5),
    ),
    DocType.PERMIT: (
        ("permit", 3.5),
        ("разрешение", 4.0),
        ("rd document", 3.0),
        ("рд ", 1.5),
        ("сводная", 1.2),
        ("ds rd", 2.5),
        ("ss rd", 2.5),
        ("sarmant", 3.0),
        ("valid until", 1.5),
        ("действует до", 1.5),
    ),
}

_FILENAME_HINTS: dict[DocType, tuple[str, ...]] = {
    DocType.INVOICE: ("invoice", "inv", "инвойс", "счет", "счёт"),
    DocType.PACKING_LIST: ("packing", "pl", "упаков", "pack"),
    DocType.SPECIFICATION: ("spec", "специф"),
    DocType.CATALOG: ("catalog", "catalogue", "справоч", "tnved", "тнвэд", "описание"),
    DocType.PERMIT: ("permit", "rd", "разреш"),
}


def _count_phrase(blob: str, phrase: str) -> int:
    if " " in phrase or any(ord(ch) > 127 for ch in phrase):
        return blob.count(phrase)
    return len(re.findall(rf"\b{re.escape(phrase)}\b", blob))


def classify_document(
    *,
    filename: str,
    text: str,
    sheet_names: list[str] | None = None,
) -> ClassificationResult:
    """Keyword heuristic. Returns None doc_type when confidence is too low."""
    parts = [tokens_for_search(filename), tokens_for_search(text)]
    if sheet_names:
        parts.append(tokens_for_search(" ".join(sheet_names)))
    blob = " ".join(p for p in parts if p)

    scores: dict[DocType, float] = {doc_type: 0.0 for doc_type in DocType}
    hits: list[str] = []

    stem = tokens_for_search(Path(filename).stem)
    stem_raw = Path(filename).stem.lower()
    if stem_raw.endswith(("_ci", "-ci")) or stem_raw.endswith(" ci"):
        scores[DocType.INVOICE] += 3.0
        hits.append("filename:_ci->INVOICE")
    if stem_raw.endswith(("_pl", "-pl")) or stem_raw.endswith(" pl"):
        scores[DocType.PACKING_LIST] += 3.0
        hits.append("filename:_pl->PACKING_LIST")
    for doc_type, hints in _FILENAME_HINTS.items():
        for hint in hints:
            if hint in stem:
                scores[doc_type] += 2.5
                hits.append(f"filename:{hint}->{doc_type.value}")

    for doc_type, weighted in KEYWORD_WEIGHTS.items():
        for phrase, weight in weighted:
            n = _count_phrase(blob, phrase)
            if n:
                scores[doc_type] += weight * min(n, 5)
                hits.append(f"{phrase}x{n}->{doc_type.value}")

    ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    best_type, best_score = ranked[0]
    second_score = ranked[1][1] if len(ranked) > 1 else 0.0

    # Require a clear winner; never silently guess on a tie / weak signal.
    if best_score < 2.5 or (best_score - second_score) < 0.8:
        return ClassificationResult(
            doc_type=None,
            score=best_score,
            hits=hits,
            scores_by_type={k.value: v for k, v in scores.items()},
        )

    return ClassificationResult(
        doc_type=best_type,
        score=best_score,
        hits=hits,
        scores_by_type={k.value: v for k, v in scores.items()},
    )
