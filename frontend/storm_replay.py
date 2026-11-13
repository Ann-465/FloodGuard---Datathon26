"""Synthetic rainfall scenarios for the FloodShift demo."""

SCENARIOS = {
    "Moderate": [0, 5, 10, 18, 22, 15, 8, 2],
    "Severe": [0, 10, 30, 50, 65, 75, 40, 15],
    "Flash Flood": [0, 5, 20, 70, 100, 90, 45, 10],
}

STEP_MINUTES = 10


def get_storm_frame(scenario: str, step: int) -> dict:
    rates = SCENARIOS[scenario]

    if not 0 <= step < len(rates):
        raise ValueError("Invalid storm step")

    return {
        "step": step,
        "elapsed_minutes": step * STEP_MINUTES,
        "rainfall_mm_hr": float(rates[step]),
        "cumulative_rainfall_mm": round(
            sum(rates[:step + 1]) * STEP_MINUTES / 60,
            2,
        ),
        "source": "synthetic_replay",
    }


if __name__ == "__main__":
    assert get_storm_frame("Severe", 4)["rainfall_mm_hr"] == 65
    print("Storm replay checks passed")