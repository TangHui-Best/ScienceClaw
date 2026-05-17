from datetime import datetime

import pytest
from pydantic import ValidationError

from backend.rpa.harness.models import (
    HarnessActionEvidence,
    HarnessPageState,
    HarnessRuntimeResult,
    HarnessScenarioAsset,
    HarnessStepCheckpoint,
)


def _page_state() -> HarnessPageState:
    return HarnessPageState(
        url="https://example.test/search",
        title="Search",
        html_path="steps/001/before.html",
        html_sha256="abc123",
    )


def test_scenario_asset_defaults_to_local_draft_and_supports_full_sop_scope():
    asset = HarnessScenarioAsset(
        asset_id="asset-1",
        capture_scope="full_sop",
        source={"captured_at": datetime(2026, 5, 17).isoformat()},
        step_checkpoints=[],
    )

    assert asset.capture_scope == "full_sop"
    assert asset.asset_status == "draft"
    assert asset.sensitivity == "local-only"


def test_scenario_asset_supports_selected_steps_scope():
    asset = HarnessScenarioAsset(
        asset_id="asset-2",
        capture_scope="selected_steps",
        source={"captured_at": datetime(2026, 5, 17).isoformat()},
        step_checkpoints=[],
    )

    assert asset.capture_scope == "selected_steps"


def test_scenario_asset_rejects_unknown_capture_scope():
    with pytest.raises(ValidationError):
        HarnessScenarioAsset(
            asset_id="asset-3",
            capture_scope="page_capture",
            source={"captured_at": datetime(2026, 5, 17).isoformat()},
            step_checkpoints=[],
        )


def test_step_checkpoint_requires_intent_before_action_and_result():
    checkpoint = HarnessStepCheckpoint(
        step_index=1,
        step_id="step-001",
        step_intent="Click the ScienceClaw search result",
        recording_mode="natural_language",
        before=_page_state(),
        action=HarnessActionEvidence(
            trace_events_path="steps/001/trace_events.json",
            expected_action_type="click",
        ),
        after=HarnessPageState(
            url="https://example.test/project/scienceclaw",
            title="ScienceClaw",
            html_path="steps/001/after.html",
            html_sha256="def456",
        ),
        runtime_result=HarnessRuntimeResult(status="success"),
        captured_at=datetime(2026, 5, 17),
    )

    assert checkpoint.step_intent == "Click the ScienceClaw search result"
    assert checkpoint.runtime_result.status == "success"


def test_step_checkpoint_after_state_can_dedupe_before_html():
    checkpoint = HarnessStepCheckpoint(
        step_index=1,
        step_id="step-001",
        step_intent="Read the current project title",
        recording_mode="manual",
        before=_page_state(),
        action=HarnessActionEvidence(
            trace_events_path="steps/001/trace_events.json",
            expected_action_type="extract",
        ),
        after=HarnessPageState(
            url="https://example.test/search",
            title="Search",
            html_path="steps/001/before.html",
            html_sha256="abc123",
            same_as_before=True,
        ),
        runtime_result=HarnessRuntimeResult(status="success"),
        captured_at=datetime(2026, 5, 17),
    )

    assert checkpoint.after is not None
    assert checkpoint.after.same_as_before is True


def test_success_checkpoint_requires_after_state_or_dedupe_marker():
    with pytest.raises(ValidationError):
        HarnessStepCheckpoint(
            step_index=1,
            step_id="step-001",
            step_intent="Click the ScienceClaw search result",
            recording_mode="natural_language",
            before=_page_state(),
            action=HarnessActionEvidence(
                trace_events_path="steps/001/trace_events.json",
                expected_action_type="click",
            ),
            runtime_result=HarnessRuntimeResult(status="success"),
            captured_at=datetime(2026, 5, 17),
        )
