#!/usr/bin/env python3
"""Fill a data directory from the fake Places server, for trying the UI.

The park list is cached against the search settings, not the API key, so a
directory seeded here lets the real server (or the container) start up and
serve a populated board without ever calling Google:

    python test/seed_data.py ./demo-data
    docker run -p 8098:8098 -v "$PWD/demo-data:/data" \
      -e GOOGLE_API_KEY=unused -e LATITUDE=-27.4705 -e LONGITUDE=153.0260 \
      -e RADIUS_KM=5 -e MAX_PARKS=10 park-visits
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "server"))
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "test"))

from aiohttp import FormData  # noqa: E402
from aiohttp.test_utils import TestClient, TestServer  # noqa: E402

from test_server import fake_places_app  # noqa: E402


def _png(width: int, height: int, rgb: tuple[int, int, int]) -> bytes:
    """A real single-colour PNG, so the seeded photo actually displays."""
    import struct
    import zlib

    raw = b"".join(b"\x00" + bytes(rgb) * width for _ in range(height))

    def chunk(kind: bytes, payload: bytes) -> bytes:
        body = kind + payload
        return struct.pack(">I", len(payload)) + body + struct.pack(">I", zlib.crc32(body))

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw, 9))
        + chunk(b"IEND", b"")
    )


async def main(target: Path) -> None:
    target.mkdir(parents=True, exist_ok=True)
    places = TestServer(await fake_places_app())
    await places.start_server()
    base = f"http://127.0.0.1:{places.port}"

    os.environ.update({
        "GOOGLE_API_KEY": "test-key",
        "LATITUDE": "-27.4705",
        "LONGITUDE": "153.0260",
        "RADIUS_KM": "5",
        "MAX_PARKS": "10",
        "PEOPLE": "Kids,Mum,Dad",
        "DATA_DIR": str(target),
    })

    import ha_compat

    ha_compat.install()
    from custom_components.park_visits import coordinator as coord_mod
    from custom_components.park_visits import geocoding as geo_mod
    from custom_components.park_visits import views as views_mod

    coord_mod.PLACES_API_BASE_URL = f"{base}/v1/places:searchNearby"
    for mod in (coord_mod, geo_mod, views_mod):
        if hasattr(mod, "PLACES_API_DETAILS_URL"):
            mod.PLACES_API_DETAILS_URL = base + "/v1/places/{place_id}"
        if hasattr(mod, "GEOCODE_API_URL"):
            mod.GEOCODE_API_URL = f"{base}/v1/places:searchText"
        if hasattr(mod, "PLACES_API_PHOTO_URL"):
            mod.PLACES_API_PHOTO_URL = base + "/v1/{photo_name}/media"

    import app as server_app

    server_app.DATA_DIR = str(target)
    server_app.SETTINGS_FILE = target / "settings.json"

    application = await server_app.create_app()
    client = TestClient(TestServer(application))
    await client.start_server()

    # A visited park, a photo and a park still to go, so every view has
    # something in it.
    await client.post("/api/services/park_visits/rate_park", json={
        "place_id": "park_a",
        "visit_date": "2026-09-14",
        "person_ratings": {"kids": 9, "mum": 8, "dad": 7},
        "playground_rating": 9,
        "scenery_rating": 8,
        "facilities_rating": 6,
        "note": "Huge playground, shady picnic tables by the water.",
        "liked": "The flying fox",
        "disliked": "Parking fills up by 10am",
    })
    form = FormData()
    form.add_field("photo", _png(160, 120, (76, 140, 74)),
                   filename="swing.png", content_type="image/png")
    await client.post("/api/park_visits/upload/park_a", data=form)
    await client.post("/api/services/park_visits/set_next_park", json={"place_id": "park_d"})

    res = await client.get("/api/states")
    parks = [s for s in await res.json() if s["attributes"].get("source") == "park_visits"]
    print(f"seeded {len(parks)} parks into {target}")

    await client.close()
    await places.close()


if __name__ == "__main__":
    asyncio.run(main(Path(sys.argv[1] if len(sys.argv) > 1 else "demo-data").resolve()))
