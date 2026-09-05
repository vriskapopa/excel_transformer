"""Quick probe for Tosun upload files."""
from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from app.parsing.pipeline import parse_file

FILES = [
    Path(r"c:\Users\ASUS I5\Downloads\Документы для бота\Tosun\TOSUNOGLU SM REGIONTEKSTIL_261071_CI.pdf"),
    Path(r"c:\Users\ASUS I5\Downloads\Документы для бота\Tosun\Specification TOSUN 18259.xlsx"),
    Path(r"c:\Users\ASUS I5\Downloads\Документы для бота\Tosun\TOSUNOGLU SM REGION_261071_PL.pdf"),
]

if __name__ == "__main__":
    for path in FILES:
        started = time.time()
        doc = parse_file(str(path), allow_ocr=True)
        elapsed = round(time.time() - started, 1)
        print(
            path.name,
            doc.mime_hint,
            doc.doc_type,
            f"lines={len(doc.lines)}",
            f"ocr={doc.ocr_used}",
            f"{elapsed}s",
            doc.warnings[:2],
        )
