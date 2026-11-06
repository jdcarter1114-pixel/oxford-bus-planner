# Oxford Move — Bus Journey Planner

**A full-stack public transport route planner for Oxford, England.** Enter a starting location and destination (or use browser geolocation), choose when to leave, and compare the earliest scheduled bus-and-walking journeys — including a change of bus where needed.

> **Portfolio project — not an official passenger-information service.** Journeys are calculated from published **scheduled** GTFS timetables; live disruption, fares, accessibility and walking path networks are not currently modelled. Walking time and map paths are approximate. Always check with the operator before travelling.

## Features

- Search Oxford addresses, postcodes and landmarks with OpenStreetMap Nominatim (explicit search only; local caching and throttling).
- Use your current location (browser permission required) or select either endpoint by clicking the map.
- Explore bus-only journeys plus walking connections, waiting and transfers.
- Compare the fastest scheduled arrival against meaningful alternative services, including walking-only when practical.
- Display boarding/alighting stops, bus route numbers, headsigns and departure/arrival times.
- Draw routes and stops on an interactive Leaflet/OpenStreetMap map.
- Import public GTFS data into SQLite using a reproducible Python ETL pipeline.
- Run automated unit/integration tests and GitHub Actions CI.

## Technology

| Layer | Technology |
|---|---|
| UI | HTML, CSS, vanilla JavaScript, Leaflet |
| API | Python 3.11+, Flask, HTTP/JSON |
| Data | GTFS ZIP files, SQLite, SQL window functions |
| Routing | Timetable **connection scan**, walking transfer links, earliest-arrival comparison |
| Testing | pytest and GitHub Actions |

## How it works

```text
Oxford Bus GTFS ZIP
       │
       ▼
 GTFS import (validation, calendars, stops, trips, stop_times)
       │
       ▼
SQLite + precomputed consecutive-stop bus connections
       │
       ▼
Flask /api/routes ──► calendar exceptions + scheduled departures
       │                                 │
       └──────────► earliest-arrival connection scan
                                         │
                               short walking connections
                                         │
                              JSON itineraries + estimates
                                         │
                               JavaScript + Leaflet UI
```

This project does **not** call Google Maps, Citymapper, Trainline or another journey-planning service for its routes. It calculates route options from the imported timetable itself.

## Installation (Windows / VS Code)

Clone/download the repo, open a terminal in its root folder, then:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

On macOS/Linux use `python3 -m venv .venv`, `source .venv/bin/activate`, and then `python -m pip install -r requirements.txt`.

### 1. Get real Oxford bus timetables

