import streamlit as st
import pandas as pd
from pathlib import Path

from storm_replay import SCENARIOS, get_storm_frame

st.set_page_config(
    page_title="FloodShift AI",
    page_icon="🌊",
    layout="wide"
)

st.title("🌊 FloodShift AI")
st.caption("Adaptive Flood Intelligence & Response")
st.warning("Demonstration using synthetic rainfall, not live flood monitoring.")

# Storm controls
scenario = st.sidebar.selectbox(
    "Storm Scenario",
    list(SCENARIOS.keys())
)

step = st.sidebar.slider(
    "Storm Step",
    0,
    len(SCENARIOS[scenario]) - 1
)

frame = get_storm_frame(scenario, step)

# Rainfall metrics
col1, col2, col3 = st.columns(3)

col1.metric("Elapsed Time", f"{frame['elapsed_minutes']} min")
col2.metric("Rainfall Intensity", f"{frame['rainfall_mm_hr']} mm/h")
col3.metric("Cumulative Rainfall", f"{frame['cumulative_rainfall_mm']} mm")

# Load crossing locations
data_path = Path(__file__).resolve().parent.parent / "data" / "locations.csv"
locations = pd.read_csv(data_path)

st.subheader("San Antonio Low-Water Crossings")
st.map(locations, latitude="latitude", longitude="longitude")

st.write("Total mapped crossings:", len(locations))

# Rainfall progression
history = [
    get_storm_frame(scenario, i)
    for i in range(step + 1)
]

st.subheader("Rainfall Progression")
st.line_chart(
    pd.DataFrame(history),
    x="elapsed_minutes",
    y="rainfall_mm_hr"
)