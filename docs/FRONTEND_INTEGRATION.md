# Frontend integration contract

The dashboard should call one stable function and retain the prior assessment list
between replay frames:

```python
from floodshift import process_dashboard_update

payload = process_dashboard_update(
    rainfall=current_frame["rainfall"],
    observations=location_verified_visual_observations,
    resources={
        "inspection_teams": 2,
        "debris_crews": 1,
        "traffic_units": 1,
        "emergency_units": 1,
        "human_reviewers": 2,
    },
    previous_assessments=st.session_state.get("previous_assessments", []),
)
st.session_state["previous_assessments"] = payload["risk_assessments"]
```

`payload` is JSON-safe and contains:

- `risk_assessments`: map markers/ranking, score, severity, component scores,
  confidence, evidence, uncertainties, triggers, and score delta.
- `recommendations`: ranked actions with rationale, required resource,
  allocated/deferred status, and human-approval flag.
- `resources`, `warnings`, `evaluated_at`, `update_id`, and methodology version.

## Historical replay fixture

Load `data/real/replay_2023-04-20.json`. Each item in `steps` already provides the
exact `rainfall` list accepted above. The fixture contains 27 real NOAA hourly frames
and four nearest-gauge assignments. Its county NFIP claims are evaluation context
only and must not be displayed as crossing-specific outcomes.

```python
import json
from pathlib import Path

replay = json.loads(Path("data/real/replay_2023-04-20.json").read_text())
current_frame = replay["steps"][step_index]
```

## Image handoff

Call `analyze_flood_image(path, metadata)` before the dashboard update. Supply
`location_id` only when independently verified; an unlocated result may be shown in
an evidence panel but the risk engine will exclude it from location scores.

```python
from floodshift import analyze_flood_image

observation = analyze_flood_image(uploaded_path, metadata={})
location_verified_visual_observations = [observation.model_dump(mode="json")]
```

If inference is unavailable, the observation returns `analysis_status: fallback`
with an uncertainty message. The deterministic rainfall/infrastructure pipeline
continues operating.
