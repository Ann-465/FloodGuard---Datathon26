"""Validated, JSON-compatible contracts shared by every FloodShift component."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class Provenance(StrEnum):
    ORGANIZER = "organizer_provided"
    OFFICIAL_LINKED = "official_linked_external"
    EXTERNAL = "additional_external"
    SYNTHETIC = "synthetic_demo"
    HUMAN = "human_observation"
    MODEL = "model_observation"


class Severity(StrEnum):
    LOW = "low"
    MODERATE = "moderate"
    HIGH = "high"
    CRITICAL = "critical"


class EvidenceValue(StrEnum):
    YES = "yes"
    NO = "no"
    UNCERTAIN = "uncertain"


class AnalysisStatus(StrEnum):
    SUCCESS = "success"
    FALLBACK = "fallback"


class ActionType(StrEnum):
    HUMAN_VERIFICATION = "request_human_verification"
    INSPECT_INFRASTRUCTURE = "inspect_drainage_infrastructure"
    DEBRIS_REMOVAL = "prioritize_debris_removal"
    ROAD_CLOSURE_REVIEW = "road_closure_review"
    EMERGENCY_RESPONSE = "prioritize_emergency_response"


class AllocationStatus(StrEnum):
    ALLOCATED = "allocated"
    DEFERRED = "deferred_resource_limit"
    ADVISORY = "advisory_no_resource_required"


class Location(StrictModel):
    location_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    is_low_water_crossing: bool = False
    drainage_vulnerability: float = Field(
        default=0.5, ge=0, le=1,
        description="Transparent 0-1 vulnerability feature, not a flood probability.",
    )
    criticality: float = Field(default=0.5, ge=0, le=1)
    nearby_inlet_count: int | None = Field(default=None, ge=0)
    provenance: Provenance
    source_name: str
    source_url: str | None = None
    attributes: dict[str, Any] = Field(default_factory=dict)


class RainfallCondition(StrictModel):
    location_id: str
    timestamp: datetime
    hourly_mm: float = Field(default=0, ge=0)
    previous_3h_mm: float = Field(default=0, ge=0)
    previous_24h_mm: float = Field(default=0, ge=0)
    provenance: Provenance = Provenance.SYNTHETIC
    source_name: str = "storm replay"

    @field_validator("timestamp")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


class VisualEvidence(StrictModel):
    observation_id: str
    location_id: str | None = None
    observed_at: datetime | None = None
    analysis_status: AnalysisStatus = AnalysisStatus.SUCCESS
    visible_flooding: EvidenceValue = EvidenceValue.UNCERTAIN
    road_obstructed: EvidenceValue = EvidenceValue.UNCERTAIN
    debris_visible: EvidenceValue = EvidenceValue.UNCERTAIN
    visual_severity: int = Field(default=0, ge=0, le=3)
    evidence: list[str] = Field(default_factory=list)
    uncertainties: list[str] = Field(default_factory=list)
    model_reported_evidence_strength: float = Field(
        default=0, ge=0, le=1,
        description="Model-reported evidence strength; not a calibrated probability.",
    )
    provenance: Provenance = Provenance.MODEL
    source_name: str = "Qwen3-VL-8B-Instruct"
    image_reference: str | None = None
    supplied_metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("observed_at")
    @classmethod
    def normalize_observed_at_timezone(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


class RiskAssessment(StrictModel):
    location_id: str
    location_name: str
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    evaluated_at: datetime
    risk_score: float = Field(ge=0, le=100)
    severity: Severity
    confidence: float = Field(ge=0, le=1)
    component_scores: dict[str, float]
    evidence: list[str]
    uncertainties: list[str]
    triggers: list[str]
    data_provenance: list[Provenance]
    rank: int | None = Field(default=None, ge=1)
    change_from_previous: float | None = None


class ResourceAvailability(StrictModel):
    inspection_teams: int = Field(default=0, ge=0)
    debris_crews: int = Field(default=0, ge=0)
    traffic_units: int = Field(default=0, ge=0)
    emergency_units: int = Field(default=0, ge=0)
    human_reviewers: int = Field(default=0, ge=0)


class ResponseRecommendation(StrictModel):
    recommendation_id: str
    location_id: str
    location_name: str
    risk_score: float = Field(ge=0, le=100)
    risk_level: Severity
    action: ActionType
    priority_score: float = Field(ge=0, le=100)
    rationale: str
    evidence: list[str]
    uncertainties: list[str]
    required_resource: str | None
    allocation_status: AllocationStatus
    human_approval_required: bool


class InputContext(StrictModel):
    rainfall_location_count: int = Field(default=0, ge=0)
    rainfall_observed_from: datetime | None = None
    rainfall_observed_through: datetime | None = None
    latest_rainfall_age_minutes: float | None = Field(default=None, ge=0)
    max_hourly_mm: float | None = Field(default=None, ge=0)
    max_previous_3h_mm: float | None = Field(default=None, ge=0)
    max_previous_24h_mm: float | None = Field(default=None, ge=0)
    rainfall_provenance: list[Provenance] = Field(default_factory=list)
    visual_observation_count: int = Field(default=0, ge=0)
    location_verified_visual_count: int = Field(default=0, ge=0)
    unlocated_visual_count: int = Field(default=0, ge=0)
    latest_visual_observed_at: datetime | None = None
    latest_visual_age_minutes: float | None = Field(default=None, ge=0)
    synthetic_inputs_present: bool = False


class StormUpdateResult(StrictModel):
    update_id: str
    evaluated_at: datetime
    risk_assessments: list[RiskAssessment]
    recommendations: list[ResponseRecommendation]
    resources: ResourceAvailability
    input_context: InputContext = Field(default_factory=InputContext)
    warnings: list[str] = Field(default_factory=list)
    methodology_version: str = "floodshift-0.1"


class IncidentCommandBrief(StrictModel):
    brief_id: str
    generated_at: datetime
    title: str = "FloodShift Incident Command Brief"
    safety_notice: str
    situation_summary: dict[str, Any]
    priority_threats: list[dict[str, Any]]
    recommended_actions: list[dict[str, Any]]
    resource_situation: dict[str, Any]
    unverified_information: list[str]
    decision_summary: str
    plain_text: str

