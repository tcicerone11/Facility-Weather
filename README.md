# Facility Weather Operations

A small, standalone Python weather decision-support dashboard for facility managers.

This version intentionally does **not** send email, text messages, or push notifications. It uses GitHub Actions to run Python, NOAA/NWS and NOAA Aviation Weather for weather data, and GitHub Pages to display the dashboard.

## What the dashboard does

For every configured facility it shows:

* **NORMAL** — no configured test threshold currently suggests an operational change.
* **WATCH** — monitor conditions and prepare.
* **ACTION** — a significant test threshold has been reached; take the protective action defined by your facility policy.
* **CLOSE CRITERIA MET** — a configured test closure threshold or critical warning has been reached; follow your approved closure or emergency procedure.

The dashboard deliberately says **CLOSE CRITERIA MET** rather than automatically ordering a closure. The code is decision support. The thresholds in this test repository are examples, not approved facility policy.

## Plain-language data sources

The website uses plain-language labels. Technical aviation data is hidden inside expandable details.

* **Current Airport Conditions** means a NOAA Aviation Weather METAR observation. This is used only when an airport ICAO code is configured.
* **Airport Short Term Forecast** means a NOAA Aviation Weather TAF. This is used only when an airport ICAO code is configured.
* **Official Weather Alerts** are active National Weather Service alerts. The program checks alerts affecting the exact facility latitude/longitude first, then adds broader configured zone alerts.
* **7 Day Facility Outlook** comes from the National Weather Service point/grid forecast for the facility's coordinates.

## Adaptive weather checks

The GitHub workflow wakes every 5 minutes. Python decides whether each facility actually needs another NOAA request.

* NORMAL: every 30 minutes
* WATCH: every 15 minutes
* ACTION: every 5 minutes
* CLOSE CRITERIA MET: every 5 minutes

These values are editable in `facilities.json`.

## Files

```text
.github/
  workflows/
    weather-monitor.yml

docs/
  .nojekyll
  index.html       # automatically generated
  status.json      # automatically generated

facilities.json    # facilities and test thresholds
monitor.py         # all Python logic and website generation
requirements.txt
README.md
```

## Adding another airport

Add an entry under `facilities` in `facilities.json`:

```json
{
  "id": "example-airport",
  "name": "Example Airport",
  "icao": "KABC",
  "zone": "XXZ000",
  "latitude": 40.0000,
  "longitude": -75.0000
}
```

The ICAO code enables airport observation and short-term airport forecast data.

## Adding a non-airport facility

A normal facility does not need an ICAO code:

```json
{
  "id": "community-center",
  "name": "Community Recreation Center",
  "zone": "VAZ000",
  "latitude": 39.0000,
  "longitude": -77.0000
}
```

The dashboard will automatically hide airport-only sections and continue using the exact latitude/longitude for NWS point forecasts and alerts.

The `zone` field is optional. If you include it, the dashboard can show broader zone alerts as secondary context. Exact point alerts are checked first.

## Test thresholds

The current thresholds are examples only. Change them in `facilities.json` when you have approved operating criteria.

```json
"wind_watch_kt": 30,
"wind_action_kt": 35,
"wind_close_kt": 40,
"snow_watch_in": 4,
"snow_action_in": 6,
"snow_close_in": 8,
"precip_watch_in": 2,
"precip_action_in": 4,
"thunder_watch_hours": 6
```

The website displays wind in mph for easier reading, while the threshold engine keeps the test wind values in knots.

## Deploying an update to your existing GitHub Pages site

1. Open your Facility Weather repository in GitHub.
2. Replace `monitor.py` with the new version.
3. Replace `facilities.json` with the new version.
4. Replace `README.md` if you want the updated instructions in GitHub.
5. Leave `requirements.txt`, `.github/workflows/weather-monitor.yml`, and `docs/.nojekyll` in place.
6. Go to **Actions**.
7. Open **Facility Weather Monitor**.
8. Click **Run workflow**, keep the `main` branch selected, then click **Run workflow** again.
9. Wait for the green checkmark.
10. Open the GitHub Pages website. If the old appearance is cached, refresh the page once.

The workflow regenerates `docs/index.html` and `docs/status.json` for you. You do not manually edit those two generated files.

## Important limitation: lightning

This version can identify thunderstorm potential and official thunderstorm alerts. It cannot calculate the distance to a live lightning strike. A rule such as “close a pool for lightning within 7 miles and wait 30 minutes after the last strike” requires a separate real-time lightning-strike data source.

## Notifications

This repository intentionally has no notification dependency. A separate version can later add email, SMS, or app notifications without changing this standalone dashboard.
