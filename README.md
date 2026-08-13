# Park Visits

A Home Assistant custom integration that tracks the top-rated parks within a
configurable radius of a configurable centre point — defaults to
**Cornubia, City of Logan, Queensland, Australia** (-27.6599, 153.2138) and a
**100 km** radius — using the **Google Places API**, ranked by Google rating.

The dashboard is a sortable table: click a column to sort by it, click a park
to open its detail panel with Google's photos and reviews, and write your own
review — rating, what you liked, what you didn't, notes and photos.

## What it does

- Queries the **Google Places API (New)** for parks around your configured
  centre point, tiling several 50km-radius requests to cover radii bigger
  than Google's single-request cap.
- Ranks results by **Google's average rating** (rating count breaks ties),
  keeping the configured number of top parks. Places with fewer than **5
  Google ratings** are excluded, so a lone 5.0 review can't outrank a
  genuinely popular park (`MIN_RATING_COUNT` in `const.py`).
- Each park keeps **all** of the categories/types Google reports for it
  (e.g. a place can be both a "Park" and a "Tourist Attraction"), not a
  single fixed category.
- Creates:
  - One **`geo_location`** entity per tracked park, carrying rank,
    categories, address, Google rating/count, a Google Maps link, and our
    own review summary.
  - Three summary **sensors**: `sensor.nearby_parks` (how many parks are
    tracked), `sensor.next_park` (the park we plan to visit next) and
    `sensor.last_visited_park` (the most recently reviewed park). The last
    two are usable in automations — "remind us about the next park on
    Saturday morning", say.
  - A **"Refresh parks" button** — see [Refresh cost](#refresh-cost-and-cadence).
- Registers services to record and remove reviews — **`rate_park`** (rating,
  liked, disliked, notes), **`delete_review`** (also deletes that review's
  photo files) and **`delete_photo`** (one photo) — plus
  **`set_next_park`** / **`clear_next_park`** for planning the next visit. Reviews are stored locally
  (`.storage`, keyed by Google's place_id) and survive dataset refreshes —
  including a park dropping out of the tracked list, since the park's name is
  saved with the review.
- Ships two **custom Lovelace cards**:
  - `park-visits-table-card` — spreadsheet-style sorting (click a header to
    sort, click again to reverse; numeric columns sort numerically and
    unrated parks sink to the bottom in both directions), a text filter, and
    a **Review** button on every row. Clicking a park's name opens a detail
    panel with Google's rating, editorial summary, opening hours, website,
    photos and written reviews, plus our own review. Writing or editing a
    review opens its **own popup** in place of that panel, where you can set
    a rating, record what you liked and didn't, add notes, attach photos,
    delete individual photos, or delete the whole review.
  - `park-visits-gallery-card` — a collage of every photo attached to a
    review. Click one to see it large alongside the park name and our
    review, and page through the rest.

## How photos and reviews are handled

Google's reviews and photos are **not** part of the bulk park search — they
live on pricier SKUs, so fetching them for every tracked park on each refresh
would cost far more than the search itself. Instead the integration calls
**Place Details for a single park, only when you open it**, and caches the
result for 24 hours (so reopening a park is free).

Photo URLs from Google require the API key. Rather than putting that in an
`<img src>` — which would expose the key to every browser that loads the page
— the integration proxies photo bytes server-side and hands the frontend a
**short-lived signed URL** via Home Assistant's `auth/sign_path`. The key
never leaves your instance.

Your own uploaded photos are written to `<config>/park_visits_photos/<place_id>/`
and served through the same signed-path mechanism. Only the filenames are kept
in the review store, since that file is held in memory and rewritten on every
save.

## Installation

### 1. Install the integration

**Via HACS (recommended):** HACS > Integrations > ⋮ > Custom repositories
> add `https://github.com/Wounded28886/Park-Visits` as category
"Integration". Install it, then restart Home Assistant.

**Manual:** copy `custom_components/park_visits` into your Home Assistant
`config/custom_components/` directory, then restart Home Assistant.

### 2. Get a Google Places API key

1. Create/select a project at [console.cloud.google.com](https://console.cloud.google.com).
2. **APIs & Services > Library** → enable **Places API (New)**.
3. **Billing** → link a billing account (Google gives ~$200/month free
   credit). See [Refresh cost](#refresh-cost-and-cadence) for what this
   integration actually spends.
4. **APIs & Services > Credentials > Create Credentials > API key**, then
   restrict it to "Places API (New)" only.

### 3. Add the integration

1. **Settings > Devices & Services > Add Integration**, search for
   **Park Visits**.
2. Paste your Google Places API key, and accept the defaults (Cornubia,
   100 km, top 100) or adjust the centre latitude/longitude, radius and
   number of parks to show.
3. You can change these later via the integration's **Configure** button —
   this triggers a reload and regenerates the tracked parks.

### 4. Install the custom card

HACS installs `custom_components/park_visits` but not the `www/` folder, so
this step is always manual regardless of how you did step 1:

1. Copy `www/park-visits-table-card.js` and `www/park-visits-gallery-card.js`
   into your Home Assistant `config/www/` directory.
2. **Settings > Dashboards > ⋮ > Resources > Add Resource** — once for each:
   - `/local/park-visits-table-card.js` — type **JavaScript module**
   - `/local/park-visits-gallery-card.js` — type **JavaScript module**
3. Hard-refresh your browser (a plain refresh can serve a cached copy of a
   resource URL — if the card doesn't render or doesn't pick up an update,
   this is the first thing to try, or bump the resource URL to `...js?v=2`).

### 5. Add the dashboard

1. **Settings > Dashboards > Add Dashboard > New dashboard from scratch**,
   give it a name, then open it and choose **Edit in YAML** from the
   three-dot menu.
2. Paste the contents of
   [`dashboards/park_visits_dashboard.yaml`](dashboards/park_visits_dashboard.yaml).

The card filters by the `source: park_visits` attribute rather than entity
IDs, so it keeps working if Home Assistant suffixes your entity names.

## Refresh cost and cadence

There is **no automatic polling**. Google is contacted only when:

| Action | Cost |
|---|---|
| Adding the integration for the first time | One full park search |
| Changing centre point, radius or park count | One full park search |
| Pressing **Refresh parks** | One full park search |
| Opening a park for the first time in 24h | One Place Details call |
| Viewing a park's Google photos | One photo fetch each |
| **Restarting Home Assistant** | **Nothing** — the park list is restored from disk |

That last row matters: Home Assistant normally refreshes an integration's
data on every startup, which here would mean a paid search each restart. The
fetched list is cached to `.storage` and restored instead, keyed by the
search settings so it's correctly discarded when you change them.

A full park search tiles the configured radius into overlapping 50km-radius
Nearby Search requests (Google's per-request cap), so cost scales with
radius: the default 100km needs on the order of 15-20 requests, roughly
$0.35-0.60 at Basic field-tier pricing. Place Details with reviews sits on a
pricier SKU (order of a few cents per park opened), which is exactly why it
is fetched on demand and cached rather than pulled for all 100 parks.

Writing a review, uploading a photo, and sorting/filtering the table cost
nothing — they never touch Google.

## Architecture

```
custom_components/park_visits/
├── __init__.py         # entry setup/unload, rate_park service, view registration
├── manifest.json       # HA integration manifest
├── const.py            # domain, defaults, Google Places config, attribute keys
├── util.py             # haversine distance + geodesic tile-centre calculation
├── coordinator.py      # tiled Google Places queries, ranking, review merging
├── storage.py          # persistent local reviews (place_id -> rating/liked/photos)
├── views.py            # HTTP: Place Details, photo proxy, photo upload/serve
├── config_flow.py      # setup + options UI (API key, centre point, radius, count)
├── geo_location.py     # one GeolocationEvent entity per tracked park
├── sensor.py           # summary "Nearby Parks" count sensor
├── button.py           # manual "Refresh parks" button — the only API trigger
├── services.yaml       # service descriptions (Developer Tools UI)
└── strings.json / translations/en.json
www/
├── park-visits-table-card.js     # sortable table, park detail panel, review form
└── park-visits-gallery-card.js   # collage of our review photos
dashboards/
└── park_visits_dashboard.yaml
```

## Requirements

Home Assistant 2024.6.0 or newer (uses modern `ConfigFlow`/`OptionsFlow`
and the core `aiohttp` client helper). No external Python dependencies —
all Google API calls go through Home Assistant's shared `aiohttp` session.
