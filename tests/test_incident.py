from datetime import datetime, timezone

from floodshift import generate_incident_brief, process_dashboard_update
from conftest import rainfall, visual


NOW = datetime(2026, 11, 13, 18, 0, tzinfo=timezone.utc)


def test_dashboard_payload_contains_safe_incident_brief(location):
    payload = process_dashboard_update(
        [rainfall(location.location_id, 35, 70, 100)],
        [visual(location.location_id)],
        {
            "inspection_teams": 1,
            "debris_crews": 0,
            "traffic_units": 1,
            "emergency_units": 0,
            "human_reviewers": 1,
        },
        locations=[location],
        evaluated_at=NOW,
    )

    brief = payload["incident_brief"]
    assert "not an official FEMA or ICS form" in brief["safety_notice"]
    assert "not a confirmed city deployment" in brief["resource_situation"]["allocation_label"]
    assert brief["priority_threats"][0]["latitude"] == location.latitude
    assert brief["priority_threats"][0]["longitude"] == location.longitude
    assert brief["situation_summary"]["latest_visual_age_minutes"] == 0
    assert "No road closure, dispatch, or field operation is confirmed" in brief["plain_text"]
    consequential = {
        "road_closure_review",
        "prioritize_emergency_response",
    }
    assert all(
        item["human_approval_required"]
        for item in brief["recommended_actions"]
        if item["action"] in consequential
    )

    # The public generator also accepts the complete dashboard dictionary even
    # though that dictionary already has its derived incident_brief field.
    regenerated = generate_incident_brief(payload)
    assert regenerated.brief_id == brief["brief_id"]
    assert regenerated.plain_text == brief["plain_text"]


def test_incident_brief_handles_missing_rainfall_and_visual_data(location):
    payload = process_dashboard_update(
        [],
        [],
        {
            "inspection_teams": 0,
            "debris_crews": 0,
            "traffic_units": 0,
            "emergency_units": 0,
            "human_reviewers": 0,
        },
        locations=[location],
        evaluated_at=NOW,
    )

    brief = payload["incident_brief"]
    assert "No current visual observations were supplied." in brief["unverified_information"]
    assert "No rainfall freshness timestamp is available." in brief["unverified_information"]
    assert brief["situation_summary"]["rainfall_observed_through"] is None
    assert brief["decision_summary"]
