import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx

from app.services.materials_18233 import kit_sources


def check(kit: str, expected: int) -> None:
    src = kit_sources(kit)
    files = []
    for key in ("invoice", "packing", "specification"):
        path = src[key]
        mime = (
            "application/vnd.ms-excel"
            if path.suffix.lower() == ".xls"
            else "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
        files.append(("files", (path.name, path.read_bytes(), mime)))
    response = httpx.post(
        "http://127.0.0.1:8000/api/v1/shipments/",
        data={"title": "18233", "profile_type": "18233"},
        files=files,
        timeout=120,
    )
    response.raise_for_status()
    data = response.json()
    assert data["item_count"] == expected, data
    shipment_id = data["id"]
    export = httpx.post(
        f"http://127.0.0.1:8000/api/v1/shipments/{shipment_id}/export",
        timeout=120,
    )
    export.raise_for_status()
    names = export.json()["files"]
    print(kit, "items", data["item_count"], "warn", data["warning_count"], "files", names)
    assert not any("СПЕЦИФ" in str(n).upper() for n in names), names
    assert any(str(n).lower().endswith(".zip") for n in names), names
    assert any("ИНВОЙС" in str(n).upper() or "инвойс" in str(n).lower() for n in names), names
    assert any("ПАКИНГ" in str(n).upper() or "пакинг" in str(n).lower() for n in names), names
    print(kit, "EXPORT OK (invoice+packing, no specification)")


if __name__ == "__main__":
    check("626-1", 13)
    check("626-2", 17)
    print("ALL OK")