Oxford Bus Company publishes **Current GTFS** on its [open-data page](https://www.oxfordbus.co.uk/open-data). Download its GTFS ZIP and import it:

```powershell
python -m planner.import_gtfs data/your-downloaded-file.zip
```

You can alternatively attempt to download and import the current feed in one command:

```powershell
python -m planner.import_gtfs --download
```

The operator may change its download link or block automated downloads. If that happens, use the web page and the file import command above. The ZIP contains `stops.txt`, `routes.txt`, `trips.txt`, `stop_times.txt` and `calendar.txt` and/or `calendar_dates.txt`; both calendar sources are supported. **This repo does not redistribute a real operator feed**; the data is downloaded by each developer so it is not mistaken for current at a later date.

The app currently covers **services in the imported feed**, initially Oxford Bus Company. Some Oxford services operated by other companies may not appear. Incorporating additional GTFS feeds, e.g. the [Bus Open Data Service](https://www.gov.uk/guidance/find-and-use-bus-open-data), is a natural next step.

### No feed available? Try the explicitly synthetic demo

A small fictitious timetable is included as `examples/demo_oxford_gtfs.zip`. It uses Oxford-shaped coordinates but **all X1/X2/X3 routes and times in it are invented**, purely for tests and UI demonstration. It is **not suitable for actual journey planning**.

```powershell
python -m planner.import_gtfs examples/demo_oxford_gtfs.zip
```

For a demo route, set the departure to **Thursday 5 November 2026 at 09:00**, select the Railway Station and Headington Shops points on the map, and compare a faster two-bus journey with an invented direct option.

### 2. Run the app

```powershell
python app.py
```

Open **http://127.0.0.1:5000**.

Type two Oxford addresses and select **Find my route**, or click **Select start on map** and **Select destination** to avoid address lookup. The browser's location button works on `localhost` and HTTPS, subject to permission. Internet access is required for map tiles and address searches, and optionally to download the timetable. The **routing algorithm itself runs locally** once the feed is imported.

## Run tests

```powershell
python -m pytest -q
```

The test suite uses only *synthetic GTFS*, so no network or live operator account is required. It covers importing, re-importing, fastest transfer routes, direct buses, missing service, calendar exception days, overnight time parsing and geographical helper functions.

## HTTP API

| Endpoint | Purpose |
|---|---|
| `GET /api/health` | Imported-feed status and number of stops |
| `GET /api/stops?point_lat=51.7533&point_lon=-1.2694` | Nearest stops and estimated walking minutes |
| `GET /api/geocode?q=Oxford%20Railway%20Station` | Address lookup (throttled and cached) |
| `GET /api/routes?start_lat=51.7533&start_lon=-1.2694&end_lat=51.7598&end_lon=-1.2157&depart=2026-11-05T09:00` | Scheduled route options |

All request times are interpreted in **Europe/London** unless an offset is provided. The planner searches up to five hours forward. Because scheduled GTFS can include services spanning midnight, service days surrounding the requested date are considered. The website limits its requested locations to the Oxford area.

## Route selection algorithm

1. Read route stops and nearby origin/destination boarding candidates (up to 1.2 km away).
2. Determine **active GTFS service IDs** for the requested date using weekly schedules and `calendar_dates` additions/removals.
3. Read consecutive-stop **connections** for an approximately five-hour departure window. Each connection has a boarding stop, alighting stop, departure time, arrival time and trip identifier.
4. Scan connections by departure time, recording the earliest feasible arrival at each stop and whether the traveller is already aboard a particular trip. A 90-second margin is applied to bus-to-bus changes, but staying aboard the same bus incurs no such margin.
5. Add short walking transfers (up to 200 m between nearby stops) and access/egress walking times. Track predecessor steps to reconstruct each itinerary.
6. Compare total door-to-door arrival time. Re-run with the chosen first service excluded to seek an alternative route.

Compared with a generic unweighted graph search, time-dependent transport routing must account for **when** a connection departs and whether the passenger can reach it before departure. Walking time here uses great-circle distance with a 1.28 detour multiplier and an assumed speed of 4.5 km/h. This is an **estimate, not a pedestrian routing engine**. The map joins GTFS stop coordinates schematically rather than using actual road or sidewalk geometry.

### Engineering trade-offs and limitations

- **Timetable rather than realtime.** No live bus positions, disruptions, cancelled journeys or guaranteed connections.
- **GTFS coverage varies.** Imported operator feed may omit other operators and seasonal services; scheduled results depend entirely on its quality/currentness.
- **Simplified transfer constraints.** Default 90-second transfer buffer may be too short, especially at a large interchange.
- **Walking is approximate.** Neither pedestrian routing nor mobility constraints (stairs, crossing points) are modelled. For production, connect an accessible walking graph provider or self-host a suitable router.
- **Some GTFS features remain unsupported.** In particular `frequencies.txt`-defined headway service, stop-specific `pickup_type`/`drop_off_type`, transfers specified by `transfers.txt`, and intermediate stop records without times need a fuller implementation before production use.
- **DST edge cases.** Late-night journeys during a daylight saving change need timezone ambiguity handling beyond this prototype.
- **Not a hosted passenger service.** A public deployment should use a hosted geocoding service with an appropriate agreement, stronger API rate limits, monitoring, secure configuration and regular feed-refresh jobs.

## Public address search: usage policy

This project includes direct, deliberate low-volume [Nominatim](https://operations.osmfoundation.org/policies/nominatim/) search for a local portfolio demo. The client makes **no autocomplete requests**; searches are server-side, rate-limited to fewer than one request per second in a **single-process** Flask run, and successful results are cached in SQLite. Provide an identifying User-Agent including a contact method using the `GEOCODER_USER_AGENT` environment variable, e.g.:

```powershell
$env:GEOCODER_USER_AGENT = "OxfordMove/1.0 (contact: you@example.com)"
```

The public Nominatim endpoint is **not intended for heavy use or production deployment**. In a multi-worker deployment, the simple in-memory throttle is not sufficient; use a managed geocoding provider or centrally enforced rate limiting. The service can be switched by editing `GEOCODE_URL` in `app.py`. Map data and tile usage remain subject to OpenStreetMap licence and [tile policy](https://operations.osmfoundation.org/policies/tiles/).

## Repository structure

```text
oxford-bus-planner/
├── app.py                    Flask application and HTTP API
├── planner/
│   ├── geometry.py           Geographical helpers
│   ├── import_gtfs.py        GTFS ZIP → SQLite importer
│   └── routing.py            Timetable connection-scan planner
├── static/
│   ├── script.js             Interactive map and request handling
│   └── style.css             Responsive interface
├── templates/index.html      Main web page
├── examples/
│   ├── make_demo_feed.py     Invented GTFS generator
│   └── demo_oxford_gtfs.zip  Clearly labelled synthetic data
├── tests/                    Offline routing and importer tests
├── .github/workflows/        CI workflow
├── requirements.txt
├── .env.example
└── LICENSE
```

## Why I built it / future improvements

This portfolio project brings together **software engineering, relational data modelling, transport network optimisation, API development and data visualisation**. Next steps include (1) unifying other Oxford bus operators through BODS feeds, (2) true pedestrian routing, (3) GTFS realtime data, (4) service-aware uncertainty in arrival times, and (5) a production hosting pipeline with scheduled GTFS refreshes.

## Open data credits

Oxford Bus Company network GTFS is made available under the [Open Government Licence v3.0](https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/) as described on its [data page](https://www.oxfordbus.co.uk/open-data). OpenStreetMap data is © [OpenStreetMap contributors](https://www.openstreetmap.org/copyright) under the applicable licence. The accompanying **demo GTFS ZIP is invented**, not operator data.

Code: MIT licence (see `LICENSE`).
