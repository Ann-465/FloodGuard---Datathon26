"""Fetch and align real San Antonio/Bexar flood evidence from public sources.

Sources:
- City of San Antonio SATRIP road flood sensors
- City of San Antonio storm-inlet, underground-drainage, and channel layers
- NOAA GHCN-Daily precipitation stations in the San Antonio area
- OpenFEMA NFIP claims in Bexar County as historical flood-loss labels

Only compact, derived CSVs are stored. Run again to refresh source revisions.
"""

from __future__ import annotations

import csv
import io
import json
import math
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "data" / "real"
START_DATE = "2018-01-01"
END_DATE = "2025-12-31"
BBOX = "29.8,-99.0,29.1,-98.1"  # north, west, south, east
SATRIP_URL = "https://gis.sanantonio.gov/Satrip/SATripData/floodsensors.csv"
NCEI_SEARCH_URL = "https://www.ncei.noaa.gov/access/services/search/v1/data"
NCEI_DATA_URL = "https://www.ncei.noaa.gov/access/services/data/v1"
OPENFEMA_CLAIMS_URL = "https://www.fema.gov/api/open/v3/NfipClaims"
ARCGIS_LAYERS = {
    "inlets": "https://services.arcgis.com/g1fRTDLeMgspWrYp/arcgis/rest/services/StormInlets/FeatureServer/0",
    "underground_segments": "https://services.arcgis.com/g1fRTDLeMgspWrYp/arcgis/rest/services/StormwaterUnderground/FeatureServer/0",
    "channel_segments": "https://services.arcgis.com/g1fRTDLeMgspWrYp/arcgis/rest/services/StormChannels/FeatureServer/0",
}


def fetch_bytes(url: str, timeout: int = 120) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "FloodShift-AI/0.1"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


def fetch_json(url: str, timeout: int = 120) -> dict:
    return json.loads(fetch_bytes(url, timeout=timeout))


