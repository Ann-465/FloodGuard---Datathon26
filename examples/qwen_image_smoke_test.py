"""Verify real structured image inference against the configured Qwen server."""

from __future__ import annotations

import argparse
import json

from floodshift.schemas import AnalysisStatus
from floodshift.vision import QwenVisionClient


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("image", help="PNG/JPEG/WebP photograph to analyze")
    parser.add_argument("--location-id", help="Only supply when geolocation is independently verified")
    parser.add_argument("--observed-at", help="ISO timestamp supplied with the photograph")
    args = parser.parse_args()

    client = QwenVisionClient()
    print(json.dumps({"healthcheck": client.healthcheck()}, indent=2))
    result = client.analyze(
        args.image,
        {"location_id": args.location_id, "observed_at": args.observed_at},
    )
    print(json.dumps({"visual_observation": result.model_dump(mode="json")}, indent=2))
    if result.analysis_status != AnalysisStatus.SUCCESS:
        raise SystemExit("Image inference failed; inspect visual_observation.uncertainties above")
    if result.location_id is not None and not args.location_id:
        raise SystemExit("Safety failure: the model inferred a location that was not supplied")


if __name__ == "__main__":
    main()
