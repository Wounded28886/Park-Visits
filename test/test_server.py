#!/usr/bin/env python3
"""End-to-end tests for the standalone Park Visits server.

A fake Google Places server stands in for the real one — so this exercises
the integration's own fetching, ranking, storage, services and views without
spending a cent of Places quota. Run it with:

    python test/test_server.py
"""
from __future__ import annotations

import asyncio
import json
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "server"))
sys.path.insert(0, str(ROOT))

from aiohttp import FormData, web  # noqa: E402
from aiohttp.test_utils import TestClient, TestServer  # noqa: E402

PASS = 0
FAIL = 0


def ok(condition, message):
    global PASS, FAIL
    if condition:
        PASS += 1
    else:
        FAIL += 1
        print(f"  x {message}")


def section(name):
    print(f"\n== {name} ==")


# --------------------------------------------------------------------------
# a stand-in for Google Places
# --------------------------------------------------------------------------

PARKS = [
    ("park_a", "Riverside Park", 4.8, 120, -27.470, 153.021),
    ("park_b", "Hilltop Reserve", 4.5, 60, -27.480, 153.030),
    ("park_c", "Tiny Green", 5.0, 2, -27.490, 153.040),      # too few ratings
    ("park_d", "Lakeside Gardens", 4.2, 300, -27.500, 153.050),
]

calls = {"nearby": 0, "details": 0, "text": 0, "photo": 0}


async def fake_places_app() -> web.Application:
    app = web.Application()

    async def nearby(request):
        calls["nearby"] += 1
        if request.headers.get("X-Goog-Api-Key") != "test-key":
            return web.json_response({"error": "bad key"}, status=403)
        return web.json_response({"places": [
            {
                "id": pid,
                "displayName": {"text": name},
                "formattedAddress": f"{name}, Brisbane",
                "location": {"latitude": lat, "longitude": lon},
                "rating": rating,
                "userRatingCount": count,
                "types": ["park", "point_of_interest", "establishment"],
                "googleMapsUri": f"https://maps.google.com/?cid={pid}",
            }
            for pid, name, rating, count, lat, lon in PARKS
        ]})

    async def details(request):
        calls["details"] += 1
        pid = request.match_info["place_id"]
        known = {p[0]: p for p in PARKS}
        if pid not in known:
            return web.json_response({"error": {"message": "not found"}}, status=404)
        _, name, rating, count, lat, lon = known[pid]
        return web.json_response({
            "id": pid,
            "displayName": {"text": name},
            "formattedAddress": f"{name}, Brisbane",
            "location": {"latitude": lat, "longitude": lon},
            "rating": rating,
            "userRatingCount": count,
            "types": ["park"],
            "googleMapsUri": f"https://maps.google.com/?cid={pid}",
            "editorialSummary": {"text": f"A lovely spot at {name}."},
            "reviews": [{
                "rating": 5,
                "text": {"text": "Great playground"},
                "authorAttribution": {"displayName": "A Local"},
                "relativePublishTimeDescription": "a month ago",
            }],
            "photos": [{"name": f"places/{pid}/photos/abc"}],
            "currentOpeningHours": {"weekdayDescriptions": ["Monday: Open 24 hours"]},
        })

    async def text_search(request):
        calls["text"] += 1
        body = await request.json()
        query = body.get("textQuery", "")
        return web.json_response({"places": [{
            "id": "found_park",
            "displayName": {"text": f"{query} Park"},
            "formattedAddress": f"{query}, Brisbane",
            "location": {"latitude": -27.46, "longitude": 153.02},
            "rating": 4.4,
            "userRatingCount": 40,
            "types": ["park"],
            "googleMapsUri": "https://maps.google.com/?cid=found_park",
        }]})

    async def photo(request):
        calls["photo"] += 1
        return web.Response(body=b"\x89PNG\r\n\x1a\nfake", content_type="image/png")

    app.router.add_post("/v1/places:searchNearby", nearby)
    app.router.add_post("/v1/places:searchText", text_search)
    app.router.add_get("/v1/places/{place_id}", details)
    app.router.add_get("/v1/places/{place_id}/photos/{photo_id}/media", photo)
    return app


