"""Transparent multimodal flood-risk scoring with explicit uncertainty."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable

from .schemas import (
    AnalysisStatus,
    EvidenceValue,
    Location,
    Provenance,
    RainfallCondition,
    RiskAssessment,
    Severity,
    VisualEvidence,
)


RISK_WEIGHTS = {
    "rainfall": 45.0,
    "infrastructure": 30.0,
    "visual_observation": 25.0,
}


def _severity(score: float) -> Severity:
    if score >= 75:
        return Severity.CRITICAL
    if score >= 50:
        return Severity.HIGH
    if score >= 25:
        return Severity.MODERATE
    return Severity.LOW


def _rainfall_score(rain: RainfallCondition) -> float:
    # Saturating, documented thresholds. These are scenario-scoring thresholds,
    # not claims about a universal physical flood threshold.
    hourly = min(rain.hourly_mm / 50.0, 1.0)
    three_hour = min(rain.previous_3h_mm / 100.0, 1.0)
    daily = min(rain.previous_24h_mm / 200.0, 1.0)
    return 45.0 * (0.45 * hourly + 0.35 * three_hour + 0.20 * daily)


def _infrastructure_score(location: Location) -> float:
    crossing = 12.0 if location.is_low_water_crossing else 0.0
    vulnerability = 12.0 * location.drainage_vulnerability
    criticality = 4.0 * location.criticality
    # Sparse inlets can be a concern, but the weak two-point weight avoids
    # presenting inlet count as hydraulic capacity.
    inlet_factor = 0.0
    if location.nearby_inlet_count is not None:
        inlet_factor = 2.0 * max(0.0, 1.0 - min(location.nearby_inlet_count / 8.0, 1.0))
    return crossing + vulnerability + criticality + inlet_factor


def _visual_age_hours(observation: VisualEvidence | None, evaluated_at: datetime) -> float | None:
    if not observation or not observation.observed_at:
        return None
    return max(0.0, (evaluated_at - observation.observed_at).total_seconds() / 3600.0)


def _visual_score(observation: VisualEvidence | None, evaluated_at: datetime) -> float:
    if not observation or observation.analysis_status != AnalysisStatus.SUCCESS:
        return 0.0
    flooding = {EvidenceValue.YES: 8.0, EvidenceValue.UNCERTAIN: 3.0, EvidenceValue.NO: 0.0}[
        observation.visible_flooding
    ]
    road = {EvidenceValue.YES: 7.0, EvidenceValue.UNCERTAIN: 2.0, EvidenceValue.NO: 0.0}[
        observation.road_obstructed
    ]
    debris = {EvidenceValue.YES: 3.0, EvidenceValue.UNCERTAIN: 1.0, EvidenceValue.NO: 0.0}[
        observation.debris_visible
    ]
    severity = 7.0 * observation.visual_severity / 3.0
    raw = flooding + road + debris + severity
    # Weak model evidence is retained but discounted; it cannot override the
    # numerical rainfall/infrastructure components.
    strength_multiplier = 0.5 + 0.5 * observation.model_reported_evidence_strength
    age_hours = _visual_age_hours(observation, evaluated_at)
    freshness_multiplier = 0.5 if age_hours is None else (0.0 if age_hours > 6 else (0.5 if age_hours > 2 else 1.0))
    return min(25.0, raw * strength_multiplier * freshness_multiplier)


def _latest_observation(
    observations: Iterable[VisualEvidence], location_id: str
) -> VisualEvidence | None:
    matched = [item for item in observations if item.location_id == location_id]
    if not matched:
        return None
    return max(
        matched,
        key=lambda item: item.observed_at or datetime.min.replace(tzinfo=timezone.utc),
    )


def _confidence(
    location: Location,
    rain: RainfallCondition | None,
    observation: VisualEvidence | None,
    evaluated_at: datetime,
) -> float:
    synthetic_features = bool(location.attributes.get("demo_scoring_attributes_synthetic"))
    infrastructure_quality = 0.20 if (
        location.provenance == Provenance.SYNTHETIC or synthetic_features
    ) else 0.30
    rainfall_quality = 0.40 if rain and rain.provenance != Provenance.SYNTHETIC else (0.30 if rain else 0.0)
    visual_quality = 0.0
    if observation and observation.analysis_status == AnalysisStatus.SUCCESS:
        age_hours = _visual_age_hours(observation, evaluated_at)
        freshness = 0.5 if age_hours is None else (0.0 if age_hours > 6 else (0.5 if age_hours > 2 else 1.0))
        visual_quality = 0.30 * observation.model_reported_evidence_strength * freshness
    return round(min(1.0, infrastructure_quality + rainfall_quality + visual_quality), 3)


def evaluate_flood_risk(
    locations: Iterable[Location | dict],
    rainfall: Iterable[RainfallCondition | dict],
    observations: Iterable[VisualEvidence | dict] = (),
    *,
    previous_assessments: Iterable[RiskAssessment | dict] = (),
    evaluated_at: datetime | None = None,
) -> list[RiskAssessment]:
    """Score and rank locations using transparent, bounded components.

    Only observations with an explicitly matching ``location_id`` affect a location.
    This prevents Houston training/evaluation photographs from being attached to a
    San Antonio crossing without valid geographic evidence.
    """
    now = evaluated_at or datetime.now(timezone.utc)
    parsed_locations = [Location.model_validate(item) for item in locations]
    parsed_rain = [RainfallCondition.model_validate(item) for item in rainfall]
    parsed_observations = [VisualEvidence.model_validate(item) for item in observations]
    previous = [RiskAssessment.model_validate(item) for item in previous_assessments]
    rain_by_location = {item.location_id: item for item in parsed_rain}
    previous_by_location = {item.location_id: item for item in previous}

    assessments: list[RiskAssessment] = []
    for location in parsed_locations:
        rain = rain_by_location.get(location.location_id)
        visual = _latest_observation(parsed_observations, location.location_id)
        components = {
            "rainfall": round(_rainfall_score(rain), 2) if rain else 0.0,
            "infrastructure": round(_infrastructure_score(location), 2),
            "visual_observation": round(_visual_score(visual, now), 2),
        }
        score = round(min(100.0, sum(components.values())), 2)
        evidence = [
            f"Infrastructure component {components['infrastructure']:.1f}/30",
        ]
        uncertainties: list[str] = []
        triggers: list[str] = []
        provenance = [location.provenance]

        if location.is_low_water_crossing:
            evidence.append("Location is identified as a low-water crossing")
            triggers.append("low_water_crossing")
        if location.attributes.get("drainage_vulnerability_method") == "mapped_asset_density_proxy_v1":
            evidence.append(
                f"Official mapped assets within {location.attributes.get('buffer_radius_m', 500)} m: "
                f"{location.nearby_inlet_count or 0} inlets, "
                f"{location.attributes.get('underground_segment_count', 0)} underground segments, "
                f"{location.attributes.get('channel_segment_count', 0)} channel segments"
            )
            uncertainties.append(
                "Mapped asset density is an explainable drainage proxy, not measured hydraulic capacity"
            )
            triggers.append("infrastructure_density_proxy")
        if location.attributes.get("criticality_method") == "neutral_until_verified_road_criticality_data":
            uncertainties.append(
                "Road criticality is neutral because verified traffic and emergency-route data are not integrated"
            )
        if rain:
            evidence.append(
                f"Rainfall: {rain.hourly_mm:.1f} mm/h, {rain.previous_3h_mm:.1f} mm/3h, "
                f"{rain.previous_24h_mm:.1f} mm/24h"
            )
            provenance.append(rain.provenance)
            rain_age_hours = max(0.0, (now - rain.timestamp).total_seconds() / 3600.0)
            if rain_age_hours > 2:
                uncertainties.append(f"Rainfall observation is {rain_age_hours:.1f} hours old")
                triggers.append("stale_rainfall")
            if rain.provenance == Provenance.SYNTHETIC:
                uncertainties.append("Rainfall is a simulated storm-replay input")
                triggers.append("synthetic_rainfall")
        else:
            uncertainties.append("No location-specific rainfall update was supplied")
            triggers.append("missing_rainfall")

        if visual and visual.analysis_status == AnalysisStatus.SUCCESS:
            evidence.extend(visual.evidence)
            uncertainties.extend(visual.uncertainties)
            provenance.append(visual.provenance)
            visual_age_hours = _visual_age_hours(visual, now)
            if visual_age_hours is None:
                uncertainties.append("Visual observation has no verified timestamp and is freshness-discounted")
                triggers.append("visual_timestamp_missing")
            elif visual_age_hours > 6:
                uncertainties.append(f"Visual observation is stale ({visual_age_hours:.1f} hours old) and does not affect current risk")
                triggers.append("stale_visual_observation")
            elif visual_age_hours > 2:
                uncertainties.append(f"Visual observation is aging ({visual_age_hours:.1f} hours old) and is freshness-discounted")
                triggers.append("aging_visual_observation")
            # Stale or untimed images remain visible as evidence, but they cannot
            # trigger consequential response candidates as if they were current.
            visual_is_actionable = (
                visual_age_hours is not None and visual_age_hours <= 6
            )
            if visual_is_actionable:
                if visual.visible_flooding == EvidenceValue.YES:
                    triggers.append("visible_flooding")
                if visual.road_obstructed == EvidenceValue.YES:
                    triggers.append("road_obstructed")
                if visual.debris_visible == EvidenceValue.YES:
                    triggers.append("debris_visible")
        else:
            uncertainties.append("No successful, location-verified visual observation is available")
            triggers.append("missing_visual_observation")

        if location.provenance == Provenance.SYNTHETIC:
            uncertainties.append("Location attributes are an illustrative demo fixture")
            triggers.append("synthetic_infrastructure")
        elif location.attributes.get("demo_scoring_attributes_synthetic"):
            uncertainties.append(
                "Crossing identity and coordinates are official; vulnerability, criticality, and inlet-count features are illustrative"
            )
            triggers.append("synthetic_infrastructure_attributes")
            provenance.append(Provenance.SYNTHETIC)

        previous_item = previous_by_location.get(location.location_id)
        change = round(score - previous_item.risk_score, 2) if previous_item else None
        assessments.append(
            RiskAssessment(
                location_id=location.location_id,
                location_name=location.name,
                latitude=location.latitude,
                longitude=location.longitude,
                evaluated_at=now,
                risk_score=score,
                severity=_severity(score),
                confidence=_confidence(location, rain, visual, now),
                component_scores=components,
                evidence=evidence,
                uncertainties=list(dict.fromkeys(uncertainties)),
                triggers=list(dict.fromkeys(triggers)),
                data_provenance=list(dict.fromkeys(provenance)),
                change_from_previous=change,
            )
        )

    assessments.sort(key=lambda item: (-item.risk_score, item.location_id))
    for rank, assessment in enumerate(assessments, start=1):
        assessment.rank = rank
    return assessments

