"""Build replay-ready rainfall JSON from a real NOAA hourly storm window.

The output follows FloodShift's RainfallCondition contract. It contains no invented
imagery or crossing outcomes; county NFIP claims are noted only as validation context.
"""

from __future__ import annotations

import argparse
import json
import math
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
NCEI_SEARCH_URL = "https://www.ncei.noaa.gov/access/services/search/v1/data"
NCEI_DATA_URL = "https://www.ncei.noaa.gov/access/services/data/v1"
CENTRAL_STANDARD = timezone(timedelta(hours=-6))


def fetch_json(url: str):
    request = urllib.request.Request(url, headers={"User-Agent": "FloodShift-AI/0.1"})
    with urllib.request.urlopen(request, timeout=120) as response:
        return json.load(response)


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius = 6371.0088
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    value = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return radius * 2 * math.atan2(math.sqrt(value), math.sqrt(1 - value))


def discover_stations(start: date, end: date) -> list[dict]:
    params = {
        "dataset": "local-climatological-data",
        "startDate": f"{start.isoformat()}T00:00:00",
        "endDate": f"{end.isoformat()}T23:59:59",
        "bbox": "29.8,-99.0,29.1,-98.1",
        "dataTypes": "HourlyPrecipitation",
        "limit": "100",
    }
    payload = fetch_json(f"{NCEI_SEARCH_URL}?{urllib.parse.urlencode(params)}")
    stations = []
    for result in payload.get("results", []):
        if not result.get("stations") or not result.get("boundingPoints"):
            continue
        record = result["stations"][0]
        longitude, latitude = result["boundingPoints"][0]["coordinates"]
        stations.append(
            {
                "station_id": record["id"],
                "station_name": record.get("name", record["id"]),
                "latitude": latitude,
                "longitude": longitude,
            }
        )
    return stations


def hourly_precipitation(station_id: str, start: date, end: date) -> dict[datetime, float]:
    params = {
        "dataset": "local-climatological-data",
        "stations": station_id,
        "startDate": start.isoformat(),
        "endDate": end.isoformat(),
        "dataTypes": "HourlyPrecipitation",
        "format": "json",
        "units": "metric",
        "includeAttributes": "true",
    }
    rows = fetch_json(f"{NCEI_DATA_URL}?{urllib.parse.urlencode(params)}")
    values: dict[datetime, float] = {}
    for row in rows:
        # FM-16 special observations can overlap the routine hourly total. Using
        # FM-15 avoids double-counting those within-hour reports.
        if row.get("REPORT_TYPE", "").strip() != "FM-15":
            continue
        raw = row.get("HourlyPrecipitation")
        if raw is None:
            continue
        amount = 0.0 if raw == "T" else float(raw)
        observed = datetime.fromisoformat(row["DATE"]).replace(tzinfo=CENTRAL_STANDARD)
        bucket = observed.replace(minute=0, second=0, microsecond=0)
        values[bucket] = max(0.0, amount)
    return values


def paid_claim_context(day: date) -> dict:
    path = ROOT / "data" / "real" / "fema_bexar_nfip_claims_2018_2025.csv"
    if not path.exists():
        return {"paid_claim_count": None, "paid_amount_usd": None}
    import csv

    count = 0
    amount = 0.0
    with path.open(encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            if row["dateOfLoss"][:10] != day.isoformat():
                continue
            paid = float(row.get("amountPaidOnBuildingClaim") or 0) + float(
                row.get("amountPaidOnContentsClaim") or 0
            )
            if paid > 0:
                count += 1
                amount += paid
    return {"paid_claim_count": count, "paid_amount_usd": round(amount, 2)}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", type=date.fromisoformat, default=date(2023, 4, 20))
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "data" / "real" / "replay_2023-04-20.json",
    )
    args = parser.parse_args()
    query_start, query_end = args.date - timedelta(days=1), args.date + timedelta(days=1)
    locations = json.loads((ROOT / "data" / "sample_locations.json").read_text(encoding="utf-8"))
    stations = discover_stations(query_start, query_end)
    if not stations:
        raise RuntimeError("No NOAA LCD hourly-precipitation stations were found")
    station_values = {
        station["station_id"]: hourly_precipitation(station["station_id"], query_start, query_end)
        for station in stations
    }
    assignments = {}
    for location in locations:
        station = min(
            stations,
            key=lambda item: haversine_km(
                location["latitude"], location["longitude"], item["latitude"], item["longitude"]
            ),
        )
        assignments[location["location_id"]] = {
            **station,
            "distance_km": round(
                haversine_km(
                    location["latitude"], location["longitude"],
                    station["latitude"], station["longitude"],
                ),
                2,
            ),
        }

    target_start = datetime.combine(args.date, time.min, tzinfo=CENTRAL_STANDARD)
    target_end = target_start + timedelta(days=1, hours=2)
    timestamps = [target_start + timedelta(hours=offset) for offset in range(27)]
    steps = []
    for timestamp in timestamps:
        rainfall = []
        for location in locations:
            assignment = assignments[location["location_id"]]
            values = station_values[assignment["station_id"]]
            current = values.get(timestamp, 0.0)
            previous_3h = sum(values.get(timestamp - timedelta(hours=offset), 0.0) for offset in range(3))
            previous_24h = sum(values.get(timestamp - timedelta(hours=offset), 0.0) for offset in range(24))
            rainfall.append(
                {
                    "location_id": location["location_id"],
                    "timestamp": timestamp.isoformat(),
                    "hourly_mm": round(current, 2),
                    "previous_3h_mm": round(previous_3h, 2),
                    "previous_24h_mm": round(previous_24h, 2),
                    "provenance": "additional_external",
                    "source_name": f"NOAA LCD {assignment['station_id']} (nearest gauge, {assignment['distance_km']} km)",
                }
            )
        steps.append({"timestamp": timestamp.isoformat(), "rainfall": rainfall, "observations": []})

    payload = {
        "scenario_name": f"Historical NOAA rainfall replay: {args.date.isoformat()}",
        "time_basis": "NOAA Local Standard Time (UTC-06:00; no daylight-saving adjustment)",
        "source_url": NCEI_DATA_URL,
        "station_assignments": assignments,
        "county_outcome_context": {
            **paid_claim_context(args.date),
            "warning": "County/day NFIP claims are validation context, not crossing-level labels.",
        },
        "steps": steps,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    peak = max(
        (item for step in steps for item in step["rainfall"]),
        key=lambda item: item["hourly_mm"],
    )
    print(json.dumps({"steps": len(steps), "stations": len(stations), "peak": peak}, indent=2))


if __name__ == "__main__":
    main()
