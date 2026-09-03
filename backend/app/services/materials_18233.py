"""Locate MVP_18233 material folders and эталон templates."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

# backend/app/services/materials_18233.py -> parents[3] = project root
PROJECT_ROOT = Path(__file__).resolve().parents[3]
MATERIALS_ROOT = PROJECT_ROOT / "materials" / "MVP_18233"


@lru_cache(maxsize=1)
def materials_available() -> bool:
    return MATERIALS_ROOT.exists()


def kit_base(kit: str) -> Path:
    return next(p for p in MATERIALS_ROOT.rglob("*") if p.is_dir() and p.name.endswith(kit))


def kit_sources(kit: str) -> dict[str, Path]:
    base = kit_base(kit)
    src = next(c for c in base.iterdir() if c.is_dir() and c.name.startswith("01"))
    files = list(src.iterdir())
    return {
        "invoice": next(p for p in files if "INVOICE" in p.name.upper()),
        "packing": next(p for p in files if "PL" in p.name.upper() or "PACK" in p.name.upper()),
        "specification": next(p for p in files if "SPEC" in p.name.upper()),
    }


def kit_templates(kit: str) -> dict[str, Path]:
    base = kit_base(kit)
    ready = next(c for c in base.iterdir() if c.is_dir() and c.name.startswith("02"))
    files = list(ready.iterdir())
    return {
        "invoice": next(p for p in files if "ИНВОЙС" in p.name or "инвойс" in p.name.lower()),
        "packing": next(p for p in files if "ПАКИНГ" in p.name or "пакинг" in p.name.lower()),
        "specification": next(
            p for p in files if "СПЕЦИФ" in p.name.upper() or "специф" in p.name.lower()
        ),
    }
