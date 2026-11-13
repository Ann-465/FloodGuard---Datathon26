"""FloodShift AI emergency-operations dashboard."""

from __future__ import annotations

import hashlib
import tempfile
import time
from pathlib import Path

import pandas as pd
import pydeck as pdk
import streamlit as st

from floodshift import analyze_flood_image
from floodshift.infrastructure import load_locations
from floodshift.vision import QwenVisionClient
from frontend.operations import (
    DEFAULT_RESOURCES,
    allocation_changes,
    calculate_replay_payloads,
    catalog_partition,
)
from frontend.storm_replay import (
    SCENARIOS,
    build_synthetic_frames,
    load_historical_frames,
    rainfall_summary,
)


ROOT = Path(__file__).resolve().parents[1]
CATALOG_PATH = ROOT / "data" / "locations.csv"

SEVERITY_COLORS = {
    "low": [45, 199, 137, 220],
    "moderate": [245, 184, 65, 230],
    "high": [242, 116, 51, 235],
    "critical": [225, 54, 80, 245],
}


st.set_page_config(
    page_title="FloodShift Storm Operations",
    page_icon="🌊",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
    <style>
    .stApp { background: linear-gradient(145deg, #071521 0%, #0b2030 56%, #102838 100%); }
    [data-testid="stHeader"] { background: rgba(7, 21, 33, .75); }
    [data-testid="stSidebar"] { background: #071722; border-right: 1px solid #1e4054; }
    .block-container { padding-top: 1.3rem; padding-bottom: 3rem; max-width: 1600px; }
    h1, h2, h3 { letter-spacing: -0.02em; }
    div[data-testid="stMetric"] {
        background: linear-gradient(160deg, rgba(22, 52, 70, .96), rgba(11, 35, 50, .96));
        border: 1px solid #28546a; border-radius: 14px; padding: 12px 14px;
        box-shadow: 0 8px 24px rgba(0,0,0,.16);
    }
    div[data-testid="stMetricValue"] { color: #f4fbff; }
    .mode-badge {
        display:inline-block; padding:6px 11px; border-radius:999px;
        background:#123d52; color:#9ee6ff; border:1px solid #25647f;
        font-weight:700; font-size:.8rem; letter-spacing:.04em; text-transform:uppercase;
    }
    .ops-card {
        background:rgba(12, 38, 54, .96); border:1px solid #28546a;
        border-radius:14px; padding:16px; margin-bottom:12px;
    }
    .allocated { border-left:4px solid #2dc789; }
    .deferred { border-left:4px solid #f27433; }
    .muted { color:#9db4c1; }
    .tiny { font-size:.78rem; color:#9db4c1; }
    </style>
    """,
    unsafe_allow_html=True,
)


@st.cache_data(show_spinner=False)
def load_catalog() -> list[dict]:
    return pd.read_csv(CATALOG_PATH).to_dict(orient="records")


@st.cache_data(show_spinner=False)
def load_historical() -> tuple[list[dict], dict]:
    return load_historical_frames()


@st.cache_resource(show_spinner=False)
def scored_locations():
    return load_locations()


def reset_timeline() -> None:
    st.session_state.timeline_index = 0
    st.session_state.playing = False
    st.session_state.last_tick = time.monotonic()


def step_timeline(amount: int, maximum: int) -> None:
    st.session_state.timeline_index = min(
        maximum,
        max(0, st.session_state.timeline_index + amount),
    )


def resource_usage(recommendations: list[dict]) -> dict[str, int]:
    usage = {key: 0 for key in DEFAULT_RESOURCES}
    for item in recommendations:
        if item["allocation_status"] != "allocated" or not item["required_resource"]:
            continue
        for resource in item["required_resource"].split(" + "):
            usage[resource] = usage.get(resource, 0) + 1
    return usage


def display_recommendations(items: list[dict], empty_message: str) -> None:
    if not items:
        st.info(empty_message)
        return
    for item in items:
        state_class = "allocated" if item["allocation_status"] == "allocated" else "deferred"
        approval = "Human approval required" if item["human_approval_required"] else "Human review not required to queue"
        st.markdown(
            f"""
            <div class="ops-card {state_class}">
              <b>{item['location_name']}</b> · {item['action'].replace('_', ' ').title()}<br>
              <span class="muted">Priority {item['priority_score']:.1f} · {item['required_resource'] or 'No constrained resource'}</span><br>
              <span>{item['rationale']}</span><br>
              <span class="tiny">{approval} · Proposed scenario assignment only</span>
            </div>
            """,
            unsafe_allow_html=True,
        )


def build_map_rows(assessments: list[dict]) -> list[dict]:
    rows = []
    for item in assessments:
        change = item["change_from_previous"]
        arrow = "→" if change is None or abs(change) < 0.05 else ("↑" if change > 0 else "↓")
        rows.append(
            {
                **item,
                "fill_color": SEVERITY_COLORS[item["severity"]],
                "radius": 120 + item["risk_score"] * 4,
                "trend_label": f"{arrow} {change:+.1f}" if change is not None else "First frame",
                "score_label": f"{item['risk_score']:.1f}/100",
            }
        )
    return rows


def add_synthetic_evidence(location_id: str, timestamp: str) -> None:
    observation_id = hashlib.sha256(
        f"{location_id}|{timestamp}|illustrative".encode()
    ).hexdigest()[:12]
    observation = {
        "observation_id": f"synthetic-{observation_id}",
        "location_id": location_id,
        "observed_at": timestamp,
        "analysis_status": "success",
        "visible_flooding": "yes",
        "road_obstructed": "yes",
        "debris_visible": "uncertain",
        "visual_severity": 3,
        "evidence": [
            "Illustrative scenario input: water is shown covering the road surface",
            "Illustrative scenario input: vehicle passability cannot be confirmed",
        ],
        "uncertainties": [
            "Synthetic location-matched evidence used only for the judge demonstration"
        ],
        "model_reported_evidence_strength": 0.9,
        "provenance": "synthetic_demo",
        "source_name": "Explicitly labeled synthetic visual scenario",
        "image_reference": None,
        "supplied_metadata": {"demo_only": True, "location_verified": False},
    }
    existing = [
        item for item in st.session_state.visual_observations
        if item["observation_id"] != observation["observation_id"]
    ]
    st.session_state.visual_observations = existing + [observation]
    st.session_state.last_visual_result = observation


for key, value in {
    "timeline_index": 0,
    "playing": False,
    "last_tick": time.monotonic(),
    "visual_observations": [],
    "last_visual_result": None,
    "qwen_health": None,
}.items():
    if key not in st.session_state:
        st.session_state[key] = value


locations = scored_locations()
location_ids = [item.location_id for item in locations]
catalog = load_catalog()
catalog_scored, catalog_unscored = catalog_partition(catalog, locations)

st.sidebar.markdown("## Storm control")
mode = st.sidebar.radio(
    "Playback source",
    ["Historical NOAA Replay", "Simulated Storm"],
    key="playback_mode",
    on_change=reset_timeline,
)
scenario = None
historical_metadata = None
if mode == "Historical NOAA Replay":
    frames, historical_metadata = load_historical()
    st.sidebar.caption("27 real NOAA hourly frames · April 20–21, 2023")
else:
    scenario = st.sidebar.selectbox(
        "Simulated scenario",
        list(SCENARIOS),
        key="synthetic_scenario",
        on_change=reset_timeline,
    )
    frames = build_synthetic_frames(scenario, location_ids)
    st.sidebar.caption("Uniform simulated rainfall over real infrastructure")

maximum_frame = len(frames) - 1
st.session_state.timeline_index = min(st.session_state.timeline_index, maximum_frame)

st.sidebar.markdown("### Playback")
speed = st.sidebar.select_slider(
    "Playback speed",
    options=[0.5, 1.0, 1.5, 2.0, 3.0],
    value=1.0,
    format_func=lambda value: f"{value:g}×",
)
control_cols = st.sidebar.columns(4)
control_cols[0].button(
    "◀",
    help="Previous frame",
    width="stretch",
    on_click=step_timeline,
    args=(-1, maximum_frame),
)
if control_cols[1].button("▶" if not st.session_state.playing else "Ⅱ", width="stretch"):
    st.session_state.playing = not st.session_state.playing
    st.session_state.last_tick = time.monotonic()
control_cols[2].button(
    "▶|",
    help="Next frame",
    width="stretch",
    on_click=step_timeline,
    args=(1, maximum_frame),
)
control_cols[3].button("↺", help="Reset", width="stretch", on_click=reset_timeline)

st.sidebar.select_slider(
    "Timeline frame",
    options=list(range(len(frames))),
    key="timeline_index",
    format_func=lambda index: frames[index]["label"],
)
# Read the authoritative session value after rendering. Streamlit can return the
# preceding widget value during a button-triggered rerun even though the callback
# has already advanced the keyed state.
frame_index = st.session_state.timeline_index

if st.session_state.playing:
    interval = max(0.35, 1.5 / speed)

    @st.fragment(run_every=0.25)
    def playback_driver() -> None:
        elapsed = time.monotonic() - st.session_state.last_tick
        if elapsed < interval:
            return
        if st.session_state.timeline_index >= maximum_frame:
            st.session_state.playing = False
        else:
            st.session_state.timeline_index += 1
            st.session_state.last_tick = time.monotonic()
        st.rerun(scope="app")

    playback_driver()

st.sidebar.markdown("### Available scenario resources")
resources = {
    "inspection_teams": st.sidebar.number_input("Inspection teams", 0, 10, 2),
    "debris_crews": st.sidebar.number_input("Debris crews", 0, 10, 1),
    "traffic_units": st.sidebar.number_input("Traffic units", 0, 10, 1),
    "emergency_units": st.sidebar.number_input("Emergency units", 0, 10, 1),
    "human_reviewers": st.sidebar.number_input("Human reviewers", 0, 10, 2),
}

with st.spinner("Calculating risk and constrained response priorities…"):
    replay_payloads = calculate_replay_payloads(
        frames,
        frame_index,
        locations,
        resources,
        st.session_state.visual_observations,
    )
payload = replay_payloads[-1]
previous_payload = replay_payloads[-2] if len(replay_payloads) > 1 else None
frame = frames[frame_index]
assessments = payload["risk_assessments"]
recommendations = payload["recommendations"]
allocated = [item for item in recommendations if item["allocation_status"] == "allocated"]
deferred = [item for item in recommendations if item["allocation_status"] == "deferred_resource_limit"]
usage = resource_usage(recommendations)
rain = rainfall_summary(frame)

st.markdown(f'<span class="mode-badge">{mode}</span>', unsafe_allow_html=True)
st.title("FloodShift · Storm Operations")
st.caption(
    f"Assessment {frame['label']} · {frame['source_label']} · "
    "Estimated decision-support risk, not a calibrated flood probability"
)
if mode == "Historical NOAA Replay":
    st.info(
        "Historical playback of NOAA rainfall—not live monitoring. County NFIP claims are "
        "context only and are not attributed to individual crossings."
    )
else:
    st.warning(
        "Simulated storm over real San Antonio infrastructure. Rainfall is spatially uniform "
        "and no actual emergency or dispatch is represented."
    )

elevated = [item for item in assessments if item["severity"] in {"high", "critical"}]
increasing = [
    item for item in assessments
    if item["change_from_previous"] is not None and item["change_from_previous"] > 0.05
]
highest = max((item["risk_score"] for item in assessments), default=0)

kpis = st.columns(7)
kpis[0].metric("Scored crossings", len(assessments), help=f"{len(catalog_unscored)} catalog crossings are shown only when requested and are not scored")
kpis[1].metric("High / critical", len(elevated))
kpis[2].metric("Highest risk", f"{highest:.1f}/100")
kpis[3].metric("Increasing", len(increasing))
kpis[4].metric("Rainfall", f"{rain['max_hourly_mm']:.1f} mm/h")
kpis[5].metric("Allocated", len(allocated))
kpis[6].metric("Deferred", len(deferred))

left, right = st.columns([1.7, 1], gap="large")
with left:
    map_header, map_toggle = st.columns([3, 1])
    map_header.subheader("San Antonio crossing risk map")
    show_unscored = map_toggle.toggle(
        f"Show {len(catalog_unscored)} unscored",
        value=False,
        help="Catalog-only locations appear gray and never receive invented scores.",
    )
    map_rows = build_map_rows(assessments)
    layers = [
        pdk.Layer(
            "ScatterplotLayer",
            data=map_rows,
            get_position="[longitude, latitude]",
            get_fill_color="fill_color",
            get_radius="radius",
            pickable=True,
            stroked=True,
            get_line_color=[235, 248, 255, 230],
            line_width_min_pixels=1,
            radius_min_pixels=7,
            radius_max_pixels=22,
        )
    ]
    if show_unscored:
        layers.insert(
            0,
            pdk.Layer(
                "ScatterplotLayer",
                data=catalog_unscored,
                get_position="[longitude, latitude]",
                get_fill_color=[115, 129, 140, 90],
                get_radius=80,
                pickable=True,
                radius_min_pixels=3,
                radius_max_pixels=6,
            ),
        )
    st.pydeck_chart(
        pdk.Deck(
            layers=layers,
            initial_view_state=pdk.ViewState(
                latitude=29.45,
                longitude=-98.50,
                zoom=9.6,
                pitch=32,
            ),
            tooltip={
                "html": "<b>{location_name}</b><br/>Risk {score_label}<br/>{severity}<br/>{trend_label}",
                "style": {"backgroundColor": "#071722", "color": "white"},
            },
            map_style=None,
        ),
        width="stretch",
        height=500,
    )
    st.caption(
        f"Eight crossings have validated backend features. The remaining {len(catalog_unscored)} "
        "City catalog locations are unscored and optional; gray markers do not imply low risk."
    )

with right:
    st.subheader("Rainfall progression")
    rainfall_history = []
    for history_frame in frames[: frame_index + 1]:
        summary = rainfall_summary(history_frame)
        rainfall_history.append(
            {
                "Time": history_frame["label"],
                "Intensity (mm/h)": summary["max_hourly_mm"],
                "24h accumulation (mm)": summary["max_previous_24h_mm"],
            }
        )
    rain_df = pd.DataFrame(rainfall_history).set_index("Time")
    st.line_chart(rain_df, height=280, color=["#54d2ff", "#f5b841"])
    st.markdown("#### Scenario resource use")
    resource_df = pd.DataFrame(
        [
            {
                "Resource": key.replace("_", " ").title(),
                "Available": resources[key],
                "Proposed use": usage.get(key, 0),
            }
            for key in resources
        ]
    ).set_index("Resource")
    st.dataframe(resource_df, width="stretch")

ranked_names = [item["location_name"] for item in assessments]
selected_name = st.selectbox("Inspect a scored crossing", ranked_names)
selected = next(item for item in assessments if item["location_name"] == selected_name)
selected_id = selected["location_id"]

detail, actions = st.columns([1.25, 1], gap="large")
with detail:
    st.subheader("Explainable risk analysis")
    score_col, confidence_col, trend_col = st.columns(3)
    delta = selected["change_from_previous"]
    score_col.metric(
        "Estimated risk",
        f"{selected['risk_score']:.1f}/100",
        delta=f"{delta:+.1f}" if delta is not None else None,
    )
    confidence_col.metric("Evidence confidence", f"{selected['confidence']:.0%}")
    trend_col.metric("Current rank", f"#{selected['rank']}")

    components = pd.DataFrame(
        [
            {
                "Component": key.replace("_", " ").title(),
                "Points": value,
            }
            for key, value in selected["component_scores"].items()
        ]
    ).set_index("Component")
    st.bar_chart(components, height=220, color="#54d2ff")
    st.caption("Contributions are bounded points in an explainable score—not probabilities.")

    trend_rows = []
    for index, history_payload in enumerate(replay_payloads):
        item = next(
            assessment
            for assessment in history_payload["risk_assessments"]
            if assessment["location_id"] == selected_id
        )
        trend_rows.append(
            {"Time": frames[index]["label"], "Estimated risk score": item["risk_score"]}
        )
    st.line_chart(pd.DataFrame(trend_rows).set_index("Time"), height=210, color="#ef6f6c")
    with st.expander("Evidence and uncertainty", expanded=True):
        st.markdown("**Supporting evidence**")
        for line in selected["evidence"]:
            st.markdown(f"- {line}")
        st.markdown("**Uncertainties**")
        for line in selected["uncertainties"]:
            st.markdown(f"- {line}")

with actions:
    st.subheader("Emergency response prioritization")
    st.caption("Optimizer proposals only—no crew has been dispatched or road closed.")
    changes = allocation_changes(previous_payload, payload)
    if previous_payload and (changes["newly_allocated"] or changes["no_longer_allocated"]):
        st.warning(
            "Proposed Reallocation · "
            f"{len(changes['newly_allocated'])} newly allocated, "
            f"{len(changes['no_longer_allocated'])} no longer allocated since the previous frame."
        )
    selected_actions = [item for item in recommendations if item["location_id"] == selected_id]
    selected_allocated = [item for item in selected_actions if item["allocation_status"] == "allocated"]
    selected_deferred = [item for item in selected_actions if item["allocation_status"] != "allocated"]
    allocation_tab, deferred_tab, all_tab = st.tabs(
        [f"Allocated ({len(selected_allocated)})", f"Deferred ({len(selected_deferred)})", "All locations"]
    )
    with allocation_tab:
        display_recommendations(selected_allocated, "No resource was allocated to this crossing in the current scenario.")
    with deferred_tab:
        display_recommendations(selected_deferred, "No action is deferred for this crossing.")
    with all_tab:
        recommendation_table = pd.DataFrame(
            [
                {
                    "Ranked location": item["location_name"],
                    "Action": item["action"].replace("_", " "),
                    "Priority": item["priority_score"],
                    "Resource": item["required_resource"],
                    "Status": item["allocation_status"],
                    "Approval": item["human_approval_required"],
                }
                for item in recommendations
            ]
        )
        st.dataframe(recommendation_table, width="stretch", hide_index=True, height=360)

st.divider()
vision_col, brief_col = st.columns([1, 1.25], gap="large")
with vision_col:
    st.subheader("Qwen flood-image analysis")
    st.caption("Qwen runs only when an image is submitted; it does not run on replay frames.")
    health_col, clear_col = st.columns(2)
    if health_col.button("Check Qwen availability", width="stretch"):
        try:
            with st.spinner("Checking organizer endpoint…"):
                st.session_state.qwen_health = QwenVisionClient().healthcheck()
        except Exception as exc:
            st.session_state.qwen_health = {"available": False, "error": str(exc)}
    if clear_col.button("Clear visual evidence", width="stretch"):
        st.session_state.visual_observations = []
        st.session_state.last_visual_result = None
        st.rerun()
    if st.session_state.qwen_health:
        if st.session_state.qwen_health.get("available"):
            st.success(
                f"Organizer model available: {st.session_state.qwen_health['configured_model']}"
            )
        else:
            st.error(f"Qwen unavailable: {st.session_state.qwen_health.get('error', 'unknown error')}")

    with st.form("image_analysis_form"):
        upload = st.file_uploader("Flood photograph", type=["jpg", "jpeg", "png", "webp"])
        verified_match = st.checkbox(
            "I independently verified that this image belongs to the selected crossing",
            value=False,
        )
        submitted = st.form_submit_button("Analyze photograph", width="stretch")
    if submitted:
        if upload is None:
            st.error("Choose an image before submitting.")
        else:
            suffix = Path(upload.name).suffix.lower()
            temp_path = None
            try:
                with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as handle:
                    handle.write(upload.getbuffer())
                    temp_path = Path(handle.name)
                metadata = {
                    "observed_at": frame["timestamp"],
                    "source_name": "Dashboard image submission",
                }
                if verified_match:
                    metadata["location_id"] = selected_id
                with st.spinner("Qwen3-VL is examining visible flood evidence…"):
                    result = analyze_flood_image(temp_path, metadata)
                result_dict = result.model_dump(mode="json")
                st.session_state.visual_observations = [
                    item for item in st.session_state.visual_observations
                    if item["observation_id"] != result_dict["observation_id"]
                ] + [result_dict]
                st.session_state.last_visual_result = result_dict
                if result_dict["analysis_status"] == "success":
                    st.success("Schema-valid Qwen analysis received.")
                else:
                    st.warning("Qwen was unavailable; a structured fallback was preserved.")
                st.rerun()
            finally:
                if temp_path and temp_path.is_file():
                    temp_path.unlink()

    if st.button(
        "Add labeled synthetic visual event to selected crossing",
        help="Judge-demo evidence only; never represented as a real photograph.",
        width="stretch",
    ):
        add_synthetic_evidence(selected_id, frame["timestamp"])
        st.rerun()

    result = st.session_state.last_visual_result
    if result:
        label = "Location verified" if result.get("location_id") else "Unlocated evidence—excluded from crossing risk"
        st.markdown(f"**Latest result:** {label}")
        fields = st.columns(4)
        fields[0].metric("Flooding", result["visible_flooding"].title())
        fields[1].metric("Road", result["road_obstructed"].title())
        fields[2].metric("Debris", result["debris_visible"].title())
        fields[3].metric("Severity", f"{result['visual_severity']}/3")
        for line in result["evidence"]:
            st.markdown(f"- {line}")
        for line in result["uncertainties"]:
            st.warning(line)

with brief_col:
    st.subheader("FloodShift Incident Command Brief")
    st.caption("Deterministic decision-support draft · not an official FEMA or ICS form")
    brief = payload["incident_brief"]
    st.text_area(
        "Operational briefing",
        brief["plain_text"],
        height=520,
        label_visibility="collapsed",
    )
    st.download_button(
        "Download briefing as text",
        data=brief["plain_text"],
        file_name=f"floodshift-brief-{frame_index:02d}.txt",
        mime="text/plain",
        width="stretch",
    )

if payload["warnings"]:
    with st.expander("Active data warnings"):
        for warning in payload["warnings"]:
            st.warning(warning)

with st.expander("Model Evaluation & Limitations"):
    st.markdown(
        """
        **Historical county-level rainfall validation**

        - Overall ROC-AUC: **0.8867**
        - 2023–2025 temporal holdout ROC-AUC: **0.8718**

        This uses Bexar County NFIP paid-claim dates as an imperfect county/day proxy.
        It is not validation of flooding at an individual crossing.

        **Illustrative prioritization comparison**

        | Method | NDCG@3 | Urgent Recall@3 |
        |---|---:|---:|
        | Rainfall only | 0.6151 | **0.75** |
        | Infrastructure only | 0.3975 | 0.25 |
        | Multimodal | **0.8786** | 0.50 |

        The prioritization labels are scenario-based. Multimodal improves NDCG@3 but
        does not beat rainfall-only urgent recall@3. FloodShift is a research
        decision-support prototype—not a validated crossing-level prediction,
        hydraulic model, road-safety authorization, or automated dispatch system.
        """
    )
