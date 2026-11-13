from pathlib import Path

from floodshift.schemas import AnalysisStatus, EvidenceValue
from floodshift.vision import QwenVisionClient, analyze_flood_image


def test_missing_image_returns_fallback_not_exception(tmp_path: Path):
    result = analyze_flood_image(tmp_path / "missing.jpg", {"location_id": "loc-1"})
    assert result.analysis_status == AnalysisStatus.FALLBACK
    assert result.visible_flooding == EvidenceValue.UNCERTAIN
    assert result.location_id == "loc-1"


def test_valid_json_is_schema_validated(monkeypatch, tmp_path: Path):
    image = tmp_path / "photo.jpg"
    image.write_bytes(b"not-decoded-because-request-is-mocked")
    client = QwenVisionClient()
    monkeypatch.setattr(
        client,
        "_request",
        lambda path, metadata: """```json
        {"visible_flooding":"yes","road_obstructed":"uncertain","debris_visible":"no",
        "visual_severity":2,"evidence":["Water covers normally dry pavement"],
        "uncertainties":["Road edge is partially obscured"],
        "model_reported_evidence_strength":0.8}
        ```""",
    )
    result = client.analyze(image, {"location_id": "loc-1", "observed_at": "2026-11-13T12:00:00-06:00"})
    assert result.analysis_status == AnalysisStatus.SUCCESS
    assert result.location_id == "loc-1"
    assert result.model_reported_evidence_strength == 0.8


def test_location_is_never_inferred(monkeypatch, tmp_path: Path):
    image = tmp_path / "photo.jpg"
    image.write_bytes(b"fixture")
    client = QwenVisionClient()
    monkeypatch.setattr(
        client,
        "_request",
        lambda path, metadata: '{"visible_flooding":"no","road_obstructed":"no","debris_visible":"no","visual_severity":0,"evidence":[],"uncertainties":[],"model_reported_evidence_strength":0.7}',
    )
    assert client.analyze(image).location_id is None


def test_missing_server_configuration_returns_fallback(monkeypatch, tmp_path: Path):
    for name in ("FLOODSHIFT_VLM_BASE_URL", "FLOODSHIFT_VLM_MODEL", "FLOODSHIFT_VLM_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    image = tmp_path / "photo.jpg"
    image.write_bytes(b"fixture")
    result = QwenVisionClient().analyze(image)
    assert result.analysis_status == AnalysisStatus.FALLBACK
    assert "Missing Qwen configuration" in result.uncertainties[0]

