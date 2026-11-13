"""Historical and synthetic replay adapters for the FloodShift dashboard."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable


ROOT = Path(__file__).resolve().parents[1]
HISTORICAL_REPLAY_PATH = ROOT / "data" / "real" / "replay_2023-04-20.json"

SCENARIOS = {
    "Moderate": [0, 5, 10, 18, 22, 15, 8, 2],
    "Severe": [0, 10, 30, 50, 65, 75, 40, 15],
    "Flash Flood": [0, 5, 20, 70, 100, 90, 45, 10],
}

STEP_MINUTES = 10
SYNTHETIC_START = datetime(2026, 11, 13, 13, 0, tzinfo=timezone(timedelta(hours=-6)))


def get_storm_frame(scenario: str, step: int) -> dict:
    """Keep the teammate's original compact frame contract."""
    rates = SCENARIOS[scenario]
    if not 0 <= step < len(rates):
        raise ValueError("Invalid storm step")
    return {
        "step": step,
        "elapsed_minutes": step * STEP_MINUTES,
        "rainfall_mm_hr": float(rates[step]),
        "cumulative_rainfall_mm": round(
            sum(rates[: step + 1]) * STEP_MINUTES / 60,
            2,
        ),
        "source": "synthetic_replay",
    }


def _rolling_accumulation_mm(rates: list[float], step: int, hours: float) -> float:
    """Integrate piecewise-constant mm/h rates using the ten-minute frame duration."""
    window_steps = int(hours * 60 / STEP_MINUTES)
    first = max(0, step - window_steps + 1)
    return round(sum(rates[first : step + 1]) * STEP_MINUTES / 60, 3)


def build_synthetic_frames(
    scenario: str,
    location_ids: Iterable[str],
    *,
    start_at: datetime = SYNTHETIC_START,
) -> list[dict]:
    """Adapt the teammate's rates into valid per-location rainfall contracts.

    Every crossing receives the same explicitly simulated rate. Accumulations are
    rainfall depths calculated from the ten-minute time step; no spatial variation
    is fabricated.
    """
    rates = [float(value) for value in SCENARIOS[scenario]]
    identifiers = list(location_ids)
    frames: list[dict] = []
    for index, hourly_rate in enumerate(rates):
        timestamp = start_at + timedelta(minutes=index * STEP_MINUTES)
        previous_3h = _rolling_accumulation_mm(rates, index, 3)
        previous_24h = _rolling_accumulation_mm(rates, index, 24)
        rainfall = [
            {
                "location_id": location_id,
                "timestamp": timestamp.isoformat(),
                "hourly_mm": hourly_rate,
                "previous_3h_mm": previous_3h,
                "previous_24h_mm": previous_24h,
                "provenance": "synthetic_demo",
                "source_name": (
                    f"Uniform {scenario} simulated rainfall; {STEP_MINUTES}-minute steps"
                ),
            }
            for location_id in identifiers
        ]
        frames.append(
            {
                "step": index,
                "timestamp": timestamp.isoformat(),
                "elapsed_minutes": index * STEP_MINUTES,
                "label": f"+{index * STEP_MINUTES} min",
                "rainfall": rainfall,
                "source_label": "Simulated uniform rainfall",
                "mode_label": "Simulated Storm",
            }
        )
    return frames


def load_historical_frames(path: Path = HISTORICAL_REPLAY_PATH) -> tuple[list[dict], dict]:
    """Load all real NOAA frames without altering their records or timestamps."""
    document = json.loads(path.read_text(encoding="utf-8"))
    frames = []
    for index, item in enumerate(document["steps"]):
        frames.append(
            {
                **item,
                "step": index,
                "elapsed_minutes": index * 60,
                "label": datetime.fromisoformat(item["timestamp"]).strftime("%b %d, %I:%M %p"),
                "source_label": "NOAA hourly observations",
                "mode_label": "Historical NOAA Replay",
            }
        )
    metadata = {key: value for key, value in document.items() if key != "steps"}
    return frames, metadata


def rainfall_summary(frame: dict) -> dict[str, float]:
    """Return display statistics calculated from the active backend inputs."""
    rainfall = frame["rainfall"]
    return {
        "max_hourly_mm": max((item["hourly_mm"] for item in rainfall), default=0.0),
        "max_previous_3h_mm": max(
            (item["previous_3h_mm"] for item in rainfall), default=0.0
        ),
        "max_previous_24h_mm": max(
            (item["previous_24h_mm"] for item in rainfall), default=0.0
        ),
    }


if __name__ == "__main__":
    assert get_storm_frame("Severe", 4)["cumulative_rainfall_mm"] == 25.83
    example = build_synthetic_frames("Severe", ["one"])
    assert example[4]["rainfall"][0]["previous_3h_mm"] == 25.833
    print("Storm replay checks passed")
