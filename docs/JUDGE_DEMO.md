# FloodShift 60-second judge demonstration

## Start

```powershell
conda activate floodshift
python -m pip install -e ".[dashboard]"
python -m streamlit run frontend/dashboard.py
```

## Demonstration sequence

1. Choose **Simulated Storm → Flash Flood**, then press Play or step to `+30 min`.
   Point out that the eight colored crossings use real mapped infrastructure and
   every score is calculated by the backend. Gray catalog crossings are unscored.
2. Select the highest-ranked crossing. Show its rainfall, infrastructure, and
   visual component chart, evidence, uncertainty, and risk trend.
3. Click **Add labeled synthetic visual event to selected crossing**. Explain that
   this is explicitly synthetic, geographically matched scenario evidence. The
   backend recalculates risk, ranking, proposed allocation, and the brief.
4. Reduce **Traffic units** or **Human reviewers** to zero. Show an action moving to
   Deferred and the **Proposed Reallocation** notice. No actual crew movement or
   closure is claimed.
5. Optionally upload the public-domain FEMA flood image. Leave the verification box
   unchecked so Qwen's result appears as unlocated evidence and does not change a
   San Antonio risk score.
6. Show the refreshed **FloodShift Incident Command Brief**, then switch to
   **Historical NOAA Replay** to establish that all 27 real rainfall frames are also
   supported.

The centerpiece is the decision change: new, labeled evidence or fewer resources
changes what the system proposes officials review next—not merely the visual score.
