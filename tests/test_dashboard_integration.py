import csv
from pathlib import Path

import pytest

from floodshift.infrastructure import load_locations
from frontend.operations import (
    DEFAULT_RESOURCES,
    calculate_replay_payloads,
    catalog_partition,
    summarize_changes,
)
from frontend.storm_replay import build_synthetic_frames, load_historical_frames


ROOT = Path(__file__).resolve().parents[1]


def test_historical_replay_ingests_all_noaa_frames():
    frames, metadata = load_historical_frames()
    assert len(frames) == 27
    assert all(len(frame["rainfall"]) == 8 for frame in frames)
    assert all(
        item["provenance"] == "additional_external"
        for frame in frames
        for item in frame["rainfall"]
    )
    assert "not crossing-level" in metadata["county_outcome_context"]["warning"]


def test_synthetic_adapter_uses_correct_ten_minute_accumulation_units():
    frames = build_synthetic_frames("Severe", ["one", "two"])
    fifth = frames[4]["rainfall"][0]
    assert fifth["hourly_mm"] == 65
    assert fifth["previous_3h_mm"] == pytest.approx(25.833)
    assert fifth["previous_24h_mm"] == pytest.approx(25.833)
    assert all(item["source_name"].startswith("Uniform Severe simulated") for item in frames[4]["rainfall"])


def test_catalog_explicitly_separates_scored_and_unscored_locations():
    with (ROOT / "data" / "locations.csv").open(encoding="utf-8") as handle:
        catalog = list(csv.DictReader(handle))
    scored, unscored = catalog_partition(catalog, load_locations())
    assert len(scored) == 8
    assert len(unscored) == len(catalog) - 8
    assert {item["location_id"] for item in scored} == {
        item.location_id for item in load_locations()
    }


def test_three_frames_change_real_backend_risk_and_brief():
    locations = load_locations()
    frames = build_synthetic_frames("Flash Flood", [item.location_id for item in locations])
    payloads = calculate_replay_payloads(
        frames,
        5,
        locations,
        DEFAULT_RESOURCES,
    )
    top_scores = [payloads[index]["risk_assessments"][0]["risk_score"] for index in (0, 3, 5)]
    assert len(set(top_scores)) == 3
    assert payloads[-1]["incident_brief"]["plain_text"]
    assert all(item["change_from_previous"] is not None for item in payloads[-1]["risk_assessments"])


def test_resource_limits_change_exact_optimizer_allocations():
    locations = load_locations()
    frames = build_synthetic_frames("Flash Flood", [item.location_id for item in locations])
    no_resources = {key: 0 for key in DEFAULT_RESOURCES}
    constrained = calculate_replay_payloads(frames, 5, locations, no_resources)[-1]
    available = calculate_replay_payloads(frames, 5, locations, DEFAULT_RESOURCES)[-1]
    constrained_allocated = sum(
        item["allocation_status"] == "allocated" for item in constrained["recommendations"]
    )
    available_allocated = sum(
        item["allocation_status"] == "allocated" for item in available["recommendations"]
    )
    assert constrained_allocated == 0
    assert available_allocated > constrained_allocated


def test_change_summary_is_derived_from_consecutive_backend_frames():
    locations = load_locations()
    frames = build_synthetic_frames("Flash Flood", [item.location_id for item in locations])
    payloads = calculate_replay_payloads(frames, 4, locations, DEFAULT_RESOURCES)
    summary = summarize_changes(payloads[-2], payloads[-1])

    assert not summary["is_baseline"]
    assert summary["risk_increases"]
    assert all(item["delta"] > 0 for item in summary["risk_increases"])
    assert summary["risk_increases"][0]["score"] == payloads[-1]["risk_assessments"][0]["risk_score"]


def test_unlocated_image_never_changes_crossing_risk():
    locations = load_locations()
    frames = build_synthetic_frames("Moderate", [item.location_id for item in locations])
    baseline = calculate_replay_payloads(frames, 2, locations, DEFAULT_RESOURCES)[-1]
    observation = {
        "observation_id": "unlocated-integration-test",
        "location_id": None,
        "observed_at": frames[2]["timestamp"],
        "analysis_status": "success",
        "visible_flooding": "yes",
        "road_obstructed": "yes",
        "debris_visible": "yes",
        "visual_severity": 3,
        "evidence": ["Test fixture"],
        "uncertainties": [],
        "model_reported_evidence_strength": 1,
        "provenance": "model_observation",
        "source_name": "test",
    }
    with_unlocated = calculate_replay_payloads(
        frames, 2, locations, DEFAULT_RESOURCES, [observation]
    )[-1]
    assert [item["risk_score"] for item in baseline["risk_assessments"]] == [
        item["risk_score"] for item in with_unlocated["risk_assessments"]
    ]
    assert with_unlocated["input_context"]["unlocated_visual_count"] == 1


def test_streamlit_dashboard_starts_with_key_controls():
    streamlit = pytest.importorskip("streamlit")
    from streamlit.testing.v1 import AppTest

    app = AppTest.from_file(str(ROOT / "frontend" / "dashboard.py")).run(timeout=30)
    assert not app.exception
    assert app.title[0].value == "FloodShift · Storm Operations"
    button_labels = {item.label for item in app.button}
    assert "▶ Start Storm Simulation" in button_labels
    assert "▶ Resume" in button_labels
    assert "Check Qwen availability" in button_labels
    assert "Add labeled synthetic visual event to selected crossing" in button_labels
    assert app.select_slider
    assert app.radio[0].value == "Simulated Storm"
    assert app.session_state["synthetic_scenario"] == "Flash Flood"
    assert any("What Changed?" in item.value for item in app.subheader)

    next_button = next(item for item in app.button if item.label == "Step →")
    app = next_button.click().run(timeout=30)
    assert app.select_slider[1].value == 1
    assert any("Assessment +10 min" in item.value for item in app.caption)
