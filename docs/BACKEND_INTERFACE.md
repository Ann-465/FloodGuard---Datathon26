# FloodShift backend interface

All public inputs accept Pydantic objects or ordinary dictionaries. Outputs are
Pydantic models; use `model_dump(mode="json")` for the dashboard.

## 1. Analyze an image

```python
analyze_flood_image(image_path, metadata=None) -> VisualEvidence
```

Metadata is never inferred. Supply `location_id` only when the image is validly
matched to that location. An unlocated organizer image can still be evaluated but
will not affect a location-specific risk score.

Important output fields:

- `analysis_status`: `success` or `fallback`
- `visible_flooding`, `road_obstructed`, `debris_visible`
- `visual_severity`: ordinal 0-3
- `evidence`, `uncertainties`
- `model_reported_evidence_strength`: evidence clarity, not probability

## 2. Evaluate risk

```python
evaluate_flood_risk(
    locations,
    rainfall,
    observations=(),
    previous_assessments=(),
    evaluated_at=None,
) -> list[RiskAssessment]
```

Results are sorted highest-risk first and contain:

- `risk_score`, `severity`, and `rank`
- `component_scores`: rainfall /45, infrastructure /30, visual /25
- `confidence`
- `evidence`, `uncertainties`, and machine-readable `triggers`
- `data_provenance`
- `change_from_previous`

The bundled crossing records use real City asset counts and an explicitly named
`mapped_asset_density_proxy_v1`. The API states that this proxy is not measured
hydraulic capacity. A neutral `criticality` input avoids inventing traffic importance.

## 3. Recommend and allocate responses

```python
recommend_responses(risk_assessments, resources) -> list[ResponseRecommendation]
```

Resource fields:

```json
{
  "inspection_teams": 2,
  "debris_crews": 1,
  "traffic_units": 1,
  "emergency_units": 1,
  "human_reviewers": 2
}
```

The exact optimizer maximizes total candidate priority while enforcing every
capacity. Road-closure review and emergency prioritization consume both their
operational unit and a human reviewer. Unselected candidates remain visible with
`allocation_status: deferred_resource_limit`.

## 4. Process a complete storm update

```python
process_storm_update(
    rainfall,
    observations,
    resources,
    locations=None,
    previous_assessments=(),
    evaluated_at=None,
) -> StormUpdateResult
```

This is the preferred dashboard entry point. Persist the previous update's
`risk_assessments` and send them with the next storm step to obtain score deltas.

For Streamlit, use the JSON-safe wrapper:

```python
process_dashboard_update(...) -> dict
```

It accepts the same arguments and returns a plain dictionary. A complete copy/paste
example and historical replay instructions are in `docs/FRONTEND_INTEGRATION.md`.

## Geographic integrity rule

An observation changes a risk score only when its `location_id` exactly matches a
known location. The engine does not use filename, visual appearance, or model guesses
to assign geography.

## Error behavior

- Invalid contracts fail early with Pydantic validation errors.
- Qwen/provider/image errors return a `fallback` visual observation.
- Missing rainfall or imagery lowers confidence and adds explicit uncertainties.
- No AI response can directly authorize a road closure or emergency dispatch.
