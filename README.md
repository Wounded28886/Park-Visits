# Park Visits

A Home Assistant custom integration that tracks the top parks within a
configurable radius of a configurable centre point — defaults to
**Cornubia, City of Logan, Queensland, Australia** (-27.6599, 153.2138) and a
**100 km** radius, showing the **top 100** curated parks pinned on a Map
card and in a sortable list view.

## What it does

- Ships with a **curated, ranked dataset** of real parks, national parks,
  conservation parks, regional parks and gardens across South East
  Queensland (Brisbane, Logan, Gold Coast, Ipswich, Redland City, Scenic
  Rim, Moreton Bay and the Gold Coast hinterland) — see
  [Data source & ranking](#data-source--ranking) below.
- On setup (and whenever you change the options), it filters that dataset
  to parks within your configured radius of your configured centre point,
  keeps the top N by curated rank, and creates:
  - One **`geo_location`** entity per park (so the built-in **Map** card
    plots them automatically), with attributes for rank, category,
    locality and a short description.
  - One summary **sensor** (`sensor.nearby_parks`) reporting how many
    parks are currently in range.
- A ready-to-import Lovelace dashboard with a **Map** view and a **List**
  view (a live-updating markdown table, sorted by rank).

## Installation

### Option A — HACS (custom repository)

1. In HACS, go to **Integrations > ⋮ > Custom repositories**.
2. Add this repository's URL with category **Integration**.
3. Install **Park Visits**, then restart Home Assistant.

### Option B — Manual

1. Copy `custom_components/park_visits` into your Home Assistant
   `config/custom_components/` directory.
2. Restart Home Assistant.

### Add the integration

1. Go to **Settings > Devices & Services > Add Integration**, search for
   **Park Visits**.
2. Accept the defaults (Cornubia, 100 km, 100 parks) or adjust the centre
   latitude/longitude, radius and number of parks to show.
3. You can change these later via the integration's **Configure** button
   — this triggers a reload and regenerates the tracked parks.

### Add the dashboard

1. Go to **Settings > Dashboards > Add Dashboard > New dashboard from
   scratch**, give it a name, then open it and choose **Edit in YAML**
   from the three-dot menu.
2. Paste the contents of [`dashboards/park_visits_dashboard.yaml`](dashboards/park_visits_dashboard.yaml).
3. Save. You'll get a **Map** view (all tracked parks pinned) and a
   **List** view (a ranked table of every tracked park).

If your sensor's entity ID isn't exactly `sensor.nearby_parks` (Home
Assistant may suffix it if you have multiple entries), update the
`entities:` card on the Map view to match — check
**Settings > Devices & Services > Park Visits** to find the exact ID.

## Data source & ranking

There's no free API that returns a live "top parks" popularity ranking,
and this project intentionally avoids requiring a paid Google Places API
key. Instead, `custom_components/park_visits/data/parks.json` is a
**hand-curated snapshot**, researched from public sources (OpenStreetMap,
Wikipedia, Queensland Parks & Wildlife Service listings and local council
park directories), ranked by real-world notability/popularity as a
best-effort editorial judgement — not a live, continuously-updated score.

Practical implications:

- The bundled dataset only covers the South East Queensland region around
  Cornubia. If you change the centre point to somewhere far away, you may
  get few or no results — this integration is not a general-purpose
  "parks anywhere" data source.
- To refresh or extend the list (e.g. add more parks, fix a coordinate,
  update descriptions), edit `custom_components/park_visits/data/parks.json`
  directly. Each entry is:

  ```json
  {
    "rank": 1,
    "name": "Example Park",
    "locality": "Suburb, QLD",
    "lat": -27.0,
    "lon": 153.0,
    "category": "national_park",
    "description": "One-line description."
  }
  ```

  Lower `rank` = higher priority when trimming to the configured "number
  of parks to show". Distance filtering and final display order are
  computed live from your configured centre point, so you don't need to
  pre-sort by distance.

## Architecture

```
custom_components/park_visits/
├── __init__.py        # entry setup/unload, options-change reload
├── manifest.json       # HA integration manifest
├── const.py             # domain, defaults, attribute keys
├── util.py               # haversine distance + dataset loader
├── coordinator.py         # filters/ranks parks around the configured centre
├── config_flow.py          # setup + options UI (centre point, radius, count)
├── geo_location.py          # one GeolocationEvent entity per tracked park
├── sensor.py                 # summary "Nearby Parks" count sensor
├── strings.json / translations/en.json
└── data/parks.json            # curated parks dataset
```

## Requirements

Home Assistant 2024.6.0 or newer (uses modern `ConfigFlow`/`OptionsFlow`
and selector APIs). No external Python dependencies.
