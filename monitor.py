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
    "User-Agent": "FacilityWeatherGitHubPages/1.0",
    "Accept": "application/geo+json",
}
AWC_HEADERS = {"User-Agent": "FacilityWeatherGitHubPages/1.0"}
LEVEL = {"normal": 0, "watch": 1, "action": 2, "close": 3}

CLOSE_EVENTS = {
    "Tornado Warning", "Extreme Wind Warning", "Flash Flood Warning",
    "Hurricane Warning", "Storm Surge Warning", "Tsunami Warning"
}
ACTION_EVENTS = {
    "Severe Thunderstorm Warning", "Blizzard Warning", "Ice Storm Warning",
    "Winter Storm Warning", "High Wind Warning", "Flood Warning",
    "Extreme Heat Warning", "Excessive Heat Warning"
}
WATCH_EVENTS = {
    "Tornado Watch", "Severe Thunderstorm Watch", "Winter Storm Watch",
    "High Wind Watch", "Flood Watch", "Flash Flood Watch",
    "Winter Weather Advisory", "Wind Advisory", "Heat Advisory",
    "Dense Fog Advisory"
}


def now_utc():
    return datetime.now(timezone.utc)


def iso(dt):
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def parse_dt(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
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


def mps_to_kt(v):
    return None if v is None else round(float(v) * 1.943844, 1)


def kmh_to_kt(v):
    return None if v is None else round(float(v) * 0.539957, 1)


def mm_to_in(v):
    return None if v is None else round(float(v) / 25.4, 2)


def max_level(current, proposed):
    return proposed if LEVEL[proposed] > LEVEL[current] else current


def parse_metar_wind(raw):
    if not raw:
        return None, None
    # Typical group: 28015G28KT or VRB05KT
    m = re.search(r"\b(?:\d{3}|VRB)(\d{2,3})(?:G(\d{2,3}))?KT\b", raw)
    if not m:
        return None, None
    return float(m.group(1)), float(m.group(2)) if m.group(2) else None


def parse_metar_visibility(raw):
    if not raw:
        return None
    # Handles common US forms such as 10SM, 3SM, 1/2SM, 1 1/2SM
    m = re.search(r"\b(?:(\d+)\s+)?(\d+)/(\d+)SM\b", raw)
    if m:
        whole = float(m.group(1) or 0)
        return round(whole + float(m.group(2)) / float(m.group(3)), 2)
    m = re.search(r"\b(\d+(?:\.\d+)?)SM\b", raw)
    return float(m.group(1)) if m else None


def fetch_metar(icao):
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
    return {
        "raw": raw,
        "observed": row.get("reportTime") or row.get("obsTime") or row.get("receiptTime"),
        "wind_kt": float(wind) if wind is not None else None,
        "gust_kt": float(gust) if gust is not None else None,
        "temperature_f": c_to_f(temp_c),
        "visibility_sm": parse_metar_visibility(raw),
        "flight_category": row.get("fltCat") or row.get("flightCategory"),
    }


def fetch_taf(icao):
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


def fetch_zone_alerts(zone):
    data = get_json(f"{NWS}/alerts/active/zone/{zone}")
    alerts = []
    for f in data.get("features", []) if isinstance(data, dict) else []:
        p = f.get("properties", {})
        alerts.append({
            "event": p.get("event") or "Weather Alert",
            "headline": p.get("headline") or "",
            "severity": p.get("severity") or "Unknown",
            "urgency": p.get("urgency") or "Unknown",
            "expires": p.get("expires"),
        })
    return alerts


def evaluate(facility, settings):
    lat, lon, icao, zone = facility["latitude"], facility["longitude"], facility["icao"], facility["zone"]
    point, hourly, forecast, grid = nws_point_data(lat, lon)
    metar = fetch_metar(icao)
    taf = fetch_taf(icao)
    alerts = fetch_zone_alerts(zone)

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
        if dt and dt <= thunder_cutoff and "thunder" in (p.get("shortForecast") or "").lower():
            thunder_soon = True
            break
    if taf and taf.get("thunder"):
        thunder_soon = True

    status = "normal"
    reasons = []

    def add(level, title, detail):
        nonlocal status
        status = max_level(status, level)
        reasons.append({"level": level, "title": title, "detail": detail})

    for a in alerts:
        event = a["event"]
        if event in CLOSE_EVENTS:
            add("close", event, a["headline"])
        elif event in ACTION_EVENTS:
            add("action", event, a["headline"])
        elif event in WATCH_EVENTS:
            add("watch", event, a["headline"])

    if peak_gust is not None:
        if peak_gust >= settings["wind_close_kt"]:
            add("close", "Wind threshold", f"Observed or forecast gust {peak_gust:.0f} kt")
        elif peak_gust >= settings["wind_action_kt"]:
            add("action", "Wind threshold", f"Observed or forecast gust {peak_gust:.0f} kt")
        elif peak_gust >= settings["wind_watch_kt"]:
            add("watch", "Wind threshold", f"Observed or forecast gust {peak_gust:.0f} kt")

    if snow_7d >= settings["snow_close_in"]:
        add("close", "Snow forecast", f"About {snow_7d:.1f} in in the 7 day NWS grid forecast")
    elif snow_7d >= settings["snow_action_in"]:
        add("action", "Snow forecast", f"About {snow_7d:.1f} in in the 7 day NWS grid forecast")
    elif snow_7d >= settings["snow_watch_in"]:
        add("watch", "Snow forecast", f"About {snow_7d:.1f} in in the 7 day NWS grid forecast")

    if precip_7d >= settings["precip_action_in"]:
        add("action", "Heavy precipitation outlook", f"About {precip_7d:.1f} in liquid precipitation in 7 days")
    elif precip_7d >= settings["precip_watch_in"]:
        add("watch", "Heavy precipitation outlook", f"About {precip_7d:.1f} in liquid precipitation in 7 days")

    if thunder_soon:
        add("watch", "Thunderstorm potential", f"Thunderstorm signal in the next {settings['thunder_watch_hours']} hours or airport TAF")

    fc = []
    for p in forecast.get("properties", {}).get("periods", [])[:8]:
        fc.append({
            "name": p.get("name"), "temperature": p.get("temperature"),
            "temperatureUnit": p.get("temperatureUnit"), "shortForecast": p.get("shortForecast"),
            "windSpeed": p.get("windSpeed"), "windDirection": p.get("windDirection")
        })

    point_props = point.get("properties", {})
    return {
        "name": facility["name"], "icao": icao, "zone": zone,
        "latitude": lat, "longitude": lon,
        "forecast_zone_name": (point_props.get("forecastZone") or "").split("/")[-1],
        "status": status, "reasons": reasons,
        "metar": metar, "taf": taf, "alerts": alerts,
        "metrics": {"peak_gust_24h_kt": peak_gust, "precip_7d_in": precip_7d, "snow_7d_in": snow_7d},
        "forecast": fc,
        "checked_at": iso(now_utc()),
    }


def interval_for(status, settings):
    return settings[f"{status}_check_minutes"]


def render_html(payload):
    data_json = json.dumps(payload).replace("</", "<\\/")
    return f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Facility Weather Operations</title>
<style>
:root{{--bg:#f3f5f7;--card:#fff;--ink:#17212b;--muted:#66717c;--line:#dce2e7;--normal:#237a4b;--watch:#b17a00;--action:#c65a00;--close:#b42318}}
*{{box-sizing:border-box}}body{{margin:0;font-family:Arial,Helvetica,sans-serif;background:var(--bg);color:var(--ink)}}.wrap{{max-width:1200px;margin:auto;padding:24px}}
h1{{margin:0 0 5px}}.intro,.muted{{color:var(--muted)}}.facility{{background:var(--card);border:1px solid var(--line);border-radius:16px;overflow:hidden;margin:22px 0;box-shadow:0 2px 10px rgba(0,0,0,.05)}}
.banner{{padding:20px 22px;color:white;display:flex;justify-content:space-between;gap:15px;align-items:center;flex-wrap:wrap}}.banner.normal{{background:var(--normal)}}.banner.watch{{background:var(--watch)}}.banner.action{{background:var(--action)}}.banner.close{{background:var(--close)}}
.banner .level{{font-size:30px;font-weight:900;letter-spacing:.06em}}.body{{padding:20px 22px}}.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px;margin:16px 0}}.metric{{border:1px solid var(--line);border-radius:10px;padding:13px}}.metric strong{{display:block;font-size:23px;margin-top:4px}}.reason{{border-left:5px solid #999;background:#fafafa;padding:10px 12px;margin:9px 0}}.reason.watch{{border-color:var(--watch)}}.reason.action{{border-color:var(--action)}}.reason.close{{border-color:var(--close)}}
.alert{{padding:11px 12px;background:#fff8e6;border:1px solid #ead29a;border-radius:9px;margin:8px 0}}.forecast{{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:8px}}.forecast>div{{border:1px solid var(--line);border-radius:9px;padding:10px}}code{{font-size:12px;white-space:pre-wrap;word-break:break-word}}.small{{font-size:13px}}.footer{{font-size:13px;color:var(--muted);line-height:1.5;margin:26px 0}}
</style></head><body><div class="wrap"><h1>Facility Weather Operations</h1><div class="intro">Airport-specific operations dashboard using NOAA/NWS and Aviation Weather Center data.</div><div id="app"></div><div class="footer">NORMAL checks every 30 minutes, WATCH every 15 minutes, ACTION and CLOSE every 5 minutes. The GitHub workflow itself wakes every 5 minutes and Python decides whether each facility is due. This dashboard does not provide real-time lightning strike distance. Follow official warnings and your organization's written operating policy.</div></div>
<script>const DATA={data_json};const e=s=>String(s??'').replace(/[&<>\"]/g,m=>({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}}[m]));
function card(r){{const m=r.metrics,met=r.metar||{{}},taf=r.taf||{{}};const reasons=r.reasons.length?r.reasons.map(x=>`<div class="reason ${{e(x.level)}}"><b>${{e(x.title)}}</b><br>${{e(x.detail)}}</div>`).join(''):'<p class="muted">No configured operational threshold is currently triggered.</p>';const alerts=r.alerts.length?r.alerts.map(a=>`<div class="alert"><b>${{e(a.event)}}</b><br>${{e(a.headline)}}</div>`).join(''):'<p class="muted">No active NWS zone alerts.</p>';const f=r.forecast.map(p=>`<div><b>${{e(p.name)}}</b><br>${{e(p.temperature)}}°${{e(p.temperatureUnit)}}<br>${{e(p.shortForecast)}}<br><span class="muted small">${{e(p.windSpeed)}} ${{e(p.windDirection)}}</span></div>`).join('');return `<section class="facility"><div class="banner ${{e(r.status)}}"><div><div class="small">${{e(r.name)}} · ${{e(r.icao)}} · ${{e(r.zone)}}</div><div class="level">${{e(r.status.toUpperCase())}}</div></div><div>Next check: ${{e(r.next_check_minutes)}} min<br><span class="small">Last checked ${{e(new Date(r.checked_at).toLocaleString())}}</span></div></div><div class="body"><div class="grid"><div class="metric">Current wind<strong>${{met.wind_kt==null?'—':e(met.wind_kt)+' kt'}}</strong></div><div class="metric">Current gust<strong>${{met.gust_kt==null?'—':e(met.gust_kt)+' kt'}}</strong></div><div class="metric">Peak gust, 24h<strong>${{m.peak_gust_24h_kt==null?'—':e(Math.round(m.peak_gust_24h_kt))+' kt'}}</strong></div><div class="metric">Visibility<strong>${{met.visibility_sm==null?'—':e(met.visibility_sm)+' mi'}}</strong></div><div class="metric">Snow, 7d<strong>${{e(m.snow_7d_in)}} in</strong></div><div class="metric">Precip, 7d<strong>${{e(m.precip_7d_in)}} in</strong></div></div><h3>Why this level?</h3>${{reasons}}<h3>Official NWS alerts, zone ${{e(r.zone)}}</h3>${{alerts}}<h3>Airport observation, ${{e(r.icao)}} METAR</h3><code>${{e(met.raw||'Unavailable')}}</code><h3>Airport forecast, ${{e(r.icao)}} TAF</h3><code>${{e(taf.raw||'Unavailable')}}</code><h3>NWS point forecast</h3><div class="forecast">${{f}}</div></div></section>`}}
document.getElementById('app').innerHTML=DATA.facilities.map(card).join('');</script></body></html>'''


def main(force=False):
    config = load_json(CONFIG_FILE, {})
    settings = config.get("settings", {})
    facilities = config.get("facilities", [])
    old = load_json(STATUS_FILE, {"facilities": []})
    old_by_icao = {x.get("icao"): x for x in old.get("facilities", [])}
    results = []
    any_due = force
    current = now_utc()

    for f in facilities:
        previous = old_by_icao.get(f["icao"])
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
        previous = old_by_icao.get(f["icao"])
        due = force or not previous
        if previous and not due:
            interval = interval_for(previous.get("status", "normal"), settings)
            checked = parse_dt(previous.get("checked_at"))
            due = not checked or current >= checked + timedelta(minutes=interval)
        if due:
            try:
                result = evaluate(f, settings)
            except Exception as exc:
                # Preserve last good result but make the data problem visible.
                if previous:
                    result = dict(previous)
                    result["data_error"] = str(exc)
                else:
                    result = {**f, "status": "watch", "reasons": [{"level":"watch","title":"Data unavailable","detail":str(exc)}], "metrics":{}, "alerts":[], "metar":None, "taf":None, "forecast":[], "checked_at":iso(current)}
        else:
            result = previous
        result["next_check_minutes"] = interval_for(result.get("status", "normal"), settings)
        results.append(result)

    payload = {"generated_at": iso(current), "facilities": results, "settings": settings}
    DOCS.mkdir(exist_ok=True)
    STATUS_FILE.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    HTML_FILE.write_text(render_html(payload), encoding="utf-8")
    print("Dashboard updated:", ", ".join(f"{r.get('icao')}={r.get('status')}" for r in results))
    return 0


if __name__ == "__main__":
    sys.exit(main(force="--force" in sys.ar
