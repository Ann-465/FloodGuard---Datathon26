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
