"""Infrastructure ingestion for organizer-linked San Antonio data sources."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Iterable

import requests

from .schemas import Location, Provenance


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_LOCATION_FILE = PROJECT_ROOT / "data" / "sample_locations.json"

OFFICIAL_LINKED_SOURCES = {
    "low_water_crossings": "https://opendata-cosagis.opendata.arcgis.com/datasets/4089adb69af14608acfb02703b1dd439_0/about",
    "storm_inlets": "https://opendata-cosagis.opendata.arcgis.com/datasets/CoSAGIS::storminlets/about",
    "stormwater_underground": "https://opendata-cosagis.opendata.arcgis.com/datasets/CoSAGIS::stormwaterunderground/about",
    "storm_channels": "https://opendata-cosagis.opendata.arcgis.com/datasets/CoSAGIS::stormchannels/about",
    "manholes": "https://opendata-cosagis.opendata.arcgis.com/datasets/CoSAGIS::manholes/about",
    "outfalls": "https://opendata-cosagis.opendata.arcgis.com/datasets/CoSAGIS::outfalls/about",
    "imp_drainage": "https://data.sanantonio.gov/dataset/imp-drainage",
}


def load_locations(path: str | Path | None = None) -> list[Location]:
    """Load validated location records from a JSON list or GeoJSON FeatureCollection."""
    selected = Path(path or os.getenv("FLOODSHIFT_INFRASTRUCTURE_FILE", DEFAULT_LOCATION_FILE))
    payload = json.loads(selected.read_text(encoding="utf-8"))
    if isinstance(payload, list):
        return [Location.model_validate(item) for item in payload]
    if payload.get("type") == "FeatureCollection":
        return locations_from_geojson_features(payload.get("features", []))
    raise ValueError(f"Unsupported infrastructure format in {selected}")


def locations_from_geojson_features(
    features: Iterable[dict[str, Any]],
    *,
    source_name: str = "Organizer-linked San Antonio GeoJSON",
    source_url: str | None = None,
    default_is_low_water_crossing: bool = False,
) -> list[Location]:
    """Normalize point features while retaining their original attributes.

    Dataset-specific field names remain in ``attributes``. No vulnerability value is
    invented silently: absent values use a documented neutral 0.5 default.
    """
    locations: list[Location] = []
    for index, feature in enumerate(features):
        geometry = feature.get("geometry") or {}
        coordinates = geometry.get("coordinates") or []
        if geometry.get("type") != "Point" or len(coordinates) < 2:
            continue
        props = feature.get("properties") or {}
        identifier = str(
            props.get("location_id")
            or props.get("CartID")
            or props.get("OBJECTID")
            or props.get("objectid")
            or props.get("ID")
            or f"feature-{index + 1}"
        )
        name = str(
            props.get("name")
            or props.get("Name")
            or props.get("NAME")
            or props.get("StreetName")
            or props.get("STREET")
            or f"Infrastructure location {identifier}"
        )
        locations.append(
            Location(
                location_id=identifier,
                name=name,
                longitude=float(coordinates[0]),
                latitude=float(coordinates[1]),
                is_low_water_crossing=bool(
                    props.get("is_low_water_crossing", default_is_low_water_crossing)
                ),
                drainage_vulnerability=float(props.get("drainage_vulnerability", 0.5)),
                criticality=float(props.get("criticality", 0.5)),
                nearby_inlet_count=props.get("nearby_inlet_count"),
                provenance=Provenance.OFFICIAL_LINKED,
                source_name=str(props.get("source_name", source_name)),
                source_url=props.get("source_url", source_url),
                attributes=props,
            )
        )
    return locations


def fetch_arcgis_geojson(
    feature_service_url: str,
    *,
    where: str = "1=1",
    limit: int = 1000,
    timeout: float = 30,
) -> dict[str, Any]:
    """Fetch GeoJSON from an ArcGIS FeatureServer layer query endpoint."""
    endpoint = feature_service_url.rstrip("/") + "/query"
    response = requests.get(
        endpoint,
        params={
            "where": where,
            "outFields": "*",
            "f": "geojson",
            "outSR": "4326",
            "resultRecordCount": limit,
        },
        timeout=timeout,
    )
    response.raise_for_status()
    payload = response.json()
    if payload.get("type") != "FeatureCollection":
        raise ValueError("ArcGIS response was not a GeoJSON FeatureCollection")
    return payload


def find_texas_student_data(search_root: str | Path | None = None) -> Path | None:
    """Find the separately supplied organizer dataset without downloading substitutes."""
    root = Path(search_root) if search_root else PROJECT_ROOT.parent
    candidates = [
        root / "Texas_Flood_Student_Data",
        PROJECT_ROOT / "Texas_Flood_Student_Data",
        PROJECT_ROOT.parent / "Texas_Flood_Student_Data",
    ]
    for candidate in candidates:
        if (candidate / "image_metadata.csv").is_file():
            return candidate.resolve()
    return None


def validate_texas_student_data(path: str | Path) -> dict[str, Any]:
    """Report organizer-dataset readiness without treating Houston as San Antonio."""
    folder = Path(path)
    required = ["image_metadata.csv", "observations.sqlite"]
    missing = [name for name in required if not (folder / name).is_file()]
    image_count = sum(
        1 for suffix in ("*.jpg", "*.jpeg", "*.png", "*.webp") for _ in folder.rglob(suffix)
    )
    return {
        "path": str(folder.resolve()),
        "ready": not missing and image_count > 0,
        "missing": missing,
        "image_count": image_count,
        "geographic_constraint": (
            "Use these images to evaluate visual analysis only unless image metadata "
            "validly matches a risk-assessment location."
        ),
    }

