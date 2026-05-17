from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field

from .models import (
    CaptureScope,
    HarnessActionEvidence,
    HarnessPageState,
    HarnessRuntimeResult,
    HarnessStepCheckpoint,
    RecordingMode,
    RuntimeStatus,
)
from .expected_signals import build_expected_signal_draft
from .store import HarnessAssetStore


class HarnessCaptureSessionState(BaseModel):
    capture_id: str = Field(default_factory=lambda: f"hcap-{uuid4().hex}")
    session_id: str
    capture_scope: CaptureScope
    selected_step_indexes: list[int] = Field(default_factory=list)
    pending_natural_language_step_captures: int = 0
    started_at: datetime = Field(default_factory=datetime.now)
    status: Literal["active", "stopped"] = "active"

    def mark_step_selected(self, step_index: int) -> None:
        if self.capture_scope != "selected_steps":
            return
        if step_index not in self.selected_step_indexes:
            self.selected_step_indexes.append(step_index)
            self.selected_step_indexes.sort()

    def mark_next_natural_language_step_selected(self) -> None:
        if self.capture_scope != "selected_steps":
            return
        self.pending_natural_language_step_captures = 1

    def consume_natural_language_step_selection(self, step_index: int) -> None:
        if step_index in self.selected_step_indexes:
            return
        if self.pending_natural_language_step_captures > 0:
            self.pending_natural_language_step_captures -= 1

    def should_capture_step(self, step_index: int) -> bool:
        if self.capture_scope == "full_sop":
            return True
        return step_index in self.selected_step_indexes or self.pending_natural_language_step_captures > 0


class HarnessCapturedPageState(BaseModel):
    url: str = ""
    title: str = ""
    html: str = ""


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _relative_step_path(step_index: int, filename: str) -> str:
    return f"steps/{step_index:03d}/{filename}"


async def _capture_page_state(
    page,
    store: HarnessAssetStore,
    capture_id: str,
    step_index: int,
    filename: str,
    *,
    html_override: str | None = None,
    same_as_before: bool = False,
) -> HarnessPageState:
    title = await page.title()
    html = html_override if html_override is not None else await page.content()
    html_sha256 = _sha256_text(html)
    html_path = _relative_step_path(step_index, filename)
    if not same_as_before:
        store.write_text(store.capture_dir(capture_id) / html_path, html)
    return HarnessPageState(
        url=str(getattr(page, "url", "") or ""),
        title=str(title or ""),
        html_path=html_path,
        html_sha256=html_sha256,
        same_as_before=same_as_before,
    )


async def capture_current_page_state(page) -> HarnessCapturedPageState:
    return HarnessCapturedPageState(
        url=str(getattr(page, "url", "") or ""),
        title=str(await page.title() or ""),
        html=str(await page.content() or ""),
    )


def _write_captured_page_state(
    captured: HarnessCapturedPageState,
    store: HarnessAssetStore,
    capture_id: str,
    step_index: int,
    filename: str,
    *,
    same_as_before: bool = False,
) -> HarnessPageState:
    html_path = _relative_step_path(step_index, filename)
    if not same_as_before:
        store.write_text(store.capture_dir(capture_id) / html_path, captured.html)
    return HarnessPageState(
        url=captured.url,
        title=captured.title,
        html_path=html_path,
        html_sha256=_sha256_text(captured.html),
        same_as_before=same_as_before,
    )


async def capture_step_checkpoint(
    state: HarnessCaptureSessionState,
    store: HarnessAssetStore,
    *,
    step_index: int,
    step_id: str,
    step_intent: str,
    recording_mode: RecordingMode,
    before_page=None,
    after_page=None,
    before_state: HarnessCapturedPageState | None = None,
    after_state: HarnessCapturedPageState | None = None,
    trace_events: list[dict],
    runtime_status: RuntimeStatus,
    error: str | None = None,
) -> HarnessStepCheckpoint | None:
    if not state.should_capture_step(step_index):
        return None

    step_dir = store.step_dir(state.capture_id, step_index)
    if before_state is None:
        if before_page is None:
            raise ValueError("harness checkpoint capture requires before_page or before_state")
        before_state = await capture_current_page_state(before_page)
    before = _write_captured_page_state(before_state, store, state.capture_id, step_index, "before.html")

    store.write_json(step_dir / "trace_events.json", trace_events)

    after = None
    if runtime_status == "success":
        if after_state is None:
            if after_page is None:
                raise ValueError("successful harness checkpoint capture requires after_page or after_state")
            after_state = await capture_current_page_state(after_page)
        same_as_before = _sha256_text(after_state.html) == before.html_sha256
        after = _write_captured_page_state(
            after_state,
            store,
            state.capture_id,
            step_index,
            "before.html" if same_as_before else "after.html",
            same_as_before=same_as_before,
        )

    failure_path = ""
    if runtime_status == "failed":
        failure_path = _relative_step_path(step_index, "failure.json")
        store.write_json(
            step_dir / "failure.json",
            {
                "error": error or "",
                "captured_at": datetime.now().isoformat(),
                "step_intent": step_intent,
            },
        )

    expected = build_expected_signal_draft(
        step_intent=step_intent,
        recording_mode=recording_mode,
        trace_events=trace_events,
    )
    expected_path = _relative_step_path(step_index, "expected.json")
    store.write_json(step_dir / "expected.json", expected.model_dump(mode="json"))

    checkpoint = HarnessStepCheckpoint(
        step_index=step_index,
        step_id=step_id,
        step_intent=step_intent,
        recording_mode=recording_mode,
        before=before,
        action=HarnessActionEvidence(
            trace_events_path=_relative_step_path(step_index, "trace_events.json"),
        ),
        after=after,
        runtime_result=HarnessRuntimeResult(status=runtime_status, error=error),
        captured_at=datetime.now(),
        expected_path=expected_path,
        failure_path=failure_path,
    )
    store.write_json(step_dir / "checkpoint.json", checkpoint.model_dump(mode="json"))
    return checkpoint
