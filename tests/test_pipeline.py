import json
from pathlib import Path

from floodshift.evaluation import compare_ranking_baselines
from floodshift.infrastructure import load_locations
from floodshift.pipeline import process_storm_update
from floodshift.pipeline import process_dashboard_update
from floodshift.schemas import RainfallCondition


ROOT = Path(__file__).resolve().parents[1]


def _scenario():
    return json.loads((ROOT / "examples" / "storm_scenario.json").read_text(encoding="utf-8"))


def _rainfall(step):
    return [
        {**item, "timestamp": step["timestamp"], "provenance": "synthetic_demo"}
        for item in step["rainfall"]
    ]


def test_end_to_end_pipeline_updates_rankings():
    scenario = _scenario()
    locations = load_locations()
    first = process_storm_update(
        _rainfall(scenario["steps"][0]), [], scenario["resources"], locations=locations
    )
    second = process_storm_update(
        _rainfall(scenario["steps"][1]),
        scenario["steps"][1]["observations"],
        scenario["resources"],
        locations=locations,
        previous_assessments=first.risk_assessments,
    )
    affected = next(item for item in second.risk_assessments if item.location_id == "LWC_7070194")
    assert affected.change_from_previous > 0
    assert affected.rank == 1
    assert second.recommendations
    assert second.model_dump(mode="json")["risk_assessments"]


def test_bundled_crossings_use_real_mapped_asset_features():
    locations = load_locations()
    assert all(item.provenance.value == "official_linked_external" for item in locations)
    assert all(item.is_low_water_crossing for item in locations)
    assert all(
        item.attributes["drainage_vulnerability_method"] == "mapped_asset_density_proxy_v1"
        for item in locations
    )
    assert all(item.nearby_inlet_count is not None for item in locations)
    assert all(item.criticality == 0.5 for item in locations)


def test_baseline_comparison_reports_measurable_metrics():
    scenario = _scenario()
    locations = load_locations()
    step = scenario["steps"][-1]
    result = compare_ranking_baselines(
        locations,
        _rainfall(step),
        step["observations"],
        scenario["scenario_relevance"],
        k=3,
    )
    assert set(result["methods"]) == {
        "rainfall_only",
        "infrastructure_only",
        "full_multimodal",
    }
    assert all(0 <= item["ndcg_at_k"] <= 1 for item in result["methods"].values())


def test_historical_replay_uses_valid_real_rainfall_contracts():
    payload = json.loads(
        (ROOT / "data" / "real" / "replay_2023-04-20.json").read_text(encoding="utf-8")
    )
    rainfall = [
        RainfallCondition.model_validate(item)
        for step in payload["steps"]
        for item in step["rainfall"]
    ]
    assert len(rainfall) == 216
    assert all(item.provenance.value == "additional_external" for item in rainfall)
    assert payload["county_outcome_context"]["paid_claim_count"] == 3
    assert "not crossing-level" in payload["county_outcome_context"]["warning"]


def test_dashboard_adapter_returns_json_safe_contract():
    scenario = _scenario()
    payload = process_dashboard_update(
        _rainfall(scenario["steps"][0]),
        [],
        scenario["resources"],
        locations=load_locations(),
    )
    assert isinstance(payload["evaluated_at"], str)
    assert payload["risk_assessments"]
    assert payload["recommendations"]
    assert payload["input_context"]["rainfall_location_count"] == 8
    assert payload["incident_brief"]["plain_text"]

