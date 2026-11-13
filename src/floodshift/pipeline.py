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
    evaluated_at: datetime | None = None,
) -> StormUpdateResult:
    """Run risk ranking and constrained response allocation in one stable call."""
    now = evaluated_at or datetime.now(timezone.utc)
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
    return StormUpdateResult(
        update_id=f"storm-{sha256(seed.encode()).hexdigest()[:12]}",
        evaluated_at=now,
        risk_assessments=assessments,
        recommendations=recommendations,
        resources=parsed_resources,
        warnings=warnings,
    )


def process_dashboard_update(
    rainfall: Iterable[RainfallCondition | dict],
    observations: Iterable[VisualEvidence | dict],
    resources: ResourceAvailability | dict,
    *,
    locations: Iterable[Location | dict] | None = None,
    previous_assessments: Iterable[RiskAssessment | dict] = (),
    evaluated_at: datetime | None = None,
) -> dict:
    """Return the complete update as a JSON-safe dictionary for Streamlit."""
    return process_storm_update(
        rainfall,
        observations,
        resources,
        locations=locations,
        previous_assessments=previous_assessments,
        evaluated_at=evaluated_at,
    ).model_dump(mode="json")

