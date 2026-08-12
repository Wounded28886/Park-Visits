# Park Visits

A Home Assistant custom integration that tracks the top-rated parks within a
configurable radius of a configurable centre point — defaults to
**Cornubia, City of Logan, Queensland, Australia** (-27.6599, 153.2138) and a
**100 km** radius — using the **Google Places API**, ranked by Google rating.
Includes a custom Lovelace map card: click a park's marker to see its
details and submit your own rating/note, which is stored locally.

## What it does

- Queries the **Google Places API (New)** for parks around your configured
  centre point, tiling several 50km-radius requests to cover radii bigger
  than Google's single-request cap.
- Ranks results by **Google's average rating** (rating count breaks ties),
  keeping the configured number of top parks.
- Each park keeps **all** of the categories/types Google reports for it
  (e.g. a place can be both a "Park" and a "Tourist Attraction"), not a
  single fixed category.
- Creates:
  - One **`geo_location`** entity per tracked park (so the built-in **Map**
    card, or the bundled custom map card, can plot them), with attributes
    for rank, categories, address, Google rating/count, a Google Maps link,
    and your own rating/note if you've left one.
  - One summary **sensor** (`sensor.nearby_parks`) reporting how many parks
    are currently tracked.
- Registers a **`park_visits.rate_park`** service — call it with a park's
  `place_id`, a `rating` (0-10) and an optional `note` to record what you
  thought of it. Reviews are stored locally (`.storage`, keyed by Google's
  place_id) and survive dataset refreshes.
- Ships a **custom Lovelace card** (`park-visits-map-card`): a Leaflet map
  of every tracked park where clicking a marker opens a popup with the
  park's details, your past rating if any, and a small form to submit a
  new one — calling the service above directly from the map.

## Installation

Private repos aren't supported by HACS, so this is a manual install.

### 1. Install the integration

1. Copy `custom_components/park_visits` into your Home Assistant
   `config/custom_components/` directory.
2. Restart Home Assistant.

### 2. Get a Google Places API key

1. Create/select a project at [console.cloud.google.com](https://console.cloud.google.com).
2. **APIs & Services > Library** → enable **Places API (New)**.
3. **Billing** → link a billing account (Google gives ~$200/month free
   credit; Nearby Search runs ~$0.032/request at Basic field tier, and one
   full refresh of a 100km radius costs roughly $0.35-0.60 depending on how
   many tiles that radius needs — see "Refresh cost" below).
4. **APIs & Services > Credentials > Create Credentials > API key**, then
   restrict it to "Places API (New)" only.

### 3. Add the integration

1. Go to **Settings > Devices & Services > Add Integration**, search for
   **Park Visits**.
2. Paste your Google Places API key, and accept the defaults (Cornubia,
   100 km, top 100) or adjust the centre latitude/longitude, radius and
   number of parks to show.
3. You can change these later via the integration's **Configure** button
   — this triggers a reload and regenerates the tracked parks.

### 4. Install the custom map card

1. Copy `www/park-visits-map-card.js` into your Home Assistant
   `config/www/` directory.
2. **Settings > Dashboards > ⋮ > Resources > Add Resource**:
   - URL: `/local/park-visits-map-card.js`
   - Resource type: **JavaScript module**
3. Refresh your browser.

### 5. Add the dashboard

1. Go to **Settings > Dashboards > Add Dashboard > New dashboard from
   scratch**, give it a name, then open it and choose **Edit in YAML**
   from the three-dot menu.
2. Paste the contents of
   [`dashboards/park_visits_dashboard.yaml`](dashboards/park_visits_dashboard.yaml).
3. Save. You'll get a **Map** view (click any pin to see details and rate
   the park) and a **List** view (a ranked table of every tracked park,
   including your own ratings).

If your sensor's entity ID isn't exactly `sensor.nearby_parks` (Home
Assistant may suffix it if you have multiple entries), that's fine — the
map card filters by the `source: park_visits` attribute, not entity ID.

## Refresh cost and cadence

Every refresh tiles the configured radius into overlapping 50km-radius
Nearby Search requests (Google's per-request cap), so cost scales with
radius: the default 100km radius needs on the order of 15-20 requests per
refresh. The coordinator refreshes **once every 24 hours** by default — a
review submitted through the map card updates instantly and locally
without using any API quota, since it never triggers a re-fetch.

## Architecture

```
custom_components/park_visits/
├── __init__.py         # entry setup/unload, options-change reload, rate_park service
├── manifest.json       # HA integration manifest
├── const.py            # domain, defaults, Google Places config, attribute keys
├── util.py              # haversine distance + geodesic tile-centre calculation
├── coordinator.py       # tiled Google Places queries, ranking, review merging
├── storage.py            # persistent local review storage (place_id -> rating/note)
├── config_flow.py       # setup + options UI (API key, centre point, radius, count)
├── geo_location.py      # one GeolocationEvent entity per tracked park
├── sensor.py             # summary "Nearby Parks" count sensor
├── services.yaml         # rate_park service description (Developer Tools UI)
└── strings.json / translations/en.json
www/
└── park-visits-map-card.js   # custom Lovelace card: map + click-to-rate popups
dashboards/
└── park_visits_dashboard.yaml
```

## Requirements

Home Assistant 2024.6.0 or newer (uses modern `ConfigFlow`/`OptionsFlow`
and the core `aiohttp` client helper). No external Python dependencies —
all Google API calls go through Home Assistant's shared `aiohttp` session.
