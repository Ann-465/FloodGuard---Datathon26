"""Run the complete two-step FloodShift storm demonstration."""

from __future__ import annotations

import json
from pathlib import Path

from floodshift.evaluation import compare_ranking_baselines
from floodshift.infrastructure import load_locations
from floodshift.pipeline import process_storm_update


HERE = Path(__file__).resolve().parent


def main() -> None:
    scenario = json.loads((HERE / "storm_scenario.json").read_text(encoding="utf-8"))
    locations = load_locations()
    previous = []
    results = []
    for step in scenario["steps"]:
        rainfall = [
            {
                **item,
                "timestamp": step["timestamp"],
                "provenance": "synthetic_demo",
                "source_name": "Illustrative storm replay",
            }
            for item in step["rainfall"]
        ]
        result = process_storm_update(
            rainfall,
            step["observations"],
            scenario["resources"],
            locations=locations,
            previous_assessments=previous,
        )
        results.append(result)
        previous = result.risk_assessments

    last_step = scenario["steps"][-1]
    final_rainfall = [
        {
            **item,
            "timestamp": last_step["timestamp"],
            "provenance": "synthetic_demo",
            "source_name": "Illustrative storm replay",
        }
        for item in last_step["rainfall"]
    ]
    evaluation = compare_ranking_baselines(
        locations,
        final_rainfall,
        last_step["observations"],
        scenario["scenario_relevance"],
        k=3,
    )
    payload = {
        "scenario": scenario["scenario_name"],
        "data_policy": scenario["data_policy"],
        "storm_updates": [item.model_dump(mode="json") for item in results],
        "baseline_evaluation": evaluation,
    }
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()

