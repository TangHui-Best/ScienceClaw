from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field

from .models import (
    CaptureScope,
    HarnessActionEvidence,
    HarnessPageState,
    HarnessRuntimeResult,
    HarnessScenarioAsset,
    HarnessScenarioSource,
    HarnessStepCheckpoint,
    HarnessStepCheckpointRef,
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
    capture_quality: dict = Field(default_factory=dict)


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _relative_step_path(step_index: int, filename: str) -> str:
    return f"steps/{step_index:03d}/{filename}"


def _body_text_chars_from_html(html: str) -> int:
    text = re.sub(r"<[^>]+>", " ", html or "")
    return len(re.sub(r"\s+", " ", text).strip())


def _html_bytes(html: str) -> int:
    return len((html or "").encode("utf-8"))


def _is_shell_like_sample(*, title: str, html: str, body_text_chars: int) -> bool:
    return not html.strip() or (
        not title.strip()
        and _html_bytes(html) < 50_000
        and body_text_chars < 80
    )


async def _safe_document_ready_state(page) -> str:
    evaluate = getattr(page, "evaluate", None)
    if not callable(evaluate):
        return ""
    try:
        return str(await evaluate("document.readyState") or "")
    except Exception:
        return ""


def _quality_for_sample(
    *,
    status: str,
    reason: str,
    attempts: int,
    settle_ms: int,
    url: str,
    title: str,
    html: str,
    body_text_chars: int,
    ready_state: str,
    url_stable: bool,
    title_stable: bool,
    html_stable: bool,
) -> dict:
    return {
        "status": status,
        "reason": reason,
        "attempts": attempts,
        "settle_ms": settle_ms,
        "url": url,
        "html_bytes": _html_bytes(html),
        "body_text_chars": body_text_chars,
        "title_present": bool(title.strip()),
        "ready_state": ready_state,
        "url_stable": url_stable,
        "title_stable": title_stable,
        "html_stable": html_stable,
        "shell_like": _is_shell_like_sample(title=title, html=html, body_text_chars=body_text_chars),
    }


async def _capture_stable_page_state(
    page,
    *,
    attempts: int = 10,
    delay_ms: int = 200,
) -> HarnessCapturedPageState:
    previous: HarnessCapturedPageState | None = None
    best: HarnessCapturedPageState | None = None
    best_score = -1
    max_attempts = max(1, attempts)

    for attempt in range(max_attempts):
        url = str(getattr(page, "url", "") or "")
        title = str(await page.title() or "")
        html = str(await page.content() or "")
        ready_state = await _safe_document_ready_state(page)
        body_text_chars = _body_text_chars_from_html(html)
        url_stable = previous is not None and previous.url == url
        title_stable = previous is not None and previous.title == title
        previous_bytes = _html_bytes(previous.html) if previous is not None else 0
        current_bytes = _html_bytes(html)
        html_stable = (
            previous is not None
            and previous_bytes > 0
            and abs(current_bytes - previous_bytes) <= max(128, int(current_bytes * 0.02))
        )
        shell_like = _is_shell_like_sample(title=title, html=html, body_text_chars=body_text_chars)
        quality = _quality_for_sample(
            status="partial",
            reason="sampling",
            attempts=attempt + 1,
            settle_ms=attempt * delay_ms,
            url=url,
            title=title,
            html=html,
            body_text_chars=body_text_chars,
            ready_state=ready_state,
            url_stable=url_stable,
            title_stable=title_stable,
            html_stable=html_stable,
        )
        sample = HarnessCapturedPageState(url=url, title=title, html=html, capture_quality=quality)
        score = current_bytes + body_text_chars * 10 + (50_000 if title.strip() else 0) - (100_000 if shell_like else 0)
        if best is None or score > best_score:
            best = sample
            best_score = score
        if not shell_like and url_stable and title_stable and html_stable:
            sample.capture_quality = _quality_for_sample(
                status="stable",
                reason="",
                attempts=attempt + 1,
                settle_ms=attempt * delay_ms,
                url=url,
                title=title,
                html=html,
                body_text_chars=body_text_chars,
                ready_state=ready_state,
                url_stable=url_stable,
                title_stable=title_stable,
                html_stable=html_stable,
            )
            return sample

        previous = sample
        if attempt < max_attempts - 1:
            wait_for_timeout = getattr(page, "wait_for_timeout", None)
            if callable(wait_for_timeout):
                await wait_for_timeout(delay_ms)

    assert best is not None
    best_quality = dict(best.capture_quality)
    best_quality["status"] = "partial"
    best_quality["reason"] = "shell_like_after_capture" if best_quality.get("shell_like") else "timeout_before_stable"
    best_quality["attempts"] = max_attempts
    best_quality["settle_ms"] = max(0, (max_attempts - 1) * delay_ms)
    best.capture_quality = best_quality
    return best


def _load_or_create_scenario_manifest(
    state: HarnessCaptureSessionState,
    store: HarnessAssetStore,
) -> HarnessScenarioAsset:
    scenario_path = store.capture_dir(state.capture_id) / "scenario.json"
    if scenario_path.exists():
        try:
            return HarnessScenarioAsset.model_validate(json.loads(scenario_path.read_text(encoding="utf-8")))
        except Exception as exc:
            raise ValueError(f"Invalid harness scenario manifest: {scenario_path}") from exc

    return HarnessScenarioAsset(
        asset_id=state.capture_id,
        capture_scope=state.capture_scope,
        source=HarnessScenarioSource(
            recording_id=state.session_id,
            captured_at=state.started_at.isoformat(),
            capture_mode="harness",
            capture_trigger=state.capture_scope,
        ),
    )


def _write_scenario_manifest(
    state: HarnessCaptureSessionState,
    store: HarnessAssetStore,
    checkpoint: HarnessStepCheckpoint,
    scenario: HarnessScenarioAsset,
) -> None:
    refs: dict[int, HarnessStepCheckpointRef] = {}
    for item in scenario.step_checkpoints:
        ref = item if isinstance(item, HarnessStepCheckpointRef) else HarnessStepCheckpointRef.model_validate(item)
        refs[ref.step_index] = ref
    refs[checkpoint.step_index] = HarnessStepCheckpointRef(
        step_index=checkpoint.step_index,
        checkpoint_path=_relative_step_path(checkpoint.step_index, "checkpoint.json"),
    )
    scenario.step_checkpoints = [refs[index] for index in sorted(refs)]
    scenario.page_patterns = sorted({*scenario.page_patterns, *checkpoint.page_patterns})
    store.write_json(
        store.capture_dir(state.capture_id) / "scenario.json",
        scenario.model_dump(mode="json"),
    )


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
    captured = (
        HarnessCapturedPageState(
            url=str(getattr(page, "url", "") or ""),
            title=str(await page.title() or ""),
            html=html_override,
            capture_quality={"status": "provided"},
        )
        if html_override is not None
        else await _capture_stable_page_state(page)
    )
    html = captured.html
    html_sha256 = _sha256_text(html)
    html_path = _relative_step_path(step_index, filename)
    if not same_as_before:
        store.write_text(store.capture_dir(capture_id) / html_path, html)
    return HarnessPageState(
        url=captured.url,
        title=captured.title,
        html_path=html_path,
        html_sha256=html_sha256,
        same_as_before=same_as_before,
        capture_quality=captured.capture_quality,
    )


async def capture_current_page_state(page) -> HarnessCapturedPageState:
    return await _capture_stable_page_state(page)


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
        capture_quality=captured.capture_quality,
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
    scenario = _load_or_create_scenario_manifest(state, store)

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
    _write_scenario_manifest(state, store, checkpoint, scenario)
    return checkpoint
