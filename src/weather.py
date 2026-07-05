"""Weather lane: Kalshi daily high-temperature markets (KXHIGH**) priced from
NWS official data — free, no key, and the same source Kalshi settles against.

Fair value logic: today's settled high = max(observed max so far, remaining
forecast max). Early in the day the forecast dominates (wide sigma); after the
afternoon peak the observed max becomes a hard floor and sigma collapses —
that late-day window is where lagging quotes are most often wrong.
"""
import datetime as dt
import math
import re

import requests

from .kalshi_client import KalshiPublic, normalize_market

# series -> (NWS station, lat, lon, IANA tz, rules keyword sanity check)
CITIES = {
    "KXHIGHNY":   ("KNYC", 40.783, -73.967, "America/New_York",    "Central Park"),
    "KXHIGHCHI":  ("KMDW", 41.786, -87.752, "America/Chicago",     "Midway"),
    "KXHIGHAUS":  ("KAUS", 30.183, -97.680, "America/Chicago",     "Bergstrom"),
    "KXHIGHMIA":  ("KMIA", 25.788, -80.317, "America/New_York",    "Miami"),
    "KXHIGHLAX":  ("KLAX", 33.938, -118.389, "America/Los_Angeles", "Los Angeles"),
    "KXHIGHDEN":  ("KDEN", 39.847, -104.656, "America/Denver",     "Denver"),
    "KXHIGHPHIL": ("KPHL", 39.868, -75.231, "America/New_York",    "Philadelphia"),
}

_S = requests.Session()
_S.headers["User-Agent"] = "kalshi-research-pipeline/0.1 (contact: paper)"


def _phi(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _nws_json(url: str, **params) -> dict:
    r = _S.get(url, params=params or None, timeout=25)
    r.raise_for_status()
    return r.json()


def observed_max_f(station: str, local_midnight_utc: dt.datetime) -> float | None:
    """Max observed temperature (F) at the station since local midnight."""
    try:
        j = _nws_json(f"https://api.weather.gov/stations/{station}/observations",
                      start=local_midnight_utc.isoformat().replace("+00:00", "Z"),
                      limit=200)
    except Exception:
        return None
    temps_c = [f["properties"]["temperature"]["value"]
               for f in j.get("features", [])
               if f["properties"].get("temperature", {}).get("value") is not None]
    if not temps_c:
        return None
    return max(temps_c) * 9 / 5 + 32


def forecast_remaining_max_f(lat: float, lon: float, now_utc: dt.datetime,
                             local_day_end_utc: dt.datetime) -> float | None:
    try:
        meta = _nws_json(f"https://api.weather.gov/points/{lat},{lon}")
        hourly = _nws_json(meta["properties"]["forecastHourly"])
    except Exception:
        return None
    temps = []
    for p in hourly["properties"]["periods"]:
        t0 = dt.datetime.fromisoformat(p["startTime"])
        if now_utc <= t0.astimezone(dt.timezone.utc) <= local_day_end_utc:
            temps.append(float(p["temperature"]))          # already F
    return max(temps) if temps else None


def _sigma_for_local_hour(h: int) -> float:
    """High-of-day uncertainty by local time: forecast-wide in the morning,
    collapsing once the afternoon peak has passed."""
    if h < 12:
        return 2.0
    if h < 15:
        return 1.3
    if h < 17:
        return 0.8
    if h < 19:
        return 0.5
    return 0.35


def _bucket_prob(mu: float, sigma: float, sub: str, strike: float) -> float | None:
    """P(settled integer high falls in this market's bucket).
    B{x} buckets cover the two integer degrees around x (x±0.5 -> [x-1, x+1) real).
    T{x} thresholds read direction from the subtitle text (e.g. '<98' / '98 or above')."""
    if math.isnan(strike):
        return None
    lo_tail = "<" in sub or "below" in sub.lower()
    if abs(strike - round(strike)) > 0.01:                 # B-style bucket, e.g. 98.5
        return _phi((strike + 1.0 - mu) / sigma) - _phi((strike - 1.0 - mu) / sigma)
    if lo_tail:                                            # settled high < strike
        return _phi((strike - 0.5 - mu) / sigma)
    return 1.0 - _phi((strike - 0.5 - mu) / sigma)         # strike or above


def candidates(cfg: dict) -> list[dict]:
    wc = cfg["weather"]
    api = KalshiPublic()
    now = dt.datetime.now(dt.timezone.utc)
    out = []
    for series, (stn, lat, lon, tz, keyword) in CITIES.items():
        if series not in wc["series"]:
            continue
        # local-time gate: only trade when the model has information (post-morning)
        offset = {"America/New_York": -4, "America/Chicago": -5,
                  "America/Denver": -6, "America/Los_Angeles": -7}[tz]
        local_now = now + dt.timedelta(hours=offset)
        if not (wc["active_local_hours"][0] <= local_now.hour <= wc["active_local_hours"][1]):
            continue
        page = api._get("/markets", series_ticker=series, status="open", limit=100)
        markets = [normalize_market(m) for m in page.get("markets", [])]
        markets = [m for m in markets if m["status"] == "active" and m["close_time"]]
        todays = [m for m in markets
                  if 0 < (dt.datetime.fromisoformat(m["close_time"].replace("Z", "+00:00"))
                          - now).total_seconds() <= 20 * 3600]
        if not todays:
            continue
        if keyword.lower() not in (todays[0].get("rules_primary") or "").lower():
            print(f"WARN {series}: station keyword '{keyword}' not in rules - skipping city")
            continue
        midnight_local = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
        midnight_utc = midnight_local - dt.timedelta(hours=offset)
        day_end_utc = midnight_utc + dt.timedelta(hours=24)
        obs = observed_max_f(stn, midnight_utc)
        fc = forecast_remaining_max_f(lat, lon, now, day_end_utc)
        if obs is None and fc is None:
            print(f"WARN {series}: no NWS data")
            continue
        mu = max(x for x in (obs, fc) if x is not None)
        sigma = _sigma_for_local_hour(local_now.hour)
        for m in todays:
            tail = m["ticker"].rsplit("-", 1)[-1]
            mt = re.match(r"^[BT](\d+(?:\.\d+)?)$", tail)
            if not mt:
                continue
            if not (m["yes_bid"] > 0 and 0.02 <= m["yes_ask"] <= 0.98):
                continue
            q = _bucket_prob(mu, sigma, m.get("yes_sub_title") or "", float(mt.group(1)))
            if q is None:
                continue
            out.append({"ticker": m["ticker"], "series": series,
                        "q_model": round(min(max(q, 0.001), 0.999), 4),
                        "yes_bid": m["yes_bid"], "yes_ask": m["yes_ask"],
                        "no_ask": m["no_ask"],
                        "mid": round((m["yes_bid"] + m["yes_ask"]) / 2, 4),
                        "mu": round(mu, 1), "sigma": sigma,
                        "obs_max": None if obs is None else round(obs, 1),
                        "fc_max": None if fc is None else round(fc, 1),
                        "local_hour": local_now.hour})
    return out
