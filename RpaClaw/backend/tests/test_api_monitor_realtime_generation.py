import asyncio
import unittest
from datetime import datetime

from unittest.mock import patch

import pytest

from backend.rpa.api_monitor.models import (
    ApiMonitorSession,
    ApiToolDefinition,
    ApiToolGenerationCandidate,
)


def test_generation_candidate_defaults_are_serializable():
    candidate = ApiToolGenerationCandidate(
        session_id="session-1",
        dedup_key="GET /api/orders",
        method="GET",
        url_pattern="/api/orders",
    )

    dumped = candidate.model_dump(mode="json")

    assert dumped["status"] == "pending"
    assert dumped["source_call_ids"] == []
    assert dumped["sample_call_ids"] == []
    assert dumped["tool_id"] is None
    assert dumped["attempts"] == 0
    assert dumped["retry_after"] is None
    assert dumped["capture_dom_context"] == {}
    assert isinstance(dumped["created_at"], str)
    assert isinstance(dumped["updated_at"], str)


def test_session_contains_generation_candidates_by_default():
    session = ApiMonitorSession(
        user_id="user-1",
        sandbox_session_id="sandbox-1",
    )

    assert session.generation_candidates == []


def test_session_separates_generation_calls_from_evidence_calls():
    session = ApiMonitorSession(
        user_id="user-1",
        sandbox_session_id="sandbox-1",
        target_url="https://example.com",
    )
    evidence_call = _call("csrf-call", method="GET", path="/api/csrf")
    generation_call = _call("orders-call", method="GET", path="/api/orders")

    session.evidence_calls.append(evidence_call)
    session.captured_calls.append(generation_call)

    assert session.evidence_calls == [evidence_call]
    assert session.captured_calls == [generation_call]


def test_tool_definition_can_reference_generation_candidate():
    tool = ApiToolDefinition(
        session_id="session-1",
        name="list_orders",
        description="List orders",
        method="GET",
        url_pattern="/api/orders",
        yaml_definition="name: list_orders",
        generation_candidate_id="candidate-1",
    )

    assert tool.generation_candidate_id == "candidate-1"
    assert tool.model_dump(mode="json")["generation_candidate_id"] == "candidate-1"


# ── Upsert and reconcile helper tests ─────────────────────────────────────


from backend.rpa.api_monitor.manager import ApiMonitorSessionManager
from backend.rpa.api_monitor.models import CapturedApiCall, CapturedRequest, CapturedResponse


def _call(
    call_id: str,
    url: str | None = None,
    *,
    method: str = "GET",
    path: str | None = None,
) -> CapturedApiCall:
    if path is None:
        path = "/api/orders?page={page}"
        url = url or "https://example.com/api/orders?page=1"
    else:
        url = url or f"https://example.com{path}"
    url_pattern = path
    if url is not None and "?" in url and path == "/api/orders?page={page}":
        url_pattern = "/api/orders?page={page}"
    return CapturedApiCall(
        id=call_id,
        request=CapturedRequest(
            request_id=call_id,
            url=url,
            method=method,
            headers={},
            timestamp=datetime(2026, 1, 1),
            resource_type="fetch",
        ),
        response=CapturedResponse(
            status=200,
            status_text="OK",
            headers={"content-type": "application/json"},
            body='{"items":[{"id":1}]}',
            content_type="application/json",
            timestamp=datetime(2026, 1, 1),
        ),
        url_pattern=url_pattern,
    )


def _manager_with_session() -> tuple[ApiMonitorSessionManager, str]:
    manager = ApiMonitorSessionManager()
    session = ApiMonitorSession(
        id="session-1",
        user_id="user-1",
        sandbox_session_id="sandbox-1",
        target_url="https://example.com/app",
    )
    manager.sessions[session.id] = session
    return manager, session.id


async def _collect_events(generator):
    events = []
    async for event in generator:
        events.append(event)
    return events


def test_upsert_generation_candidate_creates_placeholder():
    manager, session_id = _manager_with_session()
    call = _call("call-1")

    candidate, created = manager._upsert_generation_candidate(
        session_id,
        call,
        dom_context={"inputs": [{"name": "page"}]},
        page_url="https://example.com/app",
        title="Orders",
        dom_digest="digest-1",
    )

    assert created is True
    assert candidate.status == "pending"
    assert candidate.method == "GET"
    assert candidate.url_pattern == "/api/orders?page={page}"
    assert candidate.source_call_ids == ["call-1"]
    assert candidate.sample_call_ids == ["call-1"]
    assert candidate.capture_dom_context["inputs"][0]["name"] == "page"
    assert manager.sessions[session_id].generation_candidates == [candidate]


