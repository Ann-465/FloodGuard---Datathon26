"""Qwen3-VL adapter that converts visible evidence into a guarded schema."""

from __future__ import annotations

import base64
import hashlib
import json
import mimetypes
import os
import re
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from .schemas import AnalysisStatus, EvidenceValue, Provenance, VisualEvidence


SYSTEM_PROMPT = """You analyze flood photographs for a decision-support prototype.
Use only visible pixels and metadata explicitly supplied by the user. Never infer a
location, date, water depth, cause, monetary damage, or road-safety authorization.
Ordinary rivers and ponds alone are not evidence that normally dry land is flooded.
Return one JSON object only, with exactly these keys:
visible_flooding, road_obstructed, debris_visible (yes/no/uncertain);
visual_severity (integer 0-3); evidence (short list of visible facts);
uncertainties (short list); model_reported_evidence_strength (0-1).
The strength value describes how clearly the pixels support the observations. It is
not a calibrated probability. When evidence is ambiguous, use uncertain."""


class _ModelOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    visible_flooding: EvidenceValue
    road_obstructed: EvidenceValue
    debris_visible: EvidenceValue
    visual_severity: int = Field(ge=0, le=3)
    evidence: list[str]
    uncertainties: list[str]
    model_reported_evidence_strength: float = Field(ge=0, le=1)


def _image_data_url(path: Path) -> str:
    mime = mimetypes.guess_type(path.name)[0]
    if mime not in {"image/png", "image/jpeg", "image/webp"}:
        raise ValueError(f"Unsupported image type: {path.suffix}")
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{encoded}"


def _extract_json(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    fenced = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", cleaned, flags=re.DOTALL | re.IGNORECASE)
    if fenced:
        cleaned = fenced.group(1)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start < 0 or end <= start:
            raise
        return json.loads(cleaned[start : end + 1])


class QwenVisionClient:
    def __init__(
        self,
        *,
        base_url: str | None = None,
        model: str | None = None,
        api_key: str | None = None,
        timeout_seconds: float | None = None,
    ) -> None:
        from dotenv import load_dotenv

        load_dotenv()
        self.base_url = base_url or os.getenv("FLOODSHIFT_VLM_BASE_URL")
        self.model = model or os.getenv("FLOODSHIFT_VLM_MODEL")
        self.api_key = api_key or os.getenv("FLOODSHIFT_VLM_API_KEY")
        self.timeout_seconds = timeout_seconds or float(os.getenv("FLOODSHIFT_VLM_TIMEOUT_SECONDS", "120"))

    def _require_configuration(self) -> None:
        missing = [
            name
            for name, value in (
                ("FLOODSHIFT_VLM_BASE_URL", self.base_url),
                ("FLOODSHIFT_VLM_MODEL", self.model),
                ("FLOODSHIFT_VLM_API_KEY", self.api_key),
            )
            if not value
        ]
        if missing:
            raise RuntimeError("Missing Qwen configuration: " + ", ".join(missing))

    def healthcheck(self) -> dict[str, Any]:
        """Verify that the OpenAI-compatible endpoint exposes a model list."""
        from openai import OpenAI

        self._require_configuration()
        with OpenAI(
            base_url=self.base_url,
            api_key=self.api_key,
            timeout=min(self.timeout_seconds, 15),
            max_retries=0,
        ) as client:
            models = client.models.list()
        ids = [item.id for item in models.data]
        return {"available": True, "base_url": self.base_url, "models": ids, "configured_model": self.model}

    def _request(self, image_path: Path, metadata: dict[str, Any]) -> str:
        from openai import OpenAI

        self._require_configuration()
        safe_metadata = {
            key: metadata[key]
            for key in ("location_id", "observed_at", "source_name")
            if metadata.get(key) is not None
        }
        user_text = (
            "Analyze this photograph. Supplied metadata (do not add or infer fields): "
            + json.dumps(safe_metadata, default=str)
        )
        content = [
            {"type": "text", "text": user_text},
            {"type": "image_url", "image_url": {"url": _image_data_url(image_path)}},
        ]
        with OpenAI(
            base_url=self.base_url,
            api_key=self.api_key,
            timeout=self.timeout_seconds,
            max_retries=0,
        ) as client:
            response = client.chat.completions.create(
                model=self.model,
                temperature=0,
                top_p=0.8,
                max_tokens=450,
                extra_body={"top_k": 20, "chat_template_kwargs": {"enable_thinking": False}},
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": content},
                ],
            )
        answer = (response.choices[0].message.content or "").strip()
        if not answer:
            raise ValueError("Qwen returned an empty response")
        return answer

    def analyze(self, image_path: str | Path, metadata: dict[str, Any] | None = None) -> VisualEvidence:
        """Return validated evidence or a non-throwing fallback observation."""
        path = Path(image_path)
        supplied = dict(metadata or {})
        identifier_seed = str(path.resolve()).encode("utf-8", errors="replace")
        observation_id = str(supplied.get("observation_id") or f"visual-{hashlib.sha256(identifier_seed).hexdigest()[:12]}")
        common = {
            "observation_id": observation_id,
            "location_id": supplied.get("location_id"),
            "observed_at": supplied.get("observed_at"),
            "source_name": self.model or "unconfigured_vlm",
            "image_reference": path.name,
            "supplied_metadata": supplied,
        }
        try:
            if not path.is_file():
                raise FileNotFoundError(f"Image not found: {path}")
            parsed = _ModelOutput.model_validate(_extract_json(self._request(path, supplied)))
            return VisualEvidence(
                **common,
                analysis_status=AnalysisStatus.SUCCESS,
                provenance=Provenance.MODEL,
                **parsed.model_dump(),
            )
        except Exception as exc:  # boundary intentionally converts provider failures into data
            return VisualEvidence(
                **common,
                analysis_status=AnalysisStatus.FALLBACK,
                visible_flooding=EvidenceValue.UNCERTAIN,
                road_obstructed=EvidenceValue.UNCERTAIN,
                debris_visible=EvidenceValue.UNCERTAIN,
                visual_severity=0,
                evidence=[],
                uncertainties=[f"Visual analysis unavailable: {type(exc).__name__}: {exc}"],
                model_reported_evidence_strength=0,
                provenance=Provenance.MODEL,
            )


def analyze_flood_image(
    image_path: str | Path,
    metadata: dict[str, Any] | None = None,
    *,
    client: QwenVisionClient | None = None,
) -> VisualEvidence:
    """Convenience interface used by notebooks and the dashboard integration."""
    return (client or QwenVisionClient()).analyze(image_path, metadata)