async def main() -> None:
    data_dir = tempfile.mkdtemp(prefix="park-visits-")
    places = TestServer(await fake_places_app())
    await places.start_server()
    base = f"http://127.0.0.1:{places.port}"

    import os

    os.environ.update({
        "GOOGLE_API_KEY": "test-key",
        "LATITUDE": "-27.4705",
        "LONGITUDE": "153.0260",
        "RADIUS_KM": "5",
        "MAX_PARKS": "10",
        "PEOPLE": "Kids,Mum,Dad",
        "DATA_DIR": data_dir,
        "TITLE": "Test Parks",
        "PORT": "0",
    })

    import ha_compat

    ha_compat.install()

    # Point the integration at the stand-in instead of Google.
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

    server_app.DATA_DIR = data_dir
    server_app.SETTINGS_FILE = Path(data_dir) / "settings.json"

    application = await server_app.create_app()
    client = TestClient(TestServer(application))
    await client.start_server()

    async def get_json(path):
        res = await client.get(path)
        return res.status, (await res.json() if "json" in res.headers.get("content-type", "") else await res.text())

    async def post_json(path, payload=None):
        res = await client.post(path, json=payload or {})
        body = await res.json() if "json" in res.headers.get("content-type", "") else await res.text()
        return res.status, body

    # ---------------- setup ----------------
    section("setup")
    status, health = await get_json("/healthz")
    ok(status == 200 and health["ok"], "healthz responds")
    ok(calls["nearby"] > 0, "fetched parks from the Places stand-in")
    # Tiny Green has 2 ratings, below the MIN_RATING_COUNT floor.
    ok(health["parks"] == 3, f"low-rating-count parks are left out (got {health['parks']})")

    status, config = await get_json("/api/config")
    ok(config["title"] == "Test Parks" and config["people"] == ["Kids", "Mum", "Dad"], "config is served")
    ok(set(config["services"]) >= {
        "rate_park", "delete_review", "add_park", "remove_park", "restore_park",
        "set_next_park", "clear_next_park", "delete_photo", "set_park_tag", "clear_park_tag",
    }, f"all services registered ({config['services']})")

    # ---------------- states ----------------
    section("states")
    status, states = await get_json("/api/states")
    parks = [s for s in states if s["attributes"].get("source") == "park_visits"]
    ok(len(parks) == 3, f"three geo_location entities ({len(parks)})")
    top = next(s for s in parks if s["attributes"]["rank"] == 1)
    ok(top["attributes"]["place_id"] == "park_a", f"best-rated park ranks first ({top['attributes']['place_id']})")
    ok(top["attributes"]["rating"] == 4.8 and top["attributes"]["rating_count"] == 120, "google rating carried through")
    ok(isinstance(top["state"], (int, float)), f"state is the distance ({top['state']})")
    ok("latitude" in top["attributes"] and "longitude" in top["attributes"], "coordinates present for the map")
    ok(any(s["entity_id"].startswith("sensor.") for s in states), "summary sensor present")
    ok(any(s["entity_id"].startswith("button.") for s in states), "refresh button present")

    # ---------------- recording a visit ----------------
    section("reviews")
    status, body = await post_json("/api/services/park_visits/rate_park", {
        "place_id": "park_a",
        "visit_date": "2026-09-20",
        "person_ratings": {"kids": 9, "mum": 8},
        "playground_rating": 7,
        "note": "Ducks everywhere",
        "liked": "The big slide",
    })
    ok(status == 200, f"rate_park accepted ({body})")
    status, states = await get_json("/api/states")
    rated = next(s for s in states if s["attributes"].get("place_id") == "park_a")
    ok(rated["attributes"]["our_visit_date"] == "2026-09-20", "visit date stored")
    ok(rated["attributes"]["our_person_ratings"] == {"kids": 9.0, "mum": 8.0}, f"per-person ratings stored ({rated['attributes']['our_person_ratings']})")
    ok(rated["attributes"]["our_note"] == "Ducks everywhere", "note stored")
    ok(rated["attributes"]["our_overall_rating"] is not None, "overall rating computed")

    status, body = await post_json("/api/services/park_visits/rate_park", {
        "place_id": "nope", "visit_date": "2026-09-20",
    })
    ok(status == 400, f"a review for an unknown park is refused ({status})")
    status, body = await post_json("/api/services/park_visits/rate_park", {
        "place_id": "park_a", "visit_date": "not-a-date",
    })
    ok(status == 400, "a malformed date is refused by the service schema")

    # ---------------- park details ----------------
    section("details")
    status, details = await get_json("/api/park_visits/details/park_a")
    ok(status == 200 and details.get("name") == "Riverside Park", f"details view works ({str(details)[:80]})")
    ok(details.get("reviews") and details["reviews"][0]["text"] == "Great playground", "google reviews come through")
    ok(calls["details"] > 0, "details hit the Places stand-in")

    # ---------------- add / remove / restore ----------------
    section("adding and removing parks")
    status, body = await post_json("/api/services/park_visits/add_park", {"query": "Secret"})
    ok(status == 200, f"add_park accepted ({body})")
    status, states = await get_json("/api/states")
    added = [s for s in states if s["attributes"].get("place_id") == "found_park"]
    ok(len(added) == 1 and added[0]["attributes"].get("manually_added"), "manually added park appears and is badged")

    status, _ = await post_json("/api/services/park_visits/remove_park", {"place_id": "park_b"})
    status, states = await get_json("/api/states")
    ok(not any(s["attributes"].get("place_id") == "park_b" for s in states), "removed park disappears")
    status, removed = await get_json("/api/park_visits/removed")
    ok(any(r.get("place_id") == "park_b" for r in (removed.get("parks") if isinstance(removed, dict) else removed)),
       f"removed park is listed for restoring ({removed})")

    status, _ = await post_json("/api/services/park_visits/restore_park", {"place_id": "park_b"})
    status, states = await get_json("/api/states")
    ok(any(s["attributes"].get("place_id") == "park_b" for s in states), "restored park comes back")

    # ---------------- next park ----------------
    section("next park")
    status, _ = await post_json("/api/services/park_visits/set_next_park", {"place_id": "park_d"})
    status, states = await get_json("/api/states")
    sensors = [s for s in states if s["entity_id"].startswith("sensor.")]
    ok(any("park_d" in json.dumps(s["attributes"]) or "Lakeside" in json.dumps(s["attributes"]) for s in sensors),
       "next park shows up on a sensor")
    status, _ = await post_json("/api/services/park_visits/clear_next_park", {})
    ok(status == 200, "next park can be cleared")

    # ---------------- photos ----------------
    section("photos")
    png = b"\x89PNG\r\n\x1a\n" + b"0" * 64
    form = FormData()
    form.add_field("photo", png, filename="swing.png", content_type="image/png")
    res = await client.post("/api/park_visits/upload/park_a", data=form)
    ok(res.status in (200, 201), f"photo upload accepted ({res.status}: {await res.text()})")
    uploaded = (await res.json()).get("filename") if res.status == 200 else None

    bad = FormData()
    bad.add_field("photo", b"not an image", filename="x.txt", content_type="text/plain")
    res = await client.post("/api/park_visits/upload/park_a", data=bad)
    ok(res.status == 400, f"a non-image upload is refused ({res.status})")
    status, states = await get_json("/api/states")
    shot = next(s for s in states if s["attributes"].get("place_id") == "park_a")
    ok(shot["attributes"]["our_photo_count"] == 1, f"photo counted ({shot['attributes']['our_photo_count']})")

    status, gallery = await get_json("/api/park_visits/gallery")
    entry = next((p for p in gallery["parks"] if p["place_id"] == "park_a"), None)
    ok(entry and uploaded in entry["photos"],
       f"the gallery lists the uploaded photo ({entry and entry.get('photos')})")

    res = await client.get(f"/api/park_visits/photo/park_a/{uploaded}")
    ok(res.status == 200 and (await res.read()).startswith(b"\x89PNG"), "the photo itself is served back")
    res = await client.get("/api/park_visits/photo/park_a/../../settings.json")
    ok(res.status in (400, 403, 404), f"a path-traversal filename is refused ({res.status})")

    stored = [p for p in Path(data_dir).rglob("*.png") if p.is_file()]
    ok(stored, f"photo written under the data directory ({[str(p) for p in stored][:2]})")
    ok(uploaded and any(p.name == uploaded for p in stored), "the stored file is the one reported back")

    status, _ = await post_json("/api/services/park_visits/delete_photo", {
        "place_id": "park_a", "filename": uploaded,
    })
    status, states = await get_json("/api/states")
    shot = next(s for s in states if s["attributes"].get("place_id") == "park_a")
    ok(shot["attributes"]["our_photo_count"] == 0, "photo deleted")

    # ---------------- persistence ----------------
    section("persistence")
    await client.close()
    nearby_before = calls["nearby"]
    application2 = await server_app.create_app()
    client2 = TestClient(TestServer(application2))
    await client2.start_server()
    res = await client2.get("/api/states")
    states = await res.json()
    again = next((s for s in states if s["attributes"].get("place_id") == "park_a"), None)
    ok(again is not None and again["attributes"]["our_visit_date"] == "2026-09-20",
       "the review survives a restart")
    ok(any(s["attributes"].get("place_id") == "found_park" for s in states),
       "a manually added park survives a restart")
    ok(calls["nearby"] == nearby_before,
       f"a restart costs no Places quota — the cached list is reused ({calls['nearby']} vs {nearby_before})")

    # ---------------- refresh ----------------
    section("refresh")
    res = await client2.post("/api/refresh")
    ok(res.status == 200 and calls["nearby"] > nearby_before, "refresh really calls Places again")
    res = await client2.get("/api/states")
    states = await res.json()
    ok(next(s for s in states if s["attributes"].get("place_id") == "park_a")["attributes"]["our_visit_date"] == "2026-09-20",
       "a refresh keeps our review attached")

    # ---------------- configuration ----------------
    section("configuration")
    # LOCATION is resolved by name through Text Search, cached, and reused.
    loc_dir = tempfile.mkdtemp(prefix="park-visits-loc-")
    os.environ.pop("LATITUDE"), os.environ.pop("LONGITUDE")
    os.environ["LOCATION"] = "Cornubia"
    os.environ["DATA_DIR"] = loc_dir
    server_app.DATA_DIR = loc_dir
    server_app.SETTINGS_FILE = Path(loc_dir) / "settings.json"
    text_before = calls["text"]
    app_loc = await server_app.create_app()
    client_loc = TestClient(TestServer(app_loc))
    await client_loc.start_server()
    health = await (await client_loc.get("/healthz")).json()
    ok(health["ok"] and "Cornubia" in health["location"],
       f"a named location is looked up and used ({health.get('location')})")
    ok(calls["text"] == text_before + 1, "looking it up costs exactly one Text Search")
    settings = json.loads((Path(loc_dir) / "settings.json").read_text())
    ok(settings["latitude"] == -27.46, "the resolved coordinates are saved")
    await client_loc.close()

    app_loc2 = await server_app.create_app()
    ok(calls["text"] == text_before + 1, "a restart reuses the saved location, costing nothing")

    # A missing key, or a location Google can't find, reports rather than crashing.
    del os.environ["GOOGLE_API_KEY"]
    app_bad = await server_app.create_app()
    client_bad = TestClient(TestServer(app_bad))
    await client_bad.start_server()
    res = await client_bad.get("/healthz")
    body = await res.json()
    ok(res.status == 503 and not body["ok"] and "GOOGLE_API_KEY" in body["error"],
       f"a missing API key is reported, not a crash ({body})")
    res = await client_bad.get("/")
    ok(res.status == 200 and "can't start yet" in (await res.text()),
       "and the page says so")
    await client_bad.close()
    os.environ["GOOGLE_API_KEY"] = "test-key"
    os.environ["DATA_DIR"] = data_dir
    server_app.DATA_DIR = data_dir
    server_app.SETTINGS_FILE = Path(data_dir) / "settings.json"
    shutil.rmtree(loc_dir, ignore_errors=True)

    # ---------------- the page ----------------
    section("page")
    res = await client2.get("/")
    html = await res.text()
    ok(res.status == 200 and "park-visits-table-card" in html, "the page loads both cards")
    ok("home assistant" not in html.lower() and "hacs" not in html.lower(),
       "the page carries no Home Assistant branding")
    res = await client2.get("/cards/park-visits-table-card.js")
    ok(res.status == 200 and "customElements.define" in (await res.text()),
       "the card bundle is served from the integration's own www/")

    await client2.close()
    await places.close()
    shutil.rmtree(data_dir, ignore_errors=True)

    print(f"\n{PASS} passed, {FAIL} failed")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    asyncio.run(main())