def test_upsert_generation_candidate_dedups_and_marks_generated_stale():
    manager, session_id = _manager_with_session()
    first = _call("call-1", "https://example.com/api/orders?page=1")
    second = _call("call-2", "https://example.com/api/orders?page=2")

    candidate, _ = manager._upsert_generation_candidate(session_id, first)
    candidate.status = "generated"
    candidate.tool_id = "tool-1"

    updated, created = manager._upsert_generation_candidate(session_id, second)

    assert created is False
    assert updated.id == candidate.id
    assert updated.status == "stale"
    assert updated.source_call_ids == ["call-1", "call-2"]
    assert updated.sample_call_ids == ["call-1", "call-2"]


def test_reconcile_generation_candidates_rebuilds_missing_candidate():
    manager, session_id = _manager_with_session()
    session = manager.sessions[session_id]
    session.captured_calls.append(_call("call-1"))

    candidates = manager.reconcile_generation_candidates(session_id, enqueue=False)

    assert len(candidates) == 1
    assert candidates[0].source_call_ids == ["call-1"]
    assert session.generation_candidates[0].dedup_key == "GET /api/orders"


def test_reconcile_does_not_mark_generated_candidate_stale_without_new_calls():
    manager, session_id = _manager_with_session()
    session = manager.sessions[session_id]
    call = _call("call-1")
    session.captured_calls.append(call)
    candidate, _ = manager._upsert_generation_candidate(session_id, call)
    candidate.status = "generated"
    candidate.tool_id = "tool-1"

    candidates = manager.reconcile_generation_candidates(session_id, enqueue=False)

    assert candidates == []
    assert candidate.status == "generated"


# ── Worker success path tests ────────────────────────────────────────────


