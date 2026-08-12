import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent
CONFIG_FILE = ROOT / "facilities.json"
DOCS = ROOT / "docs"
STATUS_FILE = DOCS / "status.json"
HTML_FILE = DOCS / "index.html"

NWS = "https://api.weather.gov"
AWC = "https://aviationweather.gov/api/data"

HEADERS = {
    "User-Agent": "FacilityWeatherGitHubPages/2.0",
    "Accept": "application/geo+json",
}
AWC_HEADERS = {"User-Agent": "FacilityWeatherGitHubPages/2.0"}

LEVEL = {"normal": 0, "watch": 1, "action": 2, "close": 3}

STATUS_COPY = {
    "normal": {
        "label": "NORMAL",
        "summary": "No configured weather condition currently suggests an operational change.",
        "action": "Continue normal operations and routine monitoring.",
    },
    "watch": {
        "label": "WATCH",
        "summary": "Weather could affect operations if conditions develop as forecast.",
        "action": "Monitor conditions and prepare staff, equipment, or outdoor operations.",
    },
    "action": {
        "label": "ACTION",
        "summary": "A significant weather threshold has been reached or is expected.",
        "action": "Take the protective action defined by your facility's operating plan.",
    },
    "close": {
        "label": "CLOSE CRITERIA MET",
        "summary": "A configured closure threshold or critical weather warning has been reached.",
        "action": "Follow your approved closure, restriction, or emergency procedure.",
    },
}

CLOSE_EVENTS = {
    "Tornado Warning",
    "Extreme Wind Warning",
    "Flash Flood Warning",
    "Hurricane Warning",
    "Storm Surge Warning",
    "Tsunami Warning",
}

ACTION_EVENTS = {
    "Severe Thunderstorm Warning",
    "Blizzard Warning",
    "Ice Storm Warning",
    "Winter Storm Warning",
    "High Wind Warning",
    "Flood Warning",
    "Extreme Heat Warning",
    "Excessive Heat Warning",
}

WATCH_EVENTS = {
    "Tornado Watch",
    "Severe Thunderstorm Watch",
    "Winter Storm Watch",
    "High Wind Watch",
    "Flood Watch",
    "Flash Flood Watch",
    "Winter Weather Advisory",
    "Wind Advisory",
    "Heat Advisory",
    "Dense Fog Advisory",
}


def now_utc():
    return datetime.now(timezone.utc)


