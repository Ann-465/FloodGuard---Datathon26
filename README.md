# FloodShift AI

## Adaptive Flood Intelligence & Response

FloodShift is a full-stack decision-support prototype for the UTSA Dell Social Impact
AI Datathon. It combines changing rainfall conditions, drainage-infrastructure
features, and **location-verified** visual evidence to estimate evolving risk and
allocate limited response resources.

> Product hypothesis: Can a multimodal AI system combine flood imagery, rainfall
> conditions, and drainage infrastructure data to estimate evolving flood risks,
> detect emerging threats, and prioritize effective interventions before and during
> heavy rainfall?

Testable scenario hypothesis: combining rainfall, infrastructure, and
location-verified visual evidence improves limited-resource response prioritization
over rainfall-only and infrastructure-only rankings.

## What is implemented

- Explainable 0-100 risk scoring with separate rainfall (45), infrastructure (30),
  and visual-observation (25) components.
- Explicit uncertainty, data provenance, synthetic-input warnings, and confidence.
- Qwen3-VL-8B integration through the organizer's OpenAI-compatible shared endpoint.
- Strict image guardrails: no inferred location, time, depth, cause, or damage.
- Deterministic recommendations for verification, inspection, debris assessment,
  road-closure review, and emergency prioritization.
- Exact, dependency-free resource allocation under inspection, maintenance,
  traffic, emergency, and shared human-review constraints.
- Rainfall-only, infrastructure-only, and full multimodal comparisons using NDCG@K
  and urgent-location recall.
- Historical rainfall validation against real paid OpenFEMA NFIP flood claims, with
  an airport-only baseline and a 2023-2025 temporal holdout.
- Stable Pydantic/JSON contracts for the teammate's storm replay and dashboard.
- A deterministic Incident Command Brief with priority threats, resource status,
  unverified information, and a human-review safety boundary.
- Observation-freshness discounting, geographic coordinates, and input-freshness
  context in every dashboard update.
- A judge-ready Streamlit operations dashboard with 27-frame historical NOAA
  playback, three synthetic scenarios, resource controls, real Qwen upload,
  explainable maps/charts, proposed reallocations, and briefing download.
- Automated backend, integration, replay-unit, geographic-integrity, allocation,
  offline-fallback, and Streamlit-startup tests.

## Architecture

```text
Storm replay rainfall ─┐
Infrastructure data ───┼─> Risk engine ─> Response candidates ─> Resource optimizer
Qwen visual evidence ──┘       │                                      │
                               └─ score, provenance, uncertainty       └─ allocated/deferred actions
                                                │                                  │
                                                └──── Streamlit Storm Operations ──┘
```

## Quick start with Anaconda

```powershell
conda create -n floodshift python=3.11 pip -y
conda activate floodshift
python -m pip install -e ".[dev,dashboard]"
python -m pytest -q
python examples/run_demo.py
python -m streamlit run frontend/dashboard.py
```

The dashboard opens at `http://localhost:8501`. See
[`docs/JUDGE_DEMO.md`](docs/JUDGE_DEMO.md) for the one-minute demonstration.

## Shared Qwen3-VL inference

The competition organizer provides an OpenAI-compatible Qwen3-VL server. No local
GB10 deployment is required. Copy `.env.example` to the ignored `.env` file and set
the organizer-supplied URL, exact model identifier, and private API key there:

```powershell
Copy-Item .env.example .env
# Edit .env locally. Never commit or paste the private key into a notebook output.
python examples/qwen_image_smoke_test.py C:\path\to\flood-photo.jpg
```

The smoke test first checks `/v1/models`, then sends the real image and requires a
schema-valid observation. Omit `--location-id` unless the image's geography has been
independently verified. The expected output includes `visible_flooding`,
`road_obstructed`, `debris_visible`, ordinal severity, visible evidence, uncertainty,
and model-reported evidence strength.