class TestGenerateToolForCandidate(unittest.IsolatedAsyncioTestCase):

    async def test_generate_candidate_creates_tool_and_applies_confidence(self):
        manager, session_id = _manager_with_session()
        session = manager.sessions[session_id]
        # Provide source_evidence so the confidence scorer gives a high score:
        #   action_window_matched=True (+30), business_path (+25),
        #   json_response (+20), has_source (+15), response_richness (+10) = 100
        call = _call("call-1")
        call.source_evidence = {
            "action_window_matched": True,
            "initiator_urls": ["https://example.com/app"],
            "js_stack_urls": [],
            "frame_url": "https://example.com/app",
        }
        session.captured_calls.append(call)
        candidate, _ = manager._upsert_generation_candidate(
            session_id,
            call,
            dom_context={"forms": [{"inputs": [{"name": "page"}]}]},
            page_url="https://example.com/app",
            title="Orders",
            dom_digest="digest-1",
        )

        async def fake_generate_tool_definition(**kwargs):
            assert kwargs["method"] == "GET"
            assert kwargs["url_pattern"] == "/api/orders?page={page}"
            assert "page" in kwargs["dom_context"]
            return (
                "name: list_orders\n"
                "description: List orders\n"
                "method: GET\n"
                "url: /api/orders\n"
                "parameters:\n  type: object\n  properties: {}\n"
                "response:\n  type: object\n  properties: {}\n"
            )

        with patch(
            "backend.rpa.api_monitor.manager.generate_tool_definition",
            fake_generate_tool_definition,
        ):
            tool = await manager._generate_tool_for_candidate(session_id, candidate.id)

        assert tool is not None
        assert tool.name == "list_orders"
        assert tool.generation_candidate_id == candidate.id
        assert tool.source_calls == ["call-1"]
        assert tool.confidence == "high"
        assert tool.selected is True
        assert candidate.status == "generated"
        assert candidate.tool_id == tool.id
        assert session.tool_definitions == [tool]

    async def test_candidate_generation_rate_limit_sets_retry_after(self):
        manager, session_id = _manager_with_session()
        session = manager.sessions[session_id]
        call = _call("call-1")
        session.captured_calls.append(call)
        candidate, _ = manager._upsert_generation_candidate(session_id, call)

        async def fake_generate_tool_definition(**kwargs):
            raise RuntimeError("429 rate limit exceeded")

        with patch(
            "backend.rpa.api_monitor.manager.generate_tool_definition",
            fake_generate_tool_definition,
        ):
            tool = await manager._generate_tool_for_candidate(session_id, candidate.id)

        assert tool is None
        assert candidate.status == "rate_limited"
        assert candidate.attempts == 1
        assert candidate.retry_after is not None
        assert "429" in candidate.error

    async def test_candidate_generation_failure_keeps_captured_call(self):
        manager, session_id = _manager_with_session()
        session = manager.sessions[session_id]
        call = _call("call-1")
        session.captured_calls.append(call)
        candidate, _ = manager._upsert_generation_candidate(session_id, call)

        async def fake_generate_tool_definition(**kwargs):
            raise ValueError("bad yaml")

        with patch(
            "backend.rpa.api_monitor.manager.generate_tool_definition",
            fake_generate_tool_definition,
        ):
            tool = await manager._generate_tool_for_candidate(session_id, candidate.id)

        assert tool is None
        assert candidate.status == "failed"
        assert candidate.attempts == 1
        assert candidate.error == "bad yaml"
        assert session.captured_calls == [call]

    async def test_candidate_generation_marks_invalid_yaml_contract(self):
        manager, session_id = _manager_with_session()
        session = manager.sessions[session_id]
        call = _call("call-1")
        call.source_evidence = {
            "action_window_matched": True,
            "initiator_urls": ["https://example.com/app"],
            "js_stack_urls": [],
            "frame_url": "https://example.com/app",
        }
        session.captured_calls.append(call)
        candidate, _ = manager._upsert_generation_candidate(session_id, call)

        async def fake_generate_tool_definition(**kwargs):
            return (
                'swagger: "2.0"\n'
                "info:\n"
                "  title: search_completed_contracts\n"
                "  description: Search contracts\n"
                '  version: "1.0"\n'
                "paths:\n"
                "  /contracts/search:\n"
                "    post:\n"
                "      operationId: search_completed_contracts\n"
                "      summary: Search contracts\n"
                "      parameters:\n"
                "        - name: body\n"
                "          in: body\n"
                "          schema:\n"
                "            type: object\n"
                "            properties:\n"
                "              contractType:\n"
                "                type: string\n"
                "                description: Contract type filter, placeholder: 合同类型\n"
                "      responses:\n"
                '        "200":\n'
                "          description: Success\n"
            )

        with patch(
            "backend.rpa.api_monitor.manager.generate_tool_definition",
            fake_generate_tool_definition,
        ):
            tool = await manager._generate_tool_for_candidate(session_id, candidate.id)

        assert tool is not None
        assert tool.name == "get_api_orders"
        assert tool.description == "Generated API tool (YAML validation failed)"
        assert tool.validation_status == "invalid"
        assert any("Invalid YAML" in error for error in tool.validation_errors)
        assert candidate.status == "generated"

    async def test_running_candidate_regenerates_when_new_sample_marks_stale(self):
        manager, session_id = _manager_with_session()
        session = manager.sessions[session_id]
        first = _call("call-1", "https://example.com/api/orders?page=1")
        second = _call("call-2", "https://example.com/api/orders?page=2")
        session.captured_calls.append(first)
        candidate, _ = manager._upsert_generation_candidate(session_id, first)
        sample_counts: list[int] = []

        async def fake_generate_tool_definition(**kwargs):
            sample_counts.append(len(kwargs["samples"]))
            if len(sample_counts) == 1:
                session.captured_calls.append(second)
                manager._upsert_generation_candidate(session_id, second)
            return (
                "name: list_orders\n"
                "description: List orders\n"
                "method: GET\n"
                "url: /api/orders\n"
                "parameters:\n  type: object\n  properties: {}\n"
                "response:\n  type: object\n  properties: {}\n"
            )

        with patch(
            "backend.rpa.api_monitor.manager.generate_tool_definition",
            fake_generate_tool_definition,
        ):
            await manager._run_generation_candidate(session_id, candidate.id)

        assert sample_counts == [1, 2]
        assert candidate.status == "generated"
        assert candidate.source_call_ids == ["call-1", "call-2"]

    async def test_enqueue_generation_candidate_records_followup_when_task_is_running(self):
        manager, session_id = _manager_with_session()
        call = _call("call-1")
        candidate, _ = manager._upsert_generation_candidate(session_id, call)
        pending_task = asyncio.create_task(asyncio.sleep(60))
        manager._generation_tasks.setdefault(session_id, {})[candidate.id] = pending_task

        try:
            manager._enqueue_generation_candidate(session_id, candidate.id)

            assert (session_id, candidate.id) in manager._generation_followups
        finally:
            pending_task.cancel()
            try:
                await pending_task
            except asyncio.CancelledError:
                pass

    async def test_worker_marks_candidate_failed_when_unexpected_generation_error_escapes(self):
        manager, session_id = _manager_with_session()
        session = manager.sessions[session_id]
        call = _call("call-1")
        session.captured_calls.append(call)
        candidate, _ = manager._upsert_generation_candidate(session_id, call)

        async def broken_generate(session_id_arg, candidate_id_arg, **kwargs):
            candidate.status = "running"
            raise RuntimeError("parse exploded")

        with patch.object(manager, "_generate_tool_for_candidate", side_effect=broken_generate):
            await manager._run_generation_candidate(session_id, candidate.id)

        assert candidate.status == "failed"
        assert candidate.error == "parse exploded"

    async def test_candidate_generation_updates_tool_id_target(self):
        manager, session_id = _manager_with_session()
        session = manager.sessions[session_id]
        call = _call("call-1", path="/api/orders")
        call.source_evidence = {
            "action_window_matched": True,
            "initiator_urls": ["https://example.com/app"],
            "js_stack_urls": [],
            "frame_url": "https://example.com/app",
        }
        session.captured_calls.append(call)
        candidate, _ = manager._upsert_generation_candidate(
            session_id,
            call,
            dom_context={"forms": [{"action": "/api/orders", "inputs": []}]},
            page_url="https://example.com/app",
        )
        original_tool = ApiToolDefinition(
            id="tool-existing",
            session_id=session_id,
            name="old_orders",
            description="Old description",
            method="GET",
            url_pattern="/api/orders",
            yaml_definition="name: old_orders",
            source_calls=["call-1"],
            selected=False,
            generation_candidate_id=None,
        )
        session.tool_definitions.append(original_tool)
        candidate.tool_id = original_tool.id

        async def fake_generate_tool_definition(**kwargs):
            assert kwargs["dom_context"] != "{}"
            return (
                'swagger: "2.0"\n'
                "info:\n"
                "  title: list_orders\n"
                '  version: "1.0"\n'
                "host: api.example.com\n"
                "paths:\n"
                "  /api/orders:\n"
                "    get:\n"
                "      operationId: list_orders\n"
                "      responses:\n"
                '        "200":\n'
                "          description: Success\n"
            )

        with patch(
            "backend.rpa.api_monitor.manager.generate_tool_definition",
            fake_generate_tool_definition,
        ):
            tool = await manager._generate_tool_for_candidate(
                session_id,
                candidate.id,
                skip_filter=True,
            )

        assert tool is original_tool
        assert [item.id for item in session.tool_definitions] == ["tool-existing"]
        assert tool.name == "list_orders"
        assert tool.generation_candidate_id == candidate.id
        assert candidate.tool_id == "tool-existing"
        assert tool.selected is False