def iso(dt):
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def parse_dt(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def load_json(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def get_json(url, params=None, headers=None, timeout=25):
    r = requests.get(url, params=params, headers=headers or HEADERS, timeout=timeout)
    if r.status_code == 204:
        return []
    r.raise_for_status()
    return r.json()


def c_to_f(v):
    return None if v is None else round((float(v) * 9 / 5) + 32, 1)


def kt_to_mph(v):
    return None if v is None else round(float(v) * 1.15078, 1)


def mps_to_kt(v):
    return None if v is None else round(float(v) * 1.943844, 1)


def kmh_to_kt(v):
    return None if v is None else round(float(v) * 0.539957, 1)


def mm_to_in(v):
    return None if v is None else round(float(v) / 25.4, 2)


def max_level(current, proposed):
    return proposed if LEVEL[proposed] > LEVEL[current] else current


def facility_key(facility):
    return facility.get("id") or facility.get("icao") or facility.get("name")


def parse_metar_wind(raw):
    if not raw:
        return None, None
    m = re.search(r"\b(?:\d{3}|VRB)(\d{2,3})(?:G(\d{2,3}))?KT\b", raw)
    if not m:
        return None, None
    return float(m.group(1)), float(m.group(2)) if m.group(2) else None


def parse_metar_visibility(raw):
    if not raw:
        return None
    m = re.search(r"\b(?:(\d+)\s+)?(\d+)/(\d+)SM\b", raw)
    if m:
        whole = float(m.group(1) or 0)
        return round(whole + float(m.group(2)) / float(m.group(3)), 2)
    m = re.search(r"\b(\d+(?:\.\d+)?)SM\b", raw)
    return float(m.group(1)) if m else None


def fetch_metar(icao):
    if not icao:
        return None
    data = get_json(f"{AWC}/metar", {"ids": icao, "format": "json"}, AWC_HEADERS)
    if not data:
        return None
    row = data[0]
    raw = row.get("rawOb") or row.get("raw_text") or row.get("raw") or ""
    wind, gust = parse_metar_wind(raw)
    if wind is None:
        wind = row.get("wspd") or row.get("windSpeed")
    if gust is None:
        gust = row.get("wgst") or row.get("windGust")
    temp_c = row.get("temp") if row.get("temp") is not None else row.get("tempC")
    wind = float(wind) if wind is not None else None
    gust = float(gust) if gust is not None else None
    return {
        "raw": raw,
        "observed": row.get("reportTime") or row.get("obsTime") or row.get("receiptTime"),
        "wind_kt": wind,
        "wind_mph": kt_to_mph(wind),
        "gust_kt": gust,
        "gust_mph": kt_to_mph(gust),
        "temperature_f": c_to_f(temp_c),
        "visibility_sm": parse_metar_visibility(raw),
        "flight_category": row.get("fltCat") or row.get("flightCategory"),
    }


def fetch_taf(icao):
    if not icao:
        return None
    data = get_json(f"{AWC}/taf", {"ids": icao, "format": "json"}, AWC_HEADERS)
    if not data:
        return None
    row = data[0]
    raw = row.get("rawTAF") or row.get("raw_text") or row.get("raw") or ""
    upper = raw.upper()
    return {
        "raw": raw,
        "issued": row.get("issueTime") or row.get("issue_time"),
        "valid_from": row.get("validTimeFrom") or row.get("valid_from"),
        "valid_to": row.get("validTimeTo") or row.get("valid_to"),
        "thunder": "TS" in upper,
        "snow": bool(re.search(r"\bSN\b|\bSHSN\b|\bBLSN\b", upper)),
        "freezing_precip": bool(re.search(r"\bFZRA\b|\bFZDZ\b", upper)),
    }


def nws_point_data(lat, lon):
    point = get_json(f"{NWS}/points/{lat:.4f},{lon:.4f}")
    p = point.get("properties", {})
    hourly = get_json(p["forecastHourly"]) if p.get("forecastHourly") else {"properties": {"periods": []}}
    forecast = get_json(p["forecast"]) if p.get("forecast") else {"properties": {"periods": []}}
    grid = get_json(p["forecastGridData"]) if p.get("forecastGridData") else {"properties": {}}
    return point, hourly, forecast, grid


def value_series(prop, kind, hours=168):
    if not isinstance(prop, dict):
        return []
    out = []
    end = now_utc() + timedelta(hours=hours)
    for item in prop.get("values", []) or []:
        start_text = str(item.get("validTime", "")).split("/", 1)[0]
        dt = parse_dt(start_text)
        if not dt or dt > end:
            continue
        v = item.get("value")
        if v is None:
            continue
        unit = (prop.get("uom") or "").lower()
        v = float(v)
        if kind == "wind":
            if "km_h" in unit or "km/h" in unit:
                v = kmh_to_kt(v)
            elif "m_s" in unit or "m/s" in unit:
                v = mps_to_kt(v)
        elif kind in {"precip", "snow"}:
            if "mm" in unit:
                v = mm_to_in(v)
            elif "cm" in unit:
                v = round(v / 2.54, 2)
        out.append(v)
    return out


def alert_from_feature(feature, source):
    p = feature.get("properties", {})
    return {
        "event": p.get("event") or "Weather Alert",
        "headline": p.get("headline") or "",
        "severity": p.get("severity") or "Unknown",
        "urgency": p.get("urgency") or "Unknown",
        "expires": p.get("expires"),
        "source": source,
    }


def fetch_point_alerts(lat, lon):
    data = get_json(f"{NWS}/alerts/active", {"point": f"{lat:.4f},{lon:.4f}"})
    if not isinstance(data, dict):
        return []
    return [alert_from_feature(f, "Exact facility location") for f in data.get("features", [])]


def fetch_zone_alerts(zone):
    if not zone:
        return []
    data = get_json(f"{NWS}/alerts/active/zone/{zone}")
    if not isinstance(data, dict):
        return []
    return [alert_from_feature(f, f"Broader NWS zone {zone}") for f in data.get("features", [])]


def merge_alerts(point_alerts, zone_alerts):
    seen = set()
    merged = []
    for item in point_alerts + zone_alerts:
        key = (item.get("event"), item.get("headline"), item.get("expires"))
        if key in seen:
            continue
        seen.add(key)
        merged.append(item)
    return merged


def evaluate(facility, settings):
    lat = float(facility["latitude"])
    lon = float(facility["longitude"])
    icao = facility.get("icao")
    zone = facility.get("zone")

    point, hourly, forecast, grid = nws_point_data(lat, lon)
    metar = fetch_metar(icao)
    taf = fetch_taf(icao)
    alerts = merge_alerts(fetch_point_alerts(lat, lon), fetch_zone_alerts(zone))

    gp = grid.get("properties", {})
    gusts = value_series(gp.get("windGust"), "wind", 24)
    precip = value_series(gp.get("quantitativePrecipitation"), "precip", 168)
    snow = value_series(gp.get("snowfallAmount"), "snow", 168)

    peak_gust = max(gusts) if gusts else None
    if metar and metar.get("gust_kt") is not None:
        peak_gust = max(peak_gust or 0, metar["gust_kt"])

    precip_7d = round(sum(precip), 2)
    snow_7d = round(sum(snow), 2)

    periods = hourly.get("properties", {}).get("periods", []) or []
    thunder_cutoff = now_utc() + timedelta(hours=settings["thunder_watch_hours"])
    thunder_soon = False
    for p in periods:
        dt = parse_dt(p.get("startTime"))
        text = f"{p.get('shortForecast') or ''} {p.get('detailedForecast') or ''}".lower()
        if dt and dt <= thunder_cutoff and "thunder" in text:
            thunder_soon = True
            break
    if taf and taf.get("thunder"):
        thunder_soon = True

    status = "normal"
    reasons = []

    def add(level, title, detail, action):
        nonlocal status
        status = max_level(status, level)
        reasons.append({"level": level, "title": title, "detail": detail, "action": action})

    for a in alerts:
        event = a["event"]
        source = a.get("source", "NWS")
        if event in CLOSE_EVENTS:
            add("close", event, a["headline"] or event,
                f"Critical official alert. Follow the facility's emergency or closure procedure. Source: {source}.")
        elif event in ACTION_EVENTS:
            add("action", event, a["headline"] or event,
                f"Review and implement the protective action in the facility plan. Source: {source}.")
        elif event in WATCH_EVENTS:
            add("watch", event, a["headline"] or event,
                f"Monitor updates and prepare staff or equipment. Source: {source}.")

    if peak_gust is not None:
        mph = kt_to_mph(peak_gust)
        if peak_gust >= settings["wind_close_kt"]:
            add("close", "Strong wind threshold reached",
                f"Observed or forecast gusts may reach about {mph:.0f} mph ({peak_gust:.0f} kt).",
                "Follow your approved high-wind closure or restriction procedure.")
        elif peak_gust >= settings["wind_action_kt"]:
            add("action", "Strong winds expected",
                f"Observed or forecast gusts may reach about {mph:.0f} mph ({peak_gust:.0f} kt).",
                "Secure vulnerable outdoor items and take the protective action defined by the facility plan.")
        elif peak_gust >= settings["wind_watch_kt"]:
            add("watch", "Wind may affect operations",
                f"Observed or forecast gusts may reach about {mph:.0f} mph ({peak_gust:.0f} kt).",
                "Monitor wind conditions and prepare for outdoor restrictions if winds increase.")

    if snow_7d >= settings["snow_close_in"]:
        add("close", "Heavy snow threshold reached",
            f"The 7 day outlook contains about {snow_7d:.1f} inches of forecast snow.",
            "Follow the facility's approved severe snow or closure procedure.")
    elif snow_7d >= settings["snow_action_in"]:
        add("action", "Significant snow expected",
            f"The 7 day outlook contains about {snow_7d:.1f} inches of forecast snow.",
            "Prepare snow response resources and review staffing or access plans.")
    elif snow_7d >= settings["snow_watch_in"]:
        add("watch", "Snow may affect operations",
            f"The 7 day outlook contains about {snow_7d:.1f} inches of forecast snow.",
            "Monitor forecast changes and begin snow response planning.")

    if precip_7d >= settings["precip_action_in"]:
        add("action", "Heavy precipitation outlook",
            f"About {precip_7d:.1f} inches of liquid precipitation is represented in the 7 day outlook.",
            "Review drainage, flooding, outdoor work, and access concerns.")
    elif precip_7d >= settings["precip_watch_in"]:
        add("watch", "Wet weather may affect operations",
            f"About {precip_7d:.1f} inches of liquid precipitation is represented in the 7 day outlook.",
            "Monitor drainage, outdoor work, and access conditions.")

    if thunder_soon:
        add("watch", "Thunderstorms may affect the facility",
            f"A thunderstorm signal appears in the next {settings['thunder_watch_hours']} hours in the local or airport forecast.",
            "Monitor official warnings and your approved lightning procedure. This system does not measure lightning strike distance.")

    fc = []
    for p in forecast.get("properties", {}).get("periods", [])[:8]:
        fc.append({
            "name": p.get("name"),
            "temperature": p.get("temperature"),
            "temperatureUnit": p.get("temperatureUnit"),
            "shortForecast": p.get("shortForecast"),
            "windSpeed": p.get("windSpeed"),
            "windDirection": p.get("windDirection"),
        })

    point_props = point.get("properties", {})
    return {
        "id": facility_key(facility),
        "name": facility["name"],
        "icao": icao,
        "zone": zone,
        "latitude": lat,
        "longitude": lon,
        "forecast_zone_name": (point_props.get("forecastZone") or "").split("/")[-1],
        "status": status,
        "status_copy": STATUS_COPY[status],
        "reasons": reasons,
        "metar": metar,
        "taf": taf,
        "alerts": alerts,
        "metrics": {
            "peak_gust_24h_kt": peak_gust,
            "peak_gust_24h_mph": kt_to_mph(peak_gust),
            "precip_7d_in": precip_7d,
            "snow_7d_in": snow_7d,
        },
        "forecast": fc,
        "checked_at": iso(now_utc()),
    }


def interval_for(status, settings):
    return settings[f"{status}_check_minutes"]


def render_html(payload):
    data_json = json.dumps(payload).replace("</", "<\\/")
    html = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Facility Weather Operations</title>
<style>
:root{--bg:#eef2f5;--card:#fff;--ink:#18212a;--muted:#66727d;--line:#d9e0e5;--normal:#24764b;--watch:#a87300;--action:#c45500;--close:#aa271d}
*{box-sizing:border-box}body{margin:0;font-family:Arial,Helvetica,sans-serif;background:var(--bg);color:var(--ink)}.wrap{max-width:1180px;margin:auto;padding:24px}
h1{margin:0 0 6px;font-size:34px}h2{margin-top:0}h3{margin-top:28px}.intro,.muted,.small{color:var(--muted)}.small{font-size:13px}
.test-notice{margin:18px 0;padding:14px 16px;border-radius:12px;background:#fff4d7;border:1px solid #e6c56c;line-height:1.45}
.legend{display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:10px;margin:18px 0 24px}.legend-item{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px}.legend-item strong{display:block;margin-bottom:6px}.legend-item.normal{border-top:5px solid var(--normal)}.legend-item.watch{border-top:5px solid var(--watch)}.legend-item.action{border-top:5px solid var(--action)}.legend-item.close{border-top:5px solid var(--close)}
.facility{background:var(--card);border:1px solid var(--line);border-radius:18px;overflow:hidden;margin:24px 0;box-shadow:0 3px 12px rgba(0,0,0,.06)}.banner{padding:22px;color:white;display:flex;justify-content:space-between;gap:18px;align-items:flex-start;flex-wrap:wrap}.banner.normal{background:var(--normal)}.banner.watch{background:var(--watch)}.banner.action{background:var(--action)}.banner.close{background:var(--close)}.level{font-size:30px;font-weight:900;letter-spacing:.04em;margin-top:5px}.status-summary{max-width:670px;margin-top:8px;line-height:1.4}.body{padding:22px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(175px,1fr));gap:12px;margin:16px 0}.metric{border:1px solid var(--line);background:#fbfcfd;border-radius:11px;padding:14px}.metric strong{display:block;font-size:23px;margin-top:5px}
.reason{border-left:5px solid #999;background:#fafafa;padding:12px 14px;margin:10px 0;border-radius:7px}.reason.watch{border-color:var(--watch)}.reason.action{border-color:var(--action)}.reason.close{border-color:var(--close)}.reason .do{display:block;margin-top:7px;font-weight:700}
.alert{padding:12px 13px;background:#fff9e9;border:1px solid #ead7a4;border-radius:9px;margin:8px 0}.forecast{display:grid;grid-template-columns:repeat(auto-fit,minmax(145px,1fr));gap:9px}.forecast>div{border:1px solid var(--line);border-radius:10px;padding:11px;background:#fbfcfd}details{margin-top:25px;border-top:1px solid var(--line);padding-top:15px}summary{cursor:pointer;font-weight:700}code{display:block;margin-top:8px;font-size:12px;white-space:pre-wrap;word-break:break-word;background:#f5f7f8;padding:10px;border-radius:8px}.footer{font-size:13px;color:var(--muted);line-height:1.55;margin:28px 0}
</style>
</head>
<body>
<div class="wrap">
<h1>Facility Weather Operations</h1>
<div class="intro">Weather translated into operational awareness for facility managers.</div>
<div class="test-notice"><strong>TEST SYSTEM.</strong> The thresholds on this dashboard are examples for development and testing. They are not approved operating, restriction, or closure policy.</div>
<h2>Status Guide</h2>
<div class="legend">
<div class="legend-item normal"><strong>NORMAL</strong>Normal operations. No configured weather threshold currently suggests an operational change.</div>
<div class="legend-item watch"><strong>WATCH</strong>Weather could affect operations. Monitor conditions and prepare staff or equipment.</div>
<div class="legend-item action"><strong>ACTION</strong>A significant condition has been reached or is expected. Take the protective action in the facility plan.</div>
<div class="legend-item close"><strong>CLOSE CRITERIA MET</strong>A configured closure threshold or critical warning has been reached. Follow approved closure or emergency procedures.</div>
</div>
<div id="app"></div>
<div class="footer">This system uses exact facility coordinates for NWS point forecasts and point-based alerts, plus the configured broader NWS zone for additional context. Airport facilities can also use airport observations and airport short-term forecasts. This dashboard does not provide live lightning-strike distance.</div>
</div>
<script>
const DATA=__DATA__;
const e=s=>String(s??'').replace(/[&<>\"]/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[m]));
function card(r){
 const m=r.metrics||{},met=r.metar||{},taf=r.taf||{},sc=r.status_copy||{};
 const reasons=(r.reasons||[]).length ? r.reasons.map(x=>`<div class="reason ${e(x.level)}"><b>${e(x.title)}</b><br>${e(x.detail)}<span class="do">What to do: ${e(x.action||'Review the facility operating plan.')}</span></div>`).join('') : '<p class="muted">No configured operational threshold is currently triggered.</p>';
 const alerts=(r.alerts||[]).length ? r.alerts.map(a=>`<div class="alert"><b>${e(a.event)}</b><br>${e(a.headline||'Official NWS weather alert.')}<br><span class="small">${e(a.source||'NWS')}</span></div>`).join('') : '<p class="muted">No active official NWS alerts affecting the exact facility point or configured broader zone.</p>';
 const forecast=(r.forecast||[]).map(p=>`<div><b>${e(p.name)}</b><br>${e(p.temperature)}°${e(p.temperatureUnit)}<br>${e(p.shortForecast)}<br><span class="muted small">${e(p.windSpeed)} ${e(p.windDirection)}</span></div>`).join('');
 const airportCurrent=r.icao?`<h3>Current Airport Conditions</h3><div class="grid"><div class="metric">Temperature<strong>${met.temperature_f==null?'—':e(met.temperature_f)+'°F'}</strong></div><div class="metric">Current wind<strong>${met.wind_mph==null?'—':e(met.wind_mph)+' mph'}</strong><span class="small">${met.wind_kt==null?'':e(met.wind_kt)+' kt'}</span></div><div class="metric">Current gust<strong>${met.gust_mph==null?'—':e(met.gust_mph)+' mph'}</strong><span class="small">${met.gust_kt==null?'':e(met.gust_kt)+' kt'}</span></div><div class="metric">Visibility<strong>${met.visibility_sm==null?'—':e(met.visibility_sm)+' mi'}</strong></div></div>`:'';
 const technical=r.icao?`<details><summary>Technical airport weather details</summary><p class="small">METAR is the coded current airport observation. TAF is the coded airport short-term forecast.</p><b>Raw current airport observation, ${e(r.icao)} METAR</b><code>${e(met.raw||'Unavailable')}</code><br><b>Raw airport short-term forecast, ${e(r.icao)} TAF</b><code>${e(taf.raw||'Unavailable')}</code></details>`:'';
 const meta=[r.icao?`Airport station ${e(r.icao)}`:'',r.zone?`NWS zone ${e(r.zone)}`:'',`${e(r.latitude)}, ${e(r.longitude)}`].filter(Boolean).join(' · ');
 return `<section class="facility"><div class="banner ${e(r.status)}"><div><div class="small">${e(r.name)} · ${meta}</div><div class="level">${e(sc.label||String(r.status).toUpperCase())}</div><div class="status-summary">${e(sc.summary||'')}</div></div><div>Next weather check: ${e(r.next_check_minutes)} min<br><span class="small">Last checked ${e(new Date(r.checked_at).toLocaleString())}</span></div></div><div class="body"><h3>What should the facility manager do?</h3><p><strong>${e(sc.action||'Review current conditions and facility policy.')}</strong></p>${airportCurrent}<h3>Facility Weather Outlook</h3><div class="grid"><div class="metric">Peak gust, next 24h<strong>${m.peak_gust_24h_mph==null?'—':e(Math.round(m.peak_gust_24h_mph))+' mph'}</strong><span class="small">${m.peak_gust_24h_kt==null?'':e(Math.round(m.peak_gust_24h_kt))+' kt'}</span></div><div class="metric">Snow, next 7 days<strong>${e(m.snow_7d_in??0)} in</strong></div><div class="metric">Precipitation, next 7 days<strong>${e(m.precip_7d_in??0)} in</strong></div></div><h3>Why is the facility at this level?</h3>${reasons}<h3>Official Weather Alerts</h3>${alerts}<h3>7 Day Facility Outlook</h3><div class="forecast">${forecast}</div>${technical}</div></section>`;
}
document.getElementById('app').innerHTML=(DATA.facilities||[]).map(card).join('');
</script>
</body>
</html>"""
    return html.replace("__DATA__", data_json)


def main(force=False):
    config = load_json(CONFIG_FILE, {})
    settings = config.get("settings", {})
    facilities = config.get("facilities", [])
    old = load_json(STATUS_FILE, {"facilities": []})
    old_by_key = {
        x.get("id") or x.get("icao") or x.get("name"): x
        for x in old.get("facilities", [])
    }

    results = []
    any_due = force
    current = now_utc()

    for f in facilities:
        previous = old_by_key.get(facility_key(f))
        if not previous:
            any_due = True
            continue
        interval = interval_for(previous.get("status", "normal"), settings)
        checked = parse_dt(previous.get("checked_at"))
        if not checked or current >= checked + timedelta(minutes=interval):
            any_due = True

    if not any_due:
        print("No facility is due for a weather check yet.")
        return 0

    for f in facilities:
        key = facility_key(f)
        previous = old_by_key.get(key)
        due = force or not previous

        if previous and not due:
            interval = interval_for(previous.get("status", "normal"), settings)
            checked = parse_dt(previous.get("checked_at"))
            due = not checked or current >= checked + timedelta(minutes=interval)

        if due:
            try:
                result = evaluate(f, settings)
            except Exception as exc:
                if previous:
                    result = dict(previous)
                    result["data_error"] = str(exc)
                else:
                    result = {
                        "id": key,
                        "name": f["name"],
                        "icao": f.get("icao"),
                        "zone": f.get("zone"),
                        "latitude": f["latitude"],
                        "longitude": f["longitude"],
                        "status": "watch",
                        "status_copy": STATUS_COPY["watch"],
                        "reasons": [{
                            "level": "watch",
                            "title": "Weather data temporarily unavailable",
                            "detail": str(exc),
                            "action": "Use official local weather sources until the next successful update.",
                        }],
                        "metrics": {},
                        "alerts": [],
                        "metar": None,
                        "taf": None,
                        "forecast": [],
                        "checked_at": iso(current),
                    }
        else:
            result = previous

        result["next_check_minutes"] = interval_for(result.get("status", "normal"), settings)
        results.append(result)

    payload = {
        "generated_at": iso(current),
        "facilities": results,
        "settings": settings,
    }

    DOCS.mkdir(exist_ok=True)
    STATUS_FILE.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    HTML_FILE.write_text(render_html(payload), encoding="utf-8")
    print("Dashboard updated:", ", ".join(f"{r.get('name')}={r.get('status')}" for r in results))
    return 0


if __name__ == "__main__":
    sys.exit(main(force="--force" in sys.argv))

