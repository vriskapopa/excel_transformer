"""One-off: verify export returns zip."""
from fastapi.testclient import TestClient

from app.main import app
from app.services.materials_18233 import kit_sources

client = TestClient(app)
src = kit_sources("626-1")
files = [
    ("files", (p.name, p.read_bytes(), "application/vnd.ms-excel"))
    for p in (src["invoice"], src["packing"], src["specification"])
]
r = client.post("/api/v1/shipments/", data={"title": "18233", "profile_type": "18233"}, files=files)
r.raise_for_status()
sid = r.json()["id"]
er = client.post(f"/api/v1/shipments/{sid}/export")
print(er.status_code, er.json())
er.raise_for_status()
zip_name = er.json()["files"][0]
d = client.get(f"{er.json()['download_base']}/{zip_name}")
print("zip", zip_name, d.status_code, d.headers.get("content-type"), len(d.content))
