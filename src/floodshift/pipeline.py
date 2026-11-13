"""End-to-end storm update orchestration for notebooks and dashboard clients."""

from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
from typing import Iterable

from .infrastructure import load_locations
from .response import recommend_responses
from .risk import evaluate_flood_risk
from .schemas import (
    Location,
    InputContext,
    Provenance,
    RainfallCondition,
    ResourceAvailability,
    RiskAssessment,
    StormUpdateResult,
    VisualEvidence,
)


def process_storm_update(
    rainfall: Iterable[RainfallCondition | dict],
    observations: Iterable[VisualEvidence | dict],
    resources: ResourceAvailability | dict,
    *,
    locations: Iterable[Location | dict] | None = None,
    previous_assessments: Iterable[RiskAssessment | dict] = (),
    evaluated_at: datetime | str | None = None,
) -> StormUpdateResult:
    """Run risk ranking and constrained response allocation in one stable call."""
    now = (
        datetime.fromisoformat(evaluated_at)
        if isinstance(evaluated_at, str)
        else evaluated_at or datetime.now(timezone.utc)
    )
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    parsed_locations = (
        [Location.model_validate(item) for item in locations]
        if locations is not None
        else load_locations()
    )
    parsed_rain = [RainfallCondition.model_validate(item) for item in rainfall]
    parsed_observations = [VisualEvidence.model_validate(item) for item in observations]
    parsed_resources = ResourceAvailability.model_validate(resources)
    assessments = evaluate_flood_risk(
        parsed_locations,
        parsed_rain,
        parsed_observations,
        previous_assessments=previous_assessments,
        evaluated_at=now,
    )
    recommendations = recommend_responses(assessments, parsed_resources)
    warnings: list[str] = []
    if any(item.provenance == Provenance.SYNTHETIC for item in parsed_locations):
        warnings.append("One or more infrastructure locations are synthetic demo fixtures")
    if any(item.attributes.get("demo_scoring_attributes_synthetic") for item in parsed_locations):
        warnings.append(
            "Crossing geography is official; vulnerability, criticality, and inlet-count features are illustrative"
        )
    if any(item.provenance == Provenance.SYNTHETIC for item in parsed_rain):
        warnings.append("Rainfall conditions include simulated storm-replay inputs")
    if not parsed_observations:
        warnings.append("No location-verified visual observations were supplied")
    if any(item.location_id is None for item in parsed_observations):
        warnings.append("Unlocated images were excluded from location-specific risk updates")
    seed = f"{now.isoformat()}|{','.join(item.location_id for item in assessments)}"
    rainfall_times = [item.timestamp for item in parsed_rain]
    latest_rainfall_age = (
        max(0.0, (now - max(rainfall_times)).total_seconds() / 60.0)
        if rainfall_times else None
    )
    visual_times = [
        item.observed_at for item in parsed_observations if item.observed_at is not None
    ]
    latest_visual_age = (
        max(0.0, (now - max(visual_times)).total_seconds() / 60.0)
        if visual_times else None
    )
    return StormUpdateResult(
        update_id=f"storm-{sha256(seed.encode()).hexdigest()[:12]}",
        evaluated_at=now,
        risk_assessments=assessments,
        recommendations=recommendations,
        resources=parsed_resources,
        input_context=InputContext(
            rainfall_location_count=len({item.location_id for item in parsed_rain}),
            rainfall_observed_from=min(rainfall_times) if rainfall_times else None,
            rainfall_observed_through=max(rainfall_times) if rainfall_times else None,
            latest_rainfall_age_minutes=round(latest_rainfall_age, 2) if latest_rainfall_age is not None else None,
            max_hourly_mm=max((item.hourly_mm for item in parsed_rain), default=None),
            max_previous_3h_mm=max((item.previous_3h_mm for item in parsed_rain), default=None),
            max_previous_24h_mm=max((item.previous_24h_mm for item in parsed_rain), default=None),
            rainfall_provenance=list(dict.fromkeys(item.provenance for item in parsed_rain)),
            visual_observation_count=len(parsed_observations),
            location_verified_visual_count=sum(item.location_id is not None for item in parsed_observations),
            unlocated_visual_count=sum(item.location_id is None for item in parsed_observations),
            latest_visual_observed_at=max(visual_times) if visual_times else None,
            latest_visual_age_minutes=(
                round(latest_visual_age, 2)
                if latest_visual_age is not None
                else None
            ),
            synthetic_inputs_present=(
                any(item.provenance == Provenance.SYNTHETIC for item in parsed_rain)
                or any(item.provenance == Provenance.SYNTHETIC for item in parsed_observations)
                or any(
                    item.provenance == Provenance.SYNTHETIC
                    or item.attributes.get("demo_scoring_attributes_synthetic")
                    for item in parsed_locations
                )
            ),
        ),
        warnings=warnings,
    )


def process_dashboard_update(
    rainfall: Iterable[RainfallCondition | dict],
    observations: Iterable[VisualEvidence | dict],
    resources: ResourceAvailability | dict,
    *,
    locations: Iterable[Location | dict] | None = None,
    previous_assessments: Iterable[RiskAssessment | dict] = (),
    evaluated_at: datetime | str | None = None,
) -> dict:
    """Return the complete update as a JSON-safe dictionary for Streamlit."""
    result = process_storm_update(
        rainfall,
        observations,
        resources,
        locations=locations,
        previous_assessments=previous_assessments,
        evaluated_at=evaluated_at,
    )
    payload = result.model_dump(mode="json")
    from .incident import generate_incident_brief

    payload["incident_brief"] = generate_incident_brief(result).model_dump(mode="json")
    return payload

