from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, model_validator


CaptureScope = Literal["full_sop", "selected_steps"]
AssetStatus = Literal["draft", "active", "flaky", "archived", "superseded"]
Sensitivity = Literal["local-only", "sanitized", "repo-safe", "sensitive"]
RuntimeStatus = Literal["success", "failed", "skipped"]
RecordingMode = Literal["natural_language", "manual", "unknown"]
PromotionStatus = Literal["captured", "candidate", "golden", "rejected"]
RunnerMode = Literal["offline_core_chain", "skill_replay_e2e"]
CoreChainCoverage = Literal[
    "html_to_raw_snapshot",
    "raw_to_compact_snapshot",
    "planner_action_selection",
    "trace_to_skill",
    "skill_replay",
]


class HarnessPageState(BaseModel):
    url: str = ""
    title: str = ""
    html_path: str = ""
    html_sha256: str = ""
    same_as_before: bool = False
    capture_quality: Dict[str, Any] = Field(default_factory=dict)
    screenshot_path: str = ""
    raw_snapshot_path: str = ""
    compact_snapshot_path: str = ""
    active_page_id: str = ""
    iframe_metadata: List[Dict[str, Any]] = Field(default_factory=list)


class HarnessActionEvidence(BaseModel):
    trace_events_path: str = ""
    expected_action_type: str = ""
    target_evidence: Dict[str, Any] = Field(default_factory=dict)


class HarnessRuntimeResult(BaseModel):
    status: RuntimeStatus
    error: Optional[str] = None


class HarnessExpectedSignals(BaseModel):
    snapshot_signals: Dict[str, Any] = Field(default_factory=dict)
    action_signals: Dict[str, Any] = Field(default_factory=dict)
    compiler_signals: Dict[str, Any] = Field(default_factory=dict)
    state_signals: Dict[str, Any] = Field(default_factory=dict)


class HarnessStepCheckpoint(BaseModel):
    step_index: int
    step_id: str = ""
    step_intent: str
    recording_mode: RecordingMode = "unknown"
    page_patterns: List[str] = Field(default_factory=list)
    captured_at: datetime = Field(default_factory=datetime.now)
    before: HarnessPageState
    action: HarnessActionEvidence
    after: Optional[HarnessPageState] = None
    runtime_result: HarnessRuntimeResult
    expected_path: str = ""
    failure_path: str = ""

    @model_validator(mode="after")
    def _success_requires_after_state(self) -> "HarnessStepCheckpoint":
        if self.runtime_result.status == "success" and self.after is None:
            raise ValueError("successful harness checkpoints require after state")
        return self


class HarnessStepCheckpointRef(BaseModel):
    step_index: int
    checkpoint_path: str


class HarnessScenarioGovernance(BaseModel):
    promotion_status: PromotionStatus = "captured"
    runner_modes: List[RunnerMode] = Field(default_factory=lambda: ["offline_core_chain"])
    core_chain_coverage: List[CoreChainCoverage] = Field(default_factory=list)
    expected_signals_reviewed: bool = False
    sensitivity_reviewed: bool = False
    review_notes: str = ""


class HarnessScenarioSource(BaseModel):
    recording_id: str = ""
    captured_at: str
    capture_mode: str = "harness"
    capture_trigger: str = ""


class HarnessScenarioAsset(BaseModel):
    schema_version: str = "rpa-harness-scenario-v0"
    asset_id: str
    capture_scope: CaptureScope
    sop_intent: str = ""
    source: HarnessScenarioSource | Dict[str, Any]
    environment: Dict[str, Any] = Field(default_factory=dict)
    asset_status: AssetStatus = "draft"
    sensitivity: Sensitivity = "local-only"
    page_patterns: List[str] = Field(default_factory=list)
    governance: HarnessScenarioGovernance = Field(default_factory=HarnessScenarioGovernance)
    step_checkpoints: List[HarnessStepCheckpointRef | Dict[str, Any]] = Field(default_factory=list)