class TestProcessCapturedCalls(unittest.IsolatedAsyncioTestCase):

    async def test_process_captured_calls_appends_session_and_enqueues(self):
        manager, session_id = _manager_with_session()
        enqueued: list[tuple[str, str]] = []

        def fake_enqueue(session_id_arg: str, candidate_id: str, **kwargs):
            enqueued.append((session_id_arg, candidate_id))

        with patch.object(manager, "_enqueue_generation_candidate", side_effect=fake_enqueue):
            calls = [_call("call-1")]
            candidates = await manager._process_captured_calls_for_generation(
                session_id,
                calls,
                dom_context={"inputs": [{"name": "q"}]},
                page_url="https://example.com/app",
                title="Orders",
                dom_digest="digest-1",
            )

        session = manager.sessions[session_id]
        assert session.captured_calls == calls
        assert len(candidates) == 1
        assert enqueued == [(session_id, candidates[0].id)]

    async def test_process_evidence_calls_does_not_create_generation_candidate(self):
        manager, session_id = _manager_with_session()
        call = _call("csrf-call", method="GET", path="/api/csrf")
        enqueued: list[tuple[str, str]] = []

        def fake_enqueue(session_id_arg: str, candidate_id: str, **kwargs):
            enqueued.append((session_id_arg, candidate_id))

        with patch.object(manager, "_enqueue_generation_candidate", side_effect=fake_enqueue):
            added = manager._store_evidence_calls(session_id, [call])

        session = manager.sessions[session_id]
        assert added == [call]
        assert session.evidence_calls == [call]
        assert session.captured_calls == []
        assert session.generation_candidates == []
        assert enqueued == []

    async def test_evidence_call_is_not_promoted_to_generation_candidate(self):
        manager, session_id = _manager_with_session()
        call = _call("csrf-call", method="GET", path="/api/csrf")
        session = manager.sessions[session_id]
        session.evidence_calls.append(call)
        enqueued: list[tuple[str, str]] = []

        def fake_enqueue(session_id_arg: str, candidate_id: str, **kwargs):
            enqueued.append((session_id_arg, candidate_id))

        with patch.object(manager, "_enqueue_generation_candidate", side_effect=fake_enqueue):
            candidates = await manager._process_captured_calls_for_generation(session_id, [call])

        assert candidates == []
        assert session.evidence_calls == [call]
        assert session.captured_calls == []
        assert session.generation_candidates == []
        assert enqueued == []

    async def test_store_evidence_calls_deduplicates_against_generation_and_evidence_calls(self):
        manager, session_id = _manager_with_session()
        evidence_call = _call("csrf-call", method="GET", path="/api/csrf")
        generated_call = _call("orders-call", method="GET", path="/api/orders")
        session = manager.sessions[session_id]
        session.evidence_calls.append(evidence_call)
        session.captured_calls.append(generated_call)

        added = manager._store_evidence_calls(session_id, [evidence_call, generated_call])

        assert added == []
        assert session.evidence_calls == [evidence_call]
        assert session.captured_calls == [generated_call]

    async def test_start_recording_stores_pre_calls_as_evidence_only(self):
        manager, session_id = _manager_with_session()
        pre_call = _call("csrf-call", method="GET", path="/api/csrf")
        session = manager.sessions[session_id]

        class _Capture:
            def __init__(self):
                self.calls = [pre_call]

            def drain_new_calls(self):
                calls = list(self.calls)
                self.calls = []
                return calls

        manager._captures[session_id] = _Capture()
        manager._enqueue_generation_candidate = lambda *args, **kwargs: None

        await manager.start_recording(session_id)
        await manager._stop_recording_drain_task(session_id)

        assert session.evidence_calls == [pre_call]
        assert session.captured_calls == []
        assert session.generation_candidates == []

    async def test_stop_recording_does_not_run_legacy_batch_generation(self):
        manager, session_id = _manager_with_session()
        session = manager.sessions[session_id]
        session.status = "recording"
        calls = [_call("call-1")]

        class _Capture:
            def drain_new_calls(self):
                return calls

        async def forbidden_generate(*args, **kwargs):
            raise AssertionError("legacy batch generation should not run")

        manager._captures[session_id] = _Capture()
        manager._generate_tools_from_calls = forbidden_generate
        manager._enqueue_generation_candidate = lambda *args, **kwargs: None

        tools = await manager.stop_recording(session_id)

        assert tools == []
        assert session.status == "idle"
        assert session.captured_calls == calls
        assert len(session.generation_candidates) == 1

    async def test_recording_drain_loop_processes_calls_before_stop(self):
        manager, session_id = _manager_with_session()
        session = manager.sessions[session_id]
        session.status = "recording"
        call = _call("call-1")

        class _Capture:
            def __init__(self):
                self.calls = [call]

            def drain_new_calls(self):
                calls = list(self.calls)
                self.calls = []
                return calls

        manager._captures[session_id] = _Capture()
        manager._enqueue_generation_candidate = lambda *args, **kwargs: None

        task = asyncio.create_task(manager._recording_drain_loop(session_id, model_config=None, interval_s=0.01))
        manager._recording_drain_tasks[session_id] = task
        await asyncio.sleep(0.05)
        await manager._stop_recording_drain_task(session_id)

        assert session.captured_calls == [call]
        assert [candidate.source_call_ids for candidate in session.generation_candidates] == [["call-1"]]

    async def test_recording_drain_stop_waits_for_in_flight_processing(self):
        manager, session_id = _manager_with_session()
        session = manager.sessions[session_id]
        session.status = "recording"
        call = _call("call-1")
        entered_processing = asyncio.Event()
        release_processing = asyncio.Event()

        class _Capture:
            def __init__(self):
                self.calls = [call]

            def drain_new_calls(self):
                calls = list(self.calls)
                self.calls = []
                return calls

        async def slow_dom_context(session_id_arg):
            entered_processing.set()
            await release_processing.wait()
            return {}, "", "", ""

        manager._captures[session_id] = _Capture()
        manager._capture_generation_dom_context = slow_dom_context
        manager._enqueue_generation_candidate = lambda *args, **kwargs: None

        task = asyncio.create_task(manager._recording_drain_loop(session_id, model_config=None, interval_s=0.01))
        manager._recording_drain_tasks[session_id] = task
        await asyncio.wait_for(entered_processing.wait(), timeout=1)

        stop_task = asyncio.create_task(manager._stop_recording_drain_task(session_id))
        await asyncio.sleep(0)

        assert not stop_task.done()

        release_processing.set()
        await asyncio.wait_for(stop_task, timeout=1)

        assert session.captured_calls == [call]
        assert [candidate.source_call_ids for candidate in session.generation_candidates] == [["call-1"]]

    async def test_free_analysis_processes_each_probe_batch_without_final_replay(self):
        manager, session_id = _manager_with_session()

        class _Page:
            url = "https://example.com/app"

        manager._pages[session_id] = _Page()
        first = _call("call-1", "https://example.com/api/orders?page=1")
        second = _call("call-2", "https://example.com/api/users?page=1")
        batches: list[list[str]] = []

        async def fake_scan(page):
            return [{"tag": "a", "text": "Orders"}, {"tag": "a", "text": "Users"}]

        async def fake_analyze_elements(**kwargs):
            return {"safe": [0, 1], "skip": []}

        async def fake_probe(page, elem):
            return [first] if elem["text"] == "Orders" else [second]

        async def fake_process(session_id_arg, calls, **kwargs):
            batches.append([call.id for call in calls])
            return []

        with patch.object(manager, "_scan_interactive_elements", side_effect=fake_scan):
            with patch("backend.rpa.api_monitor.manager.analyze_elements", fake_analyze_elements):
                with patch.object(manager, "_probe_element", side_effect=fake_probe):
                    with patch.object(manager, "_process_captured_calls_for_generation", side_effect=fake_process):
                        events = await _collect_events(manager.analyze_page(session_id))

        assert batches == [["call-1"], ["call-2"]]
        assert any(event["event"] == "analysis_complete" for event in events)


