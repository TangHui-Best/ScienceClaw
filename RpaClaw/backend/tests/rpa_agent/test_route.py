from __future__ import annotations

from collections import defaultdict
import asyncio
import json
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from fastapi import FastAPI
from fastapi.testclient import TestClient
import httpx
import pytest
from pydantic import ValidationError

from backend.config import settings
from backend.rpa_agent.browser_use import (
    NonSopActionClassification,
    RecordingRoundReport,
)
from backend.rpa_agent.api.models import (
    AgentInstructionRequest,
    ManualEventRequest,
    TestRunRequest as ApiTestRunRequest,
)
from backend.rpa_agent.creation import ControlMode, SkillCreationSession
from backend.rpa_agent.host import (
    BrowserHostSession,
    BrowserSession,
    HostBrowserEvent,
    PlaywrightBrowserSessionPort,
    SessionState,
    SessionStore,
)
from backend.rpa_agent.host.browser_session import HostDownloadEvent
from backend.rpa_agent.host.manual_input import ManualTarget
from backend.route.rpa_agent import (
    RpaAgentApiServices,
    _scienceclaw_browser_provider,
    _sanitize,
    build_router,
)
from backend.user.dependencies import User, require_user


NOW = "2026-07-18T08:00:00Z"


class FakeBrowserPort:
    main_page_runtime_ref = "runtime_main"
    main_frame_runtime_ref = "frame_main"

    def __init__(self) -> None:
        self.context = object()
        self.main_page = object()
        self._listeners: dict[str, list[Callable[[object], None]]] = defaultdict(list)
        self.release_count = 0
        self.manual_click_count = 0
        self.manual_value = ""
        self.manual_checked = False
        self.manual_target = ManualTarget(
            page_runtime_ref="runtime_main",
            frame_runtime_ref="frame_main",
            target_key="query-button",
            target_name="查询",
            target_locators=(
                {"strategy": "role", "role": "button", "name": "查询", "exact": True},
            ),
            interaction_kind="click",
            handle=object(),
        )

    def subscribe(self, kind: str, callback: Callable[[object], None]) -> Callable[[], None]:
        self._listeners[kind].append(callback)

        def release() -> None:
            self.release_count += 1
            self._listeners[kind].remove(callback)

        return release

    def emit(self, kind: str, event: HostBrowserEvent) -> None:
        for callback in tuple(self._listeners[kind]):
            callback(event)

    async def resolve_pointer_target(self, *, x: float, y: float) -> ManualTarget:
        del x, y
        return self.manual_target

    async def resolve_focused_target(self) -> ManualTarget:
        return self.manual_target

    @asynccontextmanager
    async def action_dispatch_scope(self, target: ManualTarget):
        del target
        yield

    async def click(self, target: ManualTarget) -> None:
        del target
        self.manual_click_count += 1

    async def insert_text(self, target: ManualTarget, text: str) -> None:
        del target
        self.manual_value += text

    async def read_value(self, target: ManualTarget) -> str:
        del target
        return self.manual_value

    async def read_checked(self, target: ManualTarget) -> bool:
        del target
        return self.manual_checked


class FakePublisher:
    def __init__(self) -> None:
        self.calls = 0

    async def __call__(self, session: object) -> dict[str, str]:
        self.calls += 1
        return {"skill_ref": "saved/purchase-order-acceptance"}


def _services(
    tmp_path: Path,
    *,
    with_agent: bool = True,
    run_status: str = "succeeded",
    expected_browser_ref: str = "browser-workbench-1",
):
    port = FakeBrowserPort()
    publisher = FakePublisher()

    async def browser_provider(owner_id: str, browser_session_ref: str) -> FakeBrowserPort:
        assert owner_id == "user-1"
        assert browser_session_ref.startswith("bhs_")
        return port

    async def agent_executor(session: object, request: object) -> RecordingRoundReport:
        return RecordingRoundReport(
            invocation_count=1,
            actual_action_count=1,
            candidate_ids=(),
            non_sop=(
                NonSopActionClassification(
                    action_name="done", status="succeeded", reason="control_action"
                ),
            ),
        )

    async def runtime_runner(session: object, request: object) -> dict[str, Any]:
        return {"status": run_status, "run_id": "run-1", "outputs": {}}

    services = RpaAgentApiServices(
        artifact_root=tmp_path / "artifacts",
        browser_provider=browser_provider,
        agent_executor=agent_executor if with_agent else None,
        runtime_runner=runtime_runner,
        publisher=publisher,
    )
    return services, port, publisher


def _client(services: RpaAgentApiServices) -> TestClient:
    app = FastAPI()
    app.include_router(build_router(services), prefix="/api/v1/rpa-agent")
    app.dependency_overrides[require_user] = lambda: User(
        id="user-1", username="tester", role="user"
    )
    return TestClient(app)


def _start(client: TestClient) -> str:
    response = client.post(
        "/api/v1/rpa-agent/sessions",
        json={},
    )
    assert response.status_code == 201, response.text
    payload = response.json()
    assert payload["session_id"].startswith("rca_")
    assert payload["state"] == "recording"
    assert payload["browser_session_ref"].startswith("bhs_recording_")
    assert payload["generation"].startswith("gen_")
    return payload["session_id"]


def _record_one_click(client: TestClient, session_id: str) -> None:
    reservation = client.post(
        f"/api/v1/rpa-agent/sessions/{session_id}/manual-reservations",
        json={
            "candidate_id": "manual_submit",
            "page_runtime_ref": "runtime_main",
            "frame_runtime_ref": "frame_main",
        },
    )
    assert reservation.status_code == 201, reservation.text
    token = reservation.json()["reservation_token"]
    assert "manual_submit" not in token

    event = client.post(
        f"/api/v1/rpa-agent/sessions/{session_id}/manual-events",
        json={
            "reservation_token": token,
            "kind": "click",
            "interaction_kind": "click",
            "page_runtime_ref": "runtime_main",
            "frame_runtime_ref": "frame_main",
            "target_key": "submit-button",
            "target_name": "查询",
            "target_locators": [{"strategy": "role", "role": "button", "name": "查询", "exact": True}],
            "observed_at": NOW,
            "finish": True,
        },
    )
    assert event.status_code == 200, event.text
    assert event.json()["candidate_ids"] == ["manual_submit"]


def _record_one_fill(client: TestClient, session_id: str) -> None:
    token = client.post(
        f"/api/v1/rpa-agent/sessions/{session_id}/manual-reservations",
        json={
            "candidate_id": "manual_order_no",
            "page_runtime_ref": "runtime_main",
            "frame_runtime_ref": "frame_main",
        },
    ).json()["reservation_token"]
    common = {
        "reservation_token": token,
        "interaction_kind": "fill",
        "page_runtime_ref": "runtime_main",
        "frame_runtime_ref": "frame_main",
        "target_key": "order-number",
        "target_name": "订单号",
        "target_locators": [
            {"strategy": "label", "value": "订单号", "exact": True}
        ],
        "observed_at": NOW,
    }
    assert client.post(
        f"/api/v1/rpa-agent/sessions/{session_id}/manual-events",
        json={**common, "kind": "input", "value": "PO-RECORDED", "finish": False},
    ).status_code == 200
    finished = client.post(
        f"/api/v1/rpa-agent/sessions/{session_id}/manual-events",
        json={**common, "kind": "blur", "finish": True},
    )
    assert finished.status_code == 200, finished.text


def test_atomic_manual_input_endpoint_authors_scope_locator_and_candidate(tmp_path: Path) -> None:
    services, port, _publisher = _services(tmp_path)
    with _client(services) as client:
        session_id = _start(client)

        response = client.post(
            f"/api/v1/rpa-agent/sessions/{session_id}/manual-inputs",
            json={"input_id": "ui_click_1", "kind": "click", "x": 12.5, "y": 18.0},
        )

        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["input_id"] == "ui_click_1"
        assert payload["draft_id"].startswith("draft_")
        assert payload["capture_status"] == "captured"
        assert port.manual_click_count == 1
        projection = client.get(
            f"/api/v1/rpa-agent/sessions/{session_id}/projection"
        ).json()["items"]
        assert [(row["kind"], row["capture_status"]) for row in projection] == [
            ("manual", "captured")
        ]


def test_atomic_manual_input_is_idempotent_and_rejects_ui_authored_scope(tmp_path: Path) -> None:
    services, port, _publisher = _services(tmp_path)
    with _client(services) as client:
        session_id = _start(client)
        path = f"/api/v1/rpa-agent/sessions/{session_id}/manual-inputs"
        command = {"input_id": "ui_click_once", "kind": "click", "x": 1.0, "y": 2.0}

        first = client.post(path, json=command)
        second = client.post(path, json=command)
        forged = client.post(
            path,
            json={
                **command,
                "input_id": "ui_click_forged",
                "page_runtime_ref": "runtime_forged",
                "target_locators": [{"strategy": "css", "value": "#forged"}],
            },
        )

        assert first.status_code == second.status_code == 200
        assert first.json() == second.json()
        assert port.manual_click_count == 1
        assert forged.status_code == 422


def test_atomic_manual_input_fails_closed_after_stop(tmp_path: Path) -> None:
    services, _port, _publisher = _services(tmp_path)
    with _client(services) as client:
        session_id = _start(client)
        assert client.post(f"/api/v1/rpa-agent/sessions/{session_id}/stop").status_code == 200

        response = client.post(
            f"/api/v1/rpa-agent/sessions/{session_id}/manual-inputs",
            json={"input_id": "ui_click_stopped", "kind": "click", "x": 1.0, "y": 2.0},
        )

        assert response.status_code == 409