def write_csv(path: Path, rows: list[dict], fields: list[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius = 6371.0088
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    value = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return radius * 2 * math.atan2(math.sqrt(value), math.sqrt(1 - value))


def fetch_satrip() -> tuple[list[dict], dict]:
    text = fetch_bytes(SATRIP_URL).decode("utf-8-sig")
    rows = list(csv.DictReader(io.StringIO(text)))
    fields = [
        "ID", "SensorName", "Agency", "AgencyIdentifier", "Latitude", "Longitude",
        "Status", "LastUpdated", "LastStatusChanged",
    ]
    write_csv(OUTPUT / "satrip_flood_sensors.csv", rows, fields)
    counts: dict[str, int] = {}
    for row in rows:
        counts[row.get("Status", "unknown")] = counts.get(row.get("Status", "unknown"), 0) + 1
    return rows, {"row_count": len(rows), "status_counts": counts, "source": SATRIP_URL}


def arcgis_count_within(latitude: float, longitude: float, layer_url: str, radius_m: int) -> int:
    params = {
        "f": "json",
        "where": "1=1",
        "geometry": f"{longitude},{latitude}",
        "geometryType": "esriGeometryPoint",
        "inSR": "4326",
        "spatialRel": "esriSpatialRelIntersects",
        "distance": str(radius_m),
        "units": "esriSRUnit_Meter",
        "returnCountOnly": "true",
    }
    payload = fetch_json(f"{layer_url}/query?{urllib.parse.urlencode(params)}")
    if "error" in payload:
        raise RuntimeError(f"ArcGIS query failed for {layer_url}: {payload['error']}")
    return int(payload["count"])


def infrastructure_proxy(inlets: int, underground: int, channels: int) -> float:
    """Return a transparent exposure/capacity proxy, not a hydraulic probability.

    Sparse mapped drainage assets increase the proxy while mapped channel density
    represents exposure. Fixed caps prevent extreme feature counts from dominating.
    """
    inlet_deficit = 1.0 - min(inlets / 150.0, 1.0)
    underground_deficit = 1.0 - min(underground / 150.0, 1.0)
    channel_exposure = min(channels / 75.0, 1.0)
    return round(
        0.35 * inlet_deficit + 0.25 * underground_deficit + 0.40 * channel_exposure,
        4,
    )


def fetch_infrastructure_features(crossings: list[dict], radius_m: int = 500) -> tuple[list[dict], dict]:
    rows: list[dict] = []
    for crossing in crossings:
        latitude = float(crossing["latitude"])
        longitude = float(crossing["longitude"])
        counts = {
            name: arcgis_count_within(latitude, longitude, url, radius_m)
            for name, url in ARCGIS_LAYERS.items()
        }
        rows.append(
            {
                "location_id": crossing["location_id"],
                "name": crossing["name"],
                "latitude": latitude,
                "longitude": longitude,
                "buffer_radius_m": radius_m,
                "inlet_count": counts["inlets"],
                "underground_segment_count": counts["underground_segments"],
                "channel_segment_count": counts["channel_segments"],
                "drainage_vulnerability_proxy": infrastructure_proxy(
                    counts["inlets"], counts["underground_segments"], counts["channel_segments"]
                ),
            }
        )
    fields = [
        "location_id", "name", "latitude", "longitude", "buffer_radius_m",
        "inlet_count", "underground_segment_count", "channel_segment_count",
        "drainage_vulnerability_proxy",
    ]
    write_csv(OUTPUT / "san_antonio_crossing_features.csv", rows, fields)
    return rows, {
        "row_count": len(rows),
        "buffer_radius_m": radius_m,
        "layers": ARCGIS_LAYERS,
        "method": (
            "0.35*inlet_deficit + 0.25*underground_segment_deficit + "
            "0.40*channel_segment_exposure; fixed caps 150/150/75"
        ),
    }


def prcp_coverage(result: dict) -> float:
    for station in result.get("stations", []):
        for data_type in station.get("dataTypes", []):
            if isinstance(data_type, dict) and data_type.get("id") == "PRCP":
                return float(data_type.get("coverage") or 0)
    return 0.0


def discover_precipitation_stations(crossings: list[dict]) -> list[dict]:
    params = {
        "dataset": "daily-summaries",
        "startDate": f"{START_DATE}T00:00:00",
        "endDate": f"{END_DATE}T23:59:59",
        "bbox": BBOX,
        "dataTypes": "PRCP",
        "limit": "500",
        "offset": "0",
    }
    payload = json.loads(fetch_bytes(f"{NCEI_SEARCH_URL}?{urllib.parse.urlencode(params)}"))
    candidates: list[dict] = []
    for result in payload.get("results", []):
        station_records = result.get("stations") or []
        coordinates = (result.get("location") or {}).get("coordinates") or []
        if not station_records or len(coordinates) < 2:
            continue
        station = station_records[0]
        coverage = prcp_coverage(result)
        if coverage < 70:
            continue
        candidates.append(
            {
                "station_id": station.get("id"),
                "station_name": station.get("name"),
                "longitude": float(coordinates[0]),
                "latitude": float(coordinates[1]),
                "coverage": coverage,
            }
        )
    # Select the nearest high-coverage station for each demonstration crossing,
    # then add the airport station as a stable long-record reference.
    selected: dict[str, dict] = {}
    for crossing in crossings:
        if not candidates:
            break
        nearest = min(
            candidates,
            key=lambda station: haversine_km(
                float(crossing["latitude"]), float(crossing["longitude"]),
                station["latitude"], station["longitude"],
            ),
        )
        selected[nearest["station_id"]] = nearest
    selected.setdefault(
        "USW00012921",
        {
            "station_id": "USW00012921",
            "station_name": "SAN ANTONIO INTERNATIONAL AIRPORT, TX US",
            "latitude": 29.5443,
            "longitude": -98.4840,
            "coverage": 99.0,
        },
    )
    return sorted(selected.values(), key=lambda item: item["station_id"])


def fetch_precipitation(crossings: list[dict]) -> tuple[list[dict], dict]:
    stations = discover_precipitation_stations(crossings)
    params = {
        "dataset": "daily-summaries",
        "stations": ",".join(item["station_id"] for item in stations),
        "startDate": START_DATE,
        "endDate": END_DATE,
        "dataTypes": "PRCP",
        "format": "csv",
        "units": "metric",
        "includeAttributes": "true",
        "includeStationName": "true",
    }
    text = fetch_bytes(f"{NCEI_DATA_URL}?{urllib.parse.urlencode(params)}").decode("utf-8-sig")
    rows = list(csv.DictReader(io.StringIO(text)))
    fields = ["STATION", "NAME", "DATE", "PRCP", "PRCP_ATTRIBUTES"]
    write_csv(OUTPUT / "noaa_bexar_daily_precip_2018_2025.csv", rows, fields)
    write_csv(
        OUTPUT / "noaa_selected_stations.csv",
        stations,
        ["station_id", "station_name", "latitude", "longitude", "coverage"],
    )
    return rows, {
        "row_count": len(rows),
        "station_count": len(stations),
        "stations": stations,
        "source": NCEI_DATA_URL,
    }


def fetch_nfip_claims() -> tuple[list[dict], dict]:
    """Fetch Bexar County claim dates without downloading the national archive."""
    selected_fields = [
        "id", "dateOfLoss", "yearOfLoss", "state", "countyCode", "reportedZipCode",
        "latitude", "longitude", "floodEvent", "amountPaidOnBuildingClaim",
        "amountPaidOnContentsClaim", "buildingDamageAmount", "contentsDamageAmount",
        "waterDepth", "exteriorWaterDepth", "interiorWaterDepth",
    ]
    date_filter = (
        "countyCode eq '48029' and "
        f"dateOfLoss ge '{START_DATE}T00:00:00.000Z' and "
        f"dateOfLoss lt '2026-01-01T00:00:00.000Z'"
    )
    rows: list[dict] = []
    page_size = 1000
    skip = 0
    while True:
        params = {
            "$filter": date_filter,
            "$select": ",".join(selected_fields),
            "$orderby": "id",
            "$top": str(page_size),
            "$skip": str(skip),
        }
        payload = fetch_json(f"{OPENFEMA_CLAIMS_URL}?{urllib.parse.urlencode(params)}")
        page = payload.get("NfipClaims", [])
        rows.extend(page)
        if len(page) < page_size:
            break
        skip += page_size
    write_csv(OUTPUT / "fema_bexar_nfip_claims_2018_2025.csv", rows, selected_fields)
    positive_payments = sum(
        1 for row in rows
        if float(row.get("amountPaidOnBuildingClaim") or 0)
        + float(row.get("amountPaidOnContentsClaim") or 0) > 0
    )
    return rows, {
        "row_count": len(rows),
        "claim_dates": len({row.get("dateOfLoss", "")[:10] for row in rows}),
        "claims_with_positive_payment": positive_payments,
        "county_fips": "48029",
        "source": OPENFEMA_CLAIMS_URL,
    }


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    crossings = json.loads((ROOT / "data" / "sample_locations.json").read_text(encoding="utf-8"))
    satrip_rows, satrip_meta = fetch_satrip()
    infrastructure_rows, infrastructure_meta = fetch_infrastructure_features(crossings)
    precip_rows, precip_meta = fetch_precipitation(crossings)
    claim_rows, claim_meta = fetch_nfip_claims()
    metadata = {
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
        "geographic_scope": "San Antonio/Bexar County, Texas",
        "date_range": [START_DATE, END_DATE],
        "satrip": satrip_meta,
        "infrastructure": infrastructure_meta,
        "precipitation": precip_meta,
        "nfip_claims": claim_meta,
        "limitations": [
            "SATRIP is a current snapshot and some device timestamps are stale.",
            "NFIP claims cover insured properties only and are county/day labels, not crossing outcomes.",
            "Mapped asset counts and the derived vulnerability proxy are not hydraulic capacity.",
            "Station precipitation can miss highly localized rainfall between gauges.",
        ],
    }
    (OUTPUT / "metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "satrip_sensors": len(satrip_rows),
                "crossing_feature_rows": len(infrastructure_rows),
                "precipitation_rows": len(precip_rows),
                "nfip_claim_rows": len(claim_rows),
                "output": str(OUTPUT),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()