class TestRegenerateTool(unittest.IsolatedAsyncioTestCase):
    async def test_regenerate_tool_reuses_existing_candidate_context(self):
        manager, session_id = _manager_with_session()
        session = manager.sessions[session_id]
        call = _call("call-1", path="/api/orders")
        session.captured_calls.append(call)
        candidate, _ = manager._upsert_generation_candidate(
            session_id,
            call,
            dom_context={"forms": [{"action": "/api/orders", "inputs": [{"name": "keyword"}]}]},
            page_url="https://example.com/app",
            title="Orders",
            dom_digest="digest-1",
        )
        tool = ApiToolDefinition(
            id="tool-1",
            session_id=session_id,
            name="old_orders",
            description="Old",
            method="GET",
            url_pattern="/api/orders",
            yaml_definition="name: old_orders",
            source_calls=["call-1"],
            selected=False,
            generation_candidate_id=candidate.id,
        )
        session.tool_definitions.append(tool)
        candidate.tool_id = tool.id

        async def fake_generate_tool_definition(**kwargs):
            assert '"keyword"' in kwargs["dom_context"]
            assert kwargs["page_context"] == "https://example.com/app"
            return (
                'swagger: "2.0"\n'
                "info:\n"
                "  title: list_orders\n"
                '  version: "1.0"\n'
                "host: api.example.com\n"
                "paths:\n"
                "  /api/orders:\n"
                "    get:\n"
                "      operationId: list_orders\n"
                "      responses:\n"
                '        "200":\n'
                "          description: Success\n"
            )

        with patch(
            "backend.rpa.api_monitor.manager.generate_tool_definition",
            fake_generate_tool_definition,
        ):
            regenerated = await manager.regenerate_tool(session_id, tool.id)

        assert regenerated is tool
        assert regenerated.name == "list_orders"
        assert regenerated.id == "tool-1"
        assert regenerated.selected is False
        assert candidate.status == "generated"

    async def test_regenerate_tool_backfills_candidate_from_historical_candidate_context(self):
        manager, session_id = _manager_with_session()
        session = manager.sessions[session_id]
        call = _call("call-1", path="/api/orders")
        session.captured_calls.append(call)
        historical_candidate = ApiToolGenerationCandidate(
            session_id=session_id,
            dedup_key=manager._candidate_dedup_key(call),
            method="GET",
            url_pattern="/api/orders",
            source_call_ids=["call-1"],
            sample_call_ids=["call-1"],
            capture_dom_context={"forms": [{"action": "/api/orders", "inputs": [{"name": "keyword"}]}]},
            capture_page_url="https://example.com/app",
            capture_title="Orders",
            capture_dom_digest="digest-1",
            status="generated",
        )
        session.generation_candidates.append(historical_candidate)
        tool = ApiToolDefinition(
            id="tool-legacy",
            session_id=session_id,
            name="old_orders",
            description="Old",
            method="GET",
            url_pattern="/api/orders",
            yaml_definition="name: old_orders",
            source_calls=["call-1"],
            selected=True,
            generation_candidate_id=None,
        )
        session.tool_definitions.append(tool)

        async def fake_generate_tool_definition(**kwargs):
            assert '"keyword"' in kwargs["dom_context"]
            return (
                'swagger: "2.0"\n'
                "info:\n"
                "  title: list_orders\n"
                '  version: "1.0"\n'
                "host: api.example.com\n"
                "paths:\n"
                "  /api/orders:\n"
                "    get:\n"
                "      operationId: list_orders\n"
                "      responses:\n"
                '        "200":\n'
                "          description: Success\n"
            )

        with patch(
            "backend.rpa.api_monitor.manager.generate_tool_definition",
            fake_generate_tool_definition,
        ):
            regenerated = await manager.regenerate_tool(session_id, tool.id)

        assert regenerated is tool
        assert tool.generation_candidate_id == historical_candidate.id
        assert historical_candidate.tool_id == "tool-legacy"
        assert tool.selected is True
        assert len(session.generation_candidates) == 1

    async def test_regenerate_tool_rejects_missing_historical_dom_context(self):
        manager, session_id = _manager_with_session()
        session = manager.sessions[session_id]
        call = _call("call-1", path="/api/orders")
        session.captured_calls.append(call)
        candidate, _ = manager._upsert_generation_candidate(session_id, call)
        tool = ApiToolDefinition(
            id="tool-1",
            session_id=session_id,
            name="old_orders",
            description="Old",
            method="GET",
            url_pattern="/api/orders",
            yaml_definition="name: old_orders",
            source_calls=["call-1"],
            generation_candidate_id=candidate.id,
        )
        session.tool_definitions.append(tool)

        with patch.object(manager, "_capture_generation_dom_context") as capture_dom:
            try:
                await manager.regenerate_tool(session_id, tool.id)
            except ValueError as exc:
                assert "missing historical DOM context" in str(exc) or "missing generation candidate context" in str(exc)
            else:
                raise AssertionError("Expected missing DOM context error")

        capture_dom.assert_not_called()


