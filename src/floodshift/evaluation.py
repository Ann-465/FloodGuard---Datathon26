"""Scenario-based ranking evaluation against transparent baselines."""

from __future__ import annotations

import math
from typing import Iterable, Mapping

from .risk import evaluate_flood_risk
from .schemas import Location, RainfallCondition, RiskAssessment, VisualEvidence


def _rank(items: list[RiskAssessment], component: str | None) -> list[str]:
    if component is None:
        key = lambda item: (-item.risk_score, item.location_id)
    else:
        key = lambda item: (-item.component_scores[component], item.location_id)
    return [item.location_id for item in sorted(items, key=key)]


def ndcg_at_k(ranking: list[str], relevance: Mapping[str, int | float], k: int) -> float:
    """Normalized discounted cumulative gain for a scenario's reviewed urgency labels."""
    def dcg(order: list[str]) -> float:
        return sum(
            (2 ** float(relevance.get(location_id, 0)) - 1) / math.log2(index + 2)
            for index, location_id in enumerate(order[:k])
        )

    ideal = sorted(relevance, key=lambda item: (-float(relevance[item]), item))
    denominator = dcg(ideal)
    return round(dcg(ranking) / denominator, 4) if denominator else 0.0


def urgent_recall_at_k(
    ranking: list[str], relevance: Mapping[str, int | float], k: int, threshold: float = 2
) -> float:
    urgent = {item for item, score in relevance.items() if float(score) >= threshold}
    if not urgent:
        return 0.0
    return round(len(urgent.intersection(ranking[:k])) / len(urgent), 4)


def compare_ranking_baselines(
    locations: Iterable[Location | dict],
    rainfall: Iterable[RainfallCondition | dict],
    observations: Iterable[VisualEvidence | dict],
    scenario_relevance: Mapping[str, int | float],
    *,
    k: int = 3,
) -> dict:
    """Compare rainfall-only, infrastructure-only, and full multimodal rankings.

    ``scenario_relevance`` must be a human-authored scenario label (0-3). Results
    demonstrate scenario prioritization only, not real-world damage reduction.
    """
    assessments = evaluate_flood_risk(locations, rainfall, observations)
    rankings = {
        "rainfall_only": _rank(assessments, "rainfall"),
        "infrastructure_only": _rank(assessments, "infrastructure"),
        "full_multimodal": _rank(assessments, None),
    }
    return {
        "scope": "illustrative scenario-based prioritization",
        "k": k,
        "methods": {
            name: {
                "ranking": ranking,
                "ndcg_at_k": ndcg_at_k(ranking, scenario_relevance, k),
                "urgent_recall_at_k": urgent_recall_at_k(ranking, scenario_relevance, k),
            }
            for name, ranking in rankings.items()
        },
        "limitation": "Scenario labels are not evidence of real-world flood prevention or damage reduction.",
    }

