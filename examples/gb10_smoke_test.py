"""Compatibility wrapper for endpoint health checks and optional image inference.

The backend now uses the organizer's environment-configured shared server; it does
not require a local GB10 deployment.
"""

from __future__ import annotations

import argparse
import json

from floodshift.vision import QwenVisionClient


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--image", help="Optional PNG/JPEG/WebP flood photograph")
    parser.add_argument("--location-id", help="Supply only when location is verified")
    parser.add_argument("--observed-at", help="ISO timestamp supplied with the image")
    args = parser.parse_args()

    client = QwenVisionClient()
    print(json.dumps(client.healthcheck(), indent=2))
    if args.image:
        result = client.analyze(
            args.image,
            {"location_id": args.location_id, "observed_at": args.observed_at},
        )
        print(json.dumps(result.model_dump(mode="json"), indent=2))


if __name__ == "__main__":
    main()

