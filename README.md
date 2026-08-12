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
- Ships two **custom Lovelace cards**:
  - `park-visits-map-card` — a Leaflet map of every tracked park where
    clicking a marker opens a popup with the park's details, your past
    rating if any, and a small form to submit a new one, calling the
    service above directly from the map.
  - `park-visits-table-card` — a spreadsheet-style table: click any column
    header to sort by it, click again to reverse. Numeric columns sort
    numerically (not alphabetically) and unrated parks always sort to the
    bottom in both directions. Includes a quick text filter.
- Adds a **"Refresh parks" button** entity. There is no automatic polling —
  that button (plus the initial fetch on setup, or on an options change) is
  the only thing that ever calls the Google API, so you control exactly
  when quota gets spent.

## Installation

### 1. Install the integration

**Via HACS (recommended):** HACS > Integrations > ⋮ > Custom repositories
> add `https://github.com/Wounded28886/Park-Visits` as category
"Integration" (skip this if it's already added — search for "Park Visits"
directly instead). Install it, then restart Home Assistant.

**Manual:** copy `custom_components/park_visits` into your Home Assistant
`config/custom_components/` directory, then restart Home Assistant.

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

### 4. Install the custom cards

HACS installs `custom_components/park_visits` but not the `www/` folder, so
this step is always manual regardless of how you did step 1:

1. Copy both `www/park-visits-map-card.js` and
   `www/park-visits-table-card.js` into your Home Assistant `config/www/`
   directory.
2. **Settings > Dashboards > ⋮ > Resources > Add Resource** — once for each:
   - URL: `/local/park-visits-map-card.js` — type **JavaScript module**
   - URL: `/local/park-visits-table-card.js` — type **JavaScript module**
3. Hard-refresh your browser (a plain refresh can serve a cached copy of a
   resource URL — if a card doesn't render or doesn't pick up an update,
   this is the first thing to try, or bump the resource URL to
   `...js?v=2` etc.).

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

There is **no automatic polling**. The only things that call the Google
API are: the initial fetch when you add the integration, a reload after
you change its options (centre point, radius, count, or API key), and
pressing the **"Refresh parks"** button. Everything else — including
submitting a review through the map card — updates entities from
already-fetched data and costs nothing.

Every one of those fetches tiles the configured radius into overlapping
50km-radius Nearby Search requests (Google's per-request cap), so cost
scales with radius: the default 100km radius needs on the order of 15-20
requests per press, roughly $0.35-0.60 at Basic field-tier pricing. Press
it as often (or rarely) as you like — nothing else will call Google on
your behalf.

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
├── button.py             # manual "Refresh parks" button — the only trigger for an API call
├── services.yaml         # rate_park service description (Developer Tools UI)
└── strings.json / translations/en.json
www/
├── park-visits-map-card.js     # custom card: map + click-to-rate popups
└── park-visits-table-card.js   # custom card: sortable/filterable table
dashboards/
└── park_visits_dashboard.yaml
```

## Requirements

Home Assistant 2024.6.0 or newer (uses modern `ConfigFlow`/`OptionsFlow`
and the core `aiohttp` client helper). No external Python dependencies —
all Google API calls go through Home Assistant's shared `aiohttp` session.
