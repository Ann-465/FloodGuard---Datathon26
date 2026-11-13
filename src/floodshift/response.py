"""Evidence-aware recommendations and exact small-scenario resource allocation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .schemas import (
    ActionType,
    AllocationStatus,
    ResourceAvailability,
    ResponseRecommendation,
    RiskAssessment,
    Severity,
)


RESOURCE_FIELDS = (
    "inspection_teams",
    "debris_crews",
    "traffic_units",
    "emergency_units",
    "human_reviewers",
)


@dataclass(frozen=True)
class _Candidate:
    assessment: RiskAssessment
    action: ActionType
    priority: float
    rationale: str
    demands: tuple[int, int, int, int, int]
    human_approval: bool


def _clamp(value: float) -> float:
    return round(max(0.0, min(100.0, value)), 2)


def _candidate_actions(item: RiskAssessment) -> list[_Candidate]:
    triggers = set(item.triggers)
    results: list[_Candidate] = []
    low_confidence = item.confidence < 0.70 or "missing_visual_observation" in triggers
    if low_confidence:
        results.append(
            _Candidate(
                item,
                ActionType.HUMAN_VERIFICATION,
                _clamp(item.risk_score + 15 * (1 - item.confidence)),
                "Resolve material uncertainty before escalating automated evidence.",
                (0, 0, 0, 0, 1),
                False,
            )
        )

    if item.severity in {Severity.MODERATE, Severity.HIGH, Severity.CRITICAL} or "low_water_crossing" in triggers:
        results.append(
            _Candidate(
                item,
                ActionType.INSPECT_INFRASTRUCTURE,
                _clamp(item.risk_score + (6 if "low_water_crossing" in triggers else 2)),
                "Inspect the vulnerable drainage asset and verify current site conditions.",
                (1, 0, 0, 0, 0),
                False,
            )
        )

    if "debris_visible" in triggers:
        results.append(
            _Candidate(
                item,
                ActionType.DEBRIS_REMOVAL,
                _clamp(item.risk_score + 8),
                "Visible debris may obstruct drainage; prioritize a safe maintenance assessment.",
                (0, 1, 0, 0, 0),
                True,
            )
        )

    road_condition = "road_obstructed" in triggers or (
        item.severity == Severity.CRITICAL and "low_water_crossing" in triggers
    )
    if road_condition:
        results.append(
            _Candidate(
                item,
                ActionType.ROAD_CLOSURE_REVIEW,
                _clamp(item.risk_score + 12),
                "Road-access evidence warrants immediate review by authorized traffic personnel.",
                (0, 0, 1, 0, 1),
                True,
            )
        )

    if item.severity == Severity.CRITICAL and (
        "visible_flooding" in triggers or "road_obstructed" in triggers
    ):
        results.append(
            _Candidate(
                item,
                ActionType.EMERGENCY_RESPONSE,
                _clamp(item.risk_score + 15),
                "Critical risk plus location-verified visual evidence supports emergency prioritization.",
                (0, 0, 0, 1, 1),
                True,
            )
        )
    return results


def _allocate_exact(candidates: list[_Candidate], resources: ResourceAvailability) -> set[int]:
    """Maximize total priority under all resource constraints via sparse DP.

    The datathon scenario is intentionally small (dozens of candidate actions), so
    an exact dynamic program is understandable, deterministic, and dependency-free.
    """
    capacity = tuple(getattr(resources, name) for name in RESOURCE_FIELDS)
    # state -> (utility, selected indices); lexicographic indices make ties stable.
    states: dict[tuple[int, ...], tuple[float, tuple[int, ...]]] = {
        (0, 0, 0, 0, 0): (0.0, ())
    }
    for index, candidate in enumerate(candidates):
        updated = dict(states)
        for used, (utility, selected) in states.items():
            next_used = tuple(used[pos] + candidate.demands[pos] for pos in range(5))
            if any(next_used[pos] > capacity[pos] for pos in range(5)):
                continue
            proposal = (round(utility + candidate.priority, 4), selected + (index,))
            current = updated.get(next_used)
            if current is None or proposal[0] > current[0] or (
                proposal[0] == current[0] and proposal[1] < current[1]
            ):
                updated[next_used] = proposal
        states = updated
    best = max(states.values(), key=lambda item: (item[0], tuple(-x for x in item[1])))
    return set(best[1])


def recommend_responses(
    risk_assessments: Iterable[RiskAssessment | dict],
    resources: ResourceAvailability | dict,
) -> list[ResponseRecommendation]:
    """Generate candidates, optimize allocations, and preserve deferred actions."""
    parsed = [RiskAssessment.model_validate(item) for item in risk_assessments]
    available = ResourceAvailability.model_validate(resources)
    candidates = [candidate for item in parsed for candidate in _candidate_actions(item)]
    candidates.sort(
        key=lambda candidate: (
            -candidate.priority,
            candidate.assessment.location_id,
            candidate.action.value,
        )
    )
    selected = _allocate_exact(candidates, available)
    recommendations: list[ResponseRecommendation] = []
    for index, candidate in enumerate(candidates):
        demanded = [
            RESOURCE_FIELDS[pos] for pos, amount in enumerate(candidate.demands) if amount
        ]
        recommendations.append(
            ResponseRecommendation(
                recommendation_id=f"{candidate.assessment.location_id}:{candidate.action.value}",
                location_id=candidate.assessment.location_id,
                location_name=candidate.assessment.location_name,
                risk_score=candidate.assessment.risk_score,
                risk_level=candidate.assessment.severity,
                action=candidate.action,
                priority_score=candidate.priority,
                rationale=candidate.rationale,
                evidence=candidate.assessment.evidence,
                uncertainties=candidate.assessment.uncertainties,
                required_resource=" + ".join(demanded) or None,
                allocation_status=(
                    AllocationStatus.ALLOCATED if index in selected else AllocationStatus.DEFERRED
                ),
                human_approval_required=candidate.human_approval,
            )
        )
    return recommendations