def _compile_minimal_skill(client: TestClient, session_id: str) -> str:
    _record_one_click(client, session_id)
    stopped = client.post(f"/api/v1/rpa-agent/sessions/{session_id}/stop")
    assert stopped.status_code == 200, stopped.text
    configured = client.put(
        f"/api/v1/rpa-agent/sessions/{session_id}/configuration",
        json={
            "schema_version": "skill-configuration-draft/v0.1",
            "skill": {"name": "完整性测试", "description": "验证编译产物未被篡改"},
            "inputs": [],
            "secrets": [],
            "asset_inputs": [],
            "outputs": [],
            "asset_outputs": [],
            "binding_promotions": [],
        },
    )
    assert configured.status_code == 200, configured.text
    compiled = client.post(f"/api/v1/rpa-agent/sessions/{session_id}/compile")
    assert compiled.status_code == 200, compiled.text
    return compiled.json()["artifact_hash"]


def test_full_api_journey_reuses_compiled_artifact_before_save(tmp_path: Path) -> None:
    services, port, publisher = _services(tmp_path)
    with _client(services) as client:
        session_id = _start(client)
        _record_one_click(client, session_id)

        agent = client.post(
            f"/api/v1/rpa-agent/sessions/{session_id}/agent-instructions",
            headers={"Idempotency-Key": "journey-agent-key-001"},
            json={
                "instruction": "观察查询结果后结束",
                "business_terms": ["采购订单"],
                "required_variable_refs": [],
                "allowed_inputs": {},
                "allowed_secret_names": [],
                "allowed_data_assets": {},
                "page_aliases": {"main": "采购订单查询页"},
            },
        )
        assert agent.status_code == 202, agent.text
        assert agent.json()["execution_status"] == "queued"

        projection = client.get(
            f"/api/v1/rpa-agent/sessions/{session_id}/projection"
        )
        assert projection.status_code == 200
        assert projection.json()["items"][0]["kind"] == "manual"

        stopped = client.post(f"/api/v1/rpa-agent/sessions/{session_id}/stop")
        assert stopped.status_code == 200, stopped.text
        assert stopped.json()["state"] == "stopped"
        assert stopped.json()["configuration_draft"]["schema_version"] == "skill-configuration-draft/v0.1"

        configured = client.put(
            f"/api/v1/rpa-agent/sessions/{session_id}/configuration",
            json={
                "schema_version": "skill-configuration-draft/v0.1",
                "skill": {"name": "采购订单验收", "description": "查询采购订单并登记验收"},
                "inputs": [],
                "secrets": [],
                "asset_inputs": [],
                "outputs": [],
                "asset_outputs": [],
                "binding_promotions": [],
            },
        )
        assert configured.status_code == 200, configured.text
        assert configured.json()["state"] == "configured"

        compiled = client.post(f"/api/v1/rpa-agent/sessions/{session_id}/compile")
        assert compiled.status_code == 200, compiled.text
        assert compiled.json()["state"] == "compiled"
        assert sorted(compiled.json()["artifact_files"]) == [
            "SKILL.md", "browser_segment.py", "skill.manifest.json", "skill.py"
        ]
        artifact_hash = compiled.json()["artifact_hash"]
        manifest = json.loads(
            (tmp_path / "artifacts" / session_id / "skill.manifest.json").read_text(
                encoding="utf-8"
            )
        )
        assert manifest["schema_version"] == "skill-manifest/v0.2"
        assert manifest["source"]["source_hash"] == compiled.json()["source_hash"]
        assert manifest["source"]["item_count"] == 2
        assert manifest["source"]["playwright_segment_count"] == 1
        assert manifest["source"]["agent_segment_count"] == 1

        tested = client.post(
            f"/api/v1/rpa-agent/sessions/{session_id}/test-run",
            json={"inputs": {}, "secrets": {}, "data_assets": {}},
        )
        assert tested.status_code == 200, tested.text
        assert tested.json()["state"] == "tested"
        assert tested.json()["artifact_hash"] == artifact_hash
        assert tested.json()["run_result"]["status"] == "succeeded"
        first_test_browser_ref = tested.json()["test_session"]["browser_session_ref"]

        retested = client.post(
            f"/api/v1/rpa-agent/sessions/{session_id}/test-run",
            json={"inputs": {}, "secrets": {}, "data_assets": {}},
        )
        assert retested.status_code == 200, retested.text
        assert retested.json()["state"] == "tested"
        assert (
            retested.json()["test_session"]["browser_session_ref"]
            != first_test_browser_ref
        )

        saved = client.post(f"/api/v1/rpa-agent/sessions/{session_id}/save")
        assert saved.status_code == 200, saved.text
        assert saved.json() == {
            "state": "saved",
            "skill_ref": "saved/purchase-order-acceptance",
            "artifact_hash": artifact_hash,
        }
        assert publisher.calls == 1

    assert port.release_count == 3


def test_start_returns_fake_provider_main_scope_for_manual_round_trip(
    tmp_path: Path,
) -> None:
    services, _, _ = _services(tmp_path)
    with _client(services) as client:
        started = client.post(
            "/api/v1/rpa-agent/sessions",
            json={},
        )
        assert started.status_code == 201, started.text
        payload = started.json()
        assert payload["page_ref"] == "runtime_main"
        reserved = client.post(
            f"/api/v1/rpa-agent/sessions/{payload['session_id']}/manual-reservations",
                json={
                    "candidate_id": "manual_round_trip",
                    "page_runtime_ref": "runtime_main",
                    "frame_runtime_ref": "frame_main",
                },
        )
        assert reserved.status_code == 201, reserved.text


def test_stop_draft_is_derived_from_exact_timeline_binding_locations(tmp_path: Path) -> None:
    services, _, _ = _services(tmp_path)
    with _client(services) as client:
        session_id = _start(client)
        _record_one_fill(client, session_id)
        stopped = client.post(f"/api/v1/rpa-agent/sessions/{session_id}/stop")
        assert stopped.status_code == 200, stopped.text
        payload = stopped.json()
        locations = payload["configuration_options"]["binding_locations"]
        assert locations == [
            {
                "trace_id": locations[0]["trace_id"],
                "binding_name": "value",
                "direction": "input",
                "kind": "literal",
                "ref": None,
                "sensitive": False,
            }
        ]
        assert locations[0]["trace_id"].startswith("trace_")
        assert "PO-RECORDED" not in stopped.text
        assert payload["configuration_options"]["readiness"] == {
            "ready": True,
            "issues": [],
        }


def test_old_shapes_and_out_of_order_operations_fail_closed(tmp_path: Path) -> None:
    services, _, _ = _services(tmp_path)
    with _client(services) as client:
        old_start = client.post(
            "/api/v1/rpa-agent/sessions",
            json={"sandbox_session_id": "legacy", "skill_name": "old", "traces": []},
        )
        assert old_start.status_code == 422
        assert "traces" not in old_start.text

        session_id = _start(client)
        assert client.post(f"/api/v1/rpa-agent/sessions/{session_id}/compile").status_code == 409
        assert client.post(f"/api/v1/rpa-agent/sessions/{session_id}/test-run", json={"inputs": {}, "secrets": {}, "data_assets": {}}).status_code == 409
        assert client.post(f"/api/v1/rpa-agent/sessions/{session_id}/save").status_code == 409
        assert client.get("/api/v1/rpa-agent/sessions/legacy-session/projection").status_code in {404, 422}


def test_agent_is_explicitly_unavailable_without_injected_executor(tmp_path: Path) -> None:
    services, _, _ = _services(tmp_path, with_agent=False)
    with _client(services) as client:
        session_id = _start(client)
        response = client.post(
            f"/api/v1/rpa-agent/sessions/{session_id}/agent-instructions",
            headers={"Idempotency-Key": "unavailable-agent-001"},
            json={
                "instruction": "提取订单号",
                "business_terms": [],
                "required_variable_refs": [],
                "allowed_inputs": {},
                "allowed_secret_names": [],
                "allowed_data_assets": {},
                "page_aliases": {},
            },
        )
        assert response.status_code == 503
        assert response.json()["detail"]["code"] == "rpa_agent.agent_unavailable"