# ── Retry generation candidate tests ───────────────────────────────────


def test_retry_generation_candidate_resets_failed_candidate():
    manager, session_id = _manager_with_session()
    call = _call("call-1")
    manager.sessions[session_id].captured_calls.append(call)
    candidate, _ = manager._upsert_generation_candidate(session_id, call)
    candidate.status = "failed"
    candidate.error = "bad yaml"
    candidate.attempts = 2
    enqueued: list[str] = []

    # Patch enqueue to track calls
    import unittest.mock
    with unittest.mock.patch.object(
        manager,
        "_enqueue_generation_candidate",
        side_effect=lambda sid, cid, **kw: enqueued.append(cid),
    ):
        result = manager.retry_generation_candidate(session_id, candidate.id)

    assert result.id == candidate.id
    assert result.status == "pending"
    assert result.error == ""
    assert result.retry_after is None
    assert enqueued == [candidate.id]


# ── Intent prune helper tests ─────────────────────────────────────────────


from backend.rpa.api_monitor.intent_pruner import IntentPruneItem
from backend.rpa.api_monitor.manager import ApiMonitorSessionManager
from backend.rpa.api_monitor.models import ApiMonitorSession, ApiToolGenerationCandidate


def test_apply_prune_item_sets_filtered_candidate_state():
    manager = ApiMonitorSessionManager()
    session = ApiMonitorSession(id="session_1", user_id="user_1", sandbox_session_id="sandbox_1")
    candidate = ApiToolGenerationCandidate(
        session_id="session_1",
        dedup_key="GET /api/menu/tree",
        method="GET",
        url_pattern="/api/menu/tree",
    )
    session.generation_candidates.append(candidate)
    manager.sessions[session.id] = session

    manager._apply_prune_item_to_candidate(
        session,
        candidate,
        IntentPruneItem(
            candidate_key="GET /api/menu/tree",
            intent_group="bootstrap",
            intent_score=20,
            intent_rank=None,
            intent_reason="菜单初始化接口。",
        ),
        batch_id="batch_1",
    )

    assert candidate.status == "intent_filtered"
    assert candidate.intent_group == "bootstrap"
    assert candidate.intent_filter_reason == "菜单初始化接口。"
    assert candidate.intent_batch_id == "batch_1"