Real organizer-server image inference was verified on 13 November 2026 with both a
local non-flood image and a public-domain
[FEMA Texas flooded-road photograph](https://commons.wikimedia.org/wiki/File:FEMA_-_37361_-_Flooded_road_in_Texas.jpg).
For the flood photograph, Qwen returned schema-valid `yes` observations for visible
flooding and road obstruction, `no` for debris, severity 3, and concrete supporting
evidence. Its location remained unset, so it did not update a San Antonio score.
These two smoke tests verify live structured inference and guardrails, not population-
level visual accuracy; use the optional LADI benchmark for a labeled estimate.

```python
from floodshift import analyze_flood_image

evidence = analyze_flood_image(
    "photo.jpg",
    {
        "location_id": "verified-location-id",
        "observed_at": "2026-11-13T13:05:00-06:00",
    },
)
print(evidence.model_dump(mode="json"))
```

Connection failures return a structured `fallback` observation and never crash the
deterministic risk and response pipeline.

After the image smoke test succeeds, run the optional labeled visual benchmark:

```bash
python -m pip install -e '.[vision-eval]'
python scripts/evaluate_qwen_ladi.py --samples 20
```

This evaluates flood/debris evidence on a seeded, balanced sample from MIT Lincoln
Laboratory's CC-BY-4.0 LADI-v2 test split. The 2023 test events intentionally differ
from its training distribution. The images are evaluation-only and are never mapped
to San Antonio locations.

## Backend integration

```python
from floodshift import process_dashboard_update

dashboard_payload = process_dashboard_update(
    rainfall=rainfall_updates,
    observations=visual_observations,
    resources={
        "inspection_teams": 2,
        "debris_crews": 1,
        "traffic_units": 1,
        "emergency_units": 1,
        "human_reviewers": 2,
    },
    locations=infrastructure_locations,
    previous_assessments=previous_payload["risk_assessments"] if previous_payload else [],
    evaluated_at=current_frame["timestamp"],
)
```

The returned dictionary includes `risk_assessments`, `recommendations`,
`input_context`, and `incident_brief` (both structured sections and `plain_text`).

See [`docs/BACKEND_INTERFACE.md`](docs/BACKEND_INTERFACE.md) for complete contracts.

## Data policy

Priority order:

1. Organizer-provided files, including `Texas_Flood_Student_Data` if supplied.
2. Sources explicitly linked by the organizers in `UTSA_more_data.md`.
3. Cited public data that fills a measurable gap, including NOAA weather and
   OpenFEMA historical flood-loss outcomes.
4. Clearly labeled synthetic storm inputs only for replay/demo states that have no
   contemporaneous observation.

The repository includes eight real City of San Antonio low-water-crossing identities
and coordinates from the organizer-linked Feature Service. It also includes real
counts of mapped storm inlets, underground-drainage segments, and channel segments
within 500 m of each crossing. A documented density formula converts these into an
explainable vulnerability proxy; it is not hydraulic capacity. Road criticality is
held at a neutral value until verified traffic or emergency-route data are added.
The infrastructure loader accepts JSON, GeoJSON, and ArcGIS FeatureServer output.

Historical Houston flood photographs may evaluate Qwen's visual-analysis behavior,
but **cannot update a San Antonio location** without valid matching location metadata.

Primary organizer-linked infrastructure sources include:

- [Low Water Crossings](https://opendata-cosagis.opendata.arcgis.com/datasets/4089adb69af14608acfb02703b1dd439_0/about)
- [Storm Inlets](https://opendata-cosagis.opendata.arcgis.com/datasets/CoSAGIS::storminlets/about)
- [Stormwater Underground](https://opendata-cosagis.opendata.arcgis.com/datasets/CoSAGIS::stormwaterunderground/about)
- [Storm Channels](https://opendata-cosagis.opendata.arcgis.com/datasets/CoSAGIS::stormchannels/about)
- [Manholes](https://opendata-cosagis.opendata.arcgis.com/datasets/CoSAGIS::manholes/about)
- [Outfalls](https://opendata-cosagis.opendata.arcgis.com/datasets/CoSAGIS::outfalls/about)
- [IMP Drainage](https://data.sanantonio.gov/dataset/imp-drainage)

## Evaluation

Run:

```powershell
python examples/run_demo.py
```

The bundled illustrative scenario currently produces this top-three comparison:

| Method | NDCG@3 | Urgent recall@3 | Interpretation |
|---|---:|---:|---|
| Rainfall only | 0.6151 | **0.75** | Strong urgent recall but weaker graded ranking |
| Infrastructure only | 0.3975 | 0.25 | Static asset density misses changing storm evidence |
| Full multimodal | **0.8786** | 0.50 | Best graded ranking; does not beat rainfall-only recall |

These values demonstrate behavior on a human-authored synthetic scenario. The full
system improves NDCG@3 but not urgent recall@3, so they do not establish calibrated
flood probability, operational safety, prevented damage, or real-world superiority.

### Real historical rainfall validation

Run:

```powershell
python scripts/fetch_real_data.py
python scripts/validate_historical_rainfall.py
python scripts/build_historical_replay.py
```

The committed 2018-2025 snapshot contains 9,905 NOAA daily precipitation records
from nine San Antonio-area gauges and 179 Bexar County NFIP claim records. Using only
the 107 claims with a positive payment yields 45 positive claim dates among 2,915
days.

| Rainfall signal | ROC-AUC | Precision at 45 |
|---|---:|---:|
| Airport-only daily rainfall | 0.7829 | 0.3556 |
| Multi-gauge daily maximum | 0.8634 | 0.4000 |
| Multi-gauge + antecedent wetness | **0.8867** | **0.4222** |

The fixed antecedent-aware signal retains ROC-AUC 0.8718 on the 2023-2025 temporal
holdout. This supports the rainfall-risk component and the value of local gauge
coverage. NFIP data covers insured-property losses, so this is not crossing-level
validation and does not validate the response optimizer.

`build_historical_replay.py` also produces dashboard-ready hourly rainfall for the
real 20 April 2023 San Antonio storm window. Each crossing is assigned to its nearest
available NOAA LCD station, with the gauge distance and Local Standard Time basis
preserved. The same date has paid Bexar County NFIP claims, but those claims are never
presented as crossing-specific outcomes.

## Limitations and safety boundary

- This is an explainable prioritization prototype, not a hydraulic flood model.
- Qwen evidence strength is model-reported and not a calibrated probability.
- A photograph cannot establish safe water depth, structural integrity, or causality.
- Road closures, debris operations, and emergency dispatch require authorized human
  review.
- Synthetic inputs are never presented as real observations.
- The scoring thresholds must be calibrated and validated before operational use.
- Real-world impact requires geographically aligned observations and outcome data.
- Public-data use was confirmed by the team; every external source remains cited and
  its geographic/temporal limitations are preserved.
