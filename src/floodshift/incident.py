"""Deterministic, safety-bounded operational briefing generation."""

from __future__ import annotations

from collections import Counter
from hashlib import sha256

from .schemas import AllocationStatus, IncidentCommandBrief, Severity, StormUpdateResult


SAFETY_NOTICE = (
    "Decision-support draft; not an official FEMA or ICS form. Risk scores are estimates, "
    "resource allocations are scenario recommendations, and consequential actions require "
    "authorized human review."
)


def _trend(change: float | None) -> str:
    if change is None:
        return "no prior frame"
    if change > 1:
        return f"increasing (+{change:.1f})"
    if change < -1:
        return f"decreasing ({change:.1f})"
    return f"stable ({change:+.1f})"


def generate_incident_brief(
    dashboard_payload: StormUpdateResult | dict,
    *,
    top_n: int = 3,
) -> IncidentCommandBrief:
    """Convert validated backend output into a concise operational review draft."""
    if isinstance(dashboard_payload, dict):
        # ``process_dashboard_update`` already contains the generated brief. Strip
        # that derived field so callers can safely regenerate after display edits.
        dashboard_payload = {
            key: value for key, value in dashboard_payload.items() if key != "incident_brief"
        }
    result = StormUpdateResult.model_validate(dashboard_payload)
    context = result.input_context
    ranked = sorted(result.risk_assessments, key=lambda item: (item.rank or 999, -item.risk_score))
    priority = ranked[: max(1, top_n)]
    elevated = [item for item in ranked if item.severity in {Severity.MODERATE, Severity.HIGH, Severity.CRITICAL}]
    rising = [item for item in ranked if item.change_from_previous is not None and item.change_from_previous > 1]
    provenance = sorted(
        {
            item.value
            for assessment in ranked
            for item in assessment.data_provenance
        }
    )

    situation = {
        "assessment_timestamp": result.evaluated_at.isoformat(),
        "rainfall_observed_through": context.rainfall_observed_through.isoformat() if context.rainfall_observed_through else None,
        "latest_rainfall_age_minutes": context.latest_rainfall_age_minutes,
        "latest_visual_observed_at": (
            context.latest_visual_observed_at.isoformat()
            if context.latest_visual_observed_at
            else None
        ),
        "latest_visual_age_minutes": context.latest_visual_age_minutes,
        "rainfall_conditions": {
            "max_hourly_mm": context.max_hourly_mm,
            "max_previous_3h_mm": context.max_previous_3h_mm,
            "max_previous_24h_mm": context.max_previous_24h_mm,
        },
        "storm_trend": f"{len(rising)} assessed locations increasing" if rising else "no increasing location scores detected",
        "assessed_locations": len(ranked),
        "elevated_risk_locations": len(elevated),
        "input_labels": provenance or ["no assessed input provenance"],
        "synthetic_inputs_present": context.synthetic_inputs_present,
        "visual_observations": context.visual_observation_count,
    }

    threats = []
    for item in priority:
        triggers = set(item.triggers)
        passability = (
            "possible obstruction visible; passability still requires authorized field verification"
            if "road_obstructed" in triggers
            else "unverified"
        )
        threats.append(
            {
                "rank": item.rank,
                "location_id": item.location_id,
                "location_name": item.location_name,
                "latitude": item.latitude,
                "longitude": item.longitude,
                "risk_score": item.risk_score,
                "severity": item.severity.value,
                "trend": _trend(item.change_from_previous),
                "confidence": item.confidence,
                "supporting_evidence": item.evidence[:4],
                "uncertainties": item.uncertainties,
                "passability_status": passability,
            }
        )

    recommendations = sorted(
        result.recommendations,
        key=lambda item: (
            item.allocation_status != AllocationStatus.ALLOCATED,
            -item.priority_score,
            item.location_id,
        ),
    )
    actions = [
        {
            "location_id": item.location_id,
            "location_name": item.location_name,
            "action": item.action.value,
            "priority_score": item.priority_score,
            "rationale": item.rationale,
            "required_resource": item.required_resource,
            "allocation_status": item.allocation_status.value,
            "human_approval_required": item.human_approval_required,
        }
        for item in recommendations[:12]
    ]

    allocated = [item for item in recommendations if item.allocation_status == AllocationStatus.ALLOCATED]
    deferred = [item for item in recommendations if item.allocation_status == AllocationStatus.DEFERRED]
    shortages = Counter(item.required_resource or "unspecified" for item in deferred)
    resources = {
        "available": result.resources.model_dump(),
        "allocated_actions": len(allocated),
        "deferred_actions": len(deferred),
        "resource_shortages": dict(shortages),
        "human_approval_actions": sum(item.human_approval_required for item in recommendations),
        "allocation_label": "hypothetical scenario allocation; not a confirmed city deployment",
    }

    unverified = [
        "Water depth is unknown; image analysis does not estimate safe depth.",
        "No road closure, dispatch, or field operation is confirmed by this system.",
    ]
    if context.visual_observation_count == 0:
        unverified.append("No current visual observations were supplied.")
    elif context.latest_visual_age_minutes is None:
        unverified.append("Visual observation timestamps are unavailable.")
    elif context.latest_visual_age_minutes > 360:
        unverified.append(
            f"Latest visual observation is stale "
            f"({context.latest_visual_age_minutes:.0f} minutes old)."
        )
    if context.unlocated_visual_count:
        unverified.append(f"{context.unlocated_visual_count} image observation(s) lack verified location and were excluded from location risk.")
    if context.synthetic_inputs_present:
        unverified.append("One or more inputs are clearly labeled as synthetic demo data.")
    if context.latest_rainfall_age_minutes is None:
        unverified.append("No rainfall freshness timestamp is available.")
    elif context.latest_rainfall_age_minutes > 120:
        unverified.append(f"Latest rainfall input is stale ({context.latest_rainfall_age_minutes:.0f} minutes old).")
    for item in priority:
        unverified.extend(item.uncertainties)
    unverified = list(dict.fromkeys(unverified))

    first = priority[0] if priority else None
    if first:
        decision = (
            f"Review {first.location_name} first (risk {first.risk_score:.1f}, {first.severity.value}) "
            f"because it is the highest-ranked current assessment. {len(allocated)} action(s) fit the "
            f"available scenario resources and {len(deferred)} are deferred. Verify road and water "
            "conditions before any closure, dispatch, or field operation."
        )
    else:
        decision = "No locations were assessed. Supply rainfall and infrastructure inputs before prioritizing operations."

    lines = [
        "FLOODSHIFT INCIDENT COMMAND BRIEF",
        SAFETY_NOTICE,
        "",
        "SITUATION SUMMARY",
        f"Assessment: {result.evaluated_at.isoformat()} | Locations: {len(ranked)} | Elevated: {len(elevated)}",
        f"Storm trend: {situation['storm_trend']}",
        "",
        "PRIORITY THREATS",
    ]
    lines.extend(
        f"{item['rank']}. {item['location_name']} — risk {item['risk_score']:.1f} ({item['severity']}), {item['trend']}; passability {item['passability_status']}"
        for item in threats
    )
    lines.extend(["", "RECOMMENDED ACTIONS"])
    lines.extend(
        f"- {item['location_name']}: {item['action']} [{item['allocation_status']}]"
        for item in actions[:6]
    )
    lines.extend(["", "RESOURCE SITUATION", f"Allocated: {len(allocated)} | Deferred: {len(deferred)}", "", "UNVERIFIED INFORMATION"])
    lines.extend(f"- {item}" for item in unverified)
    lines.extend(["", "DECISION SUMMARY", decision])
    # A brief is a deterministic rendering of a validated storm update. Reusing
    # the assessment timestamp also prevents a regenerated brief from appearing
    # newer than its underlying evidence.
    generated = result.evaluated_at
    seed = result.update_id
    return IncidentCommandBrief(
        brief_id=f"brief-{sha256(seed.encode()).hexdigest()[:12]}",
        generated_at=generated,
        safety_notice=SAFETY_NOTICE,
        situation_summary=situation,
        priority_threats=threats,
        recommended_actions=actions,
        resource_situation=resources,
        unverified_information=unverified,
        decision_summary=decision,
        plain_text="\n".join(lines),
    )
