from datetime import datetime, timezone

import pytest

from floodshift.schemas import Location, Provenance, RainfallCondition, VisualEvidence


@pytest.fixture
def location() -> Location:
    return Location(
        location_id="loc-1",
        name="Test crossing",
        latitude=29.4,
        longitude=-98.5,
        is_low_water_crossing=True,
        drainage_vulnerability=0.8,
        criticality=0.7,
        nearby_inlet_count=1,
        provenance=Provenance.OFFICIAL_LINKED,
        source_name="Test fixture",
    )


def rainfall(location_id: str, hourly: float, three_hour: float, daily: float) -> RainfallCondition:
    return RainfallCondition(
        location_id=location_id,
        timestamp=datetime(2026, 11, 13, 18, tzinfo=timezone.utc),
        hourly_mm=hourly,
        previous_3h_mm=three_hour,
        previous_24h_mm=daily,
        provenance=Provenance.SYNTHETIC,
    )


def visual(location_id: str) -> VisualEvidence:
    return VisualEvidence(
        observation_id="obs-1",
        location_id=location_id,
        observed_at=datetime(2026, 11, 13, 18, tzinfo=timezone.utc),
        visible_flooding="yes",
        road_obstructed="yes",
        debris_visible="yes",
        visual_severity=3,
        evidence=["Water visibly covers the road surface"],
        uncertainties=["Image does not establish water depth"],
        model_reported_evidence_strength=0.9,
    )

