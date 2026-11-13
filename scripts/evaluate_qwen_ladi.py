"""Evaluate GB10 Qwen flood evidence on the labeled LADI-v2 test split.

LADI is aerial disaster imagery, not San Antonio crossing evidence. This script
measures visual classification behavior only and never assigns a location_id.
"""

from __future__ import annotations

import argparse
import json
import tempfile
import time
from pathlib import Path

from datasets import load_dataset

from floodshift.schemas import AnalysisStatus, EvidenceValue
from floodshift.vision import QwenVisionClient


ROOT = Path(__file__).resolve().parents[1]


def classification_metrics(labels: list[bool], predictions: list[EvidenceValue]) -> dict:
    evaluated = [
        (label, prediction == EvidenceValue.YES)
        for label, prediction in zip(labels, predictions)
        if prediction != EvidenceValue.UNCERTAIN
    ]
    tp = sum(label and predicted for label, predicted in evaluated)
    fp = sum(not label and predicted for label, predicted in evaluated)
    fn = sum(label and not predicted for label, predicted in evaluated)
    tn = sum(not label and not predicted for label, predicted in evaluated)
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        "samples": len(labels),
        "evaluated": len(evaluated),
        "coverage": round(len(evaluated) / len(labels), 4) if labels else 0.0,
        "accuracy": round((tp + tn) / len(evaluated), 4) if evaluated else 0.0,
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "confusion": {"tp": tp, "fp": fp, "fn": fn, "tn": tn},
    }


def balanced_flood_sample(sample_count: int):
    target_positive = sample_count // 2
    target_negative = sample_count - target_positive
    positives, negatives = [], []
    stream = load_dataset(
        "MITLL/LADI-v2-dataset",
        split="test",
        streaming=True,
    ).shuffle(seed=42, buffer_size=500)
    for row in stream:
        bucket = positives if bool(row["flooding_any"]) else negatives
        target = target_positive if bool(row["flooding_any"]) else target_negative
        if len(bucket) < target:
            bucket.append(row)
        if len(positives) >= target_positive and len(negatives) >= target_negative:
            break
    return positives + negatives


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--samples", type=int, default=20, help="Balanced flood/no-flood sample size")
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "data" / "real" / "qwen_ladi_evaluation.json",
    )
    args = parser.parse_args()
    if args.samples < 2:
        raise SystemExit("--samples must be at least 2")

    client = QwenVisionClient()
    health = client.healthcheck()
    rows = balanced_flood_sample(args.samples)
    results = []
    started = time.perf_counter()
    with tempfile.TemporaryDirectory(prefix="floodshift-ladi-") as temp_dir:
        temp = Path(temp_dir)
        for index, row in enumerate(rows):
            image_path = temp / f"ladi-{index:03d}.jpg"
            row["image"].convert("RGB").save(image_path, format="JPEG", quality=90)
            item_started = time.perf_counter()
            observation = client.analyze(
                image_path,
                {
                    "source_name": "MITLL/LADI-v2-dataset test split",
                    "observation_id": f"ladi-test-{index:03d}",
                },
            )
            if observation.analysis_status != AnalysisStatus.SUCCESS:
                raise RuntimeError(observation.uncertainties[0])
            results.append(
                {
                    "sample_index": index,
                    "labels": {
                        "flooding_any": bool(row["flooding_any"]),
                        "debris_any": bool(row["debris_any"]),
                    },
                    "predictions": {
                        "visible_flooding": observation.visible_flooding.value,
                        "debris_visible": observation.debris_visible.value,
                    },
                    "visual_severity": observation.visual_severity,
                    "evidence_strength": observation.model_reported_evidence_strength,
                    "latency_seconds": round(time.perf_counter() - item_started, 3),
                }
            )

    report = {
        "dataset": "MITLL/LADI-v2-dataset",
        "dataset_url": "https://huggingface.co/datasets/MITLL/LADI-v2-dataset",
        "license": "CC-BY-4.0",
        "split": "test (2023 distribution-shift events)",
        "sampling": "seeded balanced sample on flooding_any; seed=42",
        "model_health": health,
        "sample_count": len(results),
        "elapsed_seconds": round(time.perf_counter() - started, 3),
        "metrics": {
            "flooding_any": classification_metrics(
                [item["labels"]["flooding_any"] for item in results],
                [EvidenceValue(item["predictions"]["visible_flooding"]) for item in results],
            ),
            "debris_any": classification_metrics(
                [item["labels"]["debris_any"] for item in results],
                [EvidenceValue(item["predictions"]["debris_visible"]) for item in results],
            ),
        },
        "limitations": [
            "LADI contains aerial disaster imagery rather than street-level crossing photographs.",
            "This small balanced benchmark estimates visual classification behavior only.",
            "LADI images are not assigned to San Antonio locations or used as live observations.",
            "The road-obstructed output is not scored because LADI roads_damage is not equivalent.",
        ],
        "predictions": results,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({key: report[key] for key in ("sample_count", "elapsed_seconds", "metrics")}, indent=2))


if __name__ == "__main__":
    main()
