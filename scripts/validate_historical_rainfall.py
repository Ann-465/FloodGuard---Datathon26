"""Evaluate real Bexar County rainfall signals against OpenFEMA NFIP claim dates."""

from __future__ import annotations

import csv
import json
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "real"


def parse_precip(value: str | None) -> float | None:
    if value is None or value.strip() in {"", "T"}:
        return 0.0 if value and value.strip() == "T" else None
    try:
        return max(0.0, float(value))
    except ValueError:
        return None


def total_paid(row: dict[str, str]) -> float:
    return sum(float(row.get(field) or 0) for field in (
        "amountPaidOnBuildingClaim", "amountPaidOnContentsClaim"
    ))


def auc(labels: list[int], scores: list[float]) -> float:
    positives = [score for label, score in zip(labels, scores) if label]
    negatives = [score for label, score in zip(labels, scores) if not label]
    if not positives or not negatives:
        return 0.0
    wins = 0.0
    for positive in positives:
        for negative in negatives:
            wins += 1.0 if positive > negative else (0.5 if positive == negative else 0.0)
    return wins / (len(positives) * len(negatives))


def precision_at_n(labels: list[int], scores: list[float], n: int) -> float:
    order = sorted(range(len(scores)), key=lambda index: (-scores[index], index))[:n]
    return sum(labels[index] for index in order) / n if n else 0.0


def signal_metrics(labels: list[int], scores: list[float]) -> dict[str, float]:
    positive_count = sum(labels)
    return {
        "roc_auc": round(auc(labels, scores), 4),
        "precision_at_positive_count": round(
            precision_at_n(labels, scores, positive_count), 4
        ),
    }


def main() -> None:
    by_day: dict[date, list[float]] = defaultdict(list)
    with (DATA / "noaa_bexar_daily_precip_2018_2025.csv").open(encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            amount = parse_precip(row.get("PRCP"))
            if amount is not None:
                by_day[date.fromisoformat(row["DATE"][:10])].append(amount)

    claims_by_day: dict[date, list[dict[str, str]]] = defaultdict(list)
    with (DATA / "fema_bexar_nfip_claims_2018_2025.csv").open(encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            # Unpaid records can include denied/closed reports and are retained in
            # the raw file, but the outcome label requires a positive claim payment.
            if total_paid(row) > 0:
                claims_by_day[date.fromisoformat(row["dateOfLoss"][:10])].append(row)

    dates = sorted(day for day in by_day if date(2018, 1, 8) <= day <= date(2025, 12, 31))
    labels: list[int] = []
    max_daily: list[float] = []
    airport_daily: list[float] = []
    antecedent: list[float] = []
    daily_max_by_date = {day: max(values) for day, values in by_day.items() if values}
    airport_by_date: dict[date, float] = {}
    with (DATA / "noaa_bexar_daily_precip_2018_2025.csv").open(encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            if row.get("STATION") == "USW00012921":
                amount = parse_precip(row.get("PRCP"))
                if amount is not None:
                    airport_by_date[date.fromisoformat(row["DATE"][:10])] = amount
    for day in dates:
        today = daily_max_by_date.get(day, 0.0)
        previous_3d = sum(daily_max_by_date.get(day - timedelta(days=offset), 0.0) for offset in range(3))
        previous_7d = sum(daily_max_by_date.get(day - timedelta(days=offset), 0.0) for offset in range(7))
        labels.append(int(day in claims_by_day))
        max_daily.append(today)
        airport_daily.append(airport_by_date.get(day, 0.0))
        # Fixed before evaluation: current rain dominates; antecedent wetness adds context.
        antecedent.append(0.65 * min(today / 100.0, 1.0) + 0.25 * min(previous_3d / 180.0, 1.0) + 0.10 * min(previous_7d / 300.0, 1.0))

    event_count = sum(labels)
    paid_claim_count = sum(len(items) for items in claims_by_day.values())
    paid_amount = sum(total_paid(row) for items in claims_by_day.values() for row in items)
    train_mask = [day <= date(2022, 12, 31) for day in dates]
    test_mask = [day >= date(2023, 1, 1) for day in dates]

    def subset(values: list[float], mask: list[bool]) -> list[float]:
        return [value for value, keep in zip(values, mask) if keep]

    train_labels = subset(labels, train_mask)
    test_labels = subset(labels, test_mask)
    report = {
        "scope": "Bexar County day-level rainfall signal vs paid NFIP claim dates, 2018-2025",
        "days": len(dates),
        "positive_claim_days": event_count,
        "paid_claims": paid_claim_count,
        "paid_claim_amount_usd": round(paid_amount, 2),
        "metrics_all_dates": {
            "airport_only_daily_rainfall": signal_metrics(labels, airport_daily),
            "multi_gauge_daily_max": signal_metrics(labels, max_daily),
            "multi_gauge_antecedent_aware": signal_metrics(labels, antecedent),
        },
        "temporal_holdout": {
            "development_2018_2022": {
                "days": len(train_labels),
                "positive_claim_days": sum(train_labels),
                "multi_gauge_antecedent_aware": signal_metrics(
                    train_labels, subset(antecedent, train_mask)
                ),
            },
            "holdout_2023_2025": {
                "days": len(test_labels),
                "positive_claim_days": sum(test_labels),
                "multi_gauge_antecedent_aware": signal_metrics(
                    test_labels, subset(antecedent, test_mask)
                ),
            },
        },
        "claim_day_mean_max_rain_mm": round(
            sum(score for label, score in zip(labels, max_daily) if label) / event_count, 2
        ) if event_count else None,
        "non_event_day_mean_max_rain_mm": round(
            sum(score for label, score in zip(labels, max_daily) if not label) / (len(labels) - event_count), 2
        ) if len(labels) > event_count else None,
        "limitations": [
            "NFIP claims represent insured properties and do not capture every flood impact.",
            "The claims are county/day outcomes and do not identify which crossing flooded.",
            "Gauge coverage varies by day and can miss localized rainfall.",
            "This validates rainfall signal only, not the complete intervention policy.",
        ],
    }
    (DATA / "historical_validation.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()

