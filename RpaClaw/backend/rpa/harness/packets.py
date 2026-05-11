from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Literal, Optional
from uuid import uuid4

from pydantic import BaseModel, Field


class RPAHarnessStage(str, Enum):
    RECORDING = "recording"
    SNAPSHOT = "snapshot"
    PLANNER = "planner"
    EXECUTION = "execution"
    REPAIR = "repair"
    COMPILE = "compile"
    REPLAY = "replay"


class RPAHarnessArtifactRef(BaseModel):
    artifact_id: str = Field(default_factory=lambda: f"artifact-{uuid4().hex}")
    path: str
    media_type: str = "application/json"
    redacted: bool = True
    sha256: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class RPAHarnessPageState(BaseModel):
    url: str = ""
    title: str = ""
    snapshot_summary: Dict[str, Any] = Field(default_factory=dict)


class RPAHarnessRedactionPolicy(BaseModel):
    enabled: bool = True
    replacement: str = "<redacted>"
    sensitive_keys: List[str] = Field(
        default_factory=lambda: [
            "access_token",
            "api_key",
            "authorization",
            "cookie",
            "email",
            "password",
            "secret",
            "token",
        ]
    )


class ObservationPacket(BaseModel):
    packet_kind: Literal["observation"] = "observation"
    packet_id: str = Field(default_factory=lambda: f"obs-{uuid4().hex}")
    session_id: str
    step_id: Optional[str] = None
    stage: RPAHarnessStage
    user_instruction: Optional[str] = None
    started_at: Optional[datetime] = None
    ended_at: Optional[datetime] = None
    before_page: RPAHarnessPageState = Field(default_factory=RPAHarnessPageState)
    after_page: RPAHarnessPageState = Field(default_factory=RPAHarnessPageState)
    raw_snapshot_ref: Optional[RPAHarnessArtifactRef] = None
    compact_snapshot_ref: Optional[RPAHarnessArtifactRef] = None
    accepted_trace_ref: Optional[RPAHarnessArtifactRef] = None
    generated_code_ref: Optional[RPAHarnessArtifactRef] = None
    compiler_output_ref: Optional[RPAHarnessArtifactRef] = None
    execution_result: Dict[str, Any] = Field(default_factory=dict)
    diagnostics: Dict[str, Any] = Field(default_factory=dict)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=datetime.now)


class FailurePacket(BaseModel):
    packet_kind: Literal["failure"] = "failure"
    packet_id: str = Field(default_factory=lambda: f"fail-{uuid4().hex}")
    session_id: str
    step_id: Optional[str] = None
    stage: RPAHarnessStage
    failure_type: str
    user_instruction: Optional[str] = None
    current_url: str = ""
    current_title: str = ""
    failed_plan_summary: Optional[str] = None
    raw_error_ref: Optional[RPAHarnessArtifactRef] = None
    failed_code_ref: Optional[RPAHarnessArtifactRef] = None
    snapshot_after_failure_ref: Optional[RPAHarnessArtifactRef] = None
    compact_snapshot_ref: Optional[RPAHarnessArtifactRef] = None
    repair_input_ref: Optional[RPAHarnessArtifactRef] = None
    repair_output_ref: Optional[RPAHarnessArtifactRef] = None
    attempt_trace_ref: Optional[RPAHarnessArtifactRef] = None
    accepted_trace_ref: Optional[RPAHarnessArtifactRef] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=datetime.now)
