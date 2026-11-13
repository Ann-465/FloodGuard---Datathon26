"""Pure integration helpers shared by Streamlit and focused tests."""

from __future__ import annotations

from datetime import datetime
from typing import Iterable

from floodshift import process_dashboard_update
from floodshift.schemas import Location, VisualEvidence


DEFAULT_RESOURCES = {
    "inspection_teams": 2,
    "debris_crews": 1,
    "traffic_units": 1,
    "emergency_units": 1,
    "human_reviewers": 2,
}


def observations_available_at(
    observations: Iterable[VisualEvidence | dict],
    evaluated_at: str,
) -> list[dict]:
    """Prevent evidence submitted later in a replay from affecting earlier frames."""
    frame_time = datetime.fromisoformat(evaluated_at)
    available = []
    for raw in observations:
        item = VisualEvidence.model_validate(raw)
        if item.observed_at is None or item.observed_at <= frame_time:
            available.append(item.model_dump(mode="json"))
    return available


def calculate_replay_payloads(
    frames: list[dict],
    frame_index: int,
    locations: Iterable[Location | dict],
    resources: dict,
    observations: Iterable[VisualEvidence | dict] = (),
) -> list[dict]:
    """Run every frame through the real backend so deltas remain chronological."""
    if not frames:
        raise ValueError("Replay has no frames")
    if not 0 <= frame_index < len(frames):
        raise IndexError("Replay frame is outside the available timeline")
    parsed_locations = [Location.model_validate(item) for item in locations]
    previous = []
    payloads = []
    for frame in frames[: frame_index + 1]:
        payload = process_dashboard_update(
            rainfall=frame["rainfall"],
            observations=observations_available_at(observations, frame["timestamp"]),
            resources=resources,
            locations=parsed_locations,
            previous_assessments=previous,
            evaluated_at=frame["timestamp"],
        )
        payloads.append(payload)
        previous = payload["risk_assessments"]
    return payloads


def allocation_changes(previous: dict | None, current: dict) -> dict[str, list[str]]:
    """Explain proposed assignment changes without implying an actual dispatch."""
    def allocated(payload: dict | None) -> set[str]:
        if not payload:
            return set()
        return {
            item["recommendation_id"]
            for item in payload["recommendations"]
            if item["allocation_status"] == "allocated"
        }

    before = allocated(previous)
    after = allocated(current)
    return {
        "newly_allocated": sorted(after - before),
        "no_longer_allocated": sorted(before - after),
    }


def summarize_changes(previous: dict | None, current: dict) -> dict:
    """Return backend-derived changes for the judge-facing operations view."""
    current_assessments = current["risk_assessments"]
    current_recommendations = current["recommendations"]
    if previous is None:
        return {
            "risk_increases": [],
            "rank_changes": [],
            "new_actions": [],
            "newly_allocated": [],
            "no_longer_allocated": [],
            "newly_deferred": [],
            "is_baseline": True,
        }

    previous_assessments = {
        item["location_id"]: item for item in previous["risk_assessments"]
    }
    risk_increases = []
    rank_changes = []
    for item in current_assessments:
        before = previous_assessments.get(item["location_id"])
        if not before:
            continue
        delta = round(item["risk_score"] - before["risk_score"], 1)
        if delta > 0.05:
            risk_increases.append(
                {
                    "location_id": item["location_id"],
                    "location_name": item["location_name"],
                    "delta": delta,
                    "score": item["risk_score"],
                }
            )
        rank_delta = before["rank"] - item["rank"]
        if rank_delta:
            rank_changes.append(
                {
                    "location_id": item["location_id"],
                    "location_name": item["location_name"],
                    "from_rank": before["rank"],
                    "to_rank": item["rank"],
                    "places": abs(rank_delta),
                    "direction": "up" if rank_delta > 0 else "down",
                }
            )

    previous_recommendations = {
        item["recommendation_id"]: item for item in previous["recommendations"]
    }
    current_ids = {item["recommendation_id"] for item in current_recommendations}
    new_actions = [
        item for item in current_recommendations
        if item["recommendation_id"] not in previous_recommendations
    ]
    newly_deferred = [
        item for item in current_recommendations
        if item["allocation_status"] == "deferred_resource_limit"
        and (
            item["recommendation_id"] not in previous_recommendations
            or previous_recommendations[item["recommendation_id"]]["allocation_status"]
            != "deferred_resource_limit"
        )
    ]
    allocation_delta = allocation_changes(previous, current)
    recommendations_by_id = {
        item["recommendation_id"]: item for item in current_recommendations
    }
    previous_by_id = {
        item["recommendation_id"]: item for item in previous["recommendations"]
    }

    def describe(ids: list[str], source: dict[str, dict]) -> list[dict]:
        return [source[item_id] for item_id in ids if item_id in source]

    return {
        "risk_increases": sorted(risk_increases, key=lambda item: item["delta"], reverse=True),
        "rank_changes": sorted(
            rank_changes,
            key=lambda item: (item["direction"] != "up", -item["places"]),
        ),
        "new_actions": new_actions,
        "newly_allocated": describe(
            allocation_delta["newly_allocated"], recommendations_by_id
        ),
        "no_longer_allocated": describe(
            allocation_delta["no_longer_allocated"], previous_by_id
        ),
        "newly_deferred": newly_deferred,
        "is_baseline": False,
        "active_action_count": len(current_ids),
    }


def catalog_partition(
    catalog_rows: Iterable[dict],
    scored_locations: Iterable[Location | dict],
) -> tuple[list[dict], list[dict]]:
    """Explicitly separate validated/scored and catalog-only crossings."""
    scored_ids = {Location.model_validate(item).location_id for item in scored_locations}
    scored, unscored = [], []
    for row in catalog_rows:
        (scored if row["location_id"] in scored_ids else unscored).append(row)
    return scored, unscored
