# Facility Weather Operations

This version is intentionally simple. It uses only Python, GitHub Actions, GitHub Pages, and free NOAA/NWS government weather APIs.

## What it checks

For each airport it combines:

* The exact latitude/longitude NWS point forecast.
* The NWS hourly and raw grid forecast.
* Official active NWS alerts for the configured forecast zone.
* The airport METAR from the Aviation Weather Center for current observed conditions.
* The airport TAF from the Aviation Weather Center for airport-specific short-term forecast context.

The dashboard shows one operational banner: NORMAL, WATCH, ACTION, or CLOSE.

## Adaptive checking

GitHub wakes the Python job every 5 minutes. Python only calls the weather APIs when that facility is due:

* NORMAL: every 30 minutes.
* WATCH: every 15 minutes.
* ACTION: every 5 minutes.
* CLOSE: every 5 minutes.

Change these values in `facilities.json` if needed.

## Files

```text
Facility-Weather/
├── .github/
│   └── workflows/
│       └── weather-monitor.yml
├── docs/
│   ├── .nojekyll
│   ├── index.html        generated automatically
│   └── status.json       generated automatically
├── facilities.json
├── monitor.py
├── requirements.txt
└── README.md
```

## Airports already configured

Denver International Airport uses ICAO `KDEN`, NWS zone `COZ040`, and exact airport coordinates.

Washington Dulles International Airport uses ICAO `KIAD`, NWS zone `VAZ506`, and exact airport coordinates.

## First setup in GitHub

1. Upload all files and folders into the root of your GitHub repository.
2. Open the repository's `Actions` tab.
3. Open `Facility Weather Monitor`.
4. Click `Run workflow` once. This creates the first `docs/index.html` and `docs/status.json`.
5. Go to repository `Settings`.
6. Click `Pages` in the left menu.
7. Under `Build and deployment`, choose `Deploy from a branch`.
8. Select branch `main` and folder `/docs`.
9. Click `Save`.
10. GitHub will display the public website address on the Pages settings screen.

After that, the workflow wakes every five minutes automatically. You do not need Render and you do not need any email or API secrets.

## Changing thresholds

Open `facilities.json` and edit only the numbers in `settings`.

For example:

```json
"wind_watch_kt": 30,
"wind_action_kt": 35,
"wind_close_kt": 40
```

The included starting snow thresholds are 4 inches for WATCH, 6 inches for ACTION, and 8 inches for CLOSE.

## Adding another facility

Add another object inside the `facilities` list in `facilities.json`:

```json
{
  "name": "Example Airport",
  "icao": "KABC",
  "zone": "XXZ000",
  "latitude": 00.0000,
  "longitude": -00.0000
}
```

Use the airport ICAO identifier for METAR/TAF data and the appropriate NWS forecast zone for official zone alerts.

## Important lightning limitation

The NWS API and Aviation Weather Center data used here do not provide a live geolocated lightning-strike feed. The dashboard can identify thunderstorm forecast signals and official thunderstorm warnings, but it cannot certify that lightning has occurred within 7 miles of the airport. A real 7-mile / 30-minute lightning rule would require a separate lightning data source.

## Data sources

National Weather Service API: `api.weather.gov`

NOAA/NWS Aviation Weather Center Data API: `aviationweather.gov/api/data`
