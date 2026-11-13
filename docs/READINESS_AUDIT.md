# FloodShift competition readiness audit

| Component | Implemented and verified | Data basis | Status and limit |
|---|---|---|---|
| Flood risk engine | Bounded rainfall, infrastructure, visual, freshness, provenance, confidence, trend, and coordinate outputs; unit and end-to-end tested | Real City of San Antonio crossing/assets; real NOAA and labeled replay inputs | **Verified as explainable prioritization.** Not a hydraulic depth or calibrated probability model. |
| Qwen visual analysis | Real organizer endpoint, schema validation, geographic guardrail, graceful fallback | Real non-flood image and public-domain FEMA Texas flooded-road smoke tests; synthetic located observation for integration | **Verified for live structured inference.** Population-level flood/debris accuracy still needs the labeled benchmark. |
| Adaptive response engine | Ranked actions, exact capacity-constrained allocation, deferred actions, human-approval flags | Controlled scenarios and backend assessments | **Verified for scenario allocation.** Not an actual dispatch system or validated intervention policy. |
| Storm replay compatibility | Previous-frame deltas, frame timestamps, real NOAA replay fixture, synthetic fixture | 27-frame NOAA replay plus two-frame illustrative storm | **Verified at backend contract level.** UI playback is teammate-owned. |
| Interactive dashboard integration | JSON-safe single-call contract, exact Streamlit wiring, map coordinates, allocated/deferred lists, brief payload | Backend integration tests and documented fixtures | **Partially verified.** Frontend branch is separate and was not overwritten; final UI connection remains teammate-owned. |
| Incident Command Brief | Deterministic structured/plain-text output, freshness, top threats, resource status, uncertainties, safety labels | Validated backend output | **Verified.** Decision-support draft only, not an official FEMA/ICS form. |

## Scientific interpretation

The implementation demonstrates that rainfall, real mapped infrastructure features,
and location-verified visual evidence can be fused into an explainable, changing
priority ranking and limited-resource recommendation. The illustrative scenario's
full multimodal ranking improves NDCG@3 (0.8786) over rainfall-only (0.6151) and
infrastructure-only (0.3975), but its urgent recall@3 (0.50) is below rainfall-only
(0.75). The historical rainfall signal reaches ROC-AUC 0.8867 overall and 0.8718 on
the 2023–2025 temporal holdout.

These results do not prove crossing-level flood forecasts, response effectiveness,
safe road passability, damage prevention, or real-world superiority. FEMA NFIP
claims are county/day insured-loss proxies. Operational deployment requires
geographically aligned outcomes, calibrated thresholds, field validation, secure
availability engineering, agency-approved procedures, and authorized humans making
consequential decisions.
