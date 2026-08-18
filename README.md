# Park Visits

A Home Assistant custom integration that tracks the top-rated parks within a
configurable radius of a location **you type in** during setup — a suburb,
city or street address, resolved automatically to a point on the map — using
the **Google Places API**, ranked by Google rating.

The dashboard is a sortable table: click a column to sort by it, click a park
to open its detail panel with Google's photos and reviews, and write your own
review — a visit date, per-person and per-aspect ratings, what you liked,
what you didn't, notes and photos. A second **Visited** view tracks progress
against the whole tracked list with a "23 / 100 visited" bar and a table of
every visited park.

## What it does

- During setup, resolves the suburb/city/address you type into coordinates
  via Google Places **Text Search** — no separate Geocoding API needed, and
  no latitude/longitude to look up yourself.
- Queries the **Google Places API (New)** for parks around that resolved
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
  - Four summary **sensors**: `sensor.nearby_parks` (how many parks are
    tracked), `sensor.next_park` (the park we plan to visit next),
    `sensor.last_visited_park` (the most recently *visited* park, by visit
    date) and `sensor.parks_visited` (how many of the tracked parks have a
    review, with `total` and `percent` attributes — what the Visited view's
    progress bar is built from). The first three are usable in
    automations — "remind us about the next park on Saturday morning", say.
  - A **"Refresh parks" button** — see [Refresh cost](#refresh-cost-and-cadence).
- Registers services to record and remove reviews — **`rate_park`** (visit
  date, Kids Rating required, Mums/Dads/Playground/Scenery/Wildlife/
  Facilities/Parking ratings optional, liked, disliked, notes — see
  [Family ratings](#family-ratings)), **`delete_review`** (also deletes that
  review's photo files) and **`delete_photo`** (one photo) — plus
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
    the visit date, every rating, what you liked and didn't, add notes,
    attach photos, delete individual photos, or delete the whole review. The
    card's `columns` config controls which columns show (see
    [Family ratings](#family-ratings)), and `only_visited` / `show_progress`
    power the Visited view. Set `show_upload: false` to hide the "Add photos"
    field when a park's pictures come from Immich instead.
  - `park-visits-gallery-card` — a collage of every photo attached to a
    review or matched by a park's Immich tag, filterable by park and by
    Immich tag (`show_filter: false` hides the filter bar). Click one to see
    it large alongside the park name and our review, and page through the
    rest — paging follows whatever the filter has narrowed things to.
- Optionally pulls a park's photos straight from **Immich** by tag, so they
  don't have to be uploaded into Home Assistant at all — see
  [Photos from Immich](#photos-from-immich).

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

## Photos from Immich

Uploading every park photo into Home Assistant adds up fast. If you already
keep your library in [Immich](https://immich.app/), the integration can show a
park's photos straight from there instead — nothing is copied, and nothing is
written to disk.

It works by **matching tags**. Tag the photos in Immich however you already
do (one tag per park), then link that tag to the park:

1. Put your Immich URL (e.g. `http://192.168.1.10:2283`) and an API key
   (Immich → Account Settings → API Keys) into the Park Visits options.
   Use an address that reaches Immich **directly** — a public hostname sitting
   behind Cloudflare Access, Authelia or a similar login portal will bounce
   the API call to a sign-in page, since those don't know about Immich's
   `x-api-key`. Home Assistant is usually on the same network as Immich, so
   the LAN address is both simpler and faster.
2. Open a park in the table card. Under **Photos from Immich**, pick the tag
   whose photos belong to it.
3. Every photo carrying that tag now shows on the park and in the gallery.

The link is stored per `place_id`, so it survives refreshes and a park
dropping out of the tracked list. Removing the tag (choose *— no tag —*)
only unlinks it; the photos in Immich are never touched.

**Max Immich photos per park** in the options controls how many tagged
photos a park shows — 250 by default, up to 1000 (Immich's own page-size
ceiling). Grid tiles load Immich's small thumbnail (~19KB) lazily and the full preview
(~370KB) is fetched only for the photo you actually open — a 20x difference
that's what makes a 135-photo park workable over a phone connection. Every
thumbnail needs its own signed URL, so they're all signed in one parallel
burst; done one at a time, a large tag would stall the popup for seconds on
a remote connection.

The Immich API key is treated exactly like the Google one: it stays
server-side, and thumbnails are relayed through the integration behind a
short-lived signed URL. Leave the two Immich fields blank and none of this
appears anywhere in the UI.

Two services back it, if you'd rather script it: **`set_park_tag`**
(`place_id`, `tag_id`) and **`clear_park_tag`** (`place_id`).

With Immich supplying the pictures you can turn the upload field off entirely
— set `show_upload: false` on the table card. Existing uploaded photos still
display and can still be deleted; only the "Add photos" input goes away.

## Family ratings

A review is a **visit date** (defaults to today, but can be back-dated —
this is what drives "last visited" and the Visited view's sort, not when you
happened to type the review in) plus up to eight ratings out of 10:

- **Kids Rating** — the only rating that's required.
- **Mums Rating**, **Dads Rating** — optional.
- **Playground**, **Scenery**, **Wildlife**, **Facilities**, **Parking** —
  optional per-aspect scores.

**Overall Rating** isn't entered — it's the average of whichever of Kids,
Mums and Dads ratings were filled in, computed fresh every time
(`Review.overall_rating` in `storage.py`) so it can never drift out of sync
with the ratings it's built from. It's what shows in the main Parks table
and what `sensor.last_visited_park` reports.

The table card only shows the columns you list in its `columns` config
(anything omitted just isn't rendered — the underlying data is still there).
The default Parks view keeps things compact: rank, name, Google rating,
categories, distance, Overall Rating. The Visited view opts into every
rating column plus the visit date — see `dashboards/park_visits_dashboard.yaml`
for the exact list, or write your own.

**If you're upgrading from a version before this**, your existing single
0–10 rating becomes the **Kids Rating** on every existing review, and the
date portion of its old timestamp becomes its **visit date** — nothing is
lost, but Mums/Dads/Playground/Scenery/Wildlife/Facilities/Parking start
blank on those older reviews until you edit them. This happens automatically
the first time each review is loaded; there's no manual migration step.

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
2. Paste your Google Places API key, type in a **location** to search
   around — a suburb, city or street address (e.g. "Cornubia QLD" or
   "123 Example St, Brisbane") — and set the radius (default 100 km) and
   number of parks to show (default top 100). The location is resolved to
   coordinates automatically; if it can't be found, the form shows an error
   so you can try a more specific location.
3. Optionally fill in the **Immich URL** and **Immich API key** to pull park
   photos from your own library, and **Max Immich photos per park** to cap how
   many each park shows — see [Photos from Immich](#photos-from-immich).
   Leave the URL and key blank to skip it entirely.
4. You can change any of this later via the integration's **Configure**
   button — this triggers a reload and regenerates the tracked parks.

### 4. Add the dashboard

Nothing manual needed for the cards themselves: they live inside
`custom_components/park_visits/www/`, so the integration serves them and
registers them on every dashboard itself the moment it's set up (via
`add_extra_js_url`) — no `config/www` copy and no "Add Resource" step, in
HACS or manual installs alike. If you update the integration and a card
doesn't seem to pick up a change, **hard-refresh your browser** — that's
almost always a cached copy of the JS file, not a setup problem.

> **Upgrading from an older version?** Earlier versions needed the cards
> copied to `config/www` and added manually under **Settings > Dashboards >
> Resources**. After updating, remove that manual resource entry and delete
> `config/www/park-visits-table-card.js` / `park-visits-gallery-card.js` if
> you added them — otherwise the card loads twice and logs a harmless but
> noisy "already defined" warning in the browser console.

1. **Settings > Dashboards > Add Dashboard > New dashboard from scratch**,
   give it a name, then open it and choose **Edit in YAML** from the
   three-dot menu.
2. Paste the contents of
   [`dashboards/park_visits_dashboard.yaml`](dashboards/park_visits_dashboard.yaml).

This gives you three views: **Parks** (the top-rated list), **Visited**
(progress bar + every visited park with all its ratings) and **Gallery**
(photo collage). The cards filter by the `source: park_visits` attribute
rather than entity IDs, so they keep working if Home Assistant suffixes
your entity names.

## Refresh cost and cadence

There is **no automatic polling**. Google is contacted only when:

| Action | Cost |
|---|---|
| Adding the integration for the first time | One location lookup + one full park search |
| Changing the location, radius or park count | One location lookup + one full park search |
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
├── __init__.py         # entry setup/unload, rate_park service, view/frontend registration
├── manifest.json       # HA integration manifest
├── const.py            # domain, defaults, Google Places config, attribute keys
├── util.py             # haversine distance + geodesic tile-centre calculation
├── geocoding.py         # resolves a typed suburb/city/address to coordinates
├── coordinator.py      # tiled Google Places queries, ranking, review merging
├── storage.py          # persistent local reviews (place_id -> rating/liked/photos)
├── views.py            # HTTP: Place Details, photo proxy, photo upload/serve, Immich tags/thumbs
├── immich.py           # optional Immich client: list tags, find tagged assets, fetch thumbnails
├── frontend.py          # serves www/ and registers the cards on every dashboard
├── config_flow.py      # setup + options UI (API key, location, radius, count)
├── geo_location.py     # one GeolocationEvent entity per tracked park
├── sensor.py           # summary "Nearby Parks" count sensor
├── button.py           # manual "Refresh parks" button — the only API trigger
├── services.yaml       # service descriptions (Developer Tools UI)
├── strings.json / translations/en.json
└── www/
    ├── park-visits-table-card.js     # sortable table, park detail panel, review form
    ├── park-visits-gallery-card.js   # collage of review + Immich-tagged photos
    └── probe.html                    # browser diagnostic for old embedded displays
dashboards/
└── park_visits_dashboard.yaml
```

Bundling the cards inside `custom_components/park_visits/www/` (rather than
a top-level `www/`) is deliberate: HACS downloads and updates the whole
`custom_components/park_visits/` tree as one unit, so the cards ship and
update with the integration automatically. `frontend.py` serves that folder
at a URL and calls `add_extra_js_url()` so every dashboard picks the cards
up without a manual Lovelace "Add Resource" step.

## Requirements

Home Assistant 2024.6.0 or newer (uses modern `ConfigFlow`/`OptionsFlow`
and the core `aiohttp` client helper). No external Python dependencies —
all Google API calls go through Home Assistant's shared `aiohttp` session.
