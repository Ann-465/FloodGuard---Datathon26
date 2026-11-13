from floodshift.risk import evaluate_flood_risk

from conftest import rainfall, visual


def test_risk_increases_with_rainfall(location):
    low = evaluate_flood_risk([location], [rainfall("loc-1", 5, 10, 20)])[0]
    high = evaluate_flood_risk([location], [rainfall("loc-1", 45, 90, 180)])[0]
    assert high.risk_score > low.risk_score
    assert high.component_scores["rainfall"] > low.component_scores["rainfall"]


def test_location_verified_visual_evidence_changes_risk(location):
    rain = rainfall("loc-1", 20, 40, 60)
    without = evaluate_flood_risk([location], [rain])[0]
    with_visual = evaluate_flood_risk([location], [rain], [visual("loc-1")])[0]
    wrong_location = evaluate_flood_risk([location], [rain], [visual("houston-image")])[0]
    assert with_visual.risk_score > without.risk_score
    assert wrong_location.risk_score == without.risk_score
    assert "road_obstructed" in with_visual.triggers


def test_missing_data_reduces_confidence(location):
    complete = evaluate_flood_risk(
        [location], [rainfall("loc-1", 20, 40, 60)], [visual("loc-1")]
    )[0]
    missing = evaluate_flood_risk([location], [])[0]
    assert missing.confidence < complete.confidence
    assert "missing_rainfall" in missing.triggers


def test_score_breakdown_is_bounded(location):
    result = evaluate_flood_risk(
        [location], [rainfall("loc-1", 500, 1000, 2000)], [visual("loc-1")]
    )[0]
    assert 0 <= result.risk_score <= 100
    assert result.component_scores["rainfall"] <= 45
    assert result.component_scores["infrastructure"] <= 30
    assert result.component_scores["visual_observation"] <= 25

