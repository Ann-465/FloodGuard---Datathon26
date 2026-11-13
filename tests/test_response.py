from floodshift.response import recommend_responses
from floodshift.risk import evaluate_flood_risk
from floodshift.schemas import ActionType, AllocationStatus

from conftest import rainfall, visual


def test_recommendations_respect_resource_limits(location):
    assessment = evaluate_flood_risk(
        [location], [rainfall("loc-1", 50, 100, 200)], [visual("loc-1")]
    )
    recommendations = recommend_responses(
        assessment,
        {
            "inspection_teams": 1,
            "debris_crews": 1,
            "traffic_units": 1,
            "emergency_units": 1,
            "human_reviewers": 1,
        },
    )
    allocated_reviewer_actions = [
        item
        for item in recommendations
        if item.allocation_status == AllocationStatus.ALLOCATED
        and item.action
        in {ActionType.HUMAN_VERIFICATION, ActionType.ROAD_CLOSURE_REVIEW, ActionType.EMERGENCY_RESPONSE}
    ]
    assert len(allocated_reviewer_actions) <= 1
    assert any(item.allocation_status == AllocationStatus.DEFERRED for item in recommendations)


def test_high_impact_actions_require_human_approval(location):
    assessment = evaluate_flood_risk(
        [location], [rainfall("loc-1", 50, 100, 200)], [visual("loc-1")]
    )
    recommendations = recommend_responses(assessment, {"traffic_units": 1, "emergency_units": 1, "human_reviewers": 2})
    high_impact = [
        item for item in recommendations
        if item.action in {ActionType.ROAD_CLOSURE_REVIEW, ActionType.EMERGENCY_RESPONSE}
    ]
    assert high_impact
    assert all(item.human_approval_required for item in high_impact)