def test_apply_prune_item_sets_uncertain_candidate_state():
    manager = ApiMonitorSessionManager()
    session = ApiMonitorSession(id="session_1", user_id="user_1", sandbox_session_id="sandbox_1")
    candidate = ApiToolGenerationCandidate(
        session_id="session_1",
        dedup_key="GET /api/unknown",
        method="GET",
        url_pattern="/api/unknown",
    )
    session.generation_candidates.append(candidate)
    manager.sessions[session.id] = session

    manager._apply_prune_item_to_candidate(
        session,
        candidate,
        IntentPruneItem(
            candidate_key="GET /api/unknown",
            intent_group="uncertain",
            intent_score=0,
            intent_rank=None,
            intent_reason="证据不足。",
        ),
        batch_id="batch_2",
    )

    assert candidate.status == "intent_review"
    assert candidate.intent_group == "uncertain"
    assert candidate.intent_reason == "证据不足。"


# ── Batch intent pruning integration test ─────────────────────────────────


from backend.rpa.api_monitor.intent_pruner import IntentPruneResult


class TestBatchIntentPruning(unittest.IsolatedAsyncioTestCase):

    async def test_generate_tools_from_calls_uses_batch_intent_pruning(self):
        manager = ApiMonitorSessionManager()
        session = ApiMonitorSession(
            id="session_1",
            user_id="user_1",
            sandbox_session_id="sandbox_1",
            intent="查询订单列表",
            target_url="https://example.com/orders",
        )
        manager.sessions[session.id] = session
        order_call = _call(
            "order_1",
            method="POST",
            path="/api/orders/search",
        )
        order_call.source_evidence = {
            "action_window_matched": True,
            "initiator_urls": ["https://example.com/app.js"],
        }
        order_call.response.body = '{"items":[{"orderNo":"A001"}]}'
        menu_call = _call(
            "menu_1",
            method="GET",
            path="/api/menu/tree",
        )
        menu_call.source_evidence = {
            "action_window_matched": True,
            "initiator_urls": ["https://example.com/app.js"],
        }
        menu_call.response.body = '{"menus":[]}'

        async def fake_prune(candidates, intent, page_context="", model_config=None):
            assert intent == "查询订单列表"
            return IntentPruneResult(
                batch_id="batch_1",
                items=[
                    IntentPruneItem(candidates[0].candidate_key, "primary", 95, 1, "订单查询主接口。"),
                    IntentPruneItem(candidates[1].candidate_key, "bootstrap", 20, None, "菜单初始化接口。"),
                ],
            )

        async def fake_generate_tool_definition(**kwargs):
            return 'swagger: "2.0"\ninfo:\n  title: list_orders\n  version: "1.0"\npaths:\n  /api/orders/search:\n    post:\n      operationId: list_orders\n      responses:\n        "200":\n          description: OK\n'

        with patch("backend.rpa.api_monitor.manager.prune_candidates_by_intent", side_effect=fake_prune):
            with patch("backend.rpa.api_monitor.manager.generate_tool_definition", side_effect=fake_generate_tool_definition):
                tools = await manager._generate_tools_from_calls(session.id, [order_call, menu_call], model_config=None)

        assert [tool.url_pattern for tool in tools] == [order_call.url_pattern or order_call.request.url]
        assert session.tool_definitions[0].selected is True
        filtered = [candidate for candidate in session.generation_candidates if candidate.status == "intent_filtered"]
        assert len(filtered) == 1
        assert filtered[0].intent_group == "bootstrap"
        assert filtered[0].intent_filter_reason == "菜单初始化接口。"


