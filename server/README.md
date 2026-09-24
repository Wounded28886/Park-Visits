# Park Visits — standalone server

Track the parks near you, tick them off as you go, and keep your own ratings,
notes and photos for each one. Runs on its own: one container, one folder, its
own address.

**Nothing else is required.** No Home Assistant, no database, no message
broker. It talks to Google Places (to find the parks) and optionally to your
Immich server (for photos) — nothing else, ever.

- **Parks near you, ranked** — pulled from Google Places, sorted by rating,
  with the ones nobody rates filtered out.
- **Your own reviews** — a visit date, a score per person, playground /
  scenery / wildlife / facilities / parking, what you liked and didn't, notes.
- **Photos** — upload your own, or match them from an Immich tag.
- **Still-to-go and visited views**, a progress bar, a "next up" park, and a
  gallery across every park you've photographed.
- **Add or remove parks by hand** — anything Google knows about, plus the
  ability to hide the ones you'll never visit (reversibly).

---

## Synology (Container Manager)

Nothing is built on the NAS — it pulls a ready-made image.

1. **Get a Google Places API key.** In the
   [Google Cloud console](https://console.cloud.google.com/): create a project,
   enable **Places API (New)**, then create an API key under
   *APIs & Services → Credentials*. Google's free tier covers ordinary use of
   this app comfortably — the park list is fetched only when you press
   **Refresh**, not on a timer.
2. **Container Manager → Project → Create.**
   - **Project name:** `park-visits`
   - **Path:** a new folder, e.g. `/volume1/docker/park-visits`
   - **Source:** *Create docker-compose.yml* and paste:

   ```yaml
   services:
     parks:
       image: ghcr.io/wounded28886/park-visits:latest
       container_name: park-visits
       restart: unless-stopped
       ports:
         - "8098:8098"
       volumes:
         - ./data:/data
       environment:
         GOOGLE_API_KEY: "paste-your-key-here"
         LOCATION: "Brisbane, Australia"
         RADIUS_KM: "25"
         MAX_PARKS: "60"
         PEOPLE: "Kids,Mum,Dad"
   ```

3. Click through; it downloads the image and starts in seconds.
4. Open **`http://<nas-ip>:8098`** and press **Refresh from Google** to fetch
   your parks the first time.

The project folder grows a `data/` directory with the park list, your reviews
and your photos. Add it to Hyper Backup and everything is covered.

**Updating:** Container Manager → the project → **Action → Reset**. Your
`data/` folder is untouched.

The image is public, multi-arch (`linux/amd64` and `linux/arm64`) and built by
GitHub Actions straight from this repository.

## Anywhere else

```bash
docker run -d --name park-visits -p 8098:8098 \
  -v /volume1/docker/park-visits/data:/data \
  -e GOOGLE_API_KEY=your-key \
  -e LOCATION="Brisbane, Australia" \
  --restart unless-stopped ghcr.io/wounded28886/park-visits:latest
```

Or run it straight from a checkout — it's plain Python with two dependencies:

```bash
pip install -r requirements.txt
GOOGLE_API_KEY=your-key LOCATION="Brisbane, Australia" DATA_DIR=./data \
  python server/app.py
```

## Settings

| Variable | Default | Meaning |
| --- | --- | --- |
| `GOOGLE_API_KEY` | — | **Required.** Places API (New) key |
| `LOCATION` | — | Where to search from: a suburb, city or address. Looked up once and remembered. |
| `LATITUDE` / `LONGITUDE` | — | Use these instead of `LOCATION` to skip the lookup entirely |
| `RADIUS_KM` | `25` | How far out to search |
| `MAX_PARKS` | `60` | How many parks to keep in the list |
| `PEOPLE` | `Kids,Mum,Dad` | Who gets their own score on a review |
| `IMMICH_URL` | — | Optional Immich server, e.g. `http://192.168.1.10:2283` |
| `IMMICH_API_KEY` | — | Optional, for the same |
| `IMMICH_MAX_ASSETS` | `200` | Most photos to pull for one park |
| `TITLE` | `Park Visits` | Heading on the page |
| `PORT` | `8098` | Port inside the container |
| `DATA_DIR` | `/data` | Where everything is stored — mount this |
| `LOG_LEVEL` | `INFO` | `DEBUG` for a lot more detail |
| `PUID` / `PGID` | `1000` | Run the server as this user instead. See below. |

### Permissions on the data folder

The server runs unprivileged. A folder you bind-mount belongs to whoever
created it on the host — on a NAS that is usually root — so the container
starts as root just long enough to hand that folder to its own user, then
drops root for good.

If you would rather it ran as an existing account instead of re-owning the
folder, set `PUID` and `PGID` to that account's ids and make sure it can
write there.

## What it costs

Google bills the Places API per call, so the app is careful with it:

- The park list is fetched **only** when you press *Refresh from Google* — never
  on a timer, and not even on start-up (the list is cached on disk against your
  search settings, so restarts are free).
- A park's details (opening hours, Google's reviews, photos) are fetched when
  you open that park, then cached for a day.
- Looking up `LOCATION` costs a single call, once, and the answer is saved.

Adding a park by name uses one cheap Text Search plus one details call.

## Photos from Immich

Set `IMMICH_URL` and `IMMICH_API_KEY` and each park can show photos straight
out of your own library: give a park a tag in the app and every Immich asset
with that tag appears under it. Nothing is copied — the server proxies the
thumbnails, so the photos stay in Immich.

Without Immich configured, every photo path simply falls back to the ones you
upload yourself.

> **There is no login.** Anyone who can reach the address can add a review.
> That's usually right for a house; if you want it reachable from outside, put
> it behind a reverse proxy that handles authentication.

## Under the hood

The server runs the **same integration code** that the Home Assistant version
of Park Visits runs — `custom_components/park_visits`, copied into the image
untouched. `server/ha_compat.py` supplies stand-ins for the handful of Home
Assistant pieces it expects (a storage helper, a service registry, an HTTP view
base class, an update coordinator), and `server/app.py` puts an aiohttp server
in front:

| Endpoint | Purpose |
| --- | --- |
| `GET /api/states` | Every park, as the cards consume them |
| `POST /api/services/park_visits/<service>` | The integration's own services |
| `POST /api/refresh` | Fetch the park list from Google |
| `GET /api/park_visits/...` | The integration's own views, unchanged |
| `GET /healthz` | `{ok:true}` plus the park count |

Because it is one codebase, a fix in either place lands in both.

| Path | What it is |
| --- | --- |
| `app.py` | The server: config, routes, entity states |
| `ha_compat.py` | The Home Assistant stand-ins |
| `public/index.html` | The page, and every colour it uses |
| `public/app.js` | Wires the cards to this server |

Tested by `test/test_server.py` — it runs the whole stack against a stand-in
for Google Places, so the suite costs nothing to run:

```bash
python test/test_server.py
```