def test_start_logs_browser_host_failure_without_exception_details(
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    secret = "do-not-log-this-runtime-detail"

    async def unavailable(_owner_id: str, _browser_ref: str):
        raise RuntimeError(secret)

    services = RpaAgentApiServices(
        artifact_root=tmp_path / "artifacts",
        browser_provider=unavailable,
    )
    monkeypatch.setattr(settings, "storage_backend", "local")
    caplog.set_level("ERROR", logger="backend.route.rpa_agent")

    with _client(services) as client:
        response = client.post(
            "/api/v1/rpa-agent/sessions",
            json={},
        )

    assert response.status_code == 503
    assert "storage_backend=local" in caplog.text
    assert "error_type=RuntimeError" in caplog.text
    assert secret not in caplog.text


def test_start_accepts_an_opaque_host_ref_that_begins_with_a_digit(
    tmp_path: Path,
) -> None:
    browser_ref = "7Zp4vQ2m-browser"
    services, _, _ = _services(
        tmp_path,
        expected_browser_ref=browser_ref,
    )
    with _client(services) as client:
        response = client.post(
            "/api/v1/rpa-agent/sessions",
            json={},
        )
    assert response.status_code == 201, response.text


def test_agent_switch_settles_an_open_manual_fill_with_its_exact_scope(
    tmp_path: Path,
) -> None:
    services, _, _ = _services(tmp_path)
    with _client(services) as client:
        session_id = _start(client)
        token = client.post(
            f"/api/v1/rpa-agent/sessions/{session_id}/manual-reservations",
            json={
                "candidate_id": "manual_open_fill",
                "page_runtime_ref": "runtime_main",
                "frame_runtime_ref": "frame_main",
            },
        ).json()["reservation_token"]
        event = client.post(
            f"/api/v1/rpa-agent/sessions/{session_id}/manual-events",
            json={
                "reservation_token": token,
                "kind": "input",
                "interaction_kind": "fill",
                "page_runtime_ref": "runtime_main",
                "frame_runtime_ref": "frame_main",
                "target_key": "order-number",
                "target_name": "订单号",
                "target_locators": [
                    {"strategy": "label", "value": "订单号", "exact": True}
                ],
                "observed_at": NOW,
                "value": "PO-OPEN",
                "finish": False,
            },
        )
        assert event.status_code == 200, event.text

        agent = client.post(
            f"/api/v1/rpa-agent/sessions/{session_id}/agent-instructions",
            headers={"Idempotency-Key": "open-fill-agent-001"},
            json={
                "instruction": "继续处理当前订单",
                "business_terms": [],
                "required_variable_refs": [],
                "allowed_inputs": {},
                "allowed_secret_names": [],
                "allowed_data_assets": {},
                "page_aliases": {},
            },
        )
        assert agent.status_code == 202, agent.text
        projection = client.get(
            f"/api/v1/rpa-agent/sessions/{session_id}/projection"
        )
        assert projection.status_code == 200, projection.text
        assert [step["kind"] for step in projection.json()["items"]] == [
            "manual", "ai_instruction"
        ]


def test_failed_test_run_cannot_be_saved(tmp_path: Path) -> None:
    services, _, _ = _services(tmp_path, run_status="failed")
    with _client(services) as client:
        session_id = _start(client)
        _record_one_click(client, session_id)
        assert client.post(f"/api/v1/rpa-agent/sessions/{session_id}/stop").status_code == 200
        assert client.put(
            f"/api/v1/rpa-agent/sessions/{session_id}/configuration",
            json={
                "schema_version": "skill-configuration-draft/v0.1",
                "skill": {"name": "失败回放", "description": "用于验证失败不发布"},
                "inputs": [], "secrets": [], "asset_inputs": [], "outputs": [],
                "asset_outputs": [], "binding_promotions": [],
            },
        ).status_code == 200
        assert client.post(f"/api/v1/rpa-agent/sessions/{session_id}/compile").status_code == 200
        tested = client.post(
            f"/api/v1/rpa-agent/sessions/{session_id}/test-run",
            json={"inputs": {}, "secrets": {}, "data_assets": {}},
        )
        assert tested.status_code == 200
        assert tested.json()["state"] == "compiled"
        assert client.post(f"/api/v1/rpa-agent/sessions/{session_id}/save").status_code == 409


def test_popup_fact_locks_the_explicit_reservation_and_projects_one_effect(tmp_path: Path) -> None:
    services, port, _ = _services(tmp_path)
    with _client(services) as client:
        session_id = _start(client)
        reservation = client.post(
            f"/api/v1/rpa-agent/sessions/{session_id}/manual-reservations",
            json={
                "candidate_id": "manual_open_acceptance",
                "page_runtime_ref": "runtime_main",
                "frame_runtime_ref": "frame_main",
            },
        ).json()
        port.emit(
            "new_page",
            HostBrowserEvent(
                kind="new_page",
                observed_at=datetime(2026, 7, 18, 8, 0, 0, 1000, tzinfo=timezone.utc),
                source_page_runtime_ref="runtime_main",
                source_frame_runtime_ref="frame_main",
                runtime_page_ref="runtime_popup_random",
                detail={"initial_url": "https://eval.invalid/task/random-token"},
            ),
        )
        response = client.post(
            f"/api/v1/rpa-agent/sessions/{session_id}/manual-events",
            json={
                "reservation_token": reservation["reservation_token"],
                "kind": "click",
                "interaction_kind": "click",
                "page_runtime_ref": "runtime_main",
                "frame_runtime_ref": "frame_main",
                "target_key": "acceptance-row",
                "target_name": "发起验收",
                "target_locators": [
                    {"strategy": "role", "role": "button", "name": "发起验收", "exact": True}
                ],
                "observed_at": NOW,
                "finish": True,
            },
        )
        assert response.status_code == 200, response.text
        steps = client.get(
            f"/api/v1/rpa-agent/sessions/{session_id}/projection"
        ).json()["items"]
        assert len(steps) == 1
        assert steps[0]["kind"] == "manual"


def test_reservation_token_is_session_and_scope_bound(tmp_path: Path) -> None:
    services, _, _ = _services(tmp_path)
    with _client(services) as client:
        first = _start(client)
        second = _start(client)
        token = client.post(
            f"/api/v1/rpa-agent/sessions/{first}/manual-reservations",
            json={
                "candidate_id": "manual_first",
                "page_runtime_ref": "runtime_main",
                "frame_runtime_ref": "frame_main",
            },
        ).json()["reservation_token"]
        wrong_scope = client.post(
            f"/api/v1/rpa-agent/sessions/{first}/manual-events",
            json={
                "reservation_token": token,
                "kind": "click", "interaction_kind": "click",
                "page_runtime_ref": "runtime_other", "frame_runtime_ref": "frame_main",
                "target_key": "x", "target_name": "X",
                "target_locators": [{"strategy": "css", "value": "#x"}],
                "observed_at": NOW, "finish": True,
            },
        )
        assert wrong_scope.status_code == 409
        cross_session = client.post(
            f"/api/v1/rpa-agent/sessions/{second}/manual-events",
            json={
                "reservation_token": token,
                "kind": "click", "interaction_kind": "click",
                "page_runtime_ref": "runtime_main", "frame_runtime_ref": "frame_main",
                "target_key": "x", "target_name": "X",
                "target_locators": [{"strategy": "css", "value": "#x"}],
                "observed_at": NOW, "finish": True,
            },
        )
        assert cross_session.status_code == 409


def test_identity_mismatch_is_not_enumerable(tmp_path: Path) -> None:
    services, _, _ = _services(tmp_path)
    app = FastAPI()
    app.include_router(build_router(services), prefix="/api/v1/rpa-agent")
    app.dependency_overrides[require_user] = lambda: User(id="user-1", username="one")
    with TestClient(app) as client:
        session_id = _start(client)
        app.dependency_overrides[require_user] = lambda: User(id="user-2", username="two")
        response = client.get(f"/api/v1/rpa-agent/sessions/{session_id}/projection")
        assert response.status_code == 404
        assert response.json()["detail"]["code"] == "rpa_agent.session_not_found"


def test_concurrent_stop_is_serialized_and_duplicate_is_rejected(tmp_path: Path) -> None:
    services, _, _ = _services(tmp_path)
    with _client(services) as client:
        session_id = _start(client)
        with ThreadPoolExecutor(max_workers=2) as pool:
            responses = list(
                pool.map(
                    lambda _: client.post(
                        f"/api/v1/rpa-agent/sessions/{session_id}/stop"
                    ),
                    range(2),
                )
            )
        assert sorted(response.status_code for response in responses) == [200, 409]


def test_invalid_secret_payload_is_never_mirrored_in_validation_error(tmp_path: Path) -> None:
    services, _, _ = _services(tmp_path)
    with _client(services) as client:
        session_id = _start(client)
        plaintext = "TOP-SECRET-SHOULD-NOT-ECHO"
        response = client.post(
            f"/api/v1/rpa-agent/sessions/{session_id}/test-run",
            json={"inputs": {}, "secrets": {"system.password": [plaintext]}, "data_assets": {}},
        )
        assert response.status_code == 422
        assert plaintext not in response.text
        assert response.json()["detail"]["code"] == "rpa_agent.request_invalid"


def test_ttl_cleanup_releases_browser_listeners(tmp_path: Path) -> None:
    services, port, _ = _services(tmp_path)
    with _client(services) as client:
        _start(client)
    assert services.store is not None
    cleaned = asyncio.run(
        services.store.cleanup_expired(
            now=datetime.now(timezone.utc) + timedelta(days=1)
        )
    )
    assert cleaned == 1
    assert port.release_count == 3


def test_listener_cleanup_does_not_mask_an_existing_primary_error() -> None:
    class BrokenReleasePort(FakeBrowserPort):
        def subscribe(self, kind: str, callback: Callable[[object], None]) -> Callable[[], None]:
            super().subscribe(kind, callback)

            def release() -> None:
                raise RuntimeError("cleanup exploded")

            return release

    port = BrokenReleasePort()
    creation = SkillCreationSession(
        session_id="creation_cleanup",
        main_runtime_ref="runtime_main",
        fact_buffer_capacity=8,
        fact_ttl=timedelta(seconds=5),
    )
    browser = BrowserSession(port=port, creation=creation)
    browser.attach()
    primary = KeyboardInterrupt("primary")
    browser.detach(primary=primary)
    assert browser.cleanup_errors == ["RuntimeError", "RuntimeError", "RuntimeError"]


def test_main_mounts_new_route_without_replacing_legacy_route() -> None:
    from backend.main import create_app

    paths = {route.path for route in create_app().routes}
    assert "/api/v1/rpa-agent/sessions" in paths
    assert any(path.startswith("/api/v1/rpa/") for path in paths)


def test_main_lifespan_cleans_expired_and_closes_all_even_on_app_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import backend.main as main_module
    from backend.rpa import cdp_connector as cdp_module

    class Store:
        def __init__(self) -> None:
            self.cleanup_calls = 0
            self.close_calls = 0

        async def cleanup_expired(self) -> int:
            self.cleanup_calls += 1
            return 0

        async def close_all(self) -> None:
            self.close_calls += 1

    class RuntimeManager:
        async def cleanup_orphans(self) -> int:
            return 0

    async def noop() -> None:
        return None

    async def wait_for_stop(stop_event: asyncio.Event) -> None:
        await stop_event.wait()

    store = Store()
    monkeypatch.setattr(main_module, "init_storage", noop)
    monkeypatch.setattr(main_module, "init_system_models", noop)
    monkeypatch.setattr(main_module, "ensure_admin_user", noop)
    monkeypatch.setattr(
        main_module,
        "migrate_local_admin_assets_to_bootstrap_admin",
        noop,
    )
    monkeypatch.setattr(main_module, "cleanup_orphaned_sessions", noop)
    monkeypatch.setattr(main_module, "graceful_shutdown_agents", noop)
    monkeypatch.setattr(main_module, "close_storage", noop)
    monkeypatch.setattr(
        main_module,
        "get_session_runtime_manager",
        lambda: RuntimeManager(),
    )
    monkeypatch.setattr(main_module, "_runtime_cleanup_loop", wait_for_stop)
    monkeypatch.setattr(cdp_module.cdp_connector, "close", noop)
    monkeypatch.setattr(main_module.rpa_agent_default_services, "store", store)

    async def scenario() -> None:
        async with main_module.lifespan(FastAPI()):
            for _ in range(20):
                if store.cleanup_calls:
                    break
                await asyncio.sleep(0)
            raise RuntimeError("app failed")

    with pytest.raises(RuntimeError, match="app failed"):
        asyncio.run(scenario())
    assert store.cleanup_calls >= 1
    assert store.close_calls == 1


def test_browser_use_dependency_is_exactly_pinned() -> None:
    requirements = (
        Path(__file__).resolve().parents[2] / "requirements.txt"
    ).read_text(encoding="utf-8").splitlines()
    pins = [line.strip() for line in requirements if line.strip().startswith("browser-use")]
    assert pins == ["browser-use==0.13.2"]


def test_playwright_port_observes_navigation_and_download_on_new_pages() -> None:
    class Source:
        def __init__(self) -> None:
            self.listeners: dict[str, list[Callable[..., None]]] = defaultdict(list)

        def on(self, event: str, callback: Callable[..., None]) -> None:
            self.listeners[event].append(callback)

        def remove_listener(self, event: str, callback: Callable[..., None]) -> None:
            self.listeners[event].remove(callback)

        def emit(self, event: str, value: object) -> None:
            for callback in tuple(self.listeners[event]):
                callback(value)

    class Context(Source):
        def __init__(self, main: object) -> None:
            super().__init__()
            self.pages = [main]

    class Page(Source):
        def __init__(self, ref: str, opener_ref: str | None = None) -> None:
            super().__init__()
            self.ref = ref
            self.opener_ref = opener_ref
            self.url = f"https://eval.invalid/{ref}"

    class Frame:
        parent_frame = None

        def __init__(self, page: Page, ref: str) -> None:
            self.page = page
            self.ref = ref
            self.url = page.url

    main = Page("runtime_main")
    popup = Page("runtime_popup", "runtime_main")
    nested_popup = Page("runtime_nested", "runtime_popup")
    context = Context(main)
    port = PlaywrightBrowserSessionPort(
        context=context,
        main_page=main,
        main_page_runtime_ref="runtime_main",
        main_frame_runtime_ref="frame_main",
        page_runtime_ref=lambda page: page.ref,
        frame_runtime_ref=lambda frame: frame.ref,
        frame_path=lambda _page, _frame: (),
        page_main_frame_runtime_ref=lambda page: "frame_" + page.ref,
    )
    events: list[HostBrowserEvent] = []
    releases = [
        port.subscribe("navigation", events.append),
        port.subscribe("new_page", events.append),
        port.subscribe("download", events.append),
    ]

    context.pages.append(popup)
    main.emit("popup", popup)
    assert len(popup.listeners["framenavigated"]) == 1
    assert len(popup.listeners["download"]) == 1
    popup.emit("framenavigated", Frame(popup, "frame_popup"))
    assert [(event.kind, event.runtime_page_ref) for event in events] == [
        ("new_page", "runtime_popup"),
        ("navigation", "runtime_popup"),
    ]
    context.pages.append(nested_popup)
    popup.emit("popup", nested_popup)
    assert events[-1].source_page_runtime_ref == "runtime_popup"
    assert events[-1].source_frame_runtime_ref == "frame_runtime_popup"

    for release in releases:
        release()
    assert not popup.listeners["framenavigated"]
    assert not popup.listeners["download"]


def test_download_locks_candidate_before_delayed_failure_and_control_switch() -> None:
    class Source:
        def __init__(self) -> None:
            self.listeners: dict[str, list[Callable[..., None]]] = defaultdict(list)

        def on(self, event: str, callback: Callable[..., None]) -> None:
            self.listeners[event].append(callback)

        def remove_listener(self, event: str, callback: Callable[..., None]) -> None:
            self.listeners[event].remove(callback)

        def emit(self, event: str, value: object) -> None:
            for callback in tuple(self.listeners[event]):
                callback(value)

    class Page(Source):
        def __init__(self) -> None:
            super().__init__()
            self.ref = "runtime_main"
            self.url = "https://eval.invalid/orders"
            self.main_frame = Frame(self)

    class Frame:
        parent_frame = None

        def __init__(self, page: Page) -> None:
            self.page = page
            self.ref = "frame_main"
            self.url = page.url

    class Context:
        def __init__(self, page: Page) -> None:
            self.pages = [page]

    async def scenario() -> None:
        failure_ready = asyncio.Event()

        class Download:
            suggested_filename = "orders.csv"

            async def failure(self) -> None:
                await failure_ready.wait()
                return None

        page = Page()
        port = PlaywrightBrowserSessionPort(
            context=Context(page),
            main_page=page,
            main_page_runtime_ref="runtime_main",
            main_frame_runtime_ref="frame_main",
            page_runtime_ref=lambda target: target.ref,
            frame_runtime_ref=lambda target: target.ref,
            frame_path=lambda _page, _frame: (),
            page_main_frame_runtime_ref=lambda target: target.main_frame.ref,
        )
        creation = SkillCreationSession(
            session_id="creation_download_delay",
            main_runtime_ref="runtime_main",
            fact_buffer_capacity=8,
            fact_ttl=timedelta(seconds=30),
        )
        browser = BrowserSession(port=port, creation=creation)
        browser.attach()
        settle_calls: list[str] = []
        original_settle = creation.settle_candidate

        def counting_settle(candidate_id: str, **kwargs: object):
            settle_calls.append(candidate_id)
            return original_settle(candidate_id, **kwargs)

        creation.settle_candidate = counting_settle  # type: ignore[method-assign]
        token = browser.reserve_manual(
            candidate_id="manual_download",
            page_runtime_ref="runtime_main",
            frame_runtime_ref="frame_main",
        )

        page.emit("download", Download())
        assert creation.observer.pending_count == 1

        browser.ingest_manual(
            token=token,
            event=browser.manual_event_from_payload(
                type(
                    "Payload",
                    (),
                    {
                        "kind": "click",
                        "page_runtime_ref": "runtime_main",
                        "frame_runtime_ref": "frame_main",
                        "target_key": "download-orders",
                        "target_name": "下载订单",
                        "target_locators": (
                            {
                                "strategy": "role",
                                "role": "button",
                                "name": "下载订单",
                                "exact": True,
                            },
                        ),
                        "interaction_kind": "click",
                        "observed_at": datetime.now(timezone.utc),
                        "target_path": (),
                        "binding_hints": (
                            {
                                "name": "downloaded_file",
                                "direction": "output",
                                "kind_hint": "data_asset",
                                "ref_hint": "asset_orders",
                                "sensitive": False,
                            },
                        ),
                        "value": None,
                        "checked": None,
                    },
                )()
            ),
            finish=True,
        )
        creation.switch_control(ControlMode.AGENT, at=datetime.now(timezone.utc))
        assert settle_calls == []
        assert "manual_download" not in creation.accepted_traces

        failure_ready.set()
        await browser.drain_pending_facts(timeout=1)
        fact = creation.fact_buffer.facts()[0]
        assert fact.candidate_id == "manual_download"
        assert fact.detail.status == "completed"
        assert creation.observer.pending_count == 0
        assert settle_calls == ["manual_download"]
        trace = creation.accepted_traces["manual_download"]
        assert [effect.kind for effect in trace.effects] == ["download"]
        assert trace.effects[0].binding == "downloaded_file"

    asyncio.run(scenario())


def test_multiple_pending_downloads_settle_candidate_only_after_the_last_one() -> None:
    async def scenario() -> None:
        first_ready = asyncio.Event()
        second_ready = asyncio.Event()

        async def completion(ready: asyncio.Event) -> None:
            await ready.wait()

        port = FakeBrowserPort()
        creation = SkillCreationSession(
            session_id="creation_multiple_downloads",
            main_runtime_ref="runtime_main",
            fact_buffer_capacity=8,
            fact_ttl=timedelta(seconds=30),
        )
        browser = BrowserSession(port=port, creation=creation)
        browser.attach()
        settle_calls: list[str] = []
        original_settle = creation.settle_candidate

        def counting_settle(candidate_id: str, **kwargs: object):
            settle_calls.append(candidate_id)
            return original_settle(candidate_id, **kwargs)

        creation.settle_candidate = counting_settle  # type: ignore[method-assign]
        token = browser.reserve_manual(
            candidate_id="manual_multiple_downloads",
            page_runtime_ref="runtime_main",
            frame_runtime_ref="frame_main",
        )
        for download_ref, ready in (
            ("download_first", first_ready),
            ("download_second", second_ready),
        ):
            browser.handle_event(
                HostDownloadEvent(
                    observed_at=datetime.now(timezone.utc),
                    source_page_runtime_ref="runtime_main",
                    source_frame_runtime_ref="frame_main",
                    runtime_page_ref="runtime_main",
                    download_ref=download_ref,
                    suggested_filename=f"{download_ref}.csv",
                    failure=completion(ready),
                )
            )
        event = browser.manual_event_from_payload(
            type(
                "Payload",
                (),
                {
                    "kind": "click",
                    "page_runtime_ref": "runtime_main",
                    "frame_runtime_ref": "frame_main",
                    "target_key": "download-orders",
                    "target_name": "下载订单",
                    "target_locators": (
                        {
                            "strategy": "role",
                            "role": "button",
                            "name": "下载订单",
                            "exact": True,
                        },
                    ),
                    "interaction_kind": "click",
                    "observed_at": datetime.now(timezone.utc),
                    "target_path": (),
                    "binding_hints": (
                        {
                            "name": "downloaded_file",
                            "direction": "output",
                            "kind_hint": "data_asset",
                            "ref_hint": "asset_orders",
                            "sensitive": False,
                        },
                    ),
                    "value": None,
                    "checked": None,
                },
            )()
        )
        browser.ingest_manual(token=token, event=event, finish=True)
        assert settle_calls == []

        first_ready.set()
        for _ in range(20):
            if creation.observer.pending_count == 1:
                break
            await asyncio.sleep(0)
        assert settle_calls == []

        second_ready.set()
        await browser.drain_pending_facts(timeout=1)
        assert settle_calls == ["manual_multiple_downloads"]
        assert "manual_multiple_downloads" in creation.diagnostics

    asyncio.run(scenario())


def test_stop_waits_for_a_prelocked_download_before_building_the_draft(
    tmp_path: Path,
) -> None:
    services, port, _ = _services(tmp_path)
    app = FastAPI()
    app.include_router(build_router(services), prefix="/api/v1/rpa-agent")
    app.dependency_overrides[require_user] = lambda: User(
        id="user-1", username="tester", role="user"
    )

    async def scenario() -> None:
        completion_ready = asyncio.Event()

        async def completion() -> None:
            await completion_ready.wait()

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            started = await client.post(
                "/api/v1/rpa-agent/sessions",
                json={},
            )
            payload = started.json()
            token = (
                await client.post(
                    f"/api/v1/rpa-agent/sessions/{payload['session_id']}/manual-reservations",
                    json={
                        "candidate_id": "manual_stop_download",
                        "page_runtime_ref": "runtime_main",
                        "frame_runtime_ref": "frame_main",
                    },
                )
            ).json()["reservation_token"]
            port.emit(
                "download",
                HostDownloadEvent(
                    observed_at=datetime.now(timezone.utc),
                    source_page_runtime_ref="runtime_main",
                    source_frame_runtime_ref="frame_main",
                    runtime_page_ref="runtime_main",
                    download_ref="download_stop",
                    suggested_filename="orders.csv",
                    failure=completion(),
                ),
            )
            manual = await client.post(
                f"/api/v1/rpa-agent/sessions/{payload['session_id']}/manual-events",
                json={
                    "reservation_token": token,
                    "kind": "click",
                    "interaction_kind": "click",
                    "page_runtime_ref": "runtime_main",
                    "frame_runtime_ref": "frame_main",
                    "target_key": "download-orders",
                    "target_name": "下载订单",
                    "target_locators": [
                        {
                            "strategy": "role",
                            "role": "button",
                            "name": "下载订单",
                            "exact": True,
                        }
                    ],
                    "binding_hints": [
                        {
                            "name": "downloaded_file",
                            "direction": "output",
                            "kind_hint": "data_asset",
                            "ref_hint": "asset_orders",
                            "sensitive": False,
                        }
                    ],
                    "observed_at": datetime.now(timezone.utc).isoformat(),
                    "finish": True,
                },
            )
            assert manual.status_code == 200, manual.text
            stop_task = asyncio.create_task(
                client.post(
                    f"/api/v1/rpa-agent/sessions/{payload['session_id']}/stop"
                )
            )
            await asyncio.sleep(0)
            assert not stop_task.done()
            completion_ready.set()
            stopped = await stop_task
            assert stopped.status_code == 200, stopped.text
            assert stopped.json()["state"] == "stopped"

            assert services.store is not None
            async with services.store.use(
                payload["session_id"], owner_id="user-1"
            ) as hosted:
                trace = hosted.browser.creation.accepted_traces[
                    "manual_stop_download"
                ]
                assert [effect.kind for effect in trace.effects] == ["download"]

    asyncio.run(scenario())


def test_stop_drain_failure_keeps_recording_attached_and_retryable(
    tmp_path: Path,
) -> None:
    services, port, _ = _services(tmp_path)
    app = FastAPI()
    app.include_router(build_router(services), prefix="/api/v1/rpa-agent")
    app.dependency_overrides[require_user] = lambda: User(
        id="user-1", username="tester", role="user"
    )

    async def scenario() -> None:
        completion_ready = asyncio.Event()

        async def completion() -> None:
            await completion_ready.wait()

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            started = await client.post(
                "/api/v1/rpa-agent/sessions",
                json={},
            )
            payload = started.json()
            token = (
                await client.post(
                    f"/api/v1/rpa-agent/sessions/{payload['session_id']}/manual-reservations",
                    json={
                        "candidate_id": "manual_retry_download",
                        "page_runtime_ref": "runtime_main",
                        "frame_runtime_ref": "frame_main",
                    },
                )
            ).json()["reservation_token"]
            port.emit(
                "download",
                HostDownloadEvent(
                    observed_at=datetime.now(timezone.utc),
                    source_page_runtime_ref="runtime_main",
                    source_frame_runtime_ref="frame_main",
                    runtime_page_ref="runtime_main",
                    download_ref="download_retry",
                    suggested_filename="orders.csv",
                    failure=completion(),
                ),
            )
            manual = await client.post(
                f"/api/v1/rpa-agent/sessions/{payload['session_id']}/manual-events",
                json={
                    "reservation_token": token,
                    "kind": "click",
                    "interaction_kind": "click",
                    "page_runtime_ref": "runtime_main",
                    "frame_runtime_ref": "frame_main",
                    "target_key": "download-orders",
                    "target_name": "下载订单",
                    "target_locators": [
                        {
                            "strategy": "role",
                            "role": "button",
                            "name": "下载订单",
                            "exact": True,
                        }
                    ],
                    "binding_hints": [
                        {
                            "name": "downloaded_file",
                            "direction": "output",
                            "kind_hint": "data_asset",
                            "ref_hint": "asset_orders",
                            "sensitive": False,
                        }
                    ],
                    "observed_at": datetime.now(timezone.utc).isoformat(),
                    "finish": True,
                },
            )
            assert manual.status_code == 200, manual.text

            assert services.store is not None
            async with services.store.use(
                payload["session_id"], owner_id="user-1"
            ) as hosted:
                original_drain = hosted.browser.drain_pending_facts

                async def timeout_once(*, timeout: float) -> None:
                    del timeout
                    raise ValueError("browser_session.pending_fact_timeout")

                hosted.browser.drain_pending_facts = timeout_once  # type: ignore[method-assign]

            failed = await client.post(
                f"/api/v1/rpa-agent/sessions/{payload['session_id']}/stop"
            )
            assert failed.status_code == 409, failed.text
            async with services.store.use(
                payload["session_id"], owner_id="user-1"
            ) as hosted:
                assert hosted.state.value == "recording"
                assert hosted.browser.creation.control_mode is ControlMode.HUMAN
                assert port.release_count == 0
                hosted.browser.drain_pending_facts = original_drain  # type: ignore[method-assign]

            completion_ready.set()
            retried = await client.post(
                f"/api/v1/rpa-agent/sessions/{payload['session_id']}/stop"
            )
            assert retried.status_code == 200, retried.text
            assert retried.json()["state"] == "stopped"

    asyncio.run(scenario())


def test_cleanup_expired_skips_an_active_use_and_session_remains_available(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        port = FakeBrowserPort()
        creation = SkillCreationSession(
            session_id="creation_active_cleanup",
            main_runtime_ref="runtime_main",
            fact_buffer_capacity=8,
            fact_ttl=timedelta(seconds=30),
        )
        browser = BrowserSession(port=port, creation=creation)
        browser.attach()
        store = SessionStore(ttl=timedelta(seconds=1))
        hosted = await store.create(
            owner_id="user-1",
            browser_session_ref="browser-workbench-1",
            browser=browser,
            artifact_dir=tmp_path,
        )
        cleanup_task: asyncio.Task[int]
        timed_out = False
        async with store.use(hosted.session_id, owner_id="user-1"):
            cleanup_task = asyncio.create_task(
                store.cleanup_expired(
                    now=datetime.now(timezone.utc) + timedelta(days=1)
                )
            )
            try:
                cleaned = await asyncio.wait_for(
                    asyncio.shield(cleanup_task), timeout=0.05
                )
            except asyncio.TimeoutError:
                timed_out = True
                cleaned = -1
        if not cleanup_task.done():
            await cleanup_task
        assert not timed_out
        assert cleaned == 0
        async with store.use(hosted.session_id, owner_id="user-1") as available:
            assert available.state.value == "recording"
        await store.close_all()

    asyncio.run(scenario())


def test_sanitize_redacts_secret_substrings_recursively() -> None:
    sanitized = _sanitize(
        {
            "message": "Bearer TOPSECRET and SECRET",
            "nested": [
                "prefix TOPSECRET suffix",
                {"key-TOPSECRET": RuntimeError("transport SECRET failed")},
            ],
            "empty": "ordinary text",
        },
        secret_values=frozenset({"TOPSECRET", "SECRET", ""}),
    )
    rendered = str(sanitized)
    assert "TOPSECRET" not in rendered
    assert "SECRET" not in rendered
    assert "Bearer [REDACTED]" in rendered
    assert "ordinary text" in rendered


def test_api_dto_containers_have_explicit_upper_bounds() -> None:
    with pytest.raises(ValidationError):
        AgentInstructionRequest.model_validate(
            {
                "instruction": "inspect",
                "business_terms": [f"term-{index}" for index in range(65)],
                "required_variable_refs": [],
                "allowed_inputs": {},
                "allowed_secret_names": [],
                "allowed_data_assets": {},
                "page_aliases": {},
            }
        )
    with pytest.raises(ValidationError):
        ManualEventRequest.model_validate(
            {
                "reservation_token": "x" * 32,
                "kind": "click",
                "interaction_kind": "click",
                "page_runtime_ref": "runtime_main",
                "frame_runtime_ref": "frame_main",
                "target_key": "button",
                "target_name": "Button",
                "target_locators": [
                    {"strategy": "css", "value": f"#button-{index}"}
                    for index in range(33)
                ],
                "observed_at": NOW,
            }
        )
    with pytest.raises(ValidationError):
        ApiTestRunRequest.model_validate(
            {
                "inputs": {f"input_{index}": index for index in range(257)},
                "secrets": {},
                "data_assets": {},
            }
        )


def test_agent_instruction_dto_accepts_business_variable_path() -> None:
    request = AgentInstructionRequest.model_validate(
        {
            "instruction": "提取采购订单字段",
            "business_terms": ["采购订单"],
            "required_variable_refs": ["采购订单.订单号", "采购订单.供应商"],
            "allowed_inputs": {},
            "allowed_secret_names": [],
            "allowed_data_assets": {},
            "page_aliases": {},
        }
    )
    assert request.required_variable_refs == ["采购订单.订单号", "采购订单.供应商"]


@pytest.mark.parametrize(
    "variable_ref",
    ["", "采购订单..订单号", ".采购订单", "采购订单.", "采购订单.123.订单号"],
)
def test_agent_instruction_dto_rejects_invalid_business_variable_path(
    variable_ref: str,
) -> None:
    with pytest.raises(ValidationError):
        AgentInstructionRequest.model_validate(
            {
                "instruction": "提取采购订单字段",
                "business_terms": [],
                "required_variable_refs": [variable_ref],
                "allowed_inputs": {},
                "allowed_secret_names": [],
                "allowed_data_assets": {},
                "page_aliases": {},
            }
        )


def test_agent_instruction_route_accepts_business_variable_path(tmp_path: Path) -> None:
    services, _, _ = _services(tmp_path)
    with _client(services) as client:
        session_id = _start(client)
        response = client.post(
            f"/api/v1/rpa-agent/sessions/{session_id}/agent-instructions",
            headers={"Idempotency-Key": "business-variable-001"},
            json={
                "instruction": "提取采购订单字段",
                "business_terms": ["采购订单"],
                "required_variable_refs": ["采购订单.订单号", "采购订单.供应商"],
                "allowed_inputs": {},
                "allowed_secret_names": [],
                "allowed_data_assets": {},
                "page_aliases": {},
            },
        )
        assert response.status_code == 202, response.text
        assert response.json()["execution_status"] == "queued"


def test_test_run_rejects_tampered_compiled_files_before_runtime(
    tmp_path: Path,
) -> None:
    services, _, _ = _services(tmp_path)
    runtime_calls = 0

    async def runtime_runner(_session: object, _request: object) -> dict[str, Any]:
        nonlocal runtime_calls
        runtime_calls += 1
        return {"status": "succeeded", "outputs": {}}

    services.runtime_runner = runtime_runner
    with _client(services) as client:
        session_id = _start(client)
        _compile_minimal_skill(client, session_id)
        artifact = tmp_path / "artifacts" / session_id / "skill.py"
        artifact.write_text(
            artifact.read_text(encoding="utf-8") + "\n# tampered\n",
            encoding="utf-8",
        )
        response = client.post(
            f"/api/v1/rpa-agent/sessions/{session_id}/test-run",
            json={"inputs": {}, "secrets": {}, "data_assets": {}},
        )
        assert response.status_code == 409, response.text
        assert response.json()["detail"]["code"] == "rpa_agent.artifact_changed"
        assert runtime_calls == 0


@pytest.mark.parametrize("mutation", ["missing", "directory"])
def test_test_run_rejects_missing_or_replaced_required_artifact(
    tmp_path: Path,
    mutation: str,
) -> None:
    services, _, _ = _services(tmp_path)
    runtime_calls = 0

    async def runtime_runner(_session: object, _request: object) -> dict[str, Any]:
        nonlocal runtime_calls
        runtime_calls += 1
        return {"status": "succeeded", "outputs": {}}

    services.runtime_runner = runtime_runner
    with _client(services) as client:
        session_id = _start(client)
        _compile_minimal_skill(client, session_id)
        artifact = tmp_path / "artifacts" / session_id / "skill.py"
        artifact.unlink()
        if mutation == "directory":
            artifact.mkdir()

        response = client.post(
            f"/api/v1/rpa-agent/sessions/{session_id}/test-run",
            json={"inputs": {}, "secrets": {}, "data_assets": {}},
        )
        assert response.status_code == 409, response.text
        assert response.json()["detail"]["code"] == "rpa_agent.artifact_changed"
        assert runtime_calls == 0


def test_test_run_rejects_required_artifact_changed_during_runtime_without_state_leak(
    tmp_path: Path,
) -> None:
    services, _, _ = _services(tmp_path)

    async def runtime_runner(session: object, _request: object) -> dict[str, Any]:
        artifact = getattr(session, "artifact_dir") / "skill.py"
        artifact.write_text(
            artifact.read_text(encoding="utf-8") + "\n# runtime tamper\n",
            encoding="utf-8",
        )
        return {"status": "succeeded", "outputs": {"leaked": True}}

    services.runtime_runner = runtime_runner
    with _client(services) as client:
        session_id = _start(client)
        _compile_minimal_skill(client, session_id)
        response = client.post(
            f"/api/v1/rpa-agent/sessions/{session_id}/test-run",
            json={"inputs": {}, "secrets": {}, "data_assets": {}},
        )
        assert response.status_code == 409, response.text
        assert response.json()["detail"]["code"] == "rpa_agent.artifact_changed"

        async def assert_session_unchanged() -> None:
            assert services.store is not None
            async with services.store.use(session_id, owner_id="user-1") as hosted:
                assert hosted.state is SessionState.COMPILED
                assert hosted.run_result is None
                assert hosted.test_passed is False

        asyncio.run(assert_session_unchanged())


def test_save_rejects_files_tampered_after_successful_test(
    tmp_path: Path,
) -> None:
    services, _, publisher = _services(tmp_path)
    with _client(services) as client:
        session_id = _start(client)
        _compile_minimal_skill(client, session_id)
        tested = client.post(
            f"/api/v1/rpa-agent/sessions/{session_id}/test-run",
            json={"inputs": {}, "secrets": {}, "data_assets": {}},
        )
        assert tested.status_code == 200, tested.text
        artifact = tmp_path / "artifacts" / session_id / "SKILL.md"
        artifact.write_text("tampered", encoding="utf-8")
        response = client.post(f"/api/v1/rpa-agent/sessions/{session_id}/save")
        assert response.status_code == 409, response.text
        assert response.json()["detail"]["code"] == "rpa_agent.artifact_changed"
        assert publisher.calls == 0


def test_save_allows_runtime_cache_created_during_successful_test_run(
    tmp_path: Path,
) -> None:
    services, _, publisher = _services(tmp_path)

    async def runtime_runner(session: object, _request: object) -> dict[str, Any]:
        artifact_dir = getattr(session, "artifact_dir")
        cache_dir = artifact_dir / "__pycache__"
        cache_dir.mkdir()
        (cache_dir / "skill.cpython-314.pyc").write_bytes(b"runtime cache")
        return {"status": "succeeded", "outputs": {}}

    services.runtime_runner = runtime_runner
    with _client(services) as client:
        session_id = _start(client)
        _compile_minimal_skill(client, session_id)
        tested = client.post(
            f"/api/v1/rpa-agent/sessions/{session_id}/test-run",
            json={"inputs": {}, "secrets": {}, "data_assets": {}},
        )
        assert tested.status_code == 200, tested.text

        response = client.post(f"/api/v1/rpa-agent/sessions/{session_id}/save")
        assert response.status_code == 200, response.text
        assert response.json()["state"] == "saved"
        assert publisher.calls == 1


@pytest.mark.parametrize("operation", ["ttl", "close_all"])
def test_store_cleanup_cancels_and_drains_pending_browser_fact_tasks(
    tmp_path: Path,
    operation: str,
) -> None:
    async def scenario() -> None:
        cancelled = asyncio.Event()
        never = asyncio.Event()

        async def completion() -> None:
            try:
                await never.wait()
            except asyncio.CancelledError:
                cancelled.set()
                raise

        port = FakeBrowserPort()
        creation = SkillCreationSession(
            session_id=f"creation_cleanup_{operation}",
            main_runtime_ref="runtime_main",
            fact_buffer_capacity=8,
            fact_ttl=timedelta(seconds=30),
        )
        browser = BrowserSession(port=port, creation=creation)
        browser.attach()
        browser.handle_event(
            HostDownloadEvent(
                observed_at=datetime.now(timezone.utc),
                source_page_runtime_ref="runtime_main",
                source_frame_runtime_ref="frame_main",
                runtime_page_ref="runtime_main",
                download_ref=f"download_cleanup_{operation}",
                suggested_filename="orders.csv",
                failure=completion(),
            )
        )
        await asyncio.sleep(0)
        store = SessionStore(ttl=timedelta(seconds=1))
        await store.create(
            owner_id="user-1",
            browser_session_ref="browser-workbench-1",
            browser=browser,
            artifact_dir=tmp_path,
        )
        if operation == "ttl":
            cleaned = await store.cleanup_expired(
                now=datetime.now(timezone.utc) + timedelta(seconds=2)
            )
            assert cleaned == 1
        else:
            await store.close_all()
        assert cancelled.is_set()
        assert browser.background_task_count == 0
        assert creation.closed

    asyncio.run(scenario())


def test_default_provider_resolves_popup_main_and_named_iframe_without_guessing(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    class Source:
        def __init__(self) -> None:
            self.listeners: dict[str, list[Callable[..., None]]] = defaultdict(list)

        def on(self, event: str, callback: Callable[..., None]) -> None:
            self.listeners[event].append(callback)

        def remove_listener(self, event: str, callback: Callable[..., None]) -> None:
            self.listeners[event].remove(callback)

        def emit(self, event: str, value: object) -> None:
            for callback in tuple(self.listeners[event]):
                callback(value)

    class Frame:
        def __init__(
            self,
            page: Page,
            *,
            name: str,
            parent_frame: Frame | None,
        ) -> None:
            self.page = page
            self.name = name
            self.parent_frame = parent_frame
            self.url = page.url

    class Page(Source):
        def __init__(self, ref: str) -> None:
            super().__init__()
            self.ref = ref
            self.url = f"https://eval.invalid/{ref}"
            self.main_frame = Frame(self, name="", parent_frame=None)

    class Context:
        def __init__(self, main: Page) -> None:
            self.pages = [main]

    main = Page("main")
    popup = Page("popup")
    context = Context(main)
    main.context = context
    popup.context = context
    named_frame = Frame(
        popup,
        name='acceptance"form\\v1',
        parent_frame=popup.main_frame,
    )
    unnamed_frame = Frame(popup, name="", parent_frame=popup.main_frame)

    from backend import browser_preview
    from backend.rpa_agent.host import scienceclaw_browser
    from backend.runtime import ownership

    async def owned(_browser_ref: str, _owner_id: str) -> bool:
        return True

    monkeypatch.setattr(ownership, "user_owns_runtime_session", owned)
    monkeypatch.setattr(
        browser_preview.browser_preview_registry,
        "get_active_page",
        lambda _browser_ref: main,
    )

    class Lease:
        page = main
        cdp_url = "ws://runtime.test/devtools/browser/provider-test"

        async def aclose(self) -> None:
            return None

    async def acquire(**_kwargs):
        return Lease()

    monkeypatch.setattr(
        scienceclaw_browser,
        "acquire_browser_runtime_lease",
        acquire,
    )

    async def scenario() -> None:
        port = await _scienceclaw_browser_provider("owner-1", "7browser")
        events: list[HostBrowserEvent] = []
        port.subscribe("new_page", events.append)
        port.subscribe("navigation", events.append)

        context.pages.append(popup)
        main.emit("popup", popup)
        popup.emit("framenavigated", popup.main_frame)
        popup_main_event = events[-1]
        popup_main_frame_ref = str(popup_main_event.detail["frame_runtime_ref"])
        assert port.resolve_frame_path(
            popup_main_event.runtime_page_ref,
            popup_main_frame_ref,
        ) == ()

        popup.emit("framenavigated", named_frame)
        named_event = events[-1]
        assert port.resolve_frame_path(
            named_event.runtime_page_ref,
            str(named_event.detail["frame_runtime_ref"]),
        ) == (
            {
                "name": 'acceptance"form\\v1',
                "locators": [
                    {
                        "strategy": "css",
                        "value": 'iframe[name="acceptance\\"form\\\\v1"]',
                    }
                ],
            },
        )

        popup.emit("framenavigated", unnamed_frame)
        unnamed_event = events[-1]
        with pytest.raises(
            ValueError,
            match="browser_host.frame_locator_unavailable",
        ):
            port.resolve_frame_path(
                unnamed_event.runtime_page_ref,
                str(unnamed_event.detail["frame_runtime_ref"]),
            )

        captured_ports: list[PlaywrightBrowserSessionPort] = []

        async def provider(owner_id: str, browser_ref: str):
            captured = await _scienceclaw_browser_provider(owner_id, browser_ref)
            captured_ports.append(captured)
            return captured

        services = RpaAgentApiServices(
            artifact_root=tmp_path / "artifacts",
            browser_provider=provider,
        )
        app = FastAPI()
        app.include_router(build_router(services), prefix="/api/v1/rpa-agent")
        app.dependency_overrides[require_user] = lambda: User(
            id="owner-1",
            username="tester",
            role="user",
        )
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            started = await client.post(
                "/api/v1/rpa-agent/sessions",
                json={},
            )
            assert started.status_code == 201, started.text
            payload = started.json()
            assert payload["page_ref"] == captured_ports[0].main_page_runtime_ref
            reserved = await client.post(
                f"/api/v1/rpa-agent/sessions/{payload['session_id']}/manual-reservations",
                json={
                    "candidate_id": "manual_default_round_trip",
                    "page_runtime_ref": captured_ports[0].main_page_runtime_ref,
                    "frame_runtime_ref": captured_ports[0].main_frame_runtime_ref,
                },
            )
            assert reserved.status_code == 201, reserved.text
        assert services.store is not None
        await services.store.close_all()

    asyncio.run(scenario())


def test_default_provider_uses_neutral_local_cdp_resolver_in_local_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backend import browser_preview
    from backend.rpa_agent import host
    from backend.rpa_agent.host import scienceclaw_browser
    from backend.runtime import local_cdp, ownership

    captured: dict[str, object] = {}

    async def owned(_browser_ref: str, _owner_id: str) -> bool:
        return True

    class Page:
        context = object()
        main_frame = object()

    class Lease:
        page = Page()
        cdp_url = "ws://127.0.0.1:19222/devtools/browser/local"

        async def aclose(self) -> None:
            return None

    async def acquire(**kwargs):
        captured.update(kwargs)
        return Lease()

    class Connector:
        async def get_cdp_url(self) -> str:
            captured["connector_called"] = True
            return Lease.cdp_url

    monkeypatch.setattr(settings, "storage_backend", "local")
    monkeypatch.setattr(ownership, "user_owns_runtime_session", owned)
    monkeypatch.setattr(local_cdp, "local_cdp_connector", Connector())
    monkeypatch.setattr(
        browser_preview.browser_preview_registry,
        "get_active_page",
        lambda _browser_ref: Lease.page,
    )
    monkeypatch.setattr(
        scienceclaw_browser,
        "acquire_browser_runtime_lease",
        acquire,
    )
    monkeypatch.setattr(host, "PlaywrightBrowserSessionPort", lambda **kwargs: kwargs)

    async def scenario() -> None:
        await _scienceclaw_browser_provider("owner-1", "7browser")
        resolver = captured.get("resolve_cdp_url")
        assert callable(resolver)
        assert await resolver("7browser", "owner-1") == Lease.cdp_url

    asyncio.run(scenario())
    assert captured["connector_called"] is True


def test_default_provider_keeps_session_runtime_path_outside_local_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backend import browser_preview
    from backend.rpa_agent import host
    from backend.rpa_agent.host import scienceclaw_browser
    from backend.runtime import ownership

    captured: dict[str, object] = {}

    async def owned(_browser_ref: str, _owner_id: str) -> bool:
        return True

    class Page:
        context = object()
        main_frame = object()

    class Lease:
        page = Page()
        cdp_url = "ws://runtime.test/devtools/browser/remote"

        async def aclose(self) -> None:
            return None

    async def acquire(**kwargs):
        captured.update(kwargs)
        return Lease()

    monkeypatch.setattr(settings, "storage_backend", "mongo")
    monkeypatch.setattr(ownership, "user_owns_runtime_session", owned)
    monkeypatch.setattr(
        browser_preview.browser_preview_registry,
        "get_active_page",
        lambda _browser_ref: Lease.page,
    )
    monkeypatch.setattr(
        scienceclaw_browser,
        "acquire_browser_runtime_lease",
        acquire,
    )
    monkeypatch.setattr(host, "PlaywrightBrowserSessionPort", lambda **kwargs: kwargs)

    asyncio.run(_scienceclaw_browser_provider("owner-1", "7browser"))
    assert captured.get("resolve_cdp_url") is None


def test_agent_cancellation_preserves_identity_and_restores_human_control(tmp_path: Path) -> None:
    services, _, _ = _services(tmp_path)

    async def cancelled(_session: object, _request: object) -> RecordingRoundReport:
        raise asyncio.CancelledError()

    services.agent_executor = cancelled
    app = FastAPI()
    app.include_router(build_router(services), prefix="/api/v1/rpa-agent")
    app.dependency_overrides[require_user] = lambda: User(
        id="user-1", username="tester", role="user"
    )

    async def scenario() -> None:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            created = await client.post(
                "/api/v1/rpa-agent/sessions",
                json={},
            )
            session_id = created.json()["session_id"]
            admitted = await client.post(
                f"/api/v1/rpa-agent/sessions/{session_id}/agent-instructions",
                headers={"Idempotency-Key": "cancel-agent-key-001"},
                json={
                    "instruction": "取消本轮",
                    "business_terms": [], "required_variable_refs": [],
                    "allowed_inputs": {}, "allowed_secret_names": [],
                    "allowed_data_assets": {}, "page_aliases": {},
                },
            )
            assert admitted.status_code == 202
            for _ in range(100):
                projection = await client.get(
                    f"/api/v1/rpa-agent/sessions/{session_id}/projection"
                )
                if projection.json()["items"][0]["execution_status"] == "cancelled":
                    break
                await asyncio.sleep(0.01)
            assert projection.json()["items"][0]["execution_status"] == "cancelled"
            assert services.store is not None
            async with services.store.use(session_id, owner_id="user-1") as hosted:
                assert hosted.browser.creation.control_mode.value == "human"
                assert hosted.state.value == "recording"

    asyncio.run(scenario())


def test_agent_admission_is_immediate_idempotent_and_does_not_block_projection(
    tmp_path: Path,
) -> None:
    services, _, _ = _services(tmp_path)
    started = asyncio.Event()
    release = asyncio.Event()

    async def blocking_agent(_session: object, _request: object) -> object:
        started.set()
        await release.wait()
        return object()

    services.agent_executor = blocking_agent
    app = FastAPI()
    app.include_router(build_router(services), prefix="/api/v1/rpa-agent")
    app.dependency_overrides[require_user] = lambda: User(
        id="user-1", username="tester", role="user"
    )

    async def scenario() -> None:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            created = await client.post(
                "/api/v1/rpa-agent/sessions",
                json={},
            )
            session_id = created.json()["session_id"]
            url = f"/api/v1/rpa-agent/sessions/{session_id}/agent-instructions"
            request = {"instruction": "打开和 skill 最相关的项目"}
            headers = {"Idempotency-Key": "agent-key-0000001"}

            admitted = await client.post(url, json=request, headers=headers)
            assert admitted.status_code == 202, admitted.text
            step_id = admitted.json()["step_id"]
            assert admitted.json()["execution_status"] == "queued"

            await asyncio.wait_for(started.wait(), timeout=1)
            projection = await asyncio.wait_for(
                client.get(f"/api/v1/rpa-agent/sessions/{session_id}/projection"),
                timeout=1,
            )
            assert projection.status_code == 200, projection.text
            assert projection.json()["items"] == [
                {
                    "id": step_id,
                    "kind": "ai_instruction",
                    "ordinal": 1,
                    "title": request["instruction"],
                    "capture_status": "observing",
                    "execution_status": "running",
                    "replay_status": "pending",
                    "compile_mode": None,
                    "observations": [],
                }
            ]

            replay = await client.post(url, json=request, headers=headers)
            assert replay.status_code == 202
            assert replay.json()["step_id"] == step_id
            assert replay.json()["execution_status"] == "running"

            conflict = await client.post(
                url,
                json={"instruction": "另一条指令"},
                headers=headers,
            )
            assert conflict.status_code == 409
            assert conflict.json()["detail"]["code"] == "rpa_agent.idempotency_conflict"

            busy = await client.post(
                url,
                json=request,
                headers={"Idempotency-Key": "agent-key-0000002"},
            )
            assert busy.status_code == 409
            assert busy.json()["detail"]["code"] == "rpa_agent.agent_instruction_in_progress"

            release.set()
            for _ in range(100):
                projection = await client.get(
                    f"/api/v1/rpa-agent/sessions/{session_id}/projection"
                )
                if projection.json()["items"][0]["execution_status"] == "succeeded":
                    break
                await asyncio.sleep(0.01)
            assert projection.json()["items"][0]["execution_status"] == "succeeded"
            assert projection.json()["items"][0]["id"] == step_id

    asyncio.run(scenario())


def test_stop_cancels_active_agent_before_freezing_timeline(tmp_path: Path) -> None:
    services, _, _ = _services(tmp_path)
    started = asyncio.Event()

    async def blocking_agent(_session: object, _request: object) -> object:
        started.set()
        await asyncio.Event().wait()

    services.agent_executor = blocking_agent
    app = FastAPI()
    app.include_router(build_router(services), prefix="/api/v1/rpa-agent")
    app.dependency_overrides[require_user] = lambda: User(
        id="user-1", username="tester", role="user"
    )

    async def scenario() -> None:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            created = await client.post("/api/v1/rpa-agent/sessions", json={})
            session_id = created.json()["session_id"]
            admitted = await client.post(
                f"/api/v1/rpa-agent/sessions/{session_id}/agent-instructions",
                headers={"Idempotency-Key": "stop-agent-key-0001"},
                json={"instruction": "打开和 skill 最相关的项目"},
            )
            assert admitted.status_code == 202
            step_id = admitted.json()["step_id"]
            await asyncio.wait_for(started.wait(), timeout=1)

            stopped = await asyncio.wait_for(
                client.post(f"/api/v1/rpa-agent/sessions/{session_id}/stop"),
                timeout=1,
            )
            assert stopped.status_code == 200, stopped.text

            projection = await client.get(
                f"/api/v1/rpa-agent/sessions/{session_id}/projection"
            )
            assert projection.status_code == 200
            assert projection.json()["recording_state"] == "stopped"
            assert projection.json()["items"][0]["id"] == step_id
            assert projection.json()["items"][0]["execution_status"] == "cancelled"

            rejected = await client.post(
                f"/api/v1/rpa-agent/sessions/{session_id}/agent-instructions",
                headers={"Idempotency-Key": "stop-agent-key-0002"},
                json={"instruction": "获取 star 数"},
            )
            assert rejected.status_code == 409

    asyncio.run(scenario())


def test_manual_input_projects_draft_before_browser_action_finishes(tmp_path: Path) -> None:
    services, port, _ = _services(tmp_path)
    started = asyncio.Event()
    release = asyncio.Event()

    async def blocking_click(_target: object) -> None:
        started.set()
        await release.wait()
        port.manual_click_count += 1

    port.click = blocking_click  # type: ignore[method-assign]
    app = FastAPI()
    app.include_router(build_router(services), prefix="/api/v1/rpa-agent")
    app.dependency_overrides[require_user] = lambda: User(
        id="user-1", username="tester", role="user"
    )

    async def scenario() -> None:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            created = await client.post(
                "/api/v1/rpa-agent/sessions",
                json={},
            )
            session_id = created.json()["session_id"]
            url = f"/api/v1/rpa-agent/sessions/{session_id}/manual-inputs"
            payload = {"input_id": "manual-click-0001", "kind": "click", "x": 10, "y": 20}
            pending = asyncio.create_task(client.post(url, json=payload))

            await asyncio.wait_for(started.wait(), timeout=1)
            projection = await asyncio.wait_for(
                client.get(f"/api/v1/rpa-agent/sessions/{session_id}/projection"),
                timeout=1,
            )
            draft = projection.json()["items"][0]
            assert draft["kind"] == "manual"
            assert draft["capture_status"] == "capturing"
            assert draft["execution_status"] == "running"

            replay = await client.post(url, json=payload)
            assert replay.status_code == 200
            assert replay.json()["draft_id"] == draft["id"]
            assert replay.json()["capture_status"] == "capturing"

            release.set()
            completed = await asyncio.wait_for(pending, timeout=1)
            assert completed.status_code == 200, completed.text
            assert completed.json() == {
                "input_id": payload["input_id"],
                "draft_id": draft["id"],
                "capture_status": "captured",
            }
            projection = await client.get(
                f"/api/v1/rpa-agent/sessions/{session_id}/projection"
            )
            item = projection.json()["items"][0]
            assert item["id"].startswith("trace_")
            assert item["kind"] == "manual"
            assert item["capture_status"] == "captured"
            assert item["execution_status"] == "succeeded"

    asyncio.run(scenario())


def test_manual_navigation_is_an_immediate_top_level_core_trace(tmp_path: Path) -> None:
    services, port, _ = _services(tmp_path)
    visited: list[str] = []

    class Page:
        async def goto(self, url: str) -> None:
            visited.append(url)

    port.main_page = Page()
    with _client(services) as client:
        session_id = _start(client)
        response = client.post(
            f"/api/v1/rpa-agent/sessions/{session_id}/manual-inputs",
            json={
                "input_id": "manual-navigation-0001",
                "kind": "navigate",
                "text": "https://github.com/trending",
            },
        )
        assert response.status_code == 200, response.text
        assert response.json()["capture_status"] == "captured"
        assert visited == ["https://github.com/trending"]

        projection = client.get(
            f"/api/v1/rpa-agent/sessions/{session_id}/projection"
        ).json()
        assert len(projection["items"]) == 1
        assert projection["items"][0]["kind"] == "manual"
        assert projection["items"][0]["capture_status"] == "captured"
        assert projection["items"][0]["execution_status"] == "succeeded"
        assert projection["items"][0]["title"] == "navigate"


def test_recording_test_and_rerecord_receive_distinct_host_identity_and_page(
    tmp_path: Path,
) -> None:
    class Factory:
        def __init__(self) -> None:
            self.hosts: list[BrowserHostSession] = []

        async def _create(self, kind: str) -> BrowserHostSession:
            port = FakeBrowserPort()
            host = BrowserHostSession(
                browser_session_ref=f"bhs_{kind}_{len(self.hosts) + 1}",
                page_ref=f"page_{kind}_{len(self.hosts) + 1}",
                target_id=f"target_{kind}_{len(self.hosts) + 1}",
                generation=f"gen_{kind}_{len(self.hosts) + 1}",
                port=port,
            )
            self.hosts.append(host)
            return host

        async def create_recording(self, *, owner_id: str) -> BrowserHostSession:
            assert owner_id == "user-1"
            return await self._create("recording")

        async def create_test(self, *, owner_id: str, skill_id: str) -> BrowserHostSession:
            assert owner_id == "user-1" and skill_id.startswith("skill_")
            return await self._create("test")

        async def create_run(self, *, owner_id: str, skill_id: str) -> BrowserHostSession:
            assert owner_id == "user-1" and skill_id
            return await self._create("run")

    factory = Factory()
    runtime_pages: list[object] = []

    async def runtime_runner(session: object, _request: object) -> dict[str, Any]:
        runtime_pages.append(getattr(getattr(session, "browser"), "main_page"))
        return {"status": "succeeded", "outputs": {}}

    services = RpaAgentApiServices(
        artifact_root=tmp_path / "artifacts",
        browser_factory=factory,
        agent_executor=lambda *_args: None,  # type: ignore[arg-type]
        runtime_runner=runtime_runner,
        publisher=FakePublisher(),
    )
    with _client(services) as client:
        session_id = _start(client)
        _compile_minimal_skill(client, session_id)
        tested = client.post(
            f"/api/v1/rpa-agent/sessions/{session_id}/test-run",
            json={"inputs": {}, "secrets": {}, "data_assets": {}},
        )
        assert tested.status_code == 200, tested.text
        rerecorded = client.post(
            f"/api/v1/rpa-agent/sessions/{session_id}/rerecord", json={}
        )
        assert rerecorded.status_code == 201, rerecorded.text

    assert [host.browser_session_ref for host in factory.hosts] == [
        "bhs_recording_1",
        "bhs_test_2",
        "bhs_recording_3",
    ]
    assert len({id(host.port.main_page) for host in factory.hosts}) == 3
    assert runtime_pages == [factory.hosts[1].port.main_page]
    assert rerecorded.json()["session_id"] != session_id
    assert rerecorded.json()["generation"] == "gen_recording_3"