# ── Realtime buffer tests ───────────────────────────────────────────────


class TestRealtimeBuffer(unittest.IsolatedAsyncioTestCase):

    async def test_process_captured_calls_buffers_high_confidence_candidates_when_intent_exists(self):
        manager = ApiMonitorSessionManager()
        session = ApiMonitorSession(
            id="session_1",
            user_id="user_1",
            sandbox_session_id="sandbox_1",
            intent="查询订单列表",
        )
        manager.sessions[session.id] = session
        enqueued: list[str] = []
        manager._enqueue_generation_candidate = lambda _sid, candidate_id, **_kw: enqueued.append(candidate_id)
        manager._schedule_intent_prune_flush = lambda _sid, **_kw: None
        call = _call(
            "order_1",
            method="POST",
            path="/api/orders/search",
        )
        call.source_evidence = {
            "action_window_matched": True,
            "initiator_urls": ["https://example.com/app.js"],
        }
        call.response.body = '{"items":[{"orderNo":"A001"}]}'

        changed = await manager._process_captured_calls_for_generation(session.id, [call], model_config=None)

        assert len(changed) == 1
        assert enqueued == []
        assert manager._intent_prune_buffers[session.id] == {changed[0].id}


# ── Reserve generation and force flow tests ────────────────────────────────


class TestReserveGeneration(unittest.IsolatedAsyncioTestCase):

    async def test_supporting_candidate_generates_reserve_tool(self):
        manager = ApiMonitorSessionManager()
        session = ApiMonitorSession(
            id="session_1",
            user_id="user_1",
            sandbox_session_id="sandbox_1",
            intent="查询订单列表",
        )
        manager.sessions[session.id] = session
        call = _call(
            "status_1",
            method="GET",
            path="/api/order/status-options",
        )
        call.source_evidence = {
            "action_window_matched": True,
            "initiator_urls": ["https://example.com/app.js"],
        }
        call.response.body = '{"options":["paid"]}'
        session.captured_calls.append(call)
        candidate, _ = manager._upsert_generation_candidate(session.id, call)
        candidate.intent_group = "supporting"
        candidate.intent_reason = "订单查询筛选条件。"
        candidate.intent_score = 75

        async def fake_generate_tool_definition(**kwargs):
            return 'swagger: "2.0"\ninfo:\n  title: list_order_statuses\n  version: "1.0"\npaths:\n  /api/order/status-options:\n    get:\n      operationId: list_order_statuses\n      responses:\n        "200":\n          description: OK\n'

        with patch(
            "backend.rpa.api_monitor.manager.generate_tool_definition",
            fake_generate_tool_definition,
        ):
            tool = await manager._generate_tool_for_candidate(session.id, candidate.id, skip_filter=True)

        assert tool is not None
        assert tool.selected is False
        assert tool.is_reserve is True
        assert tool.intent_group == "supporting"
        assert tool.intent_reason == "订单查询筛选条件。"


def test_force_generate_allows_intent_review_candidate():
    manager = ApiMonitorSessionManager()
    session = ApiMonitorSession(id="session_1", user_id="user_1", sandbox_session_id="sandbox_1")
    candidate = ApiToolGenerationCandidate(
        session_id="session_1",
        dedup_key="GET /api/unknown",
        method="GET",
        url_pattern="/api/unknown",
        status="intent_review",
        intent_group="uncertain",
    )
    session.generation_candidates.append(candidate)
    manager.sessions[session.id] = session

    manager.force_generate_candidate(session.id, candidate.id)

    assert candidate.status == "pending"
